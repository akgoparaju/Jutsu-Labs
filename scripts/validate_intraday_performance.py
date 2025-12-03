"""
Performance validation script for intraday data fetching.

Tests the get_intraday_bars_for_time_window method with real database
to validate <10ms query performance.
"""
from datetime import date, time, datetime
import time as time_module
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.data.handlers.database import MultiSymbolDataHandler

def main():
    # Connect to real database
    engine = create_engine('sqlite:///data/market_data.db')
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create handler
    handler = MultiSymbolDataHandler(
        session=session,
        symbols=['QQQ', 'TQQQ', 'PSQ'],
        timeframe='1D',  # Not used for intraday method
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 11, 24)
    )

    print("Performance Validation: Intraday Data Fetching")
    print("=" * 60)
    print()

    # Test 1: First 15 minutes (9:30-9:45 AM)
    print("Test 1: First 15 minutes (9:30-9:45 AM ET)")
    start = time_module.perf_counter()
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 45),
        interval='5m'
    )
    end = time_module.perf_counter()
    query_time_ms = (end - start) * 1000
    print(f"  Bars fetched: {len(bars)}")
    print(f"  Query time: {query_time_ms:.2f} ms")
    print(f"  Status: {'✅ PASS' if query_time_ms < 10 else '❌ FAIL'} (<10ms target)")
    print()

    # Test 2: Full hour (9:30-10:30 AM)
    print("Test 2: Full hour (9:30-10:30 AM ET)")
    start = time_module.perf_counter()
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(10, 30),
        interval='5m'
    )
    end = time_module.perf_counter()
    query_time_ms = (end - start) * 1000
    print(f"  Bars fetched: {len(bars)}")
    print(f"  Query time: {query_time_ms:.2f} ms")
    print(f"  Status: {'✅ PASS' if query_time_ms < 10 else '❌ FAIL'} (<10ms target)")
    print()

    # Test 3: TQQQ intraday
    print("Test 3: TQQQ first 15 minutes (9:30-9:45 AM ET)")
    start = time_module.perf_counter()
    bars = handler.get_intraday_bars_for_time_window(
        symbol='TQQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 45),
        interval='5m'
    )
    end = time_module.perf_counter()
    query_time_ms = (end - start) * 1000
    print(f"  Bars fetched: {len(bars)}")
    print(f"  Query time: {query_time_ms:.2f} ms")
    print(f"  Status: {'✅ PASS' if query_time_ms < 10 else '❌ FAIL'} (<10ms target)")
    print()

    # Test 4: 15min interval
    print("Test 4: PSQ 15min interval (9:30-10:30 AM ET)")
    start = time_module.perf_counter()
    bars = handler.get_intraday_bars_for_time_window(
        symbol='PSQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(10, 30),
        interval='15m'
    )
    end = time_module.perf_counter()
    query_time_ms = (end - start) * 1000
    print(f"  Bars fetched: {len(bars)}")
    print(f"  Query time: {query_time_ms:.2f} ms")
    print(f"  Status: {'✅ PASS' if query_time_ms < 10 else '❌ FAIL'} (<10ms target)")
    print()

    # Test 5: Recent date
    print("Test 5: Recent date (2025-11-24)")
    start = time_module.perf_counter()
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 11, 24),
        start_time=time(9, 30),
        end_time=time(9, 45),
        interval='5m'
    )
    end = time_module.perf_counter()
    query_time_ms = (end - start) * 1000
    print(f"  Bars fetched: {len(bars)}")
    print(f"  Query time: {query_time_ms:.2f} ms")
    print(f"  Status: {'✅ PASS' if query_time_ms < 10 else '❌ FAIL'} (<10ms target)")
    print()

    print("=" * 60)
    print("Performance validation complete!")

    session.close()

if __name__ == '__main__':
    main()
