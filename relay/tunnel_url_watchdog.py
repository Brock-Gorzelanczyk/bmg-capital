"""Cloudflared tunnel URL watchdog.

Detects when the cloudflared quick-tunnel URL rotates (process restart)
and auto-updates Railway env var RELAY_URL on the bmg-capital backend
service. Closes the loop in the no-persistent-tunnel architecture so
autonomous overnight runs survive a cloudflared restart without manual
env updates.

Runs as a launchd job that polls /tmp/cloudflared.err every 60s.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

LOG_PATH = os.environ.get("CLOUDFLARED_LOG", "/tmp/cloudflared.err")
STATE_PATH = "/tmp/bmg_tunnel_watchdog.state"
POLL_INTERVAL_SECONDS = 60

# Railway project + service IDs for the bmg-capital backend (disciplined-intuition)
RAILWAY_PROJECT_ID = "7e082751-828a-44d2-b2cb-edc87c2bf214"
RAILWAY_ENVIRONMENT_ID = "20574ea1-68f9-442a-b8b1-95db9ea91c54"
RAILWAY_SERVICE_ID = "423eb898-6beb-49df-9417-4c8c43a14309"
RAILWAY_API = "https://backboard.railway.com/graphql/v2"

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def latest_url_from_log(path: str) -> str | None:
    """Return the MOST RECENT trycloudflare URL in the log, or None if absent.

    cloudflared logs the URL only at startup, so the last match is the
    URL of the currently-running tunnel process.
    """
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        return None
    matches = URL_RE.findall(content)
    return matches[-1] if matches else None


def saved_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(d: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(d, f)


def update_railway_relay_url(new_url: str, railway_token: str) -> bool:
    """Upsert RELAY_URL on the backend service via Railway GraphQL.

    Returns True on success.
    """
    query = """
    mutation Upsert($input: VariableUpsertInput!) {
      variableUpsert(input: $input)
    }
    """
    variables = {
        "input": {
            "projectId": RAILWAY_PROJECT_ID,
            "environmentId": RAILWAY_ENVIRONMENT_ID,
            "serviceId": RAILWAY_SERVICE_ID,
            "name": "RELAY_URL",
            "value": new_url,
        }
    }
    req = urllib.request.Request(
        RAILWAY_API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"Bearer {railway_token}",
            "Content-Type": "application/json",
            # Cloudflare blocks default urllib UA with error 1010.
            "User-Agent": "bmg-tunnel-watchdog/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        return body.get("data", {}).get("variableUpsert") is True
    except Exception as exc:
        sys.stderr.write(f"[watchdog] Railway upsert failed: {exc}\n")
        return False


def main() -> int:
    railway_token = os.environ.get("RAILWAY_TOKEN", "").strip()
    if not railway_token:
        sys.stderr.write("[watchdog] RAILWAY_TOKEN env var required\n")
        return 1

    state = saved_state()
    last_url = state.get("last_url")
    sys.stderr.write(f"[watchdog] starting; last_known_url={last_url}\n")

    while True:
        current = latest_url_from_log(LOG_PATH)
        if current and current != last_url:
            sys.stderr.write(f"[watchdog] URL changed: {last_url} -> {current}\n")
            if update_railway_relay_url(current, railway_token):
                last_url = current
                save_state({"last_url": current, "updated_at": time.time()})
                sys.stderr.write(f"[watchdog] Railway RELAY_URL updated to {current}\n")
            else:
                sys.stderr.write("[watchdog] update failed; will retry next cycle\n")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
