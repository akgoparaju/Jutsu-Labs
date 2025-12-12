#!/usr/bin/env python3
"""
Independent Regime Analysis for Hierarchical_Adaptive_v3_5b Strategy

This script performs independent calculation of the market regime
and allocation based on the v3.5b strategy logic, using:
1. Historical data from PostgreSQL database
2. Current quotes from Schwab API (pseudo-data for today) - OR -
3. Historical-only mode for any past date (for verification)

Usage:
  python regime_analysis_v3_5b.py                    # Today's analysis with live quotes
  python regime_analysis_v3_5b.py 2025-12-09        # Historical analysis for Dec 9, 2025
  python regime_analysis_v3_5b.py --date 2025-12-09 # Same as above
  python regime_analysis_v3_5b.py --help            # Show help

Author: Claude Analysis
Date: 2025-12-11
"""

import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pandas as pd
import numpy as np
from typing import Optional, Tuple, Dict, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import production Kalman filter for exact backtest matching
from jutsu_engine.indicators.kalman import AdaptiveKalmanFilter, KalmanFilterModel

# Database connection
import psycopg2
from psycopg2.extras import RealDictCursor

# Schwab API for current quotes
try:
    import schwab
    from schwab import auth
    SCHWAB_AVAILABLE = True
except ImportError as e:
    SCHWAB_AVAILABLE = False
    print(f"Warning: schwab-py not available ({e}), will use latest database data")

# =============================================================================
# GOLDEN CONFIG PARAMETERS (from docs/Hierarchical_Adaptive_v3_5b-Strategy.md)
# =============================================================================

# Kalman Trend Parameters
MEASUREMENT_NOISE = 3000.0
PROCESS_NOISE_1 = 0.01
PROCESS_NOISE_2 = 0.01
OSC_SMOOTHNESS = 15
STRENGTH_SMOOTHNESS = 15
T_MAX = Decimal("50.0")

# SMA Structure Parameters
SMA_FAST = 40
SMA_SLOW = 140

# Trend Classification Thresholds
T_NORM_BULL_THRESH = Decimal("0.05")
T_NORM_BEAR_THRESH = Decimal("-0.30")

# Volatility Z-Score Parameters
REALIZED_VOL_WINDOW = 21
VOL_BASELINE_WINDOW = 160
UPPER_THRESH_Z = Decimal("1.0")
LOWER_THRESH_Z = Decimal("0.2")

# Vol-Crush Override
VOL_CRUSH_THRESHOLD = Decimal("-0.15")
VOL_CRUSH_LOOKBACK = 5

# Treasury Overlay Parameters
ALLOW_TREASURY = True
BOND_SMA_FAST = 20
BOND_SMA_SLOW = 60
MAX_BOND_WEIGHT = Decimal("0.4")

# Symbols
SIGNAL_SYMBOL = "QQQ"
CORE_LONG_SYMBOL = "QQQ"
LEVERAGED_LONG_SYMBOL = "TQQQ"
INVERSE_HEDGE_SYMBOL = "PSQ"
TREASURY_TREND_SYMBOL = "TLT"
BULL_BOND_SYMBOL = "TMF"
BEAR_BOND_SYMBOL = "TMV"

# Database Configuration
DB_CONFIG = {
    'host': 'tower.local',
    'port': 5423,
    'database': 'jutsu_labs',
    'user': 'jutsudB',
    'password': 'Maruthi13JT@@'
}

# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_db_connection():
    """Get PostgreSQL database connection."""
    return psycopg2.connect(**DB_CONFIG)

def fetch_historical_data(symbol: str, lookback_days: int = 200, as_of_date: Optional[datetime] = None) -> pd.DataFrame:
    """
    Fetch historical OHLCV data from PostgreSQL.

    Args:
        symbol: Stock symbol
        lookback_days: Number of days of history to fetch
        as_of_date: If provided, only fetch data up to and including this date
                   (for historical regime analysis / verification)

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    if as_of_date:
        # Historical mode: fetch data up to specified date
        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM market_data
            WHERE symbol = %s
              AND timeframe = '1D'
              AND is_valid = true
              AND DATE(timestamp) <= %s
            ORDER BY timestamp ASC
        """
        params = (symbol, as_of_date.strftime('%Y-%m-%d'))
    else:
        # Current mode: fetch all data
        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM market_data
            WHERE symbol = %s
              AND timeframe = '1D'
              AND is_valid = true
            ORDER BY timestamp ASC
        """
        params = (symbol,)

    conn = get_db_connection()
    try:
        df = pd.read_sql_query(query, conn, params=params)
        # Handle timezone-aware datetimes
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)

        # Convert to numeric types
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)
        df['volume'] = df['volume'].astype(int)

        return df
    finally:
        conn.close()

def get_current_quote_from_schwab(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get current quote from Schwab API.

    Args:
        symbol: Stock symbol

    Returns:
        Dict with current price data or None if unavailable
    """
    if not SCHWAB_AVAILABLE:
        return None

    try:
        # Use existing token
        token_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'token.json'
        )

        if not os.path.exists(token_path):
            print(f"Warning: Token file not found at {token_path}")
            return None

        api_key = os.environ.get('SCHWAB_API_KEY', '1LmXnGOvF7RI60bVaM48WtPhHOEepeJQKy9rINtYPHx864Ou')
        app_secret = os.environ.get('SCHWAB_API_SECRET', 'TMeXlJGFKzpzlxuhSEWyYOQNODoi0ASu2Bh9ZDpf5G58CsGipyeqvLO2C6StGmGl')

        client = schwab.auth.client_from_token_file(
            token_path=token_path,
            api_key=api_key,
            app_secret=app_secret
        )

        # Get quote
        response = client.get_quote(symbol)
        if response.status_code == 200:
            data = response.json()
            if symbol in data:
                quote = data[symbol].get('quote', {})
                return {
                    'symbol': symbol,
                    'last_price': quote.get('lastPrice'),
                    'open': quote.get('openPrice'),
                    'high': quote.get('highPrice'),
                    'low': quote.get('lowPrice'),
                    'close': quote.get('closePrice'),
                    'volume': quote.get('totalVolume'),
                    'timestamp': datetime.now(timezone.utc)
                }
        return None
    except Exception as e:
        print(f"Error fetching quote for {symbol}: {e}")
        return None

