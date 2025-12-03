"""
Market Calendar Module

Purpose:
    Trading day validation using NYSE calendar.
    Identifies weekends, holidays, and market closures.

Dependencies:
    - pandas-market-calendars>=4.0.0

Usage:
    from jutsu_engine.live.market_calendar import is_trading_day

    if is_trading_day():
        # Execute trading logic
        pass
    else:
        # Market closed
        pass
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

import pandas_market_calendars as mcal

logger = logging.getLogger('LIVE.MARKET_CALENDAR')


def is_trading_day(check_date: Optional[date] = None) -> bool:
    """
    Check if given date is a trading day on NYSE.

    Args:
        check_date: Date to check (default: today in UTC)

    Returns:
        True if trading day, False if weekend/holiday

    Examples:
        >>> is_trading_day(date(2025, 11, 28))  # Thanksgiving
        False
        >>> is_trading_day(date(2025, 12, 25))  # Christmas
        False
        >>> is_trading_day(date(2025, 11, 24))  # Monday
        True
    """
    if check_date is None:
        check_date = datetime.now(timezone.utc).date()

    logger.debug(f"Checking if {check_date} is a trading day")

    # Load NYSE calendar
    nyse = mcal.get_calendar('NYSE')

    # Get trading days for the month containing check_date
    # (Use month range to avoid edge cases)
    start_date = check_date.replace(day=1)
    if check_date.month == 12:
        end_date = check_date.replace(year=check_date.year + 1, month=1, day=1)
    else:
        end_date = check_date.replace(month=check_date.month + 1, day=1)

    # Get valid trading days
    schedule = nyse.schedule(start_date=start_date, end_date=end_date)

    # Check if check_date is in trading days
    trading_dates = schedule.index.date
    is_trading = check_date in trading_dates

    if is_trading:
        logger.info(f"✅ {check_date} is a trading day")
    else:
        logger.info(f"❌ {check_date} is NOT a trading day (weekend/holiday)")

    return is_trading


def get_next_trading_day(check_date: Optional[date] = None) -> date:
    """
    Get next trading day after given date.

    Args:
        check_date: Starting date (default: today)

    Returns:
        Next trading day

    Examples:
        >>> get_next_trading_day(date(2025, 11, 27))  # Thanksgiving (Thu)
        date(2025, 11, 29)  # Black Friday
    """
    if check_date is None:
        check_date = datetime.now(timezone.utc).date()

    logger.debug(f"Finding next trading day after {check_date}")

    nyse = mcal.get_calendar('NYSE')

    # Get schedule for next 30 days
    start_date = check_date
    end_date = start_date + pd.Timedelta(days=30)

    schedule = nyse.schedule(start_date=start_date, end_date=end_date)

    # Find first trading day AFTER check_date
    trading_dates = schedule.index.date
    future_dates = [d for d in trading_dates if d > check_date]

    if not future_dates:
        raise ValueError(f"No trading day found in next 30 days after {check_date}")

    next_trading = future_dates[0]
    logger.info(f"Next trading day after {check_date}: {next_trading}")

    return next_trading


def get_previous_trading_day(check_date: Optional[date] = None) -> date:
    """
    Get previous trading day before given date.

    Args:
        check_date: Starting date (default: today)

    Returns:
        Previous trading day

    Examples:
        >>> get_previous_trading_day(date(2025, 11, 29))  # Day after Thanksgiving
        date(2025, 11, 26)  # Wednesday before Thanksgiving
    """
    if check_date is None:
        check_date = datetime.now(timezone.utc).date()

    logger.debug(f"Finding previous trading day before {check_date}")

    nyse = mcal.get_calendar('NYSE')

    # Get schedule for previous 30 days
    end_date = check_date
    start_date = end_date - pd.Timedelta(days=30)

    schedule = nyse.schedule(start_date=start_date, end_date=end_date)

    # Find last trading day BEFORE check_date
    trading_dates = schedule.index.date
    past_dates = [d for d in trading_dates if d < check_date]

    if not past_dates:
        raise ValueError(f"No trading day found in previous 30 days before {check_date}")

    previous_trading = past_dates[-1]
    logger.info(f"Previous trading day before {check_date}: {previous_trading}")

    return previous_trading


def is_market_open_now() -> bool:
    """
    Check if market is currently open (9:30-16:00 EST).

    Returns:
        True if market is open right now

    Note:
        Checks both if today is a trading day AND if current time
        is within trading hours (9:30-16:00 EST).
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    # First check if trading day
    if not is_trading_day(today):
        logger.info(f"Market closed: {today} is not a trading day")
        return False

    # Convert UTC to EST
    from datetime import timedelta
    est_offset = timedelta(hours=-5)  # EST is UTC-5
    now_est = now + est_offset
    current_time = now_est.time()

    # Market hours: 9:30-16:00 EST
    market_open = datetime.strptime("09:30", "%H:%M").time()
    market_close = datetime.strptime("16:00", "%H:%M").time()

    is_open = market_open <= current_time <= market_close

    if is_open:
        logger.info(f"✅ Market is OPEN (EST time: {current_time.strftime('%H:%M')})")
    else:
        logger.info(f"❌ Market is CLOSED (EST time: {current_time.strftime('%H:%M')})")

    return is_open


