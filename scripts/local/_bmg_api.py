"""BMG API client for local scripts.

Mints a short-lived JWT from Railway's JWT_SECRET (pulled from Railway CLI)
and calls prod endpoints. Same auth path as scripts/bmg_admin.sh, in Python
so local jobs can parse JSON responses easily.

**Security discipline (per CLAUDE.md §S1):**
JWT_SECRET is read via `railway variables --json` and piped into python
subprocess on stdin — never argv, never env var, never printed. If you
need to debug, use `_debug=True` on init but NEVER paste output.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class BMGApiError(Exception):
    pass


class BMGApiClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.environ.get(
            "BMG_API_URL", "https://bmg-capital.up.railway.app"
        )
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _mint_token(self) -> str:
        """Read JWT_SECRET from Railway CLI + mint HS256 sub=1 token via stdin pipe."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        # Get secret via Railway CLI — same path as bmg_admin.sh
        r = subprocess.run(
            ["railway", "variables", "--json", "--service", "bmg-capital"],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            raise BMGApiError(
                "railway variables call failed — is Railway CLI installed + "
                "linked to bmg-capital project? Run `railway link` first."
            )
        try:
            vars_ = json.loads(r.stdout)
            secret = vars_.get("JWT_SECRET")
            if not secret:
                raise BMGApiError("JWT_SECRET not found in Railway service vars")
        except json.JSONDecodeError as e:
            raise BMGApiError(f"parsing railway variables output: {e}")

        # Mint via stdin — never argv, per §S1
        py = subprocess.run(
            ["python3", "-c",
             "import sys,jwt,time;s=sys.stdin.read().strip();"
             "print(jwt.encode({'sub':'1','exp':int(time.time())+900},s,algorithm='HS256'))"],
            input=secret,
            capture_output=True,
            text=True,
            check=False,
        )
        if py.returncode != 0:
            raise BMGApiError(f"jwt encode failed: {py.stderr}")

        self._token = py.stdout.strip()
        self._token_expires_at = time.time() + 900
        return self._token

    def get(self, path: str) -> Dict[str, Any]:
        return self._req("GET", path)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._req("POST", path, body)

    def _req(self, method: str, path: str, body: Optional[Dict] = None) -> Dict[str, Any]:
        token = self._mint_token()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise BMGApiError(f"{method} {url} → {e.code}: {e.read().decode('utf-8')[:500]}")
        except urllib.error.URLError as e:
            raise BMGApiError(f"{method} {url} network error: {e.reason}")


_client: Optional[BMGApiClient] = None


def get_client() -> BMGApiClient:
    global _client
    if _client is None:
        _client = BMGApiClient()
    return _client
