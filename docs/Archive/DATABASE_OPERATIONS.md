# Database Operations Guide - Jutsu Labs

> Complete guide for PostgreSQL backup, restore, and maintenance operations

**Last Updated:** December 27, 2025

---

## Overview

Jutsu Labs supports two database backends:
- **SQLite**: Development and local testing
- **PostgreSQL**: Production deployment (Docker/Unraid)

This guide focuses on PostgreSQL operations for production environments.

---

## PostgreSQL Configuration

### Environment Variables (.env)

```env
# Database Type
DATABASE_TYPE=postgresql

# PostgreSQL Connection
POSTGRES_HOST=tower.local      # Your Docker host
POSTGRES_PORT=5423             # External port mapping
POSTGRES_USER=jutsudB
POSTGRES_PASSWORD=your_password
POSTGRES_DATABASE=jutsu_labs
```

### Docker Configuration (Unraid Example)

| Setting | Value |
|---------|-------|
| Container Port | 5432 |
| Host Port | 5423 |
| Data Path | `/mnt/user/appdata/jutsu-postgres` |
| PostgreSQL Version | 17.x |

---

## Backup Operations

### Quick Backup (One-Liner)

```bash
# Find container and backup in one command
docker exec $(docker ps -qf "ancestor=postgres") pg_dump -U jutsudB -d jutsu_labs > jutsu_backup_$(date +%Y%m%d_%H%M%S).sql
```

### Step-by-Step Backup

```bash
# 1. Find your PostgreSQL container
docker ps | grep postgres
# Output: 7a7be00ec0a6   postgres:17   ...

# 2. Create backup with timestamp
docker exec 7a7be00ec0a6 pg_dump -U jutsudB -d jutsu_labs > jutsu_backup_$(date +%Y%m%d_%H%M%S).sql

# 3. Verify backup created
ls -lh jutsu_backup_*.sql
# Output: -rw-r--r--  1 user  staff  18.5M Dec 27 18:29 jutsu_backup_20251227_182924.sql
```

### Scheduled Backups (Cron)

Add to crontab for daily backups:

```bash
crontab -e
```

Add line:
```cron
# Daily PostgreSQL backup at 2 AM
0 2 * * * docker exec $(docker ps -qf "ancestor=postgres") pg_dump -U jutsudB -d jutsu_labs > /path/to/backups/jutsu_backup_$(date +\%Y\%m\%d).sql 2>&1
```

### Backup Best Practices

1. **Before any upgrade**: Always backup before PostgreSQL version upgrades
2. **Before schema changes**: Backup before running migrations
3. **Weekly minimum**: Keep at least 7 days of backups
4. **Offsite storage**: Copy backups to cloud storage or different machine
5. **Test restores**: Periodically verify backups can be restored

---

## Restore Operations

### Full Database Restore

```bash
# 1. Stop any applications using the database
# (Stop Jutsu Labs dashboard, trading engine, etc.)

# 2. Restore from backup
docker exec -i CONTAINER_ID psql -U jutsudB -d jutsu_labs < jutsu_backup_20251227_182924.sql

# 3. Verify restore
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "SELECT COUNT(*) FROM performance_snapshots;"
```

### Restore to Fresh Database (After Upgrade)

```bash
# 1. Drop and recreate database (if needed)
docker exec CONTAINER_ID psql -U jutsudB -c "DROP DATABASE IF EXISTS jutsu_labs;"
docker exec CONTAINER_ID psql -U jutsudB -c "CREATE DATABASE jutsu_labs;"

# 2. Restore from backup
docker exec -i CONTAINER_ID psql -U jutsudB -d jutsu_labs < jutsu_backup_20251227_182924.sql
```

### Initialize Fresh Tables (No Backup Available)

```bash
# Copy init script to container and run
docker cp scripts/init_postgres_tables.sql CONTAINER_ID:/tmp/
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -f /tmp/init_postgres_tables.sql
```

---

## Schema Migrations

### Common Migration: Column Rename

```sql
-- Rename system_state.last_updated to updated_at
ALTER TABLE system_state RENAME COLUMN last_updated TO updated_at;
```

### Common Migration: Add Default Constraints

```sql
-- Add NOT NULL with DEFAULT to timestamp columns
ALTER TABLE performance_snapshots ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE performance_snapshots ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
```

### Apply Migration via Python (Recommended)

```python
import psycopg2

conn = psycopg2.connect(
    host="tower.local", port=5423, user="jutsudB",
    password="your_password", database="jutsu_labs"
)
cur = conn.cursor()

# Your migration SQL here
cur.execute("ALTER TABLE system_state RENAME COLUMN last_updated TO updated_at;")
cur.execute("ALTER TABLE performance_snapshots ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;")

conn.commit()
print("Migration complete!")
conn.close()
```

---

## PostgreSQL Version Upgrades

