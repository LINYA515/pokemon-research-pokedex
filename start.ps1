param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup.ps1 first.' }
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Run npm.cmd run build in frontend first.' }
if (-not (Test-Path -LiteralPath 'data\pokedex.sqlite')) { throw 'Run .venv\Scripts\python.exe scripts\build_data.py first.' }
$env:TEMP = Join-Path $PSScriptRoot '.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
if (Test-Path -LiteralPath 'config.local.json') {
    $config = Get-Content -LiteralPath 'config.local.json' -Raw | ConvertFrom-Json
    foreach ($name in @('POKE_LLM_BASE_URL', 'POKE_LLM_MODEL', 'POKE_LLM_API_KEY', 'POKE_EMBEDDING_MODEL_PATH')) {
        if ($config.PSObject.Properties.Name -contains $name) {
            $value = [string]$config.$name
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                [Environment]::SetEnvironmentVariable($name, $value.Trim(), 'Process')
            }
        }
    }
}
Write-Host "Pokedex: http://127.0.0.1:$Port"
& $python -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
