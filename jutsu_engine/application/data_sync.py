"""
Data synchronization engine for incremental database updates.

Manages the process of fetching new market data from external sources
and storing it in the database. Tracks metadata to support incremental
updates, avoiding redundant data fetching.

Example:
    from jutsu_engine.application.data_sync import DataSync
    from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher

    fetcher = SchwabDataFetcher()
    sync = DataSync(session=session)

    # Sync specific symbol and timeframe
    sync.sync_symbol(
        fetcher=fetcher,
        symbol='AAPL',
        timeframe='1D',
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31)
    )

    # Check status
    status = sync.get_sync_status('AAPL', '1D')
    print(f"Last update: {status['last_update']}")
"""
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from jutsu_engine.data.models import MarketData, DataMetadata, DataAuditLog
from jutsu_engine.data.fetchers.base import DataFetcher
from jutsu_engine.utils.logging_config import get_data_logger

logger = get_data_logger('SYNC')


def _normalize_to_utc(dt: datetime) -> datetime:
    """
    Normalize datetime to UTC timezone.
    
    Handles three cases:
    1. Naive datetime (no tzinfo) - assumes UTC and attaches tzinfo
    2. UTC datetime - returns as-is
    3. Non-UTC timezone (e.g., PST, EST) - converts to UTC
    
    This is critical for PostgreSQL which may return timestamps with
    local timezone offset (e.g., -08:00 PST) that need conversion to
    UTC for consistent comparisons.
    
    Args:
        dt: datetime to normalize (can be naive or timezone-aware)
        
    Returns:
        datetime in UTC timezone
    """
    if dt.tzinfo is None:
        # Naive datetime - assume UTC
        return dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo == timezone.utc:
        # Already UTC
        return dt
    else:
        # Convert from non-UTC timezone to UTC
        return dt.astimezone(timezone.utc)


def _is_weekend(timestamp: datetime) -> bool:
    """
    Check if timestamp falls on a weekend (Saturday=5, Sunday=6).

    Market data should only exist on weekdays. Weekend dates from external
    data sources indicate data quality issues that should be filtered out
    before storing in the database.

    Args:
        timestamp: datetime to check

    Returns:
        True if Saturday or Sunday, False otherwise
    """
    return timestamp.weekday() in (5, 6)  # Saturday=5, Sunday=6


def _is_market_holiday(timestamp: datetime) -> bool:
    """
    Check if timestamp falls on a market holiday (NYSE closed).

    Uses NYSE calendar to determine if the trading date is a holiday.
    Always converts to Eastern Time to get the correct NYSE trading date,
    since NYSE trading dates are defined in ET.

    Example: A daily bar stored as 2026-01-19 21:00:00 PST represents
    trading on Jan 20, since 21:00 PST = 00:00 ET the next day.

    Args:
        timestamp: datetime to check (should be timezone-aware)

    Returns:
        True if NYSE is closed for holiday, False otherwise
    """
    import pytz
    import pandas_market_calendars as mcal
    from datetime import date, time

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

    # Get NYSE calendar - cache this for efficiency
    if not hasattr(_is_market_holiday, '_nyse_cache'):
        _is_market_holiday._nyse_cache = {}

    # Get trading days for the year (cached)
    year = trading_date.year
    if year not in _is_market_holiday._nyse_cache:
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )
        _is_market_holiday._nyse_cache[year] = set(schedule.index.date)

    trading_days = _is_market_holiday._nyse_cache[year]

    # If weekday but not in trading days, it's a holiday
    return trading_date not in trading_days


def _is_outside_market_hours(timestamp: datetime, timeframe: str) -> bool:
    """
    Check if intraday bar timestamp is outside regular market hours (9:30-16:00 ET).

    Only applies to intraday timeframes (5m, 15m, 1H, etc.). Daily bars are
    not filtered by time as they represent the entire trading day.

    Args:
        timestamp: datetime to check (should be timezone-aware)
        timeframe: Bar timeframe ('1D', '5m', '15m', etc.)

    Returns:
        True if intraday bar is outside market hours, False otherwise
    """
    import pytz
    from datetime import time

    # Daily bars don't need market hours filtering
    if timeframe in ('1D', 'D', '1W', 'W', '1M', 'M'):
        return False

    # Convert to Eastern Time
    et = pytz.timezone('America/New_York')
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    ts_et = timestamp.astimezone(et)
    ts_time = ts_et.time()

    # Market hours: 9:30 AM - 4:00 PM ET
    market_open = time(9, 30)
    market_close = time(16, 0)

    return ts_time < market_open or ts_time >= market_close


