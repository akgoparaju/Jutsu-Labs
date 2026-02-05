"""
Database data handler for reading market data from SQLite/PostgreSQL.

Implements DataHandler interface to provide historical market data
from the database for backtesting. Ensures chronological ordering
and prevents lookback bias.

Example:
    from jutsu_engine.data.handlers.database import DatabaseDataHandler
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine('sqlite:///data/market_data.db')
    Session = sessionmaker(bind=engine)
    session = Session()

    handler = DatabaseDataHandler(
        session=session,
        symbol='AAPL',
        timeframe='1D',
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31)
    )

    for bar in handler.get_next_bar():
        print(f"{bar.timestamp}: ${bar.close}")
"""
from datetime import datetime, timedelta
from typing import Iterator, List, Optional
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import and_

from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.data.handlers.base import DataHandler
from jutsu_engine.data.models import MarketData
from jutsu_engine.utils.logging_config import get_data_logger

logger = get_data_logger('DATABASE')


def _is_weekend(timestamp: datetime) -> bool:
    """
    Check if timestamp falls on a weekend (Saturday=5, Sunday=6).

    Market data should only exist on weekdays. Weekend dates in the database
    indicate data quality issues that should be filtered out.

    Args:
        timestamp: datetime to check

    Returns:
        True if Saturday or Sunday, False otherwise
    """
    return timestamp.weekday() in (5, 6)  # Saturday=5, Sunday=6


def _is_market_holiday(timestamp: datetime) -> bool:
    """
    Check if timestamp falls on a market holiday (NYSE closed).

    Defensive filter for read-side data quality protection.
    Always converts to Eastern Time to get the correct NYSE trading date,
    since NYSE trading dates are defined in ET.

    Args:
        timestamp: datetime to check

    Returns:
        True if NYSE is closed for holiday, False otherwise
    """
    import pytz
    import pandas_market_calendars as mcal
    from datetime import date, time, timezone

    # Always convert to Eastern Time to get correct NYSE trading date
    # Example: 2026-01-19 21:00:00 PST = 2026-01-20 00:00:00 ET → trading date Jan 20
    et = pytz.timezone('America/New_York')
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    ts_et = timestamp.astimezone(et)
    trading_date = ts_et.date()

    # Skip weekend check (handled by _is_weekend)
    if trading_date.weekday() >= 5:
        return False

    # Get NYSE calendar - cache for efficiency
    if not hasattr(_is_market_holiday, '_nyse_cache'):
        _is_market_holiday._nyse_cache = {}

    year = trading_date.year
    if year not in _is_market_holiday._nyse_cache:
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )
        _is_market_holiday._nyse_cache[year] = set(schedule.index.date)

    trading_days = _is_market_holiday._nyse_cache[year]
    return trading_date not in trading_days


