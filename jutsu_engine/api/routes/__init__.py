"""
API Routes Package

Contains all FastAPI route modules:
- auth: JWT authentication endpoints
- two_factor: Two-factor authentication (2FA/TOTP)
- passkey: WebAuthn/FIDO2 passkey authentication
- schwab_auth: Schwab API OAuth authentication
- status: System status and regime information
- config: Configuration management
- trades: Trade history and export
- performance: Performance metrics
- control: Engine start/stop control
- indicators: Current indicator values
- users: User management (admin-only)
- invitations: Invitation acceptance (public)
- backtest: Backtest results display
"""

from jutsu_engine.api.routes.auth import router as auth_router
from jutsu_engine.api.routes.two_factor import router as two_factor_router
from jutsu_engine.api.routes.passkey import router as passkey_router
from jutsu_engine.api.routes.schwab_auth import router as schwab_auth_router
from jutsu_engine.api.routes.status import router as status_router
from jutsu_engine.api.routes.config import router as config_router
from jutsu_engine.api.routes.trades import router as trades_router
from jutsu_engine.api.routes.performance import router as performance_router
from jutsu_engine.api.routes.control import router as control_router
from jutsu_engine.api.routes.indicators import router as indicators_router
from jutsu_engine.api.routes.users import router as users_router
from jutsu_engine.api.routes.invitations import router as invitations_router
from jutsu_engine.api.routes.backtest import router as backtest_router

__all__ = [
    'auth_router',
    'two_factor_router',
    'passkey_router',
    'schwab_auth_router',
    'status_router',
    'config_router',
    'trades_router',
    'performance_router',
    'control_router',
    'indicators_router',
    'users_router',
    'invitations_router',
    'backtest_router',
]
