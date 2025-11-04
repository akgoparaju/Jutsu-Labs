#!/usr/bin/env python3
"""
Debug script to investigate Schwab API responses.
"""
import os
import json
from datetime import datetime, timezone
from schwab import auth
from schwab.client import Client

# Load credentials
api_key = os.getenv('SCHWAB_API_KEY')
api_secret = os.getenv('SCHWAB_API_SECRET')
callback_url = os.getenv('SCHWAB_CALLBACK_URL', 'https://localhost:8080/callback')
token_path = 'token.json'

# Create client
print("Creating Schwab client...")
client = auth.easy_client(
    api_key=api_key,
    app_secret=api_secret,
    callback_url=callback_url,
    token_path=token_path,
    asyncio=False,
)
print("✅ Client authenticated\n")

# Test 1: Short date range (should work)
print("=" * 80)
print("TEST 1: Short date range (2024-01-01 to 2024-01-05)")
print("=" * 80)
start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
end_date = datetime(2024, 1, 5, tzinfo=timezone.utc)

response = client.get_price_history(
    'AAPL',
    period_type=Client.PriceHistory.PeriodType.YEAR,
    frequency_type=Client.PriceHistory.FrequencyType.DAILY,
    frequency=Client.PriceHistory.Frequency.DAILY,
    start_datetime=start_date,
    end_datetime=end_date,
    need_extended_hours_data=False,
)

print(f"Status code: {response.status_code}")
data = response.json()
print(f"Response keys: {data.keys()}")
print(f"Number of candles: {len(data.get('candles', []))}")
if data.get('candles'):
    print(f"First candle: {data['candles'][0]}")
    print(f"Last candle: {data['candles'][-1]}")
print(f"\nFull response:\n{json.dumps(data, indent=2)}\n")

# Test 2: Long date range (2000-11-01 to 2025-11-03) - like our actual request
print("=" * 80)
print("TEST 2: Long date range (2000-11-01 to 2025-11-03) - 25 years")
print("=" * 80)
start_date_long = datetime(2000, 11, 1, tzinfo=timezone.utc)
end_date_long = datetime(2025, 11, 3, tzinfo=timezone.utc)

response_long = client.get_price_history(
    'AAPL',
    period_type=Client.PriceHistory.PeriodType.YEAR,
    frequency_type=Client.PriceHistory.FrequencyType.DAILY,
    frequency=Client.PriceHistory.Frequency.DAILY,
    start_datetime=start_date_long,
    end_datetime=end_date_long,
    need_extended_hours_data=False,
)

print(f"Status code: {response_long.status_code}")
data_long = response_long.json()
print(f"Response keys: {data_long.keys()}")
print(f"Number of candles: {len(data_long.get('candles', []))}")
print(f"\nFull response:\n{json.dumps(data_long, indent=2)}\n")

# Test 3: Using only period parameter (no start/end dates)
print("=" * 80)
print("TEST 3: Using period parameter only (20 years, no start/end)")
print("=" * 80)
response_period = client.get_price_history(
    'AAPL',
    period_type=Client.PriceHistory.PeriodType.YEAR,
    period=Client.PriceHistory.Period.TWENTY_YEARS,
    frequency_type=Client.PriceHistory.FrequencyType.DAILY,
    frequency=Client.PriceHistory.Frequency.DAILY,
    need_extended_hours_data=False,
)

print(f"Status code: {response_period.status_code}")
data_period = response_period.json()
print(f"Response keys: {data_period.keys()}")
print(f"Number of candles: {len(data_period.get('candles', []))}")
if data_period.get('candles'):
    print(f"Date range: {data_period['candles'][0]['datetime']} to {data_period['candles'][-1]['datetime']}")
print(f"\nFull response (first 500 chars):\n{json.dumps(data_period, indent=2)[:500]}...\n")

# Test 4: Check available Period values
print("=" * 80)
print("TEST 4: Available Schwab API period values")
print("=" * 80)
print("Period types:")
for attr in dir(Client.PriceHistory.PeriodType):
    if not attr.startswith('_'):
        print(f"  - {attr}")

print("\nPeriod values for YEAR:")
for attr in dir(Client.PriceHistory.Period):
    if not attr.startswith('_'):
        print(f"  - {attr}")

print("\nFrequency types:")
for attr in dir(Client.PriceHistory.FrequencyType):
    if not attr.startswith('_'):
        print(f"  - {attr}")

print("\n" + "=" * 80)
print("INVESTIGATION COMPLETE")
print("=" * 80)
