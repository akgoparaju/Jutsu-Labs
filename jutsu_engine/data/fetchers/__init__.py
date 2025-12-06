"""Data fetchers package."""
from jutsu_engine.data.fetchers.base import DataFetcher
from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher

__all__ = ['DataFetcher', 'SchwabDataFetcher']
