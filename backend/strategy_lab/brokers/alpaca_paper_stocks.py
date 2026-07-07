"""Alpaca paper trading adapter — US equities.

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


class PaperStocksAdapter(BrokerAdapter):
    """BrokerAdapter backed by the Alpaca paper trading endpoint for US stocks."""

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
            # 2026-07-07: raise_for_status hides the response body which is
            # where Alpaca puts the actual rejection reason. Include the
            # first 300 chars of body in the exception so [ALPACA-REJECT]
            # log lines are actionable.
            body = ""
            try:
                body = resp.text[:300]
            except Exception:
                pass
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

    def submit_options_order(
        self,
        contract_symbol: str,
        contracts: int,
        side: str,
        limit_price: float,
        time_in_force: str = "day",
    ) -> dict:
        """Submit a single-leg options limit order to Alpaca paper.

        Returns raw dict with status_code, body, and order_id — does NOT
        raise_for_status so callers can inspect error responses.
        """
        payload = {
            "symbol": contract_symbol,
            "qty": str(contracts),
            "side": side,
            "type": "limit",
            "time_in_force": time_in_force,
            "limit_price": str(limit_price),
            "order_class": "simple",
        }
        resp = requests.post(
            f"{_PAPER_BASE}/orders",
            json=payload,
            headers=self._headers,
            timeout=10,
        )
        data = resp.json() if resp.content else {}
        return {"status_code": resp.status_code, "body": data, "order_id": data.get("id")}

    def _get_owned_qty(self, symbol: str) -> float:
        """Return current owned qty at Alpaca for symbol. Zero if not held.

        Used pre-flight before SELL orders to avoid Alpaca rejecting with
        'fractional orders cannot be sold short' when we don't have the
        position. Cheap: /v2/positions/{symbol} is one request, cached
        60s inside Alpaca side.
        """
        try:
            resp = requests.get(
                f"{_PAPER_BASE}/positions/{symbol}",
                headers=self._headers,
                timeout=5,
            )
            if resp.status_code == 404:
                return 0.0
            resp.raise_for_status()
            data = resp.json()
            return abs(float(data.get("qty", 0) or 0))
        except Exception:
            return 0.0

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        stop_price: float,
        target_price: float,
        limit_price: Optional[float] = None,
        extended_hours: bool = False,
    ) -> dict:
        """Submit an entry order to Alpaca paper.

        NB: 2026-07-07 — bracket orders were rejecting ~80% of stock
        submissions because our runner computes stop_price/target_price
        from a cached entry_price, which drifts from Alpaca's live
        base_price. Alpaca requires take_profit > base_price for BUY and
        < base_price for SELL, so any drift produced 422 rejects with
        "take_profit.limit_price must be >= base_price + 0.01".

        Fix: downgrade to a plain limit order (or market if no limit).
        Stop and target still logged so position_monitor can close
        server-side. Same approach the crypto adapter now uses.

        For SELL orders: pre-flight check that we actually own the qty.
        Alpaca's "fractional orders cannot be sold short" rejects any
        fractional sell where owned_qty=0 or < requested_qty. Skip the
        submit entirely in that case rather than eat a hard reject.
        """
        if side == "sell":
            owned = self._get_owned_qty(symbol)
            if owned < qty:
                # Don't try to sell what we don't own. Downsize or skip.
                if owned <= 0:
                    logger.info(
                        "[PAPER-STOCKS] SKIP sell %s x%.4f — Alpaca owned=0 "
                        "(would reject as fractional short)",
                        symbol, qty,
                    )
                    return {"order_id": None, "raw": {"skipped": "no_position"}}
                logger.info(
                    "[PAPER-STOCKS] downsize sell %s %.4f -> %.4f (owned)",
                    symbol, qty, owned,
                )
                qty = owned
        # 2026-07-07: downgrade to simple market/limit order (no bracket).
        # Alpaca's bracket geometry (take_profit direction, stop_loss
        # direction) is validated against base_price at submit time. Our
        # stop_price / target_price are computed off cached entry_price
        # which drifts from Alpaca's base_price during volatile market
        # opens. Result: 80%+ of stock brackets rejected with
        # "take_profit.limit_price must be >= base_price + 0.01" or
        # "take_profit.limit_price must be < stop_loss.stop_price".
        # Server-side position_monitor handles exits at stop_price /
        # target_price. Same fix pattern as crypto adapter.
        if extended_hours:
            entry_limit = limit_price or round((stop_price + target_price) / 2, 4)
            payload: dict = {
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "limit",
                "time_in_force": "day",
                "limit_price": str(entry_limit),
                "extended_hours": True,
            }
            data = self._post("/orders", payload)
            logger.info(
                "[PAPER-STOCKS] Extended-hours limit order: %s %s x%.4f limit=%.4f → id=%s",
                side, symbol, qty, entry_limit, data.get("id"),
            )
            return {"order_id": data.get("id"), "raw": data}

        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "time_in_force": "day",
        }
        if limit_price is not None:
            payload["type"] = "limit"
            payload["limit_price"] = str(limit_price)
        else:
            payload["type"] = "market"

        data = self._post("/orders", payload)
        logger.info(
            "[PAPER-STOCKS] Simple order (bracket downgraded): %s %s x%.4f entry=%s "
            "stop=%.4f target=%.4f (managed by position_monitor) → id=%s",
            side, symbol, qty,
            f"limit@{limit_price}" if limit_price else "market",
            stop_price, target_price, data.get("id"),
        )
        return {"order_id": data.get("id"), "raw": data}

    def get_activities(
        self,
        activity_type: str = "FILL",
        after: Optional[str] = None,
        until: Optional[str] = None,
        page_size: int = 100,
    ) -> list[dict]:
        """GET /v2/account/activities/{activity_type}. Returns raw list.

        Parameters after/until are ISO date strings (YYYY-MM-DD).
        Empty list on non-200 / timeout / any error. Never raises.
        """
        try:
            params: list[str] = [f"page_size={page_size}"]
            if after:
                params.append(f"after={after}")
            if until:
                params.append(f"until={until}")
            query = "&".join(params)
            path = f"/account/activities/{activity_type}"
            if query:
                path = f"{path}?{query}"
            resp = requests.get(
                f"{_PAPER_BASE}{path}",
                headers=self._headers,
                timeout=10,
            )
            if resp.status_code == 429:
                logger.warning("[alpaca] get_activities rate-limited (429) for %s", activity_type)
                return []
            if not resp.ok:
                logger.warning(
                    "[alpaca] get_activities non-200 for %s: status=%d",
                    activity_type, resp.status_code,
                )
                return []
            data = resp.json()
            if not isinstance(data, list):
                logger.warning("[alpaca] get_activities unexpected shape: %r", type(data))
                return []
            return data
        except requests.exceptions.RequestException as exc:
            logger.warning("[alpaca] get_activities request error: %s", exc)
            return []
        except Exception as exc:
            logger.warning("[alpaca] get_activities unexpected error: %s", exc)
            return []
