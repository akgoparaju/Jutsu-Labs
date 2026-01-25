"""
Unit tests for EOD finalization corner cases.

Task 8.2: Tests for corner case handling functions in eod_finalization.py.

Tests cover:
1. First-day handling (cold start for new strategies)
2. Data gap detection (non-consecutive trading days)
3. API fallback behavior (before EOD finalization)
4. Edge case logging (structured logging at appropriate levels)

Reference: claudedocs/eod_daily_performance_workflow.md Phase 8, Task 8.2
"""

import pytest
from decimal import Decimal
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import logging

from jutsu_engine.jobs.eod_finalization import (
    handle_first_day,
    handle_data_gap,
    log_edge_case,
)


# =============================================================================
# Task 6.1: First-Day Handling Tests
# =============================================================================

class TestFirstDayHandling:
    """Tests for handle_first_day()."""

    def test_first_day_returns_zero_daily_return(self):
        """Test that first day has zero daily return."""
        result = handle_first_day(
            strategy_id='v3_5b',
            mode='offline_mock',
            today_equity=10000.0,
            entity_type='strategy',
        )

        assert result['daily_return'] == Decimal('0')

    def test_first_day_sets_is_first_day_flag(self):
        """Test that is_first_day flag is set to True."""
        result = handle_first_day(
            strategy_id='v3_5b',
            mode='offline_mock',
            today_equity=10000.0,
        )

        assert result['is_first_day'] is True

    def test_first_day_zero_cumulative_return(self):
        """Test that cumulative return is zero on first day."""
        result = handle_first_day(
            strategy_id='v3_5b',
            mode='offline_mock',
            today_equity=10000.0,
        )

        assert result['cumulative_return'] == Decimal('0')

    def test_first_day_initializes_kpi_state(self):
        """Test that KPI state is initialized correctly."""
        result = handle_first_day(
            strategy_id='v3_5b',
            mode='offline_mock',
            today_equity=10000.0,
        )

        assert 'kpi_state' in result
        kpi_state = result['kpi_state']

        # Check KPI state has correct initial values
        assert kpi_state['returns_sum'] == 0.0
        assert kpi_state['returns_sum_sq'] == 0.0
        assert kpi_state['returns_count'] == 0
        assert kpi_state['high_water_mark'] == 10000.0
        assert kpi_state['is_first_day'] is True
        # KPIs should be None (insufficient data)
        assert kpi_state['sharpe_ratio'] is None
        assert kpi_state['sortino_ratio'] is None

    def test_first_day_sets_initial_capital(self):
        """Test that initial capital is set from first day equity."""
        result = handle_first_day(
            strategy_id='v3_5b',
            mode='offline_mock',
            today_equity=15000.0,
        )

        assert result['initial_capital'] == Decimal('15000')

    def test_first_day_days_since_previous_zero(self):
        """Test that days_since_previous is zero for first day."""
        result = handle_first_day(
            strategy_id='v3_5b',
            mode='offline_mock',
            today_equity=10000.0,
        )

        assert result['days_since_previous'] == 0

    def test_first_day_trading_days_count_one(self):
        """Test that trading_days_count is 1 for first day."""
        result = handle_first_day(
            strategy_id='v3_5b',
            mode='offline_mock',
            today_equity=10000.0,
        )

        assert result['trading_days_count'] == 1

    def test_first_day_baseline_entity_type(self):
        """Test first day handling for baseline entity type."""
        result = handle_first_day(
            strategy_id='QQQ',
            mode='offline_mock',
            today_equity=100.0,
            entity_type='baseline',
        )

        # Should work the same for baselines
        assert result['is_first_day'] is True
        assert result['daily_return'] == Decimal('0')


# =============================================================================
# Task 6.2: Data Gap Detection Tests
# =============================================================================

class TestDataGapDetection:
    """Tests for handle_data_gap()."""

    def test_small_gap_logs_debug(self, caplog):
        """Test that small gaps (2-3 days) log at DEBUG level."""
        with caplog.at_level(logging.DEBUG):
            handle_data_gap(
                strategy_id='v3_5b',
                mode='offline_mock',
                prev_date=date(2026, 1, 20),
                today_date=date(2026, 1, 22),  # 2 trading day gap
                gap_days=2,
            )

        # Check log was at DEBUG level
        assert any(
            record.levelno == logging.DEBUG and 'DATA_GAP' in record.message
            for record in caplog.records
        )

    def test_normal_gap_logs_info(self, caplog):
        """Test that normal gaps (4-5 days) log at INFO level."""
        with caplog.at_level(logging.INFO):
            handle_data_gap(
                strategy_id='v3_5b',
                mode='offline_mock',
                prev_date=date(2026, 1, 15),
                today_date=date(2026, 1, 22),  # 5 trading day gap
                gap_days=5,
            )

        assert any(
            record.levelno == logging.INFO and 'DATA_GAP' in record.message
            for record in caplog.records
        )

    def test_large_gap_logs_warning(self, caplog):
        """Test that large gaps (>5 days) log at WARNING level."""
        with caplog.at_level(logging.WARNING):
            handle_data_gap(
                strategy_id='v3_5b',
                mode='offline_mock',
                prev_date=date(2026, 1, 10),
                today_date=date(2026, 1, 23),  # 10 trading day gap
                gap_days=10,
            )

        assert any(
            record.levelno == logging.WARNING and 'DATA_GAP' in record.message
            for record in caplog.records
        )

    def test_gap_message_contains_dates(self, caplog):
        """Test that gap log message contains both dates."""
        with caplog.at_level(logging.INFO):
            handle_data_gap(
                strategy_id='v3_5b',
                mode='offline_mock',
                prev_date=date(2026, 1, 15),
                today_date=date(2026, 1, 22),
                gap_days=5,
            )

        assert any(
            '2026-01-15' in record.message and '2026-01-22' in record.message
            for record in caplog.records
        )


