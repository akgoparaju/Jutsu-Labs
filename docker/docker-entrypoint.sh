#!/bin/bash
set -e

echo "=================================================="
echo "Jutsu Trading Dashboard - Docker Entrypoint"
echo "=================================================="

# Create required directories if they don't exist
echo "Creating required directories..."
mkdir -p /app/data /app/state /app/logs /app/token_cache

# Set timezone (graceful handling - TZ env var is sufficient for most apps)
if [ -n "$TZ" ]; then
    echo "Timezone set via TZ environment variable: $TZ"
    # Note: System timezone files (/etc/localtime) require root access
    # The TZ environment variable is sufficient for Python datetime operations
fi

# Display configuration
echo ""
echo "Configuration:"
echo "  - Database: ${DATABASE_URL:-sqlite:///app/data/market_data.db}"
echo "  - Log Level: ${LOG_LEVEL:-INFO}"
echo "  - Timezone: ${TZ:-America/New_York}"
echo "  - Mode: ${TRADING_MODE:-offline_mock}"
echo ""

# Check for Schwab credentials
if [ -n "$SCHWAB_APP_KEY" ] && [ -n "$SCHWAB_APP_SECRET" ]; then
    echo "Schwab API credentials detected"

    # Check for token.json
    if [ -f "/app/token.json" ]; then
        echo "  - OAuth token file found: /app/token.json"
    else
        echo "  - WARNING: No OAuth token file found"
        echo "  - You'll need to authenticate on first run"
    fi
else
    echo "WARNING: Schwab API credentials not set"
    echo "  - Set SCHWAB_APP_KEY and SCHWAB_APP_SECRET environment variables"
    echo "  - Trading will only work in mock mode"
fi

# Verify database directory is writable
if [ ! -w "/app/data" ]; then
    echo "ERROR: /app/data directory is not writable"
    echo "  - Check volume mount permissions"
    exit 1
fi

# Verify state directory is writable
if [ ! -w "/app/state" ]; then
    echo "ERROR: /app/state directory is not writable"
    echo "  - Check volume mount permissions"
    exit 1
fi

# Note: Database initialization happens automatically when API starts
# via SQLAlchemy Base.metadata.create_all() in the API module

# Display startup summary
echo ""
echo "=================================================="
echo "Starting Jutsu Trading Dashboard..."
echo "  - Frontend: http://localhost:80"
echo "  - API Docs: http://localhost:80/docs"
echo "  - WebSocket: ws://localhost:80/ws"
echo "=================================================="
echo ""

# Execute the main command (supervisord or custom command)
exec "$@"
