"""DB-free unit tests for the PBO/CSCV math (Module 3)."""
from math import comb

import numpy as np
import pytest

from jutsu_engine.audit.pbo import (
    split_blocks,
    partition_sharpes,
    N_CHOOSE_HALF,
    _sharpes_from_stats,
    _block_stats,
)


class TestSplitBlocks:
    def test_splits_into_S_contiguous_index_blocks(self):
        """split_blocks returns S contiguous index arrays covering all rows once."""
        blocks = split_blocks(T=16, S=4)
        assert len(blocks) == 4
        flat = np.concatenate(blocks)
        assert list(flat) == list(range(16))
        # contiguity: each block's indices are consecutive
        for b in blocks:
            assert list(b) == list(range(b[0], b[-1] + 1))

    def test_uneven_split_is_balanced(self):
        """T not divisible by S still covers every row exactly once."""
        blocks = split_blocks(T=17, S=4)
        assert sorted(np.concatenate(blocks)) == list(range(17))

    def test_too_few_rows_raises(self):
        """Need at least S rows to make S blocks."""
        with pytest.raises(ValueError, match="need at least S"):
            split_blocks(T=3, S=4)


class TestPartitionSharpes:
    def test_partition_count_is_C_S_half(self):
        """partition_sharpes yields exactly C(S, S/2) (IS_sharpe, OOS_sharpe) pairs."""
        mat = np.random.default_rng(0).standard_normal((32, 5))
        pairs = list(partition_sharpes(mat, S=8))
        assert len(pairs) == comb(8, 4)
        assert N_CHOOSE_HALF(8) == comb(8, 4)

    def test_each_pair_has_one_sharpe_per_combo(self):
        """Each partition returns an IS and OOS Sharpe vector of length N (combos)."""
        mat = np.random.default_rng(1).standard_normal((16, 3))
        is_sr, oos_sr = next(iter(partition_sharpes(mat, S=4)))
        assert is_sr.shape == (3,)
        assert oos_sr.shape == (3,)


# ---------------------------------------------------------------------------
# Task 5: compute_pbo + relative_rank + logit tests
# ---------------------------------------------------------------------------
from jutsu_engine.audit.pbo import compute_pbo, relative_rank, logit


class TestRelativeRankAndLogit:
    def test_relative_rank_best_is_one_worst_is_zero(self):
        """The top combo has relative rank 1.0, the bottom 0.0."""
        oos = np.array([0.1, 0.5, -0.2, 0.3])   # combo 1 best, combo 2 worst
        assert relative_rank(oos, best_idx=1) == pytest.approx(1.0)
        assert relative_rank(oos, best_idx=2) == pytest.approx(0.0)

    def test_relative_rank_middle(self):
        """A middle combo beats a proportional fraction of the others."""
        oos = np.array([0.1, 0.5, -0.2, 0.3])   # combo 0 beats only combo 2 → 1/3
        assert relative_rank(oos, best_idx=0) == pytest.approx(1.0 / 3.0)

    def test_logit_sign(self):
        """ω̄ > 0.5 → positive logit; ω̄ < 0.5 → negative logit."""
        assert logit(0.75) > 0
        assert logit(0.25) < 0
        assert logit(0.5) == pytest.approx(0.0)


