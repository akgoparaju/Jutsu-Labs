"""
Trading Calendar Module for EOD Daily Performance

Purpose:
    NYSE trading calendar integration for end-of-day performance calculations.
    Provides timezone-aware trading day validation, market close times, and
    half-day detection using pandas_market_calendars.

Dependencies:
    - pandas-market-calendars>=4.0.0
    - zoneinfo (Python 3.9+ standard library)

Usage:
    from jutsu_engine.utils.trading_calendar import (
        is_trading_day,
        get_market_close_time,
        get_eod_trigger_time,
        get_trading_days_between,
    )

    # Check if today is a trading day
    if is_trading_day(date.today()):
        close_time = get_market_close_time(date.today())
        eod_time = get_eod_trigger_time(date.today())  # close + 15 min

    # Get trading days for backfill
    days = get_trading_days_between(start_date, end_date)

Note:
    This module is specifically for EOD daily performance calculations.
    For live trading market hours, see jutsu_engine/live/market_calendar.py
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional

import pandas_market_calendars as mcal
from zoneinfo import ZoneInfo

logger = logging.getLogger('UTILS.TRADING_CALENDAR')

# Timezone constants
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Cache NYSE calendar at module level for efficiency
_NYSE_CALENDAR = mcal.get_calendar('NYSE')

# Normal market close time (4:00 PM ET)
NORMAL_CLOSE_TIME = time(16, 0)

# Half-day market close time (1:00 PM ET)
HALF_DAY_CLOSE_TIME = time(13, 0)

# EOD job delay after market close (minutes)
EOD_DELAY_MINUTES = 15


def is_trading_day(target_date: Optional[date] = None) -> bool:
    """
    Check if a date is a trading day on NYSE.

    Args:
        target_date: Date to check (default: today in Eastern Time)

    Returns:
        True if trading day, False if weekend/holiday

    Examples:
        >>> is_trading_day(date(2025, 12, 25))  # Christmas
        False
        >>> is_trading_day(date(2025, 11, 27))  # Thanksgiving
        False
        >>> is_trading_day(date(2025, 11, 24))  # Monday
        True
    """
    if target_date is None:
        target_date = get_trading_date()

    schedule = _NYSE_CALENDAR.schedule(
        start_date=target_date,
        end_date=target_date
    )
    is_trading = len(schedule) > 0

    logger.debug(f"is_trading_day({target_date}): {is_trading}")
    return is_trading


def get_market_close_time(target_date: date) -> Optional[datetime]:
    """
    Get market close time for a given date.

    Handles both normal days (4:00 PM ET) and half-days (1:00 PM ET).
    Uses pandas_market_calendars schedule which correctly identifies
    early close days like the day after Thanksgiving.

    Args:
        target_date: Date to check

    Returns:
        Timezone-aware datetime in ET, or None if not a trading day

    Examples:
        >>> get_market_close_time(date(2025, 11, 28))  # Day after Thanksgiving (half-day)
        datetime(2025, 11, 28, 13, 0, tzinfo=ZoneInfo('America/New_York'))
        >>> get_market_close_time(date(2025, 11, 24))  # Normal Monday
        datetime(2025, 11, 24, 16, 0, tzinfo=ZoneInfo('America/New_York'))
        >>> get_market_close_time(date(2025, 11, 27))  # Thanksgiving (closed)
        None
    """
    schedule = _NYSE_CALENDAR.schedule(
        start_date=target_date,
        end_date=target_date
    )

    if len(schedule) == 0:
        logger.debug(f"get_market_close_time({target_date}): Not a trading day")
        return None

    # market_close is a pandas Timestamp with timezone info
    market_close = schedule.iloc[0]['market_close']

    # Convert to datetime and ensure ET timezone
    close_dt = market_close.to_pydatetime()

    # The schedule returns UTC times, convert to ET
    close_et = close_dt.astimezone(ET)

    logger.debug(f"get_market_close_time({target_date}): {close_et.strftime('%H:%M')} ET")
    return close_et


def is_half_day(target_date: date) -> bool:
    """
    Check if a date is a half-day (early close at 1:00 PM ET).

    Half-days include:
    - Day after Thanksgiving
    - Christmas Eve (when market is open)
    - July 3rd (when July 4th is on weekday)

    Args:
        target_date: Date to check

    Returns:
        True if half-day, False otherwise
    """
    close_time = get_market_close_time(target_date)

    if close_time is None:
        return False

    # Half-day if close is before normal 4 PM
    is_early = close_time.time() < NORMAL_CLOSE_TIME

    if is_early:
        logger.info(f"Half-day detected: {target_date} closes at {close_time.strftime('%H:%M')} ET")

    return is_early


def get_trading_date() -> date:
    """
    Get current trading date in Eastern Time.

    Returns:
        Current date in America/New_York timezone

    Note:
        This is the calendar date, not necessarily a trading day.
        Use is_trading_day() to verify.
    """
    return datetime.now(ET).date()


def get_eod_trigger_time(trading_date: date) -> Optional[datetime]:
    """
    Get EOD job trigger time (market close + 15 minutes).

    The EOD finalization job should run after market close to ensure
    all data is settled. Default delay is 15 minutes.

    Args:
        trading_date: Date to get trigger time for

    Returns:
        Timezone-aware datetime in ET, or None if not a trading day

    Examples:
        >>> get_eod_trigger_time(date(2025, 11, 24))  # Normal day
        datetime(2025, 11, 24, 16, 15, tzinfo=ZoneInfo('America/New_York'))
        >>> get_eod_trigger_time(date(2025, 11, 28))  # Half-day
        datetime(2025, 11, 28, 13, 15, tzinfo=ZoneInfo('America/New_York'))
    """
    close_time = get_market_close_time(trading_date)

    if close_time is None:
        logger.debug(f"get_eod_trigger_time({trading_date}): Not a trading day")
        return None

    trigger_time = close_time + timedelta(minutes=EOD_DELAY_MINUTES)

    logger.debug(f"get_eod_trigger_time({trading_date}): {trigger_time.strftime('%H:%M')} ET")
    return trigger_time


def get_trading_days_between(start: date, end: date) -> List[date]:
    """
    Get all trading days in a date range (inclusive).

    Excludes weekends and NYSE holidays.

    Args:
        start: Start date (inclusive)
        end: End date (inclusive)

    Returns:
        List of trading dates in ascending order

    Examples:
        >>> get_trading_days_between(date(2025, 11, 24), date(2025, 11, 28))
        [date(2025, 11, 24), date(2025, 11, 25), date(2025, 11, 26), date(2025, 11, 28)]
        # Note: Nov 27 (Thanksgiving) is excluded
    """
    schedule = _NYSE_CALENDAR.schedule(start_date=start, end_date=end)

    trading_days = [d.date() for d in schedule.index]

    logger.debug(
        f"get_trading_days_between({start}, {end}): {len(trading_days)} trading days"
    )
    return trading_days


def get_previous_trading_day(check_date: Optional[date] = None) -> date:
    """
    Get previous trading day before given date.

    Args:
        check_date: Starting date (default: today in ET)

    Returns:
        Previous trading day

    Raises:
        ValueError: If no trading day found in previous 30 days

    Examples:
        >>> get_previous_trading_day(date(2025, 11, 28))  # Day after Thanksgiving
        date(2025, 11, 26)  # Wednesday (Thursday was Thanksgiving)
    """
    if check_date is None:
        check_date = get_trading_date()

    # Search previous 30 days
    start_date = check_date - timedelta(days=30)
    end_date = check_date - timedelta(days=1)

    schedule = _NYSE_CALENDAR.schedule(start_date=start_date, end_date=end_date)

    if len(schedule) == 0:
        raise ValueError(f"No trading day found in 30 days before {check_date}")

    # Get the last trading day in the range
    previous = schedule.index[-1].date()

    logger.debug(f"get_previous_trading_day({check_date}): {previous}")
    return previous


def get_next_trading_day(check_date: Optional[date] = None) -> date:
    """
    Get next trading day after given date.

    Args:
        check_date: Starting date (default: today in ET)

    Returns:
        Next trading day

    Raises:
        ValueError: If no trading day found in next 30 days

    Examples:
        >>> get_next_trading_day(date(2025, 11, 26))  # Wednesday before Thanksgiving
        date(2025, 11, 28)  # Friday (Thursday is Thanksgiving)
    """
    if check_date is None:
        check_date = get_trading_date()

    # Search next 30 days
    start_date = check_date + timedelta(days=1)
    end_date = check_date + timedelta(days=30)

    schedule = _NYSE_CALENDAR.schedule(start_date=start_date, end_date=end_date)

    if len(schedule) == 0:
        raise ValueError(f"No trading day found in 30 days after {check_date}")

    # Get the first trading day in the range
    next_day = schedule.index[0].date()

    logger.debug(f"get_next_trading_day({check_date}): {next_day}")
    return next_day


def count_trading_days_between(start: date, end: date) -> int:
    """
    Count trading days between two dates (inclusive).

    Args:
        start: Start date
        end: End date

    Returns:
        Number of trading days

    Examples:
        >>> count_trading_days_between(date(2025, 11, 24), date(2025, 11, 28))
        4  # Mon, Tue, Wed, Fri (Thu is Thanksgiving)
    """
    return len(get_trading_days_between(start, end))


def get_trading_days_in_year(year: int) -> List[date]:
    """
    Get all trading days in a calendar year.

    Args:
        year: Calendar year (e.g., 2025)

    Returns:
        List of all trading dates in the year

    Note:
        Typically ~252 trading days per year.
    """
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    return get_trading_days_between(start, end)


def days_since_last_trading_day(check_date: Optional[date] = None) -> int:
    """
    Calculate calendar days since the previous trading day.

    Useful for detecting data gaps in EOD performance.

    Args:
        check_date: Date to check from (default: today)

    Returns:
        Number of calendar days since previous trading day

    Examples:
        >>> days_since_last_trading_day(date(2025, 11, 28))  # Day after Thanksgiving
        2  # Thursday (holiday) was skipped
        >>> days_since_last_trading_day(date(2025, 11, 25))  # Tuesday
        1  # Monday was the previous trading day
    """
    if check_date is None:
        check_date = get_trading_date()

    prev_trading = get_previous_trading_day(check_date)
    delta = (check_date - prev_trading).days

    logger.debug(
        f"days_since_last_trading_day({check_date}): {delta} days "
        f"(previous trading day: {prev_trading})"
    )
    return delta
