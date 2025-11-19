"""
Tests for WFO Monte Carlo input generation.

Validates:
- Per-trade portfolio return calculation
- FIFO cost basis accuracy
- CSV output format
- Data validation and error handling
"""
import pytest
import pandas as pd
from decimal import Decimal
from pathlib import Path
from datetime import datetime
import tempfile
import shutil

from jutsu_engine.application.wfo_runner import WFORunner


class TestMonteCarloInputGeneration:
    """Test suite for _generate_monte_carlo_input() method."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create temporary output directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def sample_trades_df(self):
        """
        Create sample trades DataFrame with all required columns for 5-column Monte Carlo output.

        Scenario:
        - Initial capital: $10,000
        - BUY QQQ at 2024-01-15
        - SELL QQQ at 2024-01-22 (+2.34% return)
        - BUY TQQQ at 2024-02-05
        - SELL TQQQ at 2024-02-10 (+4.12% return)
        """
        return pd.DataFrame({
            'Date': pd.to_datetime([
                '2024-01-15',  # BUY QQQ
                '2024-01-22',  # SELL QQQ
                '2024-02-05',  # BUY TQQQ
                '2024-02-10'   # SELL TQQQ
            ]),
            'Ticker': ['QQQ', 'QQQ', 'TQQQ', 'TQQQ'],
            'Decision': ['BUY', 'SELL', 'BUY', 'SELL'],
            'Shares': [50, 50, 100, 100],
            'Fill_Price': [Decimal('200.00'), Decimal('201.00'), Decimal('50.00'), Decimal('51.00')],
            'Portfolio_Value_Before': [
                Decimal('10000.00'),
                Decimal('10234.00'),
                Decimal('10234.00'),
                Decimal('10655.71')
            ],
            'Portfolio_Value_After': [
                Decimal('10234.00'),
                Decimal('10234.00'),  # No change (SELL completes position)
                Decimal('10655.71'),
                Decimal('10655.71')   # No change (SELL completes position)
            ],
            'OOS_Period_ID': ['Window_001', 'Window_001', 'Window_001', 'Window_001']
        })


    @pytest.fixture
    def wfo_runner_mock(self, temp_output_dir):
        """Create mock WFO runner with minimal config."""
        # Create minimal config file
        config_path = temp_output_dir / "test_config.yaml"
        config_content = """
strategy: MACD_Trend_v4
symbol_sets:
  - signal_symbol: QQQ
    bull_symbol: TQQQ
    defense_symbol: BIL
base_config:
  initial_capital: 10000
  commission: 0
  slippage: 0
parameters:
  ema_period: [20, 30]
walk_forward:
  total_start_date: '2020-01-01'
  total_end_date: '2024-12-31'
  window_size_years: 2
  in_sample_years: 1
  out_of_sample_years: 1
  slide_years: 1
  selection_metric: sharpe_ratio
