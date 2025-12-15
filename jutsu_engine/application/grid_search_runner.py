"""
Grid Search Parameter Optimization System.

Automates parameter testing through exhaustive grid search. Takes parameter ranges,
generates all combinations, runs backtests, and produces comparison CSVs.

Example:
    from jutsu_engine.application.grid_search_runner import GridSearchRunner

    # Load configuration from YAML
    config = GridSearchRunner.load_config("grid-configs/macd_optimization.yaml")

    # Create runner
    runner = GridSearchRunner(config)

    # Execute grid search
    result = runner.execute_grid_search(output_base="output")

    # Access results
    print(f"Total Runs: {len(result.run_results)}")
    print(f"Best Run: {result.summary_df.loc[result.summary_df['sharpe_ratio'].idxmax()]}")
"""
import logging
import json
import shutil
import inspect
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional
import itertools

import yaml
import pandas as pd
import numpy as np
from tqdm import tqdm

from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.utils.logging_config import setup_logger
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker
from jutsu_engine.performance.analyzer import PerformanceAnalyzer

logger = setup_logger('APPLICATION.GRID_SEARCH', log_to_console=True)


# Known index symbols that require $ prefix in database
INDEX_SYMBOLS = {'VIX', 'DJI', 'SPX', 'NDX', 'RUT', 'VXN'}


def normalize_index_symbols(symbols: List[str]) -> List[str]:
    """
    Normalize index symbols by adding $ prefix if missing.
    
    Allows YAML configs to use 'VIX' which gets normalized to '$VIX' to match
    database convention. Prevents symbol mismatch between config and database.
    
    Args:
        symbols: List of symbol strings from YAML config
        
    Returns:
        List with normalized symbols (index symbols get $ prefix)
        
    Examples:
        ['QQQ', 'VIX', 'TQQQ'] → ['QQQ', '$VIX', 'TQQQ']
        ['QQQ', '$VIX', 'TQQQ'] → ['QQQ', '$VIX', 'TQQQ']  # Already prefixed
        ['AAPL', 'MSFT'] → ['AAPL', 'MSFT']  # No change
    """
    if not symbols:
        return symbols
    
    normalized = []
    for symbol in symbols:
        # Check if it's a known index symbol WITHOUT $ prefix
        if symbol.upper() in INDEX_SYMBOLS and not symbol.startswith('$'):
            normalized_symbol = f'${symbol.upper()}'
            logger.info(f"Normalized index symbol: {symbol} → {normalized_symbol}")
            normalized.append(normalized_symbol)
        else:
            # Keep as is (regular symbols or already prefixed)
            normalized.append(symbol.upper())
    
    return normalized


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
    
    # Get bear_symbol from symbol_set (new optional field)
    bear_sym = symbol_set.get('bear_symbol') if isinstance(symbol_set, dict) else symbol_set.bear_symbol
    
    if 'bear_3x_symbol' in param_names:
        if bear_sym:
            # Use bear_symbol if specified (SQQQ for KalmanGearing)
            strategy_params['bear_3x_symbol'] = bear_sym
        elif defense_sym:
            # Fallback to defense_symbol for backward compatibility
            strategy_params['bear_3x_symbol'] = defense_sym
    
    if 'vix_symbol' in param_names and vix_sym:
        # Normalize index symbols to match database convention (VIX → $VIX)
        normalized_vix = normalize_index_symbols([vix_sym])[0] if vix_sym else vix_sym
        strategy_params['vix_symbol'] = normalized_vix
    
    # Get core_long_symbol and leveraged_long_symbol (for Hierarchical_Adaptive_v2)
    core_long_sym = symbol_set.get('core_long_symbol') if isinstance(symbol_set, dict) else symbol_set.core_long_symbol
    leveraged_long_sym = symbol_set.get('leveraged_long_symbol') if isinstance(symbol_set, dict) else symbol_set.leveraged_long_symbol

    if 'core_long_symbol' in param_names and core_long_sym:
        strategy_params['core_long_symbol'] = core_long_sym
    if 'leveraged_long_symbol' in param_names and leveraged_long_sym:
        strategy_params['leveraged_long_symbol'] = leveraged_long_sym

    # Get leveraged_short_symbol (for Hierarchical_Adaptive_v2_6)
    leveraged_short_sym = symbol_set.get('leveraged_short_symbol') if isinstance(symbol_set, dict) else symbol_set.leveraged_short_symbol

    if 'leveraged_short_symbol' in param_names and leveraged_short_sym:
        strategy_params['leveraged_short_symbol'] = leveraged_short_sym

    # Get inverse_hedge_symbol (for Hierarchical_Adaptive_v3_5)
    inverse_hedge_sym = symbol_set.get('inverse_hedge_symbol') if isinstance(symbol_set, dict) else symbol_set.inverse_hedge_symbol

    if 'inverse_hedge_symbol' in param_names and inverse_hedge_sym:
        strategy_params['inverse_hedge_symbol'] = inverse_hedge_sym

    # Get Treasury Overlay symbols (for Hierarchical_Adaptive_v3_5b)
    treasury_trend_sym = symbol_set.get('treasury_trend_symbol') if isinstance(symbol_set, dict) else symbol_set.treasury_trend_symbol
    bull_bond_sym = symbol_set.get('bull_bond_symbol') if isinstance(symbol_set, dict) else symbol_set.bull_bond_symbol
    bear_bond_sym = symbol_set.get('bear_bond_symbol') if isinstance(symbol_set, dict) else symbol_set.bear_bond_symbol

    if 'treasury_trend_symbol' in param_names and treasury_trend_sym:
        strategy_params['treasury_trend_symbol'] = treasury_trend_sym
    if 'bull_bond_symbol' in param_names and bull_bond_sym:
        strategy_params['bull_bond_symbol'] = bull_bond_sym
    if 'bear_bond_symbol' in param_names and bear_bond_sym:
        strategy_params['bear_bond_symbol'] = bear_bond_sym

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

    # Filter to only parameters that strategy actually accepts
    # This excludes metadata parameters like 'version', 'description', etc.
    converted_params = {k: v for k, v in converted_params.items() if k in param_names}

    # Add converted optimization parameters
    strategy_params.update(converted_params)

    return strategy_params


@dataclass
class SymbolSet:
    """
    Grouped symbol configuration (prevents invalid combinations).

    Symbol sets ensure that incompatible symbol combinations
    (e.g., mixing NVDA signals with QQQ leverage) don't occur.

    Attributes:
        name: Human-readable name (e.g., "NVDA-NVDL" or "QQQ-TQQQ-VIX")
        signal_symbol: Symbol for signals (e.g., NVDA, QQQ)
        bull_symbol: Optional leveraged bull symbol (e.g., NVDL, TQQQ)
                    Used for MACD strategies and KalmanGearing bull regime
        defense_symbol: Optional defensive position symbol (e.g., NVDA, QQQ)
                       Used for MACD strategies and KalmanGearing defense regime
        bear_symbol: Optional inverse leveraged symbol (e.g., SQQQ)
                    Used for STRONG_BEAR regime in KalmanGearing
        vix_symbol: Optional VIX symbol for regime detection (e.g., VIX)
                   Required for MACD_Trend_v5 and other VIX-filtered strategies
        core_long_symbol: Optional 1x base allocation symbol (e.g., QQQ)
                         Required for Hierarchical_Adaptive_v2 continuous exposure
        leveraged_long_symbol: Optional 3x leveraged overlay symbol (e.g., TQQQ)
                              Required for Hierarchical_Adaptive_v2 continuous exposure
        leveraged_short_symbol: Optional -1x short symbol (e.g., SQQQ)
                               Required for Hierarchical_Adaptive_v2_6
        inverse_hedge_symbol: Optional inverse hedge symbol (e.g., PSQ)
                             Required for Hierarchical_Adaptive_v3_5 Cell 6 hedge
        treasury_trend_symbol: Optional Treasury trend signal (e.g., TLT)
                              Required for Hierarchical_Adaptive_v3_5b Treasury Overlay
        bull_bond_symbol: Optional leveraged bull bonds (e.g., TMF)
                         Required for Hierarchical_Adaptive_v3_5b Treasury Overlay
        bear_bond_symbol: Optional leveraged bear bonds (e.g., TMV)
                         Required for Hierarchical_Adaptive_v3_5b Treasury Overlay
    """
    name: str
    signal_symbol: str
    bull_symbol: Optional[str] = None
    defense_symbol: Optional[str] = None
    bear_symbol: Optional[str] = None
    vix_symbol: Optional[str] = None
    core_long_symbol: Optional[str] = None
    leveraged_long_symbol: Optional[str] = None
    leveraged_short_symbol: Optional[str] = None
    inverse_hedge_symbol: Optional[str] = None
    treasury_trend_symbol: Optional[str] = None
    bull_bond_symbol: Optional[str] = None
    bear_bond_symbol: Optional[str] = None


@dataclass
class GridSearchConfig:
    """
    Grid search configuration from YAML.

    Attributes:
        strategy_name: Strategy class name
        symbol_sets: List of symbol groupings
        base_config: Fixed backtest configuration
        parameters: Parameter ranges for grid search
        max_combinations: Warning threshold for total combinations
        checkpoint_interval: Save state every N runs
    """
    strategy_name: str
    symbol_sets: List[SymbolSet]
    base_config: Dict[str, Any]
    parameters: Dict[str, List[Any]]
    max_combinations: int = 500
    checkpoint_interval: int = 10


@dataclass
class RunConfig:
    """
    Single backtest configuration.

    Represents one specific combination of symbol set and parameters.

    Attributes:
        run_id: Zero-padded run identifier (e.g., "001")
        symbol_set: Symbol grouping for this run
        parameters: Parameter values for this run
    """
    run_id: str
    symbol_set: SymbolSet
    parameters: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """
        Flatten for CSV export.

        Returns:
            Dictionary with flattened structure for CSV row
        """
        result = {
            'run_id': self.run_id,
            'symbol_set': self.symbol_set.name,
            'signal_symbol': self.symbol_set.signal_symbol,
            **self.parameters
        }

        # Include optional symbols if present
        if self.symbol_set.bull_symbol is not None:
            result['bull_symbol'] = self.symbol_set.bull_symbol
        if self.symbol_set.defense_symbol is not None:
            result['defense_symbol'] = self.symbol_set.defense_symbol
        if self.symbol_set.bear_symbol is not None:
            result['bear_symbol'] = self.symbol_set.bear_symbol
        if self.symbol_set.vix_symbol is not None:
            result['vix_symbol'] = self.symbol_set.vix_symbol
        if self.symbol_set.core_long_symbol is not None:
            result['core_long_symbol'] = self.symbol_set.core_long_symbol
        if self.symbol_set.leveraged_long_symbol is not None:
            result['leveraged_long_symbol'] = self.symbol_set.leveraged_long_symbol
        if self.symbol_set.leveraged_short_symbol is not None:
            result['leveraged_short_symbol'] = self.symbol_set.leveraged_short_symbol
        if self.symbol_set.inverse_hedge_symbol is not None:
            result['inverse_hedge_symbol'] = self.symbol_set.inverse_hedge_symbol
        if self.symbol_set.treasury_trend_symbol is not None:
            result['treasury_trend_symbol'] = self.symbol_set.treasury_trend_symbol
        if self.symbol_set.bull_bond_symbol is not None:
            result['bull_bond_symbol'] = self.symbol_set.bull_bond_symbol
        if self.symbol_set.bear_bond_symbol is not None:
            result['bear_bond_symbol'] = self.symbol_set.bear_bond_symbol

        return result


