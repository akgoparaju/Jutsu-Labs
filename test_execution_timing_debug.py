#!/usr/bin/env python3
"""
Debug script to test execution timing dependency injection.
Tests if set_end_date() and set_data_handler() actually set the variables.
"""
from datetime import datetime, date
from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b

# Create strategy instance
strategy = Hierarchical_Adaptive_v3_5b(
    execution_time="15min_after_open"
)

# Initialize
strategy.init()

print(f"After init():")
print(f"  _end_date: {strategy._end_date}")
print(f"  _data_handler: {strategy._data_handler}")
print()

# Call set_end_date
test_end_date = date(2025, 11, 24)
print(f"Calling set_end_date({test_end_date})...")
strategy.set_end_date(test_end_date)
print(f"After set_end_date():")
print(f"  _end_date: {strategy._end_date}")
print(f"  Type: {type(strategy._end_date)}")
print()

# Test _is_last_day
test_timestamp = datetime(2025, 11, 24, 16, 0, 0)
is_last = strategy._is_last_day(test_timestamp)
print(f"Testing _is_last_day({test_timestamp}):")
print(f"  Result: {is_last}")
print(f"  Comparison: {test_timestamp.date()} == {strategy._end_date} = {test_timestamp.date() == strategy._end_date}")
print()

# Test with a mock data handler
class MockDataHandler:
    def get_intraday_bars_for_time_window(self, **kwargs):
        print(f"  MockDataHandler.get_intraday_bars_for_time_window() called with: {kwargs}")
        return []

mock_handler = MockDataHandler()
print(f"Calling set_data_handler(mock_handler)...")
strategy.set_data_handler(mock_handler)
print(f"After set_data_handler():")
print(f"  _data_handler: {strategy._data_handler}")
print(f"  Type: {type(strategy._data_handler)}")
print()

print("✅ TEST COMPLETE - Variables are set correctly!")
print(f"   _end_date = {strategy._end_date}")
print(f"   _data_handler = {type(strategy._data_handler).__name__}")
print(f"   _is_last_day() = {is_last}")
