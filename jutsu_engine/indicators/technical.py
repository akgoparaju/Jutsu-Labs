"""
Technical indicators for trading strategies.

Provides common technical analysis indicators using pandas for efficient computation.
All indicators accept either pandas Series or lists and return pandas Series.

Example:
    from jutsu_engine.indicators.technical import sma, rsi

    closes = strategy.get_closes(lookback=50)
    sma_20 = sma(closes, period=20)
    rsi_14 = rsi(closes, period=14)
"""
from decimal import Decimal
from typing import List, Union
import pandas as pd
import numpy as np


def _to_series(data: Union[pd.Series, List[Decimal], List[float]]) -> pd.Series:
    """
    Convert input data to pandas Series.

    Args:
        data: Price data as Series or list

    Returns:
        pandas Series with float values
    """
    if isinstance(data, pd.Series):
        return data.astype(float)

    # Convert Decimal to float for pandas compatibility
    if data and isinstance(data[0], Decimal):
        return pd.Series([float(x) for x in data])

    return pd.Series(data, dtype=float)


def sma(data: Union[pd.Series, List], period: int) -> pd.Series:
    """
    Calculate Simple Moving Average (SMA).

    SMA is the arithmetic mean of the last N periods.

    Args:
        data: Price data (typically close prices)
        period: Number of periods for moving average

    Returns:
        pandas Series with SMA values (NaN for insufficient data)

    Example:
        closes = [100, 102, 101, 103, 105, 104, 106]
        sma_3 = sma(closes, period=3)
        # Returns: [NaN, NaN, 101.0, 102.0, 103.0, 104.0, 105.0]
    """
    series = _to_series(data)
    return series.rolling(window=period).mean()


def ema(data: Union[pd.Series, List], period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA).

    EMA gives more weight to recent prices using exponential smoothing.

    Args:
        data: Price data (typically close prices)
        period: Number of periods for moving average

    Returns:
        pandas Series with EMA values

    Example:
        closes = [100, 102, 101, 103, 105, 104, 106]
        ema_3 = ema(closes, period=3)
    """
    series = _to_series(data)
    return series.ewm(span=period, adjust=False).mean()


def rsi(data: Union[pd.Series, List], period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI).

    RSI measures momentum on a scale of 0-100.
    Typically: RSI > 70 indicates overbought, RSI < 30 indicates oversold.

    Args:
        data: Price data (typically close prices)
        period: Number of periods for RSI calculation (default: 14)

    Returns:
        pandas Series with RSI values (0-100 scale)

    Example:
        closes = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42]
        rsi_14 = rsi(closes, period=14)

    Note:
        RSI = 100 - (100 / (1 + RS))
        where RS = Average Gain / Average Loss over period
    """
    series = _to_series(data)

    # Calculate price changes
    delta = series.diff()

    # Separate gains and losses
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    # Calculate average gain and loss using Wilder's smoothing (EMA)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()

    # Calculate RS and RSI
    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))

    return rsi_values


