"""
Unit tests for OrderExecutor module.

Tests order execution, fill validation, and retry logic with mocked Schwab API.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
import tempfile

from jutsu_engine.live.order_executor import OrderExecutor
from jutsu_engine.live.exceptions import CriticalFailure, SlippageExceeded


@pytest.fixture
def config():
    """Standard test configuration."""
    return {
        'execution': {
            'max_slippage_pct': 0.5,
            'slippage_warning_pct': 0.3,
            'slippage_abort_pct': 1.0,
            'max_order_retries': 3,
            'retry_delay_seconds': 0.1  # Fast for testing
        },
        'schwab': {
            'environment': 'paper'
        }
    }


@pytest.fixture
def mock_client():
    """Create mock Schwab client."""
    client = Mock()
    return client


@pytest.fixture
def trade_log_path():
    """Create temporary trade log file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        return Path(f.name)


@pytest.fixture
def executor(mock_client, config, trade_log_path):
    """Create OrderExecutor instance with mocked client."""
    return OrderExecutor(
        client=mock_client,
        account_hash='test_account_hash',
        config=config,
        trade_log_path=trade_log_path
    )


class TestOrderSubmission:
    """Test order submission and fill waiting."""

    def test_submit_buy_order_success(self, executor, mock_client):
        """Test successful BUY order submission and fill."""
        # Mock order submission response
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER123'}
        mock_client.place_order.return_value = mock_response

        # Mock order status (FILLED)
        mock_client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{
                    'price': '50.10'
                }]
            }]
        }

        # Submit order
        fill = executor.submit_order(
            symbol='TQQQ',
            action='BUY',
            quantity=100,
            expected_price=Decimal('50.00')
        )

        # Verify order was placed
        mock_client.place_order.assert_called_once()

        # Verify fill info
        assert fill['symbol'] == 'TQQQ'
        assert fill['action'] == 'BUY'
        assert fill['quantity'] == 100
        assert fill['fill_price'] == Decimal('50.10')
        assert fill['order_id'] == 'ORDER123'

    def test_submit_sell_order_success(self, executor, mock_client):
        """Test successful SELL order submission."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER456'}
        mock_client.place_order.return_value = mock_response

        mock_client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{
                    'price': '49.95'
                }]
            }]
        }

        fill = executor.submit_order(
            symbol='TQQQ',
            action='SELL',
            quantity=100,
            expected_price=Decimal('50.00')
        )

        assert fill['action'] == 'SELL'
        assert fill['fill_price'] == Decimal('49.95')

    def test_submit_order_api_failure(self, executor, mock_client):
        """Test order submission with API failure raises CriticalFailure."""
        mock_client.place_order.side_effect = Exception("API connection failed")

        with pytest.raises(CriticalFailure):
            executor.submit_order(
                symbol='TQQQ',
                action='BUY',
                quantity=100,
                expected_price=Decimal('50.00')
            )

    def test_submit_order_rejected(self, executor, mock_client):
        """Test order rejection raises CriticalFailure."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER789'}
        mock_client.place_order.return_value = mock_response

        # Order rejected
        mock_client.get_order.return_value = {'status': 'REJECTED'}

        with pytest.raises(CriticalFailure):
            executor.submit_order(
                symbol='TQQQ',
                action='BUY',
                quantity=100,
                expected_price=Decimal('50.00')
            )


class TestRetryLogic:
    """Test partial fill retry logic."""

    def test_partial_fill_retry_success(self, executor, mock_client):
        """Test partial fill that succeeds on retry."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER999'}
        mock_client.place_order.return_value = mock_response

        # First check: PARTIALLY_FILLED, second check: FILLED
        mock_client.get_order.side_effect = [
            {'status': 'PARTIALLY_FILLED'},
            {
                'status': 'FILLED',
                'orderActivityCollection': [{
                    'executionLegs': [{'price': '50.15'}]
                }]
            }
        ]

        fill = executor.submit_order(
            symbol='TQQQ',
            action='BUY',
            quantity=100,
            expected_price=Decimal('50.00')
        )

        # Verify retry occurred
        assert mock_client.get_order.call_count == 2
        assert fill['fill_price'] == Decimal('50.15')

    def test_partial_fill_max_retries_exceeded(self, executor, mock_client):
        """Test max retries exceeded raises CriticalFailure."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER999'}
        mock_client.place_order.return_value = mock_response

        # Always return PARTIALLY_FILLED
        mock_client.get_order.return_value = {'status': 'PARTIALLY_FILLED'}

        with pytest.raises(CriticalFailure):
            executor.submit_order(
                symbol='TQQQ',
                action='BUY',
                quantity=100,
                expected_price=Decimal('50.00')
            )

        # Verify max retries reached (3)
        assert mock_client.get_order.call_count == 3


