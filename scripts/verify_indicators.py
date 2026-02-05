#!/usr/bin/env python3
"""
Verify Indicators - Diagnostic Script for Z-Score Discrepancy Investigation

This script independently calculates all indicators using the SAME functions
as the strategy to verify z-score calculations match expected values.

Purpose:
    - Load closes from database for the signal symbol (QQQ)
    - Compute all indicators using production functions
    - Compare with backtest CSV output
    - Show intermediate values to identify discrepancy source

Usage:
    python scripts/verify_indicators.py                     # Feb 4, 2026 (default)
    python scripts/verify_indicators.py 2026-02-04         # Specific date
    python scripts/verify_indicators.py --date 2026-02-03  # Same as above
    python scripts/verify_indicators.py --bars 221         # Custom bar count
    python scripts/verify_indicators.py --csv output/.../signals_log.csv  # Compare with CSV

Author: Claude Analysis
Date: 2026-02-04
"""

import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
import pandas as pd
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import production functions
from jutsu_engine.indicators.technical import sma, annualized_volatility
from jutsu_engine.indicators.kalman import AdaptiveKalmanFilter, KalmanFilterModel

# Database connection
import psycopg2
from psycopg2.extras import RealDictCursor

# =============================================================================
# CONFIGURATION (from config/strategies/v3_5d.yaml)
# =============================================================================

# Default parameters matching v3_5d config
DEFAULT_CONFIG = {
    # Volatility Z-Score Parameters
    'vol_baseline_window': 200,
    'realized_vol_window': 21,
    'upper_thresh_z': Decimal("1.0"),
    'lower_thresh_z': Decimal("0.2"),

    # Vol-Crush Override
    'vol_crush_threshold': Decimal("-0.15"),
    'vol_crush_lookback': 5,

    # Structural Trend Parameters
    'sma_fast': 40,
    'sma_slow': 140,
    't_norm_bull_thresh': Decimal("0.05"),
    't_norm_bear_thresh': Decimal("-0.30"),

    # Kalman Trend Parameters
    'measurement_noise': 3000.0,
    'process_noise_1': 0.01,
    'process_noise_2': 0.01,
    'osc_smoothness': 15,
    'strength_smoothness': 15,
    'T_max': Decimal("50.0"),

    # Symbols
    'signal_symbol': 'QQQ',
}

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


