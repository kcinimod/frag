param(
    [switch]$Growth,
    [ValidateRange(1, 65535)][int]$Port = 8087
)

$ErrorActionPreference = 'Stop'
$repo = Resolve-Path (Join-Path $PSScriptRoot '../..')
Push-Location $repo
try {
    $kind = if ($Growth) { 'growth' } else { 'lookup' }
    $run = New-Item -ItemType Directory -Path ".frag-model/$kind-$([guid]::NewGuid())"
    $store = Join-Path $run.FullName 'store'
    $filing = Join-Path $run.FullName 'filing.htm'
    .venv/Scripts/python.exe -c "import gzip,pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(gzip.decompress(pathlib.Path('artifacts/phase01/originals/msft-20230630.htm.gz').read_bytes()))" $filing
    if ($LASTEXITCODE -ne 0) { throw 'Could not decompress the retained filing.' }
    $source = .venv/Scripts/frag.exe ingest $filing --store $store --provenance local_original | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not ingest the retained filing.' }

    $cases = if ($Growth) {
        $question = 'How did reported consolidated revenue change from FY2022 to FY2023?'
        @{ Name = 'cold'; Question = $question; Expected = '6.88' }
        @{ Name = 'warm'; Question = $question; Expected = '6.88' }
    } else {
        @{ Name = 'cold'; Question = 'What was reported consolidated revenue in FY2023?'; Expected = '211915000000'; Year = 2023 }
        @{ Name = 'warm'; Question = 'What was reported consolidated revenue in FY2023?'; Expected = '211915000000'; Year = 2023 }
        @{ Name = 'prior'; Question = 'What was reported consolidated revenue in FY2022?'; Expected = '198270000000'; Year = 2022 }
    }
    $healthUrl = "http://127.0.0.1:$Port/health"
    curl.exe --noproxy '*' --max-time 1 -s $healthUrl | Out-Null
    if ($LASTEXITCODE -eq 0) { throw "Port $Port already serves HTTP. Choose an unused planner port." }

    # Record GPU samples before the runtime starts so cold loading is included.
    $gpu = Start-Job -ScriptBlock {
        Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -Continuous -ErrorAction Stop |
            ForEach-Object {
                [pscustomobject]@{ Usage = $_.CounterSamples | Select-Object InstanceName,CookedValue }
            }
    }
    $samples = @()
    $server = $null
    try {
        for ($i = 0; $i -lt 50 -and $samples.Count -eq 0; $i++) {
            Start-Sleep -Milliseconds 100
            $samples += @(Receive-Job $gpu)
        }
        if ($samples.Count -eq 0) { throw 'Windows GPU process counters did not start.' }

        $clock = [Diagnostics.Stopwatch]::StartNew()
        $server = .\scripts\start-local-model.ps1 -Background -Port $Port
        do {
            if ($server.HasExited -or $clock.Elapsed.TotalSeconds -gt 20) { throw 'Planner failed to start.' }
            curl.exe --noproxy '*' --max-time 1 -fs $healthUrl | Out-Null
            if ($LASTEXITCODE -eq 0) { break }
            Start-Sleep -Milliseconds 50
        } while ($true)
        $startup = $clock.Elapsed.TotalMilliseconds

        $measurements = foreach ($case in $cases) {
            $record = Join-Path $run.FullName "$($case.Name).json"
            $requestClock = [Diagnostics.Stopwatch]::StartNew()
            $answer = .venv/Scripts/python.exe -c (
                'import sys; from frag import cli, local_model; local_model.PORT = int(sys.argv.pop(1)); raise SystemExit(cli.main())'
            ) $Port ask $source.source_id $case.Question --store $store --record $record
            $requestMs = $requestClock.Elapsed.TotalMilliseconds
            if ($LASTEXITCODE -ne 0) { throw "Ask command failed ($($case.Name))." }
            if ($case.Name -eq 'cold') { $coldAnswer = $answer }
            $result = $answer | ConvertFrom-Json
            if ($Growth) {
                if ($result.status -ne 'calculated' -or $result.percent.value -ne $case.Expected -or
                    $result.trace.Count -ne 3 -or $result.citations.Count -ne 9) {
                    throw "Unexpected growth outcome ($($case.Name)). Inspect $record."
                }
            } elseif ($result.status -ne 'answered' -or $result.fact.normalized_amount -ne $case.Expected -or
                $result.fact.currency -ne 'USD' -or $result.fiscal_year -ne $case.Year) {
                throw "Unexpected lookup outcome ($($case.Name)). Inspect $record."
            }
            $saved = Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
            $server.Refresh()
            $measurement = [ordered]@{
                case = $case.Name
                cli_request_ms = [Math]::Round($requestMs, 3)
                planner_ms = $saved.timings_ms.model
                runtime_peak_working_set_bytes = $server.PeakWorkingSet64
            }
            if ($Growth) {
                $measurement.percent = $result.percent.value
            } else {
                $measurement.fiscal_year = $case.Year
                $measurement.currency = $result.fact.currency
                $measurement.amount = $result.fact.normalized_amount
            }
            $measurement
        }
        $samples += @(Receive-Job $gpu)
        $vram = foreach ($sample in $samples) {
            $usage = @($sample.Usage | Where-Object InstanceName -Like "pid_$($server.Id)_*")
            if ($usage.Count) {
                [long]($usage | Measure-Object CookedValue -Sum).Sum
            }
        }
    } finally {
        if ($server -and !$server.HasExited) {
            Stop-Process -Id $server.Id
            $server.WaitForExit()
        }
        Stop-Job $gpu
        Remove-Job $gpu
    }
    $coldRecord = Join-Path $run.FullName 'cold.json'
    $replayAnswer = .venv/Scripts/frag.exe replay-ask $coldRecord --store $store
    if ($LASTEXITCODE -ne 0 -or $replayAnswer -cne $coldAnswer) {
        throw 'Saved-plan replay failed with the model unloaded.'
    }
    $replay = $replayAnswer | ConvertFrom-Json
    [ordered]@{
        run = $run.Name
        model_startup_ms = [Math]::Round($startup, 3)
        cold_start_through_cli_ms = [Math]::Round($startup + $measurements[0].cli_request_ms, 3)
        gpu_samples = $samples.Count
        runtime_gpu_samples = @($vram).Count
        sampled_runtime_peak_dedicated_vram_bytes = if ($vram) { ($vram | Measure-Object -Maximum).Maximum } else { 0 }
        requests = $measurements
        unloaded_replay_status = $replay.status
    } | ConvertTo-Json -Depth 4
} finally {
    Pop-Location
}
