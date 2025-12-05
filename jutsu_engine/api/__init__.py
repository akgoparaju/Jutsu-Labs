"""
Jutsu Engine API Module

FastAPI-based REST API for the Jutsu trading dashboard.
Provides endpoints for:
- System status and regime information
- Configuration management
- Trade history and export
- Performance metrics
- Engine control (start/stop)
- Indicator values

Version: 1.0.0 (Phase 3)
"""

__version__ = '1.0.0'
__author__ = 'Anil Goparaju, Padma Priya Garnepudi'

from jutsu_engine.api.main import app, create_app

__all__ = ['app', 'create_app']
