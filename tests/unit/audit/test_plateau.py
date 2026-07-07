# tests/unit/audit/test_plateau.py
import json
import math
from pathlib import Path

import pytest

from jutsu_engine.audit.plateau import (
    PERTURBABLE_EXCLUDE,
    load_golden_params,
    perturbable_params,
)


class TestPerturbableParams:
    def test_perturbable_params_from_golden_dict(self):
        """perturbable_params keeps numeric non-bool keys and drops strings/bools/infra."""
        golden = {
            "sma_fast": 40, "t_norm_bear_thresh": -0.3, "measurement_noise": 3000.0,
            "allow_treasury": True, "use_inverse_hedge": False,
            "execution_time": "15min_after_open", "signal_symbol": "QQQ",
            "leveraged_long_symbol": "TQQQ",
        }
        p = perturbable_params(golden)
        assert set(p) == {"sma_fast", "t_norm_bear_thresh", "measurement_noise"}

    def test_bool_is_not_treated_as_numeric(self):
        """Booleans are excluded even though bool is a subclass of int in Python."""
        assert "allow_treasury" not in perturbable_params({"allow_treasury": True})

    def test_exclude_set_lists_infra_string_keys(self):
        """PERTURBABLE_EXCLUDE names the infra/symbol keys so they never perturb."""
        assert "execution_time" in PERTURBABLE_EXCLUDE
        assert "signal_symbol" in PERTURBABLE_EXCLUDE
        assert "treasury_trend_symbol" in PERTURBABLE_EXCLUDE

    def test_load_golden_params_reads_live_yaml(self):
        """load_golden_params reads the real v3_5b live YAML (no DB); golden spot-checks hold."""
        golden = load_golden_params("v3_5b")
        assert golden["sma_fast"] == 40
        assert golden["sma_slow"] == 140
        assert golden["t_norm_bear_thresh"] == -0.3
        # perturbable set is exactly the 22 numeric params (symbols/bools/exec excluded)
        assert len(perturbable_params(golden)) == 22


from jutsu_engine.audit.plateau import (
    OAT_MULTIPLIERS,
    oat_samples,
    params_hash,
    _apply_validity,
)


class TestOATSamples:
    def test_multipliers_are_the_spec_steps(self):
        """OAT multipliers are x0.8, x0.9, x1.1, x1.2 (spec §6 +/-10% and +/-20%)."""
        assert OAT_MULTIPLIERS == (0.8, 0.9, 1.1, 1.2)

    def test_float_param_produces_four_multiplied_variants(self):
        """A float param yields one sample per multiplier, each overriding just that key."""
        golden = {"leverage_scalar": 1.0, "sma_fast": 40}
        samples = [s for s in oat_samples(golden) if s["param"] == "leverage_scalar"]
        overrides = sorted(s["overrides"]["leverage_scalar"] for s in samples)
        assert overrides == [0.8, 0.9, 1.1, 1.2]
        # each OAT sample overrides exactly one parameter
        assert all(list(s["overrides"]) == ["leverage_scalar"] for s in samples)

    def test_negative_threshold_preserves_sign(self):
        """Multiplicative perturbation of t_norm_bear_thresh (-0.3) keeps it negative."""
        golden = {"t_norm_bear_thresh": -0.3}
        vals = [s["overrides"]["t_norm_bear_thresh"] for s in oat_samples(golden)]
        assert all(v < 0 for v in vals)
        # x0.8 of -0.3 = -0.24 (closer to zero), x1.2 = -0.36 (further)
        assert min(vals) == pytest.approx(-0.36)
        assert max(vals) == pytest.approx(-0.24)

    def test_integer_param_is_rounded_and_deduped(self):
        """Integer window is rounded; multipliers that round to the golden value are dropped."""
        # sma_fast=5: x0.8=4, x0.9=4->clamped to 5 floor? 4<5 -> raised to 5 == golden -> dropped;
        # use sma_fast=40 for a clean rounding case instead.
        golden = {"sma_fast": 40}
        vals = sorted(s["overrides"]["sma_fast"] for s in oat_samples(golden))
        # 32, 36, 44, 48 — all ints, all != 40, all >= 5 window floor
        assert vals == [32, 36, 44, 48]
        assert all(isinstance(v, int) for v in vals)

    def test_integer_rounding_collapse_is_deduped(self):
        """When x0.9/x1.1 round back to the golden int, those samples are dropped."""
        # osc_smoothness=5 (period, floor 2): x0.9=4.5->4? round(4.5)=4 (banker's? use int floor rules below)
        golden = {"osc_smoothness": 10}
        vals = sorted(s["overrides"]["osc_smoothness"] for s in oat_samples(golden))
        # 8, 9, 11, 12 — none collapse to 10
        assert 10 not in vals
        assert vals == [8, 9, 11, 12]

    def test_window_validity_floor_applied(self):
        """A tiny window whose x0.8 falls below the floor is clamped, then deduped vs golden."""
        golden = {"sma_fast": 6}  # window floor 5
        vals = sorted(s["overrides"]["sma_fast"] for s in oat_samples(golden))
        # x0.8=4.8->5 (floor), x0.9=5.4->5, x1.1=6.6->7, x1.2=7.2->7
        # 5 (deduped), 7 (deduped) -> {5, 7}; golden 6 dropped
        assert vals == [5, 7]


