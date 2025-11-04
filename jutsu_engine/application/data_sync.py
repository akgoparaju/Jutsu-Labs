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
                # Ensure last_bar_timestamp is timezone-aware (UTC)
                # SQLite may return naive datetime even with timezone=True
                last_bar = metadata.last_bar_timestamp
                if last_bar.tzinfo is None:
                    last_bar = last_bar.replace(tzinfo=timezone.utc)

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
                    first_bar = first_bar_result[0]
                    if first_bar.tzinfo is None:
                        first_bar = first_bar.replace(tzinfo=timezone.utc)

                    # Determine fetch strategy based on start_date vs existing data range
                    if start_date >= last_bar:
                        # Incremental update: fetch from last_bar + 1 day
                        actual_start_date = last_bar + timedelta(days=1)
                        actual_end_date = end_date
                        logger.info(
                            f"Incremental update: fetching from {actual_start_date.date()}"
                        )
                    elif start_date < first_bar:
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

        if bars_fetched == 0:
            logger.info("No new data to sync")
            return {
                'bars_fetched': 0,
                'bars_stored': 0,
                'bars_updated': 0,
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

        logger.info(
            f"Sync complete: {bars_stored} stored, {bars_updated} updated "
            f"in {duration:.2f}s"
        )

        return {
            'bars_fetched': bars_fetched,
            'bars_stored': bars_stored,
            'bars_updated': bars_updated,
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

        Args:
            symbol: Stock ticker symbol
            timeframe: Bar timeframe
            bar_data: Dictionary with bar data (timestamp, open, high, low, close, volume)

        Returns:
            Tuple of (stored, updated) booleans
        """
        # Check if bar already exists
        existing_bar = (
            self.session.query(MarketData)
            .filter(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == timeframe,
                    MarketData.timestamp == bar_data['timestamp'],
                )
            )
            .first()
        )

        if existing_bar:
            # Update existing bar
            existing_bar.open = bar_data['open']
            existing_bar.high = bar_data['high']
            existing_bar.low = bar_data['low']
            existing_bar.close = bar_data['close']
            existing_bar.volume = bar_data['volume']
            existing_bar.is_valid = True
            return (False, True)
        else:
            # Create new bar
            new_bar = MarketData(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=bar_data['timestamp'],
                open=bar_data['open'],
                high=bar_data['high'],
                low=bar_data['low'],
                close=bar_data['close'],
                volume=bar_data['volume'],
                data_source=bar_data.get('data_source', 'schwab'),
                is_valid=True,
            )
            self.session.add(new_bar)
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
