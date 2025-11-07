"""
Unit tests for Momentum_ATR strategy.

Tests regime detection, regime transitions, multi-symbol handling,
VIX kill switch, stop-loss checking, and edge cases.
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from jutsu_engine.strategies.Momentum_ATR import Momentum_ATR
from jutsu_engine.core.events import MarketDataEvent


class TestMomentumATRRegimeDetection:
    """Test regime detection logic."""

    def test_regime_1_risk_off_vix_kill_switch(self):
        """Test Regime 1: Risk-Off / Kill-Switch (VIX > 30)."""
        strategy = Momentum_ATR()
        strategy.init()

        # VIX > 30 should trigger kill switch regardless of other indicators
        regime = strategy._determine_regime(
            vix=Decimal('35.00'),
            histogram=Decimal('0.05'),  # Positive histogram
            histogram_delta=Decimal('0.01')  # Positive delta
        )
        assert regime == 1

    def test_regime_2_strong_bull(self):
        """Test Regime 2: Strong Bull (VIX ≤ 30, Histogram > 0, Delta > 0)."""
        strategy = Momentum_ATR()
        strategy.init()

        regime = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')
        )
        assert regime == 2

    def test_regime_3_waning_bull(self):
        """Test Regime 3: Waning Bull (VIX ≤ 30, Histogram > 0, Delta ≤ 0)."""
        strategy = Momentum_ATR()
        strategy.init()

        # Positive histogram but non-positive delta
        regime = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('-0.01')
        )
        assert regime == 3

        # Delta exactly zero
        regime_zero = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.00')
        )
        assert regime_zero == 3

    def test_regime_4_strong_bear(self):
        """Test Regime 4: Strong Bear (VIX ≤ 30, Histogram < 0, Delta < 0)."""
        strategy = Momentum_ATR()
        strategy.init()

        regime = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('-0.05'),
            histogram_delta=Decimal('-0.01')
        )
        assert regime == 4

    def test_regime_5_waning_bear(self):
        """Test Regime 5: Waning Bear (VIX ≤ 30, Histogram < 0, Delta ≥ 0)."""
        strategy = Momentum_ATR()
        strategy.init()

        # Negative histogram but non-negative delta
        regime = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('-0.05'),
            histogram_delta=Decimal('0.01')
        )
        assert regime == 5

        # Delta exactly zero
        regime_zero = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('-0.05'),
            histogram_delta=Decimal('0.00')
        )
        assert regime_zero == 5

    def test_regime_6_neutral(self):
        """Test Regime 6: Neutral / Flat (Histogram = 0)."""
        strategy = Momentum_ATR()
        strategy.init()

        # Histogram exactly zero
        regime = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.00'),
            histogram_delta=Decimal('0.01')
        )
        assert regime == 6

    def test_vix_boundary_at_30(self):
        """Test VIX threshold boundary at 30."""
        strategy = Momentum_ATR()
        strategy.init()

        # VIX exactly at 30 (should NOT trigger kill switch)
        regime_at = strategy._determine_regime(
            vix=Decimal('30.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')
        )
        assert regime_at == 2  # Strong Bull (not kill switch)

        # VIX just above 30 (should trigger kill switch)
        regime_above = strategy._determine_regime(
            vix=Decimal('30.01'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')
        )
        assert regime_above == 1  # Risk-Off

    def test_histogram_boundary_at_zero(self):
        """Test histogram boundary at zero."""
        strategy = Momentum_ATR()
        strategy.init()

        # Histogram slightly positive
        regime_pos = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.0001'),
            histogram_delta=Decimal('0.01')
        )
        assert regime_pos == 2  # Strong Bull

        # Histogram exactly zero
        regime_zero = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.00'),
            histogram_delta=Decimal('0.01')
        )
        assert regime_zero == 6  # Neutral

        # Histogram slightly negative
        regime_neg = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('-0.0001'),
            histogram_delta=Decimal('-0.01')
        )
        assert regime_neg == 4  # Strong Bear

    def test_delta_boundary_at_zero(self):
        """Test histogram delta boundary at zero."""
        strategy = Momentum_ATR()
        strategy.init()

        # Positive histogram with delta > 0
        regime_pos_delta = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.0001')
        )
        assert regime_pos_delta == 2  # Strong Bull

        # Positive histogram with delta = 0
        regime_zero_delta = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.00')
        )
        assert regime_zero_delta == 3  # Waning Bull

        # Positive histogram with delta < 0
        regime_neg_delta = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('-0.0001')
        )
        assert regime_neg_delta == 3  # Waning Bull

    def test_vix_kill_switch_overrides_all(self):
        """Test that VIX kill switch has highest priority."""
        strategy = Momentum_ATR()
        strategy.init()

        # Even with perfect bull signals, VIX > 30 → CASH
        regime = strategy._determine_regime(
            vix=Decimal('40.00'),
            histogram=Decimal('1.00'),  # Very strong positive
            histogram_delta=Decimal('0.50')  # Very strong positive delta
        )
        assert regime == 1  # Risk-Off (not bull)

        # Even with perfect bear signals, VIX > 30 → CASH
        regime_bear = strategy._determine_regime(
            vix=Decimal('40.00'),
            histogram=Decimal('-1.00'),  # Very strong negative
            histogram_delta=Decimal('-0.50')  # Very strong negative delta
        )
        assert regime_bear == 1  # Risk-Off (not bear)


class TestMomentumATRParameterization:
    """Test strategy parameterization."""

    def test_custom_macd_parameters(self):
        """Test custom MACD parameters."""
        strategy = Momentum_ATR(
            macd_fast_period=10,
            macd_slow_period=20,
            macd_signal_period=5
        )
        strategy.init()

        assert strategy.macd_fast_period == 10
        assert strategy.macd_slow_period == 20
        assert strategy.macd_signal_period == 5

    def test_custom_vix_kill_switch(self):
        """Test custom VIX kill switch level."""
        strategy = Momentum_ATR(vix_kill_switch=Decimal('25.0'))
        strategy.init()

        # VIX > custom threshold (25) should trigger kill switch
        regime = strategy._determine_regime(
            vix=Decimal('26.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')
        )
        assert regime == 1

        # VIX ≤ custom threshold should allow normal regimes
        regime_normal = strategy._determine_regime(
            vix=Decimal('24.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')
        )
        assert regime_normal == 2  # Strong Bull

    def test_custom_atr_parameters(self):
        """Test custom ATR parameters."""
        strategy = Momentum_ATR(
            atr_period=20,
            atr_stop_multiplier=Decimal('3.0')
        )
        strategy.init()

        assert strategy.atr_period == 20
        assert strategy.atr_stop_multiplier == Decimal('3.0')

    def test_custom_risk_parameters(self):
        """Test custom risk parameters."""
        strategy = Momentum_ATR(
            risk_strong_trend=Decimal('0.05'),  # 5%
            risk_waning_trend=Decimal('0.02')   # 2%
        )
        strategy.init()

        assert strategy.risk_strong_trend == Decimal('0.05')
        assert strategy.risk_waning_trend == Decimal('0.02')

    def test_default_parameters(self):
        """Test default parameter values match specification."""
        strategy = Momentum_ATR()
        strategy.init()

        # MACD defaults
        assert strategy.macd_fast_period == 12
        assert strategy.macd_slow_period == 26
        assert strategy.macd_signal_period == 9

        # VIX default
        assert strategy.vix_kill_switch == Decimal('30.0')

        # ATR defaults
        assert strategy.atr_period == 14
        assert strategy.atr_stop_multiplier == Decimal('2.0')

        # Risk defaults
        assert strategy.risk_strong_trend == Decimal('0.03')  # 3.0%
        assert strategy.risk_waning_trend == Decimal('0.015')  # 1.5%


class TestMomentumATRSymbolValidation:
    """Test symbol validation logic."""

    def _create_test_bars(self, symbols, num_bars=50):
        """Helper function to create test bars for multiple symbols."""
        bars = []
        base_time = datetime(2025, 1, 1, 9, 30, 0, tzinfo=timezone.utc)
        for i in range(num_bars):
            for symbol in symbols:
                bar = MarketDataEvent(
                    symbol=symbol,
                    timestamp=base_time + timedelta(days=i),
                    open=Decimal('100.00'),
                    high=Decimal('101.00'),
                    low=Decimal('99.00'),
                    close=Decimal('100.50'),
                    volume=1000000,
                    timeframe='1D'
                )
                bars.append(bar)
        return bars

    def test_validation_passes_with_all_symbols(self):
        """Test that validation succeeds when all 4 required symbols are present."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with all 4 required symbols
        bars = self._create_test_bars(['QQQ', '$VIX', 'TQQQ', 'SQQQ'], 50)
        for bar in bars:
            strategy._update_bar(bar)

        # Validation should pass without error
        strategy._validate_required_symbols()
        assert True  # If we get here, validation passed

    def test_validation_fails_missing_vix(self):
        """Test that validation fails when $VIX is missing."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with only 3 symbols (missing $VIX)
        bars = self._create_test_bars(['QQQ', 'TQQQ', 'SQQQ'], 50)
        for bar in bars:
            strategy._update_bar(bar)

        # Validation should fail with clear error
        with pytest.raises(ValueError, match=r"missing.*\$VIX"):
            strategy._validate_required_symbols()

    def test_validation_fails_missing_qqq(self):
        """Test that validation fails when QQQ is missing."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with only 3 symbols (missing QQQ)
        bars = self._create_test_bars(['$VIX', 'TQQQ', 'SQQQ'], 50)
        for bar in bars:
            strategy._update_bar(bar)

        # Validation should fail with clear error
        with pytest.raises(ValueError, match=r"missing.*QQQ"):
            strategy._validate_required_symbols()

    def test_validation_fails_missing_tqqq(self):
        """Test that validation fails when TQQQ is missing."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with only 3 symbols (missing TQQQ)
        bars = self._create_test_bars(['QQQ', '$VIX', 'SQQQ'], 50)
        for bar in bars:
            strategy._update_bar(bar)

        # Validation should fail with clear error
        with pytest.raises(ValueError, match=r"missing.*TQQQ"):
            strategy._validate_required_symbols()

    def test_validation_fails_missing_sqqq(self):
        """Test that validation fails when SQQQ is missing."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with only 3 symbols (missing SQQQ)
        bars = self._create_test_bars(['QQQ', '$VIX', 'TQQQ'], 50)
        for bar in bars:
            strategy._update_bar(bar)

        # Validation should fail with clear error
        with pytest.raises(ValueError, match=r"missing.*SQQQ"):
            strategy._validate_required_symbols()

    def test_validation_fails_multiple_missing(self):
        """Test that validation fails and lists all missing symbols."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with only QQQ (missing 3 symbols)
        bars = self._create_test_bars(['QQQ'], 50)
        for bar in bars:
            strategy._update_bar(bar)

        # Validation should fail and show all missing symbols
        with pytest.raises(ValueError) as exc_info:
            strategy._validate_required_symbols()

        # Check error message includes missing symbols
        error_msg = str(exc_info.value)
        assert '$VIX' in error_msg
        assert 'TQQQ' in error_msg
        assert 'SQQQ' in error_msg
        assert 'missing' in error_msg

    def test_validation_error_shows_available_symbols(self):
        """Test that validation error shows which symbols are available."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with only QQQ
        bars = self._create_test_bars(['QQQ'], 50)
        for bar in bars:
            strategy._update_bar(bar)

        # Validation should show available symbols in error
        with pytest.raises(ValueError) as exc_info:
            strategy._validate_required_symbols()

        error_msg = str(exc_info.value)
        assert 'Available symbols:' in error_msg
        assert 'QQQ' in error_msg

    def test_validation_runs_on_bar(self):
        """Test that validation automatically runs during on_bar()."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with missing $VIX
        bars = self._create_test_bars(['QQQ', 'TQQQ', 'SQQQ'], 50)
        for bar in bars:
            strategy._update_bar(bar)

        # Call on_bar - should trigger validation and raise error
        last_bar = strategy._bars[-1]
        with pytest.raises(ValueError, match=r"missing.*\$VIX"):
            strategy.on_bar(last_bar)

    def test_validation_only_runs_once(self):
        """Test that validation only runs once, not on every bar."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create bars with all symbols
        bars = self._create_test_bars(['QQQ', '$VIX', 'TQQQ', 'SQQQ'], 100)
        for bar in bars:
            strategy._update_bar(bar)

        # Validation should not have run yet
        assert not strategy._symbols_validated

        # Call on_bar once - validation should run
        strategy.on_bar(strategy._bars[-1])
        assert strategy._symbols_validated

        # Call on_bar again - validation should not run again
        # (We can't easily test this without mocking, but we verified the flag is set)


