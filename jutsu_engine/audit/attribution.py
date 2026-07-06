"""Module 4 — Era and cell attribution (spec §8).

Consumes artifacts that BacktestRunner already emits:
  - regime timeseries CSV (regime_analyzer.py:192-222): columns
    Date, Regime ('Cell_N'), Trend, Vol, QQQ_Daily_Return, Strategy_Daily_Return.
  - portfolio CSV (portfolio_exporter.py): Date, Regime, Portfolio_Total_Value,
    per-ticker TMF_Value / TMV_Value (Treasury overlay lives in cells 4-6 only).

Pure analysis functions here (era/cell/treasury) are unit-tested on synthetic
DataFrames. Task 6 adds the backtest driver that produces the real CSVs.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Era:
    label: str
    start: date
    end: date  # inclusive


# Era slices from spec §8. 2025-present end-bounded far in the future.
ERAS: list[Era] = [
    Era("2010-2014", date(2010, 1, 1), date(2014, 12, 31)),
    Era("2015-2019", date(2015, 1, 1), date(2019, 12, 31)),
    Era("2020 (COVID)", date(2020, 1, 1), date(2020, 12, 31)),
    Era("2021", date(2021, 1, 1), date(2021, 12, 31)),
    Era("2022 bear", date(2022, 1, 1), date(2022, 12, 31)),
    Era("2023-2024 bull", date(2023, 1, 1), date(2024, 12, 31)),
    Era("2025-present", date(2025, 1, 1), date(2100, 12, 31)),
]


def assign_era(d: date) -> str:
    """Return the era label for a date, or 'unknown' if before the first era or NaT."""
    if pd.isna(d):
        return "unknown"
    for era in ERAS:
        if era.start <= d <= era.end:
            return era.label
    return "unknown"


def _cell_from_regime(regime) -> int:
    """'Cell_4' -> 4; return -1 for unparseable regimes (empty string, None, malformed).

    Portfolio/regime CSVs can carry empty-string Regime rows (missing regime data,
    portfolio_exporter.py:459). Consumers mask out cell == -1 rather than crashing.
    """
    try:
        return int(str(regime).split("_")[1])
    except (IndexError, ValueError):
        return -1


def _sharpe(returns: pd.Series, periods: int = 252) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods))


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    equity = (1.0 + r).cumprod()
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min()) if len(dd) else 0.0


def _total_return(returns: pd.Series) -> float:
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def era_metrics(ts: pd.DataFrame) -> pd.DataFrame:
    """Per-era metrics from a regime timeseries DataFrame.

    Expects columns: Date, QQQ_Daily_Return, Strategy_Daily_Return.
    Returns one row per populated era: era, days, strategy_total_return,
    qqq_total_return, alpha_total, sharpe, max_drawdown.
    """
    df = ts.copy()
    # Bucket by ET trading date (matches the exporter's _get_trading_date convention).
    df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.tz_convert("America/New_York")
    df["era"] = df["Date"].dt.date.map(assign_era)

    rows = []
    for era_label, g in df.groupby("era", sort=False):
        strat_tot = _total_return(g["Strategy_Daily_Return"])
        qqq_tot = _total_return(g["QQQ_Daily_Return"])
        rows.append({
            "era": era_label,
            "days": int(len(g)),
            "strategy_total_return": strat_tot,
            "qqq_total_return": qqq_tot,
            "alpha_total": strat_tot - qqq_tot,
            "sharpe": _sharpe(g["Strategy_Daily_Return"]),
            "max_drawdown": _max_drawdown(g["Strategy_Daily_Return"]),
        })
    out = pd.DataFrame(rows)
    # Order by era definition for stable reports.
    order = {e.label: i for i, e in enumerate(ERAS)}
    out["_o"] = out["era"].map(lambda x: order.get(x, 999))
    return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)


def cell_attribution(ts: pd.DataFrame) -> pd.DataFrame:
    """Per-cell P&L attribution (cells 1-6) from a regime timeseries DataFrame.

    Expects columns: Regime ('Cell_N'), QQQ_Daily_Return, Strategy_Daily_Return.
    Returns one row per observed cell: cell, days, strategy_compounded_return,
    qqq_compounded_return, strategy_return_sum, hit_rate (fraction of days with
    strategy return > 0), strategy_daily_avg.

    strategy_compounded_return / qqq_compounded_return are prod(1+r)-1 compounded
    over the cell's (non-contiguous) days — a per-regime QUALITY measure, NOT
    additive across cells, and NOT a portfolio contribution. Use strategy_return_sum
    (simple-return sum) for an ~additive contribution comparison across cells.

    Rows with an unparseable Regime (cell == -1, e.g. empty-string Regime) are
    excluded (M2).
    """
    df = ts.copy()
    df["cell"] = df["Regime"].map(_cell_from_regime)
    df = df[df["cell"] != -1]
    rows = []
    for cell, g in df.groupby("cell"):
        sr = g["Strategy_Daily_Return"].fillna(0.0)
        rows.append({
            "cell": int(cell),
            "days": int(len(g)),
            "strategy_compounded_return": _total_return(sr),
            "qqq_compounded_return": _total_return(g["QQQ_Daily_Return"]),
            "strategy_return_sum": float(sr.sum()),
            "hit_rate": float((sr > 0).mean()) if len(sr) else 0.0,
            "strategy_daily_avg": float(sr.mean()) if len(sr) else 0.0,
        })
    return pd.DataFrame(rows).sort_values("cell").reset_index(drop=True)


def treasury_overlay_contribution(portfolio: pd.DataFrame) -> dict:
    """Approximate Treasury-overlay (TMF/TMV) P&L in cells 4-6 vs a cash counterfactual.

    Sums WITHIN-EPISODE day-over-day changes of the (TMF_Value + TMV_Value) sleeve.
    Defensive periods are non-contiguous episodes (the sleeve is sold to 0 outside
    cells 4-6, Hierarchical_Adaptive_v3_5b.py:873-876); cross-episode value jumps are
    allocation flows, NOT returns, and are excluded. Episode boundary = calendar gap
    > 7 days between consecutive defensive-cell rows. Entry days contribute no diff.

    Caveat (report must carry this label): position-value based — a mid-episode
    rebalance into/out of the sleeve while staying in cells 4-6 contaminates the
    diff. Exact isolation would require bond prices x held shares.
    """
    df = portfolio.copy()
    df["cell"] = df["Regime"].map(_cell_from_regime)
    df = df[df["cell"].isin([4, 5, 6])].copy()
    if df.empty:
        return {"treasury_days": 0, "treasury_pnl_abs": 0.0, "contribution_vs_cash": 0.0}

    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    df = df.sort_values("Date")
    tmf = df["TMF_Value"] if "TMF_Value" in df.columns else pd.Series(0.0, index=df.index)
    tmv = df["TMV_Value"] if "TMV_Value" in df.columns else pd.Series(0.0, index=df.index)
    sleeve = tmf.fillna(0.0) + tmv.fillna(0.0)

    episode = (df["Date"].diff() > pd.Timedelta(days=7)).cumsum()
    pnl = float(sleeve.groupby(episode.values).diff().dropna().sum())

    return {"treasury_days": int(len(df)), "treasury_pnl_abs": pnl,
            "contribution_vs_cash": pnl}


def build_strategy_instance(strategy_id: str):
    """Instantiate a live strategy from its exact live YAML config.

    Reuses LiveStrategyRunner's config->strategy mapping (strategy_runner.py:
    _initialize_strategy), which reads config['strategy']['parameters'], drops
    EXCLUDED_PARAMS, converts floats to Decimal, and calls strategy_class(**params)
    then strategy.init(). Returning runner.strategy guarantees the audit backtest
    uses the identical parameters the live deployment uses.
    """
    from jutsu_engine.audit.config import resolve_strategy
    from jutsu_engine.live.strategy_runner import LiveStrategyRunner

    spec = resolve_strategy(strategy_id)
    mod = importlib.import_module(spec.module_path)
    strategy_class = getattr(mod, spec.class_name)
    runner = LiveStrategyRunner(strategy_class=strategy_class, config_path=spec.config_path)
    return runner.strategy


def _all_symbols(strategy_id: str) -> list[str]:
    """All trading symbols the strategy touches (signal, leveraged, hedge, bonds)."""
    from jutsu_engine.audit.config import resolve_strategy
    from jutsu_engine.live.strategy_runner import LiveStrategyRunner

    spec = resolve_strategy(strategy_id)
    mod = importlib.import_module(spec.module_path)
    strategy_class = getattr(mod, spec.class_name)
    runner = LiveStrategyRunner(strategy_class=strategy_class, config_path=spec.config_path)
    return runner.get_all_symbols()


@dataclass
class AttributionResult:
    """Everything the report needs for one strategy's era/cell attribution."""
    strategy_id: str
    metrics: dict            # headline backtest metrics (sharpe, max_drawdown, ...)
    era_table: pd.DataFrame
    cell_table: pd.DataFrame
    treasury: dict
    regime_timeseries_csv: str
    portfolio_csv: str


