"""
Backtest Results API Routes

GET /api/backtest/data - Get all backtest data (summary + timeseries)
GET /api/backtest/config - Get strategy config.yaml (admin only)
GET /api/backtest/regime-breakdown - Get regime performance for date range
"""

import csv
import io
import logging
import math
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any, List

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query

from jutsu_engine.api.schemas import ErrorResponse
from jutsu_engine.api.dependencies import verify_credentials, get_current_user

logger = logging.getLogger('API.BACKTEST')

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

# Default backtest data location
BACKTEST_DATA_DIR = Path("config/backtest")


def _find_dashboard_csv() -> Optional[Path]:
    """
    Find the dashboard CSV file in the config/backtest directory.

    Returns:
        Path to dashboard CSV file, or None if not found
    """
    if not BACKTEST_DATA_DIR.exists():
        return None

    # Look for dashboard_*.csv files
    csv_files = list(BACKTEST_DATA_DIR.glob("dashboard_*.csv"))
    if not csv_files:
        return None

    # Return the most recently modified if multiple exist
    return max(csv_files, key=lambda p: p.stat().st_mtime)


def _extract_strategy_name(csv_path: Path) -> Optional[str]:
    """
    Extract strategy name from dashboard CSV filename.

    Args:
        csv_path: Path like 'dashboard_Hierarchical_Adaptive_v3_5b.csv'

    Returns:
        Strategy name like 'Hierarchical_Adaptive_v3_5b', or None if not extractable
    """
    filename = csv_path.stem  # e.g., 'dashboard_Hierarchical_Adaptive_v3_5b'
    if filename.startswith("dashboard_"):
        return filename[len("dashboard_"):]
    return None


def _find_config_for_strategy(strategy_name: Optional[str]) -> Optional[Path]:
    """
    Find config file for a strategy, with fallback to generic config.

    Lookup order:
    1. config_<strategy>.yaml
    2. config_<strategy>.yml
    3. config.yaml (fallback)
    4. config.yml (fallback)

    Args:
        strategy_name: Strategy name extracted from dashboard CSV

    Returns:
        Path to config file, or None if not found
    """
    if strategy_name:
        # Try strategy-specific config first
        for ext in [".yaml", ".yml"]:
            config_path = BACKTEST_DATA_DIR / f"config_{strategy_name}{ext}"
            if config_path.exists():
                return config_path

    # Fall back to generic config
    for ext in [".yaml", ".yml"]:
        config_path = BACKTEST_DATA_DIR / f"config{ext}"
        if config_path.exists():
            return config_path

    return None


def _parse_dashboard_csv(csv_path: Path) -> Dict[str, Any]:
    """
    Parse the consolidated dashboard CSV file.

    Extracts:
    - Summary metadata from comment header lines
    - Timeseries data from data rows

    Args:
        csv_path: Path to dashboard CSV file

    Returns:
        Dictionary with 'summary' and 'timeseries' keys
    """
    summary = {}
    timeseries = []

    # Read file content once to avoid seek/tell issues
    with open(csv_path, 'r') as f:
        lines = f.readlines()

    # Parse comment lines for metadata
    data_start_idx = 0
    for i, line in enumerate(lines):
        line = line.strip()

        if line.startswith('#'):
            # Skip the title line
            if 'Dashboard Export' in line:
                continue

            # Parse key: value pairs
            if ':' in line:
                # Remove # prefix and split on first :
                parts = line[1:].strip().split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()

                    # Convert numeric values
                    if key in ['total_return', 'annualized_return', 'sharpe_ratio',
                               'max_drawdown', 'alpha', 'initial_capital']:
                        try:
                            summary[key] = float(value)
                        except ValueError:
                            summary[key] = value
                    else:
                        summary[key] = value
        else:
            # Non-comment line - this is the header row
            data_start_idx = i
            break

    # Parse data rows using csv.DictReader on remaining lines
    if data_start_idx < len(lines):
        data_content = ''.join(lines[data_start_idx:])
        reader = csv.DictReader(io.StringIO(data_content))

        for row in reader:
            entry = {
                'date': row.get('Date', ''),
                'portfolio': _parse_float(row.get('Portfolio_Value')),
                'baseline': _parse_float(row.get('Baseline_Value')),
                'buyhold': _parse_float(row.get('BuyHold_Value')),
                'regime': row.get('Regime', ''),
                'trend': row.get('Trend', ''),
                'vol': row.get('Vol', ''),
            }
            timeseries.append(entry)

    # Recalculate alpha from actual timeseries data (CAGR difference)
    if timeseries and len(timeseries) >= 2:
        first = timeseries[0]
        last = timeseries[-1]

        # Calculate date range for CAGR
        try:
            start_dt = datetime.strptime(first['date'], '%Y-%m-%d')
            end_dt = datetime.strptime(last['date'], '%Y-%m-%d')
            years = (end_dt - start_dt).days / 365.25
        except (ValueError, KeyError):
            years = 0

        # Calculate baseline total return and CAGR
        if first.get('baseline') and last.get('baseline') and first['baseline'] > 0:
            baseline_total_return = ((last['baseline'] / first['baseline']) - 1) * 100
            summary['baseline_total_return'] = round(baseline_total_return, 2)

            # Calculate baseline CAGR
            if years > 0:
                baseline_cagr = ((last['baseline'] / first['baseline']) ** (1 / years) - 1) * 100
                summary['baseline_cagr'] = round(baseline_cagr, 2)

                # Recalculate alpha as CAGR difference (Portfolio CAGR - Baseline CAGR)
                if summary.get('annualized_return') is not None:
                    summary['alpha'] = round(summary['annualized_return'] - baseline_cagr, 2)

    return {
        'summary': summary,
        'timeseries': timeseries,
    }


