"""add_user_roles_and_invitations

Revision ID: c8e9f1234567
Revises: b7b84bccdb08
Create Date: 2026-01-13 00:01:00.000000+00:00

This migration:
1. Replaces is_admin boolean column with role string column
2. Creates user_invitations table for invitation-based onboarding

Supports both SQLite (development) and PostgreSQL (production).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "c8e9f1234567"
down_revision = "b7b84bccdb08"
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
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    """
    Add role column to users table and create user_invitations table.

    Safely checks for existing columns/tables to be idempotent.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # ==========================================================================
    # STEP 1: Add role column to users table and migrate is_admin data
    # ==========================================================================

    if _table_exists(inspector, 'users'):
        # Add role column if it doesn't exist
        if not _column_exists(inspector, 'users', 'role'):
            op.add_column('users', sa.Column(
                'role',
                sa.String(20),
                nullable=False,
                server_default='viewer'
            ))
        # Create index for role column if it doesn't exist
        if not _index_exists(inspector, 'users', 'ix_users_role'):
            op.create_index('ix_users_role', 'users', ['role'])

        # Migrate is_admin data to role column
        # First check if is_admin column exists
        if _column_exists(inspector, 'users', 'is_admin'):
            # Update role based on is_admin value
            # Use dialect-specific SQL for boolean comparison
            if dialect == 'postgresql':
                op.execute("""
                    UPDATE users
                    SET role = CASE
                        WHEN is_admin = true THEN 'admin'
                        ELSE 'viewer'
                    END
                """)
            else:
                # SQLite uses 0/1 for boolean
                op.execute("""
                    UPDATE users
                    SET role = CASE
                        WHEN is_admin = 1 THEN 'admin'
                        ELSE 'viewer'
                    END
                """)
            # Drop is_admin column after migration
            op.drop_column('users', 'is_admin')

    # ==========================================================================
    # STEP 2: Create user_invitations table
    # ==========================================================================

    if not _table_exists(inspector, 'user_invitations'):
        op.create_table(
            'user_invitations',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('token', sa.String(length=64), nullable=False),
            sa.Column('role', sa.String(length=20), nullable=False, server_default='viewer'),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('accepted_by', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['accepted_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )
        # Create indexes for fast lookups
        op.create_index('ix_user_invitations_token', 'user_invitations', ['token'], unique=True)
        op.create_index('ix_user_invitations_email', 'user_invitations', ['email'])


def downgrade() -> None:
    """
    Remove user_invitations table and revert role column to is_admin.

    WARNING: This will delete all invitations and may lose role granularity!
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ==========================================================================
    # STEP 1: Drop user_invitations table
    # ==========================================================================

    if _table_exists(inspector, 'user_invitations'):
        op.drop_index('ix_user_invitations_email', table_name='user_invitations')
        op.drop_index('ix_user_invitations_token', table_name='user_invitations')
        op.drop_table('user_invitations')

    # ==========================================================================
    # STEP 2: Revert role column to is_admin in users table
    # ==========================================================================

    if _table_exists(inspector, 'users'):
        # Add is_admin column back
        if not _column_exists(inspector, 'users', 'is_admin'):
            op.add_column('users', sa.Column(
                'is_admin',
                sa.Boolean(),
                nullable=False,
                server_default='0'
            ))

        # Migrate role data back to is_admin
        if _column_exists(inspector, 'users', 'role'):
            op.execute("""
                UPDATE users
                SET is_admin = CASE
                    WHEN role = 'admin' THEN 1
                    ELSE 0
                END
            """)
            # Drop role column and its index
            op.drop_index('ix_users_role', table_name='users')
            op.drop_column('users', 'role')
