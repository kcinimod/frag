$ErrorActionPreference = 'Stop'
$repo = Resolve-Path (Join-Path $PSScriptRoot '../..')
Push-Location $repo
try {
    $run = New-Item -ItemType Directory -Path ".frag-model/lookup-$([guid]::NewGuid())"
    $store = Join-Path $run.FullName 'store'
    $filing = Join-Path $run.FullName 'filing.htm'
    .venv/Scripts/python.exe -c "import gzip,pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(gzip.decompress(pathlib.Path('artifacts/phase01/originals/msft-20230630.htm.gz').read_bytes()))" $filing
    if ($LASTEXITCODE -ne 0) { throw 'Could not decompress the retained filing.' }
    $source = .venv/Scripts/frag.exe ingest $filing --store $store --provenance local_original | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not ingest the retained filing.' }

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
        $server = .\scripts\start-local-model.ps1 -Background
        do {
            if ($server.HasExited -or $clock.Elapsed.TotalSeconds -gt 20) { throw 'Planner failed to start.' }
            curl.exe --noproxy '*' --max-time 1 -fs http://127.0.0.1:8087/health | Out-Null
            if ($LASTEXITCODE -eq 0) { break }
            Start-Sleep -Milliseconds 50
        } while ($true)
        $startup = $clock.Elapsed.TotalMilliseconds

        $measurements = foreach ($case in @(
            @{ Name = 'cold'; Year = 2023; Amount = '211915000000' },
            @{ Name = 'warm'; Year = 2023; Amount = '211915000000' },
            @{ Name = 'prior'; Year = 2022; Amount = '198270000000' }
        )) {
            $record = Join-Path $run.FullName "$($case.Name).json"
            $requestClock = [Diagnostics.Stopwatch]::StartNew()
            $answer = .venv/Scripts/frag.exe ask $source.source_id (
                'What was reported consolidated revenue in FY{0}?' -f $case.Year
            ) --store $store --record $record
            $requestMs = $requestClock.Elapsed.TotalMilliseconds
            if ($LASTEXITCODE -ne 0) { throw "Lookup command failed ($($case.Name))." }
            $result = $answer | ConvertFrom-Json
            if ($result.status -ne 'answered' -or $result.fact.normalized_amount -ne $case.Amount -or
                $result.fact.currency -ne 'USD' -or $result.fiscal_year -ne $case.Year) {
                throw "Unexpected lookup outcome ($($case.Name)). Inspect $record."
            }
            $saved = Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
            $server.Refresh()
            [ordered]@{
                case = $case.Name
                fiscal_year = $case.Year
                currency = $result.fact.currency
                amount = $result.fact.normalized_amount
                cli_request_ms = [Math]::Round($requestMs, 3)
                planner_ms = $saved.timings_ms.model
                runtime_peak_working_set_bytes = $server.PeakWorkingSet64
            }
        }
        $samples += @(Receive-Job $gpu)
        $vram = foreach ($sample in $samples) {
            $dedicated = $sample.Usage | Where-Object InstanceName -Like "pid_$($server.Id)_*" |
                Measure-Object CookedValue -Sum
            [long]$dedicated.Sum
        }
    } finally {
        if ($server -and !$server.HasExited) { Stop-Process -Id $server.Id }
        Stop-Job $gpu
        Remove-Job $gpu
    }
    $coldRecord = Join-Path $run.FullName 'cold.json'
    $replay = .venv/Scripts/frag.exe replay-lookup $coldRecord --store $store | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $replay.status -ne 'answered' -or $replay.fact.normalized_amount -ne '211915000000') {
        throw 'Saved-plan replay failed with the model unloaded.'
    }
    [ordered]@{
        run = $run.Name
        model_startup_ms = [Math]::Round($startup, 3)
        cold_start_through_cli_ms = [Math]::Round($startup + $measurements[0].cli_request_ms, 3)
        gpu_samples = $samples.Count
        sampled_runtime_peak_dedicated_vram_bytes = ($vram | Measure-Object -Maximum).Maximum
        requests = $measurements
        unloaded_replay_status = $replay.status
    } | ConvertTo-Json -Depth 4
} finally {
    Pop-Location
}
