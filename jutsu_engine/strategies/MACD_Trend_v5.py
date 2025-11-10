"""
Dynamic Regime Strategy (V9.0): VIX-filtered Goldilocks with dual playbooks.

This strategy extends MACD_Trend_v4 by adding VIX regime detection to dynamically
switch between two parameter "playbooks" optimized for different volatility environments.

Strategy Logic:
- VIX Regime Detection: Compare raw VIX to VIX_EMA_50
  * CALM regime (VIX <= VIX_EMA_50): Use slow EMA (200), wide stop (3.0 ATR)
  * CHOPPY regime (VIX > VIX_EMA_50): Use fast EMA (75), tight stop (2.0 ATR)
- Goldilocks V8.0 logic: Same 3-regime system (CASH/TQQQ/QQQ) but with dynamic parameters
- Processes 3 symbols: QQQ (signal), TQQQ (bull), VIX (regime filter)

More Info: MACD_Trend-v5.md
"""
from decimal import Decimal
from typing import Optional, Dict, List
from jutsu_engine.strategies.MACD_Trend_v4 import MACD_Trend_v4
from jutsu_engine.indicators.technical import ema


class MACD_Trend_v5(MACD_Trend_v4):
    """
    Dynamic Regime Strategy: VIX-filtered Goldilocks with adaptive parameters.

    Inherits from MACD_Trend_v4 and adds VIX regime detection to dynamically
    switch between two parameter sets ("playbooks") optimized for different
    volatility environments.

    VIX Regime Logic:
    - CALM (VIX_raw <= VIX_EMA_50): Slow EMA (200), wide stop (3.0)
    - CHOPPY (VIX_raw > VIX_EMA_50): Fast EMA (75), tight stop (2.0)

    Parameters:
        vix_symbol: Symbol for VIX data (default: 'VIX')
        vix_ema_period: VIX EMA period for regime detection (default: 50)
        ema_period_calm: EMA period for CALM regime (default: 200)
        atr_stop_calm: ATR stop multiplier for CALM regime (default: 3.0)
        ema_period_choppy: EMA period for CHOPPY regime (default: 75)
        atr_stop_choppy: ATR stop multiplier for CHOPPY regime (default: 2.0)
        (All other parameters inherited from MACD_Trend_v4)
    """

    def __init__(
        self,
        # VIX regime parameters
        vix_symbol: str = 'VIX',
        vix_ema_period: int = 50,
        ema_period_calm: int = 200,
        atr_stop_calm: Decimal = Decimal('3.0'),
        ema_period_choppy: int = 75,
        atr_stop_choppy: Decimal = Decimal('2.0'),
        # V4 parameters (inherited)
        signal_symbol: str = 'QQQ',
        bull_symbol: str = 'TQQQ',
        defense_symbol: str = 'QQQ',
        macd_fast_period: int = 12,
        macd_slow_period: int = 26,
        macd_signal_period: int = 9,
        # NOTE: ema_period will be OVERRIDDEN by regime playbooks
        ema_period: int = 200,  # Default to CALM playbook
        atr_period: int = 14,
        # NOTE: atr_stop_multiplier will be OVERRIDDEN by regime playbooks
        atr_stop_multiplier: Decimal = Decimal('3.0'),  # Default to CALM playbook
        risk_bull: Decimal = Decimal('0.025'),
        allocation_defense: Decimal = Decimal('0.60'),
    ):
        """
        Initialize Dynamic Regime strategy with VIX filter.

        Args:
            vix_symbol: Symbol for VIX data (default: 'VIX')
            vix_ema_period: VIX EMA period for regime detection (default: 50)
            ema_period_calm: EMA period for CALM regime (default: 200)
            atr_stop_calm: ATR stop multiplier for CALM regime (default: 3.0)
            ema_period_choppy: EMA period for CHOPPY regime (default: 75)
            atr_stop_choppy: ATR stop multiplier for CHOPPY regime (default: 2.0)
            (All other parameters: See MACD_Trend_v4 documentation)
        """
        # Initialize parent class with default CALM playbook parameters
        super().__init__(
            signal_symbol=signal_symbol,
            bull_symbol=bull_symbol,
            defense_symbol=defense_symbol,
            macd_fast_period=macd_fast_period,
            macd_slow_period=macd_slow_period,
            macd_signal_period=macd_signal_period,
            ema_period=ema_period,  # Will be overridden dynamically
            atr_period=atr_period,
            atr_stop_multiplier=atr_stop_multiplier,  # Will be overridden dynamically
            risk_bull=risk_bull,
            allocation_defense=allocation_defense,
        )

        # Store VIX-specific parameters
        self.vix_symbol = vix_symbol
        self.vix_ema_period = vix_ema_period

        # Convert float parameters to Decimal (prevent type mixing errors)
        self.ema_period_calm = ema_period_calm
        self.atr_stop_calm = Decimal(str(atr_stop_calm))
        self.ema_period_choppy = ema_period_choppy
        self.atr_stop_choppy = Decimal(str(atr_stop_choppy))

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

        V5 requires 3 symbols: signal_symbol, bull_symbol, vix_symbol.

        Raises:
            ValueError: If any required symbol is missing from available symbols
        """
        required_symbols = [
            self.signal_symbol,  # e.g., QQQ - signal calculations and defensive trading
            self.bull_symbol,    # e.g., TQQQ - leveraged long
            self.vix_symbol,     # e.g., VIX - regime detection
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
                f"MACD_Trend_v5 requires symbols {unique_required} but "
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
        - CALM: VIX_raw <= VIX_EMA_50 (volatility is low)
        - CHOPPY: VIX_raw > VIX_EMA_50 (volatility is elevated)

        Returns:
            'CALM' if VIX_raw <= VIX_EMA_50, 'CHOPPY' otherwise

        Note:
            Returns 'CALM' if insufficient VIX bars for calculation.
        """
        # Need enough VIX bars for EMA calculation
        if len(self._vix_bars) < self.vix_ema_period:
            return 'CALM'  # Default to CALM when insufficient data

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

    def on_bar(self, bar):
        """
        Process each bar with VIX regime detection.

        Processing order:
        1. Process VIX bars (store for VIX_EMA_50 calculation)
        2. Update regime parameters before QQQ processing
        3. Delegate to v4 logic (with updated parameters)

        Args:
            bar: Market data bar (MarketDataEvent)

        Note:
            VIX regime detection runs BEFORE v4 logic to ensure correct parameters.
        """
        # Step 1: Process VIX bars (calculate VIX_EMA_50)
        if bar.symbol == self.vix_symbol:
            self._process_vix_bar(bar)
            return

        # Step 2: Update regime parameters BEFORE signal asset processing
        if bar.symbol == self.signal_symbol:
            # Detect VIX regime
            vix_regime = self._detect_vix_regime()

            # Check for regime change
            if vix_regime != self.current_vix_regime:
                old_regime = self.current_vix_regime or 'NONE'
                self.log(
                    f"VIX REGIME CHANGE: {old_regime} → {vix_regime} | "
                    f"EMA: {self.ema_period} → "
                    f"{self.ema_period_calm if vix_regime == 'CALM' else self.ema_period_choppy}, "
                    f"ATR Stop: {self.atr_stop_multiplier} → "
                    f"{self.atr_stop_calm if vix_regime == 'CALM' else self.atr_stop_choppy}"
                )
                self.current_vix_regime = vix_regime

            # Update parameters based on VIX regime
            if vix_regime == 'CALM':
                self.ema_period = self.ema_period_calm
                self.atr_stop_multiplier = self.atr_stop_calm
            else:  # CHOPPY
                self.ema_period = self.ema_period_choppy
                self.atr_stop_multiplier = self.atr_stop_choppy

        # Step 3: Delegate to v4 logic (with updated parameters)
        super().on_bar(bar)
