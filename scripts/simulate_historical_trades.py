"""
Historical Trade Simulation Script - Phase 3 Multi-Strategy Scheduler

This script simulates scheduler execution for a strategy from a start date to end date,
generating trades and performance snapshots as if the scheduler had been running.

Used to populate historical data for strategies that weren't running during a period,
enabling apples-to-apples comparison between strategies.

Version: 1.0
Created: 2026-01-22

Key Features:
- Iterates day-by-day through trading days
- Loads historical market data from database (not live API)
- Runs strategy to generate signals at each date
- Records trades when positions change
- Saves performance snapshots with snapshot_source='scheduler'
- Maintains position/cash state across simulation

Usage:
    # Dry run (preview without database writes)
    python scripts/simulate_historical_trades.py \\
        --strategy-id v3_5d \\
        --start-date 2025-12-04 \\
        --end-date 2026-01-22 \\
        --dry-run

    # Actual run
    python scripts/simulate_historical_trades.py \\
        --strategy-id v3_5d \\
        --start-date 2025-12-04 \\
        --end-date 2026-01-22 \\
        --initial-capital 10000
"""

import argparse
import sys
import logging
import json
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, date, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, func, desc
from sqlalchemy.orm import sessionmaker
import pytz

from jutsu_engine.live.market_calendar import is_trading_day
from jutsu_engine.live.strategy_runner import LiveStrategyRunner
from jutsu_engine.live.strategy_registry import StrategyRegistry
from jutsu_engine.live.position_rounder import PositionRounder
from jutsu_engine.data.models import MarketData, LiveTrade, PerformanceSnapshot
from jutsu_engine.utils.config import get_database_url, get_database_type, DATABASE_TYPE_SQLITE
from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b
from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5d import Hierarchical_Adaptive_v3_5d

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/historical_simulation_{datetime.now():%Y%m%d_%H%M%S}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('SIMULATION')

# Eastern timezone for scheduler simulation
EASTERN = pytz.timezone('America/New_York')

# Strategy class mapping
STRATEGY_CLASSES = {
    'Hierarchical_Adaptive_v3_5b': Hierarchical_Adaptive_v3_5b,
    'Hierarchical_Adaptive_v3_5d': Hierarchical_Adaptive_v3_5d,
}


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_trading_days(start_date: date, end_date: date) -> List[date]:
    """
    Get list of trading days between start and end (inclusive).

    Uses NYSE calendar via market_calendar module.

    Args:
        start_date: First date to consider
        end_date: Last date to consider

    Returns:
        List of trading days in chronological order
    """
    trading_days = []
    current = start_date

    while current <= end_date:
        if is_trading_day(current):
            trading_days.append(current)
        current += timedelta(days=1)

    logger.info(f"Found {len(trading_days)} trading days from {start_date} to {end_date}")
    return trading_days


def load_historical_data(
    db_session,
    sim_date: date,
    symbols: List[str],
    lookback: int = 250
) -> Dict[str, pd.DataFrame]:
    """
    Load market data as it would appear on sim_date.

    Only includes bars with timestamp <= sim_date.

    Args:
        db_session: Database session
        sim_date: Simulation date (only data up to this date is loaded)
        symbols: List of symbols to load
        lookback: Number of bars to retrieve per symbol

    Returns:
        Dict of {symbol: DataFrame} with columns: date, open, high, low, close, volume
    """
    result = {}

    for symbol in symbols:
        # Query daily bars up to sim_date
        bars = db_session.query(MarketData).filter(
            MarketData.symbol == symbol,
            MarketData.timeframe == '1D',
            func.date(MarketData.timestamp) <= sim_date
        ).order_by(
            MarketData.timestamp.desc()
        ).limit(lookback).all()

        if not bars:
            logger.warning(f"No data found for {symbol} up to {sim_date}")
            continue

        # Convert to DataFrame (reverse to chronological order)
        data = []
        for bar in reversed(bars):
            data.append({
                'date': bar.timestamp,
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': int(bar.volume),
            })

        df = pd.DataFrame(data)
        result[symbol] = df

    return result


