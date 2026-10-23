# Runs the daily job (collect, reply check, email digest) for the "jobscout daily" scheduled task.
# All output goes to data\output\daily.log in UTF-8, and the script exits with Python's exit code
# so a failure shows up in the task's LastTaskResult.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$outDir = Join-Path $root "data\output"
$log = Join-Path $outDir "daily.log"
$utf8 = New-Object System.Text.UTF8Encoding $false
New-Item -ItemType Directory -Force $outDir | Out-Null

function Write-Log([string]$text) { [IO.File]::AppendAllText($log, $text + "`r`n", $utf8) }

# Earlier runs wrote UTF-16. Keep that file aside instead of mixing encodings in one log.
if (Test-Path $log) {
    $fs = [IO.File]::OpenRead($log)
    $bom = New-Object byte[] 2
    $n = $fs.Read($bom, 0, 2)
    $fs.Close()
    if ($n -eq 2 -and (($bom[0] -eq 0xFF -and $bom[1] -eq 0xFE) -or ($bom[0] -eq 0xFE -and $bom[1] -eq 0xFF))) {
        $old = Join-Path $outDir "daily.old.log"
        if (Test-Path $old) { $old = Join-Path $outDir ("daily.old.{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss")) }
        Move-Item $log $old
    }
}

Write-Log ""
Write-Log ("--- {0} starting jobscout daily" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Log "Python not found at $python"
    exit 9009
}
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
# cmd appends Python's bytes unchanged, so the log stays UTF-8 and stderr lines are not wrapped as PowerShell errors.
cmd /c ".venv\Scripts\python.exe -m jobscout.daily >> data\output\daily.log 2>&1"
$code = $LASTEXITCODE
Write-Log ("--- {0} finished, exit code {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $code)
exit $code