def fetch_closes(
    symbol: str,
    as_of_date: datetime,
    lookback_bars: Optional[int] = None
) -> pd.DataFrame:
    """
    Fetch historical close prices from PostgreSQL.

    Args:
        symbol: Stock symbol (e.g., 'QQQ')
        as_of_date: Fetch data up to and including this date
        lookback_bars: If provided, limit to last N bars; otherwise fetch ALL data

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    conn = get_db_connection()

    try:
        if lookback_bars:
            # Fetch limited history (simulating backtest behavior)
            query = """
                SELECT timestamp, open, high, low, close, volume
                FROM market_data
                WHERE symbol = %s
                  AND timeframe = '1D'
                  AND is_valid = true
                  AND DATE(timestamp) <= %s
                ORDER BY timestamp DESC
                LIMIT %s
            """
            params = (symbol, as_of_date.strftime('%Y-%m-%d'), lookback_bars)
            df = pd.read_sql_query(query, conn, params=params)
            # Reverse to get chronological order
            df = df.iloc[::-1].reset_index(drop=True)
        else:
            # Fetch ALL historical data
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


# =============================================================================
# INDICATOR CALCULATION FUNCTIONS
# =============================================================================

def calculate_zscore(
    closes: pd.Series,
    vol_baseline_window: int = 200,
    realized_vol_window: int = 21,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Calculate z-score using production functions with detailed output.

    This mirrors _calculate_volatility_zscore() from the strategy.

    Args:
        closes: Series of close prices
        vol_baseline_window: Window for baseline statistics (default: 200)
        realized_vol_window: Window for realized volatility (default: 21)
        verbose: Print detailed intermediate values

    Returns:
        Dict with all intermediate values and final z-score
    """
    result = {
        'closes_count': len(closes),
        'min_required': vol_baseline_window + realized_vol_window,
        'sufficient_data': len(closes) >= vol_baseline_window + realized_vol_window,
    }

    if not result['sufficient_data']:
        result['error'] = f"Insufficient data: {len(closes)} < {result['min_required']}"
        return result

    # Calculate volatility series using production function
    vol_series = annualized_volatility(closes, lookback=realized_vol_window)

    result['vol_series_length'] = len(vol_series)
    result['vol_series_valid_count'] = vol_series.dropna().shape[0]

    # Check if enough vol values
    if len(vol_series) < vol_baseline_window:
        result['error'] = f"Vol series too short: {len(vol_series)} < {vol_baseline_window}"
        return result

    # Get last vol_baseline_window values (THIS IS THE KEY OPERATION)
    vol_values = vol_series.tail(vol_baseline_window)
    vol_values_clean = vol_values.dropna()

    result['vol_values_tail_length'] = len(vol_values)
    result['vol_values_clean_length'] = len(vol_values_clean)

    if len(vol_values_clean) < vol_baseline_window - 10:
        result['error'] = f"Vol values too short after dropna: {len(vol_values_clean)}"
        return result

    # Calculate baseline statistics
    vol_mean = float(vol_values_clean.mean())
    vol_std = float(vol_values_clean.std())

    result['vol_mean'] = vol_mean
    result['vol_std'] = vol_std

    if vol_std == 0:
        result['error'] = "Vol std is zero"
        result['z_score'] = 0.0
        return result

    # Current realized volatility (latest value)
    sigma_t = float(vol_series.iloc[-1])
    result['sigma_t'] = sigma_t

    # Z-score calculation
    z_score = (sigma_t - vol_mean) / vol_std
    result['z_score'] = z_score

    # Additional debug info
    if verbose:
        # First and last 5 vol values used in baseline
        result['vol_baseline_first_5'] = vol_values_clean.head(5).tolist()
        result['vol_baseline_last_5'] = vol_values_clean.tail(5).tolist()

        # Date range of vol values used
        if hasattr(vol_values_clean, 'index'):
            try:
                result['vol_baseline_start_date'] = str(vol_values_clean.index[0])
                result['vol_baseline_end_date'] = str(vol_values_clean.index[-1])
            except:
                pass

    return result


def calculate_kalman_trend(
    df: pd.DataFrame,
    config: Dict[str, Any]
) -> Tuple[float, float]:
    """
    Calculate Kalman trend strength by processing ALL bars.

    This mirrors the strategy's Kalman filter initialization and update.

    Args:
        df: DataFrame with OHLCV data
        config: Configuration parameters

    Returns:
        Tuple of (filtered_price, T_norm)
    """
    # Initialize Kalman filter with production parameters
    kalman_filter = AdaptiveKalmanFilter(
        model=KalmanFilterModel.VOLUME_ADJUSTED,
        measurement_noise=config['measurement_noise'],
        process_noise_1=config['process_noise_1'],
        process_noise_2=config['process_noise_2'],
        osc_smoothness=config['osc_smoothness'],
        strength_smoothness=config.get('strength_smoothness', 15),
        return_signed=True  # Strategy uses signed T_norm
    )

    # Process all bars
    filtered_price = None
    trend_strength_signed = None

    for _, row in df.iterrows():
        filtered_price, trend_strength_signed = kalman_filter.update(
            close=row['close'],
            high=row['high'],
            low=row['low'],
            volume=row['volume']
        )

    # Calculate T_norm (normalized trend strength)
    if trend_strength_signed is not None:
        T_norm = float(Decimal(str(trend_strength_signed)) / config['T_max'])
        T_norm = max(-1.0, min(1.0, T_norm))  # Clamp to [-1, 1]
    else:
        T_norm = 0.0

    return float(filtered_price) if filtered_price else 0.0, T_norm


