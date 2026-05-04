# Register camera_bridge as a Windows startup task
# Run this ONCE as admin. After that, bridge auto-starts on every login.

param(
    [switch]$Uninstall
)

$TASK_NAME = "FaceAttendance-CameraBridge"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$BRIDGE_SCRIPT = Join-Path $ROOT "camera_bridge.py"

# Detect conda python path
$CONDA_PYTHON = (conda run -n edge python -c "import sys; print(sys.executable)" 2>$null).Trim()
if (-not $CONDA_PYTHON -or -not (Test-Path $CONDA_PYTHON)) {
    # Fallback: search common conda paths
    $CONDA_PYTHON = "$env:USERPROFILE\miniconda3\envs\edge\python.exe"
    if (-not (Test-Path $CONDA_PYTHON)) {
        $CONDA_PYTHON = "$env:USERPROFILE\anaconda3\envs\edge\python.exe"
    }
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Camera bridge startup task removed." -ForegroundColor Yellow
    exit 0
}

if (-not (Test-Path $CONDA_PYTHON)) {
    Write-Host "Cannot find Python in 'edge' conda env. Please check your conda installation." -ForegroundColor Red
    exit 1
}

Write-Host "Python: $CONDA_PYTHON" -ForegroundColor DarkGray
Write-Host "Script: $BRIDGE_SCRIPT" -ForegroundColor DarkGray

$ACTION = New-ScheduledTaskAction `
    -Execute $CONDA_PYTHON `
    -Argument "`"$BRIDGE_SCRIPT`" --index 1 --port 8888" `
    -WorkingDirectory $ROOT

$TRIGGER = New-ScheduledTaskTrigger -AtLogOn

$SETTINGS = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

$PRINCIPAL = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TASK_NAME `
    -Action $ACTION `
    -Trigger $TRIGGER `
    -Settings $SETTINGS `
    -Principal $PRINCIPAL `
    -Description "Face Attendance: streams USB webcam as MJPEG for Docker edge container" | Out-Null

Write-Host ""
Write-Host "Camera bridge registered as startup task." -ForegroundColor Green
Write-Host "It will start automatically on next login." -ForegroundColor Green
Write-Host ""
Write-Host "Start it NOW without rebooting:" -ForegroundColor Yellow
Start-ScheduledTask -TaskName $TASK_NAME
Start-Sleep -Seconds 5

# Verify
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8888/health" -TimeoutSec 5 -UseBasicParsing
    Write-Host "Bridge is running: $($resp.Content)" -ForegroundColor Green
} catch {
    Write-Host "Bridge starting... check http://localhost:8888/health in a few seconds." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "To remove: .\setup_camera_autostart.ps1 -Uninstall" -ForegroundColor DarkGray
