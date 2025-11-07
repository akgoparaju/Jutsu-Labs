"""API middleware for request processing.

Implements rate limiting, logging, and other cross-cutting concerns.
"""
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import time
from collections import defaultdict
from typing import Dict, List
import logging

logger = logging.getLogger("API.MIDDLEWARE")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using token bucket algorithm.

    Limits requests per client IP address to prevent abuse.

    Attributes:
        requests_per_minute: Maximum requests allowed per minute per IP
        requests: Dictionary tracking request timestamps per IP
    """

    def __init__(self, app, requests_per_minute: int = 60):
        """
        Initialize rate limiter.

        Args:
            app: FastAPI application
            requests_per_minute: Max requests per minute (default: 60)
        """
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests: Dict[str, List[float]] = defaultdict(list)
        logger.info(f"Rate limiter initialized: {requests_per_minute} req/min")

    async def dispatch(self, request: Request, call_next):
        """
        Process request with rate limiting.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler

        Returns:
            HTTP response

        Raises:
            HTTPException: 429 if rate limit exceeded
        """
        client_ip = request.client.host
        now = time.time()

        # Clean old requests (older than 1 minute)
        self.requests[client_ip] = [
            req_time for req_time in self.requests[client_ip]
            if now - req_time < 60
        ]

        # Check rate limit
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            logger.warning(
                f"Rate limit exceeded for {client_ip}: "
                f"{len(self.requests[client_ip])} requests in last minute"
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later."
            )

        # Add current request
        self.requests[client_ip].append(now)

        # Process request
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        # Add response time header
        response.headers["X-Process-Time"] = str(process_time)

        logger.debug(
            f"{request.method} {request.url.path} - "
            f"{response.status_code} - {process_time:.3f}s"
        )

        return response
