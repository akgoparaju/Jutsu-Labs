#!/usr/bin/env python3
"""
Add strategy_id columns to performance_snapshots and live_trades tables.
Part of Multi-Strategy Engine implementation.

Supports both PostgreSQL and SQLite databases.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text, inspect
from jutsu_engine.utils.config import get_database_url, get_safe_database_url_for_logging, is_postgresql


def column_exists(inspector, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    try:
        columns = inspector.get_columns(table_name)
        return any(col['name'] == column_name for col in columns)
    except Exception:
        return False


def index_exists(inspector, table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    try:
        indexes = inspector.get_indexes(table_name)
        return any(idx['name'] == index_name for idx in indexes)
    except Exception:
        return False


def main():
    url = get_database_url()
    print(f"Connecting to database: {get_safe_database_url_for_logging(url)}")
    print(f"Database type: {'PostgreSQL' if is_postgresql() else 'SQLite'}")

    # Configure engine based on database type
    connect_args = {}
    if is_postgresql():
        connect_args = {'connect_timeout': 30}
    else:
        connect_args = {'check_same_thread': False}

    engine = create_engine(url, connect_args=connect_args)
    inspector = inspect(engine)

    with engine.connect() as conn:
        # Add strategy_id to performance_snapshots
        print("\n--- Processing performance_snapshots ---")
        if not column_exists(inspector, 'performance_snapshots', 'strategy_id'):
            print("Adding strategy_id column...")
            if is_postgresql():
                conn.execute(text("ALTER TABLE performance_snapshots ADD COLUMN strategy_id VARCHAR(50) DEFAULT 'v3_5b'"))
            else:
                conn.execute(text("ALTER TABLE performance_snapshots ADD COLUMN strategy_id TEXT DEFAULT 'v3_5b'"))
            conn.execute(text("UPDATE performance_snapshots SET strategy_id = 'v3_5b' WHERE strategy_id IS NULL"))
            print("Column added.")
        else:
            print("Column already exists, skipping.")

        # Create index if not exists
        if not index_exists(inspector, 'performance_snapshots', 'idx_perf_snapshots_strategy'):
            print("Creating index idx_perf_snapshots_strategy...")
            conn.execute(text("CREATE INDEX idx_perf_snapshots_strategy ON performance_snapshots(strategy_id, timestamp)"))
            print("Index created.")
        else:
            print("Index already exists, skipping.")

        # Add strategy_id to live_trades
        print("\n--- Processing live_trades ---")
        if not column_exists(inspector, 'live_trades', 'strategy_id'):
            print("Adding strategy_id column...")
            if is_postgresql():
                conn.execute(text("ALTER TABLE live_trades ADD COLUMN strategy_id VARCHAR(50) DEFAULT 'v3_5b'"))
            else:
                conn.execute(text("ALTER TABLE live_trades ADD COLUMN strategy_id TEXT DEFAULT 'v3_5b'"))
            conn.execute(text("UPDATE live_trades SET strategy_id = 'v3_5b' WHERE strategy_id IS NULL"))
            print("Column added.")
        else:
            print("Column already exists, skipping.")

        # Create index if not exists
        if not index_exists(inspector, 'live_trades', 'idx_live_trades_strategy'):
            print("Creating index idx_live_trades_strategy...")
            conn.execute(text("CREATE INDEX idx_live_trades_strategy ON live_trades(strategy_id, timestamp)"))
            print("Index created.")
        else:
            print("Index already exists, skipping.")

        conn.commit()
        print("\n✓ Migration complete!")

    # Verify
    print("\n--- Verification ---")
    inspector = inspect(engine)

    perf_exists = column_exists(inspector, 'performance_snapshots', 'strategy_id')
    print(f"strategy_id in performance_snapshots: {'✓ EXISTS' if perf_exists else '✗ NOT FOUND'}")

    trades_exists = column_exists(inspector, 'live_trades', 'strategy_id')
    print(f"strategy_id in live_trades: {'✓ EXISTS' if trades_exists else '✗ NOT FOUND'}")

    if perf_exists and trades_exists:
        print("\n✓ All migrations applied successfully!")
        return 0
    else:
        print("\n✗ Some migrations failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
