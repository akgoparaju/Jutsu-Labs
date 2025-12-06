# Docker Deployment for Jutsu Trading Dashboard

## Quick Start

### Local Development with Docker Compose

```bash
# 1. Clone the repository
git clone <repository-url>
cd Jutsu-Labs

# 2. Create .env file with your credentials
cat > .env << EOF
SCHWAB_APP_KEY=your_app_key_here
SCHWAB_APP_SECRET=your_app_secret_here
SCHWAB_CALLBACK_URL=https://127.0.0.1
LOG_LEVEL=INFO
TZ=America/New_York
TRADING_MODE=offline_mock
EOF

# 3. Build and run with docker-compose
docker-compose up -d

# 4. Check logs
docker-compose logs -f

# 5. Access the dashboard
open http://localhost:8080
```

### Production Build

```bash
# Build the image
docker build -t jutsu-trading-dashboard:latest .

# Run the container
docker run -d \
  --name jutsu-dashboard \
  -p 8080:80 \
  -e SCHWAB_APP_KEY=your_key \
  -e SCHWAB_APP_SECRET=your_secret \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config:/app/config:ro \
  -v $(pwd)/state:/app/state \
  -v $(pwd)/logs:/app/logs \
  jutsu-trading-dashboard:latest
```

## Architecture

### Multi-Stage Build

The Dockerfile uses a multi-stage build for optimal image size:

1. **Stage 1 (frontend-builder)**: Builds React frontend with Node 20
   - Installs npm dependencies
   - Runs Vite build (TypeScript compilation + bundling)
   - Outputs to `dashboard/dist/`

2. **Stage 2 (production)**: Python 3.11 backend + Nginx
   - Installs Python dependencies
   - Copies frontend build from Stage 1
   - Installs nginx + supervisor
   - Sets up non-root user for security

### Container Services

The container runs two services managed by supervisord:

1. **Nginx (port 80)**:
   - Serves static frontend files from `/app/dashboard/dist`
   - Proxies `/api/*` requests to FastAPI backend
   - Proxies `/ws` WebSocket connections
   - Implements caching, compression, and security headers

2. **FastAPI (port 8000, internal)**:
   - Runs via Uvicorn ASGI server
   - Handles REST API endpoints
   - Manages WebSocket connections
   - Interacts with SQLite database

```
┌─────────────────────────────────────────┐
│         Container (Port 80)             │
│  ┌───────────────────────────────────┐  │
│  │          Nginx                    │  │
│  │  - Serves React app (/)           │  │
│  │  - Proxies /api → FastAPI         │  │
│  │  - Proxies /ws → FastAPI          │  │
│  └────────────┬──────────────────────┘  │
│               │                          │
│  ┌────────────▼──────────────────────┐  │
│  │      FastAPI (port 8000)          │  │
│  │  - REST API endpoints             │  │
│  │  - WebSocket handler              │  │
│  │  - Database operations            │  │
│  └───────────────────────────────────┘  │
│                                          │
│  Volumes:                                │
│  - /app/data (database)                  │
│  - /app/state (runtime state)            │
│  - /app/logs (application logs)          │
└─────────────────────────────────────────┘
```

## File Structure

```
docker/
├── nginx.conf              # Nginx configuration
├── supervisord.conf        # Supervisor process manager config
├── docker-entrypoint.sh    # Container initialization script
├── README.md               # This file
└── UNRAID_SETUP.md        # Unraid deployment guide

Dockerfile                  # Multi-stage build definition
docker-compose.yml          # Local development orchestration
.dockerignore              # Build context exclusions
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SCHWAB_APP_KEY` | Yes* | - | Schwab API application key |
| `SCHWAB_APP_SECRET` | Yes* | - | Schwab API application secret |
| `SCHWAB_CALLBACK_URL` | Yes* | `https://127.0.0.1` | OAuth callback URL |
| `DATABASE_URL` | No | `sqlite:////app/data/market_data.db` | Database connection string |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `TZ` | No | `America/New_York` | Container timezone |
| `TRADING_MODE` | No | `offline_mock` | Trading mode |

\* Required for live trading; optional for mock mode

### Volume Mounts

| Container Path | Purpose | Writable |
|----------------|---------|----------|
| `/app/data` | SQLite database and market data | Yes |
| `/app/config` | Configuration files | No (read-only recommended) |
| `/app/state` | Runtime state (state.json, scheduler_state.json) | Yes |
| `/app/logs` | Application logs | Yes |
| `/app/token.json` | Schwab OAuth token (optional) | No |

### Ports

- **80**: HTTP (serves both frontend and API)
  - Frontend: `http://localhost:80/`
  - API: `http://localhost:80/api/*`
  - WebSocket: `ws://localhost:80/ws`
  - Docs: `http://localhost:80/docs`

## Security Features

### Non-Root User

The container runs as user `jutsu` (UID 1000) for security:
- Reduces attack surface
- Prevents privilege escalation
- Follows Docker best practices

