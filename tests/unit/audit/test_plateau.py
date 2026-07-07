# tests/unit/audit/test_plateau.py
import json
import math
from datetime import date
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


from jutsu_engine.audit.plateau import (
    append_result,
    build_campaign_samples,
    load_completed_hashes,
    run_one_sample,
)


class TestCheckpointIO:
    def test_append_and_reload_hashes(self, tmp_path):
        """append_result writes a JSONL row; load_completed_hashes reads back its hash."""
        f = tmp_path / "campaign.jsonl"
        row = {"hash": "abc123", "kind": "oat", "param": "sma_fast",
               "overrides": {"sma_fast": 32}, "sharpe": 0.5,
               "max_drawdown": -0.2, "annualized_return": 0.1, "total_return": 1.0}
        append_result(f, row)
        assert load_completed_hashes(f) == {"abc123"}

    def test_missing_file_is_empty_set(self, tmp_path):
        """load_completed_hashes on a nonexistent file returns an empty set (fresh start)."""
        assert load_completed_hashes(tmp_path / "nope.jsonl") == set()

    def test_two_rows_two_hashes(self, tmp_path):
        """Multiple appended rows all resume-skippable by hash."""
        f = tmp_path / "c.jsonl"
        append_result(f, {"hash": "h1", "overrides": {}, "sharpe": 1.0,
                          "max_drawdown": -0.1, "annualized_return": 0.1,
                          "total_return": 1.0, "kind": "joint", "param": None})
        append_result(f, {"hash": "h2", "overrides": {}, "sharpe": 1.0,
                          "max_drawdown": -0.1, "annualized_return": 0.1,
                          "total_return": 1.0, "kind": "joint", "param": None})
        assert load_completed_hashes(f) == {"h1", "h2"}

    def test_truncated_trailing_line_is_tolerated(self, tmp_path):
        """A killed process mid-write leaves a partial final line; resume still reads the good rows.

        Simulates a crash where the last JSONL line was only partially flushed:
        load_completed_hashes must return the completed hashes and silently drop
        the corrupt trailing fragment (crash must not poison resume).
        """
        f = tmp_path / "c.jsonl"
        append_result(f, {"hash": "h1", "overrides": {}, "sharpe": 1.0,
                          "max_drawdown": -0.1, "annualized_return": 0.1,
                          "total_return": 1.0, "kind": "oat", "param": "sma_fast"})
        # Append a truncated JSON fragment with no trailing newline (mid-write crash).
        with open(f, "a") as fh:
            fh.write('{"hash": "h2", "overrides": {"sma_fast": 3')
        assert load_completed_hashes(f) == {"h1"}
        # And a fresh append after the corrupt fragment still recovers cleanly.
        append_result(f, {"hash": "h3", "overrides": {}, "sharpe": 1.0,
                          "max_drawdown": -0.1, "annualized_return": 0.1,
                          "total_return": 1.0, "kind": "oat", "param": "sma_slow"})
        assert load_completed_hashes(f) == {"h1", "h3"}


