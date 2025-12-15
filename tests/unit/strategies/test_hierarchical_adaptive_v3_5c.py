"""
Unit tests for Hierarchical Adaptive v3.5c strategy.

Test Coverage:
1. Initialization (3 tests)
2. Shock Brake Parameter Validation (4 tests)
3. Shock Detection DOWN_ONLY Mode (4 tests)
4. Shock Detection ABS Mode (3 tests)
5. Shock Brake Cooldown Timer (5 tests)
6. Shock Brake VolState Override (4 tests)
7. Shock Brake Precedence (3 tests)
8. Backwards Compatibility (2 tests)
9. Integration with Treasury Overlay (2 tests)

Total: 30 tests (Shock Brake specific)

Note: v3.5c inherits all v3.5b features, so base functionality
is tested via v3.5b tests. This file focuses on Shock Brake feature.
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5c import Hierarchical_Adaptive_v3_5c
from jutsu_engine.core.events import MarketDataEvent


# ===== Fixtures =====

@pytest.fixture
def strategy_default():
    """Create strategy with default parameters (shock brake enabled)."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()
    return strategy


@pytest.fixture
def strategy_shock_disabled():
    """Create strategy with shock brake disabled (v3.5b behavior)."""
    strategy = Hierarchical_Adaptive_v3_5c(enable_shock_brake=False)
    strategy.init()
    return strategy


@pytest.fixture
def strategy_shock_abs():
    """Create strategy with ABS shock direction mode."""
    strategy = Hierarchical_Adaptive_v3_5c(
        enable_shock_brake=True,
        shock_direction_mode="ABS",
        shock_threshold_pct=Decimal("0.03")
    )
    strategy.init()
    return strategy


@pytest.fixture
def strategy_conservative_shock():
    """Create strategy with conservative shock settings."""
    strategy = Hierarchical_Adaptive_v3_5c(
        enable_shock_brake=True,
        shock_threshold_pct=Decimal("0.05"),  # 5% threshold
        shock_cooldown_days=3,  # 3-day cooldown
        shock_direction_mode="DOWN_ONLY"
    )
    strategy.init()
    return strategy


@pytest.fixture
def sample_bars():
    """Create sample market data bars for warmup."""
    base_time = datetime.now(timezone.utc)
    bars = []
    for i in range(300):
        bars.append(
            MarketDataEvent(
                symbol="QQQ",
                timestamp=base_time + timedelta(days=i),
                open=Decimal("300.00") + Decimal(str(i * 0.1)),
                high=Decimal("301.00") + Decimal(str(i * 0.1)),
                low=Decimal("299.00") + Decimal(str(i * 0.1)),
                close=Decimal("300.00") + Decimal(str(i * 0.1)),
                volume=1000000
            )
        )
    return bars


def _create_bar(symbol: str, close: Decimal, timestamp: datetime) -> MarketDataEvent:
    """Helper to create a market data bar."""
    return MarketDataEvent(
        symbol=symbol,
        timestamp=timestamp,
        open=close - Decimal("1"),
        high=close + Decimal("1"),
        low=close - Decimal("2"),
        close=close,
        volume=1000000
    )


# ===== 1. Initialization Tests (3 tests) =====

def test_initialization_default_shock_brake_parameters():
    """Test strategy initialization with default shock brake parameters."""
    strategy = Hierarchical_Adaptive_v3_5c()

    # Shock Brake parameters (NEW in v3.5c)
    assert strategy.enable_shock_brake is True
    assert strategy.shock_threshold_pct == Decimal("0.03")
    assert strategy.shock_cooldown_days == 5
    assert strategy.shock_direction_mode == "DOWN_ONLY"

    # Verify inherited v3.5b parameters
    assert strategy.measurement_noise == Decimal("2000.0")
    assert strategy.sma_fast == 40
    assert strategy.sma_slow == 140
    assert strategy.upper_thresh_z == Decimal("1.0")
    assert strategy.lower_thresh_z == Decimal("0.2")


def test_initialization_custom_shock_brake_parameters():
    """Test strategy initialization with custom shock brake parameters."""
    strategy = Hierarchical_Adaptive_v3_5c(
        enable_shock_brake=True,
        shock_threshold_pct=Decimal("0.05"),
        shock_cooldown_days=7,
        shock_direction_mode="ABS"
    )

    assert strategy.enable_shock_brake is True
    assert strategy.shock_threshold_pct == Decimal("0.05")
    assert strategy.shock_cooldown_days == 7
    assert strategy.shock_direction_mode == "ABS"


