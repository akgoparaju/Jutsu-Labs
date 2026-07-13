"""Hierarchical Adaptive v3.5b — vol-input ablation adapter (DIAGNOSTIC ONLY).

Subclasses v3.5b and blends a PRECOMPUTED vol-input series into the vol-z step. This
strategy exists solely for the EXP-007 ablation battery; it is NEVER referenced by a
live YAML or the scheduler. Arms differ only by which series CSV is injected.

Behavior: at the vol-z step, blended = (1-w)*vol_z + w*series[date]. If the series has
no finite value for the current bar's date (warmup/gap) or the base vol_z is None,
fall back to pure vol_z (== stock v3.5b). Hysteresis thresholds and all other logic
and parameters are untouched.

IDENTITY GUARANTEE: with vol_input_series=None the subclass produces a bit-identical
regime stream to stock v3.5b over the full period (enforced by the identity regression
test — the adapter's most important test).

Construction: the battery harness constructs this class DIRECTLY (not via a live YAML).
The two new params are passed explicitly. vol_blend_weight is a Decimal; if the harness
ever routes it through the LiveStrategyRunner/plateau float->Decimal bridge, add it to
that DECIMAL_PARAMS set — but the battery keeps construction explicit (Task 11), so the
Decimal is supplied directly here.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import (
    Hierarchical_Adaptive_v3_5b,
)


class Hierarchical_Adaptive_v3_5b_VolInput(Hierarchical_Adaptive_v3_5b):
    """v3.5b + precomputed vol-input blend at the vol-z step (ablation only)."""

    def __init__(self, *args,
                 vol_input_series: Optional[str] = None,
                 vol_blend_weight: Decimal = Decimal("0.5"),
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.vol_input_series = vol_input_series
        self.vol_blend_weight = (vol_blend_weight if isinstance(vol_blend_weight, Decimal)
                                 else Decimal(str(vol_blend_weight)))
        # date -> float value map (NaN allowed); empty when no series.
        self._vol_series_map: dict[date, float] = {}
        if vol_input_series is not None:
            self._vol_series_map = self._load_series_map(Path(vol_input_series))

    @staticmethod
    def _load_series_map(path: Path) -> dict[date, float]:
        """Parse a builder CSV (comment header + date,value,...) to a date->float map."""
        df = pd.read_csv(path, comment="#")
        out: dict[date, float] = {}
        for _, r in df.iterrows():
            d = pd.Timestamp(r["date"]).date()
            out[d] = float(r["value"])
        return out

    def _calculate_volatility_zscore(self, closes: pd.Series) -> Optional[Decimal]:
        """Engine-truth vol_z, then blend the injected series value for the bar's date.

        The base class returns the production vol_z (or None during warmup). We read
        the current signal-symbol bar's date from self._bars[-1].timestamp (closes has
        an integer index and no date). If a finite series value exists for that date,
        blend it; otherwise (warmup/gap/None base) return the base value unchanged.
        """
        base = super()._calculate_volatility_zscore(closes)
        if base is None or not self._vol_series_map or not self._bars:
            return base
        d = self._bars[-1].timestamp
        d = d.date() if hasattr(d, "date") else d
        val = self._vol_series_map.get(d)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return base                                  # warmup/gap -> pure vol_z
        w = self.vol_blend_weight
        return (Decimal("1") - w) * base + w * Decimal(str(val))
