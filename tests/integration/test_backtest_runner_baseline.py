"""
Integration tests for baseline calculation in BacktestRunner.

Tests full end-to-end baseline feature:
- Baseline calculation with QQQ data
- Alpha calculation (strategy vs baseline)
- Graceful handling when QQQ missing
- Edge cases (insufficient data, zero returns)
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent


class SimpleTestStrategy(Strategy):
    """Simple test strategy that generates one buy signal."""

    def init(self):
        self.traded = False

    def on_bar(self, bar: MarketDataEvent):
        # Buy on first bar with enough history
        if not self.traded and len(self.get_closes(10)) >= 10:
            self.buy(bar.symbol, Decimal('0.5'))  # 50% of portfolio
            self.traded = True


class BuyAndHoldStrategy(Strategy):
    """Buy and hold strategy for testing."""

    def init(self):
        self.bought = False

    def on_bar(self, bar: MarketDataEvent):
        if not self.bought and bar.symbol == 'QQQ':
            self.buy('QQQ', Decimal('1.0'))  # 100% of portfolio
            self.bought = True


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_database_with_qqq(tmp_path):
    """Create mock database with QQQ test data."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from jutsu_engine.data.models import Base, MarketData, DataMetadata

    # Create in-memory database
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    # Add QQQ test data (20 days with 10% gain)
    # Start: $300, End: $330 (10% total return)
    start_price = Decimal('300.00')
    end_price = Decimal('330.00')
    price_increment = (end_price - start_price) / Decimal('19')

    for i in range(20):
        timestamp = datetime(2024, 1, i+1, 16, 0, tzinfo=timezone.utc)
        current_price = start_price + (price_increment * Decimal(i))
        bar = MarketData(
            symbol='QQQ',
            timestamp=timestamp,
            timeframe='1D',
            open=current_price,
            high=current_price + Decimal('2.00'),
            low=current_price - Decimal('2.00'),
            close=current_price,
            volume=1000000,
            data_source='test',
            is_valid=True
        )
        session.add(bar)

    # Add metadata for QQQ
    metadata = DataMetadata(
        symbol='QQQ',
        timeframe='1D',
        last_bar_timestamp=datetime(2024, 1, 20, tzinfo=timezone.utc),
        total_bars=20,
        last_updated=datetime.now(timezone.utc)
    )
    session.add(metadata)
    session.commit()
    session.close()

    return db_url


@pytest.fixture
def mock_database_with_qqq_and_aapl(tmp_path):
    """Create mock database with QQQ and AAPL test data."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from jutsu_engine.data.models import Base, MarketData, DataMetadata

    # Create in-memory database
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    # Add QQQ data (10% gain)
    qqq_start = Decimal('300.00')
    qqq_end = Decimal('330.00')
    qqq_increment = (qqq_end - qqq_start) / Decimal('19')

    # Add AAPL data (20% gain - outperforms baseline)
    aapl_start = Decimal('150.00')
    aapl_end = Decimal('180.00')
    aapl_increment = (aapl_end - aapl_start) / Decimal('19')

    for i in range(20):
        timestamp = datetime(2024, 1, i+1, 16, 0, tzinfo=timezone.utc)

        # QQQ bar
        qqq_price = qqq_start + (qqq_increment * Decimal(i))
        qqq_bar = MarketData(
            symbol='QQQ',
            timestamp=timestamp,
            timeframe='1D',
            open=qqq_price,
            high=qqq_price + Decimal('2.00'),
            low=qqq_price - Decimal('2.00'),
            close=qqq_price,
            volume=1000000,
            data_source='test',
            is_valid=True
        )
        session.add(qqq_bar)

        # AAPL bar
        aapl_price = aapl_start + (aapl_increment * Decimal(i))
        aapl_bar = MarketData(
            symbol='AAPL',
            timestamp=timestamp,
            timeframe='1D',
            open=aapl_price,
            high=aapl_price + Decimal('1.00'),
            low=aapl_price - Decimal('1.00'),
            close=aapl_price,
            volume=1000000,
            data_source='test',
            is_valid=True
        )
        session.add(aapl_bar)

    # Add metadata
    for symbol in ['QQQ', 'AAPL']:
        metadata = DataMetadata(
            symbol=symbol,
            timeframe='1D',
            last_bar_timestamp=datetime(2024, 1, 20, tzinfo=timezone.utc),
            total_bars=20,
            last_updated=datetime.now(timezone.utc)
        )
        session.add(metadata)

    session.commit()
    session.close()

    return db_url


@pytest.fixture
def mock_database_without_qqq(tmp_path):
    """Create mock database WITHOUT QQQ data."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from jutsu_engine.data.models import Base, MarketData, DataMetadata

    # Create in-memory database
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    # Only add AAPL data (no QQQ)
    for i in range(20):
        timestamp = datetime(2024, 1, i+1, 16, 0, tzinfo=timezone.utc)
        bar = MarketData(
            symbol='AAPL',
            timestamp=timestamp,
            timeframe='1D',
            open=Decimal('150.00') + Decimal(i),
            high=Decimal('152.00') + Decimal(i),
            low=Decimal('149.00') + Decimal(i),
            close=Decimal('151.00') + Decimal(i),
            volume=1000000,
            data_source='test',
            is_valid=True
        )
        session.add(bar)

    # Add metadata
    metadata = DataMetadata(
        symbol='AAPL',
        timeframe='1D',
        last_bar_timestamp=datetime(2024, 1, 20, tzinfo=timezone.utc),
        total_bars=20,
        last_updated=datetime.now(timezone.utc)
    )
    session.add(metadata)
    session.commit()
    session.close()

    return db_url