class TestComputePBO:
    def test_persistent_matrix_pbo_zero(self):
        """A perfectly persistent winner (combo 0 dominates every block) → PBO 0."""
        # Deterministic: combo 0 has highest mean & non-zero variance in EVERY block.
        S, rows_per, N = 16, 4, 5
        T = S * rows_per
        mat = np.zeros((T, N))
        for j in range(N):
            base = 0.05 - 0.01 * j                      # combo0 best, combo4 worst
            mat[:, j] = base + 0.0001 * np.tile([1, -1, 1, -1], S)
        res = compute_pbo(mat, S=16)
        assert res["pbo"] == pytest.approx(0.0, abs=1e-12)
        assert res["prob_oos_loss"] == pytest.approx(0.0, abs=1e-12)
        assert res["n_partitions"] == 12870

    def test_tiny_S4_dominant_combo_hand_enumerable(self):
        """Tiny S=4 (6 partitions) with a dominant combo 0 → PBO 0."""
        mat = np.array([
            [0.03, 0.01, -0.01], [0.03, 0.01, -0.01],
            [0.03, 0.01, -0.01], [0.03, 0.01, -0.01],
            [0.03, 0.01, -0.01], [0.03, 0.01, -0.01],
            [0.03, 0.01, -0.01], [0.03, 0.01, -0.01],
        ]) + np.tile([[0.001, -0.001, 0.0005],
                      [-0.001, 0.001, -0.0005]], (4, 1))
        res = compute_pbo(mat, S=4)
        assert res["n_partitions"] == 6
        assert res["pbo"] == pytest.approx(0.0, abs=1e-12)

    def test_noise_pbo_exceeds_persistent(self):
        """Pure-noise combos overfit far more than a persistent winner (ordering)."""
        rng = np.random.default_rng(0)
        noise = rng.standard_normal((160, 50))
        noise_pbo = compute_pbo(noise, S=16)["pbo"]
        # persistent baseline from the first test ≈ 0
        assert noise_pbo > 0.1     # honest band: noise overfits materially more than 0

    def test_degradation_slope_negative_for_overfit(self):
        """IS-vs-OOS Sharpe regression slope < 1 when OOS underperforms IS."""
        rng = np.random.default_rng(2)
        noise = rng.standard_normal((160, 40))
        res = compute_pbo(noise, S=16)
        # overfit ⇒ high IS Sharpe does not carry to OOS ⇒ slope well below 1
        assert res["degradation_slope"] < 0.5

    def test_logit_distribution_length_matches_partitions(self):
        """The logit distribution has one entry per partition."""
        rng = np.random.default_rng(4)
        mat = rng.standard_normal((32, 6))
        res = compute_pbo(mat, S=8)
        assert len(res["logits"]) == res["n_partitions"]

    def test_too_few_combos_raises(self):
        """PBO needs >= 2 combos to rank."""
        with pytest.raises(ValueError, match="at least 2 combos"):
            compute_pbo(np.random.default_rng(0).standard_normal((32, 1)), S=8)

    def test_nan_in_matrix_raises(self):
        """compute_pbo must reject matrices containing NaN — caller must drop combos."""
        mat = np.random.default_rng(7).standard_normal((32, 4))
        mat[5, 2] = np.nan
        with pytest.raises(ValueError, match="matrix contains NaN"):
            compute_pbo(mat, S=8)


# ---------------------------------------------------------------------------
# Fix 1: robust zero/near-zero variance guard in _sharpes_from_stats
# ---------------------------------------------------------------------------

