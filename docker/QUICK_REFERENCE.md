# Docker Setup - Quick Reference Card

## Files Created

```
Jutsu-Labs/
├── Dockerfile                      # Multi-stage build (Node + Python)
├── docker-compose.yml              # Local development orchestration
├── .dockerignore                   # Build context exclusions
├── .env.docker.example             # Environment template
└── docker/
    ├── nginx.conf                  # Reverse proxy configuration
    ├── supervisord.conf            # Process manager config
    ├── docker-entrypoint.sh        # Container initialization
    ├── README.md                   # Comprehensive Docker guide
    ├── UNRAID_SETUP.md             # Unraid deployment guide
    ├── DEPLOYMENT_CHECKLIST.md     # Production checklist
    ├── DOCKER_SETUP_SUMMARY.md     # Complete overview
    └── QUICK_REFERENCE.md          # This file
```

## One-Liner Commands

```bash
# Local Development
cp .env.docker.example .env && nano .env && docker-compose up -d

# View Logs
docker-compose logs -f

# Stop
docker-compose down

# Rebuild
docker-compose build --no-cache && docker-compose up -d

# Shell Access
docker exec -it jutsu-trading-dashboard bash

# Health Check
curl http://localhost:8080/api/status

# Database Shell
docker exec -it jutsu-trading-dashboard sqlite3 /app/data/market_data.db
```

## Container Architecture

```
Port 80 (Exposed) → Nginx
                    ├── / → React Frontend (Static)
                    ├── /api/* → FastAPI Backend (Proxy)
                    └── /ws → WebSocket (Proxy)
                           ↓
                    FastAPI (Port 8000, Internal)
                    └── SQLite Database
```

## Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `http://localhost:8080/` | Dashboard UI |
| `http://localhost:8080/api/status` | API health check |
| `http://localhost:8080/docs` | Swagger API docs |
| `http://localhost:8080/redoc` | ReDoc API docs |
| `ws://localhost:8080/ws` | WebSocket live updates |

## Environment Variables (Essential)

```bash
# Schwab API (required for live trading)
SCHWAB_APP_KEY=your_app_key
SCHWAB_APP_SECRET=your_app_secret
SCHWAB_CALLBACK_URL=https://127.0.0.1

# Application
DATABASE_URL=sqlite:////app/data/market_data.db
LOG_LEVEL=INFO
TZ=America/New_York
TRADING_MODE=offline_mock  # or online_live
```

## Volume Mounts

| Container | Host (Docker Compose) | Host (Unraid) | Purpose |
|-----------|-----------------------|---------------|---------|
| `/app/data` | `./data` | `/mnt/user/appdata/jutsu/data` | Database |
| `/app/config` | `./config` | `/mnt/user/appdata/jutsu/config` | Config (RO) |
| `/app/state` | `./state` | `/mnt/user/appdata/jutsu/state` | State |
| `/app/logs` | `./logs` | `/mnt/user/appdata/jutsu/logs` | Logs |
| `/app/token.json` | `./token.json` | `/mnt/user/appdata/jutsu/token.json` | OAuth (RO) |

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Container won't start | `docker logs jutsu-trading-dashboard` | Check volume permissions, verify .env |
| Dashboard not loading | `docker exec jutsu-trading-dashboard ps aux \| grep nginx` | Restart: `docker-compose restart` |
| API errors | `curl http://localhost:8080/api/status` | Check FastAPI logs, verify database |
| Database errors | `docker exec jutsu-trading-dashboard ls /app/data/` | Ensure volumes mounted correctly |

## Health Monitoring

```bash
# Container status
docker ps | grep jutsu

# Resource usage
docker stats jutsu-trading-dashboard

# Service status
docker exec jutsu-trading-dashboard supervisorctl status

# Application logs
docker logs jutsu-trading-dashboard | tail -50

# Nginx logs
docker exec jutsu-trading-dashboard tail /var/log/nginx/error.log
```

## Backup & Restore

