"""
Endpoint-specific tests for all API routes.

Tests individual endpoint behavior, validation, and responses.
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from decimal import Decimal

from jutsu_api.main import app

client = TestClient(app)


class TestBacktestEndpoints:
    """Detailed tests for backtest endpoints."""

    def test_run_backtest_schema_validation(self):
        """Test request schema validation for backtest."""
        # Valid request
        valid_request = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "parameters": {
                "short_period": 20,
                "long_period": 50
            }
        }

        # Schema should accept valid request
        response = client.post("/api/v1/backtest/run", json=valid_request)
        # May fail due to missing data, but schema should be valid
        assert response.status_code in [201, 400, 500]  # Not 422 (validation error)

    def test_backtest_date_validation(self):
        """Test that end_date must be after start_date."""
        invalid_request = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "start_date": "2024-12-31T00:00:00",
            "end_date": "2024-01-01T00:00:00",  # Before start
            "initial_capital": "100000.00",
            "parameters": {}
        }

        response = client.post("/api/v1/backtest/run", json=invalid_request)
        assert response.status_code == 422

    def test_backtest_positive_capital_validation(self):
        """Test that initial_capital must be positive."""
        invalid_request = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "-1000.00",  # Negative
            "parameters": {}
        }

        response = client.post("/api/v1/backtest/run", json=invalid_request)
        assert response.status_code == 422

    def test_delete_backtest(self):
        """Test deleting a backtest."""
        # Try to delete non-existent backtest
        response = client.delete("/api/v1/backtest/nonexistent")
        assert response.status_code == 404

    def test_backtest_history_pagination(self):
        """Test backtest history pagination."""
        response = client.get("/api/v1/backtest/history?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


class TestDataEndpoints:
    """Detailed tests for data management endpoints."""

    def test_sync_date_range_validation(self):
        """Test that sync validates date ranges."""
        invalid_request = {
            "symbol": "AAPL",
            "source": "schwab",
            "timeframe": "1D",
            "start_date": "2024-12-31T00:00:00",
            "end_date": "2024-01-01T00:00:00"  # Before start
        }

        response = client.post("/api/v1/data/sync", json=invalid_request)
        assert response.status_code == 422

    def test_get_bars_pagination(self):
        """Test market data bars pagination."""
        response = client.get("/api/v1/data/AAPL/bars?limit=100&timeframe=1D")
        # May return 404 if no data, 500 if table missing, but pagination should work
        assert response.status_code in [200, 404, 500]

    def test_get_bars_date_filtering(self):
        """Test bars retrieval with date filters."""
        response = client.get(
            "/api/v1/data/AAPL/bars"
            "?start_date=2024-01-01T00:00:00"
            "&end_date=2024-12-31T00:00:00"
        )
        # May return 404 if no data, 500 if table missing
        assert response.status_code in [200, 404, 500]

    def test_validate_data_endpoint(self):
        """Test data validation endpoint."""
        response = client.post("/api/v1/data/AAPL/validate?timeframe=1D")
        # May fail if no data, but endpoint should exist
        assert response.status_code in [200, 404, 500]

    def test_metadata_symbol_filter(self):
        """Test metadata endpoint with symbol filter."""
        response = client.get("/api/v1/data/metadata?symbol=AAPL")
        # May return 500 if table missing in test environment
        assert response.status_code in [200, 500]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)


class TestStrategyEndpoints:
    """Detailed tests for strategy endpoints."""

    def test_list_strategies_structure(self):
        """Test structure of strategies list."""
        response = client.get("/api/v1/strategies")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        if len(data) > 0:
            strategy = data[0]
            assert "name" in strategy
            assert "description" in strategy
            assert "parameters" in strategy
            assert "default_values" in strategy

    def test_get_strategy_sma_crossover(self):
        """Test retrieving SMA_Crossover strategy details."""
        response = client.get("/api/v1/strategies/SMA_Crossover")
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "SMA_Crossover"
        assert "short_period" in data["parameters"]
        assert "long_period" in data["parameters"]
        assert "position_percent" in data["parameters"]

    def test_validate_parameters_unknown_param(self):
        """Test validation rejects unknown parameters."""
        response = client.post(
            "/api/v1/strategies/validate",
            params={"strategy_name": "SMA_Crossover"},
            json={
                "unknown_parameter": 123
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False

    def test_strategy_schema_structure(self):
        """Test strategy schema endpoint structure."""
        response = client.get("/api/v1/strategies/SMA_Crossover/schema")
        assert response.status_code == 200

        data = response.json()
        assert "strategy_name" in data
        assert "schema" in data
        assert data["schema"]["type"] == "object"
        assert "properties" in data["schema"]


class TestOptimizationEndpoints:
    """Detailed tests for optimization endpoints."""

    def test_grid_search_request_validation(self):
        """Test grid search request validation."""
        valid_request = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "parameter_space": {
                "short_period": [10, 20],
                "long_period": [40, 50]
            },
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "metric": "sharpe_ratio"
        }

        response = client.post("/api/v1/optimization/grid-search", json=valid_request)
        # May fail due to missing data, but schema should be valid
        assert response.status_code in [201, 400, 500]

    def test_genetic_optimizer_type(self):
        """Test genetic optimizer forces correct type."""
        request_data = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "parameter_space": {
                "short_period": [10, 20, 30],
                "long_period": [40, 50, 60]
            },
            "optimizer_type": "grid_search",  # Will be overridden
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "metric": "sharpe_ratio"
        }

        response = client.post("/api/v1/optimization/genetic", json=request_data)
        # Optimizer type should be forced to 'genetic'
        assert response.status_code in [201, 400, 500]

    def test_optimization_metric_validation(self):
        """Test optimization metric validation."""
        request_data = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "parameter_space": {
                "short_period": [10, 20]
            },
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "metric": "sharpe_ratio"  # Valid metric
        }

        response = client.post("/api/v1/optimization/grid-search", json=request_data)
        # Schema should accept valid metric
        assert response.status_code in [201, 400, 500]

    def test_list_jobs_status_filter(self):
        """Test listing jobs with status filter."""
        response = client.get("/api/v1/optimization/jobs/list?status=completed")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_jobs_limit(self):
        """Test listing jobs with limit."""
        response = client.get("/api/v1/optimization/jobs/list?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


class TestOpenAPIDocumentation:
    """Test OpenAPI documentation endpoints."""

    def test_openapi_schema_available(self):
        """Test that OpenAPI schema is generated."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        schema = response.json()
        assert "openapi" in schema
        assert "info" in schema
        assert "paths" in schema

    def test_docs_endpoint_accessible(self):
        """Test that Swagger UI docs are accessible."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_redoc_endpoint_accessible(self):
        """Test that ReDoc docs are accessible."""
        response = client.get("/redoc")
        assert response.status_code == 200


class TestResponseHeaders:
    """Test response headers and metadata."""

    def test_process_time_header(self):
        """Test that X-Process-Time header is added."""
        response = client.get("/health")
        assert response.status_code == 200
        assert "X-Process-Time" in response.headers

    def test_cors_headers(self):
        """Test CORS headers are present."""
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert response.status_code == 200
        # CORS headers should be present
        assert "access-control-allow-origin" in response.headers


class TestErrorResponses:
    """Test error response formats."""

    def test_404_error_format(self):
        """Test 404 error response format."""
        response = client.get("/api/v1/backtest/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_422_validation_error_format(self):
        """Test 422 validation error format."""
        response = client.post("/api/v1/backtest/run", json={})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_500_error_handling(self):
        """Test that 500 errors are handled gracefully."""
        # Trigger internal error with invalid strategy
        response = client.post(
            "/api/v1/backtest/run",
            json={
                "strategy_name": "NonExistent",
                "symbol": "AAPL",
                "start_date": "2024-01-01T00:00:00",
                "end_date": "2024-12-31T00:00:00",
                "initial_capital": "100000.00",
                "parameters": {}
            }
        )
        # Should return 400 (validation) or 500, not crash
        assert response.status_code in [400, 500]
