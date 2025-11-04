# Schwab API Period Parameter Fix

**Date**: 2025-11-02
**Issue**: Schwab API returning 0 bars for historical data requests
**Resolution**: Added missing `period` parameter to API call

## Root Cause
Missing required `period` parameter in `get_price_history()` API call in `jutsu_engine/data/fetchers/schwab.py:280`

## Fix Applied
```python
period=Client.PriceHistory.Period.TWENTY_YEARS
```

## Validation Results
- **AAPL**: 6,288 bars fetched (25 years: 2000-2025) ✅
- **MSFT**: 461 bars fetched (2024-2025) ✅ (symbol-specific API limitation)

## Symbol-Specific Limitations Discovered
- **AAPL**: Full 25-year history available
- **MSFT**: ~2 years history available (Schwab API limitation)

## Files Modified
- `jutsu_engine/data/fetchers/schwab.py:280`
- `CHANGELOG.md` (comprehensive documentation added)

## Key Learning
Schwab API requires **BOTH** `period` parameter AND custom date ranges together, following schwab-py library reference implementation patterns.
