"""DB-free unit tests for the Deflated Sharpe Ratio math (Module 3)."""
import math

import numpy as np
import pytest

from jutsu_engine.audit.dsr import psr
from jutsu_engine.audit.dsr import expected_max_sharpe
from jutsu_engine.audit.dsr import (
    sample_moments, deflated_sharpe, DEFAULT_N_BRACKETS,
    deflated_sharpe_brackets,
)


class TestPSR:
    def test_symmetric_normal_reference(self):
        """PSR(SR*=0) for SR_obs=0.5, T=101, normal returns matches hand value."""
        # num=(0.5-0)*sqrt(100)=5.0; den=sqrt(1 - 0*0.5 + (2/4)*0.25)=sqrt(1.0625)=1.03078...
        # Wait: (g4-1)/4 = (3-1)/4 = 0.5; 0.5*0.25=0.125; den=sqrt(1.125)=1.06066; z=4.71405
        got = psr(sr_obs=0.5, sr_star=0.0, T=101, skew=0.0, kurt_nonexcess=3.0)
        assert got == pytest.approx(0.9999987858, abs=1e-9)

    def test_nonnormal_small_T_reference(self):
        """PSR with negative skew, fat tails, small T matches hand value."""
        # num=(0.1-0)*sqrt(9)=0.3; den=sqrt(1 -(-0.5)(0.1)+((4-1)/4)(0.01))
        #    =sqrt(1+0.05+0.0075)=sqrt(1.0575)=1.02835; z=0.291730; PSR=0.6147534586
        got = psr(sr_obs=0.1, sr_star=0.0, T=10, skew=-0.5, kurt_nonexcess=4.0)
        assert got == pytest.approx(0.6147534586, abs=1e-9)

    def test_sr_obs_equal_sr_star_is_half(self):
        """When SR_obs == SR*, the numerator is 0 so PSR = Φ(0) = 0.5."""
        got = psr(sr_obs=0.3, sr_star=0.3, T=200, skew=0.0, kurt_nonexcess=3.0)
        assert got == pytest.approx(0.5, abs=1e-12)

    def test_small_T_guard(self):
        """T < 2 has no √(T−1); raise a clear ValueError."""
        with pytest.raises(ValueError, match="T must be >= 2"):
            psr(sr_obs=0.5, sr_star=0.0, T=1, skew=0.0, kurt_nonexcess=3.0)

    def test_nonpositive_variance_guard(self):
        """A skew/kurtosis combo making the denominator radicand <= 0 raises."""
        # 1 - g3*SR + ((g4-1)/4)*SR^2 <= 0 is pathological; guard against sqrt of <=0.
        with pytest.raises(ValueError, match="non-positive"):
            psr(sr_obs=1.0, sr_star=0.0, T=100, skew=10.0, kurt_nonexcess=3.0)


class TestExpectedMaxSharpe:
    def test_reference_N243_V001(self):
        """SR* for N=243, V=0.01 matches the hand-computed value."""
        # Φ⁻¹(1-1/243)=2.6424666; Φ⁻¹(1-1/(243e))=2.9648999; γ=0.5772157
        # SR* = 0.1*((0.4227843)(2.6424666)+(0.5772157)(2.9648999)) = 0.28285802
        got = expected_max_sharpe(V=0.01, N=243)
        assert got == pytest.approx(0.28285802, abs=1e-7)

    def test_reference_N1000(self):
        """SR* grows with N (more trials → higher expected max) — N=1000."""
        got = expected_max_sharpe(V=0.01, N=1000)
        assert got == pytest.approx(0.32551215, abs=1e-7)

    def test_reference_N5000(self):
        """SR* for the widest bracket N=5000."""
        got = expected_max_sharpe(V=0.01, N=5000)
        assert got == pytest.approx(0.36877031, abs=1e-7)

    def test_monotone_in_N(self):
        """More trials → strictly higher expected max Sharpe at fixed V."""
        a = expected_max_sharpe(V=0.01, N=243)
        b = expected_max_sharpe(V=0.01, N=1000)
        c = expected_max_sharpe(V=0.01, N=5000)
        assert a < b < c

    def test_scales_with_sqrt_V(self):
        """SR* scales as √V: quadrupling V doubles SR* at fixed N."""
        base = expected_max_sharpe(V=0.01, N=1000)
        quad = expected_max_sharpe(V=0.04, N=1000)
        assert quad == pytest.approx(2.0 * base, rel=1e-9)

    def test_N_one_guard(self):
        """N=1 has no selection (Φ⁻¹(0) = −∞); raise a clear ValueError."""
        with pytest.raises(ValueError, match="N must be >= 2"):
            expected_max_sharpe(V=0.01, N=1)

    def test_negative_variance_guard(self):
        """Cross-trial variance V must be non-negative."""
        with pytest.raises(ValueError, match="V must be >= 0"):
            expected_max_sharpe(V=-0.01, N=100)

    def test_N_ceiling_guard(self):
        """N > 10**12 causes Phi-inverse to degenerate; raise a clear ValueError."""
        with pytest.raises(ValueError, match="N too large"):
            expected_max_sharpe(V=0.01, N=10 ** 12 + 1)