"""
        with open(config_path, 'w') as f:
            f.write(config_content)

        runner = WFORunner(str(config_path), output_dir=str(temp_output_dir))
        return runner

    def test_monte_carlo_input_basic(self, wfo_runner_mock, sample_trades_df):
        """Test basic Monte Carlo input generation with 5-column output."""
        initial_capital = Decimal('10000.00')

        # Generate Monte Carlo input
        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            sample_trades_df,
            initial_capital
        )

        # Validate file exists
        assert mc_path.exists()
        assert mc_path.name == 'monte_carlo_input.csv'

        # Load and validate
        mc_df = pd.read_csv(mc_path)

        # Check columns (5 columns in specified order)
        expected_columns = ['Portfolio_Return_Percent', 'Exit_Date', 'Entry_Date', 'Symbol', 'OOS_Period_ID']
        assert list(mc_df.columns) == expected_columns

        # Check row count (2 completed trades: QQQ and TQQQ)
        assert len(mc_df) == 2

        # Validate first trade (QQQ)
        assert mc_df['Symbol'].iloc[0] == 'QQQ'
        assert pd.to_datetime(mc_df['Exit_Date'].iloc[0]) == pd.to_datetime('2024-01-22')
        assert pd.to_datetime(mc_df['Entry_Date'].iloc[0]) == pd.to_datetime('2024-01-15')
        assert mc_df['OOS_Period_ID'].iloc[0] == 'Window_001'

        # Validate second trade (TQQQ)
        assert mc_df['Symbol'].iloc[1] == 'TQQQ'
        assert pd.to_datetime(mc_df['Exit_Date'].iloc[1]) == pd.to_datetime('2024-02-10')
        assert pd.to_datetime(mc_df['Entry_Date'].iloc[1]) == pd.to_datetime('2024-02-05')
        assert mc_df['OOS_Period_ID'].iloc[1] == 'Window_001'


    def test_monte_carlo_return_calculation(self, wfo_runner_mock, sample_trades_df):
        """Test portfolio return percentage calculation accuracy."""
        initial_capital = Decimal('10000.00')
        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            sample_trades_df,
            initial_capital
        )

        mc_df = pd.read_csv(mc_path)

        # With fixed calculation using entry_value from BUY:
        # QQQ: (10234 - 10000) / 10000 = +2.34% return
        # TQQQ: (10655.71 - 10234) / 10234 = +4.12% return

        assert len(mc_df) == 2  # 2 completed trades
        assert 'Portfolio_Return_Percent' in mc_df.columns

        # Validate positive returns for profitable trades
        qqq_return = mc_df[mc_df['Symbol'] == 'QQQ']['Portfolio_Return_Percent'].iloc[0]
        tqqq_return = mc_df[mc_df['Symbol'] == 'TQQQ']['Portfolio_Return_Percent'].iloc[0]

        # QQQ: +2.34% return
        assert pytest.approx(qqq_return, rel=1e-4) == 0.0234

        # TQQQ: +4.12% return (with decimal precision)
        # (10655.71 - 10234) / 10234 = 421.71 / 10234 = 0.04120676...
        assert pytest.approx(tqqq_return, rel=1e-3) == 0.0412


    def test_monte_carlo_chronological_order(self, wfo_runner_mock):
        """Test that trades are sorted chronologically."""
        # Create out-of-order BUY/SELL pairs
        trades_df = pd.DataFrame({
            'Date': pd.to_datetime([
                '2024-02-10',  # SELL TQQQ (later date first)
                '2024-01-15',  # BUY QQQ
                '2024-02-05',  # BUY TQQQ
                '2024-01-22'   # SELL QQQ
            ]),
            'Ticker': ['TQQQ', 'QQQ', 'TQQQ', 'QQQ'],
            'Decision': ['SELL', 'BUY', 'BUY', 'SELL'],
            'Portfolio_Value_Before': [
                Decimal('10234.00'),
                Decimal('10000.00'),
                Decimal('10234.00'),
                Decimal('10234.00')
            ],
            'Portfolio_Value_After': [
                Decimal('10655.71'),
                Decimal('10234.00'),
                Decimal('10234.00'),
                Decimal('10234.00')
            ],
            'OOS_Period_ID': ['Window_001', 'Window_001', 'Window_001', 'Window_001']
        })

        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            trades_df,
            Decimal('10000.00')
        )

        mc_df = pd.read_csv(mc_path)

        # After sorting, should get: QQQ (Jan 15-22), TQQQ (Feb 05-10)
        assert len(mc_df) == 2
        assert mc_df['Symbol'].iloc[0] == 'QQQ'
        assert mc_df['Symbol'].iloc[1] == 'TQQQ'
        assert pd.to_datetime(mc_df['Exit_Date'].iloc[0]) < pd.to_datetime(mc_df['Exit_Date'].iloc[1])


    def test_monte_carlo_missing_columns(self, wfo_runner_mock):
        """Test error handling for missing required columns."""
        # Missing Ticker, Decision, OOS_Period_ID
        invalid_df = pd.DataFrame({
            'Date': pd.to_datetime(['2024-01-15']),
            'Portfolio_Value_Before': [Decimal('10000.00')],
            'Portfolio_Value_After': [Decimal('10234.00')]
        })

        with pytest.raises(ValueError, match="Missing required columns"):
            wfo_runner_mock._generate_monte_carlo_input(
                invalid_df,
                Decimal('10000.00')
            )


    def test_monte_carlo_nan_detection(self, wfo_runner_mock):
        """Test error handling for invalid portfolio values (zero or NaN)."""
        # Create scenario where portfolio calculation would fail
        # Case: Portfolio_Value_Before at BUY is 0 (division by zero when calculating return)
        invalid_df = pd.DataFrame({
            'Date': pd.to_datetime(['2024-01-15', '2024-01-22']),
            'Ticker': ['QQQ', 'QQQ'],
            'Decision': ['BUY', 'SELL'],
            'Portfolio_Value_Before': [Decimal('0.00'), Decimal('10234.00')],  # BUY with zero causes div-by-zero
            'Portfolio_Value_After': [Decimal('10234.00'), Decimal('10234.00')],
            'OOS_Period_ID': ['Window_001', 'Window_001']
        })

        # Should raise error when invalid portfolio values encountered
        # The fix uses entry_value from BUY, so zero at BUY causes division by zero
        with pytest.raises((ValueError, ZeroDivisionError)):
            wfo_runner_mock._generate_monte_carlo_input(
                invalid_df,
                Decimal('10000.00')
            )


    def test_monte_carlo_zero_trades(self, wfo_runner_mock):
        """Test handling of empty trades DataFrame."""
        empty_df = pd.DataFrame({
            'Date': pd.to_datetime([]),
            'Ticker': [],
            'Decision': [],
            'Portfolio_Value_Before': [],
            'Portfolio_Value_After': [],
            'OOS_Period_ID': []
        })

        # Should succeed but create empty file with correct columns
        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            empty_df,
            Decimal('10000.00')
        )

        mc_df = pd.read_csv(mc_path)
        assert len(mc_df) == 0
        # Check all 5 columns exist
        expected_columns = ['Portfolio_Return_Percent', 'Exit_Date', 'Entry_Date', 'Symbol', 'OOS_Period_ID']
        assert list(mc_df.columns) == expected_columns


    def test_monte_carlo_single_trade(self, wfo_runner_mock):
        """Test Monte Carlo generation with single completed trade."""
        single_trade_df = pd.DataFrame({
            'Date': pd.to_datetime(['2024-01-15', '2024-01-22']),
            'Ticker': ['QQQ', 'QQQ'],
            'Decision': ['BUY', 'SELL'],
            'Portfolio_Value_Before': [Decimal('10000.00'), Decimal('10234.00')],
            'Portfolio_Value_After': [Decimal('10234.00'), Decimal('10234.00')],
            'OOS_Period_ID': ['Window_001', 'Window_001']
        })

        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            single_trade_df,
            Decimal('10000.00')
        )

        mc_df = pd.read_csv(mc_path)
        assert len(mc_df) == 1
        assert mc_df['Symbol'].iloc[0] == 'QQQ'
        assert pd.to_datetime(mc_df['Entry_Date'].iloc[0]) == pd.to_datetime('2024-01-15')
        assert pd.to_datetime(mc_df['Exit_Date'].iloc[0]) == pd.to_datetime('2024-01-22')


    def test_monte_carlo_negative_returns(self, wfo_runner_mock):
        """Test Monte Carlo with losing trades."""
        losing_trades_df = pd.DataFrame({
            'Date': pd.to_datetime([
                '2024-01-15',  # BUY QQQ
                '2024-01-22',  # SELL QQQ (-5%)
                '2024-02-05',  # BUY TQQQ
                '2024-02-10'   # SELL TQQQ (-5.26%)
            ]),
            'Ticker': ['QQQ', 'QQQ', 'TQQQ', 'TQQQ'],
            'Decision': ['BUY', 'SELL', 'BUY', 'SELL'],
            'Portfolio_Value_Before': [
                Decimal('10000.00'),  # QQQ BUY: entry value
                Decimal('9500.00'),   # QQQ SELL: (unused, we use entry_value)
                Decimal('9500.00'),   # TQQQ BUY: entry value
                Decimal('9000.00')    # TQQQ SELL: (unused, we use entry_value)
            ],
            'Portfolio_Value_After': [
                Decimal('9500.00'),   # QQQ BUY: portfolio drops
                Decimal('9500.00'),   # QQQ SELL: exit value (-5%)
                Decimal('9000.00'),   # TQQQ BUY: portfolio drops
                Decimal('9000.00')    # TQQQ SELL: exit value (-5.26%)
            ],
            'OOS_Period_ID': ['Window_001', 'Window_001', 'Window_001', 'Window_001']
        })

        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            losing_trades_df,
            Decimal('10000.00')
        )

        mc_df = pd.read_csv(mc_path)

        # Should have 2 completed trades
        assert len(mc_df) == 2

        # With fixed calculation using entry_value:
        # QQQ: (9500 - 10000) / 10000 = -5% (-0.05)
        # TQQQ: (9000 - 9500) / 9500 = -5.26% (-0.0526...)
        qqq_return = mc_df[mc_df['Symbol'] == 'QQQ']['Portfolio_Return_Percent'].iloc[0]
        tqqq_return = mc_df[mc_df['Symbol'] == 'TQQQ']['Portfolio_Return_Percent'].iloc[0]

        assert pytest.approx(qqq_return, rel=1e-4) == -0.05  # -5%
        assert pytest.approx(tqqq_return, rel=1e-3) == -0.0526  # -5.26%


    def test_monte_carlo_output_format(self, wfo_runner_mock, sample_trades_df):
        """Test that output CSV has correct 5-column format for Monte Carlo simulation."""
        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            sample_trades_df,
            Decimal('10000.00')
        )

        # Read CSV
        with open(mc_path, 'r') as f:
            lines = f.readlines()

        # Check header (5 columns in specific order)
        expected_header = 'Portfolio_Return_Percent,Exit_Date,Entry_Date,Symbol,OOS_Period_ID'
        assert lines[0].strip() == expected_header

        # Check data rows (5 columns per row)
        for line in lines[1:]:
            parts = line.strip().split(',')
            assert len(parts) == 5  # Exactly 5 columns
            # Verify Portfolio_Return_Percent is a valid float
            float(parts[0])
            # Verify dates are present
            assert parts[1]  # Exit_Date
            assert parts[2]  # Entry_Date
            # Verify Symbol and OOS_Period_ID
            assert parts[3]  # Symbol
            assert parts[4]  # OOS_Period_ID


    def test_monte_carlo_statistics_logging(self, wfo_runner_mock, sample_trades_df, caplog):
        """Test that statistics are logged correctly."""
        import logging
        caplog.set_level(logging.INFO)

        wfo_runner_mock._generate_monte_carlo_input(
            sample_trades_df,
            Decimal('10000.00')
        )

        # Check that statistics were logged
        log_text = caplog.text
        assert 'Monte Carlo input statistics' in log_text
        assert 'mean=' in log_text
        assert 'std=' in log_text
        assert 'min=' in log_text
        assert 'max=' in log_text

    def test_monte_carlo_large_dataset(self, wfo_runner_mock):
        """Test Monte Carlo generation with realistic trade count."""
        # Generate 100 BUY/SELL pairs (200 rows total)
        import numpy as np
        np.random.seed(42)

        n_pairs = 100
        initial = Decimal('10000.00')
        
        dates = []
        tickers = []
        decisions = []
        portfolio_before = []
        portfolio_after = []
        
        current_value = initial
        
        for i in range(n_pairs):
            # BUY date
            buy_date = pd.Timestamp('2024-01-01') + pd.Timedelta(days=i*2)
            # SELL date
            sell_date = buy_date + pd.Timedelta(days=1)
            
            # Generate random return
            return_pct = Decimal(str(np.random.normal(0.01, 0.03)))
            next_value = current_value * (Decimal('1.0') + return_pct)
            
            # BUY row
            dates.append(buy_date)
            tickers.append('QQQ')
            decisions.append('BUY')
            portfolio_before.append(current_value)
            portfolio_after.append(current_value)
            
            # SELL row
            dates.append(sell_date)
            tickers.append('QQQ')
            decisions.append('SELL')
            portfolio_before.append(current_value)
            portfolio_after.append(next_value)
            
            current_value = next_value

        trades_df = pd.DataFrame({
            'Date': dates,
            'Ticker': tickers,
            'Decision': decisions,
            'Portfolio_Value_Before': portfolio_before,
            'Portfolio_Value_After': portfolio_after,
            'OOS_Period_ID': ['Window_001'] * len(dates)
        })

        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            trades_df,
            initial
        )

        mc_df = pd.read_csv(mc_path)

        # Validate (should have 100 completed trades)
        assert len(mc_df) == n_pairs
        assert mc_df['Portfolio_Return_Percent'].isna().sum() == 0
        
        # Check all 5 columns exist
        expected_columns = ['Portfolio_Return_Percent', 'Exit_Date', 'Entry_Date', 'Symbol', 'OOS_Period_ID']
        assert list(mc_df.columns) == expected_columns

        # Check statistics are reasonable
        mean_return = mc_df['Portfolio_Return_Percent'].mean()
        assert -0.1 < mean_return < 0.1  # Within reasonable bounds


    def test_monte_carlo_integration_with_generate_outputs(
        self,
        wfo_runner_mock,
        sample_trades_df,
        temp_output_dir
    ):
        """Test integration of Monte Carlo generation in _generate_outputs()."""
        from jutsu_engine.application.wfo_runner import WindowResult, WFOWindow
        from datetime import datetime

        # Create mock window result
        window = WFOWindow(
            window_id=1,
            is_start=datetime(2024, 1, 1),
            is_end=datetime(2024, 6, 30),
            oos_start=datetime(2024, 7, 1),
            oos_end=datetime(2024, 12, 31)
        )

        window_result = WindowResult(
            window=window,
            best_params={'ema_period': 20},
            metric_value=1.5,
            oos_trades=sample_trades_df,
            oos_metrics={'total_return': 0.0489, 'sharpe_ratio': 1.2}
        )

        # Call _generate_outputs
        outputs = wfo_runner_mock._generate_outputs([window_result])

        # Validate Monte Carlo file was created
        assert 'monte_carlo_input' in outputs['output_files']
        mc_path = Path(outputs['output_files']['monte_carlo_input'])
        assert mc_path.exists()

        # Validate content (5 columns, 2 completed trades)
        mc_df = pd.read_csv(mc_path)
        expected_columns = ['Portfolio_Return_Percent', 'Exit_Date', 'Entry_Date', 'Symbol', 'OOS_Period_ID']
        assert list(mc_df.columns) == expected_columns


class TestMonteCarloEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def wfo_runner_mock(self):
        """Create mock runner for edge case testing."""
        import tempfile
        temp_dir = Path(tempfile.mkdtemp())

        config_path = temp_dir / "test_config.yaml"
        config_content = """
