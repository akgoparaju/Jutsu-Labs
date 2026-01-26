# Regime Cell Overlay on Equity Curve - Implementation Plan

**Date:** 2026-01-19
**Status:** ✅ IMPLEMENTED
**Target Strategy:** Hierarchical_Adaptive_v3_5b (already has `get_current_regime()`)

---

## Overview

Add colored background bands to the equity curve visualization showing which regime cell (1-6) was active during each time period. This enables visual correlation between portfolio performance and market regime.

---

## Prerequisites

- Strategy must implement `get_current_regime()` method
- v3_5b, v3_5c, v3_6, v3_8, v4_0 already support this
- Portfolio CSV must have Regime, Trend, Vol columns (auto-generated when strategy supports regime tracking)

---

## Implementation Tasks

### Task 1: Add Regime Color Constants to EquityPlotter

**File:** `jutsu_engine/infrastructure/visualization/equity_plotter.py`

**Location:** Add after imports, before class definition

```python
# Regime cell color palette (semi-transparent for overlay)
REGIME_COLORS = {
    1: 'rgba(34, 139, 34, 0.18)',   # Forest green - Bull/Low Vol
    2: 'rgba(144, 238, 144, 0.18)', # Light green - Bull/High Vol
    3: 'rgba(255, 215, 0, 0.18)',   # Gold - Sideways/Low Vol
    4: 'rgba(255, 165, 0, 0.18)',   # Orange - Sideways/High Vol
    5: 'rgba(255, 140, 0, 0.18)',   # Dark orange - Bear/Low Vol
    6: 'rgba(220, 20, 60, 0.18)',   # Crimson - Bear/High Vol
}

REGIME_LABELS = {
    1: 'Cell 1: Bull/Low',
    2: 'Cell 2: Bull/High',
    3: 'Cell 3: Sideways/Low',
    4: 'Cell 4: Sideways/High',
    5: 'Cell 5: Bear/Low',
    6: 'Cell 6: Bear/High',
}
```

---

### Task 2: Modify `_load_and_validate_data()` to Detect Regime Column

**File:** `jutsu_engine/infrastructure/visualization/equity_plotter.py`

**Location:** End of `_load_and_validate_data()` method

```python
# Detect regime column for overlay support
self._has_regime_data = 'Regime' in self._df.columns
if self._has_regime_data:
    logger.info("Regime data detected in CSV - overlay will be available")
else:
    logger.debug("No Regime column in CSV - overlay will be skipped")
```

---

### Task 3: Add New Method `_get_regime_spans()`

**File:** `jutsu_engine/infrastructure/visualization/equity_plotter.py`

**Location:** Add as new method in EquityPlotter class

```python
def _get_regime_spans(self) -> List[Tuple[datetime, datetime, int]]:
    """
    Consolidate consecutive days with same regime into spans.

    Processes the Regime column (format: 'Cell_X') and groups consecutive
    days with the same regime into single spans for efficient visualization.

    Returns:
        List of (start_date, end_date, regime_cell) tuples
        Empty list if no regime data available

    Example:
        [(datetime(2020,1,1), datetime(2020,1,15), 1),
         (datetime(2020,1,16), datetime(2020,2,1), 3),
         ...]
    """
    if not self._has_regime_data:
        return []

    # Parse regime cell number from 'Cell_X' format
    df = self._df.copy()
    df['regime_num'] = df['Regime'].str.extract(r'Cell_(\d+)').astype(float)

    spans = []
    current_regime = None
    span_start = None
    prev_date = None

    for _, row in df.iterrows():
        regime = row.get('regime_num')
        if pd.isna(regime):
            continue
        regime = int(regime)

        if regime != current_regime:
            # Close previous span
            if current_regime is not None:
                spans.append((span_start, prev_date, current_regime))
            # Start new span
            current_regime = regime
            span_start = row['Date']
        prev_date = row['Date']

    # Close final span
    if current_regime is not None:
        spans.append((span_start, prev_date, current_regime))

    logger.info(f"Identified {len(spans)} regime spans for overlay")
    return spans
```

**Note:** Add `from typing import Tuple` to imports if not already present.

---

