"""
WebSocket support for live updates.

Provides real-time streaming of:
- Status updates (running state, uptime)
- Regime changes (cell, trend, volatility)
- Portfolio updates (positions, equity)
- Trade executions
- Indicator values

Security:
- WebSocket authentication via query parameter token when AUTH_REQUIRED=true
- Connection refused if token is invalid/expired
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Set, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("API.WEBSOCKET")


def _verify_websocket_token(token: Optional[str]) -> Optional[str]:
    """
    Verify WebSocket authentication token.

    Args:
        token: JWT token from query parameter

    Returns:
        Username if valid, None if invalid
    """
    if not token:
        return None

    try:
        from jutsu_engine.api.dependencies import decode_access_token
        payload = decode_access_token(token)

        if payload is None:
            return None

        username = payload.get("sub")
        return username
    except Exception as e:
        logger.warning(f"WebSocket token verification failed: {e}")
        return None


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._broadcast_task: Optional[asyncio.Task] = None
        self._running = False

    async def connect(self, websocket: WebSocket):
        """Accept and track new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection from tracking."""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        if not self.active_connections:
            return

        data = json.dumps(message)
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections.discard(conn)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to specific WebSocket connection."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Failed to send personal message: {e}")

    def start_broadcast_loop(self, get_status_func, interval: float = 1.0):
        """Start background task to broadcast status updates."""
        if self._running:
            return

        self._running = True
        self._broadcast_task = asyncio.create_task(
            self._broadcast_loop(get_status_func, interval)
        )
        logger.info("WebSocket broadcast loop started")

    def stop_broadcast_loop(self):
        """Stop background broadcast task."""
        self._running = False
        if self._broadcast_task:
            self._broadcast_task.cancel()
            self._broadcast_task = None
        logger.info("WebSocket broadcast loop stopped")

    async def _broadcast_loop(self, get_status_func, interval: float):
        """Background loop that broadcasts status at regular intervals."""
        while self._running:
            try:
                if self.active_connections:
                    status = get_status_func()
                    if status:
                        await self.broadcast({
                            "type": "status_update",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "data": status
                        })

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Broadcast loop error: {e}")
                await asyncio.sleep(interval)


# Global connection manager instance
manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint handler.

    Authentication:
    - If AUTH_REQUIRED=true, requires valid JWT token as query parameter
    - Connect with: ws://host/ws?token=<jwt_token>
    - Connection closed with 4001 code if authentication fails

    Messages sent by server:
    - status_update: Regular status broadcasts
    - trade_executed: When a trade executes
    - regime_change: When regime changes
    - error: Error notifications

    Messages accepted from client:
    - subscribe: Subscribe to specific update types
    - unsubscribe: Unsubscribe from update types
    - ping: Keep-alive ping (server responds with pong)
    """
    # Check if authentication is required
    auth_required = os.getenv('AUTH_REQUIRED', 'false').lower() == 'true'

    if auth_required:
        # Get token from query parameters
        token = websocket.query_params.get('token')

        if not token:
            # No token provided - reject connection
            await websocket.close(code=4001, reason="Authentication required. Provide token as query parameter.")
            logger.warning("WebSocket connection rejected: no token provided")
            return

        username = _verify_websocket_token(token)

        if not username:
            # Invalid token - reject connection
            await websocket.close(code=4001, reason="Invalid or expired token")
            logger.warning("WebSocket connection rejected: invalid token")
            return

        logger.info(f"WebSocket authenticated for user: {username}")
    else:
        username = "anonymous"

    await manager.connect(websocket)

    try:
        # Send initial connection acknowledgment
        await manager.send_personal_message({
            "type": "connected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "WebSocket connection established",
            "user": username
        }, websocket)

        # Handle incoming messages
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                msg_type = message.get("type", "")

                if msg_type == "ping":
                    await manager.send_personal_message({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }, websocket)

                elif msg_type == "subscribe":
                    # Subscription handling (future enhancement)
                    await manager.send_personal_message({
                        "type": "subscribed",
                        "channels": message.get("channels", [])
                    }, websocket)

                elif msg_type == "unsubscribe":
                    await manager.send_personal_message({
                        "type": "unsubscribed",
                        "channels": message.get("channels", [])
                    }, websocket)

                else:
                    await manager.send_personal_message({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}"
                    }, websocket)

            except json.JSONDecodeError:
                await manager.send_personal_message({
                    "type": "error",
                    "message": "Invalid JSON"
                }, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# Utility functions for broadcasting specific events
async def broadcast_trade_executed(trade_data: dict):
    """Broadcast trade execution event."""
    await manager.broadcast({
        "type": "trade_executed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": trade_data
    })


async def broadcast_regime_change(regime_data: dict):
    """Broadcast regime change event."""
    await manager.broadcast({
        "type": "regime_change",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": regime_data
    })


async def broadcast_error(error_message: str):
    """Broadcast error notification."""
    await manager.broadcast({
        "type": "error",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": error_message
    })


async def broadcast_data_refresh(refresh_data: dict = None):
    """
    Broadcast data refresh event.

    Called after hourly refresh completes to notify frontend
    to invalidate cached queries and fetch fresh data.
    """
    await manager.broadcast({
        "type": "data_refresh",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": refresh_data or {}
    })
