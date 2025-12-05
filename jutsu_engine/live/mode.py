"""
Trading Mode Enumeration - Define execution modes for live trading.

This module provides the TradingMode enum used to distinguish between
offline mock (dry-run) and online live trading modes throughout
the live trading system.

Version: 2.0 (PRD v2.0.1 Compliant)
"""

from enum import Enum, auto


class TradingMode(Enum):
    """
    Trading execution mode enumeration.

    Defines the two primary modes of operation:
    - OFFLINE_MOCK: Dry-run mode with hypothetical orders (no real trades)
    - ONLINE_LIVE: Live trading with real order execution via broker API

    Usage:
        from jutsu_engine.live.mode import TradingMode

        mode = TradingMode.OFFLINE_MOCK
        if mode == TradingMode.OFFLINE_MOCK:
            executor = MockOrderExecutor(...)
        else:
            executor = OrderExecutor(...)

    Database mapping:
        The mode is stored as string in database tables:
        - "offline_mock" for OFFLINE_MOCK
        - "online_live" for ONLINE_LIVE
    """

    OFFLINE_MOCK = "offline_mock"
    ONLINE_LIVE = "online_live"

    @classmethod
    def from_string(cls, value: str) -> 'TradingMode':
        """
        Parse TradingMode from string value.

        Args:
            value: Mode string ("offline_mock", "online_live", "mock", "live", "dry_run")

        Returns:
            TradingMode enum value

        Raises:
            ValueError: If value is not a valid mode string

        Examples:
            >>> TradingMode.from_string("offline_mock")
            TradingMode.OFFLINE_MOCK

            >>> TradingMode.from_string("live")
            TradingMode.ONLINE_LIVE
        """
        # Normalize input
        normalized = value.lower().strip().replace("-", "_").replace(" ", "_")

        # Map aliases to canonical values
        mode_map = {
            "offline_mock": cls.OFFLINE_MOCK,
            "online_live": cls.ONLINE_LIVE,
            "mock": cls.OFFLINE_MOCK,
            "live": cls.ONLINE_LIVE,
            "dry_run": cls.OFFLINE_MOCK,
            "dryrun": cls.OFFLINE_MOCK,
            "paper": cls.OFFLINE_MOCK,  # Paper trading is also mock
        }

        if normalized in mode_map:
            return mode_map[normalized]

        raise ValueError(
            f"Invalid trading mode: '{value}'. "
            f"Valid values: {list(mode_map.keys())}"
        )

    @property
    def is_mock(self) -> bool:
        """Return True if this is mock/dry-run mode."""
        return self == TradingMode.OFFLINE_MOCK

    @property
    def is_live(self) -> bool:
        """Return True if this is live trading mode."""
        return self == TradingMode.ONLINE_LIVE

    @property
    def db_value(self) -> str:
        """Return database-compatible string value."""
        return self.value

    def __str__(self) -> str:
        """Return human-readable mode name."""
        return self.value.replace("_", " ").title()