class DataSync:
    """
    Manages incremental data synchronization to database.

    Coordinates data fetching from external sources and storage in database.
    Tracks metadata to enable efficient incremental updates.

    Attributes:
        session: SQLAlchemy database session
    """

    def __init__(self, session: Session):
        """
        Initialize data sync manager.

        Args:
            session: SQLAlchemy session for database operations

        Example:
            sync = DataSync(session)
        """
        self.session = session
        logger.info("DataSync initialized")

    def sync_symbol(
        self,
        fetcher: DataFetcher,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Synchronize data for a symbol and timeframe.

        Fetches data from external source and stores in database.
        Supports incremental updates by checking existing data.

        Args:
            fetcher: DataFetcher implementation (e.g., SchwabDataFetcher)
            symbol: Stock ticker symbol
            timeframe: Bar timeframe ('1D', '1H', etc.)
            start_date: Start of date range
            end_date: End of date range (default: today)
            force_refresh: If True, re-fetch all data ignoring metadata

        Returns:
            Dictionary with sync results:
            - bars_fetched: Number of bars retrieved
            - bars_stored: Number of bars written to database
            - bars_updated: Number of existing bars updated
            - start_date: Actual start date used
            - end_date: Actual end date used
            - duration_seconds: Time taken for sync

        Example:
            result = sync.sync_symbol(
                fetcher=schwab_fetcher,
                symbol='AAPL',
                timeframe='1D',
                start_date=datetime(2024, 1, 1)
            )
            print(f"Stored {result['bars_stored']} bars")
        """
        start_time = datetime.now(timezone.utc)

        # Defensive: Ensure all input datetimes are timezone-aware (UTC)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)

        if end_date is None:
            end_date = datetime.now(timezone.utc)
            
            # For daily bars, only fetch complete bars (market must be closed)
            # This prevents fetching partial data during market hours
            if timeframe == '1D' and not force_refresh:
                from jutsu_engine.live.market_calendar import is_daily_bar_complete, is_trading_day
                today = datetime.now(timezone.utc).date()
                if not is_daily_bar_complete(today):
                    # Market is open for today - check if we should cap
                    yesterday = today - timedelta(days=1)
                    
                    # Only cap to yesterday if yesterday was a trading day
                    # If yesterday was weekend/holiday, include today to get recent data
                    if is_trading_day(yesterday):
                        end_date = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc)
                        logger.info(
                            f"⏳ Market hours: Capping end_date to {yesterday} for daily bars "
                            f"(today's bar is incomplete)"
                        )
                    else:
                        # Yesterday was not a trading day, keep today's date
                        logger.info(
                            f"📊 Yesterday ({yesterday}) was not a trading day, "
                            f"including today's partial data for daily bars"
                        )
        elif end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        logger.info(
            f"Starting sync: {symbol} {timeframe} "
            f"from {start_date.date()} to {end_date.date()}"
        )

        # Check for existing data unless force refresh
        actual_start_date = start_date
        actual_end_date = end_date
        if not force_refresh:
            metadata = self._get_metadata(symbol, timeframe)
            if metadata:
                # Normalize last_bar_timestamp to UTC
                # PostgreSQL may return timestamps with local timezone (e.g., -08:00 PST)
                # SQLite may return naive datetime
                last_bar = _normalize_to_utc(metadata.last_bar_timestamp)

                # Get earliest bar timestamp for backfill detection
                first_bar_result = (
                    self.session.query(MarketData.timestamp)
                    .filter(
                        and_(
                            MarketData.symbol == symbol,
                            MarketData.timeframe == timeframe,
                            MarketData.is_valid == True,  # noqa: E712
                        )
                    )
                    .order_by(MarketData.timestamp.asc())
                    .first()
                )

                if first_bar_result:
                    # Normalize first_bar to UTC (handles both naive and non-UTC timezones)
                    first_bar = _normalize_to_utc(first_bar_result[0])

                    # Determine fetch strategy based on start_date vs existing data range
                    if start_date.date() >= last_bar.date():
                        # Incremental update: fetch from last_bar + 1 day (normalized to start of day)
                        # Normalize to midnight to prevent start_date > end_date errors when
                        # last_bar has a time component (e.g., market close at 20:45)
                        actual_start_date = (last_bar + timedelta(days=1)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                        actual_end_date = end_date

                        # Check if calculated start_date is in the future
                        # If yes, data is already up to date (no new bars available yet)
                        # Debug: Log the comparison values
                        today = datetime.now(timezone.utc).date()
                        next_fetch_date = actual_start_date.date()
                        logger.info(
                            f"Future date check: next_fetch_date={next_fetch_date}, "
                            f"today={today}, is_future_or_today={next_fetch_date >= today}"
                        )
                        
                        if actual_start_date.date() >= datetime.now(timezone.utc).date():
                            logger.info(
                                f"Already up to date: last bar is {last_bar.date()}, "
                                f"next bar would be {actual_start_date.date()} (future)"
                            )
                            return {
                                'bars_fetched': 0,
                                'bars_stored': 0,
                                'bars_updated': 0,
                                'start_date': start_date,
                                'end_date': end_date,
                                'duration_seconds': 0,
                            }

                        logger.info(
                            f"Incremental update: fetching from {actual_start_date.date()}"
                        )
                    elif start_date.date() < first_bar.date():
                        # Backfill: user wants data BEFORE earliest existing data
                        # Fetch ONLY the missing earlier data (not all data)
                        actual_start_date = start_date
                        actual_end_date = first_bar - timedelta(days=1)
                        logger.info(
                            f"Backfill mode: fetching from {actual_start_date.date()} "
                            f"to {actual_end_date.date()} (existing data starts at {first_bar.date()})"
                        )
                    # else: start_date falls within existing range, will update/fill gaps

        # Fetch data from external source
        try:
            bars = fetcher.fetch_bars(
                symbol=symbol,
                timeframe=timeframe,
                start_date=actual_start_date,
                end_date=actual_end_date,
            )
        except Exception as e:
            logger.error(f"Failed to fetch data: {e}")
            self._create_audit_log(
                symbol=symbol,
                timeframe=timeframe,
                operation='fetch',
                status='error',
                message=str(e),
            )
            raise

        bars_fetched = len(bars)
        logger.info(f"Fetched {bars_fetched} bars from external source")

        # Filter out invalid data (data quality issues from external sources)
        # 1. Weekend data (Saturday/Sunday)
        # 2. Market holidays (NYSE closed)
        # 3. Outside market hours (for intraday bars only)
        original_count = len(bars)
        weekend_filtered = 0
        holiday_filtered = 0
        off_hours_filtered = 0

        valid_bars = []
        for bar in bars:
            ts = bar['timestamp']

            # Filter 1: Weekend data
            if _is_weekend(ts):
                weekend_filtered += 1
                continue

            # Filter 2: Market holiday data
            if _is_market_holiday(ts):
                holiday_filtered += 1
                continue

            # Filter 3: Outside market hours (intraday only)
            if _is_outside_market_hours(ts, timeframe):
                off_hours_filtered += 1
                continue

            valid_bars.append(bar)

        bars = valid_bars
        total_filtered = weekend_filtered + holiday_filtered + off_hours_filtered

        if total_filtered > 0:
            logger.warning(
                f"Filtered {total_filtered} invalid bars from {symbol}: "
                f"{weekend_filtered} weekend, {holiday_filtered} holiday, "
                f"{off_hours_filtered} off-hours"
            )
        bars_fetched = len(bars)  # Update count after filtering

        if bars_fetched == 0:
            logger.info("No new data to sync (after filtering)")
            return {
                'bars_fetched': 0,
                'bars_stored': 0,
                'bars_updated': 0,
                'weekend_filtered': weekend_filtered,
                'holiday_filtered': holiday_filtered,
                'off_hours_filtered': off_hours_filtered,
                'start_date': actual_start_date,
                'end_date': end_date,
                'duration_seconds': (datetime.now(timezone.utc) - start_time).total_seconds(),
            }

        # Store data in database
        bars_stored = 0
        bars_updated = 0

        for bar_data in bars:
            stored, updated = self._store_bar(
                symbol=symbol,
                timeframe=timeframe,
                bar_data=bar_data,
            )
            if stored:
                bars_stored += 1
            if updated:
                bars_updated += 1

        # Commit all changes
        self.session.commit()

        # Update metadata - preserve most recent last_bar_timestamp
        fetched_last_bar = bars[-1]['timestamp']
        
        # Ensure fetched_last_bar is timezone-aware (UTC)
        # Schwab API may return offset-naive datetime
        if fetched_last_bar.tzinfo is None:
            fetched_last_bar = fetched_last_bar.replace(tzinfo=timezone.utc)
        
        metadata = self._get_metadata(symbol, timeframe)

        if metadata:
            # Ensure existing timestamp is timezone-aware
            existing_last_bar = metadata.last_bar_timestamp
            if existing_last_bar.tzinfo is None:
                existing_last_bar = existing_last_bar.replace(tzinfo=timezone.utc)

            # Keep the MOST RECENT timestamp (important for backfill scenarios)
            last_bar_timestamp = max(existing_last_bar, fetched_last_bar)
        else:
            # No existing metadata, use fetched data
            last_bar_timestamp = fetched_last_bar

        self._update_metadata(
            symbol=symbol,
            timeframe=timeframe,
            last_bar_timestamp=last_bar_timestamp,
            total_bars=self._count_bars(symbol, timeframe),
        )

        # Create audit log
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        self._create_audit_log(
            symbol=symbol,
            timeframe=timeframe,
            operation='sync',
            status='success',
            message=f"Synced {bars_stored} new bars, updated {bars_updated}",
            bars_affected=bars_stored + bars_updated,
        )

        filter_msg = ""
        if total_filtered > 0:
            filter_msg = f", filtered: {weekend_filtered} weekend, {holiday_filtered} holiday, {off_hours_filtered} off-hours"
        logger.info(
            f"Sync complete: {bars_stored} stored, {bars_updated} updated{filter_msg} "
            f"in {duration:.2f}s"
        )

        return {
            'bars_fetched': bars_fetched,
            'bars_stored': bars_stored,
            'bars_updated': bars_updated,
            'weekend_filtered': weekend_filtered,
            'holiday_filtered': holiday_filtered,
            'off_hours_filtered': off_hours_filtered,
            'start_date': actual_start_date,
            'end_date': end_date,
            'duration_seconds': duration,
        }

    def _store_bar(
        self,
        symbol: str,
        timeframe: str,
        bar_data: Dict[str, Any],
    ) -> tuple[bool, bool]:
        """
        Store or update a single bar in database.

        For daily bars, uses trading date (in ET) to find existing bars to prevent
        duplicates when Schwab returns different timestamps for the same trading day
        (e.g., 21:00 PST during market hours vs 22:00 PST after close).

        Args:
            symbol: Stock ticker symbol
            timeframe: Bar timeframe
            bar_data: Dictionary with bar data (timestamp, open, high, low, close, volume)

        Returns:
            Tuple of (stored, updated) booleans
        """
        import pytz
        from sqlalchemy import func

        # Ensure timestamp is timezone-aware (UTC) before database operations
        # Schwab API may return offset-naive datetime
        bar_timestamp = bar_data['timestamp']
        if bar_timestamp.tzinfo is None:
            bar_timestamp = bar_timestamp.replace(tzinfo=timezone.utc)

        logger.debug(f"Storing bar: {symbol} {timeframe} {bar_timestamp} (tzinfo={bar_timestamp.tzinfo})")

        existing_bar = None

        if timeframe == '1D':
            # For daily bars, find existing bar by trading date (in ET) to prevent duplicates
            # when timestamps differ (21:00 vs 22:00 PST for same trading day)
            et = pytz.timezone('America/New_York')
            bar_et = bar_timestamp.astimezone(et)
            trading_date = bar_et.date()

            # Schwab 1D bars have timestamps after market close, typically around
            # midnight-1AM ET the next calendar day. When fetched on weekends or
            # after holidays, the timestamp can shift forward, misidentifying the
            # trading day. Detect and normalize: if the inferred actual trading day
            # (ET date - 1) is not a valid trading day (weekend or holiday),
            # adjust to the previous valid trading day.
            from jutsu_engine.live.market_calendar import get_previous_trading_day, is_trading_day
            inferred_actual_day = trading_date - timedelta(days=1)
            if not is_trading_day(inferred_actual_day):
                correct_trading_day = get_previous_trading_day(trading_date)
                # Normalize timestamp to canonical form: 01:00 ET on (trading_day + 1)
                next_day = correct_trading_day + timedelta(days=1)
                canonical_et = et.localize(
                    datetime(next_day.year, next_day.month, next_day.day, 1, 0, 0)
                )
                logger.info(
                    f"Normalized weekend-shifted 1D bar: "
                    f"ET date {trading_date} -> trading day {correct_trading_day} "
                    f"(original: {bar_timestamp}, canonical: {canonical_et})"
                )
                bar_timestamp = canonical_et.astimezone(timezone.utc)
                bar_et = bar_timestamp.astimezone(et)
                trading_date = bar_et.date()

            # Find any existing bar for this trading date
            existing_bar = (
                self.session.query(MarketData)
                .filter(
                    and_(
                        MarketData.symbol == symbol,
                        MarketData.timeframe == timeframe,
                        func.date(
                            func.timezone('America/New_York', MarketData.timestamp)
                        ) == trading_date,
                    )
                )
                .first()
            )
            if existing_bar:
                logger.debug(f"Found existing daily bar for trading date {trading_date} at {existing_bar.timestamp}")
        else:
            # For intraday bars, use exact timestamp match
            existing_bar = (
                self.session.query(MarketData)
                .filter(
                    and_(
                        MarketData.symbol == symbol,
                        MarketData.timeframe == timeframe,
                        MarketData.timestamp == bar_timestamp,
                    )
                )
                .first()
            )

        if existing_bar:
            # Update existing bar - update timestamp too in case it changed (21:00 → 22:00)
            logger.debug(f"Found existing bar at {existing_bar.timestamp}, updating")
            existing_bar.timestamp = bar_timestamp  # Update to latest timestamp
            existing_bar.open = bar_data['open']
            existing_bar.high = bar_data['high']
            existing_bar.low = bar_data['low']
            existing_bar.close = bar_data['close']
            existing_bar.volume = bar_data['volume']
            existing_bar.is_valid = True
            return (False, True)
        else:
            # Create new bar
            logger.debug(f"No existing bar found, creating new bar at {bar_timestamp}")
            new_bar = MarketData(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=bar_timestamp,
                open=bar_data['open'],
                high=bar_data['high'],
                low=bar_data['low'],
                close=bar_data['close'],
                volume=bar_data['volume'],
                data_source=bar_data.get('data_source', 'schwab'),
                is_valid=True,
            )
            self.session.add(new_bar)
            logger.debug(f"Added new bar to session: {new_bar}")
            return (True, False)

    def _get_metadata(self, symbol: str, timeframe: str) -> Optional[DataMetadata]:
        """Get metadata for symbol and timeframe."""
        return (
            self.session.query(DataMetadata)
            .filter(
                and_(
                    DataMetadata.symbol == symbol,
                    DataMetadata.timeframe == timeframe,
                )
            )
            .first()
        )

    def _update_metadata(
        self,
        symbol: str,
        timeframe: str,
        last_bar_timestamp: datetime,
        total_bars: int,
    ):
        """Update or create metadata record."""
        metadata = self._get_metadata(symbol, timeframe)

        if metadata:
            metadata.last_bar_timestamp = last_bar_timestamp
            metadata.total_bars = total_bars
            metadata.last_updated = datetime.now(timezone.utc)
        else:
            metadata = DataMetadata(
                symbol=symbol,
                timeframe=timeframe,
                last_bar_timestamp=last_bar_timestamp,
                total_bars=total_bars,
                last_updated=datetime.now(timezone.utc),
            )
            self.session.add(metadata)

        self.session.commit()

    def _count_bars(self, symbol: str, timeframe: str) -> int:
        """Count total bars for symbol and timeframe."""
        return (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == timeframe,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .count()
        )

    def _create_audit_log(
        self,
        symbol: str,
        timeframe: str,
        operation: str,
        status: str,
        message: str,
        bars_affected: int = 0,
    ):
        """Create audit log entry."""
        audit_log = DataAuditLog(
            symbol=symbol,
            timeframe=timeframe,
            operation=operation,
            status=status,
            message=message,
            bars_affected=bars_affected,
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add(audit_log)
        self.session.commit()

    def get_sync_status(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """
        Get synchronization status for symbol and timeframe.

        Args:
            symbol: Stock ticker symbol
            timeframe: Bar timeframe

        Returns:
            Dictionary with status information:
            - has_data: Whether any data exists
            - total_bars: Number of bars in database
            - last_update: Timestamp of last sync
            - last_bar_timestamp: Timestamp of most recent bar
            - first_bar_timestamp: Timestamp of oldest bar

        Example:
            status = sync.get_sync_status('AAPL', '1D')
            if status['has_data']:
                print(f"Last update: {status['last_update']}")
        """
        metadata = self._get_metadata(symbol, timeframe)

        if not metadata:
            return {
                'has_data': False,
                'total_bars': 0,
                'last_update': None,
                'last_bar_timestamp': None,
                'first_bar_timestamp': None,
            }

        # Get first bar timestamp
        first_bar = (
            self.session.query(MarketData.timestamp)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == timeframe,
                    MarketData.is_valid == True,  # noqa: E712
                )
            )
            .order_by(MarketData.timestamp.asc())
            .first()
        )

        return {
            'has_data': True,
            'total_bars': metadata.total_bars,
            'last_update': metadata.last_updated,
            'last_bar_timestamp': metadata.last_bar_timestamp,
            'first_bar_timestamp': first_bar[0] if first_bar else None,
        }

    def get_audit_logs(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 100,
    ) -> List[DataAuditLog]:
        """
        Retrieve audit logs for data operations.

        Args:
            symbol: Optional symbol filter
            timeframe: Optional timeframe filter
            limit: Maximum number of logs to return

        Returns:
            List of DataAuditLog objects

        Example:
            logs = sync.get_audit_logs(symbol='AAPL', limit=10)
            for log in logs:
                print(f"{log.timestamp}: {log.operation} - {log.status}")
        """
        query = self.session.query(DataAuditLog)

        if symbol:
            query = query.filter(DataAuditLog.symbol == symbol)
        if timeframe:
            query = query.filter(DataAuditLog.timeframe == timeframe)

        return (
            query.order_by(DataAuditLog.timestamp.desc())
            .limit(limit)
            .all()
        )

    def validate_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Validate data quality for symbol and timeframe.

        Checks for:
        - Missing bars (gaps in data)
        - Invalid OHLC relationships (high < low, etc.)
        - Zero volume bars
        - Duplicate timestamps

        Args:
            symbol: Stock ticker symbol
            timeframe: Bar timeframe
            start_date: Optional start date for validation range
            end_date: Optional end date for validation range

        Returns:
            Dictionary with validation results:
            - total_bars: Total bars checked
            - valid_bars: Number of valid bars
            - invalid_bars: Number of invalid bars
            - issues: List of issue descriptions

        Example:
            validation = sync.validate_data('AAPL', '1D')
            if validation['invalid_bars'] > 0:
                print(f"Found {validation['invalid_bars']} issues")
        """
        query = self.session.query(MarketData).filter(
            and_(
                MarketData.symbol == symbol,
                MarketData.timeframe == timeframe,
            )
        )

        if start_date:
            query = query.filter(MarketData.timestamp >= start_date)
        if end_date:
            query = query.filter(MarketData.timestamp <= end_date)

        bars = query.order_by(MarketData.timestamp.asc()).all()

        total_bars = len(bars)
        invalid_bars = 0
        issues = []

        for bar in bars:
            # Check OHLC relationships
            if bar.high < bar.low:
                invalid_bars += 1
                issues.append(
                    f"{bar.timestamp}: High ({bar.high}) < Low ({bar.low})"
                )
                bar.is_valid = False

            if bar.close > bar.high or bar.close < bar.low:
                invalid_bars += 1
                issues.append(
                    f"{bar.timestamp}: Close ({bar.close}) outside High/Low range"
                )
                bar.is_valid = False

            if bar.open > bar.high or bar.open < bar.low:
                invalid_bars += 1
                issues.append(
                    f"{bar.timestamp}: Open ({bar.open}) outside High/Low range"
                )
                bar.is_valid = False

            # Check for zero volume (may be valid for some assets)
            if bar.volume == 0:
                issues.append(f"{bar.timestamp}: Zero volume")

        self.session.commit()

        logger.info(
            f"Validation complete: {total_bars} bars checked, "
            f"{invalid_bars} invalid"
        )

        return {
            'total_bars': total_bars,
            'valid_bars': total_bars - invalid_bars,
            'invalid_bars': invalid_bars,
            'issues': issues,
        }

    def sync_all_symbols(
        self,
        fetcher: DataFetcher,
        end_date: Optional[datetime] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Synchronize all existing symbols to latest date (today).

        Queries DataMetadata for all (symbol, timeframe) combinations and syncs
        each from last_bar_timestamp + 1 day to end_date (default: today).
        Retries failed symbols once before continuing.

        Args:
            fetcher: DataFetcher implementation (e.g., SchwabDataFetcher)
            end_date: End date for sync (default: today)
            force: If True, ignore market hours check and fetch all data
                   (may result in partial bars for current day)

        Returns:
            Dictionary with sync results:
            - total_symbols: Total number of symbols found
            - successful_syncs: Number of successful syncs
            - failed_syncs: Number of failed syncs
            - results: Dict mapping symbol to sync result
              - For each symbol: {start_date, end_date, bars_added, status, error}

        Example:
            result = sync.sync_all_symbols(fetcher=schwab_fetcher)
            print(f"Synced {result['successful_syncs']} symbols")
            for symbol, info in result['results'].items():
                print(f"{symbol}: {info['bars_added']} bars added")
        """
        start_time = datetime.now(timezone.utc)

        # Defensive: Ensure end_date is timezone-aware (UTC)
        if end_date is None:
            end_date = datetime.now(timezone.utc)
        elif end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        logger.info(f"Starting sync_all_symbols to {end_date.date()}")

        # Query all (symbol, timeframe) combinations from metadata
        metadata_entries = self.session.query(DataMetadata).all()

        if not metadata_entries:
            logger.warning("No symbols found in metadata table")
            return {
                'total_symbols': 0,
                'successful_syncs': 0,
                'failed_syncs': 0,
                'results': {},
            }

        total_symbols = len(metadata_entries)
        successful_syncs = 0
        failed_syncs = 0
        results = {}

        logger.info(f"Found {total_symbols} symbol/timeframe combinations")

        for metadata in metadata_entries:
            symbol = metadata.symbol
            timeframe = metadata.timeframe
            symbol_key = f"{symbol}:{timeframe}"

            # Normalize last_bar_timestamp to UTC (handles naive, UTC, and non-UTC timezones)
            last_bar = _normalize_to_utc(metadata.last_bar_timestamp)

            # Determine start_date based on force mode
            if force:
                # FORCE MODE: Full refresh - start from the FIRST bar in database
                # This allows re-fetching and updating all historical data
                first_bar_query = (
                    self.session.query(func.min(MarketData.timestamp))
                    .filter(MarketData.symbol == symbol)
                    .filter(MarketData.timeframe == timeframe)
                    .scalar()
                )
                if first_bar_query:
                    first_bar = _normalize_to_utc(first_bar_query)
                    start_date = first_bar.replace(hour=0, minute=0, second=0, microsecond=0)
                    logger.info(
                        f"🔄 {symbol_key}: Force mode - full refresh from {start_date.date()}"
                    )
                else:
                    # No data in database, start from a reasonable default
                    start_date = (last_bar + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
            else:
                # INCREMENTAL MODE: Start from day after last bar
                start_date = (last_bar + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )

            # For daily bars, only fetch complete bars (market must be closed)
            # unless force=True is specified
            actual_end_date = end_date
            if timeframe == '1D' and not force:
                from jutsu_engine.live.market_calendar import is_daily_bar_complete, is_trading_day
                today = datetime.now(timezone.utc).date()
                if not is_daily_bar_complete(today):
                    # Market is open for today - check if we should cap
                    yesterday = today - timedelta(days=1)
                    
                    # Only cap to yesterday if yesterday was a trading day
                    # If yesterday was weekend/holiday, include today to get the most recent data
                    if is_trading_day(yesterday):
                        max_end_date = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc)
                        if end_date > max_end_date:
                            actual_end_date = max_end_date
                            logger.info(
                                f"⏳ {symbol_key}: Market hours - capping end_date to {yesterday} "
                                f"(today's bar incomplete)"
                            )
                    else:
                        # Yesterday was not a trading day (weekend/holiday)
                        # Include today to get the most recent available data
                        logger.info(
                            f"📊 {symbol_key}: Yesterday ({yesterday}) was not a trading day, "
                            f"including today's partial data"
                        )
            
            # Check if already up-to-date (only in non-force mode)
            # In force mode, we always sync even if start_date > actual_end_date
            if not force and start_date > actual_end_date:
                logger.info(
                    f"✅ {symbol_key}: Already up to date through {last_bar.date()}"
                )
                results[symbol_key] = {
                    'start_date': None,
                    'end_date': actual_end_date,
                    'bars_added': 0,
                    'status': 'up_to_date',
                    'error': None,
                }
                successful_syncs += 1
                continue
            
            logger.info(
                f"Syncing {symbol_key}: "
                f"{start_date.date()} to {actual_end_date.date()}"
            )

            # First attempt
            try:
                sync_result = self.sync_symbol(
                    fetcher=fetcher,
                    symbol=symbol,
                    timeframe=timeframe,
                    start_date=start_date,
                    end_date=actual_end_date,
                    force_refresh=force,
                )

                results[symbol_key] = {
                    'start_date': start_date,
                    'end_date': actual_end_date,
                    'bars_added': sync_result['bars_stored'],
                    'status': 'success',
                    'error': None,
                }
                successful_syncs += 1
                logger.info(
                    f"{symbol_key}: Success - {sync_result['bars_stored']} bars added"
                )

            except Exception as e:
                logger.warning(f"{symbol_key}: First attempt failed - {e}")

                # Retry once
                try:
                    logger.info(f"{symbol_key}: Retrying...")
                    sync_result = self.sync_symbol(
                        fetcher=fetcher,
                        symbol=symbol,
                        timeframe=timeframe,
                        start_date=start_date,
                        end_date=actual_end_date,
                        force_refresh=force,
                    )

                    results[symbol_key] = {
                        'start_date': start_date,
                        'end_date': actual_end_date,
                        'bars_added': sync_result['bars_stored'],
                        'status': 'success_after_retry',
                        'error': None,
                    }
                    successful_syncs += 1
                    logger.info(
                        f"{symbol_key}: Retry successful - "
                        f"{sync_result['bars_stored']} bars added"
                    )

                except Exception as retry_error:
                    logger.error(f"{symbol_key}: Retry failed - {retry_error}")
                    results[symbol_key] = {
                        'start_date': start_date,
                        'end_date': end_date,
                        'bars_added': 0,
                        'status': 'failed',
                        'error': str(retry_error),
                    }
                    failed_syncs += 1

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            f"Sync all complete: {successful_syncs} successful, "
            f"{failed_syncs} failed in {duration:.2f}s"
        )

        return {
            'total_symbols': total_symbols,
            'successful_syncs': successful_syncs,
            'failed_syncs': failed_syncs,
            'results': results,
        }

    def get_all_symbols_metadata(self) -> List[Dict[str, Any]]:
        """
        Get metadata for all symbols with date ranges.

        Queries DataMetadata and MarketData tables to retrieve:
        - Symbol and timeframe
        - First bar timestamp (MIN)
        - Last bar timestamp (MAX)
        - Total bars count

        Returns:
            List of dictionaries with symbol metadata:
            - symbol: Stock ticker symbol
            - timeframe: Bar timeframe
            - first_bar: Timestamp of earliest bar
            - last_bar: Timestamp of latest bar
            - total_bars: Number of bars in database

        Example:
            metadata_list = sync.get_all_symbols_metadata()
            for item in metadata_list:
                print(f"{item['symbol']} ({item['timeframe']}): "
                      f"{item['first_bar'].date()} to {item['last_bar'].date()}")
        """
        logger.info("Querying all symbols metadata")

        # Get all metadata entries
        metadata_entries = self.session.query(DataMetadata).all()

        if not metadata_entries:
            logger.warning("No symbols found in metadata table")
            return []

        results = []

        for metadata in metadata_entries:
            symbol = metadata.symbol
            timeframe = metadata.timeframe

            # Get first bar timestamp
            first_bar_result = (
                self.session.query(MarketData.timestamp)
                .filter(
                    and_(
                        MarketData.symbol == symbol,
                        MarketData.timeframe == timeframe,
                        MarketData.is_valid == True,  # noqa: E712
                    )
                )
                .order_by(MarketData.timestamp.asc())
                .first()
            )

            # Get last bar timestamp (use metadata for consistency)
            last_bar = metadata.last_bar_timestamp

            # Normalize timestamps to UTC (handles naive, UTC, and non-UTC timezones)
            if first_bar_result:
                first_bar = _normalize_to_utc(first_bar_result[0])
            else:
                first_bar = None

            if last_bar:
                last_bar = _normalize_to_utc(last_bar)

            results.append({
                'symbol': symbol,
                'timeframe': timeframe,
                'first_bar': first_bar,
                'last_bar': last_bar,
                'total_bars': metadata.total_bars,
            })

        logger.info(f"Retrieved metadata for {len(results)} symbol/timeframe combinations")

        return results

    def delete_symbol_data(
        self,
        symbol: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Delete all market data for a symbol.

        Removes all market_data and data_metadata entries for the specified symbol
        across all timeframes. This operation is irreversible.

        Args:
            symbol: Stock ticker symbol to delete
            force: Skip existence check if True (for scripting)

        Returns:
            Dictionary with deletion results:
            - success: bool - Whether deletion succeeded
            - symbol: str - Symbol that was deleted
            - rows_deleted: int - Number of market_data rows deleted
            - metadata_deleted: bool - Whether metadata was deleted
            - message: str - Human-readable result message

        Raises:
            ValueError: If symbol is empty or invalid format
            DatabaseError: If deletion transaction fails

        Example:
            result = sync.delete_symbol_data(symbol='TQQQ')
            if result['success']:
                print(f"Deleted {result['rows_deleted']} bars for {result['symbol']}")
        """
        # Validate symbol format
        if not symbol or not symbol.strip():
            raise ValueError("Symbol cannot be empty")

        symbol = symbol.strip().upper()

        # Basic format validation (alphanumeric + $ for indexes)
        if not all(c.isalnum() or c == '$' for c in symbol):
            raise ValueError(f"Invalid symbol format: {symbol}")

        logger.info(f"Delete request for symbol: {symbol}")

        # Check if symbol has data (unless force mode)
        if not force:
            row_count = (
                self.session.query(MarketData)
                .filter(MarketData.symbol == symbol)
                .count()
            )

            if row_count == 0:
                logger.warning(f"No data found for {symbol}")
                return {
                    'success': True,
                    'symbol': symbol,
                    'rows_deleted': 0,
                    'metadata_deleted': False,
                    'message': f"No data to delete for {symbol}",
                }

        # Delete data in transaction (atomic operation)
        try:
            # Delete market_data rows
            deleted_rows = (
                self.session.query(MarketData)
                .filter(MarketData.symbol == symbol)
                .delete(synchronize_session='fetch')
            )

            # Delete metadata entries
            deleted_metadata = (
                self.session.query(DataMetadata)
                .filter(DataMetadata.symbol == symbol)
                .delete(synchronize_session='fetch')
            )

            # Commit transaction
            self.session.commit()

            # Create audit log
            self._create_audit_log(
                symbol=symbol,
                timeframe='all',
                operation='delete',
                status='success',
                message=f"Deleted {deleted_rows} market_data rows, {deleted_metadata} metadata entries",
                bars_affected=deleted_rows,
            )

            logger.info(
                f"Successfully deleted {deleted_rows} rows and {deleted_metadata} metadata entries for {symbol}"
            )

            return {
                'success': True,
                'symbol': symbol,
                'rows_deleted': deleted_rows,
                'metadata_deleted': deleted_metadata > 0,
                'message': f"Successfully deleted {deleted_rows} bars for {symbol}",
            }

        except Exception as e:
            # Rollback on error
            self.session.rollback()

            logger.error(f"Failed to delete data for {symbol}: {e}")

            # Create error audit log
            self._create_audit_log(
                symbol=symbol,
                timeframe='all',
                operation='delete',
                status='error',
                message=f"Delete failed: {str(e)}",
                bars_affected=0,
            )

            raise
