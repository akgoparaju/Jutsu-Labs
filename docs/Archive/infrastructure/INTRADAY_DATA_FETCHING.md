# Intraday Data Fetching Feature

**Module**: `jutsu_engine.data.handlers.database`
**Class**: `MultiSymbolDataHandler`
**Method**: `get_intraday_bars_for_time_window()`
**Author**: DATABASE_HANDLER_AGENT
**Date**: 2025-11-24
**Status**: ✅ Complete

## Overview

Added intraday data fetching capability to support execution timing analysis for the Hierarchical_Adaptive_v3_5b strategy. This feature allows strategies to fetch bars within specific market hour windows (e.g., first 15 minutes of trading) for analyzing optimal entry/exit timing.

## Implementation

### Method Signature

```python
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

    Args:
        symbol: Stock ticker symbol (e.g., 'QQQ')
        date: Trading date (timezone-naive or aware, will be converted to UTC)
        start_time: Start time in market hours ET (e.g., time(9, 30))
        end_time: End time in market hours ET (e.g., time(9, 45))
        interval: Bar interval ('5m' or '15m')

    Returns:
        List of MarketDataEvent objects for the time window

    Raises:
        ValueError: If interval is not '5m' or '15m'
        ValueError: If symbol not in handler symbols
    """
```

### Key Features

1. **Timezone Handling**:
   - Accepts ET market times (e.g., 9:30 AM)
   - Automatically converts to UTC for database queries
   - Handles timezone-aware and naive datetime inputs

2. **Flexible Time Windows**:
   - Fetch specific intraday periods (e.g., 9:30-9:45 AM)
   - Supports both 5min and 15min intervals
   - Inclusive of start and end times

3. **Multi-Symbol Support**:
   - Works with all symbols in handler (QQQ, TQQQ, PSQ, VIX)
   - Consistent interface across symbols

4. **Performance Optimized**:
   - Query time: 0.6ms - 4ms (well under 10ms target)
   - Efficient database indexing
   - No N+1 query problems

### Example Usage

```python
from datetime import date, time, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jutsu_engine.data.handlers.database import MultiSymbolDataHandler

# Setup database connection
engine = create_engine('sqlite:///data/market_data.db')
Session = sessionmaker(bind=engine)
session = Session()

# Create handler
handler = MultiSymbolDataHandler(
    session=session,
    symbols=['QQQ', 'TQQQ', 'PSQ'],
    timeframe='1D',
    start_date=datetime(2025, 3, 1),
    end_date=datetime(2025, 11, 24)
)

# Fetch first 15 minutes of trading (9:30-9:45 AM ET)
bars = handler.get_intraday_bars_for_time_window(
    symbol='QQQ',
    date=date(2025, 3, 10),
    start_time=time(9, 30),
    end_time=time(9, 45),
    interval='5m'
)

# Results: 4 bars (9:30, 9:35, 9:40, 9:45)
for bar in bars:
    print(f"{bar.timestamp}: ${bar.close}")
```

## Testing

### Test Coverage

**File**: `tests/unit/infrastructure/test_intraday_data_handler.py`
**Tests**: 14 comprehensive tests
**Coverage**: 100% for new method
**Status**: ✅ All tests passing

### Test Scenarios

1. **Basic Functionality**:
   - ✅ Fetch specific time windows
   - ✅ First 15 minutes of trading
   - ✅ Full hour fetch
   - ✅ Single bar fetch

2. **Timezone Handling**:
   - ✅ ET to UTC conversion accuracy
   - ✅ Naive and aware datetime inputs
   - ✅ DST handling (EDT vs EST)

3. **Multi-Symbol Support**:
   - ✅ QQQ 5min data
   - ✅ TQQQ 5min data
   - ✅ PSQ 15min data

4. **Edge Cases**:
   - ✅ No data for time window
   - ✅ Weekend date (market closed)
   - ✅ Invalid symbol handling
   - ✅ Invalid interval handling

5. **Data Quality**:
   - ✅ Chronological ordering
   - ✅ OHLC data validation
   - ✅ Decimal precision preserved
   - ✅ No gaps in time series

6. **Performance**:
   - ✅ Query time <10ms (target met)
   - ✅ Efficient database indexing
   - ✅ No memory issues

## Performance Validation

**Script**: `scripts/validate_intraday_performance.py`

### Results

| Test Case | Bars Fetched | Query Time | Status |
|-----------|--------------|------------|--------|
| First 15 min (QQQ 5m) | 4 | 4.09 ms | ✅ PASS |
| Full hour (QQQ 5m) | 13 | 0.62 ms | ✅ PASS |
| TQQQ first 15 min | 4 | 0.85 ms | ✅ PASS |
| PSQ 15min interval | 5 | 1.07 ms | ✅ PASS |
| Recent date (2025-11-24) | 4 | 0.98 ms | ✅ PASS |

**Performance Target**: <10ms ✅ **ACHIEVED**
**Average Query Time**: ~1.5ms
**Peak Query Time**: 4.09ms

## Database Support

### Supported Intervals
- `5m` - 5-minute bars
- `15m` - 15-minute bars

### Supported Symbols
- QQQ: 14,118 bars of 5min data, 4,706 bars of 15min data
- TQQQ: 14,118 bars of 5min data, 4,706 bars of 15min data
- PSQ: 4,703 bars of 15min data
- VIX: Daily data only (no intraday)

### Date Range
- **Start Date**: 2025-03-10
- **End Date**: 2025-11-24
- **Total**: 189-191 trading days

## Timezone Reference

### ET to UTC Conversion

**Eastern Daylight Time (EDT)** - March to November:
- 9:30 AM ET = 13:30 UTC
- 4:00 PM ET = 20:00 UTC

