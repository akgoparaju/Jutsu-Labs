"""DB-free unit tests for the PBO/CSCV math (Module 3)."""
from math import comb

import numpy as np
import pytest

from jutsu_engine.audit.pbo import split_blocks, partition_sharpes, N_CHOOSE_HALF


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
