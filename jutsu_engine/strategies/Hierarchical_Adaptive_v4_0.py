"""
Hierarchical Adaptive v4.0: Correlation-Aware Regime Allocator with Crisis Alpha

v4.0 introduces three major robustness improvements over v3.5b:

1. **Macro Trend Filter (NEW)**:
   - Uses SMA(200) as "line in the sand" to distinguish Bull Bias vs Bear Bias
   - Contextualizes Sideways regimes: Accumulation (buy dips) vs Distribution (sell rallies)
   - Prevents false signals in prolonged sideways markets (2015, 2022)

2. **Correlation Guard (NEW)**:
   - Monitors SPY/TLT correlation to detect inflation regimes
   - When correlation > 0.2, bonds are NOT safe havens → force Cash
   - Prevents "double down" losses when stocks and bonds fall together (2022)

3. **Crisis Alpha (NEW)**:
   - Activates SQQQ (-3x QQQ) in Cell 6 (Bear/High Vol) for asymmetric downside capture
   - Parameterized weight (10-30%) to balance alpha vs volatility drag
   - Only activated in high-certainty crash regimes

4. **Smart Rebalancing (NEW)**:
   - Variable drift thresholds: 3% (Low Vol) vs 6% (High Vol)
   - Reduces transaction costs in noisy markets
   - Maintains tight bands in stable regimes

Key Architecture:
- Hierarchical Trend: Fast (Kalman) gated by Slow (SMA 50/200) + Macro Bias (SMA 200)
- Volatility Z-Score: Rolling 21-day realized vol vs 126-day baseline
- 6-Cell Allocation Matrix with Contextual Logic
- Correlation Guard: Inflation regime detection (SPY/TLT corr > 0.2)
- Crisis Alpha: SQQQ allocation in Cell 6
- Vol-Crush Override: 15% vol drop in 5 days forces Low state
- Hybrid Leverage: Base weights × leverage_scalar (0.8-1.2)

Performance Targets:
    - Processing Speed: <1ms per bar
    - Memory: O(max_lookback_period)
    - Backtest: 2010-2025 (15 years) in <20 seconds
"""
from decimal import Decimal
from typing import Optional, Dict, Tuple
from datetime import time
import logging
import pandas as pd
import numpy as np

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.technical import sma
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('STRATEGY.HIERARCHICAL_ADAPTIVE_V4_0')


