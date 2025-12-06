# Unraid Deployment Guide for Jutsu Trading Dashboard

## Overview

This guide provides instructions for deploying the Jutsu Trading Dashboard on an Unraid server using Docker.

## Prerequisites

- Unraid 6.9+ with Docker enabled
- Minimum 2GB RAM allocated to the container
- Minimum 2GB free disk space on appdata share

## Docker Hub Image

**Repository**: `ankugo/jutsu-labs`

```bash
# Pull the latest image
docker pull ankugo/jutsu-labs:latest
```

**Available Tags**:
- `latest` - Latest stable release from main branch
- `v1.0.0` - Specific version tags
- `main` - Latest from main branch

## Installation Steps

### 1. Pull the Docker Image (Recommended)

The image is automatically built and published to Docker Hub:

```bash
# Pull the latest image
docker pull ankugo/jutsu-labs:latest
```

**Alternative: Build Locally**

If you prefer to build from source:

```bash
git clone https://github.com/akgoparaju/Jutsu-Labs.git
cd Jutsu-Labs
docker build -t ankugo/jutsu-labs:latest .
```

### 2. Create Unraid Application Directory

On your Unraid server, create the appdata directory:

```bash
mkdir -p /mnt/user/appdata/jutsu/{data,config,state,logs}
chmod -R 755 /mnt/user/appdata/jutsu
```

### 3. Copy Configuration Files

Copy your configuration files to Unraid:

```bash
# Copy config.yaml
cp config/live_trading_config.yaml /mnt/user/appdata/jutsu/config/

# Copy token.json (if you have Schwab OAuth token)
cp token.json /mnt/user/appdata/jutsu/
```

### 4. Add Docker Container in Unraid

#### Option A: Using Unraid WebUI

1. Go to Docker tab
2. Click "Add Container"
3. Fill in the following fields:

**Basic Settings:**
- **Name:** `jutsu-trading-dashboard`
- **Repository:** `ankugo/jutsu-labs:latest`
- **Network Type:** `Bridge`
- **Console shell command:** `bash`

**Port Mappings:**
- Container Port: `8080` → Host Port: `8080` (or your preferred host port)
  - Note: Container uses port 8080 internally (non-root user cannot bind to port 80)

**Path Mappings:**
- Container Path: `/app/data` → Host Path: `/mnt/user/appdata/jutsu/data`
- Container Path: `/app/config` → Host Path: `/mnt/user/appdata/jutsu/config` (Read-only)
- Container Path: `/app/state` → Host Path: `/mnt/user/appdata/jutsu/state`
- Container Path: `/app/logs` → Host Path: `/mnt/user/appdata/jutsu/logs`
- Container Path: `/app/token.json` → Host Path: `/mnt/user/appdata/jutsu/token.json` (Read-only, if exists)

**Environment Variables:**
- `SCHWAB_APP_KEY` = `your_app_key_here`
- `SCHWAB_APP_SECRET` = `your_app_secret_here`
- `SCHWAB_CALLBACK_URL` = `https://127.0.0.1`
- `DATABASE_URL` = `sqlite:////app/data/market_data.db`
- `LOG_LEVEL` = `INFO`
- `TZ` = `America/New_York`
- `TRADING_MODE` = `offline_mock` (or `online_live` for real trading)

**Advanced Settings:**
- CPU Limit: `2.0` (2 cores)
- Memory Limit: `2G`

5. Click "Apply" to create the container

#### Option B: Using Docker Compose (Advanced)

1. Install "Compose Manager" plugin from Community Applications
2. Create a new compose stack with the provided `docker-compose.yml`
3. Adjust volume paths to use `/mnt/user/appdata/jutsu/`
4. Deploy the stack

### 5. Verify Deployment

1. Check container logs in Unraid Docker tab
2. Access the dashboard: `http://YOUR_UNRAID_IP:8080`
3. Check API docs: `http://YOUR_UNRAID_IP:8080/docs`

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SCHWAB_APP_KEY` | Yes (for live trading) | - | Schwab API application key |
| `SCHWAB_APP_SECRET` | Yes (for live trading) | - | Schwab API application secret |
| `SCHWAB_CALLBACK_URL` | Yes (for live trading) | `https://127.0.0.1` | OAuth callback URL |
| `DATABASE_URL` | No | `sqlite:////app/data/market_data.db` | Database connection string |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `TZ` | No | `America/New_York` | Container timezone |
| `TRADING_MODE` | No | `offline_mock` | Trading mode (offline_mock, online_live) |
| `JUTSU_API_USERNAME` | No | - | Optional API authentication username |
| `JUTSU_API_PASSWORD` | No | - | Optional API authentication password |

## Volume Paths Reference

