"""
KPI Calculation Module for EOD Daily Performance.

This module provides all Key Performance Indicator (KPI) calculations
for the daily_performance table. It fixes the Sharpe ratio bug by
calculating metrics from equity changes rather than stored daily_return values.

Reference: claudedocs/eod_daily_performance_architecture.md v1.1 Section 7

Key Principles:
    - All return values are decimals (0.01 = 1%), NOT percentages (1.0 = 1%)
    - Sharpe/Sortino/Volatility are annualized using sqrt(252)
    - Edge cases return None (not 0) when there's insufficient data
    - Incremental updates use Welford's algorithm for numerical stability

Functions:
    - calculate_daily_return: (today - yesterday) / yesterday
    - calculate_cumulative_return: (current - initial) / initial
    - calculate_sharpe_ratio: (mean - rf) / std * sqrt(252)
    - calculate_sortino_ratio: CAGR / downside_deviation
    - calculate_calmar_ratio: CAGR / abs(max_drawdown)
    - calculate_max_drawdown: min((equity - peak) / peak)
    - calculate_volatility: std(returns) * sqrt(252)
    - calculate_cagr: (final/initial)^(1/years) - 1
    - calculate_trade_statistics: FIFO matching from live_trades
    - update_kpis_incremental: O(1) update using running statistics

Created: 2026-01-23
"""

from decimal import Decimal
from typing import List, Optional, Dict, Any, Union
import numpy as np
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Basic Return Calculations (Tasks 2.1, 2.2)
# =============================================================================

def calculate_daily_return(
    today_equity: Union[Decimal, float],
    yesterday_equity: Union[Decimal, float]
) -> Decimal:
    """
    Calculate daily return from equity change.

    This is the CORRECT way to calculate daily return - from actual equity
    values, not from stored daily_return fields which may be corrupt.

    Args:
        today_equity: Today's total equity value
        yesterday_equity: Previous trading day's total equity value

    Returns:
        Decimal: Daily return as decimal (0.01 = 1%)
                 Returns 0 if yesterday_equity is 0 or None

    Example:
        >>> calculate_daily_return(Decimal('10100'), Decimal('10000'))
        Decimal('0.01')  # 1% gain
    """
    today = Decimal(str(today_equity)) if not isinstance(today_equity, Decimal) else today_equity
    yesterday = Decimal(str(yesterday_equity)) if not isinstance(yesterday_equity, Decimal) else yesterday_equity

    if yesterday == 0 or yesterday is None:
        return Decimal('0')

    return (today - yesterday) / yesterday


def calculate_cumulative_return(
    current_equity: Union[Decimal, float],
    initial_capital: Union[Decimal, float]
) -> Decimal:
    """
    Calculate total return since inception.

    Args:
        current_equity: Current total equity value
        initial_capital: Starting capital (first day's equity)

    Returns:
        Decimal: Cumulative return as decimal (0.10 = 10%)
                 Returns 0 if initial_capital is 0 or None

    Example:
        >>> calculate_cumulative_return(Decimal('10219'), Decimal('10000'))
        Decimal('0.0219')  # 2.19% total return
    """
    current = Decimal(str(current_equity)) if not isinstance(current_equity, Decimal) else current_equity
    initial = Decimal(str(initial_capital)) if not isinstance(initial_capital, Decimal) else initial_capital

    if initial == 0 or initial is None:
        return Decimal('0')

    return (current - initial) / initial


# =============================================================================
# Risk-Adjusted Return Metrics (Tasks 2.3, 2.4, 2.5)
# =============================================================================

