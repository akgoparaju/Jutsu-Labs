"""
Unit tests for Strategy Runner.

Tests live strategy execution on market data.
"""

import pytest
import pandas as pd
from decimal import Decimal
from pathlib import Path

from jutsu_engine.live.strategy_runner import LiveStrategyRunner


@pytest.fixture
def sample_market_data():
    """Create sample market data for testing."""
    dates = pd.date_range('2025-11-01', periods=200, tz='UTC')

    return {
        'QQQ': pd.DataFrame({
            'date': dates,
            'open': [500.0] * 200,
            'high': [505.0] * 200,
            'low': [495.0] * 200,
            'close': [502.0 + i for i in range(200)],
            'volume': [1000000] * 200
        }),
        'TLT': pd.DataFrame({
            'date': dates,
            'open': [100.0] * 200,
            'high': [102.0] * 200,
            'low': [98.0] * 200,
            'close': [100.0 + (i * 0.1) for i in range(200)],
            'volume': [500000] * 200
        })
    }


class TestStrategyRunner:
    """Test suite for LiveStrategyRunner class."""

    def test_initialization(self):
        """Test that strategy runner initializes correctly."""
        runner = LiveStrategyRunner()

        assert runner.strategy is not None
        assert runner.config is not None

    def test_calculate_signals(self, sample_market_data):
        """Test signal calculation from market data."""
        runner = LiveStrategyRunner()

        signals = runner.calculate_signals(sample_market_data)

        assert 'trend_state' in signals
        assert 'bond_trend_state' in signals
        assert 'vol_state' in signals
        assert 'current_cell' in signals
        assert 'timestamp' in signals

        # Vol state should be valid
        assert signals['vol_state'] in [-1, 0, 1]

        # Current cell should be 1-6
        assert 1 <= signals['current_cell'] <= 6

    def test_determine_target_allocation(self, sample_market_data):
        """Test target allocation determination."""
        runner = LiveStrategyRunner()

        signals = runner.calculate_signals(sample_market_data)
        equity = Decimal('100000')

        allocation = runner.determine_target_allocation(signals, equity)

        assert isinstance(allocation, dict)

        # Weights should sum to ~1.0
        total_weight = sum(allocation.values())
        assert 0.99 <= total_weight <= 1.01

        # All weights should be 0-1
        for symbol, weight in allocation.items():
            assert 0 <= weight <= 1

    def test_get_strategy_state(self, sample_market_data):
        """Test strategy state retrieval."""
        runner = LiveStrategyRunner()

        runner.calculate_signals(sample_market_data)
        state = runner.get_strategy_state()

        assert 'vol_state' in state
        assert 'current_cell' in state
        assert 'equity_trend' in state
        assert 'bond_trend' in state
        assert 'current_allocation' in state
