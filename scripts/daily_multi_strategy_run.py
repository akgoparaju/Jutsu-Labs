"""
Daily Multi-Strategy Run Script - Phase 1 Multi-Strategy Scheduler

This script executes ALL active strategies from the StrategyRegistry,
running them sequentially with isolated state and failure handling.

Version: 1.0 (Multi-Strategy Scheduler Infrastructure)
Created: 2026-01-22

Key Features:
- Loads strategies from config/strategies_registry.yaml
- Executes strategies in defined execution order
- Primary strategy failures are critical (raise)
- Secondary strategy failures are logged but isolated
- Each strategy has its own state file and executor
- Shared market data fetch for efficiency

Workflow:
1. Load StrategyRegistry
2. Fetch market data (shared across all strategies)
3. For each active strategy in execution order:
   a. Load strategy-specific config
   b. Load strategy-specific state
   c. Run strategy with isolated executor
   d. Save strategy-specific state
4. Report execution summary

Usage:
    python scripts/daily_multi_strategy_run.py
    python scripts/daily_multi_strategy_run.py --check-freshness
    python scripts/daily_multi_strategy_run.py --strategy v3_5b  # Run single strategy
"""

import argparse
import sys
import logging
import json
import time
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import os
import traceback

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from schwab import auth
import yaml
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker

from jutsu_engine.live.market_calendar import is_trading_day
from jutsu_engine.live.data_fetcher import LiveDataFetcher
from jutsu_engine.live.strategy_runner import LiveStrategyRunner
from jutsu_engine.live.state_manager import StateManager
from jutsu_engine.live.position_rounder import PositionRounder
from jutsu_engine.live.mode import TradingMode
from jutsu_engine.live.executor_router import ExecutorRouter
from jutsu_engine.live.data_freshness import DataFreshnessChecker, DataFreshnessError
from jutsu_engine.live.strategy_registry import StrategyRegistry, StrategyConfig
from jutsu_engine.data.models import Position, SystemState, PerformanceSnapshot
from jutsu_engine.utils.config import get_database_url, get_database_type, DATABASE_TYPE_SQLITE

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/daily_multi_strategy_{datetime.now():%Y%m%d}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('LIVE.MULTI_STRATEGY')


