# Troubleshooting Guide - Jutsu Labs

> Common issues and solutions for the Jutsu Labs backtesting engine

**Last Updated:** November 2, 2025

---

## Quick Diagnostics

**Run the credentials check script first:**
```bash
python scripts/check_credentials.py
```

This will automatically diagnose:
- ✅ .env file exists
- ✅ Environment variables are set
- ✅ Database schema is correct
- ✅ API connection works

---

## Error Categories

### 0. PostgreSQL Docker Issues (Production)

#### Symptom: Schema Errors After PostgreSQL Upgrade
```
ERROR: column "updated_at" does not exist at character 32
ERROR: null value in column "created_at" violates not-null constraint
```

#### Root Cause
PostgreSQL major version upgrades (e.g., v16 → v17) require data migration. The new version starts with empty tables.

#### Solution

**Step 1: Backup Before Upgrade**
```bash
# Find container ID
docker ps | grep postgres

# Create backup (replace CONTAINER_ID)
docker exec CONTAINER_ID pg_dump -U jutsudB -d jutsu_labs > jutsu_backup_$(date +%Y%m%d_%H%M%S).sql
```

**Step 2: After Upgrade - Restore Tables**
```bash
# Option A: Initialize fresh tables
docker exec -i CONTAINER_ID psql -U jutsudB -d jutsu_labs < scripts/init_postgres_tables.sql

# Option B: Restore from backup
docker exec -i CONTAINER_ID psql -U jutsudB -d jutsu_labs < jutsu_backup_YYYYMMDD_HHMMSS.sql
```

**Step 3: Apply Schema Migrations (if needed)**
```bash
# Fix column naming issues
docker exec -i CONTAINER_ID psql -U jutsudB -d jutsu_labs << 'EOF'
ALTER TABLE system_state RENAME COLUMN last_updated TO updated_at;
ALTER TABLE performance_snapshots ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
EOF
```

See `docs/DATABASE_OPERATIONS.md` for complete backup/restore procedures.

---

### 1. Authentication Errors (401 Unauthorized)

#### Symptom
```
2025-11-02 17:17:15 | DATA.SCHWAB | ERROR | Authentication failed: 401 Client Error: Unauthorized for url: https://api.schwabapi.com/v1/oauth/token
```

#### Root Causes

**A. Missing or Invalid .env File**
```bash
# Check if .env exists
ls -la .env

# If missing:
cp .env.example .env
```

**B. Placeholder Credentials in .env**
```bash
# Check current values
grep SCHWAB_API .env

# If you see "your_api_key_here", you need to replace it!
# Edit .env and add your REAL credentials from https://developer.schwab.com
nano .env
```

**C. Environment Variables Not Loaded**
```bash
# Install python-dotenv
pip install python-dotenv

# Or manually load for testing
export $(cat .env | grep -v '^#' | xargs)
```

**D. Invalid API Credentials**
- Credentials expired or revoked
- Wrong API key/secret combination
- Account not approved by Schwab

#### Solutions

**Step 1: Verify .env File**
```bash
# Should output "yes"
[ -f .env ] && echo "yes" || echo "no"
```

**Step 2: Check Credentials Format**
```bash
# Your .env should look like this (with REAL values):
SCHWAB_API_KEY=abc123xyz789...  # NOT "your_api_key_here"
SCHWAB_API_SECRET=def456uvw012...  # NOT "your_api_secret_here"
SCHWAB_CALLBACK_URL=https://localhost:8080/callback
```

**Step 3: Get Real Credentials from Schwab**
1. Go to https://developer.schwab.com
2. Login or create account
3. Create New App
4. Copy API Key and API Secret
5. Paste into .env file

**Step 4: Test Configuration**
```bash
python scripts/check_credentials.py
```

---

### 2. Database Schema Errors

#### Symptom
```
✗ Sync failed: 'timeframe' is an invalid keyword argument for DataAuditLog
```

Or:

```
sqlalchemy.exc.OperationalError: no such table: data_audit_log
```

#### Root Cause
Database schema outdated or corrupted after code changes.

#### Solution

**Recreate Database:**
```bash
# Backup old database (if you have data)
mv data/market_data.db data/market_data.db.backup

# Reinitialize with correct schema
jutsu init

# Verify
python scripts/check_credentials.py
```

