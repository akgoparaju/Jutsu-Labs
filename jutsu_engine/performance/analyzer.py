"""
Performance analysis for backtesting results.

Calculates comprehensive performance metrics including returns, risk-adjusted
metrics, drawdowns, and trade statistics.

Example:
    from jutsu_engine.performance.analyzer import PerformanceAnalyzer

    analyzer = PerformanceAnalyzer(
        fills=all_fills,
        equity_curve=portfolio.get_equity_curve(),
        initial_capital=Decimal('100000')
    )

    metrics = analyzer.calculate_metrics()
    print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {metrics['max_drawdown']:.2%}")
"""
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
import pandas as pd
import numpy as np
from scipy import stats

from jutsu_engine.core.events import FillEvent
from jutsu_engine.utils.logging_config import get_performance_logger

logger = get_performance_logger()


class PerformanceAnalyzer:
    """
    Analyzes backtest performance and calculates metrics.

    Provides comprehensive performance metrics including:
    - Returns (total, annualized, monthly)
    - Risk metrics (Sharpe ratio, volatility, max drawdown)
    - Trade statistics (win rate, profit factor, average win/loss)

    Attributes:
        fills: List of all fill events from backtest
        equity_curve: List of (timestamp, portfolio_value) tuples
        initial_capital: Starting capital amount
    """

    def __init__(
        self,
        fills: List[FillEvent],
        equity_curve: List[Tuple[datetime, Decimal]],
        initial_capital: Decimal,
    ):
        """
        Initialize performance analyzer.

        Args:
            fills: List of FillEvent objects from backtest
            equity_curve: List of (timestamp, value) tuples
            initial_capital: Starting capital

        Example:
            analyzer = PerformanceAnalyzer(
                fills=backtest_fills,
                equity_curve=portfolio.get_equity_curve(),
                initial_capital=Decimal('100000')
            )
        """
        self.fills = fills
        self.equity_curve = equity_curve
        self.initial_capital = initial_capital

        # Convert equity curve to DataFrame for analysis
        if equity_curve:
            self.equity_df = pd.DataFrame(
                equity_curve,
                columns=['timestamp', 'value']
            )
            self.equity_df['value'] = self.equity_df['value'].astype(float)
            self.equity_df['timestamp'] = pd.to_datetime(self.equity_df['timestamp'])
            self.equity_df.set_index('timestamp', inplace=True)
        else:
            self.equity_df = pd.DataFrame()

        logger.info(
            f"PerformanceAnalyzer initialized: "
            f"{len(fills)} fills, {len(equity_curve)} equity points"
        )

    def calculate_metrics(self) -> Dict[str, float]:
        """
        Calculate comprehensive performance metrics.

        Returns:
            Dictionary of performance metrics

        Example:
            metrics = analyzer.calculate_metrics()
            print(f"Total Return: {metrics['total_return']:.2%}")
            print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        """
        metrics = {}

        if self.equity_df.empty:
            logger.warning("Empty equity curve, returning zero metrics")
            return self._zero_metrics()

        # Return metrics
        metrics['total_return'] = self._calculate_total_return()
        metrics['annualized_return'] = self._calculate_annualized_return()

        # Risk metrics
        metrics['volatility'] = self._calculate_volatility()
        metrics['sharpe_ratio'] = self._calculate_sharpe_ratio()
        metrics['sortino_ratio'] = self.calculate_sortino_ratio(self.equity_df['returns'])
        metrics['max_drawdown'] = self._calculate_max_drawdown()
        metrics['calmar_ratio'] = self._calculate_calmar_ratio()

        # Trade statistics
        trade_stats = self._calculate_trade_statistics()
        metrics.update(trade_stats)

        # Additional metrics
        metrics['final_value'] = float(self.equity_df['value'].iloc[-1])
        metrics['initial_capital'] = float(self.initial_capital)

        logger.info(
            f"Performance: Return={metrics['total_return']:.2%}, "
            f"Sharpe={metrics['sharpe_ratio']:.2f}, "
            f"MaxDD={metrics['max_drawdown']:.2%}"
        )

        return metrics

    def _zero_metrics(self) -> Dict[str, float]:
        """Return zero metrics for empty backtest."""
        return {
            'total_return': 0.0,
            'annualized_return': 0.0,
            'volatility': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown': 0.0,
            'calmar_ratio': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'final_value': float(self.initial_capital),
            'initial_capital': float(self.initial_capital),
        }

    def _calculate_total_return(self) -> float:
        """Calculate total return percentage."""
        final_value = self.equity_df['value'].iloc[-1]
        initial_value = float(self.initial_capital)
        return (final_value - initial_value) / initial_value

    def _calculate_annualized_return(self) -> float:
        """Calculate annualized return."""
        total_return = self._calculate_total_return()

        # Calculate time period in years
        start_date = self.equity_df.index[0]
        end_date = self.equity_df.index[-1]
        days = (end_date - start_date).days

        if days == 0:
            return 0.0

        years = days / 365.25

        # Annualized return = (1 + total_return)^(1/years) - 1
        annualized = (1 + total_return) ** (1 / years) - 1

        return annualized

    def _calculate_volatility(self) -> float:
        """Calculate annualized volatility (standard deviation of returns)."""
        if len(self.equity_df) < 2:
            return 0.0

        # Calculate daily returns
        self.equity_df['returns'] = self.equity_df['value'].pct_change()

        # Annualized volatility (assuming 252 trading days)
        daily_std = self.equity_df['returns'].std()
        annualized_vol = daily_std * np.sqrt(252)

        return annualized_vol

    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sharpe ratio (risk-adjusted return).

        Args:
            risk_free_rate: Annual risk-free rate (default: 2%)

        Returns:
            Sharpe ratio
        """
        annualized_return = self._calculate_annualized_return()
        volatility = self._calculate_volatility()

        if volatility == 0:
            return 0.0

        sharpe = (annualized_return - risk_free_rate) / volatility
        return sharpe

    def _calculate_max_drawdown(self) -> float:
        """
        Calculate maximum drawdown percentage.

        Maximum drawdown is the largest peak-to-trough decline.
        Capped at -100% (cannot lose more than 100% in traditional sense).
        """
        if len(self.equity_df) < 2:
            return 0.0

        # Calculate running maximum
        self.equity_df['cummax'] = self.equity_df['value'].cummax()

        # Calculate drawdown
        self.equity_df['drawdown'] = (
            (self.equity_df['value'] - self.equity_df['cummax']) /
            self.equity_df['cummax']
        )

        # Maximum drawdown (most negative value)
        max_dd = self.equity_df['drawdown'].min()

        # Cap drawdown at -100% (cannot lose more than 100%)
        # Values below -1.0 indicate portfolio went negative or calculation error
        if max_dd < -1.0:
            logger.warning(
                f"Max drawdown {max_dd:.2%} exceeds -100%, capping at -100%. "
                f"This may indicate portfolio went negative or position management issues."
            )
            max_dd = -1.0

        return max_dd

    def _calculate_calmar_ratio(self) -> float:
        """
        Calculate Calmar ratio (annualized return / max drawdown).

        Measures return per unit of downside risk.
        """
        annualized_return = self._calculate_annualized_return()
        max_drawdown = abs(self._calculate_max_drawdown())

        if max_drawdown == 0:
            return 0.0

        return annualized_return / max_drawdown

    def _calculate_trade_statistics(self) -> Dict[str, float]:
        """Calculate trade-level statistics."""
        if not self.fills:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
            }

        # Group fills by symbol to calculate PnL per trade
        trades_by_symbol = {}

        for fill in self.fills:
            symbol = fill.symbol
            if symbol not in trades_by_symbol:
                trades_by_symbol[symbol] = []
            trades_by_symbol[symbol].append(fill)

        # Calculate PnL for each closed trade
        trade_pnls = []

        for symbol, symbol_fills in trades_by_symbol.items():
            position = Decimal('0')
            entry_price = Decimal('0')
            shares_in_position = Decimal('0')

            for fill in symbol_fills:
                if fill.direction == 'BUY':
                    # Update average entry price
                    total_cost = (entry_price * shares_in_position) + \
                                (fill.fill_price * fill.quantity)
                    shares_in_position += fill.quantity
                    if shares_in_position > 0:
                        entry_price = total_cost / shares_in_position
                    position += fill.quantity

                else:  # SELL
                    if position > 0:
                        # Calculate PnL for this exit
                        pnl = (fill.fill_price - entry_price) * fill.quantity
                        pnl -= (fill.commission + fill.slippage)
                        trade_pnls.append(float(pnl))

                    position -= fill.quantity
                    shares_in_position -= fill.quantity

        if not trade_pnls:
            # Count number of trades (buy or sell fills) but no closed trades
            return {
                'total_trades': len(self.fills),
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
            }

        # Separate winning and losing trades
        wins = [pnl for pnl in trade_pnls if pnl > 0]
        losses = [pnl for pnl in trade_pnls if pnl <= 0]

        total_trades = len(trade_pnls)
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        # Average win/loss
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        # Profit factor = total wins / total losses
        total_wins = sum(wins)
        total_losses = abs(sum(losses))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0.0

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
        }

    def generate_report(self) -> str:
        """
        Generate formatted performance report.

        Returns:
            String containing formatted performance metrics

        Example:
            report = analyzer.generate_report()
            print(report)
        """
        metrics = self.calculate_metrics()

        report = []
        report.append("=" * 60)
        report.append("BACKTEST PERFORMANCE REPORT")
        report.append("=" * 60)
        report.append("")

        report.append("RETURNS:")
        report.append(f"  Initial Capital:      ${metrics['initial_capital']:>15,.2f}")
        report.append(f"  Final Value:          ${metrics['final_value']:>15,.2f}")
        report.append(f"  Total Return:         {metrics['total_return']:>16.2%}")
        report.append(f"  Annualized Return:    {metrics['annualized_return']:>16.2%}")
        report.append("")

        report.append("RISK METRICS:")
        report.append(f"  Volatility:           {metrics['volatility']:>16.2%}")
        report.append(f"  Sharpe Ratio:         {metrics['sharpe_ratio']:>16.2f}")
        report.append(f"  Max Drawdown:         {metrics['max_drawdown']:>16.2%}")
        report.append(f"  Calmar Ratio:         {metrics['calmar_ratio']:>16.2f}")
        report.append("")

        report.append("TRADE STATISTICS:")
        report.append(f"  Total Trades:         {metrics['total_trades']:>16}")
        report.append(f"  Winning Trades:       {metrics['winning_trades']:>16}")
        report.append(f"  Losing Trades:        {metrics['losing_trades']:>16}")
        report.append(f"  Win Rate:             {metrics['win_rate']:>16.2%}")
        report.append(f"  Profit Factor:        {metrics['profit_factor']:>16.2f}")
        report.append(f"  Average Win:          ${metrics['avg_win']:>15,.2f}")
        report.append(f"  Average Loss:         ${metrics['avg_loss']:>15,.2f}")
        report.append("")
        report.append("=" * 60)

        return "\n".join(report)

    # ============================================================================
    # Phase 2: Advanced Metrics
    # ============================================================================

    def calculate_sortino_ratio(
        self,
        returns: pd.Series,
        target_return: float = 0.0,
        periods: int = 252
    ) -> float:
        """
        Calculate Sortino ratio (downside deviation-adjusted returns).

        Args:
            returns: Series of returns
            target_return: Minimum acceptable return (MAR)
            periods: Number of periods per year for annualization

        Returns:
            Sortino ratio (higher is better, focuses on downside risk)

        Formula:
            Sortino = (Mean Return - Target) / Downside Deviation
            where Downside Deviation = std of returns below target
        """
        if len(returns) < 2:
            logger.warning(f"Insufficient data for Sortino ratio: {len(returns)} returns")
            return 0.0

        excess_returns = returns - target_return
        downside_returns = excess_returns[excess_returns < 0]

        if len(downside_returns) == 0:
            logger.debug("No downside returns - returning infinite Sortino ratio")
            return float('inf')

        downside_std = downside_returns.std()

        if downside_std == 0:
            logger.debug("Zero downside deviation - returning infinite Sortino ratio")
            return float('inf')

        # Annualize
        annualized_return = returns.mean() * periods
        annualized_downside = downside_std * np.sqrt(periods)

        sortino = (annualized_return - target_return) / annualized_downside

        logger.debug(f"Sortino ratio calculated: {sortino:.2f}")
        return float(sortino)

    def calculate_omega_ratio(
        self,
        returns: pd.Series,
        threshold: float = 0.0
    ) -> float:
        """
        Calculate Omega ratio (probability-weighted gains vs losses).

        Args:
            returns: Series of returns
            threshold: Return threshold (default 0%)

        Returns:
            Omega ratio (>1 means gains outweigh losses)

        Formula:
            Omega = Sum(gains above threshold) / Sum(losses below threshold)
        """
        if len(returns) < 2:
            logger.warning(f"Insufficient data for Omega ratio: {len(returns)} returns")
            return 0.0

        gains = returns[returns > threshold] - threshold
        losses = threshold - returns[returns < threshold]

        if losses.sum() == 0:
            logger.debug("No losses - returning infinite Omega ratio")
            return float('inf')

        omega = gains.sum() / losses.sum()

        logger.debug(f"Omega ratio calculated: {omega:.2f}")
        return float(omega)

    def calculate_tail_ratio(self, returns: pd.Series) -> float:
        """
        Calculate tail ratio (95th percentile / 5th percentile).

        Measures extreme performance - higher values indicate
        better extreme gains relative to extreme losses.

        Args:
            returns: Series of returns

        Returns:
            Tail ratio (higher is better)

        Formula:
            Tail Ratio = abs(95th percentile / 5th percentile)
        """
        if len(returns) < 20:
            logger.warning(f"Insufficient data for tail ratio: {len(returns)} returns (need >= 20)")
            return 0.0

        percentile_95 = returns.quantile(0.95)
        percentile_5 = returns.quantile(0.05)

        if abs(percentile_5) < 1e-10:
            logger.debug("5th percentile near zero - returning infinite tail ratio")
            return float('inf')

        tail_ratio = abs(percentile_95 / percentile_5)

        logger.debug(f"Tail ratio calculated: {tail_ratio:.2f}")
        return float(tail_ratio)

    def calculate_var(
        self,
        returns: pd.Series,
        confidence: float = 0.95,
        method: str = 'historical'
    ) -> float:
        """
        Calculate Value at Risk at given confidence level.

        Args:
            returns: Series of returns
            confidence: Confidence level (e.g., 0.95 for 95%)
            method: 'historical', 'parametric', or 'cornish_fisher'

        Returns:
            VaR as a positive number (e.g., 0.05 means 5% potential loss)

        Methods:
            - historical: Empirical quantile
            - parametric: Assumes normal distribution
            - cornish_fisher: Accounts for skewness and kurtosis
        """
        if len(returns) < 2:
            logger.warning(f"Insufficient data for VaR: {len(returns)} returns")
            return 0.0

        if method == 'historical':
            # Historical VaR
            var = -returns.quantile(1 - confidence)

        elif method == 'parametric':
            # Parametric VaR (assumes normal distribution)
            z_score = stats.norm.ppf(1 - confidence)
            var = -(returns.mean() + z_score * returns.std())

        elif method == 'cornish_fisher':
            # Cornish-Fisher VaR (accounts for skewness and kurtosis)
            z = stats.norm.ppf(1 - confidence)
            s = returns.skew()
            k = returns.kurtosis()

            # Cornish-Fisher expansion
            z_cf = (z +
                    (z**2 - 1) * s / 6 +
                    (z**3 - 3*z) * k / 24 -
                    (2*z**3 - 5*z) * s**2 / 36)

            var = -(returns.mean() + z_cf * returns.std())

        else:
            logger.error(f"Unknown VaR method: {method}")
            raise ValueError(f"Unknown VaR method: {method}. Use 'historical', 'parametric', or 'cornish_fisher'")

        var_result = max(var, 0.0)  # VaR should be non-negative

        logger.debug(f"VaR ({method}, {confidence:.0%}): {var_result:.4f}")
        return float(var_result)

    def calculate_cvar(
        self,
        returns: pd.Series,
        confidence: float = 0.95
    ) -> float:
        """
        Calculate Conditional Value at Risk (Expected Shortfall).

        Average loss in worst (1-confidence)% of cases.
        More conservative than VaR.

        Args:
            returns: Series of returns
            confidence: Confidence level

        Returns:
            CVaR as a positive number

        Formula:
            CVaR = Mean of returns below VaR threshold
        """
        if len(returns) < 2:
            logger.warning(f"Insufficient data for CVaR: {len(returns)} returns")
            return 0.0

        var = self.calculate_var(returns, confidence, method='historical')

        # Get returns worse than VaR threshold
        threshold = -var
        tail_losses = returns[returns < threshold]

        if len(tail_losses) == 0:
            logger.debug("No tail losses - CVaR equals VaR")
            return var

        cvar = -tail_losses.mean()

        logger.debug(f"CVaR ({confidence:.0%}): {cvar:.4f}")
        return float(cvar)

    def calculate_rolling_sharpe(
        self,
        returns: pd.Series,
        window: int = 252,
        periods: int = 252
    ) -> pd.Series:
        """
        Calculate rolling Sharpe ratio.

        Args:
            returns: Series of returns
            window: Rolling window size (default 252 = 1 year daily)
            periods: Periods per year for annualization

        Returns:
            Series of rolling Sharpe ratios
        """
        if len(returns) < window:
            logger.warning(f"Insufficient data for rolling Sharpe: {len(returns)} < {window}")
            return pd.Series(dtype=float)

        rolling_mean = returns.rolling(window).mean()
        rolling_std = returns.rolling(window).std()

        # Annualize
        annualized_return = rolling_mean * periods
        annualized_vol = rolling_std * np.sqrt(periods)

        # Avoid division by zero
        rolling_sharpe = annualized_return / annualized_vol.replace(0, np.nan)

        logger.debug(f"Rolling Sharpe calculated with window={window}")
        return rolling_sharpe

    def calculate_rolling_volatility(
        self,
        returns: pd.Series,
        window: int = 252,
        periods: int = 252
    ) -> pd.Series:
        """
        Calculate rolling annualized volatility.

        Args:
            returns: Series of returns
            window: Rolling window size
            periods: Periods per year for annualization

        Returns:
            Series of rolling volatility values
        """
        if len(returns) < window:
            logger.warning(f"Insufficient data for rolling volatility: {len(returns)} < {window}")
            return pd.Series(dtype=float)

        rolling_std = returns.rolling(window).std()
        rolling_vol = rolling_std * np.sqrt(periods)

        logger.debug(f"Rolling volatility calculated with window={window}")
        return rolling_vol

    def calculate_rolling_correlation(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series,
        window: int = 252
    ) -> pd.Series:
        """
        Calculate rolling correlation with benchmark.

        Args:
            returns: Strategy returns
            benchmark_returns: Benchmark returns
            window: Rolling window size

        Returns:
            Series of rolling correlation coefficients
        """
        if len(returns) < window or len(benchmark_returns) < window:
            logger.warning(f"Insufficient data for rolling correlation")
            return pd.Series(dtype=float)

        rolling_corr = returns.rolling(window).corr(benchmark_returns)

        logger.debug(f"Rolling correlation calculated with window={window}")
        return rolling_corr

    def calculate_rolling_beta(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series,
        window: int = 252
    ) -> pd.Series:
        """
        Calculate rolling beta relative to benchmark.

        Args:
            returns: Strategy returns
            benchmark_returns: Benchmark returns
            window: Rolling window size

        Returns:
            Series of rolling beta values

        Formula:
            Beta = Cov(returns, benchmark) / Var(benchmark)
        """
        if len(returns) < window or len(benchmark_returns) < window:
            logger.warning(f"Insufficient data for rolling beta")
            return pd.Series(dtype=float)

        # Calculate rolling covariance and variance
        rolling_cov = returns.rolling(window).cov(benchmark_returns)
        rolling_var = benchmark_returns.rolling(window).var()

        # Avoid division by zero
        rolling_beta = rolling_cov / rolling_var.replace(0, np.nan)

        logger.debug(f"Rolling beta calculated with window={window}")
        return rolling_beta

    def calculate_advanced_metrics(
        self,
        returns: pd.Series,
        benchmark_returns: Optional[pd.Series] = None
    ) -> Dict[str, Any]:
        """
        Calculate advanced risk and performance metrics.

        Args:
            returns: Strategy returns
            benchmark_returns: Optional benchmark for comparison

        Returns:
            Dictionary of advanced metrics including:
            - Sortino, Omega, Tail ratios
            - VaR and CVaR at multiple confidence levels
            - Distribution statistics (skewness, kurtosis)
            - Benchmark-relative metrics (if benchmark provided)
        """
        logger.info(f"Calculating advanced metrics for {len(returns)} returns")

        metrics = {
            # Downside risk metrics
            'sortino_ratio': self.calculate_sortino_ratio(returns),
            'omega_ratio': self.calculate_omega_ratio(returns),
            'tail_ratio': self.calculate_tail_ratio(returns),

            # Value at Risk
            'var_95_historical': self.calculate_var(returns, 0.95, 'historical'),
            'var_95_parametric': self.calculate_var(returns, 0.95, 'parametric'),
            'var_95_cornish_fisher': self.calculate_var(returns, 0.95, 'cornish_fisher'),
            'var_99_historical': self.calculate_var(returns, 0.99, 'historical'),
            'cvar_95': self.calculate_cvar(returns, 0.95),
            'cvar_99': self.calculate_cvar(returns, 0.99),

            # Distribution statistics
            'skewness': float(returns.skew()),
            'kurtosis': float(returns.kurtosis()),
        }

        # Add benchmark-relative metrics if provided
        if benchmark_returns is not None:
            logger.debug("Calculating benchmark-relative metrics")
            metrics.update({
                'correlation_to_benchmark': float(returns.corr(benchmark_returns)),
                'beta_to_benchmark': self._calculate_beta(returns, benchmark_returns),
                'alpha': self._calculate_alpha(returns, benchmark_returns),
            })

        logger.info("Advanced metrics calculation complete")
        return metrics

    def calculate_rolling_metrics(
        self,
        returns: pd.Series,
        window: int = 252
    ) -> pd.DataFrame:
        """
        Calculate rolling window metrics for time-series analysis.

        Args:
            returns: Strategy returns
            window: Rolling window size (default 252 days)

        Returns:
            DataFrame with rolling metrics over time including:
            - rolling_sharpe
            - rolling_volatility
            - rolling_max_dd
            - rolling_var_95
        """
        logger.info(f"Calculating rolling metrics with window={window}")

        rolling_df = pd.DataFrame({
            'rolling_sharpe': self.calculate_rolling_sharpe(returns, window),
            'rolling_volatility': self.calculate_rolling_volatility(returns, window),
            'rolling_max_dd': self._calculate_rolling_max_drawdown(returns, window),
            'rolling_var_95': returns.rolling(window).apply(
                lambda x: self.calculate_var(x, 0.95, 'historical')
            ),
        })

        logger.info("Rolling metrics calculation complete")
        return rolling_df

    def _calculate_beta(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series
    ) -> float:
        """
        Calculate beta relative to benchmark.

        Args:
            returns: Strategy returns
            benchmark_returns: Benchmark returns

        Returns:
            Beta value

        Formula:
            Beta = Cov(returns, benchmark) / Var(benchmark)
        """
        covariance = returns.cov(benchmark_returns)
        benchmark_variance = benchmark_returns.var()

        if benchmark_variance == 0:
            logger.warning("Benchmark variance is zero - cannot calculate beta")
            return 0.0

        beta = covariance / benchmark_variance
        logger.debug(f"Beta calculated: {beta:.2f}")
        return float(beta)

    def _calculate_alpha(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series,
        risk_free_rate: float = 0.0
    ) -> float:
        """
        Calculate alpha (excess return over CAPM expected return).

        Args:
            returns: Strategy returns
            benchmark_returns: Benchmark returns
            risk_free_rate: Annual risk-free rate

        Returns:
            Alpha value (annualized)

        Formula:
            Alpha = Return - (Risk_Free + Beta * (Benchmark_Return - Risk_Free))
        """
        beta = self._calculate_beta(returns, benchmark_returns)

        # Annualized returns
        avg_return = returns.mean() * 252
        avg_benchmark = benchmark_returns.mean() * 252

        expected_return = risk_free_rate + beta * (avg_benchmark - risk_free_rate)
        alpha = avg_return - expected_return

        logger.debug(f"Alpha calculated: {alpha:.4f}")
        return float(alpha)

    def _calculate_rolling_max_drawdown(
        self,
        returns: pd.Series,
        window: int
    ) -> pd.Series:
        """
        Calculate rolling maximum drawdown.

        Args:
            returns: Strategy returns
            window: Rolling window size

        Returns:
            Series of rolling maximum drawdown values
        """
        cumulative = (1 + returns).cumprod()
        rolling_max = cumulative.rolling(window, min_periods=1).max()
        drawdown = (cumulative - rolling_max) / rolling_max

        rolling_max_dd = drawdown.rolling(window).min()

        logger.debug(f"Rolling max drawdown calculated with window={window}")
        return rolling_max_dd

    def calculate_baseline(
        self,
        symbol: str,
        start_price: Decimal,
        end_price: Decimal,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate buy-and-hold baseline returns.

        Simulates buying 100% of initial capital in the given symbol at start_price
        and holding until end_date at end_price.

        Args:
            symbol: Baseline symbol (typically 'QQQ')
            start_price: Price at backtest start
            end_price: Price at backtest end
            start_date: Backtest start date
            end_date: Backtest end date

        Returns:
            Dict with baseline metrics:
                - baseline_symbol: str
                - baseline_final_value: float
                - baseline_total_return: float
                - baseline_annualized_return: float
            Returns None if calculation fails (invalid inputs)

        Raises:
            ValueError: If start_price or end_price <= 0
        """
        # 1. Validate inputs
        if start_price <= 0 or end_price <= 0:
            logger.warning(
                f"Invalid prices for baseline: start={start_price}, end={end_price}"
            )
            return None

        # 2. Calculate shares bought with 100% of capital
        shares_bought = self.initial_capital / start_price
        final_value = shares_bought * end_price

        # 3. Calculate total return
        total_return = float((final_value - self.initial_capital) / self.initial_capital)

        # 4. Calculate annualized return
        days = (end_date - start_date).days
        years = Decimal(days) / Decimal('365.25')

        if years < Decimal('0.01'):  # Less than ~4 days
            annualized_return = total_return  # Can't annualize
            logger.debug(
                f"Short period ({days} days) - returning total return as annualized"
            )
        else:
            # Annualized return = (1 + total_return)^(1/years) - 1
            annualized_return = float(
                (1 + Decimal(str(total_return))) ** (1 / years) - 1
            )

        logger.info(
            f"Baseline ({symbol}): {total_return:.2%} total, "
            f"{annualized_return:.2%} annualized over {days} days"
        )

        # 5. Return results
        return {
            'baseline_symbol': symbol,
            'baseline_final_value': float(final_value),
            'baseline_total_return': total_return,
            'baseline_annualized_return': annualized_return
        }

    def export_trades_to_csv(
        self,
        trade_logger: 'TradeLogger',
        strategy_name: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        Export trade log to CSV file with summary statistics footer.

        Converts TradeLogger records to DataFrame and exports to CSV with all
        required columns including dynamic indicators and thresholds.
        Appends summary statistics footer with performance metrics.

        Automatically generates filename with timestamp and strategy name if
        output_path is not provided: trades/{strategy_name}_{timestamp}.csv

        Args:
            trade_logger: TradeLogger instance with recorded trades
            strategy_name: Name of strategy (used in auto-generated filename)
            output_path: Optional path to output CSV file. If None, auto-generates
                        filename as: trades/{strategy_name}_{YYYY-MM-DD_HHMMSS}.csv

        Returns:
            Absolute path to created CSV file

        Raises:
            ValueError: If no trades to export
            IOError: If file cannot be written

        Example:
            from jutsu_engine.performance.trade_logger import TradeLogger

            trade_logger = TradeLogger(initial_capital=Decimal('10000'))
            # ... run backtest ...

            analyzer = PerformanceAnalyzer(fills, equity_curve, initial_capital)

            # Auto-generated filename
            csv_path = analyzer.export_trades_to_csv(trade_logger, 'ADX_Trend')
            # Result: trades/ADX_Trend_2025-11-06_143022.csv

            # Custom filename
            csv_path = analyzer.export_trades_to_csv(trade_logger, 'ADX_Trend', 'my_trades.csv')
            # Result: my_trades.csv
        """
        # Convert trade logger to DataFrame
        df = trade_logger.to_dataframe()

        if df.empty:
            raise ValueError("No trades to export - TradeLogger contains no records")

        # Auto-generate filename if not provided
        if output_path is None:
            timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
            output_path = f"trades/{strategy_name}_{timestamp}.csv"
            logger.info(f"Auto-generated CSV filename: {output_path}")

        # Resolve full path
        full_path = Path(output_path).resolve()

        # Ensure directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Export trades DataFrame to CSV
        try:
            df.to_csv(full_path, index=False)
        except IOError as e:
            logger.error(f"Failed to write CSV to {full_path}: {e}")
            raise

        # Calculate and append summary statistics footer
        try:
            self._append_summary_footer(full_path)
        except Exception as e:
            logger.warning(f"Failed to append summary footer to CSV: {e}")
            # Don't fail if footer append fails - trades are already exported

        logger.info(
            f"Exported {len(df)} trades to {full_path} "
            f"({len(df.columns)} columns) with summary footer"
        )

        return str(full_path)

    def _append_summary_footer(self, csv_path: Path) -> None:
        """
        Append summary statistics footer to CSV file.

        Adds a blank line separator followed by summary statistics including:
        - Initial Capital, Final Value, Total Return
        - Annualized Return, Sharpe Ratio, Max Drawdown
        - Total Trades, Win Rate

        Args:
            csv_path: Path to CSV file to append footer to

        Raises:
            IOError: If file cannot be opened or written
        """
        metrics = self.calculate_metrics()

        # Build summary lines
        summary_lines = [
            "",  # Blank line separator
            "Summary Statistics:",
            f"Initial Capital,${metrics['initial_capital']:,.2f}",
            f"Final Value,${metrics['final_value']:,.2f}",
            f"Total Return,{metrics['total_return']:.2%}",
            f"Annualized Return,{metrics['annualized_return']:.2%}",
            f"Sharpe Ratio,{metrics['sharpe_ratio']:.2f}",
            f"Max Drawdown,{metrics['max_drawdown']:.2%}",
            f"Total Trades,{metrics['total_trades']}",
            f"Win Rate,{metrics['win_rate']:.2%}",
        ]

        # Append to CSV
        with open(csv_path, 'a', newline='') as f:
            for line in summary_lines:
                f.write(line + '\n')

        logger.debug(f"Appended summary statistics footer to {csv_path}")
