"""
Monte Carlo Simulator - Bootstrap resampling for strategy robustness testing.

This module implements Monte Carlo simulation using bootstrap resampling to test
whether a strategy's performance is due to skill or luck by shuffling trade order.

Core Philosophy:
    "A strategy's performance depends on trade order - Monte Carlo shuffles to reveal
    if success was skill or luck"

Author: Jutsu Labs
Date: 2025-11-10
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import percentileofscore
from tqdm import tqdm

from jutsu_engine.utils.logging_config import get_logger


@dataclass
class MonteCarloConfig:
    """Configuration for Monte Carlo simulation."""

    # Input/Output
    input_file: Path
    output_directory: Path

    # Simulation Parameters
    iterations: int = 10000
    initial_capital: Decimal = Decimal('10000')
    random_seed: Optional[int] = None

    # Analysis Configuration
    percentiles: List[int] = field(default_factory=lambda: [5, 25, 50, 75, 95])
    confidence_level: float = 0.95
    risk_thresholds: List[int] = field(default_factory=lambda: [30, 40, 50])

    # Performance Options
    parallel: bool = False
    num_workers: Optional[int] = None

    # Visualization Settings
    visualization_enabled: bool = True
    visualization_dpi: int = 300
    visualization_figsize: Tuple[int, int] = (10, 6)


class MonteCarloSimulator:
    """
    Bootstrap resampling Monte Carlo simulation for strategy robustness testing.

    Tests vulnerability to luck and sequence risk by shuffling trade order.
    Answers: "If my trades happened in random order, what's my failure probability?"

    The simulator performs the following steps:
    1. Loads portfolio returns from WFO output (monte_carlo_input.csv)
    2. Runs N iterations (default: 10,000) of bootstrap resampling
    3. For each iteration:
       - Shuffles returns WITH replacement (bootstrap sampling)
       - Compounds returns to generate synthetic equity curve
       - Tracks max drawdown and final equity
    4. Analyzes distribution:
       - Percentiles (5th, 25th, 50th, 75th, 95th)
       - Risk of ruin (% below loss thresholds)
       - Confidence intervals (default: 95%)
    5. Generates outputs:
       - monte_carlo_results.csv (all simulation results)
       - monte_carlo_summary.txt (statistical analysis)

    Example:
        >>> config = MonteCarloConfig(
        ...     input_file=Path('output/wfo_*/monte_carlo_input.csv'),
        ...     output_directory=Path('output/monte_carlo_*'),
        ...     iterations=10000,
        ...     initial_capital=Decimal('10000')
        ... )
        >>> simulator = MonteCarloSimulator(config)
        >>> results = simulator.run()
        >>> print(f"Results: {results['summary_file']}")
    """

    def __init__(self, config: MonteCarloConfig):
        """
        Initialize Monte Carlo simulator with configuration.

        Args:
            config: MonteCarloConfig with all simulation parameters

        Raises:
            ValueError: If configuration is invalid
        """
        self.config = config
        self.logger = get_logger('APPLICATION.MONTE_CARLO')

        # Validate configuration
        self._validate_config()

        # Set random seed for reproducibility
        if self.config.random_seed is not None:
            np.random.seed(self.config.random_seed)
            self.logger.info(f"Random seed set to {self.config.random_seed} for reproducibility")

    def _validate_config(self) -> None:
        """
        Validate configuration parameters.

        Raises:
            ValueError: If any configuration parameter is invalid
        """
        if self.config.iterations <= 0:
            raise ValueError(f"Iterations must be positive, got {self.config.iterations}")

        if self.config.initial_capital <= 0:
            raise ValueError(f"Initial capital must be positive, got {self.config.initial_capital}")

        if not 0 < self.config.confidence_level < 1:
            raise ValueError(f"Confidence level must be between 0 and 1, got {self.config.confidence_level}")

        if not all(0 < t < 100 for t in self.config.risk_thresholds):
            raise ValueError(f"Risk thresholds must be between 0 and 100, got {self.config.risk_thresholds}")

    def run(self) -> Dict[str, Any]:
        """
        Run complete Monte Carlo simulation.

        Orchestrates: load input → run simulations → analyze → generate outputs

        Returns:
            Dict with keys:
                - results_file: Path to monte_carlo_results.csv
                - summary_file: Path to monte_carlo_summary.txt
                - analysis: Statistics dict with percentiles, risk, CI

        Raises:
            FileNotFoundError: If input file doesn't exist
            ValueError: If input validation fails
        """
        self.logger.info(f"Starting Monte Carlo simulation: {self.config.iterations} iterations")
        start_time = datetime.now()

        # 1. Load and validate input
        returns, original_equity = self._load_input()
        self.logger.info(f"Loaded {len(returns)} trade returns")

        # 2. Run simulations
        results_df = self._run_simulations(returns)
        self.logger.info(f"Completed {len(results_df)} simulations")

        # 3. Analyze results
        analysis = self._analyze_results(results_df, original_equity)

        # 4. Generate histograms
        self._generate_histograms(results_df, analysis)

        # 5. Generate outputs
        results_path = self._save_results(results_df)
        summary_path = self._save_summary(analysis, original_equity)

        duration = (datetime.now() - start_time).total_seconds()
        self.logger.info(f"Monte Carlo simulation complete in {duration:.1f}s")

        return {
            'results_file': results_path,
            'summary_file': summary_path,
            'analysis': analysis,
            'duration_seconds': duration
        }

    def _load_input(self) -> Tuple[np.ndarray, Optional[Decimal]]:
        """
        Load and validate input file.

        Returns:
            Tuple of (returns as numpy array, original final equity if available)

        Raises:
            FileNotFoundError: If input file doesn't exist
            ValueError: If input validation fails
        """
        if not self.config.input_file.exists():
            raise FileNotFoundError(
                f"Input file not found: {self.config.input_file}\n"
                f"Run WFO first: jutsu wfo --config wfo_config.yaml"
            )

        # Load CSV
        df = pd.read_csv(self.config.input_file)
        self.logger.debug(f"Loaded CSV with columns: {df.columns.tolist()}")

        # Validate required column
        if 'Portfolio_Return_Percent' not in df.columns:
            raise ValueError(
                f"Required column 'Portfolio_Return_Percent' not found.\n"
                f"Available columns: {df.columns.tolist()}"
            )

        # Extract returns (convert from percentage to decimal)
        returns = df['Portfolio_Return_Percent'].values / 100.0

        # Check for NaN values
        if np.isnan(returns).any():
            nan_count = np.isnan(returns).sum()
            raise ValueError(
                f"NaN values detected in returns ({nan_count} values).\n"
                f"Check monte_carlo_input.csv for data quality issues."
            )

        # Validate minimum trades
        if len(returns) < 10:
            raise ValueError(
                f"Only {len(returns)} trades found. Need at least 10 for meaningful Monte Carlo.\n"
                f"Run WFO with longer date range or lower optimization thresholds."
            )

        # Calculate original final equity if we can
        original_equity = None
        try:
            equity = float(self.config.initial_capital)
            for ret in returns:
                equity *= (1 + ret)
            original_equity = Decimal(str(equity))
            self.logger.info(f"Original final equity: ${original_equity:,.2f}")
        except Exception as e:
            self.logger.warning(f"Could not calculate original equity: {e}")

        self.logger.debug(f"Returns: mean={returns.mean():.4f}, std={returns.std():.4f}")

        return returns, original_equity

    def _calculate_actual_result(self, returns: np.ndarray) -> Tuple[Decimal, Decimal]:
        """
        Calculate actual WFO result (sequential order, no shuffling).

        Args:
            returns: Array of portfolio returns in original order

        Returns:
            Tuple of (final_equity, max_drawdown)
        """
        equity = float(self.config.initial_capital)
        peak_equity = equity
        max_drawdown = 0.0

        for ret in returns:
            equity *= (1 + ret)

            # Track peak and drawdown
            if equity > peak_equity:
                peak_equity = equity

            drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return Decimal(str(equity)), Decimal(str(max_drawdown))

    def _run_simulations(self, returns: np.ndarray) -> pd.DataFrame:
        """
        Run bootstrap simulations.

        Args:
            returns: Array of portfolio returns (as decimals, not percentages)

        Returns:
            DataFrame with columns: Run_ID, Final_Equity, Annualized_Return, Max_Drawdown
        """
        self.logger.info(f"Running {self.config.iterations} bootstrap simulations...")

        results = []

        # Use tqdm for progress bar
        for run_id in tqdm(range(1, self.config.iterations + 1), desc="Simulations"):
            result = self._simulate_single_run(returns, run_id)
            results.append(result)

        results_df = pd.DataFrame(results)
        return results_df

    def _simulate_single_run(self, returns: np.ndarray, run_id: int) -> Dict[str, Any]:
        """
        Simulate single run with shuffled returns.

        Args:
            returns: Array of portfolio returns
            run_id: Unique identifier for this run

        Returns:
            Dict with Run_ID, Final_Equity, Annualized_Return, Max_Drawdown
        """
        # Bootstrap sample: resample WITH replacement
        shuffled_returns = np.random.choice(returns, size=len(returns), replace=True)

        # Compound returns to generate equity curve
        equity = float(self.config.initial_capital)
        peak_equity = equity
        max_drawdown = 0.0

        for ret in shuffled_returns:
            equity *= (1 + ret)

            # Track peak and drawdown
            if equity > peak_equity:
                peak_equity = equity

            drawdown = (peak_equity - equity) / peak_equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        final_equity = equity

        # Calculate annualized return
        # Assuming daily returns, annualize with 252 trading days
        num_periods = len(shuffled_returns)
        total_return = (final_equity / float(self.config.initial_capital)) - 1
        annualized_return = (1 + total_return) ** (252 / num_periods) - 1 if num_periods > 0 else 0

        return {
            'Run_ID': run_id,
            'Final_Equity': round(final_equity, 2),
            'Annualized_Return': round(annualized_return * 100, 2),  # Convert to percentage
            'Max_Drawdown': round(max_drawdown * 100, 2)  # Convert to percentage
        }

    def _analyze_results(self, results_df: pd.DataFrame, original_equity: Optional[Decimal]) -> Dict[str, Any]:
        """
        Analyze simulation results.

        Args:
            results_df: DataFrame with simulation results
            original_equity: Original WFO final equity (if available)

        Returns:
            Dict with statistical analysis:
                - percentiles: Dict[metric, Dict[percentile, value]]
                - risk_of_ruin: Dict[threshold, percentage]
                - confidence_intervals: Dict[metric, Dict[lower, upper]]
                - original_result: Dict with actual WFO result and percentile rankings
        """
        self.logger.info("Analyzing simulation results...")

        analysis = {}

        # Calculate percentiles for each metric
        metrics = ['Final_Equity', 'Annualized_Return', 'Max_Drawdown']
        percentiles_dict = {}

        for metric in metrics:
            percentiles_dict[metric] = {}
            for p in self.config.percentiles:
                value = np.percentile(results_df[metric].values, p)
                percentiles_dict[metric][p] = round(float(value), 2)

        analysis['percentiles'] = percentiles_dict

        # Calculate risk of ruin (% of simulations below each threshold)
        risk_of_ruin = {}
        for threshold in self.config.risk_thresholds:
            # Risk of ruin = % of runs with max_drawdown > threshold
            loss_percentage = threshold
            count = (results_df['Max_Drawdown'] > loss_percentage).sum()
            risk_pct = (count / len(results_df)) * 100
            risk_of_ruin[threshold] = round(float(risk_pct), 2)

        analysis['risk_of_ruin'] = risk_of_ruin

        # Calculate confidence intervals
        alpha = 1 - self.config.confidence_level
        lower_percentile = (alpha / 2) * 100
        upper_percentile = (1 - alpha / 2) * 100

        confidence_intervals = {}
        for metric in metrics:
            lower = np.percentile(results_df[metric].values, lower_percentile)
            upper = np.percentile(results_df[metric].values, upper_percentile)
            confidence_intervals[metric] = {
                'lower': round(float(lower), 2),
                'upper': round(float(upper), 2)
            }

        analysis['confidence_intervals'] = confidence_intervals

        # Calculate actual WFO result and its ranking
        # This is loaded from the input file directly
        if original_equity is not None:
            # Calculate actual return and drawdown from original input order
            # We need to reload returns in original order
            df = pd.read_csv(self.config.input_file)
            returns = df['Portfolio_Return_Percent'].values / 100.0

            actual_equity, actual_dd = self._calculate_actual_result(returns)

            # Calculate annualized return
            num_periods = len(returns)
            total_return = (float(actual_equity) / float(self.config.initial_capital)) - 1
            actual_return = ((1 + total_return) ** (252 / num_periods) - 1) * 100 if num_periods > 0 else 0

            # Rank in distribution using percentileofscore
            return_percentile = percentileofscore(results_df['Annualized_Return'], actual_return, kind='weak')
            dd_percentile = percentileofscore(results_df['Max_Drawdown'], float(actual_dd) * 100, kind='weak')

            analysis['original_result'] = {
                'final_equity': float(actual_equity),
                'annualized_return': round(actual_return, 2),
                'max_drawdown': round(float(actual_dd) * 100, 2),
                'return_percentile': round(return_percentile, 1),
                'drawdown_percentile': round(dd_percentile, 1)
            }

            # Keep backward compatibility
            analysis['original_percentile'] = round(
                percentileofscore(results_df['Final_Equity'], float(actual_equity), kind='weak'), 1
            )
        else:
            analysis['original_result'] = None
            analysis['original_percentile'] = None

        return analysis

    def _generate_histograms(self, results_df: pd.DataFrame, analysis: Dict[str, Any]) -> None:
        """
        Generate return and drawdown histograms if visualization is enabled.

        Args:
            results_df: DataFrame with all simulation results
            analysis: Statistical analysis dict with original_result data
        """
        if not self.config.visualization_enabled:
            self.logger.info("Histogram generation disabled")
            return

        if analysis['original_result'] is None:
            self.logger.warning("Cannot generate histograms: original result not available")
            return

        self.logger.info("Generating histograms...")

        try:
            self._generate_return_histogram(results_df, analysis)
            self._generate_drawdown_histogram(results_df, analysis)
            self.logger.info("Histograms generated successfully")
        except Exception as e:
            self.logger.error(f"Failed to generate histograms: {e}")

    def _generate_return_histogram(self, results_df: pd.DataFrame, analysis: Dict[str, Any]) -> None:
        """
        Generate return distribution histogram with statistical markers.

        Creates histogram showing:
        1. Distribution of 10,000 simulated annualized returns
        2. Red dashed line: Actual WFO return
        3. Text annotation: Percentile of actual return
        4. Orange dotted line: 5th percentile threshold

        Args:
            results_df: DataFrame with simulation results
            analysis: Statistical analysis dict with original_result
        """
        # Create figure
        fig, ax = plt.subplots(figsize=self.config.visualization_figsize)

        # Get data
        simulated_returns = results_df['Annualized_Return'].values
        actual_return = analysis['original_result']['annualized_return']
        return_percentile = analysis['original_result']['return_percentile']
        percentile_5th = analysis['percentiles']['Annualized_Return'][5]

        # Plot histogram
        ax.hist(simulated_returns, bins=50, alpha=0.7, color='steelblue', edgecolor='black')

        # Add actual return marker (red dashed)
        ax.axvline(actual_return, color='red', linestyle='--', linewidth=2,
                  label=f'Actual WFO Return: {actual_return:.1f}%')

        # Add percentile annotation
        y_max = ax.get_ylim()[1]
        ax.text(actual_return, y_max * 0.95, f'{return_percentile:.1f}th percentile',
               ha='center', va='top', fontsize=10, color='darkred',
               bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

        # Add 5th percentile marker (orange dotted)
        ax.axvline(percentile_5th, color='orange', linestyle=':', linewidth=2,
                  label=f'5th Percentile: {percentile_5th:.1f}%')

        # Labels and title
        ax.set_xlabel('Annualized Return (%)', fontsize=12)
        ax.set_ylabel('Frequency', fontsize=12)
        ax.set_title('Monte Carlo Return Distribution (10,000 simulations)', fontsize=14, fontweight='bold')
        ax.legend(loc='upper left', fontsize=10)
        ax.grid(True, alpha=0.3)

        # Save figure
        self.config.output_directory.mkdir(parents=True, exist_ok=True)
        output_file = self.config.output_directory / 'monte_carlo_returns_histogram.png'
        fig.savefig(output_file, dpi=self.config.visualization_dpi, bbox_inches='tight')
        plt.close(fig)

        self.logger.info(f"Return histogram saved to: {output_file}")

    def _generate_drawdown_histogram(self, results_df: pd.DataFrame, analysis: Dict[str, Any]) -> None:
        """
        Generate drawdown distribution histogram with statistical markers.

        Creates histogram showing:
        1. Distribution of 10,000 simulated max drawdowns
        2. Dark red dashed line: Actual WFO max drawdown
        3. Text annotation: Percentile of actual drawdown
        4. Orange dotted line: 5th percentile (worst case)

        Args:
            results_df: DataFrame with simulation results
            analysis: Statistical analysis dict with original_result
        """
        # Create figure
        fig, ax = plt.subplots(figsize=self.config.visualization_figsize)

        # Get data
        simulated_drawdowns = results_df['Max_Drawdown'].values
        actual_dd = analysis['original_result']['max_drawdown']
        dd_percentile = analysis['original_result']['drawdown_percentile']
        percentile_5th = analysis['percentiles']['Max_Drawdown'][5]

        # Plot histogram
        ax.hist(simulated_drawdowns, bins=50, alpha=0.7, color='coral', edgecolor='black')

        # Add actual drawdown marker (dark red dashed)
        ax.axvline(actual_dd, color='darkred', linestyle='--', linewidth=2,
                  label=f'Actual WFO Drawdown: {actual_dd:.1f}%')

        # Add percentile annotation
        y_max = ax.get_ylim()[1]
        ax.text(actual_dd, y_max * 0.95, f'{dd_percentile:.1f}th percentile',
               ha='center', va='top', fontsize=10, color='darkred',
               bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

        # Add 5th percentile marker (orange dotted) - worst case
        ax.axvline(percentile_5th, color='orange', linestyle=':', linewidth=2,
                  label=f'5th Percentile: {percentile_5th:.1f}%')

        # Labels and title
        ax.set_xlabel('Max Drawdown (%)', fontsize=12)
        ax.set_ylabel('Frequency', fontsize=12)
        ax.set_title('Monte Carlo Drawdown Distribution (10,000 simulations)', fontsize=14, fontweight='bold')
        ax.legend(loc='upper right', fontsize=10)
        ax.grid(True, alpha=0.3)

        # Save figure
        output_file = self.config.output_directory / 'monte_carlo_drawdown_histogram.png'
        fig.savefig(output_file, dpi=self.config.visualization_dpi, bbox_inches='tight')
        plt.close(fig)

        self.logger.info(f"Drawdown histogram saved to: {output_file}")

    def _save_results(self, results_df: pd.DataFrame) -> Path:
        """
        Save simulation results to CSV.

        Args:
            results_df: DataFrame with all simulation results

        Returns:
            Path to saved results file
        """
        # Create output directory if needed
        self.config.output_directory.mkdir(parents=True, exist_ok=True)

        # Generate output filename
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        output_file = self.config.output_directory / f'monte_carlo_results_{timestamp}.csv'

        # Save to CSV
        results_df.to_csv(output_file, index=False)
        self.logger.info(f"Results saved to: {output_file}")

        return output_file

    def _save_summary(self, analysis: Dict[str, Any], original_equity: Optional[Decimal]) -> Path:
        """
        Generate and save human-readable summary report.

        Args:
            analysis: Statistical analysis dict
            original_equity: Original WFO final equity (if available)

        Returns:
            Path to saved summary file
        """
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        summary_file = self.config.output_directory / f'monte_carlo_summary_{timestamp}.txt'

        with open(summary_file, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("Monte Carlo Simulation Results\n")
            f.write("=" * 80 + "\n\n")

            f.write("Strategy Robustness Analysis\n")
            f.write("-" * 80 + "\n")

            if original_equity:
                original_return = ((float(original_equity) / float(self.config.initial_capital)) - 1) * 100
                f.write(f"Your original WFO result: ${original_equity:,.2f} ({original_return:.1f}% return)\n")
            else:
                f.write(f"Initial capital: ${self.config.initial_capital:,.2f}\n")

            f.write(f"Simulation: {self.config.iterations:,} shuffled trade sequences\n\n")

            # Percentile Analysis
            f.write("Percentile Analysis - Final Equity:\n")
            f.write("-" * 80 + "\n")
            percentile_descriptions = {
                5: "Very unlucky scenario",
                25: "Below average",
                50: "Median outcome",
                75: "Above average",
                95: "Very lucky scenario"
            }

            for p in self.config.percentiles:
                value = analysis['percentiles']['Final_Equity'][p]
                desc = percentile_descriptions.get(p, "")
                f.write(f"{p:3d}th percentile: ${value:>10,.2f}  ({desc})\n")

            f.write("\n")

            # Original result percentile
            if analysis['original_percentile'] is not None:
                percentile = analysis['original_percentile']
                f.write(f"Your original result (${original_equity:,.2f}) is at the {percentile:.1f}th percentile.\n")

                if percentile < 30:
                    interpretation = "This suggests your result is below average - you may have been unlucky with trade sequence."
                elif percentile < 60:
                    interpretation = "This suggests your result is near median - likely reflects true strategy edge rather than luck."
                elif percentile < 85:
                    interpretation = "This suggests your result is above average - you had a favorable trade sequence."
                else:
                    interpretation = "This suggests your result is in the top tier - you had a very lucky trade sequence."

                f.write(interpretation + "\n\n")

            # Risk of Ruin
            f.write("Risk of Ruin:\n")
            f.write("-" * 80 + "\n")
            risk_interpretations = {
                (0, 5): "VERY LOW RISK",
                (5, 15): "LOW RISK",
                (15, 30): "MODERATE RISK",
                (30, float('inf')): "HIGH RISK"
            }

            for threshold in self.config.risk_thresholds:
                risk_pct = analysis['risk_of_ruin'][threshold]

                # Determine risk level
                risk_level = "UNKNOWN"
                for (low, high), level in risk_interpretations.items():
                    if low <= risk_pct < high:
                        risk_level = level
                        break

                f.write(f"  {threshold}% loss: {risk_pct:>5.1f}% of simulations ({risk_level})\n")

            f.write("\n")

            # Confidence Intervals
            f.write(f"{int(self.config.confidence_level * 100)}% Confidence Intervals:\n")
            f.write("-" * 80 + "\n")

            ci = analysis['confidence_intervals']
            f.write(f"Final Equity:       ${ci['Final_Equity']['lower']:>10,.2f} to ${ci['Final_Equity']['upper']:>10,.2f}\n")
            f.write(f"Annualized Return:  {ci['Annualized_Return']['lower']:>9.1f}% to {ci['Annualized_Return']['upper']:>9.1f}%\n")
            f.write(f"Max Drawdown:       {ci['Max_Drawdown']['lower']:>9.1f}% to {ci['Max_Drawdown']['upper']:>9.1f}%\n\n")

            # Interpretation and Recommendations
            f.write("Interpretation:\n")
            f.write("-" * 80 + "\n")

            # Determine overall robustness
            median_equity = analysis['percentiles']['Final_Equity'][50]
            equity_range = (analysis['confidence_intervals']['Final_Equity']['upper'] -
                          analysis['confidence_intervals']['Final_Equity']['lower'])

            max_risk = max(analysis['risk_of_ruin'].values())

            interpretations = []

            if median_equity > float(self.config.initial_capital) * 1.1:
                interpretations.append("✅ POSITIVE EXPECTANCY: Median outcome shows profit")
            else:
                interpretations.append("⚠️  LOW EXPECTANCY: Median outcome near breakeven")

            if max_risk < 10:
                interpretations.append("✅ LOW RISK: Probability of catastrophic loss is very low")
            elif max_risk < 25:
                interpretations.append("⚠️  MODERATE RISK: Some probability of significant loss")
            else:
                interpretations.append("❌ HIGH RISK: Significant probability of large losses")

            if equity_range / float(self.config.initial_capital) < 1.0:
                interpretations.append("✅ CONSISTENT: Narrow range of outcomes suggests robust strategy")
            else:
                interpretations.append("⚠️  VOLATILE: Wide range of outcomes suggests high sensitivity to trade sequence")

            for interp in interpretations:
                f.write(interp + "\n")

            f.write("\n")

            # Recommendation
            f.write("Recommendation:\n")
            f.write("-" * 80 + "\n")

            if max_risk < 10 and median_equity > float(self.config.initial_capital) * 1.1:
                f.write("Strategy appears robust with low risk. Consider proceeding to paper trading.\n")
            elif max_risk < 25:
                f.write("Strategy shows potential but moderate risk. Consider further optimization or position sizing.\n")
            else:
                f.write("Strategy shows high risk of significant loss. Consider major revisions before live trading.\n")

        self.logger.info(f"Summary saved to: {summary_file}")
        return summary_file
