# Staging Environment Architecture

> **Created**: 2026-01-02  
> **Status**: Implementation Plan  
> **Estimated Effort**: 2-3 Days

## Overview

This document outlines the staging environment architecture for Jutsu Labs, enabling safe testing of changes before production deployment.

```
                           ┌─────────────────┐
                           │   Developer     │
                           │   Workstation   │
                           └────────┬────────┘
                                    │
                                    ▼
                           ┌─────────────────┐
                           │  feature/*      │
                           │  branches       │
                           └────────┬────────┘
                                    │ PR + Review
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                        GitHub Repository                          │
│  ┌────────────┐         ┌────────────┐         ┌────────────┐    │
│  │  feature/* │ ──PR──▶ │  staging   │ ──PR──▶ │   main     │    │
│  │            │         │            │         │            │    │
│  └────────────┘         └─────┬──────┘         └─────┬──────┘    │
└───────────────────────────────┼──────────────────────┼───────────┘
                                │                      │
                    ┌───────────┘                      └───────────┐
                    ▼                                              ▼
           ┌───────────────┐                              ┌───────────────┐
           │ GitHub Actions│                              │ GitHub Actions│
           │ Build :staging│                              │ Build :latest │
           └───────┬───────┘                              └───────┬───────┘
                   │                                              │
                   ▼                                              ▼
           ┌───────────────┐                              ┌───────────────┐
           │  Docker Hub   │                              │  Docker Hub   │
           │ jutsu:staging │                              │ jutsu:latest  │
           └───────┬───────┘                              └───────┬───────┘
                   │                                              │
                   ▼                                              ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                           Unraid Server (tower.local)                      │
│                                                                            │
│  ┌──────────────────────────┐         ┌──────────────────────────┐        │
│  │  Staging Container       │         │  Production Container    │        │
│  │  ────────────────────    │         │  ────────────────────    │        │
│  │  Image: jutsu:staging    │         │  Image: jutsu:latest     │        │
│  │  API:   :8002            │         │  API:   :8001            │        │
│  │  UI:    :3002            │         │  UI:    :3001            │        │
│  │  DB: jutsu_labs_staging  │         │  DB: jutsu_labs          │        │
│  │  Schwab: DISABLED        │         │  Schwab: ENABLED         │        │
│  │  Trading: PAPER ONLY     │         │  Trading: LIVE           │        │
│  └─────────────┬────────────┘         └─────────────┬────────────┘        │
│                │                                    │                      │
│                └──────────────┬─────────────────────┘                      │
│                               ▼                                            │
│                ┌──────────────────────────────┐                           │
│                │      PostgreSQL 17           │                           │
│                │  ┌────────────────────────┐  │                           │
│                │  │ jutsu_labs (production)│  │                           │
│                │  └───────────┬────────────┘  │                           │
│                │              │               │                           │
│                │        Nightly Sync          │                           │
│                │        (2 AM ET)             │                           │
│                │              ▼               │                           │
│                │  ┌────────────────────────┐  │                           │
│                │  │ jutsu_labs_staging     │  │                           │
│                │  └────────────────────────┘  │                           │
│                └──────────────────────────────┘                           │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture Decisions

### 1. Docker Application Strategy

| Aspect | Production | Staging |
|--------|-----------|---------|
| Branch | `main` | `staging` |
| Docker Tag | `ankugo/jutsu-labs:latest` | `ankugo/jutsu-labs:staging` |
| API Port | 8001 | 8002 |
| Dashboard Port | 3001 | 3002 |
| Container Name | `jutsu-labs` | `jutsu-labs-staging` |

**Rationale**: Branch-based deployments follow GitOps best practices. Each branch triggers CI/CD to build and push tagged images. Containers on Unraid pull specific tags.

### 2. Database Replication Strategy

**Approach**: Nightly pg_dump/pg_restore from production → staging

**What Gets Synced**:
| Table | Synced? | Rationale |
|-------|---------|-----------|
| `market_data` | ✅ Yes | Historical data for realistic testing |
| `performance_snapshots` | ✅ Yes | Reference data for dashboard testing |
| `positions` | ❌ No | Staging has independent operational state |
| `live_trades` | ❌ No | Staging has independent trade history |
| `system_state` | ❌ No | Staging has independent scheduler state |
| `config_overrides` | ⚠️ Optional | May want staging-specific configs |

**Sync Timing**: 2:00 AM Eastern Time
- Market closes at 4:00 PM ET
- Production sync completes by 6:00 PM ET
- Safe window: 2:00 AM - 6:00 AM ET

### 3. Security & Isolation

| Secret | Same as Production? | Notes |
|--------|---------------------|-------|
| `SECRET_KEY` | ❌ Different | JWT isolation prevents cross-environment token reuse |
| `ADMIN_PASSWORD` | ✅ Same OK | Convenience for same administrator |
| `SCHWAB_*` | ❌ Disabled | Staging does not connect to Schwab API |
| `POSTGRES_PASSWORD` | ✅ Same | Same PostgreSQL server, different database |

**Critical Safety Features**:
- `SCHWAB_ENABLED=false` - No live API connections
- `PAPER_TRADING_ONLY=true` - Force paper trading mode
- Separate database - No accidental production data mutation

---

## Implementation Tasks

### Phase 1: Git & CI/CD Setup (Day 1)

#### Task 1.1: Create Staging Branch
```bash
# From main branch
git checkout main
git pull origin main
git checkout -b staging
git push -u origin staging
```

#### Task 1.2: Update GitHub Actions
```yaml
# .github/workflows/docker-publish.yml
name: Build and Push Docker Image

