from __future__ import annotations

import json
import logging
from typing import Dict, List, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {}  # client_id → symbols

    async def connect(self, client_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.connections[client_id] = ws
        self.subscriptions[client_id] = set()

    def disconnect(self, client_id: str) -> None:
        self.connections.pop(client_id, None)
        self.subscriptions.pop(client_id, None)

    def subscribe(self, client_id: str, symbols: List[str]) -> None:
        if client_id in self.subscriptions:
            self.subscriptions[client_id].update(symbols)

    def unsubscribe(self, client_id: str, symbols: List[str]) -> None:
        if client_id in self.subscriptions:
            self.subscriptions[client_id] -= set(symbols)

    async def send_to_symbol_subscribers(self, symbol: str, data: dict) -> None:
        dead = []
        for client_id, ws in self.connections.items():
            if symbol in self.subscriptions.get(client_id, set()):
                try:
                    await ws.send_text(json.dumps(data))
                except Exception:
                    dead.append(client_id)
        for c in dead:
            self.disconnect(c)

    async def broadcast(self, data: dict) -> None:
        dead = []
        for client_id, ws in self.connections.items():
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(client_id)
        for c in dead:
            self.disconnect(c)


connection_manager = ConnectionManager()
