"""
VIX-Filtered Strategy (V10.0): Goldilocks with VIX master switch.

This strategy extends MACD_Trend_v4 by adding VIX as a "master switch" that controls
whether the base Goldilocks logic runs at all. Unlike v5 which modifies parameters,
v6 uses VIX to enable/disable trading entirely.

Core Philosophy: "Only run V8.0 (v4) when market is CALM, else hold CASH"

Strategy Logic:
- VIX Master Switch: Compare raw VIX to VIX_EMA_50
  * CALM regime (VIX <= VIX_EMA_50): Run full v4 logic (CASH/TQQQ/QQQ)
  * CHOPPY regime (VIX > VIX_EMA_50): Hold CASH (liquidate all positions)
- Hierarchical 2-step logic:
  1. Step 1 (Master Switch): VIX > VIX_EMA → CASH (STOP, don't run v4)
  2. Step 2: VIX <= VIX_EMA → Run full v4 logic
- Processes 3 symbols: QQQ (signal), TQQQ (bull), VIX (master switch)

More Info: MACD_Trend-v6.md
"""
from decimal import Decimal
from typing import Optional, List
from jutsu_engine.strategies.MACD_Trend_v4 import MACD_Trend_v4
from jutsu_engine.indicators.technical import ema


class MACD_Trend_v6(MACD_Trend_v4):
    """
    VIX-Filtered Strategy: Goldilocks with VIX master switch.

    Inherits from MACD_Trend_v4 and adds VIX regime detection as a "gate" that
    controls whether the base Goldilocks logic runs. When VIX is elevated (CHOPPY),
    the strategy liquidates all positions and holds CASH. When VIX is low (CALM),
    it runs the full v4 logic.

    VIX Master Switch Logic:
    - CHOPPY (VIX_raw > VIX_EMA_50): Liquidate → Hold CASH (don't run v4)
    - CALM (VIX_raw <= VIX_EMA_50): Run full v4 logic (CASH/TQQQ/QQQ)

    Key Difference from v5:
    - v5: Detects regime → updates params → ALWAYS runs v4 logic
    - v6: Detects regime → if CHOPPY, liquidate and RETURN (don't run v4)

    Parameters:
        vix_symbol: Symbol for VIX data (default: 'VIX')
        vix_ema_period: VIX EMA period for regime detection (default: 50)
        (All v4 parameters inherited unchanged)
    """

    def __init__(
        self,
        # VIX master switch parameters
        vix_symbol: str = '$VIX',  # Index symbols use $ prefix
        vix_ema_period: int = 50,
        # V4 parameters (inherited, all unchanged)
        signal_symbol: str = 'QQQ',
        bull_symbol: str = 'TQQQ',
        defense_symbol: str = 'QQQ',
        macd_fast_period: int = 12,
        macd_slow_period: int = 26,
        macd_signal_period: int = 9,
        ema_period: int = 100,
        atr_period: int = 14,
        atr_stop_multiplier: Decimal = Decimal('3.0'),
        risk_bull: Decimal = Decimal('0.025'),
        allocation_defense: Decimal = Decimal('0.60'),
    ):
        """
        Initialize VIX-Filtered strategy with master switch.

        Args:
            vix_symbol: Symbol for VIX data (default: '$VIX', index symbols use $ prefix)
            vix_ema_period: VIX EMA period for regime detection (default: 50)
            (All other parameters: See MACD_Trend_v4 documentation)
        """
        # Initialize parent class with all v4 parameters
        super().__init__(
            signal_symbol=signal_symbol,
            bull_symbol=bull_symbol,
            defense_symbol=defense_symbol,
            macd_fast_period=macd_fast_period,
            macd_slow_period=macd_slow_period,
            macd_signal_period=macd_signal_period,
            ema_period=ema_period,
            atr_period=atr_period,
            atr_stop_multiplier=atr_stop_multiplier,
            risk_bull=risk_bull,
            allocation_defense=allocation_defense,
        )

        # Store VIX-specific parameters
        self.vix_symbol = vix_symbol
        self.vix_ema_period = vix_ema_period

        # VIX bar history (separate from main bar history)
        self._vix_bars: List = []
        self.current_vix_regime: Optional[str] = None  # 'CALM' or 'CHOPPY'

    def init(self):
        """Initialize strategy state."""
        super().init()
        self._vix_bars = []
        self.current_vix_regime = None

    def _validate_required_symbols(self) -> None:
        """
        Validate that all required symbols are present in data handler.

        V6 requires 3 symbols: signal_symbol, bull_symbol, vix_symbol.

        Raises:
            ValueError: If any required symbol is missing from available symbols
        """
        required_symbols = [
            self.signal_symbol,  # e.g., QQQ - signal calculations and defensive trading
            self.bull_symbol,    # e.g., TQQQ - leveraged long
            self.vix_symbol,     # e.g., VIX - master switch
        ]

        # Get unique symbols from loaded bars
        available_symbols = list(set(bar.symbol for bar in self._bars))

        # Get unique required symbols count
        unique_required = list(set(required_symbols))

        # Check for missing symbols
        missing_symbols = [s for s in unique_required if s not in available_symbols]

        # Defer validation until all unique required symbols have appeared
        if missing_symbols and len(available_symbols) >= len(unique_required):
            raise ValueError(
                f"MACD_Trend_v6 requires symbols {unique_required} but "
                f"missing: {missing_symbols}. Available symbols: {available_symbols}. "
                f"Please include all required symbols in your backtest command."
            )

    def _process_vix_bar(self, bar) -> None:
        """
        Store VIX bar for regime detection.

        Maintains separate VIX bar history for VIX_EMA_50 calculation.

        Args:
            bar: VIX market data bar
        """
        self._vix_bars.append(bar)

        # Log VIX bar received (debug level)
        if len(self._vix_bars) % 50 == 0:  # Log every 50 bars to avoid noise
            self.log(f"VIX bars collected: {len(self._vix_bars)}")

    def _detect_vix_regime(self) -> str:
        """
        Determine VIX regime (CALM vs CHOPPY) based on VIX vs VIX_EMA_50.

        Logic:
        - CALM: VIX_raw <= VIX_EMA_50 (volatility is low, run v4 logic)
        - CHOPPY: VIX_raw > VIX_EMA_50 (volatility is elevated, hold CASH)

        Returns:
            'CALM' if VIX_raw <= VIX_EMA_50, 'CHOPPY' otherwise

        Note:
            Returns 'CHOPPY' if insufficient VIX bars (conservative default).
        """
        # Need enough VIX bars for EMA calculation
        if len(self._vix_bars) < self.vix_ema_period:
            return 'CHOPPY'  # Default to CHOPPY (conservative) when insufficient data

        # Calculate VIX_EMA_50
        vix_closes = [bar.close for bar in self._vix_bars[-self.vix_ema_period-10:]]
        vix_ema_values = ema(vix_closes, period=self.vix_ema_period)
        vix_ema_50 = Decimal(str(vix_ema_values.iloc[-1]))

        # Get current VIX value
        vix_raw = self._vix_bars[-1].close

        # Determine regime
        if vix_raw <= vix_ema_50:
            return 'CALM'
        else:
            return 'CHOPPY'

    def _enter_cash_regime(self) -> None:
        """
        Enter CASH regime by liquidating all positions.

        Called when VIX master switch indicates CHOPPY regime.
        Liquidates current position (if any) and prevents v4 logic from running.

        Note:
            Uses self.buy(symbol, Decimal('0.0')) to liquidate positions.
            This pattern works for both long and short positions.
        """
        # Only liquidate if we have an active position
        if self.current_position_symbol is None:
            return

        symbol = self.current_position_symbol

        # Log context BEFORE liquidation signal
        if self._trade_logger and hasattr(self, '_current_bar'):
            # Create descriptive regime message with VIX values
            if len(self._vix_bars) >= self.vix_ema_period:
                vix_current = self._vix_bars[-1].close
                vix_ema = self._last_indicator_values.get('VIX_EMA', 'N/A')
                regime_desc = f"VIX CHOPPY regime: VIX({vix_current:.2f}) > VIX_EMA({vix_ema:.2f}), Liquidating {symbol}"
            else:
                regime_desc = f"VIX CHOPPY regime (insufficient data): Liquidating {symbol} position"

            self._trade_logger.log_strategy_context(
                timestamp=self._current_bar.timestamp,
                symbol=symbol,
                strategy_state=regime_desc,
                decision_reason="VIX > VIX_EMA (master switch OFF)",
                indicator_values=self._last_indicator_values if hasattr(self, '_last_indicator_values') else {},
                threshold_values=self._last_threshold_values if hasattr(self, '_last_threshold_values') else {}
            )

        # Close position (100% exit)
        self.buy(symbol, Decimal('0.0'))  # Allocate 0% = liquidate

        self.log(f"VIX MASTER SWITCH: CHOPPY regime → Liquidated {symbol} position")

        # Clear state tracking
        self.current_position_symbol = None
        self.tqqq_entry_price = None
        self.tqqq_stop_loss = None
        self.current_regime = None  # Force regime re-evaluation when CALM returns

    def on_bar(self, bar):
        """
        Process each bar with VIX master switch gating logic.

        Processing order (hierarchical 2-step):
        1. Process VIX bars (store for VIX_EMA_50 calculation)
        2. VIX Master Switch (evaluated FIRST before v4 logic):
           - CHOPPY (VIX > VIX_EMA): Liquidate → Hold CASH → RETURN (don't call super)
           - CALM (VIX <= VIX_EMA): Continue to step 3
        3. Run v4 Goldilocks logic (only if CALM)

        Args:
            bar: Market data bar (MarketDataEvent)

        Note:
            Key difference from v5: Returns early when CHOPPY, doesn't call super().
        """
        # Step 1: Process VIX bars (calculate VIX_EMA_50)
        if bar.symbol == self.vix_symbol:
            self._process_vix_bar(bar)
            return

        # NEW: Store current bar for context logging (BEFORE checking VIX regime)
        if bar.symbol == self.signal_symbol:
            self._current_bar = bar

            # Calculate VIX indicators for logging (if sufficient data)
            if len(self._vix_bars) >= self.vix_ema_period:
                vix_closes = [b.close for b in self._vix_bars[-self.vix_ema_period-10:]]
                vix_ema_values = ema(vix_closes, period=self.vix_ema_period)
                vix_ema = Decimal(str(vix_ema_values.iloc[-1]))
                vix_current = self._vix_bars[-1].close

                # Store VIX-specific indicator/threshold values for logging
                self._last_indicator_values = {
                    'VIX': vix_current,
                    'VIX_EMA': vix_ema,
                }
                self._last_threshold_values = {
                    'vix_ema_period': self.vix_ema_period,
                }

        # Step 2: VIX Master Switch (evaluated BEFORE v4 logic)
        if bar.symbol == self.signal_symbol:
            # Detect VIX regime
            vix_regime = self._detect_vix_regime()

            # Check for regime change
            if vix_regime != self.current_vix_regime:
                old_regime = self.current_vix_regime or 'NONE'
                self.log(
                    f"VIX REGIME CHANGE: {old_regime} → {vix_regime} | "
                    f"Master Switch: {'ON (run v4)' if vix_regime == 'CALM' else 'OFF (hold CASH)'}"
                )
                self.current_vix_regime = vix_regime

            # CHOPPY regime: Liquidate and RETURN (don't run v4 logic)
            if vix_regime == 'CHOPPY':
                self._enter_cash_regime()
                return  # KEY DIFFERENCE from v5: Don't call super() when CHOPPY

        # Step 3: Run Goldilocks v4 logic (only if CALM or non-signal bars)
        super().on_bar(bar)
