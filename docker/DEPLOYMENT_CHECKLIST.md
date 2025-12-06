# Jutsu Trading Dashboard - Deployment Checklist

## Pre-Deployment Checklist

### 1. Code Preparation
- [ ] Latest code pulled from repository
- [ ] All tests passing: `pytest`
- [ ] Code quality checks passed: `black . && isort . && mypy jutsu_engine/`
- [ ] No sensitive data in code (check for hardcoded credentials)

### 2. Configuration Files
- [ ] `config/live_trading_config.yaml` reviewed and updated
- [ ] Environment variables documented
- [ ] `.env.docker.example` copied to `.env` with actual values
- [ ] Schwab API credentials obtained from developer.schwab.com

### 3. Schwab OAuth Token
- [ ] Decision made: Generate now OR generate in container
- [ ] If generating now: `token.json` file exists in project root
- [ ] If generating later: Plan to run OAuth flow in container documented

### 4. Docker Environment
- [ ] Docker installed and running (Docker Desktop or Docker Engine)
- [ ] Docker Compose installed (version 1.29+ or 2.x)
- [ ] Sufficient disk space (minimum 2GB for image + data)
- [ ] Network ports available (default: 8080 → container port 80)

## Build Phase Checklist

### 1. Local Testing with Docker Compose
```bash
# Terminal commands to verify
[ ] docker --version
[ ] docker-compose --version
[ ] docker ps  # Verify Docker daemon running
```

### 2. Build the Image
```bash
# Build command
[ ] docker-compose build --no-cache

# Verify build success
[ ] docker images | grep jutsu-trading-dashboard
```

### 3. Configuration Verification
```bash
# Verify .env file
[ ] cat .env  # Check all required variables set

# Verify config files exist
[ ] ls -la config/live_trading_config.yaml
[ ] ls -la state/  # Should exist (create if not)
[ ] ls -la data/   # Should exist (create if not)
```

## Deployment Phase Checklist

### 1. Start Container
```bash
# Start with docker-compose
[ ] docker-compose up -d

# Verify container running
[ ] docker ps | grep jutsu-trading-dashboard
[ ] docker-compose ps
```

### 2. Health Checks
```bash
# Check container logs
[ ] docker-compose logs -f  # Look for startup messages

# Verify services running
[ ] docker exec jutsu-trading-dashboard supervisorctl status
# Expected: nginx RUNNING, fastapi RUNNING

# Test endpoints
[ ] curl http://localhost:8080/health
[ ] curl http://localhost:8080/api/status
[ ] curl http://localhost:8080/  # Should return HTML
```

### 3. Database Verification
```bash
# Check database created
[ ] docker exec jutsu-trading-dashboard ls -la /app/data/market_data.db

# Verify tables created
[ ] docker exec jutsu-trading-dashboard sqlite3 /app/data/market_data.db ".tables"
# Expected: market_data, data_metadata, alembic_version
```

### 4. Frontend Verification
```bash
# Browser tests
[ ] Open http://localhost:8080 in browser
[ ] Dashboard loads without errors
[ ] No console errors in browser dev tools (F12)
[ ] WebSocket connects (check network tab)
```

### 5. API Verification
```bash
# API endpoints
[ ] http://localhost:8080/docs  # Swagger UI loads
[ ] http://localhost:8080/redoc  # ReDoc loads
[ ] API returns valid JSON responses
```

## Post-Deployment Checklist

### 1. Schwab OAuth (if not done pre-deployment)
```bash
# If token.json doesn't exist
[ ] docker exec -it jutsu-trading-dashboard bash
[ ] python3 -c "from jutsu_engine.live.schwab_executor import authenticate; authenticate()"
[ ] Follow OAuth flow in browser
[ ] Verify token.json created
[ ] Copy to host: docker cp jutsu-trading-dashboard:/app/token.json ./token.json
[ ] Restart container: docker-compose restart
```

### 2. Monitoring Setup
```bash
# Log monitoring
[ ] docker-compose logs -f --tail=100  # Verify no errors
[ ] Check application logs: ls -la logs/

# Resource monitoring
[ ] docker stats jutsu-trading-dashboard  # Check CPU/Memory usage
```

### 3. Functional Testing
- [ ] Start trading engine via API or dashboard
- [ ] Verify data sync works (market data fetching)
- [ ] Check portfolio updates in dashboard
- [ ] Test WebSocket live updates
- [ ] Verify scheduler service (if enabled)

### 4. Security Checks
```bash
# User permissions
[ ] docker exec jutsu-trading-dashboard whoami  # Should be "jutsu", not "root"

# File permissions
[ ] docker exec jutsu-trading-dashboard ls -la /app/data
[ ] docker exec jutsu-trading-dashboard ls -la /app/state

# API authentication (if enabled)
[ ] curl http://localhost:8080/api/status  # Should require auth if JUTSU_API_USERNAME set
```

## Production Deployment Checklist (Unraid)

### 1. Unraid Server Preparation
```bash
# On Unraid server
[ ] SSH access to Unraid server enabled
[ ] Docker service running
[ ] Sufficient space on appdata share (minimum 2GB)
```

### 2. Create Directories
```bash
[ ] mkdir -p /mnt/user/appdata/jutsu/{data,config,state,logs}
[ ] chmod -R 755 /mnt/user/appdata/jutsu
```

