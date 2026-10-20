# Starts the jobscout triage page and appends its output to data\output\web.log.
# Used by the "jobscout web" scheduled task (see README).
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& (Join-Path $root ".venv\Scripts\Activate.ps1")
New-Item -ItemType Directory -Force (Join-Path $root "data\output") | Out-Null
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
Add-Content -Encoding utf8 -Path "data\output\web.log" -Value "--- $(Get-Date -Format s) starting jobscout web"
# cmd handles the redirection so the log stays plain UTF-8 and stderr lines are not wrapped as PowerShell errors.
cmd /c "python -m jobscout.web >> data\output\web.log 2>&1"
exit $LASTEXITCODE