def load_strategy_config(config_path: Path) -> Dict:
    """Load configuration from strategy-specific YAML file."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    logger.info(f"  Config loaded: {config['strategy']['name']}")
    return config


def get_baseline_config_from_db(db_session, strategy_id: str = None) -> Dict:
    """
    Get baseline configuration from database system_state table.
    
    Args:
        db_session: Database session
        strategy_id: Optional strategy ID for strategy-specific baseline
    
    Returns dict with:
        - initial_qqq_price: float (QQQ price on paper trading start date)
        - baseline_shares: float (number of QQQ shares for baseline)
        - initial_capital: float (starting capital for baseline)
        - start_date: str (date paper trading started)
    
    Returns empty dict if no baseline config found in database.
    """
    try:
        baseline_config = {}
        # For now, use shared baseline keys (can be extended per-strategy later)
        keys_to_fetch = [
            'baseline_initial_qqq_price',
            'baseline_shares', 
            'baseline_initial_capital',
            'baseline_start_date'
        ]
        
        for key in keys_to_fetch:
            result = db_session.query(SystemState).filter(
                SystemState.key == key
            ).first()
            
            if result:
                if result.value_type == 'float':
                    baseline_config[key.replace('baseline_', '')] = float(result.value)
                elif result.value_type == 'date':
                    baseline_config[key.replace('baseline_', '')] = result.value
                else:
                    baseline_config[key.replace('baseline_', '')] = result.value
        
        if baseline_config:
            logger.info(f"  Baseline config loaded: initial_qqq_price=${baseline_config.get('initial_qqq_price', 'N/A')}")
        
        return baseline_config
        
    except Exception as e:
        logger.warning(f"  Failed to load baseline config: {e}")
        return {}


def initialize_schwab_client():
    """Initialize Schwab API client with OAuth."""
    load_dotenv()
    
    project_root = Path(__file__).parent.parent
    
    # Handle Docker paths
    token_path_raw = 'token.json'
    if Path('/app').exists():
        token_path = Path('/app/data') / token_path_raw
    else:
        token_path = project_root / token_path_raw

    if not token_path.exists():
        logger.error(f"No Schwab token found at {token_path}.")
        raise FileNotFoundError(f"Schwab token not found at {token_path}.")

    # Check token expiration
    is_docker = Path('/app').exists()
    try:
        with open(token_path, 'r') as f:
            token_data = json.load(f)

        if 'creation_timestamp' in token_data:
            creation_ts = token_data['creation_timestamp']
            age_seconds = time.time() - creation_ts
            max_age_seconds = 7 * 24 * 60 * 60  # 7 days

            if age_seconds > max_age_seconds:
                age_days = age_seconds / (24 * 60 * 60)
                if is_docker:
                    raise ValueError("Schwab token has expired (>7 days old).")
                logger.warning("Token expired - browser will open for re-authentication")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not read token file: {e}")

    try:
        schwab_client = auth.easy_client(
            api_key=os.getenv('SCHWAB_API_KEY'),
            app_secret=os.getenv('SCHWAB_API_SECRET'),
            callback_url=os.getenv('SCHWAB_CALLBACK_URL', 'https://127.0.0.1:8182'),
            token_path=str(token_path)
        )
        logger.info(f"Schwab client initialized (token: {token_path})")
        return schwab_client
    except Exception as e:
        logger.error(f"Failed to initialize Schwab client: {e}")
        raise


def fetch_shared_market_data(
    schwab_client,
    data_fetcher: LiveDataFetcher,
    symbols: Dict[str, str]
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Decimal]]:
    """
    Fetch market data shared across all strategies.
    
    Returns:
        Tuple of (market_data, current_prices)
    """
    logger.info("Fetching shared market data...")
    
    # Fetch historical bars
    historical_data = {}
    for key in ['signal_symbol', 'bond_signal']:
        symbol = symbols.get(key)
        if not symbol:
            continue
        logger.info(f"  Fetching {symbol} historical bars (250 days)")
        df = data_fetcher.fetch_historical_bars(symbol, lookback=250)
        historical_data[symbol] = df
        logger.info(f"  {symbol}: {len(df)} bars retrieved")
    
    # Fetch current quotes
    current_prices = {}
    all_symbols = set(symbols.values())
    for symbol in all_symbols:
        logger.info(f"  Fetching {symbol} quote")
        response = schwab_client.get_quote(symbol)
        if response.status_code != 200:
            logger.error(f"Quote API error for {symbol}: status {response.status_code}")
            raise ValueError(f"Failed to get quote for {symbol}")
        data = response.json()
        if symbol not in data:
            logger.error(f"Symbol {symbol} not in quote response")
            raise ValueError(f"Symbol {symbol} not in response")
        quote_info = data[symbol].get('quote', {})
        last_price = Decimal(str(quote_info.get('lastPrice', 0)))
        current_prices[symbol] = last_price
        logger.info(f"  {symbol}: ${last_price:.2f}")
    
    # Validate corporate actions
    for symbol, df in historical_data.items():
        is_valid = data_fetcher.validate_corporate_actions(df)
        if not is_valid:
            logger.error(f"Corporate action detected in {symbol} - ABORTING")
            raise ValueError(f"Corporate action detected in {symbol}")
    logger.info("  No corporate actions detected ✅")
    
    # Create synthetic daily bars
    market_data = {}
    for key in ['signal_symbol', 'bond_signal']:
        symbol = symbols.get(key)
        if not symbol or symbol not in historical_data:
            continue
        hist_df = historical_data[symbol]
        current_quote = current_prices[symbol]
        synthetic_df = data_fetcher.create_synthetic_daily_bar(hist_df, current_quote)
        market_data[symbol] = synthetic_df
        logger.info(f"  {symbol}: {len(synthetic_df)} bars (historical + synthetic)")
    
    return market_data, current_prices


def run_single_strategy(
    strategy_config: StrategyConfig,
    market_data: Dict[str, pd.DataFrame],
    current_prices: Dict[str, Decimal],
    schwab_client
) -> Tuple[bool, Optional[str]]:
    """
    Execute a single strategy with isolated state and executor.
    
    Args:
        strategy_config: Strategy configuration from registry
        market_data: Pre-fetched market data
        current_prices: Current market prices
        schwab_client: Authenticated Schwab client
    
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    strategy_id = strategy_config.id
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Strategy: {strategy_config.display_name} ({strategy_id})")
    logger.info(f"{'='*60}")
    
    try:
        # Load strategy-specific config
        config_path = Path(strategy_config.config_file)
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")
        
        config = load_strategy_config(config_path)
        strategy_name = config['strategy']['name']
        params = config['strategy']['parameters']
        
        # Initialize state manager with strategy_id for isolation
        state_manager = StateManager(strategy_id=strategy_id)
        state = state_manager.load_state()
        
        # Initialize position rounder
        position_rounder = PositionRounder()
        
        # Create executor with strategy_id
        executor = ExecutorRouter.create(
            mode=TradingMode.OFFLINE_MOCK,
            config=config,
            trade_log_path=Path(f'logs/live_trades_{strategy_id}.csv'),
            strategy_id=strategy_id
        )
        logger.info(f"  Executor created: mode={executor.get_mode().value}")
        
        # Get symbols from strategy config
        symbols = {
            'signal_symbol': params['signal_symbol'],
            'bull_symbol': params['leveraged_long_symbol'],
            'bond_signal': params['treasury_trend_symbol'],
            'bull_bond': params['bull_bond_symbol'],
            'bear_bond': params['bear_bond_symbol']
        }
        
        # Get portfolio config
        portfolio_config = config.get('portfolio', {})
        initial_capital = Decimal(str(portfolio_config.get('initial_capital', 10000)))
        
        # Check for first run
        state_equity = state.get('account_equity')
        is_first_run = state_equity is None
        
        # Load current positions from database for this strategy
        db_url = get_database_url()
        db_type = get_database_type()
        if db_type == DATABASE_TYPE_SQLITE:
            engine = create_engine(db_url, connect_args={'check_same_thread': False})
        else:
            engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        db_session = Session()
        
        try:
            # Query positions for this specific strategy
            # BUG FIX (2026-01-23): Must filter by strategy_id to prevent position collision
            # between multiple strategies. Previously loaded all positions, causing v3_5d to
            # read v3_5b's position counts and corrupt data.
            db_positions = db_session.query(Position).filter(
                Position.mode == 'offline_mock',
                Position.strategy_id == strategy_id
            ).all()
            
            if db_positions:
                current_positions = {p.symbol: p.quantity for p in db_positions}
                logger.info(f"  Loaded {len(current_positions)} positions from DB")
            else:
                current_positions = state.get('current_positions', {})
                if current_positions:
                    logger.info(f"  Loaded {len(current_positions)} positions from state.json")
                else:
                    current_positions = {}
                    logger.info("  No positions found (first run)")
        finally:
            db_session.close()
            engine.dispose()
        
        if is_first_run:
            logger.info(f"  First run - Initial Capital: ${initial_capital:,.2f}")
            account_equity = initial_capital
        else:
            # Calculate current equity
            position_value = Decimal('0')
            for symbol, qty in current_positions.items():
                if symbol in current_prices:
                    position_value += current_prices[symbol] * qty
            
            account_equity = Decimal(str(state_equity)) if state_equity else initial_capital
            logger.info(f"  Portfolio Equity: ${account_equity:,.2f}")
        
        # Initialize strategy runner with proper class
        # Import the strategy class dynamically (must import class FROM module, not module itself)
        from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b
        from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5d import Hierarchical_Adaptive_v3_5d
        
        strategy_classes = {
            'Hierarchical_Adaptive_v3_5b': Hierarchical_Adaptive_v3_5b,
            'Hierarchical_Adaptive_v3_5d': Hierarchical_Adaptive_v3_5d,
        }
        
        strategy_class = strategy_classes.get(strategy_name)
        if not strategy_class:
            raise ValueError(f"Unknown strategy class: {strategy_name}")
        
        strategy_runner = LiveStrategyRunner(
            strategy_class=strategy_class,
            config_path=config_path
        )
        
        # Run strategy
        logger.info(f"  Running strategy: {strategy_name}")
        signals = strategy_runner.calculate_signals(market_data)
        logger.info(f"  Signals: Cell {signals['current_cell']}, Vol State {signals['vol_state']}")
        
        # Inject portfolio capital after warmup
        strategy_runner.strategy._cash = account_equity
        
        # Determine target allocation
        target_weights = strategy_runner.determine_target_allocation(signals, account_equity)
        logger.info(f"  Target Weights: {target_weights}")
        
        # Convert weights to shares
        target_positions = position_rounder.convert_weights_to_shares(
            target_weights, account_equity, current_prices
        )
        logger.info(f"  Target Positions: {target_positions}")
        
        # Validate and calculate cash
        position_rounder.validate_no_over_allocation(
            target_positions, current_prices, account_equity
        )
        cash_amount, cash_pct = position_rounder.calculate_cash_remainder(
            target_positions, current_prices, account_equity
        )
        logger.info(f"  Cash Remainder: ${cash_amount:,.2f} ({cash_pct:.2f}%)")
        
        # Calculate position diffs
        position_diffs = {}
        all_symbols = set(current_positions.keys()) | set(target_positions.keys())
        for symbol in all_symbols:
            current = current_positions.get(symbol, 0)
            target = target_positions.get(symbol, 0)
            diff = target - current
            if diff != 0:
                position_diffs[symbol] = diff
        
        logger.info(f"  Position diffs (before filtering): {position_diffs}")
        
        if not position_diffs:
            logger.info("  No position changes needed")
            fills = []
            filtered_diffs = {}
        else:
            # Filter by rebalance threshold
            filtered_diffs = executor.filter_by_threshold(
                position_diffs, current_prices, account_equity
            )
            
            if not filtered_diffs:
                logger.info("  No trades exceed threshold")
                fills = []
            else:
                # Build strategy context
                strategy_context = {
                    'current_cell': signals.get('current_cell'),
                    'trend_state': signals.get('trend_state'),
                    'vol_state': signals.get('vol_state'),
                    't_norm': signals.get('t_norm'),
                    'z_score': signals.get('z_score'),
                }
                
                # Execute trades
                fills, fill_prices = executor.execute_rebalance(
                    position_diffs=filtered_diffs,
                    current_prices=current_prices,
                    reason="Rebalance",
                    strategy_context=strategy_context
                )
        
        # Calculate actual positions after trades
        if fills:
            actual_positions = dict(current_positions)
            for symbol, diff in filtered_diffs.items():
                current_qty = actual_positions.get(symbol, 0)
                actual_positions[symbol] = current_qty + diff
            logger.info(f"  Actual positions after trades: {actual_positions}")
        else:
            actual_positions = current_positions
        
        if fills:
            logger.info(f"  {len(fills)} hypothetical orders logged:")
            for fill in fills:
                logger.info(f"    {fill['action']} {fill['quantity']} {fill['symbol']} @ ${fill['fill_price']:.2f}")
        
        # Update positions in database if trades executed
        if fills:
            executor.update_positions(
                target_positions=actual_positions,
                current_prices=current_prices,
                account_equity=account_equity
            )
            logger.info("  Positions updated in database ✅")
        
        # Calculate equity and cash for snapshot
        positions_value = sum(
            current_prices.get(sym, Decimal('0')) * qty
            for sym, qty in actual_positions.items()
        )
        
        # Get previous cash
        db_url = get_database_url()
        db_type = get_database_type()
        if db_type == DATABASE_TYPE_SQLITE:
            snap_engine = create_engine(db_url, connect_args={'check_same_thread': False})
        else:
            snap_engine = create_engine(db_url)
        SnapSession = sessionmaker(bind=snap_engine)
        snap_session = SnapSession()
        
        try:
            previous_snapshot = snap_session.query(PerformanceSnapshot).filter(
                PerformanceSnapshot.mode == 'offline_mock',
                PerformanceSnapshot.strategy_id == strategy_id
            ).order_by(desc(PerformanceSnapshot.timestamp)).first()
            
            if previous_snapshot and previous_snapshot.cash is not None:
                previous_cash = Decimal(str(previous_snapshot.cash))
            else:
                previous_cash = initial_capital - sum(
                    current_prices.get(sym, Decimal('0')) * qty
                    for sym, qty in current_positions.items()
                )
        finally:
            snap_session.close()
            snap_engine.dispose()
        
        if fills:
            cash_change = Decimal('0')
            for fill in fills:
                fill_value = Decimal(str(fill['value']))
                if fill['action'] == 'SELL':
                    cash_change += fill_value
                else:
                    cash_change -= fill_value
            actual_cash = previous_cash + cash_change
        else:
            actual_cash = previous_cash
        
        actual_equity = positions_value + actual_cash
        logger.info(f"  Actual equity: ${actual_equity:,.2f}")
        
        # Calculate baseline
        qqq_price = current_prices.get('QQQ', current_prices.get(symbols['signal_symbol']))
        initial_qqq_price = state.get('initial_qqq_price')
        
        if initial_qqq_price is None:
            initial_qqq_price = float(qqq_price)
            state['initial_qqq_price'] = initial_qqq_price
            baseline_value = initial_capital
            baseline_return = 0.0
        else:
            qqq_return = (float(qqq_price) / initial_qqq_price) - 1
            baseline_value = initial_capital * Decimal(str(1 + qqq_return))
            baseline_return = qqq_return * 100
        
        logger.info(f"  QQQ Baseline: ${baseline_value:,.2f} ({baseline_return:+.2f}%)")
        
        # Save performance snapshot
        executor.save_performance_snapshot(
            account_equity=actual_equity,
            cash_balance=actual_cash,
            positions_value=positions_value,
            initial_capital=initial_capital,
            strategy_context={
                'current_cell': signals.get('current_cell'),
                'trend_state': signals.get('trend_state'),
                'vol_state': signals.get('vol_state'),
                't_norm': signals.get('t_norm'),
                'z_score': signals.get('z_score'),
                'sma_fast': signals.get('sma_fast'),
                'sma_slow': signals.get('sma_slow'),
            },
            baseline_value=baseline_value,
            baseline_return=baseline_return
        )
        logger.info("  Performance snapshot saved ✅")
        
        # Save state
        vol_state_map = {'Low': 0, 'High': 1, None: None}
        state['vol_state'] = vol_state_map.get(signals['vol_state'], 0)
        state['trend_state'] = signals.get('trend_state')
        if fills:
            state['current_positions'] = actual_positions
        state['account_equity'] = float(actual_equity)
        state['last_allocation'] = target_weights
        
        state_manager.save_state(state)
        logger.info("  State saved ✅")
        
        # Cleanup
        executor.close()
        
        logger.info(f"Strategy {strategy_id} completed successfully ✅")
        return True, None
        
    except Exception as e:
        error_msg = f"Strategy {strategy_id} failed: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return False, error_msg


