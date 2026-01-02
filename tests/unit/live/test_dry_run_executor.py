"""
Unit tests for Dry-Run Executor.

Tests hypothetical order calculation, threshold filtering, and CSV logging.
"""

import pytest
import tempfile
import csv
from pathlib import Path
from decimal import Decimal

from jutsu_engine.live.dry_run_executor import DryRunExecutor


@pytest.fixture
def temp_log_dir():
    """Create temporary directory for trade logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def executor(temp_log_dir):
    """Create DryRunExecutor with temporary log file."""
    log_path = temp_log_dir / 'live_trades.csv'
    return DryRunExecutor(
        trade_log_path=log_path,
        rebalance_threshold_pct=5.0
    )


class TestDryRunExecutor:
    """Test suite for DryRunExecutor class."""

    def test_initialization_creates_csv(self, executor):
        """Test that CSV is created with header on init."""
        assert executor.trade_log_path.exists()

        # Verify header
        with open(executor.trade_log_path, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == [
                'Date', 'Time', 'Ticker', 'Action', 'Qty',
                'Price', 'Value', 'Reason', 'Mode'
            ]

    def test_calculate_rebalance_diff_buy_signal(self, executor):
        """Test rebalance diff for buy signal (increase position)."""
        current = {'TQQQ': 100}
        target = {'TQQQ': 120}

        diffs = executor.calculate_rebalance_diff(current, target)

        assert diffs == {'TQQQ': 20}  # Buy 20 more

    def test_calculate_rebalance_diff_sell_signal(self, executor):
        """Test rebalance diff for sell signal (decrease position)."""
        current = {'TQQQ': 100}
        target = {'TQQQ': 80}

        diffs = executor.calculate_rebalance_diff(current, target)

        assert diffs == {'TQQQ': -20}  # Sell 20

    def test_calculate_rebalance_diff_new_position(self, executor):
        """Test rebalance diff for new position (buy from 0)."""
        current = {}
        target = {'TMF': 50}

        diffs = executor.calculate_rebalance_diff(current, target)

        assert diffs == {'TMF': 50}  # Buy 50 (new position)

    def test_calculate_rebalance_diff_close_position(self, executor):
        """Test rebalance diff for closing position (sell all)."""
        current = {'TQQQ': 100}
        target = {}

        diffs = executor.calculate_rebalance_diff(current, target)

        assert diffs == {'TQQQ': -100}  # Sell all 100

    def test_calculate_rebalance_diff_multiple_symbols(self, executor):
        """Test rebalance diff with multiple symbols."""
        current = {'TQQQ': 100, 'TMF': 50}
        target = {'TQQQ': 120, 'TMF': 30, 'TMV': 10}

        diffs = executor.calculate_rebalance_diff(current, target)

        assert diffs == {
            'TQQQ': 20,   # Buy 20
            'TMF': -20,   # Sell 20
            'TMV': 10     # Buy 10 (new)
        }

    def test_calculate_rebalance_diff_no_changes(self, executor):
        """Test rebalance diff returns empty for no changes."""
        current = {'TQQQ': 100}
        target = {'TQQQ': 100}

        diffs = executor.calculate_rebalance_diff(current, target)

        assert diffs == {}

    def test_filter_by_threshold_above_threshold(self, executor):
        """Test filtering keeps trades above 5% threshold."""
        diffs = {'TQQQ': 200}  # $10K trade
        current = {'TQQQ': 100}
        prices = {'TQQQ': Decimal('50.00')}
        equity = Decimal('100000')  # 5% threshold = $5K

        filtered = executor.filter_by_threshold(
            diffs, current, prices, equity
        )

        # $10K > $5K → Keep
        assert filtered == {'TQQQ': 200}

    def test_filter_by_threshold_below_threshold(self, executor):
        """Test filtering removes trades below 5% threshold."""
        diffs = {'TQQQ': 10}  # $500 trade
        current = {'TQQQ': 100}
        prices = {'TQQQ': Decimal('50.00')}
        equity = Decimal('100000')  # 5% threshold = $5K

        filtered = executor.filter_by_threshold(
            diffs, current, prices, equity
        )

        # $500 < $5K → Filter out
        assert filtered == {}

    def test_filter_by_threshold_exactly_at_threshold(self, executor):
        """Test filtering keeps trades exactly at threshold."""
        diffs = {'TQQQ': 100}  # Exactly $5K
        current = {'TQQQ': 100}
        prices = {'TQQQ': Decimal('50.00')}
        equity = Decimal('100000')  # 5% threshold = $5K

        filtered = executor.filter_by_threshold(
            diffs, current, prices, equity
        )

        # Exactly $5K → Keep (>= threshold)
        assert filtered == {'TQQQ': 100}

    def test_filter_by_threshold_mixed_symbols(self, executor):
        """Test filtering with mixed symbols (some pass, some fail)."""
        diffs = {
            'TQQQ': 200,  # $10K → Keep
            'TMF': 10      # $200 → Filter out
        }
        current = {'TQQQ': 100, 'TMF': 50}
        prices = {'TQQQ': Decimal('50.00'), 'TMF': Decimal('20.00')}
        equity = Decimal('100000')

        filtered = executor.filter_by_threshold(
            diffs, current, prices, equity
        )

        assert filtered == {'TQQQ': 200}  # Only TQQQ kept

    def test_log_hypothetical_orders_buy(self, executor):
        """Test logging hypothetical buy order."""
        diffs = {'TQQQ': 50}
        prices = {'TQQQ': Decimal('100.00')}

        orders = executor.log_hypothetical_orders(diffs, prices)

        assert len(orders) == 1
        assert orders[0]['symbol'] == 'TQQQ'
        assert orders[0]['action'] == 'BUY'
        assert orders[0]['qty'] == 50
        assert orders[0]['price'] == Decimal('100.00')
        assert orders[0]['value'] == 5000
        assert orders[0]['mode'] == 'DRY-RUN'

    def test_log_hypothetical_orders_sell(self, executor):
        """Test logging hypothetical sell order."""
        diffs = {'TQQQ': -75}
        prices = {'TQQQ': Decimal('100.00')}

        orders = executor.log_hypothetical_orders(diffs, prices)

        assert len(orders) == 1
        assert orders[0]['action'] == 'SELL'
        assert orders[0]['qty'] == 75  # Absolute value

    def test_log_hypothetical_orders_writes_to_csv(self, executor):
        """Test that orders are actually written to CSV file."""
        diffs = {'TQQQ': 50, 'TMF': -25}
        prices = {'TQQQ': Decimal('100.00'), 'TMF': Decimal('50.00')}

        executor.log_hypothetical_orders(diffs, prices, reason="Test")

        # Read CSV and verify entries
        with open(executor.trade_log_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        assert rows[0]['Ticker'] == 'TQQQ'
        assert rows[0]['Action'] == 'BUY'
        assert rows[0]['Mode'] == 'DRY-RUN'
        assert rows[1]['Ticker'] == 'TMF'
        assert rows[1]['Action'] == 'SELL'

    def test_log_hypothetical_orders_empty_diffs(self, executor):
        """Test logging with empty position diffs."""
        diffs = {}
        prices = {'TQQQ': Decimal('100.00')}

        orders = executor.log_hypothetical_orders(diffs, prices)

        assert orders == []

    def test_log_hypothetical_orders_missing_price(self, executor):
        """Test that missing price logs warning but doesn't crash."""
        diffs = {'TQQQ': 50, 'TMF': 25}
        prices = {'TQQQ': Decimal('100.00')}  # Missing TMF

        orders = executor.log_hypothetical_orders(diffs, prices)

        # Only TQQQ logged (TMF skipped)
        assert len(orders) == 1
        assert orders[0]['symbol'] == 'TQQQ'

    def test_execute_dry_run_complete_workflow(self, executor):
        """Test complete dry-run workflow end-to-end."""
        current = {'TQQQ': 100}
        # TMF needs 100 shares to reach 5% threshold ($50 × 100 = $5K = 5% of $100K)
        target = {'TQQQ': 150, 'TMF': 100}
        prices = {'TQQQ': Decimal('100.00'), 'TMF': Decimal('50.00')}
        equity = Decimal('100000')

        orders, final_diffs = executor.execute_dry_run(
            current, target, prices, equity
        )

        # Should have 2 orders (buy TQQQ, buy TMF)
        assert len(orders) == 2

        # Verify orders
        tqqq_order = next(o for o in orders if o['symbol'] == 'TQQQ')
        assert tqqq_order['action'] == 'BUY'
        assert tqqq_order['qty'] == 50

        tmf_order = next(o for o in orders if o['symbol'] == 'TMF')
        assert tmf_order['action'] == 'BUY'
        assert tmf_order['qty'] == 100  # 100 shares to reach 5% threshold

        # Verify final diffs
        assert final_diffs == {'TQQQ': 50, 'TMF': 100}

    def test_execute_dry_run_no_action_needed(self, executor):
        """Test dry-run returns empty when no changes needed."""
        current = {'TQQQ': 100}
        target = {'TQQQ': 100}
        prices = {'TQQQ': Decimal('100.00')}
        equity = Decimal('100000')

        orders, final_diffs = executor.execute_dry_run(
            current, target, prices, equity
        )

        assert orders == []
        assert final_diffs == {}

    def test_execute_dry_run_filtered_by_threshold(self, executor):
        """Test dry-run filters small trades below threshold."""
        current = {'TQQQ': 100}
        target = {'TQQQ': 105}  # Small change (5 shares = $500)
        prices = {'TQQQ': Decimal('100.00')}
        equity = Decimal('100000')  # 5% threshold = $5K

        orders, final_diffs = executor.execute_dry_run(
            current, target, prices, equity
        )

        # $500 < $5K → Filtered
        assert orders == []
        assert final_diffs == {}

    def test_rebalance_threshold_configurable(self, temp_log_dir):
        """Test that rebalance threshold is configurable."""
        executor = DryRunExecutor(
            trade_log_path=temp_log_dir / 'trades.csv',
            rebalance_threshold_pct=2.0  # 2% threshold
        )

        assert executor.rebalance_threshold_pct == 2.0

        # Test filtering with 2% threshold
        diffs = {'TQQQ': 30}  # $3K = 3%
        current = {'TQQQ': 100}
        prices = {'TQQQ': Decimal('100.00')}
        equity = Decimal('100000')

        filtered = executor.filter_by_threshold(
            diffs, current, prices, equity
        )

        # 3% > 2% threshold → Keep
        assert filtered == {'TQQQ': 30}