**Eastern Standard Time (EST)** - November to March:
- 9:30 AM ET = 14:30 UTC
- 4:00 PM ET = 21:00 UTC

The method automatically handles DST transitions using Python's `zoneinfo` module.

## Use Case: Strategy Execution Timing

### Hierarchical_Adaptive_v3_5b Strategy

This feature enables the strategy to:

1. **Analyze entry timing**: Compare performance of entries at different times:
   - First 15 minutes (9:30-9:45 AM)
   - First hour (9:30-10:30 AM)
   - Morning session (9:30 AM - 12:00 PM)
   - Afternoon session (12:00 PM - 4:00 PM)

2. **Optimize execution**:
   - Identify optimal entry windows
   - Avoid low-liquidity periods
   - Reduce slippage costs

3. **Risk management**:
   - Exit positions during volatile opening minutes
   - Implement time-based stops

### Example: First 15 Minutes Analysis

```python
# Fetch first 15 minutes for analysis
opening_bars = handler.get_intraday_bars_for_time_window(
    symbol='QQQ',
    date=trade_date,
    start_time=time(9, 30),
    end_time=time(9, 45),
    interval='5m'
)

# Calculate opening volatility
opening_range = max(bar.high for bar in opening_bars) - min(bar.low for bar in opening_bars)
opening_volume = sum(bar.volume for bar in opening_bars)

# Decision: Enter trade if volatility is manageable
if opening_range < threshold and opening_volume > min_volume:
    strategy.enter_long()
```

## Integration Points

### Current Integration
- **Module**: `jutsu_engine.data.handlers.database.MultiSymbolDataHandler`
- **Used By**: Strategy execution timing analysis
- **Dependencies**: SQLAlchemy, zoneinfo

### Future Integration
- **Hierarchical_Adaptive_v3_5b**: Primary consumer
- **Execution timing optimizer**: Performance analysis
- **Slippage calculator**: Time-based slippage models

## Known Limitations

1. **Interval Support**: Currently only 5min and 15min intervals
   - Future: Add 1min, 30min, 1H support

2. **VIX Data**: No intraday VIX data available
   - VIX is an index, calculated once per day

3. **Data Availability**: Limited to data in database
   - Date range: 2025-03-10 to 2025-11-24
   - Missing data returns empty list with warning

4. **Timezone Assumption**: Assumes ET market hours
   - All US equity markets (NYSE, NASDAQ)
   - Not suitable for international markets

## Error Handling

### Validation Errors

```python
# Invalid symbol
ValueError: "Requested symbol AAPL not in handler symbols ['QQQ', 'TQQQ', 'PSQ']"

# Invalid interval
ValueError: "Interval must be '5m' or '15m', got: 1H"
```

### Data Warnings

```python
# No data found
logger.warning("No 5m bars found for QQQ on 2025-03-08 between 09:30:00 and 09:45:00 ET")
# Returns: []
```

### Logging

```python
# Debug: Query details
logger.debug("Fetching QQQ 5m bars for 2025-03-10 ET 09:30:00-09:45:00 (UTC 13:30:00-13:45:00)")

# Info: Success
logger.info("Retrieved 4 5m bars for QQQ on 2025-03-10 ET 09:30:00-09:45:00")

# Warning: No data
logger.warning("No 5m bars found for QQQ on 2025-03-08 between 09:30:00 and 09:45:00 ET")
```

## Dependencies

```python
# Core Python
from datetime import datetime, date, time
from typing import List
from zoneinfo import ZoneInfo

# SQLAlchemy
from sqlalchemy import and_
from sqlalchemy.orm import Session

# Jutsu Engine
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.data.models import MarketData
```

## Future Enhancements

### Phase 2: Additional Intervals
- 1min bars for high-frequency analysis
- 30min bars for swing trading
- 1H bars for position trading

### Phase 3: Advanced Features
- Time-weighted average price (TWAP) calculation
- Volume-weighted average price (VWAP) calculation
- Intraday volatility metrics
- Liquidity analysis

### Phase 4: Optimization
- Caching for frequently accessed time windows
- Batch fetching for multiple dates
- Parallel queries for multiple symbols

## References

- Database schema: `jutsu_engine/data/models.py`
- Database handler: `jutsu_engine/data/handlers/database.py`
- Unit tests: `tests/unit/infrastructure/test_intraday_data_handler.py`
- Performance validation: `scripts/validate_intraday_performance.py`
- Agent context: `.claude/layers/infrastructure/modules/DATABASE_HANDLER_AGENT.md`

## Change History

| Date | Author | Change |
|------|--------|--------|
| 2025-11-24 | DATABASE_HANDLER_AGENT | Initial implementation |
| 2025-11-24 | DATABASE_HANDLER_AGENT | Added comprehensive tests (14 tests) |
| 2025-11-24 | DATABASE_HANDLER_AGENT | Performance validation (0.6-4ms query time) |
| 2025-11-24 | DATABASE_HANDLER_AGENT | Documentation complete |

---

**Status**: ✅ **PRODUCTION READY**

All success criteria met:
- ✅ Method implemented with full type hints and docstring
- ✅ 14 comprehensive tests passing (100% coverage)
- ✅ Performance validated (<10ms target met with ~1.5ms avg)
- ✅ Works with all required symbols (QQQ, TQQQ, PSQ)
- ✅ Timezone handling correct (ET to UTC conversion)
- ✅ Multi-symbol support verified
- ✅ Edge cases handled (no data, invalid inputs)
- ✅ Data quality validated (OHLC relationships, decimal precision)
- ✅ Documentation complete