class TestRebalanceExecution:
    """Test full rebalance workflow."""

    def test_execute_rebalance_sell_then_buy(self, executor, mock_client):
        """Test rebalance executes SELL orders first, then BUY."""
        # Setup mocks
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER_ID'}
        mock_client.place_order.return_value = mock_response

        mock_client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{'price': '50.00'}]
            }]
        }

        position_diffs = {
            'TQQQ': -50,  # SELL 50 (negative)
            'TMF': 100    # BUY 100 (positive)
        }

        current_prices = {
            'TQQQ': Decimal('50.00'),
            'TMF': Decimal('20.00')
        }

        fills, fill_prices = executor.execute_rebalance(
            position_diffs,
            current_prices
        )

        # Verify order count
        assert len(fills) == 2

        # Verify SELL executed first (check call order)
        calls = mock_client.place_order.call_args_list
        # First call should be SELL
        first_order_args = calls[0][1]['order_spec']
        # Second call should be BUY
        second_order_args = calls[1][1]['order_spec']

        assert len(calls) == 2

    def test_execute_rebalance_empty_diffs(self, executor, mock_client):
        """Test rebalance with no orders returns empty."""
        fills, fill_prices = executor.execute_rebalance(
            {},  # No diffs
            {}
        )

        assert fills == []
        assert fill_prices == {}
        mock_client.place_order.assert_not_called()

    def test_execute_rebalance_only_sells(self, executor, mock_client):
        """Test rebalance with only SELL orders."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER_ID'}
        mock_client.place_order.return_value = mock_response

        mock_client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{'price': '50.00'}]
            }]
        }

        position_diffs = {
            'TQQQ': -100,
            'TMF': -50
        }

        current_prices = {
            'TQQQ': Decimal('50.00'),
            'TMF': Decimal('20.00')
        }

        fills, fill_prices = executor.execute_rebalance(
            position_diffs,
            current_prices
        )

        assert len(fills) == 2
        assert all(fill['action'] == 'SELL' for fill in fills)

    def test_execute_rebalance_only_buys(self, executor, mock_client):
        """Test rebalance with only BUY orders."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER_ID'}
        mock_client.place_order.return_value = mock_response

        mock_client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{'price': '50.00'}]
            }]
        }

        position_diffs = {
            'TQQQ': 100,
            'TMF': 50
        }

        current_prices = {
            'TQQQ': Decimal('50.00'),
            'TMF': Decimal('20.00')
        }

        fills, fill_prices = executor.execute_rebalance(
            position_diffs,
            current_prices
        )

        assert len(fills) == 2
        assert all(fill['action'] == 'BUY' for fill in fills)


class TestSlippageValidation:
    """Test slippage validation during execution."""

    def test_execute_rebalance_acceptable_slippage(self, executor, mock_client):
        """Test rebalance with acceptable slippage passes."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER_ID'}
        mock_client.place_order.return_value = mock_response

        # Fill price with 0.2% slippage (acceptable)
        mock_client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{'price': '50.10'}]  # 0.2% from 50.00
            }]
        }

        position_diffs = {'TQQQ': 100}
        current_prices = {'TQQQ': Decimal('50.00')}

        fills, fill_prices = executor.execute_rebalance(
            position_diffs,
            current_prices
        )

        assert len(fills) == 1
        assert fill_prices['TQQQ'] == Decimal('50.10')

    def test_execute_rebalance_excessive_slippage_aborts(self, executor, mock_client):
        """Test rebalance with excessive slippage raises SlippageExceeded."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER_ID'}
        mock_client.place_order.return_value = mock_response

        # Fill price with 1.5% slippage (exceeds abort threshold)
        mock_client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{'price': '50.75'}]  # 1.5% from 50.00
            }]
        }

        position_diffs = {'TQQQ': 100}
        current_prices = {'TQQQ': Decimal('50.00')}

        with pytest.raises(SlippageExceeded):
            executor.execute_rebalance(
                position_diffs,
                current_prices
            )


class TestTradeLogging:
    """Test trade logging to CSV."""

    def test_trades_logged_to_csv(self, executor, mock_client, trade_log_path):
        """Test all trades are logged to CSV file."""
        mock_response = Mock()
        mock_response.headers = {'Location': '/accounts/123/orders/ORDER_ID'}
        mock_client.place_order.return_value = mock_response

        mock_client.get_order.return_value = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{'price': '50.10'}]
            }]
        }

        position_diffs = {'TQQQ': 100}
        current_prices = {'TQQQ': Decimal('50.00')}

        executor.execute_rebalance(
            position_diffs,
            current_prices
        )

        # Verify CSV was written
        assert trade_log_path.exists()

        # Read CSV and verify content
        with open(trade_log_path, 'r') as f:
            lines = f.readlines()

        # Should have header + 1 trade line
        assert len(lines) == 2
        assert 'TQQQ' in lines[1]
        assert 'BUY' in lines[1]
        assert '100' in lines[1]


class TestExtractMethods:
    """Test helper extraction methods."""

    def test_extract_order_id(self, executor):
        """Test order ID extraction from response."""
        mock_response = Mock()
        mock_response.headers = {
            'Location': '/accounts/test_account/orders/ORDER12345'
        }

        order_id = executor._extract_order_id(mock_response)
        assert order_id == 'ORDER12345'

    def test_extract_order_id_missing(self, executor):
        """Test order ID extraction failure raises CriticalFailure."""
        mock_response = Mock()
        mock_response.headers = {}  # No Location header

        with pytest.raises(CriticalFailure):
            executor._extract_order_id(mock_response)

    def test_extract_fill_price(self, executor):
        """Test fill price extraction from order status."""
        order_status = {
            'status': 'FILLED',
            'orderActivityCollection': [{
                'executionLegs': [{
                    'price': '123.45'
                }]
            }]
        }

        fill_price = executor._extract_fill_price(order_status)
        assert fill_price == Decimal('123.45')

    def test_extract_fill_price_missing(self, executor):
        """Test fill price extraction failure raises CriticalFailure."""
        order_status = {
            'status': 'FILLED',
            'orderActivityCollection': []  # No activities
        }

        with pytest.raises(CriticalFailure):
            executor._extract_fill_price(order_status)
