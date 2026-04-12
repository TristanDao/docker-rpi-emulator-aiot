# Face Attendance System — Start Script
# Usage: .\start.ps1
# Requires camera bridge to be set up: .\setup_camera_autostart.ps1

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "=== Face Attendance System ===" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Docker Desktop check ──
Write-Host "[1/3] Checking Docker Desktop..." -ForegroundColor Yellow
$dockerRunning = $false
try { docker info 2>&1 | Out-Null; $dockerRunning = $LASTEXITCODE -eq 0 } catch {}

if (-not $dockerRunning) {
    Write-Host "      Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Write-Host "      Waiting 30s..."
    Start-Sleep -Seconds 30
}
Write-Host "      Docker is running." -ForegroundColor Green

# ── Step 2: Check camera bridge ──
Write-Host "[2/3] Checking camera bridge..." -ForegroundColor Yellow
$bridgeOk = $false
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8888/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
    $bridgeOk = $resp.StatusCode -eq 200
} catch {}

if (-not $bridgeOk) {
    Write-Host "      Bridge not running. Starting..." -ForegroundColor Yellow
    $CONDA_PYTHON = (conda run -n edge python -c "import sys; print(sys.executable)" 2>$null).Trim()
    if (-not $CONDA_PYTHON) { $CONDA_PYTHON = "$env:USERPROFILE\miniconda3\envs\edge\python.exe" }
    Start-Process $CONDA_PYTHON -ArgumentList "`"$ROOT\camera_bridge.py`" --index -1 --port 8888" -WindowStyle Hidden
    Start-Sleep -Seconds 6
}

try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8888/health" -TimeoutSec 5 -UseBasicParsing
    Write-Host "      Camera bridge OK: http://localhost:8888/stream.mjpg" -ForegroundColor Green
} catch {
    Write-Host "      Camera bridge not responding. Check webcam." -ForegroundColor Red
}

# Auto-update .env with current LAN IP
$LAN_IP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -ne "127.0.0.1" -and $_.PrefixOrigin -ne "WellKnown"
} | Sort-Object InterfaceMetric | Select-Object -First 1).IPAddress

if ($LAN_IP) {
    (Get-Content "$ROOT\.env") -replace 'CAMERA_SOURCE=http://[^:]+:8888', "CAMERA_SOURCE=http://${LAN_IP}:8888" | Set-Content "$ROOT\.env"
    Write-Host "      LAN IP: $LAN_IP" -ForegroundColor DarkGray
}

# ── Step 3: Start Docker services ──
Write-Host "[3/3] Starting Docker services..." -ForegroundColor Yellow
Set-Location $ROOT
docker compose up -d

# Wait for edge to be ready
$deadline = (Get-Date).AddSeconds(90)
do {
    $log = docker compose logs edge --tail 3 2>&1
    if ($log -match "Recognition loop started") { break }
    Start-Sleep -Seconds 3
} until ((Get-Date) -gt $deadline)

Write-Host ""
Write-Host "=== System running ===" -ForegroundColor Cyan
Write-Host "  Live view + Enrollment : http://localhost:8001" -ForegroundColor Green
Write-Host "  API Server             : http://localhost:8000" -ForegroundColor Green
Write-Host "  Swagger UI             : http://localhost:8000/docs" -ForegroundColor Green
Write-Host ""
Write-Host "  To stop: docker compose down" -ForegroundColor DarkGray
Write-Host ""
Start-Process "http://localhost:8001"
