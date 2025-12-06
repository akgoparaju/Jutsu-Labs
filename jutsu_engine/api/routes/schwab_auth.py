"""
Schwab API Authentication Routes.

Provides endpoints for OAuth authentication with Schwab API:
- GET /api/schwab/status: Check token status
- POST /api/schwab/initiate: Start OAuth flow, get authorization URL
- POST /api/schwab/callback: Complete OAuth flow with callback URL

Designed to work in both local development and Docker environments
using the manual OAuth flow (copy-paste URLs).
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from jutsu_engine.api.dependencies import get_current_user
from jutsu_engine.utils.config import get_config

logger = logging.getLogger('API.SCHWAB_AUTH')

router = APIRouter(prefix="/api/schwab", tags=["schwab-auth"])


# ==============================================================================
# SCHEMAS
# ==============================================================================

class SchwabAuthStatus(BaseModel):
    """Schwab authentication status response."""
    authenticated: bool
    token_exists: bool
    token_valid: bool
    token_age_days: Optional[float] = None
    expires_in_days: Optional[float] = None
    message: str
    callback_url: Optional[str] = None


class SchwabAuthInitiate(BaseModel):
    """OAuth initiation response with authorization URL."""
    authorization_url: str
    callback_url: str
    state: str
    instructions: str


class SchwabAuthCallback(BaseModel):
    """OAuth callback request - user pastes the redirect URL."""
    callback_url: str


class SchwabAuthCallbackResponse(BaseModel):
    """OAuth callback response."""
    success: bool
    message: str
    token_created: bool


# ==============================================================================
# TOKEN UTILITIES
# ==============================================================================

def get_schwab_config() -> dict:
    """Get Schwab API configuration from environment."""
    config = get_config()

    api_key = os.getenv('SCHWAB_API_KEY') or config.get('SCHWAB_API_KEY')
    api_secret = os.getenv('SCHWAB_API_SECRET') or config.get('SCHWAB_API_SECRET')
    callback_url = os.getenv('SCHWAB_CALLBACK_URL') or config.get('SCHWAB_CALLBACK_URL', 'https://127.0.0.1:8182')
    token_path = os.getenv('SCHWAB_TOKEN_PATH') or config.get('SCHWAB_TOKEN_PATH', 'token.json')

    # Handle Docker paths
    if Path('/app').exists() and not token_path.startswith('/'):
        token_path = f'/app/data/{token_path}'

    return {
        'api_key': api_key,
        'api_secret': api_secret,
        'callback_url': callback_url,
        'token_path': token_path,
    }


def get_token_status() -> dict:
    """
    Check Schwab token file status.

    Returns:
        dict with token status information
    """
    schwab_config = get_schwab_config()
    token_path = schwab_config['token_path']

    result = {
        'token_exists': False,
        'token_valid': False,
        'token_age_days': None,
        'expires_in_days': None,
        'creation_timestamp': None,
    }

    if not os.path.isfile(token_path):
        return result

    result['token_exists'] = True

    try:
        with open(token_path, 'r') as f:
            token_data = json.load(f)

        # schwab-py wraps tokens with metadata
        if 'creation_timestamp' in token_data:
            creation_ts = token_data['creation_timestamp']
            result['creation_timestamp'] = creation_ts

            # Calculate age
            age_seconds = time.time() - creation_ts
            result['token_age_days'] = age_seconds / (24 * 60 * 60)

            # Schwab tokens expire after 7 days
            max_age_seconds = 7 * 24 * 60 * 60
            remaining_seconds = max_age_seconds - age_seconds
            result['expires_in_days'] = remaining_seconds / (24 * 60 * 60)

            # Token is valid if less than 7 days old
            result['token_valid'] = remaining_seconds > 0
        else:
            # Legacy token format - can't determine validity
            result['token_valid'] = False

    except (json.JSONDecodeError, KeyError, IOError) as e:
        logger.warning(f"Error reading token file: {e}")
        result['token_valid'] = False

    return result


# ==============================================================================
# IN-MEMORY AUTH STATE
# ==============================================================================

# Store pending OAuth states (in production, use Redis or DB)
_pending_auth_states: dict = {}


# ==============================================================================
# ROUTES
# ==============================================================================

@router.get("/status", response_model=SchwabAuthStatus)
async def get_schwab_auth_status(
    current_user=Depends(get_current_user)
):
    """
    Get current Schwab API authentication status.

    Returns information about:
    - Whether token exists
    - Whether token is valid (not expired)
    - Token age and expiration
    - Configured callback URL
    """
    schwab_config = get_schwab_config()
    token_status = get_token_status()

    # Check if API credentials are configured
    if not schwab_config['api_key'] or not schwab_config['api_secret']:
        return SchwabAuthStatus(
            authenticated=False,
            token_exists=False,
            token_valid=False,
            message="Schwab API credentials not configured. Set SCHWAB_API_KEY and SCHWAB_API_SECRET.",
            callback_url=schwab_config['callback_url'],
        )

    if not token_status['token_exists']:
        return SchwabAuthStatus(
            authenticated=False,
            token_exists=False,
            token_valid=False,
            message="No token found. Please authenticate with Schwab API.",
            callback_url=schwab_config['callback_url'],
        )

    if not token_status['token_valid']:
        expires_msg = ""
        if token_status['token_age_days'] is not None:
            expires_msg = f" Token is {token_status['token_age_days']:.1f} days old (max 7 days)."

        return SchwabAuthStatus(
            authenticated=False,
            token_exists=True,
            token_valid=False,
            token_age_days=token_status['token_age_days'],
            expires_in_days=token_status['expires_in_days'],
            message=f"Token expired.{expires_msg} Please re-authenticate.",
            callback_url=schwab_config['callback_url'],
        )

    return SchwabAuthStatus(
        authenticated=True,
        token_exists=True,
        token_valid=True,
        token_age_days=token_status['token_age_days'],
        expires_in_days=token_status['expires_in_days'],
        message=f"Authenticated. Token expires in {token_status['expires_in_days']:.1f} days.",
        callback_url=schwab_config['callback_url'],
    )


@router.post("/initiate", response_model=SchwabAuthInitiate)
async def initiate_schwab_auth(
    current_user=Depends(get_current_user)
):
    """
    Initiate Schwab OAuth authentication flow.

    Returns an authorization URL that the user must open in a browser
    to log in to Schwab. After login, Schwab redirects to the callback URL.
    The user must copy that URL and submit it to the /callback endpoint.

    This flow works in both local and Docker environments.
    """
    schwab_config = get_schwab_config()

    # Validate configuration
    if not schwab_config['api_key'] or not schwab_config['api_secret']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schwab API credentials not configured. Set SCHWAB_API_KEY and SCHWAB_API_SECRET in .env"
        )

    try:
        # Import schwab auth module
        from schwab.auth import get_auth_context

        # Generate OAuth authorization URL
        auth_context = get_auth_context(
            schwab_config['api_key'],
            schwab_config['callback_url']
        )

        # Store state for callback validation
        _pending_auth_states[auth_context.state] = {
            'created_at': time.time(),
            'callback_url': auth_context.callback_url,
        }

        # Clean up old states (older than 10 minutes)
        current_time = time.time()
        expired_states = [
            s for s, data in _pending_auth_states.items()
            if current_time - data['created_at'] > 600
        ]
        for s in expired_states:
            del _pending_auth_states[s]

        logger.info(f"Initiated Schwab OAuth flow, state: {auth_context.state[:8]}...")

        return SchwabAuthInitiate(
            authorization_url=auth_context.authorization_url,
            callback_url=auth_context.callback_url,
            state=auth_context.state,
            instructions=(
                "1. Open the authorization URL in your browser\n"
                "2. Log in to your Schwab account\n"
                "3. Authorize the application\n"
                "4. Copy the ENTIRE URL from your browser's address bar after redirect\n"
                "5. Paste that URL into the callback field and submit"
            )
        )

    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="schwab-py library not installed. Run: pip install schwab-py"
        )
    except Exception as e:
        logger.error(f"Failed to initiate Schwab auth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate authentication: {str(e)}"
        )


@router.post("/callback", response_model=SchwabAuthCallbackResponse)
async def complete_schwab_auth(
    data: SchwabAuthCallback,
    current_user=Depends(get_current_user)
):
    """
    Complete Schwab OAuth authentication with callback URL.

    After the user authorizes the app in their browser, they are redirected
    to the callback URL. They must copy that entire URL and submit it here
    to complete the authentication and receive their access token.
    """
    schwab_config = get_schwab_config()

    # Validate configuration
    if not schwab_config['api_key'] or not schwab_config['api_secret']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schwab API credentials not configured"
        )

    received_url = data.callback_url.strip()

    if not received_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Callback URL is required"
        )

    # Extract state from received URL
    from urllib.parse import urlparse, parse_qs

    try:
        parsed = urlparse(received_url)
        params = parse_qs(parsed.query)
        received_state = params.get('state', [None])[0]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid callback URL format: {e}"
        )

    # Validate state (CSRF protection)
    if received_state not in _pending_auth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state. Please restart the authentication flow."
        )

    # Get stored auth state
    auth_state_data = _pending_auth_states.pop(received_state)

    try:
        # Import schwab auth modules
        from schwab.auth import get_auth_context, client_from_received_url

        # Reconstruct auth context with the stored state
        auth_context = get_auth_context(
            schwab_config['api_key'],
            auth_state_data['callback_url'],
            state=received_state
        )

        # Token write function
        token_path = schwab_config['token_path']

        def token_write_func(token, *args, **kwargs):
            logger.info(f"Writing token to {token_path}")
            # Ensure directory exists
            token_dir = os.path.dirname(token_path)
            if token_dir:
                os.makedirs(token_dir, exist_ok=True)
            with open(token_path, 'w') as f:
                json.dump(token, f)

        # Exchange callback URL for token
        client = client_from_received_url(
            schwab_config['api_key'],
            schwab_config['api_secret'],
            auth_context,
            received_url,
            token_write_func,
            asyncio=False,
            enforce_enums=False
        )

        logger.info("Successfully authenticated with Schwab API")

        return SchwabAuthCallbackResponse(
            success=True,
            message="Successfully authenticated with Schwab API. Token saved.",
            token_created=True
        )

    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="schwab-py library not installed. Run: pip install schwab-py"
        )
    except Exception as e:
        logger.error(f"Failed to complete Schwab auth: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to complete authentication: {str(e)}"
        )


@router.delete("/token")
async def delete_schwab_token(
    current_user=Depends(get_current_user)
):
    """
    Delete the current Schwab token.

    This forces re-authentication on the next API call.
    Useful for testing or when token is corrupted.
    """
    schwab_config = get_schwab_config()
    token_path = schwab_config['token_path']

    if os.path.isfile(token_path):
        try:
            os.remove(token_path)
            logger.info(f"Deleted Schwab token at {token_path}")
            return {"success": True, "message": "Token deleted successfully"}
        except OSError as e:
            logger.error(f"Failed to delete token: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete token: {str(e)}"
            )
    else:
        return {"success": True, "message": "No token file exists"}
