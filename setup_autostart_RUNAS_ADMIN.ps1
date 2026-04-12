# Run this script as Administrator (Right-click -> Run as administrator)
# This is a ONE-TIME setup. After this, camera bridge starts automatically on login.

$TASK_NAME = "FaceAttendance-CameraBridge"
    $PYTHON    = "C:\Users\sudon\miniconda3\envs\edge\python.exe"
$SCRIPT    = "D:\education\AIOT\docker-rpi-emulator-aiot\camera_bridge.py"
$WORKDIR   = "D:\education\AIOT\docker-rpi-emulator-aiot"

$action   = New-ScheduledTaskAction -Execute $PYTHON -Argument "`"$SCRIPT`" --index -1 --port 8888" -WorkingDirectory $WORKDIR
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "sudon" -LogonType Interactive

Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TASK_NAME -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Face Attendance: streams webcam as MJPEG for Docker edge"

Write-Host "Starting bridge now..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName $TASK_NAME
Start-Sleep -Seconds 8

try {
    $r = Invoke-WebRequest -Uri "http://localhost:8888/health" -TimeoutSec 5 -UseBasicParsing
    Write-Host "Camera bridge is running!" -ForegroundColor Green
    Write-Host "Stream: http://localhost:8888/stream.mjpg" -ForegroundColor Green
} catch {
    Write-Host "Starting... open http://localhost:8888/health in a moment." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete. Bridge will auto-start on every login." -ForegroundColor Cyan
Read-Host "Press Enter to close"
