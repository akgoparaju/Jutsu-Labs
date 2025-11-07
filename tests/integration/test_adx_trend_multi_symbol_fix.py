"""
Integration test to verify ADX_Trend multi-symbol bar filtering fix.

This test specifically verifies the bug fix where ADX_Trend was using mixed
QQQ/TQQQ/SQQQ bars for indicator calculations, resulting in only QQQ trades.

Bug Context:
- strategy_base._bars contains all symbols' bars mixed
- get_closes/get_highs/get_lows must filter by symbol for multi-symbol strategies
- Without filtering, indicator calculations use corrupted data
"""
from decimal import Decimal
from datetime import datetime, timezone
import pandas as pd

from jutsu_engine.strategies.ADX_Trend import ADX_Trend
from jutsu_engine.core.events import MarketDataEvent


def test_adx_trend_filters_bars_by_symbol():
    """
    Verify that ADX_Trend correctly filters bars by signal symbol.

    This is a regression test for the multi-symbol bar mixing bug.
    """
    strategy = ADX_Trend()
    strategy.init()

    # Create synthetic bar data with 3 symbols
    # QQQ at $400, TQQQ at $60, SQQQ at $30 (realistic 2024 prices)
    base_time = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)

    # Add 70 bars of mixed symbols (enough for lookback=60)
    for i in range(70):
        timestamp = base_time.replace(hour=9 + (30 + i) // 60, minute=(30 + i) % 60)

        # QQQ bar - signal asset
        qqq_bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=timestamp,
            open=Decimal('400.00') + Decimal(str(i * 0.5)),
            high=Decimal('401.00') + Decimal(str(i * 0.5)),
            low=Decimal('399.00') + Decimal(str(i * 0.5)),
            close=Decimal('400.50') + Decimal(str(i * 0.5)),
            volume=1000000
        )
        strategy._update_bar(qqq_bar)

        # TQQQ bar - 3x leveraged (higher prices, more volatile)
        tqqq_bar = MarketDataEvent(
            symbol='TQQQ',
            timestamp=timestamp,
            open=Decimal('60.00') + Decimal(str(i * 1.5)),
            high=Decimal('62.00') + Decimal(str(i * 1.5)),
            low=Decimal('58.00') + Decimal(str(i * 1.5)),
            close=Decimal('61.00') + Decimal(str(i * 1.5)),
            volume=5000000
        )
        strategy._update_bar(tqqq_bar)

        # SQQQ bar - 3x inverse (use constant price, direction doesn't matter for test)
        sqqq_bar = MarketDataEvent(
            symbol='SQQQ',
            timestamp=timestamp,
            open=Decimal('30.00'),
            high=Decimal('31.00'),
            low=Decimal('29.00'),
            close=Decimal('30.50'),
            volume=4000000
        )
        strategy._update_bar(sqqq_bar)

    # Verify internal bar storage contains all symbols
    assert len(strategy._bars) == 210  # 70 * 3 symbols

    # Get closes with and without symbol filter
    all_closes = strategy.get_closes(lookback=60)  # No filter - returns last 60 bars (mixed)
    qqq_closes = strategy.get_closes(lookback=60, symbol='QQQ')  # Filter - returns QQQ only

    # Verify filtering works
    assert len(all_closes) == 60, "Should return 60 most recent bars (mixed symbols)"
    assert len(qqq_closes) == 60, "Should return 60 QQQ bars only"

    # Verify QQQ closes are in correct price range
    # QQQ should be ~400-440 (400 + 60*0.5 increments)
    assert all(Decimal('390') < price < Decimal('450') for price in qqq_closes), \
        f"QQQ closes should be in range $390-$450, got {qqq_closes.tolist()}"

    # Verify all closes (mixed) would have different range if bug existed
    # If bug exists, all_closes would include TQQQ ($60-150) and SQQQ ($30 to negative)
    # With fix, all_closes is just last 60 bars regardless of symbol

    # Most importantly: QQQ closes should be sequential and increasing
    # (We added 0.5 per bar, so each should be higher than previous)
    for i in range(1, len(qqq_closes)):
        assert qqq_closes.iloc[i] > qqq_closes.iloc[i-1], \
            f"QQQ closes should be increasing: {qqq_closes.tolist()}"

    # Verify highs and lows also filter correctly
    qqq_highs = strategy.get_highs(lookback=60, symbol='QQQ')
    qqq_lows = strategy.get_lows(lookback=60, symbol='QQQ')

    assert len(qqq_highs) == 60
    assert len(qqq_lows) == 60

    # Highs should be ~1 higher than closes, lows ~0.5 lower
    assert all(Decimal('390') < price < Decimal('450') for price in qqq_highs)
    assert all(Decimal('390') < price < Decimal('450') for price in qqq_lows)


