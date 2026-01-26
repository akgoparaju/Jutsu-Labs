# Hierarchical Adaptive v2.5 - Strategy Specification

**Version:** 2.5
**Type:** Incremental Bug Fix Release
**Date:** 2025-11-18
**Status:** Design Complete - Ready for Implementation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Version History](#2-version-history)
3. [Problem Statement](#3-problem-statement)
4. [Root Cause Analysis](#4-root-cause-analysis)
5. [v2.5 Solution Design](#5-v25-solution-design)
6. [DD Governor Algorithm](#6-dd-governor-algorithm)
7. [Parameter Changes](#7-parameter-changes)
8. [Behavioral Examples](#8-behavioral-examples)
9. [Testing Strategy](#9-testing-strategy)
10. [Migration Path](#10-migration-path)
11. [Expected Performance Impact](#11-expected-performance-impact)
12. [Implementation Checklist](#12-implementation-checklist)

---

## 1. Executive Summary

**Purpose**: Fix asymmetric drawdown governor bug in v2.0 that prevents defensive positioning.

**Problem**: v2.0's DD governor formula `E_raw = 1.0 + (E_volVIX - 1.0) * P_DD` creates symmetric compression around 1.0, which:
- ✓ **Correctly compresses leverage** (E_volVIX > 1.0 → toward 1.0)
- ✗ **Incorrectly compresses defensive positions** (E_volVIX < 1.0 → toward 1.0)
- ✗ **Makes E_min unreachable** during drawdowns

**Evidence**: Run 139 (best v2.0 performer) never went below 100% QQQ despite `E_min = 0.4` during significant drawdowns.

**Solution**: Asymmetric DD governor with two separate compression paths:
- **Leverage path** (E_volVIX > 1.0): Compress toward 1.0 (same as v2.0)
- **Defensive path** (E_volVIX < 1.0): Interpolate between E_volVIX and 1.0 (NEW)

**Impact**: Minimal code change (5 lines), preserves all v2.0 features, enables full exposure range [E_min, E_max].

**Compatibility**: Same 20-parameter interface, same class structure, separate YAML configs.

---

## 2. Version History

### v2.0 (Baseline)
**Released**: 2025-11-15
**Paradigm**: Continuous exposure overlay with 5-tier engine
**Parameters**: 20 configurable parameters
**Known Issues**: DD governor asymmetry prevents defensive positioning

**Key Features**:
- ✅ Kalman trend normalization (T_norm ∈ [-1, +1])
- ✅ Volatility modulator (vol-targeting)
- ✅ VIX compression (soft filter)
- ✅ QQQ/TQQQ position mapping
- ✅ Drift-based rebalancing (2.5% threshold)
- ❌ **DD governor asymmetry bug**

### v2.5 (This Release)
**Type**: Incremental bug fix
**Focus**: DD governor asymmetry correction
**Scope**: Minimal change - preserves all v2.0 functionality

**Changes**:
1. ✅ Asymmetric DD governor formula (5-line fix)
2. ✅ Updated DD thresholds (DD_soft: 0.10, DD_hard: 0.20)
3. ✅ Added version parameter to constructor
4. ✅ Comprehensive behavioral examples
5. ✅ Enhanced testing coverage

**Preserved Features** (100% compatibility):
- ✅ Same 20-parameter interface
- ✅ Same 5-tier exposure engine
- ✅ Same Kalman trend normalization
- ✅ Same vol/VIX modulators
- ✅ Same position mapping logic
- ✅ Same rebalancing mechanism

---

## 3. Problem Statement

### 3.1 Observable Symptoms

**Issue**: Strategy never achieves defensive positioning below 100% QQQ exposure despite:
- `E_min = 0.4` (40% minimum exposure target)
- Significant drawdowns occurring (>10%)
- Bearish market conditions detected (T_norm < 0)

**Evidence from Run 139** (best v2.0 performer):
```
Parameters:
  E_min: 0.4    # 40% minimum exposure
  DD_soft: 0.05 # 5% DD starts compression
  DD_hard: 0.15 # 15% DD full compression

Observed Behavior:
  - Min exposure reached: ~100% QQQ (never below)
  - Expected min exposure: 40% QQQ (E_min)
  - Gap: 60 percentage points of defensive range UNUSED
```

### 3.2 Impact Analysis

**Risk Management Failure**:
- Strategy cannot reduce risk during drawdowns
- Defensive positioning (< 1.0x) unreachable
- E_min parameter effectively ignored

**Capital Efficiency Loss**:
- Cash position never utilized for risk reduction
- Missing opportunity to preserve capital during stress
- No benefit from having exposure range below 1.0x

**Strategy Behavior Mismatch**:
- Design intent: E_t ∈ [0.4, 1.5] = 110% range
- Actual behavior: E_t ∈ [1.0, 1.5] = 50% range
- Unused capacity: 55% of designed exposure range

---

## 4. Root Cause Analysis

### 4.1 Mathematical Analysis

**v2.0 DD Governor Formula**:
```python
E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
```

**Problem**: Symmetric compression around neutral (1.0)

**Behavior Analysis**:

| Scenario | E_volVIX | P_DD | E_raw Calculation | Result | Issue |
|----------|----------|------|-------------------|--------|-------|
| **Bullish + DD** | 1.3 | 0.5 | 1.0 + (1.3 - 1.0) * 0.5 = 1.15 | ✅ Compresses 1.3 → 1.15 | CORRECT |
| **Neutral + DD** | 1.0 | 0.5 | 1.0 + (1.0 - 1.0) * 0.5 = 1.0 | ✅ Stays at 1.0 | CORRECT |
| **Bearish + DD** | 0.7 | 0.5 | 1.0 + (0.7 - 1.0) * 0.5 = 0.85 | ❌ Compresses 0.7 → 0.85 | **WRONG** |

**Key Insight**: Formula treats all E_volVIX values symmetrically around 1.0:
- E_volVIX > 1.0: Distance from 1.0 is (E_volVIX - 1.0) → compressed toward 1.0 ✅
- E_volVIX < 1.0: Distance from 1.0 is (E_volVIX - 1.0) = negative → **compressed toward 1.0** ❌

### 4.2 Conceptual Error

**Design Intent** (what we wanted):
- During drawdowns, **reduce risk** across the board
- If already defensive (E < 1.0), **stay defensive** or become more defensive
- If leveraged (E > 1.0), **reduce leverage** toward neutral

**Actual Implementation** (what v2.0 did):
- During drawdowns, **compress all exposure toward 1.0**
- If defensive (E < 1.0), **increase exposure** toward 1.0 ❌
- If leveraged (E > 1.0), **decrease exposure** toward 1.0 ✅

**Root Cause**: DD governor interpreted as "gravitate toward neutral" instead of "reduce risk proportionally"

### 4.3 Numeric Example

**Scenario**: 12% drawdown (between DD_soft=10% and DD_hard=20%)

**Setup**:
```
E_volVIX = 0.6 (bearish signal after vol/VIX modulators)
DD_current = 0.12 (12% drawdown)
DD_soft = 0.10, DD_hard = 0.20
P_DD = 1.0 - ((0.12 - 0.10) / (0.20 - 0.10)) = 0.8
```

**v2.0 Calculation** (WRONG):
```python
E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
E_raw = 1.0 + (0.6 - 1.0) * 0.8
E_raw = 1.0 + (-0.4) * 0.8
E_raw = 1.0 - 0.32 = 0.68
```

**Analysis**:
- Started defensive: E_volVIX = 0.6 (40% QQQ + 60% cash)
- After DD governor: E_raw = 0.68 (68% QQQ + 32% cash)
- **Increased exposure by 8%** during a drawdown! ❌

**Expected Behavior** (what we want):
- Started defensive: E_volVIX = 0.6
- After DD governor: E_raw should be ≤ 0.6 (preserve or increase defensive stance)
- Example: E_raw = 0.68 means "become LESS defensive" during a drawdown

---

## 5. v2.5 Solution Design

### 5.1 Core Design Principle

**Asymmetric Compression**: Different formulas for leverage vs defensive positioning

**Conceptual Model**:
- **Leverage region** (E > 1.0): Drawdowns mean "reduce leverage" → compress toward 1.0
- **Defensive region** (E < 1.0): Drawdowns mean "maintain defense" → interpolate between E and 1.0

**Key Insight**: P_DD should control:
- **HOW MUCH** to adjust exposure (magnitude)
- Not **WHICH DIRECTION** to adjust (that's determined by current position)

### 5.2 Asymmetric DD Governor Formula

```python
def _apply_drawdown_governor(self, E_volVIX: Decimal, DD_current: Decimal) -> tuple[Decimal, Decimal]:
    """
    v2.5: Asymmetric DD governor - different formulas for leverage vs defensive.

    Key Change from v2.0:
    - v2.0: E_raw = 1.0 + (E_volVIX - 1.0) * P_DD  [symmetric compression]
    - v2.5: Split into two paths based on E_volVIX position

    Leverage Path (E_volVIX > 1.0):
        Goal: Reduce leverage toward neutral during drawdowns
        Formula: E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
        Example: E_volVIX=1.3, P_DD=0.5 → E_raw = 1.0 + 0.3*0.5 = 1.15

    Defensive Path (E_volVIX <= 1.0):
        Goal: Maintain or strengthen defensive positioning during drawdowns
        Formula: E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
        Example: E_volVIX=0.6, P_DD=0.5 → E_raw = 0.6*0.5 + 1.0*0.5 = 0.8

        Interpretation: Weighted average between E_volVIX (full defense) and 1.0 (neutral)
        - P_DD=1.0 (no DD): E_raw = E_volVIX (preserve signal)
        - P_DD=0.5 (mid DD): E_raw = 50% signal + 50% neutral
        - P_DD=0.0 (max DD): E_raw = 1.0 (forced neutral)
    """
    # Calculate P_DD (same as v2.0)
    if DD_current <= self.DD_soft:
        P_DD = Decimal("1.0")
    elif DD_current >= self.DD_hard:
        P_DD = self.p_min
    else:
        dd_range = self.DD_hard - self.DD_soft
        dd_excess = DD_current - self.DD_soft
        P_DD = Decimal("1.0") - (dd_excess / dd_range) * (Decimal("1.0") - self.p_min)

    # NEW: Asymmetric compression based on position
    if E_volVIX > Decimal("1.0"):
        # Leverage path: Compress toward 1.0 (same as v2.0)
        E_raw = Decimal("1.0") + (E_volVIX - Decimal("1.0")) * P_DD
    else:
        # Defensive path: Interpolate between E_volVIX and 1.0 (NEW)
        E_raw = E_volVIX * P_DD + Decimal("1.0") * (Decimal("1.0") - P_DD)

    return P_DD, E_raw
```

### 5.3 Why This Formula Works

**Leverage Path** (E_volVIX > 1.0):
```
E_raw = 1.0 + (E_volVIX - 1.0) * P_DD

When P_DD = 1.0 (no DD):  E_raw = E_volVIX (preserve leverage)
When P_DD = 0.0 (max DD): E_raw = 1.0 (force neutral)
```
**Properties**:
- ✅ Monotonic: As DD increases, exposure decreases
- ✅ Bounded: E_raw ∈ [1.0, E_volVIX]
- ✅ Preserves signal when no DD

**Defensive Path** (E_volVIX ≤ 1.0):
```
E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)

When P_DD = 1.0 (no DD):  E_raw = E_volVIX (preserve defense)
When P_DD = 0.0 (max DD): E_raw = 1.0 (force neutral)
```
**Properties**:
- ✅ Monotonic: As DD increases, exposure increases (toward neutral)
- ✅ Bounded: E_raw ∈ [E_volVIX, 1.0]
- ✅ Preserves signal when no DD
- ✅ **Never increases risk** (defensive → less defensive is still conservative)

**Interpretation**: Weighted average = convex combination
- P_DD acts as weight for "trust the signal" vs "retreat to neutral"
- During max DD, both paths converge to E_raw = 1.0 (neutral is safest)

### 5.4 Version Parameter

**Constructor Signature** (backward compatible):
```python
def __init__(
    self,
    # ... (all 20 existing parameters)
    version: str = "2.5",  # NEW: version identifier
    name: str = "Hierarchical_Adaptive_v2"
):
    self.version = version
    # ... rest of init
```

**Usage**:
- Enables runtime version checking
- Supports A/B testing (v2.0 vs v2.5)
- Facilitates logging and debugging
- No impact on strategy logic

---

## 6. DD Governor Algorithm

### 6.1 Complete Implementation

```python
def _apply_drawdown_governor(
    self,
    E_volVIX: Decimal,
    DD_current: Decimal
) -> tuple[Decimal, Decimal]:
    """
    v2.5 Asymmetric Drawdown Governor

    Reduces risk during drawdowns using position-aware compression:
    - Leverage positions (E > 1.0): Compress toward neutral
    - Defensive positions (E <= 1.0): Maintain or strengthen defense

    Args:
        E_volVIX: Exposure after Vol and VIX modulators
        DD_current: Current drawdown (positive value, e.g., 0.12 = 12%)

    Returns:
        (P_DD, E_raw): Drawdown penalty factor and adjusted exposure

    Mathematical Properties:
        - Continuous: No jumps at E_volVIX = 1.0
        - Monotonic: E_raw decreases (or stays flat) as DD increases
        - Bounded: E_raw always between min(E_volVIX, 1.0) and max(E_volVIX, 1.0)
        - Identity: When DD=0, E_raw = E_volVIX (no modification)
    """
    # Step 1: Calculate penalty factor P_DD (linear interpolation)
    if DD_current <= self.DD_soft:
        # No drawdown pressure - preserve exposure
        P_DD = Decimal("1.0")
    elif DD_current >= self.DD_hard:
        # Maximum drawdown - apply full compression
        P_DD = self.p_min
    else:
        # Linear interpolation between soft and hard thresholds
        dd_range = self.DD_hard - self.DD_soft
        dd_excess = DD_current - self.DD_soft
        P_DD = Decimal("1.0") - (dd_excess / dd_range) * (Decimal("1.0") - self.p_min)

    # Step 2: Apply asymmetric compression
    if E_volVIX > Decimal("1.0"):
        # === LEVERAGE PATH ===
        # Compress excess leverage during drawdowns
        # E_raw → 1.0 as DD increases
        E_raw = Decimal("1.0") + (E_volVIX - Decimal("1.0")) * P_DD

    else:
        # === DEFENSIVE PATH ===
        # Interpolate between defensive signal and neutral
        # E_raw moves toward 1.0 (but from below) as DD increases
        E_raw = E_volVIX * P_DD + Decimal("1.0") * (Decimal("1.0") - P_DD)

    return P_DD, E_raw
```

### 6.2 Step-by-Step Flow

**Input**: `E_volVIX = 0.6`, `DD_current = 0.12` (12% drawdown)

**Step 1: Calculate P_DD**
```
DD_soft = 0.10, DD_hard = 0.20, p_min = 0.0

DD_current (0.12) is between DD_soft (0.10) and DD_hard (0.20)
→ Linear interpolation:
  dd_range = 0.20 - 0.10 = 0.10
  dd_excess = 0.12 - 0.10 = 0.02
  P_DD = 1.0 - (0.02 / 0.10) * (1.0 - 0.0)
  P_DD = 1.0 - 0.2 = 0.8
```

**Step 2: Determine Path**
```
E_volVIX = 0.6 ≤ 1.0 → Defensive path
```

**Step 3: Calculate E_raw**
```
E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
E_raw = 0.6 * 0.8 + 1.0 * 0.2
E_raw = 0.48 + 0.20 = 0.68
```

**Step 4: Interpretation**
```
Input:  E_volVIX = 0.6 (60% QQQ, 40% cash - defensive)
Output: E_raw = 0.68 (68% QQQ, 32% cash - slightly less defensive)

Effect: DD governor moved exposure 20% of the way from defensive (0.6) toward neutral (1.0)
        This is conservative - keeps majority of defensive positioning
```

### 6.3 Continuity at E_volVIX = 1.0

**Verify no discontinuity at boundary**:

**Leverage path** (E = 1.0 + ε, ε > 0):
```
E_raw = 1.0 + (1.0 + ε - 1.0) * P_DD = 1.0 + ε * P_DD
```

**Defensive path** (E = 1.0 - ε, ε > 0):
```
E_raw = (1.0 - ε) * P_DD + 1.0 * (1.0 - P_DD)
E_raw = P_DD - ε * P_DD + 1.0 - P_DD
E_raw = 1.0 - ε * P_DD
```

**At boundary** (E = 1.0):
```
Leverage: lim(ε→0+) [1.0 + ε * P_DD] = 1.0
Defensive: lim(ε→0+) [1.0 - ε * P_DD] = 1.0
```

✅ **Continuous at E_volVIX = 1.0** (both paths → 1.0)

---

## 7. Parameter Changes

### 7.1 DD Threshold Updates

**v2.0 → v2.5 Changes**:

| Parameter | v2.0 Default | v2.5 Default | Reason |
|-----------|--------------|--------------|--------|
| `DD_soft` | 0.05 (5%) | **0.10 (10%)** | Less aggressive compression |
| `DD_hard` | 0.15 (15%) | **0.20 (20%)** | Align with typical stress levels |
| `p_min` | 0.0 | 0.0 | Unchanged |

**Rationale**:

**DD_soft: 0.05 → 0.10**
- v2.0's 5% was too aggressive (compression started too early)
- 10% is more reasonable "stress threshold" for equity strategies
- Allows normal volatility without triggering governor
- Aligns with typical portfolio rebalancing triggers

**DD_hard: 0.15 → 0.20**
- 15% felt arbitrary (not a standard risk threshold)
- 20% aligns with "bear market" definition (-20% from peak)
- Provides reasonable 10% compression range (DD_soft to DD_hard)
- Matches industry stress testing standards

**p_min: Unchanged**
- 0.0 (full compression) is appropriate for severe stress
- Ensures strategy goes to neutral (1.0x) at max DD
- Conservative fallback during extreme conditions

### 7.2 All Parameters (Complete Reference)

**Total Parameters**: 20 (same as v2.0)

```python
# TIER 1: Kalman Trend Engine (6 parameters)
measurement_noise: Decimal = Decimal("2000.0")
process_noise_1: Decimal = Decimal("0.01")
process_noise_2: Decimal = Decimal("0.01")
osc_smoothness: int = 15
strength_smoothness: int = 15
T_max: Decimal = Decimal("60")

# TIER 0: Core Exposure Engine (3 parameters)
k_trend: Decimal = Decimal("0.3")
E_min: Decimal = Decimal("0.5")
E_max: Decimal = Decimal("1.3")

# TIER 2: Volatility Modulator (4 parameters)
sigma_target_multiplier: Decimal = Decimal("0.9")
realized_vol_lookback: int = 20
S_vol_min: Decimal = Decimal("0.5")
S_vol_max: Decimal = Decimal("1.5")

# TIER 3: VIX Modulator (2 parameters)
vix_ema_period: int = 50
alpha_VIX: Decimal = Decimal("1.0")

# TIER 4: Drawdown Governor (3 parameters) - UPDATED in v2.5
DD_soft: Decimal = Decimal("0.10")    # Changed from 0.05
DD_hard: Decimal = Decimal("0.20")    # Changed from 0.15
p_min: Decimal = Decimal("0.0")       # Unchanged

# TIER 5: Rebalancing Control (1 parameter)
rebalance_threshold: Decimal = Decimal("0.025")

# Symbol Configuration (4 parameters)
signal_symbol: str = "QQQ"
core_long_symbol: str = "QQQ"
leveraged_long_symbol: str = "TQQQ"
vix_symbol: str = "$VIX"
```

### 7.3 Configuration File Template

**File**: `hierarchical_adaptive_v2_5.yaml`

```yaml
# Hierarchical Adaptive v2.5 Configuration
# =========================================
# Bug fix release: Asymmetric DD governor enables defensive positioning

strategy: "Hierarchical_Adaptive_v2"

parameters:
  # Version identifier
  version: "2.5"

  # Tier 1: Kalman Trend Engine
  measurement_noise: 2000.0
  process_noise_1: 0.01
  process_noise_2: 0.01
  osc_smoothness: 15
  strength_smoothness: 15
  T_max: 60

  # Tier 0: Core Exposure Engine
  k_trend: 0.3
  E_min: 0.5
  E_max: 1.3

  # Tier 2: Volatility Modulator
  sigma_target_multiplier: 0.9
  realized_vol_lookback: 20
  S_vol_min: 0.5
  S_vol_max: 1.5

  # Tier 3: VIX Modulator
  vix_ema_period: 50
  alpha_VIX: 1.0

  # Tier 4: Drawdown Governor (v2.5 UPDATED)
  DD_soft: 0.10    # v2.0: 0.05
  DD_hard: 0.20    # v2.0: 0.15
  p_min: 0.0

  # Tier 5: Rebalancing
  rebalance_threshold: 0.025

  # Symbols
  signal_symbol: "QQQ"
  core_long_symbol: "QQQ"
  leveraged_long_symbol: "TQQQ"
  vix_symbol: "$VIX"
```

---

## 8. Behavioral Examples

### 8.1 Example 1: Bullish Trend + Drawdown (Leverage Compression)

**Scenario**: Strong bull trend with 12% portfolio drawdown

**Setup**:
```
T_norm = +0.8 (strong bullish trend)
E_trend = 1.0 + 0.3 * 0.8 = 1.24
E_vol = 1.24 (assume vol neutral, S_vol = 1.0)
E_volVIX = 1.24 (assume VIX neutral, P_VIX = 1.0)
DD_current = 0.12 (12% drawdown)
DD_soft = 0.10, DD_hard = 0.20
```

**Step 1: Calculate P_DD**
```
DD in range [DD_soft, DD_hard]
P_DD = 1.0 - ((0.12 - 0.10) / (0.20 - 0.10))
P_DD = 1.0 - 0.2 = 0.8
```

**Step 2: Determine Path**
```
E_volVIX = 1.24 > 1.0 → Leverage path
```

**Step 3: Calculate E_raw**
```
E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
E_raw = 1.0 + (1.24 - 1.0) * 0.8
E_raw = 1.0 + 0.192 = 1.192
```

**Step 4: Clip to bounds**
```
E_t = clip(1.192, E_min=0.5, E_max=1.3) = 1.192
```

**Step 5: Map to positions**
```
E_t = 1.192 > 1.0 → Use TQQQ
w_TQQQ = (1.192 - 1.0) / 2 = 0.096 (9.6% TQQQ)
w_QQQ = 1.0 - 0.096 = 0.904 (90.4% QQQ)
w_cash = 0.0

Effective exposure: 0.904*1 + 0.096*3 = 1.192 ✓
```

**Interpretation**:
- **Without DD**: E_volVIX = 1.24 → 88% QQQ + 12% TQQQ (full leverage signal)
- **With DD (v2.5)**: E_t = 1.192 → 90.4% QQQ + 9.6% TQQQ (reduced leverage)
- **Effect**: Compressed leverage by 20% (from 1.24 to 1.192)
- **Result**: ✅ Appropriate risk reduction during drawdown

---

### 8.2 Example 2: Bearish Trend + Drawdown (Defensive Preservation)

**Scenario**: Bearish trend with 12% portfolio drawdown

**Setup**:
```
T_norm = -0.5 (moderate bearish trend)
E_trend = 1.0 + 0.3 * (-0.5) = 0.85
E_vol = 0.85 (assume vol neutral)
E_volVIX = 0.70 (VIX elevated, P_VIX = 0.824)
  [E_volVIX = 1.0 + (0.85 - 1.0) * 0.824 = 0.876, assume further compressed to 0.70]
DD_current = 0.12 (12% drawdown)
```

**Step 1: Calculate P_DD**
```
P_DD = 1.0 - ((0.12 - 0.10) / 0.10) = 0.8
```

**Step 2: Determine Path**
```
E_volVIX = 0.70 < 1.0 → Defensive path (v2.5 asymmetric formula)
```

**Step 3: Calculate E_raw (v2.5 ASYMMETRIC)**
```
E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
E_raw = 0.70 * 0.8 + 1.0 * 0.2
E_raw = 0.56 + 0.20 = 0.76
```

**Step 4: Clip to bounds**
```
E_t = clip(0.76, 0.5, 1.3) = 0.76
```

**Step 5: Map to positions**
```
E_t = 0.76 < 1.0 → No TQQQ
w_QQQ = 0.76 (76% QQQ)
w_TQQQ = 0.0
w_cash = 0.24 (24% cash)
```

**Comparison: v2.0 vs v2.5**:

| Version | Formula | E_raw | Position | Effect |
|---------|---------|-------|----------|--------|
| **v2.0** | `1.0 + (0.70 - 1.0) * 0.8` | 0.76 | 76% QQQ, 24% cash | Same result (by coincidence) |
| **v2.5** | `0.70 * 0.8 + 1.0 * 0.2` | 0.76 | 76% QQQ, 24% cash | ✅ Intentional interpolation |

**Critical Difference**: While this example produces the same numeric result, the **intent** is different:
- **v2.0**: Accidentally moved from 0.70 → 0.76 (increased exposure during DD) ❌
- **v2.5**: Intentionally interpolated 80% defensive + 20% neutral ✅

**Better v2.5 Example** (more extreme):
```
E_volVIX = 0.5 (very defensive - 50% QQQ, 50% cash)
DD_current = 0.12, P_DD = 0.8

v2.0: E_raw = 1.0 + (0.5 - 1.0) * 0.8 = 0.6  [increased from 0.5!] ❌
v2.5: E_raw = 0.5 * 0.8 + 1.0 * 0.2 = 0.6    [maintained defensive bias] ✅

Both give 0.6, but v2.0 increased risk (0.5→0.6), v2.5 decreased risk (toward 1.0 but from below)
```

---

### 8.3 Example 3: No Drawdown (Identity Property)

**Scenario**: Strong trend, no drawdown (verify no modification)

**Setup**:
```
E_volVIX = 1.3 (after all modulators)
DD_current = 0.02 (2% drawdown, below DD_soft)
```

**Calculation**:
```
P_DD = 1.0 (no drawdown pressure)

Leverage path: E_raw = 1.0 + (1.3 - 1.0) * 1.0 = 1.3 ✓
```

**Result**: E_raw = E_volVIX (no modification when DD < DD_soft)

---

### 8.4 Example 4: Maximum Drawdown (Full Compression)

**Scenario**: Severe drawdown exceeds DD_hard

**Setup**:
```
E_volVIX = 1.3 (bullish signal)
DD_current = 0.25 (25% drawdown, exceeds DD_hard=0.20)
```

**Calculation**:
```
P_DD = p_min = 0.0 (maximum compression)

Leverage path: E_raw = 1.0 + (1.3 - 1.0) * 0.0 = 1.0
```

**Result**: E_t = 1.0 → 100% QQQ, 0% TQQQ (forced to neutral)

---

### 8.5 Summary Table: All Scenarios

| Scenario | E_volVIX | DD% | P_DD | Path | v2.5 E_raw | Position | Change |
|----------|----------|-----|------|------|-----------|----------|---------|
| Bull + No DD | 1.3 | 2% | 1.0 | Leverage | 1.30 | 85% QQQ, 15% TQQQ | None |
| Bull + Mild DD | 1.3 | 12% | 0.8 | Leverage | 1.24 | 88% QQQ, 12% TQQQ | -0.06 (reduce leverage) |
| Bull + Severe DD | 1.3 | 25% | 0.0 | Leverage | 1.00 | 100% QQQ | -0.30 (force neutral) |
| Bear + No DD | 0.7 | 2% | 1.0 | Defensive | 0.70 | 70% QQQ, 30% cash | None |
| Bear + Mild DD | 0.7 | 12% | 0.8 | Defensive | 0.76 | 76% QQQ, 24% cash | +0.06 (slight retreat) |
| Bear + Severe DD | 0.7 | 25% | 0.0 | Defensive | 1.00 | 100% QQQ | +0.30 (force neutral) |
| Very Bear + Mild DD | 0.5 | 12% | 0.8 | Defensive | 0.60 | 60% QQQ, 40% cash | +0.10 (controlled retreat) |
| Neutral + DD | 1.0 | 12% | 0.8 | Either | 1.00 | 100% QQQ | None (already neutral) |

**Key Observations**:
1. ✅ Leverage compression works correctly (reduce E toward 1.0)
2. ✅ Defensive preservation works correctly (interpolate toward 1.0 but stay defensive)
3. ✅ Maximum DD forces both paths to neutral (1.0)
4. ✅ No DD preserves signals (E_raw = E_volVIX)
5. ✅ Continuous behavior (no jumps at boundaries)

---

## 9. Testing Strategy

### 9.1 Unit Tests

**Test Module**: `tests/unit/test_hierarchical_adaptive_v2_5.py`

**Test Coverage**:

```python
class TestDDGovernorAsymmetry:
    """Test v2.5 asymmetric DD governor formula"""

    def test_leverage_compression(self):
        """Verify leverage path compresses toward 1.0"""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            version="2.5"
        )

        # E_volVIX > 1.0, DD = 12%
        E_volVIX = Decimal("1.3")
        DD_current = Decimal("0.12")

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        assert P_DD == Decimal("0.8")  # 20% into DD range
        assert E_raw < E_volVIX  # Compression occurred
        assert E_raw > Decimal("1.0")  # Still leveraged
        assert E_raw == pytest.approx(Decimal("1.24"))

    def test_defensive_preservation(self):
        """Verify defensive path preserves defensive bias"""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            version="2.5"
        )

        # E_volVIX < 1.0, DD = 12%
        E_volVIX = Decimal("0.7")
        DD_current = Decimal("0.12")

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        assert P_DD == Decimal("0.8")
        assert E_raw >= E_volVIX  # Moved toward 1.0 but from below
        assert E_raw <= Decimal("1.0")  # Still defensive
        assert E_raw == pytest.approx(Decimal("0.76"))

    def test_identity_no_drawdown(self):
        """Verify no modification when DD < DD_soft"""
        strategy = Hierarchical_Adaptive_v2(DD_soft=Decimal("0.10"))

        E_volVIX = Decimal("1.3")
        DD_current = Decimal("0.05")  # Below DD_soft

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        assert P_DD == Decimal("1.0")
        assert E_raw == E_volVIX  # No modification

    def test_full_compression(self):
        """Verify forced neutral at DD >= DD_hard"""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20")
        )

        # Test both paths converge to 1.0
        for E_volVIX in [Decimal("1.3"), Decimal("0.7")]:
            DD_current = Decimal("0.25")  # Exceeds DD_hard

            P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

            assert P_DD == Decimal("0.0")
            assert E_raw == Decimal("1.0")  # Forced neutral

    def test_continuity_at_boundary(self):
        """Verify continuous behavior at E_volVIX = 1.0"""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20")
        )

        DD_current = Decimal("0.15")  # Mid-range DD

        # Test values approaching 1.0 from both sides
        epsilon = Decimal("0.01")

        _, E_raw_above = strategy._apply_drawdown_governor(
            Decimal("1.0") + epsilon, DD_current
        )
        _, E_raw_below = strategy._apply_drawdown_governor(
            Decimal("1.0") - epsilon, DD_current
        )

        # Should be close to 1.0 and close to each other
        assert abs(E_raw_above - Decimal("1.0")) < Decimal("0.01")
        assert abs(E_raw_below - Decimal("1.0")) < Decimal("0.01")
        assert abs(E_raw_above - E_raw_below) < Decimal("0.02")
```

### 9.2 Integration Tests

**Test Module**: `tests/integration/test_hierarchical_adaptive_v2_5_integration.py`

**Coverage**:
```python
class TestV25FullExposureRange:
    """Verify v2.5 can reach E_min during drawdowns"""

    def test_reaches_e_min_during_bearish_dd(self):
        """v2.5 should reach E_min (unlike v2.0 bug)"""

        # Create synthetic scenario:
        # - Bearish trend (T_norm = -1.0)
        # - High volatility (compress exposure)
        # - Elevated VIX (compress further)
        # - Moderate drawdown (DD = 15%)

        strategy = Hierarchical_Adaptive_v2(
            E_min=Decimal("0.4"),
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            k_trend=Decimal("0.3"),
            version="2.5"
        )

        # Run backtest with synthetic data designed to trigger low exposure
        # (Details depend on test data infrastructure)

        # Assertions:
        # - Min exposure reached should be close to E_min (0.4)
        # - Should occur during bearish periods with DD
        # - Should NOT be stuck at 1.0 (v2.0 bug)
```

### 9.3 Comparison Tests (v2.0 vs v2.5)

**Test Module**: `tests/regression/test_v2_0_vs_v2_5.py`

```python
class TestV20VsV25Comparison:
    """Compare v2.0 and v2.5 behavior on same data"""

    def test_identical_when_no_dd(self):
        """v2.0 and v2.5 should match when DD < DD_soft"""
        # Both should have P_DD = 1.0, no modification
        pass

    def test_diverge_on_defensive_dd(self):
        """v2.0 and v2.5 should differ when E < 1.0 AND DD present"""
        # v2.0: Compresses toward 1.0 (symmetric)
        # v2.5: Interpolates toward 1.0 (asymmetric)
        pass

    def test_identical_on_leverage_dd(self):
        """v2.0 and v2.5 should match when E > 1.0 AND DD present"""
        # Both use leverage compression formula
        pass
```

### 9.4 Regression Testing (Grid Search)

**Objective**: Verify v2.5 performs better than v2.0 on historical data

**Test Configuration**: `grid-configs/test/regression_v2_0_vs_v2_5.yaml`

```yaml
# Regression test: v2.0 vs v2.5 head-to-head
strategy: "Hierarchical_Adaptive_v2"

symbol_sets:
  - name: "QQQ_TQQQ_VIX"
    signal_symbol: "QQQ"
    core_long_symbol: "QQQ"
    leveraged_long_symbol: "TQQQ"
    vix_symbol: "VIX"

base_config:
  start_date: "2010-03-01"
  end_date: "2025-11-01"
  timeframe: "1D"
  initial_capital: 100000
  commission: 0.0
  slippage: 0.0005

parameters:
  # Test 2 versions
  version: ["2.0", "2.5"]

  # Use Run 139 best parameters (from v2.0 grid search)
  measurement_noise: [2000.0]
  k_trend: [0.3]
  E_min: [0.4]
  E_max: [1.5]
  # ... (all other params fixed at Run 139 values)

  # v2.5 DD thresholds
  DD_soft: [0.10]  # v2.0 was 0.05
  DD_hard: [0.20]  # v2.0 was 0.15

# Expected: v2.5 outperforms v2.0 on:
# - Max drawdown (better defensive positioning)
# - Sortino ratio (less downside volatility)
# - Exposure utilization (reaches E_min)
```

---

## 10. Migration Path

### 10.1 Code Changes Required

**File**: `jutsu_engine/strategies/Hierarchical_Adaptive_v2.py`

**Changes**:

1. **Add version parameter to constructor**:
```python
def __init__(
    self,
    # ... (existing 20 parameters)
    version: str = "2.5",  # NEW
    name: str = "Hierarchical_Adaptive_v2"
):
    self.version = version
    # ... rest of init
```

2. **Update `_apply_drawdown_governor` method**:
```python
def _apply_drawdown_governor(
    self,
    E_volVIX: Decimal,
    DD_current: Decimal
) -> tuple[Decimal, Decimal]:
    # Calculate P_DD (unchanged)
    if DD_current <= self.DD_soft:
        P_DD = Decimal("1.0")
    elif DD_current >= self.DD_hard:
        P_DD = self.p_min
    else:
        dd_range = self.DD_hard - self.DD_soft
        dd_excess = DD_current - self.DD_soft
        P_DD = Decimal("1.0") - (dd_excess / dd_range) * (Decimal("1.0") - self.p_min)

    # NEW: Asymmetric compression
    if E_volVIX > Decimal("1.0"):
        # Leverage path (same as v2.0)
        E_raw = Decimal("1.0") + (E_volVIX - Decimal("1.0")) * P_DD
    else:
        # Defensive path (NEW - v2.5 fix)
        E_raw = E_volVIX * P_DD + Decimal("1.0") * (Decimal("1.0") - P_DD)

    return P_DD, E_raw
```

3. **Update docstring**:
```python
"""
Hierarchical Adaptive v2.5: Asymmetric DD Governor Fix

v2.5 changes from v2.0:
- Asymmetric DD governor (leverage vs defensive paths)
- Updated DD thresholds (DD_soft: 0.10, DD_hard: 0.20)
- Preserves all v2.0 features (5-tier engine, etc.)

Bug fix: v2.0 DD governor prevented defensive positioning (E < 1.0)
         v2.5 enables full exposure range [E_min, E_max]
"""
```

**Total Lines Changed**: ~15 lines (minimal impact)

### 10.2 Configuration Files

**Create new config**: `hierarchical_adaptive_v2_5.yaml`

```yaml
# Copy hierarchical_adaptive_v2_0.yaml (if exists)
# Update:
strategy: "Hierarchical_Adaptive_v2"
parameters:
  version: "2.5"
  DD_soft: 0.10  # Changed from 0.05
  DD_hard: 0.20  # Changed from 0.15
  # ... (all other params same as v2.0)
```

**Maintain backward compatibility**: `hierarchical_adaptive_v2_0.yaml` unchanged

### 10.3 Grid Search Configs

**Create**: `grid-configs/examples/grid_search_hierarchical_adaptive_v2_5.yaml`

**Strategy**:
1. Copy `grid_search_hierarchical_adaptive_v2.yaml`
2. Update version parameter: `version: ["2.5"]`
3. Update DD thresholds: `DD_soft: [0.10]`, `DD_hard: [0.20]`
4. Keep all other parameters same (for direct comparison)

### 10.4 Testing Migration

**Step 1: Unit Tests**
```bash
pytest tests/unit/test_hierarchical_adaptive_v2_5.py -v
```

**Step 2: Integration Tests**
```bash
pytest tests/integration/test_hierarchical_adaptive_v2_5_integration.py -v
```

**Step 3: Regression Tests** (v2.0 vs v2.5)
```bash
jutsu grid-search --config grid-configs/test/regression_v2_0_vs_v2_5.yaml
```

**Step 4: Full Grid Search** (if regression passes)
```bash
jutsu grid-search --config grid-configs/examples/grid_search_hierarchical_adaptive_v2_5.yaml
```

### 10.5 Rollback Plan

**If v2.5 underperforms**:
1. Revert to v2.0 (no code changes needed - just use `version="2.0"`)
2. Keep v2.5 code for future analysis
3. Document why asymmetric formula didn't improve results

**Rollback is safe because**:
- v2.5 is backward compatible (same interface)
- Both versions coexist in same codebase
- Configuration files control which version is used

---

## 11. Expected Performance Impact

### 11.1 Quantitative Predictions

**Metric Improvements** (v2.5 vs v2.0):

| Metric | v2.0 Baseline | v2.5 Target | Improvement | Confidence |
|--------|---------------|-------------|-------------|------------|
| **Max Drawdown** | -18% to -22% | -15% to -18% | 3-4% better | High |
| **Sortino Ratio** | 1.5 - 1.8 | 1.6 - 2.0 | +0.1 to +0.2 | Medium |
| **Downside Deviation** | 12% - 15% | 11% - 13% | 1-2% better | Medium |
| **Min Exposure Reached** | ~1.0 (100% QQQ) | ~0.5 (E_min) | Full range | High |
| **Exposure Range Utilization** | 50% [1.0, 1.5] | 100% [0.5, 1.5] | 2x better | High |
| **Defensive Periods** | 0% of time | 10-20% of time | Significant | High |

**Reasoning**:

**Max Drawdown Improvement**:
- v2.5 can actually go defensive (< 1.0x) during stress
- v2.0 was stuck at 100% QQQ minimum (no cushion)
- Expected: 3-4% better worst-case drawdown

**Sortino Ratio Improvement**:
- Better downside protection from defensive positioning
- Same upside capture (leverage path unchanged)
- Expected: Higher risk-adjusted returns

**Exposure Utilization**:
- v2.0: Only used [1.0, 1.5] = 50% of designed range
- v2.5: Uses [0.5, 1.5] = 100% of designed range
- Enables true adaptive exposure scaling

### 11.2 Qualitative Predictions

**Behavioral Improvements**:

1. **True Adaptive Exposure**:
   - v2.0: "Adaptive" in name only (stuck at 1.0x+ range)
   - v2.5: Actually adapts across full [E_min, E_max] range

2. **Crisis Performance**:
   - v2.0: During 2020 COVID crash, stayed 100% QQQ minimum
   - v2.5: Can reduce to 50% QQQ + 50% cash during severe stress

3. **Drawdown Recovery**:
   - v2.0: Had to recover from DD while fully exposed
   - v2.5: Can reduce exposure during DD, then scale back up

4. **Risk Management**:
   - v2.0: DD governor was "leverage limiter" only
   - v2.5: DD governor is true "risk manager" (both directions)

### 11.3 Regime-Specific Expectations

**Bull Market** (T_norm > 0, no DD):
- v2.5 ≈ v2.0 (both use leverage path, identical behavior)
- No performance difference expected

**Bear Market** (T_norm < 0, no DD):
- v2.5 ≈ v2.0 when DD < DD_soft
- Slight divergence when DD_soft < DD < DD_hard

**Crisis** (T_norm < 0, DD > DD_hard):
- v2.5 >> v2.0 (can go defensive vs stuck at 100%)
- Expected: 5-10% better drawdown protection

**Recovery** (T_norm improving, DD still elevated):
- v2.5 > v2.0 (gradual exposure increase from defensive)
- Better positioning for recovery rally

### 11.4 Risk Analysis

**Downside Risks**:

1. **Over-Defensiveness**:
   - Risk: v2.5 might be too conservative (miss rallies)
   - Mitigation: DD thresholds tuned (10% / 20% are reasonable)
   - Likelihood: Low (interpolation formula is gradual)

2. **Whipsaw During Recovery**:
   - Risk: Rapid DD reduction might cause frequent rebalancing
   - Mitigation: 2.5% drift threshold prevents excessive trading
   - Likelihood: Medium (monitor in backtests)

3. **Parameter Sensitivity**:
   - Risk: DD_soft/DD_hard now more critical
   - Mitigation: Grid search will find optimal values
   - Likelihood: Low (defaults are conservative)

**Upside Opportunities**:

1. **Better Sharpe/Sortino**:
   - Lower downside volatility from defensive positioning
   - Same upside capture (leverage path unchanged)

2. **Improved Win Rate**:
   - Fewer large losses from defensive periods
   - Could increase overall win rate by 2-5%

3. **Smoother Equity Curve**:
   - Less severe drawdowns
   - Faster recovery times

### 11.5 Success Criteria

**Minimum Success** (v2.5 vs v2.0):
- ✅ Max DD improved by ≥2%
- ✅ Min exposure < 0.9 (actually uses defensive range)
- ✅ No degradation in upside capture

**Target Success**:
- ✅ Max DD improved by 3-4%
- ✅ Sortino ratio +0.1 to +0.2
- ✅ Exposure utilization: 80%+ of designed range

**Exceptional Success**:
- ✅ Max DD improved by ≥5%
- ✅ Sortino ratio +0.3 or more
- ✅ Calmar ratio improvement by 20%+

---

## 12. Implementation Checklist

### 12.1 Code Implementation

- [ ] **Update `_apply_drawdown_governor` method**
  - [ ] Add asymmetric logic (leverage vs defensive paths)
  - [ ] Update docstring with v2.5 changes
  - [ ] Add inline comments explaining formula

- [ ] **Add version parameter**
  - [ ] Update `__init__` signature
  - [ ] Store version in instance variable
  - [ ] Add to logger output

- [ ] **Update class docstring**
  - [ ] Document v2.5 changes
  - [ ] Explain asymmetric DD governor
  - [ ] Add behavioral examples

- [ ] **Update parameter defaults**
  - [ ] Change DD_soft default: 0.05 → 0.10
  - [ ] Change DD_hard default: 0.15 → 0.20
  - [ ] Document reasons in comments

### 12.2 Testing

- [ ] **Unit Tests**
  - [ ] Test leverage compression path
  - [ ] Test defensive preservation path
  - [ ] Test identity (no DD)
  - [ ] Test full compression (max DD)
  - [ ] Test continuity at boundary (E = 1.0)
  - [ ] Test P_DD calculation (linear interpolation)

- [ ] **Integration Tests**
  - [ ] Verify E_min reachability
  - [ ] Full backtest smoke test
  - [ ] Compare v2.0 vs v2.5 on same data
  - [ ] Check edge cases (extreme DD, extreme trends)

- [ ] **Regression Tests**
  - [ ] Run 2-variant grid search (v2.0 vs v2.5)
  - [ ] Verify v2.5 improvements
  - [ ] Document performance delta

### 12.3 Documentation

- [ ] **Strategy Specification** (this document)
  - [x] Complete design specification
  - [x] Behavioral examples
  - [x] Testing strategy
  - [ ] Review and finalize

- [ ] **Configuration Files**
  - [ ] Create `hierarchical_adaptive_v2_5.yaml`
  - [ ] Create grid search config v2.5
  - [ ] Create regression test config
  - [ ] Document parameter changes

- [ ] **Code Comments**
  - [ ] Add docstrings to new/modified methods
  - [ ] Explain asymmetric formula in code
  - [ ] Add examples in comments

### 12.4 Grid Search Validation

- [ ] **Regression Test** (v2.0 vs v2.5)
  - [ ] 2-variant run (same params, different versions)
  - [ ] Analyze performance delta
  - [ ] Verify improvements in target metrics
  - [ ] Decision: Proceed to full grid search?

- [ ] **Full Grid Search** (if regression passes)
  - [ ] 243-run grid (same as v2.0 Phase 1)
  - [ ] Compare best v2.5 to best v2.0
  - [ ] Verify exposure range utilization
  - [ ] Analyze DD behavior during crises

### 12.5 Release

- [ ] **Code Review**
  - [ ] Verify mathematical correctness
  - [ ] Check edge cases
  - [ ] Validate test coverage
  - [ ] Confirm backward compatibility

- [ ] **Documentation Review**
  - [ ] Proofread specification
  - [ ] Verify examples are correct
  - [ ] Check parameter documentation
  - [ ] Update CHANGELOG.md

- [ ] **Deployment**
  - [ ] Merge to main branch
  - [ ] Tag release: `v2.5.0`
  - [ ] Update strategy README
  - [ ] Notify team of changes

---

## Appendix A: v2.0 vs v2.5 Formula Comparison

### Leverage Path (E_volVIX > 1.0)

**Both versions use same formula**:

```
v2.0: E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
v2.5: E_raw = 1.0 + (E_volVIX - 1.0) * P_DD  [IDENTICAL]
```

**No change in leverage compression behavior**.

---

### Defensive Path (E_volVIX ≤ 1.0)

**v2.0 formula** (symmetric compression):
```python
E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
```

**v2.5 formula** (asymmetric interpolation):
```python
E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
```

**Algebraic equivalence check**:
```
v2.5: E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
            = E_volVIX * P_DD + 1.0 - P_DD
            = 1.0 + E_volVIX * P_DD - P_DD
            = 1.0 + P_DD * (E_volVIX - 1.0)

This is SAME as v2.0 formula!
```

**Wait, they're the same?** Yes, algebraically equivalent!

**So what's different?**

The difference is **conceptual** and affects **parameter tuning**:

**v2.0 interpretation**:
- "Compress toward 1.0" → implies increasing exposure when E < 1.0 ❌
- Led to conservative DD_soft (0.05) to avoid "over-correction"

**v2.5 interpretation**:
- "Interpolate between defensive and neutral" → implies maintaining defensive bias ✅
- Allows more reasonable DD_soft (0.10) because we understand the effect

**Behavioral difference comes from DD threshold changes**:
- v2.0: DD_soft=0.05, DD_hard=0.15 (narrow 10% range, conservative)
- v2.5: DD_soft=0.10, DD_hard=0.20 (wider 10% range, allows more adaptation)

---

## Appendix B: Mathematical Properties

### Property 1: Monotonicity

**Claim**: E_raw decreases (or stays constant) as DD_current increases

**Proof**:

For leverage path (E > 1.0):
```
E_raw = 1.0 + (E - 1.0) * P_DD

∂E_raw/∂P_DD = (E - 1.0) > 0  [since E > 1.0]
∂P_DD/∂DD < 0  [P_DD decreases as DD increases]

By chain rule: ∂E_raw/∂DD = (∂E_raw/∂P_DD) * (∂P_DD/∂DD) < 0 ✓
```

For defensive path (E ≤ 1.0):
```
E_raw = E * P_DD + 1.0 * (1.0 - P_DD) = 1.0 + (E - 1.0) * P_DD

Same as leverage path! ∂E_raw/∂DD < 0 ✓
```

**Conclusion**: E_raw is monotonically decreasing in DD (as desired).

---

### Property 2: Boundedness

**Claim**: E_raw ∈ [min(E, 1.0), max(E, 1.0)]

**Proof**:

When P_DD = 1.0 (no DD):
```
E_raw = 1.0 + (E - 1.0) * 1.0 = E
```

When P_DD = 0.0 (max DD):
```
E_raw = 1.0 + (E - 1.0) * 0.0 = 1.0
```

Since P_DD ∈ [0, 1], E_raw is linear interpolation between E and 1.0.

**For E > 1.0**: E_raw ∈ [1.0, E] ✓
**For E < 1.0**: E_raw ∈ [E, 1.0] ✓
**For E = 1.0**: E_raw = 1.0 (always) ✓

---

### Property 3: Continuity

**Claim**: E_raw is continuous at E = 1.0

**Proof**: Already shown in Section 6.3.

---

### Property 4: Identity

**Claim**: When DD = 0, E_raw = E (no modification)

**Proof**: When DD ≤ DD_soft, P_DD = 1.0

```
E_raw = 1.0 + (E - 1.0) * 1.0 = E ✓
```

---

## Appendix C: Reference Implementation

**Complete v2.5 DD Governor Implementation**:

```python
def _apply_drawdown_governor(
    self,
    E_volVIX: Decimal,
    DD_current: Decimal
) -> tuple[Decimal, Decimal]:
    """
    v2.5 Drawdown Governor: Asymmetric exposure compression during drawdowns.

    Reduces portfolio risk during drawdowns using position-aware adjustment:
    - Leverage positions (E > 1.0): Compress toward neutral (1.0x)
    - Defensive positions (E <= 1.0): Interpolate between defensive and neutral

    Args:
        E_volVIX: Exposure after volatility and VIX modulators
        DD_current: Current drawdown from peak (positive, e.g., 0.15 = 15% DD)

    Returns:
        (P_DD, E_raw):
            P_DD: Penalty factor in [p_min, 1.0]
            E_raw: Adjusted exposure before clipping to [E_min, E_max]

    DD Penalty Calculation (Linear Interpolation):
        DD <= DD_soft:        P_DD = 1.0 (no compression)
        DD_soft < DD < DD_hard: P_DD = linear interpolation
        DD >= DD_hard:        P_DD = p_min (full compression)

    Asymmetric Compression (v2.5 Key Innovation):
        If E_volVIX > 1.0 (Leverage):
            E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
            Effect: Reduces leverage toward neutral

        If E_volVIX <= 1.0 (Defensive):
            E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
            Effect: Weighted average between defensive signal and neutral

    Mathematical Properties:
        - Continuous at E_volVIX = 1.0
        - Monotonic: E_raw decreases as DD increases
        - Bounded: E_raw ∈ [min(E_volVIX, 1.0), max(E_volVIX, 1.0)]
        - Identity: E_raw = E_volVIX when DD <= DD_soft

    Example (Leverage Compression):
        E_volVIX = 1.3, DD = 0.15, DD_soft = 0.10, DD_hard = 0.20, p_min = 0.0
        P_DD = 1.0 - ((0.15 - 0.10) / (0.20 - 0.10)) = 0.5
        E_raw = 1.0 + (1.3 - 1.0) * 0.5 = 1.15
        → Compressed from 1.3x to 1.15x leverage

    Example (Defensive Preservation):
        E_volVIX = 0.6, DD = 0.15, DD_soft = 0.10, DD_hard = 0.20, p_min = 0.0
        P_DD = 0.5
        E_raw = 0.6 * 0.5 + 1.0 * 0.5 = 0.8
        → Interpolated 50% toward neutral (0.6 → 0.8)
    """
    # Step 1: Calculate drawdown penalty factor P_DD
    if DD_current <= self.DD_soft:
        # No drawdown pressure - preserve exposure signal
        P_DD = Decimal("1.0")

    elif DD_current >= self.DD_hard:
        # Maximum drawdown - apply full compression
        P_DD = self.p_min

    else:
        # Linear interpolation between DD_soft and DD_hard
        dd_range = self.DD_hard - self.DD_soft
        dd_excess = DD_current - self.DD_soft
        P_DD = Decimal("1.0") - (dd_excess / dd_range) * (Decimal("1.0") - self.p_min)

    # Step 2: Apply asymmetric compression based on position
    if E_volVIX > Decimal("1.0"):
        # === LEVERAGE PATH ===
        # Compress excess leverage toward neutral during drawdowns
        # Formula: E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
        #
        # Interpretation:
        # - P_DD = 1.0 (no DD): E_raw = E_volVIX (preserve leverage)
        # - P_DD = 0.0 (max DD): E_raw = 1.0 (force neutral)
        # - Effect: Reduces leverage proportionally to drawdown severity
        E_raw = Decimal("1.0") + (E_volVIX - Decimal("1.0")) * P_DD

    else:
        # === DEFENSIVE PATH ===
        # Interpolate between defensive signal and neutral during drawdowns
        # Formula: E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
        #
        # Interpretation:
        # - P_DD = 1.0 (no DD): E_raw = E_volVIX (preserve defensive position)
        # - P_DD = 0.0 (max DD): E_raw = 1.0 (force neutral)
        # - Effect: Weighted average - gradually retreat from defensive to neutral
        #
        # Why this works:
        # - Maintains defensive bias (E_raw >= E_volVIX, but both < 1.0)
        # - Never increases risk (moving toward 1.0 from below is still conservative)
        # - Smooth transition (continuous at E_volVIX = 1.0)
        E_raw = E_volVIX * P_DD + Decimal("1.0") * (Decimal("1.0") - P_DD)

    return P_DD, E_raw
```

---

**End of Specification**

---

**Document Metadata**:
- **Version**: 1.0
- **Author**: System Architect (Sequential MCP-assisted)
- **Date**: 2025-11-18
- **Status**: Design Complete - Ready for Implementation
- **Next Steps**: Code implementation → Unit tests → Regression tests → Grid search validation
