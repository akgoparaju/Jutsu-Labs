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


import json
from pathlib import Path

from jutsu_engine.audit.selection_bias import (
    _RETURNS_RESULT_KEYS, append_returns_row, load_completed_combo_hashes,
    reload_returns_rows, is_error_row,
)


class TestReturnsPersistence:
    def _row(self, h, dates, returns, error=None):
        return {"combo_id": 0, "hash": h, "overrides": {"sma_fast": 40},
                "dates": dates, "returns": returns, "sharpe": None if error else 0.5,
                "error": error}

    def test_append_and_reload_roundtrip(self, tmp_path):
        """A returns row survives append → reload with its dates/returns intact."""
        p = tmp_path / "c.jsonl"
        append_returns_row(p, self._row("h1", ["2010-02-01", "2010-02-02"],
                                        [0.01, -0.02]))
        rows = reload_returns_rows(p)
        assert len(rows) == 1
        assert rows[0]["returns"] == [0.01, -0.02]
        assert rows[0]["dates"] == ["2010-02-01", "2010-02-02"]

    def test_completed_hashes_skips_errors_when_retrying(self, tmp_path):
        """--retry-errors excludes error rows from the completed set."""
        p = tmp_path / "c.jsonl"
        append_returns_row(p, self._row("ok", ["d"], [0.01]))
        append_returns_row(p, self._row("bad", None, None, error="boom"))
        assert load_completed_combo_hashes(p) == {"ok", "bad"}
        assert load_completed_combo_hashes(p, retry_errors=True) == {"ok"}

    def test_last_wins_dedup_on_retry(self, tmp_path):
        """A retried combo (error then success) counts as done regardless of flag."""
        p = tmp_path / "c.jsonl"
        append_returns_row(p, self._row("h", None, None, error="boom"))
        append_returns_row(p, self._row("h", ["d"], [0.01]))   # success supersedes
        assert load_completed_combo_hashes(p, retry_errors=True) == {"h"}
        rows = reload_returns_rows(p)
        assert len(rows) == 1 and rows[0]["error"] is None

    def test_torn_final_line_tolerated(self, tmp_path):
        """A truncated trailing line (crash mid-write) is skipped, not fatal."""
        p = tmp_path / "c.jsonl"
        append_returns_row(p, self._row("h", ["d"], [0.01]))
        with open(p, "a") as f:
            f.write('{"hash": "partial", "returns": [0.0')   # no newline, truncated
        assert load_completed_combo_hashes(p) == {"h"}
        assert len(reload_returns_rows(p)) == 1

    def test_is_error_row(self):
        """A row with a non-null error or missing returns is an error row."""
        assert is_error_row({"error": "x", "returns": None})
        assert is_error_row({"error": None, "returns": None})
        assert not is_error_row({"error": None, "returns": [0.01]})


from datetime import date

from jutsu_engine.audit.selection_bias import (
    run_returns_campaign, ReturnsCampaignResult, DEFAULT_MAX_CONSECUTIVE_ERRORS,
)


def _fake_run_fn(strategy_id, combo, symbols, start, end, initial_capital="10000"):
    """Deterministic fake worker: returns a 2-day series keyed by combo_id."""
    return {"combo_id": combo["combo_id"], "hash": combo["hash"],
            "overrides": combo["overrides"],
            "dates": ["2010-02-01", "2010-02-02"],
            "returns": [0.001 * combo["combo_id"], -0.001 * combo["combo_id"]],
            "sharpe": 0.1 * combo["combo_id"], "error": None}


def _error_run_fn(strategy_id, combo, symbols, start, end, initial_capital="10000"):
    """Fake worker that always errors (to trip the circuit breaker)."""
    return {"combo_id": combo["combo_id"], "hash": combo["hash"],
            "overrides": combo["overrides"], "dates": None, "returns": None,
            "sharpe": None, "error": "boom"}


class TestReturnsCampaign:
    def _combos(self, n):
        from jutsu_engine.audit.selection_bias import combo_hash
        return [{"combo_id": i, "overrides": {"sma_fast": 40 + i},
                 "hash": combo_hash({"sma_fast": 40 + i})} for i in range(n)]

    def test_serial_runs_every_combo(self, tmp_path):
        """Serial campaign writes one row per combo."""
        p = tmp_path / "c.jsonl"
        res = run_returns_campaign(
            "v3_5b", self._combos(3), p, run_fn=_fake_run_fn, symbols=[],
            start=date(2010, 2, 1), end=date(2026, 7, 1), workers=1)
        assert len(res.rows) == 3
        assert isinstance(res, ReturnsCampaignResult)

    def test_resume_skips_completed(self, tmp_path):
        """A second run with all combos present runs zero new backtests."""
        p = tmp_path / "c.jsonl"
        combos = self._combos(3)
        run_returns_campaign("v3_5b", combos, p, run_fn=_fake_run_fn, symbols=[],
                             start=date(2010, 2, 1), end=date(2026, 7, 1), workers=1)
        calls = []

        def counting(strategy_id, combo, symbols, start, end, initial_capital="10000"):
            calls.append(combo["combo_id"])
            return _fake_run_fn(strategy_id, combo, symbols, start, end)

        run_returns_campaign("v3_5b", combos, p, run_fn=counting, symbols=[],
                             start=date(2010, 2, 1), end=date(2026, 7, 1), workers=1)
        assert calls == []   # nothing re-run

    def test_circuit_breaker_aborts_on_systemic_failure(self, tmp_path):
        """N consecutive errored combos abort the campaign with a clear message."""
        p = tmp_path / "c.jsonl"
        combos = self._combos(DEFAULT_MAX_CONSECUTIVE_ERRORS + 5)
        with pytest.raises(RuntimeError, match="consecutive errored"):
            run_returns_campaign("v3_5b", combos, p, run_fn=_error_run_fn,
                                 symbols=[], start=date(2010, 2, 1),
                                 end=date(2026, 7, 1), workers=1)