def test_adx_trend_generates_non_qqq_trades():
    """
    Verify that ADX_Trend generates TQQQ/SQQQ trades, not just QQQ.

    This is a high-level regression test for the bug where only QQQ trades occurred.
    """
    strategy = ADX_Trend(
        ema_fast_period=10,
        ema_slow_period=20,
        adx_period=10  # Shorter periods for faster regime detection
    )
    strategy.init()

    base_time = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)

    # Create strong uptrend with high ADX (should trigger Regime 1: TQQQ 60%)
    for i in range(50):
        timestamp = base_time.replace(hour=9 + (30 + i) // 60, minute=(30 + i) % 60)

        # Strong uptrend: QQQ rising sharply
        qqq_bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=timestamp,
            open=Decimal('400.00') + Decimal(str(i * 2.0)),  # Strong trend
            high=Decimal('405.00') + Decimal(str(i * 2.0)),
            low=Decimal('399.00') + Decimal(str(i * 2.0)),
            close=Decimal('404.00') + Decimal(str(i * 2.0)),  # Large moves
            volume=1000000
        )
        strategy._update_bar(qqq_bar)
        strategy.on_bar(qqq_bar)

        # Add TQQQ/SQQQ bars (needed for portfolio to have current prices)
        for symbol in ['TQQQ', 'SQQQ']:
            bar = MarketDataEvent(
                symbol=symbol,
                timestamp=timestamp,
                open=Decimal('50.00'),
                high=Decimal('51.00'),
                low=Decimal('49.00'),
                close=Decimal('50.50'),
                volume=1000000
            )
            strategy._update_bar(bar)
            # Don't call on_bar for TQQQ/SQQQ (strategy ignores them)

    # Get generated signals
    signals = strategy.get_signals()

    # With strong uptrend and high ADX, we should see TQQQ trades
    # (At minimum, initial regime establishment should allocate to TQQQ)
    tqqq_signals = [s for s in signals if s.symbol == 'TQQQ']

    assert len(tqqq_signals) > 0, \
        f"Expected TQQQ signals in strong uptrend, got signals: {[(s.symbol, s.signal_type) for s in signals]}"

    # Verify TQQQ buy signal uses correct allocation (60% for Regime 1)
    tqqq_buys = [s for s in tqqq_signals if s.signal_type == 'BUY']
    assert any(s.portfolio_percent == Decimal('0.60') for s in tqqq_buys), \
        f"Expected TQQQ 60% allocation in Regime 1, got: {[s.portfolio_percent for s in tqqq_buys]}"


def test_adx_trend_regime_detection_with_clean_data():
    """
    Verify regime detection doesn't error with clean QQQ-only data.

    This test ensures the fix allows strategy to run without errors.
    The first two tests already validate correct filtering behavior.
    """
    strategy = ADX_Trend(
        ema_fast_period=10,
        ema_slow_period=20,
        adx_period=10
    )
    strategy.init()

    base_time = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)

    # Create 35 bars (enough for lookback=30 + buffer)
    for i in range(35):
        timestamp = base_time.replace(hour=9 + (30 + i) // 60, minute=(30 + i) % 60)

        qqq_bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=timestamp,
            open=Decimal('400.00') + Decimal(str(i * 1.0)),
            high=Decimal('402.00') + Decimal(str(i * 1.0)),
            low=Decimal('398.00') + Decimal(str(i * 1.0)),
            close=Decimal('401.00') + Decimal(str(i * 1.0)),
            volume=1000000
        )
        strategy._update_bar(qqq_bar)

        # Add other symbols to _bars (simulating multi-symbol environment)
        for symbol in ['TQQQ', 'SQQQ']:
            other_bar = MarketDataEvent(
                symbol=symbol,
                timestamp=timestamp,
                open=Decimal('50.00'),
                high=Decimal('51.00'),
                low=Decimal('49.00'),
                close=Decimal('50.50'),
                volume=1000000
            )
            strategy._update_bar(other_bar)

        # Only process QQQ bars for strategy logic
        strategy.on_bar(qqq_bar)

    # If we get here without error, the fix is working
    # The strategy is properly filtering by symbol and calculating indicators

    # Verify internal bar count is correct (35 bars * 3 symbols = 105 total)
    assert len(strategy._bars) == 105, \
        f"Expected 105 bars (35 QQQ + 35 TQQQ + 35 SQQQ), got {len(strategy._bars)}"

    # Verify get_closes with symbol filter returns only QQQ bars
    qqq_closes = strategy.get_closes(lookback=30, symbol='QQQ')
    assert len(qqq_closes) == 30, \
        f"Expected 30 QQQ close prices, got {len(qqq_closes)}"

    # Verify prices are in QQQ range (not mixed with TQQQ/SQQQ)
    assert all(Decimal('390') < price < Decimal('450') for price in qqq_closes), \
        f"QQQ closes should be in $390-$450 range, got {qqq_closes.tolist()}"
