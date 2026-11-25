param(
    [Parameter(Mandatory)][string]$Destination,
    [string]$LiveReport = (Join-Path $PSScriptRoot 'evidence-gap-live.json.gz')
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $repo '.venv/Scripts/python.exe'
$live = (Resolve-Path -LiteralPath $LiveReport).Path
$revision = '7c558e27ae0ff9a3ca0fc32af68d6e80a55b3390'
$snapshot = & (Join-Path $PSScriptRoot 'snapshot.ps1') -Destination $Destination
foreach ($name in @('expected.json', 'acceptance-text.json')) {
    if (Test-Path -LiteralPath "$snapshot/artifacts/phase05/$name") {
        throw "The scorer reference $name is present in the replay snapshot."
    }
}
$files = @(git -C $repo diff --name-only f62d21a $revision -- src/frag)
if ($LASTEXITCODE -ne 0) { throw 'Could not list the frozen production changes.' }
git -C $repo -c core.autocrlf=false archive --format=zip --output="$snapshot/candidate.zip" $revision -- @files
if ($LASTEXITCODE -ne 0) { throw 'Candidate export failed.' }
Expand-Archive -LiteralPath "$snapshot/candidate.zip" -DestinationPath $snapshot -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'evidence-gap-freeze.json') -Destination "$snapshot/freeze.json"
& $python -c "import gzip, pathlib, sys; raw = pathlib.Path(sys.argv[1]).read_bytes(); pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(raw) if raw.startswith(bytes((31, 139))) else raw)" $live "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Could not copy the saved live run.' }
& $python "$snapshot/artifacts/phase05/baseline.py" replay --data $snapshot --freeze "$snapshot/freeze.json" --work "$snapshot/replay" --live "$snapshot/live.json"
$replayExit = $LASTEXITCODE
if (Test-Path -LiteralPath "$snapshot/replay/report.json") {
    & $python -c "import hashlib, json, pathlib, sys; path = pathlib.Path(sys.argv[2]); report = json.loads(path.read_bytes()); report['live_sha256'] = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest(); path.write_text(json.dumps(report, indent=2) + chr(10), encoding='utf-8')" "$snapshot/live.json" "$snapshot/replay/report.json"
    if ($LASTEXITCODE -ne 0) { throw 'Could not bind the replay report to the saved live run.' }
}
exit $replayExit