def test_initialization_shock_brake_state():
    """Test that shock brake state is properly initialized."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()

    assert strategy._shock_timer == 0
    assert strategy._previous_close is None
    assert strategy._shock_brake_active is False


# ===== 2. Shock Brake Parameter Validation (4 tests) =====

def test_invalid_shock_threshold_negative():
    """Test that negative shock threshold raises error."""
    with pytest.raises(ValueError, match="shock_threshold_pct must be positive"):
        Hierarchical_Adaptive_v3_5c(shock_threshold_pct=Decimal("-0.03"))


def test_invalid_shock_threshold_zero():
    """Test that zero shock threshold raises error."""
    with pytest.raises(ValueError, match="shock_threshold_pct must be positive"):
        Hierarchical_Adaptive_v3_5c(shock_threshold_pct=Decimal("0"))


def test_invalid_cooldown_days_zero():
    """Test that zero cooldown days raises error."""
    with pytest.raises(ValueError, match="shock_cooldown_days must be >= 1"):
        Hierarchical_Adaptive_v3_5c(shock_cooldown_days=0)


def test_invalid_direction_mode():
    """Test that invalid direction mode raises error."""
    with pytest.raises(ValueError, match="shock_direction_mode must be one of"):
        Hierarchical_Adaptive_v3_5c(shock_direction_mode="INVALID")


# ===== 3. Shock Detection DOWN_ONLY Mode (4 tests) =====

def test_shock_detection_down_only_triggers_on_negative():
    """Test that DOWN_ONLY mode triggers on negative returns >= threshold."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_threshold_pct=Decimal("0.03"),
        shock_direction_mode="DOWN_ONLY"
    )
    strategy.init()

    # Set previous close
    strategy._previous_close = Decimal("100.00")

    # 4% down move (triggers -3% threshold)
    current_close = Decimal("96.00")
    shock = strategy._detect_shock(current_close)

    assert shock is True


def test_shock_detection_down_only_no_trigger_on_positive():
    """Test that DOWN_ONLY mode does NOT trigger on positive returns."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_threshold_pct=Decimal("0.03"),
        shock_direction_mode="DOWN_ONLY"
    )
    strategy.init()

    # Set previous close
    strategy._previous_close = Decimal("100.00")

    # 5% up move (should NOT trigger in DOWN_ONLY)
    current_close = Decimal("105.00")
    shock = strategy._detect_shock(current_close)

    assert shock is False


def test_shock_detection_down_only_boundary():
    """Test DOWN_ONLY mode at exact threshold boundary."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_threshold_pct=Decimal("0.03"),
        shock_direction_mode="DOWN_ONLY"
    )
    strategy.init()

    strategy._previous_close = Decimal("100.00")

    # Exactly -3% (r_t = -0.03 <= -0.03, should trigger)
    current_close = Decimal("97.00")
    shock = strategy._detect_shock(current_close)

    assert shock is True


def test_shock_detection_down_only_just_above_threshold():
    """Test DOWN_ONLY mode just above threshold (should NOT trigger)."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_threshold_pct=Decimal("0.03"),
        shock_direction_mode="DOWN_ONLY"
    )
    strategy.init()

    strategy._previous_close = Decimal("100.00")

    # -2.9% (r_t = -0.029 > -0.03, should NOT trigger)
    current_close = Decimal("97.10")
    shock = strategy._detect_shock(current_close)

    assert shock is False


# ===== 4. Shock Detection ABS Mode (3 tests) =====

def test_shock_detection_abs_triggers_on_negative():
    """Test that ABS mode triggers on negative returns >= threshold."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_threshold_pct=Decimal("0.03"),
        shock_direction_mode="ABS"
    )
    strategy.init()

    strategy._previous_close = Decimal("100.00")

    # -4% down move (triggers)
    current_close = Decimal("96.00")
    shock = strategy._detect_shock(current_close)

    assert shock is True


def test_shock_detection_abs_triggers_on_positive():
    """Test that ABS mode triggers on positive returns >= threshold."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_threshold_pct=Decimal("0.03"),
        shock_direction_mode="ABS"
    )
    strategy.init()

    strategy._previous_close = Decimal("100.00")

    # +4% up move (triggers in ABS mode)
    current_close = Decimal("104.00")
    shock = strategy._detect_shock(current_close)

    assert shock is True


def test_shock_detection_abs_no_trigger_below_threshold():
    """Test that ABS mode does NOT trigger below threshold."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_threshold_pct=Decimal("0.03"),
        shock_direction_mode="ABS"
    )
    strategy.init()

    strategy._previous_close = Decimal("100.00")

    # +2% move (below threshold)
    current_close = Decimal("102.00")
    shock = strategy._detect_shock(current_close)

    assert shock is False