class DatabaseDataHandler(DataHandler):
    """
    Reads historical market data from database for backtesting.

    Implements DataHandler interface to provide chronologically-ordered
    market data bars. Ensures no lookback bias by strictly ordering data.

    Attributes:
        session: SQLAlchemy session
        symbol: Stock ticker symbol
        timeframe: Bar timeframe ('1D', '1H', etc.)
        start_date: Start of backtest period
        end_date: End of backtest period
    """

    def __init__(
        self,
        session: Session,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        warmup_bars: int = 0,
    ):
        """
        Initialize database data handler.

        Args:
            session: SQLAlchemy session for database access
            symbol: Stock ticker symbol to retrieve
            timeframe: Bar timeframe ('1D', '1H', '5m', etc.)
            start_date: Start of TRADING period
            end_date: End of trading period (inclusive)
            warmup_bars: Number of bars to fetch BEFORE start_date for indicator warmup

        Example:
            handler = DatabaseDataHandler(
                session=session,
                symbol='AAPL',
                timeframe='1D',
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
                warmup_bars=50
            )
        """
        self.session = session
        self.symbol = symbol
        self.timeframe = timeframe
        self.warmup_bars = warmup_bars

        # Convert timezone-aware datetimes to naive UTC for database comparison
        # Database stores timestamps as naive TEXT in SQLite, so we need naive datetimes
        # for proper comparison in WHERE clauses
        if start_date.tzinfo is not None:
            start_date = start_date.replace(tzinfo=None)
        if end_date.tzinfo is not None:
            end_date = end_date.replace(tzinfo=None)

        # FIX: If end_date is midnight (date-only input), set to end of day
        # to include ALL bars for that date (e.g., intraday timestamps like 05:00:00)
        if end_date.hour == 0 and end_date.minute == 0 and end_date.second == 0:
            end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            logger.debug(f"end_date set to end of day: {end_date}")

        # Calculate actual query start date if warmup is needed
        if warmup_bars > 0:
            self.start_date = self._calculate_warmup_start_date(start_date, warmup_bars)
            logger.info(
                f"DatabaseDataHandler: Fetching {warmup_bars} warmup bars before {start_date.date()} "
                f"(query start: {self.start_date.date()})"
            )
        else:
            self.start_date = start_date

        self.end_date = end_date

        # Cache for latest bar
        self._latest_bar: Optional[MarketDataEvent] = None

        # Validate data exists
        count = self._get_bar_count()
        logger.info(
            f"DatabaseDataHandler initialized: {symbol} {timeframe} "
            f"from {start_date.date()} to {end_date.date()} ({count} bars)"
        )

        if count == 0:
            logger.warning(
                f"No data found for {symbol} {timeframe} in date range"
            )

    def _get_bar_count(self) -> int:
        """Get total number of bars in date range."""
        return (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == self.symbol,
                    MarketData.timeframe == self.timeframe,
                    MarketData.timestamp >= self.start_date,
                    MarketData.timestamp <= self.end_date,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .count()
        )

    def _calculate_warmup_start_date(self, start_date: datetime, warmup_bars: int) -> datetime:
        """
        Calculate start date to fetch warmup bars using NYSE market calendar.

        Uses pandas_market_calendars for exact trading day calculation
        with a 10% buffer to account for data gaps.

        Args:
            start_date: Requested trading start date
            warmup_bars: Number of warmup bars needed

        Returns:
            datetime: Start date to begin fetching (with buffer)

        Notes:
            - Uses NYSE calendar for accurate US market trading days
            - Accounts for weekends, holidays, and market closures
            - Adds 10% buffer to handle data gaps in database
            - Falls back to 2× buffer if calendar lookup fails

        Example:
            # For 221-bar warmup on 2025-12-04 start
            warmup_start = _calculate_warmup_start_date(
                datetime(2025, 12, 4), 221
            )
            # Returns date ~243 trading days before (221 * 1.1)
        """
        import pandas_market_calendars as mcal

        # Get NYSE calendar
        nyse = mcal.get_calendar('NYSE')

        # Convert start_date to date for calendar operations
        if isinstance(start_date, datetime):
            start_dt = start_date.date()
        else:
            start_dt = start_date

        # Single-symbol handler: 10% buffer for data gaps
        warmup_with_buffer = int(warmup_bars * 1.1)

        try:
            # Get trading schedule going back far enough
            # Use 2× warmup_with_buffer as calendar days to ensure we have enough history
            search_start = start_dt - timedelta(days=warmup_with_buffer * 2)
            schedule = nyse.schedule(start_date=search_start, end_date=start_dt - timedelta(days=1))

            # Get trading days STRICTLY BEFORE start_date
            trading_days = schedule.index.date.tolist()

            if len(trading_days) < warmup_with_buffer:
                # Need to look back further - extend search
                search_start = start_dt - timedelta(days=warmup_with_buffer * 3)
                schedule = nyse.schedule(start_date=search_start, end_date=start_dt - timedelta(days=1))
                trading_days = schedule.index.date.tolist()

            if len(trading_days) < warmup_with_buffer:
                logger.warning(
                    f"Only found {len(trading_days)} trading days, need {warmup_with_buffer}. "
                    f"Using earliest available date."
                )
                warmup_start = trading_days[0] if trading_days else search_start
            else:
                # Use buffered warmup to get extra safety margin
                warmup_start = trading_days[-warmup_with_buffer]

            logger.debug(
                f"Calculated warmup start: {warmup_start} "
                f"({warmup_with_buffer} trading days before {start_dt}, "
                f"includes {int((warmup_with_buffer/warmup_bars - 1) * 100)}% buffer over {warmup_bars} required)"
            )

            return datetime.combine(warmup_start, datetime.min.time())

        except Exception as e:
            # Fallback to 2× buffer if calendar lookup fails
            logger.warning(
                f"NYSE calendar lookup failed: {e}. "
                f"Falling back to 2× buffer estimation."
            )
            calendar_days = int(warmup_with_buffer * 2.0)
            warmup_start = start_date - timedelta(days=calendar_days)
            return warmup_start

    def _convert_to_event(self, db_bar: MarketData) -> MarketDataEvent:
        """
        Convert database MarketData model to MarketDataEvent.

        Args:
            db_bar: MarketData database record

        Returns:
            MarketDataEvent for event loop processing
        """
        return MarketDataEvent(
            symbol=db_bar.symbol,
            timestamp=db_bar.timestamp,
            open=db_bar.open,
            high=db_bar.high,
            low=db_bar.low,
            close=db_bar.close,
            volume=db_bar.volume,
            timeframe=db_bar.timeframe,
        )

    def get_next_bar(self) -> Iterator[MarketDataEvent]:
        """
        Yield bars one at a time in chronological order.

        This is the primary method for EventLoop to consume data.
        Yields bars sequentially to prevent lookback bias.

        Yields:
            MarketDataEvent objects in chronological order

        Example:
            for bar in data_handler.get_next_bar():
                strategy.on_bar(bar)
                portfolio.update_market_value({'AAPL': bar})
        """
        # Query bars in chronological order
        query = (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == self.symbol,
                    MarketData.timeframe == self.timeframe,
                    MarketData.timestamp >= self.start_date,
                    MarketData.timestamp <= self.end_date,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .order_by(MarketData.timestamp.asc())  # CRITICAL: chronological order
        )

        # Stream results to avoid loading all into memory
        # Track skips for summary logging
        weekend_skip_count = 0
        holiday_skip_count = 0

        for db_bar in query.yield_per(1000):
            # Filter out weekend dates (data quality issue)
            if _is_weekend(db_bar.timestamp):
                weekend_skip_count += 1
                continue

            # Filter out market holidays (defensive - should be filtered at sync)
            if _is_market_holiday(db_bar.timestamp):
                holiday_skip_count += 1
                continue

            event = self._convert_to_event(db_bar)
            self._latest_bar = event
            yield event

        # Log summary of skipped bars
        if weekend_skip_count > 0 or holiday_skip_count > 0:
            logger.warning(
                f"Skipped {weekend_skip_count} weekend, {holiday_skip_count} holiday "
                f"bars for {self.symbol} (data quality issue)"
            )

    def get_latest_bar(self, symbol: str) -> Optional[MarketDataEvent]:
        """
        Get the most recent bar for a symbol.

        Args:
            symbol: Stock ticker symbol (must match initialized symbol)

        Returns:
            Latest MarketDataEvent or None if no data

        Example:
            latest = data_handler.get_latest_bar('AAPL')
            if latest:
                current_price = latest.close
        """
        if symbol != self.symbol:
            logger.warning(
                f"Requested symbol {symbol} doesn't match handler symbol {self.symbol}"
            )
            return None

        return self._latest_bar

    def get_bars(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        limit: Optional[int] = None,
        warmup_bars: int = 0
    ) -> List[MarketDataEvent]:
        """
        Get bars for a date range, optionally including warmup period.

        Args:
            symbol: Stock ticker symbol
            start_date: Start of TRADING period
            end_date: End of trading period
            limit: Optional max number of bars to return
            warmup_bars: Number of bars to fetch BEFORE start_date for indicator warmup

        Returns:
            List of MarketDataEvent objects in chronological order

        Notes:
            - If warmup_bars > 0, fetches data from approximately (start_date - warmup_bars trading days)
            - Warmup bars are included in the returned data
            - Actual warmup start is calculated using _calculate_warmup_start_date()

        Example:
            # Get bars for January 2024 with 50-bar warmup
            bars = data_handler.get_bars(
                'AAPL',
                datetime(2024, 1, 1),
                datetime(2024, 1, 31),
                warmup_bars=50
            )
            # Returns bars from ~Nov 2023 through Jan 2024
        """
        if symbol != self.symbol:
            logger.warning(
                f"Requested symbol {symbol} doesn't match handler symbol {self.symbol}"
            )
            return []

        # Convert timezone-aware datetimes to naive UTC for database comparison
        # Database stores timestamps as naive TEXT in SQLite, so we need naive datetimes
        # for proper comparison in WHERE clauses
        if start_date.tzinfo is not None:
            start_date = start_date.replace(tzinfo=None)
        if end_date.tzinfo is not None:
            end_date = end_date.replace(tzinfo=None)

        # If end_date is midnight (date-only input), set to end of day
        # to include ALL bars for that date (e.g., intraday timestamps like 05:00:00)
        if end_date.hour == 0 and end_date.minute == 0 and end_date.second == 0:
            end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            logger.debug(f"get_bars: end_date set to end of day: {end_date}")

        # Calculate warmup start date if needed
        query_start = start_date
        if warmup_bars > 0:
            query_start = self._calculate_warmup_start_date(start_date, warmup_bars)
            logger.info(
                f"Fetching {warmup_bars} warmup bars before {start_date.date()} "
                f"(query start: {query_start.date()})"
            )

        query = (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == self.timeframe,
                    MarketData.timestamp >= query_start,
                    MarketData.timestamp <= end_date,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .order_by(MarketData.timestamp.asc())
        )

        if limit:
            query = query.limit(limit)

        return [self._convert_to_event(db_bar) for db_bar in query.all()]

    def get_bars_lookback(self, symbol: str, lookback: int) -> List[MarketDataEvent]:
        """
        Get last N bars for a symbol up to current position.

        IMPORTANT: Only returns bars up to the current bar being processed.
        This prevents lookback bias by not peeking into the future.

        Args:
            symbol: Stock ticker symbol
            lookback: Number of bars to retrieve

        Returns:
            List of MarketDataEvent objects (most recent first)

        Example:
            # Get last 20 bars for SMA calculation
            bars = data_handler.get_bars_lookback('AAPL', 20)
            closes = [bar.close for bar in bars]
            sma = sum(closes) / len(closes)
        """
        if symbol != self.symbol:
            logger.warning(
                f"Requested symbol {symbol} doesn't match handler symbol {self.symbol}"
            )
            return []

        if not self._latest_bar:
            return []

        # Query bars up to (and including) current bar
        # CRITICAL: timestamp <= current bar prevents future peeking
        query = (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == self.timeframe,
                    MarketData.timestamp <= self._latest_bar.timestamp,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .order_by(MarketData.timestamp.desc())
            .limit(lookback)
        )

        # Return in chronological order (oldest first)
        bars = [self._convert_to_event(db_bar) for db_bar in query.all()]
        return list(reversed(bars))

    def get_symbols(self) -> List[str]:
        """
        Get list of available symbols.

        Returns:
            List containing the initialized symbol

        Example:
            symbols = data_handler.get_symbols()
            # ['AAPL']
        """
        return [self.symbol]