```bash
# Backup (quick)
tar czf backup-$(date +%Y%m%d).tar.gz data/ state/ config/ token.json

# Restore
tar xzf backup-20240101.tar.gz

# Database only
docker exec jutsu-trading-dashboard sqlite3 /app/data/market_data.db \
  ".backup /app/data/backup.db"
```

## Unraid Quick Setup

```bash
# 1. On Unraid, create directories
mkdir -p /mnt/user/appdata/jutsu/{data,config,state,logs}

# 2. Transfer files
scp config/live_trading_config.yaml root@unraid:/mnt/user/appdata/jutsu/config/
scp token.json root@unraid:/mnt/user/appdata/jutsu/

# 3. Add container in Unraid UI
#    - Repository: jutsu-trading-dashboard:latest
#    - Port: 8080:80
#    - Volumes: See UNRAID_SETUP.md
#    - Env vars: SCHWAB_APP_KEY, SCHWAB_APP_SECRET, etc.
```

## Security Checklist

- [ ] Non-root user (jutsu:1000) configured in Dockerfile
- [ ] Config volumes mounted read-only
- [ ] token.json file permissions restricted (chmod 600)
- [ ] API authentication enabled (JUTSU_API_USERNAME/PASSWORD)
- [ ] Security headers configured in nginx
- [ ] No sensitive data in docker-compose.yml (use .env)

## Performance Tips

```bash
# Enable SQLite WAL mode (already done in entrypoint)
docker exec jutsu-trading-dashboard sqlite3 /app/data/market_data.db \
  "PRAGMA journal_mode=WAL;"

# Increase workers (if needed)
# Edit docker-compose.yml: environment.UVICORN_WORKERS=2

# Adjust resource limits
docker update --cpus 2 --memory 2g jutsu-trading-dashboard

# Monitor performance
docker stats --no-stream jutsu-trading-dashboard
```

## Documentation Reference

| File | Purpose |
|------|---------|
| `docker/README.md` | Comprehensive Docker guide |
| `docker/UNRAID_SETUP.md` | Unraid deployment steps |
| `docker/DEPLOYMENT_CHECKLIST.md` | Production deployment checklist |
| `docker/DOCKER_SETUP_SUMMARY.md` | Complete technical overview |
| `.env.docker.example` | Environment variable template |

## Common Issues

### 1. "Permission denied" on volumes
```bash
chmod -R 755 data/ state/ logs/
chown -R 1000:1000 data/ state/ logs/
```

### 2. Port already in use
```bash
# Change host port in docker-compose.yml
ports:
  - "8081:80"  # Use 8081 instead of 8080
```

### 3. Database locked
```bash
# Stop container, enable WAL mode, restart
docker-compose down
docker-compose up -d
docker exec jutsu-trading-dashboard sqlite3 /app/data/market_data.db \
  "PRAGMA journal_mode=WAL;"
```

### 4. Schwab OAuth token missing
```bash
# Generate token interactively
docker exec -it jutsu-trading-dashboard bash
python3 -c "from jutsu_engine.live.schwab_executor import authenticate; authenticate()"
# Follow browser flow, copy token.json to host
```

## Build & Deploy Workflow

```bash
# Development
git pull
docker-compose build
docker-compose up -d
docker-compose logs -f

# Production (Unraid)
docker build -t jutsu-trading-dashboard:latest .
docker tag jutsu-trading-dashboard:latest myregistry.com/jutsu:latest
docker push myregistry.com/jutsu:latest
# Deploy via Unraid UI
```

## Contact & Support

- **Documentation**: See `docker/` directory for detailed guides
- **API Docs**: `http://localhost:8080/docs` (after deployment)
- **Logs**: `docker logs jutsu-trading-dashboard`
- **Issues**: Check DEPLOYMENT_CHECKLIST.md troubleshooting section

---

**Quick Start**: `cp .env.docker.example .env && nano .env && docker-compose up -d`

**First Time**: See `docker/README.md` for complete setup guide

**Production**: See `docker/UNRAID_SETUP.md` for Unraid deployment
