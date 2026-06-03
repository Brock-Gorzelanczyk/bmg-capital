"""Alpaca paper trading adapter — US equities.

Targets paper-api.alpaca.markets only.  No real money ever touches this class.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from strategy_lab.core.execution import BrokerAdapter

logger = logging.getLogger(__name__)

_PAPER_BASE = "https://paper-api.alpaca.markets/v2"


class PaperStocksAdapter(BrokerAdapter):
    """BrokerAdapter backed by the Alpaca paper trading endpoint for US stocks."""

    def __init__(self) -> None:
        self._api_key = os.getenv("ALPACA_PAPER_KEY", "")
        self._secret = os.getenv("ALPACA_PAPER_SECRET", "")
        self._headers = {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret,
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> Any:
        resp = requests.get(f"{_PAPER_BASE}{path}", headers=self._headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> Any:
        resp = requests.post(f"{_PAPER_BASE}{path}", json=payload, headers=self._headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> bool:
        resp = requests.delete(f"{_PAPER_BASE}{path}", headers=self._headers, timeout=10)
        return resp.ok

    # ── BrokerAdapter interface ───────────────────────────────────────────

    def submit_order(self, symbol: str, qty: float, side: str) -> dict:
        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        data = self._post("/orders", payload)
        logger.info("[PAPER-STOCKS] Order submitted: %s %s x%.4f → id=%s", side, symbol, qty, data.get("id"))
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
            "paper": True,
        }

    def cancel_order(self, order_id: str) -> bool:
        return self._delete(f"/orders/{order_id}")
