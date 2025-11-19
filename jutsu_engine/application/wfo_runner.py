"""
Walk-Forward Optimization (WFO) Runner.

Implements rigorous walk-forward testing methodology to defeat curve-fitting.
Periodically re-optimizes on past data (in-sample) and tests on future data (out-of-sample).

Key Algorithm:
    1. Sliding Windows: Divide total period into overlapping chunks (IS + OOS)
    2. For Each Window:
       - Optimize: Run grid search on IS period → select best parameters
       - Test: Run backtest with best params on OOS period → collect trades
       - Slide: Move window forward
    3. Stitch: Combine all OOS trades chronologically
    4. Analyze: Generate equity curve, parameter stability, final metrics

Example:
    from jutsu_engine.application.wfo_runner import WFORunner

    # Load WFO configuration
    runner = WFORunner(config_path="grid-configs/examples/wfo_macd_v6.yaml")

    # Execute WFO
    result = runner.run()

    # Access results
    print(f"OOS Return: {result['oos_return']:.2%}")
    print(f"Parameter Stability: {result['param_stability']}")
"""
import logging
import json
import shutil
import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml
import pandas as pd
from tqdm import tqdm

from jutsu_engine.application.grid_search_runner import GridSearchRunner, GridSearchConfig
from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.performance.analyzer import PerformanceAnalyzer
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('APPLICATION.WFO', log_to_console=True)


def _get_strategy_class_from_module(module):
    """
    Find concrete Strategy subclass in module, regardless of class name.

    Handles cases where module name ≠ class name (e.g., kalman_gearing.py → KalmanGearing).

    Args:
        module: Imported strategy module

    Returns:
        Strategy subclass found in module

    Raises:
        ValueError: If no Strategy subclass found or multiple candidates
    """
    from jutsu_engine.core.strategy_base import Strategy

    candidates = []
    for name, obj in inspect.getmembers(module, inspect.isclass):
        # Must be a Strategy subclass (but not Strategy itself)
        if issubclass(obj, Strategy) and obj is not Strategy:
            # Must be defined in this module (not imported from elsewhere)
            if obj.__module__ == module.__name__:
                candidates.append(obj)

    if not candidates:
        raise ValueError(f"No Strategy subclass found in {module.__name__}")
    if len(candidates) > 1:
        raise ValueError(f"Multiple Strategy subclasses in {module.__name__}: {[c.__name__ for c in candidates]}")

    return candidates[0]


def _build_strategy_params(strategy_class, symbol_set, optimization_params):
    """
    Build strategy parameters based on strategy's __init__ signature.

    Uses introspection to detect which symbol parameters the strategy accepts,
    allowing different strategies to use different parameter naming conventions.

    Also performs type conversion based on strategy's type hints - if strategy
    expects Decimal but receives float/int from YAML, automatically converts.

    Args:
        strategy_class: Strategy class (obtained from _get_strategy_class_from_module)
        symbol_set: SymbolSet or dict with symbol configuration
        optimization_params: Dict of optimization parameters from config

    Returns:
        Dict of parameters to pass to strategy __init__

    Examples:
        MACD_Trend_v6 accepts: signal_symbol, bull_symbol, defense_symbol, vix_symbol
        KalmanGearing accepts: signal_symbol, bull_3x_symbol, bear_3x_symbol, unleveraged_symbol

        This function passes only the parameters each strategy expects.
    """
    from typing import get_type_hints

    # Get strategy's __init__ parameters
    sig = inspect.signature(strategy_class.__init__)
    param_names = set(sig.parameters.keys()) - {'self'}

    strategy_params = {}

    # Conditionally add symbol parameters (only if strategy accepts them AND value exists)
    # Handle both dict and SymbolSet object access
    signal_sym = symbol_set.get('signal_symbol') if isinstance(symbol_set, dict) else symbol_set.signal_symbol
    bull_sym = symbol_set.get('bull_symbol') if isinstance(symbol_set, dict) else symbol_set.bull_symbol
    defense_sym = symbol_set.get('defense_symbol') if isinstance(symbol_set, dict) else symbol_set.defense_symbol
    vix_sym = symbol_set.get('vix_symbol') if isinstance(symbol_set, dict) else symbol_set.vix_symbol

    # Map config symbols to strategy-specific parameter names
    # MACD strategies use: bull_symbol, defense_symbol
    # KalmanGearing uses: bull_3x_symbol, bear_3x_symbol, unleveraged_symbol
    if 'signal_symbol' in param_names and signal_sym:
        strategy_params['signal_symbol'] = signal_sym
    if 'bull_symbol' in param_names and bull_sym:
        strategy_params['bull_symbol'] = bull_sym
    if 'bull_3x_symbol' in param_names and bull_sym:
        strategy_params['bull_3x_symbol'] = bull_sym
    if 'defense_symbol' in param_names and defense_sym:
        strategy_params['defense_symbol'] = defense_sym
    if 'unleveraged_symbol' in param_names and defense_sym:
        strategy_params['unleveraged_symbol'] = defense_sym
    if 'bear_3x_symbol' in param_names and defense_sym:
        # Use defense_symbol for bear_3x_symbol if not specified separately
        strategy_params['bear_3x_symbol'] = defense_sym
    if 'vix_symbol' in param_names and vix_sym:
        strategy_params['vix_symbol'] = vix_sym

    # Type introspection: Convert optimization params based on strategy's type hints
    try:
        type_hints = get_type_hints(strategy_class.__init__)
    except (AttributeError, NameError):
        # Fallback if type hints not available
        type_hints = {}

    # Convert optimization parameters based on expected types
    converted_params = {}
    for param_name, param_value in optimization_params.items():
        # Skip None values
        if param_value is None:
            converted_params[param_name] = param_value
            continue

        # Check if parameter has type hint
        if param_name in type_hints:
            expected_type = type_hints[param_name]

            # If Decimal expected but got float/int, convert
            if expected_type is Decimal and isinstance(param_value, (float, int)):
                converted_params[param_name] = Decimal(str(param_value))
            else:
                # Keep original value (type already matches or no conversion needed)
                converted_params[param_name] = param_value
        else:
            # No type hint, use original value
            converted_params[param_name] = param_value

    # Add converted optimization parameters
    strategy_params.update(converted_params)

    return strategy_params


