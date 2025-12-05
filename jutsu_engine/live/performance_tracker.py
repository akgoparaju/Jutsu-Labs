"""
Performance Tracker - Daily portfolio snapshots and performance metrics.

This module captures end-of-day portfolio state and calculates
performance metrics for live trading tracking and analysis.

Version: 2.0 (PRD v2.0.1 Compliant)
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, time
from sqlalchemy.orm import Session
from sqlalchemy import desc

from jutsu_engine.data.models import PerformanceSnapshot
from jutsu_engine.live.mode import TradingMode

logger = logging.getLogger('LIVE.PERFORMANCE_TRACKER')


# Default snapshot time: 16:05 ET (5 minutes after close)
SNAPSHOT_TIME = time(16, 5)


class PerformanceTracker:
    """
    Track portfolio performance with daily snapshots.

    Records end-of-day portfolio metrics to database for performance
    analysis and dashboards. Calculates daily return, cumulative return,
    and drawdown against high water mark.

    Features:
        - Daily snapshot at 16:05 ET
        - Separate tracking for offline/online modes
        - High water mark tracking for drawdown
        - Strategy context capture (cell, trend_state, vol_state)

    Usage:
        tracker = PerformanceTracker(session, mode=TradingMode.OFFLINE_MOCK)

        # Record daily snapshot
        tracker.record_snapshot(
            total_equity=Decimal('100000.00'),
            cash=Decimal('50000.00'),
            positions_value=Decimal('50000.00'),
            strategy_context={'current_cell': 1, 'trend_state': 'BullStrong', 'vol_state': 'Low'}
        )

        # Get performance history
        history = tracker.get_performance_history(days=30)
    """

    def __init__(
        self,
        session: Session,
        mode: TradingMode,
        initial_capital: Optional[Decimal] = None
    ):
        """
        Initialize performance tracker.

        Args:
            session: SQLAlchemy database session
            mode: Trading mode (OFFLINE_MOCK or ONLINE_LIVE)
            initial_capital: Starting capital for cumulative return calculation.
                            If None, uses first recorded equity as baseline.
        """
        self.session = session
        self.mode = mode
        self.initial_capital = initial_capital
        self._high_water_mark: Optional[Decimal] = None

        # Load initial state from existing snapshots
        self._load_initial_state()

        logger.info(
            f"PerformanceTracker initialized: mode={mode.value}, "
            f"initial_capital={initial_capital}, hwm={self._high_water_mark}"
        )

    def _load_initial_state(self) -> None:
        """
        Load high water mark and baseline from existing snapshots.

        Queries database for previous snapshots to initialize tracking state.
        """
        # Get most recent snapshot for this mode
        latest = self.get_latest_snapshot()

        if latest:
            # Set high water mark to max equity seen
            all_snapshots = self.get_performance_history(days=3650)  # ~10 years
            if all_snapshots:
                self._high_water_mark = max(s.total_equity for s in all_snapshots)
                logger.debug(f"Loaded high water mark: {self._high_water_mark}")

            # If no initial capital set, use first snapshot's equity
            if self.initial_capital is None:
                oldest = min(all_snapshots, key=lambda s: s.timestamp) if all_snapshots else None
                if oldest:
                    self.initial_capital = oldest.total_equity
                    logger.debug(f"Set initial capital from oldest snapshot: {self.initial_capital}")

    def record_snapshot(
        self,
        total_equity: Decimal,
        cash: Decimal,
        positions_value: Decimal,
        strategy_context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> PerformanceSnapshot:
        """
        Record a performance snapshot to the database.

        Captures current portfolio state and calculates performance metrics.
        Creates a unique snapshot per day per mode (existing snapshot updated).

        Args:
            total_equity: Total portfolio value (cash + positions)
            cash: Available cash balance
            positions_value: Total value of open positions
            strategy_context: Optional strategy state dict with keys:
                - current_cell: Regime cell (1-6)
                - trend_state: BullStrong, Sideways, BearStrong
                - vol_state: Low, High
            timestamp: Optional snapshot timestamp (defaults to now UTC)

        Returns:
            Created or updated PerformanceSnapshot object
        """
        ts = timestamp or datetime.now(timezone.utc)
        context = strategy_context or {}

        # Calculate metrics
        daily_return = self._calculate_daily_return(total_equity)
        cumulative_return = self._calculate_cumulative_return(total_equity)
        drawdown = self._calculate_drawdown(total_equity)

        # Update high water mark
        if self._high_water_mark is None or total_equity > self._high_water_mark:
            self._high_water_mark = total_equity
            logger.debug(f"New high water mark: {self._high_water_mark}")

        # Check for existing snapshot at same date/mode
        existing = self._get_snapshot_for_date(ts)

        if existing:
            # Update existing snapshot
            existing.total_equity = total_equity
            existing.cash = cash
            existing.positions_value = positions_value
            existing.daily_return = daily_return
            existing.cumulative_return = cumulative_return
            existing.drawdown = drawdown
            existing.strategy_cell = context.get('current_cell')
            existing.trend_state = context.get('trend_state')
            existing.vol_state = context.get('vol_state')

            self.session.commit()
            logger.info(f"Updated snapshot: equity={total_equity}, return={daily_return}%")
            return existing

        # Create new snapshot
        snapshot = PerformanceSnapshot(
            timestamp=ts,
            mode=self.mode.db_value,
            total_equity=total_equity,
            cash=cash,
            positions_value=positions_value,
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            drawdown=drawdown,
            strategy_cell=context.get('current_cell'),
            trend_state=context.get('trend_state'),
            vol_state=context.get('vol_state'),
        )

        self.session.add(snapshot)
        self.session.commit()

        logger.info(
            f"Recorded snapshot: equity={total_equity}, "
            f"daily={daily_return:.4f}%, cum={cumulative_return:.4f}%, "
            f"dd={drawdown:.4f}%"
        )

        return snapshot

    def _calculate_daily_return(self, current_equity: Decimal) -> Decimal:
        """
        Calculate day-over-day return percentage.

        Args:
            current_equity: Current total equity

        Returns:
            Daily return as percentage (e.g., 1.5 for 1.5%)
        """
        previous = self.get_latest_snapshot()

        if previous is None or previous.total_equity == 0:
            return Decimal('0')

        prev_equity = Decimal(str(previous.total_equity))
        return ((current_equity - prev_equity) / prev_equity) * Decimal('100')

    def _calculate_cumulative_return(self, current_equity: Decimal) -> Decimal:
        """
        Calculate total return since inception percentage.

        Args:
            current_equity: Current total equity

        Returns:
            Cumulative return as percentage (e.g., 25.5 for 25.5%)
        """
        if self.initial_capital is None or self.initial_capital == 0:
            # Set initial capital from current if not set
            if self.initial_capital is None:
                self.initial_capital = current_equity
            return Decimal('0')

        return ((current_equity - self.initial_capital) / self.initial_capital) * Decimal('100')

    def _calculate_drawdown(self, current_equity: Decimal) -> Decimal:
        """
        Calculate current drawdown from high water mark.

        Drawdown is expressed as a negative percentage from peak.

        Args:
            current_equity: Current total equity

        Returns:
            Drawdown as percentage (e.g., -5.2 for 5.2% down from peak)
        """
        if self._high_water_mark is None:
            self._high_water_mark = current_equity
            return Decimal('0')

        if self._high_water_mark == 0:
            return Decimal('0')

        hwm = self._high_water_mark
        if current_equity >= hwm:
            return Decimal('0')

        return ((current_equity - hwm) / hwm) * Decimal('100')

    def _get_snapshot_for_date(self, ts: datetime) -> Optional[PerformanceSnapshot]:
        """
        Get existing snapshot for a specific date and mode.

        Args:
            ts: Timestamp to check

        Returns:
            Existing snapshot or None
        """
        # Match by date (ignore time) and mode
        date_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = ts.replace(hour=23, minute=59, second=59, microsecond=999999)

        return self.session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.mode == self.mode.db_value,
            PerformanceSnapshot.timestamp >= date_start,
            PerformanceSnapshot.timestamp <= date_end
        ).first()

    def get_latest_snapshot(self) -> Optional[PerformanceSnapshot]:
        """
        Get the most recent performance snapshot for this mode.

        Returns:
            Latest PerformanceSnapshot or None if no snapshots exist
        """
        return self.session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.mode == self.mode.db_value
        ).order_by(desc(PerformanceSnapshot.timestamp)).first()

    def get_performance_history(
        self,
        days: int = 30,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[PerformanceSnapshot]:
        """
        Get historical performance snapshots.

        Args:
            days: Number of days to look back (ignored if dates provided)
            start_date: Optional start of date range
            end_date: Optional end of date range

        Returns:
            List of PerformanceSnapshot objects, oldest first
        """
        query = self.session.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.mode == self.mode.db_value
        )

        if start_date:
            query = query.filter(PerformanceSnapshot.timestamp >= start_date)
        elif not end_date:
            # Use days lookback
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.filter(PerformanceSnapshot.timestamp >= cutoff)

        if end_date:
            query = query.filter(PerformanceSnapshot.timestamp <= end_date)

        return query.order_by(PerformanceSnapshot.timestamp).all()

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get summary of key performance metrics.

        Returns:
            Dictionary with summary metrics:
                - total_days: Number of days tracked
                - total_return: Cumulative return %
                - max_drawdown: Maximum drawdown seen %
                - avg_daily_return: Average daily return %
                - current_equity: Latest equity value
                - high_water_mark: Peak equity value
        """
        history = self.get_performance_history(days=3650)  # All history

        if not history:
            return {
                'total_days': 0,
                'total_return': Decimal('0'),
                'max_drawdown': Decimal('0'),
                'avg_daily_return': Decimal('0'),
                'current_equity': self.initial_capital or Decimal('0'),
                'high_water_mark': self.initial_capital or Decimal('0'),
            }

        latest = history[-1]
        daily_returns = [s.daily_return or Decimal('0') for s in history]
        drawdowns = [s.drawdown or Decimal('0') for s in history]

        return {
            'total_days': len(history),
            'total_return': latest.cumulative_return or Decimal('0'),
            'max_drawdown': min(drawdowns),  # Most negative
            'avg_daily_return': sum(daily_returns) / len(daily_returns) if daily_returns else Decimal('0'),
            'current_equity': latest.total_equity,
            'high_water_mark': self._high_water_mark or latest.total_equity,
        }

    def is_snapshot_time(self, current_time: Optional[time] = None) -> bool:
        """
        Check if current time is snapshot time (16:05 ET).

        Args:
            current_time: Time to check (defaults to now)

        Returns:
            True if within snapshot window (16:05-16:10 ET)
        """
        if current_time is None:
            from zoneinfo import ZoneInfo
            et = ZoneInfo('America/New_York')
            current_time = datetime.now(et).time()

        # Snapshot window: 16:05 to 16:10 ET
        snapshot_start = SNAPSHOT_TIME
        snapshot_end = time(16, 10)

        return snapshot_start <= current_time <= snapshot_end


def main():
    """Test PerformanceTracker."""
    logging.basicConfig(level=logging.INFO)

    print("\n>>> PerformanceTracker Test")
    print("This module requires database session.")
    print("\nCore functionality:")
    print("  - Records daily portfolio snapshots")
    print("  - Calculates daily return, cumulative return, drawdown")
    print("  - Tracks high water mark")
    print("  - Supports offline/online mode separation")
    print("\nSnapshot time: 16:05 ET (5 min after close)")


if __name__ == "__main__":
    main()