class TestMomentumATRSymbolHandling:
    """Test multi-symbol handling."""

    def test_signal_symbols(self):
        """Test signal and trading symbols are correctly configured."""
        strategy = Momentum_ATR()
        strategy.init()

        assert strategy.signal_symbol == 'QQQ'
        assert strategy.vix_symbol == '$VIX'  # Index symbols use $ prefix
        assert strategy.bull_symbol == 'TQQQ'
        assert strategy.bear_symbol == 'SQQQ'

    def test_ignores_non_qqq_bars_for_regime(self):
        """Test that strategy ignores non-QQQ bars for regime calculation."""
        strategy = Momentum_ATR()
        strategy.init()

        # Create TQQQ bar (should be ignored for regime calculation)
        tqqq_bar = MarketDataEvent(
            symbol='TQQQ',
            timestamp=datetime(2025, 1, 1, 9, 30, 0, tzinfo=timezone.utc),
            open=Decimal('50.00'),
            high=Decimal('51.00'),
            low=Decimal('49.50'),
            close=Decimal('50.50'),
            volume=1000000,
            timeframe='1D'
        )

        # Call on_bar - should return early (no error, no regime change)
        strategy.on_bar(tqqq_bar)

        # Regime should still be None (never initialized)
        assert strategy.previous_regime is None


