param(
    [Parameter(Mandatory)][string]$Destination,
    [string]$Custody = (Join-Path $PSScriptRoot '../../../FRAG-SEC-Holdout-32'),
    [switch]$ReplayRetained
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$custody = (Resolve-Path -LiteralPath $Custody).Path
$python = Join-Path $repo '.venv/Scripts/python.exe'
$revision = '96fa9501f9f383d9586c165cfcda78e3323b4401'
$phase = 'artifacts/phase05'
$snapshot = (New-Item -ItemType Directory -Path $Destination).FullName
$paths = @(
    'src', 'pyproject.toml', 'uv.lock', 'scripts/start-local-model.ps1', 'scripts/setup-local-model.ps1',
    'artifacts/phase04/sec_holdout_runner.py', 'artifacts/phase04/sec_holdout_score.py',
    'artifacts/phase04/sec-holdout-receipt.json', 'artifacts/phase04/SEC_ACCEPTANCE_PROTOCOL.md',
    "$phase/baseline.py", "$phase/holdout.py", "$phase/score.py", "$phase/HOLDOUT_PROTOCOL.md",
    "$phase/sec-holdout-receipt.json", "$phase/custody.json", "$phase/holdout-freeze.json", "$phase/inputs.json"
)
git -C $repo -c core.autocrlf=false archive --format=zip --output="$snapshot/snapshot.zip" $revision -- @paths
if ($LASTEXITCODE -ne 0) { throw 'Could not export the pre-change revision.' }
Expand-Archive -LiteralPath "$snapshot/snapshot.zip" -DestinationPath $snapshot

function Invoke-CheckedPython {
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Python command failed ($LASTEXITCODE): $args" }
}

$manifest = Get-Content -LiteralPath "$snapshot/$phase/inputs.json" -Raw | ConvertFrom-Json
foreach ($filing in $manifest.sources) {
    $target = Join-Path $snapshot $filing.archive
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo $filing.archive) -Destination $target
}
$openedFreeze = "$snapshot/$phase/holdout-freeze.json"
$earlierFreeze = "$snapshot/earlier-freeze.json"
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'earlier-freeze.json') -Destination $earlierFreeze
Copy-Item -LiteralPath "$custody/runner/inputs.zip" -Destination "$snapshot/opened-inputs.zip"
$openedRunner = "$snapshot/$phase/holdout.py"
$earlierRunner = "$snapshot/$phase/baseline.py"
$openedLive = "$snapshot/opened-live/report.json"
$earlierLive = "$snapshot/earlier-live/report.json"
if ($ReplayRetained) {
    $openedLive = "$snapshot/opened-live.json"
    $earlierLive = "$snapshot/earlier-live.json"
    $unpack = 'import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))'
    Invoke-CheckedPython -c $unpack (Join-Path $PSScriptRoot 'opened-live.json.gz') $openedLive
    Invoke-CheckedPython -c $unpack (Join-Path $PSScriptRoot 'earlier-live.json.gz') $earlierLive
} else {
    $model = (New-Item -ItemType Directory -Path "$snapshot/model").FullName
    Copy-Item -LiteralPath @("$repo/.frag-model/model.gguf", "$repo/.frag-model/runtime") -Destination $model -Recurse
    Invoke-CheckedPython $openedRunner live $openedFreeze --model $model --inputs "$snapshot/opened-inputs.zip" --work "$snapshot/opened-live"
    Invoke-CheckedPython $earlierRunner live --data $snapshot --freeze $earlierFreeze --model $model --work "$snapshot/earlier-live"
}
Invoke-CheckedPython $openedRunner replay $openedFreeze --inputs "$snapshot/opened-inputs.zip" --work "$snapshot/opened-replay" --saved-run $openedLive
$earlierReplay = "$snapshot/earlier-replay/report.json"
Invoke-CheckedPython $earlierRunner replay --data $snapshot --freeze $earlierFreeze --work "$snapshot/earlier-replay" --live $earlierLive
$bind = "import hashlib, json, pathlib, sys; path = pathlib.Path(sys.argv[2]); report = json.loads(path.read_bytes()); report['live_sha256'] = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest(); path.write_bytes((json.dumps(report, indent=2, sort_keys=True) + chr(10)).encode())"
Invoke-CheckedPython -c $bind $earlierLive $earlierReplay

# Export reviewed references and the historical scorers after replay.
$scoring = (New-Item -ItemType Directory -Path "$snapshot/scoring").FullName
$scoringPaths = @(
    'artifacts/phase04/sec_holdout_score.py',
    "$phase/acceptance_score.py", "$phase/holdout_score.py", "$phase/score.py",
    "$phase/sec-holdout-receipt.json", "$phase/inputs.json", "$phase/expected.json", "$phase/acceptance-text.json"
) + @($manifest.sources | ForEach-Object { $_.archive })
git -C $repo -c core.autocrlf=false archive --format=zip --output="$scoring/scoring.zip" $revision -- @scoringPaths
if ($LASTEXITCODE -ne 0) { throw 'Could not export the frozen scoring inputs.' }
Expand-Archive -LiteralPath "$scoring/scoring.zip" -DestinationPath $scoring
$savedPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$snapshot/src"
    & $python "$scoring/$phase/holdout_score.py" $openedFreeze "$snapshot/opened-inputs.zip" "$custody/scorer/expected.zip" $openedLive "$snapshot/opened-replay/report.json" "$snapshot/opened-score.json"
    if ($LASTEXITCODE -notin @(0, 1) -or -not (Test-Path -LiteralPath "$snapshot/opened-score.json")) {
        throw 'Opened cohort scoring failed.'
    }
    Invoke-CheckedPython "$scoring/$phase/score.py" $scoring $earlierLive $earlierReplay "$snapshot/earlier-stages.json"
    & $python "$scoring/$phase/acceptance_score.py" $scoring $earlierLive $earlierReplay "$snapshot/earlier-score.json"
    if ($LASTEXITCODE -notin @(0, 1) -or -not (Test-Path -LiteralPath "$snapshot/earlier-score.json")) {
        throw 'Earlier development scoring failed.'
    }
    Invoke-CheckedPython (Join-Path $PSScriptRoot 'observations.py') $snapshot $earlierLive $openedLive "$custody/scorer/expected.zip"
} finally {
    $env:PYTHONPATH = $savedPythonPath
}
Write-Output "Baseline reports in $snapshot"