class Hierarchical_Adaptive_v4_0(Hierarchical_Adaptive_v3_5b):
    """
    Hierarchical Adaptive v4.0: Correlation-Aware Regime Allocator with Crisis Alpha

    Extends v3.5b with robustness improvements targeting 2015 chop and 2022 inflation regimes.

    Six-cell allocation system with contextual logic based on Macro Bias and Correlation Guard:

    Regime Grid (3x2):
        | Trend      | Low Vol                           | High Vol                  |
        |------------|-----------------------------------|---------------------------|
        | BullStrong | Aggressive (100% TQQQ)           | Anti-Whipsaw (100% QQQ)   |
        | Sideways   | Contextual (Bull: 50/50 T/SH)    | Defensive (100% Cash)     |
        |            | (Bear: 100% Cash)                 |                           |
        | BearStrong | Hedged (50% SafeHaven + 50% Cash)| Crisis Alpha (40% SH +    |
        |            |                                   | 40% Cash + 20% SQQQ)      |

    Key Features:
    - Macro Trend Filter: SMA(200) distinguishes Bull Bias vs Bear Bias
    - Correlation Guard: Detects inflation regimes (SPY/TLT corr > 0.2) → force Cash
    - Crisis Alpha: SQQQ (-3x) allocation in Cell 6 for downside capture
    - Smart Rebalancing: Variable drift thresholds (3% Low Vol, 6% High Vol)
    - All v3.5b features: Hierarchical trend, hysteresis, vol-crush override

    Example:
        strategy = Hierarchical_Adaptive_v4_0(
            macro_trend_lookback=200,
            corr_lookback=60,
            corr_threshold=Decimal("0.20"),
            crisis_alpha_weight=Decimal("0.20"),
            drift_low_vol=Decimal("0.03"),
            drift_high_vol=Decimal("0.06"),
            ...
        )
    """

    def __init__(
        self,
        # ==================================================================
        # MACRO TREND FILTER (NEW - v4.0)
        # ==================================================================
        macro_trend_lookback: int = 200,

        # ==================================================================
        # CORRELATION GUARD (NEW - v4.0)
        # ==================================================================
        corr_lookback: int = 60,
        corr_symbol_1: str = "SPY",
        corr_symbol_2: str = "TLT",
        corr_threshold: Decimal = Decimal("0.20"),

        # ==================================================================
        # CRISIS ALPHA (NEW - v4.0)
        # ==================================================================
        crisis_short_symbol: str = "SQQQ",
        crisis_alpha_weight: Decimal = Decimal("0.20"),

        # ==================================================================
        # SMART REBALANCING (NEW - v4.0)
        # ==================================================================
        drift_low_vol: Decimal = Decimal("0.03"),
        drift_high_vol: Decimal = Decimal("0.06"),

        # ==================================================================
        # v3.5b PARAMETERS (Inherited)
        # ==================================================================
        # Kalman Trend
        measurement_noise: Decimal = Decimal("2000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 15,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("50.0"),

        # Structural Trend
        sma_fast: int = 40,
        sma_slow: int = 140,
        t_norm_bull_thresh: Decimal = Decimal("0.2"),
        t_norm_bear_thresh: Decimal = Decimal("-0.3"),

        # Volatility Z-Score
        realized_vol_window: int = 21,
        vol_baseline_window: int = 126,
        upper_thresh_z: Decimal = Decimal("1.0"),
        lower_thresh_z: Decimal = Decimal("0.2"),

        # Vol-Crush Override
        vol_crush_threshold: Decimal = Decimal("-0.15"),
        vol_crush_lookback: int = 5,

        # Allocation
        leverage_scalar: Decimal = Decimal("1.0"),

        # Instrument Toggles
        use_inverse_hedge: bool = False,
        w_PSQ_max: Decimal = Decimal("0.5"),

        # Treasury Overlay
        allow_treasury: bool = True,
        bond_sma_fast: int = 20,
        bond_sma_slow: int = 60,
        max_bond_weight: Decimal = Decimal("0.4"),
        treasury_trend_symbol: str = "TLT",

        # Rebalancing (DEPRECATED in v4.0 - replaced by drift_low_vol/drift_high_vol)
        rebalance_threshold: Decimal = Decimal("0.025"),

        # Execution Timing
        execution_time: str = "close",

        # Symbol Configuration
        signal_symbol: str = "QQQ",
        core_long_symbol: str = "QQQ",
        leveraged_long_symbol: str = "TQQQ",
        inverse_hedge_symbol: str = "PSQ",
        bull_bond_symbol: str = "TMF",
        bear_bond_symbol: str = "TMV",

        # Metadata
        trade_logger: Optional = None,
        name: str = "Hierarchical_Adaptive_v4_0"
    ):
        """
        Initialize Hierarchical Adaptive v4.0 strategy.

        v4.0 introduces correlation-aware regime allocation with macro trend filtering
        and crisis alpha for robust performance across all market regimes.

        Args:
            macro_trend_lookback: SMA period for macro bias (default: 200)
            corr_lookback: Rolling window for correlation calculation (default: 60)
            corr_symbol_1: First symbol for correlation (default: 'SPY')
            corr_symbol_2: Second symbol for correlation (default: 'TLT')
            corr_threshold: Correlation threshold for inflation regime (default: 0.20)
            crisis_short_symbol: Short symbol for crisis alpha (default: 'SQQQ')
            crisis_alpha_weight: SQQQ weight in Cell 6 (default: 0.20 = 20%)
            drift_low_vol: Drift threshold for low vol cells (default: 0.03 = 3%)
            drift_high_vol: Drift threshold for high vol cells (default: 0.06 = 6%)
            [... v3.5b parameters inherited from parent class ...]
        """
        # Validate v4.0-specific parameters
        if macro_trend_lookback < 100:
            raise ValueError(
                f"macro_trend_lookback must be >= 100, got {macro_trend_lookback}"
            )

        if corr_lookback < 20:
            raise ValueError(
                f"corr_lookback must be >= 20, got {corr_lookback}"
            )

        if not (Decimal("0.0") <= corr_threshold <= Decimal("1.0")):
            raise ValueError(
                f"corr_threshold must be in [0.0, 1.0], got {corr_threshold}"
            )

        if not (Decimal("0.0") <= crisis_alpha_weight <= Decimal("0.5")):
            raise ValueError(
                f"crisis_alpha_weight must be in [0.0, 0.5], got {crisis_alpha_weight}"
            )

        if not (Decimal("0.0") < drift_low_vol <= Decimal("0.1")):
            raise ValueError(
                f"drift_low_vol must be in (0.0, 0.1], got {drift_low_vol}"
            )

        if not (Decimal("0.0") < drift_high_vol <= Decimal("0.15")):
            raise ValueError(
                f"drift_high_vol must be in (0.0, 0.15], got {drift_high_vol}"
            )

        if drift_low_vol >= drift_high_vol:
            raise ValueError(
                f"drift_low_vol ({drift_low_vol}) must be < drift_high_vol ({drift_high_vol})"
            )

        # Initialize parent class (v3.5b)
        super().__init__(
            measurement_noise=measurement_noise,
            process_noise_1=process_noise_1,
            process_noise_2=process_noise_2,
            osc_smoothness=osc_smoothness,
            strength_smoothness=strength_smoothness,
            T_max=T_max,
            sma_fast=sma_fast,
            sma_slow=sma_slow,
            t_norm_bull_thresh=t_norm_bull_thresh,
            t_norm_bear_thresh=t_norm_bear_thresh,
            realized_vol_window=realized_vol_window,
            vol_baseline_window=vol_baseline_window,
            upper_thresh_z=upper_thresh_z,
            lower_thresh_z=lower_thresh_z,
            vol_crush_threshold=vol_crush_threshold,
            vol_crush_lookback=vol_crush_lookback,
            leverage_scalar=leverage_scalar,
            use_inverse_hedge=use_inverse_hedge,
            w_PSQ_max=w_PSQ_max,
            allow_treasury=allow_treasury,
            bond_sma_fast=bond_sma_fast,
            bond_sma_slow=bond_sma_slow,
            max_bond_weight=max_bond_weight,
            treasury_trend_symbol=treasury_trend_symbol,
            rebalance_threshold=rebalance_threshold,  # Still passed for parent compatibility
            execution_time=execution_time,
            signal_symbol=signal_symbol,
            core_long_symbol=core_long_symbol,
            leveraged_long_symbol=leveraged_long_symbol,
            inverse_hedge_symbol=inverse_hedge_symbol,
            bull_bond_symbol=bull_bond_symbol,
            bear_bond_symbol=bear_bond_symbol,
            trade_logger=trade_logger,
            name=name
        )

        # Store v4.0-specific parameters
        self.macro_trend_lookback = macro_trend_lookback
        self.corr_lookback = corr_lookback
        self.corr_symbol_1 = corr_symbol_1
        self.corr_symbol_2 = corr_symbol_2
        self.corr_threshold = corr_threshold
        self.crisis_short_symbol = crisis_short_symbol
        self.crisis_alpha_weight = crisis_alpha_weight
        self.drift_low_vol = drift_low_vol
        self.drift_high_vol = drift_high_vol

        # State variables
        self.current_sqqq_weight: Decimal = Decimal("0")
        self.macro_bias: Optional[str] = None  # "bull" or "bear"
        self.inflation_regime: bool = False  # True if correlation > threshold
        self._macro_bias_state = "bear"  # Initial state for hysteresis

        logger.info(
            f"Initialized {name} (v4.0 - CORRELATION-AWARE): "
            f"macro_trend_lookback={macro_trend_lookback}, "
            f"corr_lookback={corr_lookback}, corr_threshold={corr_threshold}, "
            f"crisis_alpha_weight={crisis_alpha_weight}, "
            f"drift_low_vol={drift_low_vol}, drift_high_vol={drift_high_vol}"
        )

    def get_required_warmup_bars(self) -> int:
        """
        Calculate warmup bars needed for Hierarchical Adaptive v4.0 indicators.

        v4.0 adds macro trend filter and correlation guard to v3.5b warmup requirements:
        1. SMA indicators: max(sma_slow, macro_trend_lookback) + buffer (10 bars)
        2. Volatility z-score: vol_baseline_window (126) + realized_vol_window (21)
        3. Bond SMA (if Treasury Overlay enabled): bond_sma_slow
        4. Correlation guard: corr_lookback + vol_realized (for returns calculation)

        Returns:
            int: Maximum lookback required by all indicator systems

        Example:
            With sma_slow=140, macro_trend_lookback=200, vol_baseline=126,
            vol_realized=21, bond_sma_slow=60, corr_lookback=60:
            Returns max(200+10, 126+21, 60, 60+21) = max(210, 147, 60, 81) = 210
        """
        # Calculate lookback for SMA indicators (including macro trend)
        sma_lookback = max(self.sma_slow, self.macro_trend_lookback) + 10

        # Calculate lookback for volatility z-score
        vol_lookback = self.vol_baseline_window + self.realized_vol_window

        # Calculate lookback for bond SMA (if Treasury Overlay enabled)
        bond_lookback = self.bond_sma_slow if self.allow_treasury else 0

        # Calculate lookback for correlation guard (need returns, so +1 for realized_vol_window)
        corr_lookback = self.corr_lookback + self.realized_vol_window

        # Return maximum of all indicator requirements
        required_warmup = max(sma_lookback, vol_lookback, bond_lookback, corr_lookback)

        return required_warmup

    def _calculate_macro_bias(self, symbol: str, lookback: int) -> str:
        """
        Determine Bull Bias vs Bear Bias using SMA(macro_trend_lookback).

        Macro Bias Logic:
        - Bull Bias: Close > SMA(lookback) → Sideways = Accumulation (buy dips)
        - Bear Bias: Close <= SMA(lookback) → Sideways = Distribution (sell rallies)

        Args:
            symbol: Signal symbol (typically QQQ)
            lookback: macro_trend_lookback parameter (typically 200)

        Returns:
            "bull" if Close > SMA(lookback), else "bear"

        Notes:
            - Uses current bar's close price (EOD or intraday based on execution_time)
            - SMA calculation includes historical EOD + current execution-time price
            - Critical for Cell 3 (Sideways/Low) allocation decision
        """
        # Get closes for indicator calculation (historical EOD + current intraday)
        # Need lookback + 10 buffer for SMA calculation
        try:
            closes = self._get_closes_for_indicator_calculation(
                lookback=lookback + 10,
                symbol=symbol,
                current_bar=self._bars[-1]  # Current bar
            )
        except (ValueError, IndexError) as e:
            logger.warning(f"Macro bias calculation failed: {e}, defaulting to 'bear'")
            return "bear"

        if len(closes) < lookback:
            logger.warning(
                f"Insufficient data for macro bias: {len(closes)} < {lookback}, "
                f"defaulting to 'bear'"
            )
            return "bear"

        # Calculate SMA(lookback)
        sma_series = sma(closes, lookback)

        if pd.isna(sma_series.iloc[-1]):
            logger.warning("Macro SMA calculation returned NaN, defaulting to 'bear'")
            return "bear"

        current_close = Decimal(str(closes.iloc[-1]))
        sma_val = Decimal(str(sma_series.iloc[-1]))

        # Implement gray zone hysteresis (3% band)
        bull_threshold = sma_val * Decimal("1.03")   # Switch to bull: Close > SMA200 * 1.03
        bear_threshold = sma_val * Decimal("0.97")   # Switch to bear: Close < SMA200 * 0.97

        if current_close > bull_threshold:
            self._macro_bias_state = "bull"
            return "bull"
        elif current_close < bear_threshold:
            self._macro_bias_state = "bear"
            return "bear"
        else:
            # Gray zone: Stay in previous state
            return self._macro_bias_state

    def _calculate_correlation_guard(
        self,
        symbol1: str,
        symbol2: str,
        lookback: int,
        threshold: Decimal
    ) -> bool:
        """
        Check if Stock/Bond correlation indicates inflation regime.

        Correlation Guard Logic:
        - Normal Regime (corr <= threshold): Bonds are safe haven (TMF/TMV valid)
        - Inflation Regime (corr > threshold): Bonds correlated with stocks → force Cash

        Args:
            symbol1: First correlation symbol (typically SPY)
            symbol2: Second correlation symbol (typically TLT)
            lookback: corr_lookback parameter (typically 60)
            threshold: corr_threshold parameter (typically 0.2)

        Returns:
            True if correlation > threshold (inflation regime, bonds unsafe)
            False otherwise (normal regime, bonds safe)

        Notes:
            - Calculates rolling correlation of daily returns
            - Uses current execution-time prices for latest correlation value
            - Critical for SafeHaven selection in defensive cells (3, 5, 6)
        """
        try:
            # Get price histories for both symbols
            # Need lookback + 1 prices to get lookback returns after pct_change()
            closes1 = self._get_closes_for_indicator_calculation(
                lookback=lookback + 1,
                symbol=symbol1,
                current_bar=self._bars[-1]
            )
            closes2 = self._get_closes_for_indicator_calculation(
                lookback=lookback + 1,
                symbol=symbol2,
                current_bar=self._bars[-1]
            )
        except (ValueError, KeyError) as e:
            logger.warning(
                f"Correlation guard calculation failed: {e}, "
                f"defaulting to inflation regime (unsafe for bonds)"
            )
            return True  # Conservative: assume inflation regime if data unavailable

        if len(closes1) < lookback + 1 or len(closes2) < lookback + 1:
            logger.warning(
                f"Insufficient data for correlation guard: "
                f"{symbol1}={len(closes1)}, {symbol2}={len(closes2)} < {lookback + 1}, "
                f"defaulting to inflation regime"
            )
            return True

        # Calculate daily returns
        returns1 = closes1.pct_change().dropna()
        returns2 = closes2.pct_change().dropna()

        # Align series (in case of mismatched timestamps)
        aligned = pd.DataFrame({
            symbol1: returns1,
            symbol2: returns2
        }).dropna()

        if len(aligned) < lookback:
            logger.warning(
                f"Insufficient aligned data for correlation: {len(aligned)} < {lookback}, "
                f"defaulting to inflation regime"
            )
            return True

        # Take only last lookback returns for both symbols
        if len(aligned) > lookback:
            recent_aligned = aligned.iloc[-lookback:]
        else:
            recent_aligned = aligned

        # Compute correlation between the two return series
        correlation = recent_aligned[symbol1].corr(recent_aligned[symbol2])

        if pd.isna(correlation):
            logger.warning("Correlation calculation returned NaN, defaulting to inflation regime")
            return True

        current_corr = Decimal(str(correlation))

        # Check threshold
        if current_corr > threshold:
            logger.info(
                f"Inflation regime detected: Corr({symbol1}, {symbol2}) = {current_corr:.3f} > {threshold}"
            )
            return True
        else:
            return False

    def _get_safe_haven_with_guard(self, target_weight: Decimal) -> Tuple[Optional[str], Decimal]:
        """
        Select SafeHaven instrument with correlation guard.

        SafeHaven Selection Logic:
        1. Check correlation guard: Is Corr(SPY, TLT) > threshold?
           - YES (Inflation Regime): Force Cash (bonds unsafe)
           - NO (Normal Regime): Use Treasury Overlay (TMF/TMV based on bond trend)
        2. If Normal Regime: Call parent's get_safe_haven_allocation()

        Args:
            target_weight: Desired allocation to SafeHaven (e.g., Decimal("0.5") = 50%)

        Returns:
            (symbol, weight) or (None, Decimal("0")) if forced to cash

        Notes:
            - Called by _get_cell_allocation() for defensive cells (3, 5, 6)
            - Prevents "double down" losses when stocks and bonds fall together
            - Critical for 2022-style inflation regime performance
        """
        # Check correlation guard
        inflation_regime = self._calculate_correlation_guard(
            self.corr_symbol_1,
            self.corr_symbol_2,
            self.corr_lookback,
            self.corr_threshold
        )

        self.inflation_regime = inflation_regime  # Store for external access

        if inflation_regime:
            # Force Cash (return None symbol with 0 weight)
            logger.info(
                f"Correlation guard triggered: Forcing Cash instead of bonds "
                f"(weight={target_weight:.3f})"
            )
            return None, Decimal("0")

        # Normal regime: use treasury overlay logic (existing v3.5b method)
        try:
            # Get TLT closes for bond trend detection
            tlt_closes = self._get_closes_for_indicator_calculation(
                lookback=self.bond_sma_slow + 10,
                symbol=self.treasury_trend_symbol,
                current_bar=self._bars[-1]
            )
        except (ValueError, KeyError) as e:
            logger.warning(f"Could not retrieve TLT data: {e}, falling back to Cash")
            return None, Decimal("0")

        # Call parent's treasury overlay method
        safe_haven = self.get_safe_haven_allocation(tlt_closes, target_weight)

        # Extract bond symbol and weight from safe haven allocation
        if self.bull_bond_symbol in safe_haven and safe_haven[self.bull_bond_symbol] > Decimal("0"):
            return self.bull_bond_symbol, safe_haven[self.bull_bond_symbol]
        elif self.bear_bond_symbol in safe_haven and safe_haven[self.bear_bond_symbol] > Decimal("0"):
            return self.bear_bond_symbol, safe_haven[self.bear_bond_symbol]
        else:
            # Cash allocation (no bonds)
            return None, Decimal("0")

    def _get_cell_allocation(self, cell_id: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """
        Get base allocation weights for cell ID with v4.0 contextual logic.

        6-Cell Allocation Matrix (v4.0 - Robust):
            Cell 1 (Bull/Low):   100% TQQQ (Aggressive, leverage 1.3x via leverage_scalar)
            Cell 2 (Bull/High):  100% QQQ (Anti-Whipsaw, leverage 1.0x)
            Cell 3 (Side/Low):   Contextual based on Macro Bias:
                                 - Bull Bias: 50% TQQQ + 50% SafeHaven (with correlation guard)
                                 - Bear Bias: 100% Cash
            Cell 4 (Side/High):  100% Cash (Defensive, avoid noise)
            Cell 5 (Bear/Low):   50% SafeHaven + 50% Cash (Hedged, with correlation guard)
            Cell 6 (Bear/High):  40% SafeHaven + 40% Cash + 20% SQQQ (Crisis Alpha)
                                 (SafeHaven subject to correlation guard)

        Args:
            cell_id: Cell identifier [1-6]

        Returns:
            (w_TQQQ, w_QQQ, w_PSQ, w_cash) base weights (sum = 1.0)
            Note: SQQQ handled separately in on_bar() execution logic

        Notes:
            - Cell 1: Changed from 60/40 TQQQ/QQQ to 100% TQQQ for max aggression
            - Cell 3: NEW contextual logic based on macro bias
            - Cell 6: Crisis alpha (SQQQ) handled in on_bar(), not here
            - PSQ logic (Cell 6b) inherited from v3.5b but discouraged
        """
        if cell_id == 1:
            # Kill Zone: Maximum aggression
            return (Decimal("1.0"), Decimal("0.0"), Decimal("0.0"), Decimal("0.0"))

        elif cell_id == 2:
            # Fragile Trend: De-risk (same as v3.5b)
            return (Decimal("0.0"), Decimal("1.0"), Decimal("0.0"), Decimal("0.0"))

        elif cell_id == 3:
            # Drift Zone: Contextual based on Macro Bias
            if self.macro_bias == "bull":
                # Bull Bias: Safe accumulation → 50% TQQQ + 50% SafeHaven
                return (Decimal("0.5"), Decimal("0.0"), Decimal("0.0"), Decimal("0.5"))
            else:
                # Bear Bias: Distribution → 100% QQQ (1x to stay in game)
                return (Decimal("0.0"), Decimal("1.0"), Decimal("0.0"), Decimal("0.0"))

        elif cell_id == 4:
            # Chopping Block: Avoid whipsaw (same as v3.5b)
            return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))

        elif cell_id == 5:
            # Grind: Defensive hold → 50% SafeHaven + 50% Cash
            return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))

        elif cell_id == 6:
            # Crash: Crisis Alpha → 40% SafeHaven + 40% Cash + 20% SQQQ
            # Note: SQQQ handled separately, return base Cash allocation here
            if self.use_inverse_hedge:
                # Cell 6b: Use PSQ (inherited from v3.5b, discouraged in v4.0)
                w_PSQ = min(Decimal("0.5"), self.w_PSQ_max)
                w_cash = Decimal("1.0") - w_PSQ
                return (Decimal("0.0"), Decimal("0.0"), w_PSQ, w_cash)
            else:
                # Cell 6a: Use Cash base (SQQQ added in on_bar())
                return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))

        else:
            raise ValueError(f"Invalid cell_id: {cell_id}")

    def _should_rebalance(self, current_allocations: Dict[str, Decimal]) -> bool:
        """
        Determine if rebalancing is needed based on vol-based drift thresholds.

        Smart Rebalancing Logic:
        - Low Vol Cells (1, 3, 5): Use drift_low_vol threshold (default: 3%)
        - High Vol Cells (2, 4, 6): Use drift_high_vol threshold (default: 6%)
        - First Allocation: ALWAYS rebalance (establish initial position)

        Purpose:
        - Reduce transaction costs in noisy markets (wider bands in high vol)
        - Maintain tight control in stable markets (narrow bands in low vol)
        - Ensure first trade executes immediately after warmup

        Args:
            current_allocations: Current target allocations {symbol: weight}

        Returns:
            True if rebalancing needed, False otherwise

        Notes:
            - Replaces single rebalance_threshold from v3.5b
            - Uses self.vol_state to determine current volatility regime
            - Calculates total weight deviation across all positions
            - BUGFIX (2025-01-29): Force rebalance on first allocation
        """
        # Extract target weights from current_allocations
        target_tqqq = current_allocations.get(self.leveraged_long_symbol, Decimal("0"))
        target_qqq = current_allocations.get(self.core_long_symbol, Decimal("0"))
        target_psq = current_allocations.get(self.inverse_hedge_symbol, Decimal("0"))
        target_tmf = current_allocations.get(self.bull_bond_symbol, Decimal("0"))
        target_tmv = current_allocations.get(self.bear_bond_symbol, Decimal("0"))
        target_sqqq = current_allocations.get(self.crisis_short_symbol, Decimal("0"))

        # Check if all current position weights are zero
        all_current_weights_zero = (
            self.current_tqqq_weight == Decimal("0") and
            self.current_qqq_weight == Decimal("0") and
            self.current_psq_weight == Decimal("0") and
            getattr(self, 'current_tmf_weight', Decimal("0")) == Decimal("0") and
            getattr(self, 'current_tmv_weight', Decimal("0")) == Decimal("0") and
            getattr(self, 'current_sqqq_weight', Decimal("0")) == Decimal("0")
        )

        # Check if target allocation includes any positions (not 100% cash)
        target_has_positions = (
            target_tqqq > Decimal("0") or
            target_qqq > Decimal("0") or
            target_psq > Decimal("0") or
            target_tmf > Decimal("0") or
            target_tmv > Decimal("0") or
            target_sqqq > Decimal("0")
        )

        # First allocation: Portfolio at 100% cash + target has positions → ALWAYS rebalance
        # This handles transition from warmup (cash-only) to first real position
        is_first_allocation = all_current_weights_zero and target_has_positions

        if is_first_allocation:
            logger.info("First allocation detected - forcing rebalance to establish initial position")
            return True

        # Determine current vol state for drift threshold
        if self.vol_state == "Low":
            threshold = self.drift_low_vol
        else:  # High vol
            threshold = self.drift_high_vol

        # Calculate drift from current weights
        weight_deviation = (
            abs(self.current_tqqq_weight - target_tqqq) +
            abs(self.current_qqq_weight - target_qqq) +
            abs(self.current_psq_weight - target_psq) +
            abs(getattr(self, 'current_tmf_weight', Decimal("0")) - target_tmf) +
            abs(getattr(self, 'current_tmv_weight', Decimal("0")) - target_tmv) +
            abs(getattr(self, 'current_sqqq_weight', Decimal("0")) - target_sqqq)
        )

        # Return True if drift exceeds threshold
        return weight_deviation > threshold

    def on_bar(self, bar: MarketDataEvent) -> None:
        """
        Process each bar through v4.0 correlation-aware regime allocator.

        Pipeline:
        1. Calculate Kalman trend (T_norm) - Fast signal
        2. Calculate SMA_fast, SMA_slow - Slow structural filter
        3. Calculate Macro Bias (SMA 200) - NEW v4.0
        4. Calculate Correlation Guard (SPY/TLT) - NEW v4.0
        5. Calculate realized volatility and z-score
        6. Apply hysteresis to determine VolState (Low/High)
        7. Check vol-crush override
        8. Classify TrendState (BullStrong/Sideways/BearStrong)
        9. Map to 6-cell allocation matrix with contextual logic
        10. Apply SafeHaven selection with correlation guard
        11. Add Crisis Alpha (SQQQ) for Cell 6
        12. Apply leverage_scalar
        13. Smart rebalance with vol-based thresholds

        Notes:
            - Inherits most logic from v3.5b parent class
            - Overrides Cell 3 and Cell 6 allocation logic
            - Adds macro bias and correlation guard calculations
            - Uses smart rebalancing instead of fixed threshold
        """
        # Only process signal symbol
        if bar.symbol != self.signal_symbol:
            return

        # Warmup period check (count bars for signal_symbol only, not total bars across all symbols)
        min_warmup = self.get_required_warmup_bars()
        signal_bars = [b for b in self._bars if b.symbol == self.signal_symbol]
        if len(signal_bars) < min_warmup:
            logger.debug(f"Warmup: {len(signal_bars)}/{min_warmup} bars for {self.signal_symbol}")
            return

        # BUGFIX (2025-11-29): Reset weight tracking on first trading bar
        # During warmup transition, strategy may execute "rebalance" that sets weight 
        # variables without actual trades. Reset them when trading starts.
        if not hasattr(self, '_trading_started'):
            logger.info("Trading period started - resetting weight tracking")
            self.current_tqqq_weight = Decimal("0")
            self.current_qqq_weight = Decimal("0")
            self.current_psq_weight = Decimal("0")
            self.current_tmf_weight = Decimal("0")
            self.current_tmv_weight = Decimal("0")
            self.current_sqqq_weight = Decimal("0")
            self._trading_started = True

        # 1-2. Calculate Kalman trend and structural trend (inherited from v3.5b)
        # For intraday execution, use current intraday price for Kalman filter
        if self.execution_time == "close":
            kalman_price = bar.close
        else:
            kalman_price = self._get_current_intraday_price(self.signal_symbol, bar)

        filtered_price, trend_strength_signed = self.kalman_filter.update(
            close=kalman_price,
            high=bar.high,
            low=bar.low,
            volume=bar.volume
        )
        T_norm = self._calculate_kalman_trend(Decimal(str(trend_strength_signed)))

        # Calculate structural trend indicators
        required_lookback = max(
            self.sma_slow + 10,
            self.vol_baseline_window + self.realized_vol_window,
            self.macro_trend_lookback + 10,
            self.corr_lookback + self.realized_vol_window
        )

        closes = self._get_closes_for_indicator_calculation(
            lookback=required_lookback,
            symbol=self.signal_symbol,
            current_bar=bar
        )
        sma_fast_series = sma(closes, self.sma_fast)
        sma_slow_series = sma(closes, self.sma_slow)

        if pd.isna(sma_fast_series.iloc[-1]) or pd.isna(sma_slow_series.iloc[-1]):
            logger.warning("SMA calculation returned NaN")
            return

        sma_fast_val = Decimal(str(sma_fast_series.iloc[-1]))
        sma_slow_val = Decimal(str(sma_slow_series.iloc[-1]))

        # 3. Calculate Macro Bias (NEW v4.0)
        self.macro_bias = self._calculate_macro_bias(self.signal_symbol, self.macro_trend_lookback)

        # 4. Calculate Correlation Guard (NEW v4.0)
        # Note: This is called within _get_safe_haven_with_guard(), but we can pre-calculate
        # for logging purposes
        self.inflation_regime = self._calculate_correlation_guard(
            self.corr_symbol_1,
            self.corr_symbol_2,
            self.corr_lookback,
            self.corr_threshold
        )

        # 5-7. Calculate volatility, hysteresis, vol-crush (inherited from v3.5b)
        z_score = self._calculate_volatility_zscore(closes)

        if z_score is None:
            logger.error("Volatility z-score calculation failed - insufficient warmup data")
            return

        self._apply_hysteresis(z_score)
        vol_crush_triggered = self._check_vol_crush_override(closes)

        # 8. Classify trend regime
        trend_state = self._classify_trend_regime(T_norm, sma_fast_val, sma_slow_val)

        # Apply vol-crush override to trend
        if vol_crush_triggered:
            if trend_state == "BearStrong":
                logger.info("Vol-crush override: BearStrong → Sideways")
                trend_state = "Sideways"
            # Vol-crush also forces macro bias to "bull" (implied safe drift)
            self.macro_bias = "bull"

        # 9. Get cell ID and base allocation
        cell_id = self._get_cell_id(trend_state, self.vol_state)
        w_TQQQ, w_QQQ, w_PSQ, w_cash = self._get_cell_allocation(cell_id)

        # Store regime state for external access
        self.trend_state = trend_state
        self.cell_id = cell_id

        # 10. Apply SafeHaven selection with correlation guard for defensive cells
        w_TMF = Decimal("0")
        w_TMV = Decimal("0")
        w_SQQQ = Decimal("0")

        if cell_id == 3 and self.macro_bias == "bull":
            # Cell 3 Bull Bias: 50% TQQQ + 50% SafeHaven
            defensive_weight = Decimal("0.5")
            safe_haven_symbol, safe_haven_weight = self._get_safe_haven_with_guard(defensive_weight)

            if safe_haven_symbol == self.bull_bond_symbol:
                w_TMF = safe_haven_weight
                w_cash = defensive_weight - safe_haven_weight
            elif safe_haven_symbol == self.bear_bond_symbol:
                w_TMV = safe_haven_weight
                w_cash = defensive_weight - safe_haven_weight
            else:
                # Correlation guard forced Cash
                w_cash = defensive_weight

        elif cell_id == 5:
            # Cell 5 (Bear/Low): 50% SafeHaven + 50% Cash
            defensive_weight = Decimal("0.5")
            safe_haven_symbol, safe_haven_weight = self._get_safe_haven_with_guard(defensive_weight)

            if safe_haven_symbol == self.bull_bond_symbol:
                w_TMF = safe_haven_weight
                w_cash = Decimal("0.5") + (defensive_weight - safe_haven_weight)
            elif safe_haven_symbol == self.bear_bond_symbol:
                w_TMV = safe_haven_weight
                w_cash = Decimal("0.5") + (defensive_weight - safe_haven_weight)
            else:
                # Correlation guard forced Cash
                w_cash = Decimal("1.0")

        elif cell_id == 6:
            # Cell 6 (Bear/High): Crisis Alpha
            if self.use_inverse_hedge:
                # PSQ mode (inherited from v3.5b, discouraged in v4.0)
                pass
            else:
                # Crisis Alpha mode: 40% SafeHaven + 40% Cash + 20% SQQQ
                defensive_weight = Decimal("0.4")
                safe_haven_symbol, safe_haven_weight = self._get_safe_haven_with_guard(defensive_weight)

                if safe_haven_symbol == self.bull_bond_symbol:
                    w_TMF = safe_haven_weight
                    w_cash = Decimal("0.4") + (defensive_weight - safe_haven_weight)
                elif safe_haven_symbol == self.bear_bond_symbol:
                    w_TMV = safe_haven_weight
                    w_cash = Decimal("0.4") + (defensive_weight - safe_haven_weight)
                else:
                    # Correlation guard forced Cash
                    w_cash = Decimal("0.8")  # 40% SafeHaven → Cash + 40% base Cash

                # Add Crisis Alpha (SQQQ)
                w_SQQQ = self.crisis_alpha_weight
                w_cash = w_cash - w_SQQQ  # Reduce cash by SQQQ weight

        # 11. Apply leverage_scalar to base weights (but not to bonds/SQQQ - already leveraged)
        w_TQQQ = w_TQQQ * self.leverage_scalar
        w_QQQ = w_QQQ * self.leverage_scalar
        w_PSQ = w_PSQ * self.leverage_scalar

        # 12. Normalize to ensure sum = 1.0
        total_weight = w_TQQQ + w_QQQ + w_PSQ + w_TMF + w_TMV + w_SQQQ + w_cash
        if total_weight > Decimal("0"):
            w_TQQQ = w_TQQQ / total_weight
            w_QQQ = w_QQQ / total_weight
            w_PSQ = w_PSQ / total_weight
            w_TMF = w_TMF / total_weight
            w_TMV = w_TMV / total_weight
            w_SQQQ = w_SQQQ / total_weight
            w_cash = w_cash / total_weight

        # 13. Check smart rebalancing threshold
        current_allocations = {
            self.leveraged_long_symbol: w_TQQQ,
            self.core_long_symbol: w_QQQ,
            self.inverse_hedge_symbol: w_PSQ,
            self.bull_bond_symbol: w_TMF,
            self.bear_bond_symbol: w_TMV,
            self.crisis_short_symbol: w_SQQQ
        }
        needs_rebalance = self._should_rebalance(current_allocations)

        # Log context
        macro_log = f"macro_bias={self.macro_bias}"
        corr_log = f"inflation_regime={self.inflation_regime}"
        sqqq_log = f", w_SQQQ={w_SQQQ:.3f}" if w_SQQQ > Decimal("0") else ""
        treasury_log = ""
        if w_TMF > Decimal("0") or w_TMV > Decimal("0"):
            treasury_log = f", w_TMF={w_TMF:.3f}, w_TMV={w_TMV:.3f}"

        logger.info(
            f"[{bar.timestamp}] v4.0 Regime (Correlation-Aware) | "
            f"T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f}, SMA_slow={sma_slow_val:.2f} → "
            f"TrendState={trend_state} | "
            f"z_score={z_score:.3f} → VolState={self.vol_state} | "
            f"{macro_log}, {corr_log} | "
            f"vol_crush={vol_crush_triggered} | "
            f"Cell={cell_id} → w_TQQQ={w_TQQQ:.3f}, w_QQQ={w_QQQ:.3f}, w_PSQ={w_PSQ:.3f}{treasury_log}{sqqq_log}, "
            f"w_cash={w_cash:.3f} (leverage_scalar={self.leverage_scalar})"
        )

        # Execute rebalance if needed
        if needs_rebalance:
            # Determine threshold used
            threshold = self.drift_low_vol if self.vol_state == "Low" else self.drift_high_vol
            logger.info(
                f"Rebalancing: weights drifted beyond {threshold:.3f} "
                f"(vol-based threshold for {self.vol_state} vol)"
            )

            if self._trade_logger:
                # Log context for all 6 possible positions
                for symbol in [
                    self.core_long_symbol,
                    self.leveraged_long_symbol,
                    self.inverse_hedge_symbol,
                    self.bull_bond_symbol,
                    self.bear_bond_symbol,
                    self.crisis_short_symbol
                ]:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=symbol,
                        strategy_state=f"v4.0 Cell {cell_id}: {trend_state}/{self.vol_state} ({self.macro_bias} bias)",
                        decision_reason=(
                            f"Kalman T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f} vs SMA_slow={sma_slow_val:.2f}, "
                            f"z_score={z_score:.3f}, macro_bias={self.macro_bias}, "
                            f"inflation_regime={self.inflation_regime}, vol_crush={vol_crush_triggered}"
                        ),
                        indicator_values={
                            'T_norm': float(T_norm),
                            'SMA_fast': float(sma_fast_val),
                            'SMA_slow': float(sma_slow_val),
                            'z_score': float(z_score),
                            'macro_bias': 1.0 if self.macro_bias == "bull" else -1.0,
                            'inflation_regime': 1.0 if self.inflation_regime else 0.0
                        },
                        threshold_values={
                            'upper_thresh_z': float(self.upper_thresh_z),
                            'lower_thresh_z': float(self.lower_thresh_z),
                            'leverage_scalar': float(self.leverage_scalar),
                            'corr_threshold': float(self.corr_threshold)
                        }
                    )

            # Execute rebalance with SQQQ support
            self._execute_rebalance_v4(w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_SQQQ)

    def _execute_rebalance_v4(
        self,
        target_tqqq_weight: Decimal,
        target_qqq_weight: Decimal,
        target_psq_weight: Decimal,
        target_tmf_weight: Decimal = Decimal("0"),
        target_tmv_weight: Decimal = Decimal("0"),
        target_sqqq_weight: Decimal = Decimal("0")
    ) -> None:
        """
        Rebalance portfolio to target weights with SQQQ support.

        Extends v3.5b rebalancing to include crisis_short_symbol (SQQQ).

        Phase 1: Reduce positions (execute SELLs first to free cash)
        Phase 2: Increase positions (execute BUYs with freed cash)

        Args:
            target_tqqq_weight: Target TQQQ weight
            target_qqq_weight: Target QQQ weight
            target_psq_weight: Target PSQ weight
            target_tmf_weight: Target TMF weight
            target_tmv_weight: Target TMV weight
            target_sqqq_weight: Target SQQQ weight (NEW v4.0)
        """
        # No validation - let Portfolio simulator handle fractional shares
        # Previous validation using get_closes() failed for symbols not yet processed in multi-symbol flow

        # Phase 1: REDUCE positions (execute SELLs first)

        # TQQQ: Reduce if needed
        if target_tqqq_weight == Decimal("0"):
            self.sell(self.leveraged_long_symbol, Decimal("0.0"))
        elif target_tqqq_weight > Decimal("0") and target_tqqq_weight < self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        # QQQ: Reduce if needed
        if target_qqq_weight == Decimal("0"):
            self.sell(self.core_long_symbol, Decimal("0.0"))
        elif target_qqq_weight > Decimal("0") and target_qqq_weight < self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        # PSQ: Reduce if needed
        if target_psq_weight == Decimal("0"):
            self.sell(self.inverse_hedge_symbol, Decimal("0.0"))
        elif target_psq_weight > Decimal("0") and target_psq_weight < self.current_psq_weight:
            self.buy(self.inverse_hedge_symbol, target_psq_weight)

        # TMF: Reduce if needed
        if target_tmf_weight == Decimal("0"):
            self.sell(self.bull_bond_symbol, Decimal("0.0"))
        elif target_tmf_weight > Decimal("0") and target_tmf_weight < getattr(self, 'current_tmf_weight', Decimal("0")):
            self.buy(self.bull_bond_symbol, target_tmf_weight)

        # TMV: Reduce if needed
        if target_tmv_weight == Decimal("0"):
            self.sell(self.bear_bond_symbol, Decimal("0.0"))
        elif target_tmv_weight > Decimal("0") and target_tmv_weight < getattr(self, 'current_tmv_weight', Decimal("0")):
            self.buy(self.bear_bond_symbol, target_tmv_weight)

        # SQQQ: Reduce if needed (NEW v4.0)
        if target_sqqq_weight == Decimal("0"):
            self.sell(self.crisis_short_symbol, Decimal("0.0"))
        elif target_sqqq_weight > Decimal("0") and target_sqqq_weight < self.current_sqqq_weight:
            self.buy(self.crisis_short_symbol, target_sqqq_weight)

        # Phase 2: INCREASE positions (execute BUYs second)

        # TQQQ: Increase if needed
        if target_tqqq_weight > Decimal("0") and target_tqqq_weight > self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        # QQQ: Increase if needed
        if target_qqq_weight > Decimal("0") and target_qqq_weight > self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        # PSQ: Increase if needed
        if target_psq_weight > Decimal("0") and target_psq_weight > self.current_psq_weight:
            self.buy(self.inverse_hedge_symbol, target_psq_weight)

        # TMF: Increase if needed
        if target_tmf_weight > Decimal("0") and target_tmf_weight > getattr(self, 'current_tmf_weight', Decimal("0")):
            self.buy(self.bull_bond_symbol, target_tmf_weight)

        # TMV: Increase if needed
        if target_tmv_weight > Decimal("0") and target_tmv_weight > getattr(self, 'current_tmv_weight', Decimal("0")):
            self.buy(self.bear_bond_symbol, target_tmv_weight)

        # SQQQ: Increase if needed (NEW v4.0)
        if target_sqqq_weight > Decimal("0") and target_sqqq_weight > self.current_sqqq_weight:
            self.buy(self.crisis_short_symbol, target_sqqq_weight)

        # Update current weights
        self.current_tqqq_weight = target_tqqq_weight
        self.current_qqq_weight = target_qqq_weight
        self.current_psq_weight = target_psq_weight
        self.current_tmf_weight = target_tmf_weight
        self.current_tmv_weight = target_tmv_weight
        self.current_sqqq_weight = target_sqqq_weight

        logger.info(
            f"Executed v4.0 rebalance: TQQQ={target_tqqq_weight:.3f}, "
            f"QQQ={target_qqq_weight:.3f}, PSQ={target_psq_weight:.3f}, "
            f"TMF={target_tmf_weight:.3f}, TMV={target_tmv_weight:.3f}, "
            f"SQQQ={target_sqqq_weight:.3f}"
        )

    def get_current_regime_v4(self) -> dict:
        """
        Get current regime classification with v4.0 context.

        Returns regime state for external analysis including v4.0-specific metrics.

        Returns:
            Dict with regime state:
            - trend_state: "BullStrong", "Sideways", or "BearStrong"
            - vol_state: "Low" or "High"
            - cell_id: 1-6 (regime cell identifier)
            - macro_bias: "bull" or "bear" (NEW v4.0)
            - inflation_regime: bool (NEW v4.0)

        Example:
            regime = strategy.get_current_regime_v4()
            # Returns: {
            #     "trend_state": "BullStrong",
            #     "vol_state": "Low",
            #     "cell_id": 1,
            #     "macro_bias": "bull",
            #     "inflation_regime": False
            # }
        """
        if self.trend_state is None or self.cell_id is None:
            # Not yet initialized
            return {
                "trend_state": "Sideways",
                "vol_state": "Low",
                "cell_id": 3,
                "macro_bias": "bear",
                "inflation_regime": False
            }

        return {
            "trend_state": self.trend_state,
            "vol_state": self.vol_state,
            "cell_id": self.cell_id,
            "macro_bias": self.macro_bias,
            "inflation_regime": self.inflation_regime
        }
