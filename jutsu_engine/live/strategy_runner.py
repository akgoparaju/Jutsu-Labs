"""
Live Strategy Runner - Execute trading strategies on live market data.

This module runs the Hierarchical Adaptive v3.5b strategy on live/synthetic data
to generate trading signals and target allocations for automated execution.
"""

import logging
import pandas as pd
from decimal import Decimal
from typing import Dict, Optional, Any
from pathlib import Path
import yaml

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent

logger = logging.getLogger('LIVE.STRATEGY_RUNNER')


class LiveStrategyRunner:
    """
    Execute trading strategy on live market data.

    Manages strategy lifecycle, signal calculation, and target allocation
    determination for live trading execution.
    """

    def __init__(
        self,
        strategy_class: type[Strategy] = Hierarchical_Adaptive_v3_5b,
        config_path: Path = Path('config/live_trading_config.yaml')
    ):
        """
        Initialize strategy runner with configuration.

        Args:
            strategy_class: Strategy class to instantiate (default: Hierarchical_Adaptive_v3_5b)
            config_path: Path to configuration file

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If strategy parameters are invalid
        """
        self.strategy_class = strategy_class
        self.config_path = config_path
        self.config = self._load_config()
        self.strategy = self._initialize_strategy()

        logger.info(f"Initialized {self.strategy_class.__name__} with config from {config_path}")

    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from YAML file.

        Returns:
            Configuration dictionary

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        logger.info(f"Loaded config: {config['strategy']['name']}")
        return config

    def _initialize_strategy(self) -> Strategy:
        """
        Initialize strategy with parameters from config.

        Returns:
            Initialized strategy instance

        Raises:
            ValueError: If strategy initialization fails
        """
        try:
            # Extract strategy parameters from config
            strategy_config = self.config['strategy']
            universe = strategy_config['universe']
            trend_engine = strategy_config['trend_engine']
            vol_engine = strategy_config['volatility_engine']
            allocation = strategy_config['allocation']

            # Initialize strategy with Titan Config parameters
            # Map config keys to strategy's expected parameter names
            strategy = self.strategy_class(
                # Symbols
                signal_symbol=universe['signal_symbol'],
                core_long_symbol=universe.get('core_long_symbol', 'QQQ'),
                leveraged_long_symbol=universe['bull_symbol'],
                treasury_trend_symbol=universe['bond_signal'],
                bull_bond_symbol=universe['bull_bond'],
                bear_bond_symbol=universe['bear_bond'],
                # Trend Engine (SMA)
                sma_fast=trend_engine['equity_fast_sma'],
                sma_slow=trend_engine['equity_slow_sma'],
                bond_sma_fast=trend_engine['bond_fast_sma'],
                bond_sma_slow=trend_engine['bond_slow_sma'],
                # Volatility Engine
                realized_vol_window=vol_engine['short_window'],
                vol_baseline_window=vol_engine['long_window'],
                upper_thresh_z=vol_engine['z_upper'],
                lower_thresh_z=vol_engine['z_lower'],
                vol_crush_threshold=vol_engine['vol_crush_threshold'],
                # Allocation
                leverage_scalar=allocation['leverage_scalar'],
                use_inverse_hedge=allocation['inverse_hedge'],
                allow_treasury=allocation['safe_haven_active'],
                max_bond_weight=allocation['max_bond_weight']
            )

            # Initialize strategy (calls strategy.init())
            strategy.init()

            logger.info(f"Strategy initialized with Titan Config")
            return strategy

        except Exception as e:
            logger.error(f"Strategy initialization failed: {e}")
            raise ValueError(f"Failed to initialize strategy: {e}")

    def calculate_signals(
        self,
        market_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, Any]:
        """
        Calculate trading signals from market data.

        Processes historical + synthetic bar data through strategy logic
        to generate signals (trend state, volatility regime, etc.).

        Args:
            market_data: {symbol: DataFrame} with OHLCV data

        Returns:
            Signals dictionary with:
                - trend_state: Equity trend (bull/bear)
                - bond_trend_state: Bond trend (bull/bear)
                - vol_state: Volatility regime (-1/0/1)
                - current_cell: Allocation matrix cell (1-6)

        Raises:
            ValueError: If market data is incomplete or invalid
        """
        # Validate market data
        required_symbols = [
            self.config['strategy']['universe']['signal_symbol'],
            self.config['strategy']['universe']['bond_signal']
        ]

        for symbol in required_symbols:
            if symbol not in market_data:
                raise ValueError(f"Missing required symbol data: {symbol}")

        logger.info("Calculating signals from market data")

        # Process bars through strategy
        # Note: In live trading, we feed the complete synthetic bar dataset
        # The strategy's on_bar() method will be called for each bar
        signal_df = market_data[self.config['strategy']['universe']['signal_symbol']]
        bond_df = market_data[self.config['strategy']['universe']['bond_signal']]

        # Feed bars to strategy (simulating backtest bar-by-bar processing)
        for idx in range(len(signal_df)):
            # Create MarketDataEvent for strategy
            row = signal_df.iloc[idx]
            bar = MarketDataEvent(
                symbol=self.config['strategy']['universe']['signal_symbol'],
                timestamp=row['date'],
                open=Decimal(str(row['open'])),
                high=Decimal(str(row['high'])),
                low=Decimal(str(row['low'])),
                close=Decimal(str(row['close'])),
                volume=int(row['volume']),
                timeframe="1D"
            )

            # Process bar through strategy
            self.strategy.on_bar(bar)

        # Extract final signals from strategy state
        # Map string vol_state to numeric: "Low" → -1, "Normal" → 0, "High" → 1
        raw_vol_state = getattr(self.strategy, 'vol_state', 0)
        vol_state_map = {'Low': -1, 'Normal': 0, 'High': 1, -1: -1, 0: 0, 1: 1}
        vol_state_numeric = vol_state_map.get(raw_vol_state, 0)

        signals = {
            'trend_state': getattr(self.strategy, 'equity_trend_state', 'bull'),
            'bond_trend_state': getattr(self.strategy, 'bond_trend_state', 'bull'),
            'vol_state': vol_state_numeric,
            'current_cell': getattr(self.strategy, 'current_cell', 1),
            'timestamp': signal_df.iloc[-1]['date']
        }

        logger.info(f"Signals calculated: Cell {signals['current_cell']}, Vol State {signals['vol_state']}")
        return signals

    def determine_target_allocation(
        self,
        signals: Dict[str, Any],
        account_equity: Decimal
    ) -> Dict[str, float]:
        """
        Determine target allocation weights from signals.

        Converts strategy signals into target portfolio weights (0-1)
        for each symbol. Weights sum to 1.0 (including CASH).

        Args:
            signals: Trading signals from calculate_signals()
            account_equity: Current account equity (for logging only)

        Returns:
            Target weights: {symbol: weight} where weight is 0-1
            Example: {'TQQQ': 0.6, 'TMF': 0.2, 'CASH': 0.2}

        Raises:
            ValueError: If signals are invalid or allocation fails
        """
        logger.info(f"Determining target allocation for ${account_equity:,.2f}")

        # Get current cell and vol state
        current_cell = signals.get('current_cell', 1)
        vol_state = signals.get('vol_state', 0)

        # Call strategy's allocation method
        # Note: This assumes the strategy has calculated weights internally
        # during on_bar() processing
        allocation = getattr(self.strategy, 'current_allocation', {})

        if not allocation:
            logger.warning("No allocation from strategy, using default")
            allocation = {'CASH': 1.0}

        # Validate weights sum to ~1.0
        total_weight = sum(allocation.values())
        if not (0.99 <= total_weight <= 1.01):
            logger.warning(f"Weights sum to {total_weight:.4f}, not 1.0")

        # Log allocation
        logger.info(f"Target allocation: {allocation}")
        for symbol, weight in allocation.items():
            if weight > 0:
                logger.info(f"  {symbol}: {weight*100:.1f}%")

        return allocation

    def get_strategy_state(self) -> Dict[str, Any]:
        """
        Get current strategy internal state.

        Useful for debugging and validation reports.

        Returns:
            Strategy state dictionary
        """
        return {
            'vol_state': getattr(self.strategy, 'vol_state', None),
            'current_cell': getattr(self.strategy, 'current_cell', None),
            'equity_trend': getattr(self.strategy, 'equity_trend_state', None),
            'bond_trend': getattr(self.strategy, 'bond_trend_state', None),
            'current_allocation': getattr(self.strategy, 'current_allocation', {})
        }


def main():
    """Test strategy runner with sample data."""
    # This is a test function for development/debugging
    runner = LiveStrategyRunner()
    logger.info("Strategy runner test complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
