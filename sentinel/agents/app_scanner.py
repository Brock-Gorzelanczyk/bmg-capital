"""
App Scanner Agent — Playwright headless browser checks key pages every 5 minutes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sentinel.db.session import SessionLocal
from sentinel.orchestrator import insert_event, route_event
from sentinel.settings import settings
from sentinel.agents.error_classifier import classify_error

logger = logging.getLogger(__name__)

PAGES_TO_CHECK = [
    {"path": "/health",          "is_api": True,  "name": "health"},
    {"path": "/login",           "is_api": False, "name": "login"},
    {"path": "/strategy",        "is_api": False, "name": "strategy-lab"},
    {"path": "/strategy/forge",  "is_api": False, "name": "forge"},
    {"path": "/strategy/scout",  "is_api": False, "name": "scout"},
]


def _fp(page_name: str, error_summary: str) -> str:
    raw = f"scanner:{page_name}:{error_summary[:120]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


# _classify_error replaced by classify_error() from error_classifier.py (R1 — SHIP 3)


class AppScannerAgent:
    def run(self) -> None:
        if not settings.sentinel_enabled:
            return
        if not settings.app_url:
            logger.debug("[app-scanner] No APP_URL configured, skipping")
            return
        try:
            self._scan_pages()
        except Exception as e:
            logger.error("[app-scanner] Error: %s", e, exc_info=True)

    def _scan_pages(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[app-scanner] Playwright not available, skipping")
            return

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for page_cfg in PAGES_TO_CHECK:
                    self._check_page(browser, page_cfg)
            finally:
                browser.close()

    def _check_page(self, browser: Any, page_cfg: dict) -> None:
        from playwright.sync_api import Page
        url = settings.app_url.rstrip("/") + page_cfg["path"]
        page_name = page_cfg["name"]

        console_errors: list[dict] = []
        network_failures: list[dict] = []

        try:
            ctx = browser.new_context()
            page = ctx.new_page()

            page.on("console", lambda msg: (
                console_errors.append({
                    "text": msg.text,
                    "type": msg.type,
                    "location": str(msg.location),
                }) if msg.type == "error" else None
            ))

            page.on("requestfailed", lambda req: network_failures.append({
                "url": req.url,
                "failure": req.failure,
            }))

            resp = page.goto(url, timeout=20_000, wait_until="networkidle")
            status = resp.status if resp else 0

            if status >= 400:
                self._emit_issue(
                    page_name=page_name,
                    category="other",
                    detail=f"HTTP {status} on {url}",
                    severity="critical" if status >= 500 else "warning",
                    payload={"file": "", "url": url, "status": status},
                )

            for err in console_errors:
                classification = classify_error(err["text"], err.get("location", ""))
                category = classification.get("category", "other")
                suggested_file = classification.get("suggested_file", "")
                side = classification.get("frontend_or_backend", "unknown")

                self._emit_issue(
                    page_name=page_name,
                    category=category,
                    detail=err["text"][:200],
                    severity="warning",
                    payload={
                        "file": suggested_file,
                        "error_text": err["text"][:500],
                        "location": err.get("location", ""),
                        "frontend_or_backend": side,
                        "url": url,
                    },
                )

            ctx.close()
        except Exception as e:
            logger.warning("[app-scanner] Failed to check %s: %s", url, e)

    def _emit_issue(
        self,
        page_name: str,
        category: str,
        detail: str,
        severity: str,
        payload: dict,
    ) -> None:
        fp = _fp(page_name, detail)
        db = SessionLocal()
        try:
            event_id = insert_event(
                db=db,
                agent_id="app-scanner",
                severity=severity,
                category=category,
                fingerprint=fp,
                payload={**payload, "page": page_name, "detail": detail},
            )
        finally:
            db.close()

        if event_id:
            route_event(event_id, category, payload)