def run_attribution(strategy_id: str, start=None, end=None,
                    initial_capital: Decimal = Decimal("10000"),
                    output_dir: str = "output") -> AttributionResult:
    """Run one full-period backtest and produce era + cell + treasury attribution.

    Reuses BacktestRunner (backtest_runner.py:66-102,284-331). The Hierarchical
    strategy exposes get_current_regime, so BacktestRunner emits the regime
    timeseries CSV and portfolio CSV that the pure functions consume.
    """
    from jutsu_engine.application.backtest_runner import BacktestRunner
    from jutsu_engine.audit.config import ATTRIBUTION_START

    start = start or ATTRIBUTION_START
    end = end or date.today()

    config = {
        "symbols": _all_symbols(strategy_id),
        "timeframe": "1D",
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end_date": datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        "initial_capital": initial_capital,
    }
    strategy = build_strategy_instance(strategy_id)

    runner = BacktestRunner(config)
    results = runner.run(strategy, output_dir=output_dir)

    ts_csv = results.get("regime_timeseries_csv")
    port_csv = results.get("portfolio_csv_path")
    if not ts_csv or not Path(ts_csv).exists():
        raise RuntimeError(
            "Backtest did not emit a regime timeseries CSV; cannot attribute by cell. "
            "Confirm the strategy exposes get_current_regime."
        )

    ts = pd.read_csv(ts_csv)
    era_table = era_metrics(ts)
    cell_table = cell_attribution(ts)

    treasury = {"treasury_days": 0, "treasury_pnl_abs": 0.0, "contribution_vs_cash": 0.0}
    if port_csv and Path(port_csv).exists():
        port = pd.read_csv(port_csv)
        if "Regime" in port.columns:
            treasury = treasury_overlay_contribution(port)

    metrics = {
        "sharpe_ratio": results.get("sharpe_ratio"),
        "max_drawdown": results.get("max_drawdown"),
        "annualized_return": results.get("annualized_return"),
        "total_return": results.get("total_return"),
        "final_value": results.get("final_value"),
        "alpha_vs_qqq": (results.get("baseline") or {}).get("alpha"),
    }

    return AttributionResult(
        strategy_id=strategy_id,
        metrics=metrics,
        era_table=era_table,
        cell_table=cell_table,
        treasury=treasury,
        regime_timeseries_csv=str(ts_csv),
        portfolio_csv=str(port_csv) if port_csv else "",
    )