class TestParamsHash:
    def test_hash_is_stable_and_order_independent(self):
        """params_hash is deterministic and independent of dict insertion order."""
        a = params_hash({"sma_fast": 40, "sma_slow": 140})
        b = params_hash({"sma_slow": 140, "sma_fast": 40})
        assert a == b and len(a) == 16

    def test_hash_differs_on_value_change(self):
        """A changed value changes the hash."""
        assert params_hash({"sma_fast": 40}) != params_hash({"sma_fast": 41})


from jutsu_engine.audit.plateau import JOINT_BOX_FRACTION, joint_samples


class TestJointSamples:
    def test_default_count_and_seed_reproducibility(self):
        """joint_samples(N, seed) yields N reproducible samples for a fixed seed."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0, "signal_symbol": "QQQ"}
        a = joint_samples(golden, n=10, seed=7)
        b = joint_samples(golden, n=10, seed=7)
        assert len(a) == 10
        assert [s["overrides"] for s in a] == [s["overrides"] for s in b]

    def test_different_seed_gives_different_samples(self):
        """A different seed produces a different sample sequence."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0}
        a = joint_samples(golden, n=10, seed=1)
        b = joint_samples(golden, n=10, seed=2)
        assert [s["overrides"] for s in a] != [s["overrides"] for s in b]

    def test_every_sample_perturbs_all_params_within_box(self):
        """Each joint sample perturbs every perturbable param within +/-15% (integers rounded)."""
        golden = {"leverage_scalar": 1.0, "sma_fast": 40, "signal_symbol": "QQQ"}
        s = joint_samples(golden, n=50, seed=3)[0]
        assert set(s["overrides"]) == {"leverage_scalar", "sma_fast"}
        lo, hi = 1.0 * (1 - JOINT_BOX_FRACTION), 1.0 * (1 + JOINT_BOX_FRACTION)
        assert lo <= s["overrides"]["leverage_scalar"] <= hi
        assert isinstance(s["overrides"]["sma_fast"], int)

    def test_negative_param_stays_negative_in_box(self):
        """A negative threshold stays negative across the whole +/-15% box."""
        golden = {"t_norm_bear_thresh": -0.3}
        samples = joint_samples(golden, n=100, seed=5)
        assert all(s["overrides"]["t_norm_bear_thresh"] < 0 for s in samples)

    def test_sample_kind_and_hash_present(self):
        """Joint samples are tagged kind='joint' and carry a params hash."""
        s = joint_samples({"sma_fast": 40}, n=1, seed=9)[0]
        assert s["kind"] == "joint"
        assert len(s["hash"]) == 16


from jutsu_engine.audit.plateau import (
    CLIFF_LOSS_FRACTION,
    cliff_list,
    degradation_table,
    joint_stats,
    plateau_score,
)


def _oat_row(param, override_val, sharpe):
    ov = {param: override_val}
    return {"hash": params_hash(ov), "kind": "oat", "param": param,
            "overrides": ov, "sharpe": sharpe, "max_drawdown": -0.2,
            "annualized_return": 0.1, "total_return": 1.0}


