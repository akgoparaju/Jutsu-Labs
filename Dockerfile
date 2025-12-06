# Multi-stage Dockerfile for Jutsu Trading Dashboard
# Combines React frontend + FastAPI backend in single container

# ============================================================================
# Stage 1: Build React Frontend
# ============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build

# Copy package files for dependency installation
COPY dashboard/package*.json ./

# Install ALL dependencies (devDependencies needed for Vite/Rollup build)
RUN npm ci

# Copy frontend source
COPY dashboard/ ./

# Build production frontend
RUN npm run build

# ============================================================================
# Stage 2: Python Backend + Nginx Production Image
# ============================================================================
FROM python:3.11-slim

# Set metadata
LABEL maintainer="Anil Goparaju <anil.goparaju@gmail.com>"
LABEL description="Jutsu Trading Dashboard - Live/Paper Trading with Schwab API"
LABEL version="1.0.0"

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=America/New_York \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash jutsu && \
    mkdir -p /app /var/log/supervisor /var/log/nginx && \
    chown -R jutsu:jutsu /app /var/log/supervisor /var/log/nginx

WORKDIR /app

# Copy Python requirements
COPY requirements.txt .

# Install Python dependencies as root
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install gunicorn

# Copy application code
COPY jutsu_engine/ ./jutsu_engine/
COPY config/ ./config/
COPY scripts/ ./scripts/

# Copy frontend build from previous stage
COPY --from=frontend-builder /build/dist ./dashboard/dist

# Create necessary directories with proper permissions
RUN mkdir -p \
    /app/data \
    /app/state \
    /app/logs \
    /app/token_cache && \
    chown -R jutsu:jutsu \
    /app/data \
    /app/state \
    /app/logs \
    /app/token_cache

# Copy nginx configuration
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy entrypoint script
COPY docker/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port 8080 (nginx serves both static files and proxies API)
# Note: Using 8080 instead of 80 because container runs as non-root user
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/api/status || exit 1

# Switch to non-root user
USER jutsu

# Set entrypoint
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Default command (runs supervisor to manage nginx + uvicorn)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
