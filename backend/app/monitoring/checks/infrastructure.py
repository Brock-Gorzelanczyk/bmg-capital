"""Infrastructure health checks (Category A)."""
from __future__ import annotations
import ssl
import socket
import time
import logging
import httpx
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def check_backend_api_health() -> dict:
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://localhost:8000/health")
        latency_ms = int((time.monotonic() - t0) * 1000)
        passed = resp.status_code == 200
        return {
            "passed": passed,
            "detail": f"Status {resp.status_code}, latency {latency_ms}ms" if passed
                      else f"Non-200 response: {resp.status_code}",
        }
    except Exception as exc:
        return {"passed": False, "detail": f"Request failed: {exc}"}


async def check_db_ping(db) -> dict:
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        return {"passed": True, "detail": "DB ping OK"}
    except Exception as exc:
        return {"passed": False, "detail": f"DB ping failed: {exc}"}


async def check_ssl_cert_expiry() -> dict:
    domains = ["bmg-capital.up.railway.app"]  # update as needed
    results = []
    all_ok = True
    for domain in domains:
        try:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
                s.settimeout(5)
                s.connect((domain, 443))
                cert = s.getpeercert()
            expires_str = cert.get("notAfter", "")
            expires = datetime.strptime(expires_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days_left = (expires - datetime.now(timezone.utc)).days
            if days_left < 30:
                all_ok = False
                results.append(f"{domain}: {days_left} days left (WARN)")
            else:
                results.append(f"{domain}: {days_left} days left (OK)")
        except Exception as exc:
            all_ok = False
            results.append(f"{domain}: error — {exc}")
    return {"passed": all_ok, "detail": "; ".join(results)}
