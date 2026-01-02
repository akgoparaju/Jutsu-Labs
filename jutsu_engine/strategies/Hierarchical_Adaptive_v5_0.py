"""
Hierarchical Adaptive v5.0: Tri-Asset Regime Allocator with Precious Metals Overlay

v5.0 extends v3.5b with Commodity-Augmented Regime Strategy:

1. **Hedge Preference Signal** (NEW):
   - Calculates 60-day QQQ/TLT correlation
   - Paper Hedge (Corr < 0.2): Use TMF/TMV for safe haven
   - Hard Hedge (Corr > 0.2): Use GLD/SLV for safe haven
   - Addresses 2022-style inflationary environments where bonds fail

2. **Precious Metals Overlay** (NEW):
   - GLD (Gold) as primary hard asset hedge
   - SLV (Silver) as high-beta commodity kicker
   - Dynamic gold allocation based on commodity momentum

3. **9-Cell Allocation Matrix** (Extended from 6-cell):
   - Cells 1-3: Bull/Neutral with GLD integration
   - Cells 4a/4b: Neutral/High with Paper vs Hard hedge routing
   - Cells 5-6: Bear regime with crisis alpha via GLD/SLV

4. **Silver Momentum Gate** (NEW):
   - SLV only included if outperforming GLD (ROC comparison)
   - Controlled by silver_momentum_gate parameter

Key Architecture (inherited from v3.5b):
- Hierarchical Trend: Fast (Kalman) gated by Slow (SMA 40/140)
- Volatility Z-Score: Rolling 21-day realized vol vs 200-day baseline
- 9-Cell Allocation Matrix: (Trend × Vol × HedgePref) → allocations
- Vol-Crush Override: 15% vol drop in 5 days forces Low state
- Hysteresis State Machine: Prevents regime flicker

Performance Targets:
    - Processing Speed: <2ms per bar (commodity calcs add overhead)
    - Memory: O(max_lookback_period)
    - Backtest: 2010-2025 (15 years) in <30 seconds
"""
from decimal import Decimal
from typing import Optional, Dict, Tuple
from datetime import time
import logging
import pandas as pd
import numpy as np

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.kalman import AdaptiveKalmanFilter, KalmanFilterModel
from jutsu_engine.indicators.technical import sma, annualized_volatility
from jutsu_engine.performance.trade_logger import TradeLogger
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('STRATEGY.HIERARCHICAL_ADAPTIVE_V5_0')

# Execution time mapping (ET market times)
EXECUTION_TIMES = {
    "open": time(9, 30),               # 9:30 AM ET
    "15min_after_open": time(9, 45),   # 9:45 AM ET
    "15min_before_close": time(15, 45), # 3:45 PM ET
    "5min_before_close": time(15, 55),  # 3:55 PM ET
    "close": time(16, 0),               # 4:00 PM ET
}


