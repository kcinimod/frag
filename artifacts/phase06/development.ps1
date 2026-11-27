param(
    [Parameter(Mandatory)][string]$Destination,
    [string]$Custody = (Join-Path $PSScriptRoot '../../../FRAG-SEC-Holdout-32'),
    [switch]$ReplayRetained,
    [string]$Revision
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$custody = (Resolve-Path -LiteralPath $Custody).Path
$python = Join-Path $repo '.venv/Scripts/python.exe'
$historicalRevision = 'd5ea2c36af63bb64b30721ceb94cb26236dc4b0a'
if (-not $Revision) { $Revision = $historicalRevision }
if ($ReplayRetained -and $Revision -ne $historicalRevision) {
    throw 'The retained #42 run requires its original production revision.'
}
$snapshot = (New-Item -ItemType Directory -Path $Destination).FullName
$paths = @('src', 'scripts', 'pyproject.toml', 'uv.lock', 'artifacts/phase01', 'artifacts/phase02',
    'artifacts/phase03', 'artifacts/phase04', 'artifacts/phase05', 'artifacts/phase06', 'tests', 'web')
git -C $repo -c core.autocrlf=false archive --format=zip --output="$snapshot/snapshot.zip" $revision -- @paths
if ($LASTEXITCODE -ne 0) { throw 'Could not export the Phase 6 production revision.' }
Expand-Archive -LiteralPath "$snapshot/snapshot.zip" -DestinationPath $snapshot
foreach ($script in @('development_run.py', 'development_score.py')) {
    # Match the retained script hashes when Git checks out Windows line endings.
    $source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot $script)).Replace("`r`n", "`n")
    [IO.File]::WriteAllText("$snapshot/artifacts/phase06/$script", $source, [Text.UTF8Encoding]::new($false))
}
Copy-Item -LiteralPath "$custody/runner/inputs.zip" -Destination "$snapshot/opened-inputs.zip"

function Invoke-CheckedPython {
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Python command failed ($LASTEXITCODE): $args" }
}

if (-not $ReplayRetained) {
    $model = (New-Item -ItemType Directory -Path "$snapshot/model").FullName
    Copy-Item -LiteralPath @("$repo/.frag-model/model.gguf", "$repo/.frag-model/runtime") -Destination $model -Recurse
}
$runner = "$snapshot/artifacts/phase06/development_run.py"
foreach ($cohort in @('opened', 'earlier')) {
    $live = "$snapshot/$cohort-live.json"
    if ($ReplayRetained) {
        $unpack = 'import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))'
        Invoke-CheckedPython -c $unpack (Join-Path $PSScriptRoot "gate-$cohort-live.json.gz") $live
    } else {
        Invoke-CheckedPython $runner $cohort "$snapshot/$cohort-live" --model $model
        Move-Item -LiteralPath "$snapshot/$cohort-live/report.json" -Destination $live
    }
    Invoke-CheckedPython $runner $cohort "$snapshot/$cohort-replay" --live $live
}
Invoke-CheckedPython "$snapshot/artifacts/phase06/development_score.py" $snapshot "$custody/scorer/expected.zip"
Write-Output "Development gate runs in $snapshot"