### Security Headers

Nginx adds security headers:
- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: no-referrer-when-downgrade`

### Process Isolation

Supervisor manages processes with:
- Auto-restart on failure
- Graceful shutdown handling
- Process monitoring and health checks

## Health Checks

The container includes a health check that:
- Runs every 30 seconds
- Checks `/api/status` endpoint
- Allows 40 seconds for startup
- Retries 3 times before marking unhealthy

```bash
# Check container health
docker inspect jutsu-dashboard | grep -A 5 Health

# Manual health check
curl http://localhost:8080/api/status
```

## Logging

### Log Locations

- **Container logs**: `docker logs jutsu-dashboard`
- **Nginx access**: `/var/log/nginx/access.log`
- **Nginx error**: `/var/log/nginx/error.log`
- **Supervisor**: `/var/log/supervisor/supervisord.log`
- **Application**: `/app/logs/*.log` (mounted volume)

### Log Rotation

Docker Compose includes log rotation:
- Max size: 10MB per file
- Keep 3 files per container
- JSON format for structured logging

## Troubleshooting

### Container Won't Start

```bash
# Check container logs
docker logs jutsu-dashboard

# Check supervisor status
docker exec jutsu-dashboard supervisorctl status

# Verify entrypoint execution
docker exec jutsu-dashboard cat /var/log/supervisor/supervisord.log
```

### Frontend Not Loading

```bash
# Verify nginx is running
docker exec jutsu-dashboard ps aux | grep nginx

# Check nginx configuration
docker exec jutsu-dashboard nginx -t

# View nginx logs
docker exec jutsu-dashboard tail -f /var/log/nginx/error.log
```

### API Errors

```bash
# Check FastAPI process
docker exec jutsu-dashboard supervisorctl status fastapi

# View FastAPI logs
docker logs jutsu-dashboard | grep fastapi

# Test API directly
curl http://localhost:8080/api/status
```

### Database Issues

```bash
# Check database file exists
docker exec jutsu-dashboard ls -la /app/data/

# Verify database permissions
docker exec jutsu-dashboard sqlite3 /app/data/market_data.db ".tables"

# Check disk space
docker exec jutsu-dashboard df -h /app/data
```

### WebSocket Connection Issues

```bash
# Test WebSocket connection
websocat ws://localhost:8080/ws

# Check nginx WebSocket proxy
docker exec jutsu-dashboard grep -A 10 "location /ws" /etc/nginx/nginx.conf

# Monitor WebSocket traffic
docker logs jutsu-dashboard | grep -i websocket
```

## Performance Optimization

### Build Optimization

```bash
# Multi-stage build reduces image size
# Frontend build: ~200MB
# Final image: ~600MB (vs ~1.2GB without multi-stage)

# Use BuildKit for faster builds
DOCKER_BUILDKIT=1 docker build -t jutsu-dashboard .

# Leverage build cache
docker build --cache-from jutsu-dashboard:latest -t jutsu-dashboard .
```

### Runtime Optimization

```bash
# Increase worker processes (if needed)
docker run -e UVICORN_WORKERS=2 ...

# Adjust resource limits
docker update --cpus 2 --memory 2g jutsu-dashboard

# Enable nginx caching for static assets
# Already configured in nginx.conf with 1-year cache
```

### Database Optimization

```bash
# Enable WAL mode for better concurrency
docker exec jutsu-dashboard sqlite3 /app/data/market_data.db \
  "PRAGMA journal_mode=WAL;"

# Optimize database file
docker exec jutsu-dashboard sqlite3 /app/data/market_data.db "VACUUM;"
```

## Maintenance

### Updating the Container

```bash
# Pull latest code
git pull

# Rebuild image
docker-compose build

# Restart with new image
docker-compose down
docker-compose up -d

# Verify health
docker-compose logs -f
```

### Backup and Restore

```bash
# Backup data volumes
docker run --rm -v jutsu-labs_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/jutsu-backup-$(date +%Y%m%d).tar.gz /data

# Restore from backup
docker run --rm -v jutsu-labs_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/jutsu-backup-20240101.tar.gz -C /
```

### Cleanup

```bash
# Stop and remove container
docker-compose down

# Remove volumes (WARNING: deletes all data)
docker-compose down -v

# Remove images
docker rmi jutsu-trading-dashboard:latest
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Build and Push Docker Image

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build image
        run: docker build -t myregistry/jutsu-dashboard:${{ github.sha }} .

      - name: Push image
        run: docker push myregistry/jutsu-dashboard:${{ github.sha }}
```

## Additional Resources

- **Unraid Setup**: See `UNRAID_SETUP.md` for Unraid server deployment
- **API Documentation**: Access `/docs` after container is running
- **Project Documentation**: See `../docs/` directory
- **Configuration Guide**: See `../config/README.md`

## Support

For issues or questions:
1. Check container logs: `docker logs jutsu-dashboard`
2. Review troubleshooting section above
3. Check GitHub issues
4. Consult project documentation