class TestPlateauScore:
    def test_mean_retained_sharpe_fraction_at_20pct(self):
        """plateau_score returns dict with mean_retained = mean(perturbed/golden) over +/-20% rows."""
        golden = {"sma_fast": 40}
        golden_sharpe = 1.0
        # x0.8 -> sma 32 retains 0.9; x1.2 -> sma 48 retains 0.7; +/-10% ignored for the score
        rows = [
            _oat_row("sma_fast", 32, 0.9),
            _oat_row("sma_fast", 36, 0.95),  # x0.9, ignored by the +/-20% score
            _oat_row("sma_fast", 44, 0.99),  # x1.1, ignored
            _oat_row("sma_fast", 48, 0.7),
        ]
        result = plateau_score(rows, golden, golden_sharpe, "sma_fast")
        assert result["mean_retained"] == pytest.approx((0.9 + 0.7) / 2)
        assert result["worst_retained"] == pytest.approx(0.7)
        assert result["n_rows"] == 2

    def test_missing_rows_return_nan(self):
        """A parameter with no +/-20% rows collected yields NaN (not a crash)."""
        result = plateau_score([], {"sma_fast": 40}, 1.0, "sma_fast")
        assert math.isnan(result["mean_retained"])
        assert math.isnan(result["worst_retained"])
        assert result["n_rows"] == 0

    def test_plateau_score_worst_retained_exposes_one_sided_collapse(self):
        """worst_retained catches a one-sided collapse that mean_retained would mask."""
        # sides 1.25 and 0.125 -> mean 0.688 (looks ok), worst 0.125 (clearly bad)
        golden = {"sma_fast": 40}
        rows = [
            _oat_row("sma_fast", 32, 1.25),  # x0.8 side: good
            _oat_row("sma_fast", 48, 0.125),  # x1.2 side: collapse
        ]
        result = plateau_score(rows, golden, 1.0, "sma_fast")
        assert result["mean_retained"] == pytest.approx((1.25 + 0.125) / 2)
        assert result["worst_retained"] == pytest.approx(0.125)
        assert result["n_rows"] == 2


class TestDegradationTable:
    def test_one_row_per_param_step_with_retained_fraction(self):
        """degradation_table returns per-param, per-step retained Sharpe and MAR fractions."""
        golden = {"sma_fast": 40}
        rows = [_oat_row("sma_fast", 32, 0.5), _oat_row("sma_fast", 48, 1.0)]
        tbl = degradation_table(rows, golden, golden_sharpe=1.0)
        assert set(tbl["param"]) == {"sma_fast"}
        # retained_sharpe for the sma_fast=32 row = 0.5 / 1.0
        r = tbl[tbl["override_value"] == 32].iloc[0]
        assert r["retained_sharpe"] == pytest.approx(0.5)


class TestCliffList:
    def test_flags_params_losing_more_than_30pct_at_10pct(self):
        """cliff_list flags params whose +/-10% (x0.9 or x1.1) move loses > 30% of Sharpe."""
        golden = {"sma_fast": 40, "sma_slow": 140}
        rows = [
            _oat_row("sma_fast", 36, 0.5),   # x0.9 of 40 -> retains 0.5 -> cliff (>30% loss)
            _oat_row("sma_fast", 44, 0.95),
            _oat_row("sma_slow", 126, 0.98), # x0.9 of 140
            _oat_row("sma_slow", 154, 0.99),
        ]
        cliffs = cliff_list(rows, golden, golden_sharpe=1.0)
        assert "sma_fast" in cliffs
        assert "sma_slow" not in cliffs

    def test_cliff_threshold_constant(self):
        """The cliff loss threshold is 30% (spec §6)."""
        assert CLIFF_LOSS_FRACTION == 0.30


class TestJointStats:
    def test_histogram_and_golden_percentile(self):
        """joint_stats returns histogram bins and the golden Sharpe's percentile in the joint sample."""
        rows = [{"hash": str(i), "kind": "joint", "param": None, "overrides": {},
                 "sharpe": s, "max_drawdown": -0.2, "annualized_return": 0.1,
                 "total_return": 1.0}
                for i, s in enumerate([0.2, 0.4, 0.6, 0.8, 1.0])]
        stats = joint_stats(rows, golden_sharpe=0.6, bins=5)
        assert stats["count"] == 5
        # golden 0.6: two of five samples (0.2, 0.4) are strictly below -> 40th pct
        assert stats["golden_percentile"] == pytest.approx(40.0)
        assert len(stats["hist_counts"]) == 5
        assert len(stats["hist_edges"]) == 6

    def test_empty_joint_returns_nan_percentile(self):
        """No joint rows -> count 0 and NaN percentile (graceful)."""
        stats = joint_stats([], golden_sharpe=0.6)
        assert stats["count"] == 0
        assert math.isnan(stats["golden_percentile"])


def _joint_row(sharpe):
    return {"hash": "x", "kind": "joint", "param": None, "overrides": {},
            "sharpe": sharpe, "max_drawdown": -0.2, "annualized_return": 0.1,
            "total_return": 1.0}