**If You Need to Preserve Data:**
```bash
# Contact us for migration script or manually export/import
# For now, Phase 1 MVP doesn't have migration support
```

---

### 3. Module Import Errors

#### Symptom
```
ModuleNotFoundError: No module named 'jutsu_engine'
```

#### Solution

**A. Virtual Environment Not Activated**
```bash
# Activate venv
source venv/bin/activate

# Verify
which python
# Should show: /path/to/Jutsu-Labs/venv/bin/python
```

**B. Package Not Installed**
```bash
# Install in editable mode
pip install -e .

# Verify
jutsu --version
# Should show: Jutsu, version 0.1.0
```

---

### 4. Rate Limiting Errors

#### Symptom
```
⚠️ Warning: Rate limit exceeded (HTTP 429)
```

#### Cause
Schwab API limits:
- 2 requests per second
- 120 requests per minute

#### Solution
**This is NORMAL and handled automatically!**

Jutsu Labs implements automatic retry with exponential backoff:
- Initial retry: 2 seconds
- Next retry: 4 seconds
- Max retries: 3 attempts

Just wait - it will resume automatically.

---

### 5. Data Validation Errors

#### Symptom
```
❌ Invalid OHLC relationship: High (150.00) < Low (151.00)
```

#### Solution

**Run Data Validation:**
```bash
jutsu validate AAPL

# Fix invalid data
jutsu sync AAPL --force-refresh
```

**Automatic Handling:**
- Invalid bars marked with `is_valid=False`
- Not used in backtests
- Preserved for audit trail

---

### 6. CLI Command Errors

#### Symptom
```
Error: Missing option '--symbol'
```

#### Solution

**Check Command Syntax:**
```bash
# Correct
jutsu sync --symbol AAPL --start 2024-01-01

# Wrong
jutsu sync AAPL --start 2024-01-01  # Missing --symbol flag
```

**Get Help:**
```bash
jutsu --help
jutsu sync --help
jutsu backtest --help
```

---

### 7. No Data Found Errors

#### Symptom
```
❌ No data available for AAPL 1D in date range
```

#### Solution

**A. Sync Data First**
```bash
# Check what you have
jutsu status

# Sync missing data
jutsu sync --symbol AAPL --start 2023-01-01
```

**B. Verify Date Range**
```bash
# Check available data
jutsu status

# Make sure backtest dates are within data range
jutsu backtest AAPL \
  --start-date 2023-01-01 \  # Must be >= first data date
  --end-date 2024-10-31       # Must be <= last data date
```

---

## Common Workflows

### Fresh Start (Reset Everything)
```bash
# 1. Remove old database
rm -f data/market_data.db

# 2. Reinitialize
jutsu init

# 3. Check credentials
python scripts/check_credentials.py

# 4. Sync data
jutsu sync --symbol AAPL --start 2024-01-01

# 5. Run backtest
jutsu backtest AAPL --strategy SMA_Crossover
```

### Debug Mode
```bash
# Enable debug logging in .env
LOG_LEVEL=DEBUG

# Run command
jutsu sync --symbol AAPL --start 2024-11-01

# Check logs
tail -f logs/jutsu_engine_*.log
```

### Test API Connection
```bash
# 1. Check credentials
python scripts/check_credentials.py

# 2. Try small sync (1 month of data)
jutsu sync --symbol AAPL --start 2024-10-01

# 3. If successful, sync more data
jutsu sync --symbol AAPL --start 2023-01-01
```

---

## Error Reference Table

| Error Code | Meaning | Solution |
|------------|---------|----------|
| 401 | Unauthorized | Check API credentials in .env |
| 429 | Rate limit | Wait - auto-retries enabled |
| 404 | Symbol not found | Check ticker symbol spelling |
| 500 | Schwab API error | Wait and retry later |
| SQLAlchemy errors | Database schema | Run `jutsu init` |
| ModuleNotFoundError | Import issue | Run `pip install -e .` |

---

## Diagnostic Commands

### Check Everything
```bash
python scripts/check_credentials.py
```

