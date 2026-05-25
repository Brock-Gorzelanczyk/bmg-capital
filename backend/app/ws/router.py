from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.alpaca.stream import stream_manager
from app.ws.manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/stream")
async def websocket_stream(ws: WebSocket) -> None:
    client_id = str(uuid.uuid4())
    await connection_manager.connect(client_id, ws)
    logger.info(f"WebSocket client connected: {client_id}")

    # NOTE: stream callbacks are registered once at startup in main.py lifespan,
    # not here, to avoid duplicate registrations per connection.

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg: Dict[str, Any] = __import__("json").loads(raw)
                action: str = msg.get("action", "")
                symbols = [s.upper() for s in msg.get("symbols", [])]

                if action == "subscribe" and symbols:
                    connection_manager.subscribe(client_id, symbols)
                    await stream_manager.subscribe(symbols)
                    logger.debug(f"Client {client_id} subscribed to {symbols}")

                elif action == "unsubscribe" and symbols:
                    connection_manager.unsubscribe(client_id, symbols)
                    await stream_manager.unsubscribe(symbols)
                    logger.debug(f"Client {client_id} unsubscribed from {symbols}")

                else:
                    logger.warning(f"Unknown WS action from {client_id}: {action}")

            except Exception as e:
                logger.error(f"WS message parse error for {client_id}: {e}", exc_info=True)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}", exc_info=True)
    finally:
        connection_manager.disconnect(client_id)