class TestBuildCampaignSamples:
    def test_combines_oat_and_joint_deduped(self):
        """build_campaign_samples concatenates OAT + joint and drops duplicate hashes."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0}
        samples = build_campaign_samples(golden, joint_n=5, seed=1)
        hashes = [s["hash"] for s in samples]
        assert len(hashes) == len(set(hashes))  # no dup hashes
        kinds = {s["kind"] for s in samples}
        assert kinds == {"oat", "joint"}

    def test_oat_only_flag_skips_joint(self):
        """oat_only=True yields only one-at-a-time samples."""
        golden = {"sma_fast": 40}
        samples = build_campaign_samples(golden, joint_n=5, seed=1, oat_only=True)
        assert {s["kind"] for s in samples} == {"oat"}

    def test_params_filter_restricts_oat(self):
        """params filter restricts OAT samples to the named parameters (for the smoke run)."""
        golden = {"sma_fast": 40, "sma_slow": 140}
        samples = build_campaign_samples(golden, joint_n=0, seed=1, oat_only=True,
                                         params=["sma_fast"])
        assert {s["param"] for s in samples} == {"sma_fast"}


class TestRunOneSampleErrorHandling:
    def test_backtest_failure_records_loud_error_row(self, monkeypatch, tmp_path):
        """A failed backtest returns a row with sharpe=None + an error string, not an exception.

        The campaign must record failures loudly (so the analysis layer's
        _valid_sharpe guard excludes them and joint_stats counts them as errored)
        rather than crashing the whole run.
        """
        import jutsu_engine.audit.plateau as plateau_mod

        class _BoomRunner:
            def __init__(self, config):
                pass

            def run(self, strategy, output_dir):
                raise RuntimeError("backtest exploded")

        # BacktestRunner is imported lazily inside run_one_sample; patch it there.
        import jutsu_engine.application.backtest_runner as br_mod
        monkeypatch.setattr(br_mod, "BacktestRunner", _BoomRunner)
        # build_overridden_strategy would need the DB/YAML; stub it too.
        monkeypatch.setattr(plateau_mod, "build_overridden_strategy",
                             lambda sid, ov: object())

        sample = {"hash": "boom1", "kind": "oat", "param": "sma_fast",
                  "overrides": {"sma_fast": 32}}
        row = run_one_sample("v3_5b", sample, ["QQQ"],
                             date(2010, 2, 1), date(2026, 7, 6))
        assert row["hash"] == "boom1"
        assert row["kind"] == "oat"
        assert row["sharpe"] is None
        assert isinstance(row["error"], str)
        assert "backtest exploded" in row["error"]

        # The loud error survives the JSONL round-trip (append + reload).
        f = tmp_path / "camp.jsonl"
        append_result(f, row)
        reloaded = load_completed_hashes(f)
        assert reloaded == {"boom1"}

    def test_error_row_leaves_no_tempdir(self, monkeypatch):
        """Even on backtest failure, the per-run tempdir is cleaned up (no repo litter)."""
        import glob
        import tempfile

        import jutsu_engine.audit.plateau as plateau_mod

        class _BoomRunner:
            def __init__(self, config):
                pass

            def run(self, strategy, output_dir):
                raise RuntimeError("boom")

        import jutsu_engine.application.backtest_runner as br_mod
        monkeypatch.setattr(br_mod, "BacktestRunner", _BoomRunner)
        monkeypatch.setattr(plateau_mod, "build_overridden_strategy",
                             lambda sid, ov: object())

        before = set(glob.glob(tempfile.gettempdir() + "/plateau_*"))
        sample = {"hash": "boom2", "kind": "joint", "param": None,
                  "overrides": {}}
        run_one_sample("v3_5b", sample, ["QQQ"], date(2010, 2, 1), date(2026, 7, 6))
        after = set(glob.glob(tempfile.gettempdir() + "/plateau_*"))
        assert after == before  # no new plateau_ tempdir left behind


from jutsu_engine.audit.plateau import CampaignResult, run_campaign


def _fake_run_fn(strategy_id, sample, symbols, start, end, initial_capital="10000"):
    # deterministic fake: constant successful row for every sample
    return {
        "hash": sample["hash"], "kind": sample["kind"], "param": sample["param"],
        "overrides": sample["overrides"], "sharpe": 0.8,
        "max_drawdown": -0.5, "annualized_return": 0.23, "total_return": 5.0,
        "error": None,
    }


def _error_run_fn(strategy_id, sample, symbols, start, end, initial_capital="10000"):
    # deterministic fake: every sample comes back as an errored row (sharpe=None)
    return {
        "hash": sample["hash"], "kind": sample["kind"], "param": sample["param"],
        "overrides": sample["overrides"], "sharpe": None,
        "max_drawdown": None, "annualized_return": None, "total_return": None,
        "error": "RuntimeError: simulated DB outage",
    }


# Module-level picklable run_fn for parallel breaker drain test (spawn-safe on macOS).
def _all_error_parallel_run_fn(strategy_id, sample, symbols, start, end,
                                initial_capital="10000"):
    """Every call returns an errored row; used to test parallel breaker drain."""
    return {
        "hash": sample["hash"], "kind": sample["kind"], "param": sample["param"],
        "overrides": sample["overrides"], "sharpe": None,
        "max_drawdown": None, "annualized_return": None, "total_return": None,
        "error": "RuntimeError: simulated systemic failure",
    }


class TestRunCampaign:
    def test_runs_all_samples_and_checkpoints(self, tmp_path):
        """run_campaign executes every sample once, appends to JSONL, returns rows."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0}
        camp_file = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", golden, camp_file, joint_n=3, seed=1, workers=1,
            run_fn=_fake_run_fn, symbols=["QQQ"], start=date(2010, 2, 1),
            end=date(2026, 7, 6),
        )
        assert isinstance(res, CampaignResult)
        assert len(res.rows) == len(res.samples)
        assert load_completed_hashes(camp_file) == {s["hash"] for s in res.samples}
        assert res.seed == 1

    def test_resume_skips_completed(self, tmp_path):
        """A second run over the same file skips already-completed samples (no re-run)."""
        golden = {"sma_fast": 40}
        camp_file = tmp_path / "c.jsonl"
        calls = {"n": 0}

        def counting_run_fn(*a, **k):
            calls["n"] += 1
            return _fake_run_fn(*a, **k)

        run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                     run_fn=counting_run_fn, symbols=["QQQ"], oat_only=True,
                     start=date(2010, 2, 1), end=date(2026, 7, 6))
        first = calls["n"]
        # second invocation: everything already in the file -> zero new run_fn calls
        run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                     run_fn=counting_run_fn, symbols=["QQQ"], oat_only=True,
                     start=date(2010, 2, 1), end=date(2026, 7, 6))
        assert calls["n"] == first  # no new work

    def test_params_filter_limits_to_smoke_set(self, tmp_path):
        """params filter + oat_only runs only the named parameter's four OAT samples."""
        golden = {"sma_fast": 40, "sma_slow": 140}
        camp_file = tmp_path / "smoke.jsonl"
        res = run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                           run_fn=_fake_run_fn, symbols=["QQQ"], oat_only=True,
                           params=["sma_fast"], start=date(2010, 2, 1),
                           end=date(2026, 7, 6))
        assert {r["param"] for r in res.rows} == {"sma_fast"}
        assert len(res.rows) == 4  # x0.8/x0.9/x1.1/x1.2, none collapse for sma_fast=40

    def test_circuit_breaker_trips_on_consecutive_errors(self, tmp_path):
        """N consecutive errored runs abort the campaign (guards against a DB outage)."""
        # Enough perturbable params to produce >N samples of pure OAT.
        golden = {"sma_fast": 40, "sma_slow": 140, "realized_vol_window": 20,
                  "vol_baseline_window": 60, "leverage_scalar": 1.0}
        camp_file = tmp_path / "outage.jsonl"
        with pytest.raises(RuntimeError, match="consecutive"):
            run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                         run_fn=_error_run_fn, symbols=["QQQ"], oat_only=True,
                         max_consecutive_errors=3, start=date(2010, 2, 1),
                         end=date(2026, 7, 6))
        # Exactly the breaker threshold of errored rows were checkpointed before abort.
        assert len(load_completed_hashes(camp_file)) == 3

    def test_success_resets_consecutive_error_counter(self, tmp_path):
        """A single success between errors resets the counter so the breaker does not trip."""
        golden = {"sma_fast": 40, "sma_slow": 140, "realized_vol_window": 20,
                  "vol_baseline_window": 60, "leverage_scalar": 1.0}
        camp_file = tmp_path / "flaky.jsonl"
        calls = {"n": 0}

        def flaky_run_fn(strategy_id, sample, *a, **k):
            # error, error, SUCCESS, error, error, ... — never 3 errors in a row
            calls["n"] += 1
            if calls["n"] % 3 == 0:
                return _fake_run_fn(strategy_id, sample, *a, **k)
            return _error_run_fn(strategy_id, sample, *a, **k)

        # With threshold 3 and a success every third call, the breaker must not trip.
        res = run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                           run_fn=flaky_run_fn, symbols=["QQQ"], oat_only=True,
                           max_consecutive_errors=3, start=date(2010, 2, 1),
                           end=date(2026, 7, 6))
        # Campaign completed (no exception); all samples checkpointed.
        assert len(res.rows) == len(res.samples)

    def test_single_writer_invariant_serial(self, tmp_path):
        """The orchestrator (not run_fn) is the sole writer of the JSONL.

        run_fn only returns rows; it must never touch the campaign file. We assert
        the file is empty until the orchestrator appends, by having run_fn observe
        the on-disk state at call time (it stays empty of that sample's own hash).
        """
        golden = {"sma_fast": 40}
        camp_file = tmp_path / "sw.jsonl"
        observed = []

        def observing_run_fn(strategy_id, sample, *a, **k):
            # run_fn sees the file WITHOUT its own row (parent writes after return).
            done_now = load_completed_hashes(camp_file)
            observed.append(sample["hash"] in done_now)
            return _fake_run_fn(strategy_id, sample, *a, **k)

        run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                     run_fn=observing_run_fn, symbols=["QQQ"], oat_only=True,
                     start=date(2010, 2, 1), end=date(2026, 7, 6))
        # No run_fn call ever saw its own hash already written -> parent is sole writer.
        assert observed and not any(observed)

    def test_parallel_path_runs_and_resumes(self, tmp_path):
        """workers>1 uses ProcessPoolExecutor with a picklable module-level run_fn.

        The parallel path submits the given run_fn directly, so it must be a
        module-level (picklable) function to cross the macOS spawn boundary.
        _fake_run_fn is module-level and DB-free, so it is spawn-safe. Every
        sample must land, and a second parallel run must do zero new work.
        """
        golden = {"sma_fast": 40}
        camp_file = tmp_path / "par.jsonl"
        res = run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1,
                           workers=2, run_fn=_fake_run_fn, symbols=["QQQ"],
                           oat_only=True, start=date(2010, 2, 1),
                           end=date(2026, 7, 6))
        assert load_completed_hashes(camp_file) == {s["hash"] for s in res.samples}
        # Resume: a second parallel run over the same file does zero new work.
        res2 = run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1,
                            workers=2, run_fn=_fake_run_fn, symbols=["QQQ"],
                            oat_only=True, start=date(2010, 2, 1),
                            end=date(2026, 7, 6))
        assert len(res2.rows) == len(res2.samples)

    def test_parallel_breaker_drains_finished_batch(self, tmp_path):
        """Parallel breaker drains every completed future in the batch before aborting.

        When wait(FIRST_COMPLETED) returns a batch of N completed futures and the
        breaker trips mid-batch, Fix I1 guarantees the remaining futures in that
        batch are still processed and their rows checkpointed — no completed work
        is silently discarded.

        Setup: workers=2 so up to 2 futures complete per batch; every run errors;
        max_consecutive_errors=2 so the breaker can trip within a single 2-future
        batch. After the RuntimeError, the on-disk row count must be >= 2 (i.e.
        every future that completed before the abort has its row on disk), and the
        JSONL must be parseable (no torn lines).

        The run_fn (_all_error_parallel_run_fn) is module-level and picklable so
        it crosses the macOS spawn boundary deterministically.
        """
        # Use two perturbable OAT params to get at least 8 samples (2 params × 4
        # multipliers), more than enough for the breaker to trip.
        golden = {"sma_fast": 40, "sma_slow": 140}
        camp_file = tmp_path / "par_drain.jsonl"
        max_errors = 2

        with pytest.raises(RuntimeError, match="consecutive"):
            run_campaign(
                "v3_5b", golden, camp_file,
                joint_n=0, seed=1,
                workers=2,
                run_fn=_all_error_parallel_run_fn,
                symbols=["QQQ"],
                oat_only=True,
                max_consecutive_errors=max_errors,
                start=date(2010, 2, 1),
                end=date(2026, 7, 6),
            )

        # Every future that completed has its row on disk — row count >= max_errors
        # (the breaker threshold) and the JSONL must be consistent (no torn state).
        completed_hashes = load_completed_hashes(camp_file)
        assert len(completed_hashes) >= max_errors, (
            f"Expected >= {max_errors} rows on disk after parallel abort; "
            f"got {len(completed_hashes)} — finished-batch drain is broken"
        )
        # Verify no torn lines: every line in the file must be valid JSON with a hash.
        with open(camp_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)  # raises on torn JSON
                assert "hash" in row


