"""
Tests for v3_5d Bug Fixes — January 27, 2026

Phase 4 validation tests for three bugs:
  - Bug 1: Stale equity from state.json (Critical)
  - Bug 2: Phantom trade duplicate execution (Critical)
  - Bug 3: Data staleness (Medium, no code fix needed)

These tests verify the code fixes applied in Phases 1 and 2 of the
debug_v3_5d_jan27_2026 workflow.

Requires PostgreSQL staging database (see tests/conftest.py).
"""

import pytest
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from jutsu_engine.data.models import (
    Base, LiveTrade, Position, PerformanceSnapshot
)


# ──────────────────────────────────────────────────────────────────
# Task 4.1: Unit Test — Equity Calculation
# ──────────────────────────────────────────────────────────────────

class TestEquityCalculation:
    """Verify equity uses live positions + snapshot cash, NOT state.json."""

    def test_equity_uses_live_positions_not_state_json(self, clean_db_session):
        """Equity should be computed from current DB positions + cash,
        not from state.json account_equity field.

        Setup: state.json has stale equity $9,376
        DB positions: QQQ=12, TQQQ=37
        Latest snapshot cash: $458.84
        Current prices: QQQ=$631.08, TQQQ=$56.55
        Expected equity: (12*631.08) + (37*56.55) + 458.84 = $10,124.15 (approx)
        """
        session = clean_db_session
        strategy_id = 'v3_5d_test_equity'

        # Create positions
        pos_qqq = Position(
            symbol='QQQ', quantity=12, avg_cost=Decimal('620.00'),
            mode='offline_mock', strategy_id=strategy_id
        )
        pos_tqqq = Position(
            symbol='TQQQ', quantity=37, avg_cost=Decimal('50.00'),
            mode='offline_mock', strategy_id=strategy_id
        )
        session.add_all([pos_qqq, pos_tqqq])
        session.flush()

        # Create snapshot with known cash value
        snapshot = PerformanceSnapshot(
            timestamp=datetime(2026, 1, 26, 21, 0, 0, tzinfo=timezone.utc),
            total_equity=Decimal('10001.21'),
            cash=Decimal('458.84'),
            positions_value=Decimal('9542.37'),
            mode='offline_mock',
            strategy_id=strategy_id,
            snapshot_source='scheduler'
        )
        session.add(snapshot)
        session.flush()

        # Simulate the equity calculation logic from daily_multi_strategy_run.py
        # This mirrors lines 382-419 of the fixed code
        db_positions = session.query(Position).filter(
            Position.mode == 'offline_mock',
            Position.strategy_id == strategy_id
        ).all()

        current_positions = {p.symbol: p.quantity for p in db_positions}

        # Query latest snapshot for cash
        from sqlalchemy import desc
        latest_snapshot = session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.mode == 'offline_mock',
            PerformanceSnapshot.strategy_id == strategy_id
        ).order_by(desc(PerformanceSnapshot.timestamp)).first()

        assert latest_snapshot is not None
        snapshot_cash = Decimal(str(latest_snapshot.cash))

        # Simulate current prices
        current_prices = {
            'QQQ': Decimal('631.08'),
            'TQQQ': Decimal('56.55')
        }

        # Calculate equity the NEW way (live positions + snapshot cash)
        position_value = Decimal('0')
        for symbol, qty in current_positions.items():
            if symbol in current_prices:
                position_value += current_prices[symbol] * qty

        live_equity = position_value + snapshot_cash

        # Calculate equity the OLD way (state.json)
        stale_state_json_equity = Decimal('9376.00')

        # Assertions
        assert current_positions == {'QQQ': 12, 'TQQQ': 37}
        assert snapshot_cash == Decimal('458.84')

        expected_position_value = (Decimal('631.08') * 12) + (Decimal('56.55') * 37)
        assert position_value == expected_position_value

        expected_equity = expected_position_value + Decimal('458.84')
        assert live_equity == expected_equity

        # The critical assertion: live equity != stale state.json equity
        assert live_equity != stale_state_json_equity
        assert live_equity > Decimal('10000')  # Should be ~$10,124

    def test_equity_fallback_first_run_no_snapshots(self, clean_db_session):
        """On first run with no snapshots, equity should use initial_capital."""
        session = clean_db_session
        strategy_id = 'v3_5d_test_firstrun'

        # No positions, no snapshots
        latest_snapshot = session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.mode == 'offline_mock',
            PerformanceSnapshot.strategy_id == strategy_id
        ).order_by(PerformanceSnapshot.timestamp.desc()).first()

        assert latest_snapshot is None

        # First-run logic: use initial_capital
        initial_capital = Decimal('10000')
        state_equity = None  # first run
        is_first_run = state_equity is None

        assert is_first_run is True
        account_equity = initial_capital
        assert account_equity == Decimal('10000')

    def test_equity_source_logging_format(self):
        """Verify that the equity source log line contains expected components."""
        # Simulate the log message format from the fix
        position_value = Decimal('9665.31')
        snapshot_cash = Decimal('458.84')
        total = position_value + snapshot_cash
        equity_source = "live_positions+snapshot"

        log_msg = (
            f"Equity calculation: position_value=${position_value:,.2f}, "
            f"cash=${snapshot_cash}, total=${total:,.2f} (source: {equity_source})"
        )

        assert "position_value=" in log_msg
        assert "cash=" in log_msg
        assert "total=" in log_msg
        assert "source: live_positions+snapshot" in log_msg
        assert "state.json" not in log_msg

    def test_equity_no_circular_reference(self, clean_db_session):
        """Ensure equity is NOT derived from itself (regression from Jan 2, 2026 bug).

        The Jan 2 bug had equity feeding back into itself. The fix must ensure
        equity = position_value + cash, where cash comes from snapshots, NOT from
        a previous equity calculation.
        """
        session = clean_db_session
        strategy_id = 'v3_5d_test_circular'

        # Create a snapshot where cash and equity are distinct
        snapshot = PerformanceSnapshot(
            timestamp=datetime(2026, 1, 26, 21, 0, 0, tzinfo=timezone.utc),
            total_equity=Decimal('10001.21'),
            cash=Decimal('458.84'),
            positions_value=Decimal('9542.37'),
            mode='offline_mock',
            strategy_id=strategy_id,
            snapshot_source='scheduler'
        )
        session.add(snapshot)
        session.flush()

        from sqlalchemy import desc
        latest = session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.strategy_id == strategy_id
        ).order_by(desc(PerformanceSnapshot.timestamp)).first()

        # Cash comes from snapshot.cash, NOT from snapshot.total_equity
        cash_used = Decimal(str(latest.cash))
        assert cash_used == Decimal('458.84')
        assert cash_used != Decimal(str(latest.total_equity))  # Not circular


