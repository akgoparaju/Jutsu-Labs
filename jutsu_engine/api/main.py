"""
FastAPI Main Application

Main entry point for the Jutsu trading dashboard API.
Configures CORS, routes, and middleware.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from jutsu_engine.api.websocket import websocket_endpoint, manager
from jutsu_engine.api.routes import (
    auth_router,
    schwab_auth_router,
    status_router,
    config_router,
    trades_router,
    performance_router,
    control_router,
    indicators_router,
)

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
    """
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
        - Login: POST /auth/login with username/password
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
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        debug=debug,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",  # React dev server
            "http://localhost:5173",  # Vite dev server
            "http://localhost:8080",  # Alternative dev port
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(auth_router)  # Authentication endpoints
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

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": str(exc) if debug else None,
            }
        )

    # Root endpoint
    @app.get("/", tags=["root"])
    async def root():
        """API root - returns basic info."""
        return {
            "name": title,
            "version": version,
            "docs": "/docs",
            "status": "/api/status",
        }

    # API info endpoint
    @app.get("/api", tags=["root"])
    async def api_info():
        """API information."""
        return {
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
            "docs": {
                "swagger": "/docs",
                "redoc": "/redoc",
                "openapi": "/openapi.json",
            }
        }

    return app


# Create default app instance
app = create_app()


def run_server(
    host: str = "0.0.0.0",
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