### 3. Transfer Files
```bash
# From development machine
[ ] scp config/live_trading_config.yaml root@unraid:/mnt/user/appdata/jutsu/config/
[ ] scp token.json root@unraid:/mnt/user/appdata/jutsu/  # If exists
[ ] scp .env root@unraid:/tmp/jutsu.env  # For reference, don't commit!
```

### 4. Build or Push Image
**Option A: Build on Unraid**
```bash
[ ] scp -r Jutsu-Labs/ root@unraid:/tmp/
[ ] ssh root@unraid "cd /tmp/Jutsu-Labs && docker build -t jutsu-trading-dashboard:latest ."
```

**Option B: Use Docker Registry**
```bash
# On development machine
[ ] docker tag jutsu-trading-dashboard:latest myregistry.com/jutsu-trading-dashboard:latest
[ ] docker push myregistry.com/jutsu-trading-dashboard:latest

# On Unraid
[ ] docker pull myregistry.com/jutsu-trading-dashboard:latest
```

### 5. Create Container in Unraid UI
Follow steps in `UNRAID_SETUP.md`:
- [ ] Add container via Unraid Docker tab
- [ ] Configure all port mappings
- [ ] Configure all volume mappings
- [ ] Set all environment variables
- [ ] Apply resource limits
- [ ] Start container

### 6. Verify Deployment
```bash
# On Unraid server
[ ] docker ps | grep jutsu
[ ] docker logs jutsu-trading-dashboard
[ ] curl http://localhost:8080/api/status
```

### 7. Access from Network
- [ ] Find Unraid IP: `ip addr show br0`
- [ ] Access from browser: `http://UNRAID_IP:8080`
- [ ] Test from different devices on network

## Backup Strategy Checklist

### 1. Initial Backup
```bash
# Before making any changes
[ ] docker exec jutsu-trading-dashboard sqlite3 /app/data/market_data.db ".backup /app/data/market_data.db.backup"
[ ] tar czf jutsu-backup-$(date +%Y%m%d).tar.gz data/ state/ config/ token.json
```

### 2. Automated Backups
- [ ] Backup script created (see UNRAID_SETUP.md)
- [ ] Backup schedule configured (daily recommended)
- [ ] Backup retention policy defined (7 days recommended)
- [ ] Backup restoration tested

### 3. Critical Files to Backup
- [ ] `/app/data/market_data.db` - Historical data
- [ ] `/app/state/state.json` - Trading state
- [ ] `/app/state/scheduler_state.json` - Scheduler state
- [ ] `/app/config/live_trading_config.yaml` - Configuration
- [ ] `/app/token.json` - Schwab OAuth token

## Rollback Plan Checklist

### 1. Preparation
- [ ] Previous working image tagged: `jutsu-trading-dashboard:backup`
- [ ] Data backup verified
- [ ] Rollback procedure documented

### 2. Rollback Execution
```bash
# If new deployment fails
[ ] docker-compose down
[ ] docker tag jutsu-trading-dashboard:backup jutsu-trading-dashboard:latest
[ ] Restore data from backup
[ ] docker-compose up -d
[ ] Verify functionality
```

## Troubleshooting Checklist

### If Container Won't Start
- [ ] Check logs: `docker-compose logs`
- [ ] Verify volume permissions
- [ ] Check port conflicts: `netstat -tulpn | grep 8080`
- [ ] Verify .env file syntax

### If Dashboard Won't Load
- [ ] Check nginx logs: `docker exec jutsu-trading-dashboard tail /var/log/nginx/error.log`
- [ ] Verify frontend build: `docker exec jutsu-trading-dashboard ls /app/dashboard/dist`
- [ ] Check browser console for errors

### If API Fails
- [ ] Check FastAPI logs: `docker logs jutsu-trading-dashboard | grep fastapi`
- [ ] Test database connection
- [ ] Verify environment variables
- [ ] Check Schwab API credentials

### If Trading Engine Fails
- [ ] Check application logs in `/app/logs/`
- [ ] Verify token.json exists and is valid
- [ ] Check market hours (trading disabled outside hours)
- [ ] Review trading configuration

## Performance Optimization Checklist

### 1. Initial Performance Baseline
```bash
[ ] docker stats jutsu-trading-dashboard  # Record baseline metrics
[ ] Check response times: curl -w "@curl-format.txt" http://localhost:8080/api/status
[ ] Monitor database size: docker exec jutsu-trading-dashboard du -h /app/data/
```

### 2. Optimization Actions
- [ ] Enable SQLite WAL mode (done in entrypoint)
- [ ] Adjust resource limits based on usage
- [ ] Enable nginx caching (already configured)
- [ ] Consider PostgreSQL if dataset > 10GB

### 3. Monitoring Setup
- [ ] Resource usage alerts configured
- [ ] Log rotation enabled (docker-compose)
- [ ] Disk space monitoring
- [ ] API response time tracking

## Sign-Off

### Development Environment
- [ ] All tests passed
- [ ] Docker build successful
- [ ] Local deployment verified
- [ ] Documentation reviewed

**Deployed by:** ________________
**Date:** ________________
**Version/Tag:** ________________

### Production Environment (Unraid)
- [ ] Container running and healthy
- [ ] All endpoints accessible
- [ ] Trading functionality verified
- [ ] Backups configured and tested
- [ ] Monitoring in place

**Deployed by:** ________________
**Date:** ________________
**Unraid IP:** ________________
**Container Name:** ________________

## Notes

Use this space for deployment-specific notes, issues encountered, or special configurations:

```
[Add notes here]
```

---

**Last Updated:** 2024-12-05
**Document Version:** 1.0.0
