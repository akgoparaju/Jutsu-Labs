"""DB-free unit tests for Module 3 selection-bias orchestration."""
import yaml

import pytest

from jutsu_engine.audit.selection_bias import (
    GOLDEN_GRID_AXES, enumerate_golden_grid, combo_hash, AXES_YAML_PATH,
    enumerate_golden_grid_with_live, golden_live_combo, GOLDEN_LIVE_HASH,
    GOLDEN_LIVE_KIND, GOLDEN_LIVE_COMBO_ID, GRID_KIND,
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

    def test_grid_combos_flagged_kind_grid(self):
        """Every historical grid combo is flagged kind='grid' (PBO/V includes it)."""
        assert all(c["kind"] == GRID_KIND for c in enumerate_golden_grid())

    def test_wrapper_appends_golden_live_with_empty_overrides(self):
        """enumerate_golden_grid_with_live appends a 244th golden_live combo (empty overrides)."""
        combos = enumerate_golden_grid_with_live()
        assert len(combos) == 244
        live = combos[-1]
        assert live["kind"] == GOLDEN_LIVE_KIND
        assert live["overrides"] == {}
        assert live["hash"] == GOLDEN_LIVE_HASH == combo_hash({})
        assert live["combo_id"] == GOLDEN_LIVE_COMBO_ID == 243

    def test_golden_live_hash_disjoint_from_grid(self):
        """The golden_live hash is provably distinct from every grid combo's hash."""
        grid = {c["hash"] for c in enumerate_golden_grid()}
        assert golden_live_combo()["hash"] not in grid

    def test_wrapper_limit_truncates_grid_but_keeps_golden_live(self):
        """A smoke limit truncates the GRID but always keeps the golden_live combo."""
        combos = enumerate_golden_grid_with_live(limit=4)
        grid = [c for c in combos if c["kind"] == GRID_KIND]
        live = [c for c in combos if c["kind"] == GOLDEN_LIVE_KIND]
        assert len(grid) == 4 and len(live) == 1
        assert live[0]["hash"] == GOLDEN_LIVE_HASH


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


import numpy as np

from jutsu_engine.audit.selection_bias import (
    build_returns_matrix, cross_trial_variance, golden_combo_returns,
)


class TestReturnsMatrix:
    def test_aligns_on_union_of_dates(self):
        """Combos sharing most dates align on union; the missing cell is filled 0.0."""
        # Use 1000-date series with one combo missing ONE date (0.1% fill ≤ threshold).
        dates = [f"2010-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(1000)]
        rows = [
            {"combo_id": 0, "hash": "a", "overrides": {}, "error": None,
             "dates": dates, "returns": [0.01] * 1000},
            {"combo_id": 1, "hash": "b", "overrides": {}, "error": None,
             "dates": dates[1:], "returns": [0.02] * 999},  # missing first date
        ]
        mat, cols, out_dates, n_filled = build_returns_matrix(rows)
        assert mat.shape == (1000, 2)          # union of 1000 dates, 2 combos
        assert out_dates == dates
        # combo 1 has no first date → filled 0.0
        assert mat[0, 1] == 0.0
        assert n_filled == 1                   # exactly one cell filled

    def test_aligns_on_union_of_dates_no_gaps(self):
        """Two combos sharing all dates: n_filled=0, both in matrix."""
        rows = [
            {"combo_id": 0, "hash": "a", "overrides": {}, "error": None,
             "dates": ["2010-02-01", "2010-02-02"], "returns": [0.01, 0.02]},
            {"combo_id": 1, "hash": "b", "overrides": {}, "error": None,
             "dates": ["2010-02-01", "2010-02-02"], "returns": [0.03, 0.04]},
        ]
        mat, cols, dates, n_filled = build_returns_matrix(rows)
        assert mat.shape == (2, 2)
        assert dates == ["2010-02-01", "2010-02-02"]
        assert n_filled == 0
        assert cols == ["a", "b"]

    def test_excludes_error_rows(self):
        """Error rows (returns None) are dropped from the matrix."""
        rows = [
            {"combo_id": 0, "hash": "a", "overrides": {}, "error": None,
             "dates": ["d1"], "returns": [0.01]},
            {"combo_id": 1, "hash": "b", "overrides": {}, "error": "boom",
             "dates": None, "returns": None},
        ]
        mat, cols, dates, n_filled = build_returns_matrix(rows)
        assert mat.shape[1] == 1              # only the good combo
        assert cols == ["a"]

    def test_filled_cells_counted_and_returned(self):
        """n_filled_cells counts cells zero-filled during union alignment."""
        # Build 3 combos all sharing 1000 dates (no fills) — n_filled == 0.
        dates = [f"2010-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(1000)]
        rows = [
            {"combo_id": j, "hash": chr(97 + j), "overrides": {}, "error": None,
             "dates": dates, "returns": [0.001 * j] * 1000}
            for j in range(3)
        ]
        mat, cols, out_dates, n_filled = build_returns_matrix(rows)
        assert n_filled == 0
        assert mat.shape == (1000, 3)

    def test_high_fill_fraction_combo_dropped(self):
        """A combo whose filled fraction > 0.1% is silently dropped from the matrix."""
        # 1000-date union; one combo covers only 998 dates → 2/1000 = 0.2% > threshold.
        dates = [f"2010-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(1000)]
        rows = [
            # combo 0: all 1000 dates — no fill
            {"combo_id": 0, "hash": "full", "overrides": {}, "error": None,
             "dates": dates, "returns": [0.001] * 1000},
            # combo 1: only 998 dates — 2/1000 = 0.2% fill > 0.1% threshold → dropped
            {"combo_id": 1, "hash": "short", "overrides": {}, "error": None,
             "dates": dates[:998], "returns": [0.002] * 998},
        ]
        mat, cols, out_dates, n_filled = build_returns_matrix(rows)
        assert "short" not in cols      # high-fill combo dropped
        assert "full" in cols           # no-fill combo kept
        assert mat.shape[1] == 1

    def test_low_fill_fraction_combo_kept(self):
        """A combo whose filled fraction <= 0.1% is kept (fill counted but not dropped)."""
        # 1000-date union; one combo covers 999 dates → 1/1000 = 0.1% <= threshold.
        dates = [f"2010-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(1000)]
        rows = [
            {"combo_id": 0, "hash": "full", "overrides": {}, "error": None,
             "dates": dates, "returns": [0.001] * 1000},
            {"combo_id": 1, "hash": "one_short", "overrides": {}, "error": None,
             "dates": dates[:999], "returns": [0.002] * 999},
        ]
        mat, cols, out_dates, n_filled = build_returns_matrix(rows)
        assert "one_short" in cols      # at-threshold combo kept
        assert n_filled == 1            # exactly 1 cell was filled

    def test_cross_trial_variance_from_sharpes(self):
        """V is the variance of per-combo per-period Sharpes across the matrix columns."""
        # 3 combos with distinct constant-ish returns → distinct Sharpes → V > 0.
        rng = np.random.default_rng(0)
        mat = np.column_stack([
            0.01 + 0.001 * rng.standard_normal(500),
            0.02 + 0.001 * rng.standard_normal(500),
            -0.005 + 0.001 * rng.standard_normal(500),
        ])
        V = cross_trial_variance(mat)
        assert V > 0.0
        # sanity: matches numpy variance of the per-column Sharpes
        sr = mat.mean(axis=0) / mat.std(axis=0, ddof=1)
        assert V == pytest.approx(float(np.var(sr, ddof=1)), rel=1e-9)

    def test_golden_combo_returns_selects_by_hash(self):
        """golden_combo_returns pulls one combo's series by hash."""
        rows = [
            {"combo_id": 0, "hash": "g", "overrides": {}, "error": None,
             "dates": ["d1", "d2"], "returns": [0.01, 0.02]},
            {"combo_id": 1, "hash": "x", "overrides": {}, "error": None,
             "dates": ["d1", "d2"], "returns": [0.0, 0.0]},
        ]
        r = golden_combo_returns(rows, "g")
        assert list(r) == [0.01, 0.02]


# ---------------------------------------------------------------------------
# Task 11 — run_dsr orchestrator + summarize_selection_bias
# ---------------------------------------------------------------------------
from jutsu_engine.audit.selection_bias import (
    summarize_selection_bias, DEFAULT_N_BRACKETS,
    _golden_anchor_hash, _golden_anchor_target_hash, is_golden_live_row,
)


class TestSummarize:
    def _rows_with_spread(self, n=8, T=400, seed=0):
        """N combos with distinct Sharpes over T days (deterministic)."""
        from jutsu_engine.audit.selection_bias import combo_hash
        rng = np.random.default_rng(seed)
        dates = [f"2010-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(T)]
        rows = []
        for j in range(n):
            base = rng.standard_normal(T)
            base = (base - base.mean()) / base.std(ddof=1)
            ret = (0.01 * base + 0.01 * (0.02 * j)).tolist()   # combo j Sharpe rises
            h = combo_hash({"sma_fast": 40 + j})
            rows.append({"combo_id": j, "hash": h, "overrides": {"sma_fast": 40 + j},
                         "dates": dates, "returns": ret, "sharpe": 0.02 * j,
                         "error": None})
        return rows

    def test_summary_has_dsr_brackets_and_pbo(self):
        """summarize produces bracketed DSR rows + a PBO block for v3_5b."""
        rows = self._rows_with_spread()
        golden_hash = rows[3]["hash"]           # pick combo 3 as the golden anchor
        summary = summarize_selection_bias(
            strategy_id="v3_5b", rows=rows, golden_hash=golden_hash,
            trial_inventory=[{"strategy_name": "v3_5b",
                              "optimizer_type": "grid_search", "trials": 243}],
            compute_pbo_block=True, S=8)
        assert [r["N"] for r in summary["dsr_brackets"]] == list(DEFAULT_N_BRACKETS)
        assert 0.0 <= summary["pbo"]["pbo"] <= 1.0
        assert summary["n_combos"] == 8
        assert summary["cross_trial_V"] > 0.0

    def test_dsr_only_path_skips_pbo(self):
        """v3_5d DSR-only summary carries DSR brackets but no PBO block."""
        rows = self._rows_with_spread(n=2)
        summary = summarize_selection_bias(
            strategy_id="v3_5d", rows=rows, golden_hash=rows[0]["hash"],
            trial_inventory=[], compute_pbo_block=False, S=8,
            family_N=(1000, 5000))
        assert summary["pbo"] is None
        assert [r["N"] for r in summary["dsr_brackets"]] == [1000, 5000]

    def _grid_plus_golden_live(self, T=400, sharpe_grid=0.5, sharpe_live=3.0, seed=1):
        """Grid rows sharing one Sharpe (Y) + a golden_live row with a DIFFERENT Sharpe (X).

        Deterministic: every grid combo is z-scored then scaled to daily Sharpe Y; the
        golden_live combo is z-scored then scaled to daily Sharpe X != Y so the DSR
        headline (sourced from golden_live) is distinguishable from the grid combos.
        """
        rng = np.random.default_rng(seed)
        dates = [f"2010-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(T)]

        def _series(sr, s):
            z = rng.standard_normal(T)
            z = (z - z.mean()) / z.std(ddof=1)          # mean 0, std 1
            return (z * 0.01 + sr * 0.01).tolist()      # daily Sharpe == sr

        rows = []
        for j in range(8):                              # 8 grid combos, all Sharpe Y
            rows.append({"combo_id": j, "hash": combo_hash({"sma_fast": 40 + j}),
                         "overrides": {"sma_fast": 40 + j}, "kind": GRID_KIND,
                         "dates": dates, "returns": _series(sharpe_grid, 100 + j),
                         "sharpe": sharpe_grid, "error": None})
        rows.append({"combo_id": GOLDEN_LIVE_COMBO_ID, "hash": GOLDEN_LIVE_HASH,
                     "overrides": {}, "kind": GOLDEN_LIVE_KIND, "dates": dates,
                     "returns": _series(sharpe_live, 999), "sharpe": sharpe_live,
                     "error": None})
        return rows

    def test_dsr_sourced_from_golden_live_not_grid(self):
        """DSR SR_obs comes from the golden_live returns (Sharpe X), not the grid (Y)."""
        rows = self._grid_plus_golden_live(sharpe_grid=0.5, sharpe_live=3.0)
        summary = summarize_selection_bias(
            strategy_id="v3_5b", rows=rows, golden_hash=GOLDEN_LIVE_HASH,
            trial_inventory=[], compute_pbo_block=True, S=8)
        # golden_live daily Sharpe is 3.0; grid combos are 0.5 → SR_obs must track 3.0.
        assert summary["golden_moments"]["sr_obs"] == pytest.approx(3.0, abs=0.05)
        assert summary["dsr_brackets"][0]["sr_obs"] == pytest.approx(3.0, abs=0.05)

    def test_golden_live_excluded_from_matrix_and_V(self):
        """n_combos counts GRID combos only; golden_live never enters the CSCV matrix/V."""
        rows = self._grid_plus_golden_live()
        summary = summarize_selection_bias(
            strategy_id="v3_5b", rows=rows, golden_hash=GOLDEN_LIVE_HASH,
            trial_inventory=[], compute_pbo_block=True, S=8)
        # 8 grid combos → matrix has 8 columns; the golden_live row is excluded.
        assert summary["n_combos"] == 8

    def test_golden_live_errored_raises_loud(self):
        """A missing/errored golden_live row raises RuntimeError (no silent fallback)."""
        rows = self._grid_plus_golden_live()
        rows[-1]["error"] = "backtest blew up"         # golden_live errored
        rows[-1]["returns"] = None
        with pytest.raises(RuntimeError, match="golden combo"):
            summarize_selection_bias(
                strategy_id="v3_5b", rows=rows, golden_hash=GOLDEN_LIVE_HASH,
                trial_inventory=[], compute_pbo_block=True, S=8)


class TestGoldenAnchorDiagnostic:
    def test_anchor_present_returns_hash(self):
        """_golden_anchor_hash returns the sma_slow=200 in-grid combo hash when present."""
        combos = enumerate_golden_grid_with_live()
        assert _golden_anchor_hash(combos) == _golden_anchor_target_hash()

    def test_anchor_absent_raises_value_error(self):
        """A truncated grid lacking the anchor raises ValueError (no silent combo-0 fallback)."""
        combos = enumerate_golden_grid_with_live(limit=2)   # anchor not in first 2
        assert _golden_anchor_target_hash() not in {c["hash"] for c in combos}
        with pytest.raises(ValueError, match="anchor"):
            _golden_anchor_hash(combos)


class TestSmoke:
    def test_combos_limit_truncates_grid(self):
        """enumerate_golden_grid(limit=N) returns the first N combos for smoke runs."""
        from jutsu_engine.audit.selection_bias import enumerate_golden_grid
        assert len(enumerate_golden_grid(limit=5)) == 5
        assert len(enumerate_golden_grid()) == 243

    def test_run_dsr_threads_combos_limit(self, tmp_path, monkeypatch):
        """run_dsr(combos_limit=N) runs N GRID combos PLUS the golden_live combo (244th)."""
        import jutsu_engine.audit.selection_bias as sb
        monkeypatch.setattr(sb, "_all_symbols", lambda sid: [], raising=False)
        # inject the fake worker so no DB/backtest is touched
        seen = []

        def fake_run_fn(strategy_id, combo, symbols, start, end, initial_capital="10000"):
            seen.append(combo["combo_id"])
            return {"combo_id": combo["combo_id"], "hash": combo["hash"],
                    "overrides": combo["overrides"], "kind": combo.get("kind"),
                    "dates": ["2010-02-01", "2010-02-02"],
                    "returns": [0.01, -0.02], "sharpe": 0.1, "error": None}

        monkeypatch.setattr(sb, "run_one_combo", fake_run_fn)
        # smoke=4 grid combos; the golden_live combo (id 243) is ALWAYS appended so
        # the DSR has returns to compute on.
        sb.run_dsr("v3_5b", tmp_path, combos_limit=4, cscv_blocks=2)
        assert sorted(seen) == [0, 1, 2, 3, sb.GOLDEN_LIVE_COMBO_ID]
