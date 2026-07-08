"""Module 3 — Probability of Backtest Overfitting via CSCV (Bailey et al.).

Pure numpy over a T×N returns matrix (T daily observations, N grid combos). NO
database. Deterministic (no RNG): the CSCV partition set is fully enumerated.

CSCV procedure (spec §7, S=16 blocks):
  1. Split the T rows into S contiguous time blocks.
  2. For every way to choose S/2 blocks as IN-SAMPLE (the other S/2 are OUT-of-
     SAMPLE) — that is C(S, S/2) partitions (C(16,8) = 12,870):
       a. rank all N combos by IS Sharpe, take the IS-best (n*).
       b. find n*'s OOS relative rank ω̄ ∈ [0,1]: the fraction of combos it BEATS
          out-of-sample (0 = worst OOS, 1 = best OOS).
          Convention: beaten = strictly lower OOS Sharpe; NaN counts as not-beaten.
          ω̄ = (# combos with strictly lower OOS Sharpe) / (N − 1)
       c. logit λ = ln(ω̄ / (1−ω̄)), clamped at ±_LOGIT_EPS to avoid ±∞.
  3. PBO = fraction of partitions where the IS-best lands in the BOTTOM HALF OOS,
     i.e. ω̄ < 0.5  ⟺  λ < 0.
     Tie convention: ω̄ exactly 0.5 is counted as NOT overfitting (ω̄ < 0.5 is False
     when ω̄ == 0.5), matching the strict inequality in the plan's definition.

Memory note: the plan calls for block-level precomputation of per-block sums and
sum-of-squares per combo so per-partition Sharpe is O(combos × blocks), not
O(combos × days). This is implemented in _block_stats + _sharpes_from_stats.
The full-matrix partition_sharpes generator uses this precomputation.
"""
from __future__ import annotations

import itertools
from math import comb

import numpy as np


