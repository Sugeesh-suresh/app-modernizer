# Windows (PowerShell). All the work is in dev.py, which finds the virtual
# environment's interpreter (.venv\Scripts\python.exe) itself.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Get-Command py -ErrorAction SilentlyContinue) { py -3 dev.py run @args } else { python dev.py run @args }
exit $LASTEXITCODE