### Pre-Upgrade Checklist

- [ ] Create full database backup
- [ ] Verify backup file size is reasonable (not 0 bytes)
- [ ] Test backup can be read: `head -20 jutsu_backup_*.sql`
- [ ] Document current PostgreSQL version
- [ ] Stop all applications using database

### Upgrade Steps

1. **Backup existing data**
   ```bash
   docker exec CONTAINER_ID pg_dump -U jutsudB -d jutsu_labs > pre_upgrade_backup.sql
   ```

2. **Stop old container**
   ```bash
   docker stop CONTAINER_ID
   ```

3. **Start new version container**
   - Update Docker image to new PostgreSQL version
   - Use NEW data directory (major versions are incompatible)

4. **Initialize schema**
   ```bash
   docker exec -i NEW_CONTAINER_ID psql -U jutsudB -d jutsu_labs < scripts/init_postgres_tables.sql
   ```

5. **Restore data**
   ```bash
   docker exec -i NEW_CONTAINER_ID psql -U jutsudB -d jutsu_labs < pre_upgrade_backup.sql
   ```

6. **Verify data**
   ```bash
   docker exec NEW_CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "SELECT COUNT(*) FROM market_data;"
   ```

### Post-Upgrade Verification

```bash
# Check all tables exist
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "\dt"

# Verify row counts
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "
SELECT 'market_data' as table_name, COUNT(*) FROM market_data
UNION ALL
SELECT 'performance_snapshots', COUNT(*) FROM performance_snapshots
UNION ALL
SELECT 'positions', COUNT(*) FROM positions;
"
```

---

## Diagnostic Commands

### Check Database Connection

```bash
# Via Docker
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "SELECT 1;"

# Via Python
python3 -c "
import psycopg2
conn = psycopg2.connect(host='tower.local', port=5423, user='jutsudB', password='your_password', database='jutsu_labs')
print('Connection successful!')
conn.close()
"
```

### Check Table Schema

```bash
# List all tables
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "\dt"

# Describe specific table
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "\d performance_snapshots"
```

### Check Column Defaults

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'performance_snapshots'
ORDER BY ordinal_position;
```

### Check for NULL Values

```sql
SELECT
    'created_at NULLs' as check_name,
    COUNT(*) as count
FROM performance_snapshots
WHERE created_at IS NULL;
```

---

## Troubleshooting

### Error: "column does not exist"

**Cause**: Schema mismatch between code and database

**Solution**:
```bash
# Check actual column names
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "\d system_state"

# Apply migration if needed
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "ALTER TABLE system_state RENAME COLUMN old_name TO new_name;"
```

### Error: "null value violates not-null constraint"

**Cause**: Missing DEFAULT constraint on column

**Solution**:
```bash
# Add default to column
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "ALTER TABLE tablename ALTER COLUMN columnname SET DEFAULT CURRENT_TIMESTAMP;"

# Update existing NULL values
docker exec CONTAINER_ID psql -U jutsudB -d jutsu_labs -c "UPDATE tablename SET columnname = CURRENT_TIMESTAMP WHERE columnname IS NULL;"
```

### Error: "connection refused"

**Cause**: PostgreSQL not running or wrong port

**Solution**:
```bash
# Check container is running
docker ps | grep postgres

# Check port mapping
docker port CONTAINER_ID

# Test connection
nc -zv tower.local 5423
```

---

## SQLAlchemy Key Learnings

### `default` vs `server_default`

```python
# WRONG - Only applies when SQLAlchemy creates the object
created_at = Column(DateTime, default=datetime.utcnow)

# CORRECT - Database applies default on any INSERT (including raw SQL)
created_at = Column(DateTime, server_default=func.now())
```

Always use `server_default` for timestamp columns to ensure defaults work with:
- SQLAlchemy ORM operations
- Raw SQL inserts
- Database migrations
- External tools

---

## Quick Reference

| Task | Command |
|------|---------|
| Find container | `docker ps \| grep postgres` |
| Backup | `docker exec ID pg_dump -U jutsudB -d jutsu_labs > backup.sql` |
| Restore | `docker exec -i ID psql -U jutsudB -d jutsu_labs < backup.sql` |
| List tables | `docker exec ID psql -U jutsudB -d jutsu_labs -c "\dt"` |
| Describe table | `docker exec ID psql -U jutsudB -d jutsu_labs -c "\d tablename"` |
| Row count | `docker exec ID psql -U jutsudB -d jutsu_labs -c "SELECT COUNT(*) FROM tablename;"` |

---

## Related Documentation

- `scripts/init_postgres_tables.sql` - Table initialization script
- `jutsu_engine/data/models.py` - SQLAlchemy model definitions
- `docs/TROUBLESHOOTING.md` - General troubleshooting guide
- `.serena/memories/postgres_schema_fixes_2025-12-27.md` - Schema fix details