class TestSampleMoments:
    def test_skew_and_nonexcess_kurtosis(self):
        """sample_moments returns per-period Sharpe, γ₃ skew, γ₄ NON-excess kurtosis."""
        data = np.array([0.01, -0.02, 0.015, -0.005, 0.03,
                         -0.01, 0.02, -0.015, 0.005, 0.01])
        m = sample_moments(data)
        # scipy skew(bias=False) and kurtosis(fisher=True,bias=False)+3:
        assert m["skew"] == pytest.approx(-0.023853, abs=1e-5)
        assert m["kurt_nonexcess"] == pytest.approx(2.040487, abs=1e-5)
        # non-excess kurtosis is excess + 3; normal-ish data ⇒ near 3 minus platykurtic
        assert m["T"] == 10

    def test_zero_variance_raises(self):
        """A constant series has zero std → Sharpe undefined; raise."""
        with pytest.raises(ValueError, match="zero variance"):
            sample_moments(np.array([0.01, 0.01, 0.01, 0.01]))


class TestDeflatedSharpe:
    def test_end_to_end_reference(self):
        """DSR end-to-end for a synthetic golden series matches the hand value."""
        # Build a daily series with per-period Sharpe = 0.8/sqrt(252) = 0.05039526,
        # skew≈0, non-excess kurt≈3, T=4100; N=243, V=0.0004 ⇒ SR*=0.0565716.
        rng = np.random.default_rng(7)
        T = 4100
        target_daily_sr = 0.8 / np.sqrt(252)
        # scale a standard normal to mean/std giving the target Sharpe
        base = rng.standard_normal(T)
        base = (base - base.mean()) / base.std(ddof=1)   # exact 0 mean, unit std
        returns = 0.01 * base + 0.01 * target_daily_sr   # std≈0.01, mean=0.01*SR*std
        d = deflated_sharpe(returns, N=243, V=0.0004)
        assert d["sr_star"] == pytest.approx(0.0565716, abs=1e-6)
        # DSR ≈ 0.346 for this configuration (SR_obs ≈ SR*, so DSR near 0.5·… < 0.5)
        assert 0.30 <= d["dsr"] <= 0.42
        assert d["sr_obs"] == pytest.approx(target_daily_sr, abs=1e-3)

    def test_high_sharpe_low_N_gives_high_dsr(self):
        """A genuinely high Sharpe with few trials survives deflation (DSR→1)."""
        rng = np.random.default_rng(1)
        T = 2000
        base = rng.standard_normal(T)
        base = (base - base.mean()) / base.std(ddof=1)
        # per-period Sharpe ≈ 0.2 (very high daily) with N=2 trials
        returns = 0.01 * base + 0.01 * 0.2
        d = deflated_sharpe(returns, N=2, V=0.0001)
        assert d["dsr"] > 0.99

    def test_dsr_brackets_shape(self):
        """deflated_sharpe_brackets returns one row per bracketed N, DSR falling with N."""
        rng = np.random.default_rng(3)
        base = rng.standard_normal(3000)
        base = (base - base.mean()) / base.std(ddof=1)
        returns = 0.01 * base + 0.01 * 0.08
        rows = deflated_sharpe_brackets(returns, N_values=DEFAULT_N_BRACKETS, V=0.0004)
        assert [r["N"] for r in rows] == list(DEFAULT_N_BRACKETS)
        # DSR is monotone non-increasing in N (more trials → more deflation)
        dsrs = [r["dsr"] for r in rows]
        assert dsrs == sorted(dsrs, reverse=True)

    def test_brackets_V_required(self):
        """deflated_sharpe_brackets requires V; omitting it raises TypeError."""
        rng = np.random.default_rng(9)
        returns = 0.01 * rng.standard_normal(500)
        with pytest.raises(TypeError):
            deflated_sharpe_brackets(returns)
