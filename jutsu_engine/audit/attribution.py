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
    """Return the era label for a date, or 'unknown' if before the first era."""
    for era in ERAS:
        if era.start <= d <= era.end:
            return era.label
    return "unknown"


def _cell_from_regime(regime: str) -> int:
    """'Cell_4' -> 4."""
    return int(str(regime).split("_")[1])


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
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
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
    Returns one row per observed cell: cell, days, strategy_total_return,
    qqq_total_return, hit_rate (fraction of days with strategy return > 0),
    strategy_daily_avg.
    """
    df = ts.copy()
    df["cell"] = df["Regime"].map(_cell_from_regime)
    rows = []
    for cell, g in df.groupby("cell"):
        sr = g["Strategy_Daily_Return"].fillna(0.0)
        rows.append({
            "cell": int(cell),
            "days": int(len(g)),
            "strategy_total_return": _total_return(sr),
            "qqq_total_return": _total_return(g["QQQ_Daily_Return"]),
            "hit_rate": float((sr > 0).mean()) if len(sr) else 0.0,
            "strategy_daily_avg": float(sr.mean()) if len(sr) else 0.0,
        })
    return pd.DataFrame(rows).sort_values("cell").reset_index(drop=True)


def treasury_overlay_contribution(portfolio: pd.DataFrame) -> dict:
    """Isolate the Treasury-overlay (TMF/TMV) P&L in cells 4-6 vs a cash counterfactual.

    Expects portfolio CSV columns: Regime, TMF_Value, TMV_Value.
    Treasury overlay is active only in cells 4-6 (Hierarchical_Adaptive_v3_5b.py:876).

    Contribution = absolute change in the (TMF_Value + TMV_Value) sleeve across the
    cell-4-6 days. Cash counterfactual assumes that sleeve earned 0 over the same
    days, so contribution_vs_cash == treasury_pnl_abs here (a positive number means
    the overlay beat holding cash; negative means it cost money net of whipsaw).
    """
    df = portfolio.copy()
    df["cell"] = df["Regime"].map(_cell_from_regime)
    mask = df["cell"].isin([4, 5, 6])
    treas = df.loc[mask].copy()
    if treas.empty:
        return {"treasury_days": 0, "treasury_pnl_abs": 0.0, "contribution_vs_cash": 0.0}

    sleeve = treas.get("TMF_Value", 0.0).fillna(0.0) + treas.get("TMV_Value", 0.0).fillna(0.0)
    pnl_abs = float(sleeve.iloc[-1] - sleeve.iloc[0])
    return {
        "treasury_days": int(len(treas)),
        "treasury_pnl_abs": pnl_abs,
        # Cash counterfactual: same sleeve earning 0 -> contribution vs cash = pnl_abs.
        "contribution_vs_cash": pnl_abs,
    }