### Task 4: Modify `generate_equity_curve()` to Add Regime Overlay

**File:** `jutsu_engine/infrastructure/visualization/equity_plotter.py`

**Changes:**

1. **Update method signature:**
```python
def generate_equity_curve(
    self,
    filename: str = 'equity_curve.html',
    include_baseline: bool = True,
    show_regime_overlay: bool = True  # NEW PARAMETER
) -> Path:
```

2. **Update docstring** - add parameter description:
```python
    Args:
        filename: Output filename for HTML plot
        include_baseline: Whether to include baseline comparison traces
        show_regime_overlay: Whether to show colored regime cell backgrounds (default: True)
            Requires Regime column in CSV. If not available, silently skips.
```

3. **Add regime overlay code** - insert AFTER `fig = go.Figure()` and BEFORE adding traces:
```python
# Add regime overlay (behind the lines)
if show_regime_overlay and self._has_regime_data:
    spans = self._get_regime_spans()
    added_regimes = set()  # Track which regimes we've added to avoid duplicate legends

    for start_date, end_date, regime in spans:
        # Add vertical rectangle for this regime period
        show_legend = regime not in added_regimes

        fig.add_vrect(
            x0=start_date,
            x1=end_date,
            fillcolor=REGIME_COLORS.get(regime, 'rgba(128,128,128,0.1)'),
            layer='below',
            line_width=0,
        )

        # Add invisible trace for legend entry (only first occurrence of each regime)
        if show_legend:
            fig.add_trace(go.Scatter(
                x=[None],
                y=[None],
                mode='markers',
                marker=dict(
                    size=15,
                    color=REGIME_COLORS.get(regime, 'rgba(128,128,128,0.3)'),
                    symbol='square'
                ),
                name=REGIME_LABELS.get(regime, f'Cell {regime}'),
                showlegend=True,
                legendgroup='regime'
            ))
            added_regimes.add(regime)

    logger.info(f"Added {len(spans)} regime overlay spans ({len(added_regimes)} unique regimes)")
```

---

### Task 5: Update Tests

**File:** `tests/unit/infrastructure/test_visualization.py`

**Add new test class:**

```python
class TestEquityPlotterRegimeOverlay:
    """Tests for regime overlay functionality in EquityPlotter."""

    @pytest.fixture
    def sample_csv_with_regime(self, tmp_path):
        """Create sample CSV with Regime column."""
        data = {
            'Date': pd.date_range('2020-01-01', periods=100, freq='D'),
            'Portfolio_Total_Value': np.cumsum(np.random.randn(100) * 100) + 10000,
            'Regime': ['Cell_1'] * 30 + ['Cell_3'] * 40 + ['Cell_5'] * 30,
            'Trend': ['BullStrong'] * 30 + ['Sideways'] * 40 + ['BearStrong'] * 30,
            'Vol': ['Low'] * 50 + ['High'] * 50,
            'Baseline_QQQ_Value': np.cumsum(np.random.randn(100) * 80) + 10000,
            'Baseline_QQQ_Return_Pct': np.random.randn(100) * 0.02,
            'Cash': [1000] * 100,
        }
        df = pd.DataFrame(data)
        csv_path = tmp_path / 'portfolio_with_regime.csv'
        df.to_csv(csv_path, index=False)
        return csv_path

    @pytest.fixture
    def sample_csv_without_regime(self, tmp_path):
        """Create sample CSV without Regime column."""
        data = {
            'Date': pd.date_range('2020-01-01', periods=100, freq='D'),
            'Portfolio_Total_Value': np.cumsum(np.random.randn(100) * 100) + 10000,
            'Baseline_QQQ_Value': np.cumsum(np.random.randn(100) * 80) + 10000,
            'Baseline_QQQ_Return_Pct': np.random.randn(100) * 0.02,
            'Cash': [1000] * 100,
        }
        df = pd.DataFrame(data)
        csv_path = tmp_path / 'portfolio_no_regime.csv'
        df.to_csv(csv_path, index=False)
        return csv_path

    def test_regime_overlay_with_regime_data(self, sample_csv_with_regime, tmp_path):
        """Verify regime overlay is added when Regime column exists."""
        plotter = EquityPlotter(
            csv_path=sample_csv_with_regime,
            output_dir=tmp_path
        )

        assert plotter._has_regime_data is True

        output_path = plotter.generate_equity_curve(show_regime_overlay=True)
        assert output_path.exists()

        # Verify HTML contains regime-related content
        content = output_path.read_text()
        assert 'Cell 1' in content or 'Bull/Low' in content

    def test_regime_overlay_disabled(self, sample_csv_with_regime, tmp_path):
        """Verify overlay can be disabled even with Regime data."""
        plotter = EquityPlotter(
            csv_path=sample_csv_with_regime,
            output_dir=tmp_path
        )

        output_path = plotter.generate_equity_curve(show_regime_overlay=False)
        assert output_path.exists()

    def test_no_regime_data_graceful_handling(self, sample_csv_without_regime, tmp_path):
        """Verify no error when Regime column missing."""
        plotter = EquityPlotter(
            csv_path=sample_csv_without_regime,
            output_dir=tmp_path
        )

        assert plotter._has_regime_data is False

        # Should not raise error
        output_path = plotter.generate_equity_curve(show_regime_overlay=True)
        assert output_path.exists()

    def test_get_regime_spans_consolidation(self, sample_csv_with_regime, tmp_path):
        """Verify regime spans are correctly consolidated."""
        plotter = EquityPlotter(
            csv_path=sample_csv_with_regime,
            output_dir=tmp_path
        )

        spans = plotter._get_regime_spans()

        # Should have 3 spans based on fixture data
        assert len(spans) == 3

        # Verify span structure
        for start, end, regime in spans:
            assert isinstance(regime, int)
            assert 1 <= regime <= 6
            assert start <= end
```

