"""create_passkeys_table

Revision ID: b7b84bccdb08
Revises:
Create Date: 2025-12-16 00:11:02.279389+00:00

This migration:
1. Adds missing security columns to users table (lockout, 2FA, backup codes)
2. Creates passkeys table for WebAuthn authentication

Supports both SQLite (development) and PostgreSQL (production).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = "b7b84bccdb08"
down_revision = None
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
    Add security columns to users table and create passkeys table.

    Safely checks for existing columns/tables to be idempotent.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # ==========================================================================
    # STEP 1: Add missing columns to users table
    # ==========================================================================

    if _table_exists(inspector, 'users'):
        # Add failed_login_count for brute force protection
        if not _column_exists(inspector, 'users', 'failed_login_count'):
            op.add_column('users', sa.Column(
                'failed_login_count',
                sa.Integer(),
                nullable=True,
                server_default='0'
            ))

        # Add locked_until for account lockout
        if not _column_exists(inspector, 'users', 'locked_until'):
            op.add_column('users', sa.Column(
                'locked_until',
                sa.DateTime(timezone=True),
                nullable=True
            ))

        # Add totp_secret for 2FA
        if not _column_exists(inspector, 'users', 'totp_secret'):
            op.add_column('users', sa.Column(
                'totp_secret',
                sa.String(32),
                nullable=True
            ))

        # Add totp_enabled for 2FA
        if not _column_exists(inspector, 'users', 'totp_enabled'):
            op.add_column('users', sa.Column(
                'totp_enabled',
                sa.Boolean(),
                nullable=True,
                server_default='0'
            ))

        # Add backup_codes - dialect-specific
        if not _column_exists(inspector, 'users', 'backup_codes'):
            if dialect == 'postgresql':
                # PostgreSQL: Use native ARRAY type
                op.add_column('users', sa.Column(
                    'backup_codes',
                    postgresql.ARRAY(sa.String()),
                    nullable=True
                ))
            else:
                # SQLite: Use TEXT (JSON serialized)
                op.add_column('users', sa.Column(
                    'backup_codes',
                    sa.Text(),
                    nullable=True
                ))

    # ==========================================================================
    # STEP 2: Create passkeys table for WebAuthn authentication
    # ==========================================================================

    if not _table_exists(inspector, 'passkeys'):
        op.create_table(
            'passkeys',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('credential_id', sa.LargeBinary(), nullable=False),
            sa.Column('public_key', sa.LargeBinary(), nullable=False),
            sa.Column('sign_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('device_name', sa.String(length=100), nullable=True),
            sa.Column('aaguid', sa.String(length=36), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        # Create indexes for fast lookups
        op.create_index('ix_passkeys_user_id', 'passkeys', ['user_id'])
        op.create_index('ix_passkeys_credential_id', 'passkeys', ['credential_id'], unique=True)


def downgrade() -> None:
    """
    Remove passkeys table and security columns from users.

    WARNING: This will delete all passkeys and 2FA settings!
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ==========================================================================
    # STEP 1: Drop passkeys table
    # ==========================================================================

    if _table_exists(inspector, 'passkeys'):
        op.drop_index('ix_passkeys_credential_id', table_name='passkeys')
        op.drop_index('ix_passkeys_user_id', table_name='passkeys')
        op.drop_table('passkeys')

    # ==========================================================================
    # STEP 2: Remove security columns from users table
    # ==========================================================================

    if _table_exists(inspector, 'users'):
        if _column_exists(inspector, 'users', 'backup_codes'):
            op.drop_column('users', 'backup_codes')
        if _column_exists(inspector, 'users', 'totp_enabled'):
            op.drop_column('users', 'totp_enabled')
        if _column_exists(inspector, 'users', 'totp_secret'):
            op.drop_column('users', 'totp_secret')
        if _column_exists(inspector, 'users', 'locked_until'):
            op.drop_column('users', 'locked_until')
        if _column_exists(inspector, 'users', 'failed_login_count'):
            op.drop_column('users', 'failed_login_count')
