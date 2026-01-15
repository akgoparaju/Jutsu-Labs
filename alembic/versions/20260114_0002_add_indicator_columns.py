"""add_indicator_columns_to_performance_snapshots

Revision ID: e2f3a4b5c6d7
Revises: d1a2b3c4d5e6
Create Date: 2026-01-14 23:45:00.000000+00:00

This migration:
1. Adds t_norm, z_score, sma_fast, sma_slow columns to performance_snapshots table
2. These columns store indicator values at snapshot time
3. Scheduler snapshots will populate these; refresh snapshots leave them NULL

Architecture decision 2026-01-14: Scheduler is authoritative for ALL indicator data.
Decision Tree UI should display indicators from scheduler snapshot, not live context.

Supports both SQLite (development) and PostgreSQL (production).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "e2f3a4b5c6d7"
down_revision = "d1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    """Check if a column exists in a table."""
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _table_exists(inspector, table_name):
    """Check if a table exists."""
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """
    Add indicator columns to performance_snapshots table.
    
    Safely checks for existing columns to be idempotent.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Check if performance_snapshots table exists
    if not _table_exists(inspector, 'performance_snapshots'):
        print("Table performance_snapshots does not exist, skipping migration")
        return
    
    # Add t_norm column if it doesn't exist
    if not _column_exists(inspector, 'performance_snapshots', 't_norm'):
        op.add_column(
            'performance_snapshots',
            sa.Column('t_norm', sa.Numeric(10, 6), nullable=True)
        )
        print("Added t_norm column to performance_snapshots")
    else:
        print("Column t_norm already exists in performance_snapshots")
    
    # Add z_score column if it doesn't exist
    if not _column_exists(inspector, 'performance_snapshots', 'z_score'):
        op.add_column(
            'performance_snapshots',
            sa.Column('z_score', sa.Numeric(10, 6), nullable=True)
        )
        print("Added z_score column to performance_snapshots")
    else:
        print("Column z_score already exists in performance_snapshots")
    
    # Add sma_fast column if it doesn't exist
    if not _column_exists(inspector, 'performance_snapshots', 'sma_fast'):
        op.add_column(
            'performance_snapshots',
            sa.Column('sma_fast', sa.Numeric(18, 6), nullable=True)
        )
        print("Added sma_fast column to performance_snapshots")
    else:
        print("Column sma_fast already exists in performance_snapshots")
    
    # Add sma_slow column if it doesn't exist
    if not _column_exists(inspector, 'performance_snapshots', 'sma_slow'):
        op.add_column(
            'performance_snapshots',
            sa.Column('sma_slow', sa.Numeric(18, 6), nullable=True)
        )
        print("Added sma_slow column to performance_snapshots")
    else:
        print("Column sma_slow already exists in performance_snapshots")


def downgrade() -> None:
    """
    Remove indicator columns from performance_snapshots table.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if _table_exists(inspector, 'performance_snapshots'):
        for column_name in ['t_norm', 'z_score', 'sma_fast', 'sma_slow']:
            if _column_exists(inspector, 'performance_snapshots', column_name):
                op.drop_column('performance_snapshots', column_name)
                print(f"Removed {column_name} column from performance_snapshots")
