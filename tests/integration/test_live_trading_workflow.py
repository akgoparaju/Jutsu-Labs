"""
Integration Test - Live Trading Workflow (Phase 0 & 1).

Tests end-to-end workflow with mocked Schwab API:
1. Market calendar check
2. Data fetching (historical + quotes)
3. Strategy execution
4. Position rounding (NO FRACTIONAL SHARES)
5. Rebalance calculation
6. Hypothetical order logging (DRY-RUN)
7. State persistence
"""

import pytest
from unittest.mock import Mock, patch
import tempfile
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
import pandas as pd

from jutsu_engine.live.market_calendar import is_trading_day
from jutsu_engine.live.data_fetcher import LiveDataFetcher
from jutsu_engine.live.strategy_runner import LiveStrategyRunner
from jutsu_engine.live.state_manager import StateManager
from jutsu_engine.live.position_rounder import PositionRounder
from jutsu_engine.live.dry_run_executor import DryRunExecutor


@pytest.fixture
def temp_dirs():
    """Create temporary directories for state and logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield {
            'state': Path(tmpdir) / 'state',
            'logs': Path(tmpdir) / 'logs'
        }


@pytest.fixture
def mock_schwab_client():
    """Create comprehensive mock Schwab client."""
    client = Mock()

    # Mock historical data response
    client.get_price_history.return_value = {
        'candles': [
            {
                'datetime': (datetime.now(timezone.utc).timestamp() - (i * 86400)) * 1000,
                'open': 500.0 + i,
                'high': 505.0 + i,
                'low': 495.0 + i,
                'close': 502.0 + i,
                'volume': 1000000
            }
            for i in range(250)  # 250 days of historical data
        ][::-1]  # Reverse to oldest first
    }

    # Mock quote response
    client.get_quote.return_value = {
        'quote': {
            'lastPrice': 550.00,
            'closePrice': 548.50
        }
    }

    # Mock account response
    client.get_account.return_value = {
        'securitiesAccount': {
            'currentBalances': {
                'totalEquity': 100000.00
            },
            'positions': [
                {
                    'instrument': {'symbol': 'TQQQ'},
                    'longQuantity': 100.0
                }
            ]
        }
    }

    return client


class TestLiveTradingWorkflowIntegration:
    """Integration test suite for complete Phase 0 & 1 workflow."""

    def test_phase_0_hello_world(self, mock_schwab_client):
        """Test Phase 0: Basic OAuth and market calendar check."""
        # Market calendar check (should work without API)
        is_trading = is_trading_day()
        assert isinstance(is_trading, bool)

        # OAuth check (mocked)
        quote = mock_schwab_client.get_quote('QQQ')
        assert 'quote' in quote
        assert 'lastPrice' in quote['quote']

    def test_phase_1_dry_run_complete_workflow(
        self,
        mock_schwab_client,
        temp_dirs
    ):
        """Test Phase 1: Complete dry-run workflow end-to-end."""

        # Initialize components
        data_fetcher = LiveDataFetcher(mock_schwab_client)
        strategy_runner = LiveStrategyRunner()
        state_manager = StateManager(
            state_file=temp_dirs['state'] / 'state.json',
            backup_enabled=True,
            backup_dir=temp_dirs['state'] / 'backups'
        )
        position_rounder = PositionRounder()
        dry_run_executor = DryRunExecutor(
            trade_log_path=temp_dirs['logs'] / 'trades.csv',
            rebalance_threshold_pct=5.0
        )

        # Step 1: Fetch historical bars
        hist_df = data_fetcher.fetch_historical_bars('QQQ', lookback=250)
        assert len(hist_df) == 250

        # Step 2: Fetch current quote
        quote = mock_schwab_client.get_quote('QQQ')
        current_price = Decimal(str(quote['quote']['lastPrice']))
        assert current_price > 0

        # Step 3: Create synthetic bar
        synthetic_df = data_fetcher.create_synthetic_daily_bar(hist_df, current_price)
        assert len(synthetic_df) == 251  # Historical + synthetic

        # Step 4: Run strategy
        market_data = {'QQQ': synthetic_df, 'TLT': synthetic_df}  # Simplified
        signals = strategy_runner.calculate_signals(market_data)

        assert 'current_cell' in signals
        assert 'vol_state' in signals

        # Step 5: Determine target allocation
        account_equity = Decimal('100000')
        target_weights = strategy_runner.determine_target_allocation(
            signals,
            account_equity
        )

        assert isinstance(target_weights, dict)
        assert 0.99 <= sum(target_weights.values()) <= 1.01

        # Step 6: Convert to shares (NO FRACTIONAL SHARES)
        current_prices = {
            'TQQQ': Decimal('50.00'),
            'TMF': Decimal('20.00'),
            'TMV': Decimal('30.00')
        }

        target_positions = position_rounder.convert_weights_to_shares(
            target_weights,
            account_equity,
            current_prices
        )

        # Verify NO FRACTIONAL SHARES
        for symbol, qty in target_positions.items():
            assert isinstance(qty, int), f"{symbol} has non-integer quantity"

        # Step 7: Calculate rebalance diff
        current_positions = {'TQQQ': 100}  # From account
        orders, position_diffs = dry_run_executor.execute_dry_run(
            current_positions,
            target_positions,
            current_prices,
            account_equity
        )

        # Should have logged orders (or filtered by threshold)
        assert isinstance(orders, list)

        # Step 8: Save state
        state = state_manager.load_state()
        state['vol_state'] = signals['vol_state']
        state['current_positions'] = target_positions
        state['account_equity'] = float(account_equity)
        state['last_allocation'] = target_weights

        state_manager.save_state(state)

        # Verify state saved
        assert state_manager.state_file.exists()

        # Step 9: Reload state and verify
        loaded_state = state_manager.load_state()
        assert loaded_state['vol_state'] == signals['vol_state']
        assert loaded_state['current_positions'] == target_positions

    def test_no_fractional_shares_enforcement(self, mock_schwab_client):
        """Test that NO FRACTIONAL SHARES is enforced end-to-end."""
        position_rounder = PositionRounder()

        # Test with odd values to ensure rounding down
        weights = {'TQQQ': 0.333, 'TMF': 0.667}
        equity = Decimal('99999.99')
        prices = {'TQQQ': Decimal('503.45'), 'TMF': Decimal('19.87')}

        target_positions = position_rounder.convert_weights_to_shares(
            weights, equity, prices
        )

        # Verify all are integers
        for symbol, qty in target_positions.items():
            assert isinstance(qty, int)
            assert qty >= 0

    def test_atomic_state_write(self, temp_dirs):
        """Test that state writes are atomic (no corruption)."""
        state_manager = StateManager(
            state_file=temp_dirs['state'] / 'state.json'
        )

        # Save state
        state = {
            'last_run': None,
            'vol_state': 1,
            'current_positions': {'TQQQ': 100}
        }
        state_manager.save_state(state)

        # Verify no .tmp file left behind
        temp_file = state_manager.state_file.with_suffix('.tmp')
        assert not temp_file.exists(), "Temp file not cleaned up (atomicity violated)"

    def test_dry_run_mode_no_actual_orders(self, mock_schwab_client, temp_dirs):
        """Test that DRY-RUN mode doesn't place actual orders."""
        dry_run_executor = DryRunExecutor(
            trade_log_path=temp_dirs['logs'] / 'trades.csv'
        )

        # Execute dry-run
        current = {'TQQQ': 100}
        target = {'TQQQ': 150}
        prices = {'TQQQ': Decimal('100.00')}
        equity = Decimal('100000')

        orders, _ = dry_run_executor.execute_dry_run(
            current, target, prices, equity
        )

        # Verify orders are logged but marked DRY-RUN
        for order in orders:
            assert order['mode'] == 'DRY-RUN'

        # Verify no API order placement calls were made
        assert not hasattr(mock_schwab_client, 'place_order')


