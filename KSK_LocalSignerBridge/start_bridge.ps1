param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18181
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectDir '.venv\Scripts\python.exe'
$sharedVenvPython = Join-Path (Split-Path -Parent $projectDir) 'KSK_API\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Test-Path -LiteralPath $sharedVenvPython) {
        $venvPython = $sharedVenvPython
        Write-Host 'Dung moi truong Python da cai cua KSK_API.' -ForegroundColor Yellow
    }
    else {
        throw 'Chua cai dat Bridge. Hay chay .\install_bridge.ps1 truoc.'
    }
}

Set-Location -LiteralPath $projectDir
& $venvPython -m uvicorn main:app --host 127.0.0.1 --port $Port --no-server-header
