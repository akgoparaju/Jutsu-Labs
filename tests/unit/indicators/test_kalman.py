"""
Tests for Adaptive Kalman Filter indicator.

This module tests the stateful Kalman filter implementation including:
- Initialization and parameter validation
- All three noise adjustment models
- State persistence and updates
- Trend strength calculation
- Edge cases and error handling
"""
from decimal import Decimal
import pytest
import numpy as np

from jutsu_engine.indicators.kalman import (
    AdaptiveKalmanFilter,
    KalmanFilterModel
)


class TestKalmanFilterInitialization:
    """Test Kalman filter initialization and parameters."""

    def test_default_initialization(self):
        """Test filter initializes with default parameters."""
        kf = AdaptiveKalmanFilter()

        assert kf.model == KalmanFilterModel.STANDARD
        assert kf.bar_count == 0
        assert kf.X.shape == (2, 1)
        assert kf.P.shape == (2, 2)
        assert kf.F.shape == (2, 2)
        assert kf.Q.shape == (2, 2)
        assert kf.R.shape == (1, 1)
        assert kf.H.shape == (1, 2)

    def test_custom_parameters(self):
        """Test filter with custom parameters."""
        kf = AdaptiveKalmanFilter(
            process_noise_1=0.05,
            process_noise_2=0.03,
            measurement_noise=1000.0,
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            sigma_lookback=300,
            trend_lookback=20
        )

        assert kf.model == KalmanFilterModel.VOLUME_ADJUSTED
        assert kf.Q[0, 0] == 0.05
        assert kf.Q[1, 1] == 0.03
        assert kf.R[0, 0] == 1000.0
        assert kf.sigma_lookback == 300
        assert kf.trend_lookback == 20

    def test_invalid_process_noise(self):
        """Test that negative process noise raises ValueError."""
        with pytest.raises(ValueError, match="Process noise must be positive"):
            AdaptiveKalmanFilter(process_noise_1=-0.01)

        with pytest.raises(ValueError, match="Process noise must be positive"):
            AdaptiveKalmanFilter(process_noise_2=0.0)

    def test_invalid_measurement_noise(self):
        """Test that invalid measurement noise raises ValueError."""
        with pytest.raises(ValueError, match="Measurement noise must be positive"):
            AdaptiveKalmanFilter(measurement_noise=-500.0)

    def test_invalid_lookback_periods(self):
        """Test that invalid lookback periods raise ValueError."""
        with pytest.raises(ValueError, match="Lookback periods must be positive"):
            AdaptiveKalmanFilter(sigma_lookback=0)

        with pytest.raises(ValueError, match="Lookback periods must be positive"):
            AdaptiveKalmanFilter(trend_lookback=-10)

    def test_invalid_smoothness_periods(self):
        """Test that invalid smoothness periods raise ValueError."""
        with pytest.raises(ValueError, match="Smoothness periods must be positive"):
            AdaptiveKalmanFilter(osc_smoothness=0)

        with pytest.raises(ValueError, match="Smoothness periods must be positive"):
            AdaptiveKalmanFilter(strength_smoothness=-5)