# =============================================================================
# KALMAN FILTER IMPLEMENTATION (DEPRECATED - Use AdaptiveKalmanFilter instead)
# =============================================================================

class SimpleKalmanFilter:
    """
    DEPRECATED: This class uses velocity-based trend strength which does NOT match
    the backtest implementation. Use AdaptiveKalmanFilter from jutsu_engine.indicators.kalman
    instead, which uses innovation-based trend strength with WMA smoothing.
    
    Key differences from AdaptiveKalmanFilter:
    - This class: trend_strength = mean(velocity_buffer) * 100 (WRONG)
    - AdaptiveKalmanFilter: trend_strength = WMA(innovation/max_innovation * 100) (CORRECT)
    
    Kept for reference only. DO NOT USE for analysis.
    """

    def __init__(self):
        self.state = None
        self.velocity = None
        self.P = np.array([[1, 0], [0, 1]], dtype=float)  # Covariance matrix
        self.osc_buffer = []
        self.strength_buffer = []

    def update(self, close: float, high: float, low: float, volume: int) -> Tuple[float, float]:
        """
        Update filter with new price data.

        Returns:
            Tuple of (filtered_price, trend_strength_signed)
        """
        price = float(close)

        if self.state is None:
            self.state = price
            self.velocity = 0.0
            return price, 0.0

        # Prediction step
        F = np.array([[1, 1], [0, 1]], dtype=float)  # State transition
        Q = np.array([[PROCESS_NOISE_1, 0], [0, PROCESS_NOISE_2]], dtype=float)  # Process noise

        state_vec = np.array([self.state, self.velocity])
        predicted_state = F @ state_vec
        predicted_P = F @ self.P @ F.T + Q

        # Update step
        H = np.array([[1, 0]], dtype=float)  # Observation matrix
        R = np.array([[MEASUREMENT_NOISE]], dtype=float)  # Measurement noise

        y = price - H @ predicted_state  # Innovation
        S = H @ predicted_P @ H.T + R  # Innovation covariance
        K = predicted_P @ H.T @ np.linalg.inv(S)  # Kalman gain

        updated_state = predicted_state + K.flatten() * y
        self.P = (np.eye(2) - K @ H) @ predicted_P

        self.state = updated_state[0]
        self.velocity = updated_state[1]

        # Calculate oscillator (price - filtered_price)
        oscillator = price - self.state
        self.osc_buffer.append(oscillator)

        # Smooth oscillator
        if len(self.osc_buffer) > OSC_SMOOTHNESS:
            self.osc_buffer = self.osc_buffer[-OSC_SMOOTHNESS:]
        smoothed_osc = np.mean(self.osc_buffer)

        # Calculate trend strength (velocity-based with smoothing)
        self.strength_buffer.append(self.velocity)
        if len(self.strength_buffer) > STRENGTH_SMOOTHNESS:
            self.strength_buffer = self.strength_buffer[-STRENGTH_SMOOTHNESS:]
        smoothed_strength = np.mean(self.strength_buffer)

        # Combine oscillator and velocity for trend strength
        # Use smoothed values for stability
        trend_strength = smoothed_strength * 100  # Scale for visibility

        return self.state, trend_strength

# =============================================================================
# INDICATOR FUNCTIONS
# =============================================================================