---

### Task 6: Validation with Real Grid Search

After implementation:

1. Run a grid search with v3_5b:
```bash
jutsu grid-search --config grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5b.yaml
```

2. Verify output:
   - Check portfolio CSV has Regime, Trend, Vol columns
   - Open equity_curve.html in browser
   - Verify colored bands appear behind equity line
   - Test zoom/pan functionality
   - Verify legend shows regime cells

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `jutsu_engine/infrastructure/visualization/equity_plotter.py` | Modify | Add regime overlay constants, detection, spans method, and overlay rendering |
| `tests/unit/infrastructure/test_visualization.py` | Add | New test class for regime overlay |

---

## Architecture Notes

- **Layer:** Infrastructure (visualization)
- **Dependencies:** None new (uses existing Plotly)
- **Backward Compatibility:** Full - overlay simply skipped if no Regime column
- **Performance Target:** <1s additional overhead for 4000+ bar backtest

---

## Color Palette Rationale

| Cell | Color | Hex | Rationale |
|------|-------|-----|-----------|
| 1 | Forest Green | `#228B22` | Strong bull = confident green |
| 2 | Light Green | `#90EE90` | Bull with caution = lighter green |
| 3 | Gold | `#FFD700` | Sideways/neutral = yellow |
| 4 | Orange | `#FFA500` | Sideways with volatility = warning orange |
| 5 | Dark Orange | `#FF8C00` | Bear onset = deeper orange |
| 6 | Crimson | `#DC143C` | Bear crisis = red danger |

Alpha of 0.18 provides visibility without obscuring the equity line.

---

## Related Files Reference

- `jutsu_engine/performance/portfolio_exporter.py` - Exports Regime columns to CSV
- `jutsu_engine/performance/regime_analyzer.py` - Collects regime data during backtest
- `jutsu_engine/application/backtest_runner.py` - Coordinates regime data flow
- `jutsu_engine/core/event_loop.py` - Calls `regime_analyzer.record_bar()`

---

## Estimated Effort

| Task | Time |
|------|------|
| Task 1: Color constants | 10 min |
| Task 2: Detection in load | 10 min |
| Task 3: `_get_regime_spans()` | 30 min |
| Task 4: Modify `generate_equity_curve()` | 45 min |
| Task 5: Tests | 45 min |
| Task 6: Validation | 20 min |
| **Total** | **~2.5 hours** |
