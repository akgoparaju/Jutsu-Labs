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

*Schwab API Configuration:*
- `SCHWAB_APP_KEY` = `your_app_key_here`
- `SCHWAB_APP_SECRET` = `your_app_secret_here`
- `SCHWAB_CALLBACK_URL` = `https://127.0.0.1`

*Database Configuration (choose one):*

Option A - SQLite (default, simpler):
- `DATABASE_TYPE` = `sqlite`

Option B - PostgreSQL (recommended for production):
- `DATABASE_TYPE` = `postgresql`
- `POSTGRES_HOST` = `your_postgres_host` (e.g., `tower.local` or IP)
- `POSTGRES_PORT` = `5432`
- `POSTGRES_USER` = `jutsu`
- `POSTGRES_PASSWORD` = `your_password_here` (special characters like @ are auto-encoded)
- `POSTGRES_DATABASE` = `jutsu_labs`

*Application Settings:*
- `LOG_LEVEL` = `INFO`
- `TZ` = `America/New_York`
- `TRADING_MODE` = `offline_mock` (or `online_live` for real trading)

*Authentication (recommended for remote access):*
- `AUTH_REQUIRED` = `true` (set to `false` to disable login)
- `ADMIN_PASSWORD` = `your_secure_password_here`
- `SECRET_KEY` = `your_random_secret_key_here` (generate with: `openssl rand -hex 32`)

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

### Schwab API Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SCHWAB_APP_KEY` | Yes (for live trading) | - | Schwab API application key |
| `SCHWAB_APP_SECRET` | Yes (for live trading) | - | Schwab API application secret |
| `SCHWAB_CALLBACK_URL` | Yes (for live trading) | `https://127.0.0.1` | OAuth callback URL |

### Database Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_TYPE` | No | `sqlite` | Database type: `sqlite` or `postgresql` |
| `SQLITE_DATABASE` | No | `data/market_data.db` | SQLite database path (when DATABASE_TYPE=sqlite) |
| `POSTGRES_HOST` | Yes (if postgresql) | - | PostgreSQL server hostname or IP |
| `POSTGRES_PORT` | No | `5432` | PostgreSQL server port |
| `POSTGRES_USER` | Yes (if postgresql) | - | PostgreSQL username |
| `POSTGRES_PASSWORD` | Yes (if postgresql) | - | PostgreSQL password (special chars auto-encoded) |
| `POSTGRES_DATABASE` | No | `jutsu_labs` | PostgreSQL database name |

### Authentication Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AUTH_REQUIRED` | No | `false` | Enable JWT authentication (`true`/`false`) |
| `ADMIN_PASSWORD` | Yes (if auth enabled) | `admin` | Admin user password for dashboard login |
| `SECRET_KEY` | Yes (if auth enabled) | - | JWT signing key (generate: `openssl rand -hex 32`) |

### Application Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `TZ` | No | `America/New_York` | Container timezone |
| `TRADING_MODE` | No | `offline_mock` | Trading mode (offline_mock, online_live) |

### Legacy Settings (Deprecated)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | No | - | Legacy database URL (use DATABASE_TYPE instead) |
| `JUTSU_API_USERNAME` | No | - | Legacy HTTP Basic auth (use JWT instead) |
| `JUTSU_API_PASSWORD` | No | - | Legacy HTTP Basic auth (use JWT instead) |

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

1. **Switch to PostgreSQL (recommended):**
   ```bash
   # In Unraid Docker template, set these environment variables:
   DATABASE_TYPE=postgresql
   POSTGRES_HOST=tower.local      # Your PostgreSQL server
   POSTGRES_PORT=5432
   POSTGRES_USER=jutsu
   POSTGRES_PASSWORD=your_password  # Special chars like @ are auto-encoded
   POSTGRES_DATABASE=jutsu_labs
   ```
   
   To set up PostgreSQL on Unraid:
   - Install PostgreSQL from Community Applications
   - Create database: `CREATE DATABASE jutsu_labs;`
   - Create user: `CREATE USER jutsu WITH PASSWORD 'your_password';`
   - Grant permissions: `GRANT ALL PRIVILEGES ON DATABASE jutsu_labs TO jutsu;`

2. **Enable WAL mode for SQLite** (if using SQLite):
   ```bash
   docker exec jutsu-trading-dashboard sqlite3 /app/data/market_data.db "PRAGMA journal_mode=WAL;"
   ```

## Security Recommendations

1. **Enable JWT authentication (recommended):**
   ```bash
   AUTH_REQUIRED=true
   ADMIN_PASSWORD=your_secure_password_here
   SECRET_KEY=$(openssl rand -hex 32)
   ```
   - Login at `http://YOUR_IP:8080/auth/login` with username `admin`
   - Tokens expire after 7 days for enhanced security

2. **Use PostgreSQL for production:**
   ```bash
   DATABASE_TYPE=postgresql
   POSTGRES_HOST=tower.local  # or your database server
   POSTGRES_PORT=5432
   POSTGRES_USER=jutsu
   POSTGRES_PASSWORD=your_db_password
   POSTGRES_DATABASE=jutsu_labs
   ```
   - Better performance and reliability than SQLite
   - Supports concurrent access from multiple services

3. **Use reverse proxy:**
   - Set up nginx proxy manager or swag
   - Enable HTTPS with Let's Encrypt
   - Protect dashboard with SSL/TLS encryption

4. **Restrict network access:**
   - Use Unraid firewall rules
   - Limit container network to local subnet only

5. **Protect sensitive files:**
   - Ensure `token.json` has restricted permissions
   - Use Unraid's encrypted user shares if needed
   - Never commit `.env` files or tokens to git

## Support

For issues, feature requests, or questions:
- GitHub: [Jutsu-Labs Repository]
- Documentation: `/docs` directory in project
- Logs: Check container logs and `/mnt/user/appdata/jutsu/logs/`