strategy: MACD_Trend_v4
symbol_sets:
  - signal_symbol: QQQ
    bull_symbol: TQQQ
    defense_symbol: BIL
base_config:
  initial_capital: 10000
parameters:
  ema_period: [20]
walk_forward:
  total_start_date: '2020-01-01'
  total_end_date: '2024-12-31'
  window_size_years: 2
  in_sample_years: 1
  out_of_sample_years: 1
  slide_years: 1
  selection_metric: sharpe_ratio
"""
        with open(config_path, 'w') as f:
            f.write(config_content)

        runner = WFORunner(str(config_path), output_dir=str(temp_dir))

        yield runner

        shutil.rmtree(temp_dir)

    def test_zero_return_trades(self, wfo_runner_mock):
        """Test trades with exactly 0% return."""
        # BUY at 10000, SELL at 10000 = 0% return (break-even after costs)
        trades_df = pd.DataFrame({
            'Date': pd.to_datetime(['2024-01-15', '2024-01-22', '2024-02-01', '2024-02-05']),
            'Ticker': ['QQQ', 'QQQ', 'TQQQ', 'TQQQ'],
            'Decision': ['BUY', 'SELL', 'BUY', 'SELL'],
            'Portfolio_Value_Before': [
                Decimal('10000.00'),  # BUY: entry value
                Decimal('10000.00'),  # SELL: (unused, we use entry_value)
                Decimal('10000.00'),  # BUY: entry value
                Decimal('10000.00')   # SELL: (unused, we use entry_value)
            ],
            'Portfolio_Value_After': [
                Decimal('10000.00'),  # BUY: no change
                Decimal('10000.00'),  # SELL: exit value (same as entry)
                Decimal('10000.00'),  # BUY: no change
                Decimal('10000.00')   # SELL: exit value (same as entry)
            ],
            'OOS_Period_ID': ['Window_001', 'Window_001', 'Window_001', 'Window_001']
        })

        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            trades_df,
            Decimal('10000.00')
        )

        mc_df = pd.read_csv(mc_path)
        assert len(mc_df) == 2  # 2 completed trades
        # QQQ: (10000 - 10000) / 10000 = 0.0
        # TQQQ: (10000 - 10000) / 10000 = 0.0
        assert all(mc_df['Portfolio_Return_Percent'] == 0.0)


    def test_extreme_returns(self, wfo_runner_mock):
        """Test very large positive and negative returns."""
        trades_df = pd.DataFrame({
            'Date': pd.to_datetime(['2024-01-15', '2024-01-22', '2024-02-01', '2024-02-05']),
            'Ticker': ['QQQ', 'QQQ', 'TQQQ', 'TQQQ'],
            'Decision': ['BUY', 'SELL', 'BUY', 'SELL'],
            'Portfolio_Value_Before': [
                Decimal('10000.00'),  # QQQ BUY: entry value
                Decimal('20000.00'),  # QQQ SELL: (unused, we use entry_value from BUY)
                Decimal('20000.00'),  # TQQQ BUY: entry value
                Decimal('10000.00')   # TQQQ SELL: (unused, we use entry_value from BUY)
            ],
            'Portfolio_Value_After': [
                Decimal('20000.00'),  # QQQ BUY: portfolio grows (but no trade yet)
                Decimal('20000.00'),  # QQQ SELL: exit value (+100% return)
                Decimal('10000.00'),  # TQQQ BUY: portfolio shrinks (but no trade yet)
                Decimal('10000.00')   # TQQQ SELL: exit value (-50% return)
            ],
            'OOS_Period_ID': ['Window_001', 'Window_001', 'Window_001', 'Window_001']
        })

        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            trades_df,
            Decimal('10000.00')
        )

        mc_df = pd.read_csv(mc_path)

        # Validate extreme returns
        assert len(mc_df) == 2

        # With fixed calculation using entry_value:
        # QQQ: (20000 - 10000) / 10000 = +100% (1.0)
        # TQQQ: (10000 - 20000) / 20000 = -50% (-0.5)
        qqq_return = mc_df[mc_df['Symbol'] == 'QQQ']['Portfolio_Return_Percent'].iloc[0]
        tqqq_return = mc_df[mc_df['Symbol'] == 'TQQQ']['Portfolio_Return_Percent'].iloc[0]

        assert pytest.approx(qqq_return, rel=1e-4) == 1.0  # +100%
        assert pytest.approx(tqqq_return, rel=1e-4) == -0.5  # -50%


    def test_precision_preservation(self, wfo_runner_mock):
        """Test that precision is preserved for small returns."""
        # Very small returns (0.01% and 0.01%)
        trades_df = pd.DataFrame({
            'Date': pd.to_datetime(['2024-01-15', '2024-01-22', '2024-02-01', '2024-02-05']),
            'Ticker': ['QQQ', 'QQQ', 'TQQQ', 'TQQQ'],
            'Decision': ['BUY', 'SELL', 'BUY', 'SELL'],
            'Portfolio_Value_Before': [
                Decimal('10000.0000'),  # QQQ BUY: entry value
                Decimal('10001.0000'),  # QQQ SELL: (unused, we use entry_value)
                Decimal('10001.0000'),  # TQQQ BUY: entry value
                Decimal('10002.0001')   # TQQQ SELL: (unused, we use entry_value)
            ],
            'Portfolio_Value_After': [
                Decimal('10001.0000'),  # QQQ BUY: portfolio grows
                Decimal('10001.0000'),  # QQQ SELL: exit value (+0.01%)
                Decimal('10002.0001'),  # TQQQ BUY: portfolio grows
                Decimal('10002.0001')   # TQQQ SELL: exit value (+0.01%)
            ],
            'OOS_Period_ID': ['Window_001', 'Window_001', 'Window_001', 'Window_001']
        })

        mc_path = wfo_runner_mock._generate_monte_carlo_input(
            trades_df,
            Decimal('10000.00')
        )

        mc_df = pd.read_csv(mc_path)

        # Should have 2 completed trades
        assert len(mc_df) == 2

        # With fixed calculation using entry_value:
        # QQQ: (10001 - 10000) / 10000 = +0.01% (0.0001)
        # TQQQ: (10002.0001 - 10001) / 10001 = +0.01% (0.00010000...)
        qqq_return = mc_df[mc_df['Symbol'] == 'QQQ']['Portfolio_Return_Percent'].iloc[0]
        tqqq_return = mc_df[mc_df['Symbol'] == 'TQQQ']['Portfolio_Return_Percent'].iloc[0]

        assert pytest.approx(qqq_return, rel=1e-4) == 0.0001  # +0.01%
        assert pytest.approx(tqqq_return, rel=1e-4) == 0.0001  # +0.01%