class TestSharpesZeroVarianceGuard:
    """Tests for the scale-invariant degenerate-variance guard in _sharpes_from_stats."""

    def _make_block_stats(self, matrix: np.ndarray, S: int = 4):
        """Helper: return (sums, sumsq, counts, list(range(S))) for a matrix."""
        sums, sumsq, counts = _block_stats(matrix, S)
        return sums, sumsq, counts, list(range(S))

    def test_constant_zero_column_gets_nan_sharpe(self):
        """A column of all zeros is degenerate: var_pop = 0 exactly → NaN Sharpe."""
        mat = np.zeros((16, 3))
        mat[:, 0] = 0.0          # constant zero
        mat[:, 1] = 0.01         # constant non-zero
        mat[:, 2] = np.tile([0.01, -0.01], 8)   # real variance
        sums, sumsq, counts, ids = self._make_block_stats(mat, S=4)
        sharpes = _sharpes_from_stats(ids, sums, sumsq, counts)
        assert np.isnan(sharpes[0]), "all-zero column must yield NaN Sharpe"
        assert np.isnan(sharpes[1]), "all-constant column must yield NaN Sharpe"
        assert np.isfinite(sharpes[2]), "real-variance column must yield finite Sharpe"

    def test_constant_large_value_column_gets_nan_sharpe(self):
        """A column with constant large return (e.g. 0.001 daily) is degenerate.

        This is the catastrophic-cancellation case: sumsq/n ≈ 1e-6,
        var_pop ≈ 0 (but computed as ~1e-19 due to FP cancellation).
        The exact-zero check `std == 0.0` misses this; the relative guard must catch it.
        """
        T = 64
        mat = np.zeros((T, 3))
        mat[:, 0] = 0.001        # constant — FP-cancellation case
        mat[:, 1] = 0.005        # another constant
        mat[:, 2] = np.tile([0.01, -0.01], T // 2)   # real variance
        sums, sumsq, counts, ids = self._make_block_stats(mat, S=4)
        sharpes = _sharpes_from_stats(ids, sums, sumsq, counts)
        assert np.isnan(sharpes[0]), "constant-0.001 column must yield NaN Sharpe (FP-cancellation case)"
        assert np.isnan(sharpes[1]), "constant-0.005 column must yield NaN Sharpe"
        assert np.isfinite(sharpes[2]), "real-variance column must survive"

    def test_realistic_tiny_variance_survives(self):
        """A combo with std ~100x smaller than peers but genuinely non-zero keeps finite Sharpe.

        Returns at mean ≈ std ≈ 1e-4: var_pop/mean_sq ≈ 0.5 >> 1e-12 → not zapped.
        """
        T = 64
        rng = np.random.default_rng(42)
        mat = np.zeros((T, 3))
        mat[:, 0] = rng.normal(0.01, 0.01, T)    # normal-scale combo
        mat[:, 1] = rng.normal(0.01, 0.01, T)    # normal-scale combo
        # tiny-variance combo: std ≈ 1e-4, mean ≈ 1e-4 → Sharpe ≈ 1, var is real
        mat[:, 2] = rng.normal(1e-4, 1e-4, T)
        sums, sumsq, counts, ids = self._make_block_stats(mat, S=4)
        sharpes = _sharpes_from_stats(ids, sums, sumsq, counts)
        assert np.isfinite(sharpes[2]), (
            "tiny-but-real variance combo must keep a finite Sharpe — guard must NOT zap it"
        )

    def test_constant_combo_gets_nan_sharpe_and_never_selected(self):
        """End-to-end: a constant combo is NEVER chosen IS-best → pbo is NOT forced to 0.

        4 noise combos + 1 constant combo (col 4 = 0.001 daily) assembled into a
        5-column matrix. With S=4 (6 partitions) we inspect every partition's
        nanargmax to confirm the constant combo (idx 4) is never selected.
        Also confirms pbo is a genuine measurement, not an artefact of the guard
        being missing (was ~5e7 Sharpe with the exact-zero bug).
        """
        T = 32
        rng = np.random.default_rng(99)
        mat = np.zeros((T, 5))
        for j in range(4):
            mat[:, j] = rng.standard_normal(T) * 0.01
        mat[:, 4] = 0.001    # constant — the formerly-broken case

        S = 4
        sums, sumsq, counts = _block_stats(mat, S)
        all_ids = list(range(S))
        half = S // 2
        import itertools
        for is_ids in itertools.combinations(all_ids, half):
            is_sr = _sharpes_from_stats(list(is_ids), sums, sumsq, counts)
            assert np.isnan(is_sr[4]), "constant combo must have NaN IS Sharpe"
            # nanargmax will pick from the 4 noise combos, never idx 4
            best = int(np.nanargmax(is_sr))
            assert best != 4, f"constant combo (idx 4) must never be IS-best, got {best}"

        # Full PBO run — pbo should NOT be 0.0 (that would indicate the bug is back)
        res = compute_pbo(mat, S=S)
        # With pure noise combos winning every partition, pbo > 0 is expected
        # (overfitting detector working correctly); the key assertion is pbo != 0 or
        # prob_oos_loss != 0, meaning the constant didn't capture every partition.
        # In practice noise pbo is well above 0 but we allow any non-silently-forced value:
        assert res["n_partitions"] == 6
        # The constant combo must not have silently set pbo=0.0 with prob_oos_loss=0.0
        # simultaneously (that was the failure mode).  At least one metric must differ.
        both_zero = (res["pbo"] == 0.0 and res["prob_oos_loss"] == 0.0)
        assert not both_zero, (
            "pbo=0.0 AND prob_oos_loss=0.0 simultaneously indicates the constant combo "
            "silently won every partition — the FP-cancellation bug is not fixed"
        )
