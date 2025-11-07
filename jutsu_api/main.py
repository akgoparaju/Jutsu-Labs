"""FastAPI main application.

Initializes and configures the REST API with all routers,
middleware, and CORS settings.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import logging

from jutsu_api.routers import backtest, data, strategies, optimization
from jutsu_api.middleware import RateLimitMiddleware
from jutsu_api.models.schemas import HealthResponse
from jutsu_api.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("API.MAIN")

# Initialize settings
settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title="Jutsu Labs API",
    description="Modular backtesting engine REST API for algorithmic trading strategies",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    contact={
        "name": "Jutsu Labs",
        "email": "support@jutsulabs.com"
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT"
    }
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.rate_limit_rpm
)

# Include routers
app.include_router(
    backtest.router,
    prefix="/api/v1/backtest",
    tags=["backtest"]
)
app.include_router(
    data.router,
    prefix="/api/v1/data",
    tags=["data"]
)
app.include_router(
    strategies.router,
    prefix="/api/v1/strategies",
    tags=["strategies"]
)
app.include_router(
    optimization.router,
    prefix="/api/v1/optimization",
    tags=["optimization"]
)


@app.get("/", response_model=HealthResponse)
async def root():
    """
    Root endpoint with API information.

    Returns:
        API status and version information

    Example:
        GET /
        Response: {
            "status": "healthy",
            "version": "0.2.0",
            "timestamp": "2024-01-01T00:00:00"
        }
    """
    return HealthResponse(
        status="healthy",
        version="0.2.0"
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint for monitoring.

    Returns:
        Health status of the service

    Example:
        GET /health
        Response: {
            "status": "healthy",
            "version": "0.2.0",
            "timestamp": "2024-01-01T00:00:00"
        }
    """
    return HealthResponse(
        status="healthy",
        version="0.2.0"
    )


@app.on_event("startup")
async def startup_event():
    """
    Startup event handler.

    Logs application startup information and initializes resources.
    """
    logger.info("=" * 60)
    logger.info("Jutsu Labs API starting up...")
    logger.info(f"Version: 0.2.0")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database: {settings.database_url}")
    logger.info(f"Rate limit: {settings.rate_limit_rpm} req/min")
    logger.info(f"CORS origins: {', '.join(settings.cors_origins)}")
    logger.info("=" * 60)
    logger.info("API documentation available at: /docs")
    logger.info("Alternative documentation at: /redoc")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """
    Shutdown event handler.

    Performs cleanup before application shutdown.
    """
    logger.info("=" * 60)
    logger.info("Jutsu Labs API shutting down...")
    logger.info("Performing cleanup...")
    # Add cleanup tasks here (close connections, etc.)
    logger.info("Shutdown complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "jutsu_api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info"
    )
