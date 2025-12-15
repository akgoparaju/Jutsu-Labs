"""
Hierarchical Adaptive v3.5b: Binarized Regime Allocator with Hysteresis

v3.5b introduces four major structural improvements:

1. **Binarized Volatility (3x3 → 3x2 Grid)**:
   - Eliminated "Medium Vol" - leverage decay is binary (safe or not)
   - 6-cell regime grid (Bull/Side/Bear × Low/High Vol)

2. **Rolling Z-Score Volatility**:
   - Replaced static percentile thresholds (look-ahead bias)
   - Adapts to market baseline: Z = (σ_t - μ) / σ
   - Robust across decades without magic numbers

3. **Hysteresis State Machine**:
   - Prevents flicker when volatility near threshold
   - Latch mechanism: High requires crossing upper bound, Low requires crossing lower bound
   - Deadband behavior between thresholds

4. **Removed SQQQ (Toxic Asset)**:
   - SQQQ decay extreme in high vol (only time v3.0 allowed it)
   - Replaced with Cash or PSQ (-1x) in bearish regimes
   - Negative expectancy in high-vol chopping eliminated

Key Architecture:
- Hierarchical Trend: Fast (Kalman) gated by Slow (SMA 50/200)
- Volatility Z-Score: Rolling 21-day realized vol vs 126-day baseline
- 6-Cell Allocation Matrix: (Trend × Vol) → {TQQQ, QQQ, PSQ, Cash}
- Vol-Crush Override: 20% vol drop in 5 days forces Low state
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

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.kalman import AdaptiveKalmanFilter, KalmanFilterModel
from jutsu_engine.indicators.technical import sma, annualized_volatility
from jutsu_engine.performance.trade_logger import TradeLogger
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('STRATEGY.HIERARCHICAL_ADAPTIVE_V3_5B')

# Execution time mapping (ET market times)
EXECUTION_TIMES = {
    "open": time(9, 30),               # 9:30 AM ET
    "15min_after_open": time(9, 45),   # 9:45 AM ET
    "15min_before_close": time(15, 45), # 3:45 PM ET
    "5min_before_close": time(15, 55),  # 3:55 PM ET
    "close": time(16, 0),               # 4:00 PM ET
}


class Hierarchical_Adaptive_v3_5b(Strategy):
    """
    Hierarchical Adaptive v3.5b: Binarized Regime Allocator with Intraday Execution Timing

    Six-cell allocation system combining hierarchical trend (Kalman + SMA)
    with binarized volatility (rolling Z-score with hysteresis).

    Regime Grid (3x2):
        | Trend      | Low Vol               | High Vol                  |
        |------------|------------------------|---------------------------|
        | BullStrong | Kill Zone (60/40 T/Q) | Fragile (100% QQQ)       |
        | Sideways   | Drift (20/80 T/Q)     | Chop (100% Cash)         |
        | BearStrong | Grind (50/50 Q/Cash)  | Crash (100% Cash or PSQ) |

    Key Features:
    - Hierarchical Trend: T_norm (Kalman) gated by SMA_fast/SMA_slow
    - Volatility Z-Score: Adaptive regime detection
    - Hysteresis: Prevents regime flicker
    - Vol-Crush Override: Rapid volatility collapse detection
    - Hybrid Allocation: Base weights scaled by leverage_scalar
    - Automatic Warmup: Calculates required warmup bars based on indicator requirements
      (max of sma_slow+10 and vol_baseline+vol_realized, typically 147-210 bars)
    - Execution Timing: Configurable execution timing for Portfolio fill pricing.
      Signals always use EOD bars for consistency. execution_time only affects fill prices.

    Execution Timing (NEW):
        - execution_time parameter controls Portfolio fill pricing on last day
        - Options: "open" (9:30 AM), "15min_after_open" (9:45 AM),
                   "15min_before_close" (3:45 PM), "close" (4:00 PM)
        - Default: "close" (4:00 PM fill pricing)
        - Signal Generation: ALWAYS uses EOD bars for reproducibility
        - Fill Pricing: Portfolio uses execution_time for intraday fill prices
        - Purpose: Separates signal logic (EOD) from execution pricing (intraday)

    Example:
        strategy = Hierarchical_Adaptive_v3_5b(
            sma_fast=50,
            sma_slow=200,
            upper_thresh_z=Decimal("1.0"),
            lower_thresh_z=Decimal("0.0"),
            vol_crush_threshold=Decimal("-0.20"),
            leverage_scalar=Decimal("1.0"),
            use_inverse_hedge=False,  # PSQ toggle
            execution_time="15min_after_open",  # Fill pricing at 9:45 AM on last day
            ...
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
        name: str = "Hierarchical_Adaptive_v3_5b"
    ):
        """
        Initialize Hierarchical Adaptive v3.5b strategy.

        v3.5b introduces binarized volatility regime detection with hysteresis,
        hierarchical trend classification, and hybrid allocation system.

        Args:
            measurement_noise: Kalman filter measurement noise (default: 2000.0)
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            osc_smoothness: Oscillator smoothing period (default: 15)
            strength_smoothness: Trend strength smoothing period (default: 15)
            T_max: Trend normalization threshold (default: 50.0)
            symmetric_volume_adjustment: Enable symmetric volume-based noise adjustment (default: False)
                If True, noise INCREASES when volume drops (more skeptical on low-volume days)
                If False, noise only decreases when volume increases (original behavior)
            double_smoothing: Enable double WMA smoothing for trend strength (default: False)
                If True, applies two WMA passes: first with osc_smoothness, second with strength_smoothness
                If False, applies single WMA pass with osc_smoothness (original behavior)
            sma_fast: Fast structural trend SMA period (default: 50, range: [40, 60])
            sma_slow: Slow structural trend SMA period (default: 200, range: [180, 220])
            t_norm_bull_thresh: T_norm threshold for BullStrong (default: 0.3)
            t_norm_bear_thresh: T_norm threshold for BearStrong (default: -0.3)
            realized_vol_window: Rolling realized vol window (default: 21)
            vol_baseline_window: Volatility baseline statistics window (default: 126)
            upper_thresh_z: Z-score threshold for High vol (default: 1.0, range: [0.8, 1.2])
            lower_thresh_z: Z-score threshold for Low vol (default: 0.0, range: [-0.2, 0.2])
            vol_crush_threshold: Vol-crush percentage threshold (default: -0.20, range: [-0.15, -0.25])
            vol_crush_lookback: Vol-crush detection lookback period (default: 5)
            leverage_scalar: Allocation scaling factor (default: 1.0, range: [0.8, 1.2])
            use_inverse_hedge: Enable PSQ in bearish regimes (default: False)
            w_PSQ_max: Maximum PSQ weight (default: 0.5 = 50%)
            allow_treasury: Enable Treasury Overlay (dynamic bond selection) (default: True)
            bond_sma_fast: Fast SMA for bond trend detection (default: 20)
            bond_sma_slow: Slow SMA for bond trend detection (default: 60)
            max_bond_weight: Maximum allocation to bond ETFs (default: 0.4 = 40%)
            treasury_trend_symbol: Symbol for bond trend analysis (default: 'TLT')
            rebalance_threshold: Weight drift threshold for rebalancing (default: 0.025 = 2.5%)
            execution_time: When to price fills on last day (default: 'close')
                          Options: 'open' (9:30 AM), '15min_after_open' (9:45 AM),
                                   '15min_before_close' (3:45 PM), 'close' (4:00 PM)
                          Signals always use EOD bars (reproducibility)
                          Portfolio uses this for intraday fill pricing on last day only
            signal_symbol: Signal generation symbol (default: 'QQQ')
            core_long_symbol: 1x long symbol (default: 'QQQ')
            leveraged_long_symbol: 3x long symbol (default: 'TQQQ')
            inverse_hedge_symbol: -1x short symbol (default: 'PSQ')
            bull_bond_symbol: 3x bull bond symbol (default: 'TMF')
            bear_bond_symbol: 3x bear bond symbol (default: 'TMV')
            trade_logger: Optional TradeLogger (default: None)
            name: Strategy name (default: 'Hierarchical_Adaptive_v3_5b')
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

        logger.info(
            f"Initialized {name} (v3.5b - BINARIZED REGIME): "
            f"SMA_fast={sma_fast}, SMA_slow={sma_slow}, "
            f"upper_thresh_z={upper_thresh_z}, lower_thresh_z={lower_thresh_z}, "
            f"leverage_scalar={leverage_scalar}, use_inverse_hedge={use_inverse_hedge}, "
            f"execution_time={execution_time}"
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

        logger.info(
            f"Initialized {self.name} (v3.5b) with hysteresis state: {self.vol_state}"
        )

    def get_required_warmup_bars(self) -> int:
        """
        Calculate warmup bars needed for Hierarchical Adaptive v3.5b indicators.

        This strategy uses three indicator systems that require warmup:
        1. SMA indicators: sma_slow + buffer (10 bars)
        2. Volatility z-score: vol_baseline_window (126) + realized_vol_window (21)
        3. Bond SMA (if Treasury Overlay enabled): bond_sma_slow

        Returns:
            int: Maximum lookback required by all indicator systems

        Notes:
            - Ensures sufficient warmup for SMA, volatility, and bond trend systems
            - Prevents "Volatility z-score calculation failed" errors
            - Warmup bars are fetched BEFORE start_date (don't consume trading days)

        Example:
            With sma_slow=140, vol_baseline=126, vol_realized=21, bond_sma_slow=60:
            Returns max(140+10, 126+21, 60) = max(150, 147, 60) = 150

            With sma_slow=75, vol_baseline=126, vol_realized=21, bond_sma_slow=60:
            Returns max(75+10, 126+21, 60) = max(85, 147, 60) = 147
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

        This method is called by BacktestRunner to inform the strategy of the
        backtest end date. Portfolio uses this to detect the last trading day
        and fetch intraday prices for fill pricing.

        Args:
            end_date: End date of backtest (datetime.date or datetime.datetime)

        Notes:
            - Called by BacktestRunner after strategy initialization
            - Used by Portfolio for intraday fill pricing on last day
            - Strategy signals always use EOD data (this is only for Portfolio)
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

        This method is called by BacktestRunner/EventLoop to provide the strategy
        with access to the data handler. Portfolio uses this for intraday fill pricing.

        Args:
            data_handler: MultiSymbolDataHandler instance with get_intraday_bars_for_time_window()

        Notes:
            - Called by BacktestRunner after strategy initialization
            - Used by Portfolio for intraday fill pricing on last day
            - Strategy signals always use EOD data (this is only for Portfolio)
        """
        self._data_handler = data_handler
        logger.info("Strategy data_handler set for intraday execution timing")

    def _is_last_day(self, current_timestamp) -> bool:
        """
        Check if current bar is on the last day of backtest.

        Args:
            current_timestamp: Timestamp of current bar (datetime)

        Returns:
            bool: True if on last trading day, False otherwise

        Notes:
            - Compares bar date with backtest end_date
            - Kept for Portfolio compatibility (unused by strategy)
            - Returns False if end_date not set
        """
        if self._end_date is None:
            return False

        return current_timestamp.date() == self._end_date

    def _get_current_intraday_price(self, symbol: str, current_bar: MarketDataEvent) -> Decimal:
        """
        Fetch intraday price at execution_time for current bar.

        Uses 15-minute candles to simulate real-world trading where indicators
        are calculated using current session's intraday price (not EOD).
        Falls back to EOD close if intraday data unavailable.

        Args:
            symbol: Symbol to fetch intraday price for
            current_bar: Current bar (EOD bar for date reference)

        Returns:
            Intraday close price at execution_time (or EOD close if unavailable)

        Notes:
            - Caches intraday prices to avoid repeated database queries
            - Execution time mapping:
              * "open" → 9:30 AM ET (first 15-min candle)
              * "15min_after_open" → 9:45 AM ET (second 15-min candle)
              * "15min_before_close" → 3:45 PM ET (last 15-min candle before close)
              * "close" → 4:00 PM ET (EOD close, standard behavior)
            - Pre-fetched data from database (no API calls during execution)
        """
        # DEBUG: Log entry
        logger.info(
            f"[INTRADAY_DEBUG] _get_current_intraday_price called: "
            f"symbol={symbol}, date={current_bar.timestamp.date()}, "
            f"execution_time={self.execution_time}"
        )

        # Check cache first
        cache_key = (symbol, current_bar.timestamp)
        if cache_key in self._intraday_price_cache:
            cached_price = self._intraday_price_cache[cache_key]
            logger.info(
                f"[INTRADAY_DEBUG] CACHE HIT: "
                f"symbol={symbol}, date={current_bar.timestamp.date()}, "
                f"cached_price={cached_price}"
            )
            return cached_price

        logger.info(
            f"[INTRADAY_DEBUG] CACHE MISS: "
            f"symbol={symbol}, date={current_bar.timestamp.date()}, "
            f"fetching fresh data"
        )

        if self._data_handler is None:
            logger.warning(f"No data_handler injected, using EOD close for {symbol}")
            return current_bar.close

        try:
            # Map execution_time to market time (Eastern Time)
            execution_times = {
                "open": time(9, 30),                    # 9:30 AM
                "15min_after_open": time(9, 45),        # 9:45 AM
                "15min_before_close": time(15, 45),     # 3:45 PM
            }

            target_time = execution_times.get(self.execution_time)
            logger.info(
                f"[INTRADAY_DEBUG] Time mapping: "
                f"execution_time={self.execution_time} → target_time={target_time}"
            )

            if target_time is None:
                logger.error(f"Invalid execution_time: {self.execution_time}")
                return current_bar.close

            # DEBUG: Log fetch parameters
            logger.info(
                f"[INTRADAY_DEBUG] Fetching bars: "
                f"symbol={symbol}, date={current_bar.timestamp.date()}, "
                f"start_time={target_time}, end_time={target_time}, interval=15m"
            )

            # Fetch 15-minute intraday bar at target time
            intraday_bars = self._data_handler.get_intraday_bars_for_time_window(
                symbol=symbol,
                date=current_bar.timestamp.date(),
                start_time=target_time,
                end_time=target_time,
                interval='15m'  # 15-minute candles
            )

            # DEBUG: Log fetch results
            logger.info(
                f"[INTRADAY_DEBUG] Fetch returned {len(intraday_bars) if intraday_bars else 0} bars"
            )

            if not intraday_bars:
                logger.warning(
                    f"No intraday data for {symbol} on {current_bar.timestamp.date()} "
                    f"at {target_time}, using EOD close"
                )
                return current_bar.close

            # DEBUG: Log full bar details
            bar = intraday_bars[0]
            logger.info(
                f"[INTRADAY_DEBUG] Bar details: "
                f"timestamp={bar.timestamp}, "
                f"open={bar.open}, high={bar.high}, low={bar.low}, close={bar.close}, "
                f"volume={bar.volume}"
            )

            # Select price type based on execution_time
            # "open" execution uses OPEN price, others use CLOSE price
            if self.execution_time == "open":
                intraday_price = intraday_bars[0].open
                price_type = "OPEN"
            else:
                intraday_price = intraday_bars[0].close
                price_type = "CLOSE"

            # Cache and return
            self._intraday_price_cache[cache_key] = intraday_price

            logger.info(
                f"[INTRADAY_DEBUG] RETURNING: "
                f"symbol={symbol}, date={current_bar.timestamp.date()}, "
                f"execution_time={self.execution_time}, target_time={target_time}, "
                f"intraday_price={intraday_price} (using {price_type} price)"
            )

            return intraday_price

        except Exception as e:
            logger.error(
                f"[INTRADAY_DEBUG] EXCEPTION: "
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

        Simulates real-world trading: indicators use historical EOD closes
        plus current bar's intraday price at execution_time.

        Pattern:
        - Historical bars (lookback - 1): EOD closes from database
        - Current bar: Intraday price at execution_time (15-minute candle)
        - Example: 40-bar SMA uses 39 EOD closes + 1 intraday price

        Args:
            lookback: Number of bars to retrieve
            symbol: Symbol to filter by
            current_bar: Current bar (for intraday price fetch)

        Returns:
            pandas Series of close prices (historical EOD + current intraday)

        Notes:
            - execution_time="close": Uses EOD close (standard behavior)
            - execution_time="open/15min_after_open/15min_before_close": Uses intraday
            - Applied to EVERY bar throughout backtest (not just last day)
            - Enables different execution times to produce different signals
        """
        # For EOD execution: return pure EOD closes without mixing signal symbol's price
        if self.execution_time == "close":
            return self.get_closes(lookback=lookback, symbol=symbol)
        
        # For intraday execution: use historical EOD + current intraday price
        # Get historical EOD closes (lookback - 1 bars)
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
        Process each bar through v3.5b binarized regime allocator.

        Pipeline:
        1. Calculate Kalman trend (T_norm) - Fast signal
        2. Calculate SMA_fast, SMA_slow - Slow structural filter
        3. Calculate realized volatility and z-score
        4. Apply hysteresis to determine VolState (Low/High)
        5. Check vol-crush override
        6. Classify TrendState (BullStrong/Sideways/BearStrong)
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

        # 2. Calculate structural trend
        # Calculate required lookback accounting for ALL indicator needs:
        # - SMA indicators need: sma_slow + buffer (10 bars)
        # - Volatility z-score needs: vol_baseline_window (126) + realized_vol_window (21) = 147 bars
        # Use max() to ensure sufficient warmup for both indicator systems
        sma_lookback = self.sma_slow + 10
        vol_lookback = self.vol_baseline_window + self.realized_vol_window
        required_lookback = max(sma_lookback, vol_lookback)

        # Get closes for indicator calculation (historical EOD + current intraday)
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

        # 6. Classify trend regime
        trend_state = self._classify_trend_regime(T_norm, sma_fast_val, sma_slow_val)

        # Apply vol-crush override to trend
        if vol_crush_triggered:
            if trend_state == "BearStrong":
                logger.info("Vol-crush override: BearStrong → Sideways")
                trend_state = "Sideways"

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

        # 8.4. Always compute bond SMAs for display (even when not in defensive cells)
        # This enables the dashboard to show treasury overlay values regardless of regime
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
            # Get TLT price history for bond trend detection
            try:
                # Get TLT closes for indicator calculation (historical EOD + current intraday)
                tlt_closes = self._get_closes_for_indicator_calculation(
                    lookback=self.bond_sma_slow + 10,
                    symbol=self.treasury_trend_symbol,
                    current_bar=bar
                )
            except (ValueError, KeyError) as e:
                logger.warning(f"Could not retrieve TLT data: {e}, falling back to Cash")
                tlt_closes = None

            # Determine defensive portion based on cell
            if cell_id == 4:
                # Cell 4 (Chop): Was 100% Cash, now use Safe Haven
                defensive_weight = Decimal("1.0")
                safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)

                # Override cash with safe haven allocation
                w_cash = safe_haven.get("CASH", Decimal("0"))
                w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))

            elif cell_id == 5:
                # Cell 5 (Grind): Was 50% QQQ + 50% Cash, now 50% QQQ + Safe Haven
                defensive_weight = Decimal("0.5")
                safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)

                # QQQ stays at 50%, override cash portion with safe haven
                w_cash = safe_haven.get("CASH", Decimal("0"))
                w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))

            elif cell_id == 6:
                # Cell 6 (Crash): PSQ logic takes precedence if enabled
                if self.use_inverse_hedge:
                    # PSQ mode: Keep PSQ allocation, no bonds
                    pass
                else:
                    # No PSQ: Use Safe Haven instead of 100% Cash
                    defensive_weight = Decimal("1.0")
                    safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)

                    # Override cash with safe haven allocation
                    w_cash = safe_haven.get("CASH", Decimal("0"))
                    w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                    w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))

        # Apply leverage_scalar to base weights (but not to bonds - they're already leveraged 3x)
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

        logger.info(
            f"[{bar.timestamp}] v3.5b Regime (Treasury Overlay={'ON' if self.allow_treasury else 'OFF'}) | "
            f"T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f}, SMA_slow={sma_slow_val:.2f} → "
            f"TrendState={trend_state} | "
            f"z_score={z_score:.3f} → VolState={self.vol_state} (hysteresis) | "
            f"vol_crush={vol_crush_triggered} | "
            f"Cell={cell_id} → w_TQQQ={w_TQQQ:.3f}, w_QQQ={w_QQQ:.3f}, w_PSQ={w_PSQ:.3f}{treasury_log}, "
            f"w_cash={w_cash:.3f} (leverage_scalar={self.leverage_scalar})"
        )

        # Execute rebalance if needed
        if needs_rebalance:
            logger.info(f"Rebalancing: weights drifted beyond {self.rebalance_threshold:.3f}")

            if self._trade_logger:
                # Log context for all 5 possible positions (QQQ, TQQQ, PSQ, TMF, TMV)
                # to prevent "No strategy context found" warnings
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
                        strategy_state=f"v3.5b Cell {cell_id}: {trend_state}/{self.vol_state}",
                        decision_reason=(
                            f"Kalman T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f} vs SMA_slow={sma_slow_val:.2f}, "
                            f"z_score={z_score:.3f}, vol_crush={vol_crush_triggered}"
                        ),
                        indicator_values={
                            'T_norm': float(T_norm),
                            'SMA_fast': float(sma_fast_val),
                            'SMA_slow': float(sma_slow_val),
                            'z_score': float(z_score)
                        },
                        threshold_values={
                            'upper_thresh_z': float(self.upper_thresh_z),
                            'lower_thresh_z': float(self.lower_thresh_z),
                            'leverage_scalar': float(self.leverage_scalar)
                        }
                    )

            self._execute_rebalance(w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV)

    # ===== Calculation methods =====

    def _calculate_kalman_trend(self, trend_strength_signed: Decimal) -> Decimal:
        """
        Calculate normalized SIGNED Kalman trend.

        Args:
            trend_strength_signed: Raw signed trend strength from Kalman filter

        Returns:
            T_norm ∈ [-1.0, +1.0]
        """
        T_norm = trend_strength_signed / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_structural_trend(
        self,
        sma_fast_val: Decimal,
        sma_slow_val: Decimal
    ) -> str:
        """
        Calculate structural trend from SMA crossover.

        Args:
            sma_fast_val: Fast SMA value
            sma_slow_val: Slow SMA value

        Returns:
            "Bull" if SMA_fast > SMA_slow, else "Bear"
        """
        return "Bull" if sma_fast_val > sma_slow_val else "Bear"

    def _calculate_volatility_zscore(self, closes: pd.Series) -> Optional[Decimal]:
        """
        Calculate rolling z-score of realized volatility.

        Formula:
            σ_t = Realized Volatility (21-day annualized)
            μ_vol = Mean(σ, 126-day rolling window)
            σ_vol = Std(σ, 126-day rolling window)
            z_score = (σ_t - μ_vol) / σ_vol

        Args:
            closes: Price series for volatility calculation

        Returns:
            z_score or None if insufficient data
        """
        if len(closes) < self.vol_baseline_window + self.realized_vol_window:
            return None

        # Calculate realized volatility (annualized)
        vol_series = annualized_volatility(closes, lookback=self.realized_vol_window)

        if len(vol_series) < self.vol_baseline_window:
            return None

        # Calculate rolling baseline statistics
        vol_values = vol_series.tail(self.vol_baseline_window)

        if len(vol_values) < self.vol_baseline_window:
            return None

        # Convert to Decimal for precision
        vol_mean = Decimal(str(vol_values.mean()))
        vol_std = Decimal(str(vol_values.std()))

        if vol_std == Decimal("0"):
            return Decimal("0")

        # Current realized vol
        sigma_t = Decimal(str(vol_series.iloc[-1]))

        # Z-score
        z_score = (sigma_t - vol_mean) / vol_std

        return z_score

    def _apply_hysteresis(self, z_score: Decimal) -> None:
        """
        Apply hysteresis state machine to volatility state.

        Hysteresis Logic:
            if z_score > upper_thresh_z:
                VolState = "High"
            elif z_score < lower_thresh_z:
                VolState = "Low"
            else:
                VolState = Previous_VolState (deadband)

        Initialization (Day 1):
            if z_score > 0: VolState = "High"
            else: VolState = "Low"

        Args:
            z_score: Current volatility z-score
        """
        # Day 1 initialization
        if len(self._bars) == max(self.sma_slow, self.vol_baseline_window) + 20:
            self.vol_state = "High" if z_score > Decimal("0") else "Low"
            logger.info(f"Initialized VolState: {self.vol_state} (z_score={z_score:.3f})")
            return

        # Hysteresis logic
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
        # else: Deadband - maintain current state

    def _check_vol_crush_override(self, closes: pd.Series) -> bool:
        """
        Check for vol-crush override (V-shaped recovery detection).

        Trigger: If realized volatility drops by >20% in 5 days.
        Action: Force VolState = "Low", override BearStrong → Sideways.

        Args:
            closes: Price series for volatility calculation

        Returns:
            True if vol-crush triggered, False otherwise
        """
        if len(closes) < self.realized_vol_window + self.vol_crush_lookback:
            return False

        # Calculate realized volatility series
        vol_series = annualized_volatility(closes, lookback=self.realized_vol_window)

        if len(vol_series) < self.vol_crush_lookback + 1:
            return False

        # Current and historical volatility
        sigma_t = Decimal(str(vol_series.iloc[-1]))
        sigma_t_minus_N = Decimal(str(vol_series.iloc[-(self.vol_crush_lookback + 1)]))

        if sigma_t_minus_N == Decimal("0"):
            return False

        # Calculate percentage change
        vol_change = (sigma_t - sigma_t_minus_N) / sigma_t_minus_N

        # Check if vol-crush threshold breached
        if vol_change < self.vol_crush_threshold:
            logger.info(
                f"Vol-crush override triggered: "
                f"vol drop {vol_change:.1%} in {self.vol_crush_lookback} days"
            )
            # Force VolState to Low
            self.vol_state = "Low"
            return True

        return False

    def _classify_trend_regime(
        self,
        T_norm: Decimal,
        sma_fast_val: Decimal,
        sma_slow_val: Decimal
    ) -> str:
        """
        Classify trend regime using hierarchical logic.

        Classification Rules:
        1. BullStrong: (T_norm > 0.3) AND (SMA_fast > SMA_slow)
        2. BearStrong: (T_norm < -0.3) AND (SMA_fast < SMA_slow)
        3. Sideways: All other conditions

        Args:
            T_norm: Normalized Kalman trend
            sma_fast_val: Fast SMA value
            sma_slow_val: Slow SMA value

        Returns:
            "BullStrong", "BearStrong", or "Sideways"
        """
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

        Cell Mapping:
            1: BullStrong + Low
            2: BullStrong + High
            3: Sideways + Low
            4: Sideways + High
            5: BearStrong + Low
            6: BearStrong + High

        Args:
            trend_state: "BullStrong", "Sideways", or "BearStrong"
            vol_state: "Low" or "High"

        Returns:
            cell_id ∈ [1, 6]
        """
        if trend_state == "BullStrong":
            return 1 if vol_state == "Low" else 2
        elif trend_state == "Sideways":
            return 3 if vol_state == "Low" else 4
        else:  # BearStrong
            return 5 if vol_state == "Low" else 6

    def _get_cell_allocation(self, cell_id: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """
        Get base allocation weights for cell ID.

        6-Cell Allocation Matrix (Base Weights):
            Cell 1 (Bull/Low):   60% TQQQ, 40% QQQ (Net Beta ~2.2)
            Cell 2 (Bull/High):  0% TQQQ, 100% QQQ (Net Beta 1.0)
            Cell 3 (Side/Low):   20% TQQQ, 80% QQQ (Net Beta ~1.4)
            Cell 4 (Side/High):  0% TQQQ, 0% QQQ, 100% Cash (Net Beta 0.0)
            Cell 5 (Bear/Low):   0% TQQQ, 50% QQQ, 50% Cash (Net Beta 0.5)
            Cell 6a (Bear/High, no PSQ): 0% TQQQ, 0% QQQ, 100% Cash (Net Beta 0.0)
            Cell 6b (Bear/High, PSQ): 0% TQQQ, 0% QQQ, 50% PSQ, 50% Cash (Net Beta -0.5)

        Args:
            cell_id: Cell identifier [1-6]

        Returns:
            (w_TQQQ, w_QQQ, w_PSQ, w_cash) base weights (sum = 1.0)
        """
        if cell_id == 1:
            # Kill Zone: Aggressive upside
            return (Decimal("0.6"), Decimal("0.4"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 2:
            # Fragile Trend: De-risk
            return (Decimal("0.0"), Decimal("1.0"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 3:
            # Drift Capture: Slow grind
            return (Decimal("0.2"), Decimal("0.8"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 4:
            # Chopping Block: Avoid whipsaw
            return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))
        elif cell_id == 5:
            # Grind: Defensive hold
            return (Decimal("0.0"), Decimal("0.5"), Decimal("0.0"), Decimal("0.5"))
        elif cell_id == 6:
            # Crash: Capital preservation
            if self.use_inverse_hedge:
                # Cell 6b: Use PSQ (capped)
                w_PSQ = min(Decimal("0.5"), self.w_PSQ_max)
                w_cash = Decimal("1.0") - w_PSQ
                return (Decimal("0.0"), Decimal("0.0"), w_PSQ, w_cash)
            else:
                # Cell 6a: 100% Cash
                return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))
        else:
            raise ValueError(f"Invalid cell_id: {cell_id}")

    def get_safe_haven_allocation(
        self,
        tlt_history_series: Optional[pd.Series],
        current_defensive_weight_decimal: Decimal
    ) -> dict[str, Decimal]:
        """
        Determines the optimal defensive mix (Cash + Bonds) based on TLT trend.

        Treasury Overlay Logic:
        - Bond Bull (SMA_fast > SMA_slow): Flight to safety → TMF (3x bull bonds)
        - Bond Bear (SMA_fast < SMA_slow): Inflation shock → TMV (3x bear bonds)
        - Missing data: Fallback to 100% Cash (safe default)

        Args:
            tlt_history_series: Daily close prices of TLT (needs ~60 bars)
            current_defensive_weight_decimal: The % of portfolio allocated to defense
                                            (e.g. Decimal("1.0") for Cell 4 = 100% defensive)

        Returns:
            dict: Target weights {Ticker: Decimal}
                Examples:
                - Bond Bull: {"TMF": Decimal("0.4"), "CASH": Decimal("0.6")}
                - Bond Bear: {"TMV": Decimal("0.4"), "CASH": Decimal("0.6")}
                - Missing data: {"CASH": Decimal("1.0")}

        Notes:
            - Global cap: max_bond_weight (default 40%) to control volatility
            - TMF/TMV are 3x leveraged with durations > 50
            - Sizing: bond_weight = min(defensive_weight * 0.4, max_bond_weight)
        """
        # Safety check: Data sufficiency
        if tlt_history_series is None or len(tlt_history_series) < self.bond_sma_slow:
            # Fallback to 100% Cash for the defensive portion
            logger.warning(
                f"Insufficient TLT data ({len(tlt_history_series) if tlt_history_series is not None else 0} bars, "
                f"need {self.bond_sma_slow}), falling back to Cash"
            )
            # Reset bond tracking since we're not using bonds
            self._last_bond_sma_fast = None
            self._last_bond_sma_slow = None
            self._last_bond_trend = None
            return {"CASH": current_defensive_weight_decimal}

        # Calculate indicators
        sma_fast = tlt_history_series.rolling(window=self.bond_sma_fast).mean().iloc[-1]
        sma_slow = tlt_history_series.rolling(window=self.bond_sma_slow).mean().iloc[-1]

        # Check for NaN
        if pd.isna(sma_fast) or pd.isna(sma_slow):
            logger.warning("Bond SMA calculation returned NaN, falling back to Cash")
            # Reset bond tracking since we're not using bonds
            self._last_bond_sma_fast = None
            self._last_bond_sma_slow = None
            self._last_bond_trend = None
            return {"CASH": current_defensive_weight_decimal}

        # Convert to Decimal
        sma_fast_val = Decimal(str(sma_fast))
        sma_slow_val = Decimal(str(sma_slow))

        # Store bond SMA values for decision tree (dashboard API)
        self._last_bond_sma_fast = sma_fast_val
        self._last_bond_sma_slow = sma_slow_val

        # Determine instrument
        # TMF (+3x Bonds) for Deflation/Safety (Rates Falling)
        # TMV (-3x Bonds) for Inflation/Rate Shock (Rates Rising)
        if sma_fast_val > sma_slow_val:
            selected_ticker = self.bull_bond_symbol  # Default: "TMF"
            self._last_bond_trend = "Bull"
            logger.debug(
                f"Bond trend: BULL (SMA_fast={sma_fast_val:.2f} > SMA_slow={sma_slow_val:.2f}) → {selected_ticker}"
            )
        else:
            selected_ticker = self.bear_bond_symbol  # Default: "TMV"
            self._last_bond_trend = "Bear"
            logger.debug(
                f"Bond trend: BEAR (SMA_fast={sma_fast_val:.2f} < SMA_slow={sma_slow_val:.2f}) → {selected_ticker}"
            )

        # Sizing Logic
        # We utilize up to 40% of the Total Portfolio for Bonds.
        # If the defensive weight is small (e.g. 50% in Cell 5), we scale proportionally
        # but ensure we never exceed the global MAX_BOND_TOTAL_PCT.

        # Calculate potential bond weight
        # e.g., if defensive portion is 1.0, bond part is 0.4. Cash is 0.6.
        bond_weight = min(current_defensive_weight_decimal * Decimal("0.4"), self.max_bond_weight)

        # The rest of the defensive bucket stays in Cash
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
        """
        Check if portfolio weights drifted beyond threshold.

        Args:
            target_tqqq_weight: Target TQQQ weight
            target_qqq_weight: Target QQQ weight
            target_psq_weight: Target PSQ weight
            target_tmf_weight: Target TMF weight (Treasury Overlay)
            target_tmv_weight: Target TMV weight (Treasury Overlay)

        Returns:
            True if rebalancing needed, False otherwise
        """
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
        """
        Rebalance portfolio to target weights using two-phase execution.

        Phase 1: Reduce positions (execute SELLs first to free cash)
        Phase 2: Increase positions (execute BUYs with freed cash)

        Args:
            target_tqqq_weight: Target TQQQ weight
            target_qqq_weight: Target QQQ weight
            target_psq_weight: Target PSQ weight
            target_tmf_weight: Target TMF weight (Treasury Overlay)
            target_tmv_weight: Target TMV weight (Treasury Overlay)
        """
        # Helper: Check if allocation is sufficient for at least 1 share
        def _validate_weight(symbol: str, weight: Decimal) -> Decimal:
            if weight <= Decimal("0"):
                return Decimal("0")

            # Get latest price
            closes = self.get_closes(lookback=1, symbol=symbol)
            if closes.empty:
                return Decimal("0")

            price = Decimal(str(closes.iloc[-1]))
            if price <= Decimal("0"):
                return Decimal("0")

            # Calculate portfolio equity
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

        # Validate weights before execution
        target_tqqq_weight = _validate_weight(self.leveraged_long_symbol, target_tqqq_weight)
        target_qqq_weight = _validate_weight(self.core_long_symbol, target_qqq_weight)
        target_psq_weight = _validate_weight(self.inverse_hedge_symbol, target_psq_weight)
        target_tmf_weight = _validate_weight(self.bull_bond_symbol, target_tmf_weight)
        target_tmv_weight = _validate_weight(self.bear_bond_symbol, target_tmv_weight)

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

        # Update current weights
        self.current_tqqq_weight = target_tqqq_weight
        self.current_qqq_weight = target_qqq_weight
        self.current_psq_weight = target_psq_weight
        self.current_tmf_weight = target_tmf_weight
        self.current_tmv_weight = target_tmv_weight

        logger.info(
            f"Executed v3.5b rebalance: TQQQ={target_tqqq_weight:.3f}, "
            f"QQQ={target_qqq_weight:.3f}, PSQ={target_psq_weight:.3f}, "
            f"TMF={target_tmf_weight:.3f}, TMV={target_tmv_weight:.3f}"
        )

    def get_current_regime(self) -> tuple[str, str, int]:
        """
        Get current regime classification.

        Returns regime state for external analysis (e.g., RegimePerformanceAnalyzer).
        Used to track performance metrics across different market regimes.

        Returns:
            Tuple of (trend_state, vol_state, cell_id):
            - trend_state: "BullStrong", "Sideways", or "BearStrong"
            - vol_state: "Low" or "High"
            - cell_id: 1-6 (regime cell identifier)

        Example:
            trend, vol, cell = strategy.get_current_regime()
            # Returns: ("BullStrong", "Low", 1)
        """
        if self.trend_state is None or self.cell_id is None:
            # Not yet initialized (before first bar processed)
            # Return safe default: Sideways + Low Vol = Cell 3
            return ("Sideways", "Low", 3)

        return (self.trend_state, self.vol_state, self.cell_id)

    def get_current_indicators(self) -> dict:
        """
        Get current indicator values for CSV export.

        Returns all computed indicator values from the most recent bar.
        Used by PortfolioCSVExporter to add indicator columns to daily CSV.

        Returns:
            Dict with indicator names as keys and values as floats.
            Returns empty dict if no indicators computed yet.

        Indicators returned:
            - T_norm: Kalman trend normalized value
            - z_score: Volatility z-score
            - SMA_fast: Fast SMA value
            - SMA_slow: Slow SMA value
            - vol_crush: Vol-crush triggered flag (1.0 or 0.0)
            - Bond_SMA_fast: Bond fast SMA (only when treasury enabled)
            - Bond_SMA_slow: Bond slow SMA (only when treasury enabled)

        Example:
            indicators = strategy.get_current_indicators()
            # Returns: {'T_norm': 0.15, 'z_score': -0.3, ...}
        """
        indicators = {}

        # Core indicators (always present after warmup)
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

        # Bond indicators (only when treasury is enabled and computed)
        if hasattr(self, '_last_bond_sma_fast') and self._last_bond_sma_fast is not None:
            indicators['Bond_SMA_fast'] = float(self._last_bond_sma_fast)

        if hasattr(self, '_last_bond_sma_slow') and self._last_bond_sma_slow is not None:
            indicators['Bond_SMA_slow'] = float(self._last_bond_sma_slow)

        return indicators
