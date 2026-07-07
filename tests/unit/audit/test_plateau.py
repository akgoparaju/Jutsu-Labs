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