class Hierarchical_Adaptive_v5_0(Strategy):
    """
    Hierarchical Adaptive v5.0: Tri-Asset Regime Allocator with Precious Metals Overlay

    Nine-cell allocation system combining hierarchical trend (Kalman + SMA)
    with binarized volatility (rolling Z-score with hysteresis) and
    hedge preference signal (QQQ/TLT correlation for Paper vs Hard asset routing).

    Extended Regime Grid (9 cells):
        | Trend      | Vol  | Hedge | Primary       | Defensive/Overlay           |
        |------------|------|-------|---------------|----------------------------|
        | BullStrong | Low  | N/A   | TQQQ 80%      | QQQ 20%                    |
        | BullStrong | High | N/A   | TQQQ 50%      | GLD 20%, Cash 30%          |
        | Sideways   | Low  | N/A   | QQQ 60%       | GLD 40%                    |
        | Sideways   | High | Paper | PSQ 20%       | TMF 80%                    |
        | Sideways   | High | Hard  | PSQ 20%       | GLD 60%, SLV 20%           |
        | BearStrong | Low  | N/A   | PSQ 50%       | TMV 50%                    |
        | BearStrong | High | Paper | Cash 100%     | -                          |
        | BearStrong | High | Hard  | GLD 70%       | SLV 30%                    |
        | Recovery   | Crush| N/A   | TQQQ 100%     | -                          |

    Key Features:
    - Hedge Preference Signal: QQQ/TLT correlation for Paper vs Hard routing
    - Gold Momentum: GLD SMA crossover for commodity trend
    - Silver Relative Strength: SLV vs GLD ROC comparison
    - All v3.5b features: Hysteresis, Vol-Crush, Treasury Overlay (for Paper hedge)

    Example:
        strategy = Hierarchical_Adaptive_v5_0(
            # v3.5b Golden Parameters
            sma_fast=40, sma_slow=140,
            upper_thresh_z=Decimal("1.0"), lower_thresh_z=Decimal("0.2"),
            # v5.0 New Parameters
            hedge_corr_threshold=Decimal("0.20"),
            commodity_ma_period=150,
            gold_weight_max=Decimal("0.60"),
            silver_momentum_gate=True,
        )
    """

    def __init__(
        self,
        # ==================================================================
        # KALMAN TREND PARAMETERS (8 parameters from v3.5b)
        # ==================================================================
        measurement_noise: Decimal = Decimal("3000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 10,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("50.0"),
        symmetric_volume_adjustment: bool = True,
        double_smoothing: bool = False,

        # ==================================================================
        # STRUCTURAL TREND PARAMETERS (4 parameters from v3.5b Golden)
        # ==================================================================
        sma_fast: int = 40,
        sma_slow: int = 140,
        t_norm_bull_thresh: Decimal = Decimal("0.05"),
        t_norm_bear_thresh: Decimal = Decimal("-0.3"),

        # ==================================================================
        # VOLATILITY Z-SCORE PARAMETERS (4 parameters from v3.5b Golden)
        # ==================================================================
        realized_vol_window: int = 21,
        vol_baseline_window: int = 200,
        upper_thresh_z: Decimal = Decimal("1.0"),
        lower_thresh_z: Decimal = Decimal("0.2"),

        # ==================================================================
        # VOL-CRUSH OVERRIDE (2 parameters from v3.5b Golden)
        # ==================================================================
        vol_crush_threshold: Decimal = Decimal("-0.15"),
        vol_crush_lookback: int = 5,

        # ==================================================================
        # ALLOCATION PARAMETERS (2 parameters from v3.5b)
        # ==================================================================
        leverage_scalar: Decimal = Decimal("1.0"),

        # ==================================================================
        # INSTRUMENT TOGGLES (2 parameters from v3.5b)
        # ==================================================================
        use_inverse_hedge: bool = True,
        w_PSQ_max: Decimal = Decimal("0.5"),

        # ==================================================================
        # TREASURY OVERLAY PARAMETERS (5 parameters from v3.5b - Paper Hedge)
        # ==================================================================
        allow_treasury: bool = True,
        bond_sma_fast: int = 20,
        bond_sma_slow: int = 60,
        max_bond_weight: Decimal = Decimal("0.4"),
        treasury_trend_symbol: str = "TLT",

        # ==================================================================
        # HEDGE PREFERENCE SIGNAL (2 parameters - NEW v5.0)
        # ==================================================================
        hedge_corr_threshold: Decimal = Decimal("0.20"),
        hedge_corr_lookback: int = 60,

        # ==================================================================
        # COMMODITY/PRECIOUS METALS OVERLAY (6 parameters - NEW v5.0)
        # ==================================================================
        commodity_ma_period: int = 150,
        gold_weight_max: Decimal = Decimal("0.60"),
        silver_vol_multiplier: Decimal = Decimal("0.5"),
        silver_momentum_lookback: int = 20,
        silver_momentum_gate: bool = True,

        # ==================================================================
        # REBALANCING CONTROL (1 parameter)
        # ==================================================================
        rebalance_threshold: Decimal = Decimal("0.025"),

        # ==================================================================
        # EXECUTION TIMING (1 parameter)
        # ==================================================================
        execution_time: str = "close",

        # ==================================================================
        # SYMBOL CONFIGURATION (8 parameters - Treasury + Commodities)
        # ==================================================================
        signal_symbol: str = "QQQ",
        core_long_symbol: str = "QQQ",
        leveraged_long_symbol: str = "TQQQ",
        inverse_hedge_symbol: str = "PSQ",
        bull_bond_symbol: str = "TMF",
        bear_bond_symbol: str = "TMV",
        gold_symbol: str = "GLD",
        silver_symbol: str = "SLV",

        # ==================================================================
        # METADATA
        # ==================================================================
        trade_logger: Optional[TradeLogger] = None,
        name: str = "Hierarchical_Adaptive_v5_0"
    ):
        """
        Initialize Hierarchical Adaptive v5.0 strategy.

        v5.0 extends v3.5b with Precious Metals Overlay for inflationary environments.

        Args:
            # Kalman Trend Parameters (v3.5b inherited)
            measurement_noise: Kalman filter measurement noise (default: 3000.0)
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            osc_smoothness: Oscillator smoothing period (default: 10)
            strength_smoothness: Trend strength smoothing period (default: 15)
            T_max: Trend normalization threshold (default: 50.0)
            symmetric_volume_adjustment: Enable symmetric volume-based noise adjustment (default: True)
            double_smoothing: Enable double WMA smoothing (default: False)

            # SMA Structure Parameters (v3.5b Golden)
            sma_fast: Fast structural trend SMA period (default: 40)
            sma_slow: Slow structural trend SMA period (default: 140)
            t_norm_bull_thresh: T_norm threshold for BullStrong (default: 0.05)
            t_norm_bear_thresh: T_norm threshold for BearStrong (default: -0.3)

            # Volatility Z-Score Parameters (v3.5b Golden)
            realized_vol_window: Rolling realized vol window (default: 21)
            vol_baseline_window: Volatility baseline window (default: 200)
            upper_thresh_z: Z-score threshold for High vol (default: 1.0)
            lower_thresh_z: Z-score threshold for Low vol (default: 0.2)

            # Vol-Crush Override (v3.5b Golden)
            vol_crush_threshold: Vol-crush percentage threshold (default: -0.15)
            vol_crush_lookback: Vol-crush detection lookback (default: 5)

            # Allocation Parameters
            leverage_scalar: Allocation scaling factor (default: 1.0)
            use_inverse_hedge: Enable PSQ in bearish regimes (default: True)
            w_PSQ_max: Maximum PSQ weight (default: 0.5)

            # Treasury Overlay (Paper Hedge)
            allow_treasury: Enable Treasury Overlay (default: True)
            bond_sma_fast: Fast SMA for bond trend (default: 20)
            bond_sma_slow: Slow SMA for bond trend (default: 60)
            max_bond_weight: Maximum bond allocation (default: 0.4)
            treasury_trend_symbol: Treasury trend symbol (default: 'TLT')

            # Hedge Preference Signal (NEW v5.0)
            hedge_corr_threshold: QQQ/TLT correlation threshold for Paper vs Hard (default: 0.20)
            hedge_corr_lookback: Correlation calculation lookback (default: 60)

            # Commodity/Precious Metals Overlay (NEW v5.0)
            commodity_ma_period: SMA period for GLD trend (default: 150)
            gold_weight_max: Maximum GLD allocation (default: 0.60)
            silver_vol_multiplier: SLV weight as fraction of GLD weight (default: 0.5)
            silver_momentum_lookback: ROC lookback for SLV vs GLD (default: 20)
            silver_momentum_gate: Only use SLV if outperforming GLD (default: True)

            # Symbols
            gold_symbol: Gold ETF symbol (default: 'GLD')
            silver_symbol: Silver ETF symbol (default: 'SLV')

            # Other (inherited)
            rebalance_threshold: Weight drift threshold (default: 0.025)
            execution_time: Fill pricing time (default: 'close')
            trade_logger: Optional TradeLogger
            name: Strategy name
        """
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate execution_time
        valid_execution_times = ["open", "15min_after_open", "15min_before_close", "close"]
        if execution_time not in valid_execution_times:
            raise ValueError(
                f"execution_time must be one of {valid_execution_times}, got: {execution_time}"
            )

        # Validate v3.5b parameters
        if sma_fast >= sma_slow:
            raise ValueError(f"sma_fast ({sma_fast}) must be < sma_slow ({sma_slow})")

        if not (t_norm_bear_thresh < Decimal("0") < t_norm_bull_thresh):
            raise ValueError(
                f"Trend thresholds must satisfy: "
                f"t_norm_bear_thresh ({t_norm_bear_thresh}) < 0 < t_norm_bull_thresh ({t_norm_bull_thresh})"
            )

        if upper_thresh_z <= lower_thresh_z:
            raise ValueError(
                f"upper_thresh_z ({upper_thresh_z}) must be > lower_thresh_z ({lower_thresh_z})"
            )

        if vol_crush_threshold >= Decimal("0"):
            raise ValueError(f"vol_crush_threshold must be negative, got {vol_crush_threshold}")

        if not (Decimal("0.5") <= leverage_scalar <= Decimal("1.5")):
            raise ValueError(f"leverage_scalar must be in [0.5, 1.5], got {leverage_scalar}")

        if not (Decimal("0.0") < w_PSQ_max <= Decimal("1.0")):
            raise ValueError(f"w_PSQ_max must be in (0, 1], got {w_PSQ_max}")

        if rebalance_threshold <= Decimal("0"):
            raise ValueError(f"rebalance_threshold must be positive, got {rebalance_threshold}")

        if bond_sma_fast >= bond_sma_slow:
            raise ValueError(f"bond_sma_fast ({bond_sma_fast}) must be < bond_sma_slow ({bond_sma_slow})")

        if not (Decimal("0.0") <= max_bond_weight <= Decimal("1.0")):
            raise ValueError(f"max_bond_weight must be in [0.0, 1.0], got {max_bond_weight}")

        # Validate v5.0 parameters
        if not (Decimal("-0.5") <= hedge_corr_threshold <= Decimal("0.9")):
            raise ValueError(f"hedge_corr_threshold must be in [-0.5, 0.9], got {hedge_corr_threshold}")

        if hedge_corr_lookback < 10:
            raise ValueError(f"hedge_corr_lookback must be >= 10, got {hedge_corr_lookback}")

        if commodity_ma_period < 20:
            raise ValueError(f"commodity_ma_period must be >= 20, got {commodity_ma_period}")

        if not (Decimal("0.1") <= gold_weight_max <= Decimal("1.0")):
            raise ValueError(f"gold_weight_max must be in [0.1, 1.0], got {gold_weight_max}")

        if not (Decimal("0.0") <= silver_vol_multiplier <= Decimal("1.0")):
            raise ValueError(f"silver_vol_multiplier must be in [0.0, 1.0], got {silver_vol_multiplier}")

        if silver_momentum_lookback < 5:
            raise ValueError(f"silver_momentum_lookback must be >= 5, got {silver_momentum_lookback}")

        # Store v3.5b parameters
        self.measurement_noise = measurement_noise
        self.process_noise_1 = process_noise_1
        self.process_noise_2 = process_noise_2
        self.osc_smoothness = osc_smoothness
        self.strength_smoothness = strength_smoothness
        self.T_max = T_max
        self.symmetric_volume_adjustment = symmetric_volume_adjustment
        self.double_smoothing = double_smoothing

        self.sma_fast = sma_fast
        self.sma_slow = sma_slow
        self.t_norm_bull_thresh = t_norm_bull_thresh
        self.t_norm_bear_thresh = t_norm_bear_thresh

        self.realized_vol_window = realized_vol_window
        self.vol_baseline_window = vol_baseline_window
        self.upper_thresh_z = upper_thresh_z
        self.lower_thresh_z = lower_thresh_z

        self.vol_crush_threshold = vol_crush_threshold
        self.vol_crush_lookback = vol_crush_lookback

        self.leverage_scalar = leverage_scalar

        self.use_inverse_hedge = use_inverse_hedge
        self.w_PSQ_max = w_PSQ_max

        self.allow_treasury = allow_treasury
        self.bond_sma_fast = bond_sma_fast
        self.bond_sma_slow = bond_sma_slow
        self.max_bond_weight = max_bond_weight
        self.treasury_trend_symbol = treasury_trend_symbol

        # Store v5.0 parameters
        self.hedge_corr_threshold = hedge_corr_threshold
        self.hedge_corr_lookback = hedge_corr_lookback

        self.commodity_ma_period = commodity_ma_period
        self.gold_weight_max = gold_weight_max
        self.silver_vol_multiplier = silver_vol_multiplier
        self.silver_momentum_lookback = silver_momentum_lookback
        self.silver_momentum_gate = silver_momentum_gate

        self.rebalance_threshold = rebalance_threshold
        self.execution_time = execution_time

        # Store symbols
        self.signal_symbol = signal_symbol
        self.core_long_symbol = core_long_symbol
        self.leveraged_long_symbol = leveraged_long_symbol
        self.inverse_hedge_symbol = inverse_hedge_symbol
        self.bull_bond_symbol = bull_bond_symbol
        self.bear_bond_symbol = bear_bond_symbol
        self.gold_symbol = gold_symbol
        self.silver_symbol = silver_symbol

        # State variables
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.vol_state: str = "Low"
        self.trend_state: Optional[str] = None
        self.cell_id: Optional[int] = None
        self.hedge_preference: Optional[str] = None  # "Paper" or "Hard" (NEW v5.0)
        self.current_tqqq_weight: Decimal = Decimal("0")
        self.current_qqq_weight: Decimal = Decimal("0")
        self.current_psq_weight: Decimal = Decimal("0")
        self.current_tmf_weight: Decimal = Decimal("0")
        self.current_tmv_weight: Decimal = Decimal("0")
        self.current_gld_weight: Decimal = Decimal("0")  # NEW v5.0
        self.current_slv_weight: Decimal = Decimal("0")  # NEW v5.0
        self._end_date: Optional = None
        self._data_handler: Optional = None
        self._intraday_price_cache: Dict[Tuple[str, datetime], Decimal] = {}

        logger.info(
            f"Initialized {name} (v5.0 - TRI-ASSET REGIME): "
            f"SMA_fast={sma_fast}, SMA_slow={sma_slow}, "
            f"upper_thresh_z={upper_thresh_z}, lower_thresh_z={lower_thresh_z}, "
            f"hedge_corr_threshold={hedge_corr_threshold}, "
            f"commodity_ma_period={commodity_ma_period}, gold_weight_max={gold_weight_max}, "
            f"silver_momentum_gate={silver_momentum_gate}"
        )

    def init(self) -> None:
        """Initialize strategy state."""
        # Initialize Kalman filter
        self.kalman_filter = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=float(self.measurement_noise),
            process_noise_1=float(self.process_noise_1),
            process_noise_2=float(self.process_noise_2),
            osc_smoothness=self.osc_smoothness,
            strength_smoothness=self.strength_smoothness,
            return_signed=True,
            symmetric_volume_adjustment=self.symmetric_volume_adjustment,
            double_smoothing=self.double_smoothing
        )

        # Initialize state
        self.vol_state = "Low"
        self.trend_state = None
        self.cell_id = None
        self.hedge_preference = None
        self.current_tqqq_weight = Decimal("0")
        self.current_qqq_weight = Decimal("0")
        self.current_psq_weight = Decimal("0")
        self.current_tmf_weight = Decimal("0")
        self.current_tmv_weight = Decimal("0")
        self.current_gld_weight = Decimal("0")
        self.current_slv_weight = Decimal("0")

        # Decision tree tracking for dashboard API
        self._last_t_norm = None
        self._last_z_score = None
        self._last_sma_fast = None
        self._last_sma_slow = None
        self._last_vol_crush_triggered = False
        self._last_bond_sma_fast = None
        self._last_bond_sma_slow = None
        self._last_bond_trend = None
        self._last_qqq_tlt_corr = None  # NEW v5.0
        self._last_gold_momentum = None  # NEW v5.0
        self._last_silver_relative_strength = None  # NEW v5.0

        logger.info(f"Initialized {self.name} (v5.0) with hysteresis state: {self.vol_state}")

    def get_required_warmup_bars(self) -> int:
        """
        Calculate warmup bars needed for v5.0 indicators.

        v5.0 adds commodity indicators that may require additional warmup:
        - commodity_ma_period for GLD trend
        - hedge_corr_lookback for QQQ/TLT correlation
        - silver_momentum_lookback for SLV/GLD ROC

        Returns:
            int: Maximum lookback required by all indicator systems
        """
        # v3.5b indicators
        sma_lookback = self.sma_slow + 10
        vol_lookback = self.vol_baseline_window + self.realized_vol_window
        bond_lookback = self.bond_sma_slow if self.allow_treasury else 0

        # v5.0 indicators
        commodity_lookback = self.commodity_ma_period + 10
        corr_lookback = self.hedge_corr_lookback + 10
        silver_lookback = self.silver_momentum_lookback + 5

        required_warmup = max(
            sma_lookback, vol_lookback, bond_lookback,
            commodity_lookback, corr_lookback, silver_lookback
        )

        return required_warmup

    def set_end_date(self, end_date) -> None:
        """Set the end date for execution timing."""
        from datetime import datetime
        if isinstance(end_date, datetime):
            self._end_date = end_date.date()
        else:
            self._end_date = end_date
        logger.info(f"Strategy end_date set to {self._end_date}")

    def set_data_handler(self, data_handler) -> None:
        """Set the data handler for intraday fill pricing."""
        self._data_handler = data_handler
        logger.info("Strategy data_handler set for intraday execution timing")

    def _is_last_day(self, current_timestamp) -> bool:
        """Check if current bar is on the last day of backtest."""
        if self._end_date is None:
            return False
        return current_timestamp.date() == self._end_date

    def _get_current_intraday_price(self, symbol: str, current_bar: MarketDataEvent) -> Decimal:
        """Fetch intraday price at execution_time for current bar."""
        # Cache check
        cache_key = (symbol, current_bar.timestamp)
        if cache_key in self._intraday_price_cache:
            return self._intraday_price_cache[cache_key]

        if self._data_handler is None:
            return current_bar.close

        try:
            execution_times = {
                "open": time(9, 30),
                "15min_after_open": time(9, 45),
                "15min_before_close": time(15, 45),
            }
            target_time = execution_times.get(self.execution_time)
            if target_time is None:
                return current_bar.close

            intraday_bars = self._data_handler.get_intraday_bars_for_time_window(
                symbol=symbol,
                date=current_bar.timestamp.date(),
                start_time=target_time,
                end_time=target_time,
                interval='15m'
            )

            if not intraday_bars:
                return current_bar.close

            if self.execution_time == "open":
                intraday_price = intraday_bars[0].open
            else:
                intraday_price = intraday_bars[0].close

            self._intraday_price_cache[cache_key] = intraday_price
            return intraday_price

        except Exception as e:
            logger.error(f"Intraday fetch failed for {symbol}: {e}")
            return current_bar.close

    def _get_closes_for_indicator_calculation(
        self,
        lookback: int,
        symbol: str,
        current_bar: MarketDataEvent
    ) -> pd.Series:
        """Get close prices for indicator calculation with intraday current bar."""
        if self.execution_time == "close":
            return self.get_closes(lookback=lookback, symbol=symbol)

        historical_closes = self.get_closes(lookback=lookback - 1, symbol=symbol)
        current_price = self._get_current_intraday_price(symbol, current_bar)
        combined = pd.concat([
            historical_closes,
            pd.Series([current_price], index=[current_bar.timestamp])
        ])
        return combined.iloc[-lookback:]

    # ===== v5.0 NEW INDICATOR METHODS =====

    def _calculate_hedge_preference(self, current_bar: MarketDataEvent) -> str:
        """
        Calculate hedge preference based on QQQ/TLT correlation.

        Correlation Logic:
        - Correlation < hedge_corr_threshold → "Paper" (bonds work as hedge)
        - Correlation >= hedge_corr_threshold → "Hard" (use GLD/SLV)

        The idea: When stocks and bonds move together (positive correlation),
        bonds fail as a hedge (2022 inflationary environment). Switch to gold.

        Returns:
            "Paper" or "Hard"
        """
        try:
            # Get QQQ returns
            qqq_closes = self._get_closes_for_indicator_calculation(
                lookback=self.hedge_corr_lookback + 5,
                symbol=self.signal_symbol,
                current_bar=current_bar
            )
            # Get TLT returns
            tlt_closes = self._get_closes_for_indicator_calculation(
                lookback=self.hedge_corr_lookback + 5,
                symbol=self.treasury_trend_symbol,
                current_bar=current_bar
            )

            if len(qqq_closes) < self.hedge_corr_lookback or len(tlt_closes) < self.hedge_corr_lookback:
                logger.warning("Insufficient data for correlation, defaulting to Paper")
                return "Paper"

            # Calculate daily returns
            qqq_returns = qqq_closes.pct_change().dropna().tail(self.hedge_corr_lookback)
            tlt_returns = tlt_closes.pct_change().dropna().tail(self.hedge_corr_lookback)

            if len(qqq_returns) < 10 or len(tlt_returns) < 10:
                return "Paper"

            # Align series
            common_idx = qqq_returns.index.intersection(tlt_returns.index)
            if len(common_idx) < 10:
                return "Paper"

            qqq_aligned = qqq_returns.loc[common_idx]
            tlt_aligned = tlt_returns.loc[common_idx]

            # Calculate correlation
            correlation = qqq_aligned.corr(tlt_aligned)

            if pd.isna(correlation):
                return "Paper"

            self._last_qqq_tlt_corr = Decimal(str(correlation))

            # Decision
            if Decimal(str(correlation)) >= self.hedge_corr_threshold:
                logger.debug(f"Hedge Preference: HARD (corr={correlation:.3f} >= {self.hedge_corr_threshold})")
                return "Hard"
            else:
                logger.debug(f"Hedge Preference: PAPER (corr={correlation:.3f} < {self.hedge_corr_threshold})")
                return "Paper"

        except Exception as e:
            logger.warning(f"Correlation calculation failed: {e}, defaulting to Paper")
            return "Paper"

    def _calculate_gold_momentum(self, current_bar: MarketDataEvent) -> str:
        """
        Calculate gold momentum (G-Trend) based on GLD SMA.

        Logic:
        - GLD close > SMA(commodity_ma_period) → "Bull" (gold trending up)
        - GLD close <= SMA(commodity_ma_period) → "Bear" (gold trending down)

        Returns:
            "Bull" or "Bear"
        """
        try:
            gld_closes = self._get_closes_for_indicator_calculation(
                lookback=self.commodity_ma_period + 10,
                symbol=self.gold_symbol,
                current_bar=current_bar
            )

            if len(gld_closes) < self.commodity_ma_period:
                logger.warning("Insufficient GLD data for momentum, defaulting to Bear")
                return "Bear"

            gld_sma = gld_closes.rolling(window=self.commodity_ma_period).mean().iloc[-1]
            current_gld = gld_closes.iloc[-1]

            if pd.isna(gld_sma):
                return "Bear"

            self._last_gold_momentum = "Bull" if current_gld > gld_sma else "Bear"

            if current_gld > gld_sma:
                logger.debug(f"Gold Momentum: BULL (GLD={current_gld:.2f} > SMA={gld_sma:.2f})")
                return "Bull"
            else:
                logger.debug(f"Gold Momentum: BEAR (GLD={current_gld:.2f} <= SMA={gld_sma:.2f})")
                return "Bear"

        except Exception as e:
            logger.warning(f"Gold momentum calculation failed: {e}, defaulting to Bear")
            return "Bear"

    def _calculate_silver_relative_strength(self, current_bar: MarketDataEvent) -> bool:
        """
        Calculate silver relative strength (S-Beta) vs gold.

        Logic:
        - If SLV 20-day ROC > GLD 20-day ROC → True (use SLV)
        - Otherwise → False (don't use SLV)

        The silver_momentum_gate parameter controls whether this check is applied.

        Returns:
            True if SLV should be used, False otherwise
        """
        if not self.silver_momentum_gate:
            # Gate disabled, always allow SLV
            self._last_silver_relative_strength = True
            return True

        try:
            slv_closes = self._get_closes_for_indicator_calculation(
                lookback=self.silver_momentum_lookback + 5,
                symbol=self.silver_symbol,
                current_bar=current_bar
            )
            gld_closes = self._get_closes_for_indicator_calculation(
                lookback=self.silver_momentum_lookback + 5,
                symbol=self.gold_symbol,
                current_bar=current_bar
            )

            if len(slv_closes) < self.silver_momentum_lookback + 1:
                self._last_silver_relative_strength = False
                return False
            if len(gld_closes) < self.silver_momentum_lookback + 1:
                self._last_silver_relative_strength = False
                return False

            # Calculate ROC (Rate of Change)
            slv_current = slv_closes.iloc[-1]
            slv_past = slv_closes.iloc[-(self.silver_momentum_lookback + 1)]
            gld_current = gld_closes.iloc[-1]
            gld_past = gld_closes.iloc[-(self.silver_momentum_lookback + 1)]

            if slv_past == 0 or gld_past == 0:
                self._last_silver_relative_strength = False
                return False

            slv_roc = (slv_current - slv_past) / slv_past
            gld_roc = (gld_current - gld_past) / gld_past

            use_slv = slv_roc > gld_roc
            self._last_silver_relative_strength = use_slv

            logger.debug(
                f"Silver Relative Strength: SLV_ROC={slv_roc:.3%}, GLD_ROC={gld_roc:.3%}, "
                f"Use SLV={use_slv}"
            )

            return use_slv

        except Exception as e:
            logger.warning(f"Silver relative strength calculation failed: {e}")
            self._last_silver_relative_strength = False
            return False

    def _get_hard_hedge_allocation(
        self,
        defensive_weight: Decimal,
        current_bar: MarketDataEvent
    ) -> Dict[str, Decimal]:
        """
        Get hard hedge allocation (GLD/SLV) for defensive portion.

        Logic:
        - Calculate GLD base weight (up to gold_weight_max)
        - If silver_momentum_gate passes, add SLV at silver_vol_multiplier
        - Remainder goes to Cash

        Args:
            defensive_weight: Total defensive portion (0.0 to 1.0)
            current_bar: Current market bar

        Returns:
            dict: {"GLD": Decimal, "SLV": Decimal, "CASH": Decimal}
        """
        result = {self.gold_symbol: Decimal("0"), self.silver_symbol: Decimal("0"), "CASH": Decimal("0")}

        # Calculate silver usage
        use_slv = self._calculate_silver_relative_strength(current_bar)

        if use_slv:
            # Split between GLD and SLV based on multiplier
            # e.g., if silver_vol_multiplier = 0.5, then for 60% defensive:
            # GLD gets 60% * 0.67 = 40%, SLV gets 60% * 0.33 = 20%
            slv_ratio = self.silver_vol_multiplier / (Decimal("1") + self.silver_vol_multiplier)
            gld_ratio = Decimal("1") - slv_ratio

            raw_gld_weight = defensive_weight * gld_ratio
            raw_slv_weight = defensive_weight * slv_ratio

            # Apply gold_weight_max cap
            gld_weight = min(raw_gld_weight, self.gold_weight_max)
            # SLV weight proportionally reduced if GLD capped
            if raw_gld_weight > self.gold_weight_max:
                reduction_factor = self.gold_weight_max / raw_gld_weight
                slv_weight = raw_slv_weight * reduction_factor
            else:
                slv_weight = raw_slv_weight

            cash_weight = defensive_weight - gld_weight - slv_weight
        else:
            # No SLV, all GLD (capped)
            gld_weight = min(defensive_weight, self.gold_weight_max)
            slv_weight = Decimal("0")
            cash_weight = defensive_weight - gld_weight

        result[self.gold_symbol] = gld_weight
        result[self.silver_symbol] = slv_weight
        result["CASH"] = max(Decimal("0"), cash_weight)

        logger.debug(
            f"Hard Hedge Allocation: GLD={gld_weight:.3f}, SLV={slv_weight:.3f}, "
            f"Cash={result['CASH']:.3f} (defensive={defensive_weight:.3f})"
        )

        return result

    # ===== v3.5b INHERITED METHODS (with modifications) =====

    def _calculate_kalman_trend(self, trend_strength_signed: Decimal) -> Decimal:
        """Calculate normalized SIGNED Kalman trend."""
        T_norm = trend_strength_signed / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_volatility_zscore(self, closes: pd.Series) -> Optional[Decimal]:
        """Calculate rolling z-score of realized volatility."""
        if len(closes) < self.vol_baseline_window + self.realized_vol_window:
            return None

        vol_series = annualized_volatility(closes, lookback=self.realized_vol_window)

        if len(vol_series) < self.vol_baseline_window:
            return None

        vol_values = vol_series.tail(self.vol_baseline_window)
        if len(vol_values) < self.vol_baseline_window:
            return None

        vol_mean = Decimal(str(vol_values.mean()))
        vol_std = Decimal(str(vol_values.std()))

        if vol_std == Decimal("0"):
            return Decimal("0")

        sigma_t = Decimal(str(vol_series.iloc[-1]))
        z_score = (sigma_t - vol_mean) / vol_std

        return z_score

    def _apply_hysteresis(self, z_score: Decimal) -> None:
        """Apply hysteresis state machine to volatility state."""
        min_warmup = max(self.sma_slow, self.vol_baseline_window) + 20

        if len(self._bars) == min_warmup:
            self.vol_state = "High" if z_score > Decimal("0") else "Low"
            logger.info(f"Initialized VolState: {self.vol_state} (z_score={z_score:.3f})")
            return

        if z_score > self.upper_thresh_z:
            if self.vol_state != "High":
                logger.info(f"VolState transition: {self.vol_state} → High (z={z_score:.3f})")
                self.vol_state = "High"
        elif z_score < self.lower_thresh_z:
            if self.vol_state != "Low":
                logger.info(f"VolState transition: {self.vol_state} → Low (z={z_score:.3f})")
                self.vol_state = "Low"

    def _check_vol_crush_override(self, closes: pd.Series) -> bool:
        """Check for vol-crush override (V-shaped recovery detection)."""
        if len(closes) < self.realized_vol_window + self.vol_crush_lookback:
            return False

        vol_series = annualized_volatility(closes, lookback=self.realized_vol_window)

        if len(vol_series) < self.vol_crush_lookback + 1:
            return False

        sigma_t = Decimal(str(vol_series.iloc[-1]))
        sigma_t_minus_N = Decimal(str(vol_series.iloc[-(self.vol_crush_lookback + 1)]))

        if sigma_t_minus_N == Decimal("0"):
            return False

        vol_change = (sigma_t - sigma_t_minus_N) / sigma_t_minus_N

        if vol_change < self.vol_crush_threshold:
            logger.info(f"Vol-crush override triggered: vol drop {vol_change:.1%}")
            self.vol_state = "Low"
            return True

        return False

    def _classify_trend_regime(
        self,
        T_norm: Decimal,
        sma_fast_val: Decimal,
        sma_slow_val: Decimal
    ) -> str:
        """Classify trend regime using hierarchical logic."""
        is_struct_bull = sma_fast_val > sma_slow_val

        if T_norm > self.t_norm_bull_thresh and is_struct_bull:
            return "BullStrong"
        elif T_norm < self.t_norm_bear_thresh and not is_struct_bull:
            return "BearStrong"
        else:
            return "Sideways"

    def _get_cell_id(self, trend_state: str, vol_state: str) -> int:
        """
        Map (TrendState, VolState) to cell ID (1-6).

        Note: v5.0 uses same 6-cell base as v3.5b, but cells 4 and 6
        have sub-routing based on hedge_preference (Paper vs Hard).

        Cell Mapping:
            1: BullStrong + Low
            2: BullStrong + High
            3: Sideways + Low
            4: Sideways + High (sub-routes to 4a/4b based on hedge)
            5: BearStrong + Low
            6: BearStrong + High (sub-routes to 6a/6b based on hedge)
        """
        if trend_state == "BullStrong":
            return 1 if vol_state == "Low" else 2
        elif trend_state == "Sideways":
            return 3 if vol_state == "Low" else 4
        else:  # BearStrong
            return 5 if vol_state == "Low" else 6

    def _get_cell_allocation_v5(
        self,
        cell_id: int,
        hedge_preference: str,
        current_bar: MarketDataEvent
    ) -> Tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        """
        Get v5.0 allocation weights for cell ID with hedge preference routing.

        v5.0 9-Cell Allocation Matrix:
            Cell 1 (Bull/Low):   80% TQQQ, 20% QQQ
            Cell 2 (Bull/High):  50% TQQQ, 20% GLD, 30% Cash
            Cell 3 (Side/Low):   60% QQQ, 40% GLD
            Cell 4a (Side/High/Paper): 20% PSQ, 80% TMF (paper hedge)
            Cell 4b (Side/High/Hard):  20% PSQ, 60% GLD, 20% SLV (hard hedge)
            Cell 5 (Bear/Low):   50% PSQ, 50% TMV
            Cell 6a (Bear/High/Paper): 100% Cash
            Cell 6b (Bear/High/Hard):  70% GLD, 30% SLV

        Returns:
            (w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash)
        """
        w_TQQQ = Decimal("0")
        w_QQQ = Decimal("0")
        w_PSQ = Decimal("0")
        w_TMF = Decimal("0")
        w_TMV = Decimal("0")
        w_GLD = Decimal("0")
        w_SLV = Decimal("0")
        w_cash = Decimal("0")

        if cell_id == 1:
            # Bull/Low: Aggressive upside with TQQQ
            w_TQQQ = Decimal("0.8")
            w_QQQ = Decimal("0.2")

        elif cell_id == 2:
            # Bull/High: Cautious bull with gold anchor
            w_TQQQ = Decimal("0.5")
            w_GLD = Decimal("0.2")
            w_cash = Decimal("0.3")

        elif cell_id == 3:
            # Sideways/Low: Permanent portfolio mix
            w_QQQ = Decimal("0.6")
            w_GLD = Decimal("0.4")

        elif cell_id == 4:
            # Sideways/High: Route based on hedge preference
            w_PSQ = Decimal("0.2")
            defensive_weight = Decimal("0.8")

            if hedge_preference == "Paper":
                # Paper hedge: Use TMF
                if self.allow_treasury:
                    try:
                        tlt_closes = self._get_closes_for_indicator_calculation(
                            lookback=self.bond_sma_slow + 10,
                            symbol=self.treasury_trend_symbol,
                            current_bar=current_bar
                        )
                        safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)
                        w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                        w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))
                        w_cash = safe_haven.get("CASH", Decimal("0"))
                    except Exception:
                        w_cash = defensive_weight
                else:
                    w_cash = defensive_weight
            else:
                # Hard hedge: Use GLD/SLV
                hard_alloc = self._get_hard_hedge_allocation(defensive_weight, current_bar)
                w_GLD = hard_alloc[self.gold_symbol]
                w_SLV = hard_alloc[self.silver_symbol]
                w_cash = hard_alloc["CASH"]

        elif cell_id == 5:
            # Bear/Low: Orderly decline with PSQ
            w_PSQ = min(Decimal("0.5"), self.w_PSQ_max)
            defensive_weight = Decimal("0.5")

            # Use TMV for orderly decline (rates typically rise in slow bears)
            if self.allow_treasury:
                w_TMV = min(defensive_weight * Decimal("0.8"), self.max_bond_weight)
                w_cash = defensive_weight - w_TMV
            else:
                w_cash = defensive_weight

        elif cell_id == 6:
            # Bear/High: Crisis regime - route based on hedge preference
            if hedge_preference == "Paper":
                # Paper hedge: Maximum safety in crash
                w_cash = Decimal("1.0")
            else:
                # Hard hedge: Black swan / Stagflation with GLD/SLV
                hard_alloc = self._get_hard_hedge_allocation(Decimal("1.0"), current_bar)
                w_GLD = hard_alloc[self.gold_symbol]
                w_SLV = hard_alloc[self.silver_symbol]
                w_cash = hard_alloc["CASH"]

        else:
            raise ValueError(f"Invalid cell_id: {cell_id}")

        return (w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash)

    def get_safe_haven_allocation(
        self,
        tlt_history_series: Optional[pd.Series],
        current_defensive_weight_decimal: Decimal
    ) -> dict[str, Decimal]:
        """
        Determines the optimal defensive mix (Cash + Bonds) based on TLT trend.
        (Inherited from v3.5b for Paper hedge mode)
        """
        if tlt_history_series is None or len(tlt_history_series) < self.bond_sma_slow:
            self._last_bond_sma_fast = None
            self._last_bond_sma_slow = None
            self._last_bond_trend = None
            return {"CASH": current_defensive_weight_decimal}

        sma_fast = tlt_history_series.rolling(window=self.bond_sma_fast).mean().iloc[-1]
        sma_slow = tlt_history_series.rolling(window=self.bond_sma_slow).mean().iloc[-1]

        if pd.isna(sma_fast) or pd.isna(sma_slow):
            self._last_bond_sma_fast = None
            self._last_bond_sma_slow = None
            self._last_bond_trend = None
            return {"CASH": current_defensive_weight_decimal}

        sma_fast_val = Decimal(str(sma_fast))
        sma_slow_val = Decimal(str(sma_slow))
        self._last_bond_sma_fast = sma_fast_val
        self._last_bond_sma_slow = sma_slow_val

        if sma_fast_val > sma_slow_val:
            selected_ticker = self.bull_bond_symbol
            self._last_bond_trend = "Bull"
        else:
            selected_ticker = self.bear_bond_symbol
            self._last_bond_trend = "Bear"

        bond_weight = min(current_defensive_weight_decimal * Decimal("0.4"), self.max_bond_weight)
        cash_weight = current_defensive_weight_decimal - bond_weight

        return {selected_ticker: bond_weight, "CASH": cash_weight}

    def on_bar(self, bar: MarketDataEvent) -> None:
        """
        Process each bar through v5.0 tri-asset regime allocator.

        Pipeline:
        1. Calculate Kalman trend (T_norm) - Fast signal
        2. Calculate SMA_fast, SMA_slow - Slow structural filter
        3. Calculate realized volatility and z-score
        4. Apply hysteresis to determine VolState (Low/High)
        5. Check vol-crush override
        6. Classify TrendState (BullStrong/Sideways/BearStrong)
        7. Calculate Hedge Preference (Paper/Hard) based on QQQ/TLT correlation
        8. Map to 9-cell allocation matrix with hedge routing
        9. Apply leverage_scalar
        10. Rebalance if needed
        """
        # Only process signal symbol
        if bar.symbol != self.signal_symbol:
            return

        # Warmup period check
        min_warmup = self.get_required_warmup_bars()
        if len(self._bars) < min_warmup:
            logger.debug(f"Warmup: {len(self._bars)}/{min_warmup} bars")
            return

        # 1. Calculate Kalman trend
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

        # 2. Calculate structural trend
        sma_lookback = self.sma_slow + 10
        vol_lookback = self.vol_baseline_window + self.realized_vol_window
        required_lookback = max(sma_lookback, vol_lookback)

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

        # 3. Calculate volatility z-score
        z_score = self._calculate_volatility_zscore(closes)

        if z_score is None:
            logger.error("Volatility z-score calculation failed")
            return

        # 4. Apply hysteresis
        self._apply_hysteresis(z_score)

        # 5. Check vol-crush override
        vol_crush_triggered = self._check_vol_crush_override(closes)

        # 6. Classify trend regime
        trend_state = self._classify_trend_regime(T_norm, sma_fast_val, sma_slow_val)

        # Apply vol-crush override to trend
        if vol_crush_triggered:
            if trend_state == "BearStrong":
                logger.info("Vol-crush override: BearStrong → Sideways")
                trend_state = "Sideways"

        # 7. Calculate Hedge Preference (NEW v5.0)
        hedge_preference = self._calculate_hedge_preference(bar)
        gold_momentum = self._calculate_gold_momentum(bar)

        # 8. Get cell ID and allocation
        cell_id = self._get_cell_id(trend_state, self.vol_state)
        (w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash) = \
            self._get_cell_allocation_v5(cell_id, hedge_preference, bar)

        # Store state for external access
        self.trend_state = trend_state
        self.cell_id = cell_id
        self.hedge_preference = hedge_preference
        self._last_t_norm = T_norm
        self._last_z_score = z_score
        self._last_sma_fast = sma_fast_val
        self._last_sma_slow = sma_slow_val
        self._last_vol_crush_triggered = vol_crush_triggered

        # 9. Apply leverage_scalar (to equities only, not commodities or bonds)
        w_TQQQ = w_TQQQ * self.leverage_scalar
        w_QQQ = w_QQQ * self.leverage_scalar
        w_PSQ = w_PSQ * self.leverage_scalar

        # Normalize to ensure sum = 1.0
        total_weight = w_TQQQ + w_QQQ + w_PSQ + w_TMF + w_TMV + w_GLD + w_SLV + w_cash
        if total_weight > Decimal("0"):
            w_TQQQ = w_TQQQ / total_weight
            w_QQQ = w_QQQ / total_weight
            w_PSQ = w_PSQ / total_weight
            w_TMF = w_TMF / total_weight
            w_TMV = w_TMV / total_weight
            w_GLD = w_GLD / total_weight
            w_SLV = w_SLV / total_weight
            w_cash = w_cash / total_weight

        # 10. Check rebalancing threshold
        needs_rebalance = self._check_rebalancing_threshold_v5(
            w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV
        )

        # Log context
        commodity_log = ""
        if w_GLD > Decimal("0") or w_SLV > Decimal("0"):
            commodity_log = f", w_GLD={w_GLD:.3f}, w_SLV={w_SLV:.3f}"
        treasury_log = ""
        if w_TMF > Decimal("0") or w_TMV > Decimal("0"):
            treasury_log = f", w_TMF={w_TMF:.3f}, w_TMV={w_TMV:.3f}"

        logger.info(
            f"[{bar.timestamp}] v5.0 Regime | "
            f"T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f}, SMA_slow={sma_slow_val:.2f} → "
            f"TrendState={trend_state} | "
            f"z_score={z_score:.3f} → VolState={self.vol_state} | "
            f"HedgePref={hedge_preference}, GoldMom={gold_momentum} | "
            f"Cell={cell_id} → w_TQQQ={w_TQQQ:.3f}, w_QQQ={w_QQQ:.3f}, w_PSQ={w_PSQ:.3f}"
            f"{treasury_log}{commodity_log}, w_cash={w_cash:.3f}"
        )

        # Execute rebalance if needed
        if needs_rebalance:
            logger.info(f"Rebalancing: weights drifted beyond {self.rebalance_threshold:.3f}")

            if self._trade_logger:
                for symbol in [
                    self.core_long_symbol, self.leveraged_long_symbol,
                    self.inverse_hedge_symbol, self.bull_bond_symbol, self.bear_bond_symbol,
                    self.gold_symbol, self.silver_symbol
                ]:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=symbol,
                        strategy_state=f"v5.0 Cell {cell_id}: {trend_state}/{self.vol_state}/{hedge_preference}",
                        decision_reason=(
                            f"T_norm={T_norm:.3f}, z={z_score:.3f}, "
                            f"hedge_pref={hedge_preference}, vol_crush={vol_crush_triggered}"
                        ),
                        indicator_values={
                            'T_norm': float(T_norm),
                            'SMA_fast': float(sma_fast_val),
                            'SMA_slow': float(sma_slow_val),
                            'z_score': float(z_score),
                            'qqq_tlt_corr': float(self._last_qqq_tlt_corr) if self._last_qqq_tlt_corr else 0.0
                        },
                        threshold_values={
                            'upper_thresh_z': float(self.upper_thresh_z),
                            'lower_thresh_z': float(self.lower_thresh_z),
                            'hedge_corr_threshold': float(self.hedge_corr_threshold)
                        }
                    )

            self._execute_rebalance_v5(w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV)

    def _check_rebalancing_threshold_v5(
        self,
        target_tqqq_weight: Decimal,
        target_qqq_weight: Decimal,
        target_psq_weight: Decimal,
        target_tmf_weight: Decimal,
        target_tmv_weight: Decimal,
        target_gld_weight: Decimal,
        target_slv_weight: Decimal
    ) -> bool:
        """Check if portfolio weights drifted beyond threshold (v5.0 version)."""
        weight_deviation = (
            abs(self.current_tqqq_weight - target_tqqq_weight) +
            abs(self.current_qqq_weight - target_qqq_weight) +
            abs(self.current_psq_weight - target_psq_weight) +
            abs(self.current_tmf_weight - target_tmf_weight) +
            abs(self.current_tmv_weight - target_tmv_weight) +
            abs(self.current_gld_weight - target_gld_weight) +
            abs(self.current_slv_weight - target_slv_weight)
        )
        return weight_deviation > self.rebalance_threshold

    def _execute_rebalance_v5(
        self,
        target_tqqq_weight: Decimal,
        target_qqq_weight: Decimal,
        target_psq_weight: Decimal,
        target_tmf_weight: Decimal,
        target_tmv_weight: Decimal,
        target_gld_weight: Decimal,
        target_slv_weight: Decimal
    ) -> None:
        """
        Rebalance portfolio to target weights using two-phase execution (v5.0 version).
        """
        def _validate_weight(symbol: str, weight: Decimal) -> Decimal:
            if weight <= Decimal("0"):
                return Decimal("0")
            closes = self.get_closes(lookback=1, symbol=symbol)
            if closes.empty:
                return Decimal("0")
            price = Decimal(str(closes.iloc[-1]))
            if price <= Decimal("0"):
                return Decimal("0")
            portfolio_equity = self._cash
            for sym, qty in self._positions.items():
                if qty > 0:
                    symbol_bars = [b for b in self._bars if b.symbol == sym]
                    if symbol_bars:
                        latest_price = symbol_bars[-1].close
                        portfolio_equity += Decimal(str(qty)) * latest_price
            allocation_value = portfolio_equity * weight
            if allocation_value < price:
                return Decimal("0")
            return weight

        # Validate all weights
        target_tqqq_weight = _validate_weight(self.leveraged_long_symbol, target_tqqq_weight)
        target_qqq_weight = _validate_weight(self.core_long_symbol, target_qqq_weight)
        target_psq_weight = _validate_weight(self.inverse_hedge_symbol, target_psq_weight)
        target_tmf_weight = _validate_weight(self.bull_bond_symbol, target_tmf_weight)
        target_tmv_weight = _validate_weight(self.bear_bond_symbol, target_tmv_weight)
        target_gld_weight = _validate_weight(self.gold_symbol, target_gld_weight)
        target_slv_weight = _validate_weight(self.silver_symbol, target_slv_weight)

        # Phase 1: REDUCE positions (sell first)
        # TQQQ
        if target_tqqq_weight == Decimal("0"):
            self.sell(self.leveraged_long_symbol, Decimal("0.0"))
        elif target_tqqq_weight < self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        # QQQ
        if target_qqq_weight == Decimal("0"):
            self.sell(self.core_long_symbol, Decimal("0.0"))
        elif target_qqq_weight < self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        # PSQ
        if target_psq_weight == Decimal("0"):
            self.sell(self.inverse_hedge_symbol, Decimal("0.0"))
        elif target_psq_weight < self.current_psq_weight:
            self.buy(self.inverse_hedge_symbol, target_psq_weight)

        # TMF
        if target_tmf_weight == Decimal("0"):
            self.sell(self.bull_bond_symbol, Decimal("0.0"))
        elif target_tmf_weight < self.current_tmf_weight:
            self.buy(self.bull_bond_symbol, target_tmf_weight)

        # TMV
        if target_tmv_weight == Decimal("0"):
            self.sell(self.bear_bond_symbol, Decimal("0.0"))
        elif target_tmv_weight < self.current_tmv_weight:
            self.buy(self.bear_bond_symbol, target_tmv_weight)

        # GLD (NEW v5.0)
        if target_gld_weight == Decimal("0"):
            self.sell(self.gold_symbol, Decimal("0.0"))
        elif target_gld_weight < self.current_gld_weight:
            self.buy(self.gold_symbol, target_gld_weight)

        # SLV (NEW v5.0)
        if target_slv_weight == Decimal("0"):
            self.sell(self.silver_symbol, Decimal("0.0"))
        elif target_slv_weight < self.current_slv_weight:
            self.buy(self.silver_symbol, target_slv_weight)

        # Phase 2: INCREASE positions
        if target_tqqq_weight > self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        if target_qqq_weight > self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        if target_psq_weight > self.current_psq_weight:
            self.buy(self.inverse_hedge_symbol, target_psq_weight)

        if target_tmf_weight > self.current_tmf_weight:
            self.buy(self.bull_bond_symbol, target_tmf_weight)

        if target_tmv_weight > self.current_tmv_weight:
            self.buy(self.bear_bond_symbol, target_tmv_weight)

        if target_gld_weight > self.current_gld_weight:
            self.buy(self.gold_symbol, target_gld_weight)

        if target_slv_weight > self.current_slv_weight:
            self.buy(self.silver_symbol, target_slv_weight)

        # Update state
        self.current_tqqq_weight = target_tqqq_weight
        self.current_qqq_weight = target_qqq_weight
        self.current_psq_weight = target_psq_weight
        self.current_tmf_weight = target_tmf_weight
        self.current_tmv_weight = target_tmv_weight
        self.current_gld_weight = target_gld_weight
        self.current_slv_weight = target_slv_weight