on:
  push:
    branches:
      - main      # Build and tag as 'latest'
      - staging   # Build and tag as 'staging'
      - serverdB  # Keep for compatibility

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
      
      - name: Extract branch name
        id: extract_branch
        run: echo "branch=${GITHUB_REF#refs/heads/}" >> $GITHUB_OUTPUT
      
      - name: Set Docker tag
        id: set_tag
        run: |
          if [ "${{ steps.extract_branch.outputs.branch }}" = "main" ]; then
            echo "tag=latest" >> $GITHUB_OUTPUT
          else
            echo "tag=${{ steps.extract_branch.outputs.branch }}" >> $GITHUB_OUTPUT
          fi
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ankugo/jutsu-labs:${{ steps.set_tag.outputs.tag }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

#### Task 1.3: GitHub Branch Protection Rules

**For `main` branch**:
- Require pull request before merging
- Require status checks to pass
- Require review from code owners (optional)
- Do not allow bypassing settings

**For `staging` branch**:
- Require pull request before merging
- Require status checks to pass

---

### Phase 2: PostgreSQL Staging Database (Day 1)

#### Task 2.1: Create Staging Database
```sql
-- Connect to PostgreSQL as superuser
-- Run from Unraid terminal or remote psql

-- Create the staging database
CREATE DATABASE jutsu_labs_staging 
  WITH OWNER jutsu 
  TEMPLATE template0 
  ENCODING 'UTF8' 
  LC_COLLATE 'en_US.UTF-8' 
  LC_CTYPE 'en_US.UTF-8';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE jutsu_labs_staging TO jutsu;
```

#### Task 2.2: Initialize Schema
```bash
# Connect to staging database
PGPASSWORD='Maruthi13JT@@' psql -h tower.local -p 5423 -U jutsu -d jutsu_labs_staging

# Apply schema from production dump (schema only)
PGPASSWORD='Maruthi13JT@@' pg_dump -h tower.local -p 5423 -U jutsu \
  --schema-only jutsu_labs | \
PGPASSWORD='Maruthi13JT@@' psql -h tower.local -p 5423 -U jutsu jutsu_labs_staging
```

#### Task 2.3: Create Nightly Sync Script
```bash
#!/bin/bash
# /mnt/user/appdata/jutsu/scripts/sync_staging.sh
# Syncs production data to staging database nightly

set -e

# Configuration
PROD_DB="jutsu_labs"
STAGING_DB="jutsu_labs_staging"
PG_HOST="localhost"
PG_PORT="5423"
PG_USER="jutsu"
export PGPASSWORD="Maruthi13JT@@"

# Tables to sync (only historical/reference data)
SYNC_TABLES=("market_data" "performance_snapshots")

# Log file
LOG_FILE="/mnt/user/appdata/jutsu/logs/staging_sync.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting staging sync" >> "$LOG_FILE"

for TABLE in "${SYNC_TABLES[@]}"; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Syncing table: $TABLE" >> "$LOG_FILE"
    
    # Truncate staging table
    psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$STAGING_DB" \
        -c "TRUNCATE TABLE $TABLE CASCADE;" >> "$LOG_FILE" 2>&1
    
    # Copy data from production
    pg_dump -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" \
        -t "$TABLE" --data-only "$PROD_DB" | \
    psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" "$STAGING_DB" >> "$LOG_FILE" 2>&1
    
    # Get row count
    COUNT=$(psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$STAGING_DB" \
        -t -c "SELECT COUNT(*) FROM $TABLE;")
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $TABLE: $COUNT rows synced" >> "$LOG_FILE"
done

echo "$(date '+%Y-%m-%d %H:%M:%S') - Staging sync complete" >> "$LOG_FILE"

unset PGPASSWORD
```

#### Task 2.4: Configure Cron Job (Unraid)
```bash
# Add to Unraid User Scripts or crontab
# Runs at 2:00 AM Eastern Time

# If Unraid is in different timezone, calculate offset
# For Pacific Time (PT): 2 AM ET = 11 PM PT (previous day)
# Cron format: minute hour day month weekday

# Add to /boot/config/plugins/user.scripts/schedules/
# Or via Unraid User Scripts plugin

0 2 * * * /mnt/user/appdata/jutsu/scripts/sync_staging.sh
```

---

### Phase 3: Docker Staging Container (Day 2)

#### Task 3.1: Unraid Docker Container Template

**Container Settings**:
```yaml
Name: jutsu-labs-staging
Repository: ankugo/jutsu-labs:staging
Network Type: Bridge

Port Mappings:
  - Container: 8000 → Host: 8002  (API)
  - Container: 3000 → Host: 3002  (Dashboard)

Volume Mappings:
  - /mnt/user/appdata/jutsu-staging/config:/app/config
  - /mnt/user/appdata/jutsu-staging/logs:/app/logs
  - /mnt/user/appdata/jutsu-staging/output:/app/output
  # Note: No Schwab token volume

Environment Variables:
  # Database
  DATABASE_TYPE=postgresql
  POSTGRES_HOST=tower.local
  POSTGRES_PORT=5423
  POSTGRES_USER=jutsu
  POSTGRES_PASSWORD=Maruthi13JT@@
  POSTGRES_DATABASE=jutsu_labs_staging
  
  # Authentication
  AUTH_REQUIRED=true
  SECRET_KEY=<generate_new_with_openssl_rand_hex_32>
  ADMIN_PASSWORD=<your_admin_password>
  
  # Safety: Disable live trading features
  SCHWAB_ENABLED=false
  PAPER_TRADING_ONLY=true
  
  # Environment identifier
  ENVIRONMENT=staging
```

#### Task 3.2: Generate Staging SECRET_KEY
```bash
# Generate a unique secret key for staging
openssl rand -hex 32
# Example output: a1b2c3d4e5f6...

# This MUST be different from production to prevent
# JWT tokens from working across environments
```

#### Task 3.3: Create Staging Directories
```bash
# On Unraid
mkdir -p /mnt/user/appdata/jutsu-staging/config
mkdir -p /mnt/user/appdata/jutsu-staging/logs
mkdir -p /mnt/user/appdata/jutsu-staging/output
```

---

### Phase 4: Code Changes for Safety (Day 2)

#### Task 4.1: Add SCHWAB_ENABLED Environment Variable

```python
# jutsu_engine/utils/config.py

def is_schwab_enabled() -> bool:
    """Check if Schwab API integration is enabled."""
    return os.getenv("SCHWAB_ENABLED", "true").lower() == "true"
```

```python
# jutsu_engine/data/fetchers/schwab.py

from jutsu_engine.utils.config import is_schwab_enabled

class SchwabFetcher:
    def __init__(self, ...):
        if not is_schwab_enabled():
            raise RuntimeError(
                "Schwab API is disabled in this environment. "
                "Set SCHWAB_ENABLED=true to enable."
            )
        # ... rest of initialization
```

#### Task 4.2: Add PAPER_TRADING_ONLY Environment Variable

```python
# jutsu_engine/utils/config.py

def is_paper_trading_only() -> bool:
    """Check if only paper trading is allowed."""
    return os.getenv("PAPER_TRADING_ONLY", "false").lower() == "true"
```

```python
# jutsu_engine/live/trading_engine.py

from jutsu_engine.utils.config import is_paper_trading_only

class TradingEngine:
    def start(self, paper_trading: bool = False):
        if is_paper_trading_only() and not paper_trading:
            raise RuntimeError(
                "Live trading is disabled in this environment. "
                "Only paper trading is allowed."
            )
        # ... rest of start logic
```

#### Task 4.3: Add ENVIRONMENT Variable for UI Display

```python
# jutsu_engine/api/routes/status.py

@router.get("/environment")
def get_environment():
    """Return current environment identifier for UI display."""
    return {
        "environment": os.getenv("ENVIRONMENT", "production"),
        "schwab_enabled": is_schwab_enabled(),
        "paper_trading_only": is_paper_trading_only()
    }
```

```typescript
// dashboard/src/components/Layout.tsx
// Add environment badge to header

const EnvironmentBadge = () => {
  const [env, setEnv] = useState<string>('production');
  
  useEffect(() => {
    api.get('/status/environment').then(res => {
      setEnv(res.data.environment);
    });
  }, []);
  
  if (env === 'production') return null;
  
  return (
    <span className="px-2 py-1 bg-yellow-500 text-black text-xs font-bold rounded ml-2">
      {env.toUpperCase()}
    </span>
  );
};
```

---

### Phase 5: Documentation & Validation (Day 3)

#### Task 5.1: Staging Environment Checklist

**Pre-Deployment Checklist**:
- [ ] Staging branch exists and CI/CD is configured
- [ ] `jutsu_labs_staging` database created with schema
- [ ] Nightly sync script installed and tested
- [ ] Cron job configured for 2 AM ET sync
- [ ] Docker container created with correct environment variables
- [ ] SECRET_KEY is different from production
- [ ] SCHWAB_ENABLED=false verified
- [ ] PAPER_TRADING_ONLY=true verified
- [ ] Container starts successfully
- [ ] Dashboard accessible on port 3002
- [ ] API health check passes on port 8002

**Post-Deployment Validation**:
- [ ] Login to staging dashboard
- [ ] Verify "STAGING" badge visible in UI
- [ ] Check database has synced data
- [ ] Attempt to start live trading (should fail with error)
- [ ] Run a backtest to verify functionality

#### Task 5.2: Test Full Workflow

```bash
# 1. Create feature branch
git checkout staging
git pull origin staging
git checkout -b feature/test-staging-workflow

# 2. Make a small change (e.g., update version in README)
echo "# Staging Test $(date)" >> README.md

# 3. Commit and push
git add README.md
git commit -m "test: staging workflow validation"
git push -u origin feature/test-staging-workflow

# 4. Create PR to staging branch
# - Review and merge via GitHub UI

# 5. Wait for CI/CD to build and push staging image
# - Check GitHub Actions for build status
# - Verify Docker Hub has new staging tag

# 6. Update staging container on Unraid
# - Pull new image or wait for Watchtower

# 7. Verify change is live on staging
# - Access staging dashboard on port 3002
# - Confirm change is visible

# 8. If validated, create PR from staging to main
# - Review and merge

# 9. Verify production updated
# - Access production dashboard on port 3001
```

---

## Maintenance Guide

### Daily Operations

No daily maintenance required. The nightly sync is automated.

### After Code Changes

1. Push to `staging` branch
2. Wait for CI/CD build (2-5 minutes)
3. Container auto-updates (if Watchtower configured) or manually pull
4. Test changes on staging
5. If approved, merge `staging` → `main`

### Database Schema Migrations

When code includes schema changes:

1. Apply migration to production first (standard deploy)
2. Migrations auto-apply to staging during next container restart
3. OR manually run migrations on staging database:
   ```bash
   PGPASSWORD='...' psql -h tower.local -p 5423 -U jutsu -d jutsu_labs_staging \
     -f migrations/xyz.sql
   ```

### Troubleshooting

**Staging container won't start**:
- Check environment variables are correct
- Verify staging database exists and is accessible
- Check container logs: `docker logs jutsu-labs-staging`

**Sync script fails**:
- Check PostgreSQL is running
- Verify PGPASSWORD is correct
- Check disk space on Unraid
- Review sync log: `/mnt/user/appdata/jutsu/logs/staging_sync.log`

**JWT authentication fails on staging**:
- Verify SECRET_KEY is set (not empty)
- Clear browser cookies (may have production token cached)

---

## Future Enhancements

### Phase 2 (Optional)

1. **Watchtower Integration**
   - Auto-pull new images on schedule
   - Different schedules for staging vs production
   - Slack/Discord notifications

2. **Automated E2E Tests**
   - Playwright tests running against staging
   - Block merge to main if tests fail

3. **Separate Schwab App Registration**
   - Full API testing capability on staging
   - No rate limit competition with production

4. **Blue/Green Deployment**
   - Zero-downtime production deploys
   - Instant rollback capability

---

## Quick Reference

| Resource | Production | Staging |
|----------|-----------|---------|
| Branch | `main` | `staging` |
| Docker Tag | `latest` | `staging` |
| API URL | `http://tower.local:8001` | `http://tower.local:8002` |
| Dashboard URL | `http://tower.local:3001` | `http://tower.local:3002` |
| Database | `jutsu_labs` | `jutsu_labs_staging` |
| Schwab API | Enabled | Disabled |
| Live Trading | Enabled | Paper Only |

---

## Appendix: Full Environment Variable Reference

```bash
# Staging Container Environment Variables

# === Database ===
DATABASE_TYPE=postgresql
POSTGRES_HOST=tower.local
POSTGRES_PORT=5423
POSTGRES_USER=jutsu
POSTGRES_PASSWORD=<your_password>
POSTGRES_DATABASE=jutsu_labs_staging

# === Authentication ===
AUTH_REQUIRED=true
SECRET_KEY=<staging_unique_secret_key>
ADMIN_PASSWORD=<your_admin_password>

# === Safety Switches ===
SCHWAB_ENABLED=false
PAPER_TRADING_ONLY=true

# === Environment Identifier ===
ENVIRONMENT=staging
TZ=America/New_York

# === Logging ===
LOG_LEVEL=DEBUG  # More verbose for staging
```