class TestNoneSharpeGuard:
    def test_none_sharpe_rows_are_excluded_not_crashing(self):
        """OAT row with sharpe None + a valid pair: plateau_score/degradation_table/cliff_list don't raise; None row absent from outputs."""
        golden = {"sma_fast": 40}
        bad_row = _oat_row("sma_fast", 32, None)
        bad_row["sharpe"] = None
        good_row = _oat_row("sma_fast", 48, 0.8)
        rows = [bad_row, good_row]

        # plateau_score: only the good x1.2 row counts
        result = plateau_score(rows, golden, 1.0, "sma_fast")
        assert result["n_rows"] == 1
        assert result["mean_retained"] == pytest.approx(0.8)

        # degradation_table: None-sharpe row excluded
        tbl = degradation_table(rows, golden, golden_sharpe=1.0)
        assert len(tbl) == 1
        assert tbl.iloc[0]["override_value"] == 48

        # cliff_list: no crash (the bad row is skipped)
        cliffs = cliff_list(rows, golden, golden_sharpe=1.0)
        assert isinstance(cliffs, list)

    def test_joint_stats_reports_errored_count(self):
        """3 joint rows, one sharpe None, one NaN -> count == 1, errored == 2, percentile over valid only."""
        rows = [
            _joint_row(0.5),   # valid
            _joint_row(None),  # errored
            _joint_row(float("nan")),  # errored
        ]
        stats = joint_stats(rows, golden_sharpe=0.6)
        assert stats["count"] == 1
        assert stats["errored"] == 2
        # valid sample 0.5 < golden 0.6, so 1/1 strictly below -> 100th pct
        assert stats["golden_percentile"] == pytest.approx(100.0)


from decimal import Decimal

from jutsu_engine.audit.plateau import (
    DECIMAL_PARAMS,
    build_overridden_strategy,
)


class TestBuildOverriddenStrategy:
    def test_decimal_params_match_strategy_runner(self):
        """DECIMAL_PARAMS mirrors LiveStrategyRunner._convert_decimal_params exactly."""
        assert "measurement_noise" in DECIMAL_PARAMS
        assert "t_norm_bear_thresh" in DECIMAL_PARAMS
        assert "rebalance_threshold" in DECIMAL_PARAMS
        # integer window params are NOT decimal
        assert "sma_fast" not in DECIMAL_PARAMS

    def test_override_applies_and_converts_to_decimal(self):
        """Overriding a decimal param yields a strategy whose attribute is the Decimal override."""
        strat = build_overridden_strategy("v3_5b", {"leverage_scalar": 1.2})
        assert strat.leverage_scalar == Decimal("1.2")
        # a non-overridden decimal param keeps its golden Decimal value
        assert strat.max_bond_weight == Decimal("0.4")

    def test_override_integer_param_stays_int(self):
        """Overriding an integer window keeps it an int on the built strategy."""
        strat = build_overridden_strategy("v3_5b", {"sma_fast": 32})
        assert int(strat.sma_fast) == 32
        assert strat.__class__.__name__ == "Hierarchical_Adaptive_v3_5b"

    def test_no_overrides_reproduces_golden(self):
        """With no overrides, the built strategy matches build_strategy_instance's golden values."""
        strat = build_overridden_strategy("v3_5b", {})
        assert int(strat.sma_fast) == 40
        assert int(strat.sma_slow) == 140


class TestDecimalParamsDriftGuard:
    def test_matches_live_strategy_runner_set(self):
        """DECIMAL_PARAMS is bidirectionally in sync with LiveStrategyRunner._convert_decimal_params.

        Checks both directions:
        - every name in DECIMAL_PARAMS appears in the live runner (no stale entries)
        - every name in the live runner appears in DECIMAL_PARAMS (no silently under-converted params)
        """
        import inspect
        import re
        from jutsu_engine.live import strategy_runner
        src = inspect.getsource(strategy_runner.LiveStrategyRunner._convert_decimal_params)
        live_names = set(re.findall(r"'([a-zA-Z_][a-zA-Z0-9_]*)'", src))
        assert live_names == DECIMAL_PARAMS, (
            f"DECIMAL_PARAMS out of sync with live runner:\n"
            f"  in live, missing from DECIMAL_PARAMS: {live_names - DECIMAL_PARAMS}\n"
            f"  in DECIMAL_PARAMS, missing from live: {DECIMAL_PARAMS - live_names}"
        )
