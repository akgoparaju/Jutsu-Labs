"""JWT authentication utilities.

Provides token creation and validation for API authentication.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from jutsu_api.config import get_settings
import logging

logger = logging.getLogger("API.AUTH")

security = HTTPBearer()
settings = get_settings()


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """
    Create JWT access token.

    Args:
        data: Data to encode in token (typically {"sub": username})
        expires_delta: Token expiration duration (default: from settings)

    Returns:
        Encoded JWT token string

    Example:
        token = create_access_token({"sub": "user@example.com"})
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.access_token_expire_minutes
        )
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.algorithm
    )

    logger.info(f"Access token created for: {data.get('sub', 'unknown')}")
    return encoded_jwt


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Validate JWT token and extract current user.

    Args:
        credentials: Bearer token from Authorization header

    Returns:
        Username from token

    Raises:
        HTTPException: 401 if token is invalid or expired

    Usage:
        @router.get("/protected")
        async def protected_route(user: str = Depends(get_current_user)):
            return {"user": user}
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        username: str = payload.get("sub")
        if username is None:
            logger.warning("Token missing 'sub' claim")
            raise credentials_exception

        logger.debug(f"Authenticated user: {username}")
        return username

    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise credentials_exception
