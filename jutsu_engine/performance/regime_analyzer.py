"""
Regime Performance Analyzer

Tracks regime-specific performance for strategies with discrete market regime grids.
Specifically designed for Hierarchical_Adaptive_v3_5b strategy with 3×2 regime matrix.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
import pandas as pd

logger = logging.getLogger('INFRA.PERFORMANCE.REGIME')


@dataclass
class RegimeBar:
    """Single bar with regime classification."""
    timestamp: datetime
    regime_cell: int  # 1-6
    trend_state: str  # BullStrong, Sideways, BearStrong
    vol_state: str  # Low, High
    qqq_close: Decimal
    qqq_return: Decimal
    portfolio_value: Decimal
    strategy_return: Decimal


class RegimePerformanceAnalyzer:
    """
    Analyze strategy performance across different market regimes.

    Designed for strategies with discrete regime grids (e.g., Trend × Volatility).
    Tracks days in regime, returns (QQQ vs strategy), and normalized metrics.

    Usage:
        analyzer = RegimePerformanceAnalyzer(initial_capital=Decimal('100000'))

        # During backtest (called after each bar)
        analyzer.record_bar(
            timestamp=bar.timestamp,
            regime_cell=strategy.get_current_regime()[2],  # cell_id
            trend_state=strategy.get_current_regime()[0],  # trend_state
            vol_state=strategy.get_current_regime()[1],    # vol_state
            qqq_close=qqq_bar.close,
            portfolio_value=portfolio.get_portfolio_value()
        )

        # After backtest
        summary_path, timeseries_path = analyzer.export_csv(
            strategy_name='Hierarchical_Adaptive_v3_5b',
            start_date=backtest_start,
            end_date=backtest_end
        )
    """

    def __init__(self, initial_capital: Decimal):
        """
        Initialize regime performance analyzer.

        Args:
            initial_capital: Starting portfolio value
        """
        self._initial_capital = initial_capital
        self._bars: List[RegimeBar] = []
        self._last_qqq_close: Optional[Decimal] = None
        self._last_portfolio_value: Optional[Decimal] = None

        logger.info(f"RegimePerformanceAnalyzer initialized with capital={initial_capital}")

    def record_bar(
        self,
        timestamp: datetime,
        regime_cell: int,
        trend_state: str,
        vol_state: str,
        qqq_close: Decimal,
        portfolio_value: Decimal
    ):
        """
        Record a single bar with regime classification.

        Args:
            timestamp: Bar timestamp
            regime_cell: Regime cell ID (1-6)
            trend_state: Trend classification (BullStrong, Sideways, BearStrong)
            vol_state: Volatility classification (Low, High)
            qqq_close: QQQ closing price
            portfolio_value: Portfolio value at bar close
        """
        # Calculate returns
        if self._last_qqq_close is None:
            qqq_return = Decimal('0')
            strategy_return = Decimal('0')
        else:
            qqq_return = (qqq_close - self._last_qqq_close) / self._last_qqq_close
            strategy_return = (portfolio_value - self._last_portfolio_value) / self._last_portfolio_value

        # Record bar
        bar = RegimeBar(
            timestamp=timestamp,
            regime_cell=regime_cell,
            trend_state=trend_state,
            vol_state=vol_state,
            qqq_close=qqq_close,
            qqq_return=qqq_return,
            portfolio_value=portfolio_value,
            strategy_return=strategy_return
        )
        self._bars.append(bar)

        # Update state
        self._last_qqq_close = qqq_close
        self._last_portfolio_value = portfolio_value

    def generate_summary(self) -> pd.DataFrame:
        """
        Generate regime summary matrix.

        Calculates aggregate performance metrics for each of the 6 regime cells:
        - Days in regime (exposure tracking)
        - Total returns (cumulative)
        - Daily average returns (normalized for regime comparison)
        - Annualized returns (252 trading days)

        Returns:
            DataFrame with columns: Regime, Trend, Vol, Days, QQQ_Total_Return,
            QQQ_Daily_Avg, QQQ_Annualized, Strategy_Total_Return, Strategy_Daily_Avg,
            Strategy_Annualized
        """
        if len(self._bars) == 0:
            logger.warning("No bars recorded - returning empty summary")
            return pd.DataFrame()

        # Group by regime
        df = pd.DataFrame([vars(bar) for bar in self._bars])
        summary_data = []

        for cell in range(1, 7):
            cell_bars = df[df['regime_cell'] == cell]

            if len(cell_bars) == 0:
                # No bars in this regime
                summary_data.append({
                    'Regime': f'Cell_{cell}',
                    'Trend': self._get_trend_for_cell(cell),
                    'Vol': self._get_vol_for_cell(cell),
                    'Days': 0,
                    'QQQ_Total_Return': 0.0,
                    'QQQ_Daily_Avg': 0.0,
                    'QQQ_Annualized': 0.0,
                    'Strategy_Total_Return': 0.0,
                    'Strategy_Daily_Avg': 0.0,
                    'Strategy_Annualized': 0.0
                })
                continue

            # Calculate metrics
            days = len(cell_bars)
            qqq_total = float((cell_bars['qqq_return'] + 1).prod() - 1)
            strat_total = float((cell_bars['strategy_return'] + 1).prod() - 1)

            # Daily average (normalized)
            qqq_daily_avg = qqq_total / days if days > 0 else 0.0
            strat_daily_avg = strat_total / days if days > 0 else 0.0

            # Annualized (252 trading days)
            qqq_annualized = qqq_daily_avg * 252
            strat_annualized = strat_daily_avg * 252

            summary_data.append({
                'Regime': f'Cell_{cell}',
                'Trend': cell_bars.iloc[0]['trend_state'],
                'Vol': cell_bars.iloc[0]['vol_state'],
                'Days': days,
                'QQQ_Total_Return': round(qqq_total, 4),
                'QQQ_Daily_Avg': round(qqq_daily_avg, 6),
                'QQQ_Annualized': round(qqq_annualized, 4),
                'Strategy_Total_Return': round(strat_total, 4),
                'Strategy_Daily_Avg': round(strat_daily_avg, 6),
                'Strategy_Annualized': round(strat_annualized, 4)
            })

        summary_df = pd.DataFrame(summary_data)
        logger.info(f"Generated regime summary: {len(summary_df)} regimes, {len(self._bars)} total bars")

        return summary_df

    def generate_timeseries(self) -> pd.DataFrame:
        """
        Generate daily time series with regime classification.

        Provides bar-by-bar record of regime state and returns for detailed analysis.

        Returns:
            DataFrame with columns: Date, Regime, Trend, Vol, QQQ_Close,
            QQQ_Daily_Return, Portfolio_Value, Strategy_Daily_Return
        """
        if len(self._bars) == 0:
            logger.warning("No bars recorded - returning empty timeseries")
            return pd.DataFrame()

        timeseries_data = []
        for bar in self._bars:
            timeseries_data.append({
                'Date': bar.timestamp,
                'Regime': f'Cell_{bar.regime_cell}',
                'Trend': bar.trend_state,
                'Vol': bar.vol_state,
                'QQQ_Close': float(bar.qqq_close),
                'QQQ_Daily_Return': float(bar.qqq_return),
                'Portfolio_Value': float(bar.portfolio_value),
                'Strategy_Daily_Return': float(bar.strategy_return)
            })

        timeseries_df = pd.DataFrame(timeseries_data)
        logger.info(f"Generated regime timeseries: {len(timeseries_df)} bars")

        return timeseries_df

    def export_csv(
        self,
        strategy_name: str,
        start_date: datetime,
        end_date: datetime,
        output_dir: str = 'results/regime_analysis'
    ) -> Tuple[str, str]:
        """
        Export regime analysis to CSV files.

        Creates two CSV files:
        1. Summary: Aggregate metrics per regime (6 rows, one per cell)
        2. Timeseries: Daily bar-by-bar data with regime classification

        Args:
            strategy_name: Name of strategy (for filename)
            start_date: Backtest start date
            end_date: Backtest end date
            output_dir: Output directory path (default: results/regime_analysis)

        Returns:
            Tuple of (summary_path, timeseries_path)
        """
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate filenames
        date_range = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        summary_filename = f"regime_summary_v3_5b_{strategy_name}_{date_range}.csv"
        timeseries_filename = f"regime_timeseries_v3_5b_{strategy_name}_{date_range}.csv"

        summary_path = output_path / summary_filename
        timeseries_path = output_path / timeseries_filename

        # Generate and export summary
        summary_df = self.generate_summary()
        summary_df.to_csv(summary_path, index=False)
        logger.info(f"Exported regime summary to {summary_path} ({len(summary_df)} regimes)")

        # Generate and export timeseries
        timeseries_df = self.generate_timeseries()
        timeseries_df.to_csv(timeseries_path, index=False)
        logger.info(f"Exported regime timeseries to {timeseries_path} ({len(timeseries_df)} bars)")

        return (str(summary_path), str(timeseries_path))

    @staticmethod
    def _get_trend_for_cell(cell: int) -> str:
        """Get trend state for regime cell."""
        if cell in [1, 2]:
            return "BullStrong"
        elif cell in [3, 4]:
            return "Sideways"
        else:  # cell in [5, 6]
            return "BearStrong"

    @staticmethod
    def _get_vol_for_cell(cell: int) -> str:
        """Get volatility state for regime cell."""
        if cell in [1, 3, 5]:
            return "Low"
        else:  # cell in [2, 4, 6]
            return "High"