def macd(
    data: Union[pd.Series, List],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD (Moving Average Convergence Divergence).

    MACD shows the relationship between two moving averages.

    Args:
        data: Price data (typically close prices)
        fast_period: Period for fast EMA (default: 12)
        slow_period: Period for slow EMA (default: 26)
        signal_period: Period for signal line (default: 9)

    Returns:
        Tuple of (macd_line, signal_line, histogram)
        - macd_line: Fast EMA - Slow EMA
        - signal_line: EMA of MACD line
        - histogram: MACD line - Signal line

    Example:
        closes = strategy.get_closes(lookback=100)
        macd_line, signal, histogram = macd(closes)

        if macd_line.iloc[-1] > signal.iloc[-1]:
            # Bullish signal (MACD crossed above signal)
            strategy.buy(...)
    """
    series = _to_series(data)

    # Calculate EMAs
    fast_ema = series.ewm(span=fast_period, adjust=False).mean()
    slow_ema = series.ewm(span=slow_period, adjust=False).mean()

    # MACD line = Fast EMA - Slow EMA
    macd_line = fast_ema - slow_ema

    # Signal line = EMA of MACD line
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

    # Histogram = MACD line - Signal line
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def bollinger_bands(
    data: Union[pd.Series, List],
    period: int = 20,
    num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands.

    Bollinger Bands consist of a middle band (SMA) and upper/lower bands
    at a specified number of standard deviations away.

    Args:
        data: Price data (typically close prices)
        period: Period for SMA calculation (default: 20)
        num_std: Number of standard deviations for bands (default: 2.0)

    Returns:
        Tuple of (upper_band, middle_band, lower_band)

    Example:
        closes = strategy.get_closes(lookback=50)
        upper, middle, lower = bollinger_bands(closes, period=20)

        current_price = closes.iloc[-1]
        if current_price < lower.iloc[-1]:
            # Price below lower band (potentially oversold)
            strategy.buy(...)
    """
    series = _to_series(data)

    # Middle band is SMA
    middle_band = series.rolling(window=period).mean()

    # Calculate standard deviation
    std = series.rolling(window=period).std()

    # Upper and lower bands
    upper_band = middle_band + (std * num_std)
    lower_band = middle_band - (std * num_std)

    return upper_band, middle_band, lower_band


def atr(high: Union[pd.Series, List], low: Union[pd.Series, List],
        close: Union[pd.Series, List], period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).

    ATR measures market volatility by decomposing the entire range of an asset
    price for that period.

    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: Number of periods for ATR calculation (default: 14)

    Returns:
        pandas Series with ATR values

    Example:
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        closes = [bar.close for bar in bars]
        atr_14 = atr(highs, lows, closes, period=14)
    """
    high_series = _to_series(high)
    low_series = _to_series(low)
    close_series = _to_series(close)

    # True Range is the greatest of:
    # 1. Current High - Current Low
    # 2. abs(Current High - Previous Close)
    # 3. abs(Current Low - Previous Close)

    tr1 = high_series - low_series
    tr2 = abs(high_series - close_series.shift())
    tr3 = abs(low_series - close_series.shift())

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR is EMA of True Range
    atr_values = true_range.ewm(span=period, adjust=False).mean()

    return atr_values


def stochastic(
    high: Union[pd.Series, List],
    low: Union[pd.Series, List],
    close: Union[pd.Series, List],
    k_period: int = 14,
    d_period: int = 3
) -> tuple[pd.Series, pd.Series]:
    """
    Calculate Stochastic Oscillator.

    Stochastic compares closing price to its price range over a given time period.

    Args:
        high: High prices
        low: Low prices
        close: Close prices
        k_period: Period for %K calculation (default: 14)
        d_period: Period for %D smoothing (default: 3)

    Returns:
        Tuple of (%K line, %D line)
        - %K: Fast stochastic indicator
        - %D: Slow stochastic indicator (SMA of %K)

    Example:
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        closes = [bar.close for bar in bars]
        k, d = stochastic(highs, lows, closes)

        if k.iloc[-1] < 20 and k.iloc[-1] > d.iloc[-1]:
            # Oversold and %K crossing above %D (bullish)
            strategy.buy(...)
    """
    high_series = _to_series(high)
    low_series = _to_series(low)
    close_series = _to_series(close)

    # Lowest low and highest high over k_period
    lowest_low = low_series.rolling(window=k_period).min()
    highest_high = high_series.rolling(window=k_period).max()

    # %K = 100 * (Current Close - Lowest Low) / (Highest High - Lowest Low)
    k_line = 100 * (close_series - lowest_low) / (highest_high - lowest_low)

    # %D = SMA of %K
    d_line = k_line.rolling(window=d_period).mean()

    return k_line, d_line


def obv(close: Union[pd.Series, List], volume: Union[pd.Series, List]) -> pd.Series:
    """
    Calculate On-Balance Volume (OBV).

    OBV is a cumulative indicator that uses volume flow to predict changes in price.

    Args:
        close: Close prices
        volume: Trading volume

    Returns:
        pandas Series with OBV values

    Example:
        closes = [bar.close for bar in bars]
        volumes = [bar.volume for bar in bars]
        obv_values = obv(closes, volumes)
    """
    close_series = _to_series(close)
    volume_series = _to_series(volume)

    # Determine direction: +1 if close > prev_close, -1 if close < prev_close
    direction = np.where(close_series.diff() > 0, 1,
                        np.where(close_series.diff() < 0, -1, 0))

    # OBV = cumulative sum of (direction * volume)
    obv_values = (direction * volume_series).cumsum()

    return pd.Series(obv_values, index=close_series.index)


def adx(high: Union[pd.Series, List], low: Union[pd.Series, List],
        close: Union[pd.Series, List], period: int = 14) -> pd.Series:
    """
    Calculate Average Directional Index (ADX).

    ADX measures trend strength on a 0-100 scale. It does NOT indicate trend
    direction, only strength.
    - ADX > 25: Strong trend
    - ADX 20-25: Building trend
    - ADX < 20: Weak/no trend

    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: Number of periods for ADX calculation (default: 14)

    Returns:
        pandas Series with ADX values (0-100 scale)

    Example:
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        closes = [bar.close for bar in bars]
        adx_14 = adx(highs, lows, closes, period=14)

        if adx_14.iloc[-1] > 25:
            # Strong trend (either up or down)
            # Use other indicators to determine direction
            pass

    Note:
        ADX calculation steps:
        1. Calculate True Range (TR)
        2. Calculate +DM and -DM (directional movement)
        3. Smooth TR, +DM, -DM using EMA
        4. Calculate +DI and -DI (directional indicators)
        5. Calculate DX (directional index)
        6. ADX = EMA of DX
    """
    high_series = _to_series(high)
    low_series = _to_series(low)
    close_series = _to_series(close)

    # Step 1: Calculate True Range (TR)
    tr1 = high_series - low_series
    tr2 = abs(high_series - close_series.shift())
    tr3 = abs(low_series - close_series.shift())
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Step 2: Calculate Directional Movement
    high_diff = high_series.diff()
    low_diff = -low_series.diff()

    # +DM: positive if high_diff > low_diff AND high_diff > 0, else 0
    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
    plus_dm = pd.Series(plus_dm, index=high_series.index)

    # -DM: positive if low_diff > high_diff AND low_diff > 0, else 0
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)
    minus_dm = pd.Series(minus_dm, index=high_series.index)

    # Step 3: Smooth TR, +DM, -DM using EMA
    smooth_tr = true_range.ewm(span=period, adjust=False).mean()
    smooth_plus_dm = plus_dm.ewm(span=period, adjust=False).mean()
    smooth_minus_dm = minus_dm.ewm(span=period, adjust=False).mean()

    # Step 4: Calculate Directional Indicators
    # +DI = 100 * (smoothed +DM / smoothed TR)
    # -DI = 100 * (smoothed -DM / smoothed TR)
    plus_di = 100 * (smooth_plus_dm / smooth_tr)
    minus_di = 100 * (smooth_minus_dm / smooth_tr)

    # Step 5: Calculate Directional Index (DX)
    # DX = 100 * |+DI - -DI| / (+DI + -DI)
    # Handle division by zero
    di_sum = plus_di + minus_di
    di_diff = abs(plus_di - minus_di)
    dx = 100 * (di_diff / di_sum.replace(0, np.nan))

    # Step 6: ADX = EMA of DX
    adx_values = dx.ewm(span=period, adjust=False).mean()

    return adx_values
