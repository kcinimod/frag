param(
    [Parameter(Mandatory)][ValidateSet('Freeze', 'Live', 'Replay', 'Score')][string]$Mode,
    [Parameter(Mandatory)][string]$Destination,
    [string]$Custody = (Join-Path $PSScriptRoot '../../../FRAG-SEC-Holdout-43'),
    [string]$SavedFreeze,
    [string]$SavedLive
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $repo '.venv/Scripts/python.exe'
$revision = '208cca1e410a0811cba600ad93753b53b42cc43a'
$evaluation = 'af6f34eb8d10c7535d4a30e4b5bdf624e16becc5'
$phase = 'artifacts/phase06'
$runnerBundle = 'runner/inputs.zip'

function Invoke-CheckedPython {
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Python command failed ($LASTEXITCODE): $args" }
}

if ($Mode -eq 'Freeze') {
    $session = (New-Item -ItemType Directory -Path $Destination).FullName
    $paths = @('src', 'scripts', 'pyproject.toml', 'uv.lock',
        'artifacts/phase04/SEC_ACCEPTANCE_PROTOCOL.md', 'artifacts/phase04/sec-holdout-receipt.json',
        'artifacts/phase04/sec_holdout_runner.py', 'artifacts/phase04/sec_holdout_score.py',
        'artifacts/phase05/baseline.py', 'artifacts/phase05/holdout.py', 'artifacts/phase05/score.py',
        'artifacts/phase05/custody.json', 'artifacts/phase05/holdout-freeze.json',
        'artifacts/phase05/acceptance_score.py', 'artifacts/phase05/holdout_score.py', 'artifacts/phase05/holdout-score.json',
        "$phase/sec-holdout-receipt.json", "$phase/DEVELOPMENT_LAYOUTS.md", "$phase/gate-score.json",
        "$phase/development_score.py", "$phase/revenue_score.py", "$phase/observations.py")
    git -C $repo -c core.autocrlf=false archive --format=zip --output="$session/production.zip" $revision -- @paths
    if ($LASTEXITCODE -ne 0) { throw 'Could not export the Phase 6 production revision.' }
    foreach ($role in @('runner', 'scoring')) {
        Expand-Archive -LiteralPath "$session/production.zip" -DestinationPath "$session/$role"
        $files = if ($role -eq 'runner') { @('fresh_run.py', 'FRESH_PROTOCOL.md', 'acceptance.ps1') } else { @('fresh_score.py') }
        $evaluationPaths = @($files | ForEach-Object { "$phase/$_" })
        $historical = "$session/$role-evaluation.zip"
        git -C $repo -c core.autocrlf=false archive --format=zip --output=$historical $evaluation -- @evaluationPaths
        if ($LASTEXITCODE -ne 0) { throw 'Could not export the frozen #44 evaluation revision.' }
        Expand-Archive -LiteralPath $historical -DestinationPath "$session/$role"
    }
    $runner = "$session/runner"
    if ($SavedFreeze) {
        Copy-Item -LiteralPath $SavedFreeze -Destination "$runner/freeze.json"
    } else {
        $model = (New-Item -ItemType Directory -Path "$runner/model").FullName
        Copy-Item -LiteralPath @("$repo/.frag-model/model.gguf", "$repo/.frag-model/runtime") -Destination $model -Recurse
        Invoke-CheckedPython "$runner/$phase/fresh_run.py" freeze "$runner/freeze.json" --model $model --scoring "$session/scoring"
    }
    Write-Output "Frozen workspace $session"
    return
}

$session = (Resolve-Path -LiteralPath $Destination).Path
$runner = "$session/runner"
$freeze = "$runner/freeze.json"
$inputs = "$runner/inputs.zip"
if ($Mode -eq 'Live' -or $Mode -eq 'Replay') {
    if (-not (Test-Path -LiteralPath $freeze -PathType Leaf)) { throw 'Freeze the workspace before releasing inputs.' }
    if (-not (Test-Path -LiteralPath $inputs -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $Custody $runnerBundle) -Destination $inputs
    }
    $program = "$runner/$phase/fresh_run.py"
    if ($Mode -eq 'Live') {
        Invoke-CheckedPython $program live $freeze --model "$runner/model" --inputs $inputs --work "$runner/live"
    } else {
        $live = "$runner/live/report.json"
        if ($SavedLive) {
            $live = "$runner/retained-live.json"
            $unpack = 'import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))'
            Invoke-CheckedPython -c $unpack $SavedLive $live
        }
        Invoke-CheckedPython $program replay $freeze --inputs $inputs --work "$runner/replay" --saved-run $live
    }
    return
}

$expected = (Resolve-Path -LiteralPath (Join-Path $Custody 'scorer/expected.zip')).Path
if ($expected.StartsWith("$runner\", [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The scorer archive must remain outside the runner workspace.'
}
$live = "$runner/live/report.json"
if (Test-Path -LiteralPath "$runner/retained-live.json") { $live = "$runner/retained-live.json" }
& $python "$session/scoring/$phase/fresh_score.py" $freeze $inputs $expected $live "$runner/replay/report.json" "$session/scoring/score.json"
if ($LASTEXITCODE -eq 2 -and (Test-Path -LiteralPath "$session/scoring/score.json")) {
    Write-Output 'The recorded acceptance decision is a failure.'
} elseif ($LASTEXITCODE -ne 0) {
    throw "Scorer failed ($LASTEXITCODE)."
}