def N_CHOOSE_HALF(S: int) -> int:
    """Number of CSCV partitions for S blocks: C(S, S/2)."""
    return comb(S, S // 2)


def split_blocks(T: int, S: int) -> list[np.ndarray]:
    """Split row indices [0, T) into S contiguous, near-equal blocks.

    Uses numpy.array_split so blocks stay contiguous and cover every row exactly
    once even when T is not divisible by S. Raises ValueError if T < S.
    """
    if T < S:
        raise ValueError(f"need at least S={S} rows to make S blocks (got T={T})")
    return [np.asarray(b) for b in np.array_split(np.arange(T), S)]


def _block_stats(matrix: np.ndarray, S: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Precompute per-block (sum, sum-of-squares, count) for every combo.

    Returns:
      sums:   shape (S, N) — column sums within each block.
      sumsq:  shape (S, N) — column sums-of-squares within each block.
      counts: shape (S,)   — number of rows in each block (int).

    These allow per-partition Sharpe to be computed in O(combos × S) rather than
    O(combos × T) — the precomputation trick the plan specifies.
    """
    T, N = matrix.shape
    blocks = split_blocks(T, S)
    sums = np.empty((S, N), dtype=float)
    sumsq = np.empty((S, N), dtype=float)
    counts = np.empty(S, dtype=int)
    for i, blk in enumerate(blocks):
        sub = matrix[blk]
        sums[i] = sub.sum(axis=0)
        sumsq[i] = (sub ** 2).sum(axis=0)
        counts[i] = len(blk)
    return sums, sumsq, counts


def _sharpes_from_stats(
    block_ids: list[int],
    sums: np.ndarray,
    sumsq: np.ndarray,
    counts: np.ndarray,
) -> np.ndarray:
    """Compute per-combo Sharpe for a set of blocks from precomputed stats.

    Uses the parallel formula: mean = sum/n, var = sumsq/n − mean^2, std (ddof=1)
    = sqrt(max(var*n/(n-1), 0)).  Columns with zero std get NaN Sharpe.
    """
    n = int(counts[block_ids].sum())
    if n < 2:
        # Cannot compute ddof=1 std with fewer than 2 observations.
        N = sums.shape[1]
        return np.full(N, np.nan)
    s = sums[block_ids].sum(axis=0)          # shape (N,)
    sq = sumsq[block_ids].sum(axis=0)        # shape (N,)
    mean = s / n
    # population variance from block stats; correct to sample variance (ddof=1)
    var_pop = sq / n - mean ** 2
    var_samp = np.maximum(var_pop * n / (n - 1), 0.0)
    std = np.sqrt(var_samp)
    std = np.where(std == 0.0, np.nan, std)
    return mean / std


def partition_sharpes(matrix: np.ndarray, S: int = 16):
    """Yield (IS_sharpe_vec, OOS_sharpe_vec) for every CSCV IS/OOS partition.

    matrix: shape (T, N). Splits into S contiguous blocks and enumerates all
    C(S, S/2) ways to assign half the blocks to IS (rest OOS). Each yielded pair
    is two length-N Sharpe vectors (IS and OOS) over the concatenated block rows.

    Enumeration order: itertools.combinations(range(S), S//2) — deterministic.
    Block-level precomputation: O(combos × S) per partition (not O(combos × T)).
    """
    T = matrix.shape[0]
    sums, sumsq, counts = _block_stats(matrix, S)
    all_ids = list(range(S))
    half = S // 2
    for is_ids in itertools.combinations(all_ids, half):
        oos_ids = [b for b in all_ids if b not in set(is_ids)]
        is_sr = _sharpes_from_stats(list(is_ids), sums, sumsq, counts)
        oos_sr = _sharpes_from_stats(oos_ids, sums, sumsq, counts)
        yield is_sr, oos_sr


# ---------------------------------------------------------------------------
# ω̄ / logit helpers — exposed for direct test access.
# ---------------------------------------------------------------------------

# Clamp bound so ω̄ ∈ {0, 1} does not blow up the logit.
_LOGIT_EPS = 1e-6


def relative_rank(oos_sharpes: np.ndarray, best_idx: int) -> float:
    """OOS relative rank ω̄ of the IS-best combo: fraction of OTHER combos it beats.

    ω̄ = (# combos with strictly lower OOS Sharpe) / (N − 1).
    Convention:
      - 1.0 = OOS-best (beats all N−1 others).
      - 0.0 = OOS-worst (beats none).
      - NaN OOS Sharpes count as not-beaten (NaN < ref is False in numpy).
      - Ties (equal OOS Sharpe, non-NaN) also count as not-beaten (strict <).
    """
    n = oos_sharpes.shape[0]
    if n < 2:
        return 0.0
    ref = oos_sharpes[best_idx]
    beaten = np.sum(oos_sharpes < ref)          # NaN < ref is False → not beaten
    return float(beaten) / (n - 1)


def logit(omega: float) -> float:
    """Logit of a relative rank, clamped to avoid ±∞ at ω̄ ∈ {0,1}."""
    w = min(max(omega, _LOGIT_EPS), 1.0 - _LOGIT_EPS)
    return float(np.log(w / (1.0 - w)))


def compute_pbo(matrix: np.ndarray, S: int = 16) -> dict:
    """Probability of Backtest Overfitting + diagnostics over a T×N returns matrix.

    For each CSCV partition (C(S, S/2) total):
      - pick the IS-best combo n* (highest IS Sharpe, nanargmax).
      - record ω̄ = relative_rank(oos_sharpes, n*).
      - record λ = logit(ω̄).
      - record whether n*'s OOS Sharpe ≤ 0 (an OOS loss).
      - record (IS Sharpe of n*, OOS Sharpe of n*) for degradation regression.

    PBO = fraction of partitions with ω̄ < 0.5 (equivalently λ < 0).
    Tie convention: ω̄ == 0.5 is NOT counted as overfitting (strict inequality).

    Returns dict:
      pbo               — fraction of partitions with ω̄ < 0.5.
      prob_oos_loss     — fraction of partitions where the IS-best has OOS Sharpe ≤ 0.
      degradation_slope — OLS slope of OOS Sharpe (y) on IS Sharpe (x) across the
                          IS-best of every partition. 1.0 = perfect carry-over;
                          <1 = degradation; 0.0 if IS Sharpes have no variance.
      logits            — list of per-partition logit values (the λ distribution).
      n_partitions      — C(S, S/2).

    Raises ValueError if N < 2 (nothing to rank).
    """
    if matrix.shape[1] < 2:
        raise ValueError("PBO needs at least 2 combos to rank")

    logits: list[float] = []
    oos_losses = 0
    is_best_is_sr: list[float] = []
    is_best_oos_sr: list[float] = []
    n_part = 0

    for is_sr, oos_sr in partition_sharpes(matrix, S=S):
        n_part += 1
        n_star = int(np.nanargmax(is_sr))        # IS-best combo index
        omega = relative_rank(oos_sr, n_star)
        logits.append(logit(omega))
        oos_val = oos_sr[n_star]
        if not np.isnan(oos_val) and oos_val <= 0.0:
            oos_losses += 1
        is_best_is_sr.append(float(is_sr[n_star]))
        is_best_oos_sr.append(float(oos_val) if not np.isnan(oos_val) else 0.0)

    logits_arr = np.asarray(logits)
    pbo = float(np.mean(logits_arr < 0.0))
    prob_oos_loss = float(oos_losses) / n_part

    # Degradation slope: OLS of OOS Sharpe (y) on IS Sharpe (x) across partitions.
    x = np.asarray(is_best_is_sr)
    y = np.asarray(is_best_oos_sr)
    if np.ptp(x) > 0:
        slope = float(np.polyfit(x, y, 1)[0])
    else:
        slope = 0.0

    return {
        "pbo": pbo,
        "prob_oos_loss": prob_oos_loss,
        "degradation_slope": slope,
        "logits": logits,
        "n_partitions": n_part,
    }