# =============================================================================
# Task 6.4: Edge Case Logging Tests
# =============================================================================

class TestEdgeCaseLogging:
    """Tests for log_edge_case()."""

    def test_first_day_logs_info(self, caplog):
        """Test FIRST_DAY case logs at INFO level."""
        with caplog.at_level(logging.INFO):
            log_edge_case(
                case_type='FIRST_DAY',
                entity_id='v3_5b',
                message='New strategy initialized',
                level='INFO',
            )

        assert any(
            record.levelno == logging.INFO and 'FIRST_DAY' in record.message
            for record in caplog.records
        )

    def test_no_snapshot_logs_warning(self, caplog):
        """Test NO_SNAPSHOT case logs at WARNING level."""
        with caplog.at_level(logging.WARNING):
            log_edge_case(
                case_type='NO_SNAPSHOT',
                entity_id='v3_5b',
                message='Missing snapshot data for today',
                level='WARNING',
            )

        assert any(
            record.levelno == logging.WARNING and 'NO_SNAPSHOT' in record.message
            for record in caplog.records
        )

    def test_strategy_missing_logs_error(self, caplog):
        """Test STRATEGY_MISSING case logs at ERROR level."""
        with caplog.at_level(logging.ERROR):
            log_edge_case(
                case_type='STRATEGY_MISSING',
                entity_id='unknown_strategy',
                message='Strategy not registered',
                level='ERROR',
            )

        assert any(
            record.levelno == logging.ERROR and 'STRATEGY_MISSING' in record.message
            for record in caplog.records
        )

    def test_extra_context_included(self, caplog):
        """Test that extra context is included in log message."""
        with caplog.at_level(logging.INFO):
            log_edge_case(
                case_type='RECOVERY',
                entity_id='v3_5b',
                message='Backfilling missed days',
                level='INFO',
                days_recovered=3,
                from_date='2026-01-20',
            )

        assert any(
            'days_recovered=3' in record.message
            for record in caplog.records
        )

    def test_entity_id_in_message(self, caplog):
        """Test that entity_id is included in log message."""
        with caplog.at_level(logging.INFO):
            log_edge_case(
                case_type='BASELINE_MISSING',
                entity_id='QQQ',
                message='Baseline data unavailable',
                level='WARNING',
            )

        assert any(
            'QQQ' in record.message
            for record in caplog.records
        )

    def test_debug_level_logging(self, caplog):
        """Test DEBUG level logging works correctly."""
        with caplog.at_level(logging.DEBUG):
            log_edge_case(
                case_type='DATA_GAP',
                entity_id='v3_5b',
                message='Small gap detected',
                level='DEBUG',
            )

        assert any(
            record.levelno == logging.DEBUG and 'DATA_GAP' in record.message
            for record in caplog.records
        )


# =============================================================================
# Combined Corner Case Tests
# =============================================================================

class TestCornerCaseIntegration:
    """Integration tests for multiple corner case scenarios."""

    def test_first_day_followed_by_gap(self, caplog):
        """Test first day detection followed by data gap."""
        # First day
        first_day_result = handle_first_day(
            strategy_id='new_strategy',
            mode='offline_mock',
            today_equity=10000.0,
        )

        assert first_day_result['is_first_day'] is True

        # Then a gap
        with caplog.at_level(logging.INFO):
            handle_data_gap(
                strategy_id='new_strategy',
                mode='offline_mock',
                prev_date=date(2026, 1, 20),
                today_date=date(2026, 1, 27),
                gap_days=5,
            )

        # Both should work independently
        assert first_day_result['kpi_state'] is not None

    def test_multiple_entity_types(self):
        """Test corner case handling for different entity types."""
        strategy_result = handle_first_day(
            strategy_id='v3_5b',
            mode='offline_mock',
            today_equity=10000.0,
            entity_type='strategy',
        )

        baseline_result = handle_first_day(
            strategy_id='QQQ',
            mode='offline_mock',
            today_equity=450.0,
            entity_type='baseline',
        )

        # Both should have same structure
        assert strategy_result['is_first_day'] == baseline_result['is_first_day']
        assert 'kpi_state' in strategy_result
        assert 'kpi_state' in baseline_result
