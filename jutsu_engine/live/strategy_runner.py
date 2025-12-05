"""
Live Strategy Runner - Execute trading strategies on live market data.

This module runs the Hierarchical Adaptive v3.5b strategy on live/synthetic data
to generate trading signals and target allocations for automated execution.

Version: 2.0 (Flat Config - PRD v2.0.1 Compliant)
"""

import logging
import pandas as pd
from decimal import Decimal
from typing import Dict, Optional, Any, List
from pathlib import Path
import yaml

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent

logger = logging.getLogger('LIVE.STRATEGY_RUNNER')


# Parameters that should be excluded from strategy __init__
EXCLUDED_PARAMS = {'name', 'trade_logger'}

# Required strategy parameters (must be present in config)
REQUIRED_PARAMS = {
    'signal_symbol', 'leveraged_long_symbol', 'sma_fast', 'sma_slow'
}


class LiveStrategyRunner:
    """
    Execute trading strategy on live market data.

    Manages strategy lifecycle, signal calculation, and target allocation
    determination for live trading execution.

    Version 2.0 Changes:
    - Uses FLAT parameter structure (strategy.parameters)
    - **params injection instead of manual mapping
    - Validates parameters before injection
    - Captures strategy context for trade logging
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

    def _validate_parameters(self, params: Dict[str, Any]) -> None:
        """
        Validate strategy parameters before injection.

        Args:
            params: Parameters dictionary to validate

        Raises:
            ValueError: If required parameters are missing
        """
        missing = REQUIRED_PARAMS - set(params.keys())
        if missing:
            raise ValueError(f"Missing required parameters: {missing}")

        # Validate numeric parameters are valid types
        for key, value in params.items():
            if value is None:
                raise ValueError(f"Parameter '{key}' cannot be None")

        logger.debug(f"Validated {len(params)} parameters")

    def _convert_decimal_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert float parameters to Decimal for financial precision.

        The strategy expects Decimal types for financial calculations.
        This converts float values from YAML to Decimal.

        Args:
            params: Parameters dictionary

        Returns:
            Parameters with floats converted to Decimal where appropriate
        """
        # Parameters that should be Decimal (financial precision required)
        decimal_params = {
            'measurement_noise', 'process_noise_1', 'process_noise_2',
            'T_max', 't_norm_bull_thresh', 't_norm_bear_thresh',
            'upper_thresh_z', 'lower_thresh_z', 'vol_crush_threshold',
            'leverage_scalar', 'w_PSQ_max', 'max_bond_weight',
            'rebalance_threshold'
        }

        converted = params.copy()
        for key in decimal_params:
            if key in converted and not isinstance(converted[key], Decimal):
                converted[key] = Decimal(str(converted[key]))

        return converted

    def _initialize_strategy(self) -> Strategy:
        """
        Initialize strategy with parameters from config.

        Uses FLAT parameter structure - all 32 parameters directly
        under strategy.parameters. Uses **params injection for
        clean initialization.

        Returns:
            Initialized strategy instance

        Raises:
            ValueError: If strategy initialization fails
        """
        try:
            # Extract parameters from FLAT config structure
            params = self.config['strategy']['parameters'].copy()

            # Remove metadata params that shouldn't be passed to __init__
            for excluded in EXCLUDED_PARAMS:
                params.pop(excluded, None)

            # Validate required parameters are present
            self._validate_parameters(params)

            # Convert floats to Decimal for financial precision
            params = self._convert_decimal_params(params)

            # Log parameter count for verification
            logger.info(f"Initializing strategy with {len(params)} parameters")
            logger.debug(f"Parameters: {list(params.keys())}")

            # Initialize strategy with **params injection
            strategy = self.strategy_class(**params)

            # Initialize strategy (calls strategy.init())
            strategy.init()

            logger.info(f"Strategy initialized successfully: {strategy.name}")
            return strategy

        except TypeError as e:
            # Catch parameter mismatch errors with helpful message
            logger.error(f"Strategy initialization failed - parameter mismatch: {e}")
            logger.error("Ensure config parameters match strategy __init__ signature exactly")
            raise ValueError(f"Failed to initialize strategy: {e}")
        except Exception as e:
            logger.error(f"Strategy initialization failed: {e}")
            raise ValueError(f"Failed to initialize strategy: {e}")

    def get_signal_symbol(self) -> str:
        """Get the signal symbol from config."""
        return self.config['strategy']['parameters']['signal_symbol']

    def get_treasury_symbol(self) -> str:
        """Get the treasury trend symbol from config."""
        return self.config['strategy']['parameters'].get('treasury_trend_symbol', 'TLT')

    def get_all_symbols(self) -> List[str]:
        """Get all trading symbols from config."""
        params = self.config['strategy']['parameters']
        symbols = set()

        symbol_keys = [
            'signal_symbol', 'core_long_symbol', 'leveraged_long_symbol',
            'inverse_hedge_symbol', 'bull_bond_symbol', 'bear_bond_symbol',
            'treasury_trend_symbol'
        ]

        for key in symbol_keys:
            if key in params and params[key]:
                symbols.add(params[key])

        return list(symbols)

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
                - trend_state: Equity trend (BullStrong/Sideways/BearStrong)
                - bond_trend_state: Bond trend (bull/bear)
                - vol_state: Volatility regime (Low/High)
                - current_cell: Allocation matrix cell (1-6)
                - t_norm: Normalized trend indicator
                - z_score: Volatility z-score

        Raises:
            ValueError: If market data is incomplete or invalid
        """
        # Get symbols from flat config
        signal_symbol = self.get_signal_symbol()
        treasury_symbol = self.get_treasury_symbol()

        required_symbols = [signal_symbol, treasury_symbol]

        for symbol in required_symbols:
            if symbol not in market_data:
                raise ValueError(f"Missing required symbol data: {symbol}")

        logger.info("Calculating signals from market data")

        # Process bars through strategy
        signal_df = market_data[signal_symbol]
        treasury_df = market_data.get(treasury_symbol)

        # Feed bars to strategy (simulating backtest bar-by-bar processing)
        # Must call _update_bar() before on_bar() to populate internal _bars list
        for idx in range(len(signal_df)):
            row = signal_df.iloc[idx]
            bar = MarketDataEvent(
                symbol=signal_symbol,
                timestamp=row['date'],
                open=Decimal(str(row['open'])),
                high=Decimal(str(row['high'])),
                low=Decimal(str(row['low'])),
                close=Decimal(str(row['close'])),
                volume=int(row['volume']),
                timeframe="1D"
            )

            # Store bar in strategy's internal history (required for warmup check)
            self.strategy._update_bar(bar)

            # Also store treasury bar if available (strategy needs TLT for Treasury Overlay)
            if treasury_df is not None and len(treasury_df) > idx:
                treasury_row = treasury_df.iloc[idx]
                treasury_bar = MarketDataEvent(
                    symbol=treasury_symbol,
                    timestamp=treasury_row['date'],
                    open=Decimal(str(treasury_row['open'])),
                    high=Decimal(str(treasury_row['high'])),
                    low=Decimal(str(treasury_row['low'])),
                    close=Decimal(str(treasury_row['close'])),
                    volume=int(treasury_row['volume']),
                    timeframe="1D"
                )
                self.strategy._update_bar(treasury_bar)

            # Process bar through strategy
            self.strategy.on_bar(bar)

        # Extract final signals from strategy state
        signals = self.get_strategy_context()
        signals['timestamp'] = signal_df.iloc[-1]['date']

        logger.info(f"Signals calculated: Cell {signals['current_cell']}, Vol State {signals['vol_state']}")
        return signals

    def get_strategy_context(self) -> Dict[str, Any]:
        """
        Get current strategy context for trade logging.

        Captures all relevant strategy state for post-trade analysis:
        - Regime cell (1-6)
        - Trend state (BullStrong/Sideways/BearStrong)
        - Volatility state (Low/High)
        - Indicator values (t_norm, z_score)
        - Decision tree indicators (SMA fast/slow, vol-crush, bond trend)

        Returns:
            Strategy context dictionary for trade recording
        """
        return {
            'current_cell': getattr(self.strategy, 'cell_id', None),
            'trend_state': getattr(self.strategy, 'trend_state', None),
            'vol_state': getattr(self.strategy, 'vol_state', None),
            't_norm': getattr(self.strategy, '_last_t_norm', None),
            'z_score': getattr(self.strategy, '_last_z_score', None),

            # Decision tree indicators
            'sma_fast': getattr(self.strategy, '_last_sma_fast', None),
            'sma_slow': getattr(self.strategy, '_last_sma_slow', None),
            'vol_crush_triggered': getattr(self.strategy, '_last_vol_crush_triggered', False),
            'bond_sma_fast': getattr(self.strategy, '_last_bond_sma_fast', None),
            'bond_sma_slow': getattr(self.strategy, '_last_bond_sma_slow', None),
            'bond_trend': getattr(self.strategy, '_last_bond_trend', None),

            # Keep existing attributes for compatibility
            'equity_trend': getattr(self.strategy, 'trend_state', None),
            'bond_trend_state': getattr(self.strategy, '_last_bond_trend', None),  # Use _last_bond_trend instead
        }

    def determine_target_allocation(
        self,
        signals: Dict[str, Any],
        account_equity: Decimal
    ) -> Dict[str, float]:
        """
        Determine target allocation weights from signals.

        Converts strategy signals into target portfolio weights (0-1)
        for each symbol. Weights sum to 1.0 (including CASH).

        IMPORTANT: This method recalculates weights from the current cell
        allocation instead of using cached weights. This prevents issues
        where weights were zeroed during warmup (before cash injection).

        Args:
            signals: Trading signals from calculate_signals()
            account_equity: Current account equity (used for validation)

        Returns:
            Target weights: {symbol: weight} where weight is 0-1
            Example: {'TQQQ': 0.6, 'TMF': 0.2, 'CASH': 0.2}

        Raises:
            ValueError: If signals are invalid or allocation fails
        """
        logger.info(f"Determining target allocation for ${account_equity:,.2f}")

        # CRITICAL FIX: Inject cash into strategy for validation
        # This ensures _validate_weight() uses actual account equity
        # instead of warmup cash (which may be 0)
        self.strategy._cash = account_equity
        logger.debug(f"Injected ${account_equity:,.2f} into strategy for weight validation")

        # Get current cell from signals
        current_cell = signals.get('current_cell')
        if current_cell is None:
            logger.error("No current_cell in signals, defaulting to CASH")
            return {'CASH': 1.0}

        # CRITICAL FIX: Recalculate weights from cell allocation
        # This bypasses cached zeroed weights from warmup
        w_TQQQ, w_QQQ, w_PSQ, w_cash = self.strategy._get_cell_allocation(current_cell)

        # Apply leverage scalar (same as strategy does)
        w_TQQQ = w_TQQQ * self.strategy.leverage_scalar
        w_QQQ = w_QQQ * self.strategy.leverage_scalar
        w_PSQ = w_PSQ * self.strategy.leverage_scalar

        # Treasury overlay (if applicable)
        w_TMF = Decimal("0")
        w_TMV = Decimal("0")

        if self.strategy.allow_treasury and current_cell in [4, 5, 6]:
            # Get treasury trend from signals
            bond_trend = signals.get('bond_trend', None)

            # Determine defensive weight based on cell
            if current_cell == 4:
                defensive_weight = Decimal("1.0")
            elif current_cell == 5:
                defensive_weight = Decimal("0.5")
            elif current_cell == 6 and not self.strategy.use_inverse_hedge:
                defensive_weight = Decimal("1.0")
            else:
                defensive_weight = Decimal("0")

            if defensive_weight > Decimal("0") and bond_trend:
                # Calculate bond weight (40% of defensive, capped at max_bond_weight)
                bond_weight = min(defensive_weight * Decimal("0.4"), self.strategy.max_bond_weight)
                cash_weight = defensive_weight - bond_weight

                # Apply to allocation
                if bond_trend == "Bull":
                    w_TMF = bond_weight
                    w_cash = cash_weight
                elif bond_trend == "Bear":
                    w_TMV = bond_weight
                    w_cash = cash_weight

        # Normalize to ensure sum = 1.0
        total_weight = w_TQQQ + w_QQQ + w_PSQ + w_TMF + w_TMV + w_cash
        if total_weight > Decimal("0"):
            w_TQQQ = w_TQQQ / total_weight
            w_QQQ = w_QQQ / total_weight
            w_PSQ = w_PSQ / total_weight
            w_TMF = w_TMF / total_weight
            w_TMV = w_TMV / total_weight
            w_cash = w_cash / total_weight

        # Build allocation dictionary
        allocation = {}
        params = self.config['strategy']['parameters']

        symbol_mapping = {
            'leveraged_long_symbol': (w_TQQQ, 'TQQQ'),
            'core_long_symbol': (w_QQQ, 'QQQ'),
            'inverse_hedge_symbol': (w_PSQ, 'PSQ'),
            'bull_bond_symbol': (w_TMF, 'TMF'),
            'bear_bond_symbol': (w_TMV, 'TMV'),
        }

        for config_key, (weight, default_symbol) in symbol_mapping.items():
            if weight > Decimal('0'):
                symbol = params.get(config_key, default_symbol)
                allocation[symbol] = float(weight)

        # Calculate CASH as remainder
        total_allocated = sum(allocation.values())
        if total_allocated < 1.0:
            allocation['CASH'] = 1.0 - total_allocated

        if not allocation:
            logger.warning("No allocation from strategy, using default")
            allocation = {'CASH': 1.0}

        # Validate weights sum to ~1.0
        total_weight_check = sum(allocation.values())
        if not (0.99 <= total_weight_check <= 1.01):
            logger.warning(f"Weights sum to {total_weight_check:.4f}, not 1.0")

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
            Strategy state dictionary with all relevant attributes
        """
        return {
            'vol_state': getattr(self.strategy, 'vol_state', None),
            'current_cell': getattr(self.strategy, 'cell_id', None),
            'trend_state': getattr(self.strategy, 'trend_state', None),
            'bond_trend': getattr(self.strategy, 'bond_trend_state', None),
            'current_tqqq_weight': float(getattr(self.strategy, 'current_tqqq_weight', 0)),
            'current_qqq_weight': float(getattr(self.strategy, 'current_qqq_weight', 0)),
            'current_psq_weight': float(getattr(self.strategy, 'current_psq_weight', 0)),
            'current_tmf_weight': float(getattr(self.strategy, 'current_tmf_weight', 0)),
            'current_tmv_weight': float(getattr(self.strategy, 'current_tmv_weight', 0)),
        }


def main():
    """Test strategy runner with sample data."""
    logging.basicConfig(level=logging.INFO)

    try:
        runner = LiveStrategyRunner()
        logger.info("Strategy runner initialized successfully")

        # Log all symbols
        symbols = runner.get_all_symbols()
        logger.info(f"Trading symbols: {symbols}")

        # Log strategy state
        state = runner.get_strategy_state()
        logger.info(f"Strategy state: {state}")

    except Exception as e:
        logger.error(f"Strategy runner test failed: {e}")
        raise


if __name__ == "__main__":
    main()
