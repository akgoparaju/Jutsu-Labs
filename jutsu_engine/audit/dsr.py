"""Module 3 — Deflated Sharpe Ratio math (Bailey & López de Prado).

Pure functions over per-period Sharpe inputs. NO database, NO backtest — the
returns campaign (selection_bias.py) supplies the daily-return series; this file
turns them into DSR/PSR numbers. All Sharpes are in PER-PERIOD units (daily here),
skewness is γ₃, kurtosis is γ₄ (NON-EXCESS, i.e. normal == 3.0), T is the number
of observations.

Formulas (spelled out so implementers never guess):

  PSR(SR*) = Φ( ((SR_obs − SR*)·√(T−1))
                / √(1 − γ₃·SR_obs + ((γ₄−1)/4)·SR_obs²) )

  SR*  = √V · ((1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)))     (expected max Sharpe
         under N independent trials with cross-trial Sharpe variance V; γ is the
         Euler–Mascheroni constant ≈ 0.5772)

  DSR  = PSR(SR*)
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm
from scipy.stats import skew as _scipy_skew, kurtosis as _scipy_kurtosis

# Standard-normal CDF (Φ) and inverse CDF / quantile (Φ⁻¹).
_Phi = norm.cdf
_Phi_inv = norm.ppf

# Euler–Mascheroni constant.
EULER_MASCHERONI: float = 0.5772156649015329

# Spec §7 bracketed trial counts. DSR is reported at each — history may be
# incomplete so N=243 is the known lower bound and 1000/5000 are conservative
# (higher) estimates that INCREASE deflation (lower DSR).
DEFAULT_N_BRACKETS: tuple[int, ...] = (243, 1000, 5000)


def psr(sr_obs: float, sr_star: float, T: int, skew: float, kurt: float) -> float:
    """Probabilistic Sharpe Ratio PSR(SR*): P(true SR > SR*) given sample moments.

    Args:
      sr_obs: observed per-period Sharpe (e.g. daily).
      sr_star: benchmark Sharpe to beat (0 for the classic PSR; SR* for DSR).
      T: number of return observations (>= 2).
      skew: γ₃, sample skewness of the returns.
      kurt: γ₄, NON-EXCESS kurtosis (normal == 3.0; excess kurtosis + 3).

    Returns Φ(z) where
      z = (sr_obs − sr_star)·√(T−1) / √(1 − γ₃·sr_obs + ((γ₄−1)/4)·sr_obs²).

    Raises ValueError if T < 2 (no √(T−1)) or the denominator radicand is
    non-positive (a pathological skew/kurtosis/SR combination).
    """
    if T < 2:
        raise ValueError(f"T must be >= 2 for PSR (got {T})")
    radicand = 1.0 - skew * sr_obs + ((kurt - 1.0) / 4.0) * (sr_obs ** 2)
    if radicand <= 0.0:
        raise ValueError(
            f"PSR denominator radicand is non-positive ({radicand:.6g}); "
            f"skew/kurtosis/SR combination is pathological "
            f"(skew={skew}, kurt={kurt}, sr_obs={sr_obs})"
        )
    z = (sr_obs - sr_star) * math.sqrt(T - 1) / math.sqrt(radicand)
    return float(_Phi(z))


def expected_max_sharpe(V: float, N: int) -> float:
    """Expected maximum Sharpe under N independent trials with cross-trial variance V.

    SR* = √V · ((1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)))

    where γ = EULER_MASCHERONI. This is the deflation benchmark the observed Sharpe
    must beat: the Sharpe you'd expect to see as the best of N tries by pure luck.

    Args:
      V: variance of the Sharpe ratios ACROSS trials (per-period units, so the
         same units as SR_obs fed to psr()). V >= 0.
      N: number of (effectively independent) trials. N >= 2 (N=1 means no
         selection: Φ⁻¹(1 − 1/1) = Φ⁻¹(0) = −∞).

    Raises ValueError for N < 2 or V < 0.
    """
    if N < 2:
        raise ValueError(f"N must be >= 2 (got {N}); N=1 means no selection")
    if V < 0:
        raise ValueError(f"V must be >= 0 (got {V})")
    g = EULER_MASCHERONI
    term = ((1.0 - g) * _Phi_inv(1.0 - 1.0 / N)
            + g * _Phi_inv(1.0 - 1.0 / (N * math.e)))
    return float(math.sqrt(V) * term)


def sample_moments(returns) -> dict:
    """Per-period Sharpe, γ₃ skew, γ₄ NON-excess kurtosis, and T from a return series.

    Uses scipy sample (bias-corrected) skewness and kurtosis. scipy's kurtosis is
    EXCESS (Fisher) by default; we add 3.0 to get NON-excess γ₄ (normal == 3.0),
    which is what the PSR formula expects.

    Raises ValueError if the series has < 2 finite points or zero variance
    (Sharpe undefined without dispersion).
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        raise ValueError(f"need >= 2 finite returns for moments (got {r.size})")
    std = r.std(ddof=1)
    if std == 0.0:
        raise ValueError("returns have zero variance; Sharpe is undefined")
    sr = float(r.mean() / std)
    g3 = float(_scipy_skew(r, bias=False))
    g4 = float(_scipy_kurtosis(r, fisher=True, bias=False)) + 3.0  # non-excess
    return {"sr_obs": sr, "skew": g3, "kurt_nonexcess": g4, "T": int(r.size)}


def deflated_sharpe(returns, N: int, V: float) -> dict:
    """Deflated Sharpe Ratio for a return series: DSR = PSR(SR*) under N trials.

    Args:
      returns: the strategy's per-period (daily) return series.
      N: number of trials for the deflation benchmark (>= 2).
      V: cross-trial Sharpe variance (per-period units, same as SR_obs).

    Returns dict: sr_obs, skew, kurt_nonexcess, T, sr_star, dsr.
    """
    m = sample_moments(returns)
    sr_star = expected_max_sharpe(V=V, N=N)
    dsr = psr(sr_obs=m["sr_obs"], sr_star=sr_star, T=m["T"],
              skew=m["skew"], kurt=m["kurt_nonexcess"])
    return {**m, "sr_star": sr_star, "dsr": dsr}


def deflated_sharpe_brackets(returns, N_values=DEFAULT_N_BRACKETS,
                             V: float = 0.0) -> list[dict]:
    """DSR at each bracketed N (spec §7: N = 243 / 1000 / 5000).

    Returns a list of {N, sr_obs, sr_star, dsr, T, skew, kurt_nonexcess} rows, one
    per N. Higher N ⇒ higher SR* ⇒ lower DSR (more deflation), so the caller can
    show the sensitivity of the DSR verdict to how many trials are assumed.
    """
    out = []
    for N in N_values:
        d = deflated_sharpe(returns, N=N, V=V)
        out.append({"N": N, **d})
    return out