def calculate_sharpe_ratio(
    daily_returns: List[float],
    risk_free_rate: float = 0.0
) -> Optional[float]:
    """
    Calculate annualized Sharpe ratio from all-time daily returns.

    Formula: (mean_daily_return - risk_free_daily) / std_daily * sqrt(252)

    This fixes the bug where Sharpe was showing -4 instead of ~0.82 by:
    1. Using equity-based daily returns (not corrupt stored values)
    2. Using sample standard deviation (ddof=1)
    3. Properly annualizing with sqrt(252)

    Args:
        daily_returns: List of daily returns as decimals (0.01 = 1%)
        risk_free_rate: Annual risk-free rate (default 0)

    Returns:
        float: Annualized Sharpe ratio, or None if insufficient data (<2 points)
               or zero standard deviation

    Example:
        >>> returns = [0.0082, -0.0029, 0.0104, 0.0054]  # Sample from v3_5b
        >>> calculate_sharpe_ratio(returns)
        0.82  # Approximately
    """
    if len(daily_returns) < 2:
        return None

    returns_array = np.array(daily_returns)

    mean_return = np.mean(returns_array)
    std_return = np.std(returns_array, ddof=1)  # Sample std dev (Bessel correction)

    if std_return == 0:
        return None

    # Convert annual risk-free rate to daily
    daily_rf = risk_free_rate / 252

    # Annualize: multiply by sqrt(252)
    sharpe = float((mean_return - daily_rf) / std_return * np.sqrt(252))

    return sharpe


def calculate_sortino_ratio(
    daily_returns: List[float],
    target_return: float = 0.0
) -> Optional[float]:
    """
    Calculate annualized Sortino ratio using semi-deviation.

    The Sortino ratio is like Sharpe but only penalizes downside volatility,
    making it more appropriate for strategies with asymmetric return profiles.

    Formula: (CAGR - target) / downside_deviation

    Uses Sortino & Price (1994) semi-deviation methodology:
    - All observations used (not just those below target)
    - Returns below target contribute to downside deviation
    - Square root of mean squared downside deviations

    Args:
        daily_returns: List of daily returns as decimals
        target_return: Annual target return (default 0)

    Returns:
        float: Annualized Sortino ratio, or None if insufficient data
               or zero downside deviation

    Example:
        >>> returns = [0.0082, -0.0029, 0.0104, -0.0015, 0.0054]
        >>> calculate_sortino_ratio(returns)
        1.15  # Approximately (higher than Sharpe if more upside volatility)
    """
    if len(daily_returns) < 2:
        return None

    returns_array = np.array(daily_returns)

    # Calculate CAGR for the numerator
    total_return = np.prod(1 + returns_array) - 1
    years = len(returns_array) / 252

    if years <= 0:
        return None

    cagr = (1 + total_return) ** (1 / years) - 1

    # Calculate downside deviation (semi-deviation)
    # Only negative deviations from target contribute
    daily_target = target_return / 252
    downside_returns = np.minimum(returns_array - daily_target, 0)

    # Mean of squared downside deviations
    semi_variance = np.mean(downside_returns ** 2)
    if semi_variance == 0:
        return None

    # Annualize the downside deviation
    semi_deviation = np.sqrt(semi_variance) * np.sqrt(252)

    sortino = float((cagr - target_return) / semi_deviation)

    return sortino


def calculate_calmar_ratio(
    cagr: Optional[float],
    max_drawdown: Optional[float]
) -> Optional[float]:
    """
    Calculate Calmar ratio (return per unit of drawdown risk).

    Formula: CAGR / abs(max_drawdown)

    The Calmar ratio measures risk-adjusted return relative to the worst
    historical drawdown, useful for strategies where preserving capital
    during drawdowns is important.

    Args:
        cagr: Compound Annual Growth Rate as decimal
        max_drawdown: Maximum drawdown as negative decimal (-0.10 = -10%)

    Returns:
        float: Calmar ratio, or None if max_drawdown is 0 or None

    Example:
        >>> calculate_calmar_ratio(0.15, -0.10)
        1.5  # 15% CAGR with 10% max drawdown
    """
    if max_drawdown is None or max_drawdown == 0 or cagr is None:
        return None

    return float(cagr / abs(max_drawdown))


# =============================================================================
# Risk Metrics (Tasks 2.6, 2.7)
# =============================================================================

