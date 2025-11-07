"""
Unit tests for technical indicators.

Tests pure indicator calculation functions with known values and edge cases.
"""
import pytest
import pandas as pd
import numpy as np
from decimal import Decimal

from jutsu_engine.indicators.technical import (
    sma, ema, rsi, macd, bollinger_bands, atr, stochastic, obv, adx
)


class TestADX:
    """Tests for Average Directional Index (ADX) indicator."""

    def test_adx_basic_calculation(self):
        """Test ADX calculation with known trending data."""
        # Create trending data (uptrend)
        highs = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
        lows = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
                20, 21, 22, 23, 24, 25, 26, 27, 28, 29]
        closes = [9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5,
                  20.5, 21.5, 22.5, 23.5, 24.5, 25.5, 26.5, 27.5, 28.5, 29.5]

        result = adx(highs, lows, closes, period=14)

        # ADX should be a pandas Series
        assert isinstance(result, pd.Series)
        # Should have same length as input
        assert len(result) == len(highs)
        # ADX values should be between 0 and 100
        valid_values = result.dropna()
        assert all((valid_values >= 0) & (valid_values <= 100))
        # Strong uptrend should produce ADX > 20 eventually
        assert result.iloc[-1] > 20

    def test_adx_with_sideways_market(self):
        """Test ADX with sideways/ranging market (should be low)."""
        # Sideways market - prices oscillating
        highs = [101, 99, 102, 98, 103, 97, 102, 99, 101, 98,
                 102, 99, 101, 98, 103, 97, 102, 99, 101, 98]
        lows = [99, 97, 100, 96, 101, 95, 100, 97, 99, 96,
                100, 97, 99, 96, 101, 95, 100, 97, 99, 96]
        closes = [100, 98, 101, 97, 102, 96, 101, 98, 100, 97,
                  101, 98, 100, 97, 102, 96, 101, 98, 100, 97]

        result = adx(highs, lows, closes, period=14)

        # Sideways market should produce low ADX (< 25)
        # Last few values should indicate weak trend
        assert result.iloc[-1] < 25

    def test_adx_with_decimal_inputs(self):
        """Test ADX handles Decimal input correctly."""
        highs = [Decimal('10.5'), Decimal('11.0'), Decimal('11.5'),
                 Decimal('12.0'), Decimal('12.5')] * 5
        lows = [Decimal('10.0'), Decimal('10.5'), Decimal('11.0'),
                Decimal('11.5'), Decimal('12.0')] * 5
        closes = [Decimal('10.25'), Decimal('10.75'), Decimal('11.25'),
                  Decimal('11.75'), Decimal('12.25')] * 5

        result = adx(highs, lows, closes, period=5)

        # Should not raise error and return valid Series
        assert isinstance(result, pd.Series)
        assert len(result) == 25

    def test_adx_with_list_inputs(self):
        """Test ADX works with list inputs."""
        highs = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        lows = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        closes = [9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5]

        result = adx(highs, lows, closes, period=5)

        assert isinstance(result, pd.Series)
        assert len(result) == len(highs)

    def test_adx_with_series_inputs(self):
        """Test ADX works with pandas Series inputs."""
        highs = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
        lows = pd.Series([9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
        closes = pd.Series([9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5])

        result = adx(highs, lows, closes, period=5)

        assert isinstance(result, pd.Series)
        assert len(result) == len(highs)

    def test_adx_with_insufficient_data(self):
        """Test ADX with data shorter than period."""
        highs = [10, 11, 12]
        lows = [9, 10, 11]
        closes = [9.5, 10.5, 11.5]

        result = adx(highs, lows, closes, period=14)

        # Should return Series with NaN values
        assert isinstance(result, pd.Series)
        assert len(result) == 3
        # First value should be NaN (diff() creates NaN at start)
        assert result.isna().iloc[0]
        # Most values will be NaN or edge case values due to insufficient data
        # (EMA can produce values even with limited data)

    def test_adx_with_different_periods(self):
        """Test ADX with different period settings."""
        # Use more volatile data to see differences between periods
        highs = [10, 12, 11, 14, 13, 16, 15, 18, 17, 20, 19, 22, 21, 24, 23,
                 26, 25, 28, 27, 30, 29, 32, 31, 34, 33, 36, 35, 38, 37, 40]
        lows = [9, 10, 9, 12, 11, 14, 13, 16, 15, 18, 17, 20, 19, 22, 21,
                24, 23, 26, 25, 28, 27, 30, 29, 32, 31, 34, 33, 36, 35, 38]
        closes = [9.5, 11, 10, 13, 12, 15, 14, 17, 16, 19, 18, 21, 20, 23, 22,
                  25, 24, 27, 26, 29, 28, 31, 30, 33, 32, 35, 34, 37, 36, 39]

        result_7 = adx(highs, lows, closes, period=7)
        result_14 = adx(highs, lows, closes, period=14)
        result_21 = adx(highs, lows, closes, period=21)

        # All should return valid Series
        assert isinstance(result_7, pd.Series)
        assert isinstance(result_14, pd.Series)
        assert isinstance(result_21, pd.Series)

        # All periods should produce same length output
        assert len(result_7) == len(result_14) == len(result_21)

        # Verify all have valid values at the end
        assert not pd.isna(result_7.iloc[-1])
        assert not pd.isna(result_14.iloc[-1])
        assert not pd.isna(result_21.iloc[-1])

    def test_adx_handles_zero_range(self):
        """Test ADX handles bars with zero range (high = low)."""
        highs = [10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        lows = [10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        closes = [10, 10, 10, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5]

        result = adx(highs, lows, closes, period=7)

        # Should not raise error
        assert isinstance(result, pd.Series)
        # Should handle division by zero gracefully
        valid_values = result.dropna()
        assert all((valid_values >= 0) & (valid_values <= 100))

    def test_adx_downtrend(self):
        """Test ADX in downtrend (should still show high ADX)."""
        # Create downtrend
        highs = [30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20,
                 19, 18, 17, 16, 15, 14, 13, 12, 11, 10]
        lows = [29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19,
                18, 17, 16, 15, 14, 13, 12, 11, 10, 9]
        closes = [29.5, 28.5, 27.5, 26.5, 25.5, 24.5, 23.5, 22.5, 21.5, 20.5, 19.5,
                  18.5, 17.5, 16.5, 15.5, 14.5, 13.5, 12.5, 11.5, 10.5, 9.5]

        result = adx(highs, lows, closes, period=14)

        # Strong downtrend should also produce high ADX (> 20)
        # ADX measures trend strength, not direction
        assert result.iloc[-1] > 20

    def test_adx_values_are_non_negative(self):
        """Test ADX values are always non-negative."""
        # Random-ish data
        highs = [12, 13, 11, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17, 19, 18, 20]
        lows = [10, 11, 9, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18]
        closes = [11, 12, 10, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17, 19]

        result = adx(highs, lows, closes, period=7)

        # All ADX values should be non-negative
        valid_values = result.dropna()
        assert all(valid_values >= 0)

    def test_adx_returns_correct_length(self):
        """Test ADX returns Series of correct length."""
        for length in [10, 20, 30, 50, 100]:
            highs = list(range(length))
            lows = list(range(length))
            closes = [x + 0.5 for x in range(length)]

            result = adx(highs, lows, closes, period=min(14, length - 1))

            assert len(result) == length


class TestSMA:
    """Tests for Simple Moving Average."""

    def test_sma_basic_calculation(self):
        """Test SMA with known values."""
        data = [10, 12, 14, 13, 15]
        result = sma(data, period=3)

        # First 2 values should be NaN
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        # Third value: (10 + 12 + 14) / 3 = 12.0
        assert result.iloc[2] == pytest.approx(12.0)
        # Fourth value: (12 + 14 + 13) / 3 = 13.0
        assert result.iloc[3] == pytest.approx(13.0)
        # Fifth value: (14 + 13 + 15) / 3 = 14.0
        assert result.iloc[4] == pytest.approx(14.0)


class TestRSI:
    """Tests for Relative Strength Index."""

    def test_rsi_basic_calculation(self):
        """Test RSI with known trending data."""
        # Simple uptrend
        data = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        result = rsi(data, period=5)

        # RSI should be high in uptrend
        assert isinstance(result, pd.Series)
        # Last value should be > 70 (overbought)
        assert result.iloc[-1] > 70

    def test_rsi_range(self):
        """Test RSI values are in 0-100 range."""
        data = list(range(100))
        result = rsi(data, period=14)

        valid_values = result.dropna()
        assert all((valid_values >= 0) & (valid_values <= 100))


class TestATR:
    """Tests for Average True Range."""

    def test_atr_basic_calculation(self):
        """Test ATR calculation."""
        highs = [10, 11, 12, 13, 14]
        lows = [9, 10, 11, 12, 13]
        closes = [9.5, 10.5, 11.5, 12.5, 13.5]

        result = atr(highs, lows, closes, period=3)

        assert isinstance(result, pd.Series)
        assert len(result) == len(highs)
        # ATR should be positive
        valid_values = result.dropna()
        assert all(valid_values > 0)


# Run pytest if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