class TestMomentumATRStopLoss:
    """Test stop-loss functionality."""

    def test_stop_loss_initialization(self):
        """Test stop-loss state initialization."""
        strategy = Momentum_ATR()
        strategy.init()

        assert strategy.current_position_symbol is None
        assert strategy.entry_price is None
        assert strategy.stop_loss_price is None

    def test_stop_loss_cleared_on_liquidation(self):
        """Test stop-loss tracking is cleared when positions are liquidated."""
        strategy = Momentum_ATR()
        strategy.init()

        # Manually set position tracking (simulate entry)
        strategy.current_position_symbol = 'TQQQ'
        strategy.entry_price = Decimal('50.00')
        strategy.stop_loss_price = Decimal('48.00')

        # Liquidate all positions
        strategy._liquidate_all_positions()

        # Verify tracking cleared
        assert strategy.current_position_symbol is None
        assert strategy.entry_price is None
        assert strategy.stop_loss_price is None


class TestMomentumATREdgeCases:
    """Test edge cases and error handling."""

    def test_histogram_delta_first_calculation(self):
        """Test histogram delta calculation on first bar (no previous)."""
        strategy = Momentum_ATR()
        strategy.init()

        # First calculation with no previous histogram
        assert strategy.previous_histogram is None

        # After first on_bar, histogram delta should be 0 (no previous to compare)
        # This is handled in on_bar logic

    def test_negative_vix(self):
        """Test behavior with negative VIX (should not happen but test edge case)."""
        strategy = Momentum_ATR()
        strategy.init()

        # Negative VIX should not trigger kill switch
        regime = strategy._determine_regime(
            vix=Decimal('-5.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')
        )
        assert regime == 2  # Strong Bull (VIX not > 30)

    def test_very_large_vix(self):
        """Test behavior with extreme VIX values."""
        strategy = Momentum_ATR()
        strategy.init()

        # Very high VIX should trigger kill switch
        regime = strategy._determine_regime(
            vix=Decimal('100.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')
        )
        assert regime == 1  # Risk-Off

    def test_very_small_histogram_values(self):
        """Test behavior with very small (near-zero) histogram values."""
        strategy = Momentum_ATR()
        strategy.init()

        # Very small positive histogram
        regime_tiny_pos = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.00001'),
            histogram_delta=Decimal('0.000001')
        )
        assert regime_tiny_pos == 2  # Strong Bull (still > 0)

        # Very small negative histogram
        regime_tiny_neg = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('-0.00001'),
            histogram_delta=Decimal('-0.000001')
        )
        assert regime_tiny_neg == 4  # Strong Bear (still < 0)


