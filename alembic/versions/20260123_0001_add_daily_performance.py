"""add_daily_performance_and_eod_job_status

Revision ID: 20260123_0001
Revises: 20260122_0001
Create Date: 2026-01-23 10:00:00.000000+00:00

This migration implements Phase 1 of the EOD Daily Performance architecture:
1. Creates daily_performance table - Single source of truth for end-of-day metrics
2. Creates eod_job_status table - Job execution tracking for recovery and monitoring

Fixes the Sharpe ratio bug (showing -4 instead of ~0.82) by establishing:
- One authoritative row per strategy per trading day
- Pre-computed KPIs calculated at 4:15 PM ET
- Equity-based daily return calculations

Reference: claudedocs/eod_daily_performance_architecture.md v1.1
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "20260123_0001"
down_revision = "20260122_0001"  # References strategy_id to positions migration
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    """Check if a table exists."""
    return table_name in inspector.get_table_names()


def _index_exists(inspector, table_name, index_name):
    """Check if an index exists on a table."""
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def upgrade() -> None:
    """
    Create daily_performance and eod_job_status tables.

    Safely checks for existing tables to be idempotent.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ========================================================================
    # daily_performance table
    # ========================================================================
    if not _table_exists(inspector, 'daily_performance'):
        op.create_table(
            'daily_performance',
            # Primary Key
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),

            # Composite Natural Key
            sa.Column('trading_date', sa.Date(), nullable=False),
            sa.Column('entity_type', sa.String(10), nullable=False),  # 'strategy' or 'baseline'
            sa.Column('entity_id', sa.String(50), nullable=False),    # 'v3_5b', 'QQQ', etc.
            sa.Column('mode', sa.String(20), nullable=False),         # 'offline_mock' or 'online_live'

            # Portfolio State (End of Day)
            sa.Column('total_equity', sa.Numeric(18, 6), nullable=False),
            sa.Column('cash', sa.Numeric(18, 6), nullable=True),
            sa.Column('positions_value', sa.Numeric(18, 6), nullable=True),
            sa.Column('positions_json', sa.Text(), nullable=True),  # JSON: [{symbol, quantity, value, weight}]

            # Daily Metrics (Equity-Based)
            sa.Column('daily_return', sa.Numeric(10, 6), nullable=False),     # (today - yesterday) / yesterday
            sa.Column('cumulative_return', sa.Numeric(10, 6), nullable=False), # (today - initial) / initial
            sa.Column('drawdown', sa.Numeric(10, 6), nullable=True),          # (equity - HWM) / HWM

            # Pre-Computed KPIs (All-Time from Inception)
            sa.Column('sharpe_ratio', sa.Numeric(10, 6), nullable=True),      # Annualized, rf = 0
            sa.Column('sortino_ratio', sa.Numeric(10, 6), nullable=True),     # Downside deviation based
            sa.Column('calmar_ratio', sa.Numeric(10, 6), nullable=True),      # CAGR / Max Drawdown
            sa.Column('max_drawdown', sa.Numeric(10, 6), nullable=True),      # Maximum peak-to-trough
            sa.Column('volatility', sa.Numeric(10, 6), nullable=True),        # Annualized std dev
            sa.Column('cagr', sa.Numeric(10, 6), nullable=True),              # Compound Annual Growth Rate

            # Strategy State (Strategies Only)
            sa.Column('strategy_cell', sa.Integer(), nullable=True),          # Current regime cell (1-6)
            sa.Column('trend_state', sa.String(20), nullable=True),           # BullStrong, Sideways, etc.
            sa.Column('vol_state', sa.String(10), nullable=True),             # Low, High

            # Indicator Values (Strategies Only)
            sa.Column('t_norm', sa.Numeric(10, 6), nullable=True),
            sa.Column('z_score', sa.Numeric(10, 6), nullable=True),
            sa.Column('sma_fast', sa.Numeric(18, 6), nullable=True),
            sa.Column('sma_slow', sa.Numeric(18, 6), nullable=True),

            # Trade Statistics (Strategies Only)
            sa.Column('total_trades', sa.Integer(), default=0, nullable=True),
            sa.Column('winning_trades', sa.Integer(), default=0, nullable=True),
            sa.Column('losing_trades', sa.Integer(), default=0, nullable=True),
            sa.Column('win_rate', sa.Numeric(5, 2), nullable=True),  # winning_trades / total_trades * 100

            # Baseline Reference (Strategies Only)
            sa.Column('baseline_symbol', sa.String(20), nullable=True),  # 'QQQ'

            # Metadata
            sa.Column('initial_capital', sa.Numeric(18, 6), nullable=True),
            sa.Column('high_water_mark', sa.Numeric(18, 6), nullable=True),
            sa.Column('trading_days_count', sa.Integer(), nullable=True),

            # Corner Case Handling (v1.1)
            sa.Column('days_since_previous', sa.Integer(), default=1, nullable=True),
            sa.Column('is_first_day', sa.Boolean(), default=False, nullable=True),

            # Incremental KPI State for O(1) updates (v1.1 - Welford's algorithm)
            sa.Column('returns_sum', sa.Numeric(18, 8), nullable=True),
            sa.Column('returns_sum_sq', sa.Numeric(18, 8), nullable=True),
            sa.Column('downside_sum_sq', sa.Numeric(18, 8), nullable=True),
            sa.Column('returns_count', sa.Integer(), nullable=True),

            sa.Column('finalized_at', sa.DateTime(timezone=True), server_default=sa.func.now()),

            # Check constraint for entity_type
            sa.CheckConstraint(
                "entity_type IN ('strategy', 'baseline')",
                name='ck_daily_perf_entity_type'
            ),
        )
        print("Created daily_performance table")

        # Add unique constraint
        op.create_unique_constraint(
            'uix_daily_perf',
            'daily_performance',
            ['trading_date', 'entity_type', 'entity_id', 'mode']
        )
        print("Created unique constraint uix_daily_perf")

        # Create indexes
        op.create_index(
            'idx_daily_perf_date',
            'daily_performance',
            [sa.text('trading_date DESC')],
            unique=False
        )
        print("Created index idx_daily_perf_date")

        op.create_index(
            'idx_daily_perf_entity',
            'daily_performance',
            ['entity_type', 'entity_id'],
            unique=False
        )
        print("Created index idx_daily_perf_entity")

        op.create_index(
            'idx_daily_perf_mode_entity',
            'daily_performance',
            ['mode', 'entity_type', 'entity_id', sa.text('trading_date DESC')],
            unique=False
        )
        print("Created index idx_daily_perf_mode_entity")

        # Partial index for strategies only
        op.create_index(
            'idx_daily_perf_strategy_date',
            'daily_performance',
            ['entity_id', sa.text('trading_date DESC')],
            unique=False,
            postgresql_where=sa.text("entity_type = 'strategy'")
        )
        print("Created partial index idx_daily_perf_strategy_date")

        # Add table comment (PostgreSQL only)
        try:
            op.execute("""
                COMMENT ON TABLE daily_performance IS
                'Authoritative end-of-day performance metrics. One row per strategy/baseline per trading day.';
            """)
            op.execute("""
                COMMENT ON COLUMN daily_performance.daily_return IS
                'Daily return as decimal (0.01 = 1%), calculated from equity change';
            """)
            op.execute("""
                COMMENT ON COLUMN daily_performance.sharpe_ratio IS
                'All-time annualized Sharpe ratio, risk-free rate = 0';
            """)
            op.execute("""
                COMMENT ON COLUMN daily_performance.days_since_previous IS
                'Calendar days since previous trading record (1 = consecutive, >1 = gap)';
            """)
            op.execute("""
                COMMENT ON COLUMN daily_performance.is_first_day IS
                'True if this is the first trading day for this entity';
            """)
            op.execute("""
                COMMENT ON COLUMN daily_performance.returns_sum IS
                'Running sum of daily returns for incremental KPI calculation';
            """)
            print("Added table and column comments")
        except Exception as e:
            print(f"Comments skipped (SQLite limitation): {e}")
    else:
        print("Table daily_performance already exists")

    # ========================================================================
    # eod_job_status table
    # ========================================================================
    if not _table_exists(inspector, 'eod_job_status'):
        op.create_table(
            'eod_job_status',
            sa.Column('job_date', sa.Date(), primary_key=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('status', sa.String(20), nullable=False),  # running, completed, failed, partial
            sa.Column('strategies_total', sa.Integer(), nullable=True),
            sa.Column('strategies_processed', sa.Integer(), default=0, nullable=True),
            sa.Column('baselines_total', sa.Integer(), nullable=True),
            sa.Column('baselines_processed', sa.Integer(), default=0, nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('retry_count', sa.Integer(), default=0, nullable=True),

            # Check constraint for status
            sa.CheckConstraint(
                "status IN ('running', 'completed', 'failed', 'partial')",
                name='ck_eod_job_status'
            ),
        )
        print("Created eod_job_status table")

        # Create index for job status lookups
        op.create_index(
            'idx_eod_job_status',
            'eod_job_status',
            ['status', sa.text('job_date DESC')],
            unique=False
        )
        print("Created index idx_eod_job_status")

        # Add table comment (PostgreSQL only)
        try:
            op.execute("""
                COMMENT ON TABLE eod_job_status IS
                'Tracks EOD finalization job execution for recovery and monitoring';
            """)
            print("Added eod_job_status table comment")
        except Exception as e:
            print(f"Comments skipped (SQLite limitation): {e}")
    else:
        print("Table eod_job_status already exists")


def downgrade() -> None:
    """
    Remove daily_performance and eod_job_status tables.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ========================================================================
    # eod_job_status table
    # ========================================================================
    if _table_exists(inspector, 'eod_job_status'):
        # Drop index first
        if _index_exists(inspector, 'eod_job_status', 'idx_eod_job_status'):
            op.drop_index('idx_eod_job_status', 'eod_job_status')
            print("Dropped index idx_eod_job_status")

        op.drop_table('eod_job_status')
        print("Dropped eod_job_status table")

    # ========================================================================
    # daily_performance table
    # ========================================================================
    if _table_exists(inspector, 'daily_performance'):
        # Drop indexes first
        for idx_name in [
            'idx_daily_perf_strategy_date',
            'idx_daily_perf_mode_entity',
            'idx_daily_perf_entity',
            'idx_daily_perf_date'
        ]:
            if _index_exists(inspector, 'daily_performance', idx_name):
                op.drop_index(idx_name, 'daily_performance')
                print(f"Dropped index {idx_name}")

        op.drop_table('daily_performance')
        print("Dropped daily_performance table")
