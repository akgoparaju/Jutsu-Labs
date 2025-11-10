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
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional
import itertools

import yaml
import pandas as pd
from tqdm import tqdm

from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.utils.logging_config import setup_logger
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker
from jutsu_engine.performance.analyzer import PerformanceAnalyzer

logger = setup_logger('APPLICATION.GRID_SEARCH', log_to_console=True)


@dataclass
class SymbolSet:
    """
    Grouped symbol configuration (prevents invalid combinations).

    Symbol sets ensure that incompatible symbol combinations
    (e.g., mixing NVDA signals with QQQ leverage) don't occur.

    Attributes:
        name: Human-readable name (e.g., "NVDA-NVDL" or "QQQ-TQQQ-VIX")
        signal_symbol: Symbol for signals (e.g., NVDA, QQQ)
        bull_symbol: Leveraged bull symbol (e.g., NVDL, TQQQ)
        defense_symbol: Defensive position symbol (e.g., NVDA, QQQ)
        vix_symbol: Optional VIX symbol for regime detection (e.g., VIX)
                   Required for MACD_Trend_v5 and other VIX-filtered strategies
    """
    name: str
    signal_symbol: str
    bull_symbol: str
    defense_symbol: str
    vix_symbol: Optional[str] = None


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
            'bull_symbol': self.symbol_set.bull_symbol,
            'defense_symbol': self.symbol_set.defense_symbol,
            **self.parameters
        }

        # Include vix_symbol if present (for v5 strategies)
        if self.symbol_set.vix_symbol is not None:
            result['vix_symbol'] = self.symbol_set.vix_symbol

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
        config_path: Optional[str] = None
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

        Returns:
            GridSearchResult with all run results and summary

        Example:
            result = runner.execute_grid_search(output_base="output")
            print(f"Completed {len(result.run_results)} runs")
        """
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
            end_date = datetime.strptime(end_date, '%Y-%m-%d')

        # Prepare symbols list (conditionally include vix_symbol)
        symbols = [
            run_config.symbol_set.signal_symbol,
            run_config.symbol_set.bull_symbol,
            run_config.symbol_set.defense_symbol
        ]
        if run_config.symbol_set.vix_symbol is not None:
            symbols.append(run_config.symbol_set.vix_symbol)

        # Prepare strategy params (conditionally include vix_symbol)
        strategy_params = {
            'signal_symbol': run_config.symbol_set.signal_symbol,
            'bull_symbol': run_config.symbol_set.bull_symbol,
            'defense_symbol': run_config.symbol_set.defense_symbol,
            **run_config.parameters
        }
        if run_config.symbol_set.vix_symbol is not None:
            strategy_params['vix_symbol'] = run_config.symbol_set.vix_symbol

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

            # Import strategy class dynamically
            import importlib
            module = importlib.import_module(f"jutsu_engine.strategies.{self.config.strategy_name}")
            strategy_class = getattr(module, self.config.strategy_name)
            strategy = strategy_class(**config['strategy_params'])

            result = runner.run(strategy, output_dir=str(run_dir))

            # Extract metrics
            metrics = {
                'final_value': result.get('final_value', 0.0),
                'total_return_pct': result.get('total_return', 0.0) * 100,
                'annualized_return_pct': result.get('annualized_return', 0.0) * 100,
                'sharpe_ratio': result.get('sharpe_ratio', 0.0),
                'sortino_ratio': result.get('sortino_ratio', 0.0),
                'max_drawdown_pct': result.get('max_drawdown', 0.0) * 100,
                'calmar_ratio': result.get('calmar_ratio', 0.0),
                'win_rate_pct': result.get('win_rate', 0.0) * 100,
                'total_trades': result.get('total_trades', 0),
                'profit_factor': result.get('profit_factor', 0.0),
                'avg_win_usd': result.get('avg_win', 0.0),
                'avg_loss_usd': result.get('avg_loss', 0.0)
            }

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
            total_return_pct = round(result.metrics.get('total_return_pct', 0.0) / 100, 3)  # Divide by 100 for Excel
            annualized_return_pct = round(result.metrics.get('annualized_return_pct', 0.0) / 100, 3)  # Divide by 100
            max_drawdown = round(result.metrics.get('max_drawdown_pct', 0.0) / 100, 3)  # Divide by 100
            sharpe_ratio = round(result.metrics.get('sharpe_ratio', 0.0), 2)
            sortino_ratio = round(result.metrics.get('sortino_ratio', 0.0), 2)
            calmar_ratio = round(result.metrics.get('calmar_ratio', 0.0), 2)
            total_trades = int(result.metrics.get('total_trades', 0))
            profit_factor = round(result.metrics.get('profit_factor', 0.0), 2)
            win_rate_pct = round(result.metrics.get('win_rate_pct', 0.0) / 100, 3)  # Divide by 100
            avg_win = round(result.metrics.get('avg_win_usd', 0.0), 2)
            avg_loss = round(result.metrics.get('avg_loss_usd', 0.0), 2)

            # Calculate alpha vs baseline
            alpha = 'N/A'
            if baseline_total_return is not None and total_return_pct != 0:
                strategy_return = total_return_pct  # Already in decimal form
                if baseline_total_return != 0:
                    # Alpha as ratio (e.g., 1.20 means 20% better than baseline)
                    alpha_value = strategy_return / baseline_total_return
                    alpha = f"{alpha_value:.2f}"
                else:
                    # Baseline return is zero, cannot calculate ratio
                    alpha = 'N/A'

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
                'Alpha': alpha  # NEW COLUMN
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
            'EMA Period', 'ATR Stop Multiplier', 'Risk Bull',
            'MACD Fast Period', 'MACD Slow Period', 'MACD Signal Period',
            'ATR Period', 'Allocation Defense',
            'Alpha'  # NEW - alpha column at end
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

        Uses QQQ data to calculate buy-and-hold baseline for the grid search
        date range. This baseline is written as row 000 in the summary CSV
        for performance comparison.

        Returns:
            Dict with baseline metrics or None if calculation fails:
                - baseline_symbol: str
                - baseline_final_value: float
                - baseline_total_return: float
                - baseline_annualized_return: float

        Example:
            baseline = runner._calculate_baseline_for_grid_search()
            if baseline:
                print(f"Baseline return: {baseline['baseline_total_return']:.2%}")
        """
        try:
            self.logger.info("Calculating buy-and-hold baseline (QQQ)...")

            # Parse dates from base_config (handle both str and datetime)
            start_date = self.config.base_config['start_date']
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d')

            end_date = self.config.base_config['end_date']
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, '%Y-%m-%d')

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
                baseline_symbol = 'QQQ'
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

                # Calculate baseline using PerformanceAnalyzer
                # Note: We don't need an equity curve for baseline calculation
                # PerformanceAnalyzer.calculate_baseline() only needs prices and dates

                # Create minimal PerformanceAnalyzer instance
                # (equity_df not used by calculate_baseline, but required by __init__)
                import pandas as pd
                dummy_equity_df = pd.DataFrame({
                    'timestamp': [qqq_bars[0].timestamp, qqq_bars[-1].timestamp],
                    'value': [
                        self.config.base_config['initial_capital'],
                        self.config.base_config['initial_capital']
                    ]
                }).set_index('timestamp')

                analyzer = PerformanceAnalyzer(
                    fills=[],  # No fills for baseline
                    equity_curve=dummy_equity_df,
                    initial_capital=Decimal(str(self.config.base_config['initial_capital']))
                )

                baseline_result = analyzer.calculate_baseline(
                    symbol=baseline_symbol,
                    start_price=qqq_bars[0].close,
                    end_price=qqq_bars[-1].close,
                    start_date=qqq_bars[0].timestamp,
                    end_date=qqq_bars[-1].timestamp
                )

                if baseline_result:
                    self.logger.info(
                        f"Baseline calculated: {baseline_symbol} "
                        f"{baseline_result['baseline_total_return']:.2%} total return"
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
        the summary_comparison.csv schema, with special handling for N/A values.

        Args:
            baseline: Baseline calculation results from calculate_baseline()
                Keys: baseline_symbol, baseline_final_value, baseline_total_return,
                      baseline_annualized_return

        Returns:
            Dict matching summary CSV columns with human-readable format:
                - run_id: '000'
                - symbol_set: 'Buy & Hold QQQ'
                - initial_capital, final_value, returns
                - N/A for strategy-specific metrics (Sharpe, drawdown, win rate)
                - alpha: '1.00' (baseline has alpha = 1.00 by definition)

        Example:
            baseline = self._calculate_baseline_for_grid_search()
            if baseline:
                row = self._format_baseline_row(baseline)
                # row['run_id'] == '000'
                # row['sharpe_ratio'] == 'N/A'
                # row['alpha'] == '1.00'
        """
        initial_capital = self.config.base_config['initial_capital']

        return {
            'Run ID': '000',
            'Symbol Set': 'Buy & Hold QQQ',
            'Portfolio Balance': round(baseline['baseline_final_value'], 2),
            'Total Return %': round(baseline['baseline_total_return'], 3),  # Already decimal
            'Annualized Return %': round(baseline['baseline_annualized_return'], 3),  # Already decimal
            'Max Drawdown': 'N/A',  # Requires daily equity curve
            'Sharpe Ratio': 'N/A',  # Not applicable for buy-and-hold
            'Sortino Ratio': 'N/A',  # Not applicable for buy-and-hold
            'Calmar Ratio': 'N/A',  # Not applicable for buy-and-hold
            'Total Trades': 0,
            'Profit Factor': 'N/A',  # No trades
            'Win Rate %': 'N/A',  # No trades
            'Avg Win ($)': 'N/A',  # No trades
            'Avg Loss ($)': 'N/A',  # No trades
            'Alpha': '1.00'  # Baseline has alpha = 1.00 by definition
        }
