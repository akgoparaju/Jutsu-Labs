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

from dataclasses import dataclass
from datetime import date

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
