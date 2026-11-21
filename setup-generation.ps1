param(
    [string]$BasePython = 'python',
    [switch]$DownloadModel,
    [switch]$VerifyImage
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:USE_TF = '0'
$env:USE_FLAX = '0'
$env:TEMP = Join-Path $PSScriptRoot '.tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $env:TEMP 'pip-cache'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
if (-not (Test-Path -LiteralPath $BasePython)) {
    $BasePython = (Get-Command $BasePython -ErrorAction Stop).Source
}
$python = Join-Path $PSScriptRoot '.venv-generation\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & $BasePython -m venv --system-site-packages .venv-generation
    if ($LASTEXITCODE -ne 0) { throw '推理环境创建失败。' }
}
& $python -m pip install -r requirements-generation.txt
if ($LASTEXITCODE -ne 0) { throw '推理依赖安装失败。' }
& $python scripts/check_generation_environment.py --output logs/generation-environment.json
if ($LASTEXITCODE -ne 0) { throw 'CUDA 环境检查未通过。' }
if ($DownloadModel) {
    & .venv\Scripts\python.exe scripts/download_sd15.py
    if ($LASTEXITCODE -ne 0) { throw '基础模型下载未完成，断点已保留。' }
}
if ($VerifyImage) {
    & .venv\Scripts\python.exe scripts/probe_generation.py
    if ($LASTEXITCODE -ne 0) { throw '真实单图生成检查未通过。' }
}
