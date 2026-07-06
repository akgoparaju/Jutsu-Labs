from datetime import date

import pandas as pd

from jutsu_engine.audit.attribution import (
    ERAS,
    assign_era,
    era_metrics,
    cell_attribution,
    treasury_overlay_contribution,
)


class TestEras:
    def test_eras_cover_expected_labels(self):
        """Verify that key era labels exist in the ERAS constant."""
        labels = [e.label for e in ERAS]
        assert "2020 (COVID)" in labels
        assert "2022 bear" in labels
        assert "2025-present" in labels

    def test_assign_era_boundaries(self):
        """Verify assign_era maps specific dates to the correct era label."""
        assert assign_era(date(2012, 6, 1)) == "2010-2014"
        assert assign_era(date(2020, 3, 15)) == "2020 (COVID)"
        assert assign_era(date(2022, 10, 1)) == "2022 bear"
        assert assign_era(date(2026, 7, 6)) == "2025-present"

    def test_assign_era_nat_is_unknown(self):
        """assign_era(pd.NaT) returns 'unknown' rather than raising."""
        assert assign_era(pd.NaT) == "unknown"


def _ts_df():
    # 4 days: 2 in cell 1, 2 in cell 4; simple returns.
    return pd.DataFrame({
        "Date": pd.to_datetime(
            ["2021-01-04", "2021-01-05", "2022-06-01", "2022-06-02"], utc=True),
        "Regime": ["Cell_1", "Cell_1", "Cell_4", "Cell_4"],
        "QQQ_Daily_Return": [0.01, -0.02, 0.00, 0.01],
        "Strategy_Daily_Return": [0.02, -0.01, 0.005, -0.03],
    })


class TestEraMetrics:
    def test_returns_one_row_per_populated_era_with_metrics(self):
        """era_metrics returns one row per populated era with strategy_total_return, sharpe, max_drawdown."""
        df = era_metrics(_ts_df())
        # 2021 and 2022 bear are the two populated eras.
        eras = set(df["era"])
        assert "2021" in eras and "2022 bear" in eras
        row = df[df["era"] == "2021"].iloc[0]
        # total strategy return for 2021 = (1.02)*(0.99)-1
        assert abs(row["strategy_total_return"] - ((1.02 * 0.99) - 1)) < 1e-9
        assert "sharpe" in df.columns and "max_drawdown" in df.columns


class TestCellAttribution:
    def test_buckets_pnl_by_cell(self):
        """cell_attribution returns one row per cell with correct days count, compounded and additive returns."""
        df = cell_attribution(_ts_df())
        cell1 = df[df["cell"] == 1].iloc[0]
        assert cell1["days"] == 2
        # cell 1 strategy compounded = (1.02)*(0.99)-1
        assert abs(cell1["strategy_compounded_return"] - ((1.02 * 0.99) - 1)) < 1e-9
        # additive (simple-return sum) column for cell 1 = 0.02 + (-0.01)
        assert abs(cell1["strategy_return_sum"] - (0.02 + (-0.01))) < 1e-9
        cell4 = df[df["cell"] == 4].iloc[0]
        assert cell4["days"] == 2


class TestTreasuryOverlayContribution:
    def test_cash_counterfactual_isolates_treasury(self):
        """Single defensive episode: within-episode diff of the TMF sleeve gives treasury_pnl_abs and contribution_vs_cash."""
        # Portfolio CSV: on cells 4-6 days, TMF held; measure treasury pnl vs
        # a cash counterfactual (0% return on that sleeve). Two consecutive days
        # = one episode; day-over-day diff = +300.
        port = pd.DataFrame({
            "Date": pd.to_datetime(["2022-06-01", "2022-06-02"], utc=True),
            "Regime": ["Cell_4", "Cell_4"],
            "Portfolio_Total_Value": [10000.0, 10200.0],
            "TMF_Value": [4000.0, 4300.0],  # +300 on the treasury sleeve
            "TMV_Value": [0.0, 0.0],
        })
        res = treasury_overlay_contribution(port)
        # Treasury sleeve grew from 4000 to 4300 => +300 absolute contribution.
        assert abs(res["treasury_pnl_abs"] - 300.0) < 1e-6
        assert res["treasury_days"] == 2
        # Cash counterfactual for the same sleeve = 0 growth => contribution vs cash = +300.
        assert abs(res["contribution_vs_cash"] - 300.0) < 1e-6

    def test_treasury_multi_episode_excludes_allocation_flows(self):
        """Two defensive episodes separated by >7 days: cross-episode value jump is an allocation flow, excluded (pnl == 100, not 800)."""
        # Episode A: 4000 -> 4300 (+300). Gap > 7 days. Episode B re-entry: 5000 -> 4800 (-200).
        # True within-episode P&L = +300 - 200 = +100. Last-minus-first would be 4800-4000 = +800.
        port = pd.DataFrame({
            "Date": pd.to_datetime(
                ["2022-06-01", "2022-06-02", "2022-06-15", "2022-06-16"], utc=True),
            "Regime": ["Cell_4", "Cell_4", "Cell_5", "Cell_5"],
            "TMF_Value": [4000.0, 4300.0, 5000.0, 4800.0],
            "TMV_Value": [0.0, 0.0, 0.0, 0.0],
        })
        res = treasury_overlay_contribution(port)
        assert abs(res["treasury_pnl_abs"] - 100.0) < 1e-6
        assert abs(res["contribution_vs_cash"] - 100.0) < 1e-6
        assert res["treasury_days"] == 4

    def test_treasury_missing_tmv_column_is_safe(self):
        """Portfolio without a TMV_Value column (never-held ticker omitted by exporter) works, using TMF alone."""
        port = pd.DataFrame({
            "Date": pd.to_datetime(["2022-06-01", "2022-06-02"], utc=True),
            "Regime": ["Cell_4", "Cell_4"],
            "TMF_Value": [4000.0, 4300.0],  # no TMV_Value column at all
        })
        res = treasury_overlay_contribution(port)
        assert abs(res["treasury_pnl_abs"] - 300.0) < 1e-6
        assert res["treasury_days"] == 2

    def test_empty_regime_rows_are_ignored(self):
        """An empty-string Regime row among defensive rows is masked out (no crash, excluded from treasury_days)."""
        port = pd.DataFrame({
            "Date": pd.to_datetime(
                ["2022-06-01", "2022-06-02", "2022-06-03"], utc=True),
            "Regime": ["Cell_4", "", "Cell_4"],  # empty-string regime -> cell -1 -> excluded
            "TMF_Value": [4000.0, 9999.0, 4300.0],
            "TMV_Value": [0.0, 0.0, 0.0],
        })
        res = treasury_overlay_contribution(port)
        # Only the two Cell_4 rows count: one episode, diff = +300.
        assert res["treasury_days"] == 2
        assert abs(res["treasury_pnl_abs"] - 300.0) < 1e-6