class TestMomentumATRIntegration:
    """Integration tests with realistic scenarios."""

    def test_bull_to_bear_transition(self):
        """Test transition from bullish to bearish regime."""
        strategy = Momentum_ATR()
        strategy.init()

        # Start in strong bull
        strategy.previous_regime = 2

        # Transition to strong bear (VIX low, negative histogram)
        new_regime = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('-0.05'),
            histogram_delta=Decimal('-0.01')
        )

        assert new_regime == 4
        assert new_regime != strategy.previous_regime

    def test_normal_to_risk_off_transition(self):
        """Test transition to risk-off when VIX spikes."""
        strategy = Momentum_ATR()
        strategy.init()

        # Start in strong bull
        strategy.previous_regime = 2

        # VIX spikes → Risk-off
        new_regime = strategy._determine_regime(
            vix=Decimal('40.00'),  # Spike
            histogram=Decimal('0.05'),  # Still positive
            histogram_delta=Decimal('0.01')
        )

        assert new_regime == 1  # Risk-Off
        assert new_regime != strategy.previous_regime

    def test_risk_off_to_normal_transition(self):
        """Test transition from risk-off back to normal regime."""
        strategy = Momentum_ATR()
        strategy.init()

        # Start in risk-off
        strategy.previous_regime = 1

        # VIX drops back to normal
        new_regime = strategy._determine_regime(
            vix=Decimal('20.00'),  # Normal
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')
        )

        assert new_regime == 2  # Strong Bull
        assert new_regime != strategy.previous_regime

    def test_momentum_strengthening(self):
        """Test transition from waning to strong trend."""
        strategy = Momentum_ATR()
        strategy.init()

        # Start in waning bull
        strategy.previous_regime = 3

        # Momentum strengthens (delta becomes positive)
        new_regime = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('0.01')  # Delta now positive
        )

        assert new_regime == 2  # Strong Bull
        assert new_regime != strategy.previous_regime

    def test_momentum_weakening(self):
        """Test transition from strong to waning trend."""
        strategy = Momentum_ATR()
        strategy.init()

        # Start in strong bull
        strategy.previous_regime = 2

        # Momentum weakens (delta becomes negative)
        new_regime = strategy._determine_regime(
            vix=Decimal('20.00'),
            histogram=Decimal('0.05'),
            histogram_delta=Decimal('-0.01')  # Delta now negative
        )

        assert new_regime == 3  # Waning Bull
        assert new_regime != strategy.previous_regime