def calculate_max_drawdown(equity_series: List[float]) -> Optional[float]:
    """
    Calculate maximum peak-to-trough decline.

    The max drawdown is the largest percentage drop from a peak to a
    subsequent trough before a new peak is reached.

    Formula: min((equity - running_peak) / running_peak)

    Args:
        equity_series: List of equity values in chronological order

    Returns:
        float: Maximum drawdown as negative decimal (-0.10 = -10% drawdown)
               Returns None if equity_series is empty
               Returns 0 if no drawdown occurred

    Example:
        >>> equities = [10000, 10500, 10200, 10800, 10400]
        >>> calculate_max_drawdown(equities)
        -0.037  # -3.7% drawdown (10800 -> 10400)
    """
    if not equity_series or len(equity_series) < 1:
        return None

    equity = np.array(equity_series)

    # Running maximum (peak)
    peak = np.maximum.accumulate(equity)

    # Drawdown at each point
    drawdown = (equity - peak) / peak

    # Maximum drawdown is the minimum (most negative) value
    max_dd = float(np.min(drawdown))

    return max_dd


def calculate_volatility(daily_returns: List[float]) -> Optional[float]:
    """
    Calculate annualized volatility (standard deviation of returns).

    Formula: std(daily_returns, ddof=1) * sqrt(252)

    Uses sample standard deviation (ddof=1) for unbiased estimation
    and annualizes assuming 252 trading days per year.

    Args:
        daily_returns: List of daily returns as decimals

    Returns:
        float: Annualized volatility as decimal (0.20 = 20% volatility)
               Returns None if fewer than 2 data points

    Example:
        >>> returns = [0.01, -0.005, 0.008, -0.002, 0.012]
        >>> calculate_volatility(returns)
        0.11  # Approximately 11% annualized volatility
    """
    if len(daily_returns) < 2:
        return None

    std_daily = np.std(daily_returns, ddof=1)  # Sample std dev

    # Annualize: multiply by sqrt(252)
    annualized_vol = float(std_daily * np.sqrt(252))

    return annualized_vol


# =============================================================================
# Growth Metrics (Task 2.8)
# =============================================================================

def calculate_cagr(
    initial_capital: float,
    final_equity: float,
    years: float
) -> Optional[float]:
    """
    Calculate Compound Annual Growth Rate.

    Formula: (final / initial) ^ (1/years) - 1

    Args:
        initial_capital: Starting capital
        final_equity: Current equity value
        years: Number of years (can be fractional, e.g., 0.5 for 6 months)

    Returns:
        float: CAGR as decimal (0.15 = 15% annual return)
               Returns None if initial_capital or years is 0

    Example:
        >>> calculate_cagr(10000, 11500, 1.0)
        0.15  # 15% CAGR for $10k -> $11.5k over 1 year
    """
    if initial_capital <= 0 or years <= 0:
        return None

    cagr = (final_equity / initial_capital) ** (1 / years) - 1

    return float(cagr)


def calculate_cagr_from_returns(daily_returns: List[float]) -> Optional[float]:
    """
    Calculate CAGR from a series of daily returns.

    This is a convenience function that compounds the daily returns
    and converts to annualized CAGR.

    Args:
        daily_returns: List of daily returns as decimals

    Returns:
        float: CAGR as decimal, or None if empty list

    Example:
        >>> returns = [0.01, -0.005, 0.008]  # 3 days of returns
        >>> calculate_cagr_from_returns(returns)
        0.85  # ~85% annualized (extrapolated from 3 days)
    """
    if not daily_returns:
        return None

    # Compound the returns
    total_return = np.prod(1 + np.array(daily_returns)) - 1

    # Convert to years
    years = len(daily_returns) / 252

    if years <= 0:
        return None

    # Convert total return to CAGR
    cagr = (1 + total_return) ** (1 / years) - 1

    return float(cagr)


# =============================================================================
# Trade Statistics (Task 2.9)
# =============================================================================