| Container Path | Host Path | Purpose | Read-Only |
|----------------|-----------|---------|-----------|
| `/app/data` | `/mnt/user/appdata/jutsu/data` | SQLite database and market data | No |
| `/app/config` | `/mnt/user/appdata/jutsu/config` | Configuration files | Yes |
| `/app/state` | `/mnt/user/appdata/jutsu/state` | Runtime state files | No |
| `/app/logs` | `/mnt/user/appdata/jutsu/logs` | Application logs | No |
| `/app/token.json` | `/mnt/user/appdata/jutsu/token.json` | Schwab OAuth token (if exists) | Yes |

## Schwab OAuth Token Setup

If you don't have a `token.json` file yet:

1. Start the container with `TRADING_MODE=offline_mock`
2. Access the container console: `docker exec -it jutsu-trading-dashboard bash`
3. Run the authentication helper:
   ```bash
   python3 -c "from jutsu_engine.live.schwab_executor import authenticate; authenticate()"
   ```
4. Follow the OAuth flow in your browser
5. The `token.json` will be created automatically
6. Copy it to `/mnt/user/appdata/jutsu/` on the host
7. Restart the container

## Troubleshooting

### Container Won't Start

1. Check logs: `docker logs jutsu-trading-dashboard`
2. Verify volume permissions:
   ```bash
   ls -la /mnt/user/appdata/jutsu/
   chmod -R 755 /mnt/user/appdata/jutsu/
   ```

### Database Errors

1. Check database file exists and is writable:
   ```bash
   ls -la /mnt/user/appdata/jutsu/data/market_data.db
   ```
2. Reset database (WARNING: deletes all data):
   ```bash
   rm /mnt/user/appdata/jutsu/data/market_data.db
   docker restart jutsu-trading-dashboard
   ```

### API Connection Issues

1. Verify Schwab credentials are set correctly
2. Check `token.json` exists and is valid
3. Review container logs for authentication errors

### Dashboard Not Loading

1. **⚠️ VERIFY PORT MAPPING (Most Common Issue)**:
   - Container Port MUST be `8080` (not `80`)
   - The container runs as non-root user and cannot bind to port 80
   - In Unraid Docker settings, ensure:
     - Container Port: `8080`
     - Host Port: Your choice (e.g., `8787`, `8080`)
   - **Wrong**: `Container Port: 80` → **Will NOT work**
   - **Correct**: `Container Port: 8080` → Works

2. Check nginx is running:
   ```bash
   docker exec jutsu-trading-dashboard ps aux | grep nginx
   ```

3. Verify services are listening on correct ports:
   ```bash
   docker exec jutsu-trading-dashboard netstat -tlnp
   # Should show nginx on port 8080
   ```

4. Check browser console for errors

## Upgrading

1. Stop the container
2. Pull the new image: `docker pull your-registry/jutsu-trading-dashboard:latest`
3. Restart the container
4. Verify logs and functionality

## Backup Strategy

### What to Backup

- `/mnt/user/appdata/jutsu/data/` - Database with historical data
- `/mnt/user/appdata/jutsu/state/` - Trading state
- `/mnt/user/appdata/jutsu/config/` - Configuration files
- `/mnt/user/appdata/jutsu/token.json` - OAuth credentials

### Backup Script Example

```bash
#!/bin/bash
BACKUP_DIR="/mnt/user/backups/jutsu"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/jutsu_backup_$DATE.tar.gz" \
    /mnt/user/appdata/jutsu/data \
    /mnt/user/appdata/jutsu/state \
    /mnt/user/appdata/jutsu/config \
    /mnt/user/appdata/jutsu/token.json

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/jutsu_backup_*.tar.gz | tail -n +8 | xargs -r rm
```

## Performance Tuning

### Resource Allocation

- **Light usage** (1-2 symbols, intraday): 0.5 CPU, 512MB RAM
- **Moderate usage** (5-10 symbols, hourly): 1 CPU, 1GB RAM
- **Heavy usage** (20+ symbols, minute bars): 2 CPU, 2GB RAM

### Database Optimization

For better performance with large datasets:

1. Switch to PostgreSQL:
   ```bash
   # Install PostgreSQL container in Unraid
   # Update DATABASE_URL environment variable
   DATABASE_URL=postgresql://user:pass@postgres:5432/jutsu
   ```

2. Enable WAL mode for SQLite:
   ```bash
   docker exec jutsu-trading-dashboard sqlite3 /app/data/market_data.db "PRAGMA journal_mode=WAL;"
   ```

## Security Recommendations

1. **Enable API authentication:**
   - Set `JUTSU_API_USERNAME` and `JUTSU_API_PASSWORD`

2. **Use reverse proxy:**
   - Set up nginx proxy manager or swag
   - Enable HTTPS with Let's Encrypt

3. **Restrict network access:**
   - Use Unraid firewall rules
   - Limit container network to local subnet only

4. **Protect sensitive files:**
   - Ensure `token.json` has restricted permissions
   - Use Unraid's encrypted user shares if needed

## Support

For issues, feature requests, or questions:
- GitHub: [Jutsu-Labs Repository]
- Documentation: `/docs` directory in project
- Logs: Check container logs and `/mnt/user/appdata/jutsu/logs/`
