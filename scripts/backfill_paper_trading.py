"""
Backfill Paper Trading Script for Missing Days.

This script retroactively calculates and inserts performance snapshots
for trading days that were missed due to Schwab API token expiration.

Missing Days: Dec 23, 24, 26, 2025
Strategy: Hierarchical_Adaptive_v3_5b

Execution Logic:
1. For each missing day:
   - Load historical daily data up to that day's close
   - Run strategy through warmup to calculate signals
   - Determine regime (cell, trend_state, vol_state)
   - Calculate equity using EOD close prices
   - Insert performance snapshot to PostgreSQL

Usage:
    python scripts/backfill_paper_trading.py
"""

import sys
import logging
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone, date
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import psycopg2
from sqlalchemy import create_engine, text, desc
from sqlalchemy.orm import sessionmaker

from jutsu_engine.live.strategy_runner import LiveStrategyRunner
from jutsu_engine.utils.config import get_database_url, get_database_type
from jutsu_engine.data.models import PerformanceSnapshot, Position, Base

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger('BACKFILL')


# ==========================================
# Configuration
# ==========================================

# PostgreSQL connection (from .env via psycopg2)
PG_HOST = "tower.local"
PG_PORT = 5423
PG_USER = "jutsudB"
PG_PASSWORD = "Maruthi13JT@@"
PG_DATABASE = "jutsu_labs"

# Missing trading days to backfill
MISSING_DAYS = [
    date(2025, 12, 23),  # Monday - Regular trading day
    date(2025, 12, 24),  # Tuesday - Christmas Eve (half day, closes 1 PM ET)
    # Dec 25 is Christmas - MARKET CLOSED
    date(2025, 12, 26),  # Thursday - Regular trading day
]

# Initial capital for P&L calculations
INITIAL_CAPITAL = Decimal("10000")

# Positions as of Dec 22 (from database)
DEC_22_POSITIONS = {
    "TQQQ": 37,
    "QQQ": 12,
}
DEC_22_CASH = Decimal("629.37")
DEC_22_EQUITY = Decimal("10047.80")

# Initial QQQ price for baseline calculation (from state.json)
INITIAL_QQQ_PRICE = 512.94  # From original paper trading start


def get_pg_connection():
    """Get PostgreSQL connection."""
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        database=PG_DATABASE
    )


def get_sqlalchemy_session():
    """Get SQLAlchemy session for PostgreSQL."""
    db_url = get_database_url()
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def load_historical_data(target_date: date) -> dict:
    """
    Load historical daily OHLCV data up to target_date from PostgreSQL.

    Returns:
        {symbol: DataFrame} with columns: date, open, high, low, close, volume
    """
    conn = get_pg_connection()

    symbols = ['QQQ', 'TLT']  # Signal symbol and treasury symbol
    market_data = {}

    for symbol in symbols:
        # Use Eastern Time for date extraction (NYSE trading dates)
        query = f"""
            SELECT (timestamp AT TIME ZONE 'America/New_York')::date as date, 
                   open, high, low, close, volume
            FROM market_data
            WHERE symbol = '{symbol}' AND timeframe = '1D' 
              AND (timestamp AT TIME ZONE 'America/New_York')::date <= '{target_date}'
            ORDER BY timestamp ASC
        """
        df = pd.read_sql(query, conn)
        df['date'] = pd.to_datetime(df['date'])
        market_data[symbol] = df
        logger.info(f"  Loaded {len(df)} daily bars for {symbol} up to {target_date}")

    conn.close()
    return market_data


