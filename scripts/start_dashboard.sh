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

# Check if already running
if lsof -i :8000 > /dev/null 2>&1; then
    echo "[WARNING] API server already running on port 8000"
else
    echo "[1/2] Starting API Backend (port 8000)..."
    source venv/bin/activate
    nohup uvicorn jutsu_engine.api.main:app --host 127.0.0.1 --port 8000 --log-level info > logs/api_server.log 2>&1 &
    API_PID=$!
    echo "      API PID: $API_PID"
    sleep 2

    # Verify API started
    if curl -s http://127.0.0.1:8000/api/status/health > /dev/null 2>&1; then
        echo "      API server started successfully"
    else
        echo "      [ERROR] API server failed to start. Check logs/api_server.log"
        exit 1
    fi
fi

# Dashboard uses port 3000 (configured in vite.config.ts)
if lsof -i :3000 > /dev/null 2>&1; then
    echo "[WARNING] Dashboard already running on port 3000"
else
    echo "[2/2] Starting React Dashboard (port 3000)..."
    cd dashboard
    nohup npm run dev > ../logs/dashboard.log 2>&1 &
    DASHBOARD_PID=$!
    echo "      Dashboard PID: $DASHBOARD_PID"
    cd ..

    # Wait for Vite to start (check log for "ready" message)
    echo "      Waiting for Vite to initialize..."
    for i in {1..10}; do
        if grep -q "ready" logs/dashboard.log 2>/dev/null; then
            break
        fi
        sleep 1
    done

    # Get actual port from log (Vite may use alternative if 3000 busy)
    DASHBOARD_PORT=$(grep -oE "localhost:[0-9]+" logs/dashboard.log 2>/dev/null | head -1 | cut -d: -f2 || echo "3000")

    if grep -q "ready" logs/dashboard.log 2>/dev/null; then
        echo "      Dashboard started successfully on port $DASHBOARD_PORT"
    else
        echo "      [WARNING] Dashboard may still be starting. Check logs/dashboard.log"
    fi
fi

# Get actual dashboard port
DASHBOARD_PORT=$(grep -oE "localhost:[0-9]+" logs/dashboard.log 2>/dev/null | head -1 | cut -d: -f2 || echo "3000")

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