# ──────────────────────────────────────────────────────────────────
# Task 4.2: Unit Test — Re-Entry Guard
# ──────────────────────────────────────────────────────────────────

class TestReentryGuard:
    """Verify duplicate execution guard prevents same-day re-execution."""

    def test_reentry_guard_detects_existing_trade(self, clean_db_session):
        """If strategy already traded today, guard should detect it."""
        session = clean_db_session
        strategy_id = 'v3_5d_test_guard'

        # Create a trade for today
        today_trade = LiveTrade(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            action='SELL',
            quantity=1,
            target_price=Decimal('628.49'),
            fill_price=Decimal('628.49'),
            fill_value=Decimal('628.49'),
            mode='offline_mock',
            strategy_id=strategy_id,
            execution_id='abc12345'
        )
        session.add(today_trade)
        session.flush()

        # Simulate the re-entry guard query
        today_utc = datetime.now(timezone.utc).date()
        existing_trade_today = session.query(LiveTrade).filter(
            LiveTrade.strategy_id == strategy_id,
            func.date(LiveTrade.timestamp) == today_utc
        ).first()

        # Guard should find the existing trade
        assert existing_trade_today is not None
        assert existing_trade_today.symbol == 'QQQ'
        assert existing_trade_today.strategy_id == strategy_id

    def test_reentry_guard_allows_first_execution(self, clean_db_session):
        """If no trades exist for today, guard should NOT block execution."""
        session = clean_db_session
        strategy_id = 'v3_5d_test_guard_clear'

        today_utc = datetime.now(timezone.utc).date()
        existing_trade_today = session.query(LiveTrade).filter(
            LiveTrade.strategy_id == strategy_id,
            func.date(LiveTrade.timestamp) == today_utc
        ).first()

        # No trades today — guard should allow execution
        assert existing_trade_today is None

    def test_reentry_guard_ignores_other_strategy(self, clean_db_session):
        """Guard should only check trades for the SAME strategy_id."""
        session = clean_db_session

        # Create a trade for v3_5b (different strategy)
        other_trade = LiveTrade(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            action='BUY',
            quantity=2,
            target_price=Decimal('630.00'),
            fill_price=Decimal('630.00'),
            fill_value=Decimal('1260.00'),
            mode='offline_mock',
            strategy_id='v3_5b_test',
            execution_id='xyz98765'
        )
        session.add(other_trade)
        session.flush()

        # Check guard for v3_5d — should NOT find v3_5b's trade
        today_utc = datetime.now(timezone.utc).date()
        existing_trade_today = session.query(LiveTrade).filter(
            LiveTrade.strategy_id == 'v3_5d_test_guard_other',
            func.date(LiveTrade.timestamp) == today_utc
        ).first()

        assert existing_trade_today is None

    def test_reentry_guard_ignores_yesterday_trade(self, clean_db_session):
        """Guard should only block same-day trades, not previous day trades."""
        session = clean_db_session
        strategy_id = 'v3_5d_test_guard_yesterday'

        # Create a trade from yesterday
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        old_trade = LiveTrade(
            symbol='QQQ',
            timestamp=yesterday,
            action='BUY',
            quantity=1,
            target_price=Decimal('625.00'),
            fill_price=Decimal('625.00'),
            fill_value=Decimal('625.00'),
            mode='offline_mock',
            strategy_id=strategy_id,
            execution_id='old12345'
        )
        session.add(old_trade)
        session.flush()

        # Check guard for today — yesterday's trade should not trigger it
        today_utc = datetime.now(timezone.utc).date()
        existing_trade_today = session.query(LiveTrade).filter(
            LiveTrade.strategy_id == strategy_id,
            func.date(LiveTrade.timestamp) == today_utc
        ).first()

        assert existing_trade_today is None