def get_prices_at_date(
    market_data: Dict[str, pd.DataFrame],
    all_symbols: List[str]
) -> Dict[str, Decimal]:
    """
    Get close prices from the last bar of each symbol's data.

    Args:
        market_data: Market data from load_historical_data
        all_symbols: All symbols that need prices

    Returns:
        Dict of {symbol: Decimal price}
    """
    prices = {}

    for symbol in all_symbols:
        if symbol in market_data and len(market_data[symbol]) > 0:
            close_price = market_data[symbol].iloc[-1]['close']
            prices[symbol] = Decimal(str(close_price))
        else:
            logger.warning(f"No price data for {symbol}")

    return prices


def convert_weights_to_shares(
    weights: Dict[str, float],
    equity: Decimal,
    prices: Dict[str, Decimal]
) -> Dict[str, int]:
    """
    Convert weight allocations to share quantities.

    Args:
        weights: Target allocation weights (0-1)
        equity: Total portfolio equity
        prices: Current prices per symbol

    Returns:
        Dict of {symbol: quantity} (integers, rounded down)
    """
    positions = {}

    for symbol, weight in weights.items():
        if symbol == 'CASH' or weight <= 0:
            continue

        if symbol not in prices:
            logger.warning(f"No price for {symbol}, skipping")
            continue

        target_value = equity * Decimal(str(weight))
        price = prices[symbol]

        if price > 0:
            quantity = int((target_value / price).to_integral_value(rounding=ROUND_DOWN))
            if quantity > 0:
                positions[symbol] = quantity

    return positions


def calculate_equity(
    positions: Dict[str, int],
    prices: Dict[str, Decimal],
    cash: Decimal
) -> Decimal:
    """Calculate total equity from positions and cash."""
    positions_value = sum(
        prices.get(symbol, Decimal('0')) * Decimal(str(qty))
        for symbol, qty in positions.items()
    )
    return positions_value + cash


def calculate_baseline(
    initial_qqq_price: float,
    current_qqq_price: Decimal,
    initial_capital: Decimal
) -> Tuple[Decimal, float]:
    """
    Calculate QQQ buy-and-hold baseline.

    Returns:
        Tuple of (baseline_value, baseline_return_pct)
    """
    qqq_return = (float(current_qqq_price) / initial_qqq_price) - 1
    baseline_value = initial_capital * Decimal(str(1 + qqq_return))
    baseline_return = qqq_return * 100
    return baseline_value, baseline_return


# ==============================================================================
# TRADE AND SNAPSHOT RECORDING
# ==============================================================================

def record_simulated_trade(
    db_session,
    symbol: str,
    action: str,
    quantity: int,
    price: Decimal,
    sim_date: date,
    strategy_id: str,
    strategy_context: Dict[str, Any],
    dry_run: bool = False
) -> Optional[LiveTrade]:
    """
    Record a simulated trade to live_trades table.

    Args:
        db_session: Database session
        symbol: Trade symbol
        action: 'BUY' or 'SELL'
        quantity: Number of shares (positive)
        price: Execution price
        sim_date: Simulation date
        strategy_id: Strategy identifier
        strategy_context: Strategy state at trade time
        dry_run: If True, don't commit to database

    Returns:
        LiveTrade object (or None if dry_run)
    """
    # Create timestamp at 9:45 AM Eastern on sim_date
    trade_time = EASTERN.localize(datetime.combine(sim_date, time(9, 45)))

    trade = LiveTrade(
        symbol=symbol,
        timestamp=trade_time,
        action=action,
        quantity=quantity,
        target_price=price,
        fill_price=price,  # No slippage in simulation
        fill_value=price * quantity,
        slippage_pct=Decimal('0'),
        strategy_cell=strategy_context.get('current_cell'),
        trend_state=strategy_context.get('trend_state'),
        vol_state=strategy_context.get('vol_state'),
        t_norm=Decimal(str(strategy_context.get('t_norm', 0))) if strategy_context.get('t_norm') else None,
        z_score=Decimal(str(strategy_context.get('z_score', 0))) if strategy_context.get('z_score') else None,
        reason='Rebalance (Simulated)',
        mode='offline_mock',
        strategy_id=strategy_id
    )

    if dry_run:
        logger.info(f"  [DRY RUN] Would record: {action} {quantity} {symbol} @ ${price:.2f}")
        return None

    db_session.add(trade)
    logger.info(f"  Recorded: {action} {quantity} {symbol} @ ${price:.2f}")
    return trade


