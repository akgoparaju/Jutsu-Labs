"""
Logging configuration for the Jutsu Labs backtesting engine.

Provides module-based loggers with timestamps and proper formatting.
All logs are written to a single monolithic log file: jutsu_labs_log_<datetime>.log
"""
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from typing import Optional

# Global shared log file path (created once per session)
_SHARED_LOG_FILE: Optional[Path] = None


def _get_shared_log_file() -> Path:
    """
    Get or create the shared log file path.

    Creates a single log file for all modules with format:
    jutsu_labs_log_YYYY-MM-DD_HHMMSS.log

    Returns:
        Path to shared log file
    """
    global _SHARED_LOG_FILE

    if _SHARED_LOG_FILE is None:
        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Timestamp for log file (only created once per session)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')

        # Single monolithic log file
        _SHARED_LOG_FILE = log_dir / f"jutsu_labs_log_{timestamp}.log"

    return _SHARED_LOG_FILE


def setup_logger(
    name: str, level: int = logging.INFO, log_to_console: bool = True
) -> logging.Logger:
    """
    Setup a logger with file and optional console handlers.

    All loggers write to a single shared log file: jutsu_labs_log_<datetime>.log
    Follows format: "YYYY-MM-DD HH:MM:SS | MODULE.NAME | LEVEL | Message"

    Args:
        name: Logger name (e.g., 'DATA.SCHWAB', 'STRATEGY.SMA', 'PORTFOLIO')
        level: Logging level (logging.DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_console: Whether to also output to console

    Returns:
        Configured Logger instance

    Example:
        logger = setup_logger('DATA.SCHWAB', level=logging.DEBUG)
        logger.info("Fetching AAPL data from 2024-01-01")
        # Output in jutsu_labs_log_2025-11-07_143022.log:
        # 2025-11-07 14:30:22 | DATA.SCHWAB | INFO | Fetching AAPL data...
    """
    # Get or create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding duplicate handlers
    if logger.handlers:
        return logger

    # Get shared log file path
    log_file = _get_shared_log_file()

    # File handler writing to shared log file
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=50 * 1024 * 1024,  # 50MB (larger since it's shared)
        backupCount=10,  # Keep 10 backup files
    )
    file_handler.setLevel(level)

    # Formatter with timestamp and module name
    formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler (optional)
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get existing logger or create new one with default settings.

    Args:
        name: Logger name

    Returns:
        Logger instance

    Example:
        logger = get_logger('STRATEGY.RSI')
        logger.debug("RSI value: 45.3")
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


# Module-specific logger factories
def get_data_logger(source: str = 'DATA') -> logging.Logger:
    """Get logger for data operations."""
    return get_logger(f'DATA.{source.upper()}')


def get_strategy_logger(strategy_name: str) -> logging.Logger:
    """Get logger for strategy operations."""
    return get_logger(f'STRATEGY.{strategy_name.upper()}')


def get_portfolio_logger() -> logging.Logger:
    """Get logger for portfolio operations."""
    return get_logger('PORTFOLIO')


def get_performance_logger() -> logging.Logger:
    """Get logger for performance analysis."""
    return get_logger('PERFORMANCE')


def get_engine_logger() -> logging.Logger:
    """Get logger for event loop operations."""
    return get_logger('ENGINE')


# Pre-configured loggers for common modules
DATA_LOGGER = get_data_logger()
PORTFOLIO_LOGGER = get_portfolio_logger()
PERFORMANCE_LOGGER = get_performance_logger()
ENGINE_LOGGER = get_engine_logger()
