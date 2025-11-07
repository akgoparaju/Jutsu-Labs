"""Tests for CLI symbol normalization."""

import pytest
from jutsu_engine.cli.main import normalize_index_symbols


class TestSymbolNormalization:
    """Test symbol normalization for index symbols."""

    def test_normalize_vix_symbol(self):
        """Test that VIX is normalized to $VIX."""
        symbols = ('QQQ', 'VIX', 'TQQQ')
        result = normalize_index_symbols(symbols)
        assert result == ('QQQ', '$VIX', 'TQQQ')

    def test_normalize_dji_symbol(self):
        """Test that DJI is normalized to $DJI."""
        symbols = ('SPY', 'DJI', 'QQQ')
        result = normalize_index_symbols(symbols)
        assert result == ('SPY', '$DJI', 'QQQ')

    def test_already_prefixed_unchanged(self):
        """Test that already-prefixed symbols are unchanged."""
        symbols = ('QQQ', '$VIX', 'TQQQ')
        result = normalize_index_symbols(symbols)
        assert result == ('QQQ', '$VIX', 'TQQQ')

    def test_regular_symbols_unchanged(self):
        """Test that regular symbols are unchanged."""
        symbols = ('AAPL', 'MSFT', 'GOOGL')
        result = normalize_index_symbols(symbols)
        assert result == ('AAPL', 'MSFT', 'GOOGL')

    def test_case_insensitive(self):
        """Test that normalization is case-insensitive."""
        symbols = ('qqq', 'vix', 'tqqq')
        result = normalize_index_symbols(symbols)
        assert result == ('QQQ', '$VIX', 'TQQQ')

    def test_multiple_index_symbols(self):
        """Test normalizing multiple index symbols."""
        symbols = ('VIX', 'DJI', 'SPX', 'QQQ')
        result = normalize_index_symbols(symbols)
        assert result == ('$VIX', '$DJI', '$SPX', 'QQQ')

    def test_empty_tuple(self):
        """Test that empty tuple is handled."""
        symbols = ()
        result = normalize_index_symbols(symbols)
        assert result == ()

    def test_none_handling(self):
        """Test that None is handled."""
        symbols = None
        result = normalize_index_symbols(symbols)
        assert result is None