def check_vol_crush(
    closes: pd.Series,
    vol_crush_threshold: Decimal = Decimal("-0.15"),
    vol_crush_lookback: int = 5,
    realized_vol_window: int = 21
) -> Tuple[bool, Dict[str, Any]]:
    """
    Check for vol-crush override.

    Args:
        closes: Series of close prices
        vol_crush_threshold: Threshold for vol drop (default: -0.15)
        vol_crush_lookback: Days to look back (default: 5)
        realized_vol_window: Window for realized vol (default: 21)

    Returns:
        Tuple of (triggered, details)
    """
    details = {
        'vol_crush_threshold': float(vol_crush_threshold),
        'vol_crush_lookback': vol_crush_lookback,
    }

    if len(closes) < realized_vol_window + vol_crush_lookback:
        details['error'] = "Insufficient data for vol crush check"
        return False, details

    vol_series = annualized_volatility(closes, lookback=realized_vol_window)

    if len(vol_series) < vol_crush_lookback + 1:
        details['error'] = "Vol series too short for vol crush check"
        return False, details

    sigma_t = float(vol_series.iloc[-1])
    sigma_t_minus_n = float(vol_series.iloc[-(vol_crush_lookback + 1)])

    details['sigma_t'] = sigma_t
    details['sigma_t_minus_n'] = sigma_t_minus_n

    if sigma_t_minus_n == 0:
        details['error'] = "sigma_t_minus_n is zero"
        return False, details

    vol_change = (sigma_t - sigma_t_minus_n) / sigma_t_minus_n
    details['vol_change'] = vol_change

    triggered = vol_change < float(vol_crush_threshold)
    details['triggered'] = triggered

    return triggered, details


def load_backtest_csv(csv_path: str, target_date: datetime) -> Optional[Dict[str, Any]]:
    """
    Load backtest CSV and extract values for target date.

    Args:
        csv_path: Path to signals_log.csv
        target_date: Date to extract values for

    Returns:
        Dict with backtest values or None if not found
    """
    if not os.path.exists(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path)

        # Parse date column
        if 'timestamp' in df.columns:
            df['date'] = pd.to_datetime(df['timestamp']).dt.date
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.date
        else:
            return None

        # Find target date row
        target_date_only = target_date.date() if hasattr(target_date, 'date') else target_date
        row = df[df['date'] == target_date_only]

        if row.empty:
            return None

        row = row.iloc[-1]  # Get last row for that date

        result = {}

        # Extract available columns
        column_mapping = {
            'z_score': ['z_score', 'vol_zscore', 'volatility_zscore'],
            't_norm': ['t_norm', 'T_norm', 'trend_norm', 'kalman_trend'],
            'vol_state': ['vol_state', 'VolState', 'volatility_state'],
            'trend_state': ['trend_state', 'TrendState'],
            'cell_id': ['cell_id', 'cell', 'regime_cell'],
            'sma_fast': ['sma_fast', 'SMA_fast'],
            'sma_slow': ['sma_slow', 'SMA_slow'],
        }

        for key, possible_cols in column_mapping.items():
            for col in possible_cols:
                if col in row.index:
                    result[key] = row[col]
                    break

        return result

    except Exception as e:
        print(f"Error loading CSV: {e}")
        return None


# =============================================================================
# MAIN VERIFICATION FUNCTION
# =============================================================================

