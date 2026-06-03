"""Alpaca LIVE trading adapter — crypto assets.

THIS ADAPTER TOUCHES REAL MONEY.
It raises PermissionError on instantiation unless RIA_REGISTERED=true.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from strategy_lab.core.execution import BrokerAdapter

logger = logging.getLogger(__name__)

_LIVE_BASE = "https://api.alpaca.markets/v2"


class LiveCryptoAdapter(BrokerAdapter):
    """BrokerAdapter backed by the Alpaca LIVE endpoint for crypto.

    Raises PermissionError unless the RIA_REGISTERED environment variable is
    set to 'true'.  This gate is intentional and must not be removed.
    """

    def __init__(self) -> None:
        if os.getenv("RIA_REGISTERED", "false").lower() != "true":
            raise PermissionError("Live trading not available; RIA registration pending")
        self._api_key = os.getenv("ALPACA_LIVE_KEY", "")
        self._secret = os.getenv("ALPACA_LIVE_SECRET", "")
        self._headers = {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret,
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> Any:
        resp = requests.get(f"{_LIVE_BASE}{path}", headers=self._headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> Any:
        resp = requests.post(f"{_LIVE_BASE}{path}", json=payload, headers=self._headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> bool:
        resp = requests.delete(f"{_LIVE_BASE}{path}", headers=self._headers, timeout=10)
        return resp.ok

    def submit_order(self, symbol: str, qty: float, side: str) -> dict:
        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "gtc",
        }
        data = self._post("/orders", payload)
        logger.warning("[LIVE-CRYPTO] REAL ORDER submitted: %s %s x%.6f → id=%s", side, symbol, qty, data.get("id"))
        return {"order_id": data.get("id"), "raw": data}

    def get_positions(self) -> list[dict]:
        data = self._get("/positions")
        return [
            {
                "symbol": p["symbol"],
                "qty": float(p["qty"]),
                "avg_entry_price": float(p["avg_entry_price"]),
                "current_price": float(p.get("current_price", 0)),
                "unrealized_pl": float(p.get("unrealized_pl", 0)),
            }
            for p in data
        ]

    def get_account(self) -> dict:
        data = self._get("/account")
        return {
            "equity": float(data.get("equity", 0)),
            "cash": float(data.get("cash", 0)),
            "buying_power": float(data.get("buying_power", 0)),
            "paper": False,
        }

    def cancel_order(self, order_id: str) -> bool:
        return self._delete(f"/orders/{order_id}")
