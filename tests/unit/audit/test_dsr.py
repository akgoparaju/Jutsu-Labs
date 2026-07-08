"""DB-free unit tests for the Deflated Sharpe Ratio math (Module 3)."""
import math

import pytest

from jutsu_engine.audit.dsr import psr


class TestPSR:
    def test_symmetric_normal_reference(self):
        """PSR(SR*=0) for SR_obs=0.5, T=101, normal returns matches hand value."""
        # num=(0.5-0)*sqrt(100)=5.0; den=sqrt(1 - 0*0.5 + (2/4)*0.25)=sqrt(1.0625)=1.03078...
        # Wait: (g4-1)/4 = (3-1)/4 = 0.5; 0.5*0.25=0.125; den=sqrt(1.125)=1.06066; z=4.71405
        got = psr(sr_obs=0.5, sr_star=0.0, T=101, skew=0.0, kurt=3.0)
        assert got == pytest.approx(0.9999987858, abs=1e-9)

    def test_nonnormal_small_T_reference(self):
        """PSR with negative skew, fat tails, small T matches hand value."""
        # num=(0.1-0)*sqrt(9)=0.3; den=sqrt(1 -(-0.5)(0.1)+((4-1)/4)(0.01))
        #    =sqrt(1+0.05+0.0075)=sqrt(1.0575)=1.02835; z=0.291730; PSR=0.6147534586
        got = psr(sr_obs=0.1, sr_star=0.0, T=10, skew=-0.5, kurt=4.0)
        assert got == pytest.approx(0.6147534586, abs=1e-9)

    def test_sr_obs_equal_sr_star_is_half(self):
        """When SR_obs == SR*, the numerator is 0 so PSR = Φ(0) = 0.5."""
        got = psr(sr_obs=0.3, sr_star=0.3, T=200, skew=0.0, kurt=3.0)
        assert got == pytest.approx(0.5, abs=1e-12)

    def test_small_T_guard(self):
        """T < 2 has no √(T−1); raise a clear ValueError."""
        with pytest.raises(ValueError, match="T must be >= 2"):
            psr(sr_obs=0.5, sr_star=0.0, T=1, skew=0.0, kurt=3.0)

    def test_nonpositive_variance_guard(self):
        """A skew/kurtosis combo making the denominator radicand <= 0 raises."""
        # 1 - g3*SR + ((g4-1)/4)*SR^2 <= 0 is pathological; guard against sqrt of <=0.
        with pytest.raises(ValueError, match="non-positive"):
            psr(sr_obs=1.0, sr_star=0.0, T=100, skew=10.0, kurt=3.0)
