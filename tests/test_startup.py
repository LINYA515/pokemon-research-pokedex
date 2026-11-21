import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("configured_value,expected", [("", "existing-test-value"), ("   ", "existing-test-value"), ("  replacement-test-value  ", "replacement-test-value")])
def test_startup_skips_blank_configuration_without_reading_local_config(configured_value, expected):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("需要PowerShell验证启动脚本")
    path = str(Path(__file__).resolve().parents[1] / "start.ps1").replace("'", "''")
    value = configured_value.replace("'", "''")
    # 只执行脚本AST中的环境变量循环，以合成数据替代本机配置和密钥。
    script = f"""
    $ErrorActionPreference = 'Stop'
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {{ throw 'PowerShell parse failed' }}
    $loop = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.ForEachStatementAst] }}, $true)
    $env:POKE_LLM_API_KEY = 'existing-test-value'
    $config = [pscustomobject]@{{ POKE_LLM_API_KEY = '{value}' }}
    Invoke-Expression $loop.Extent.Text
    [pscustomobject]@{{ value = $env:POKE_LLM_API_KEY }} | ConvertTo-Json -Compress
    """
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["value"] == expected
