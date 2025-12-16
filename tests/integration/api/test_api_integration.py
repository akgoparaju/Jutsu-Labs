"""
Integration tests for Jutsu Labs REST API.

Tests complete API workflows including:
- Backtest execution
- Data synchronization
- Strategy management
- Parameter optimization
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from jutsu_api.main import app
from jutsu_api.dependencies import get_db
from jutsu_engine.data.models import Base


# Test database setup
# Use StaticPool to ensure the same in-memory database is shared across all connections
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    """Override database dependency for testing."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override dependency
app.dependency_overrides[get_db] = override_get_db

# Create test client
client = TestClient(app)


@pytest.fixture(scope="function")
def setup_database():
    """Create test database tables."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_root_endpoint(self):
        """Test root endpoint returns healthy status."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.2.0"
        assert "timestamp" in data

    def test_health_endpoint(self):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.2.0"


class TestBacktestEndpoints:
    """Test backtest execution endpoints."""

    @pytest.mark.skip(reason="Requires market data in database")
    def test_run_backtest_success(self, setup_database):
        """Test successful backtest execution."""
        request_data = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "parameters": {
                "short_period": 20,
                "long_period": 50,
                "position_percent": "1.0"
            },
            "timeframe": "1D"
        }

        response = client.post("/api/v1/backtest/run", json=request_data)
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert "backtest_id" in data
        assert "metrics" in data

    def test_run_backtest_invalid_strategy(self):
        """Test backtest with invalid strategy name."""
        request_data = {
            "strategy_name": "InvalidStrategy",
            "symbol": "AAPL",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "parameters": {}
        }

        response = client.post("/api/v1/backtest/run", json=request_data)
        assert response.status_code == 400

    def test_run_backtest_invalid_dates(self):
        """Test backtest with end_date before start_date."""
        request_data = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "start_date": "2024-12-31T00:00:00",
            "end_date": "2024-01-01T00:00:00",  # Before start_date
            "initial_capital": "100000.00",
            "parameters": {
                "short_period": 20,
                "long_period": 50
            }
        }

        response = client.post("/api/v1/backtest/run", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_get_backtest_not_found(self):
        """Test retrieving non-existent backtest."""
        response = client.get("/api/v1/backtest/nonexistent_id")
        assert response.status_code == 404

    def test_list_backtest_history(self):
        """Test listing backtest history."""
        response = client.get("/api/v1/backtest/history")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestDataEndpoints:
    """Test data management endpoints."""

    def test_list_symbols_empty(self, setup_database):
        """Test listing symbols when database is empty."""
        response = client.get("/api/v1/data/symbols")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_metadata_empty(self, setup_database):
        """Test retrieving metadata when empty."""
        response = client.get("/api/v1/data/metadata")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.skip(reason="Requires Schwab API credentials")
    def test_sync_market_data(self, setup_database):
        """Test data synchronization."""
        request_data = {
            "symbol": "AAPL",
            "source": "schwab",
            "timeframe": "1D",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-01-31T00:00:00"
        }

        response = client.post("/api/v1/data/sync", json=request_data)
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"

    def test_sync_invalid_source(self, setup_database):
        """Test sync with invalid data source."""
        request_data = {
            "symbol": "AAPL",
            "source": "invalid_source",
            "timeframe": "1D",
            "start_date": "2024-01-01T00:00:00"
        }

        response = client.post("/api/v1/data/sync", json=request_data)
        assert response.status_code == 400

    def test_get_bars_not_found(self, setup_database):
        """Test retrieving bars for non-existent symbol."""
        response = client.get("/api/v1/data/AAPL/bars?timeframe=1D")
        assert response.status_code == 404


class TestStrategyEndpoints:
    """Test strategy management endpoints."""

    def test_list_strategies(self):
        """Test listing available strategies."""
        response = client.get("/api/v1/strategies")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert any(s["name"] == "SMA_Crossover" for s in data)

    def test_get_strategy_details(self):
        """Test retrieving strategy details."""
        response = client.get("/api/v1/strategies/SMA_Crossover")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "SMA_Crossover"
        assert "parameters" in data
        assert "default_values" in data

    def test_get_strategy_not_found(self):
        """Test retrieving non-existent strategy."""
        response = client.get("/api/v1/strategies/NonExistentStrategy")
        assert response.status_code == 404

    def test_validate_parameters_success(self):
        """Test validating correct parameters."""
        response = client.post(
            "/api/v1/strategies/validate",
            params={
                "strategy_name": "SMA_Crossover",
            },
            json={
                "short_period": 20,
                "long_period": 50
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True

    def test_validate_parameters_invalid(self):
        """Test validating invalid parameters."""
        response = client.post(
            "/api/v1/strategies/validate",
            params={
                "strategy_name": "SMA_Crossover",
            },
            json={
                "invalid_param": 123
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_get_strategy_schema(self):
        """Test retrieving strategy parameter schema."""
        response = client.get("/api/v1/strategies/SMA_Crossover/schema")
        assert response.status_code == 200
        data = response.json()
        assert "schema" in data
        assert data["strategy_name"] == "SMA_Crossover"


class TestOptimizationEndpoints:
    """Test parameter optimization endpoints."""

    @pytest.mark.skip(reason="Requires market data and takes time")
    def test_run_grid_search(self, setup_database):
        """Test grid search optimization."""
        request_data = {
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

        response = client.post("/api/v1/optimization/grid-search", json=request_data)
        assert response.status_code == 201
        data = response.json()
        assert data["status"] in ["running", "completed"]
        assert "job_id" in data

    def test_get_optimization_not_found(self):
        """Test retrieving non-existent optimization job."""
        response = client.get("/api/v1/optimization/nonexistent_job")
        assert response.status_code == 404

    def test_list_optimization_jobs(self):
        """Test listing optimization jobs."""
        response = client.get("/api/v1/optimization/jobs/list")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestRateLimiting:
    """Test rate limiting middleware."""

    @pytest.mark.skip(reason="Rate limiting requires multiple rapid requests")
    def test_rate_limit_exceeded(self):
        """Test that rate limiting works."""
        # Make many rapid requests
        for i in range(70):  # Exceeds default 60/min limit
            response = client.get("/health")
            if response.status_code == 429:
                # Rate limit hit
                assert True
                return

        # If we get here, rate limiting didn't work
        pytest.fail("Rate limit not enforced")


class TestErrorHandling:
    """Test error handling across endpoints."""

    def test_invalid_json(self):
        """Test handling of invalid JSON."""
        response = client.post(
            "/api/v1/backtest/run",
            data="invalid json"
        )
        assert response.status_code == 422

    def test_missing_required_fields(self):
        """Test handling of missing required fields."""
        request_data = {
            "strategy_name": "SMA_Crossover"
            # Missing required fields
        }

        response = client.post("/api/v1/backtest/run", json=request_data)
        assert response.status_code == 422

    def test_invalid_field_types(self):
        """Test handling of invalid field types."""
        request_data = {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "start_date": "invalid_date",  # Should be datetime
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "not_a_number"  # Should be Decimal
        }

        response = client.post("/api/v1/backtest/run", json=request_data)
        assert response.status_code == 422