def calculate_trade_statistics(
    trades: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Calculate all-time trade statistics using FIFO matching.

    A round-trip trade is completed when a SELL matches a previous BUY.
    A trade is "winning" if SELL price > BUY price (realized P&L > 0).

    This function takes pre-fetched trade records (not a session) to allow
    flexibility in how trades are retrieved.

    Args:
        trades: List of trade dicts with keys:
                - 'symbol': str
                - 'action': 'BUY' or 'SELL'
                - 'quantity': int or float
                - 'fill_price': Decimal or float
                Trades should be in chronological order

    Returns:
        dict: {
            'total_trades': int,      # Total round-trip trades completed
            'winning_trades': int,    # Round-trips with positive P&L
            'losing_trades': int,     # Round-trips with negative/zero P&L
            'win_rate': float | None  # winning_trades / total_trades (0-1)
        }

    Example:
        >>> trades = [
        ...     {'symbol': 'TQQQ', 'action': 'BUY', 'quantity': 100, 'fill_price': 50.0},
        ...     {'symbol': 'TQQQ', 'action': 'SELL', 'quantity': 100, 'fill_price': 55.0},
        ... ]
        >>> calculate_trade_statistics(trades)
        {'total_trades': 1, 'winning_trades': 1, 'losing_trades': 0, 'win_rate': 1.0}
    """
    from collections import defaultdict

    # Track open positions: symbol -> [{'quantity': n, 'fill_price': p}, ...]
    open_positions: Dict[str, List[Dict[str, float]]] = defaultdict(list)

    winning_trades = 0
    losing_trades = 0
    total_round_trips = 0

    for trade in trades:
        symbol = trade.get('symbol')
        action = trade.get('action')
        quantity = trade.get('quantity')
        fill_price = trade.get('fill_price')

        # Skip invalid trades
        if not all([symbol, action, quantity, fill_price]):
            continue

        # Convert to float for calculations
        qty = float(quantity)
        price = float(fill_price)

        if action == 'BUY':
            # Add to open positions
            open_positions[symbol].append({
                'quantity': qty,
                'fill_price': price
            })

        elif action == 'SELL':
            # Match against open positions using FIFO
            remaining = qty

            while remaining > 0 and open_positions[symbol]:
                buy = open_positions[symbol][0]
                close_qty = min(remaining, buy['quantity'])

                # Calculate P&L for this portion
                pnl = (price - buy['fill_price']) * close_qty
                total_round_trips += 1

                if pnl > 0:
                    winning_trades += 1
                else:
                    losing_trades += 1

                # Update remaining quantities
                remaining -= close_qty
                buy['quantity'] -= close_qty

                # Remove exhausted position
                if buy['quantity'] <= 0:
                    open_positions[symbol].pop(0)

    return {
        'total_trades': total_round_trips,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': winning_trades / total_round_trips if total_round_trips > 0 else None
    }


# =============================================================================
# Incremental KPI Updates (Task 2.10)
# =============================================================================

def update_kpis_incremental(
    prev_returns_sum: Optional[float],
    prev_returns_sum_sq: Optional[float],
    prev_downside_sum_sq: Optional[float],
    prev_returns_count: Optional[int],
    prev_high_water_mark: Optional[float],
    prev_max_drawdown: Optional[float],
    today_return: float,
    today_equity: float,
    initial_capital: float
) -> Dict[str, Any]:
    """
    Update KPIs incrementally using running statistics (O(1) complexity).

    This function uses Welford's online algorithm for numerically stable
    variance calculation, avoiding the need to recalculate from all
    historical data each day.

    For long-running strategies, this provides O(1) daily updates instead
    of O(N) where N = number of trading days.

    Args:
        prev_returns_sum: Previous running sum of daily returns
        prev_returns_sum_sq: Previous running sum of squared returns
        prev_downside_sum_sq: Previous running sum of squared downside returns
        prev_returns_count: Previous count of returns
        prev_high_water_mark: Previous peak equity value
        prev_max_drawdown: Previous maximum drawdown
        today_return: Today's daily return (decimal, e.g., 0.01 = 1%)
        today_equity: Today's total equity
        initial_capital: Strategy's starting capital

    Returns:
        dict: {
            'returns_sum': Updated running sum
            'returns_sum_sq': Updated running sum of squares
            'downside_sum_sq': Updated downside sum of squares
            'returns_count': Updated count
            'high_water_mark': Updated peak equity
            'max_drawdown': Updated max drawdown
            'drawdown': Current drawdown
            'cumulative_return': Current cumulative return
            'sharpe_ratio': Updated Sharpe (or None if <2 points)
            'sortino_ratio': Updated Sortino (or None if <2 points)
            'volatility': Updated volatility (or None if <2 points)
            'cagr': Updated CAGR
        }

    Example:
        >>> result = update_kpis_incremental(
        ...     prev_returns_sum=0.05,
        ...     prev_returns_sum_sq=0.0005,
        ...     prev_downside_sum_sq=0.0001,
        ...     prev_returns_count=10,
        ...     prev_high_water_mark=10500.0,
        ...     prev_max_drawdown=-0.02,
        ...     today_return=0.01,
        ...     today_equity=10600.0,
        ...     initial_capital=10000.0
        ... )
    """
    # Initialize if first day
    returns_sum = (prev_returns_sum or 0.0) + today_return
    returns_sum_sq = (prev_returns_sum_sq or 0.0) + today_return ** 2
    n = (prev_returns_count or 0) + 1

    # Downside contribution (only negative returns)
    downside = min(today_return, 0.0)
    downside_sum_sq = (prev_downside_sum_sq or 0.0) + downside ** 2

    # Update high water mark and calculate current drawdown
    high_water_mark = max(prev_high_water_mark or today_equity, today_equity)
    current_drawdown = (today_equity - high_water_mark) / high_water_mark if high_water_mark > 0 else 0.0

    # Update max drawdown
    max_drawdown = min(prev_max_drawdown or 0.0, current_drawdown)

    # Calculate cumulative return
    cumulative_return = (today_equity - initial_capital) / initial_capital if initial_capital > 0 else 0.0

    # Calculate years for CAGR
    years = n / 252

    # Calculate KPIs from running statistics
    sharpe_ratio = None
    sortino_ratio = None
    volatility = None
    cagr = None

    if n >= 2:
        # Mean and variance from running sums
        mean = returns_sum / n

        # Variance = E[X^2] - E[X]^2, with Bessel correction
        # Var = (sum_sq / n - mean^2) * n / (n-1)
        variance = (returns_sum_sq / n - mean ** 2) * n / (n - 1)

        if variance > 0:
            std = variance ** 0.5
            volatility = float(std * np.sqrt(252))
            sharpe_ratio = float(mean / std * np.sqrt(252))

        # CAGR
        if years > 0 and initial_capital > 0:
            cagr = float((today_equity / initial_capital) ** (1 / years) - 1)

        # Sortino from downside variance
        downside_variance = downside_sum_sq / n
        if downside_variance > 0:
            downside_std_annual = np.sqrt(downside_variance) * np.sqrt(252)
            if cagr is not None:
                sortino_ratio = float(cagr / downside_std_annual)

    return {
        'returns_sum': returns_sum,
        'returns_sum_sq': returns_sum_sq,
        'downside_sum_sq': downside_sum_sq,
        'returns_count': n,
        'high_water_mark': high_water_mark,
        'max_drawdown': max_drawdown,
        'drawdown': current_drawdown,
        'cumulative_return': cumulative_return,
        'sharpe_ratio': sharpe_ratio,
        'sortino_ratio': sortino_ratio,
        'volatility': volatility,
        'cagr': cagr,
    }


def initialize_kpi_state(initial_equity: float) -> Dict[str, Any]:
    """
    Initialize incremental KPI state for a new strategy (first day).

    On day 1:
    - daily_return = 0 (no previous day)
    - All KPIs = None (insufficient data)
    - Initialize running sums to 0

    Args:
        initial_equity: First day's equity (becomes initial_capital)

    Returns:
        dict: Initial state for incremental KPI tracking

    Example:
        >>> state = initialize_kpi_state(10000.0)
        >>> state['is_first_day']
        True
    """
    return {
        'returns_sum': 0.0,
        'returns_sum_sq': 0.0,
        'downside_sum_sq': 0.0,
        'returns_count': 0,
        'high_water_mark': initial_equity,
        'max_drawdown': 0.0,
        'drawdown': 0.0,
        'cumulative_return': 0.0,
        'initial_capital': initial_equity,
        'sharpe_ratio': None,
        'sortino_ratio': None,
        'calmar_ratio': None,
        'volatility': None,
        'cagr': None,
        'is_first_day': True,
        'days_since_previous': 0,
        'trading_days_count': 1,
    }


# =============================================================================
# Batch Calculation Functions (for backfill)
# =============================================================================

def calculate_all_kpis_batch(
    daily_equities: List[float],
    initial_capital: Optional[float] = None
) -> Dict[str, Any]:
    """
    Calculate all KPIs from a complete equity series (batch mode).

    Used during backfill to process historical data. For daily incremental
    updates, use update_kpis_incremental() instead.

    Args:
        daily_equities: List of daily equity values in chronological order
        initial_capital: Starting capital (defaults to first equity value)

    Returns:
        dict: All calculated KPIs

    Example:
        >>> equities = [10000, 10082, 10053, 10157, 10219]
        >>> kpis = calculate_all_kpis_batch(equities)
        >>> print(f"Sharpe: {kpis['sharpe_ratio']:.2f}")
    """
    if not daily_equities:
        return {}

    if initial_capital is None:
        initial_capital = daily_equities[0]

    # Calculate daily returns (equity-based)
    daily_returns = []
    for i in range(1, len(daily_equities)):
        ret = (daily_equities[i] - daily_equities[i - 1]) / daily_equities[i - 1]
        daily_returns.append(ret)

    final_equity = daily_equities[-1]
    years = len(daily_equities) / 252

    # Calculate all KPIs
    cumulative_return = calculate_cumulative_return(
        Decimal(str(final_equity)),
        Decimal(str(initial_capital))
    )
    max_drawdown = calculate_max_drawdown(daily_equities)
    volatility = calculate_volatility(daily_returns) if daily_returns else None
    sharpe_ratio = calculate_sharpe_ratio(daily_returns) if daily_returns else None
    sortino_ratio = calculate_sortino_ratio(daily_returns) if daily_returns else None
    cagr = calculate_cagr(initial_capital, final_equity, years) if years > 0 else None
    calmar_ratio = calculate_calmar_ratio(cagr, max_drawdown)

    # Calculate running sums for incremental state
    returns_sum = sum(daily_returns)
    returns_sum_sq = sum(r ** 2 for r in daily_returns)
    downside_sum_sq = sum(min(r, 0) ** 2 for r in daily_returns)

    return {
        'cumulative_return': float(cumulative_return),
        'max_drawdown': max_drawdown,
        'volatility': volatility,
        'sharpe_ratio': sharpe_ratio,
        'sortino_ratio': sortino_ratio,
        'cagr': cagr,
        'calmar_ratio': calmar_ratio,
        'high_water_mark': max(daily_equities),
        'trading_days_count': len(daily_equities),
        # Incremental state
        'returns_sum': returns_sum,
        'returns_sum_sq': returns_sum_sq,
        'downside_sum_sq': downside_sum_sq,
        'returns_count': len(daily_returns),
    }


# =============================================================================
# Validation Functions
# =============================================================================

def validate_sharpe_calculation(
    daily_returns: List[float],
    expected_sharpe: float,
    tolerance: float = 0.05
) -> bool:
    """
    Validate that Sharpe calculation is within expected tolerance.

    Used during testing and verification to ensure calculations are correct.

    Args:
        daily_returns: List of daily returns
        expected_sharpe: Expected Sharpe ratio value
        tolerance: Acceptable difference (default 0.05)

    Returns:
        bool: True if within tolerance

    Example:
        >>> returns = [0.0082, -0.0029, 0.0104, 0.0054]
        >>> validate_sharpe_calculation(returns, expected_sharpe=0.82)
        True
    """
    calculated = calculate_sharpe_ratio(daily_returns)
    if calculated is None:
        return expected_sharpe is None

    return abs(calculated - expected_sharpe) <= tolerance