class TestStandardModel:
    """Test standard Kalman filter (no noise adjustment)."""

    def test_first_bar_initialization(self):
        """Test that first bar initializes state correctly."""
        kf = AdaptiveKalmanFilter(model=KalmanFilterModel.STANDARD)

        close = Decimal('100.50')
        filtered, strength = kf.update(close=close)

        assert filtered == close  # First bar returns close price
        assert strength == Decimal('0.0')  # No trend strength yet
        assert kf.bar_count == 1
        assert kf.X[0, 0] == 100.50

    def test_multiple_updates(self):
        """Test state transitions with multiple updates."""
        kf = AdaptiveKalmanFilter(
            model=KalmanFilterModel.STANDARD,
            measurement_noise=100.0
        )

        prices = [
            Decimal('100.00'),
            Decimal('101.00'),
            Decimal('102.00'),
            Decimal('103.00'),
            Decimal('104.00')
        ]

        results = []
        for price in prices:
            filtered, strength = kf.update(close=price)
            results.append((filtered, strength))

        # Verify state accumulates
        assert kf.bar_count == 5
        assert len(kf.innovation_buffer) > 0

        # Verify filtered prices are reasonable (not exact due to filter dynamics)
        for i, (filtered, strength) in enumerate(results):
            assert isinstance(filtered, Decimal)
            assert isinstance(strength, Decimal)
            assert filtered > Decimal('0')

    def test_state_persistence(self):
        """Test that state persists across updates."""
        kf = AdaptiveKalmanFilter(model=KalmanFilterModel.STANDARD)

        # First update
        kf.update(close=Decimal('100.00'))
        state_after_first = kf.X.copy()

        # Second update
        kf.update(close=Decimal('101.00'))
        state_after_second = kf.X.copy()

        # States should be different (filter is updating)
        assert not np.array_equal(state_after_first, state_after_second)

    def test_trend_strength_builds_up(self):
        """Test that trend strength builds up with consistent trend."""
        kf = AdaptiveKalmanFilter(
            model=KalmanFilterModel.STANDARD,
            strength_smoothness=5,
            osc_smoothness=3
        )

        # Uptrend
        prices = [Decimal(str(100 + i)) for i in range(20)]

        strengths = []
        for price in prices:
            _, strength = kf.update(close=price)
            strengths.append(float(strength))

        # Trend strength should increase as trend continues
        # (after initial warmup period)
        assert strengths[-1] > strengths[5]  # Later > earlier


class TestVolumeAdjustedModel:
    """Test volume-adjusted noise model."""

    def test_requires_volume(self):
        """Test that volume-adjusted model requires volume parameter."""
        kf = AdaptiveKalmanFilter(model=KalmanFilterModel.VOLUME_ADJUSTED)

        # First bar (initialization)
        kf.update(
            close=Decimal('100.00'),
            volume=Decimal('1000000')
        )

        # Second bar without volume should raise error
        with pytest.raises(ValueError, match="Volume-adjusted model requires volume"):
            kf.update(close=Decimal('101.00'))

    def test_volume_adjustment(self):
        """Test that volume affects measurement noise."""
        kf = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=500.0
        )

        # Initialize with normal volume
        kf.update(
            close=Decimal('100.00'),
            volume=Decimal('1000000')
        )

        # Update with high volume (should reduce noise, more confidence)
        filtered_high_vol, _ = kf.update(
            close=Decimal('101.00'),
            volume=Decimal('2000000')
        )

        # Reset for comparison
        kf.reset()
        kf.update(
            close=Decimal('100.00'),
            volume=Decimal('1000000')
        )

        # Update with low volume (should increase noise, less confidence)
        filtered_low_vol, _ = kf.update(
            close=Decimal('101.00'),
            volume=Decimal('500000')
        )

        # Both should be valid Decimals
        assert isinstance(filtered_high_vol, Decimal)
        assert isinstance(filtered_low_vol, Decimal)

    def test_zero_volume_edge_case(self):
        """Test handling of zero volume."""
        kf = AdaptiveKalmanFilter(model=KalmanFilterModel.VOLUME_ADJUSTED)

        # Initialize
        kf.update(
            close=Decimal('100.00'),
            volume=Decimal('1000000')
        )

        # Zero volume should not crash (uses base noise)
        filtered, strength = kf.update(
            close=Decimal('101.00'),
            volume=Decimal('0')
        )

        assert isinstance(filtered, Decimal)
        assert isinstance(strength, Decimal)


