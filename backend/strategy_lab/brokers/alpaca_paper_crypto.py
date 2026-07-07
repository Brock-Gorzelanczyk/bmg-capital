"""Alpaca paper trading adapter — crypto assets.

Targets paper-api.alpaca.markets only.  No real money ever touches this class.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from typing import Optional

from strategy_lab.core.execution import BrokerAdapter

logger = logging.getLogger(__name__)

_PAPER_BASE = "https://paper-api.alpaca.markets/v2"


class PaperCryptoAdapter(BrokerAdapter):
    """BrokerAdapter backed by the Alpaca paper trading endpoint for crypto."""

    def __init__(self) -> None:
        self._api_key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
        self._secret = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
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
        if not resp.ok:
            # Surface Alpaca's rejection reason ({"message": "..."}) instead of just
            # the HTTP status code — otherwise "422 Unprocessable Entity" gives us
            # nothing actionable when a bracket order fails (e.g. ATOM/USD).
            body = resp.text[:500]
            raise requests.HTTPError(
                f"{resp.status_code} {resp.reason} for {path}: {body}",
                response=resp,
            )
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
            "time_in_force": "gtc",  # crypto uses GTC, not DAY
        }
        data = self._post("/orders", payload)
        logger.info("[PAPER-CRYPTO] Order submitted: %s %s x%.6f → id=%s", side, symbol, qty, data.get("id"))
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

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        stop_price: float,
        target_price: float,
        limit_price: Optional[float] = None,
        extended_hours: bool = False,  # accepted for signature parity with the stocks adapter — crypto trades 24/7
    ) -> dict:
        """Submit an entry order for crypto.

        NB: Alpaca paper crypto REJECTS bracket / OTOCO orders with
        `crypto orders not allowed for advanced order_class`. Confirmed
        via 2026-07-07 Sentry sweep of every crypto attempt in prod.
        Bracket semantics (stop_price / target_price) are handled by
        the position_monitor loop server-side, so we downgrade to a
        simple market/limit order here and let the monitor manage exits.

        Stop and target are logged so downstream reconciliation can
        cross-check that the position_monitor honored them.
        """
        payload: dict = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "time_in_force": "gtc",
        }
        if limit_price is not None:
            payload["type"] = "limit"
            payload["limit_price"] = str(limit_price)
        else:
            payload["type"] = "market"

        data = self._post("/orders", payload)
        logger.info(
            "[PAPER-CRYPTO] Simple order (bracket downgraded): %s %s x%.6f "
            "entry=%s stop=%.4f target=%.4f (managed by position_monitor) → id=%s",
            side, symbol, qty,
            f"limit@{limit_price}" if limit_price else "market",
            stop_price, target_price, data.get("id"),
        )
        return {"order_id": data.get("id"), "raw": data}
