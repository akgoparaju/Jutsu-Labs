#!/bin/bash
# Jutsu Dashboard Shutdown Script
# Stops both API backend and React frontend

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=========================================="
echo "  Jutsu Trading Dashboard - Stopping..."
echo "=========================================="

# Stop API server (uvicorn on port 8000)
echo "[1/2] Stopping API Backend..."
API_PIDS=$(lsof -t -i :8000 2>/dev/null || true)
if [ -n "$API_PIDS" ]; then
    echo "$API_PIDS" | xargs kill -9 2>/dev/null || true
    echo "      API server stopped (PIDs: $API_PIDS)"
else
    echo "      API server was not running"
fi

# Stop React dashboard (vite on port 3000 or alternative ports)
echo "[2/2] Stopping React Dashboard..."
STOPPED=false

# Check common Vite ports (3000, 3001, 3002, 5173)
for PORT in 3000 3001 3002 5173; do
    DASHBOARD_PIDS=$(lsof -t -i :$PORT 2>/dev/null || true)
    if [ -n "$DASHBOARD_PIDS" ]; then
        echo "$DASHBOARD_PIDS" | xargs kill -9 2>/dev/null || true
        echo "      Dashboard stopped on port $PORT (PIDs: $DASHBOARD_PIDS)"
        STOPPED=true
    fi
done

if [ "$STOPPED" = false ]; then
    echo "      Dashboard was not running"
fi

# Also kill any orphaned vite/node processes from npm run dev
VITE_PIDS=$(pgrep -f "vite" 2>/dev/null || true)
if [ -n "$VITE_PIDS" ]; then
    echo "$VITE_PIDS" | xargs kill -9 2>/dev/null || true
    echo "      Cleaned up orphaned vite processes"
fi

echo ""
echo "=========================================="
echo "  Dashboard Stopped"
echo "=========================================="
echo ""
echo "  To restart: ./scripts/start_dashboard.sh"
echo "=========================================="
