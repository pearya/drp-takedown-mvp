$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv\\Scripts\\python.exe")) {
  python -m venv .venv
}

& ".venv\\Scripts\\python.exe" -m pip install -r requirements.txt
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; .\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload"
