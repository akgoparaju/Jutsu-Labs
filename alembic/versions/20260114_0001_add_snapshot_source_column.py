"""add_snapshot_source_column

Revision ID: d1a2b3c4d5e6
Revises: c8e9f1234567
Create Date: 2026-01-14 00:01:00.000000+00:00

This migration:
1. Adds snapshot_source column to performance_snapshots table
2. This column tracks whether a snapshot came from:
   - "scheduler" (authoritative for regime data)
   - "refresh" (P/L updates only)
   - "backtest" (historical analysis)
   - "manual" (user-triggered)

Architecture decision 2026-01-14: Scheduler is authoritative for regime fields.

Supports both SQLite (development) and PostgreSQL (production).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "d1a2b3c4d5e6"
down_revision = "c8e9f1234567"
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
    Add snapshot_source column to performance_snapshots table.
    
    Safely checks for existing column to be idempotent.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Check if performance_snapshots table exists
    if not _table_exists(inspector, 'performance_snapshots'):
        print("Table performance_snapshots does not exist, skipping migration")
        return
    
    # Add snapshot_source column if it doesn't exist
    if not _column_exists(inspector, 'performance_snapshots', 'snapshot_source'):
        op.add_column(
            'performance_snapshots',
            sa.Column('snapshot_source', sa.String(20), nullable=True)
        )
        print("Added snapshot_source column to performance_snapshots")
    else:
        print("Column snapshot_source already exists in performance_snapshots")


def downgrade() -> None:
    """
    Remove snapshot_source column from performance_snapshots table.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if _table_exists(inspector, 'performance_snapshots'):
        if _column_exists(inspector, 'performance_snapshots', 'snapshot_source'):
            op.drop_column('performance_snapshots', 'snapshot_source')
            print("Removed snapshot_source column from performance_snapshots")