def calculate_sma(prices: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average."""
    return prices.rolling(window=period).mean()

def calculate_annualized_volatility(prices: pd.Series, lookback: int = 21) -> pd.Series:
    """
    Calculate annualized volatility using log returns.

    Args:
        prices: Price series
        lookback: Rolling window size

    Returns:
        Annualized volatility series
    """
    log_returns = np.log(prices / prices.shift(1))
    rolling_std = log_returns.rolling(window=lookback).std()
    annualized_vol = rolling_std * np.sqrt(252)
    return annualized_vol

def calculate_volatility_zscore(prices: pd.Series) -> Optional[Decimal]:
    """
    Calculate rolling z-score of realized volatility.

    Formula:
        σ_t = Realized Volatility (21-day annualized)
        μ_vol = Mean(σ, 126-day rolling window)
        σ_vol = Std(σ, 126-day rolling window)
        z_score = (σ_t - μ_vol) / σ_vol
    """
    if len(prices) < VOL_BASELINE_WINDOW + REALIZED_VOL_WINDOW:
        return None

    # Calculate realized volatility
    vol_series = calculate_annualized_volatility(prices, REALIZED_VOL_WINDOW)

    if len(vol_series) < VOL_BASELINE_WINDOW:
        return None

    # Calculate rolling baseline statistics
    vol_values = vol_series.tail(VOL_BASELINE_WINDOW)
    vol_values = vol_values.dropna()

    if len(vol_values) < VOL_BASELINE_WINDOW - 10:
        return None

    vol_mean = vol_values.mean()
    vol_std = vol_values.std()

    if vol_std == 0:
        return Decimal("0")

    # Current realized vol
    sigma_t = vol_series.iloc[-1]

    # Z-score
    z_score = (sigma_t - vol_mean) / vol_std

    return Decimal(str(z_score))

def check_vol_crush(prices: pd.Series) -> bool:
    """
    Check for vol-crush override (V-shaped recovery detection).

    Trigger: If realized volatility drops by >15% in 5 days.
    """
    if len(prices) < REALIZED_VOL_WINDOW + VOL_CRUSH_LOOKBACK:
        return False

    vol_series = calculate_annualized_volatility(prices, REALIZED_VOL_WINDOW)

    if len(vol_series) < VOL_CRUSH_LOOKBACK + 1:
        return False

    sigma_t = vol_series.iloc[-1]
    sigma_t_minus_n = vol_series.iloc[-(VOL_CRUSH_LOOKBACK + 1)]

    if sigma_t_minus_n == 0:
        return False

    vol_change = (sigma_t - sigma_t_minus_n) / sigma_t_minus_n

    return Decimal(str(vol_change)) < VOL_CRUSH_THRESHOLD

# =============================================================================
# HYSTERESIS STATE MACHINE (Matches Backtest Exactly)
# =============================================================================

def calculate_vol_state_with_hysteresis(
    prices: pd.Series,
    upper_thresh_z: Decimal = UPPER_THRESH_Z,
    lower_thresh_z: Decimal = LOWER_THRESH_Z,
    realized_vol_window: int = REALIZED_VOL_WINDOW,
    vol_baseline_window: int = VOL_BASELINE_WINDOW
) -> Tuple[str, Decimal, Dict[str, Any]]:
    """
    Calculate volatility state using TRUE hysteresis matching backtest exactly.

    This function processes ALL historical bars sequentially to track vol_state
    across the entire history. In the deadband (between lower and upper thresholds),
    it maintains the previous state instead of defaulting to "Low".

    Hysteresis Logic (from Hierarchical_Adaptive_v3_5b.py:988-1026):
        if z_score > upper_thresh_z:
            VolState = "High"
        elif z_score < lower_thresh_z:
            VolState = "Low"
        else:
            VolState = Previous_VolState (deadband - maintain state)

    Day 1 Initialization (first valid z-score):
        if z_score > 0: VolState = "High"
        else: VolState = "Low"

    Args:
        prices: Full price series (oldest to newest)
        upper_thresh_z: Upper z-score threshold for High state (default: 1.0)
        lower_thresh_z: Lower z-score threshold for Low state (default: 0.2)
        realized_vol_window: Window for realized volatility (default: 21)
        vol_baseline_window: Window for baseline statistics (default: 160)

    Returns:
        Tuple of (vol_state, final_z_score, hysteresis_info)
        - vol_state: Final volatility state ("High" or "Low")
        - final_z_score: Z-score for the last bar
        - hysteresis_info: Dict with history and diagnostics:
            - transitions: List of state transitions with dates
            - total_bars_processed: Number of bars with valid z-scores
            - deadband_bars: Number of bars where state was maintained
            - initial_state: First vol_state assigned
            - initial_date: Date of first valid z-score
    """
    if len(prices) < vol_baseline_window + realized_vol_window:
        return "Low", Decimal("0"), {"error": "Insufficient data"}

    # Calculate volatility series for ALL bars
    vol_series = calculate_annualized_volatility(prices, realized_vol_window)

    # Get dates if available (for diagnostics)
    if hasattr(prices, 'index') and hasattr(prices.index, 'date'):
        try:
            dates = prices.index
        except:
            dates = None
    else:
        dates = None

    # Initialize tracking variables
    vol_state = None  # Will be set on first valid z-score
    initial_state = None
    initial_date = None
    transitions = []
    deadband_count = 0
    bars_processed = 0
    final_z_score = Decimal("0")

    # Minimum index to have valid baseline statistics
    # Need at least vol_baseline_window volatility values
    min_idx = vol_baseline_window + realized_vol_window - 1

    # Process each bar from the first valid index to the end
    for i in range(min_idx, len(prices)):
        # Calculate rolling baseline statistics up to bar i
        vol_slice = vol_series.iloc[max(0, i - vol_baseline_window + 1):i + 1].dropna()

        if len(vol_slice) < vol_baseline_window - 10:  # Allow small tolerance
            continue

        vol_mean = vol_slice.mean()
        vol_std = vol_slice.std()

        if vol_std == 0:
            continue

        # Current realized vol
        sigma_t = vol_series.iloc[i]
        if pd.isna(sigma_t):
            continue

        # Calculate z-score for this bar
        z_score = Decimal(str((sigma_t - vol_mean) / vol_std))
        bars_processed += 1
        final_z_score = z_score

        # Day 1 initialization (first valid z-score)
        if vol_state is None:
            vol_state = "High" if z_score > Decimal("0") else "Low"
            initial_state = vol_state
            if dates is not None:
                try:
                    initial_date = dates[i]
                except:
                    initial_date = f"Bar {i}"
            else:
                initial_date = f"Bar {i}"
            transitions.append({
                "type": "init",
                "bar": i,
                "date": str(initial_date),
                "z_score": float(z_score),
                "new_state": vol_state
            })
            continue

        # Apply hysteresis logic
        prev_state = vol_state

        if z_score > upper_thresh_z:
            vol_state = "High"
        elif z_score < lower_thresh_z:
            vol_state = "Low"
        # else: Deadband - maintain current state (implicit)

        # Track transitions and deadband bars
        if z_score >= lower_thresh_z and z_score <= upper_thresh_z:
            deadband_count += 1

        if vol_state != prev_state:
            if dates is not None:
                try:
                    transition_date = dates[i]
                except:
                    transition_date = f"Bar {i}"
            else:
                transition_date = f"Bar {i}"
            transitions.append({
                "type": "transition",
                "bar": i,
                "date": str(transition_date),
                "z_score": float(z_score),
                "from_state": prev_state,
                "to_state": vol_state
            })

    # Build diagnostics
    hysteresis_info = {
        "transitions": transitions,
        "total_bars_processed": bars_processed,
        "deadband_bars": deadband_count,
        "initial_state": initial_state,
        "initial_date": str(initial_date) if initial_date else None,
        "final_z_score": float(final_z_score),
        "upper_thresh_z": float(upper_thresh_z),
        "lower_thresh_z": float(lower_thresh_z)
    }

    # Default to "Low" if never initialized (shouldn't happen with valid data)
    if vol_state is None:
        vol_state = "Low"
        hysteresis_info["warning"] = "No valid z-scores found, defaulted to Low"

    return vol_state, final_z_score, hysteresis_info


# =============================================================================
# REGIME CLASSIFICATION
# =============================================================================

def classify_trend_regime(t_norm: Decimal, sma_fast: float, sma_slow: float) -> str:
    """
    Classify trend regime using hierarchical logic.

    Classification Rules:
    1. BullStrong: (T_norm > 0.20) AND (SMA_fast > SMA_slow)
    2. BearStrong: (T_norm < -0.30) AND (SMA_fast < SMA_slow)
    3. Sideways: All other conditions
    """
    is_struct_bull = sma_fast > sma_slow

    if t_norm > T_NORM_BULL_THRESH and is_struct_bull:
        return "BullStrong"
    elif t_norm < T_NORM_BEAR_THRESH and not is_struct_bull:
        return "BearStrong"
    else:
        return "Sideways"

def get_cell_id(trend_state: str, vol_state: str) -> int:
    """
    Map (TrendState, VolState) to cell ID (1-6).

    Cell Mapping:
        1: BullStrong + Low
        2: BullStrong + High
        3: Sideways + Low
        4: Sideways + High
        5: BearStrong + Low
        6: BearStrong + High
    """
    if trend_state == "BullStrong":
        return 1 if vol_state == "Low" else 2
    elif trend_state == "Sideways":
        return 3 if vol_state == "Low" else 4
    else:  # BearStrong
        return 5 if vol_state == "Low" else 6

def get_cell_allocation(cell_id: int) -> Dict[str, Decimal]:
    """
    Get base allocation weights for cell ID.

    Returns dict with weights for TQQQ, QQQ, PSQ, Cash
    """
    allocations = {
        1: {"TQQQ": Decimal("0.6"), "QQQ": Decimal("0.4"), "PSQ": Decimal("0"), "Cash": Decimal("0")},
        2: {"TQQQ": Decimal("0"), "QQQ": Decimal("1.0"), "PSQ": Decimal("0"), "Cash": Decimal("0")},
        3: {"TQQQ": Decimal("0.2"), "QQQ": Decimal("0.8"), "PSQ": Decimal("0"), "Cash": Decimal("0")},
        4: {"TQQQ": Decimal("0"), "QQQ": Decimal("0"), "PSQ": Decimal("0"), "Cash": Decimal("1.0")},
        5: {"TQQQ": Decimal("0"), "QQQ": Decimal("0.5"), "PSQ": Decimal("0"), "Cash": Decimal("0.5")},
        6: {"TQQQ": Decimal("0"), "QQQ": Decimal("0"), "PSQ": Decimal("0"), "Cash": Decimal("1.0")},
    }
    return allocations.get(cell_id, allocations[3])

def get_safe_haven_allocation(tlt_prices: pd.Series, defensive_weight: Decimal) -> Dict[str, Decimal]:
    """
    Determine safe haven allocation based on TLT trend.

    Bond Bull (SMA_fast > SMA_slow): TMF (deflation hedge)
    Bond Bear (SMA_fast < SMA_slow): TMV (inflation hedge)
    """
    if tlt_prices is None or len(tlt_prices) < BOND_SMA_SLOW:
        return {"Cash": defensive_weight}

    sma_fast = calculate_sma(tlt_prices, BOND_SMA_FAST).iloc[-1]
    sma_slow = calculate_sma(tlt_prices, BOND_SMA_SLOW).iloc[-1]

    if pd.isna(sma_fast) or pd.isna(sma_slow):
        return {"Cash": defensive_weight}

    # Calculate bond allocation
    bond_weight = min(defensive_weight * Decimal("0.4"), MAX_BOND_WEIGHT)
    cash_weight = defensive_weight - bond_weight

    if sma_fast > sma_slow:
        # Bond Bull - use TMF
        return {"TMF": bond_weight, "Cash": cash_weight, "bond_trend": "Bull",
                "bond_sma_fast": sma_fast, "bond_sma_slow": sma_slow}
    else:
        # Bond Bear - use TMV
        return {"TMV": bond_weight, "Cash": cash_weight, "bond_trend": "Bear",
                "bond_sma_fast": sma_fast, "bond_sma_slow": sma_slow}

# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def run_regime_analysis(analysis_date: Optional[datetime] = None):
    """
    Main function to run independent regime analysis.

    Args:
        analysis_date: Optional date for historical regime analysis.
                      If None, uses today with live Schwab quotes.
                      If provided, uses only historical data up to that date.

    Returns comprehensive analysis results.
    """
    # Determine mode
    is_historical_mode = analysis_date is not None

    print("=" * 80)
    print("INDEPENDENT REGIME ANALYSIS - Hierarchical_Adaptive_v3_5b")
    print("=" * 80)

    if is_historical_mode:
        print(f"MODE: Historical Verification")
        print(f"Analysis Date: {analysis_date.strftime('%Y-%m-%d')} (using database data only)")
    else:
        print(f"MODE: Live Analysis")
        print(f"Analysis Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()

    # Step 1: Fetch historical data for all symbols
    print("Step 1: Fetching historical data from PostgreSQL...")
    symbols = [SIGNAL_SYMBOL, LEVERAGED_LONG_SYMBOL, INVERSE_HEDGE_SYMBOL,
               TREASURY_TREND_SYMBOL, BULL_BOND_SYMBOL, BEAR_BOND_SYMBOL]

    data = {}
    for symbol in symbols:
        df = fetch_historical_data(symbol, lookback_days=300, as_of_date=analysis_date)
        if len(df) == 0:
            print(f"  ERROR: No data found for {symbol} up to {analysis_date.strftime('%Y-%m-%d') if analysis_date else 'today'}")
            return None
        data[symbol] = df
        print(f"  {symbol}: {len(df)} bars, {df['timestamp'].min().date()} to {df['timestamp'].max().date()}")

    # Step 2: Get current quotes (from Schwab or database)
    if is_historical_mode:
        print(f"\nStep 2: Using database close prices for {analysis_date.strftime('%Y-%m-%d')}...")
        current_quotes = {}
        for symbol in symbols:
            # Use latest database close for that date
            latest = data[symbol].iloc[-1]
            current_quotes[symbol] = {
                'symbol': symbol,
                'last_price': latest['close'],
                'timestamp': latest['timestamp']
            }
            print(f"  {symbol}: ${latest['close']:.2f} (database close)")
    else:
        print("\nStep 2: Fetching current quotes from Schwab API...")
        current_quotes = {}
        for symbol in symbols:
            quote = get_current_quote_from_schwab(symbol)
            if quote:
                current_quotes[symbol] = quote
                print(f"  {symbol}: ${quote['last_price']:.2f}")
            else:
                # Use latest database close as fallback
                latest = data[symbol].iloc[-1]
                current_quotes[symbol] = {
                    'symbol': symbol,
                    'last_price': latest['close'],
                    'timestamp': latest['timestamp']
                }
                print(f"  {symbol}: ${latest['close']:.2f} (from database)")

    # Step 3: Prepare price series for calculations
    print("\nStep 3: Preparing price series...")
    qqq_df = data[SIGNAL_SYMBOL].copy()
    tlt_df = data[TREASURY_TREND_SYMBOL].copy()

    if is_historical_mode:
        # Historical mode: use database data as-is
        last_db_date = qqq_df['timestamp'].max().date()
        print(f"  Historical mode: Using database data up to {last_db_date}")
    else:
        # Live mode: Append current quote as pseudo-bar for today (if newer than last bar)
        last_db_date = qqq_df['timestamp'].max().date()
        current_date = datetime.now(timezone.utc).date()

        if current_date > last_db_date:
            print(f"  Adding pseudo-bar for today ({current_date}) using Schwab quotes")

            # Add QQQ pseudo-bar
            qqq_quote = current_quotes[SIGNAL_SYMBOL]
            new_row = pd.DataFrame([{
                'timestamp': datetime.now(timezone.utc),
                'open': qqq_quote.get('open', qqq_quote['last_price']),
                'high': qqq_quote.get('high', qqq_quote['last_price']),
                'low': qqq_quote.get('low', qqq_quote['last_price']),
                'close': qqq_quote['last_price'],
                'volume': qqq_quote.get('volume', 0)
            }])
            qqq_df = pd.concat([qqq_df, new_row], ignore_index=True)

            # Add TLT pseudo-bar
            tlt_quote = current_quotes[TREASURY_TREND_SYMBOL]
            new_row = pd.DataFrame([{
                'timestamp': datetime.now(timezone.utc),
                'open': tlt_quote.get('open', tlt_quote['last_price']),
                'high': tlt_quote.get('high', tlt_quote['last_price']),
                'low': tlt_quote.get('low', tlt_quote['last_price']),
                'close': tlt_quote['last_price'],
                'volume': tlt_quote.get('volume', 0)
            }])
            tlt_df = pd.concat([tlt_df, new_row], ignore_index=True)
        else:
            print(f"  Using database data for today ({last_db_date})")

    qqq_closes = qqq_df['close']
    tlt_closes = tlt_df['close']

    print(f"  QQQ price series: {len(qqq_closes)} bars")
    print(f"  TLT price series: {len(tlt_closes)} bars")

    # Step 4: Calculate Kalman Trend (T_norm)
    # Using AdaptiveKalmanFilter with EXACT backtest parameters for consistency
    print("\nStep 4: Calculating Kalman Trend (T_norm)...")
    
    # Initialize with exact backtest parameters from Hierarchical_Adaptive_v3_5b.py:340-352
    # Note: osc_smoothness=15 becomes effective=10 due to min(osc_smoothness, trend_lookback=10)
    kalman = AdaptiveKalmanFilter(
        model=KalmanFilterModel.VOLUME_ADJUSTED,  # Reduces measurement noise when volume increases
        measurement_noise=float(MEASUREMENT_NOISE),  # 3000.0
        process_noise_1=float(PROCESS_NOISE_1),      # 0.01
        process_noise_2=float(PROCESS_NOISE_2),      # 0.01
        osc_smoothness=OSC_SMOOTHNESS,               # 15 -> effective=min(15,10)=10
        strength_smoothness=STRENGTH_SMOOTHNESS,      # 15
        return_signed=True  # Returns signed trend strength [-100, 100]
    )

    # Process all bars through Kalman filter
    # trend_strength uses innovation-based calculation with WMA smoothing
    final_trend_strength = 0.0
    for idx, row in qqq_df.iterrows():
        filtered_price, trend_strength = kalman.update(
            close=float(row['close']),
            high=float(row['high']),
            low=float(row['low']),
            volume=int(row['volume'])
        )
        final_trend_strength = trend_strength  # Last value from loop
    
    # NOTE: Do NOT process last bar again - that was a bug in the original implementation
    # The final_trend_strength from the loop IS the correct value

    t_norm = Decimal(str(final_trend_strength)) / T_MAX
    t_norm = max(Decimal("-1.0"), min(Decimal("1.0"), t_norm))

    print(f"  Raw Trend Strength: {final_trend_strength:.4f}")
    print(f"  T_norm (normalized): {t_norm:.4f}")
    print(f"  T_norm Bull Threshold: > {T_NORM_BULL_THRESH}")
    print(f"  T_norm Bear Threshold: < {T_NORM_BEAR_THRESH}")

    # Step 5: Calculate SMA Structure
    print("\nStep 5: Calculating SMA Structure...")
    sma_fast_series = calculate_sma(qqq_closes, SMA_FAST)
    sma_slow_series = calculate_sma(qqq_closes, SMA_SLOW)

    sma_fast_val = sma_fast_series.iloc[-1]
    sma_slow_val = sma_slow_series.iloc[-1]

    print(f"  SMA_fast ({SMA_FAST}-day): ${sma_fast_val:.2f}")
    print(f"  SMA_slow ({SMA_SLOW}-day): ${sma_slow_val:.2f}")
    print(f"  Structural Trend: {'Bull (SMA_fast > SMA_slow)' if sma_fast_val > sma_slow_val else 'Bear (SMA_fast < SMA_slow)'}")

    # Step 6: Calculate Volatility Z-Score
    print("\nStep 6: Calculating Volatility Z-Score...")
    z_score = calculate_volatility_zscore(qqq_closes)

    # Calculate realized vol for display
    realized_vol = calculate_annualized_volatility(qqq_closes, REALIZED_VOL_WINDOW).iloc[-1]
    vol_series = calculate_annualized_volatility(qqq_closes, REALIZED_VOL_WINDOW)
    vol_baseline_mean = vol_series.tail(VOL_BASELINE_WINDOW).mean()
    vol_baseline_std = vol_series.tail(VOL_BASELINE_WINDOW).std()

    print(f"  Realized Vol ({REALIZED_VOL_WINDOW}-day): {realized_vol:.2%}")
    print(f"  Baseline Mean ({VOL_BASELINE_WINDOW}-day): {vol_baseline_mean:.2%}")
    print(f"  Baseline Std: {vol_baseline_std:.2%}")
    print(f"  Z-Score: {z_score:.4f}")
    print(f"  Upper Threshold: {UPPER_THRESH_Z} (→ High Vol)")
    print(f"  Lower Threshold: {LOWER_THRESH_Z} (→ Low Vol)")

    # Step 7: Determine Vol State with TRUE Hysteresis (Matches Backtest Exactly)
    print("\nStep 7: Determining Volatility State (TRUE Hysteresis)...")
    print("  Processing ALL historical bars to track state transitions...")

    # Use TRUE hysteresis function that processes all bars sequentially
    # This matches backtest behavior exactly: maintains state in deadband
    vol_state, hysteresis_z_score, hysteresis_info = calculate_vol_state_with_hysteresis(
        qqq_closes,
        upper_thresh_z=UPPER_THRESH_Z,
        lower_thresh_z=LOWER_THRESH_Z,
        realized_vol_window=REALIZED_VOL_WINDOW,
        vol_baseline_window=VOL_BASELINE_WINDOW
    )

    # Build reason string based on hysteresis result
    if "error" in hysteresis_info:
        vol_state_reason = f"Error: {hysteresis_info['error']}"
    elif "warning" in hysteresis_info:
        vol_state_reason = f"Warning: {hysteresis_info['warning']}"
    elif z_score > UPPER_THRESH_Z:
        vol_state_reason = f"z_score ({z_score:.4f}) > upper_thresh ({UPPER_THRESH_Z}) → High"
    elif z_score < LOWER_THRESH_Z:
        vol_state_reason = f"z_score ({z_score:.4f}) < lower_thresh ({LOWER_THRESH_Z}) → Low"
    else:
        vol_state_reason = f"z_score ({z_score:.4f}) in deadband [{LOWER_THRESH_Z}, {UPPER_THRESH_Z}] → MAINTAINED from hysteresis history"

    print(f"  Vol State: {vol_state}")
    print(f"  Reason: {vol_state_reason}")

    # Show hysteresis diagnostics
    if "error" not in hysteresis_info:
        print(f"  Hysteresis History:")
        print(f"    - Total bars processed: {hysteresis_info['total_bars_processed']}")
        print(f"    - Initial state: {hysteresis_info['initial_state']} (at {hysteresis_info['initial_date']})")
        print(f"    - Deadband bars (state maintained): {hysteresis_info['deadband_bars']}")
        print(f"    - State transitions: {len(hysteresis_info['transitions']) - 1}")  # -1 for init

        # Show recent transitions (last 5)
        transitions = hysteresis_info['transitions']
        if len(transitions) > 1:  # More than just init
            print(f"    - Recent transitions:")
            for t in transitions[-5:]:
                if t['type'] == 'init':
                    print(f"        INIT @ {t['date']}: → {t['new_state']} (z={t['z_score']:.3f})")
                else:
                    print(f"        {t['date']}: {t['from_state']} → {t['to_state']} (z={t['z_score']:.3f})")

    # Step 8: Check Vol-Crush Override
    print("\nStep 8: Checking Vol-Crush Override...")
    vol_crush_triggered = check_vol_crush(qqq_closes)

    if vol_crush_triggered:
        print(f"  Vol-Crush TRIGGERED: Vol dropped >{abs(float(VOL_CRUSH_THRESHOLD)):.0%} in {VOL_CRUSH_LOOKBACK} days")
        vol_state = "Low"  # Force Low
    else:
        print(f"  Vol-Crush NOT triggered")

    # Step 9: Classify Trend Regime
    print("\nStep 9: Classifying Trend Regime...")
    trend_state = classify_trend_regime(t_norm, sma_fast_val, sma_slow_val)

    # Apply vol-crush override to trend
    original_trend = trend_state
    if vol_crush_triggered and trend_state == "BearStrong":
        trend_state = "Sideways"
        print(f"  Vol-Crush Override: {original_trend} → {trend_state}")

    print(f"  Trend State: {trend_state}")
    print(f"  Logic:")
    print(f"    - T_norm ({t_norm:.4f}) {'>' if t_norm > T_NORM_BULL_THRESH else '<='} Bull threshold ({T_NORM_BULL_THRESH})")
    print(f"    - T_norm ({t_norm:.4f}) {'<' if t_norm < T_NORM_BEAR_THRESH else '>='} Bear threshold ({T_NORM_BEAR_THRESH})")
    print(f"    - SMA Structure: {'Bull' if sma_fast_val > sma_slow_val else 'Bear'}")

    # Step 10: Get Cell ID and Base Allocation
    print("\nStep 10: Determining Regime Cell...")
    cell_id = get_cell_id(trend_state, vol_state)
    base_allocation = get_cell_allocation(cell_id)

    cell_names = {
        1: "Kill Zone (Bull/Low)",
        2: "Fragile (Bull/High)",
        3: "Drift (Sideways/Low)",
        4: "Chop (Sideways/High)",
        5: "Grind (Bear/Low)",
        6: "Crash (Bear/High)"
    }

    print(f"  Cell ID: {cell_id}")
    print(f"  Cell Name: {cell_names[cell_id]}")
    print(f"  Base Allocation:")
    for symbol, weight in base_allocation.items():
        if weight > 0:
            print(f"    - {symbol}: {weight:.0%}")

    # Step 11: Apply Treasury Overlay (if defensive cell)
    print("\nStep 11: Applying Treasury Overlay...")
    final_allocation = base_allocation.copy()
    bond_info = None

    if ALLOW_TREASURY and cell_id in [4, 5, 6]:
        defensive_weight = base_allocation.get("Cash", Decimal("0"))
        if defensive_weight > 0:
            safe_haven = get_safe_haven_allocation(tlt_closes, defensive_weight)
            bond_info = safe_haven.copy()

            print(f"  Defensive Weight: {defensive_weight:.0%}")
            print(f"  TLT SMA_fast ({BOND_SMA_FAST}): ${safe_haven.get('bond_sma_fast', 0):.2f}")
            print(f"  TLT SMA_slow ({BOND_SMA_SLOW}): ${safe_haven.get('bond_sma_slow', 0):.2f}")
            print(f"  Bond Trend: {safe_haven.get('bond_trend', 'Unknown')}")

            # Update allocation
            final_allocation["Cash"] = safe_haven.get("Cash", Decimal("0"))
            if "TMF" in safe_haven:
                final_allocation["TMF"] = safe_haven["TMF"]
                print(f"  Safe Haven: TMF (3x Bull Bonds - Deflation Hedge)")
            elif "TMV" in safe_haven:
                final_allocation["TMV"] = safe_haven["TMV"]
                print(f"  Safe Haven: TMV (3x Bear Bonds - Inflation Hedge)")
    else:
        if ALLOW_TREASURY:
            print(f"  Cell {cell_id} is not defensive - Treasury Overlay not applied")
        else:
            print(f"  Treasury Overlay disabled")

    # Step 12: Final Results
    print("\n" + "=" * 80)
    if is_historical_mode:
        print(f"FINAL RESULTS - Regime for {analysis_date.strftime('%Y-%m-%d')}")
    else:
        print("FINAL RESULTS - Current Market Regime & Allocation")
    print("=" * 80)

    print(f"\n📊 {'HISTORICAL ' if is_historical_mode else 'CURRENT '}REGIME:")
    print(f"   Trend State:     {trend_state}")
    print(f"   Volatility State: {vol_state}")
    print(f"   Regime Cell:      {cell_id} ({cell_names[cell_id]})")

    print(f"\n📈 INDICATOR VALUES:")
    print(f"   QQQ Current:      ${current_quotes[SIGNAL_SYMBOL]['last_price']:.2f}")
    print(f"   T_norm:           {t_norm:.4f}")
    print(f"   SMA_fast ({SMA_FAST}):    ${sma_fast_val:.2f}")
    print(f"   SMA_slow ({SMA_SLOW}):   ${sma_slow_val:.2f}")
    print(f"   Vol Z-Score:      {z_score:.4f}")
    print(f"   Realized Vol:     {realized_vol:.2%}")
    print(f"   Vol-Crush:        {'Triggered' if vol_crush_triggered else 'Not Triggered'}")

    if bond_info and cell_id in [4, 5, 6]:
        print(f"\n🏦 TREASURY OVERLAY:")
        print(f"   TLT Current:      ${current_quotes[TREASURY_TREND_SYMBOL]['last_price']:.2f}")
        print(f"   Bond Trend:       {bond_info.get('bond_trend', 'N/A')}")
        print(f"   Bond SMA_fast:    ${bond_info.get('bond_sma_fast', 0):.2f}")
        print(f"   Bond SMA_slow:    ${bond_info.get('bond_sma_slow', 0):.2f}")

    print(f"\n💰 TARGET ALLOCATION:")
    for symbol in ["TQQQ", "QQQ", "PSQ", "TMF", "TMV", "Cash"]:
        weight = final_allocation.get(symbol, Decimal("0"))
        if weight > 0:
            # Get current price
            if symbol == "Cash":
                print(f"   {symbol}: {weight:.1%}")
            else:
                price = current_quotes.get(symbol, {}).get('last_price', 'N/A')
                if price != 'N/A':
                    print(f"   {symbol}: {weight:.1%} (Current: ${price:.2f})")
                else:
                    print(f"   {symbol}: {weight:.1%}")

    # Calculate Net Beta
    net_beta = (
        float(final_allocation.get("TQQQ", 0)) * 3.0 +
        float(final_allocation.get("QQQ", 0)) * 1.0 +
        float(final_allocation.get("PSQ", 0)) * -1.0
    )
    print(f"\n🎯 NET BETA: {net_beta:.2f}")

    print("\n" + "=" * 80)
    print("Analysis Complete")
    print("=" * 80)

    return {
        'analysis_date': analysis_date.strftime('%Y-%m-%d') if analysis_date else datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'mode': 'historical' if is_historical_mode else 'live',
        'trend_state': trend_state,
        'vol_state': vol_state,
        'cell_id': cell_id,
        'cell_name': cell_names[cell_id],
        't_norm': float(t_norm),
        'z_score': float(z_score),
        'sma_fast': sma_fast_val,
        'sma_slow': sma_slow_val,
        'realized_vol': realized_vol,
        'vol_crush_triggered': vol_crush_triggered,
        'allocation': {k: float(v) for k, v in final_allocation.items()},
        'net_beta': net_beta,
        'current_prices': {s: q.get('last_price') for s, q in current_quotes.items()}
    }

# =============================================================================
# ENTRY POINT
# =============================================================================

def parse_date(date_str: str) -> datetime:
    """Parse a date string in various formats."""
    formats = ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d']
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}. Use format YYYY-MM-DD (e.g., 2025-12-09)")

def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description='Independent Regime Analysis for Hierarchical_Adaptive_v3_5b Strategy',
        epilog='''
Examples:
  %(prog)s                    # Today's analysis with live Schwab quotes
  %(prog)s 2025-12-09         # Historical analysis for Dec 9, 2025
  %(prog)s --date 2025-12-09  # Same as above
  %(prog)s --date 12/09/2025  # Alternative date format
        '''
    )
    parser.add_argument(
        'date',
        nargs='?',
        default=None,
        help='Analysis date (YYYY-MM-DD format). If omitted, analyzes today with live quotes.'
    )
    parser.add_argument(
        '--date', '-d',
        dest='date_flag',
        default=None,
        help='Analysis date (alternative to positional argument)'
    )

    args = parser.parse_args()

    # Determine the date to use
    date_str = args.date_flag or args.date
    analysis_date = None

    if date_str:
        try:
            analysis_date = parse_date(date_str)
            # Verify the date is not in the future
            if analysis_date.date() > datetime.now(timezone.utc).date():
                print(f"Error: Analysis date {analysis_date.strftime('%Y-%m-%d')} is in the future")
                sys.exit(1)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

    try:
        results = run_regime_analysis(analysis_date)
        if results:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        print(f"\nError during analysis: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
