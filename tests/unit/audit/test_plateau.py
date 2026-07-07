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
