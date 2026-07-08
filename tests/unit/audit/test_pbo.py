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
