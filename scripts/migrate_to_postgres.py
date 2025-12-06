#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script

Migrates all data from SQLite database to PostgreSQL.
Preserves all data while maintaining referential integrity.

Usage:
    1. Set up PostgreSQL connection in .env:
       DATABASE_TYPE=postgresql
       POSTGRES_HOST=your-host
       POSTGRES_PORT=5432
       POSTGRES_USER=jutsu
       POSTGRES_PASSWORD=your-password
       POSTGRES_DATABASE=jutsu_labs

    2. Run migration:
       python scripts/migrate_to_postgres.py

    3. Optionally specify SQLite path:
       python scripts/migrate_to_postgres.py --sqlite-path /path/to/market_data.db

Requirements:
    - psycopg2-binary: pip install psycopg2-binary
    - SQLAlchemy: pip install sqlalchemy
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from jutsu_engine.data.models import (
    Base,
    MarketData,
    DataMetadata,
    DataAuditLog,
    LiveTrade,
    Position,
    PerformanceSnapshot,
    ConfigOverride,
    ConfigHistory,
    SystemState,
    User,
)
from jutsu_engine.utils.config import (
    get_postgresql_url,
    get_sqlite_url,
    DATABASE_TYPE_POSTGRES,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger('MIGRATION')


# Tables to migrate in order (respecting dependencies)
TABLES_TO_MIGRATE = [
    ('market_data', MarketData),
    ('data_metadata', DataMetadata),
    ('data_audit_log', DataAuditLog),
    ('live_trades', LiveTrade),
    ('positions', Position),
    ('performance_snapshots', PerformanceSnapshot),
    ('config_overrides', ConfigOverride),
    ('config_history', ConfigHistory),
    ('system_state', SystemState),
    ('users', User),
]


def get_sqlite_engine(sqlite_path: str = None):
    """Create SQLite engine."""
    if sqlite_path:
        # Use provided path
        if Path(sqlite_path).is_absolute():
            db_url = f"sqlite:///{sqlite_path}"
        else:
            db_url = f"sqlite:///{sqlite_path}"
    else:
        # Use default from config
        db_url = get_sqlite_url()

    logger.info(f"SQLite URL: {db_url}")

    return create_engine(
        db_url,
        connect_args={'check_same_thread': False},
        echo=False,
    )


def get_postgres_engine():
    """Create PostgreSQL engine."""
    db_url = get_postgresql_url()
    logger.info(f"PostgreSQL URL: {db_url[:50]}...")

    return create_engine(
        db_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


def migrate_table(sqlite_session, postgres_session, table_name: str, model_class):
    """
    Migrate a single table from SQLite to PostgreSQL.

    Args:
        sqlite_session: SQLite database session
        postgres_session: PostgreSQL database session
        table_name: Name of the table
        model_class: SQLAlchemy model class
    """
    logger.info(f"Migrating table: {table_name}")

    try:
        # Count source records
        source_count = sqlite_session.query(model_class).count()
        logger.info(f"  Source records: {source_count}")

        if source_count == 0:
            logger.info(f"  Skipping empty table: {table_name}")
            return 0

        # Check if target table has data
        target_count = postgres_session.query(model_class).count()
        if target_count > 0:
            logger.warning(f"  Target table already has {target_count} records!")
            response = input("  Overwrite? (y/N): ").strip().lower()
            if response != 'y':
                logger.info("  Skipping table")
                return 0
            # Delete existing records
            postgres_session.query(model_class).delete()
            postgres_session.commit()

        # Fetch all records from SQLite
        records = sqlite_session.query(model_class).all()

        # Detach records from SQLite session
        for record in records:
            sqlite_session.expunge(record)

        # Insert into PostgreSQL (batch insert)
        batch_size = 1000
        migrated = 0

        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]

            for record in batch:
                # Create new instance for PostgreSQL
                # This avoids issues with attached sessions
                record_dict = {
                    c.name: getattr(record, c.name)
                    for c in model_class.__table__.columns
                    if c.name != 'id'  # Let PostgreSQL generate new IDs
                }

                new_record = model_class(**record_dict)
                postgres_session.add(new_record)

            postgres_session.commit()
            migrated += len(batch)
            logger.info(f"  Migrated {migrated}/{source_count} records")

        # Verify migration
        final_count = postgres_session.query(model_class).count()
        logger.info(f"  Final count in PostgreSQL: {final_count}")

        if final_count != source_count:
            logger.warning(f"  Record count mismatch! Expected {source_count}, got {final_count}")

        return migrated

    except Exception as e:
        logger.error(f"  Error migrating {table_name}: {e}")
        postgres_session.rollback()
        raise


def run_migration(sqlite_path: str = None, dry_run: bool = False):
    """
    Run the full migration from SQLite to PostgreSQL.

    Args:
        sqlite_path: Optional path to SQLite database file
        dry_run: If True, only show what would be migrated
    """
    logger.info("=" * 60)
    logger.info("SQLite to PostgreSQL Migration")
    logger.info("=" * 60)

    # Validate PostgreSQL connection
    try:
        pg_url = get_postgresql_url()
    except ValueError as e:
        logger.error(f"PostgreSQL configuration error: {e}")
        logger.error("Please set POSTGRES_PASSWORD in your .env file")
        return False

    # Create engines
    sqlite_engine = get_sqlite_engine(sqlite_path)
    postgres_engine = get_postgres_engine()

    # Create sessions
    SQLiteSession = sessionmaker(bind=sqlite_engine)
    PostgresSession = sessionmaker(bind=postgres_engine)

    sqlite_session = SQLiteSession()
    postgres_session = PostgresSession()

    try:
        # Test connections
        logger.info("Testing connections...")

        sqlite_session.execute(text("SELECT 1"))
        logger.info("  SQLite: OK")

        postgres_session.execute(text("SELECT 1"))
        logger.info("  PostgreSQL: OK")

        # Create tables in PostgreSQL
        logger.info("Creating tables in PostgreSQL...")
        Base.metadata.create_all(postgres_engine)
        logger.info("  Tables created")

        if dry_run:
            logger.info("\n[DRY RUN] Would migrate the following tables:")
            for table_name, model_class in TABLES_TO_MIGRATE:
                count = sqlite_session.query(model_class).count()
                logger.info(f"  {table_name}: {count} records")
            return True

        # Migrate each table
        logger.info("\nMigrating tables...")
        total_migrated = 0

        for table_name, model_class in TABLES_TO_MIGRATE:
            count = migrate_table(sqlite_session, postgres_session, table_name, model_class)
            total_migrated += count

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("Migration Complete!")
        logger.info(f"Total records migrated: {total_migrated}")
        logger.info("=" * 60)

        # Update system state to mark migration
        try:
            migration_record = SystemState(
                key='migration_from_sqlite',
                value=datetime.now(timezone.utc).isoformat(),
                value_type='datetime',
            )
            postgres_session.merge(migration_record)
            postgres_session.commit()
            logger.info("Migration timestamp recorded in system_state")
        except Exception as e:
            logger.warning(f"Could not record migration timestamp: {e}")

        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

    finally:
        sqlite_session.close()
        postgres_session.close()


def main():
    parser = argparse.ArgumentParser(
        description='Migrate Jutsu database from SQLite to PostgreSQL'
    )
    parser.add_argument(
        '--sqlite-path',
        type=str,
        help='Path to SQLite database file (default: auto-detect from config)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without actually migrating'
    )

    args = parser.parse_args()

    # Load environment
    from dotenv import load_dotenv
    load_dotenv()

    success = run_migration(
        sqlite_path=args.sqlite_path,
        dry_run=args.dry_run,
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
