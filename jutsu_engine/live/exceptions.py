"""
Live Trading Exceptions - Critical error definitions.

This module defines exception classes for live trading failure conditions
that require immediate intervention or abort trading execution.
"""


class CriticalFailure(Exception):
    """
    Critical failure that requires aborting trading execution.

    Raised when conditions occur that make it unsafe to continue trading,
    such as authentication failures, extreme slippage, or data corruption.
    """
    pass


class SlippageExceeded(CriticalFailure):
    """
    Slippage exceeded critical threshold.

    Raised when fill price differs from expected price by more than
    the configured abort threshold (default: 1.0%).
    """
    pass


class AuthenticationError(CriticalFailure):
    """
    Schwab API authentication failed.

    Raised when OAuth token is invalid, expired, or API credentials
    are incorrect.
    """
    pass


class CorporateActionDetected(CriticalFailure):
    """
    Corporate action detected (split, dividend, etc).

    Raised when price movement suggests a corporate action that
    requires manual intervention.
    """
    pass


class StateCorruption(CriticalFailure):
    """
    State file is corrupted and cannot be recovered.

    Raised when state.json validation fails and no valid backup
    can be found.
    """
    pass


class PositionDriftExceeded(CriticalFailure):
    """
    Position drift between state and API exceeds threshold.

    Raised when reconciliation detects >10% drift, indicating
    manual trades or state corruption.
    """
    pass