class MultiSymbolDataHandler(DataHandler):
    """
    Reads historical market data for multiple symbols from database.

    Merges data from multiple symbols and yields bars in chronological order
    across all symbols. Essential for strategies that trade multiple instruments
    based on a single signal source (e.g., ADX_Trend trading QQQ/TQQQ/SQQQ).

    Attributes:
        session: SQLAlchemy session
        symbols: List of stock ticker symbols
        timeframe: Bar timeframe ('1D', '1H', etc.)
        start_date: Start of backtest period
        end_date: End of backtest period
    """

    def __init__(
        self,
        session: Session,
        symbols: List[str],
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        warmup_bars: int = 0,
    ):
        """
        Initialize multi-symbol database data handler.

        Args:
            session: SQLAlchemy session for database access
            symbols: List of stock ticker symbols to retrieve
            timeframe: Bar timeframe ('1D', '1H', '5m', etc.)
            start_date: Start of TRADING period
            end_date: End of trading period
            warmup_bars: Number of bars to fetch BEFORE start_date for indicator warmup

        Notes:
            - If warmup_bars > 0, fetches data from approximately (start_date - warmup_bars trading days)
            - Warmup bars are included in the returned data
            - Actual warmup start is calculated using _calculate_warmup_start_date()

        Example:
            handler = MultiSymbolDataHandler(
                session=session,
                symbols=['QQQ', 'TQQQ', 'SQQQ'],
                timeframe='1D',
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
                warmup_bars=147
            )
        """
        self.session = session
        self.symbols = symbols
        self.timeframe = timeframe
        self.warmup_bars = warmup_bars

        # Convert timezone-aware datetimes to naive UTC for database comparison
        # Database stores timestamps as naive TEXT in SQLite, so we need naive datetimes
        # for proper comparison in WHERE clauses
        if start_date.tzinfo is not None:
            start_date = start_date.replace(tzinfo=None)
        if end_date.tzinfo is not None:
            end_date = end_date.replace(tzinfo=None)

        # FIX: If end_date is midnight (date-only input), set to end of day
        # to include ALL bars for that date (e.g., intraday timestamps like 05:00:00)
        if end_date.hour == 0 and end_date.minute == 0 and end_date.second == 0:
            end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            logger.debug(f"end_date set to end of day: {end_date}")

        # Calculate actual query start date if warmup is needed
        if warmup_bars > 0:
            self.start_date = self._calculate_warmup_start_date(start_date, warmup_bars)
            logger.info(
                f"Multi-symbol handler: Fetching {warmup_bars} warmup bars before {start_date.date()} "
                f"(query start: {self.start_date.date()})"
            )
        else:
            self.start_date = start_date

        self.end_date = end_date

        # Cache for latest bars per symbol
        self._latest_bars: dict[str, Optional[MarketDataEvent]] = {
            symbol: None for symbol in symbols
        }

        # Validate data exists for each symbol
        total_bars = 0
        for symbol in symbols:
            count = self._get_bar_count(symbol)
            total_bars += count
            logger.info(
                f"MultiSymbolDataHandler: {symbol} {timeframe} "
                f"from {start_date.date()} to {end_date.date()} ({count} bars)"
            )

            if count == 0:
                logger.warning(
                    f"No data found for {symbol} {timeframe} in date range"
                )

        logger.info(
            f"MultiSymbolDataHandler initialized: {len(symbols)} symbols, "
            f"{total_bars} total bars"
        )

    def _get_bar_count(self, symbol: str) -> int:
        """Get total number of bars for a symbol in date range."""
        return (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == self.timeframe,
                    MarketData.timestamp >= self.start_date,
                    MarketData.timestamp <= self.end_date,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .count()
        )

    def _calculate_warmup_start_date(self, start_date: datetime, warmup_bars: int) -> datetime:
        """
        Calculate start date to fetch warmup bars using NYSE market calendar.

        Uses pandas_market_calendars for exact trading day calculation
        with buffer to account for multi-symbol bar distribution.

        Args:
            start_date: Requested trading start date
            warmup_bars: Number of warmup bars needed

        Returns:
            datetime: Start date to begin fetching (with buffer)

        Notes:
            - Uses NYSE calendar for accurate US market trading days
            - Accounts for weekends, holidays, and market closures
            - Multi-symbol: 50% buffer for interleaved bar distribution
            - Falls back to 2× buffer if calendar lookup fails

        Multi-Symbol Warmup Math:
            With N symbols (e.g., 6: QQQ, TQQQ, PSQ, TLT, TMF, TMV), bars are
            sorted chronologically across ALL symbols. When warmup ends by DATE,
            each symbol only has ~1/N of total bars in strategy._bars.

            Example: 221 QQQ bars needed, 6 symbols
            - 10% buffer: ~197 QQQ bars (deficit → 30 trading days late)
            - 50% buffer: ~296 QQQ bars (surplus → starts on time)
        """
        import pandas_market_calendars as mcal

        # Get NYSE calendar
        nyse = mcal.get_calendar('NYSE')

        # Convert start_date to date for calendar operations
        if isinstance(start_date, datetime):
            start_dt = start_date.date()
        else:
            start_dt = start_date

        # For multi-symbol handlers, bars are sorted chronologically across ALL symbols.
        # When warmup ends by DATE, each symbol only has ~1/N of total bars.
        # Need 50% buffer (not 10%) to ensure each symbol has enough warmup bars.
        #
        # Math: With 6 symbols and 221 required QQQ bars:
        # - 10% buffer gave ~197 QQQ bars (deficit of 24 → 30 trading days late)
        # - 50% buffer gives ~296 QQQ bars (surplus of 75 → starts on time)
        num_symbols = len(self.symbols) if hasattr(self, 'symbols') else 1
        if num_symbols > 1:
            # Multi-symbol: 50% buffer to account for interleaved bar distribution
            warmup_with_buffer = int(warmup_bars * 1.5)
            buffer_pct = 50
        else:
            # Single-symbol: 10% buffer for data gaps
            warmup_with_buffer = int(warmup_bars * 1.1)
            buffer_pct = 10

        try:
            # Get trading schedule going back far enough
            # Use 2× warmup_with_buffer as calendar days to ensure we have enough history
            search_start = start_dt - timedelta(days=warmup_with_buffer * 2)
            schedule = nyse.schedule(start_date=search_start, end_date=start_dt - timedelta(days=1))

            # Get trading days STRICTLY BEFORE start_date
            trading_days = schedule.index.date.tolist()

            if len(trading_days) < warmup_with_buffer:
                # Need to look back further - extend search
                search_start = start_dt - timedelta(days=warmup_with_buffer * 3)
                schedule = nyse.schedule(start_date=search_start, end_date=start_dt - timedelta(days=1))
                trading_days = schedule.index.date.tolist()

            if len(trading_days) < warmup_with_buffer:
                logger.warning(
                    f"Only found {len(trading_days)} trading days, need {warmup_with_buffer}. "
                    f"Using earliest available date."
                )
                warmup_start = trading_days[0] if trading_days else search_start
            else:
                # Use buffered warmup to get extra safety margin
                warmup_start = trading_days[-warmup_with_buffer]

            logger.debug(
                f"Calculated warmup start: {warmup_start} "
                f"({warmup_with_buffer} trading days before {start_dt}, "
                f"includes {buffer_pct}% buffer over {warmup_bars} required, "
                f"{num_symbols} symbols)"
            )

            return datetime.combine(warmup_start, datetime.min.time())

        except Exception as e:
            # Fallback to 2× buffer if calendar lookup fails
            logger.warning(
                f"NYSE calendar lookup failed: {e}. "
                f"Falling back to 2× buffer estimation."
            )
            calendar_days = int(warmup_with_buffer * 2.0)
            warmup_start = start_date - timedelta(days=calendar_days)
            return warmup_start

    def _convert_to_event(self, db_bar: MarketData) -> MarketDataEvent:
        """
        Convert database MarketData model to MarketDataEvent.

        Args:
            db_bar: MarketData database record

        Returns:
            MarketDataEvent for event loop processing
        """
        return MarketDataEvent(
            symbol=db_bar.symbol,
            timestamp=db_bar.timestamp,
            open=db_bar.open,
            high=db_bar.high,
            low=db_bar.low,
            close=db_bar.close,
            volume=db_bar.volume,
            timeframe=db_bar.timeframe,
        )

    def get_next_bar(self) -> Iterator[MarketDataEvent]:
        """
        Yield bars one at a time in chronological order across all symbols.

        CRITICAL: Merges data from all symbols and yields in strict timestamp order.
        This ensures strategies see data in the correct chronological sequence,
        preventing lookback bias even with multiple symbols.

        Yields:
            MarketDataEvent objects in chronological order across all symbols

        Example:
            # For symbols ['QQQ', 'TQQQ', 'SQQQ']:
            # Yields: QQQ 2024-01-01, TQQQ 2024-01-01, SQQQ 2024-01-01,
            #         QQQ 2024-01-02, TQQQ 2024-01-02, SQQQ 2024-01-02, ...
            for bar in data_handler.get_next_bar():
                strategy.on_bar(bar)  # Will receive bars from all symbols
        """
        # Query bars for ALL symbols in chronological order
        # CRITICAL: Order by timestamp first, then symbol for deterministic ordering
        query = (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol.in_(self.symbols),
                    MarketData.timeframe == self.timeframe,
                    MarketData.timestamp >= self.start_date,
                    MarketData.timestamp <= self.end_date,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .order_by(
                MarketData.timestamp.asc(),  # CRITICAL: chronological across symbols
                MarketData.symbol.asc()      # Secondary: consistent ordering within timestamp
            )
        )

        # Stream results to avoid loading all into memory
        # Track skips per symbol for summary logging
        weekend_skip_counts = {symbol: 0 for symbol in self.symbols}
        holiday_skip_counts = {symbol: 0 for symbol in self.symbols}

        for db_bar in query.yield_per(1000):
            # Filter out weekend dates (data quality issue)
            if _is_weekend(db_bar.timestamp):
                weekend_skip_counts[db_bar.symbol] += 1
                continue

            # Filter out market holidays (defensive - should be filtered at sync)
            if _is_market_holiday(db_bar.timestamp):
                holiday_skip_counts[db_bar.symbol] += 1
                continue

            event = self._convert_to_event(db_bar)
            self._latest_bars[event.symbol] = event
            yield event

        # Log summary of skipped bars
        total_weekend = sum(weekend_skip_counts.values())
        total_holiday = sum(holiday_skip_counts.values())
        if total_weekend > 0 or total_holiday > 0:
            logger.warning(
                f"Skipped {total_weekend} weekend, {total_holiday} holiday bars "
                f"across symbols (data quality issue)"
            )

    def get_latest_bar(self, symbol: str) -> Optional[MarketDataEvent]:
        """
        Get the most recent bar for a symbol.

        Args:
            symbol: Stock ticker symbol (must be in initialized symbols list)

        Returns:
            Latest MarketDataEvent or None if no data

        Example:
            latest_qqq = data_handler.get_latest_bar('QQQ')
            latest_tqqq = data_handler.get_latest_bar('TQQQ')
            if latest_qqq and latest_tqqq:
                # Compare prices across symbols
                pass
        """
        if symbol not in self.symbols:
            logger.warning(
                f"Requested symbol {symbol} not in handler symbols {self.symbols}"
            )
            return None

        return self._latest_bars.get(symbol)

    def get_bars(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        limit: Optional[int] = None,
        warmup_bars: int = 0
    ) -> List[MarketDataEvent]:
        """
        Get bars for a date range for a specific symbol, optionally including warmup period.

        Args:
            symbol: Stock ticker symbol
            start_date: Start of TRADING period
            end_date: End of trading period
            limit: Optional max number of bars to return
            warmup_bars: Number of bars to fetch BEFORE start_date for indicator warmup

        Returns:
            List of MarketDataEvent objects in chronological order

        Notes:
            - If warmup_bars > 0, fetches data from approximately (start_date - warmup_bars trading days)
            - Warmup bars are included in the returned data
            - Actual warmup start is calculated using _calculate_warmup_start_date()

        Example:
            # Get QQQ bars for January 2024 with 50-bar warmup
            bars = data_handler.get_bars(
                'QQQ',
                datetime(2024, 1, 1),
                datetime(2024, 1, 31),
                warmup_bars=50
            )
            # Returns bars from ~Nov 2023 through Jan 2024
        """
        if symbol not in self.symbols:
            logger.warning(
                f"Requested symbol {symbol} not in handler symbols {self.symbols}"
            )
            return []

        # Convert timezone-aware datetimes to naive UTC for database comparison
        # Database stores timestamps as naive TEXT in SQLite, so we need naive datetimes
        # for proper comparison in WHERE clauses
        if start_date.tzinfo is not None:
            start_date = start_date.replace(tzinfo=None)
        if end_date.tzinfo is not None:
            end_date = end_date.replace(tzinfo=None)

        # If end_date is midnight (date-only input), set to end of day
        # to include ALL bars for that date (e.g., intraday timestamps like 05:00:00)
        if end_date.hour == 0 and end_date.minute == 0 and end_date.second == 0:
            end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            logger.debug(f"get_bars (multi-symbol): end_date set to end of day: {end_date}")

        # Calculate warmup start date if needed
        query_start = start_date
        if warmup_bars > 0:
            query_start = self._calculate_warmup_start_date(start_date, warmup_bars)
            logger.info(
                f"Fetching {warmup_bars} warmup bars for {symbol} before {start_date.date()} "
                f"(query start: {query_start.date()})"
            )

        query = (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == self.timeframe,
                    MarketData.timestamp >= query_start,
                    MarketData.timestamp <= end_date,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .order_by(MarketData.timestamp.asc())
        )

        if limit:
            query = query.limit(limit)

        return [self._convert_to_event(db_bar) for db_bar in query.all()]

    def get_bars_lookback(self, symbol: str, lookback: int) -> List[MarketDataEvent]:
        """
        Get last N bars for a symbol up to current position.

        IMPORTANT: Only returns bars up to the current bar being processed.
        This prevents lookback bias by not peeking into the future.

        Args:
            symbol: Stock ticker symbol
            lookback: Number of bars to retrieve

        Returns:
            List of MarketDataEvent objects (oldest first)

        Example:
            # Get last 20 QQQ bars for SMA calculation
            bars = data_handler.get_bars_lookback('QQQ', 20)
            closes = [bar.close for bar in bars]
            sma = sum(closes) / len(closes)
        """
        if symbol not in self.symbols:
            logger.warning(
                f"Requested symbol {symbol} not in handler symbols {self.symbols}"
            )
            return []

        latest_bar = self._latest_bars.get(symbol)
        if not latest_bar:
            return []

        # Query bars up to (and including) current bar
        # CRITICAL: timestamp <= current bar prevents future peeking
        query = (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == self.timeframe,
                    MarketData.timestamp <= latest_bar.timestamp,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .order_by(MarketData.timestamp.desc())
            .limit(lookback)
        )

        # Return in chronological order (oldest first)
        bars = [self._convert_to_event(db_bar) for db_bar in query.all()]
        return list(reversed(bars))

    def get_symbols(self) -> List[str]:
        """
        Get list of available symbols.

        Returns:
            List of initialized symbols

        Example:
            symbols = data_handler.get_symbols()
            # ['QQQ', 'TQQQ', 'SQQQ']
        """
        return self.symbols

    def get_intraday_bars_for_time_window(
        self,
        symbol: str,
        date: datetime,
        start_time: datetime.time,
        end_time: datetime.time,
        interval: str = '5m'
    ) -> List[MarketDataEvent]:
        """
        Fetch intraday bars for a specific time window on a given date.

        This method is designed for execution timing analysis, allowing strategies
        to fetch bars within specific market hours (e.g., first 15 minutes of trading).

        Args:
            symbol: Stock ticker symbol (e.g., 'QQQ')
            date: Trading date (timezone-naive or aware, will be converted to UTC)
            start_time: Start time in market hours ET (e.g., time(9, 30) for 9:30 AM)
            end_time: End time in market hours ET (e.g., time(9, 45) for 9:45 AM)
            interval: Bar interval ('5m' or '15m')

        Returns:
            List of MarketDataEvent objects for the time window, chronologically ordered

        Raises:
            ValueError: If interval is not '5m' or '15m'
            ValueError: If symbol not in handler symbols

        Notes:
            - Input times are interpreted as ET market times and converted to UTC
            - Database stores timestamps in naive UTC format
            - Query is timezone-aware but database comparison uses naive datetimes
            - Returns empty list if no data found (logged as warning)

        Example:
            # Fetch 9:30 AM to 9:45 AM ET on 2025-03-10
            from datetime import date, time

            bars = handler.get_intraday_bars_for_time_window(
                symbol='QQQ',
                date=date(2025, 3, 10),
                start_time=time(9, 30),
                end_time=time(9, 45),
                interval='5m'
            )
            # Returns 3 bars: 9:30, 9:35, 9:40
        """
        from datetime import date as date_type, time as time_type
        from zoneinfo import ZoneInfo

        # Validate interval
        if interval not in ['5m', '15m']:
            raise ValueError(f"Interval must be '5m' or '15m', got: {interval}")

        # Validate symbol
        if symbol not in self.symbols:
            raise ValueError(
                f"Requested symbol {symbol} not in handler symbols {self.symbols}"
            )

        # Convert date to datetime object if needed
        if isinstance(date, date_type) and not isinstance(date, datetime):
            date = datetime.combine(date, time_type(0, 0))

        # Convert times to ET timezone-aware datetimes
        et_tz = ZoneInfo('America/New_York')
        start_datetime_et = datetime.combine(date.date(), start_time, tzinfo=et_tz)
        end_datetime_et = datetime.combine(date.date(), end_time, tzinfo=et_tz)

        # Convert to UTC for database query
        start_datetime_utc = start_datetime_et.astimezone(ZoneInfo('UTC'))
        end_datetime_utc = end_datetime_et.astimezone(ZoneInfo('UTC'))

        # Convert to naive UTC for database comparison
        # Database stores timestamps as naive TEXT in SQLite
        start_datetime_utc_naive = start_datetime_utc.replace(tzinfo=None)
        end_datetime_utc_naive = end_datetime_utc.replace(tzinfo=None)

        logger.debug(
            f"Fetching {symbol} {interval} bars for {date.date()} "
            f"ET {start_time}-{end_time} "
            f"(UTC {start_datetime_utc_naive.time()}-{end_datetime_utc_naive.time()})"
        )

        # Query database for bars in time window
        query = (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == interval,
                    MarketData.timestamp >= start_datetime_utc_naive,
                    MarketData.timestamp <= end_datetime_utc_naive,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .order_by(MarketData.timestamp.asc())
        )

        bars = [self._convert_to_event(db_bar) for db_bar in query.all()]

        if not bars:
            logger.warning(
                f"No {interval} bars found for {symbol} on {date.date()} "
                f"between {start_time} and {end_time} ET"
            )
        else:
            logger.info(
                f"Retrieved {len(bars)} {interval} bars for {symbol} "
                f"on {date.date()} ET {start_time}-{end_time}"
            )

        return bars
