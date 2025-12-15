#!/bin/bash
# Jutsu Dashboard Startup Script
# Starts both API backend and React frontend

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Ensure logs directory exists
mkdir -p logs

echo "=========================================="
echo "  Jutsu Trading Dashboard - Starting..."
echo "=========================================="

# Check if already running - clean up zombie processes first
if lsof -t -i :8000 > /dev/null 2>&1; then
    echo "[CLEANUP] Stopping existing API server on port 8000..."
    lsof -t -i :8000 | xargs kill -9 2>/dev/null || true
    sleep 2  # Wait for port to be released
fi

echo "[1/2] Starting API Backend (port 8000)..."
source venv/bin/activate
nohup uvicorn jutsu_engine.api.main:app --host 127.0.0.1 --port 8000 --log-level info > logs/api_server.log 2>&1 &
API_PID=$!
echo "      API PID: $API_PID"

# Wait for API to initialize (DB connection takes ~5-10 seconds)
echo "      Waiting for API to initialize..."
sleep 5

# Retry health check up to 15 times (max 20 seconds total wait)
API_READY=false
for i in {1..15}; do
    if curl -s http://127.0.0.1:8000/api/status/health > /dev/null 2>&1; then
        API_READY=true
        echo "      API server started successfully (took ~$((5 + i)) seconds)"
        break
    fi
    echo "      Waiting for API... attempt $i/15"
    sleep 1
done

if [ "$API_READY" = false ]; then
    echo "      [ERROR] API server failed to start after 20 seconds."
    echo "      Check logs/api_server.log for details"
    exit 1
fi

# Dashboard uses port 3000 (configured in vite.config.ts)
# Clean up existing dashboard processes first
if lsof -t -i :3000 > /dev/null 2>&1; then
    echo "[CLEANUP] Stopping existing dashboard on port 3000..."
    lsof -t -i :3000 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

echo "[2/2] Starting React Dashboard (port 3000)..."
cd dashboard
nohup npm run dev > ../logs/dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo "      Dashboard PID: $DASHBOARD_PID"
cd ..

# Wait for Vite to start (check log for "ready" message)
echo "      Waiting for Vite to initialize..."
DASHBOARD_READY=false
for i in {1..15}; do
    if grep -q "ready" logs/dashboard.log 2>/dev/null; then
        DASHBOARD_READY=true
        break
    fi
    sleep 1
done

# Get actual port from log (Vite may use alternative if 3000 busy)
DASHBOARD_PORT=$(grep -oE "localhost:[0-9]+" logs/dashboard.log 2>/dev/null | head -1 | cut -d: -f2 || echo "3000")

if [ "$DASHBOARD_READY" = true ]; then
    echo "      Dashboard started successfully on port $DASHBOARD_PORT"
else
    echo "      [WARNING] Dashboard may still be starting. Check logs/dashboard.log"
fi

echo ""
echo "=========================================="
echo "  Dashboard Ready!"
echo "=========================================="
echo ""
echo "  Dashboard UI:  http://localhost:${DASHBOARD_PORT}"
echo "  API Backend:   http://localhost:8000"
echo "  API Docs:      http://localhost:8000/docs"
echo ""
echo "  To stop: ./scripts/stop_dashboard.sh"
echo "=========================================="
