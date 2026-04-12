#!/usr/bin/env bash
# Face Attendance System — Start Script (macOS / Linux)
# Usage: ./start.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_PORT=8888

# Color helpers
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; GRAY='\033[0;37m'; NC='\033[0m'

echo ""
echo -e "${CYAN}=== Face Attendance System ===${NC}"
echo ""

# ── Step 1: Docker check ──────────────────────────────────────────────────────
echo -e "${YELLOW}[1/3] Checking Docker...${NC}"
if ! docker info &>/dev/null; then
    echo -e "      Docker not running. Attempting to start Docker Desktop..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open -a Docker
    else
        echo -e "${RED}      Please start Docker manually and re-run this script.${NC}"
        exit 1
    fi
    echo "      Waiting up to 60s for Docker to start..."
    for i in $(seq 1 20); do
        sleep 3
        docker info &>/dev/null && break
        if [[ $i -eq 20 ]]; then
            echo -e "${RED}      Docker did not start in time. Aborting.${NC}"
            exit 1
        fi
    done
fi
echo -e "      ${GREEN}Docker is running.${NC}"

# ── Step 2: Camera bridge ─────────────────────────────────────────────────────
echo -e "${YELLOW}[2/3] Checking camera bridge...${NC}"

bridge_ok=false
if curl -sf "http://localhost:${BRIDGE_PORT}/health" &>/dev/null; then
    bridge_ok=true
fi

if [[ "$bridge_ok" == "false" ]]; then
    echo "      Bridge not running. Starting..."

    # Find python from conda env 'edge', then system python3
    PYTHON=""
    if command -v conda &>/dev/null; then
        CONDA_BASE="$(conda info --base 2>/dev/null || true)"
        for candidate in \
            "${CONDA_BASE}/envs/edge/bin/python" \
            "${HOME}/miniconda3/envs/edge/bin/python" \
            "${HOME}/opt/miniconda3/envs/edge/bin/python" \
            "${HOME}/anaconda3/envs/edge/bin/python"; do
            if [[ -x "$candidate" ]]; then
                PYTHON="$candidate"
                break
            fi
        done
    fi
    if [[ -z "$PYTHON" ]]; then
        PYTHON="$(command -v python3 || command -v python)"
    fi

    if [[ -z "$PYTHON" ]]; then
        echo -e "${RED}      Python not found. Install Python or create conda env 'edge'.${NC}"
        exit 1
    fi

    nohup "$PYTHON" "$ROOT/camera_bridge.py" --index -1 --port "$BRIDGE_PORT" \
        >"$ROOT/camera_bridge.log" 2>&1 &
    echo $! >"$ROOT/.camera_bridge.pid"
    echo "      Started (PID $!), waiting 6s..."
    sleep 6
fi

if curl -sf "http://localhost:${BRIDGE_PORT}/health" &>/dev/null; then
    echo -e "      ${GREEN}Camera bridge OK: http://localhost:${BRIDGE_PORT}/stream.mjpg${NC}"
else
    echo -e "${RED}      Camera bridge not responding. Check webcam connection.${NC}"
    echo -e "${GRAY}      Log: $ROOT/camera_bridge.log${NC}"
fi

# Auto-update .env with host.docker.internal (works natively on Mac/Linux Docker Desktop)
# On Linux, replace with actual host LAN IP
if [[ "$OSTYPE" == "darwin"* ]]; then
    HOST_ADDR="host.docker.internal"
else
    # Linux: get primary LAN IP
    HOST_ADDR=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $7; exit}' || hostname -I | awk '{print $1}')
fi

if [[ -n "$HOST_ADDR" ]]; then
    # Update CAMERA_SOURCE in .env (keep stream path, replace host only)
    sed -i.bak "s|CAMERA_SOURCE=http://[^:]*:${BRIDGE_PORT}|CAMERA_SOURCE=http://${HOST_ADDR}:${BRIDGE_PORT}|g" \
        "$ROOT/.env" && rm -f "$ROOT/.env.bak"
    echo -e "      ${GRAY}CAMERA_SOURCE → http://${HOST_ADDR}:${BRIDGE_PORT}/stream.mjpg${NC}"
fi

# ── Step 3: Docker Compose ────────────────────────────────────────────────────
echo -e "${YELLOW}[3/3] Starting Docker services...${NC}"
cd "$ROOT"
docker compose up -d

# Wait for edge recognition loop
echo "      Waiting for edge to be ready (up to 90s)..."
deadline=$((SECONDS + 90))
while [[ $SECONDS -lt $deadline ]]; do
    if docker compose logs edge --tail 5 2>/dev/null | grep -q "Recognition loop started"; then
        break
    fi
    sleep 3
done

echo ""
echo -e "${CYAN}=== System running ===${NC}"
echo -e "  ${GREEN}Live view + Enrollment : http://localhost:8001${NC}"
echo -e "  ${GREEN}API Server             : http://localhost:8000${NC}"
echo -e "  ${GREEN}Swagger UI             : http://localhost:8000/docs${NC}"
echo ""
echo -e "  ${GRAY}To stop: docker compose down${NC}"
echo -e "  ${GRAY}Camera bridge log: $ROOT/camera_bridge.log${NC}"
echo ""

# Open browser
if [[ "$OSTYPE" == "darwin"* ]]; then
    open "http://localhost:8001"
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:8001"
fi
