"""
BMGAppClient — authenticated read-only HTTP client for the agent fleet.

Agents use this to cross-check dashboard data against DB state,
pull live portfolio/risk snapshots, and verify their own outputs.
All calls are GET-only. Write attempts are blocked server-side.

Usage:
    client = BMGAppClient()
    bots = await client.bots_list()
    snapshot = await client.portfolio_snapshot()
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date as _date
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Endpoints agents are expected to use
ENDPOINT_CATALOG = [
    "/api/health",
    "/api/agents/status",
    "/api/budget/status",
    "/api/portfolio/snapshot",
    "/api/admin/bots/list",
    "/api/strategy-lab/portfolio",
    "/api/strategy-lab/candidates",
    "/api/risk/status",
    "/api/proposals/history",
    "/api/proposals/pending",
    "/api/sentinel/status",
]


class BMGAppClient:
    BASE_URL = "https://disciplined-intuition-production-5207.up.railway.app"

    def __init__(self, agent_id: str = "agent_fleet"):
        self.token = os.getenv("AGENT_APP_AUTH_TOKEN", "")
        self.agent_id = agent_id
        if not self.token:
            logger.warning("[app_client] AGENT_APP_AUTH_TOKEN not set — API access unavailable")
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "BMGAgentFleet/1.0",
        }

    @property
    def available(self) -> bool:
        return bool(self.token)

    async def get(self, path: str, params: dict = None) -> dict:
        if not self.available:
            return {}
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                resp = await c.get(
                    self.BASE_URL + path,
                    headers=self._headers,
                    params=params,
                )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.debug(
                "[app_client] %s GET %s → %d (%dms)",
                self.agent_id,
                path,
                resp.status_code,
                elapsed_ms,
            )
            self._log_access(path, resp.status_code, elapsed_ms)
            if resp.is_success:
                return resp.json()
            else:
                logger.warning(
                    "[app_client] %s GET %s returned non-2xx status %d",
                    self.agent_id,
                    path,
                    resp.status_code,
                )
                return {}
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning("[app_client] %s GET %s failed: %s", self.agent_id, path, exc)
            return {}

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def portfolio_snapshot(self) -> dict:
        return await self.get("/api/portfolio/snapshot")

    async def bots_list(self) -> list:
        return (await self.get("/api/admin/bots/list")).get("bots", [])

    async def candidates(self) -> list:
        return (await self.get("/api/strategy-lab/candidates")).get("candidates", [])

    async def risk_status(self) -> dict:
        return await self.get("/api/risk/status")

    async def budget_status(self) -> dict:
        return await self.get("/api/budget/status")

    async def agent_status(self) -> dict:
        return await self.get("/api/agents/status")

    async def sentinel_status(self) -> dict:
        return await self.get("/api/sentinel/status")

    async def proposals_history(self, n: int = 20) -> list:
        return (await self.get("/api/proposals/history", params={"limit": n})).get("proposals", [])

    async def proposals_pending(self) -> list:
        return (await self.get("/api/proposals/pending")).get("proposals", [])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_access(self, endpoint: str, status_code: int, response_ms: int) -> None:
        """Write to agent_app_access_log table. Best-effort — never raises."""
        try:
            from app.dependencies import get_db
            db = next(get_db())
            try:
                from sqlalchemy import text
                from datetime import datetime, timezone
                db.execute(text("""
                    INSERT INTO agent_app_access_log
                      (agent_id, endpoint, status_code, response_ms, called_at)
                    VALUES (:agent_id, :endpoint, :status_code, :response_ms, :ts)
                """), {
                    "agent_id": self.agent_id,
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "response_ms": response_ms,
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.debug("[app_client] access log write failed (non-fatal): %s", exc)


def get_client(agent_id: str = "agent_fleet") -> BMGAppClient:
    """Returns a configured BMGAppClient for the given agent."""
    return BMGAppClient(agent_id=agent_id)
