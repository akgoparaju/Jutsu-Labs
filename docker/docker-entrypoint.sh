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

# Set default DATABASE_URL if not provided (use absolute path for Docker)
if [ -z "$DATABASE_URL" ]; then
    export DATABASE_URL="sqlite:////app/data/market_data.db"
else
    # Normalize 3-slash paths to 4-slash for absolute paths in Docker
    # sqlite:///app/... should be sqlite:////app/... (4 slashes = 3 for protocol + 1 for root)
    if echo "$DATABASE_URL" | grep -q "^sqlite:///app/"; then
        # Has only 3 slashes but starts with /app - needs to be absolute path
        export DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|^sqlite:///app/|sqlite:////app/|')
        echo "Normalized DATABASE_URL to absolute path format"
    fi
fi

# Display configuration
echo ""
echo "Configuration:"
echo "  - Database: ${DATABASE_URL}"
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

# Initialize database if it doesn't exist
echo "Initializing database..."
python3 -c "
from pathlib import Path
from sqlalchemy import create_engine
import os
import re

db_url = os.environ.get('DATABASE_URL', 'sqlite:////app/data/market_data.db')

# Normalize 3-slash paths to 4-slash for absolute paths
# sqlite:///app/... should be sqlite:////app/... (4 slashes)
if re.match(r'^sqlite:///app/', db_url):
    db_url = db_url.replace('sqlite:///app/', 'sqlite:////app/', 1)
    print(f'  Normalized to: {db_url}')

print(f'  Database URL: {db_url}')

# Parse path from SQLite URL - handle both 3 and 4 slash formats
if db_url.startswith('sqlite:////'):
    # Absolute path (4 slashes = sqlite:/// + /absolute/path)
    db_path = Path(db_url.replace('sqlite:////', '/'))
elif db_url.startswith('sqlite:///'):
    # Relative path (3 slashes = sqlite:/// + relative/path)
    db_path = Path(db_url.replace('sqlite:///', ''))
else:
    db_path = None

if db_path:
    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        print(f'  Database exists: {db_path}')
    else:
        print(f'  Creating database: {db_path}')
        try:
            from jutsu_engine.data.models import Base
            engine = create_engine(db_url, connect_args={'check_same_thread': False})
            Base.metadata.create_all(engine)
            engine.dispose()
            print('  Database schema created successfully')
        except Exception as e:
            print(f'  WARNING: Could not create database: {e}')
else:
    print('  Non-SQLite database, skipping initialization')
"

# Display startup summary
echo ""
echo "=================================================="
echo "Starting Jutsu Trading Dashboard..."
echo "  - Frontend: http://localhost:8080"
echo "  - API Docs: http://localhost:8080/docs"
echo "  - WebSocket: ws://localhost:8080/ws"
echo "Note: Container uses port 8080 internally (non-root)"
echo "=================================================="
echo ""

# Execute the main command (supervisord or custom command)
exec "$@"
