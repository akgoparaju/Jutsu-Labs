# Momentum-ATR CLI Parameter Integration

## Implementation Summary

Added strategy parameter support to CLI with .env file integration for Momentum-ATR (V4.0) strategy.

## Parameters Added to .env.example

All parameters use `STRATEGY_` prefix and are grouped together:

```bash
# MACD Indicator Parameters
STRATEGY_MACD_FAST_PERIOD=12
STRATEGY_MACD_SLOW_PERIOD=26
STRATEGY_MACD_SIGNAL_PERIOD=9

# Volatility Filter
STRATEGY_VIX_KILL_SWITCH=30.0

# Risk Management (ATR-based)
STRATEGY_ATR_PERIOD=14
STRATEGY_ATR_STOP_MULTIPLIER=2.0

# Portfolio Risk Allocation
STRATEGY_RISK_STRONG_TREND=0.03    # 3.0%
STRATEGY_RISK_WANING_TREND=0.015   # 1.5%
```

## Priority Hierarchy

1. **CLI Arguments** (highest priority) - User-provided command-line flags
2. **.env File Values** - Environment variables with STRATEGY_ prefix
3. **Strategy Defaults** (lowest priority) - Hardcoded in strategy __init__

## Implementation Pattern

```python
import os
from dotenv import load_dotenv

load_dotenv()  # Load .env file

# Load from .env with defaults
macd_fast = int(os.getenv('STRATEGY_MACD_FAST_PERIOD', '12'))

# CLI option with None default (allows detection of user override)
@click.option('--macd-fast-period', type=int, default=None)

# In function: CLI overrides .env
final_value = cli_value if cli_value is not None else env_value
```

## Usage Examples

**Using .env only:**
```bash
# Edit .env file, then run:
jutsu backtest --strategy Momentum_ATR --symbols QQQ,VIX,TQQQ,SQQQ --start 2024-01-01 --end 2024-12-31
```

**Override specific parameter via CLI:**
```bash
jutsu backtest --strategy Momentum_ATR \\
  --symbols QQQ,VIX,TQQQ,SQQQ \\
  --start 2024-01-01 --end 2024-12-31 \\
  --vix-kill-switch 25.0  # Override VIX threshold
```

**Override multiple parameters:**
```bash
jutsu backtest --strategy Momentum_ATR \\
  --symbols QQQ,VIX,TQQQ,SQQQ \\
  --start 2024-01-01 --end 2024-12-31 \\
  --risk-strong-trend 0.05 \\
  --risk-waning-trend 0.02 \\
  --vix-kill-switch 25.0
```

## CLI Options Added

- `--macd-fast-period`: MACD fast EMA period (default from .env)
- `--macd-slow-period`: MACD slow EMA period (default from .env)
- `--macd-signal-period`: MACD signal line period (default from .env)
- `--vix-kill-switch`: VIX kill switch level (default from .env)
- `--atr-period`: ATR period (default from .env)
- `--atr-stop-multiplier`: ATR stop-loss multiplier (default from .env)
- `--risk-strong-trend`: Risk for strong trends (default from .env)
- `--risk-waning-trend`: Risk for waning trends (default from .env)

All defaults are `None` to allow detection of user override.

## Dynamic Parameter Building

Uses existing dynamic parameter inspection pattern:

```python
# Build kwargs based on what strategy constructor accepts
strategy_kwargs = {}

sig = inspect.signature(strategy_class.__init__)
params = sig.parameters

if 'macd_fast_period' in params:
    strategy_kwargs['macd_fast_period'] = final_macd_fast
if 'vix_kill_switch' in params:
    strategy_kwargs['vix_kill_switch'] = Decimal(str(final_vix_kill_switch))
# ... etc
```

This ensures backwards compatibility with existing strategies that don't use these parameters.

## Testing

Verified with:
- Default .env values work
- CLI overrides work
- Missing .env file falls back to strategy defaults
- Invalid values raise appropriate errors
- Parameter inspection works for all strategies

## Files Modified

- `.env.example` - Added strategy parameters section
- `jutsu_engine/cli/main.py` - Added CLI options and parameter loading logic

## Related Files

- `jutsu_engine/strategies/Momentum_ATR.py` - Strategy implementation
- `jutsu_engine/utils/config.py` - Config management (uses python-dotenv)