def save_simulated_snapshot(
    db_session,
    sim_date: date,
    strategy_id: str,
    total_equity: Decimal,
    cash: Decimal,
    positions_value: Decimal,
    positions: Dict[str, int],
    prices: Dict[str, Decimal],
    initial_capital: Decimal,
    previous_equity: Optional[Decimal],
    max_equity: Decimal,
    strategy_context: Dict[str, Any],
    baseline_value: Decimal,
    baseline_return: float,
    dry_run: bool = False
) -> Optional[PerformanceSnapshot]:
    """
    Save a simulated performance snapshot.

    Args:
        db_session: Database session
        sim_date: Simulation date
        strategy_id: Strategy identifier
        total_equity: Current total equity
        cash: Current cash balance
        positions_value: Value of all positions
        positions: Position quantities
        prices: Current prices
        initial_capital: Starting capital
        previous_equity: Previous day's equity (for daily return)
        max_equity: Maximum equity seen (for drawdown)
        strategy_context: Strategy state
        baseline_value: QQQ baseline value
        baseline_return: QQQ baseline return %
        dry_run: If True, don't commit to database

    Returns:
        PerformanceSnapshot object (or None if dry_run)
    """
    # Create timestamp at 9:45 AM Eastern
    snapshot_time = EASTERN.localize(datetime.combine(sim_date, time(9, 45)))

    # Calculate returns
    if previous_equity and previous_equity > 0:
        daily_return = float((total_equity - previous_equity) / previous_equity * 100)
    else:
        daily_return = 0.0

    cumulative_return = float((total_equity - initial_capital) / initial_capital * 100)

    if max_equity > 0:
        drawdown = float((total_equity - max_equity) / max_equity * 100)
    else:
        drawdown = 0.0

    # Build positions JSON
    positions_list = []
    for symbol, qty in positions.items():
        if qty > 0:
            value = prices.get(symbol, Decimal('0')) * qty
            positions_list.append({
                'symbol': symbol,
                'quantity': qty,
                'value': float(value)
            })
    positions_json = json.dumps(positions_list)

    snapshot = PerformanceSnapshot(
        timestamp=snapshot_time,
        total_equity=total_equity,
        cash=cash,
        positions_value=positions_value,
        daily_return=Decimal(str(round(daily_return, 6))),
        cumulative_return=Decimal(str(round(cumulative_return, 6))),
        drawdown=Decimal(str(round(drawdown, 6))),
        strategy_cell=strategy_context.get('current_cell'),
        trend_state=strategy_context.get('trend_state'),
        vol_state=strategy_context.get('vol_state'),
        snapshot_source='scheduler',  # Mark as scheduler-generated
        t_norm=Decimal(str(strategy_context.get('t_norm', 0))) if strategy_context.get('t_norm') else None,
        z_score=Decimal(str(strategy_context.get('z_score', 0))) if strategy_context.get('z_score') else None,
        sma_fast=Decimal(str(strategy_context.get('sma_fast', 0))) if strategy_context.get('sma_fast') else None,
        sma_slow=Decimal(str(strategy_context.get('sma_slow', 0))) if strategy_context.get('sma_slow') else None,
        positions_json=positions_json,
        baseline_value=baseline_value,
        baseline_return=Decimal(str(round(baseline_return, 6))),
        mode='offline_mock',
        strategy_id=strategy_id
    )

    if dry_run:
        logger.info(f"  [DRY RUN] Would save snapshot: equity=${total_equity:.2f}, return={cumulative_return:.2f}%")
        return None

    db_session.add(snapshot)
    return snapshot


