$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectDir '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3.10 -m venv (Join-Path $projectDir '.venv')
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $projectDir 'requirements.txt')
Write-Host 'Da cai dat xong. Chay .\start_bridge.ps1 de khoi dong Local Signer Bridge.' -ForegroundColor Green
