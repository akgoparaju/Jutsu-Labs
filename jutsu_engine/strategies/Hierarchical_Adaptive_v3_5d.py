"""
Hierarchical Adaptive v3.5d: Cell 1 Exit Confirmation Lag

v3.5d extends v3.5b with a single new feature:

**Cell 1 Exit Confirmation Lag**:
- Prevents premature exits from Cell 1 (BullStrong/Low Vol) during brief T_norm dips
- Requires T_norm to stay below bull threshold for N consecutive days before exiting
- Reduces whipsaw behavior in mean-reverting post-2023 market environment
- Configurable via `cell1_exit_confirmation_enabled` and `cell1_exit_confirmation_days`

Key Behavior:
- When DISABLED (default): Identical to v3.5b (exit Cell 1 immediately when T_norm < threshold)
- When ENABLED: Track consecutive days T_norm < threshold, only exit when count >= N
- Only affects exits FROM Cell 1 due to T_norm dropping (trend change)
- Does NOT affect exits due to VolState change (Low → High goes to Cell 2)
- Immediate re-entry to Cell 1 is allowed (no entry confirmation needed)

All other features inherited from v3.5b:
- Binarized Volatility (3x2 Grid)
- Rolling Z-Score Volatility
- Hysteresis State Machine
- Vol-Crush Override
- Treasury Overlay
- Removed SQQQ (Toxic Asset)

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

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.kalman import AdaptiveKalmanFilter, KalmanFilterModel
from jutsu_engine.indicators.technical import sma, annualized_volatility
from jutsu_engine.performance.trade_logger import TradeLogger
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('STRATEGY.HIERARCHICAL_ADAPTIVE_V3_5D')

# Execution time mapping (ET market times)
EXECUTION_TIMES = {
    "open": time(9, 30),               # 9:30 AM ET
    "15min_after_open": time(9, 45),   # 9:45 AM ET
    "15min_before_close": time(15, 45), # 3:45 PM ET
    "5min_before_close": time(15, 55),  # 3:55 PM ET
    "close": time(16, 0),               # 4:00 PM ET
}


class Hierarchical_Adaptive_v3_5d(Strategy):
    """
    Hierarchical Adaptive v3.5d: Cell 1 Exit Confirmation Lag

    Extends v3.5b with configurable exit confirmation for Cell 1 (BullStrong/Low Vol).
    Requires T_norm to stay below bull threshold for N consecutive days before
    transitioning from Cell 1 to Cell 3 (Sideways/Low Vol).

    New Parameters (v3.5d):
        cell1_exit_confirmation_enabled: bool = False
            - When False: Behaves exactly like v3.5b (immediate exit)
            - When True: Requires N consecutive days below threshold
        cell1_exit_confirmation_days: int = 2
            - Number of consecutive days T_norm must be below threshold
            - Only used when cell1_exit_confirmation_enabled = True

    Exit Confirmation Logic:
        - Only applies to exits FROM Cell 1 due to T_norm dropping
        - Does NOT apply to exits due to VolState change (Cell 1 → Cell 2)
        - Counter resets when T_norm goes back above threshold
        - Immediate re-entry to Cell 1 is allowed

    Regime Grid (3x2) - Inherited from v3.5b:
        | Trend      | Low Vol               | High Vol                  |
        |------------|------------------------|---------------------------|
        | BullStrong | Kill Zone (60/40 T/Q) | Fragile (100% QQQ)       |
        | Sideways   | Drift (20/80 T/Q)     | Chop (100% Cash)         |
        | BearStrong | Grind (50/50 Q/Cash)  | Crash (100% Cash or PSQ) |

    Example:
        strategy = Hierarchical_Adaptive_v3_5d(
            cell1_exit_confirmation_enabled=True,
            cell1_exit_confirmation_days=2,
            # ... other v3.5b parameters
        )
    """

    def __init__(
        self,
        # ==================================================================
        # KALMAN TREND PARAMETERS (6 parameters from v2.8)
        # ==================================================================
        measurement_noise: Decimal = Decimal("2000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 15,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("50.0"),
        symmetric_volume_adjustment: bool = False,
        double_smoothing: bool = False,

        # ==================================================================
        # STRUCTURAL TREND PARAMETERS (4 parameters - NEW)
        # ==================================================================
        sma_fast: int = 40,
        sma_slow: int = 140,
        t_norm_bull_thresh: Decimal = Decimal("0.2"),
        t_norm_bear_thresh: Decimal = Decimal("-0.3"),

        # ==================================================================
        # VOLATILITY Z-SCORE PARAMETERS (4 parameters - NEW)
        # ==================================================================
        realized_vol_window: int = 21,
        vol_baseline_window: int = 126,
        upper_thresh_z: Decimal = Decimal("1.0"),
        lower_thresh_z: Decimal = Decimal("0.2"),

        # ==================================================================
        # VOL-CRUSH OVERRIDE (2 parameters - NEW)
        # ==================================================================
        vol_crush_threshold: Decimal = Decimal("-0.15"),
        vol_crush_lookback: int = 5,

        # ==================================================================
        # ALLOCATION PARAMETERS (2 parameters - NEW)
        # ==================================================================
        leverage_scalar: Decimal = Decimal("1.0"),

        # ==================================================================
        # INSTRUMENT TOGGLES (2 parameters - NEW)
        # ==================================================================
        use_inverse_hedge: bool = False,
        w_PSQ_max: Decimal = Decimal("0.5"),

        # ==================================================================
        # TREASURY OVERLAY PARAMETERS (5 parameters - v3.5b Treasury Extension)
        # ==================================================================
        allow_treasury: bool = True,
        bond_sma_fast: int = 20,
        bond_sma_slow: int = 60,
        max_bond_weight: Decimal = Decimal("0.4"),
        treasury_trend_symbol: str = "TLT",

        # ==================================================================
        # CELL 1 EXIT CONFIRMATION PARAMETERS (2 parameters - v3.5d NEW)
        # ==================================================================
        cell1_exit_confirmation_enabled: bool = False,
        cell1_exit_confirmation_days: int = 2,

        # ==================================================================
        # REBALANCING CONTROL (1 parameter)
        # ==================================================================
        rebalance_threshold: Decimal = Decimal("0.025"),

        # ==================================================================
        # EXECUTION TIMING (1 parameter - NEW)
        # ==================================================================
        execution_time: str = "close",

        # ==================================================================
        # SYMBOL CONFIGURATION (7 parameters - Treasury Overlay adds 3 new symbols)
        # ==================================================================
        signal_symbol: str = "QQQ",
        core_long_symbol: str = "QQQ",
        leveraged_long_symbol: str = "TQQQ",
        inverse_hedge_symbol: str = "PSQ",
        bull_bond_symbol: str = "TMF",
        bear_bond_symbol: str = "TMV",

        # ==================================================================
        # METADATA
        # ==================================================================
        trade_logger: Optional[TradeLogger] = None,
        name: str = "Hierarchical_Adaptive_v3_5d"
    ):
        """
        Initialize Hierarchical Adaptive v3.5d strategy.

        v3.5d extends v3.5b with Cell 1 Exit Confirmation Lag feature.

        New Args (v3.5d):
            cell1_exit_confirmation_enabled: Enable exit confirmation lag (default: False)
                When False, strategy behaves exactly like v3.5b.
                When True, requires cell1_exit_confirmation_days consecutive days
                below t_norm_bull_thresh before exiting Cell 1 to Cell 3.
            cell1_exit_confirmation_days: Number of consecutive days required (default: 2)
                Only used when cell1_exit_confirmation_enabled = True.
                Range: [1, 10] - recommended values: 1-5.

        Inherited Args from v3.5b:
            measurement_noise: Kalman filter measurement noise (default: 2000.0)
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            osc_smoothness: Oscillator smoothing period (default: 15)
            strength_smoothness: Trend strength smoothing period (default: 15)
            T_max: Trend normalization threshold (default: 50.0)
            symmetric_volume_adjustment: Enable symmetric volume-based noise adjustment
            double_smoothing: Enable double WMA smoothing for trend strength
            sma_fast: Fast structural trend SMA period (default: 50)
            sma_slow: Slow structural trend SMA period (default: 200)
            t_norm_bull_thresh: T_norm threshold for BullStrong (default: 0.2)
            t_norm_bear_thresh: T_norm threshold for BearStrong (default: -0.3)
            realized_vol_window: Rolling realized vol window (default: 21)
            vol_baseline_window: Volatility baseline statistics window (default: 126)
            upper_thresh_z: Z-score threshold for High vol (default: 1.0)
            lower_thresh_z: Z-score threshold for Low vol (default: 0.2)
            vol_crush_threshold: Vol-crush percentage threshold (default: -0.15)
            vol_crush_lookback: Vol-crush detection lookback period (default: 5)
            leverage_scalar: Allocation scaling factor (default: 1.0)
            use_inverse_hedge: Enable PSQ in bearish regimes (default: False)
            w_PSQ_max: Maximum PSQ weight (default: 0.5)
            allow_treasury: Enable Treasury Overlay (default: True)
            bond_sma_fast: Fast SMA for bond trend detection (default: 20)
            bond_sma_slow: Slow SMA for bond trend detection (default: 60)
            max_bond_weight: Maximum allocation to bond ETFs (default: 0.4)
            treasury_trend_symbol: Symbol for bond trend analysis (default: 'TLT')
            rebalance_threshold: Weight drift threshold for rebalancing (default: 0.025)
            execution_time: When to price fills on last day (default: 'close')
            signal_symbol: Signal generation symbol (default: 'QQQ')
            core_long_symbol: 1x long symbol (default: 'QQQ')
            leveraged_long_symbol: 3x long symbol (default: 'TQQQ')
            inverse_hedge_symbol: -1x short symbol (default: 'PSQ')
            bull_bond_symbol: 3x bull bond symbol (default: 'TMF')
            bear_bond_symbol: 3x bear bond symbol (default: 'TMV')
            trade_logger: Optional TradeLogger (default: None)
            name: Strategy name (default: 'Hierarchical_Adaptive_v3_5d')
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

        # Validate parameters
        if sma_fast >= sma_slow:
            raise ValueError(
                f"sma_fast ({sma_fast}) must be < sma_slow ({sma_slow})"
            )

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
            raise ValueError(
                f"vol_crush_threshold must be negative, got {vol_crush_threshold}"
            )

        if not (Decimal("0.5") <= leverage_scalar <= Decimal("1.5")):
            raise ValueError(
                f"leverage_scalar must be in [0.5, 1.5], got {leverage_scalar}"
            )

        if not (Decimal("0.0") < w_PSQ_max <= Decimal("1.0")):
            raise ValueError(
                f"w_PSQ_max must be in (0, 1], got {w_PSQ_max}"
            )

        if rebalance_threshold <= Decimal("0"):
            raise ValueError(
                f"rebalance_threshold must be positive, got {rebalance_threshold}"
            )

        if bond_sma_fast >= bond_sma_slow:
            raise ValueError(
                f"bond_sma_fast ({bond_sma_fast}) must be < bond_sma_slow ({bond_sma_slow})"
            )

        if not (Decimal("0.0") <= max_bond_weight <= Decimal("1.0")):
            raise ValueError(
                f"max_bond_weight must be in [0.0, 1.0], got {max_bond_weight}"
            )

        # Validate v3.5d-specific parameters
        if cell1_exit_confirmation_days < 1 or cell1_exit_confirmation_days > 10:
            raise ValueError(
                f"cell1_exit_confirmation_days must be in [1, 10], got {cell1_exit_confirmation_days}"
            )

        # Store all parameters
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

        # v3.5d: Cell 1 Exit Confirmation parameters
        self.cell1_exit_confirmation_enabled = cell1_exit_confirmation_enabled
        self.cell1_exit_confirmation_days = cell1_exit_confirmation_days

        self.rebalance_threshold = rebalance_threshold

        self.execution_time = execution_time

        self.signal_symbol = signal_symbol
        self.core_long_symbol = core_long_symbol
        self.leveraged_long_symbol = leveraged_long_symbol
        self.inverse_hedge_symbol = inverse_hedge_symbol
        self.bull_bond_symbol = bull_bond_symbol
        self.bear_bond_symbol = bear_bond_symbol

        # State variables
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.vol_state: str = "Low"  # Hysteresis state (persists across bars)
        self.trend_state: Optional[str] = None  # Current trend state (BullStrong/Sideways/BearStrong)
        self.cell_id: Optional[int] = None  # Current regime cell (1-6)
        self.current_tqqq_weight: Decimal = Decimal("0")
        self.current_qqq_weight: Decimal = Decimal("0")
        self.current_psq_weight: Decimal = Decimal("0")
        self.current_tmf_weight: Decimal = Decimal("0")
        self.current_tmv_weight: Decimal = Decimal("0")
        self._end_date: Optional = None  # Set during init() for last day detection
        self._data_handler: Optional = None  # Set via set_data_handler() for intraday fetching
        self._intraday_price_cache: Dict[Tuple[str, datetime], Decimal] = {}  # Cache intraday prices

        # v3.5d: Cell 1 Exit Confirmation state
        self._cell1_exit_pending_days: int = 0  # Counter for consecutive days below threshold

        logger.info(
            f"Initialized {name} (v3.5d - CELL 1 EXIT CONFIRMATION): "
            f"SMA_fast={sma_fast}, SMA_slow={sma_slow}, "
            f"upper_thresh_z={upper_thresh_z}, lower_thresh_z={lower_thresh_z}, "
            f"leverage_scalar={leverage_scalar}, use_inverse_hedge={use_inverse_hedge}, "
            f"execution_time={execution_time}, "
            f"cell1_exit_confirmation_enabled={cell1_exit_confirmation_enabled}, "
            f"cell1_exit_confirmation_days={cell1_exit_confirmation_days}"
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

        # Initialize hysteresis state
        self.vol_state = "Low"  # Default to Low on startup
        self.current_tqqq_weight = Decimal("0")
        self.current_qqq_weight = Decimal("0")
        self.current_psq_weight = Decimal("0")

        # Initialize regime state for external access (LiveStrategyRunner, RegimePerformanceAnalyzer)
        self.trend_state = None
        self.cell_id = None
        self._last_t_norm = None
        self._last_z_score = None

        # Initialize decision tree tracking attributes (for dashboard API)
        self._last_sma_fast = None
        self._last_sma_slow = None
        self._last_vol_crush_triggered = False
        self._last_bond_sma_fast = None
        self._last_bond_sma_slow = None
        self._last_bond_trend = None

        # v3.5d: Initialize exit confirmation counter
        self._cell1_exit_pending_days = 0

        logger.info(
            f"Initialized {self.name} (v3.5d) with hysteresis state: {self.vol_state}, "
            f"cell1_exit_confirmation: {'ENABLED' if self.cell1_exit_confirmation_enabled else 'DISABLED'}"
        )

    def get_required_warmup_bars(self) -> int:
        """
        Calculate warmup bars needed for Hierarchical Adaptive v3.5d indicators.

        This strategy uses three indicator systems that require warmup:
        1. SMA indicators: sma_slow + buffer (10 bars)
        2. Volatility z-score: vol_baseline_window (126) + realized_vol_window (21)
        3. Bond SMA (if Treasury Overlay enabled): bond_sma_slow

        Returns:
            int: Maximum lookback required by all indicator systems
        """
        # Calculate lookback for SMA indicators
        sma_lookback = self.sma_slow + 10

        # Calculate lookback for volatility z-score
        vol_lookback = self.vol_baseline_window + self.realized_vol_window

        # Calculate lookback for bond SMA (if Treasury Overlay enabled)
        bond_lookback = self.bond_sma_slow if self.allow_treasury else 0

        # Return maximum of all indicator requirements
        required_warmup = max(sma_lookback, vol_lookback, bond_lookback)

        return required_warmup

    def set_end_date(self, end_date) -> None:
        """
        Set the end date for the backtest to enable Portfolio fill pricing.
        """
        from datetime import datetime
        # Convert to date if datetime was passed
        if isinstance(end_date, datetime):
            self._end_date = end_date.date()
        else:
            self._end_date = end_date

        logger.info(f"Strategy end_date set to {self._end_date} for execution timing")

    def set_data_handler(self, data_handler) -> None:
        """
        Set the data handler for Portfolio intraday fill pricing.
        """
        self._data_handler = data_handler
        logger.info("Strategy data_handler set for intraday execution timing")

    def _is_last_day(self, current_timestamp) -> bool:
        """
        Check if current bar is on the last day of backtest.
        """
        if self._end_date is None:
            return False

        return current_timestamp.date() == self._end_date

    def _get_current_intraday_price(self, symbol: str, current_bar: MarketDataEvent) -> Decimal:
        """
        Fetch intraday price at execution_time for current bar.
        """
        # Check cache first
        cache_key = (symbol, current_bar.timestamp)
        if cache_key in self._intraday_price_cache:
            cached_price = self._intraday_price_cache[cache_key]
            return cached_price

        if self._data_handler is None:
            logger.warning(f"No data_handler injected, using EOD close for {symbol}")
            return current_bar.close

        try:
            # Map execution_time to market time (Eastern Time)
            execution_times = {
                "open": time(9, 30),
                "15min_after_open": time(9, 45),
                "15min_before_close": time(15, 45),
            }

            target_time = execution_times.get(self.execution_time)

            if target_time is None:
                logger.error(f"Invalid execution_time: {self.execution_time}")
                return current_bar.close

            # Fetch 15-minute intraday bar at target time
            intraday_bars = self._data_handler.get_intraday_bars_for_time_window(
                symbol=symbol,
                date=current_bar.timestamp.date(),
                start_time=target_time,
                end_time=target_time,
                interval='15m'
            )

            if not intraday_bars:
                logger.warning(
                    f"No intraday data for {symbol} on {current_bar.timestamp.date()} "
                    f"at {target_time}, using EOD close"
                )
                return current_bar.close

            # Select price type based on execution_time
            if self.execution_time == "open":
                intraday_price = intraday_bars[0].open
            else:
                intraday_price = intraday_bars[0].close

            # Cache and return
            self._intraday_price_cache[cache_key] = intraday_price

            return intraday_price

        except Exception as e:
            logger.error(
                f"Intraday fetch failed for {symbol} on {current_bar.timestamp.date()}: {e}, "
                f"using EOD close"
            )
            return current_bar.close

    def _get_closes_for_indicator_calculation(
        self,
        lookback: int,
        symbol: str,
        current_bar: MarketDataEvent
    ) -> pd.Series:
        """
        Get close prices for indicator calculation with intraday current bar.
        """
        # For EOD execution: return pure EOD closes without mixing signal symbol's price
        if self.execution_time == "close":
            return self.get_closes(lookback=lookback, symbol=symbol)

        # For intraday execution: use historical EOD + current intraday price
        historical_closes = self.get_closes(lookback=lookback - 1, symbol=symbol)

        # Get current bar's intraday price for the requested symbol
        current_price = self._get_current_intraday_price(symbol, current_bar)

        # Combine: historical + current
        combined = pd.concat([
            historical_closes,
            pd.Series([current_price], index=[current_bar.timestamp])
        ])

        # Return last lookback values
        return combined.iloc[-lookback:]

    def on_bar(self, bar: MarketDataEvent) -> None:
        """
        Process each bar through v3.5d binarized regime allocator with exit confirmation.

        Pipeline:
        1. Calculate Kalman trend (T_norm) - Fast signal
        2. Calculate SMA_fast, SMA_slow - Slow structural filter
        3. Calculate realized volatility and z-score
        4. Apply hysteresis to determine VolState (Low/High)
        5. Check vol-crush override
        6. Classify TrendState (BullStrong/Sideways/BearStrong)
        6b. (v3.5d) Apply Cell 1 Exit Confirmation if enabled
        7. Map to 6-cell allocation matrix
        8. Apply leverage_scalar
        9. Rebalance if needed
        """
        # Only process signal symbol
        if bar.symbol != self.signal_symbol:
            return

        # Warmup period check
        min_warmup = self.sma_slow + 20
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
            logger.error("Volatility z-score calculation failed - insufficient warmup data")
            return

        # 4. Apply hysteresis to determine VolState
        self._apply_hysteresis(z_score)

        # 5. Check vol-crush override
        vol_crush_triggered = self._check_vol_crush_override(closes)

        # 6. Classify trend regime (raw classification)
        raw_trend_state = self._classify_trend_regime(T_norm, sma_fast_val, sma_slow_val)

        # Apply vol-crush override to trend
        if vol_crush_triggered:
            if raw_trend_state == "BearStrong":
                logger.info("Vol-crush override: BearStrong → Sideways")
                raw_trend_state = "Sideways"

        # 6b. (v3.5d) Apply Cell 1 Exit Confirmation logic
        trend_state = self._apply_cell1_exit_confirmation(
            T_norm=T_norm,
            raw_trend_state=raw_trend_state,
            sma_fast_val=sma_fast_val,
            sma_slow_val=sma_slow_val
        )

        # 7-8. Get cell allocation and apply leverage_scalar
        cell_id = self._get_cell_id(trend_state, self.vol_state)
        w_TQQQ, w_QQQ, w_PSQ, w_cash = self._get_cell_allocation(cell_id)

        # Store regime state for external access (RegimePerformanceAnalyzer, LiveStrategyRunner)
        self.trend_state = trend_state
        self.cell_id = cell_id
        self._last_t_norm = T_norm
        self._last_z_score = z_score

        # Store SMA values and vol-crush for decision tree (dashboard API)
        self._last_sma_fast = sma_fast_val
        self._last_sma_slow = sma_slow_val
        self._last_vol_crush_triggered = vol_crush_triggered

        # 8.4. Always compute bond SMAs for display
        if self.allow_treasury:
            try:
                tlt_closes_for_display = self._get_closes_for_indicator_calculation(
                    lookback=self.bond_sma_slow + 10,
                    symbol=self.treasury_trend_symbol,
                    current_bar=bar
                )
                if tlt_closes_for_display is not None and len(tlt_closes_for_display) >= self.bond_sma_slow:
                    bond_sma_fast = tlt_closes_for_display.rolling(window=self.bond_sma_fast).mean().iloc[-1]
                    bond_sma_slow = tlt_closes_for_display.rolling(window=self.bond_sma_slow).mean().iloc[-1]
                    if not pd.isna(bond_sma_fast) and not pd.isna(bond_sma_slow):
                        self._last_bond_sma_fast = Decimal(str(bond_sma_fast))
                        self._last_bond_sma_slow = Decimal(str(bond_sma_slow))
                        self._last_bond_trend = "Bull" if bond_sma_fast > bond_sma_slow else "Bear"
            except Exception as e:
                logger.debug(f"Could not compute bond SMAs for display: {e}")

        # 8.5. Apply Treasury Overlay to defensive cells (if enabled)
        w_TMF = Decimal("0")
        w_TMV = Decimal("0")

        if self.allow_treasury and cell_id in [4, 5, 6]:
            try:
                tlt_closes = self._get_closes_for_indicator_calculation(
                    lookback=self.bond_sma_slow + 10,
                    symbol=self.treasury_trend_symbol,
                    current_bar=bar
                )
            except (ValueError, KeyError) as e:
                logger.warning(f"Could not retrieve TLT data: {e}, falling back to Cash")
                tlt_closes = None

            if cell_id == 4:
                defensive_weight = Decimal("1.0")
                safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)
                w_cash = safe_haven.get("CASH", Decimal("0"))
                w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))

            elif cell_id == 5:
                defensive_weight = Decimal("0.5")
                safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)
                w_cash = safe_haven.get("CASH", Decimal("0"))
                w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))

            elif cell_id == 6:
                if self.use_inverse_hedge:
                    pass
                else:
                    defensive_weight = Decimal("1.0")
                    safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)
                    w_cash = safe_haven.get("CASH", Decimal("0"))
                    w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                    w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))

        # Apply leverage_scalar to base weights
        w_TQQQ = w_TQQQ * self.leverage_scalar
        w_QQQ = w_QQQ * self.leverage_scalar
        w_PSQ = w_PSQ * self.leverage_scalar

        # Normalize to ensure sum = 1.0
        total_weight = w_TQQQ + w_QQQ + w_PSQ + w_TMF + w_TMV + w_cash
        if total_weight > Decimal("0"):
            w_TQQQ = w_TQQQ / total_weight
            w_QQQ = w_QQQ / total_weight
            w_PSQ = w_PSQ / total_weight
            w_TMF = w_TMF / total_weight
            w_TMV = w_TMV / total_weight
            w_cash = w_cash / total_weight

        # 9. Check rebalancing threshold
        needs_rebalance = self._check_rebalancing_threshold(w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV)

        # Log context
        treasury_log = ""
        if self.allow_treasury and (w_TMF > Decimal("0") or w_TMV > Decimal("0")):
            treasury_log = f", w_TMF={w_TMF:.3f}, w_TMV={w_TMV:.3f}"

        # v3.5d: Add exit confirmation status to log
        exit_confirm_log = ""
        if self.cell1_exit_confirmation_enabled:
            exit_confirm_log = f", exit_pending={self._cell1_exit_pending_days}/{self.cell1_exit_confirmation_days}"

        logger.info(
            f"[{bar.timestamp}] v3.5d Regime (Treasury Overlay={'ON' if self.allow_treasury else 'OFF'}) | "
            f"T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f}, SMA_slow={sma_slow_val:.2f} → "
            f"TrendState={trend_state} | "
            f"z_score={z_score:.3f} → VolState={self.vol_state} (hysteresis) | "
            f"vol_crush={vol_crush_triggered}{exit_confirm_log} | "
            f"Cell={cell_id} → w_TQQQ={w_TQQQ:.3f}, w_QQQ={w_QQQ:.3f}, w_PSQ={w_PSQ:.3f}{treasury_log}, "
            f"w_cash={w_cash:.3f} (leverage_scalar={self.leverage_scalar})"
        )

        # Execute rebalance if needed
        if needs_rebalance:
            logger.info(f"Rebalancing: weights drifted beyond {self.rebalance_threshold:.3f}")

            if self._trade_logger:
                for symbol in [
                    self.core_long_symbol,
                    self.leveraged_long_symbol,
                    self.inverse_hedge_symbol,
                    self.bull_bond_symbol,
                    self.bear_bond_symbol
                ]:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=symbol,
                        strategy_state=f"v3.5d Cell {cell_id}: {trend_state}/{self.vol_state}",
                        decision_reason=(
                            f"Kalman T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f} vs SMA_slow={sma_slow_val:.2f}, "
                            f"z_score={z_score:.3f}, vol_crush={vol_crush_triggered}, "
                            f"exit_pending={self._cell1_exit_pending_days}"
                        ),
                        indicator_values={
                            'T_norm': float(T_norm),
                            'SMA_fast': float(sma_fast_val),
                            'SMA_slow': float(sma_slow_val),
                            'z_score': float(z_score),
                            'cell1_exit_pending_days': self._cell1_exit_pending_days
                        },
                        threshold_values={
                            'upper_thresh_z': float(self.upper_thresh_z),
                            'lower_thresh_z': float(self.lower_thresh_z),
                            'leverage_scalar': float(self.leverage_scalar),
                            'cell1_exit_confirmation_days': self.cell1_exit_confirmation_days
                        }
                    )

            self._execute_rebalance(w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV)

    # ===== v3.5d: Cell 1 Exit Confirmation Method =====

    def _apply_cell1_exit_confirmation(
        self,
        T_norm: Decimal,
        raw_trend_state: str,
        sma_fast_val: Decimal,
        sma_slow_val: Decimal
    ) -> str:
        """
        Apply Cell 1 Exit Confirmation logic (v3.5d feature).

        This method implements the exit confirmation lag for Cell 1:
        - When enabled, requires T_norm to stay below bull threshold for N consecutive
          days before allowing exit from Cell 1 to Cell 3 (Sideways).
        - Only applies when:
          1. Feature is enabled (cell1_exit_confirmation_enabled = True)
          2. Currently in Cell 1 (BullStrong + Low Vol)
          3. T_norm drops below bull threshold (would normally exit to Sideways)
        - Does NOT apply to:
          - VolState changes (Cell 1 → Cell 2 exits immediately)
          - BearStrong transitions (Cell 1 → Cell 5/6 exits immediately)

        Args:
            T_norm: Current normalized Kalman trend value
            raw_trend_state: Trend state from _classify_trend_regime() before confirmation
            sma_fast_val: Fast SMA value (for logging)
            sma_slow_val: Slow SMA value (for logging)

        Returns:
            Final trend_state after applying exit confirmation logic:
            - If exit confirmation prevents transition: "BullStrong"
            - Otherwise: raw_trend_state unchanged
        """
        # If feature disabled, return raw trend state unchanged (v3.5b behavior)
        if not self.cell1_exit_confirmation_enabled:
            return raw_trend_state

        # Check if we're currently in Cell 1 (BullStrong + Low Vol)
        currently_in_cell1 = (self.cell_id == 1)

        # Check if SMA structure is still bullish (required for Cell 1)
        is_struct_bull = sma_fast_val > sma_slow_val

        # Case 1: Currently in Cell 1 and T_norm dropped below threshold
        if currently_in_cell1 and T_norm < self.t_norm_bull_thresh:
            # T_norm is below threshold - potential exit from Cell 1

            # But only apply confirmation if raw_trend_state would be Sideways
            # (not BearStrong - that should exit immediately)
            if raw_trend_state == "Sideways":
                # Increment pending exit counter
                self._cell1_exit_pending_days += 1

                logger.info(
                    f"Cell 1 Exit Confirmation: T_norm={T_norm:.3f} < {self.t_norm_bull_thresh}, "
                    f"pending_days={self._cell1_exit_pending_days}/{self.cell1_exit_confirmation_days}"
                )

                # Check if confirmation threshold reached
                if self._cell1_exit_pending_days >= self.cell1_exit_confirmation_days:
                    # Confirmed exit - allow transition to Sideways
                    logger.info(
                        f"Cell 1 Exit CONFIRMED after {self._cell1_exit_pending_days} days → Sideways"
                    )
                    self._cell1_exit_pending_days = 0  # Reset counter
                    return "Sideways"
                else:
                    # Not yet confirmed - stay in Cell 1 (BullStrong)
                    logger.info(
                        f"Cell 1 Exit PENDING ({self._cell1_exit_pending_days}/{self.cell1_exit_confirmation_days}) → staying BullStrong"
                    )
                    return "BullStrong"

            elif raw_trend_state == "BearStrong":
                # BearStrong transition - exit immediately (no confirmation needed)
                logger.info(
                    f"Cell 1 → BearStrong transition: exiting immediately (no confirmation for bear)"
                )
                self._cell1_exit_pending_days = 0  # Reset counter
                return "BearStrong"

        # Case 2: T_norm is above threshold OR not in Cell 1
        elif T_norm >= self.t_norm_bull_thresh:
            # T_norm recovered above threshold - reset counter
            if self._cell1_exit_pending_days > 0:
                logger.info(
                    f"Cell 1 Exit Confirmation RESET: T_norm={T_norm:.3f} >= {self.t_norm_bull_thresh}"
                )
            self._cell1_exit_pending_days = 0

        # Case 3: Not in Cell 1 - reset counter and return raw state
        elif not currently_in_cell1:
            self._cell1_exit_pending_days = 0

        # Default: return raw trend state
        return raw_trend_state

    # ===== Calculation methods (inherited from v3.5b) =====

    def _calculate_kalman_trend(self, trend_strength_signed: Decimal) -> Decimal:
        """Calculate normalized SIGNED Kalman trend."""
        T_norm = trend_strength_signed / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_structural_trend(
        self,
        sma_fast_val: Decimal,
        sma_slow_val: Decimal
    ) -> str:
        """Calculate structural trend from SMA crossover."""
        return "Bull" if sma_fast_val > sma_slow_val else "Bear"

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
        if len(self._bars) == max(self.sma_slow, self.vol_baseline_window) + 20:
            self.vol_state = "High" if z_score > Decimal("0") else "Low"
            logger.info(f"Initialized VolState: {self.vol_state} (z_score={z_score:.3f})")
            return

        if z_score > self.upper_thresh_z:
            if self.vol_state != "High":
                logger.info(
                    f"VolState transition: {self.vol_state} → High (z_score={z_score:.3f} > {self.upper_thresh_z})"
                )
                self.vol_state = "High"
        elif z_score < self.lower_thresh_z:
            if self.vol_state != "Low":
                logger.info(
                    f"VolState transition: {self.vol_state} → Low (z_score={z_score:.3f} < {self.lower_thresh_z})"
                )
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
            logger.info(
                f"Vol-crush override triggered: "
                f"vol drop {vol_change:.1%} in {self.vol_crush_lookback} days"
            )
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
        """Map (TrendState, VolState) to cell ID (1-6)."""
        if trend_state == "BullStrong":
            return 1 if vol_state == "Low" else 2
        elif trend_state == "Sideways":
            return 3 if vol_state == "Low" else 4
        else:  # BearStrong
            return 5 if vol_state == "Low" else 6

    def _get_cell_allocation(self, cell_id: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """Get base allocation weights for cell ID."""
        if cell_id == 1:
            return (Decimal("0.6"), Decimal("0.4"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 2:
            return (Decimal("0.0"), Decimal("1.0"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 3:
            return (Decimal("0.2"), Decimal("0.8"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 4:
            return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))
        elif cell_id == 5:
            return (Decimal("0.0"), Decimal("0.5"), Decimal("0.0"), Decimal("0.5"))
        elif cell_id == 6:
            if self.use_inverse_hedge:
                w_PSQ = min(Decimal("0.5"), self.w_PSQ_max)
                w_cash = Decimal("1.0") - w_PSQ
                return (Decimal("0.0"), Decimal("0.0"), w_PSQ, w_cash)
            else:
                return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))
        else:
            raise ValueError(f"Invalid cell_id: {cell_id}")

    def get_safe_haven_allocation(
        self,
        tlt_history_series: Optional[pd.Series],
        current_defensive_weight_decimal: Decimal
    ) -> dict[str, Decimal]:
        """Determines the optimal defensive mix (Cash + Bonds) based on TLT trend."""
        if tlt_history_series is None or len(tlt_history_series) < self.bond_sma_slow:
            logger.warning(
                f"Insufficient TLT data ({len(tlt_history_series) if tlt_history_series is not None else 0} bars, "
                f"need {self.bond_sma_slow}), falling back to Cash"
            )
            self._last_bond_sma_fast = None
            self._last_bond_sma_slow = None
            self._last_bond_trend = None
            return {"CASH": current_defensive_weight_decimal}

        sma_fast = tlt_history_series.rolling(window=self.bond_sma_fast).mean().iloc[-1]
        sma_slow = tlt_history_series.rolling(window=self.bond_sma_slow).mean().iloc[-1]

        if pd.isna(sma_fast) or pd.isna(sma_slow):
            logger.warning("Bond SMA calculation returned NaN, falling back to Cash")
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

        logger.info(
            f"Safe Haven allocation: {selected_ticker}={bond_weight:.3f} ({bond_weight/current_defensive_weight_decimal:.1%} of defensive), "
            f"CASH={cash_weight:.3f}"
        )

        return {
            selected_ticker: bond_weight,
            "CASH": cash_weight
        }

    def _check_rebalancing_threshold(
        self,
        target_tqqq_weight: Decimal,
        target_qqq_weight: Decimal,
        target_psq_weight: Decimal,
        target_tmf_weight: Decimal = Decimal("0"),
        target_tmv_weight: Decimal = Decimal("0")
    ) -> bool:
        """Check if portfolio weights drifted beyond threshold."""
        weight_deviation = (
            abs(self.current_tqqq_weight - target_tqqq_weight) +
            abs(self.current_qqq_weight - target_qqq_weight) +
            abs(self.current_psq_weight - target_psq_weight) +
            abs(getattr(self, 'current_tmf_weight', Decimal("0")) - target_tmf_weight) +
            abs(getattr(self, 'current_tmv_weight', Decimal("0")) - target_tmv_weight)
        )
        return weight_deviation > self.rebalance_threshold

    def _execute_rebalance(
        self,
        target_tqqq_weight: Decimal,
        target_qqq_weight: Decimal,
        target_psq_weight: Decimal,
        target_tmf_weight: Decimal = Decimal("0"),
        target_tmv_weight: Decimal = Decimal("0")
    ) -> None:
        """Rebalance portfolio to target weights using two-phase execution."""
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
                logger.debug(
                    f"Skipping {symbol} buy: Allocation ${allocation_value:.2f} < Price ${price:.2f}"
                )
                return Decimal("0")

            return weight

        target_tqqq_weight = _validate_weight(self.leveraged_long_symbol, target_tqqq_weight)
        target_qqq_weight = _validate_weight(self.core_long_symbol, target_qqq_weight)
        target_psq_weight = _validate_weight(self.inverse_hedge_symbol, target_psq_weight)
        target_tmf_weight = _validate_weight(self.bull_bond_symbol, target_tmf_weight)
        target_tmv_weight = _validate_weight(self.bear_bond_symbol, target_tmv_weight)

        # Phase 1: REDUCE positions
        if target_tqqq_weight == Decimal("0"):
            self.sell(self.leveraged_long_symbol, Decimal("0.0"))
        elif target_tqqq_weight > Decimal("0") and target_tqqq_weight < self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        if target_qqq_weight == Decimal("0"):
            self.sell(self.core_long_symbol, Decimal("0.0"))
        elif target_qqq_weight > Decimal("0") and target_qqq_weight < self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        if target_psq_weight == Decimal("0"):
            self.sell(self.inverse_hedge_symbol, Decimal("0.0"))
        elif target_psq_weight > Decimal("0") and target_psq_weight < self.current_psq_weight:
            self.buy(self.inverse_hedge_symbol, target_psq_weight)

        if target_tmf_weight == Decimal("0"):
            self.sell(self.bull_bond_symbol, Decimal("0.0"))
        elif target_tmf_weight > Decimal("0") and target_tmf_weight < getattr(self, 'current_tmf_weight', Decimal("0")):
            self.buy(self.bull_bond_symbol, target_tmf_weight)

        if target_tmv_weight == Decimal("0"):
            self.sell(self.bear_bond_symbol, Decimal("0.0"))
        elif target_tmv_weight > Decimal("0") and target_tmv_weight < getattr(self, 'current_tmv_weight', Decimal("0")):
            self.buy(self.bear_bond_symbol, target_tmv_weight)

        # Phase 2: INCREASE positions
        if target_tqqq_weight > Decimal("0") and target_tqqq_weight > self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        if target_qqq_weight > Decimal("0") and target_qqq_weight > self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        if target_psq_weight > Decimal("0") and target_psq_weight > self.current_psq_weight:
            self.buy(self.inverse_hedge_symbol, target_psq_weight)

        if target_tmf_weight > Decimal("0") and target_tmf_weight > getattr(self, 'current_tmf_weight', Decimal("0")):
            self.buy(self.bull_bond_symbol, target_tmf_weight)

        if target_tmv_weight > Decimal("0") and target_tmv_weight > getattr(self, 'current_tmv_weight', Decimal("0")):
            self.buy(self.bear_bond_symbol, target_tmv_weight)

        # Update current weights
        self.current_tqqq_weight = target_tqqq_weight
        self.current_qqq_weight = target_qqq_weight
        self.current_psq_weight = target_psq_weight
        self.current_tmf_weight = target_tmf_weight
        self.current_tmv_weight = target_tmv_weight

        logger.info(
            f"Executed v3.5d rebalance: TQQQ={target_tqqq_weight:.3f}, "
            f"QQQ={target_qqq_weight:.3f}, PSQ={target_psq_weight:.3f}, "
            f"TMF={target_tmf_weight:.3f}, TMV={target_tmv_weight:.3f}"
        )

    def get_current_regime(self) -> tuple[str, str, int]:
        """Get current regime classification."""
        if self.trend_state is None or self.cell_id is None:
            return ("Sideways", "Low", 3)

        return (self.trend_state, self.vol_state, self.cell_id)

    def get_current_indicators(self) -> dict:
        """Get current indicator values for CSV export."""
        indicators = {}

        if hasattr(self, '_last_t_norm') and self._last_t_norm is not None:
            indicators['T_norm'] = float(self._last_t_norm)

        if hasattr(self, '_last_z_score') and self._last_z_score is not None:
            indicators['z_score'] = float(self._last_z_score)

        if hasattr(self, '_last_sma_fast') and self._last_sma_fast is not None:
            indicators['SMA_fast'] = float(self._last_sma_fast)

        if hasattr(self, '_last_sma_slow') and self._last_sma_slow is not None:
            indicators['SMA_slow'] = float(self._last_sma_slow)

        if hasattr(self, '_last_vol_crush_triggered'):
            indicators['vol_crush'] = 1.0 if self._last_vol_crush_triggered else 0.0

        if hasattr(self, '_last_bond_sma_fast') and self._last_bond_sma_fast is not None:
            indicators['Bond_SMA_fast'] = float(self._last_bond_sma_fast)

        if hasattr(self, '_last_bond_sma_slow') and self._last_bond_sma_slow is not None:
            indicators['Bond_SMA_slow'] = float(self._last_bond_sma_slow)

        # v3.5d: Add exit confirmation counter to indicators
        indicators['cell1_exit_pending_days'] = float(self._cell1_exit_pending_days)

        return indicators