def verify_indicators(
    target_date: datetime,
    symbol: str = 'QQQ',
    config: Optional[Dict[str, Any]] = None,
    lookback_bars: Optional[int] = None,
    csv_path: Optional[str] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Main verification function - computes all indicators and compares.

    Args:
        target_date: Date to verify indicators for
        symbol: Signal symbol (default: QQQ)
        config: Strategy configuration (uses defaults if None)
        lookback_bars: If provided, simulate backtest with limited bars
        csv_path: Path to backtest CSV for comparison
        verbose: Print detailed output

    Returns:
        Dict with all computed values and comparison results
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    result = {
        'target_date': str(target_date.date()),
        'symbol': symbol,
        'lookback_bars': lookback_bars,
        'config': {k: float(v) if isinstance(v, Decimal) else v
                   for k, v in config.items() if k not in ['signal_symbol']},
    }

    # ==========================================================================
    # Step 1: Fetch Data
    # ==========================================================================
    print(f"\n{'='*70}")
    print(f"INDICATOR VERIFICATION - {target_date.date()}")
    print(f"{'='*70}")

    print(f"\n[1] FETCHING DATA")
    print(f"    Symbol: {symbol}")
    print(f"    As of date: {target_date.date()}")
    print(f"    Lookback bars: {'ALL (full history)' if lookback_bars is None else lookback_bars}")

    df = fetch_closes(symbol, target_date, lookback_bars)

    result['data_info'] = {
        'total_bars': len(df),
        'first_date': str(df['timestamp'].iloc[0].date()) if len(df) > 0 else None,
        'last_date': str(df['timestamp'].iloc[-1].date()) if len(df) > 0 else None,
    }

    print(f"    Total bars loaded: {len(df)}")
    print(f"    Date range: {result['data_info']['first_date']} to {result['data_info']['last_date']}")

    if len(df) == 0:
        result['error'] = "No data fetched"
        return result

    # Create close series with timestamp index
    closes = pd.Series(df['close'].values, index=df['timestamp'])

    # ==========================================================================
    # Step 2: Calculate SMA
    # ==========================================================================
    print(f"\n[2] CALCULATING SMA")

    sma_fast_series = sma(closes, config['sma_fast'])
    sma_slow_series = sma(closes, config['sma_slow'])

    sma_fast_val = float(sma_fast_series.iloc[-1]) if not pd.isna(sma_fast_series.iloc[-1]) else None
    sma_slow_val = float(sma_slow_series.iloc[-1]) if not pd.isna(sma_slow_series.iloc[-1]) else None

    result['sma'] = {
        'sma_fast': sma_fast_val,
        'sma_slow': sma_slow_val,
        'structural_trend': 'Bull' if sma_fast_val and sma_slow_val and sma_fast_val > sma_slow_val else 'Bear',
    }

    print(f"    SMA_fast ({config['sma_fast']}): ${sma_fast_val:.2f}" if sma_fast_val else "    SMA_fast: N/A")
    print(f"    SMA_slow ({config['sma_slow']}): ${sma_slow_val:.2f}" if sma_slow_val else "    SMA_slow: N/A")
    print(f"    Structural Trend: {result['sma']['structural_trend']}")

    # ==========================================================================
    # Step 3: Calculate Kalman Trend
    # ==========================================================================
    print(f"\n[3] CALCULATING KALMAN TREND")

    filtered_price, T_norm = calculate_kalman_trend(df, config)

    result['kalman'] = {
        'filtered_price': filtered_price,
        'T_norm': T_norm,
        'T_max': float(config['T_max']),
    }

    print(f"    Filtered Price: ${filtered_price:.2f}")
    print(f"    T_norm: {T_norm:.6f}")
    print(f"    T_max: {config['T_max']}")

    # ==========================================================================
    # Step 4: Calculate Volatility Z-Score (THE KEY CALCULATION)
    # ==========================================================================
    print(f"\n[4] CALCULATING VOLATILITY Z-SCORE")
    print(f"    vol_baseline_window: {config['vol_baseline_window']}")
    print(f"    realized_vol_window: {config['realized_vol_window']}")

    zscore_result = calculate_zscore(
        closes,
        vol_baseline_window=config['vol_baseline_window'],
        realized_vol_window=config['realized_vol_window'],
        verbose=verbose
    )

    result['zscore'] = zscore_result

    print(f"\n    --- Z-Score Calculation Details ---")
    print(f"    Closes count: {zscore_result['closes_count']}")
    print(f"    Min required: {zscore_result['min_required']}")
    print(f"    Sufficient data: {zscore_result['sufficient_data']}")

    if 'error' in zscore_result:
        print(f"    ERROR: {zscore_result['error']}")
    else:
        print(f"    Vol series length: {zscore_result['vol_series_length']}")
        print(f"    Vol series valid count: {zscore_result['vol_series_valid_count']}")
        print(f"    Vol values in tail({config['vol_baseline_window']}): {zscore_result['vol_values_tail_length']}")
        print(f"    Vol values clean (no NaN): {zscore_result['vol_values_clean_length']}")
        print(f"\n    sigma_t (current vol): {zscore_result['sigma_t']:.6f} ({zscore_result['sigma_t']*100:.2f}%)")
        print(f"    mu_vol (baseline mean): {zscore_result['vol_mean']:.6f} ({zscore_result['vol_mean']*100:.2f}%)")
        print(f"    sigma_vol (baseline std): {zscore_result['vol_std']:.6f} ({zscore_result['vol_std']*100:.2f}%)")
        print(f"\n    >>> Z-SCORE: {zscore_result['z_score']:.6f} <<<")

        if verbose and 'vol_baseline_start_date' in zscore_result:
            print(f"\n    Baseline period: {zscore_result['vol_baseline_start_date']} to {zscore_result['vol_baseline_end_date']}")
            print(f"    First 5 vol values: {[f'{v:.4f}' for v in zscore_result['vol_baseline_first_5']]}")
            print(f"    Last 5 vol values: {[f'{v:.4f}' for v in zscore_result['vol_baseline_last_5']]}")

    # ==========================================================================
    # Step 5: Check Vol-Crush Override
    # ==========================================================================
    print(f"\n[5] CHECKING VOL-CRUSH OVERRIDE")

    vol_crush_triggered, vol_crush_details = check_vol_crush(
        closes,
        vol_crush_threshold=config['vol_crush_threshold'],
        vol_crush_lookback=config['vol_crush_lookback'],
        realized_vol_window=config['realized_vol_window']
    )

    result['vol_crush'] = vol_crush_details

    if 'error' in vol_crush_details:
        print(f"    ERROR: {vol_crush_details['error']}")
    else:
        print(f"    sigma_t: {vol_crush_details['sigma_t']:.6f}")
        print(f"    sigma_t-{config['vol_crush_lookback']}: {vol_crush_details['sigma_t_minus_n']:.6f}")
        print(f"    Vol change: {vol_crush_details['vol_change']:.4f} ({vol_crush_details['vol_change']*100:.2f}%)")
        print(f"    Threshold: {config['vol_crush_threshold']}")
        print(f"    Vol-Crush Triggered: {vol_crush_triggered}")

    # ==========================================================================
    # Step 6: Classify Regime
    # ==========================================================================
    print(f"\n[6] CLASSIFYING REGIME")

    # Determine trend state
    t_norm_bull_thresh = float(config['t_norm_bull_thresh'])
    t_norm_bear_thresh = float(config['t_norm_bear_thresh'])

    if T_norm >= t_norm_bull_thresh:
        if sma_fast_val and sma_slow_val and sma_fast_val > sma_slow_val:
            trend_state = "BullStrong"
        else:
            trend_state = "Sideways"
    elif T_norm <= t_norm_bear_thresh:
        trend_state = "BearStrong"
    else:
        trend_state = "Sideways"

    result['regime'] = {
        'trend_state': trend_state,
        't_norm_bull_thresh': t_norm_bull_thresh,
        't_norm_bear_thresh': t_norm_bear_thresh,
    }

    print(f"    T_norm: {T_norm:.6f}")
    print(f"    Bull threshold: {t_norm_bull_thresh}")
    print(f"    Bear threshold: {t_norm_bear_thresh}")
    print(f"    Trend State: {trend_state}")

    # ==========================================================================
    # Step 7: Compare with Backtest CSV (if provided)
    # ==========================================================================
    if csv_path:
        print(f"\n[7] COMPARING WITH BACKTEST CSV")
        print(f"    CSV path: {csv_path}")

        backtest_values = load_backtest_csv(csv_path, target_date)
        result['backtest_comparison'] = backtest_values

        if backtest_values:
            print(f"\n    --- Backtest Values ---")
            for key, val in backtest_values.items():
                print(f"    {key}: {val}")

            print(f"\n    --- Comparison ---")
            if 'z_score' in backtest_values and 'z_score' in zscore_result:
                diff = zscore_result['z_score'] - float(backtest_values['z_score'])
                print(f"    Z-Score: Calculated={zscore_result['z_score']:.6f}, Backtest={backtest_values['z_score']:.6f}, Diff={diff:.6f}")

            if 't_norm' in backtest_values:
                diff = T_norm - float(backtest_values['t_norm'])
                print(f"    T_norm: Calculated={T_norm:.6f}, Backtest={backtest_values['t_norm']:.6f}, Diff={diff:.6f}")
        else:
            print(f"    No matching data found in CSV for {target_date.date()}")

    # ==========================================================================
    # Summary
    # ==========================================================================
    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"Date: {target_date.date()}")
    print(f"Data: {len(df)} bars ({result['data_info']['first_date']} to {result['data_info']['last_date']})")
    print(f"SMA_fast: ${sma_fast_val:.2f}, SMA_slow: ${sma_slow_val:.2f} → {result['sma']['structural_trend']}")
    print(f"T_norm: {T_norm:.6f} → {trend_state}")
    if 'z_score' in zscore_result:
        print(f"Z-Score: {zscore_result['z_score']:.6f}")
    print(f"Vol-Crush: {vol_crush_triggered}")
    print(f"{'='*70}\n")

    return result


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Verify indicator calculations against backtest/database values",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/verify_indicators.py                     # Feb 4, 2026 with full history
  python scripts/verify_indicators.py 2026-02-03         # Specific date
  python scripts/verify_indicators.py --bars 221         # Simulate backtest with 221 bars
  python scripts/verify_indicators.py --bars 373         # Simulate 373-bar backtest
  python scripts/verify_indicators.py --csv output/.../signals_log.csv
        """
    )

    parser.add_argument(
        'date',
        nargs='?',
        default='2026-02-04',
        help='Target date (YYYY-MM-DD format, default: 2026-02-04)'
    )

    parser.add_argument(
        '--date', '-d',
        dest='date_flag',
        help='Target date (alternative to positional argument)'
    )

    parser.add_argument(
        '--symbol', '-s',
        default='QQQ',
        help='Signal symbol (default: QQQ)'
    )

    parser.add_argument(
        '--bars', '-b',
        type=int,
        default=None,
        help='Limit to last N bars (simulate backtest); omit for full history'
    )

    parser.add_argument(
        '--csv', '-c',
        help='Path to backtest signals_log.csv for comparison'
    )

    parser.add_argument(
        '--vol-baseline', '-vb',
        type=int,
        default=200,
        help='Vol baseline window (default: 200)'
    )

    parser.add_argument(
        '--realized-vol', '-rv',
        type=int,
        default=21,
        help='Realized vol window (default: 21)'
    )

    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Minimal output (summary only)'
    )

    args = parser.parse_args()

    # Determine target date
    date_str = args.date_flag if args.date_flag else args.date
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Error: Invalid date format '{date_str}'. Use YYYY-MM-DD.")
        sys.exit(1)

    # Build config
    config = DEFAULT_CONFIG.copy()
    config['vol_baseline_window'] = args.vol_baseline
    config['realized_vol_window'] = args.realized_vol

    # Run verification
    result = verify_indicators(
        target_date=target_date,
        symbol=args.symbol,
        config=config,
        lookback_bars=args.bars,
        csv_path=args.csv,
        verbose=not args.quiet
    )

    # Exit with error if z-score couldn't be calculated
    if 'error' in result.get('zscore', {}):
        sys.exit(1)


if __name__ == '__main__':
    main()