class WFOConfigError(Exception):
    """Invalid WFO configuration."""
    pass


class WFOWindowError(Exception):
    """Error calculating or processing WFO windows."""
    pass


class WFOOptimizationError(Exception):
    """Error during IS optimization phase."""
    pass


class WFOTestingError(Exception):
    """Error during OOS testing phase."""
    pass


@dataclass
class WFOWindow:
    """
    Single WFO window definition.

    Attributes:
        window_id: Sequential window identifier (1, 2, 3, ...)
        is_start: In-sample period start date
        is_end: In-sample period end date
        oos_start: Out-of-sample period start date
        oos_end: Out-of-sample period end date
    """
    window_id: int
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime


@dataclass
class WindowResult:
    """
    Results from single WFO window.

    Attributes:
        window: Window definition
        best_params: Selected parameters from IS optimization
        metric_value: Selection metric value for best params
        oos_trades: DataFrame with OOS trades
        oos_metrics: Performance metrics from OOS testing
    """
    window: WFOWindow
    best_params: Dict[str, Any]
    metric_value: float
    oos_trades: pd.DataFrame
    oos_metrics: Dict[str, float]


class WFORunner:
    """
    Walk-Forward Optimization orchestrator.

    Coordinates complete WFO workflow:
    - Window date calculation (sliding IS/OOS periods)
    - IS optimization via GridSearchRunner
    - Parameter selection by metric
    - OOS testing via BacktestRunner
    - Result aggregation and equity curve generation

    Attributes:
        config_path: Path to WFO YAML configuration
        config: Parsed WFO configuration
        output_dir: Output directory path
    """

    def __init__(self, config_path: str, output_dir: Optional[str] = None):
        """
        Initialize WFO runner.

        Args:
            config_path: Path to WFO YAML configuration
            output_dir: Custom output directory (default: auto-generated)

        Raises:
            WFOConfigError: If configuration is invalid

        Example:
            runner = WFORunner("grid-configs/examples/wfo_macd_v6.yaml")
        """
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise WFOConfigError(f"Config file not found: {config_path}")

        self.config = self._load_config()
        self.output_dir = Path(output_dir) if output_dir else self._generate_output_dir()

        logger.info(
            f"WFORunner initialized: {self.config['strategy']}, "
            f"{self.config['walk_forward']['window_size_years']}y windows"
        )

    def _load_config(self) -> Dict[str, Any]:
        """
        Load and validate WFO configuration.

        Returns:
            Validated configuration dictionary

        Raises:
            WFOConfigError: If configuration is invalid
        """
        try:
            with open(self.config_path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise WFOConfigError(f"Invalid YAML: {e}")

        # Validate required sections
        required = ['strategy', 'symbol_sets', 'base_config', 'parameters', 'walk_forward']
        missing = [key for key in required if key not in data]
        if missing:
            raise WFOConfigError(f"Missing required sections: {', '.join(missing)}")

        # Validate walk_forward section
        wf = data['walk_forward']
        required_wf = [
            'total_start_date', 'total_end_date', 'window_size_years',
            'in_sample_years', 'out_of_sample_years', 'slide_years', 'selection_metric'
        ]
        missing_wf = [key for key in required_wf if key not in wf]
        if missing_wf:
            raise WFOConfigError(f"Missing walk_forward keys: {', '.join(missing_wf)}")

        # Validate date strings
        try:
            datetime.strptime(wf['total_start_date'], '%Y-%m-%d')
            datetime.strptime(wf['total_end_date'], '%Y-%m-%d')
        except ValueError as e:
            raise WFOConfigError(f"Invalid date format (use YYYY-MM-DD): {e}")

        # Validate numeric values
        if wf['in_sample_years'] + wf['out_of_sample_years'] != wf['window_size_years']:
            raise WFOConfigError(
                "in_sample_years + out_of_sample_years must equal window_size_years"
            )

        if wf['slide_years'] <= 0:
            raise WFOConfigError("slide_years must be positive")

        logger.info(f"Configuration loaded from: {self.config_path}")
        return data

    def _generate_output_dir(self) -> Path:
        """Generate default output directory with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        strategy_name = self.config['strategy']
        return Path("output") / f"wfo_{strategy_name}_{timestamp}"

    def calculate_windows(self) -> List[WFOWindow]:
        """
        Calculate all WFO window date ranges.

        Uses sliding window approach to generate overlapping IS/OOS periods.
        Stops when OOS period would exceed total end date.

        Returns:
            List of WFOWindow objects

        Raises:
            WFOWindowError: If window calculation fails

        Example:
            windows = runner.calculate_windows()
            print(f"Total windows: {len(windows)}")
        """
        wf = self.config['walk_forward']

        try:
            # Parse dates
            total_start = datetime.strptime(wf['total_start_date'], '%Y-%m-%d')
            total_end = datetime.strptime(wf['total_end_date'], '%Y-%m-%d')

            # Extract years
            is_years = wf['in_sample_years']
            oos_years = wf['out_of_sample_years']
            slide_years = wf['slide_years']

            windows = []
            window_id = 1
            current_start = total_start

            while True:
                # Calculate IS period
                is_start = current_start
                is_end = is_start + timedelta(days=365.25 * is_years)

                # Calculate OOS period
                oos_start = is_end
                oos_end = oos_start + timedelta(days=365.25 * oos_years)

                # Stop if OOS exceeds total end date
                if oos_end > total_end:
                    break

                windows.append(WFOWindow(
                    window_id=window_id,
                    is_start=is_start,
                    is_end=is_end,
                    oos_start=oos_start,
                    oos_end=oos_end
                ))

                # Slide window forward
                current_start = current_start + timedelta(days=365.25 * slide_years)
                window_id += 1

            if not windows:
                raise WFOWindowError(
                    f"No windows generated. Check date range and window sizes. "
                    f"Total period: {total_start} to {total_end}, "
                    f"Window size: {wf['window_size_years']}y"
                )

            logger.info(
                f"Calculated {len(windows)} windows: "
                f"{windows[0].is_start.date()} to {windows[-1].oos_end.date()}"
            )

            return windows

        except Exception as e:
            raise WFOWindowError(f"Window calculation failed: {e}")

    def select_best_parameters(
        self,
        grid_results_df: pd.DataFrame,
        selection_metric: str = 'sharpe_ratio'
    ) -> tuple[Dict[str, Any], float]:
        """
        Select best parameter set from grid search results.

        Args:
            grid_results_df: Grid search summary_comparison.csv DataFrame
            selection_metric: Metric to optimize (default: 'sharpe_ratio')

        Returns:
            Tuple of (best_params dict, metric_value)

        Raises:
            WFOOptimizationError: If selection fails

        Example:
            best_params, metric_val = runner.select_best_parameters(df, 'sharpe_ratio')
        """
        try:
            # Map metric names to CSV column names
            metric_column_map = {
                'sharpe_ratio': 'Sharpe Ratio',
                'sortino_ratio': 'Sortino Ratio',
                'calmar_ratio': 'Calmar Ratio',
                'total_return': 'Total Return %',
                'annualized_return': 'Annualized Return %'
            }

            column_name = metric_column_map.get(selection_metric, selection_metric)

            if column_name not in grid_results_df.columns:
                raise WFOOptimizationError(
                    f"Metric column '{column_name}' not found in grid results. "
                    f"Available: {list(grid_results_df.columns)}"
                )

            # Filter out baseline row (000) and error rows
            valid_results = grid_results_df[
                (grid_results_df['Run ID'] != '000') &
                (grid_results_df[column_name] != 'N/A')
            ].copy()

            if valid_results.empty:
                raise WFOOptimizationError("No valid results in grid search")

            # Convert to numeric
            valid_results[column_name] = pd.to_numeric(valid_results[column_name])

            # Find best (highest metric value)
            best_idx = valid_results[column_name].idxmax()
            best_row = valid_results.loc[best_idx]

            # Extract parameter columns (exclude metric and metadata columns)
            exclude_cols = [
                'Run ID', 'Symbol Set', 'Portfolio Balance',
                'Total Return %', 'Annualized Return %', 'Max Drawdown',
                'Sharpe Ratio', 'Sortino Ratio', 'Calmar Ratio',
                'Total Trades', 'Profit Factor', 'Win Rate %',
                'Avg Win ($)', 'Avg Loss ($)', 'Alpha', 'Error'
            ]

            param_cols = [col for col in best_row.index if col not in exclude_cols]

            # Build parameters dict (convert Title Case back to snake_case)
            param_mapping_reverse = {
                'EMA Period': 'ema_period',
                'ATR Stop Multiplier': 'atr_stop_multiplier',
                'Risk Bull': 'risk_bull',
                'MACD Fast Period': 'macd_fast_period',
                'MACD Slow Period': 'macd_slow_period',
                'MACD Signal Period': 'macd_signal_period',
                'ATR Period': 'atr_period',
                'Allocation Defense': 'allocation_defense',
                'VIX EMA Period': 'vix_ema_period',
            }

            best_params = {}
            for col in param_cols:
                param_name = param_mapping_reverse.get(col, col.lower().replace(' ', '_'))
                best_params[param_name] = best_row[col]

            metric_value = float(best_row[column_name])

            logger.debug(
                f"Selected best params: {best_params} "
                f"({selection_metric}={metric_value:.4f})"
            )

            return best_params, metric_value

        except Exception as e:
            raise WFOOptimizationError(f"Parameter selection failed: {e}")

    def generate_equity_curve(
        self,
        trades_df: pd.DataFrame,
        initial_capital: Decimal
    ) -> pd.DataFrame:
        """
        Generate WFO equity curve from combined complete trades.

        Args:
            trades_df: DataFrame with Trade_Return_Percent column (from combined trades)
            initial_capital: Starting portfolio value

        Returns:
            DataFrame with columns: Trade_Number, Exit_Date, Equity, Trade_Return_Percent

        Note:
            Trade_Return_Percent is the INDIVIDUAL trade return, not cumulative.
            Example: Trade went from $10,836 to $11,035 = +1.834% for that trade.
            The Equity column still compounds correctly.

        Example:
            equity_curve = runner.generate_equity_curve(trades_master, Decimal('10000'))
        """
        # Validate required column
        if 'Trade_Return_Percent' not in trades_df.columns:
            raise ValueError(
                "Missing 'Trade_Return_Percent' column. "
                "trades_df must contain combined trade records (use _combine_trade_pairs first)."
            )

        if 'Exit_Date' not in trades_df.columns:
            raise ValueError(
                "Missing 'Exit_Date' column. "
                "trades_df must contain combined trade records with Exit_Date."
            )

        # Sort by Exit_Date (chronological order of completed trades)
        trades_sorted = trades_df.sort_values('Exit_Date').reset_index(drop=True)

        # Initialize equity
        equity = initial_capital
        equity_curve = []

        # Add starting point (no trade yet)
        equity_curve.append({
            'Trade_Number': 0,
            'Date': None,
            'Equity': float(equity),
            'Trade_Return_Percent': 0.0  # No trade, no return
        })

        # Iterate trades and compound
        for idx, trade in trades_sorted.iterrows():
            # Get the trade return from the combined trades DataFrame
            trade_return_pct = float(trade['Trade_Return_Percent'])

            # Calculate new equity by compounding
            new_equity = equity * (Decimal('1.0') + Decimal(str(trade_return_pct)))

            equity_curve.append({
                'Trade_Number': idx + 1,
                'Date': trade['Exit_Date'],  # Use Exit_Date for completed trades
                'Equity': float(new_equity),
                'Trade_Return_Percent': trade_return_pct  # Individual trade return
            })

            # Update equity for next iteration
            equity = new_equity

        logger.debug(
            f"Generated equity curve: {len(equity_curve)} points, "
            f"final equity: ${equity:,.2f}"
        )

        return pd.DataFrame(equity_curve)

    def _generate_monte_carlo_input(
        self,
        trades_df: pd.DataFrame,
        initial_capital: Decimal
    ) -> Path:
        """
        Generate Monte Carlo simulation input file from WFO OOS combined trades.

        Since trades_df now contains combined trade records (from _combine_trade_pairs),
        we can directly use the Trade_Return_Percent and date columns.

        Output Format:
            CSV with 5 columns:
            1. Portfolio_Return_Percent: Per-trade portfolio return (gets shuffled in MC)
            2. Exit_Date: Date trade was closed
            3. Entry_Date: Date trade was opened
            4. Symbol: Ticker traded
            5. OOS_Period_ID: WFO window identifier

        Args:
            trades_df: DataFrame with combined trades (from _combine_trade_pairs)
            initial_capital: Starting portfolio value (for validation)

        Returns:
            Path to generated monte_carlo_input.csv file

        Raises:
            ValueError: If required columns missing or data validation fails

        Example:
            mc_path = runner._generate_monte_carlo_input(trades_master, Decimal('10000'))
            # Creates: output/wfo_*/monte_carlo_input.csv
        """
        # Validate required columns
        required_cols = ['Entry_Date', 'Exit_Date', 'Symbol', 'Trade_Return_Percent', 'OOS_Period_ID']
        missing_cols = [col for col in required_cols if col not in trades_df.columns]
        if missing_cols:
            raise ValueError(
                f"Missing required columns for Monte Carlo input: {missing_cols}. "
                f"Available columns: {trades_df.columns.tolist()}"
            )

        # Create MC input DataFrame (rename column for consistency with MC simulation expectations)
        mc_input_df = pd.DataFrame({
            'Portfolio_Return_Percent': trades_df['Trade_Return_Percent'],
            'Exit_Date': trades_df['Exit_Date'],
            'Entry_Date': trades_df['Entry_Date'],
            'Symbol': trades_df['Symbol'],
            'OOS_Period_ID': trades_df['OOS_Period_ID']
        })

        # Validate data quality
        if mc_input_df['Portfolio_Return_Percent'].isna().any():
            raise ValueError(
                "NaN values detected in portfolio returns. Check Trade_Return_Percent data."
            )

        if len(mc_input_df) == 0:
            logger.warning("No completed trades found for Monte Carlo input")
            # Create empty DataFrame with correct columns
            mc_input_df = pd.DataFrame(columns=[
                'Portfolio_Return_Percent',
                'Exit_Date',
                'Entry_Date',
                'Symbol',
                'OOS_Period_ID'
            ])
        else:
            # Log statistics for validation
            mean_return = mc_input_df['Portfolio_Return_Percent'].mean()
            std_return = mc_input_df['Portfolio_Return_Percent'].std()
            min_return = mc_input_df['Portfolio_Return_Percent'].min()
            max_return = mc_input_df['Portfolio_Return_Percent'].max()

            logger.info(
                f"Monte Carlo input statistics: "
                f"mean={mean_return:.4f}, std={std_return:.4f}, "
                f"min={min_return:.4f}, max={max_return:.4f}"
            )

        # Save to CSV
        output_path = self.output_dir / "monte_carlo_input.csv"
        mc_input_df.to_csv(output_path, index=False)

        logger.info(
            f"Monte Carlo input generated: {len(mc_input_df)} completed trades"
        )

        return output_path

    def run(self) -> Dict[str, Any]:
        """
        Execute complete WFO workflow.

        Orchestrates:
        1. Window calculation
        2. For each window: IS optimization + OOS testing
        3. Trade aggregation and equity curve generation
        4. Output file generation
        5. Summary report

        Returns:
            Dictionary with WFO results and output paths

        Example:
            result = runner.run()
            print(f"OOS Return: {result['oos_return_pct']:.2%}")
        """
        logger.info("=" * 60)
        logger.info("STARTING WALK-FORWARD OPTIMIZATION")
        logger.info("=" * 60)

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory: {self.output_dir}")

        # Copy config for reference
        config_copy = self.output_dir / "wfo_config.yaml"
        shutil.copy(self.config_path, config_copy)
        logger.info(f"Configuration copied to: {config_copy}")

        # Calculate windows
        windows = self.calculate_windows()
        logger.info(f"Total windows: {len(windows)}")

        # Process each window
        window_results = []
        for window in tqdm(windows, desc="WFO Windows"):
            logger.info("=" * 60)
            logger.info(f"WINDOW {window.window_id}/{len(windows)}")
            logger.info("=" * 60)
            logger.info(f"IS Period:  {window.is_start.date()} to {window.is_end.date()}")
            logger.info(f"OOS Period: {window.oos_start.date()} to {window.oos_end.date()}")

            try:
                # IS Optimization
                result = self._run_is_optimization(window)

                # OOS Testing
                oos_result = self._run_oos_testing(window, result['best_params'])

                # Create window result
                window_result = WindowResult(
                    window=window,
                    best_params=result['best_params'],
                    metric_value=result['metric_value'],
                    oos_trades=oos_result['trades_df'],
                    oos_metrics=oos_result['metrics']
                )

                window_results.append(window_result)

                logger.info(
                    f"Window {window.window_id} complete: "
                    f"{len(oos_result['trades_df'])} OOS trades"
                )

            except Exception as e:
                logger.error(
                    f"Window {window.window_id} failed: {e}",
                    exc_info=True
                )
                # Continue with remaining windows
                continue

        if not window_results:
            raise WFOTestingError("All windows failed. Check logs for details.")

        logger.info("=" * 60)
        logger.info("GENERATING WFO OUTPUTS")
        logger.info("=" * 60)

        # Generate outputs
        outputs = self._generate_outputs(window_results)

        logger.info("=" * 60)
        logger.info("WALK-FORWARD OPTIMIZATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total Windows: {len(window_results)}")
        logger.info(f"Total OOS Trades: {outputs['total_oos_trades']}")
        logger.info(f"Final Equity: ${outputs['final_equity']:,.2f}")
        logger.info(f"OOS Return: {outputs['oos_return_pct']:.2%}")
        logger.info(f"Output Directory: {self.output_dir}")
        logger.info("=" * 60)

        return outputs

    def _run_is_optimization(self, window: WFOWindow) -> Dict[str, Any]:
        """
        Run in-sample optimization using GridSearchRunner.

        Args:
            window: WFO window definition

        Returns:
            Dict with best_params and metric_value

        Raises:
            WFOOptimizationError: If optimization fails
        """
        logger.info(f"IS Optimization: Running grid search...")

        try:
            # Create grid search config (modify dates for IS period)
            gs_config = self.config.copy()
            gs_config['base_config'] = gs_config['base_config'].copy()
            gs_config['base_config']['start_date'] = window.is_start.strftime('%Y-%m-%d')
            gs_config['base_config']['end_date'] = window.is_end.strftime('%Y-%m-%d')

            # Save temporary config
            window_dir = self.output_dir / f"window_{window.window_id:03d}"
            window_dir.mkdir(exist_ok=True)

            temp_config_path = window_dir / "is_config.yaml"
            with open(temp_config_path, 'w') as f:
                yaml.dump(gs_config, f, default_flow_style=False)

            # Load as GridSearchConfig
            grid_config = GridSearchRunner.load_config(str(temp_config_path))

            # Run grid search
            grid_runner = GridSearchRunner(grid_config)
            is_output_dir = window_dir / "is_grid_search"

            grid_result = grid_runner.execute_grid_search(
                output_base=str(is_output_dir.parent),
                config_path=str(temp_config_path)
            )

            # Select best parameters
            selection_metric = self.config['walk_forward']['selection_metric']
            best_params, metric_value = self.select_best_parameters(
                grid_result.summary_df,
                selection_metric
            )

            logger.info(
                f"IS Optimization complete: {len(grid_result.run_results)} combinations tested, "
                f"best {selection_metric}={metric_value:.4f}"
            )

            return {
                'best_params': best_params,
                'metric_value': metric_value,
                'grid_output_dir': grid_result.output_dir
            }

        except Exception as e:
            raise WFOOptimizationError(
                f"IS optimization failed for window {window.window_id}: {e}"
            )

    def _run_oos_testing(
        self,
        window: WFOWindow,
        best_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Run out-of-sample testing using BacktestRunner.

        Args:
            window: WFO window definition
            best_params: Best parameters from IS optimization

        Returns:
            Dict with trades_df and metrics

        Raises:
            WFOTestingError: If OOS testing fails
        """
        logger.info(f"OOS Testing: Running backtest with best params...")

        try:
            # Get symbol set (assume first for now - could extend to multiple)
            symbol_set = self.config['symbol_sets'][0]

            # Import strategy dynamically (MUST happen before building strategy_params)
            import importlib
            module = importlib.import_module(f"jutsu_engine.strategies.{self.config['strategy']}")
            strategy_class = _get_strategy_class_from_module(module)

            # Prepare symbols list
            symbols = [
                symbol_set['signal_symbol'],
                symbol_set['bull_symbol'],
                symbol_set['defense_symbol']
            ]
            if symbol_set.get('vix_symbol'):
                symbols.append(symbol_set['vix_symbol'])

            # Prepare strategy params using introspection
            strategy_params = _build_strategy_params(
                strategy_class,
                symbol_set,
                best_params
            )

            # Prepare backtest config
            # IMPORTANT: Map commission/slippage keys to BacktestRunner's expected names
            config = {
                **self.config['base_config'],
                'start_date': window.oos_start,
                'end_date': window.oos_end,
                'symbols': symbols,
                'strategy_name': self.config['strategy'],
                'strategy_params': strategy_params,
                # Map config keys: base_config has 'commission'/'slippage' (floats)
                # but BacktestRunner expects 'commission_per_share'/'slippage_percent' (Decimals)
                'commission_per_share': Decimal(str(self.config['base_config'].get('commission', 0.0))),
                'slippage_percent': Decimal(str(self.config['base_config'].get('slippage', 0.0))),
            }

            # Run backtest
            runner = BacktestRunner(config)

            # Instantiate strategy with introspection-based params
            strategy = strategy_class(**strategy_params)

            # Create output directory
            window_dir = self.output_dir / f"window_{window.window_id:03d}"
            oos_output_dir = window_dir / "oos_backtest"

            result = runner.run(strategy, output_dir=str(oos_output_dir))

            # Load trades from CSV
            trades_csv = Path(result['trades_csv_path'])
            if not trades_csv.exists():
                raise WFOTestingError(f"Trades CSV not found: {trades_csv}")

            trades_df = pd.read_csv(trades_csv)

            # Add window metadata
            trades_df['OOS_Period_ID'] = f"Window_{window.window_id:03d}"
            trades_df['Parameters_Used'] = str(best_params)

            logger.info(
                f"OOS Testing complete: {len(trades_df)} trades, "
                f"return={result['total_return']:.2%}"
            )

            return {
                'trades_df': trades_df,
                'metrics': {
                    'total_return': result['total_return'],
                    'sharpe_ratio': result['sharpe_ratio'],
                    'max_drawdown': result['max_drawdown'],
                    'total_trades': result['total_trades']
                }
            }

        except Exception as e:
            raise WFOTestingError(
                f"OOS testing failed for window {window.window_id}: {e}"
            )

    def _combine_trade_pairs(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """
        Combine BUY/SELL transaction pairs into complete trade records.

        Uses FIFO matching: first BUY matched with first SELL for each symbol.

        Args:
            trades_df: DataFrame with separate BUY/SELL transaction rows

        Returns:
            DataFrame with complete trades (one row per BUY/SELL pair):
            - Entry_Date, Exit_Date, Symbol, OOS_Period_ID
            - Entry_Portfolio_Value, Exit_Portfolio_Value
            - Trade_Return_Percent (calculated from entry to exit)
            - Shares, Entry_Price, Exit_Price
            - Commission_Total, Slippage_Total
            - Parameters_Used
        """
        # Sort by Date first for chronological processing
        trades_sorted = trades_df.sort_values('Date').reset_index(drop=True)

        # Track open positions (FIFO queue)
        open_positions = {}  # {symbol: [list of BUY records]}
        completed_trades = []

        for _, row in trades_sorted.iterrows():
            symbol = row['Ticker']
            decision = row['Decision']

            if decision == 'BUY':
                # Open position - add to queue
                if symbol not in open_positions:
                    open_positions[symbol] = []
                open_positions[symbol].append(row)

            elif decision == 'SELL' and symbol in open_positions and open_positions[symbol]:
                # Close position - match with first BUY (FIFO)
                buy_record = open_positions[symbol].pop(0)

                # Calculate trade return (entry to exit portfolio value change)
                entry_value = buy_record['Portfolio_Value_Before']
                exit_value = row['Portfolio_Value_After']
                trade_return = (exit_value - entry_value) / entry_value

                # Create combined trade record
                completed_trades.append({
                    'Entry_Date': buy_record['Date'],
                    'Exit_Date': row['Date'],
                    'Symbol': symbol,
                    'OOS_Period_ID': row['OOS_Period_ID'],
                    'Entry_Portfolio_Value': float(entry_value),
                    'Exit_Portfolio_Value': float(exit_value),
                    'Trade_Return_Percent': float(trade_return),
                    'Shares': buy_record['Shares'],
                    'Entry_Price': float(buy_record['Fill_Price']),
                    'Exit_Price': float(row['Fill_Price']),
                    'Commission_Total': float(buy_record['Commission'] + row['Commission']),
                    'Slippage_Total': float(buy_record['Slippage'] + row['Slippage']),
                    'Parameters_Used': row.get('Parameters_Used', ''),
                })

        # Warn about unclosed positions
        unclosed_count = sum(len(positions) for positions in open_positions.values())
        if unclosed_count > 0:
            logger.warning(
                f"{unclosed_count} unclosed positions at end of WFO. "
                f"These will not appear in wfo_trades_master.csv"
            )

        if not completed_trades:
            logger.warning("No completed trades found (all positions may be open)")
            return pd.DataFrame(columns=[
                'Entry_Date', 'Exit_Date', 'Symbol', 'OOS_Period_ID',
                'Entry_Portfolio_Value', 'Exit_Portfolio_Value', 'Trade_Return_Percent',
                'Shares', 'Entry_Price', 'Exit_Price', 'Commission_Total', 'Slippage_Total',
                'Parameters_Used'
            ])

        logger.info(
            f"Combined {len(trades_sorted)} transactions into {len(completed_trades)} complete trades"
        )

        return pd.DataFrame(completed_trades)

    def _generate_outputs(self, window_results: List[WindowResult]) -> Dict[str, Any]:
        """
        Generate all WFO output files.

        Args:
            window_results: List of window results

        Returns:
            Dict with output paths and summary metrics
        """
        # 1. Aggregate OOS trades
        all_trades = []
        for result in window_results:
            all_trades.append(result.oos_trades)

        trades_master = pd.concat(all_trades, ignore_index=True)

        # Validate required columns exist
        if 'Date' not in trades_master.columns:
            raise ValueError(
                f"Missing 'Date' column in trades data. "
                f"Available columns: {trades_master.columns.tolist()}"
            )

        # CRITICAL: Combine BUY/SELL pairs BEFORE sorting/saving
        # This transforms 2N transaction rows into N complete trade rows
        logger.info(f"Processing {len(trades_master)} transactions for complete trade pairing...")
        trades_master = self._combine_trade_pairs(trades_master)

        # Sort by exit date (chronological order of completed trades)
        trades_master = trades_master.sort_values('Exit_Date').reset_index(drop=True)

        # Save trades master
        trades_master_path = self.output_dir / "wfo_trades_master.csv"
        trades_master.to_csv(trades_master_path, index=False)
        logger.info(f"Trades master saved: {trades_master_path} ({len(trades_master)} trades)")

        # 2. Generate parameter log
        param_log = []
        for result in window_results:
            row = {
                'OOS_Period_ID': f"Window_{result.window.window_id:03d}",
                'IS_Start_Date': result.window.is_start.strftime('%Y-%m-%d'),
                'IS_End_Date': result.window.is_end.strftime('%Y-%m-%d'),
                'OOS_Start_Date': result.window.oos_start.strftime('%Y-%m-%d'),
                'OOS_End_Date': result.window.oos_end.strftime('%Y-%m-%d'),
                'Selection_Metric_Value': result.metric_value,
                **result.best_params
            }
            param_log.append(row)

        param_log_df = pd.DataFrame(param_log)
        param_log_path = self.output_dir / "wfo_parameter_log.csv"
        param_log_df.to_csv(param_log_path, index=False)
        logger.info(f"Parameter log saved: {param_log_path}")

        # 3. Generate equity curve
        initial_capital = Decimal(str(self.config['base_config']['initial_capital']))
        equity_curve = self.generate_equity_curve(trades_master, initial_capital)

        equity_curve_path = self.output_dir / "wfo_equity_curve.csv"
        equity_curve.to_csv(equity_curve_path, index=False)
        logger.info(f"Equity curve saved: {equity_curve_path}")

        # 4. Generate Monte Carlo input file
        mc_input_path = self._generate_monte_carlo_input(trades_master, initial_capital)
        logger.info(f"Monte Carlo input saved: {mc_input_path}")

        # 5. Generate summary
        final_equity = equity_curve['Equity'].iloc[-1]
        oos_return = (final_equity - float(initial_capital)) / float(initial_capital)

        summary = self._generate_summary_report(
            window_results,
            trades_master,
            equity_curve,
            float(initial_capital),
            final_equity,
            oos_return
        )

        summary_path = self.output_dir / "wfo_summary.txt"
        with open(summary_path, 'w') as f:
            f.write(summary)
        logger.info(f"Summary report saved: {summary_path}")

        return {
            'output_dir': str(self.output_dir),
            'num_windows': len(window_results),
            'total_oos_trades': len(trades_master),
            'final_equity': final_equity,
            'oos_return_pct': oos_return,
            'output_files': {
                'trades_master': str(trades_master_path),
                'parameter_log': str(param_log_path),
                'equity_curve': str(equity_curve_path),
                'monte_carlo_input': str(mc_input_path),
                'summary': str(summary_path)
            }
        }

    def _generate_summary_report(
        self,
        window_results: List[WindowResult],
        trades_master: pd.DataFrame,
        equity_curve: pd.DataFrame,
        initial_capital: float,
        final_equity: float,
        oos_return: float
    ) -> str:
        """Generate comprehensive WFO summary report."""
        # Calculate parameter stability (coefficient of variation for numeric params)
        param_stability = {}
        param_log = pd.DataFrame([r.best_params for r in window_results])

        for col in param_log.columns:
            if pd.api.types.is_numeric_dtype(param_log[col]):
                mean = param_log[col].mean()
                std = param_log[col].std()
                if mean != 0:
                    cv = (std / mean) * 100
                    param_stability[col] = cv

        # Calculate drawdown from equity curve
        equity_series = pd.Series(equity_curve['Equity'].values)
        cummax = equity_series.cummax()
        drawdown = (equity_series - cummax) / cummax
        max_drawdown = drawdown.min()

        # Build report
        report = f"""
Walk-Forward Optimization Results
==================================

Strategy: {self.config['strategy']}
Date Range: {self.config['walk_forward']['total_start_date']} to {self.config['walk_forward']['total_end_date']}
Selection Metric: {self.config['walk_forward']['selection_metric']}

Window Configuration
--------------------
Window Size: {self.config['walk_forward']['window_size_years']} years
In-Sample: {self.config['walk_forward']['in_sample_years']} years
Out-of-Sample: {self.config['walk_forward']['out_of_sample_years']} years
Slide Amount: {self.config['walk_forward']['slide_years']} years
Total Windows: {len(window_results)}

Performance Metrics (OOS Only)
-------------------------------
Initial Capital: ${initial_capital:,.2f}
Final Equity: ${final_equity:,.2f}
Total Return: {oos_return:.2%}
Max Drawdown: {max_drawdown:.2%}
Total Trades: {len(trades_master)}
Avg Trades per Window: {len(trades_master) / len(window_results):.1f}

Parameter Stability (Coefficient of Variation %)
------------------------------------------------
"""
        for param, cv in sorted(param_stability.items()):
            report += f"{param}: {cv:.2f}%\n"

        report += """
Window Details
--------------
"""
        for result in window_results:
            report += f"""
Window {result.window.window_id}:
  IS Period: {result.window.is_start.date()} to {result.window.is_end.date()}
  OOS Period: {result.window.oos_start.date()} to {result.window.oos_end.date()}
  Best Params: {result.best_params}
  Metric Value: {result.metric_value:.4f}
  OOS Trades: {len(result.oos_trades)}
  OOS Return: {result.oos_metrics['total_return']:.2%}
"""

        report += """
Output Files
------------
- wfo_trades_master.csv: All OOS trades (chronological)
- wfo_parameter_log.csv: Best parameters per window
- wfo_equity_curve.csv: Trade-by-trade equity progression
- monte_carlo_input.csv: Per-trade portfolio returns for Monte Carlo simulation
- wfo_summary.txt: This report
- window_XXX/: Individual window results
  - is_grid_search/: Grid search results
  - oos_backtest/: OOS backtest results

Usage Notes
-----------
1. Review equity curve for consistency (no large drops = robust)
2. Check parameter stability (low CV% = stable parameters)
3. Analyze parameter log for trends
4. Compare OOS performance to baseline (QQQ buy-and-hold)
5. Look for overfitting: parameters jumping randomly = not robust
6. Use monte_carlo_input.csv for Monte Carlo simulation to assess:
   - Distribution of potential outcomes (percentiles)
   - Maximum drawdown probability
   - Risk of ruin analysis
   - Confidence intervals for returns
"""

        return report
