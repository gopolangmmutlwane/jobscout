# Keeps the jobscout triage page running. Used by the "jobscout web" and "jobscout web watchdog" tasks.
#
#   run_web.ps1            start the page in the background unless it is already up, then exit
#   run_web.ps1 -Stop      stop the page (the supervisor loop and the server)
#   run_web.ps1 -Supervise internal: the hidden loop that runs the server and restarts it when it exits
#
# Why a separate hidden supervisor: a scheduled task's console opens as a Windows Terminal tab on
# Windows 11 (-WindowStyle Hidden cannot hide it). Closing that tab, or Ctrl+C in it, killed the server
# (exit 0xC000013A). The supervisor is started with a hidden window of its own, so nothing visible holds it.
param([switch]$Supervise, [switch]$Stop)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $root "data\output\web.log"
$utf8 = New-Object System.Text.UTF8Encoding $false
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

# Same port as the app: WEB_PORT from .env, default 8765 (only that one line is read).
$port = 8765
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern '^\s*WEB_PORT\s*=\s*(\d+)\s*$' | Select-Object -First 1
    if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
}

function Write-Log([string]$text) {
    try { [IO.File]::AppendAllText($log, ("--- {0} {1}`r`n" -f (Get-Date -Format s), $text), $utf8) } catch { }
}
function Test-Listening { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }
function Get-Supervisors {
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like '*run_web.ps1*-Supervise*' -and $_.ProcessId -ne $PID }
}

if ($Stop) {
    Get-Supervisors | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Write-Log "stopped with run_web.ps1 -Stop"
    exit 0
}

if ($Supervise) {
    $mutex = New-Object System.Threading.Mutex($false, "Local\jobscout-web-supervisor")
    if (-not $mutex.WaitOne(0)) { exit 0 }  # another supervisor is already running
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $quickExits = 0
    while ($true) {
        if (Test-Listening) { Start-Sleep -Seconds 30; continue }  # something else serves the port
        Write-Log "starting jobscout web on port $port"
        $started = Get-Date
        # cmd appends Python's output unchanged, so web.log stays UTF-8.
        cmd /c ".venv\Scripts\python.exe -m jobscout.web >> data\output\web.log 2>&1"
        $code = $LASTEXITCODE
        Write-Log ("jobscout web exited with code {0} (0x{0:X8}); restarting" -f $code)
        if (((Get-Date) - $started).TotalSeconds -lt 60) { $quickExits++ } else { $quickExits = 0 }
        # 5 s after a normal exit; back off up to 5 min if it keeps failing straight away.
        Start-Sleep -Seconds ([int][Math]::Min(300, 5 * [Math]::Pow(2, [Math]::Min($quickExits, 6))))
    }
}

# Default: make sure the page is up, then exit so the task never holds a console open.
if (Test-Listening) { exit 0 }
if (-not (Get-Supervisors)) {
    Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -WorkingDirectory $root -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
        "-File", "`"$PSCommandPath`"", "-Supervise")
}
for ($i = 0; $i -lt 45; $i++) {
    if (Test-Listening) { exit 0 }
    Start-Sleep -Seconds 1
}
Write-Log "page not listening on port $port 45 s after start; see the lines above"
exit 1