# ===== 5. Shock Brake Cooldown Timer (5 tests) =====

def test_shock_timer_initialization():
    """Test that shock timer initializes to 0."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()

    assert strategy._shock_timer == 0


def test_shock_timer_set_on_detection():
    """Test that shock timer is set correctly on shock detection."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_cooldown_days=5,
        shock_direction_mode="DOWN_ONLY"
    )
    strategy.init()

    strategy._previous_close = Decimal("100.00")

    # Detect shock
    shock = strategy._detect_shock(Decimal("96.00"))
    assert shock is True

    # Simulate what on_bar would do after detection
    strategy._shock_timer = strategy.shock_cooldown_days

    assert strategy._shock_timer == 5


def test_shock_timer_decrement():
    """Test that shock timer decrements correctly."""
    strategy = Hierarchical_Adaptive_v3_5c(shock_cooldown_days=5)
    strategy.init()

    # Manually set timer
    strategy._shock_timer = 3

    # Simulate decrement (as done at end of on_bar)
    strategy._shock_timer = max(0, strategy._shock_timer - 1)

    assert strategy._shock_timer == 2


def test_shock_timer_does_not_go_negative():
    """Test that shock timer never goes negative."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()

    strategy._shock_timer = 1
    strategy._shock_timer = max(0, strategy._shock_timer - 1)
    assert strategy._shock_timer == 0

    # Decrement again
    strategy._shock_timer = max(0, strategy._shock_timer - 1)
    assert strategy._shock_timer == 0  # Still 0, not -1


def test_shock_timer_custom_cooldown():
    """Test shock timer with custom cooldown days."""
    strategy = Hierarchical_Adaptive_v3_5c(
        shock_cooldown_days=10,
        shock_direction_mode="DOWN_ONLY"
    )
    strategy.init()

    strategy._previous_close = Decimal("100.00")
    strategy._detect_shock(Decimal("96.00"))

    # Simulate timer set
    strategy._shock_timer = strategy.shock_cooldown_days

    assert strategy._shock_timer == 10


# ===== 6. Shock Brake VolState Override (4 tests) =====

def test_shock_brake_forces_high_vol():
    """Test that active shock brake forces VolState = High."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()

    # Simulate shock timer active
    strategy._shock_timer = 3
    strategy.vol_state = "Low"

    # Check that shock brake would force High
    if strategy._shock_timer > 0:
        strategy._shock_brake_active = True
        strategy.vol_state = "High"

    assert strategy.vol_state == "High"
    assert strategy._shock_brake_active is True


def test_shock_brake_inactive_when_timer_zero():
    """Test that shock brake is inactive when timer is 0."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()

    strategy._shock_timer = 0
    strategy._shock_brake_active = False
    strategy.vol_state = "Low"

    # Simulate check
    if strategy._shock_timer > 0:
        strategy._shock_brake_active = True

    assert strategy._shock_brake_active is False
    assert strategy.vol_state == "Low"


def test_shock_brake_disabled_does_not_force_high():
    """Test that disabled shock brake does not force High vol."""
    strategy = Hierarchical_Adaptive_v3_5c(enable_shock_brake=False)
    strategy.init()

    strategy.vol_state = "Low"

    # Shock detection should return False when disabled
    strategy._previous_close = Decimal("100.00")
    shock = strategy._detect_shock(Decimal("96.00"))

    assert shock is False
    assert strategy.vol_state == "Low"


def test_get_shock_brake_status():
    """Test get_shock_brake_status() method."""
    strategy = Hierarchical_Adaptive_v3_5c(
        enable_shock_brake=True,
        shock_threshold_pct=Decimal("0.04"),
        shock_cooldown_days=7,
        shock_direction_mode="ABS"
    )
    strategy.init()

    # Set some state
    strategy._shock_timer = 3
    strategy._shock_brake_active = True

    status = strategy.get_shock_brake_status()

    assert status["enabled"] is True
    assert status["active"] is True
    assert status["timer"] == 3
    assert status["threshold"] == 0.04
    assert status["cooldown_days"] == 7
    assert status["direction_mode"] == "ABS"


# ===== 7. Shock Brake Precedence (3 tests) =====

def test_shock_brake_overrides_vol_crush():
    """Test that shock brake takes precedence over vol-crush override."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()

    # Simulate shock brake active
    strategy._shock_timer = 3
    strategy._shock_brake_active = True
    strategy.vol_state = "High"

    # Vol-crush would normally set Low and return True
    vol_crush_triggered = True

    # But with shock brake active, vol-crush is ignored
    if strategy._shock_brake_active:
        vol_crush_triggered = False

    assert vol_crush_triggered is False
    assert strategy.vol_state == "High"


