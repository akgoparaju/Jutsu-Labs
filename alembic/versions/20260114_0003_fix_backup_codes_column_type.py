"""fix_backup_codes_column_type

Revision ID: d9f2a3456789
Revises: 20260114_0002_add_indicator_columns
Create Date: 2026-01-14 12:00:00.000000+00:00

This migration fixes the backup_codes column type mismatch that was causing
2FA verification to fail for all users.

Root Cause:
- The original migration (2025-12-09) created backup_codes as TEXT[] (PostgreSQL array)
- The SQLAlchemy model defines it as Column(JSON), expecting JSONB type
- This type mismatch caused db.commit() to fail during 2FA verification when
  saving the backup codes list

Fix:
- Convert backup_codes from TEXT[] to JSONB type in PostgreSQL
- SQLite already uses TEXT which is compatible with JSON, no change needed

Supports both SQLite (development) and PostgreSQL (production).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "d9f2a3456789"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    """Check if a column exists in a table."""
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _table_exists(inspector, table_name):
    """Check if a table exists."""
    return table_name in inspector.get_table_names()


def _get_column_type(inspector, table_name, column_name):
    """Get the type of a column."""
    columns = inspector.get_columns(table_name)
    for col in columns:
        if col['name'] == column_name:
            return str(col['type'])
    return None


def upgrade() -> None:
    """
    Fix backup_codes column type from TEXT[] to JSONB in PostgreSQL.

    For SQLite, no changes are needed as TEXT is compatible with JSON.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not _table_exists(inspector, 'users'):
        return

    if not _column_exists(inspector, 'users', 'backup_codes'):
        # Column doesn't exist, create it with correct type
        if dialect == 'postgresql':
            op.add_column('users', sa.Column(
                'backup_codes',
                sa.JSON(),
                nullable=True
            ))
        else:
            # SQLite - use TEXT (JSON compatible)
            op.add_column('users', sa.Column(
                'backup_codes',
                sa.Text(),
                nullable=True
            ))
        return

    # Column exists - check if we need to fix the type
    if dialect == 'postgresql':
        col_type = _get_column_type(inspector, 'users', 'backup_codes')
        
        # Check if it's an ARRAY type (TEXT[]) which needs fixing
        # Column types from inspector may show as 'ARRAY' or 'TEXT[]' or similar
        if col_type and ('ARRAY' in col_type.upper() or '[]' in col_type):
            # Convert TEXT[] to JSONB with data preservation
            # Using raw SQL for the type conversion with proper array-to-json handling
            op.execute("""
                ALTER TABLE users 
                ALTER COLUMN backup_codes 
                TYPE JSONB 
                USING CASE 
                    WHEN backup_codes IS NULL THEN NULL 
                    ELSE to_jsonb(backup_codes)
                END
            """)
        elif col_type and 'JSONB' not in col_type.upper() and 'JSON' not in col_type.upper():
            # Some other incompatible type, try to convert
            op.execute("""
                ALTER TABLE users 
                ALTER COLUMN backup_codes 
                TYPE JSONB 
                USING CASE 
                    WHEN backup_codes IS NULL THEN NULL 
                    WHEN backup_codes::text = '' THEN NULL
                    ELSE backup_codes::jsonb
                END
            """)
    # For SQLite, TEXT type is compatible with JSON operations, no change needed


def downgrade() -> None:
    """
    Revert backup_codes column type from JSONB to TEXT[] in PostgreSQL.

    WARNING: This will revert to the broken state. Only use for testing.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not _table_exists(inspector, 'users'):
        return

    if not _column_exists(inspector, 'users', 'backup_codes'):
        return

    if dialect == 'postgresql':
        # Convert JSONB back to TEXT[] (not recommended for production)
        op.execute("""
            ALTER TABLE users 
            ALTER COLUMN backup_codes 
            TYPE TEXT[] 
            USING CASE 
                WHEN backup_codes IS NULL THEN NULL 
                ELSE ARRAY(SELECT jsonb_array_elements_text(backup_codes))
            END
        """)
    # For SQLite, no change needed