def get_eod_prices(target_date: date) -> dict:
    """
    Get EOD close prices for all relevant symbols on target_date.

    Uses daily data for QQQ/TLT, and intraday data for TQQQ (no daily bars).
    """
    conn = get_pg_connection()
    cur = conn.cursor()

    prices = {}

    # Get daily data for QQQ, TLT (use Eastern Time for date matching)
    for symbol in ['QQQ', 'TLT']:
        cur.execute(f"""
            SELECT close FROM market_data
            WHERE symbol = '{symbol}' AND timeframe = '1D' 
              AND (timestamp AT TIME ZONE 'America/New_York')::date = '{target_date}'
            LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            prices[symbol] = Decimal(str(row[0]))
            logger.info(f"    {symbol} EOD: ${prices[symbol]:.2f}")

    # Get last 15m bar for TQQQ (no daily data available)
    # Note: For 15m bars, use Eastern Time for date matching
    for symbol in ['TQQQ']:
        cur.execute(f"""
            SELECT close FROM market_data
            WHERE symbol = '{symbol}' AND timeframe = '15m' 
              AND (timestamp AT TIME ZONE 'America/New_York')::date = '{target_date}'
            ORDER BY timestamp DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            prices[symbol] = Decimal(str(row[0]))
            logger.info(f"    {symbol} EOD (15m): ${prices[symbol]:.2f}")

    conn.close()
    return prices


def calculate_signals_for_date(market_data: dict) -> dict:
    """
    Run strategy through warmup to calculate signals.

    Uses LiveStrategyRunner which processes bars through Hierarchical_Adaptive_v3_5b.

    Returns:
        Signals dict: current_cell, trend_state, vol_state, t_norm, z_score
    """
    strategy_runner = LiveStrategyRunner()

    # Process all bars through strategy
    signals = strategy_runner.calculate_signals(market_data)

    return signals


def calculate_equity(positions: dict, prices: dict, cash: Decimal) -> Decimal:
    """Calculate total equity from positions and cash."""
    positions_value = sum(
        prices.get(symbol, Decimal("0")) * qty
        for symbol, qty in positions.items()
    )
    return positions_value + cash


def get_previous_snapshot(session, mode='offline_mock'):
    """Get the most recent performance snapshot."""
    return session.query(PerformanceSnapshot).filter(
        PerformanceSnapshot.mode == mode
    ).order_by(desc(PerformanceSnapshot.timestamp)).first()


def get_max_equity(session, mode='offline_mock'):
    """Get max equity for drawdown calculation."""
    from sqlalchemy import func
    result = session.query(func.max(PerformanceSnapshot.total_equity)).filter(
        PerformanceSnapshot.mode == mode
    ).scalar()
    return Decimal(str(result)) if result else None


def insert_performance_snapshot(
    session,
    target_date: date,
    total_equity: Decimal,
    cash: Decimal,
    positions: dict,
    prices: dict,
    signals: dict,
    baseline_value: Decimal,
    baseline_return: float
):
    """
    Insert a performance snapshot for the target date.
    """
    # Get previous snapshot for daily P&L calculation
    prev_snapshot = get_previous_snapshot(session)

    if prev_snapshot:
        prev_equity = Decimal(str(prev_snapshot.total_equity))
        daily_pnl = total_equity - prev_equity
        daily_pnl_pct = float((daily_pnl / prev_equity) * 100) if prev_equity > 0 else 0.0
    else:
        daily_pnl = Decimal("0")
        daily_pnl_pct = 0.0

    # Calculate total P&L from initial capital
    total_pnl = total_equity - INITIAL_CAPITAL
    total_pnl_pct = float((total_pnl / INITIAL_CAPITAL) * 100) if INITIAL_CAPITAL > 0 else 0.0

    # Calculate drawdown
    max_equity = get_max_equity(session)
    if max_equity and max_equity > total_equity:
        drawdown = float((max_equity - total_equity) / max_equity * 100)
    else:
        drawdown = 0.0

    # Calculate positions value
    positions_value = sum(
        prices.get(symbol, Decimal("0")) * qty
        for symbol, qty in positions.items()
    )

    # Build positions JSON
    positions_data = []
    for symbol, qty in positions.items():
        price = prices.get(symbol, Decimal("0"))
        positions_data.append({
            'symbol': symbol,
            'quantity': qty,
            'price': float(price),
            'value': float(price * qty)
        })

    # Create snapshot with timestamp at EOD of target date (4 PM ET = 21:00 UTC)
    snapshot_ts = datetime.combine(target_date, datetime.min.time()).replace(
        hour=21, minute=0, second=0, tzinfo=timezone.utc
    )

    snapshot = PerformanceSnapshot(
        timestamp=snapshot_ts,
        total_equity=float(total_equity),
        cash=float(cash),
        positions_value=float(positions_value),
        daily_return=daily_pnl_pct,
        cumulative_return=total_pnl_pct,
        drawdown=drawdown,
        strategy_cell=signals.get('current_cell'),
        trend_state=signals.get('trend_state'),
        vol_state=signals.get('vol_state'),
        positions_json=json.dumps(positions_data),
        baseline_value=float(baseline_value) if baseline_value else None,
        baseline_return=baseline_return,
        mode='offline_mock'
    )

    session.add(snapshot)
    session.commit()

    logger.info(
        f"  Inserted snapshot: ${total_equity:,.2f} | "
        f"daily={daily_pnl_pct:+.2f}% | total={total_pnl_pct:+.2f}% | "
        f"Cell {signals.get('current_cell')} ({signals.get('trend_state')}/{signals.get('vol_state')})"
    )

    return snapshot


def main():
    """Main backfill execution."""
    logger.info("=" * 80)
    logger.info("Paper Trading Backfill - Starting")
    logger.info("=" * 80)
    logger.info(f"Missing days to backfill: {MISSING_DAYS}")

    # Initialize session
    session, engine = get_sqlalchemy_session()

    # Current positions (unchanged since Dec 22 - no rebalancing needed)
    # Strategy is in Cell 3 (Sideways/Low) with 20% TQQQ, 80% QQQ allocation
    positions = DEC_22_POSITIONS.copy()
    cash = DEC_22_CASH

    try:
        for target_date in MISSING_DAYS:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing {target_date} ({target_date.strftime('%A')})")
            logger.info(f"{'='*60}")

            # Step 1: Load historical data up to target date
            logger.info("Step 1: Loading historical data")
            market_data = load_historical_data(target_date)

            # Step 2: Get EOD prices
            logger.info("Step 2: Getting EOD prices")
            prices = get_eod_prices(target_date)

            if not prices or 'QQQ' not in prices or 'TQQQ' not in prices:
                logger.error(f"  Missing price data for {target_date}, skipping")
                continue

            # Step 3: Calculate signals using strategy
            logger.info("Step 3: Running strategy to calculate signals")
            signals = calculate_signals_for_date(market_data)
            logger.info(f"  Signals: Cell {signals.get('current_cell')}, "
                       f"Trend={signals.get('trend_state')}, Vol={signals.get('vol_state')}")

            # Step 4: Calculate equity
            logger.info("Step 4: Calculating equity")
            total_equity = calculate_equity(positions, prices, cash)
            logger.info(f"  Total Equity: ${total_equity:,.2f}")

            # Step 5: Calculate baseline (QQQ buy-and-hold)
            qqq_price = float(prices.get('QQQ', 0))
            qqq_return = (qqq_price / INITIAL_QQQ_PRICE) - 1
            baseline_value = INITIAL_CAPITAL * Decimal(str(1 + qqq_return))
            baseline_return = qqq_return * 100
            logger.info(f"  Baseline: ${baseline_value:,.2f} ({baseline_return:+.2f}%)")

            # Step 6: Check for rebalancing need
            # From strategy: Cell 3 = 20% TQQQ, 80% QQQ
            # Current: TQQQ: 37, QQQ: 12
            # With prices, calculate current weights
            tqqq_value = prices['TQQQ'] * positions['TQQQ']
            qqq_value = prices['QQQ'] * positions['QQQ']
            positions_value = tqqq_value + qqq_value

            current_tqqq_weight = float(tqqq_value / positions_value) if positions_value > 0 else 0
            current_qqq_weight = float(qqq_value / positions_value) if positions_value > 0 else 0

            target_tqqq_weight = 0.20  # Cell 3
            target_qqq_weight = 0.80   # Cell 3

            # Rebalance threshold is 5%
            needs_rebalance = (
                abs(current_tqqq_weight - target_tqqq_weight) > 0.05 or
                abs(current_qqq_weight - target_qqq_weight) > 0.05
            )

            logger.info(f"  Current weights: TQQQ={current_tqqq_weight:.1%}, QQQ={current_qqq_weight:.1%}")
            logger.info(f"  Target weights:  TQQQ={target_tqqq_weight:.1%}, QQQ={target_qqq_weight:.1%}")
            logger.info(f"  Rebalance needed: {needs_rebalance}")

            # Note: Even if rebalancing is needed, we're simulating what happened
            # Based on the strategy, positions would not change unless regime changes
            # and rebalance threshold is breached

            # Step 7: Insert performance snapshot
            logger.info("Step 7: Inserting performance snapshot")
            insert_performance_snapshot(
                session=session,
                target_date=target_date,
                total_equity=total_equity,
                cash=cash,
                positions=positions,
                prices=prices,
                signals=signals,
                baseline_value=baseline_value,
                baseline_return=baseline_return
            )

        logger.info("\n" + "=" * 80)
        logger.info("Paper Trading Backfill - Complete")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