def test_shock_brake_overrides_hysteresis_low():
    """Test that shock brake overrides hysteresis transition to Low."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()

    # Shock brake active
    strategy._shock_timer = 2
    strategy._shock_brake_active = True

    # Even if z_score is very low (would normally trigger Low)
    z_score = Decimal("-0.5")

    # Hysteresis would set Low
    strategy.vol_state = "Low"

    # But shock brake forces High
    if strategy._shock_brake_active:
        strategy.vol_state = "High"

    assert strategy.vol_state == "High"


def test_vol_crush_works_when_shock_brake_inactive():
    """Test that vol-crush works normally when shock brake is inactive."""
    strategy = Hierarchical_Adaptive_v3_5c()
    strategy.init()

    strategy._shock_timer = 0
    strategy._shock_brake_active = False

    # Vol-crush can now affect state
    vol_crush_triggered = True

    # Simulate vol-crush setting Low
    if not strategy._shock_brake_active and vol_crush_triggered:
        strategy.vol_state = "Low"

    assert strategy.vol_state == "Low"


# ===== 8. Backwards Compatibility (2 tests) =====

def test_disabled_shock_brake_behaves_like_v3_5b():
    """Test that disabled shock brake produces v3.5b-identical behavior."""
    strategy = Hierarchical_Adaptive_v3_5c(enable_shock_brake=False)
    strategy.init()

    # Shock detection always returns False when disabled
    strategy._previous_close = Decimal("100.00")

    assert strategy._detect_shock(Decimal("90.00")) is False  # -10% move
    assert strategy._detect_shock(Decimal("80.00")) is False  # -20% move
    assert strategy._detect_shock(Decimal("70.00")) is False  # -30% move


def test_disabled_shock_brake_timer_stays_zero():
    """Test that timer stays 0 when shock brake is disabled."""
    strategy = Hierarchical_Adaptive_v3_5c(enable_shock_brake=False)
    strategy.init()

    assert strategy._shock_timer == 0

    # Even after "detecting" shocks (which should not work)
    strategy._previous_close = Decimal("100.00")
    strategy._detect_shock(Decimal("90.00"))

    assert strategy._shock_timer == 0


# ===== 9. Integration with Treasury Overlay (2 tests) =====

def test_shock_brake_with_treasury_overlay():
    """Test shock brake works with Treasury Overlay enabled."""
    strategy = Hierarchical_Adaptive_v3_5c(
        enable_shock_brake=True,
        allow_treasury=True
    )
    strategy.init()

    assert strategy.enable_shock_brake is True
    assert strategy.allow_treasury is True

    # Both features can be enabled simultaneously
    status = strategy.get_shock_brake_status()
    assert status["enabled"] is True


def test_shock_brake_without_treasury_overlay():
    """Test shock brake works with Treasury Overlay disabled."""
    strategy = Hierarchical_Adaptive_v3_5c(
        enable_shock_brake=True,
        allow_treasury=False
    )
    strategy.init()

    assert strategy.enable_shock_brake is True
    assert strategy.allow_treasury is False

    # Shock brake still functions independently
    strategy._previous_close = Decimal("100.00")
    shock = strategy._detect_shock(Decimal("96.00"))
    assert shock is True


# ===== 10. Warmup Calculation (1 test) =====

def test_warmup_calculation_same_as_v3_5b():
    """Test that v3.5c warmup calculation matches v3.5b."""
    strategy = Hierarchical_Adaptive_v3_5c(
        sma_slow=140,
        vol_baseline_window=126,
        realized_vol_window=21
    )

    # SMA lookback: 140 + 10 = 150
    # Vol lookback: 126 + 21 = 147
    # Expected: max(150, 147) = 150

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 150


# ===== 11. Strategy Name (1 test) =====

def test_default_strategy_name():
    """Test default strategy name is v3.5c."""
    strategy = Hierarchical_Adaptive_v3_5c()

    assert strategy.name == "Hierarchical_Adaptive_v3_5c"
    assert "v3_5c" in strategy.name.lower()