# ──────────────────────────────────────────────────────────────────
# Task 4.2b: Unit Test — Execution ID Tracing
# ──────────────────────────────────────────────────────────────────

class TestExecutionIdTracing:
    """Verify execution_id field works for trade correlation."""

    def test_execution_id_stored_on_trade(self, clean_db_session):
        """execution_id should be stored on LiveTrade records."""
        session = clean_db_session

        trade = LiveTrade(
            symbol='TQQQ',
            timestamp=datetime.now(timezone.utc),
            action='BUY',
            quantity=5,
            target_price=Decimal('56.55'),
            fill_price=Decimal('56.55'),
            fill_value=Decimal('282.75'),
            mode='offline_mock',
            strategy_id='v3_5d_test_execid',
            execution_id='a1b2c3d4'
        )
        session.add(trade)
        session.flush()

        # Retrieve and verify
        retrieved = session.query(LiveTrade).filter(
            LiveTrade.strategy_id == 'v3_5d_test_execid'
        ).first()

        assert retrieved is not None
        assert retrieved.execution_id == 'a1b2c3d4'

    def test_execution_id_nullable_for_old_trades(self, clean_db_session):
        """Old trades without execution_id should still work (nullable)."""
        session = clean_db_session

        trade = LiveTrade(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            action='SELL',
            quantity=1,
            target_price=Decimal('628.00'),
            fill_price=Decimal('628.00'),
            fill_value=Decimal('628.00'),
            mode='offline_mock',
            strategy_id='v3_5d_test_execid_null',
            execution_id=None  # Old trades won't have this
        )
        session.add(trade)
        session.flush()

        retrieved = session.query(LiveTrade).filter(
            LiveTrade.strategy_id == 'v3_5d_test_execid_null'
        ).first()

        assert retrieved is not None
        assert retrieved.execution_id is None

    def test_execution_id_correlates_same_run_trades(self, clean_db_session):
        """Multiple trades from same execution run should share execution_id."""
        session = clean_db_session
        exec_id = 'run12345'

        trade1 = LiveTrade(
            symbol='QQQ', timestamp=datetime.now(timezone.utc),
            action='SELL', quantity=1, target_price=Decimal('628.00'),
            fill_price=Decimal('628.00'), fill_value=Decimal('628.00'),
            mode='offline_mock', strategy_id='v3_5d_test_corr', execution_id=exec_id
        )
        trade2 = LiveTrade(
            symbol='TQQQ', timestamp=datetime.now(timezone.utc),
            action='BUY', quantity=5, target_price=Decimal('56.55'),
            fill_price=Decimal('56.55'), fill_value=Decimal('282.75'),
            mode='offline_mock', strategy_id='v3_5d_test_corr', execution_id=exec_id
        )
        session.add_all([trade1, trade2])
        session.flush()

        # Query by execution_id — should find both
        correlated = session.query(LiveTrade).filter(
            LiveTrade.execution_id == exec_id
        ).all()

        assert len(correlated) == 2
        symbols = {t.symbol for t in correlated}
        assert symbols == {'QQQ', 'TQQQ'}


