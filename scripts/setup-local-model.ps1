$ErrorActionPreference = 'Stop'
$modelDirectory = Join-Path $PSScriptRoot '../.frag-model'
New-Item -ItemType Directory -Path $modelDirectory -Force | Out-Null

function Get-PinnedFile($Url, $Name, $Sha256) {
    $file = Join-Path $modelDirectory $Name
    if (!(Test-Path -LiteralPath $file -PathType Leaf) -or
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $Sha256) {
        $download = "$file.download"
        curl.exe -fLsS --retry 2 $Url -o $download
        if ($LASTEXITCODE -ne 0) { throw "Download failed for $Name." }
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $Sha256) {
            throw "SHA-256 mismatch for $Name."
        }
        Move-Item -LiteralPath $download -Destination $file -Force
    }
}

Get-PinnedFile `
    'https://github.com/ggml-org/llama.cpp/releases/download/b6500/llama-b6500-bin-win-cpu-x64.zip' `
    'runtime.zip' '73e00267e852e666a6fce2c3fb7a2603dd1934a37259f3f45c2c1b6983fa605a'
Get-PinnedFile `
    'https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf' `
    'model.gguf' '74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db'

Expand-Archive -LiteralPath (Join-Path $modelDirectory 'runtime.zip') `
    -DestinationPath (Join-Path $modelDirectory 'runtime') -Force