# ==============================================================================
# MAIN SIMULATION
# ==============================================================================

def simulate_historical_trades(
    strategy_id: str,
    start_date: date,
    end_date: date,
    initial_capital: Decimal = Decimal('10000'),
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Simulate scheduler execution for a strategy from start_date to end_date.

    For each trading day:
    1. Load market data up to that day
    2. Run strategy to generate signals
    3. Calculate target positions
    4. Generate trades if positions changed
    5. Save performance snapshot

    Args:
        strategy_id: Strategy to simulate (e.g., 'v3_5d')
        start_date: First simulation date
        end_date: Last simulation date
        initial_capital: Starting capital
        dry_run: If True, preview without database writes

    Returns:
        Summary dict with statistics
    """
    logger.info("=" * 80)
    logger.info(f"Historical Trade Simulation for {strategy_id}")
    logger.info(f"Period: {start_date} to {end_date}")
    logger.info(f"Initial Capital: ${initial_capital:,.2f}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 80)

    # Load strategy registry
    registry = StrategyRegistry()
    strategy_config = registry.get_strategy(strategy_id)

    if not strategy_config:
        raise ValueError(f"Strategy not found in registry: {strategy_id}")

    logger.info(f"Strategy: {strategy_config.display_name}")
    logger.info(f"Config: {strategy_config.config_file}")

    # Get strategy class
    strategy_class = STRATEGY_CLASSES.get(strategy_config.strategy_class)
    if not strategy_class:
        raise ValueError(f"Unknown strategy class: {strategy_config.strategy_class}")

    # Initialize database
    db_url = get_database_url()
    db_type = get_database_type()

    if db_type == DATABASE_TYPE_SQLITE:
        engine = create_engine(db_url, connect_args={'check_same_thread': False})
    else:
        engine = create_engine(db_url)

    Session = sessionmaker(bind=engine)

    # Get trading days
    trading_days = get_trading_days(start_date, end_date)

    if not trading_days:
        logger.warning("No trading days in specified range")
        return {'trading_days': 0, 'trades': 0, 'snapshots': 0}

    # Get all symbols needed
    config_path = Path(strategy_config.config_file)
    import yaml
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    params = config['strategy']['parameters']
    all_symbols = list(set([
        params['signal_symbol'],
        params['leveraged_long_symbol'],
        params.get('core_long_symbol', params['signal_symbol']),
        params.get('inverse_hedge_symbol', 'PSQ'),
        params['treasury_trend_symbol'],
        params['bull_bond_symbol'],
        params['bear_bond_symbol'],
    ]))

    logger.info(f"Symbols to track: {all_symbols}")

    # Initialize simulation state
    current_positions: Dict[str, int] = {}
    current_cash = initial_capital
    previous_equity: Optional[Decimal] = None
    max_equity = initial_capital
    initial_qqq_price: Optional[float] = None

    # Statistics
    stats = {
        'trading_days': len(trading_days),
        'trades': 0,
        'snapshots': 0,
        'errors': 0,
    }

    # Position rounder
    position_rounder = PositionRounder()

    # Process each trading day
    db_session = Session()

    try:
        for idx, sim_date in enumerate(trading_days):
            if idx % 10 == 0:
                logger.info(f"\nProgress: {idx + 1}/{len(trading_days)} ({sim_date})")

            try:
                # Load historical data up to this date
                market_data = load_historical_data(
                    db_session, sim_date, all_symbols, lookback=250
                )

                if not market_data:
                    logger.warning(f"  No market data for {sim_date}, skipping")
                    continue

                # Initialize strategy runner fresh for each day
                # This ensures proper state reset
                strategy_runner = LiveStrategyRunner(
                    strategy_class=strategy_class,
                    config_path=config_path
                )

                # Run strategy to get signals
                signals = strategy_runner.calculate_signals(market_data)

                # Get current prices
                prices = get_prices_at_date(market_data, all_symbols)

                # Track initial QQQ price for baseline
                qqq_symbol = params['signal_symbol']
                if initial_qqq_price is None and qqq_symbol in prices:
                    initial_qqq_price = float(prices[qqq_symbol])
                    logger.info(f"  Initial {qqq_symbol} price: ${initial_qqq_price:.2f}")

                # Calculate current equity
                current_equity = calculate_equity(current_positions, prices, current_cash)

                # Inject equity into strategy for weight calculation
                strategy_runner.strategy._cash = current_equity

                # Determine target allocation
                target_weights = strategy_runner.determine_target_allocation(signals, current_equity)

                # Convert to shares
                target_positions = convert_weights_to_shares(target_weights, current_equity, prices)

                # Calculate position diffs
                position_diffs = {}
                all_position_symbols = set(current_positions.keys()) | set(target_positions.keys())

                for symbol in all_position_symbols:
                    current_qty = current_positions.get(symbol, 0)
                    target_qty = target_positions.get(symbol, 0)
                    diff = target_qty - current_qty
                    if diff != 0:
                        position_diffs[symbol] = diff

                # Get strategy context
                strategy_context = strategy_runner.get_strategy_context()

                # Record trades if any
                if position_diffs:
                    logger.info(f"  {sim_date}: Position changes: {position_diffs}")

                    for symbol, diff in position_diffs.items():
                        if symbol not in prices:
                            continue

                        action = 'BUY' if diff > 0 else 'SELL'
                        quantity = abs(diff)
                        price = prices[symbol]

                        trade = record_simulated_trade(
                            db_session=db_session,
                            symbol=symbol,
                            action=action,
                            quantity=quantity,
                            price=price,
                            sim_date=sim_date,
                            strategy_id=strategy_id,
                            strategy_context=strategy_context,
                            dry_run=dry_run
                        )

                        if trade:
                            stats['trades'] += 1
                        elif dry_run:
                            stats['trades'] += 1  # Count in dry run too

                        # Update cash
                        trade_value = price * quantity
                        if action == 'SELL':
                            current_cash += trade_value
                        else:
                            current_cash -= trade_value

                    # Update positions
                    current_positions = dict(target_positions)

                # Calculate equity after trades
                positions_value = sum(
                    prices.get(symbol, Decimal('0')) * Decimal(str(qty))
                    for symbol, qty in current_positions.items()
                )
                total_equity = positions_value + current_cash

                # Update max equity for drawdown
                if total_equity > max_equity:
                    max_equity = total_equity

                # Calculate baseline
                if initial_qqq_price and qqq_symbol in prices:
                    baseline_value, baseline_return = calculate_baseline(
                        initial_qqq_price, prices[qqq_symbol], initial_capital
                    )
                else:
                    baseline_value = initial_capital
                    baseline_return = 0.0

                # Save snapshot
                snapshot = save_simulated_snapshot(
                    db_session=db_session,
                    sim_date=sim_date,
                    strategy_id=strategy_id,
                    total_equity=total_equity,
                    cash=current_cash,
                    positions_value=positions_value,
                    positions=current_positions,
                    prices=prices,
                    initial_capital=initial_capital,
                    previous_equity=previous_equity,
                    max_equity=max_equity,
                    strategy_context=strategy_context,
                    baseline_value=baseline_value,
                    baseline_return=baseline_return,
                    dry_run=dry_run
                )

                if snapshot:
                    stats['snapshots'] += 1
                elif dry_run:
                    stats['snapshots'] += 1

                # Update for next iteration
                previous_equity = total_equity

                # Commit periodically (every 5 days)
                if not dry_run and (idx + 1) % 5 == 0:
                    db_session.commit()
                    logger.debug(f"  Committed at day {idx + 1}")

            except Exception as e:
                logger.error(f"  Error on {sim_date}: {e}")
                stats['errors'] += 1
                # Continue to next day instead of failing entire simulation
                continue

        # Final commit
        if not dry_run:
            db_session.commit()
            logger.info("Final commit completed")

    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        db_session.rollback()
        raise
    finally:
        db_session.close()
        engine.dispose()

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("Simulation Complete")
    logger.info("=" * 80)
    logger.info(f"Trading Days Processed: {stats['trading_days']}")
    logger.info(f"Trades Generated: {stats['trades']}")
    logger.info(f"Snapshots Saved: {stats['snapshots']}")
    logger.info(f"Errors: {stats['errors']}")

    if not dry_run:
        logger.info(f"\nFinal Equity: ${total_equity:,.2f}")
        logger.info(f"Total Return: {float((total_equity - initial_capital) / initial_capital * 100):.2f}%")
        logger.info(f"Baseline Return: {baseline_return:.2f}%")

    return stats


def delete_existing_data(strategy_id: str, dry_run: bool = False):
    """
    Delete existing simulation data for a strategy before re-running.

    Args:
        strategy_id: Strategy to clean up
        dry_run: If True, just show what would be deleted
    """
    logger.info(f"Deleting existing data for {strategy_id}")

    db_url = get_database_url()
    db_type = get_database_type()

    if db_type == DATABASE_TYPE_SQLITE:
        engine = create_engine(db_url, connect_args={'check_same_thread': False})
    else:
        engine = create_engine(db_url)

    Session = sessionmaker(bind=engine)
    db_session = Session()

    try:
        # Count existing records
        snapshot_count = db_session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.strategy_id == strategy_id,
            PerformanceSnapshot.mode == 'offline_mock'
        ).count()

        trade_count = db_session.query(LiveTrade).filter(
            LiveTrade.strategy_id == strategy_id,
            LiveTrade.mode == 'offline_mock'
        ).count()

        logger.info(f"  Found {snapshot_count} snapshots and {trade_count} trades")

        if dry_run:
            logger.info(f"  [DRY RUN] Would delete {snapshot_count} snapshots and {trade_count} trades")
            return

        # Delete snapshots
        db_session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.strategy_id == strategy_id,
            PerformanceSnapshot.mode == 'offline_mock'
        ).delete()

        # Delete trades
        db_session.query(LiveTrade).filter(
            LiveTrade.strategy_id == strategy_id,
            LiveTrade.mode == 'offline_mock'
        ).delete()

        db_session.commit()
        logger.info(f"  Deleted {snapshot_count} snapshots and {trade_count} trades")

    except Exception as e:
        logger.error(f"Failed to delete data: {e}")
        db_session.rollback()
        raise
    finally:
        db_session.close()
        engine.dispose()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Simulate historical trade execution for a strategy',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Dry run to preview
    python scripts/simulate_historical_trades.py \\
        --strategy-id v3_5d \\
        --start-date 2025-12-04 \\
        --end-date 2026-01-22 \\
        --dry-run

    # Full simulation with data cleanup
    python scripts/simulate_historical_trades.py \\
        --strategy-id v3_5d \\
        --start-date 2025-12-04 \\
        --end-date 2026-01-22 \\
        --delete-existing

    # Specify initial capital
    python scripts/simulate_historical_trades.py \\
        --strategy-id v3_5d \\
        --start-date 2025-12-04 \\
        --end-date 2026-01-22 \\
        --initial-capital 10000
        """
    )

    parser.add_argument(
        '--strategy-id',
        type=str,
        required=True,
        help='Strategy ID from registry (e.g., v3_5d)'
    )

    parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--end-date',
        type=str,
        required=True,
        help='End date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--initial-capital',
        type=float,
        default=10000.0,
        help='Initial capital (default: 10000)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview without database writes'
    )

    parser.add_argument(
        '--delete-existing',
        action='store_true',
        help='Delete existing data for strategy before simulation'
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    # Validate date range
    if start_date > end_date:
        logger.error("Start date must be before end date")
        sys.exit(1)

    # Delete existing data if requested
    if args.delete_existing:
        delete_existing_data(args.strategy_id, dry_run=args.dry_run)

    # Run simulation
    try:
        stats = simulate_historical_trades(
            strategy_id=args.strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=Decimal(str(args.initial_capital)),
            dry_run=args.dry_run
        )

        if stats['errors'] > 0:
            logger.warning(f"Completed with {stats['errors']} errors")
            sys.exit(1)

        logger.info("Simulation completed successfully")

    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