def _parse_float(value: str) -> Optional[float]:
    """Safely parse a string to float, returning None for empty/invalid."""
    if not value or value.strip() == '':
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _calculate_period_metrics(
    timeseries: List[Dict],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calculate metrics for a specific date range.

    Args:
        timeseries: Full timeseries data
        start_date: Start date (YYYY-MM-DD) or None for beginning
        end_date: End date (YYYY-MM-DD) or None for end

    Returns:
        Dictionary with period metrics
    """
    if not timeseries:
        return {}

    # Filter by date range
    filtered = timeseries
    if start_date:
        filtered = [t for t in filtered if t['date'] >= start_date]
    if end_date:
        filtered = [t for t in filtered if t['date'] <= end_date]

    if not filtered:
        return {}

    first = filtered[0]
    last = filtered[-1]

    # Calculate portfolio return
    start_portfolio = first.get('portfolio')
    end_portfolio = last.get('portfolio')

    period_return = None
    if start_portfolio and end_portfolio and start_portfolio > 0:
        period_return = ((end_portfolio / start_portfolio) - 1) * 100

    # Calculate baseline return
    start_baseline = first.get('baseline')
    end_baseline = last.get('baseline')

    baseline_return = None
    if start_baseline and end_baseline and start_baseline > 0:
        baseline_return = ((end_baseline / start_baseline) - 1) * 100

    # Calculate annualized return
    start_dt = datetime.strptime(first['date'], '%Y-%m-%d')
    end_dt = datetime.strptime(last['date'], '%Y-%m-%d')
    days = (end_dt - start_dt).days

    annualized = None
    if period_return is not None and days > 0:
        # Annualize: (1 + return)^(365/days) - 1
        try:
            annualized = ((1 + period_return / 100) ** (365 / days) - 1) * 100
        except (ValueError, OverflowError):
            annualized = None

    # Calculate baseline annualized return (baseline CAGR)
    baseline_annualized = None
    if baseline_return is not None and days > 0:
        try:
            baseline_annualized = ((1 + baseline_return / 100) ** (365 / days) - 1) * 100
        except (ValueError, OverflowError):
            baseline_annualized = None

    # Calculate alpha based on CAGR difference (Portfolio CAGR - Baseline CAGR)
    alpha = None
    if annualized is not None and baseline_annualized is not None:
        alpha = annualized - baseline_annualized

    return {
        'start_date': first['date'],
        'end_date': last['date'],
        'days': days,
        'period_return': round(period_return, 2) if period_return is not None else None,
        'annualized_return': round(annualized, 2) if annualized is not None else None,
        'baseline_return': round(baseline_return, 2) if baseline_return is not None else None,
        'baseline_annualized': round(baseline_annualized, 2) if baseline_annualized is not None else None,
        'alpha': round(alpha, 2) if alpha is not None else None,
    }


def _calculate_regime_breakdown(
    timeseries: List[Dict],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict]:
    """
    Calculate performance breakdown by regime for a date range.

    Uses compound return calculation for accurate multi-day returns.

    Args:
        timeseries: Full timeseries data
        start_date: Start date (YYYY-MM-DD) or None for beginning
        end_date: End date (YYYY-MM-DD) or None for end

    Returns:
        List of regime performance dictionaries
    """
    if not timeseries:
        return []

    # Filter by date range
    filtered = timeseries
    if start_date:
        filtered = [t for t in filtered if t['date'] >= start_date]
    if end_date:
        filtered = [t for t in filtered if t['date'] <= end_date]

    if not filtered:
        return []

    # Group data by regime
    regime_data: Dict[str, List[Dict]] = {}

    for i, entry in enumerate(filtered):
        regime = entry.get('regime', '')
        if not regime:
            continue

        if regime not in regime_data:
            regime_data[regime] = []
        regime_data[regime].append(entry)

    # Calculate metrics for each regime
    results = []
    total_days = len(filtered)

    for regime, entries in regime_data.items():
        if not entries:
            continue

        # Extract cell number, trend, vol from regime identifier
        # Format: "Cell_N" with Trend and Vol columns
        trend = entries[0].get('trend', '')
        vol = entries[0].get('vol', '')

        # Try to extract cell number from regime string
        cell = None
        if regime.startswith('Cell_'):
            try:
                cell = int(regime.split('_')[1])
            except (IndexError, ValueError):
                pass

        # Calculate compound return using daily portfolio values
        # Group consecutive days in this regime to calculate segment returns
        days = len(entries)
        pct_of_time = (days / total_days * 100) if total_days > 0 else 0

        # Calculate return contribution from this regime
        # Use first and last portfolio values for segments
        segment_returns = []

        # Build lookup for quick portfolio value access
        date_to_entry = {e['date']: e for e in filtered}

        # Find consecutive date segments in this regime
        current_segment_start = None
        prev_date = None

        sorted_entries = sorted(entries, key=lambda x: x['date'])

        for entry in sorted_entries:
            entry_date = datetime.strptime(entry['date'], '%Y-%m-%d').date()

            if current_segment_start is None:
                current_segment_start = entry
            elif prev_date:
                # Check if dates are consecutive (allowing weekends/holidays)
                gap = (entry_date - prev_date).days
                if gap > 5:  # More than a week gap, end segment
                    # Calculate segment return
                    if current_segment_start.get('portfolio') and entry.get('portfolio'):
                        start_val = current_segment_start['portfolio']
                        end_val = date_to_entry.get(prev_date.strftime('%Y-%m-%d'), {}).get('portfolio')
                        if start_val and end_val and start_val > 0:
                            segment_returns.append(end_val / start_val)
                    current_segment_start = entry

            prev_date = entry_date

        # Handle last segment
        if current_segment_start and sorted_entries:
            last_entry = sorted_entries[-1]
            if current_segment_start.get('portfolio') and last_entry.get('portfolio'):
                start_val = current_segment_start['portfolio']
                end_val = last_entry['portfolio']
                if start_val and end_val and start_val > 0:
                    segment_returns.append(end_val / start_val)

        # Calculate compound return from segments
        compound_multiplier = 1.0
        for ret in segment_returns:
            compound_multiplier *= ret

        total_return = (compound_multiplier - 1) * 100 if segment_returns else 0

        # Calculate annualized return
        annualized = None
        if days > 0 and total_return != 0:
            try:
                annualized = ((1 + total_return / 100) ** (252 / days) - 1) * 100
            except (ValueError, OverflowError):
                annualized = None

        # Calculate baseline segment returns for this regime
        baseline_segment_returns = []
        baseline_segment_start = None
        prev_baseline_date = None

        for entry in sorted_entries:
            entry_date = datetime.strptime(entry['date'], '%Y-%m-%d').date()

            if baseline_segment_start is None:
                baseline_segment_start = entry
            elif prev_baseline_date:
                gap = (entry_date - prev_baseline_date).days
                if gap > 5:
                    if baseline_segment_start.get('baseline') and entry.get('baseline'):
                        start_val = baseline_segment_start['baseline']
                        end_val = date_to_entry.get(prev_baseline_date.strftime('%Y-%m-%d'), {}).get('baseline')
                        if start_val and end_val and start_val > 0:
                            baseline_segment_returns.append(end_val / start_val)
                    baseline_segment_start = entry

            prev_baseline_date = entry_date

        # Handle last baseline segment
        if baseline_segment_start and sorted_entries:
            last_entry = sorted_entries[-1]
            if baseline_segment_start.get('baseline') and last_entry.get('baseline'):
                start_val = baseline_segment_start['baseline']
                end_val = last_entry['baseline']
                if start_val and end_val and start_val > 0:
                    baseline_segment_returns.append(end_val / start_val)

        # Calculate baseline compound return
        baseline_compound = 1.0
        for ret in baseline_segment_returns:
            baseline_compound *= ret

        baseline_total_return = (baseline_compound - 1) * 100 if baseline_segment_returns else 0

        # Calculate baseline annualized return
        baseline_annualized = None
        if days > 0 and baseline_total_return != 0:
            try:
                baseline_annualized = ((1 + baseline_total_return / 100) ** (252 / days) - 1) * 100
            except (ValueError, OverflowError):
                baseline_annualized = None

        results.append({
            'cell': cell,
            'regime': regime,
            'trend': trend,
            'vol': vol,
            'total_return': round(total_return, 2),
            'annualized_return': round(annualized, 2) if annualized is not None else None,
            'baseline_annualized': round(baseline_annualized, 2) if baseline_annualized is not None else None,
            'days': days,
            'pct_of_time': round(pct_of_time, 1),
        })

    # Sort by cell number
    return sorted(results, key=lambda x: x.get('cell') or 999)


@router.get(
    "/data",
    responses={
        404: {"model": ErrorResponse, "description": "Backtest data not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get backtest data",
    description="Returns summary metrics and timeseries data from the golden backtest."
)
async def get_backtest_data(
    start_date: Optional[str] = Query(None, description="Filter start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Filter end date (YYYY-MM-DD)"),
    _auth: bool = Depends(verify_credentials),
) -> Dict[str, Any]:
    """
    Get backtest summary and timeseries data.

    Returns:
    - summary: All-time metrics (total return, CAGR, Sharpe, max DD, alpha)
    - timeseries: Daily portfolio values with regime data
    - period_metrics: Calculated metrics for the selected date range
    """
    try:
        csv_path = _find_dashboard_csv()
        if not csv_path:
            raise HTTPException(
                status_code=404,
                detail="No backtest data found. Please run a backtest with dashboard export enabled."
            )

        # Parse CSV file
        data = _parse_dashboard_csv(csv_path)

        # Calculate period metrics if date range specified
        period_metrics = _calculate_period_metrics(
            data['timeseries'],
            start_date=start_date,
            end_date=end_date,
        )

        # Filter timeseries if date range specified
        timeseries = data['timeseries']
        if start_date:
            timeseries = [t for t in timeseries if t['date'] >= start_date]
        if end_date:
            timeseries = [t for t in timeseries if t['date'] <= end_date]

        return {
            'summary': data['summary'],
            'timeseries': timeseries,
            'period_metrics': period_metrics,
            'total_data_points': len(data['timeseries']),
            'filtered_data_points': len(timeseries),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backtest data error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/config",
    responses={
        403: {"model": ErrorResponse, "description": "Admin access required"},
        404: {"model": ErrorResponse, "description": "Config not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get strategy config (admin only)",
    description="Returns the strategy configuration YAML file. Admin access required."
)
async def get_backtest_config(
    current_user = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get strategy configuration (admin only).

    Looks for config file matching the current dashboard CSV:
    1. config_<strategy>.yaml (matches dashboard_<strategy>.csv)
    2. config_<strategy>.yml
    3. config.yaml (fallback)
    4. config.yml (fallback)
    """
    try:
        # Check admin role
        if hasattr(current_user, 'role') and current_user.role != 'admin':
            raise HTTPException(
                status_code=403,
                detail="Admin access required"
            )

        # Find current dashboard CSV and extract strategy name
        csv_path = _find_dashboard_csv()
        strategy_name = _extract_strategy_name(csv_path) if csv_path else None

        # Find matching config file
        config_path = _find_config_for_strategy(strategy_name)

        if not config_path:
            raise HTTPException(
                status_code=404,
                detail=f"No config file found. Expected: config_{strategy_name}.yaml or config.yaml"
            )

        # Parse YAML
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        return {
            'config': config,
            'file_path': str(config_path),
            'strategy_name': strategy_name,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backtest config error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/regime-breakdown",
    responses={
        404: {"model": ErrorResponse, "description": "Backtest data not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get regime breakdown",
    description="Returns performance broken down by regime for the specified date range."
)
async def get_regime_breakdown(
    start_date: Optional[str] = Query(None, description="Filter start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Filter end date (YYYY-MM-DD)"),
    _auth: bool = Depends(verify_credentials),
) -> Dict[str, Any]:
    """
    Get performance breakdown by regime.

    Filters by date range and calculates:
    - Total return for each regime
    - Annualized return
    - Days in regime
    - Percentage of time in regime
    """
    try:
        csv_path = _find_dashboard_csv()
        if not csv_path:
            raise HTTPException(
                status_code=404,
                detail="No backtest data found."
            )

        # Parse CSV file
        data = _parse_dashboard_csv(csv_path)

        # Calculate regime breakdown
        regimes = _calculate_regime_breakdown(
            data['timeseries'],
            start_date=start_date,
            end_date=end_date,
        )

        return {
            'regimes': regimes,
            'start_date': start_date or (data['timeseries'][0]['date'] if data['timeseries'] else None),
            'end_date': end_date or (data['timeseries'][-1]['date'] if data['timeseries'] else None),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Regime breakdown error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
