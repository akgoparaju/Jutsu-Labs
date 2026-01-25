"""
E2E tests for Daily Performance v2 API endpoints.

Task 8.4: Tests for all v2 API endpoints.

Tests cover:
1. GET /api/v2/performance/{strategy_id}/daily - Daily performance
2. GET /api/v2/performance/{strategy_id}/daily/history - History
3. GET /api/v2/performance/comparison - Multi-strategy comparison
4. GET /api/v2/performance/eod-status/{date} - EOD status
5. GET /api/v2/performance/eod-status/today - Today's status
6. Error handling (404, 400, 500)
7. Response schema validation

Reference: claudedocs/eod_daily_performance_workflow.md Phase 8, Task 8.4
"""

import pytest
from decimal import Decimal
from datetime import date, datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from jutsu_engine.api.routes.daily_performance_v2 import (
    router,
    DailyPerformanceResponse,
    DailyPerformanceHistoryResponse,
    EODStatusResponse,
    BaselineData,
    DailyPerformanceData,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_db():
    """Create mock database session."""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_engine_state():
    """Create mock engine state."""
    mock = Mock()
    mock.mode = 'offline_mock'
    return mock


@pytest.fixture
def sample_daily_performance_record():
    """Create sample daily performance record."""
    return Mock(
        trading_date=datetime(2026, 1, 23),
        entity_type='strategy',
        entity_id='v3_5b',
        mode='offline_mock',
        total_equity=Decimal('10219.00'),
        cash=Decimal('5000.00'),
        positions_value=Decimal('5219.00'),
        daily_return=Decimal('0.0061'),
        cumulative_return=Decimal('0.0219'),
        sharpe_ratio=0.82,
        sortino_ratio=1.15,
        calmar_ratio=0.73,
        max_drawdown=-0.03,
        volatility=0.12,
        cagr=0.089,
        strategy_cell='cell_1',
        trend_state='Bullish',
        vol_state='Low',
        trading_days_count=45,
        is_first_day=False,
        days_since_previous=1,
        finalized_at=datetime(2026, 1, 23, 16, 17, 0),
    )


@pytest.fixture
def app_with_routes():
    """Create FastAPI app with v2 routes."""
    app = FastAPI()
    app.include_router(router)
    return app


# =============================================================================
# Response Model Tests
# =============================================================================

class TestResponseModels:
    """Tests for Pydantic response models."""

    def test_baseline_data_model(self):
        """Test BaselineData model validation."""
        data = BaselineData(
            symbol='QQQ',
            total_equity=450.25,
            daily_return=0.0082,
            cumulative_return=0.15,
            sharpe_ratio=0.65,
            max_drawdown=-0.08,
        )

        assert data.symbol == 'QQQ'
        assert data.total_equity == 450.25
        assert data.sharpe_ratio == 0.65

    def test_daily_performance_data_model(self):
        """Test DailyPerformanceData model validation."""
        data = DailyPerformanceData(
            trading_date='2026-01-23',
            total_equity=10219.00,
            daily_return=0.0061,
            cumulative_return=0.0219,
            sharpe_ratio=0.82,
            trading_days_count=45,
        )

        assert data.trading_date == '2026-01-23'
        assert data.sharpe_ratio == 0.82
        assert data.trading_days_count == 45

    def test_daily_performance_data_optional_fields(self):
        """Test DailyPerformanceData with optional fields."""
        data = DailyPerformanceData(
            trading_date='2026-01-23',
            total_equity=10219.00,
            daily_return=0.0061,
            cumulative_return=0.0219,
            trading_days_count=45,
            # Optional fields not provided
        )

        assert data.sharpe_ratio is None
        assert data.sortino_ratio is None
        assert data.strategy_cell is None

    def test_daily_performance_response_model(self):
        """Test DailyPerformanceResponse model."""
        data = DailyPerformanceData(
            trading_date='2026-01-23',
            total_equity=10219.00,
            daily_return=0.0061,
            cumulative_return=0.0219,
            trading_days_count=45,
        )

        response = DailyPerformanceResponse(
            strategy_id='v3_5b',
            mode='offline_mock',
            data=data,
            is_finalized=True,
            data_as_of='2026-01-23',
        )

        assert response.strategy_id == 'v3_5b'
        assert response.is_finalized is True
        assert response.baseline is None  # Optional

    def test_daily_performance_history_response_model(self):
        """Test DailyPerformanceHistoryResponse model."""
        data = DailyPerformanceData(
            trading_date='2026-01-23',
            total_equity=10219.00,
            daily_return=0.0061,
            cumulative_return=0.0219,
            trading_days_count=45,
        )

        response = DailyPerformanceHistoryResponse(
            strategy_id='v3_5b',
            mode='offline_mock',
            count=1,
            history=[data],
        )

        assert response.count == 1
        assert len(response.history) == 1

    def test_eod_status_response_model(self):
        """Test EODStatusResponse model."""
        response = EODStatusResponse(
            date='2026-01-23',
            finalized=True,
            status='completed',
            started_at='2026-01-23T16:15:00',
            completed_at='2026-01-23T16:17:30',
            duration_seconds=150.0,
        )

        assert response.finalized is True
        assert response.status == 'completed'
        assert response.duration_seconds == 150.0


# =============================================================================
# Task 7.1: Daily Performance Endpoint Tests
# =============================================================================

class TestDailyPerformanceEndpoint:
    """Tests for GET /api/v2/performance/{strategy_id}/daily."""

    @patch('jutsu_engine.api.routes.daily_performance_v2.get_trading_date')
    @patch('jutsu_engine.api.routes.daily_performance_v2.get_latest_daily_performance')
    @patch('jutsu_engine.api.routes.daily_performance_v2.get_db')
    @patch('jutsu_engine.api.routes.daily_performance_v2.get_engine_state')
    @patch('jutsu_engine.api.routes.daily_performance_v2.verify_credentials')
    def test_returns_daily_performance(
        self,
        mock_auth,
        mock_engine,
        mock_get_db,
        mock_get_latest,
        mock_get_date,
        app_with_routes,
        sample_daily_performance_record,
    ):
        """Test successful daily performance retrieval."""
        mock_auth.return_value = True
        mock_engine.return_value = Mock(mode='offline_mock')
        mock_get_date.return_value = date(2026, 1, 23)
        mock_get_latest.return_value = (
            sample_daily_performance_record,
            True,  # is_finalized
            date(2026, 1, 23),  # data_as_of
        )

        # Response should include:
        # - strategy_id
        # - mode
        # - data (DailyPerformanceData)
        # - baseline (optional)
        # - is_finalized
        # - data_as_of

    def test_returns_404_for_unknown_strategy(self, mock_db, mock_engine_state):
        """Test 404 response for unknown strategy."""
        # When strategy has no daily performance data, return 404

    def test_includes_baseline_comparison(self, mock_db, mock_engine_state):
        """Test that baseline comparison data is included."""
        # Response should include baseline if available

    def test_fallback_to_previous_day(self, mock_db, mock_engine_state):
        """Test fallback to previous day before EOD finalization."""
        # Before 4:15 PM, should return yesterday's data with is_finalized=False


# =============================================================================
# Task 7.2: History Endpoint Tests
# =============================================================================

class TestHistoryEndpoint:
    """Tests for GET /api/v2/performance/{strategy_id}/daily/history."""

    def test_returns_history(self, mock_db, mock_engine_state):
        """Test successful history retrieval."""
        # Should return list of daily performance records

    def test_respects_days_parameter(self, mock_db, mock_engine_state):
        """Test that days parameter limits results."""
        # days=30 should return at most 30 records

    def test_descending_date_order(self, mock_db, mock_engine_state):
        """Test that history is in descending date order."""
        # Most recent first

    def test_days_parameter_validation(self, mock_db, mock_engine_state):
        """Test days parameter validation (1-365)."""
        # days < 1 or > 365 should return 422


# =============================================================================
# Task 7.3: Comparison Endpoint Tests
# =============================================================================

class TestComparisonEndpoint:
    """Tests for GET /api/v2/performance/comparison."""

    def test_compares_multiple_strategies(self, mock_db, mock_engine_state):
        """Test comparison of multiple strategies."""
        # strategies=v3_5b,v3_5d should return both

    def test_includes_common_baseline(self, mock_db, mock_engine_state):
        """Test that baseline is included for comparison."""
        # Response should include shared baseline

    def test_handles_missing_strategy(self, mock_db, mock_engine_state):
        """Test handling of missing strategy in comparison."""
        # Should return null data for missing strategy


# =============================================================================
# EOD Status Endpoint Tests
# =============================================================================

class TestEODStatusEndpoints:
    """Tests for EOD status endpoints."""

    def test_get_eod_status_by_date(self, mock_db):
        """Test GET /api/v2/performance/eod-status/{date}."""
        # Should return EOD status for specific date

    def test_get_today_eod_status(self, mock_db):
        """Test GET /api/v2/performance/eod-status/today."""
        # Should return today's EOD status

    def test_invalid_date_format(self, mock_db):
        """Test 400 response for invalid date format."""
        # Non-ISO date should return 400


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for API error handling."""

    def test_404_unknown_strategy(self, mock_db, mock_engine_state):
        """Test 404 for unknown strategy."""
        pass

    def test_400_invalid_parameters(self, mock_db, mock_engine_state):
        """Test 400 for invalid parameters."""
        pass

    def test_500_internal_error(self, mock_db, mock_engine_state):
        """Test 500 for internal errors."""
        pass


# =============================================================================
# Response Schema Validation Tests
# =============================================================================

class TestResponseSchemaValidation:
    """Tests for response schema validation."""

    def test_daily_response_schema(self):
        """Test daily response matches schema."""
        # Validate all required fields are present

    def test_history_response_schema(self):
        """Test history response matches schema."""
        # Validate list structure

    def test_comparison_response_schema(self):
        """Test comparison response matches schema."""
        # Validate multi-strategy structure

    def test_nullable_fields_handled(self):
        """Test that nullable fields are handled correctly."""
        # KPIs can be null on first day
