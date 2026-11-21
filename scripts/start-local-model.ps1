param(
    [switch]$Background,
    [ValidateRange(1, 65535)][int]$Port = 8087
)

$ErrorActionPreference = 'Stop'
$modelDirectory = Join-Path $PSScriptRoot '../.frag-model'
$runtime = Join-Path $modelDirectory 'runtime/llama-server.exe'
$weights = Join-Path $modelDirectory 'model.gguf'
if (!(Test-Path -LiteralPath $runtime -PathType Leaf) -or !(Test-Path -LiteralPath $weights -PathType Leaf)) {
    throw 'Run scripts/setup-local-model.ps1 before starting the local planner.'
}
if ((Get-FileHash -LiteralPath $weights -Algorithm SHA256).Hash -ne
    '74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db') {
    throw 'The local weights failed the pinned SHA-256 check. Run scripts/setup-local-model.ps1 again.'
}

$plannerArguments = @(
    '--offline', '--model', $weights, '--alias', 'frag-qwen25-05b-q4km',
    '--host', '127.0.0.1', '--port', $Port, '--ctx-size', '4096', '--threads', '4',
    '--n-gpu-layers', '0', '--parallel', '1', '--log-disable'
)
if ($Background) {
    $plannerArguments[2] = '"' + $weights + '"'
    Start-Process -FilePath $runtime -ArgumentList $plannerArguments -PassThru -WindowStyle Hidden
} else {
    & $runtime @plannerArguments
}