### Check Database
```bash
# List tables
sqlite3 data/market_data.db ".tables"

# Count bars
sqlite3 data/market_data.db "SELECT COUNT(*) FROM market_data;"

# Check metadata
sqlite3 data/market_data.db "SELECT * FROM data_metadata;"
```

### Check Logs
```bash
# View recent logs
tail -100 logs/jutsu_engine_*.log

# Search for errors
grep ERROR logs/jutsu_engine_*.log

# Watch live logs
tail -f logs/jutsu_engine_*.log
```

### Check Environment
```bash
# Python version (need 3.10+)
python --version

# Virtual environment active?
which python

# Installed packages
pip list | grep jutsu
```

---

## Getting Help

### Documentation
- **System Design**: `docs/SYSTEM_DESIGN.md`
- **Best Practices**: `docs/BEST_PRACTICES.md`
- **Environment Setup**: `docs/ENVIRONMENT_SETUP.md`
- **This Guide**: `docs/TROUBLESHOOTING.md`

### Debug Information to Provide
When asking for help, include:

1. **Error Message**: Full error output
2. **Command**: Exact command you ran
3. **Environment**:
   ```bash
   python --version
   jutsu --version
   which python
   ```
4. **Logs**: Recent logs from `logs/` directory
5. **Configuration**: (DON'T share API credentials!)
   ```bash
   cat .env | grep -v 'API_KEY\|API_SECRET'
   ```

### Self-Help Checklist
Before asking for help, try:
- [ ] Run `python scripts/check_credentials.py`
- [ ] Check logs in `logs/` directory
- [ ] Try `jutsu init` to reset database
- [ ] Verify .env has real credentials (not placeholders)
- [ ] Confirm virtual environment is activated
- [ ] Review error message carefully

---

## FAQ

**Q: My credentials are correct but I still get 401 errors**
A: Make sure .env is being loaded. Try: `export $(cat .env | grep -v '^#' | xargs)` then retry.

**Q: Can I use paper trading with Phase 1 MVP?**
A: No, Phase 1 is backtesting only. Paper trading is Phase 4.

**Q: Why is sync so slow?**
A: Schwab limits to 2 requests/second. Syncing years of data takes time. This is expected.

**Q: Can I use multiple data sources?**
A: Phase 1 supports only Schwab. CSV/Yahoo Finance coming in Phase 2.

**Q: How do I reset everything?**
A: `rm -rf data/ logs/` then `jutsu init`

**Q: Where are my API credentials stored?**
A: In `.env` file (which is gitignored for security)

---

## Prevention Tips

### Best Practices
1. **Always run `check_credentials.py` after setup**
2. **Keep logs/ directory for debugging** (gitignored by default)
3. **Back up `.env` file** (to secure location, NOT git)
4. **Test with small data first** (1 month before 1 year)
5. **Monitor rate limits** during large syncs
6. **Run `jutsu status`** regularly to verify data

### Avoid These
1. ❌ Never commit `.env` to git
2. ❌ Never use production API keys in development
3. ❌ Never sync 20+ years of data at once (rate limits)
4. ❌ Never edit database manually (use CLI commands)
5. ❌ Never share API credentials

---

## Still Stuck?

If you've tried everything:

1. **Create Minimal Example:**
   ```bash
   rm -rf data/ logs/
   jutsu init
   jutsu sync --symbol AAPL --start 2024-11-01
   ```

2. **Collect Debug Info:**
   ```bash
   python scripts/check_credentials.py > debug_output.txt
   jutsu --version >> debug_output.txt
   tail -100 logs/jutsu_engine_*.log >> debug_output.txt
   ```

3. **Review Documentation:**
   - Check SYSTEM_DESIGN.md
   - Review BEST_PRACTICES.md
   - Read ENVIRONMENT_SETUP.md

4. **File an Issue:**
   - Include debug_output.txt
   - Describe what you tried
   - Include error messages
   - DON'T include API credentials

---

## Summary

**Most Common Issues:**
1. **401 Authentication**: Fix .env credentials
2. **Schema Errors**: Run `jutsu init`
3. **Import Errors**: Activate venv and `pip install -e .`
4. **No Data**: Run `jutsu sync` first

**First Step for ANY Issue:**
```bash
python scripts/check_credentials.py
```

This diagnoses 90% of problems automatically! 🎯