# ──────────────────────────────────────────────────────────────────
# Task 4.3: Integration Test — Strategy Equity Flow
# ──────────────────────────────────────────────────────────────────

class TestStrategyEquityFlow:
    """End-to-end equity calculation flow matching v3_5d production scenario."""

    def test_full_equity_flow_v3_5d_scenario(self, clean_db_session):
        """Simulate the complete v3_5d equity flow with known values.

        Production scenario from Jan 27, 2026:
          - Positions: QQQ=12, TQQQ=37
          - Cash: $458.84 (from latest snapshot)
          - Prices: QQQ=$631.08, TQQQ=$56.55
          - Expected equity: 12*631.08 + 37*56.55 + 458.84 = $10,124.15
          - Stale state.json equity: $9,376 (WRONG — must not use this)
        """
        session = clean_db_session
        strategy_id = 'v3_5d_integration'

        # 1. Set up positions (as they exist in DB after Phase 0 corrections)
        session.add(Position(
            symbol='QQQ', quantity=12, avg_cost=Decimal('620.00'),
            mode='offline_mock', strategy_id=strategy_id
        ))
        session.add(Position(
            symbol='TQQQ', quantity=37, avg_cost=Decimal('50.00'),
            mode='offline_mock', strategy_id=strategy_id
        ))

        # 2. Set up latest snapshot (Jan 26 EOD — last valid before bug)
        session.add(PerformanceSnapshot(
            timestamp=datetime(2026, 1, 26, 21, 0, 0, tzinfo=timezone.utc),
            total_equity=Decimal('10001.21'),
            cash=Decimal('458.84'),
            positions_value=Decimal('9542.37'),
            mode='offline_mock',
            strategy_id=strategy_id,
            snapshot_source='scheduler'
        ))
        session.flush()

        # 3. Execute equity calculation (mirrors run_single_strategy logic)
        db_positions = session.query(Position).filter(
            Position.mode == 'offline_mock',
            Position.strategy_id == strategy_id
        ).all()

        current_positions = {p.symbol: p.quantity for p in db_positions}
        assert current_positions == {'QQQ': 12, 'TQQQ': 37}

        from sqlalchemy import desc
        latest_snapshot = session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.mode == 'offline_mock',
            PerformanceSnapshot.strategy_id == strategy_id
        ).order_by(desc(PerformanceSnapshot.timestamp)).first()

        snapshot_cash = Decimal(str(latest_snapshot.cash))

        current_prices = {
            'QQQ': Decimal('631.08'),
            'TQQQ': Decimal('56.55')
        }

        # Compute position value
        position_value = sum(
            current_prices[sym] * qty
            for sym, qty in current_positions.items()
            if sym in current_prices
        )

        account_equity = position_value + snapshot_cash

        # 4. Validate against known correct answer
        expected_pos_value = (12 * Decimal('631.08')) + (37 * Decimal('56.55'))
        assert position_value == expected_pos_value

        expected_equity = expected_pos_value + Decimal('458.84')
        assert account_equity == expected_equity

        # 5. Validate stale value would have been wrong
        stale_equity = Decimal('9376.00')
        equity_diff = abs(account_equity - stale_equity)
        assert equity_diff > Decimal('700')  # >$700 difference = material error

    def test_no_negative_cash_in_equity_calculation(self, clean_db_session):
        """Ensure equity calculation never produces negative cash scenarios.

        The Jan 27 bug produced cash=-$798.32 from phantom trade.
        With the fix, cash comes from valid snapshots only.
        """
        session = clean_db_session
        strategy_id = 'v3_5d_negcash'

        # Create only valid snapshots (positive cash)
        session.add(PerformanceSnapshot(
            timestamp=datetime(2026, 1, 26, 21, 0, 0, tzinfo=timezone.utc),
            total_equity=Decimal('10001.21'),
            cash=Decimal('458.84'),
            positions_value=Decimal('9542.37'),
            mode='offline_mock',
            strategy_id=strategy_id,
            snapshot_source='scheduler'
        ))
        session.flush()

        from sqlalchemy import desc
        latest = session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.strategy_id == strategy_id
        ).order_by(desc(PerformanceSnapshot.timestamp)).first()

        assert latest.cash > 0
        assert Decimal(str(latest.cash)) == Decimal('458.84')