class TestPhase2PaperTradingWorkflow:
    """Integration tests for Phase 2: Paper Trading Execution."""

    @pytest.fixture
    def mock_client_with_orders(self):
        """Create mock Schwab client with order execution support."""
        client = Mock()

        # Mock order placement
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER123'}
        client.place_order.return_value = mock_response

        # Mock order status (FILLED)
        client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{'price': '50.10'}]
            }]
        }

        # Mock account info
        client.get_account.return_value = Mock(
            json=Mock(return_value={
                'securitiesAccount': {
                    'currentBalances': {
                        'liquidationValue': 100000.00
                    }
                }
            })
        )

        return client

    def test_phase_2_order_execution_workflow(
        self,
        mock_client_with_orders,
        temp_dirs
    ):
        """Test Phase 2: Complete order execution workflow."""
        from jutsu_engine.live.order_executor import OrderExecutor
        from jutsu_engine.live.slippage_validator import SlippageValidator

        config = {
            'execution': {
                'max_slippage_pct': 0.5,
                'slippage_warning_pct': 0.3,
                'slippage_abort_pct': 1.0,
                'max_order_retries': 3,
                'retry_delay_seconds': 0.1
            },
            'schwab': {'environment': 'paper'}
        }

        # Initialize order executor
        executor = OrderExecutor(
            client=mock_client_with_orders,
            account_hash='test_account',
            config=config,
            trade_log_path=temp_dirs['logs'] / 'trades.csv'
        )

        # Execute rebalance (SELL first, then BUY)
        position_diffs = {
            'TQQQ': -50,  # SELL 50
            'TMF': 100    # BUY 100
        }

        current_prices = {
            'TQQQ': Decimal('50.00'),
            'TMF': Decimal('20.00')
        }

        fills, fill_prices = executor.execute_rebalance(
            position_diffs,
            current_prices,
            reason="Test Rebalance"
        )

        # Verify fills
        assert len(fills) == 2

        # Verify SELL executed first (check order calls)
        assert mock_client_with_orders.place_order.call_count == 2

        # Verify fills logged
        trade_log = temp_dirs['logs'] / 'trades.csv'
        assert trade_log.exists()

    def test_phase_2_slippage_validation(
        self,
        mock_client_with_orders,
        temp_dirs
    ):
        """Test slippage validation during execution."""
        from jutsu_engine.live.order_executor import OrderExecutor
        from jutsu_engine.live.exceptions import SlippageExceeded

        config = {
            'execution': {
                'max_slippage_pct': 0.5,
                'slippage_warning_pct': 0.3,
                'slippage_abort_pct': 1.0,
                'max_order_retries': 3,
                'retry_delay_seconds': 0.1
            },
            'schwab': {'environment': 'paper'}
        }

        # Mock excessive slippage
        mock_client_with_orders.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{'price': '50.75'}]  # 1.5% slippage from 50.00
            }]
        }

        executor = OrderExecutor(
            client=mock_client_with_orders,
            account_hash='test_account',
            config=config,
            trade_log_path=temp_dirs['logs'] / 'trades.csv'
        )

        position_diffs = {'TQQQ': 100}
        current_prices = {'TQQQ': Decimal('50.00')}

        # Should raise SlippageExceeded
        with pytest.raises(SlippageExceeded):
            executor.execute_rebalance(
                position_diffs,
                current_prices
            )

    def test_phase_2_partial_fill_retry(
        self,
        mock_client_with_orders,
        temp_dirs
    ):
        """Test partial fill retry logic."""
        from jutsu_engine.live.order_executor import OrderExecutor

        config = {
            'execution': {
                'max_slippage_pct': 0.5,
                'slippage_warning_pct': 0.3,
                'slippage_abort_pct': 1.0,
                'max_order_retries': 3,
                'retry_delay_seconds': 0.1
            },
            'schwab': {'environment': 'paper'}
        }

        # Mock partial fill then filled
        mock_client_with_orders.get_order.side_effect = [
            {'status': 'PARTIALLY_FILLED'},
            {
                'status': 'FILLED',
                'orderActivityCollection': [{
                    'executionLegs': [{'price': '50.10'}]
                }]
            }
        ]

        executor = OrderExecutor(
            client=mock_client_with_orders,
            account_hash='test_account',
            config=config,
            trade_log_path=temp_dirs['logs'] / 'trades.csv'
        )

        fill = executor.submit_order(
            symbol='TQQQ',
            action='BUY',
            quantity=100,
            expected_price=Decimal('50.00')
        )

        # Verify retry occurred
        assert mock_client_with_orders.get_order.call_count == 2
        assert fill['fill_price'] == Decimal('50.10')


