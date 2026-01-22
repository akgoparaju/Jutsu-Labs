"""add_strategy_id_to_positions

Revision ID: 20260122_0001
Revises: 20260120_0001
Create Date: 2026-01-22 00:01:00.000000+00:00

This migration:
1. Adds strategy_id column to positions table
2. Creates index for efficient strategy filtering
3. Updates unique constraint to include strategy_id
4. Backfills existing data with 'v3_5b' as default strategy

Part of Multi-Strategy Scheduler Phase 2 implementation.
Supports both SQLite (development) and PostgreSQL (production).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "20260122_0001"
down_revision = "20260120_0001"  # References strategy_id columns migration
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
    Add strategy_id column to positions table.

    Safely checks for existing columns to be idempotent.
    Backfills existing data with 'v3_5b' as the default strategy.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ========================================================================
    # positions table
    # ========================================================================
    if _table_exists(inspector, 'positions'):
        # Add strategy_id column if it doesn't exist
        if not _column_exists(inspector, 'positions', 'strategy_id'):
            op.add_column(
                'positions',
                sa.Column('strategy_id', sa.String(50), nullable=True, server_default='v3_5b')
            )
            print("Added strategy_id column to positions")

            # Backfill existing rows with 'v3_5b'
            op.execute("UPDATE positions SET strategy_id = 'v3_5b' WHERE strategy_id IS NULL")
            print("Backfilled existing positions rows with strategy_id='v3_5b'")
        else:
            print("Column strategy_id already exists in positions")

        # Add index for strategy filtering if it doesn't exist
        if not _index_exists(inspector, 'positions', 'idx_positions_strategy'):
            op.create_index(
                'idx_positions_strategy',
                'positions',
                ['strategy_id'],
                unique=False
            )
            print("Created index idx_positions_strategy")
        else:
            print("Index idx_positions_strategy already exists")

        # Update unique constraint to include strategy_id
        # Note: SQLite doesn't support ALTER CONSTRAINT, so we handle this carefully
        try:
            if not _constraint_exists(inspector, 'positions', 'uix_position_symbol_mode_strategy'):
                # For PostgreSQL: Try to drop old constraint and add new one
                try:
                    if _constraint_exists(inspector, 'positions', 'uix_position_symbol_mode'):
                        op.drop_constraint('uix_position_symbol_mode', 'positions', type_='unique')
                        print("Dropped old unique constraint uix_position_symbol_mode")
                except Exception as e:
                    print(f"Could not drop old constraint (may not exist or SQLite limitation): {e}")

                # Create new constraint with strategy_id
                op.create_unique_constraint(
                    'uix_position_symbol_mode_strategy',
                    'positions',
                    ['symbol', 'mode', 'strategy_id']
                )
                print("Created new unique constraint uix_position_symbol_mode_strategy")
            else:
                print("Constraint uix_position_symbol_mode_strategy already exists")
        except Exception as e:
            print(f"Unique constraint update skipped (SQLite limitation is expected): {e}")
    else:
        print("Table positions does not exist, skipping")


def downgrade() -> None:
    """
    Remove strategy_id column from positions table.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ========================================================================
    # positions table
    # ========================================================================
    if _table_exists(inspector, 'positions'):
        # Drop new unique constraint first
        try:
            if _constraint_exists(inspector, 'positions', 'uix_position_symbol_mode_strategy'):
                op.drop_constraint('uix_position_symbol_mode_strategy', 'positions', type_='unique')
                print("Dropped unique constraint uix_position_symbol_mode_strategy")
        except Exception as e:
            print(f"Could not drop constraint (SQLite limitation is expected): {e}")

        # Recreate old unique constraint
        try:
            if not _constraint_exists(inspector, 'positions', 'uix_position_symbol_mode'):
                op.create_unique_constraint(
                    'uix_position_symbol_mode',
                    'positions',
                    ['symbol', 'mode']
                )
                print("Recreated old unique constraint uix_position_symbol_mode")
        except Exception as e:
            print(f"Could not recreate old constraint (SQLite limitation is expected): {e}")

        # Drop index
        if _index_exists(inspector, 'positions', 'idx_positions_strategy'):
            op.drop_index('idx_positions_strategy', 'positions')
            print("Dropped index idx_positions_strategy")

        # Drop column
        if _column_exists(inspector, 'positions', 'strategy_id'):
            op.drop_column('positions', 'strategy_id')
            print("Removed strategy_id column from positions")
