"""
FastAPI Main Application

Main entry point for the Jutsu trading dashboard API.
Configures CORS, routes, rate limiting, and middleware.

Security Features:
- Rate limiting via slowapi (configurable limits)
- CORS with environment-configurable origins
- JWT authentication
- Security event logging
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

# Load environment variables from .env file EARLY
# This ensures ENGINE_AUTO_START and other env vars are available
from dotenv import load_dotenv
load_dotenv()
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Rate limiting
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    RATE_LIMITING_AVAILABLE = False

from jutsu_engine.api.websocket import websocket_endpoint, manager
from jutsu_engine.api.routes import (
    auth_router,
    two_factor_router,
    passkey_router,
    schwab_auth_router,
    status_router,
    config_router,
    trades_router,
    performance_router,
    control_router,
    indicators_router,
)

# ==============================================================================
# RATE LIMITING CONFIGURATION
# ==============================================================================

# Rate limit configuration from environment
# Format: "X/timeunit" where timeunit is second, minute, hour, or day
LOGIN_RATE_LIMIT = os.getenv('LOGIN_RATE_LIMIT', '5/minute')
API_RATE_LIMIT = os.getenv('API_RATE_LIMIT', '100/minute')

# Create global limiter instance (if slowapi available)
if RATE_LIMITING_AVAILABLE:
    # Custom key function that gets real client IP (handles proxies/Cloudflare)
    def get_real_client_ip(request: Request) -> str:
        """Get real client IP, handling Cloudflare and reverse proxies."""
        # Cloudflare's real IP header
        cf_ip = request.headers.get('CF-Connecting-IP')
        if cf_ip:
            return cf_ip

        # X-Forwarded-For (may have multiple IPs)
        xff = request.headers.get('X-Forwarded-For')
        if xff:
            return xff.split(',')[0].strip()

        # X-Real-IP (nginx)
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip

        # Fall back to direct connection
        return get_remote_address(request)

    limiter = Limiter(key_func=get_real_client_ip)
else:
    limiter = None


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger('API')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Runs startup and shutdown logic.
    """
    # Startup
    logger.info("Jutsu API starting up...")
    
    # SECURITY CHECK: Verify no default credentials in production
    try:
        from jutsu_engine.api.dependencies import check_security_configuration
        check_security_configuration()
    except Exception as e:
        logger.error(f"Security configuration check failed: {e}")

    # Create database tables if they don't exist
    try:
        from jutsu_engine.api.dependencies import engine
        from jutsu_engine.data.models import Base
        Base.metadata.create_all(engine)
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")

    # Verify database connection
    try:
        from jutsu_engine.api.dependencies import get_db_context
        with get_db_context() as db:
            # Simple connectivity check
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.warning(f"Database connection check failed: {e}")

    # Create default admin user if auth is enabled
    try:
        from jutsu_engine.api.dependencies import ensure_admin_user_exists
        ensure_admin_user_exists()
    except Exception as e:
        logger.warning(f"Failed to ensure admin user: {e}")

    # Start WebSocket broadcast loop
    def get_ws_status():
        """Get status for WebSocket broadcasts."""
        try:
            from jutsu_engine.api.dependencies import get_engine_state
            engine = get_engine_state()
            return {
                "is_running": engine.is_running,
                "mode": engine.mode,
                "uptime_seconds": engine.get_uptime_seconds(),
            }
        except Exception:
            return None

    manager.start_broadcast_loop(get_ws_status, interval=1.0)

    # Initialize and start the scheduler service
    scheduler_service = None
    try:
        from jutsu_engine.api.scheduler import get_scheduler_service
        scheduler_service = get_scheduler_service()
        scheduler_service.start()
        logger.info(f"Scheduler service started (enabled: {scheduler_service.state.enabled})")
    except Exception as e:
        logger.warning(f"Failed to start scheduler service: {e}")

    # Auto-start trading engine if configured
    # Set ENGINE_AUTO_START=offline_mock for paper trading, or leave empty to disable
    try:
        auto_start_mode = os.environ.get('ENGINE_AUTO_START', '').lower().strip()
        if auto_start_mode in ('offline_mock', 'online_live'):
            from jutsu_engine.api.dependencies import get_engine_state
            engine_state = get_engine_state()
            if not engine_state.is_running:
                success = engine_state.start(mode=auto_start_mode)
                if success:
                    logger.info(f"Trading engine auto-started in {auto_start_mode} mode")
                else:
                    logger.warning(f"Failed to auto-start trading engine in {auto_start_mode} mode")
        elif auto_start_mode and auto_start_mode not in ('false', 'no', 'off', '0', ''):
            logger.warning(f"Invalid ENGINE_AUTO_START value: '{auto_start_mode}'. Use 'offline_mock' or 'online_live'")
    except Exception as e:
        logger.warning(f"Failed to auto-start trading engine: {e}")

    # Check if dashboard data is stale and refresh if needed (>1 hour old)
    try:
        from jutsu_engine.live.data_refresh import check_and_refresh_if_stale
        
        logger.info("Checking if dashboard data needs refresh...")
        
        # Run the async staleness check in background task
        async def startup_data_refresh():
            try:
                was_refreshed, results = await check_and_refresh_if_stale(
                    threshold_hours=1.0,
                    sync_data=True,
                )
                if was_refreshed:
                    if results and results.get('success'):
                        logger.info("Startup data refresh completed successfully")
                    else:
                        logger.warning(f"Startup data refresh had issues: {results}")
                else:
                    logger.info("Dashboard data is fresh, no startup refresh needed")
            except Exception as e:
                logger.warning(f"Startup data refresh failed: {e}")
        
        # Schedule the refresh to run after startup completes
        asyncio.create_task(startup_data_refresh())
        
    except Exception as e:
        logger.warning(f"Failed to check data freshness on startup: {e}")

    yield

    # Shutdown
    manager.stop_broadcast_loop()

    # Stop scheduler service
    if scheduler_service is not None:
        try:
            scheduler_service.stop()
            logger.info("Scheduler service stopped")
        except Exception as e:
            logger.warning(f"Error stopping scheduler service: {e}")

    logger.info("Jutsu API shutting down...")