# Import pandas for Timedelta
import pandas as pd


def is_market_hours(check_datetime: Optional[datetime] = None) -> bool:
    """
    Check if given datetime is within US market hours (9:30-16:00 EST/EDT).

    This function checks if a specific datetime falls within trading hours,
    accounting for both EST and EDT (Daylight Saving Time).

    Args:
        check_datetime: Datetime to check (default: now in UTC).
                       Must be timezone-aware.

    Returns:
        True if within market hours (9:30 AM - 4:00 PM Eastern Time)

    Note:
        - Does NOT check if the date is a trading day (use is_trading_day() for that)
        - Handles DST transitions automatically using pytz
        - Market hours are 9:30-16:00 Eastern Time (EST or EDT depending on date)

    Examples:
        >>> # 2025-11-03 14:00 EST (market open)
        >>> is_market_hours(datetime(2025, 11, 3, 19, 0, tzinfo=timezone.utc))
        True
        >>> # 2025-11-03 08:00 EST (before open)
        >>> is_market_hours(datetime(2025, 11, 3, 13, 0, tzinfo=timezone.utc))
        False
        >>> # 2025-11-03 17:00 EST (after close)
        >>> is_market_hours(datetime(2025, 11, 3, 22, 0, tzinfo=timezone.utc))
        False
    """
    if check_datetime is None:
        check_datetime = datetime.now(timezone.utc)
    elif check_datetime.tzinfo is None:
        check_datetime = check_datetime.replace(tzinfo=timezone.utc)

    # Use pytz for proper DST handling
    try:
        import pytz
        eastern = pytz.timezone('US/Eastern')
        dt_eastern = check_datetime.astimezone(eastern)
    except ImportError:
        # Fallback: Use simple UTC-5 offset (EST only, no DST)
        from datetime import timedelta
        est_offset = timedelta(hours=-5)
        dt_eastern = check_datetime + est_offset
        logger.warning("pytz not available, using EST (UTC-5) without DST handling")

    current_time = dt_eastern.time()

    # Market hours: 9:30-16:00 Eastern Time
    market_open = datetime.strptime("09:30", "%H:%M").time()
    market_close = datetime.strptime("16:00", "%H:%M").time()

    is_within_hours = market_open <= current_time < market_close

    logger.debug(
        f"is_market_hours check: {check_datetime} -> Eastern: {dt_eastern.strftime('%H:%M')} "
        f"-> within hours: {is_within_hours}"
    )

    return is_within_hours


def is_daily_bar_complete(bar_date: date) -> bool:
    """
    Check if a daily bar for the given date is complete.

    A daily bar is complete when:
    1. The bar_date is before today, OR
    2. The bar_date is today AND market is closed (after 4 PM Eastern)

    Args:
        bar_date: The date of the daily bar to check

    Returns:
        True if the daily bar is complete and can be safely fetched

    Examples:
        >>> # Yesterday's bar is always complete
        >>> is_daily_bar_complete(date.today() - timedelta(days=1))
        True
        >>> # Today's bar during market hours
        >>> is_daily_bar_complete(date.today())  # Returns False if market is open
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    # Past dates are always complete
    if bar_date < today:
        logger.debug(f"Daily bar for {bar_date} is complete (past date)")
        return True

    # Future dates are never complete (shouldn't happen, but handle gracefully)
    if bar_date > today:
        logger.debug(f"Daily bar for {bar_date} is incomplete (future date)")
        return False

    # Today's date: check if market is currently open
    if not is_trading_day(today):
        # Not a trading day, no daily bar will be generated
        logger.debug(f"Daily bar for {bar_date} is complete (not a trading day)")
        return True

    # It's a trading day - check if market is open
    if is_market_hours(now):
        logger.info(
            f"Daily bar for {bar_date} is INCOMPLETE (market currently open)"
        )
        return False
    else:
        logger.debug(f"Daily bar for {bar_date} is complete (market closed)")
        return True
