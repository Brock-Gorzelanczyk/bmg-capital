"""Alpaca LIVE trading adapter — crypto assets.

THIS ADAPTER TOUCHES REAL MONEY.
It raises PermissionError on instantiation unless RIA_REGISTERED=true.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from typing import Optional

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

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        stop_price: float,
        target_price: float,
        limit_price: Optional[float] = None,
    ) -> dict:
        """Submit an OCO bracket order via Alpaca LIVE API for crypto.

        THIS TOUCHES REAL MONEY — only callable when RIA_REGISTERED=true.
        Crypto always uses GTC time_in_force.
        """
        payload: dict = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "time_in_force": "gtc",
            "order_class": "bracket",
            "take_profit": {"limit_price": str(target_price)},
            "stop_loss": {"stop_price": str(stop_price)},
        }
        if limit_price is not None:
            payload["type"] = "limit"
            payload["limit_price"] = str(limit_price)
        else:
            payload["type"] = "market"

        data = self._post("/orders", payload)
        logger.warning(
            "[LIVE-CRYPTO] REAL BRACKET ORDER: %s %s x%.6f entry=%s stop=%.4f target=%.4f → id=%s",
            side, symbol, qty,
            f"limit@{limit_price}" if limit_price else "market",
            stop_price, target_price, data.get("id"),
        )
        return {"order_id": data.get("id"), "raw": data}
