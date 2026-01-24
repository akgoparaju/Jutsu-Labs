"""
Jutsu Engine Scheduled Jobs

This module contains scheduled job implementations for automated tasks:
- EOD Finalization: Daily performance metrics calculation at market close

Reference: claudedocs/eod_daily_performance_architecture.md
"""

from jutsu_engine.jobs.eod_finalization import (
    run_eod_finalization,
    run_eod_finalization_with_recovery,
    process_strategy_eod,
    process_baseline_eod,
    monitor_eod_health,
    # Corner case handlers (Phase 6)
    handle_first_day,
    handle_data_gap,
    log_edge_case,
    get_latest_daily_performance,
    get_eod_finalization_status,
)

__all__ = [
    'run_eod_finalization',
    'run_eod_finalization_with_recovery',
    'process_strategy_eod',
    'process_baseline_eod',
    'monitor_eod_health',
    # Corner case handlers (Phase 6)
    'handle_first_day',
    'handle_data_gap',
    'log_edge_case',
    'get_latest_daily_performance',
    'get_eod_finalization_status',
]