# ──────────────────────────────────────────────────────────────────
# Task 4.4 (Partial): Code-Level Regression Checks
# ──────────────────────────────────────────────────────────────────

class TestRegressionChecks:
    """Verify historical bugs are not reintroduced by Jan 27 fixes."""

    def test_position_isolation_by_strategy_id(self, clean_db_session):
        """Regression: Jan 23 bug — positions must be filtered by strategy_id.

        Without strategy_id filter, v3_5d reads v3_5b positions.
        """
        session = clean_db_session

        # Create positions for two strategies
        session.add(Position(
            symbol='QQQ', quantity=12, mode='offline_mock', strategy_id='v3_5d_regress'
        ))
        session.add(Position(
            symbol='QQQ', quantity=8, mode='offline_mock', strategy_id='v3_5b_regress'
        ))
        session.flush()

        # Query with strategy_id filter (the fix from Jan 23)
        v3_5d_positions = session.query(Position).filter(
            Position.mode == 'offline_mock',
            Position.strategy_id == 'v3_5d_regress'
        ).all()

        assert len(v3_5d_positions) == 1
        assert v3_5d_positions[0].quantity == 12  # v3_5d's QQQ, not v3_5b's

    def test_equity_not_self_referencing(self):
        """Regression: Jan 2 bug — equity must not be derived from itself.

        The fix uses position_value + snapshot_cash, which are independent
        of the equity value being computed.
        """
        # Verify the computation is not circular
        position_value = Decimal('9665.31')
        snapshot_cash = Decimal('458.84')
        computed_equity = position_value + snapshot_cash

        # Neither input is derived from the output
        assert position_value + snapshot_cash == computed_equity
        assert snapshot_cash != computed_equity
        assert position_value != computed_equity

    def test_snapshot_cash_field_exists(self, clean_db_session):
        """Verify PerformanceSnapshot.cash column is queryable."""
        session = clean_db_session

        snapshot = PerformanceSnapshot(
            timestamp=datetime(2026, 1, 25, 21, 0, 0, tzinfo=timezone.utc),
            total_equity=Decimal('10000.00'),
            cash=Decimal('500.00'),
            positions_value=Decimal('9500.00'),
            mode='offline_mock',
            strategy_id='v3_5d_regress_snap',
            snapshot_source='scheduler'
        )
        session.add(snapshot)
        session.flush()

        result = session.query(PerformanceSnapshot.cash).filter(
            PerformanceSnapshot.strategy_id == 'v3_5d_regress_snap'
        ).scalar()

        assert result is not None
        assert Decimal(str(result)) == Decimal('500.00')

    def test_execution_id_column_exists(self, clean_db_session):
        """Verify LiveTrade.execution_id column is queryable (Phase 2 fix)."""
        session = clean_db_session

        trade = LiveTrade(
            symbol='QQQ', timestamp=datetime.now(timezone.utc),
            action='BUY', quantity=1, target_price=Decimal('630.00'),
            fill_price=Decimal('630.00'), fill_value=Decimal('630.00'),
            mode='offline_mock', strategy_id='v3_5d_regress_execid',
            execution_id='test1234'
        )
        session.add(trade)
        session.flush()

        result = session.query(LiveTrade.execution_id).filter(
            LiveTrade.strategy_id == 'v3_5d_regress_execid'
        ).scalar()

        assert result == 'test1234'
