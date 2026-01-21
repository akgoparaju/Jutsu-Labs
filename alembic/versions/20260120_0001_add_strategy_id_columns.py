"""add_strategy_id_columns

Revision ID: f1a2b3c4d5e7
Revises: e3f4g5h6i7j8
Create Date: 2026-01-20 00:01:00.000000+00:00

This migration:
1. Adds strategy_id column to performance_snapshots table
2. Adds strategy_id column to live_trades table
3. Creates indexes for efficient strategy filtering
4. Backfills existing data with 'v3_5b' as default strategy

Part of Multi-Strategy Engine implementation.
Supports both SQLite (development) and PostgreSQL (production).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "20260120_0001"
down_revision = "20260117_0001"  # References TOTP encryption migration
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    """Check if a column exists in a table."""
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _table_exists(inspector, table_name):
    """Check if a table exists."""
    return table_name in inspector.get_table_names()


def _index_exists(inspector, table_name, index_name):
    """Check if an index exists on a table."""
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def _constraint_exists(inspector, table_name, constraint_name):
    """Check if a unique constraint exists on a table."""
    constraints = inspector.get_unique_constraints(table_name)
    return any(c['name'] == constraint_name for c in constraints)


def upgrade() -> None:
    """
    Add strategy_id column to performance_snapshots and live_trades tables.

    Safely checks for existing columns to be idempotent.
    Backfills existing data with 'v3_5b' as the default strategy.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ========================================================================
    # performance_snapshots table
    # ========================================================================
    if _table_exists(inspector, 'performance_snapshots'):
        # Add strategy_id column if it doesn't exist
        if not _column_exists(inspector, 'performance_snapshots', 'strategy_id'):
            op.add_column(
                'performance_snapshots',
                sa.Column('strategy_id', sa.String(50), nullable=True, server_default='v3_5b')
            )
            print("Added strategy_id column to performance_snapshots")

            # Backfill existing rows with 'v3_5b'
            op.execute("UPDATE performance_snapshots SET strategy_id = 'v3_5b' WHERE strategy_id IS NULL")
            print("Backfilled existing performance_snapshots rows with strategy_id='v3_5b'")
        else:
            print("Column strategy_id already exists in performance_snapshots")

        # Add index for strategy filtering if it doesn't exist
        if not _index_exists(inspector, 'performance_snapshots', 'idx_perf_snapshots_strategy'):
            op.create_index(
                'idx_perf_snapshots_strategy',
                'performance_snapshots',
                ['strategy_id', 'timestamp'],
                unique=False
            )
            print("Created index idx_perf_snapshots_strategy")
        else:
            print("Index idx_perf_snapshots_strategy already exists")

        # Update unique constraint to include strategy_id (allows multiple strategies per timestamp)
        # Note: SQLite doesn't support ALTER CONSTRAINT, so we handle this carefully
        # For new installations, the model has the updated constraint
        # For existing installations, we'll create a new constraint
        try:
            if not _constraint_exists(inspector, 'performance_snapshots', 'uix_perf_snapshot_mode_strategy_ts'):
                # Try to drop old constraint if it exists (may fail on SQLite)
                try:
                    if _constraint_exists(inspector, 'performance_snapshots', 'uix_perf_snapshot_mode_ts'):
                        op.drop_constraint('uix_perf_snapshot_mode_ts', 'performance_snapshots', type_='unique')
                        print("Dropped old unique constraint uix_perf_snapshot_mode_ts")
                except Exception as e:
                    print(f"Could not drop old constraint (may not exist or SQLite limitation): {e}")

                # Create new constraint with strategy_id
                op.create_unique_constraint(
                    'uix_perf_snapshot_mode_strategy_ts',
                    'performance_snapshots',
                    ['mode', 'strategy_id', 'timestamp']
                )
                print("Created new unique constraint uix_perf_snapshot_mode_strategy_ts")
            else:
                print("Constraint uix_perf_snapshot_mode_strategy_ts already exists")
        except Exception as e:
            print(f"Unique constraint update skipped (SQLite limitation is expected): {e}")
    else:
        print("Table performance_snapshots does not exist, skipping")

    # ========================================================================
    # live_trades table
    # ========================================================================
    if _table_exists(inspector, 'live_trades'):
        # Add strategy_id column if it doesn't exist
        if not _column_exists(inspector, 'live_trades', 'strategy_id'):
            op.add_column(
                'live_trades',
                sa.Column('strategy_id', sa.String(50), nullable=True, server_default='v3_5b')
            )
            print("Added strategy_id column to live_trades")

            # Backfill existing rows with 'v3_5b'
            op.execute("UPDATE live_trades SET strategy_id = 'v3_5b' WHERE strategy_id IS NULL")
            print("Backfilled existing live_trades rows with strategy_id='v3_5b'")
        else:
            print("Column strategy_id already exists in live_trades")

        # Add index for strategy filtering if it doesn't exist
        if not _index_exists(inspector, 'live_trades', 'idx_live_trades_strategy'):
            op.create_index(
                'idx_live_trades_strategy',
                'live_trades',
                ['strategy_id', 'timestamp'],
                unique=False
            )
            print("Created index idx_live_trades_strategy")
        else:
            print("Index idx_live_trades_strategy already exists")
    else:
        print("Table live_trades does not exist, skipping")


def downgrade() -> None:
    """
    Remove strategy_id columns from performance_snapshots and live_trades tables.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ========================================================================
    # live_trades table
    # ========================================================================
    if _table_exists(inspector, 'live_trades'):
        # Drop index first
        if _index_exists(inspector, 'live_trades', 'idx_live_trades_strategy'):
            op.drop_index('idx_live_trades_strategy', 'live_trades')
            print("Dropped index idx_live_trades_strategy")

        # Drop column
        if _column_exists(inspector, 'live_trades', 'strategy_id'):
            op.drop_column('live_trades', 'strategy_id')
            print("Removed strategy_id column from live_trades")

    # ========================================================================
    # performance_snapshots table
    # ========================================================================
    if _table_exists(inspector, 'performance_snapshots'):
        # Drop index first
        if _index_exists(inspector, 'performance_snapshots', 'idx_perf_snapshots_strategy'):
            op.drop_index('idx_perf_snapshots_strategy', 'performance_snapshots')
            print("Dropped index idx_perf_snapshots_strategy")

        # Drop column
        if _column_exists(inspector, 'performance_snapshots', 'strategy_id'):
            op.drop_column('performance_snapshots', 'strategy_id')
            print("Removed strategy_id column from performance_snapshots")
