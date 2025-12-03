"""
Hierarchical Adaptive v3.8: Golden Strategy (No Delay)

v3.8 Final Adjustments:
1. REMOVED Anti-Flicker Delay (Immediate defense is superior to delayed defense).
2. RETAINED Cell 2 at 100% QQQ (Captures Bull/High Vol upside).
3. RETAINED Wide Hysteresis (0.0 - 1.0 Z-score) to naturally reduce churn.
4. RETAINED Cell 4 at 100% Cash (Strict capital preservation).

This version removes the "lag" that caused v3.7 to hold TQQQ during crash onsets.
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

logger = setup_logger('STRATEGY.HIERARCHICAL_ADAPTIVE_V3_8')

class Hierarchical_Adaptive_v3_8(Strategy):
    """
    Hierarchical Adaptive v3.8: Golden Strategy (No Delay)
    """

    def __init__(
        self,
        # ==================================================================
        # KALMAN TREND PARAMETERS
        # ==================================================================
        measurement_noise: Decimal = Decimal("2000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 15,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("50.0"),

        # ==================================================================
        # STRUCTURAL TREND PARAMETERS
        # ==================================================================
        sma_fast: int = 40,
        sma_slow: int = 140,
        t_norm_bull_thresh: Decimal = Decimal("0.2"),
        t_norm_bear_thresh: Decimal = Decimal("-0.3"),

        # ==================================================================
        # VOLATILITY Z-SCORE PARAMETERS (Wide Hysteresis Kept)
        # ==================================================================
        realized_vol_window: int = 21,
        vol_baseline_window: int = 160,          # Kept 160 for smooth baseline
        upper_thresh_z: Decimal = Decimal("1.0"),
        lower_thresh_z: Decimal = Decimal("0.0"), # Kept 0.0 for wide band

        # ==================================================================
        # VOL-CRUSH OVERRIDE
        # ==================================================================
        vol_crush_threshold: Decimal = Decimal("-0.15"),
        vol_crush_lookback: int = 5,

        # ==================================================================
        # ALLOCATION PARAMETERS
        # ==================================================================
        leverage_scalar: Decimal = Decimal("1.0"),

        # ==================================================================
        # INSTRUMENT TOGGLES
        # ==================================================================
        use_inverse_hedge: bool = False,
        w_PSQ_max: Decimal = Decimal("0.5"),

        # ==================================================================
        # TREASURY OVERLAY PARAMETERS
        # ==================================================================
        allow_treasury: bool = True,
        bond_sma_fast: int = 20,
        bond_sma_slow: int = 60,
        max_bond_weight: Decimal = Decimal("0.4"),
        treasury_trend_symbol: str = "TLT",

        # ==================================================================
        # REBALANCING CONTROL
        # ==================================================================
        rebalance_threshold: Decimal = Decimal("0.025"),

        # ==================================================================
        # EXECUTION TIMING
        # ==================================================================
        execution_time: str = "close",

        # ==================================================================
        # SYMBOL CONFIGURATION
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
        name: str = "Hierarchical_Adaptive_v3_8"
    ):
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate execution_time
        valid_execution_times = ["open", "15min_after_open", "15min_before_close", "close"]
        if execution_time not in valid_execution_times:
            raise ValueError(f"execution_time must be one of {valid_execution_times}")

        # Store parameters
        self.measurement_noise = measurement_noise
        self.process_noise_1 = process_noise_1
        self.process_noise_2 = process_noise_2
        self.osc_smoothness = osc_smoothness
        self.strength_smoothness = strength_smoothness
        self.T_max = T_max

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
        self.vol_state: str = "Low"
        self.trend_state: Optional[str] = None
        self.cell_id: Optional[int] = None
        # REMOVED: cell_4_pending_bars

        # Weights
        self.current_tqqq_weight: Decimal = Decimal("0")
        self.current_qqq_weight: Decimal = Decimal("0")
        self.current_psq_weight: Decimal = Decimal("0")
        self.current_tmf_weight: Decimal = Decimal("0")
        self.current_tmv_weight: Decimal = Decimal("0")

        self._end_date: Optional = None
        self._data_handler: Optional = None
        self._intraday_price_cache: Dict[Tuple[str, datetime], Decimal] = {}

        logger.info(
            f"Initialized {name} (v3.8 - FINAL): "
            f"SMA_fast={sma_fast}, SMA_slow={sma_slow}, "
            f"Vol_Baseline={vol_baseline_window}, Lower_Z={lower_thresh_z}, "
            f"leverage_scalar={leverage_scalar}"
        )

    def init(self) -> None:
        """Initialize strategy state."""
        self.kalman_filter = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=float(self.measurement_noise),
            process_noise_1=float(self.process_noise_1),
            process_noise_2=float(self.process_noise_2),
            osc_smoothness=self.osc_smoothness,
            strength_smoothness=self.strength_smoothness,
            return_signed=True
        )
        self.vol_state = "Low"
        self.current_tqqq_weight = Decimal("0")
        self.current_qqq_weight = Decimal("0")
        self.current_psq_weight = Decimal("0")

    def get_required_warmup_bars(self) -> int:
        sma_lookback = self.sma_slow + 10
        vol_lookback = self.vol_baseline_window + self.realized_vol_window
        bond_lookback = self.bond_sma_slow if self.allow_treasury else 0
        return max(sma_lookback, vol_lookback, bond_lookback)

    def set_end_date(self, end_date) -> None:
        from datetime import datetime
        if isinstance(end_date, datetime):
            self._end_date = end_date.date()
        else:
            self._end_date = end_date

    def set_data_handler(self, data_handler) -> None:
        self._data_handler = data_handler

    def _get_current_intraday_price(self, symbol: str, current_bar: MarketDataEvent) -> Decimal:
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

        except Exception:
            return current_bar.close

    def _get_closes_for_indicator_calculation(self, lookback: int, symbol: str, current_bar: MarketDataEvent) -> pd.Series:
        if self.execution_time == "close":
            return self.get_closes(lookback=lookback, symbol=symbol)

        historical_closes = self.get_closes(lookback=lookback - 1, symbol=symbol)
        current_price = self._get_current_intraday_price(symbol, current_bar)
        combined = pd.concat([
            historical_closes,
            pd.Series([current_price], index=[current_bar.timestamp])
        ])
        return combined.iloc[-lookback:]

    def on_bar(self, bar: MarketDataEvent) -> None:
        if bar.symbol != self.signal_symbol:
            return

        min_warmup = self.sma_slow + 20
        if len(self._bars) < min_warmup:
            return

        # 1. Kalman Trend
        kalman_price = bar.close if self.execution_time == "close" else self._get_current_intraday_price(self.signal_symbol, bar)
        filtered_price, trend_strength_signed = self.kalman_filter.update(
            close=kalman_price, high=bar.high, low=bar.low, volume=bar.volume
        )
        T_norm = self._calculate_kalman_trend(Decimal(str(trend_strength_signed)))

        # 2. Structural Trend
        sma_lookback = self.sma_slow + 10
        vol_lookback = self.vol_baseline_window + self.realized_vol_window
        required_lookback = max(sma_lookback, vol_lookback)
        closes = self._get_closes_for_indicator_calculation(required_lookback, self.signal_symbol, bar)

        sma_fast_series = sma(closes, self.sma_fast)
        sma_slow_series = sma(closes, self.sma_slow)

        if pd.isna(sma_fast_series.iloc[-1]) or pd.isna(sma_slow_series.iloc[-1]):
            return

        sma_fast_val = Decimal(str(sma_fast_series.iloc[-1]))
        sma_slow_val = Decimal(str(sma_slow_series.iloc[-1]))

        # 3. Volatility Z-Score
        z_score = self._calculate_volatility_zscore(closes)
        if z_score is None:
            return

        # 4. Hysteresis
        self._apply_hysteresis(z_score)

        # 5. Vol Crush
        vol_crush_triggered = self._check_vol_crush_override(closes)

        # 6. Trend Classification
        trend_state = self._classify_trend_regime(T_norm, sma_fast_val, sma_slow_val)
        if vol_crush_triggered and trend_state == "BearStrong":
            trend_state = "Sideways"

        # 7. Allocation
        cell_id = self._get_cell_id(trend_state, self.vol_state)
        w_TQQQ, w_QQQ, w_PSQ, w_cash = self._get_cell_allocation(cell_id)

        self.trend_state = trend_state
        self.cell_id = cell_id

        # 8. Treasury Overlay (Cells 5 & 6 only)
        w_TMF = Decimal("0")
        w_TMV = Decimal("0")

        if self.allow_treasury and cell_id in [5, 6]:
            try:
                tlt_closes = self._get_closes_for_indicator_calculation(
                    lookback=self.bond_sma_slow + 10,
                    symbol=self.treasury_trend_symbol,
                    current_bar=bar
                )
            except Exception:
                tlt_closes = None

            if cell_id == 5:
                # Cell 5: 50% QQQ + Safe Haven
                defensive_weight = Decimal("0.5")
                safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)
                w_cash = safe_haven.get("CASH", Decimal("0"))
                w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))

            elif cell_id == 6:
                # Cell 6: Check PSQ first
                if not self.use_inverse_hedge:
                    # No PSQ -> Use Safe Haven
                    defensive_weight = Decimal("1.0")
                    safe_haven = self.get_safe_haven_allocation(tlt_closes, defensive_weight)
                    w_cash = safe_haven.get("CASH", Decimal("0"))
                    w_TMF = safe_haven.get(self.bull_bond_symbol, Decimal("0"))
                    w_TMV = safe_haven.get(self.bear_bond_symbol, Decimal("0"))

        # Apply Leverage Scalar
        w_TQQQ = w_TQQQ * self.leverage_scalar
        w_QQQ = w_QQQ * self.leverage_scalar
        w_PSQ = w_PSQ * self.leverage_scalar

        # Normalize
        total_weight = w_TQQQ + w_QQQ + w_PSQ + w_TMF + w_TMV + w_cash
        if total_weight > Decimal("0"):
            w_TQQQ /= total_weight
            w_QQQ /= total_weight
            w_PSQ /= total_weight
            w_TMF /= total_weight
            w_TMV /= total_weight
            w_cash /= total_weight

        needs_rebalance = self._check_rebalancing_threshold(w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV)

        if needs_rebalance:
            if self._trade_logger:
                for symbol in [self.core_long_symbol, self.leveraged_long_symbol, self.inverse_hedge_symbol, self.bull_bond_symbol, self.bear_bond_symbol]:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=symbol,
                        strategy_state=f"v3.8 Cell {cell_id}: {trend_state}/{self.vol_state}",
                        decision_reason=f"Z={z_score:.2f}",
                        indicator_values={'T_norm': float(T_norm), 'z_score': float(z_score)},
                        threshold_values={'upper': float(self.upper_thresh_z), 'lower': float(self.lower_thresh_z)}
                    )
            self._execute_rebalance(w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV)

    def _calculate_kalman_trend(self, trend_strength_signed: Decimal) -> Decimal:
        T_norm = trend_strength_signed / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_volatility_zscore(self, closes: pd.Series) -> Optional[Decimal]:
        if len(closes) < self.vol_baseline_window + self.realized_vol_window:
            return None
        vol_series = annualized_volatility(closes, lookback=self.realized_vol_window)
        if len(vol_series) < self.vol_baseline_window:
            return None
        vol_values = vol_series.tail(self.vol_baseline_window)
        vol_mean = Decimal(str(vol_values.mean()))
        vol_std = Decimal(str(vol_values.std()))
        if vol_std == Decimal("0"):
            return Decimal("0")
        sigma_t = Decimal(str(vol_series.iloc[-1]))
        return (sigma_t - vol_mean) / vol_std

    def _apply_hysteresis(self, z_score: Decimal) -> None:
        if len(self._bars) == max(self.sma_slow, self.vol_baseline_window) + 20:
            self.vol_state = "High" if z_score > Decimal("0") else "Low"
            return
        if z_score > self.upper_thresh_z:
            if self.vol_state != "High":
                self.vol_state = "High"
        elif z_score < self.lower_thresh_z:
            if self.vol_state != "Low":
                self.vol_state = "Low"

    def _check_vol_crush_override(self, closes: pd.Series) -> bool:
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
            self.vol_state = "Low"
            return True
        return False

    def _classify_trend_regime(self, T_norm: Decimal, sma_fast_val: Decimal, sma_slow_val: Decimal) -> str:
        is_struct_bull = sma_fast_val > sma_slow_val
        if T_norm > self.t_norm_bull_thresh and is_struct_bull:
            return "BullStrong"
        elif T_norm < self.t_norm_bear_thresh and not is_struct_bull:
            return "BearStrong"
        else:
            return "Sideways"

    def _get_cell_id(self, trend_state: str, vol_state: str) -> int:
        if trend_state == "BullStrong":
            return 1 if vol_state == "Low" else 2
        elif trend_state == "Sideways":
            return 3 if vol_state == "Low" else 4
        else:
            return 5 if vol_state == "Low" else 6

    def _get_cell_allocation(self, cell_id: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        if cell_id == 1:
            return (Decimal("0.6"), Decimal("0.4"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 2:
            # OPTIMIZED: 100% QQQ (Restore exposure to capture upside)
            return (Decimal("0.0"), Decimal("1.0"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 3:
            return (Decimal("0.2"), Decimal("0.8"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 4:
            # Chop: 100% Cash (Treasury Overlay is explicitly disabled for Cell 4)
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

    def get_safe_haven_allocation(self, tlt_history_series: Optional[pd.Series], current_defensive_weight_decimal: Decimal) -> dict[str, Decimal]:
        if tlt_history_series is None or len(tlt_history_series) < self.bond_sma_slow:
            return {"CASH": current_defensive_weight_decimal}
        sma_fast = tlt_history_series.rolling(window=self.bond_sma_fast).mean().iloc[-1]
        sma_slow = tlt_history_series.rolling(window=self.bond_sma_slow).mean().iloc[-1]
        if pd.isna(sma_fast) or pd.isna(sma_slow):
            return {"CASH": current_defensive_weight_decimal}

        sma_fast_val = Decimal(str(sma_fast))
        sma_slow_val = Decimal(str(sma_slow))

        selected_ticker = self.bull_bond_symbol if sma_fast_val > sma_slow_val else self.bear_bond_symbol
        bond_weight = min(current_defensive_weight_decimal * Decimal("0.4"), self.max_bond_weight)
        cash_weight = current_defensive_weight_decimal - bond_weight
        return {selected_ticker: bond_weight, "CASH": cash_weight}

    def _check_rebalancing_threshold(self, target_tqqq_weight: Decimal, target_qqq_weight: Decimal, target_psq_weight: Decimal, target_tmf_weight: Decimal = Decimal("0"), target_tmv_weight: Decimal = Decimal("0")) -> bool:
        weight_deviation = (
            abs(self.current_tqqq_weight - target_tqqq_weight) +
            abs(self.current_qqq_weight - target_qqq_weight) +
            abs(self.current_psq_weight - target_psq_weight) +
            abs(getattr(self, 'current_tmf_weight', Decimal("0")) - target_tmf_weight) +
            abs(getattr(self, 'current_tmv_weight', Decimal("0")) - target_tmv_weight)
        )
        return weight_deviation > self.rebalance_threshold

    def _execute_rebalance(self, target_tqqq_weight: Decimal, target_qqq_weight: Decimal, target_psq_weight: Decimal, target_tmf_weight: Decimal = Decimal("0"), target_tmv_weight: Decimal = Decimal("0")) -> None:
        def _execute_single(symbol: str, target: Decimal, current: Decimal, is_sell: bool):
            if is_sell:
                if target == Decimal("0"): self.sell(symbol, Decimal("0.0"))
                elif target > Decimal("0") and target < current: self.buy(symbol, target)
            else:
                if target > Decimal("0") and target > current: self.buy(symbol, target)

        # Phase 1: SELLs
        _execute_single(self.leveraged_long_symbol, target_tqqq_weight, self.current_tqqq_weight, True)
        _execute_single(self.core_long_symbol, target_qqq_weight, self.current_qqq_weight, True)
        _execute_single(self.inverse_hedge_symbol, target_psq_weight, self.current_psq_weight, True)
        _execute_single(self.bull_bond_symbol, target_tmf_weight, getattr(self, 'current_tmf_weight', Decimal("0")), True)
        _execute_single(self.bear_bond_symbol, target_tmv_weight, getattr(self, 'current_tmv_weight', Decimal("0")), True)

        # Phase 2: BUYs
        _execute_single(self.leveraged_long_symbol, target_tqqq_weight, self.current_tqqq_weight, False)
        _execute_single(self.core_long_symbol, target_qqq_weight, self.current_qqq_weight, False)
        _execute_single(self.inverse_hedge_symbol, target_psq_weight, self.current_psq_weight, False)
        _execute_single(self.bull_bond_symbol, target_tmf_weight, getattr(self, 'current_tmf_weight', Decimal("0")), False)
        _execute_single(self.bear_bond_symbol, target_tmv_weight, getattr(self, 'current_tmv_weight', Decimal("0")), False)

        self.current_tqqq_weight = target_tqqq_weight
        self.current_qqq_weight = target_qqq_weight
        self.current_psq_weight = target_psq_weight
        self.current_tmf_weight = target_tmf_weight
        self.current_tmv_weight = target_tmv_weight

    def get_current_regime(self) -> tuple[str, str, int]:
        if self.trend_state is None or self.cell_id is None:
            return ("Sideways", "Low", 3)
        return (self.trend_state, self.vol_state, self.cell_id)
