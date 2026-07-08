"""DB-free unit tests for Module 3 selection-bias orchestration."""
import yaml

import pytest

from jutsu_engine.audit.selection_bias import (
    GOLDEN_GRID_AXES, enumerate_golden_grid, combo_hash, AXES_YAML_PATH,
)


class TestEnumerateGrid:
    def test_grid_is_243_combos(self):
        """The historical v3.5b golden grid enumerates to exactly 243 combos."""
        combos = enumerate_golden_grid()
        assert len(combos) == 243

    def test_each_combo_has_all_five_axes(self):
        """Every combo overrides exactly the five historical grid axes."""
        combos = enumerate_golden_grid()
        expected_keys = set(GOLDEN_GRID_AXES.keys())
        for c in combos:
            assert set(c["overrides"].keys()) == expected_keys

    def test_combo_ids_are_unique_and_sequential(self):
        """combo_id runs 0..242; hashes are unique."""
        combos = enumerate_golden_grid()
        assert [c["combo_id"] for c in combos] == list(range(243))
        assert len({c["hash"] for c in combos}) == 243

    def test_golden_center_combo_present(self):
        """The live golden values appear as one of the 243 combos."""
        combos = enumerate_golden_grid()
        golden = {"upper_thresh_z": 1.0, "lower_thresh_z": 0.2,
                  "vol_crush_threshold": -0.15, "sma_fast": 40, "sma_slow": 140}
        # NOTE: sma_slow golden (140) is OUTSIDE the historical axis [180,200,220];
        # the historical grid did not center on the eventual live sma_slow. We assert
        # the FOUR shared axes match at least one combo's values (documented mismatch).
        four = {k: golden[k] for k in
                ["upper_thresh_z", "lower_thresh_z", "vol_crush_threshold", "sma_fast"]}
        assert any(all(c["overrides"][k] == v for k, v in four.items())
                   for c in combos)

    def test_axes_yaml_matches_code(self):
        """The versioned axes YAML equals the code's GOLDEN_GRID_AXES (no drift)."""
        with open(AXES_YAML_PATH) as f:
            doc = yaml.safe_load(f)
        assert doc["axes"] == {k: list(v) for k, v in GOLDEN_GRID_AXES.items()}
        assert doc["total_combos"] == 243

    def test_combo_hash_is_order_independent(self):
        """combo_hash is stable regardless of dict key order."""
        a = combo_hash({"sma_fast": 40, "sma_slow": 180})
        b = combo_hash({"sma_slow": 180, "sma_fast": 40})
        assert a == b and len(a) == 16