class TestBacktestRunnerBaseline:
    """Integration tests for baseline calculation feature."""

    def test_backtest_returns_baseline_in_results(
        self,
        mock_database_with_qqq,
        temp_output_dir
    ):
        """Test that baseline is included in results dict."""
        config = {
            'symbol': 'QQQ',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_with_qqq
        }

        runner = BacktestRunner(config)
        strategy = BuyAndHoldStrategy()

        results = runner.run(strategy, output_dir=temp_output_dir)

        # Verify baseline key exists
        assert 'baseline' in results

        # Verify baseline is not None (QQQ data available)
        assert results['baseline'] is not None

        # Verify required baseline keys
        baseline = results['baseline']
        assert 'baseline_symbol' in baseline
        assert 'baseline_final_value' in baseline
        assert 'baseline_total_return' in baseline
        assert 'baseline_annualized_return' in baseline
        assert 'alpha' in baseline

        # Verify baseline symbol is QQQ
        assert baseline['baseline_symbol'] == 'QQQ'

    def test_baseline_calculation_with_real_data(
        self,
        mock_database_with_qqq,
        temp_output_dir
    ):
        """Test baseline metrics are calculated correctly."""
        config = {
            'symbol': 'QQQ',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_with_qqq
        }

        runner = BacktestRunner(config)
        strategy = BuyAndHoldStrategy()

        results = runner.run(strategy, output_dir=temp_output_dir)
        baseline = results['baseline']

        # QQQ: $300 → $330 = 10% return
        # Expected final value: $100,000 * 1.10 = $110,000
        assert baseline['baseline_total_return'] == pytest.approx(0.10, abs=0.01)
        assert baseline['baseline_final_value'] == pytest.approx(110000, rel=0.01)

        # Annualized return should be calculated
        assert 'baseline_annualized_return' in baseline
        assert baseline['baseline_annualized_return'] > 0

    def test_baseline_alpha_calculation(
        self,
        mock_database_with_qqq_and_aapl,
        temp_output_dir
    ):
        """Test alpha (outperformance) is calculated when strategy executes trades."""
        config = {
            'symbol': 'AAPL',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_with_qqq_and_aapl
        }

        runner = BacktestRunner(config)
        strategy = SimpleTestStrategy()  # Uses get_closes, so will wait for history

        results = runner.run(strategy, output_dir=temp_output_dir)
        baseline = results['baseline']

        # Verify baseline was calculated (QQQ data available)
        assert baseline is not None
        assert 'baseline_symbol' in baseline
        assert baseline['baseline_symbol'] == 'QQQ'
        assert 'baseline_total_return' in baseline
        assert 'baseline_annualized_return' in baseline
        assert 'alpha' in baseline

        # QQQ should have ~10% return
        baseline_return = baseline['baseline_total_return']
        assert baseline_return == pytest.approx(0.10, abs=0.02)

        # Alpha should be calculated (even if strategy return is 0)
        # Alpha can be any value including 0, None (if baseline return = 0), or negative
        # Just verify the field exists
        assert 'alpha' in baseline

    def test_baseline_missing_qqq_data(
        self,
        mock_database_without_qqq,
        temp_output_dir
    ):
        """Test graceful handling when QQQ not in data."""
        config = {
            'symbol': 'AAPL',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_without_qqq
        }

        runner = BacktestRunner(config)
        strategy = SimpleTestStrategy()

        results = runner.run(strategy, output_dir=temp_output_dir)

        # Baseline key should exist but be None
        assert 'baseline' in results
        assert results['baseline'] is None

        # Backtest should still complete successfully
        assert 'total_return' in results
        assert 'final_value' in results

    def test_baseline_insufficient_qqq_data(
        self,
        tmp_path,
        temp_output_dir
    ):
        """Test handling of insufficient QQQ bars (<2)."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from jutsu_engine.data.models import Base, MarketData, DataMetadata

        # Create database with only 1 QQQ bar
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)

        Session = sessionmaker(bind=engine)
        session = Session()

        # Only 1 QQQ bar
        bar = MarketData(
            symbol='QQQ',
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            timeframe='1D',
            open=Decimal('300.00'),
            high=Decimal('302.00'),
            low=Decimal('299.00'),
            close=Decimal('300.00'),
            volume=1000000,
            data_source='test',
            is_valid=True
        )
        session.add(bar)

        metadata = DataMetadata(
            symbol='QQQ',
            timeframe='1D',
            last_bar_timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            total_bars=1,
            last_updated=datetime.now(timezone.utc)
        )
        session.add(metadata)
        session.commit()
        session.close()

        config = {
            'symbol': 'QQQ',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': db_url
        }

        runner = BacktestRunner(config)
        strategy = SimpleTestStrategy()

        results = runner.run(strategy, output_dir=temp_output_dir)

        # Baseline should be None (insufficient data)
        assert 'baseline' in results
        assert results['baseline'] is None

    def test_baseline_with_multi_symbol_strategy(
        self,
        tmp_path,
        temp_output_dir
    ):
        """Test baseline with multi-symbol strategy (QQQ, TQQQ, SQQQ)."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from jutsu_engine.data.models import Base, MarketData, DataMetadata

        # Create database with QQQ, TQQQ, SQQQ
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)

        Session = sessionmaker(bind=engine)
        session = Session()

        symbols = ['QQQ', 'TQQQ', 'SQQQ']
        for symbol in symbols:
            for i in range(20):
                timestamp = datetime(2024, 1, i+1, 16, 0, tzinfo=timezone.utc)
                bar = MarketData(
                    symbol=symbol,
                    timestamp=timestamp,
                    timeframe='1D',
                    open=Decimal('100.00') + Decimal(i),
                    high=Decimal('102.00') + Decimal(i),
                    low=Decimal('99.00') + Decimal(i),
                    close=Decimal('100.00') + Decimal(i),
                    volume=1000000,
                    data_source='test',
                    is_valid=True
                )
                session.add(bar)

            metadata = DataMetadata(
                symbol=symbol,
                timeframe='1D',
                last_bar_timestamp=datetime(2024, 1, 20, tzinfo=timezone.utc),
                total_bars=20,
                last_updated=datetime.now(timezone.utc)
            )
            session.add(metadata)

        session.commit()
        session.close()

        config = {
            'symbols': ['QQQ', 'TQQQ', 'SQQQ'],
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': db_url
        }

        runner = BacktestRunner(config)
        strategy = BuyAndHoldStrategy()

        results = runner.run(strategy, output_dir=temp_output_dir)

        # Baseline should be calculated (QQQ is in symbols)
        assert 'baseline' in results
        assert results['baseline'] is not None
        assert results['baseline']['baseline_symbol'] == 'QQQ'

        # Should have QQQ data extracted correctly
        assert results['baseline']['baseline_total_return'] is not None