# Fixture for creating sample market data
@pytest.fixture
def sample_qqq_bar():
    """Create a sample QQQ bar."""
    return MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2025, 1, 1, 9, 30, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.50'),
        low=Decimal('399.50'),
        close=Decimal('401.00'),
        volume=5000000,
        timeframe='1D'
    )


@pytest.fixture
def sample_vix_bar():
    """Create a sample VIX bar."""
    return MarketDataEvent(
        symbol='$VIX',  # Index symbols use $ prefix to match database format
        timestamp=datetime(2025, 1, 1, 9, 30, 0, tzinfo=timezone.utc),
        open=Decimal('18.00'),
        high=Decimal('19.50'),
        low=Decimal('17.50'),
        close=Decimal('18.50'),
        volume=0,  # VIX is index (no volume)
        timeframe='1D'
    )


@pytest.fixture
def sample_tqqq_bar():
    """Create a sample TQQQ bar."""
    return MarketDataEvent(
        symbol='TQQQ',
        timestamp=datetime(2025, 1, 1, 9, 30, 0, tzinfo=timezone.utc),
        open=Decimal('50.00'),
        high=Decimal('51.50'),
        low=Decimal('49.50'),
        close=Decimal('50.50'),
        volume=10000000,
        timeframe='1D'
    )


@pytest.fixture
def sample_sqqq_bar():
    """Create a sample SQQQ bar."""
    return MarketDataEvent(
        symbol='SQQQ',
        timestamp=datetime(2025, 1, 1, 9, 30, 0, tzinfo=timezone.utc),
        open=Decimal('12.00'),
        high=Decimal('12.50'),
        low=Decimal('11.80'),
        close=Decimal('12.20'),
        volume=8000000,
        timeframe='1D'
    )
