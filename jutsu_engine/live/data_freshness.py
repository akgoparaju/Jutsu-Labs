"""
Data Freshness Checker Module

Purpose:
    Validates that local database has up-to-date market data before live trading
    execution. Triggers automatic sync if data is stale.

PRD Compliance:
    - Runs at 15:44 EST (5 minutes before 15:49 execution)
    - Checks all required symbols (QQQ, TLT, TQQQ, PSQ, TMF, TMV)
    - Triggers `jutsu sync --all` if any symbol is stale
    - Logs freshness status for audit trail

Usage:
    from jutsu_engine.live.data_freshness import DataFreshnessChecker

    checker = DataFreshnessChecker(db_path='data/market_data.db')
    is_fresh, stale_symbols = checker.check_freshness(['QQQ', 'TLT'])
    if not is_fresh:
        checker.trigger_sync()
"""

import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.data.models import DataMetadata, MarketData
from jutsu_engine.live.market_calendar import get_previous_trading_day, is_trading_day

logger = logging.getLogger('LIVE.DATA_FRESHNESS')


class DataFreshnessError(Exception):
    """Raised when data freshness check fails critically."""
    pass


class SyncError(Exception):
    """Raised when data sync fails."""
    pass


class DataFreshnessChecker:
    """
    Validates local database has fresh market data for live trading.

    Freshness Definition:
        Data is "fresh" if last_bar_timestamp >= previous trading day.
        For execution at 15:44 EST on Monday, data is fresh if we have
        Friday's EOD bar (or latest trading day if holiday).

    Attributes:
        db_path: Path to SQLite database
        timeframe: Bar timeframe to check (default '1D')
        required_symbols: List of symbols that must be fresh
    """

    # Default symbols required for Hierarchical_Adaptive_v3_5b strategy
    DEFAULT_REQUIRED_SYMBOLS = ['QQQ', 'TLT', 'TQQQ', 'PSQ', 'TMF', 'TMV']

    def __init__(
        self,
        db_path: str = 'data/market_data.db',
        timeframe: str = '1D',
        required_symbols: Optional[List[str]] = None
    ):
        """
        Initialize DataFreshnessChecker.

        Args:
            db_path: Path to SQLite database
            timeframe: Bar timeframe to check
            required_symbols: Symbols that must be fresh (default: strategy universe)
        """
        self.db_path = Path(db_path)
        self.timeframe = timeframe
        self.required_symbols = required_symbols or self.DEFAULT_REQUIRED_SYMBOLS

        # Initialize database connection
        if not self.db_path.exists():
            raise DataFreshnessError(f"Database not found: {self.db_path}")

        engine = create_engine(f'sqlite:///{self.db_path}')
        Session = sessionmaker(bind=engine)
        self.session = Session()

        logger.info(f"DataFreshnessChecker initialized: db={self.db_path}, symbols={self.required_symbols}")

    def get_expected_last_bar_date(self) -> datetime:
        """
        Get the expected date of the most recent bar.

        For a check running during market hours (e.g., 15:44 EST):
        - Should have yesterday's (or last trading day's) EOD bar

        Returns:
            Expected last bar date (midnight UTC of last trading day)
        """
        today = datetime.now(timezone.utc).date()

        # Get previous trading day (handles weekends and holidays)
        prev_trading_day = get_previous_trading_day(today)

        # Return as timezone-aware datetime at midnight UTC
        expected_date = datetime.combine(prev_trading_day, datetime.min.time())
        expected_date = expected_date.replace(tzinfo=timezone.utc)

        logger.debug(f"Expected last bar date: {expected_date.date()}")
        return expected_date

    def get_symbol_freshness(self, symbol: str) -> Dict[str, Any]:
        """
        Get freshness status for a single symbol.

        Args:
            symbol: Ticker symbol to check

        Returns:
            Dictionary with:
            - symbol: The symbol checked
            - is_fresh: Whether data is up-to-date
            - last_bar_date: Date of most recent bar (or None)
            - expected_date: Expected date of most recent bar
            - days_stale: Number of trading days behind (0 if fresh)
        """
        expected_date = self.get_expected_last_bar_date()

        # Query metadata for this symbol
        metadata = self.session.query(DataMetadata).filter(
            DataMetadata.symbol == symbol,
            DataMetadata.timeframe == self.timeframe
        ).first()

        if not metadata or not metadata.last_bar_timestamp:
            logger.warning(f"{symbol}: No data found in database")
            return {
                'symbol': symbol,
                'is_fresh': False,
                'last_bar_date': None,
                'expected_date': expected_date.date(),
                'days_stale': None,  # Unknown
                'reason': 'no_data'
            }

        last_bar_date = metadata.last_bar_timestamp

        # Ensure timezone-aware
        if last_bar_date.tzinfo is None:
            last_bar_date = last_bar_date.replace(tzinfo=timezone.utc)

        # Compare dates (not times)
        is_fresh = last_bar_date.date() >= expected_date.date()

        # Calculate days stale (approximate, not accounting for holidays)
        days_diff = (expected_date.date() - last_bar_date.date()).days
        days_stale = max(0, days_diff)

        status = {
            'symbol': symbol,
            'is_fresh': is_fresh,
            'last_bar_date': last_bar_date.date(),
            'expected_date': expected_date.date(),
            'days_stale': days_stale,
            'total_bars': metadata.total_bars,
            'reason': 'fresh' if is_fresh else 'stale'
        }

        if is_fresh:
            logger.info(f"{symbol}: FRESH (last bar: {last_bar_date.date()})")
        else:
            logger.warning(f"{symbol}: STALE (last bar: {last_bar_date.date()}, expected: {expected_date.date()})")

        return status

    def check_freshness(
        self,
        symbols: Optional[List[str]] = None
    ) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
        """
        Check if all required symbols have fresh data.

        Args:
            symbols: List of symbols to check (default: required_symbols)

        Returns:
            Tuple of:
            - all_fresh: True if ALL symbols are fresh
            - stale_symbols: List of symbols that are stale
            - details: Full status details for each symbol
        """
        symbols = symbols or self.required_symbols

        logger.info(f"Checking data freshness for {len(symbols)} symbols: {symbols}")

        all_fresh = True
        stale_symbols = []
        details = []

        for symbol in symbols:
            status = self.get_symbol_freshness(symbol)
            details.append(status)

            if not status['is_fresh']:
                all_fresh = False
                stale_symbols.append(symbol)

        # Summary logging
        if all_fresh:
            logger.info(f"All {len(symbols)} symbols have fresh data")
        else:
            logger.warning(f"{len(stale_symbols)}/{len(symbols)} symbols are STALE: {stale_symbols}")

        return all_fresh, stale_symbols, details

    def trigger_sync(
        self,
        symbols: Optional[List[str]] = None,
        timeout_seconds: int = 300
    ) -> bool:
        """
        Trigger data sync via CLI command.

        If symbols provided, syncs only those symbols.
        Otherwise, runs `jutsu sync --all`.

        Args:
            symbols: Specific symbols to sync (None = all)
            timeout_seconds: Maximum time to wait for sync (default 5 min)

        Returns:
            True if sync completed successfully

        Raises:
            SyncError: If sync fails or times out
        """
        if symbols:
            logger.info(f"Triggering sync for specific symbols: {symbols}")
            # Sync each symbol individually
            for symbol in symbols:
                cmd = ['jutsu', 'sync', symbol]
                logger.info(f"Running: {' '.join(cmd)}")

                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds // len(symbols)
                    )

                    if result.returncode != 0:
                        logger.error(f"Sync failed for {symbol}: {result.stderr}")
                        raise SyncError(f"Sync failed for {symbol}: {result.stderr}")

                    logger.info(f"Sync completed for {symbol}")

                except subprocess.TimeoutExpired:
                    raise SyncError(f"Sync timed out for {symbol}")
        else:
            # Sync all symbols
            cmd = ['jutsu', 'sync', '--all']
            logger.info(f"Running: {' '.join(cmd)}")

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds
                )

                if result.returncode != 0:
                    logger.error(f"Sync --all failed: {result.stderr}")
                    raise SyncError(f"Sync --all failed: {result.stderr}")

                logger.info("Sync --all completed successfully")

            except subprocess.TimeoutExpired:
                raise SyncError("Sync --all timed out")

        return True

    def ensure_fresh_data(
        self,
        symbols: Optional[List[str]] = None,
        auto_sync: bool = True
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Ensure all required data is fresh, auto-syncing if needed.

        This is the main entry point for pre-execution checks.

        Args:
            symbols: Symbols to check (default: required_symbols)
            auto_sync: If True, automatically trigger sync for stale data

        Returns:
            Tuple of:
            - success: True if data is fresh (either initially or after sync)
            - details: Status details for each symbol
        """
        symbols = symbols or self.required_symbols

        logger.info("=" * 60)
        logger.info("Pre-Execution Data Freshness Check")
        logger.info("=" * 60)

        # First check
        all_fresh, stale_symbols, details = self.check_freshness(symbols)

        if all_fresh:
            logger.info("Data freshness check PASSED - all symbols up to date")
            return True, details

        if not auto_sync:
            logger.warning("Data freshness check FAILED - auto_sync disabled")
            return False, details

        # Trigger sync for stale symbols
        logger.info(f"Auto-syncing stale symbols: {stale_symbols}")

        try:
            self.trigger_sync(symbols=stale_symbols)
        except SyncError as e:
            logger.error(f"Auto-sync failed: {e}")
            # Re-check after failed sync attempt
            all_fresh, stale_symbols, details = self.check_freshness(symbols)
            return all_fresh, details

        # Re-check after sync
        logger.info("Re-checking freshness after sync...")
        all_fresh, stale_symbols, details = self.check_freshness(symbols)

        if all_fresh:
            logger.info("Data freshness check PASSED after sync")
        else:
            logger.error(f"Data freshness check FAILED even after sync. Still stale: {stale_symbols}")

        return all_fresh, details

    def generate_report(self, details: List[Dict[str, Any]]) -> str:
        """
        Generate a human-readable freshness report.

        Args:
            details: Status details from check_freshness()

        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 60)
        lines.append("DATA FRESHNESS REPORT")
        lines.append(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"{'Symbol':<10} {'Status':<10} {'Last Bar':<12} {'Expected':<12} {'Days Stale':<10}")
        lines.append("-" * 60)

        fresh_count = 0
        stale_count = 0

        for d in details:
            symbol = d['symbol']
            status = "FRESH" if d['is_fresh'] else "STALE"
            last_bar = str(d['last_bar_date']) if d['last_bar_date'] else "N/A"
            expected = str(d['expected_date'])
            days_stale = str(d['days_stale']) if d['days_stale'] is not None else "N/A"

            lines.append(f"{symbol:<10} {status:<10} {last_bar:<12} {expected:<12} {days_stale:<10}")

            if d['is_fresh']:
                fresh_count += 1
            else:
                stale_count += 1

        lines.append("-" * 60)
        lines.append(f"Summary: {fresh_count} fresh, {stale_count} stale")

        if stale_count == 0:
            lines.append("Status: ALL SYSTEMS GO")
        else:
            lines.append("Status: SYNC REQUIRED")

        lines.append("=" * 60)

        return "\n".join(lines)

    def close(self):
        """Close database session."""
        if self.session:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