def main(check_freshness: bool = False, single_strategy: str = None):
    """
    Main multi-strategy execution workflow.
    
    Args:
        check_freshness: If True, validates local DB data freshness
        single_strategy: If set, only run this specific strategy
    """
    logger.info("=" * 80)
    logger.info("Daily Multi-Strategy Run Starting")
    logger.info("=" * 80)
    
    execution_results = []
    
    try:
        # Step 0: Data freshness check
        if check_freshness:
            logger.info("Step 0: Checking data freshness")
            try:
                required_symbols = ['QQQ', 'TLT', 'TQQQ', 'PSQ', 'TMF', 'TMV']
                checker = DataFreshnessChecker(
                    db_path=None,
                    required_symbols=required_symbols
                )
                is_fresh, details = checker.ensure_fresh_data(auto_sync=True)
                checker.close()
                
                if is_fresh:
                    logger.info("  Data freshness check PASSED ✅")
                else:
                    logger.warning("  Data freshness check WARNING - continuing with live data")
            except DataFreshnessError as e:
                logger.warning(f"  Data freshness check skipped: {e}")
        else:
            logger.info("Step 0: Data freshness check SKIPPED")
        
        # Step 1: Check if trading day
        logger.info("Step 1: Checking if trading day")
        if not is_trading_day():
            logger.info("Not a trading day (weekend/holiday) - exiting")
            return
        
        # Step 2: Load strategy registry
        logger.info("Step 2: Loading strategy registry")
        registry = StrategyRegistry()
        settings = registry.get_settings()
        
        # Get strategies to run
        if single_strategy:
            strategy = registry.get_strategy(single_strategy)
            if not strategy:
                logger.error(f"Strategy not found: {single_strategy}")
                return
            active_strategies = [strategy]
            logger.info(f"  Running single strategy: {single_strategy}")
        else:
            active_strategies = registry.get_active_strategies()
            logger.info(f"  Found {len(active_strategies)} active strategies")
        
        for s in active_strategies:
            logger.info(f"    - {s.id}: {s.display_name} (primary={s.is_primary})")
        
        # Step 3: Initialize Schwab client
        logger.info("Step 3: Initializing Schwab client")
        schwab_client = initialize_schwab_client()
        data_fetcher = LiveDataFetcher(schwab_client)
        
        # Step 4: Fetch shared market data
        logger.info("Step 4: Fetching shared market data")
        # Use symbols from primary strategy
        primary = registry.get_primary_strategy()
        primary_config = load_strategy_config(Path(primary.config_file))
        params = primary_config['strategy']['parameters']
        symbols = {
            'signal_symbol': params['signal_symbol'],
            'bull_symbol': params['leveraged_long_symbol'],
            'bond_signal': params['treasury_trend_symbol'],
            'bull_bond': params['bull_bond_symbol'],
            'bear_bond': params['bear_bond_symbol']
        }
        
        market_data, current_prices = fetch_shared_market_data(
            schwab_client, data_fetcher, symbols
        )
        
        # Step 5: Execute each strategy
        logger.info("Step 5: Executing strategies")
        for strategy_config in active_strategies:
            success, error = run_single_strategy(
                strategy_config=strategy_config,
                market_data=market_data,
                current_prices=current_prices,
                schwab_client=schwab_client
            )
            
            execution_results.append({
                'strategy_id': strategy_config.id,
                'display_name': strategy_config.display_name,
                'is_primary': strategy_config.is_primary,
                'success': success,
                'error': error
            })
            
            # Handle failures based on settings
            if not success:
                if strategy_config.is_primary:
                    logger.error(f"PRIMARY strategy {strategy_config.id} failed - ABORTING")
                    raise RuntimeError(f"Primary strategy failed: {error}")
                elif settings.isolate_failures:
                    logger.warning(f"Secondary strategy {strategy_config.id} failed (isolated)")
                else:
                    raise RuntimeError(f"Secondary strategy failed: {error}")
        
        # Step 6: Summary
        logger.info("\n" + "=" * 80)
        logger.info("Daily Multi-Strategy Run Complete - Summary")
        logger.info("=" * 80)
        
        success_count = sum(1 for r in execution_results if r['success'])
        fail_count = len(execution_results) - success_count
        
        logger.info(f"Strategies Executed: {len(execution_results)}")
        logger.info(f"Successful: {success_count}")
        logger.info(f"Failed: {fail_count}")
        
        for result in execution_results:
            status = "✅ SUCCESS" if result['success'] else f"❌ FAILED: {result['error']}"
            primary_tag = " [PRIMARY]" if result['is_primary'] else ""
            logger.info(f"  {result['strategy_id']}{primary_tag}: {status}")
        
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"Multi-strategy run failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Daily multi-strategy execution workflow',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--check-freshness',
        action='store_true',
        help='Check local DB data freshness before execution'
    )
    
    parser.add_argument(
        '--strategy',
        type=str,
        help='Run only a specific strategy by ID (e.g., v3_5b)'
    )
    
    args = parser.parse_args()
    main(check_freshness=args.check_freshness, single_strategy=args.strategy)
