"""
Dashboard Data Refresh Module

Provides functionality to refresh dashboard data (prices, P&L, indicators)
without running the full trading workflow. Used for:
1. Market close data refresh (4:00 PM EST)
2. Startup catch-up when app wasn't running at execution time
3. Manual refresh via API

Key Features:
- Syncs market data from Schwab API to local database
- Updates position market values with current prices
- Calculates and saves performance snapshots with P&L
- Recalculates strategy indicators
- Does NOT run strategy signals or execute trades

Security:
- Uses direct Python imports instead of subprocess calls
- No command injection risk (no shell execution)
- Works reliably in Docker environments

Version: 1.0.0
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd

from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import sessionmaker, Session

from jutsu_engine.data.models import (
    PerformanceSnapshot,
    Position,
    DataMetadata,
    SystemState,
    MarketData,
)
from jutsu_engine.live.mode import TradingMode
from jutsu_engine.live.market_calendar import (
    is_trading_day,
    get_previous_trading_day,
)
from jutsu_engine.utils.config import get_database_url, get_database_path, is_postgresql

logger = logging.getLogger('LIVE.DATA_REFRESH')


class DashboardDataRefresher:
    """
    Refreshes dashboard data without running the full trading workflow.
    
    This class handles:
    - Syncing market data from Schwab API to local database
    - Updating position market values with current prices
    - Calculating and saving performance snapshots
    - Checking data staleness for startup catch-up
    
    It does NOT:
    - Run strategy signal generation
    - Execute any trades
    - Change position allocations
    """
    
    # Symbols that need price updates
    REFRESH_SYMBOLS = ['QQQ', 'TQQQ', 'PSQ', 'TLT', 'TMF', 'TMV']
    
    def __init__(
        self,
        db_path: Optional[str] = None,
        mode: TradingMode = TradingMode.OFFLINE_MOCK,
        strategy_id: str = 'v3_5b',
    ):
        """
        Initialize the data refresher.

        Args:
            db_path: Path to the SQLite database (auto-detected if None)
            mode: Trading mode to filter positions/snapshots
            strategy_id: Strategy identifier for multi-strategy support (default: v3_5b)
        """
        self._strategy_id = strategy_id
        # Use centralized utility for database path detection
        if db_path is None:
            db_url = get_database_url()
            db_path = get_database_path()  # None for PostgreSQL
        else:
            db_url = f'sqlite:///{db_path}'

        self._db_path = db_path
        self._db_url = db_url
        self._mode = mode
        self._is_postgresql = is_postgresql()

        # Initialize database connection
        # Note: check_same_thread is SQLite-only, don't use for PostgreSQL
        if self._is_postgresql:
            # PostgreSQL: Add TCP keepalive to prevent connection timeouts
            self._engine = create_engine(
                db_url,
                pool_pre_ping=True,  # Validate connections before use
                pool_recycle=300,  # Recycle connections every 5 minutes
                connect_args={
                    'keepalives': 1,           # Enable TCP keepalives
                    'keepalives_idle': 60,     # Start probes after 60s idle
                    'keepalives_interval': 10,  # Probe every 10s
                    'keepalives_count': 5,      # Fail after 5 failed probes
                    'connect_timeout': 10,      # Connection timeout in seconds
                },
            )
        else:
            self._engine = create_engine(
                db_url,
                connect_args={'check_same_thread': False}
            )
        self._SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self._engine
        )
        self._session: Optional[Session] = None

        # Log with appropriate identifier (URL for PostgreSQL, path for SQLite)
        db_identifier = db_path if db_path else db_url.split('@')[1] if '@' in db_url else 'postgresql'
        logger.info(f"DashboardDataRefresher initialized: db={db_identifier}, mode={mode.value}")
    
    def _get_session(self) -> Session:
        """Get or create database session."""
        if self._session is None:
            self._session = self._SessionLocal()
        return self._session
    
    def close(self):
        """Close database session."""
        if self._session is not None:
            self._session.close()
            self._session = None
    
    def check_if_stale(self, threshold_hours: float = 1.0) -> Tuple[bool, Optional[datetime]]:
        """
        Check if dashboard data is stale (needs refresh).
        
        Data is considered stale if the last performance snapshot is older than
        the threshold, or if there's no snapshot for today.
        
        Args:
            threshold_hours: Maximum age of last snapshot in hours
            
        Returns:
            Tuple of (is_stale: bool, last_snapshot_time: Optional[datetime])
        """
        session = self._get_session()
        
        try:
            # Get the most recent performance snapshot for this mode and strategy
            latest = session.query(PerformanceSnapshot).filter(
                PerformanceSnapshot.mode == self._mode.db_value,
                PerformanceSnapshot.strategy_id == self._strategy_id
            ).order_by(desc(PerformanceSnapshot.timestamp)).first()
            
            if latest is None:
                logger.info("No performance snapshots found - data is stale")
                return True, None
            
            # Check age
            now = datetime.now(timezone.utc)
            snapshot_time = latest.timestamp
            
            # Ensure snapshot_time is timezone-aware
            if snapshot_time.tzinfo is None:
                snapshot_time = snapshot_time.replace(tzinfo=timezone.utc)
            
            age_hours = (now - snapshot_time).total_seconds() / 3600
            
            is_stale = age_hours > threshold_hours
            
            logger.info(
                f"Data staleness check: last_snapshot={snapshot_time.isoformat()}, "
                f"age={age_hours:.2f}h, threshold={threshold_hours}h, stale={is_stale}"
            )
            
            return is_stale, snapshot_time
            
        except Exception as e:
            logger.error(f"Error checking data staleness: {e}")
            return True, None
    
    def sync_market_data(
        self,
        symbols: Optional[List[str]] = None,
        force_full: bool = False,
    ) -> Tuple[bool, str]:
        """
        Sync market data from Schwab API to local database.
        
        Uses direct Python imports for security (no subprocess/CLI) and
        reliability in Docker environments.
        
        Args:
            symbols: List of symbols to sync (default: REFRESH_SYMBOLS)
            force_full: Whether to do a full refresh (default: incremental)
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            from jutsu_engine.application.data_sync import DataSync
            from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher
            
            # Initialize fetcher and sync service
            logger.info("Initializing data sync service...")
            fetcher = SchwabDataFetcher()
            session = self._get_session()
            sync_service = DataSync(session)
            
            sync_symbols = symbols or self.REFRESH_SYMBOLS
            logger.info(f"Running market data sync for symbols: {sync_symbols}")
            
            success_count = 0
            fail_count = 0
            
            for symbol in sync_symbols:
                try:
                    # Use a reasonable start_date (30 days back for incremental updates)
                    # The sync_symbol method handles incremental updates intelligently
                    start_date = datetime.now(timezone.utc) - timedelta(days=30)
                    
                    result = sync_service.sync_symbol(
                        fetcher=fetcher,
                        symbol=symbol,
                        timeframe='1D',
                        start_date=start_date,
                        force_refresh=force_full,
                    )
                    
                    logger.info(
                        f"Synced {symbol}: {result['bars_stored']} stored, "
                        f"{result['bars_updated']} updated"
                    )
                    success_count += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to sync {symbol}: {e}")
                    fail_count += 1
            
            if fail_count == 0:
                return True, f"Market data synced successfully ({success_count} symbols)"
            elif success_count > 0:
                return True, f"Partial sync: {success_count} succeeded, {fail_count} failed"
            else:
                return False, f"Sync failed for all {fail_count} symbols"
                
        except ImportError as e:
            logger.error(f"Failed to import sync dependencies: {e}")
            return False, f"Sync dependencies not available: {e}"
        except Exception as e:
            logger.error(f"Market data sync error: {e}")
            return False, str(e)
    
    def _fallback_sync(self, symbols: Optional[List[str]] = None) -> Tuple[bool, str]:
        """
        Deprecated fallback sync method.
        
        Note: This method is kept for backward compatibility but is no longer
        used since sync_market_data now uses direct Python imports.
        
        Uses the DataSync application service directly.
        """
        try:
            from jutsu_engine.application.data_sync import DataSync
            from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher
            
            fetcher = SchwabDataFetcher()
            session = self._get_session()
            sync_service = DataSync(session)
            
            sync_symbols = symbols or self.REFRESH_SYMBOLS
            
            for symbol in sync_symbols:
                try:
                    start_date = datetime.now(timezone.utc) - timedelta(days=30)
                    sync_service.sync_symbol(
                        fetcher=fetcher,
                        symbol=symbol,
                        timeframe='1D',
                        start_date=start_date,
                    )
                    logger.info(f"Synced {symbol}")
                except Exception as e:
                    logger.warning(f"Failed to sync {symbol}: {e}")
            
            return True, "Fallback sync completed"
            
        except ImportError:
            return False, "DataSync not available"
        except Exception as e:
            return False, str(e)
    
    def fetch_current_prices(self) -> Dict[str, Decimal]:
        """
        Fetch current prices for all position symbols from Schwab API.
        
        Returns:
            Dictionary mapping symbol to current price
        """
        prices: Dict[str, Decimal] = {}
        
        try:
            # Get symbols from current positions
            session = self._get_session()
            positions = session.query(Position).filter(
                Position.mode == self._mode.db_value,
            ).all()
            
            position_symbols = [p.symbol for p in positions if p.quantity > 0]
            
            # Also include standard symbols for indicators
            all_symbols = list(set(position_symbols + self.REFRESH_SYMBOLS))
            
            if not all_symbols:
                logger.info("No symbols to fetch prices for")
                return prices
            
            # Try Schwab API first
            try:
                from schwab import auth
                from dotenv import load_dotenv
                import os
                
                load_dotenv()
                
                project_root = Path(__file__).parent.parent.parent
                token_path_raw = 'token.json'
                
                # Handle Docker paths - match logic in schwab_auth.py and schwab.py
                # In Docker, /app exists and token files are stored in /app/data/
                if Path('/app').exists():
                    token_path = Path('/app/data') / token_path_raw
                else:
                    token_path = project_root / token_path_raw
                
                # CRITICAL: Check if token exists AND is valid BEFORE calling easy_client
                # In Docker/headless environments, easy_client blocks forever waiting for
                # interactive OAuth flow if token is missing OR expired
                # See: https://schwab-py.readthedocs.io/en/latest/auth.html
                is_docker = Path('/app').exists()

                if not token_path.exists():
                    logger.warning(
                        f"No Schwab token found at {token_path}. "
                        "Please authenticate via dashboard /config page first. "
                        "Falling back to database prices."
                    )
                    raise FileNotFoundError(f"Token not found: {token_path}")

                # Check if token is expired (>7 days old)
                # schwab-py tokens have creation_timestamp in the JSON
                try:
                    with open(token_path, 'r') as f:
                        token_data = json.load(f)

                    if 'creation_timestamp' in token_data:
                        creation_ts = token_data['creation_timestamp']
                        age_seconds = time.time() - creation_ts
                        max_age_seconds = 7 * 24 * 60 * 60  # 7 days

                        if age_seconds > max_age_seconds:
                            age_days = age_seconds / (24 * 60 * 60)
                            logger.error(
                                f"Schwab token at {token_path} has expired ({age_days:.1f} days old). "
                                "In Docker, re-authenticate via dashboard /config page. "
                                "Tokens expire after 7 days and require manual re-authentication."
                            )
                            if is_docker:
                                raise ValueError(
                                    "Schwab token has expired (>7 days old). "
                                    "Please re-authenticate via dashboard /config page."
                                )
                            # On local dev, let easy_client handle refresh via browser
                            logger.warning("Token expired - browser will open for re-authentication")
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Could not read token file for expiration check: {e}")
                
                # IMPORTANT: schwab-py only allows 127.0.0.1, NOT localhost
                # See: https://schwab-py.readthedocs.io/en/latest/auth.html#callback-url-advisory
                schwab_client = auth.easy_client(
                    api_key=os.getenv('SCHWAB_API_KEY'),
                    app_secret=os.getenv('SCHWAB_API_SECRET'),
                    callback_url=os.getenv('SCHWAB_CALLBACK_URL', 'https://127.0.0.1:8182'),
                    token_path=str(token_path)
                )
                
                for symbol in all_symbols:
                    try:
                        response = schwab_client.get_quote(symbol)
                        if response.status_code == 200:
                            data = response.json()
                            if symbol in data:
                                quote = data[symbol].get('quote', {})
                                last_price = quote.get('lastPrice')
                                if last_price:
                                    prices[symbol] = Decimal(str(last_price))
                                    logger.debug(f"Fetched {symbol}: ${last_price}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch quote for {symbol}: {e}")
                
                logger.info(f"Fetched {len(prices)} prices from Schwab API")
                
            except Exception as e:
                logger.warning(f"Schwab API unavailable: {e}, using database prices")
                prices = self._get_database_prices(all_symbols)
            
            return prices
            
        except Exception as e:
            logger.error(f"Error fetching prices: {e}")
            return prices
    
    def _get_database_prices(self, symbols: List[str]) -> Dict[str, Decimal]:
        """
        Get prices from database (most recent bar close).
        
        Args:
            symbols: List of symbols to get prices for
            
        Returns:
            Dictionary mapping symbol to price
        """
        prices: Dict[str, Decimal] = {}
        session = self._get_session()
        
        try:
            from jutsu_engine.data.models import MarketData
            
            for symbol in symbols:
                latest = session.query(MarketData).filter(
                    MarketData.symbol == symbol
                ).order_by(desc(MarketData.timestamp)).first()
                
                if latest:
                    prices[symbol] = Decimal(str(latest.close))
                    logger.debug(f"Database price for {symbol}: ${latest.close}")
                    
        except Exception as e:
            logger.warning(f"Error getting database prices: {e}")
        
        return prices
    
    def update_position_values(
        self,
        prices: Dict[str, Decimal],
    ) -> List[Dict[str, Any]]:
        """
        Update position market values with current prices.
        
        Args:
            prices: Dictionary mapping symbol to current price
            
        Returns:
            List of updated position info dictionaries
        """
        session = self._get_session()
        updated_positions = []
        
        try:
            positions = session.query(Position).filter(
                Position.mode == self._mode.db_value,
                Position.strategy_id == self._strategy_id,
            ).all()
            
            for pos in positions:
                if pos.symbol in prices:
                    new_price = prices[pos.symbol]
                    new_value = new_price * pos.quantity
                    
                    # Update market value only - do NOT update avg_cost
                    # avg_cost is the original purchase price, needed for P/L calculation
                    pos.market_value = float(new_value)
                    pos.updated_at = datetime.now(timezone.utc)
                    
                    updated_positions.append({
                        'symbol': pos.symbol,
                        'quantity': pos.quantity,
                        'price': float(new_price),
                        'value': float(new_value),
                    })
                    
                    logger.debug(
                        f"Updated {pos.symbol}: qty={pos.quantity}, "
                        f"price=${new_price:.2f}, value=${new_value:.2f}"
                    )
            
            session.commit()
            logger.info(f"Updated {len(updated_positions)} position values")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating position values: {e}")
            raise
        
        return updated_positions
    
    def _get_historical_data(self, symbol: str, lookback: int = 250) -> Optional[pd.DataFrame]:
        """
        Get historical market data for a symbol from the database.

        Args:
            symbol: Stock ticker symbol (e.g., 'QQQ', 'TLT')
            lookback: Number of bars to retrieve

        Returns:
            DataFrame with OHLCV data, or None if no data found
        """
        session = self._get_session()

        try:
            # Query MarketData for the symbol, ordered by timestamp desc
            rows = session.query(MarketData).filter(
                MarketData.symbol == symbol,
                MarketData.timeframe == '1D',
                MarketData.is_valid == True,
            ).order_by(desc(MarketData.timestamp)).limit(lookback).all()

            if not rows:
                return None

            # Convert to DataFrame, reverse to get chronological order
            data = [{
                'timestamp': row.timestamp,
                'open': float(row.open),
                'high': float(row.high),
                'low': float(row.low),
                'close': float(row.close),
                'volume': row.volume,
            } for row in reversed(rows)]

            return pd.DataFrame(data)

        except Exception as e:
            logger.warning(f"Error fetching historical data for {symbol}: {e}")
            return None

    def calculate_indicators(
        self,
        prices: Optional[Dict[str, Decimal]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate strategy indicators from current market data.

        This calculates indicators WITHOUT running the full strategy
        signal generation. Useful for displaying current market state.

        Args:
            prices: Optional current prices (will fetch if not provided)

        Returns:
            Dictionary of indicator values
        """
        indicators: Dict[str, Any] = {}

        try:
            # Get market data from database
            qqq_df = self._get_historical_data('QQQ', lookback=250)
            tlt_df = self._get_historical_data('TLT', lookback=250)

            if qqq_df is not None and len(qqq_df) > 0:
                # Calculate basic indicators
                from jutsu_engine.indicators import sma, ema, atr

                close_prices = qqq_df['close'].values

                # Moving averages
                sma_20 = sma.calculate_sma(close_prices, 20)
                sma_50 = sma.calculate_sma(close_prices, 50)
                ema_12 = ema.calculate_ema(close_prices, 12)
                ema_26 = ema.calculate_ema(close_prices, 26)

                # MACD
                macd_line = ema_12[-1] - ema_26[-1] if len(ema_12) > 0 and len(ema_26) > 0 else None

                # ATR
                high = qqq_df['high'].values
                low = qqq_df['low'].values
                atr_14 = atr.calculate_atr(high, low, close_prices, 14)

                # Trend state (simplified)
                last_close = float(close_prices[-1])
                trend = 'Bullish' if last_close > sma_50[-1] else 'Bearish' if last_close < sma_50[-1] else 'Sideways'

                indicators.update({
                    'qqq_price': last_close,
                    'sma_20': float(sma_20[-1]) if len(sma_20) > 0 else None,
                    'sma_50': float(sma_50[-1]) if len(sma_50) > 0 else None,
                    'macd': float(macd_line) if macd_line is not None else None,
                    'atr_14': float(atr_14[-1]) if len(atr_14) > 0 else None,
                    'trend': trend,
                })

            if tlt_df is not None and len(tlt_df) > 0:
                from jutsu_engine.indicators import sma
                tlt_close = float(tlt_df['close'].iloc[-1])
                tlt_sma_50 = sma.calculate_sma(tlt_df['close'].values, 50)

                indicators.update({
                    'tlt_price': tlt_close,
                    'tlt_sma_50': float(tlt_sma_50[-1]) if len(tlt_sma_50) > 0 else None,
                    'bond_trend': 'Up' if tlt_close > tlt_sma_50[-1] else 'Down',
                })

            logger.info(f"Calculated {len(indicators)} indicators")

        except Exception as e:
            logger.warning(f"Error calculating indicators: {e}")

        return indicators
    
    def save_performance_snapshot(
        self,
        prices: Dict[str, Decimal],
        positions: Optional[List[Dict[str, Any]]] = None,
        indicators: Optional[Dict[str, Any]] = None,
        initial_capital: Decimal = Decimal('10000'),
    ) -> bool:
        """
        Save a performance snapshot with current P&L calculations.
        
        Args:
            prices: Current prices for calculating position values
            positions: Optional list of position dictionaries
            indicators: Optional indicator values for regime fields
            initial_capital: Starting capital for total P&L calculation
            
        Returns:
            True if successful, False otherwise
        """
        # Defensive check: Don't save snapshots on weekends/holidays
        if not is_trading_day():
            logger.warning("Attempted to save performance snapshot on non-trading day - skipping")
            return False
        
        session = self._get_session()
        
        try:
            # Get current positions if not provided
            if positions is None:
                db_positions = session.query(Position).filter(
                    Position.mode == self._mode.db_value,
                    Position.strategy_id == self._strategy_id,
                ).all()
                positions = [
                    {
                        'symbol': p.symbol,
                        'quantity': p.quantity,
                        'value': float(p.market_value) if p.market_value else 0.0,
                    }
                    for p in db_positions
                ]
            
            # Calculate totals
            positions_value = Decimal(sum(p['value'] for p in positions))
            
            # Get previous snapshot for cash balance (positions value is recalculated)
            previous = session.query(PerformanceSnapshot).filter(
                PerformanceSnapshot.mode == self._mode.db_value,
                PerformanceSnapshot.strategy_id == self._strategy_id
            ).order_by(desc(PerformanceSnapshot.timestamp)).first()
            
            if previous:
                # Use previous cash balance (doesn't change without trades)
                cash_balance = Decimal(str(previous.cash)) if previous.cash else Decimal('0')
                previous_equity = Decimal(str(previous.total_equity))
            else:
                # First snapshot - estimate cash from initial capital
                cash_balance = initial_capital - positions_value
                previous_equity = initial_capital
            
            # Calculate equity
            total_equity = positions_value + cash_balance
            
            # Calculate P&L
            daily_pnl = total_equity - previous_equity
            daily_pnl_pct = float((daily_pnl / previous_equity) * 100) if previous_equity > 0 else 0.0
            
            total_pnl = total_equity - initial_capital
            total_pnl_pct = float((total_pnl / initial_capital) * 100) if initial_capital > 0 else 0.0
            
            # Calculate drawdown
            max_equity_result = session.query(
                func.max(PerformanceSnapshot.total_equity)
            ).filter(
                PerformanceSnapshot.mode == self._mode.db_value,
                PerformanceSnapshot.strategy_id == self._strategy_id
            ).scalar()
            
            if max_equity_result and max_equity_result > float(total_equity):
                peak_equity = Decimal(str(max_equity_result))
                drawdown = float((peak_equity - total_equity) / peak_equity * 100)
            else:
                drawdown = 0.0
            
            # Extract strategy context from indicators or state.json
            # Indicators may have 'trend' but NOT 'vol_state' - always read from state.json
            trend_state = indicators.get('trend') if indicators else None
            vol_state = None

            # Build positions JSON
            positions_json = json.dumps(positions) if positions else None

            # Calculate QQQ baseline (buy-and-hold comparison)
            baseline_value = None
            baseline_return = None

            # ALWAYS read regime data from state.json as fallback
            # This is critical because calculate_indicators() only sets 'trend', not 'vol_state'
            # BUG FIX: Separated regime reading from baseline calculation to ensure proper error handling
            state_path = Path(__file__).parent.parent.parent / 'state' / 'state.json'
            state_template_path = state_path.parent / 'state.json.template'
            
            # FIX: Create state.json from template if missing to prevent NULL baseline values
            # This ensures snapshots created on API restart have complete data
            if not state_path.exists():
                if state_template_path.exists():
                    import shutil
                    logger.info(f"Creating state.json from template (was missing)")
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(state_template_path, state_path)
                else:
                    # Create minimal state.json if no template exists
                    logger.warning("Creating minimal state.json (no template found)")
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    minimal_state = {
                        "last_run": None,
                        "vol_state": 0,
                        "trend_state": None,  # Will be set after first strategy calculation
                        "current_positions": {},
                        "account_equity": float(initial_capital),
                        "last_allocation": {},
                        "metadata": {"created_at": None, "version": "1.0"},
                        "initial_qqq_price": None
                    }
                    with open(state_path, 'w') as f:
                        json.dump(minimal_state, f, indent=2)
            
            # Get regime data from strategy runner context (source of truth)
            # FIX: state.json can be stale, so prefer live strategy context
            # Initialize outside try block to ensure scope availability
            strategy_context = None
            try:
                from jutsu_engine.api.dependencies import get_strategy_runner
                runner = get_strategy_runner()
                strategy_context = runner.get_strategy_context() if runner else None
                if strategy_context:
                    logger.debug(f"Got strategy context: cell={strategy_context.get('current_cell')}, trend={strategy_context.get('trend_state')}, vol={strategy_context.get('vol_state')}")
            except Exception as ctx_err:
                logger.warning(f"Could not get strategy context: {ctx_err}")
            
            try:
                if state_path.exists():
                    with open(state_path, 'r') as f:
                        state = json.load(f)
                    
                    # Get vol_state: prefer context, fall back to state.json
                    if strategy_context and strategy_context.get('vol_state'):
                        vol_state = strategy_context['vol_state']
                        logger.debug(f"Vol state from strategy context: {vol_state}")
                    else:
                        # Fall back to state.json
                        vol_state_num = state.get('vol_state')
                        if vol_state_num is not None:
                            vol_state_map = {0: 'Low', 1: 'High'}
                            vol_state = vol_state_map.get(vol_state_num, 'Low')
                            logger.debug(f"Vol state from state.json (fallback): {vol_state_num} -> {vol_state}")
                        else:
                            vol_state = 'Low'
                            logger.warning("vol_state not found, defaulting to Low")
                    
                    # Get trend_state: prefer context, fall back to state.json
                    if strategy_context and strategy_context.get('trend_state'):
                        trend_state = strategy_context['trend_state']
                        logger.debug(f"Trend state from strategy context: {trend_state}")
                    else:
                        # Fall back to state.json
                        trend_state_raw = state.get('trend_state')
                        if trend_state_raw:
                            trend_state = trend_state_raw
                            logger.debug(f"Trend state from state.json (fallback): {trend_state}")
                        elif trend_state is None:
                            trend_state = 'Sideways'
                            logger.debug(f"Trend state defaulted to: {trend_state}")

                    # Calculate QQQ baseline (with initialization if needed)
                    # Priority: 1) Database system_state, 2) state.json, 3) fallback value
                    initial_qqq_price = None
                    baseline_shares = None

                    # First, try to get baseline config from database (most reliable)
                    try:
                        db_baseline_price = session.query(SystemState).filter(
                            SystemState.key == 'baseline_initial_qqq_price'
                        ).first()
                        db_baseline_shares = session.query(SystemState).filter(
                            SystemState.key == 'baseline_shares'
                        ).first()

                        if db_baseline_price and db_baseline_shares:
                            initial_qqq_price = float(db_baseline_price.value)
                            baseline_shares = float(db_baseline_shares.value)
                            logger.info(
                                f"Baseline from DATABASE: initial_qqq_price=${initial_qqq_price:.2f}, "
                                f"shares={baseline_shares:.6f}"
                            )
                    except Exception as db_err:
                        logger.warning(f"Could not query system_state for baseline: {db_err}")

                    # Fallback to state.json if not in database
                    if initial_qqq_price is None:
                        initial_qqq_price = state.get('initial_qqq_price')
                        if initial_qqq_price:
                            logger.debug(f"Baseline from state.json: initial_qqq_price=${initial_qqq_price:.2f}")

                    logger.info(
                        f"Baseline check: initial_qqq_price={initial_qqq_price}, "
                        f"'QQQ' in prices={('QQQ' in prices)}, prices_keys={list(prices.keys())}"
                    )

                    if 'QQQ' in prices:
                        current_qqq_price = float(prices['QQQ'])

                        if initial_qqq_price is None:
                            # Last resort: use known inception date value (Dec 4, 2025 QQQ close)
                            initial_qqq_price = 622.94
                            logger.warning(
                                f"Baseline not in database or state.json, using fallback: ${initial_qqq_price:.2f}"
                            )
                            state['initial_qqq_price'] = initial_qqq_price
                            with open(state_path, 'w') as f:
                                json.dump(state, f, indent=2, default=str)

                        # Calculate baseline using shares method if available, otherwise use returns method
                        if baseline_shares:
                            # Shares method: baseline_value = shares * current_price
                            baseline_value = baseline_shares * current_qqq_price
                            baseline_return = (baseline_value / float(initial_capital) - 1) * 100
                            logger.info(
                                f"Baseline (shares method): {baseline_shares:.6f} shares × ${current_qqq_price:.2f} = "
                                f"${baseline_value:.2f} ({baseline_return:+.2f}%)"
                            )
                        else:
                            # Returns method: baseline based on QQQ price change since inception
                            qqq_return = (current_qqq_price / initial_qqq_price) - 1
                            baseline_value = float(initial_capital) * (1 + qqq_return)
                            baseline_return = qqq_return * 100
                            logger.info(
                                f"Baseline (returns method): QQQ ${initial_qqq_price:.2f} -> ${current_qqq_price:.2f}, "
                                f"baseline=${baseline_value:.2f} ({baseline_return:+.2f}%)"
                            )
                    else:
                        logger.warning(
                            f"Baseline NOT calculated: 'QQQ' not in prices (keys={list(prices.keys())})"
                        )
                else:
                    logger.warning(f"state.json not found at {state_path}")
            except Exception as e:
                logger.error(f"Failed to read state.json for regime data: {e}", exc_info=True)

            # Determine strategy cell: prefer context, fall back to computing from states
            strategy_cell = None
            if strategy_context and strategy_context.get('current_cell') is not None:
                strategy_cell = strategy_context['current_cell']
                logger.debug(f"Strategy cell from context: {strategy_cell}")
            elif trend_state and vol_state:
                # Fall back to computing from trend and vol states
                cell_map = {
                    ('BullStrong', 'Low'): 1, ('BullStrong', 'High'): 2,
                    ('Sideways', 'Low'): 3, ('Sideways', 'High'): 4,
                    ('BearStrong', 'Low'): 5, ('BearStrong', 'High'): 6,
                    ('Bullish', 'Low'): 1, ('Bullish', 'High'): 2,
                    ('Bearish', 'Low'): 5, ('Bearish', 'High'): 6,
                }
                strategy_cell = cell_map.get((trend_state, vol_state))
                logger.debug(f"Strategy cell computed from states: {strategy_cell}")

            # Create snapshot (P/L refresh - no regime fields, scheduler is authoritative)
            # Architecture decision 2026-01-14: Scheduler writes regime, refresh writes P/L only
            snapshot = PerformanceSnapshot(
                timestamp=datetime.now(timezone.utc),
                total_equity=float(total_equity),
                cash=float(cash_balance),
                positions_value=float(positions_value),
                daily_return=daily_pnl_pct,
                cumulative_return=total_pnl_pct,
                drawdown=drawdown,
                # Regime fields intentionally omitted - scheduler is authoritative source
                # strategy_cell, trend_state, vol_state set by scheduler only
                positions_json=positions_json,
                baseline_value=baseline_value,
                baseline_return=baseline_return,
                mode=self._mode.db_value,
                strategy_id=self._strategy_id,  # Multi-strategy support
                snapshot_source="refresh",  # Mark as P/L refresh snapshot
            )
            
            session.add(snapshot)
            session.commit()
            
            logger.info(
                f"Saved performance snapshot: equity=${total_equity:.2f}, "
                f"daily_pnl={daily_pnl_pct:+.2f}%, total_pnl={total_pnl_pct:+.2f}%"
            )
            
            return True
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving performance snapshot: {e}")
            return False
    
    async def full_refresh(
        self,
        sync_data: bool = True,
        calculate_ind: bool = True,
        modes: Optional[List[TradingMode]] = None,
        strategy_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Perform a full dashboard data refresh.
        
        This is the main entry point for scheduled and on-demand refreshes.
        
        Args:
            sync_data: Whether to sync market data first
            calculate_ind: Whether to calculate indicators
            modes: List of modes to refresh (default: current mode)
            strategy_ids: List of strategy IDs to refresh (default: current strategy)
            
        Returns:
            Dictionary with refresh results
        """
        results = {
            'success': True,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'steps': [],
            'errors': [],
        }
        
        try:
            # Step 1: Sync market data (optional)
            if sync_data:
                logger.info("Step 1: Syncing market data...")
                sync_success, sync_msg = self.sync_market_data()
                results['steps'].append({
                    'step': 'sync_market_data',
                    'success': sync_success,
                    'message': sync_msg,
                })
                if not sync_success:
                    results['errors'].append(f"Sync failed: {sync_msg}")
            
            # Step 2: Fetch current prices
            logger.info("Step 2: Fetching current prices...")
            prices = self.fetch_current_prices()
            results['steps'].append({
                'step': 'fetch_prices',
                'success': len(prices) > 0,
                'count': len(prices),
            })
            
            if not prices:
                results['errors'].append("Failed to fetch any prices")
                results['success'] = False
                return results
            
            # Step 3: Calculate indicators (optional)
            indicators = {}
            if calculate_ind:
                logger.info("Step 3: Calculating indicators...")
                indicators = self.calculate_indicators(prices)
                results['steps'].append({
                    'step': 'calculate_indicators',
                    'success': len(indicators) > 0,
                    'count': len(indicators),
                })
            
            # Step 4: Update positions and save snapshots for each mode AND strategy
            refresh_modes = modes or [self._mode]
            refresh_strategies = strategy_ids or [self._strategy_id]
            
            for mode in refresh_modes:
                for strategy_id in refresh_strategies:
                    logger.info(f"Step 4: Refreshing mode={mode.value}, strategy={strategy_id}...")
                    
                    # Temporarily switch mode and strategy
                    original_mode = self._mode
                    original_strategy = self._strategy_id
                    self._mode = mode
                    self._strategy_id = strategy_id
                    
                    try:
                        # Update position values
                        updated_positions = self.update_position_values(prices)
                        
                        # Save performance snapshot
                        snapshot_success = self.save_performance_snapshot(
                            prices=prices,
                            positions=updated_positions,
                            indicators=indicators,
                        )
                        
                        results['steps'].append({
                            'step': f'refresh_{mode.value}_{strategy_id}',
                            'success': snapshot_success,
                            'positions_updated': len(updated_positions),
                        })
                        
                    except Exception as strategy_err:
                        # Per-strategy error isolation: log and continue to next strategy
                        # so one failing strategy doesn't block refresh of others
                        logger.error(
                            f"Refresh failed for strategy={strategy_id}, mode={mode.value}: "
                            f"{strategy_err}",
                            exc_info=True,
                        )
                        results['steps'].append({
                            'step': f'refresh_{mode.value}_{strategy_id}',
                            'success': False,
                            'error': str(strategy_err),
                        })
                        results['errors'].append(
                            f"Strategy {strategy_id} refresh failed: {strategy_err}"
                        )
                    finally:
                        self._mode = original_mode
                        self._strategy_id = original_strategy
            
            results['success'] = len(results['errors']) == 0
            
            logger.info(
                f"Full refresh completed: success={results['success']}, "
                f"steps={len(results['steps'])}, errors={len(results['errors'])}"
            )
            
        except Exception as e:
            logger.error(f"Full refresh error: {e}", exc_info=True)
            results['success'] = False
            results['errors'].append(str(e))
        
        return results


# Singleton instance for API use
_refresher_instance: Optional[DashboardDataRefresher] = None


def get_data_refresher(
    mode: TradingMode = TradingMode.OFFLINE_MOCK
) -> DashboardDataRefresher:
    """Get the singleton data refresher instance."""
    global _refresher_instance
    
    if _refresher_instance is None:
        _refresher_instance = DashboardDataRefresher(mode=mode)
    
    return _refresher_instance


async def check_and_refresh_if_stale(
    threshold_hours: float = 1.0,
    sync_data: bool = True,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if data is stale and refresh if needed.
    
    Convenience function for API startup hook.
    
    Args:
        threshold_hours: Maximum age of data before refresh
        sync_data: Whether to sync market data during refresh
        
    Returns:
        Tuple of (was_refreshed: bool, results: Optional[dict])
    """
    refresher = get_data_refresher()
    
    is_stale, last_time = refresher.check_if_stale(threshold_hours)
    
    if is_stale:
        logger.info(f"Data is stale (last={last_time}), triggering refresh...")
        results = await refresher.full_refresh(sync_data=sync_data)
        return True, results
    
    logger.info(f"Data is fresh (last={last_time}), no refresh needed")
    return False, None
