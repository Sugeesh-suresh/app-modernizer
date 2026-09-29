# Windows (PowerShell) equivalent of start.sh.
# If script execution is blocked, run once:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) {
    Write-Error "ERROR: .env file not found. Copy .env.example and add your GEMINI_API_KEY."
}

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..."
    py -3 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

Write-Host "Starting backend on http://localhost:8000"
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
