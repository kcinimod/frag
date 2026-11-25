param([Parameter(Mandatory)][string]$Destination)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$baseline = 'e0ca1ec304880290b03ebb193cecb88000727c0b'
$snapshot = (New-Item -ItemType Directory -Path $Destination).FullName
git -C $repo -c core.autocrlf=true archive --format=zip --output="$snapshot/production.zip" $baseline src scripts/start-local-model.ps1 scripts/setup-local-model.ps1 pyproject.toml uv.lock artifacts/phase04
if ($LASTEXITCODE -ne 0) { throw 'Could not export the pre-change production commit.' }
Expand-Archive -LiteralPath "$snapshot/production.zip" -DestinationPath $snapshot
$phase = New-Item -ItemType Directory -Path "$snapshot/artifacts/phase05"
git -C $repo archive --format=zip --output="$snapshot/harness.zip" f62d21a -- artifacts/phase05/baseline.py
if ($LASTEXITCODE -ne 0) { throw 'Could not export the pre-change development harness.' }
Expand-Archive -LiteralPath "$snapshot/harness.zip" -DestinationPath $snapshot -Force
foreach ($name in @('score.py', 'inputs.json')) {
    Copy-Item -LiteralPath "$repo/artifacts/phase05/$name" -Destination $phase.FullName
}
$manifest = Get-Content -LiteralPath "$phase/inputs.json" -Raw | ConvertFrom-Json
foreach ($filing in $manifest.sources) {
    $target = Join-Path $snapshot $filing.archive
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo $filing.archive) -Destination $target
}
Write-Output $snapshot