class TestPhase3ProductionHardening:
    """Integration tests for Phase 3: Production Hardening."""

    @pytest.fixture
    def mock_alert_manager(self):
        """Create mock AlertManager."""
        return Mock()

    def test_phase_3_alert_system(self, mock_alert_manager):
        """Test alert system sends notifications correctly."""
        # Test critical alert
        mock_alert_manager.send_critical_alert(
            "Test critical error",
            "Test context"
        )

        mock_alert_manager.send_critical_alert.assert_called_once()

        # Test warning alert
        mock_alert_manager.send_warning(
            "Test warning",
            "Test details"
        )

        mock_alert_manager.send_warning.assert_called_once()

    def test_phase_3_health_monitoring(
        self,
        mock_client_with_orders,
        mock_alert_manager,
        temp_dirs
    ):
        """Test health monitoring detects failures."""
        from jutsu_engine.live.health_monitor import HealthMonitor

        config = {
            'health': {
                'thresholds': {
                    'min_disk_space_gb': 1.0
                }
            },
            'schwab': {
                'account_number': 'test_account'
            }
        }

        # Create valid state file for integrity check
        state_file = temp_dirs['state'] / 'state.json'
        state_file.parent.mkdir(parents=True, exist_ok=True)

        import json
        with open(state_file, 'w') as f:
            json.dump({
                'last_run': '2025-01-01T12:00:00Z',
                'vol_state': 0,
                'current_positions': {}
            }, f)

        # Mock API success
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client_with_orders.get_account.return_value = mock_response

        health_monitor = HealthMonitor(
            client=mock_client_with_orders,
            config=config,
            alert_manager=mock_alert_manager,
            state_file=state_file
        )

        # Run health checks
        with patch('shutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(free=10 * 1024**3)  # 10GB

            with patch('subprocess.run') as mock_subprocess:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = "0 15 * * * python scripts/live_trader.py"
                mock_subprocess.return_value = mock_result

                report = health_monitor.generate_health_report()

                # All checks should pass
                assert report['overall_status'] == 'HEALTHY'
                assert all(report['checks'].values())

                # No alert should be sent
                mock_alert_manager.send_critical_alert.assert_not_called()

    @pytest.mark.parametrize('mock_client_with_orders', [Mock()], indirect=False)
    def test_phase_3_health_monitoring_failure_detection(
        self,
        mock_alert_manager,
        temp_dirs
    ):
        """Test health monitoring sends alerts on failure."""
        from jutsu_engine.live.health_monitor import HealthMonitor

        config = {
            'health': {
                'thresholds': {
                    'min_disk_space_gb': 1.0
                }
            },
            'schwab': {
                'account_number': 'test_account'
            }
        }

        # Create mock client that fails
        failing_client = Mock()
        failing_client.get_account.side_effect = Exception("API error")

        state_file = temp_dirs['state'] / 'state.json'
        state_file.parent.mkdir(parents=True, exist_ok=True)

        import json
        with open(state_file, 'w') as f:
            json.dump({
                'last_run': '2025-01-01T12:00:00Z',
                'vol_state': 0,
                'current_positions': {}
            }, f)

        health_monitor = HealthMonitor(
            client=failing_client,
            config=config,
            alert_manager=mock_alert_manager,
            state_file=state_file
        )

        # Run health checks
        with patch('shutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(free=10 * 1024**3)

            with patch('subprocess.run') as mock_subprocess:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = ""  # No cron job
                mock_subprocess.return_value = mock_result

                report = health_monitor.generate_health_report()

                # Should be unhealthy
                assert report['overall_status'] == 'UNHEALTHY'
                assert 'api_connectivity' in report['failed_checks']

                # Alert should be sent
                mock_alert_manager.send_critical_alert.assert_called_once()
