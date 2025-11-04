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
from typing import List, Dict, Tuple
import pandas as pd
import numpy as np

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
