"""
Indicators module for Jutsu Labs backtesting engine.

Provides technical analysis indicators for trading strategies.
Includes both stateless pure functions and stateful filters.

Stateless Indicators (technical.py):
    - Moving Averages: sma, ema
    - Momentum: rsi, macd
    - Volatility: bollinger_bands, atr, annualized_volatility
    - Trend: adx
    - Volume: obv
    - Oscillators: stochastic

Stateful Indicators (kalman.py):
    - AdaptiveKalmanFilter: Kalman filter with trend strength
"""

# Stateless indicators
from jutsu_engine.indicators.technical import (
    sma,
    ema,
    rsi,
    macd,
    bollinger_bands,
    atr,
    stochastic,
    obv,
    adx,
    annualized_volatility,
)

# Stateful indicators
from jutsu_engine.indicators.kalman import (
    AdaptiveKalmanFilter,
    KalmanFilterModel,
)

__all__ = [
    # Stateless
    'sma',
    'ema',
    'rsi',
    'macd',
    'bollinger_bands',
    'atr',
    'stochastic',
    'obv',
    'adx',
    'annualized_volatility',
    # Stateful
    'AdaptiveKalmanFilter',
    'KalmanFilterModel',
]