def create_app(
    title: str = "Jutsu Trading API",
    version: str = "1.0.0",
    debug: bool = False,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        title: API title for docs
        version: API version
        debug: Enable debug mode

    Returns:
        Configured FastAPI application

    Security:
        - Set DISABLE_DOCS=true in production to hide /docs, /redoc, /openapi.json
        - OpenAPI endpoints expose API structure which could aid attackers
    """
    # Determine if docs should be enabled
    # In production, set DISABLE_DOCS=true to hide API documentation
    disable_docs = os.getenv('DISABLE_DOCS', 'false').lower() == 'true'

    if disable_docs:
        docs_url = None
        redoc_url = None
        openapi_url = None
        logger.info("OpenAPI docs disabled (DISABLE_DOCS=true)")
    else:
        docs_url = "/docs"
        redoc_url = "/redoc"
        openapi_url = "/openapi.json"
        logger.info("OpenAPI docs enabled at /docs, /redoc")

    app = FastAPI(
        title=title,
        version=version,
        description="""
        Jutsu Trading Engine API

        REST API for the Jutsu live trading dashboard.

        ## Features

        - **Auth**: JWT-based authentication for dashboard access
        - **Status**: System status, regime, and portfolio information
        - **Config**: Configuration management with runtime overrides
        - **Trades**: Trade history with filtering and CSV export
        - **Performance**: Performance metrics and equity curve
        - **Control**: Start/stop trading engine
        - **Indicators**: Current strategy indicator values

        ## Authentication

        **JWT Authentication (Recommended)**:
        Set `AUTH_REQUIRED=true` to enable JWT authentication.
        - Login: POST /api/auth/login with username/password
        - Use returned token in Authorization header: `Bearer <token>`
        - Tokens expire after 7 days

        **HTTP Basic (Legacy)**:
        Set `JUTSU_API_USERNAME` and `JUTSU_API_PASSWORD` for basic auth.

        **No Auth (Development)**:
        If neither is configured, API is open (default for local development).

        ## Database

        - **SQLite (default)**: Local file-based database for development
        - **PostgreSQL**: Server-based database for production (set `DATABASE_TYPE=postgresql`)

        ## Modes

        - `offline_mock`: Simulated trading (no real orders)
        - `online_live`: Real trading via Schwab API

        """,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
        debug=debug,
    )

    # Configure CORS from environment or use defaults
    # CORS_ORIGINS can be comma-separated list: "https://app.example.com,https://admin.example.com"
    cors_origins_env = os.getenv('CORS_ORIGINS', '')

    if cors_origins_env:
        # Production: use environment-configured origins
        cors_origins = [origin.strip() for origin in cors_origins_env.split(',') if origin.strip()]
        logger.info(f"CORS configured for production origins: {cors_origins}")
    else:
        # Development: allow localhost variants
        cors_origins = [
            "http://localhost:3000",  # React dev server
            "http://localhost:5173",  # Vite dev server
            "http://localhost:8080",  # Alternative dev port
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
        ]
        logger.info("CORS configured for local development (localhost only)")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request size limit middleware
    # Default: 10MB (configurable via MAX_REQUEST_SIZE env var)
    max_request_size = int(os.getenv('MAX_REQUEST_SIZE', str(10 * 1024 * 1024)))  # 10MB default

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        """
        Middleware to limit request body size.

        Prevents large payload attacks (DoS) by rejecting requests
        that exceed the configured maximum size.

        Configure via MAX_REQUEST_SIZE environment variable (bytes).
        Default: 10MB
        """
        content_length = request.headers.get('content-length')
        if content_length:
            try:
                size = int(content_length)
                if size > max_request_size:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "Request Entity Too Large",
                            "detail": f"Request body exceeds maximum size of {max_request_size} bytes"
                        }
                    )
            except ValueError:
                pass  # Invalid content-length header, let it through

        return await call_next(request)

    logger.info(f"Request size limit: {max_request_size / (1024*1024):.1f}MB")

    # Configure rate limiting (if available)
    if RATE_LIMITING_AVAILABLE and limiter is not None:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        logger.info(f"Rate limiting enabled: login={LOGIN_RATE_LIMIT}, api={API_RATE_LIMIT}")
    else:
        logger.warning("Rate limiting not available - install slowapi: pip install slowapi")

    # Include routers
    app.include_router(auth_router)  # Authentication endpoints
    app.include_router(two_factor_router)  # Two-factor authentication (2FA/TOTP)
    app.include_router(passkey_router)  # WebAuthn passkey authentication
    app.include_router(schwab_auth_router)  # Schwab API OAuth authentication
    app.include_router(status_router)
    app.include_router(config_router)
    app.include_router(trades_router)
    app.include_router(performance_router)
    app.include_router(control_router)
    app.include_router(indicators_router)

    # WebSocket endpoint for live updates
    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await websocket_endpoint(websocket)

    # Global exception handler - NEVER leak exception details to client
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # Log the full error for debugging (server-side only)
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        # Return generic message to client - NEVER expose internal details
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": "An unexpected error occurred. Please try again later.",
            }
        )

    # Root endpoint
    @app.get("/", tags=["root"])
    async def root():
        """API root - returns basic info."""
        response = {
            "name": title,
            "version": version,
            "status": "/api/status",
        }
        # Only advertise docs if they're enabled (security: no info disclosure)
        if not disable_docs:
            response["docs"] = "/docs"
        return response

    # API info endpoint
    @app.get("/api", tags=["root"])
    async def api_info():
        """API information."""
        response = {
            "name": title,
            "version": version,
            "endpoints": {
                "status": "/api/status",
                "config": "/api/config",
                "trades": "/api/trades",
                "performance": "/api/performance",
                "control": "/api/control",
                "indicators": "/api/indicators",
            },
        }
        # Only advertise docs if they're enabled (security: no info disclosure)
        if not disable_docs:
            response["docs"] = {
                "swagger": "/docs",
                "redoc": "/redoc",
                "openapi": "/openapi.json",
            }
        return response

    return app


# Create default app instance
app = create_app()


def run_server(
    # nosec B104 - Binding to 0.0.0.0 is required for Docker/container deployments
    # The server runs behind Cloudflare tunnel with rate limiting and auth enabled
    host: str = "0.0.0.0",  # nosec B104
    port: int = 8000,
    reload: bool = False,
    workers: int = 1,
):
    """
    Run the API server.

    Args:
        host: Host to bind to
        port: Port to bind to
        reload: Enable auto-reload for development
        workers: Number of worker processes
    """
    import uvicorn

    logger.info(f"Starting Jutsu API server on {host}:{port}")

    uvicorn.run(
        "jutsu_engine.api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level="info",
    )


if __name__ == "__main__":
    run_server(reload=True)
