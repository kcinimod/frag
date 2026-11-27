param(
    [Parameter(Mandatory)][ValidateSet('Freeze', 'Live', 'Replay', 'Score')][string]$Mode,
    [Parameter(Mandatory)][string]$Destination,
    [string]$Custody,
    [string]$SavedFreeze,
    [string]$SavedLive,
    [switch]$Continuation,
    [string]$ContinuationRevision = 'HEAD',
    [switch]$FreshContinuation,
    [string]$EvaluationRevision
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $repo '.venv/Scripts/python.exe'
$revision = '208cca1e410a0811cba600ad93753b53b42cc43a'
$evaluation = 'af6f34eb8d10c7535d4a30e4b5bdf624e16becc5'
$phase = 'artifacts/phase06'
$runnerBundle = 'runner/inputs.zip'

function Resolve-Custody([bool]$Fresh) {
    if ($Custody) { return (Resolve-Path -LiteralPath $Custody).Path }
    $number = if ($Fresh) { 54 } else { 43 }
    return (Resolve-Path -LiteralPath "$repo/../FRAG-SEC-Holdout-$number").Path
}

function Invoke-CheckedPython {
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Python command failed ($LASTEXITCODE): $args" }
}

function Confirm-ContinuationFreeze([string]$Runner, [string]$Freeze, [string]$Scoring, [switch]$RequireModel) {
    if (-not (Test-Path -LiteralPath "$Runner/continuation-audit.json" -PathType Leaf)) {
        throw 'The continuation audit is required before releasing runner inputs.'
    }
    $validate = @'
from pathlib import Path
import sys

runner, freeze, scoring = map(Path, sys.argv[1:4])
sys.path.insert(0, str(runner / "artifacts/phase06"))
from fresh_run import SCORING_FILES, configuration, digest, read_json, runtime_hashes

frozen = read_json(freeze)
config = configuration()
scorer_paths = (*SCORING_FILES, "artifacts/phase06/verify_continuation_custody.py")
scoring_files = {name: digest(scoring / name) for name in scorer_paths}
if ("continuation_audit_sha256" not in config
        or any(frozen.get(key) != value for key, value in config.items())
        or scoring_files != frozen.get("scoring_files")):
    raise SystemExit("The freeze differs from the verified continuation snapshot.")
if "--require-model" in sys.argv and (
    digest(runner / "model/model.gguf") != frozen["weights_sha256"]
    or runtime_hashes(runner / "model") != frozen["runtime_files"]
):
    raise SystemExit("The model or runtime differs from the continuation freeze.")
'@
    $arguments = @('-', $Runner, $Freeze, $Scoring)
    if ($RequireModel) { $arguments += '--require-model' }
    $validate | & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Continuation freeze validation failed.' }
}

function Export-Snapshot($Commit, $Archive, $Directory, $Paths) {
    git -C $repo -c core.autocrlf=false archive --format=zip --output=$Archive $Commit -- @Paths
    if ($LASTEXITCODE -ne 0) { throw "Could not export the Phase 6 snapshot at $Commit." }
    Expand-Archive -LiteralPath $Archive -DestinationPath $Directory
}

if ($Mode -eq 'Freeze') {
    if ($FreshContinuation) {
        if ($Continuation -or $ContinuationRevision -notmatch '^[0-9a-f]{40}$') {
            throw 'Specify the committed production revision as a full SHA with -ContinuationRevision.'
        }
        if ($EvaluationRevision -notmatch '^[0-9a-f]{40}$') {
            throw 'Specify the committed evaluation revision as a full SHA with -EvaluationRevision.'
        }
    }
    $session = (New-Item -ItemType Directory -Path $Destination).FullName
    $paths = @('src', 'scripts', 'pyproject.toml', 'uv.lock',
        'artifacts/phase04/SEC_ACCEPTANCE_PROTOCOL.md', 'artifacts/phase04/sec-holdout-receipt.json',
        'artifacts/phase04/sec_holdout_runner.py', 'artifacts/phase04/sec_holdout_score.py',
        'artifacts/phase05/baseline.py', 'artifacts/phase05/holdout.py', 'artifacts/phase05/score.py',
        'artifacts/phase05/custody.json', 'artifacts/phase05/holdout-freeze.json',
        'artifacts/phase05/acceptance_score.py', 'artifacts/phase05/holdout_score.py', 'artifacts/phase05/holdout-score.json',
        "$phase/sec-holdout-receipt.json", "$phase/DEVELOPMENT_LAYOUTS.md", "$phase/gate-score.json",
        "$phase/development_score.py", "$phase/revenue_score.py", "$phase/observations.py")
    if ($Continuation) {
        $revision = git -C $repo rev-parse --verify "$ContinuationRevision^{commit}"
        if ($LASTEXITCODE -ne 0) { throw 'Could not identify the committed continuation revision.' }
        $evaluation = $revision
    }
    if ($FreshContinuation) {
        $revision = $ContinuationRevision
        $evaluation = $EvaluationRevision
        $paths += @("$phase/continuation-holdout-receipt.json", "$phase/continuation-opened-score.json")
    }
    foreach ($role in @('runner', 'scoring')) {
        Export-Snapshot $revision "$session/$role-production.zip" "$session/$role" $paths
        $files = @(if ($role -eq 'runner') { 'fresh_run.py', 'FRESH_PROTOCOL.md', 'acceptance.ps1' } else { 'fresh_score.py' })
        if ($Continuation -or $FreshContinuation) {
            $files += 'exact_replay.py'
            $files += if ($role -eq 'runner') { 'EXACT_REPLAY.md' } else { 'fresh_score_v2.py' }
        }
        if ($FreshContinuation) {
            $files += if ($role -eq 'runner') { 'CONTINUATION_PROTOCOL.md' } else { 'verify_continuation_custody.py' }
        }
        $evaluationPaths = @($files | ForEach-Object { "$phase/$_" })
        Export-Snapshot $evaluation "$session/$role-evaluation.zip" "$session/$role" $evaluationPaths
    }
    $runner = "$session/runner"
    if ($FreshContinuation) {
        $custodyRoot = Resolve-Custody $true
        Invoke-CheckedPython "$session/scoring/$phase/verify_continuation_custody.py" $repo $revision $evaluation $custodyRoot $runner
    }
    if ($SavedFreeze) {
        if ($FreshContinuation) {
            Confirm-ContinuationFreeze $runner $SavedFreeze "$session/scoring"
        }
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
if (-not (Test-Path -LiteralPath $freeze -PathType Leaf)) { throw 'Freeze the workspace before releasing inputs.' }
$frozen = Get-Content -Raw -LiteralPath $freeze | ConvertFrom-Json
$fresh = $frozen.PSObject.Properties.Name -contains 'continuation_audit_sha256' -or
    (Test-Path -LiteralPath "$runner/$phase/CONTINUATION_PROTOCOL.md" -PathType Leaf)
if ($Mode -eq 'Live' -or $Mode -eq 'Replay') {
    if ($fresh) {
        Confirm-ContinuationFreeze $runner $freeze "$session/scoring" -RequireModel:($Mode -eq 'Live')
    }
    if (-not (Test-Path -LiteralPath $inputs -PathType Leaf)) {
        $custodyRoot = Resolve-Custody $fresh
        if ($fresh) {
            $runnerBundle = $frozen.receipt.runner_bundle.path
            if ((Get-FileHash -LiteralPath (Join-Path $custodyRoot $runnerBundle)).Hash -ne $frozen.receipt.runner_bundle.sha256) {
                throw 'The runner archive differs from the frozen seal.'
            }
        }
        Copy-Item -LiteralPath (Join-Path $custodyRoot $runnerBundle) -Destination $inputs
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
        & $python $program replay $freeze --inputs $inputs --work "$runner/replay" --saved-run $live
        if ($fresh -and $LASTEXITCODE -eq 2 -and (Test-Path -LiteralPath "$runner/replay/report.json")) { exit 2 }
        if ($LASTEXITCODE -ne 0) { throw "Replay failed ($LASTEXITCODE)." }
    }
    return
}

$expected = (Resolve-Path -LiteralPath (Join-Path (Resolve-Custody $fresh) 'scorer/expected.zip')).Path
if ($expected.StartsWith("$runner\", [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The scorer archive must remain outside the runner workspace.'
}
$live = "$runner/live/report.json"
if (Test-Path -LiteralPath "$runner/retained-live.json") { $live = "$runner/retained-live.json" }
$scoreProgram = "$session/scoring/$phase/fresh_score_v2.py"
$exactScore = Test-Path -LiteralPath $scoreProgram -PathType Leaf
if (-not $exactScore) { $scoreProgram = "$session/scoring/$phase/fresh_score.py" }
& $python $scoreProgram $freeze $inputs $expected $live "$runner/replay/report.json" "$session/scoring/score.json"
if ($LASTEXITCODE -eq 2 -and (Test-Path -LiteralPath "$session/scoring/score.json")) {
    Write-Output 'The recorded acceptance decision is a failure.'
    if ($exactScore) { exit 2 }
} elseif ($LASTEXITCODE -ne 0) {
    throw "Scorer failed ($LASTEXITCODE)."
}