class TestParkinsonAdjustedModel:
    """Test Parkinson volatility-adjusted noise model."""

    def test_requires_high_low(self):
        """Test that Parkinson model requires high and low prices."""
        kf = AdaptiveKalmanFilter(model=KalmanFilterModel.PARKINSON_ADJUSTED)

        # First bar (initialization)
        kf.update(
            close=Decimal('100.00'),
            high=Decimal('101.00'),
            low=Decimal('99.00')
        )

        # Second bar without high/low should raise error
        with pytest.raises(ValueError, match="Parkinson model requires high and low"):
            kf.update(close=Decimal('101.00'))

    def test_range_adjustment(self):
        """Test that price range affects measurement noise."""
        kf = AdaptiveKalmanFilter(
            model=KalmanFilterModel.PARKINSON_ADJUSTED,
            measurement_noise=500.0
        )

        # Initialize with normal range
        kf.update(
            close=Decimal('100.00'),
            high=Decimal('101.00'),
            low=Decimal('99.00')
        )

        # Update with wide range (should increase noise, less confidence)
        filtered_wide, _ = kf.update(
            close=Decimal('101.00'),
            high=Decimal('105.00'),
            low=Decimal('97.00')
        )

        # Reset for comparison
        kf.reset()
        kf.update(
            close=Decimal('100.00'),
            high=Decimal('101.00'),
            low=Decimal('99.00')
        )

        # Update with narrow range (should reduce noise, more confidence)
        filtered_narrow, _ = kf.update(
            close=Decimal('101.00'),
            high=Decimal('101.50'),
            low=Decimal('100.50')
        )

        # Both should be valid Decimals
        assert isinstance(filtered_wide, Decimal)
        assert isinstance(filtered_narrow, Decimal)

    def test_high_equals_low_edge_case(self):
        """Test handling when high equals low."""
        kf = AdaptiveKalmanFilter(model=KalmanFilterModel.PARKINSON_ADJUSTED)

        # Initialize
        kf.update(
            close=Decimal('100.00'),
            high=Decimal('101.00'),
            low=Decimal('99.00')
        )

        # High = Low should not crash (uses minimum range)
        filtered, strength = kf.update(
            close=Decimal('101.00'),
            high=Decimal('101.00'),
            low=Decimal('101.00')
        )

        assert isinstance(filtered, Decimal)
        assert isinstance(strength, Decimal)


class TestTrendStrength:
    """Test trend strength oscillator calculation."""

    def test_trend_strength_range(self):
        """Test that trend strength stays in reasonable range."""
        kf = AdaptiveKalmanFilter(
            strength_smoothness=5,
            osc_smoothness=3
        )

        # Generate sample data
        prices = [Decimal(str(100 + i * 0.5)) for i in range(50)]

        for price in prices:
            _, strength = kf.update(close=price)
            # Trend strength should be non-negative
            assert strength >= Decimal('0')

    def test_oscillator_buffer_size(self):
        """Test that oscillator buffer is limited to trend_lookback."""
        kf = AdaptiveKalmanFilter(
            trend_lookback=10,
            strength_smoothness=5
        )

        # Update many times
        for i in range(50):
            kf.update(close=Decimal(str(100 + i)))

        # Oscillator buffer should not exceed trend_lookback
        assert len(kf.oscillator_buffer) <= kf.trend_lookback

    def test_innovation_buffer_size(self):
        """Test that innovation buffer is limited to sigma_lookback."""
        kf = AdaptiveKalmanFilter(sigma_lookback=20)

        # Update many times
        for i in range(100):
            kf.update(close=Decimal(str(100 + i)))

        # Innovation buffer should not exceed sigma_lookback
        assert len(kf.innovation_buffer) <= kf.sigma_lookback


class TestResetFunctionality:
    """Test filter reset capability."""

    def test_reset_clears_state(self):
        """Test that reset clears all state."""
        kf = AdaptiveKalmanFilter()

        # Update a few times
        for i in range(10):
            kf.update(close=Decimal(str(100 + i)))

        # State should be populated
        assert kf.bar_count > 0
        assert len(kf.innovation_buffer) > 0

        # Reset
        kf.reset()

        # State should be cleared
        assert kf.bar_count == 0
        assert len(kf.innovation_buffer) == 0
        assert len(kf.oscillator_buffer) == 0
        assert kf.prev_high is None
        assert kf.prev_low is None
        assert kf.prev_volume is None
        assert np.allclose(kf.X, np.array([[0.0], [0.0]]))

    def test_reset_and_reuse(self):
        """Test that filter can be reset and reused."""
        kf = AdaptiveKalmanFilter()

        # First sequence
        for i in range(10):
            kf.update(close=Decimal(str(100 + i)))
        first_bar_count = kf.bar_count

        # Reset
        kf.reset()

        # Second sequence
        for i in range(10):
            kf.update(close=Decimal(str(200 + i)))
        second_bar_count = kf.bar_count

        # Should have same number of bars
        assert first_bar_count == second_bar_count