from jutsu_engine.audit.plateau import summarize_campaign


class TestSummarizeCampaign:
    def test_builds_report_summary_from_rows(self):
        """summarize_campaign turns a CampaignResult + golden metrics into the report summary dict."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0}
        rows = [
            _oat_row("sma_fast", 32, 0.8), _oat_row("sma_fast", 48, 0.6),
            _oat_row("sma_fast", 36, 0.5), _oat_row("sma_fast", 44, 0.9),
            {"hash": "j1", "kind": "joint", "param": None, "overrides": {},
             "sharpe": 0.4, "max_drawdown": -0.5, "annualized_return": 0.1,
             "total_return": 1.0},
        ]
        res = CampaignResult("v3_5b", 42, samples=rows, rows=rows,
                             campaign_file="x.jsonl", golden=golden)
        summary = summarize_campaign(res, golden_sharpe=1.0,
                                     golden_metrics={"sharpe_ratio": 1.0,
                                                     "max_drawdown": -0.5,
                                                     "annualized_return": 0.2,
                                                     "total_return": 5.0})
        assert summary["strategy_id"] == "v3_5b"
        assert summary["seed"] == 42
        assert summary["oat_count"] == 4 and summary["joint_count"] == 1
        # sma_fast x0.9 (36) retains 0.5 -> >30% loss -> cliff
        assert "sma_fast" in summary["cliffs"]
        assert "sma_fast" in summary["plateau_scores"]
        assert not summary["degradation_table"].empty
        assert summary["joint_stats"]["count"] == 1
        # plateau_scores values are dicts (not plain floats)
        assert isinstance(summary["plateau_scores"]["sma_fast"], dict)
        assert "mean_retained" in summary["plateau_scores"]["sma_fast"]
        assert "worst_retained" in summary["plateau_scores"]["sma_fast"]
        # joint_stats carries errored key
        assert "errored" in summary["joint_stats"]

    def test_oat_and_joint_counts_are_correct(self):
        """oat_count = len(oat rows), joint_count = len(joint rows)."""
        golden = {"sma_fast": 40}
        oat = [_oat_row("sma_fast", 32, 0.8), _oat_row("sma_fast", 48, 0.9)]
        joint = [{"hash": f"j{i}", "kind": "joint", "param": None,
                  "overrides": {}, "sharpe": 0.5 + i * 0.1,
                  "max_drawdown": -0.2, "annualized_return": 0.1, "total_return": 1.0}
                 for i in range(3)]
        rows = oat + joint
        res = CampaignResult("v3_5b", 0, samples=rows, rows=rows,
                             campaign_file="x.jsonl", golden=golden)
        summary = summarize_campaign(res, golden_sharpe=1.0,
                                     golden_metrics={"sharpe_ratio": 1.0,
                                                     "max_drawdown": -0.5,
                                                     "annualized_return": 0.2,
                                                     "total_return": 5.0})
        assert summary["oat_count"] == 2
        assert summary["joint_count"] == 3

    def test_empty_campaign_no_crash(self):
        """An empty campaign (no rows) produces an empty summary without crashing."""
        golden = {"sma_fast": 40}
        res = CampaignResult("v3_5b", 0, samples=[], rows=[],
                             campaign_file="x.jsonl", golden=golden)
        summary = summarize_campaign(res, golden_sharpe=1.0,
                                     golden_metrics={"sharpe_ratio": 1.0,
                                                     "max_drawdown": -0.5,
                                                     "annualized_return": 0.2,
                                                     "total_return": 5.0})
        assert summary["oat_count"] == 0
        assert summary["joint_count"] == 0
        assert summary["cliffs"] == []
        assert summary["degradation_table"].empty
        assert summary["joint_stats"]["count"] == 0
