param(
    [Parameter(Mandatory)][string]$Destination,
    [switch]$WithModel
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$revision = '67dce6d2232045542c91e42b3239bc6a868534d8'
$evaluation = '8f789dfe3953b40ffd71e5190683d3e97b5eb28c'
$snapshot = (New-Item -ItemType Directory -Path $Destination).FullName
git -C $repo -c core.autocrlf=false archive --format=zip --output="$snapshot/production.zip" $revision src scripts/start-local-model.ps1 scripts/setup-local-model.ps1 pyproject.toml uv.lock artifacts/phase04/SEC_ACCEPTANCE_PROTOCOL.md artifacts/phase04/sec-holdout-receipt.json artifacts/phase04/sec_holdout_score.py
if ($LASTEXITCODE -ne 0) { throw 'Could not export the frozen production revision.' }
Expand-Archive -LiteralPath "$snapshot/production.zip" -DestinationPath $snapshot
Copy-Item -LiteralPath "$repo/artifacts/phase04/sec_holdout_runner.py" -Destination "$snapshot/artifacts/phase04"
$phase = (New-Item -ItemType Directory -Path "$snapshot/artifacts/phase05").FullName
git -C $repo -c core.autocrlf=false archive --format=zip --output="$snapshot/evaluation.zip" $evaluation -- artifacts/phase05/baseline.py
if ($LASTEXITCODE -ne 0) { throw 'Could not export the frozen Phase 5 evaluator.' }
Expand-Archive -LiteralPath "$snapshot/evaluation.zip" -DestinationPath $snapshot -Force
foreach ($name in @('score.py', 'holdout.py', 'HOLDOUT_PROTOCOL.md', 'sec-holdout-receipt.json', 'custody.json')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $phase
}
if ($WithModel) {
    $model = (New-Item -ItemType Directory -Path "$snapshot/model").FullName
    Copy-Item -LiteralPath @("$repo/.frag-model/model.gguf", "$repo/.frag-model/runtime") -Destination $model -Recurse
}
Write-Output $snapshot