@dataclass
class RunResult:
    """
    Single backtest result.

    Attributes:
        run_config: Configuration used for this run
        metrics: Performance metrics from backtest
        output_dir: Directory containing run outputs
        error: Error message if run failed (None if successful)
    """
    run_config: RunConfig
    metrics: Dict[str, float]
    output_dir: Path
    error: Optional[str] = None


@dataclass
class GridSearchResult:
    """
    Complete grid search results.

    Attributes:
        config: Original grid search configuration
        run_results: List of individual run results
        output_dir: Base output directory
        summary_df: DataFrame with comparison metrics
    """
    config: GridSearchConfig
    run_results: List[RunResult]
    output_dir: Path
    summary_df: pd.DataFrame


class GridSearchRunner:
    """
    Orchestrates multi-parameter grid search.

    Coordinates all components to run exhaustive parameter search:
    - Loads and validates YAML configurations
    - Generates parameter combinations (Cartesian product)
    - Executes multiple BacktestRunner calls
    - Collects and aggregates metrics
    - Generates comparison CSVs
    - Provides checkpoint/resume capability

    Attributes:
        config: Grid search configuration
        logger: Module logger
    """

    def __init__(self, config: GridSearchConfig):
        """
        Initialize grid search runner.

        Args:
            config: GridSearchConfig object with search parameters

        Example:
            config = GridSearchRunner.load_config("grid-configs/macd_opt.yaml")
            runner = GridSearchRunner(config)
        """
        self.config = config
        self.logger = logger

        self.logger.info(
            f"GridSearchRunner initialized: {config.strategy_name}, "
            f"{len(config.symbol_sets)} symbol sets, "
            f"{len(config.parameters)} parameters"
        )

    @staticmethod
    def load_config(yaml_path: str) -> GridSearchConfig:
        """
        Load and validate YAML configuration.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            GridSearchConfig object

        Raises:
            ValueError: If configuration is invalid
            FileNotFoundError: If YAML file doesn't exist
            yaml.YAMLError: If YAML is malformed

        Example:
            config = GridSearchRunner.load_config("grid-configs/macd_opt.yaml")
        """
        yaml_file = Path(yaml_path)
        if not yaml_file.exists():
            raise FileNotFoundError(f"Config file not found: {yaml_path}")

        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

        # Validate required keys
        required = ['strategy', 'symbol_sets', 'base_config', 'parameters']
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"Missing required keys: {', '.join(missing)}")

        # Validate symbol_sets
        if not data['symbol_sets']:
            raise ValueError("At least one symbol_set required")

        # Parse symbol_sets
        try:
            symbol_sets = [SymbolSet(**s) for s in data['symbol_sets']]
        except TypeError as e:
            raise ValueError(f"Invalid symbol_set structure: {e}")

        # Validate VIX symbol requirement for v5 strategies
        strategy_name = data['strategy']
        if strategy_name == 'MACD_Trend_v5':
            missing_vix = [s.name for s in symbol_sets if s.vix_symbol is None]
            if missing_vix:
                raise ValueError(
                    f"Strategy '{strategy_name}' requires vix_symbol for all symbol_sets. "
                    f"Missing vix_symbol in: {', '.join(missing_vix)}"
                )

        # Validate base_config has required keys
        required_base = ['start_date', 'end_date', 'timeframe', 'initial_capital']
        missing_base = [key for key in required_base if key not in data['base_config']]
        if missing_base:
            raise ValueError(f"Missing base_config keys: {', '.join(missing_base)}")

        # Validate date ranges
        try:
            start = datetime.strptime(data['base_config']['start_date'], '%Y-%m-%d')
            end = datetime.strptime(data['base_config']['end_date'], '%Y-%m-%d')
            if start >= end:
                raise ValueError(f"Invalid date range: start ({start}) >= end ({end})")
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid date configuration: {e}")

        # Validate parameters
        if not data['parameters']:
            raise ValueError("At least one parameter required")

        # Ensure all parameter values are lists
        for param, values in data['parameters'].items():
            if not isinstance(values, list):
                raise ValueError(f"Parameter '{param}' must be a list, got {type(values)}")
            if not values:
                raise ValueError(f"Parameter '{param}' has empty values list")

        logger.info(f"Configuration loaded from: {yaml_path}")

        return GridSearchConfig(
            strategy_name=data['strategy'],
            symbol_sets=symbol_sets,
            base_config=data['base_config'],
            parameters=data['parameters'],
            max_combinations=data.get('max_combinations', 500),
            checkpoint_interval=data.get('checkpoint_interval', 10)
        )

    def generate_combinations(self) -> List[RunConfig]:
        """
        Generate all parameter combinations (Cartesian product).

        For each symbol set, generates all possible parameter combinations
        using Cartesian product.

        Returns:
            List of RunConfig objects for each combination

        Example:
            combinations = runner.generate_combinations()
            print(f"Total combinations: {len(combinations)}")
        """
        combinations = []
        run_id = 1

        # For each symbol set
        for symbol_set in self.config.symbol_sets:
            # Generate Cartesian product of parameters
            param_names = list(self.config.parameters.keys())
            param_values = list(self.config.parameters.values())

            for combo in itertools.product(*param_values):
                param_dict = dict(zip(param_names, combo))

                run_config = RunConfig(
                    run_id=f"{run_id:03d}",
                    symbol_set=symbol_set,
                    parameters=param_dict
                )
                combinations.append(run_config)
                run_id += 1

        # Warn if too many
        if len(combinations) > self.config.max_combinations:
            self.logger.warning(
                f"Generated {len(combinations)} combinations "
                f"(max: {self.config.max_combinations}). "
                f"Consider reducing parameter ranges."
            )

        self.logger.info(
            f"Generated {len(combinations)} combinations "
            f"({len(self.config.symbol_sets)} symbol_sets × "
            f"{len(combinations) // len(self.config.symbol_sets)} params)"
        )

        return combinations

    def execute_grid_search(
        self,
        output_base: str = "output",
        config_path: Optional[str] = None,
        generate_plots: bool = True
    ) -> GridSearchResult:
        """
        Execute full grid search.

        Orchestrates entire grid search workflow:
        1. Generate combinations
        2. Check for checkpoint (resume capability)
        3. Execute backtests with progress tracking
        4. Save periodic checkpoints
        5. Generate summary CSVs
        6. Create README with summary statistics

        Args:
            output_base: Base output directory (default: "output")
            config_path: Path to config file for copying (optional)
            generate_plots: Generate interactive HTML plots (default: True)

        Returns:
            GridSearchResult with all run results and summary

        Example:
            result = runner.execute_grid_search(output_base="output")
            print(f"Completed {len(result.run_results)} runs")
        """
        # Store generate_plots for use in _run_single_backtest
        self.generate_plots = generate_plots

        # Create output directory
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_dir = Path(output_base) / f"grid_search_{self.config.strategy_name}_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Output directory: {output_dir}")

        # Calculate baseline BEFORE grid search (for row 000 and alpha calculation)
        baseline_result = self._calculate_baseline_for_grid_search()
        if baseline_result:
            self.logger.info(
                f"Baseline calculated: QQQ "
                f"{baseline_result['baseline_total_return']:.2%} total return, "
                f"{baseline_result['baseline_annualized_return']:.2%} annualized"
            )
        else:
            self.logger.warning(
                "Baseline calculation failed or insufficient data. "
                "Summary CSV will not include baseline row (000) or alpha column."
            )

        # Generate combinations
        combinations = self.generate_combinations()

        # Check for checkpoint (resume)
        checkpoint_file = output_dir / "checkpoint.json"
        completed_runs = self._load_checkpoint(checkpoint_file)

        if completed_runs:
            self.logger.info(f"Resuming: {len(completed_runs)} runs already completed")

        # Execute backtests
        results = []
        for i, run_config in enumerate(tqdm(combinations, desc="Grid Search")):
            if run_config.run_id in completed_runs:
                self.logger.debug(f"Skipping {run_config.run_id} (already completed)")
                continue

            # Display progress
            progress_msg = self._format_progress(run_config, i + 1, len(combinations))
            self.logger.info(progress_msg)

            # Run backtest
            result = self._run_single_backtest(run_config, output_dir)
            results.append(result)

            # Checkpoint
            if (i + 1) % self.config.checkpoint_interval == 0:
                all_completed = [r.run_config.run_id for r in results]
                self._save_checkpoint(checkpoint_file, all_completed)
                self.logger.info(f"Checkpoint saved ({len(all_completed)} runs completed)")

        # Generate summary CSVs
        self._save_run_config_csv(combinations, output_dir)
        summary_df = self._generate_summary_comparison(results, output_dir, baseline_result)

        # Copy config for reference
        if config_path:
            try:
                shutil.copy(config_path, output_dir / "parameters.yaml")
                self.logger.info("Configuration copied to output directory")
            except Exception as e:
                self.logger.warning(f"Failed to copy config: {e}")

        # Generate README
        self._generate_readme(results, output_dir)

        # Clean up checkpoint (grid complete)
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            self.logger.info("Checkpoint removed (grid search complete)")

        # Generate plots if requested
        if generate_plots:
            try:
                from jutsu_engine.infrastructure.visualization import GridSearchPlotter
                self.logger.info("Generating grid search plots...")
                plotter = GridSearchPlotter(
                    csv_path=output_dir / "summary_comparison.csv",
                    output_dir=output_dir / "plots"
                )
                plots = plotter.generate_all_plots()
                self.logger.info(f"Plots generated: {len(plots)} plots in {output_dir / 'plots'}")
                for plot_type, path in plots.items():
                    self.logger.info(f"  - {plot_type}: {path.name}")
            except Exception as e:
                self.logger.warning(f"Plot generation failed (continuing): {e}")

        self.logger.info("=" * 60)
        self.logger.info("GRID SEARCH COMPLETE")
        self.logger.info("=" * 60)
        self.logger.info(f"Total Runs: {len(results)}")
        self.logger.info(f"Output Directory: {output_dir}")
        self.logger.info("=" * 60)

        return GridSearchResult(
            config=self.config,
            run_results=results,
            output_dir=output_dir,
            summary_df=summary_df
        )

    def _run_single_backtest(self, run_config: RunConfig, output_dir: Path) -> RunResult:
        """
        Execute single backtest using BacktestRunner.

        Args:
            run_config: Configuration for this run
            output_dir: Base output directory

        Returns:
            RunResult with metrics or error
        """
        run_dir = output_dir / f"run_{run_config.run_id}"
        run_dir.mkdir(exist_ok=True)

        # Parse dates from base_config (handle both str and datetime)
        start_date = self.config.base_config['start_date']
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d')

        end_date = self.config.base_config['end_date']
        if isinstance(end_date, str):
            # Parse date and set to end of day (23:59:59) to include all bars from that date
            end_date = datetime.strptime(end_date, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

        # Import strategy class dynamically (MUST happen before building strategy_params)
        import importlib
        module = importlib.import_module(f"jutsu_engine.strategies.{self.config.strategy_name}")
        strategy_class = _get_strategy_class_from_module(module)

        # Prepare symbols list (conditionally include all optional symbols)
        symbols = [run_config.symbol_set.signal_symbol]
        if run_config.symbol_set.bull_symbol is not None:
            symbols.append(run_config.symbol_set.bull_symbol)
        if run_config.symbol_set.defense_symbol is not None:
            symbols.append(run_config.symbol_set.defense_symbol)
        if run_config.symbol_set.bear_symbol is not None:
            symbols.append(run_config.symbol_set.bear_symbol)
        if run_config.symbol_set.vix_symbol is not None:
            symbols.append(run_config.symbol_set.vix_symbol)
        if run_config.symbol_set.core_long_symbol is not None:
            symbols.append(run_config.symbol_set.core_long_symbol)
        if run_config.symbol_set.leveraged_long_symbol is not None:
            symbols.append(run_config.symbol_set.leveraged_long_symbol)
        if run_config.symbol_set.leveraged_short_symbol is not None:
            symbols.append(run_config.symbol_set.leveraged_short_symbol)
        if run_config.symbol_set.inverse_hedge_symbol is not None:
            symbols.append(run_config.symbol_set.inverse_hedge_symbol)
        # Treasury Overlay symbols (for Hierarchical_Adaptive_v3_5b and similar)
        if run_config.symbol_set.treasury_trend_symbol is not None:
            symbols.append(run_config.symbol_set.treasury_trend_symbol)
        if run_config.symbol_set.bull_bond_symbol is not None:
            symbols.append(run_config.symbol_set.bull_bond_symbol)
        if run_config.symbol_set.bear_bond_symbol is not None:
            symbols.append(run_config.symbol_set.bear_bond_symbol)

        # Normalize index symbols (add $ prefix for VIX, DJI, etc.)
        # This ensures YAML config "VIX" matches database "$VIX"
        symbols = normalize_index_symbols(symbols)
        
        # Deduplicate while preserving order
        symbols = list(dict.fromkeys(symbols))

        # Prepare strategy params using introspection
        strategy_params = _build_strategy_params(
            strategy_class,
            run_config.symbol_set,
            run_config.parameters
        )

        # Prepare backtest config
        config = {
            **self.config.base_config,
            'start_date': start_date,  # Override with datetime
            'end_date': end_date,      # Override with datetime
            'symbols': symbols,
            'strategy_name': self.config.strategy_name,
            'strategy_params': strategy_params,
        }

        try:
            # Run backtest (BacktestRunner handles all complexity)
            runner = BacktestRunner(config)

            # Instantiate strategy with introspection-based params
            strategy = strategy_class(**config['strategy_params'])

            result = runner.run(strategy, output_dir=str(run_dir))

            # Extract metrics
            baseline_data = result.get('baseline', {}) or {}
            metrics = {
                'final_value': result.get('final_value', 0.0),
                'total_return_pct': float(result.get('total_return', 0.0) * 100),
                'annualized_return_pct': float(result.get('annualized_return', 0.0) * 100),
                'sharpe_ratio': result.get('sharpe_ratio', 0.0),
                'sortino_ratio': result.get('sortino_ratio', 0.0),
                'max_drawdown_pct': float(result.get('max_drawdown', 0.0) * 100),
                'calmar_ratio': result.get('calmar_ratio', 0.0),
                'win_rate_pct': float(result.get('win_rate', 0.0) * 100),
                'total_trades': result.get('total_trades', 0),
                'profit_factor': result.get('profit_factor', 0.0),
                'avg_win_usd': result.get('avg_win', 0.0),
                'avg_loss_usd': result.get('avg_loss', 0.0),
                # Beta metrics (systematic risk vs market benchmarks)
                'beta_vs_qqq': baseline_data.get('beta_vs_QQQ'),
                'beta_vs_spy': baseline_data.get('beta_vs_SPY')
            }

            # Generate plots for this run if requested
            if hasattr(self, 'generate_plots') and self.generate_plots:
                try:
                    from jutsu_engine.infrastructure.visualization import EquityPlotter

                    # Find the main CSV file for this run
                    csv_files = list(run_dir.glob("*.csv"))
                    main_csv = None
                    for csv in csv_files:
                        # Main CSV doesn't have suffix like _trades or _summary
                        # Use 'regime' (not '_regime') to catch both regime_*.csv and *_regime.csv
                        if not any(pattern in csv.name for pattern in ['_trades', '_summary', 'regime']):
                            main_csv = csv
                            break

                    if main_csv and main_csv.exists():
                        self.logger.info(f"Generating plots for {run_config.run_id}...")
                        plotter = EquityPlotter(csv_path=main_csv)
                        plot_paths = plotter.generate_all_plots()  # Returns Dict[str, Path]
                        self.logger.debug(f"  Generated {len(plot_paths)} plots for {run_config.run_id}")
                    else:
                        self.logger.warning(f"No main CSV found for {run_config.run_id}, skipping plots")
                except Exception as e:
                    self.logger.warning(f"Plot generation failed for {run_config.run_id}: {e}")

            return RunResult(
                run_config=run_config,
                metrics=metrics,
                output_dir=run_dir,
                error=None
            )

        except Exception as e:
            self.logger.error(f"Backtest failed for run {run_config.run_id}: {e}")

            # Return error result (don't crash entire grid search)
            return RunResult(
                run_config=run_config,
                metrics={},
                output_dir=run_dir,
                error=str(e)
            )

    def _save_run_config_csv(self, combinations: List[RunConfig], output_dir: Path):
        """
        Generate run_config.csv (parameter mapping).

        Args:
            combinations: All run configurations
            output_dir: Output directory
        """
        rows = [c.to_dict() for c in combinations]
        df = pd.DataFrame(rows)
        csv_path = output_dir / "run_config.csv"
        df.to_csv(csv_path, index=False)
        self.logger.info(f"Run config CSV saved: {csv_path}")

    def _generate_summary_comparison(
        self,
        results: List[RunResult],
        output_dir: Path,
        baseline_result: Optional[Dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Generate summary_comparison.csv (metrics).

        Formats metrics with proper precision and Excel-compatible percentages:
        - Non-percentage values: 2 decimals
        - Integer values: No decimals
        - Percentage values: 3 decimals (divided by 100 for Excel compatibility)
        - Column order: Metrics first, parameters last
        - Parameter names: Title Case with spaces
        - Includes baseline row (000) if baseline_result provided
        - Adds Alpha column (strategy return / baseline return)

        Args:
            results: All run results
            output_dir: Output directory
            baseline_result: Optional baseline calculation for row 000 and alpha

        Returns:
            DataFrame with summary metrics
        """
        rows = []

        # Add baseline row as row 000 if available
        if baseline_result:
            baseline_row = self._format_baseline_row(baseline_result)
            rows.append(baseline_row)
            self.logger.info(
                f"Baseline row added: {baseline_result['baseline_total_return']:.2%} return"
            )

        # Calculate baseline return for alpha calculation
        baseline_total_return = None
        if baseline_result:
            baseline_total_return = baseline_result['baseline_total_return']

        for result in results:
            # Format metrics with proper precision
            portfolio_balance = round(result.metrics.get('final_value', 0.0), 2)
            total_return_pct = round(result.metrics.get('total_return_pct', 0.0), 2)  # Already in percentage format
            annualized_return_pct = round(result.metrics.get('annualized_return_pct', 0.0), 2)  # Already in percentage format
            max_drawdown = round(result.metrics.get('max_drawdown_pct', 0.0), 3)  # Keep as percentage
            sharpe_ratio = round(result.metrics.get('sharpe_ratio', 0.0), 2)
            sortino_ratio = round(result.metrics.get('sortino_ratio', 0.0), 2)
            calmar_ratio = round(result.metrics.get('calmar_ratio', 0.0), 2)
            total_trades = int(result.metrics.get('total_trades', 0))
            profit_factor = round(result.metrics.get('profit_factor', 0.0), 2)
            win_rate_pct = round(result.metrics.get('win_rate_pct', 0.0), 2)  # Already in percentage format
            avg_win = round(result.metrics.get('avg_win_usd', 0.0), 2)
            avg_loss = round(result.metrics.get('avg_loss_usd', 0.0), 2)

            # Calculate alpha vs baseline
            alpha = 'N/A'
            if baseline_total_return is not None and total_return_pct != 0:
                strategy_return = total_return_pct / 100  # Convert percentage to decimal for ratio calculation
                if baseline_total_return != 0:
                    # Alpha as ratio (e.g., 1.20 means 20% better than baseline)
                    alpha_value = strategy_return / baseline_total_return
                    alpha = f"{alpha_value:.2f}"
                else:
                    # Baseline return is zero, cannot calculate ratio
                    alpha = 'N/A'

            # Extract beta metrics
            beta_vs_qqq = result.metrics.get('beta_vs_qqq')
            beta_vs_spy = result.metrics.get('beta_vs_spy')

            # Create row with METRICS FIRST, then PARAMETERS
            row = {
                'Run ID': result.run_config.run_id,
                'Symbol Set': result.run_config.symbol_set.name,
                'Portfolio Balance': portfolio_balance,
                'Total Return %': total_return_pct,
                'Annualized Return %': annualized_return_pct,
                'Max Drawdown': max_drawdown,
                'Sharpe Ratio': sharpe_ratio,
                'Sortino Ratio': sortino_ratio,
                'Calmar Ratio': calmar_ratio,
                'Total Trades': total_trades,
                'Profit Factor': profit_factor,
                'Win Rate %': win_rate_pct,
                'Avg Win ($)': avg_win,
                'Avg Loss ($)': avg_loss,
                'Alpha': alpha,
                'Beta vs QQQ': f'{beta_vs_qqq:.3f}' if beta_vs_qqq is not None else 'N/A',
                'Beta vs SPY': f'{beta_vs_spy:.3f}' if beta_vs_spy is not None else 'N/A'
            }

            # Add parameters with Title Case names
            param_mapping = {
                'ema_period': 'EMA Period',
                'atr_stop_multiplier': 'ATR Stop Multiplier',
                'risk_bull': 'Risk Bull',
                'macd_fast_period': 'MACD Fast Period',
                'macd_slow_period': 'MACD Slow Period',
                'macd_signal_period': 'MACD Signal Period',
                'atr_period': 'ATR Period',
                'allocation_defense': 'Allocation Defense',
            }

            for param_name, param_value in result.run_config.parameters.items():
                # Convert snake_case to Title Case
                display_name = param_mapping.get(param_name, param_name.replace('_', ' ').title())
                row[display_name] = param_value

            # Add error column if present
            if result.error:
                row['Error'] = result.error

            rows.append(row)

        # Create DataFrame with explicit column order (Alpha at end)
        columns_order = [
            'Run ID', 'Symbol Set', 'Portfolio Balance',
            'Total Return %', 'Annualized Return %', 'Max Drawdown',
            'Sharpe Ratio', 'Sortino Ratio', 'Calmar Ratio',
            'Total Trades', 'Profit Factor', 'Win Rate %',
            'Avg Win ($)', 'Avg Loss ($)',
            'Alpha', 'Beta vs QQQ', 'Beta vs SPY',  # Comparison metrics
            'EMA Period', 'ATR Stop Multiplier', 'Risk Bull',
            'MACD Fast Period', 'MACD Slow Period', 'MACD Signal Period',
            'ATR Period', 'Allocation Defense'
        ]

        df = pd.DataFrame(rows)

        # Reorder columns (only include columns that exist)
        existing_columns = [col for col in columns_order if col in df.columns]
        other_columns = [col for col in df.columns if col not in columns_order]
        df = df[existing_columns + other_columns]

        csv_path = output_dir / "summary_comparison.csv"
        df.to_csv(csv_path, index=False)
        self.logger.info(f"Summary comparison CSV saved: {csv_path}")

        return df

    def _generate_readme(self, results: List[RunResult], output_dir: Path):
        """
        Generate README.txt with summary statistics.

        Args:
            results: All run results
            output_dir: Output directory
        """
        # Filter successful runs
        successful_results = [r for r in results if not r.error]

        if not successful_results:
            readme = f"""
Grid Search Results Summary
============================

Strategy: {self.config.strategy_name}
Total Runs: {len(results)}
Successful: 0
Failed: {len(results)}

ERROR: All runs failed. Check individual run directories for details.
"""
        else:
            # Best run (by Sharpe ratio)
            best_run = max(successful_results, key=lambda r: r.metrics.get('sharpe_ratio', -999))
            worst_run = min(successful_results, key=lambda r: r.metrics.get('sharpe_ratio', 999))

            # Average metrics
            avg_sharpe = sum(r.metrics.get('sharpe_ratio', 0) for r in successful_results) / len(successful_results)
            avg_return = sum(r.metrics.get('annualized_return_pct', 0) for r in successful_results) / len(successful_results)

            readme = f"""
Grid Search Results Summary
============================

Strategy: {self.config.strategy_name}
Total Runs: {len(results)}
Successful: {len(successful_results)}
Failed: {len(results) - len(successful_results)}
Date Range: {self.config.base_config['start_date']} to {self.config.base_config['end_date']}

Best Run: {best_run.run_config.run_id}
  Symbol Set: {best_run.run_config.symbol_set.name}
  Sharpe Ratio: {best_run.metrics.get('sharpe_ratio', 0):.2f}
  Annualized Return: {best_run.metrics.get('annualized_return_pct', 0):.2f}%
  Max Drawdown: {best_run.metrics.get('max_drawdown_pct', 0):.2f}%

Worst Run: {worst_run.run_config.run_id}
  Symbol Set: {worst_run.run_config.symbol_set.name}
  Sharpe Ratio: {worst_run.metrics.get('sharpe_ratio', 0):.2f}

Average Metrics:
  Sharpe Ratio: {avg_sharpe:.2f}
  Annualized Return: {avg_return:.2f}%

Files:
  - summary_comparison.csv: All metrics for comparison (sortable)
  - run_config.csv: Parameter mapping for each run
  - run_XXX/: Individual backtest outputs
"""

        readme_path = output_dir / "README.txt"
        with open(readme_path, 'w') as f:
            f.write(readme)

        self.logger.info(f"README generated: {readme_path}")

    def _format_progress(self, run_config: RunConfig, current: int, total: int) -> str:
        """
        Format progress message.

        Args:
            run_config: Current run configuration
            current: Current run number
            total: Total runs

        Returns:
            Formatted progress string
        """
        params_str = " ".join([f"{k}:{v}" for k, v in run_config.parameters.items()])
        return f"Running {current}/{total}: {run_config.symbol_set.name} | {params_str}"

    def _save_checkpoint(self, checkpoint_file: Path, completed_run_ids: List[str]):
        """
        Save checkpoint for resume capability.

        Args:
            checkpoint_file: Path to checkpoint file
            completed_run_ids: List of completed run IDs
        """
        checkpoint_data = {
            'completed_runs': completed_run_ids,
            'timestamp': datetime.now().isoformat()
        }
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f, indent=2)

    def _load_checkpoint(self, checkpoint_file: Path) -> set:
        """
        Load checkpoint (return set of completed run_ids).

        Args:
            checkpoint_file: Path to checkpoint file

        Returns:
            Set of completed run IDs
        """
        if not checkpoint_file.exists():
            return set()

        try:
            with open(checkpoint_file) as f:
                data = json.load(f)
            return set(data.get('completed_runs', []))
        except (json.JSONDecodeError, IOError) as e:
            self.logger.warning(f"Checkpoint corrupted, starting fresh: {e}")
            return set()

    def _calculate_baseline_for_grid_search(self) -> Optional[Dict[str, Any]]:
        """
        Calculate baseline for grid search comparison.

        Uses configurable baseline symbol (default: QQQ) to calculate buy-and-hold
        baseline for the grid search date range. This baseline is written as row 000
        in the summary CSV for performance comparison.

        Returns:
            Dict with comprehensive baseline metrics or None if calculation fails:
                - baseline_symbol: str (configurable, defaults to 'QQQ')
                - baseline_final_value: float
                - baseline_total_return: float
                - baseline_annualized_return: float
                - baseline_max_drawdown: float
                - baseline_sharpe_ratio: float
                - baseline_sortino_ratio: float
                - baseline_calmar_ratio: float

        Example:
            baseline = runner._calculate_baseline_for_grid_search()
            if baseline:
                print(f"Baseline return: {baseline['baseline_total_return']:.2%}")
                print(f"Baseline Sharpe: {baseline['baseline_sharpe_ratio']:.2f}")
        """
        try:
            self.logger.info("Calculating buy-and-hold baseline (QQQ)...")

            # Parse dates from base_config (handle both str and datetime)
            start_date = self.config.base_config['start_date']
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d')

            end_date = self.config.base_config['end_date']
            if isinstance(end_date, str):
                # Parse date and set to end of day (23:59:59) to include all bars from that date
                end_date = datetime.strptime(end_date, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )

            # Query QQQ bars from database
            from jutsu_engine.data.models import MarketData
            from jutsu_engine.utils.config import get_config

            # Get database session
            db_config = get_config()
            database_url = self.config.base_config.get('database_url', db_config.database_url)
            engine = create_engine(database_url)
            Session = sessionmaker(bind=engine)
            session = Session()

            try:
                # Use configurable baseline symbol (defaults to QQQ if not specified)
                baseline_symbol = self.config.base_config.get('baseline_symbol', 'QQQ')
                timeframe = self.config.base_config['timeframe']

                qqq_bars = (
                    session.query(MarketData)
                    .filter(
                        and_(
                            MarketData.symbol == baseline_symbol,
                            MarketData.timeframe == timeframe,
                            MarketData.timestamp >= start_date,
                            MarketData.timestamp <= end_date,
                            MarketData.is_valid == True,  # noqa: E712
                        )
                    )
                    .order_by(MarketData.timestamp.asc())
                    .all()
                )

                if len(qqq_bars) < 2:
                    self.logger.warning(
                        f"Insufficient {baseline_symbol} data for baseline "
                        f"({len(qqq_bars)} bars, need >= 2)"
                    )
                    return None

                # Build equity curve from all baseline bars for comprehensive metrics
                initial_capital = Decimal(str(self.config.base_config['initial_capital']))
                start_price = qqq_bars[0].close
                shares = initial_capital / start_price

                # Create equity curve: list of (timestamp, value) tuples
                equity_curve = [
                    (bar.timestamp, shares * bar.close)
                    for bar in qqq_bars
                ]

                # Use PerformanceAnalyzer.calculate_metrics() for comprehensive analysis
                analyzer = PerformanceAnalyzer(
                    fills=[],  # No fills for buy-and-hold
                    equity_curve=equity_curve,
                    initial_capital=initial_capital
                )

                metrics = analyzer.calculate_metrics()

                # Build comprehensive baseline result dict
                baseline_result = {
                    'baseline_symbol': baseline_symbol,
                    'baseline_final_value': metrics['final_value'],
                    'baseline_total_return': metrics['total_return'],
                    'baseline_annualized_return': metrics['annualized_return'],
                    'baseline_max_drawdown': metrics['max_drawdown'],
                    'baseline_sharpe_ratio': metrics['sharpe_ratio'],
                    'baseline_sortino_ratio': metrics['sortino_ratio'],
                    'baseline_calmar_ratio': metrics['calmar_ratio']
                }

                self.logger.info(
                    f"Baseline calculated: {baseline_symbol} "
                    f"Total Return: {baseline_result['baseline_total_return']:.2%}, "
                    f"Sharpe: {baseline_result['baseline_sharpe_ratio']:.2f}, "
                    f"Max DD: {baseline_result['baseline_max_drawdown']:.2%}"
                )

                return baseline_result

            finally:
                session.close()

        except Exception as e:
            self.logger.error(f"Baseline calculation failed: {e}", exc_info=True)
            return None

    def _format_baseline_row(self, baseline: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format baseline results as CSV row matching summary format.

        Converts baseline calculation results into a dictionary that matches
        the summary_comparison.csv schema with comprehensive metrics.

        Args:
            baseline: Baseline calculation results from _calculate_baseline_for_grid_search()
                Keys: baseline_symbol, baseline_final_value, baseline_total_return,
                      baseline_annualized_return, baseline_max_drawdown,
                      baseline_sharpe_ratio, baseline_sortino_ratio, baseline_calmar_ratio

        Returns:
            Dict matching summary CSV columns with human-readable format:
                - run_id: '000'
                - symbol_set: 'Buy & Hold {baseline_symbol}' (dynamic)
                - initial_capital, final_value, returns
                - Comprehensive metrics: Sharpe, Sortino, Calmar, max drawdown
                - N/A for trade-specific metrics (win rate, profit factor)
                - alpha: '1.00' (baseline has alpha = 1.00 by definition)

        Example:
            baseline = self._calculate_baseline_for_grid_search()
            if baseline:
                row = self._format_baseline_row(baseline)
                # row['run_id'] == '000'
                # row['symbol_set'] == 'Buy & Hold QQQ' (or SPY, NVDA, etc.)
                # row['sharpe_ratio'] == 1.23 (numeric, not 'N/A')
                # row['alpha'] == '1.00'
        """
        initial_capital = self.config.base_config['initial_capital']

        # For baseline (buy-and-hold), beta vs itself is 1.0 by definition
        # Beta vs SPY requires calculation which we don't do for baseline
        baseline_symbol = baseline["baseline_symbol"]
        beta_vs_qqq = '1.000' if baseline_symbol == 'QQQ' else 'N/A'

        return {
            'Run ID': '000',
            'Symbol Set': f'Buy & Hold {baseline_symbol}',
            'Portfolio Balance': round(baseline['baseline_final_value'], 2),
            'Total Return %': round(baseline['baseline_total_return'] * 100, 2),  # Convert decimal to percentage
            'Annualized Return %': round(baseline['baseline_annualized_return'] * 100, 2),  # Convert decimal to percentage
            'Max Drawdown': round(baseline.get('baseline_max_drawdown', 0) * 100, 3),
            'Sharpe Ratio': round(baseline.get('baseline_sharpe_ratio', 0), 2),
            'Sortino Ratio': round(baseline.get('baseline_sortino_ratio', 0), 2),
            'Calmar Ratio': round(baseline.get('baseline_calmar_ratio', 0), 2),
            'Total Trades': 0,
            'Profit Factor': 'N/A',  # No trades
            'Win Rate %': 'N/A',  # No trades
            'Avg Win ($)': 'N/A',  # No trades
            'Avg Loss ($)': 'N/A',  # No trades
            'Alpha': '1.00',  # Baseline has alpha = 1.00 by definition
            'Beta vs QQQ': beta_vs_qqq,  # Beta vs QQQ (1.0 for QQQ baseline)
            'Beta vs SPY': 'N/A'  # Beta vs SPY not calculated for baseline
        }


class GridSearchAnalyzer:
    """
    Robustness analyzer for grid search results.

    Implements dual-stage analysis:
    - Stage A: Summary scan and filtering (top 20% by Calmar)
    - Stage B: Deep dive with stress tests and yearly consistency

    Output: analyzer_summary.csv with robustness verdicts

    Attributes:
        output_dir: Output directory containing grid search results
        logger: Module logger for analysis operations
    """

    def __init__(self, output_dir: Path):
        """
        Initialize analyzer with output directory.

        Args:
            output_dir: Path to grid search output directory containing:
                - summary_comparison.csv
                - run_config.csv
                - run_XXX/portfolio_daily.csv files
        """
        self.output_dir = Path(output_dir)
        self.logger = setup_logger('APPLICATION.GRID_SEARCH.ANALYZER')

        # Validate required files exist
        required_files = [
            self.output_dir / 'summary_comparison.csv',
            self.output_dir / 'run_config.csv'
        ]

        for required_file in required_files:
            if not required_file.exists():
                raise FileNotFoundError(
                    f"Required file not found: {required_file}\n"
                    f"Ensure grid search completed successfully"
                )

    def analyze(self) -> pd.DataFrame:
        """
        Run full dual-stage analysis with QQQ baseline and cluster mapping enhancements.

        Returns:
            DataFrame with analyzer_summary.csv schema containing:
                - cluster_id
                - cluster_run_ids
                - cluster_parameters
                - avg_total_return
                - max_drawdown
                - calmar_ratio
                - plateau_stability_pct
                - stress_2018_ret, stress_2020_ret, stress_2022_ret
                - verdict
        """
        self.logger.info("Starting Grid Search robustness analysis...")

        # Calculate QQQ baseline metrics
        self.logger.info("Calculating QQQ baseline metrics...")
        qqq_metrics = self._calculate_qqq_overall_metrics()
        qqq_stress = self._calculate_qqq_stress_tests()

        # Save QQQ baseline to separate file
        if qqq_metrics:
            self._save_qqq_baseline(qqq_metrics, qqq_stress)
            self.logger.info("  → QQQ baseline saved to analyzer_qqq_baseline.csv")

        # Create definitions file
        self._create_analyzer_definitions()
        self.logger.info("  → Analyzer definitions saved to analyzer_definitions.md")

        # Stage A: Summary scan and filtering
        self.logger.info("Stage A: Filtering top 20% by Calmar ratio...")
        candidates = self._stage_a_filter()
        self.logger.info(f"  → {len(candidates)} candidates from {candidates['cluster_id'].nunique()} clusters")

        # Load run_config for cluster mapping
        run_config_path = self.output_dir / 'run_config.csv'
        run_config = pd.read_csv(run_config_path)

        # Create cluster mapping
        cluster_map = self._map_cluster_to_runs(candidates, run_config)

        # Stage B: Deep dive (streamed)
        self.logger.info("Stage B: Deep dive analysis (streaming daily data)...")
        results = self._stage_b_analyze(candidates)
        self.logger.info(f"  → {len(results)} clusters analyzed")

        # Add cluster mapping columns
        if len(results) > 0:
            results['cluster_run_ids'] = results['cluster_id'].apply(
                lambda cid: ','.join([str(rid) for rid in cluster_map.get(cid, {}).get('run_ids', [])])
            )
            results['cluster_parameters'] = results['cluster_id'].apply(
                lambda cid: json.dumps(cluster_map.get(cid, {}).get('parameters', {}))
            )

        # Save results
        output_path = self.output_dir / 'analyzer_summary.csv'

        # Handle empty results (save with columns but no data)
        if len(results) == 0:
            # Create empty DataFrame with expected columns
            empty_df = pd.DataFrame(columns=[
                'cluster_id', 'cluster_run_ids', 'cluster_parameters',
                'avg_total_return', 'max_drawdown', 'calmar_ratio',
                'plateau_stability_pct', 'stress_2018_ret', 'stress_2020_ret',
                'stress_2022_ret', 'yearly_consistency', 'verdict'
            ])
            empty_df.to_csv(output_path, index=False)
        else:
            results.to_csv(output_path, index=False)

        self.logger.info(f"Analysis complete: {output_path}")

        # Enhance summary_comparison.csv with QQQ stress tests
        self._enhance_summary_comparison(qqq_metrics, qqq_stress)
        self.logger.info("  → summary_comparison.csv enhanced with QQQ stress tests")

        # Display summary statistics
        self._display_summary_stats(results)

        return results

    def _stage_a_filter(self) -> pd.DataFrame:
        """
        Stage A: Read summary, filter top 20% by Calmar percentile, cluster.

        Returns:
            DataFrame with candidate runs and cluster assignments
        """
        # 1. Read summary_comparison.csv
        summary_path = self.output_dir / 'summary_comparison.csv'
        summary = pd.read_csv(summary_path)

        # Skip row 000 (baseline) if present
        summary = summary[summary['Run ID'] != '000'].copy()

        self.logger.info(f"  Loaded {len(summary)} runs from summary")

        # 2. Filter top 20% by Calmar percentile threshold
        calmar_threshold = summary['Calmar Ratio'].quantile(0.80)
        candidates = summary[summary['Calmar Ratio'] >= calmar_threshold].copy()

        self.logger.info(
            f"  Top 20% filter (Calmar >= {calmar_threshold:.2f}): "
            f"{len(candidates)} runs"
        )

        # 3. Load run_config.csv for parameter clustering
        run_config_path = self.output_dir / 'run_config.csv'
        run_config = pd.read_csv(run_config_path)

        # Merge to get parameters
        candidates = candidates.merge(
            run_config,
            left_on='Run ID',
            right_on='run_id',
            how='left'
        )

        # 4. Cluster by ALL parameters (exclude non-parameter columns)
        exclude_cols = {
            'run_id', 'Run ID', 'symbol_set', 'signal_symbol',
            'bull_symbol', 'defense_symbol', 'bear_symbol', 'vix_symbol',
            'core_long_symbol', 'leveraged_long_symbol',
            'leveraged_short_symbol', 'inverse_hedge_symbol'
        }

        param_cols = [
            col for col in run_config.columns
            if col not in exclude_cols
        ]

        if not param_cols:
            self.logger.warning("No parameter columns found for clustering")
            candidates['cluster_id'] = 0
        else:
            # Create cluster ID by grouping on ALL parameters
            candidates['cluster_id'] = candidates.groupby(param_cols).ngroup()

        self.logger.info(f"  Clustered into {candidates['cluster_id'].nunique()} clusters")

        # 5. Calculate Neighbor Stability per cluster
        candidates = self._calculate_neighbor_stability(candidates, param_cols)

        return candidates

    def _calculate_neighbor_stability(
        self,
        df: pd.DataFrame,
        param_cols: List[str]
    ) -> pd.DataFrame:
        """
        Calculate Neighbor Stability Score (Plateau Test).

        Neighbor definition: SMA Slow within ±10 days AND Upper Thresh Z within ±0.1
        Degradation = 1 - (Neighbor_Return / Cluster_Return)

        Args:
            df: DataFrame with candidates and cluster assignments
            param_cols: List of parameter column names

        Returns:
            DataFrame with plateau_stability_pct column added
        """
        # Initialize stability column
        df['plateau_stability_pct'] = 100.0  # Default: stable

        # Find parameters for neighbor definition (if they exist)
        sma_slow_col = next((col for col in param_cols if 'sma_slow' in col.lower()), None)
        upper_thresh_col = next((col for col in param_cols if 'upper' in col.lower() and 'thresh' in col.lower()), None)

        if not sma_slow_col and not upper_thresh_col:
            self.logger.warning("No SMA_slow or Upper_thresh parameters found - using cluster-level stability")
            # Fallback: Use cluster-level stability (all runs in cluster are "neighbors")
            for cluster_id in df['cluster_id'].unique():
                cluster_runs = df[df['cluster_id'] == cluster_id]
                cluster_return = cluster_runs['Total Return %'].mean()

                # All runs in cluster are stable (no neighbor degradation)
                df.loc[df['cluster_id'] == cluster_id, 'plateau_stability_pct'] = 100.0

            return df

        # Calculate neighbor stability for each cluster
        for cluster_id in df['cluster_id'].unique():
            cluster_runs = df[df['cluster_id'] == cluster_id]

            if len(cluster_runs) == 1:
                # Single run in cluster - stable by definition
                df.loc[df['cluster_id'] == cluster_id, 'plateau_stability_pct'] = 100.0
                continue

            # Get cluster return (average)
            cluster_return = cluster_runs['Total Return %'].mean()

            # For each run, find neighbors and calculate degradation
            for idx, run in cluster_runs.iterrows():
                # Define neighbor criteria
                neighbors = cluster_runs.copy()

                # Filter by SMA Slow within ±10 days (if column exists)
                if sma_slow_col and sma_slow_col in cluster_runs.columns:
                    run_sma = run[sma_slow_col]
                    neighbors = neighbors[
                        (neighbors[sma_slow_col] >= run_sma - 10) &
                        (neighbors[sma_slow_col] <= run_sma + 10)
                    ]

                # Filter by Upper Thresh Z within ±0.1 (if column exists)
                if upper_thresh_col and upper_thresh_col in cluster_runs.columns:
                    run_thresh = run[upper_thresh_col]
                    neighbors = neighbors[
                        (neighbors[upper_thresh_col] >= run_thresh - 0.1) &
                        (neighbors[upper_thresh_col] <= run_thresh + 0.1)
                    ]

                # Calculate neighbor degradation
                if len(neighbors) > 0:
                    neighbor_return = neighbors['Total Return %'].mean()

                    if cluster_return != 0:
                        degradation = 1 - (neighbor_return / cluster_return)
                        stability = (1 - degradation) * 100

                        # Cap stability between 0% and 100%
                        stability = max(0.0, min(100.0, stability))
                    else:
                        stability = 100.0  # No cluster return, stable by default

                    df.loc[idx, 'plateau_stability_pct'] = stability
                else:
                    # No neighbors found - stable by default
                    df.loc[idx, 'plateau_stability_pct'] = 100.0

        return df

    def _stage_b_analyze(self, candidates: pd.DataFrame) -> pd.DataFrame:
        """
        Stage B: Stream daily data, calculate stress tests and yearly consistency.

        Memory efficient: Loads one run at a time.

        Args:
            candidates: Filtered candidates from Stage A

        Returns:
            Final analyzer_summary.csv data
        """
        results = []

        # Get QQQ benchmark return (if available)
        qqq_return = self._get_qqq_benchmark()

        # Process each cluster
        for cluster_id in tqdm(
            candidates['cluster_id'].unique(),
            desc="Analyzing clusters",
            unit="cluster"
        ):
            cluster_runs = candidates[candidates['cluster_id'] == cluster_id]

            # Get representative run for stress tests (best Sharpe ratio)
            best_run = cluster_runs.loc[cluster_runs['Sharpe Ratio'].idxmax()]

            # Stream daily data (memory efficient)
            daily_data = self._load_daily_data(best_run['Run ID'])

            if daily_data is None:
                self.logger.warning(f"Cluster {cluster_id}: No daily data for run {best_run['Run ID']}")
                continue

            # Calculate stress tests
            stress_results = self._calculate_stress_tests(daily_data)

            # Calculate yearly consistency
            yearly_score = self._calculate_yearly_consistency(daily_data, qqq_return)

            # Assign verdict
            verdict = self._classify_verdict(
                total_return=best_run['Total Return %'],
                max_drawdown=best_run['Max Drawdown'],
                calmar_ratio=best_run['Calmar Ratio'],
                stress_pass=stress_results['pass_all'],
                plateau_pass=best_run['plateau_stability_pct'] >= 90.0,
                yearly_high=yearly_score >= 10,
                benchmark_return=qqq_return
            )

            results.append({
                'cluster_id': cluster_id,
                'avg_total_return': cluster_runs['Total Return %'].mean(),
                'max_drawdown': cluster_runs['Max Drawdown'].min(),
                'calmar_ratio': cluster_runs['Calmar Ratio'].mean(),
                'plateau_stability_pct': best_run['plateau_stability_pct'],
                'stress_2018_ret': stress_results['2018_Vol'],
                'stress_2020_ret': stress_results['2020_Crash'],
                'stress_2022_ret': stress_results['2022_Bear'],
                'yearly_consistency': yearly_score,
                'verdict': verdict
            })

        return pd.DataFrame(results)

    def _load_daily_data(self, run_id) -> Optional[pd.DataFrame]:
        """
        Load portfolio daily CSV for a specific run (memory efficient streaming).

        Args:
            run_id: Run ID (string like "001" or integer like 1)

        Returns:
            DataFrame with daily portfolio data or None if not found
        """
        # Ensure run_id is zero-padded 3-digit string
        if isinstance(run_id, (int, np.integer)):
            run_id_str = f"{run_id:03d}"
        else:
            run_id_str = str(run_id).zfill(3)

        run_dir = self.output_dir / f"run_{run_id_str}"

        if not run_dir.exists():
            return None

        # Find the main portfolio CSV (not _summary or _trades)
        # Pattern: {strategy_name}_{timestamp}.csv
        csv_files = list(run_dir.glob("*.csv"))
        portfolio_file = None

        for csv_file in csv_files:
            # Skip summary and trades files
            if '_summary.csv' in csv_file.name or '_trades.csv' in csv_file.name:
                continue
            # This is the main portfolio daily file
            portfolio_file = csv_file
            break

        if portfolio_file is None:
            return None

        try:
            # Read CSV with date parsing (column name is 'Date')
            df = pd.read_csv(portfolio_file, parse_dates=['Date'])
            df['Date'] = pd.to_datetime(df['Date'])

            # Rename columns to match expected schema
            # Daily CSV has: Date, Portfolio_Total_Value (or variations)
            # Code expects: timestamp, value

            # Flexible column mapping - try multiple possible value column names
            value_column_candidates = [
                'Portfolio_Total_Value',  # Standard format
                'portfolio_value',        # Alternative format
                'value',                  # Already named correctly
                'portfolio_total_value'   # Lowercase variant
            ]

            # Find which value column exists
            value_column = None
            for candidate in value_column_candidates:
                if candidate in df.columns:
                    value_column = candidate
                    break

            if value_column is None:
                self.logger.error(
                    f"Portfolio CSV missing value column. Available columns: {df.columns.tolist()}"
                )
                return None

            # Rename columns
            rename_map = {'Date': 'timestamp'}
            if value_column != 'value':
                rename_map[value_column] = 'value'

            df = df.rename(columns=rename_map)

            # Validate that required columns exist
            if 'timestamp' not in df.columns or 'value' not in df.columns:
                self.logger.error(
                    f"Column rename failed. Final columns: {df.columns.tolist()}"
                )
                return None

            return df
        except Exception as e:
            self.logger.error(f"Failed to load {portfolio_file}: {e}")
            return None

    def _calculate_stress_tests(self, daily_df: pd.DataFrame) -> dict:
        """
        Calculate deterministic stress test returns.

        Uses EXACT date ranges and thresholds from specification.

        Args:
            daily_df: DataFrame with columns ['timestamp', 'value']

        Returns:
            {'2018_Vol': float, '2020_Crash': float, '2022_Bear': float, 'pass_all': bool}
        """
        results = {
            '2018_Vol': 0.0,
            '2020_Crash': 0.0,
            '2022_Bear': 0.0,
            'pass_all': False
        }

        # Define stress test periods and thresholds
        stress_tests = {
            '2018_Vol': {
                'start': '2018-02-01',
                'end': '2018-02-28',
                'threshold': -0.08  # -8.0%
            },
            '2020_Crash': {
                'start': '2020-02-19',
                'end': '2020-03-23',
                'threshold': -0.20  # -20.0%
            },
            '2022_Bear': {
                'start': '2022-01-01',
                'end': '2022-12-31',
                'threshold': -0.20  # -20.0%
            }
        }

        passes = []

        for test_name, test_config in stress_tests.items():
            start_date = pd.to_datetime(test_config['start'])
            end_date = pd.to_datetime(test_config['end'])
            threshold = test_config['threshold']

            # Filter data for stress period
            period_data = daily_df[
                (daily_df['timestamp'] >= start_date) &
                (daily_df['timestamp'] <= end_date)
            ].copy()

            if len(period_data) == 0:
                # No data for this period - mark as fail
                results[test_name] = threshold - 0.01  # Slightly below threshold
                passes.append(False)
                continue

            # Calculate return for period
            start_value = period_data.iloc[0]['value']
            end_value = period_data.iloc[-1]['value']

            if start_value > 0:
                period_return = (end_value - start_value) / start_value
            else:
                period_return = 0.0

            results[test_name] = period_return

            # Check if passed (return > threshold)
            passes.append(period_return > threshold)

        # Pass all tests?
        results['pass_all'] = all(passes)

        return results

    def _calculate_yearly_consistency(
        self,
        daily_df: pd.DataFrame,
        qqq_return: Optional[float]
    ) -> int:
        """
        Calculate yearly consistency score.

        Counts years where Strategy_Annual_Return > QQQ_Annual_Return.

        Args:
            daily_df: DataFrame with daily portfolio values
            qqq_return: QQQ benchmark annual return (if available)

        Returns:
            Number of years outperforming QQQ (0 if QQQ not available)
        """
        if qqq_return is None:
            return 0

        # Extract year from timestamp
        daily_df = daily_df.copy()
        daily_df['year'] = daily_df['timestamp'].dt.year

        # Calculate annual returns for each year
        years = daily_df['year'].unique()
        outperform_count = 0

        for year in years:
            year_data = daily_df[daily_df['year'] == year]

            if len(year_data) == 0:
                continue

            # Calculate annual return for strategy
            start_value = year_data.iloc[0]['value']
            end_value = year_data.iloc[-1]['value']

            if start_value > 0:
                annual_return = (end_value - start_value) / start_value
            else:
                annual_return = 0.0

            # Compare to QQQ
            if annual_return > qqq_return:
                outperform_count += 1

        return outperform_count

    def _get_qqq_benchmark(self) -> Optional[float]:
        """
        Get QQQ benchmark return from existing portfolio_daily.csv (if QQQ runs exist).

        Returns:
            QQQ annualized return or None if not available
        """
        # Look for QQQ baseline run (run_000) or QQQ symbol set runs
        qqq_run_dir = self.output_dir / "run_000"

        if qqq_run_dir.exists():
            daily_data = self._load_daily_data("000")

            if daily_data is not None and len(daily_data) > 1:
                # Calculate annualized return
                start_value = daily_data.iloc[0]['value']
                end_value = daily_data.iloc[-1]['value']

                if start_value > 0:
                    total_return = (end_value - start_value) / start_value

                    # Calculate number of years
                    days = (daily_data.iloc[-1]['timestamp'] - daily_data.iloc[0]['timestamp']).days
                    years = days / 365.25

                    if years > 0:
                        annualized_return = (1 + total_return) ** (1 / years) - 1
                        return annualized_return

        # Fallback: Try to find any QQQ run from summary
        summary_path = self.output_dir / 'summary_comparison.csv'
        summary = pd.read_csv(summary_path)

        qqq_runs = summary[summary['Symbol Set'].str.contains('QQQ', case=False, na=False)]

        if len(qqq_runs) > 0:
            # Use median annualized return from QQQ runs
            qqq_return = qqq_runs['Annualized Return %'].median()
            return qqq_return

        return None

    def _calculate_qqq_stress_tests(self) -> Dict[str, float]:
        """
        Calculate QQQ performance during stress test periods from Baseline_QQQ_Value column.

        Reads Baseline_QQQ_Value from any run's daily CSV (all runs should have identical
        baseline values) and calculates QQQ returns for three stress test periods.

        Returns:
            Dict with keys '2018_Vol', '2020_Crash', '2022_Bear' containing QQQ returns
            as float decimals (e.g., -0.073 for -7.3% return)

        Example:
            {'2018_Vol': -0.073, '2020_Crash': -0.27, '2022_Bear': -0.32}
        """
        # Find any run with daily data (prefer run_001)
        daily_data = None
        for run_id_str in ['001', '002', '003', '004', '005']:
            run_dir = self.output_dir / f"run_{run_id_str}"
            if run_dir.exists():
                csv_files = list(run_dir.glob("*.csv"))
                for csv_file in csv_files:
                    if '_summary.csv' in csv_file.name or '_trades.csv' in csv_file.name:
                        continue
                    try:
                        df = pd.read_csv(csv_file, parse_dates=['Date'])
                        if 'Baseline_QQQ_Value' in df.columns:
                            daily_data = df[['Date', 'Baseline_QQQ_Value']].copy()
                            daily_data['Date'] = pd.to_datetime(daily_data['Date'])
                            break
                    except Exception as e:
                        self.logger.warning(f"Failed to read {csv_file}: {e}")
                        continue
            if daily_data is not None:
                break

        if daily_data is None:
            self.logger.warning("No daily data with Baseline_QQQ_Value found for stress test calculation")
            return {'2018_Vol': 0.0, '2020_Crash': 0.0, '2022_Bear': 0.0}

        # Filter out N/A values and convert to numeric
        daily_data = daily_data[daily_data['Baseline_QQQ_Value'] != 'N/A'].copy()
        daily_data['Baseline_QQQ_Value'] = pd.to_numeric(daily_data['Baseline_QQQ_Value'], errors='coerce')
        daily_data = daily_data.dropna()

        if len(daily_data) == 0:
            self.logger.warning("No valid Baseline_QQQ_Value data for stress test calculation")
            return {'2018_Vol': 0.0, '2020_Crash': 0.0, '2022_Bear': 0.0}

        # Define stress test periods
        stress_periods = {
            '2018_Vol': ('2018-02-01', '2018-02-28'),
            '2020_Crash': ('2020-02-19', '2020-03-23'),
            '2022_Bear': ('2022-01-01', '2022-12-31')
        }

        results = {}

        for period_name, (start_date_str, end_date_str) in stress_periods.items():
            start_date = pd.to_datetime(start_date_str)
            end_date = pd.to_datetime(end_date_str)

            # Filter data for period
            period_data = daily_data[
                (daily_data['Date'] >= start_date) &
                (daily_data['Date'] <= end_date)
            ]

            if len(period_data) == 0:
                self.logger.warning(f"No data for stress period {period_name}")
                results[period_name] = 0.0
                continue

            # Calculate return
            start_value = period_data.iloc[0]['Baseline_QQQ_Value']
            end_value = period_data.iloc[-1]['Baseline_QQQ_Value']

            if start_value > 0:
                period_return = (end_value - start_value) / start_value
                results[period_name] = float(period_return)
            else:
                results[period_name] = 0.0

        return results

    def _calculate_qqq_overall_metrics(self) -> Dict[str, Any]:
        """
        Calculate comprehensive QQQ metrics from Baseline_QQQ_Value column.

        Calculates:
        - Total Return: (final_value - initial_value) / initial_value
        - Max Drawdown: Largest peak-to-trough decline
        - Calmar Ratio: Total Return / |Max Drawdown|
        - Sharpe Ratio: mean(daily_returns) / std(daily_returns) × sqrt(252)
        - Sortino Ratio: mean(daily_returns) / downside_std(daily_returns) × sqrt(252)

        Returns:
            Dict with all metrics as floats

        Example:
            {
                'total_return': 1.2811,
                'max_drawdown': -0.346,
                'calmar_ratio': 3.70,
                'sharpe_ratio': 1.85,
                'sortino_ratio': 2.45
            }
        """
        # Find any run with daily data
        daily_data = None
        for run_id_str in ['001', '002', '003', '004', '005']:
            run_dir = self.output_dir / f"run_{run_id_str}"
            if run_dir.exists():
                csv_files = list(run_dir.glob("*.csv"))
                for csv_file in csv_files:
                    if '_summary.csv' in csv_file.name or '_trades.csv' in csv_file.name:
                        continue
                    try:
                        df = pd.read_csv(csv_file, parse_dates=['Date'])
                        if 'Baseline_QQQ_Value' in df.columns:
                            daily_data = df[['Date', 'Baseline_QQQ_Value']].copy()
                            daily_data['Date'] = pd.to_datetime(daily_data['Date'])
                            break
                    except Exception as e:
                        self.logger.warning(f"Failed to read {csv_file}: {e}")
                        continue
            if daily_data is not None:
                break

        if daily_data is None:
            self.logger.warning("No daily data with Baseline_QQQ_Value found")
            return {}

        # Filter out N/A values and convert to numeric
        daily_data = daily_data[daily_data['Baseline_QQQ_Value'] != 'N/A'].copy()
        daily_data['Baseline_QQQ_Value'] = pd.to_numeric(daily_data['Baseline_QQQ_Value'], errors='coerce')
        daily_data = daily_data.dropna()

        if len(daily_data) < 2:
            self.logger.warning("Insufficient Baseline_QQQ_Value data for metrics calculation")
            return {}

        # Calculate metrics
        values = daily_data['Baseline_QQQ_Value'].values

        # Total Return
        initial_value = values[0]
        final_value = values[-1]
        total_return = (final_value - initial_value) / initial_value if initial_value > 0 else 0.0

        # Daily returns
        daily_returns = pd.Series(values).pct_change().dropna()

        # Max Drawdown
        peak = pd.Series(values).cummax()
        drawdown = (pd.Series(values) - peak) / peak
        max_drawdown = drawdown.min()

        # Calculate CAGR for Calmar ratio (geometric, not arithmetic)
        days = len(daily_data)
        years = days / 252.0  # Trading days per year
        if years > 0 and total_return > -1:
            cagr = (1 + total_return) ** (1 / years) - 1
        else:
            cagr = 0.0

        # Calmar Ratio: CAGR / |Max Drawdown| (industry standard)
        calmar_ratio = cagr / abs(max_drawdown) if max_drawdown != 0 else 0.0

        # Sharpe Ratio (annualized, arithmetic - no risk-free rate for comparison)
        sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if daily_returns.std() > 0 else 0.0

        # Sortino Ratio (semi-deviation per Sortino & Price 1994)
        # Key: Use ALL returns, clip at 0 (don't filter), then take sqrt(mean(squared))
        downside_returns = np.minimum(daily_returns.values, 0)  # Clip at 0, keep all obs
        semi_variance = (downside_returns ** 2).mean()  # Mean squared deviation
        if semi_variance > 0:
            semi_deviation = np.sqrt(semi_variance)
            annualized_semi_dev = semi_deviation * np.sqrt(252)
            # Use CAGR for numerator consistency
            sortino_ratio = cagr / annualized_semi_dev if annualized_semi_dev > 0 else 0.0
        else:
            sortino_ratio = 0.0

        # Profit Factor
        positive_sum = daily_returns[daily_returns > 0].sum()
        negative_sum = abs(daily_returns[daily_returns < 0].sum())
        profit_factor = positive_sum / negative_sum if negative_sum != 0 else 0.0

        return {
            'total_return': float(total_return),
            'max_drawdown': float(max_drawdown),
            'calmar_ratio': float(calmar_ratio),
            'sharpe_ratio': float(sharpe_ratio),
            'sortino_ratio': float(sortino_ratio),
            'profit_factor': float(profit_factor)
        }

    def _map_cluster_to_runs(self, candidates: pd.DataFrame, run_config: pd.DataFrame) -> Dict[int, Dict[str, Any]]:
        """
        Map each cluster_id to its constituent run_ids and parameters.

        Args:
            candidates: DataFrame from Stage A with cluster assignments
            run_config: DataFrame with run configurations

        Returns:
            Dict[cluster_id → {'run_ids': List[str], 'parameters': Dict}]

        Example:
            {
                0: {
                    'run_ids': ['001', '003', '005'],
                    'parameters': {
                        'leverage_scalar': 1.25,
                        'sma_slow': 140,
                        'use_inverse_hedge': True
                    }
                },
                ...
            }
        """
        cluster_map = {}

        for cluster_id in candidates['cluster_id'].unique():
            cluster_runs = candidates[candidates['cluster_id'] == cluster_id]

            # Get run IDs
            run_ids = cluster_runs['Run ID'].tolist()

            # Get parameters (use first run in cluster as representative)
            first_run = cluster_runs.iloc[0]

            # Extract parameters (exclude metadata columns)
            exclude_cols = {
                'run_id', 'Run ID', 'symbol_set', 'signal_symbol',
                'bull_symbol', 'defense_symbol', 'bear_symbol', 'vix_symbol',
                'core_long_symbol', 'leveraged_long_symbol',
                'leveraged_short_symbol', 'inverse_hedge_symbol',
                'Symbol Set', 'Portfolio Balance', 'Total Return %',
                'Annualized Return %', 'Max Drawdown', 'Sharpe Ratio',
                'Sortino Ratio', 'Calmar Ratio', 'Total Trades',
                'Profit Factor', 'Win Rate %', 'Avg Win ($)', 'Avg Loss ($)',
                'Alpha', 'plateau_stability_pct', 'cluster_id'
            }

            # Get parameter columns from run_config
            param_cols = [col for col in run_config.columns if col not in exclude_cols]

            # Build parameters dict (convert numpy types to Python types for JSON serialization)
            parameters = {}
            for param_col in param_cols:
                if param_col in first_run:
                    val = first_run[param_col]
                    # Convert numpy types to Python types
                    if isinstance(val, (np.integer, np.int64)):
                        parameters[param_col] = int(val)
                    elif isinstance(val, (np.floating, np.float64)):
                        parameters[param_col] = float(val)
                    elif isinstance(val, (np.bool_, bool)):
                        parameters[param_col] = bool(val)
                    else:
                        parameters[param_col] = val

            cluster_map[int(cluster_id)] = {
                'run_ids': run_ids,
                'parameters': parameters
            }

        return cluster_map

    def _save_qqq_baseline(self, qqq_metrics: Dict[str, Any], qqq_stress: Dict[str, float]):
        """
        Save QQQ baseline metrics to analyzer_qqq_baseline.csv.

        Args:
            qqq_metrics: Overall QQQ metrics dict
            qqq_stress: QQQ stress test results dict
        """
        baseline_data = {
            'metric': [
                'total_return',
                'max_drawdown',
                'calmar_ratio',
                'sharpe_ratio',
                'sortino_ratio',
                'profit_factor',
                'stress_2018_ret',
                'stress_2020_ret',
                'stress_2022_ret'
            ],
            'value': [
                f"{qqq_metrics.get('total_return', 0.0):.4f}",
                f"{qqq_metrics.get('max_drawdown', 0.0):.4f}",
                f"{qqq_metrics.get('calmar_ratio', 0.0):.4f}",
                f"{qqq_metrics.get('sharpe_ratio', 0.0):.4f}",
                f"{qqq_metrics.get('sortino_ratio', 0.0):.4f}",
                f"{qqq_metrics.get('profit_factor', 0.0):.4f}",
                f"{qqq_stress.get('2018_Vol', 0.0):.4f}",
                f"{qqq_stress.get('2020_Crash', 0.0):.4f}",
                f"{qqq_stress.get('2022_Bear', 0.0):.4f}"
            ]
        }

        df = pd.DataFrame(baseline_data)
        output_path = self.output_dir / 'analyzer_qqq_baseline.csv'
        df.to_csv(output_path, index=False)

    def _create_analyzer_definitions(self):
        """
        Create analyzer_definitions.md with verdict and metric definitions.
        """
        definitions_content = """# Analyzer Definitions

## Verdict Definitions

### TITAN CONFIG
- **Criteria**: >1.5× Benchmark AND Max DD >-25% AND passes Stress AND Plateau
- **Description**: Exceptional risk-adjusted returns with robust performance across stress periods

### Efficient Alpha
- **Criteria**: >1.2× Benchmark AND Max DD >-30% AND (passes Stress OR Plateau)
- **Description**: Strong alpha generation with acceptable risk profile

### Lucky Peak
- **Criteria**: >1.5× Benchmark AND any DD AND fails robustness
- **Description**: High returns but fails stress or plateau tests (unstable)

### Safe Harbor
- **Criteria**: 1.0-1.2× Benchmark AND Max DD >-20% AND passes Stress
- **Description**: Reliable baseline performance with strong downside protection

### Aggressive
- **Criteria**: >2.0× Benchmark AND Max DD <-30%
- **Description**: Very high returns with significant drawdown risk

### Degraded
- **Criteria**: < Benchmark AND any DD
- **Description**: Underperforms buy-and-hold benchmark

### Unsafe
- **Criteria**: any return AND Max DD <-35%
- **Description**: Catastrophic drawdown risk regardless of returns

## Metric Definitions

### Plateau Stability
- **Formula**: 100 × (1 - degradation)
- **Degradation**: 1 - (neighbor_return / cluster_return)
- **Neighbor Definition**: SMA Slow within ±10 days AND Upper Thresh Z within ±0.1
- **Interpretation**: Measures parameter sensitivity (higher = more stable)

### Yearly Consistency
- **Definition**: Number of years (out of 15: 2010-2024) where Strategy Annual Return > QQQ Annual Return
- **Interpretation**: Consistency of outperformance over time (higher = more consistent)

### Stress Tests
Three crisis periods with pass/fail thresholds:

#### 2018 Volatility Spike
- **Period**: 2018-02-01 to 2018-02-28
- **Threshold**: Return > -8.0%
- **Context**: Feb 2018 VIX explosion and market correction

#### 2020 COVID Crash
- **Period**: 2020-02-19 to 2020-03-23
- **Threshold**: Return > -20.0%
- **Context**: Fastest bear market in history

#### 2022 Bear Market
- **Period**: 2022-01-01 to 2022-12-31
- **Threshold**: Return > -20.0%
- **Context**: Fed tightening cycle and tech selloff

### Alpha
- **Formula**: Strategy_Total_Return / QQQ_Total_Return
- **Interpretation**:
  - 1.0 = Matches benchmark
  - >1.0 = Outperforms benchmark (e.g., 1.5 = 50% better)
  - <1.0 = Underperforms benchmark

### QQQ Baseline
The buy-and-hold QQQ performance for the backtest period, calculated from Baseline_QQQ_Value column in daily portfolio CSVs.
"""

        output_path = self.output_dir / 'analyzer_definitions.md'
        with open(output_path, 'w') as f:
            f.write(definitions_content)

    def _enhance_summary_comparison(self, qqq_metrics: Dict[str, Any], qqq_stress: Dict[str, float]):
        """
        Enhance summary_comparison.csv with:
        1. Fill Run 000 N/A values with calculated QQQ metrics
        2. Add qqq_stress_* columns for all runs

        Args:
            qqq_metrics: Overall QQQ metrics dict
            qqq_stress: QQQ stress test results dict
        """
        summary_path = self.output_dir / 'summary_comparison.csv'

        if not summary_path.exists():
            self.logger.warning("summary_comparison.csv not found, skipping enhancement")
            return

        # Read summary
        df = pd.read_csv(summary_path)

        # Update Run 000 if it exists (check both string '000' and integer 0)
        run_000_mask = (df['Run ID'] == '000') | (df['Run ID'] == 0)
        if run_000_mask.any():
            run_000_idx = df[run_000_mask].index[0]

            # Fill in missing metrics
            if qqq_metrics:
                df.loc[run_000_idx, 'Max Drawdown'] = round(qqq_metrics.get('max_drawdown', 0.0), 3)
                df.loc[run_000_idx, 'Sharpe Ratio'] = round(qqq_metrics.get('sharpe_ratio', 0.0), 2)
                df.loc[run_000_idx, 'Sortino Ratio'] = round(qqq_metrics.get('sortino_ratio', 0.0), 2)
                df.loc[run_000_idx, 'Calmar Ratio'] = round(qqq_metrics.get('calmar_ratio', 0.0), 2)
                df.loc[run_000_idx, 'Profit Factor'] = round(qqq_metrics.get('profit_factor', 0.0), 2)
                self.logger.info(f"  Updated Run 000 metrics: DD={qqq_metrics.get('max_drawdown', 0.0):.3f}, Sharpe={qqq_metrics.get('sharpe_ratio', 0.0):.2f}")

        # Add QQQ stress test columns for ALL runs
        df['qqq_stress_2018_ret'] = qqq_stress.get('2018_Vol', 0.0)
        df['qqq_stress_2020_ret'] = qqq_stress.get('2020_Crash', 0.0)
        df['qqq_stress_2022_ret'] = qqq_stress.get('2022_Bear', 0.0)

        # Save enhanced summary
        df.to_csv(summary_path, index=False)

    def _classify_verdict(
        self,
        total_return: float,
        max_drawdown: float,
        calmar_ratio: float,
        stress_pass: bool,
        plateau_pass: bool,
        yearly_high: bool,
        benchmark_return: Optional[float]
    ) -> str:
        """
        Assign verdict using priority queue (first match wins).

        Args:
            total_return: Total return (as decimal, e.g., 1.5 = 150%)
            max_drawdown: Max drawdown (as decimal, e.g., -0.25 = -25%)
            calmar_ratio: Calmar ratio
            stress_pass: All 3 stress tests passed
            plateau_pass: Neighbor stability >= 90%
            yearly_high: Yearly consistency >= 10 years
            benchmark_return: Benchmark return (for alpha calculation)

        Returns:
            Verdict string (one of 7 tiers)
        """
        # Calculate alpha (if benchmark available)
        alpha = None
        if benchmark_return is not None and benchmark_return != 0:
            alpha = total_return / benchmark_return

        # Priority queue (first match wins)

        # 1. TITAN CONFIG: >1.5× Benchmark AND MaxDD > -25% AND Stress_Pass AND Plateau_Pass
        if alpha is not None and alpha > 1.5 and max_drawdown > -0.25 and stress_pass and plateau_pass:
            return "TITAN CONFIG"

        # 2. Efficient Alpha: >1.2× Benchmark AND MaxDD > -30% AND (Stress_Pass OR Plateau_Pass)
        if alpha is not None and alpha > 1.2 and max_drawdown > -0.30 and (stress_pass or plateau_pass):
            return "Efficient Alpha"

        # 3. Lucky Peak: >1.5× Benchmark AND Fails robustness
        if alpha is not None and alpha > 1.5 and not (stress_pass and plateau_pass):
            return "Lucky Peak"

        # 4. Safe Harbor: 1.0-1.2× Benchmark AND MaxDD > -20% AND Stress_Pass
        if alpha is not None and 1.0 <= alpha <= 1.2 and max_drawdown > -0.20 and stress_pass:
            return "Safe Harbor"

        # 5. Aggressive: >2.0× Benchmark AND MaxDD < -30%
        if alpha is not None and alpha > 2.0 and max_drawdown < -0.30:
            return "Aggressive"

        # 6. Degraded: < Benchmark
        if alpha is not None and alpha < 1.0:
            return "Degraded"

        # 7. Unsafe: MaxDD < -35%
        if max_drawdown < -0.35:
            return "Unsafe"

        # Fallback (no clear classification)
        return "Unclassified"

    def _display_summary_stats(self, results: pd.DataFrame):
        """
        Display summary statistics for analysis results.

        Args:
            results: DataFrame with analyzer_summary.csv data
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("Analyzer Summary Statistics")
        self.logger.info("=" * 60)

        # Check if results is empty
        if len(results) == 0:
            self.logger.info("\nNo clusters analyzed (all runs filtered or missing data)")
            self.logger.info("=" * 60 + "\n")
            return

        # Count by verdict
        verdict_counts = results['verdict'].value_counts()

        self.logger.info("\nVerdicts:")
        for verdict, count in verdict_counts.items():
            self.logger.info(f"  {verdict}: {count}")

        # Average metrics by verdict
        if len(results) > 0:
            self.logger.info("\nAverage Metrics by Verdict:")
            for verdict in verdict_counts.index:
                verdict_data = results[results['verdict'] == verdict]
                avg_return = verdict_data['avg_total_return'].mean()
                avg_dd = verdict_data['max_drawdown'].mean()
                avg_calmar = verdict_data['calmar_ratio'].mean()

                self.logger.info(
                    f"  {verdict}: "
                    f"Return={avg_return:.2f}%, "
                    f"DD={avg_dd:.2f}%, "
                    f"Calmar={avg_calmar:.2f}"
                )

        self.logger.info("=" * 60 + "\n")