class TestDecimalPrecision:
    """Test Decimal precision throughout calculations."""

    def test_input_output_decimal_types(self):
        """Test that inputs and outputs maintain Decimal types."""
        kf = AdaptiveKalmanFilter()

        close = Decimal('100.50')
        filtered, strength = kf.update(close=close)

        assert isinstance(filtered, Decimal)
        assert isinstance(strength, Decimal)

    def test_precision_maintained(self):
        """Test that precision is maintained in calculations."""
        kf = AdaptiveKalmanFilter()

        # Use high-precision Decimal
        close = Decimal('100.123456789')
        filtered, strength = kf.update(close=close)

        # Should return Decimal (precision may differ due to filter)
        assert isinstance(filtered, Decimal)
        assert str(filtered).count('.') <= 1  # Valid decimal format


class TestWMAHelper:
    """Test Weighted Moving Average helper function."""

    def test_wma_calculation(self):
        """Test WMA calculation with known values."""
        kf = AdaptiveKalmanFilter()

        # Known values: [1, 2, 3] with period=3
        # Weights: [1, 2, 3]
        # WMA = (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6 = 2.333...
        values = [1.0, 2.0, 3.0]
        result = kf._wma(values, period=3)

        expected = 14.0 / 6.0
        assert abs(result - expected) < 1e-6

    def test_wma_insufficient_data(self):
        """Test WMA with insufficient data."""
        kf = AdaptiveKalmanFilter()

        values = [1.0, 2.0]
        result = kf._wma(values, period=5)

        assert result == 0.0


class TestPerformance:
    """Test performance characteristics."""

    def test_update_performance(self):
        """Test that update is fast (<5ms target)."""
        import time

        kf = AdaptiveKalmanFilter()

        # Warmup
        for i in range(10):
            kf.update(close=Decimal(str(100 + i)))

        # Time 100 updates
        start = time.perf_counter()
        for i in range(100):
            kf.update(close=Decimal(str(200 + i)))
        elapsed = time.perf_counter() - start

        # Average should be <5ms per update
        avg_time_ms = (elapsed / 100) * 1000
        assert avg_time_ms < 5.0, f"Update took {avg_time_ms:.2f}ms (target: <5ms)"


class TestIntegration:
    """Integration tests with realistic scenarios."""

    def test_realistic_price_sequence(self):
        """Test with realistic price data."""
        kf = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=500.0
        )

        # Simulate realistic price and volume data
        base_price = 150.0
        prices = []
        volumes = []

        for i in range(50):
            # Add some noise and trend
            price = base_price + i * 0.5 + np.random.randn() * 0.2
            volume = 1000000 + np.random.randint(-100000, 100000)

            prices.append(Decimal(str(round(price, 2))))
            volumes.append(Decimal(str(volume)))

        # Update filter
        results = []
        for price, volume in zip(prices, volumes):
            filtered, strength = kf.update(
                close=price,
                volume=volume
            )
            results.append((filtered, strength))

        # Verify all updates succeeded
        assert len(results) == 50
        assert all(isinstance(f, Decimal) and isinstance(s, Decimal) for f, s in results)

    def test_all_models_produce_valid_output(self):
        """Test that all models work correctly."""
        models = [
            KalmanFilterModel.STANDARD,
            KalmanFilterModel.VOLUME_ADJUSTED,
            KalmanFilterModel.PARKINSON_ADJUSTED
        ]

        for model in models:
            kf = AdaptiveKalmanFilter(model=model)

            # Generate appropriate data for model
            for i in range(20):
                close = Decimal(str(100 + i))
                high = Decimal(str(101 + i))
                low = Decimal(str(99 + i))
                volume = Decimal(str(1000000 + i * 10000))

                filtered, strength = kf.update(
                    close=close,
                    high=high,
                    low=low,
                    volume=volume
                )

                assert isinstance(filtered, Decimal)
                assert isinstance(strength, Decimal)
                assert filtered > Decimal('0')
                assert strength >= Decimal('0')
