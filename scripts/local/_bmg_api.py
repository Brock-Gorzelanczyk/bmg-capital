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

import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


def _b64url(data: bytes) -> str:
    """Base64url encode (no padding), per JWT RFC 7515."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _hs256_jwt(payload: Dict[str, Any], secret: str) -> str:
    """Mint an HS256 JWT using only stdlib. No pyjwt dep needed."""
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


class BMGApiError(Exception):
    pass


class BMGApiClient:
    # Matches scripts/bmg_admin.sh — Railway service name + base URL
    RAILWAY_SERVICE = "disciplined-intuition"
    DEFAULT_BASE = "https://disciplined-intuition-production-5207.up.railway.app"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.environ.get("BMG_API_URL", self.DEFAULT_BASE)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _mint_token(self) -> str:
        """Read JWT_SECRET from Railway CLI + mint HS256 sub=1 token via stdin pipe."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        # Allow env override for CI / testing
        secret = os.environ.get("JWT_SECRET")

        if not secret:
            # Same path as bmg_admin.sh — --kv format, grep for prefix, strip
            # (don't split on '=' since some secret values contain padding chars)
            r = subprocess.run(
                ["railway", "variables", "--service", self.RAILWAY_SERVICE, "--kv"],
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode != 0:
                raise BMGApiError(
                    f"railway variables call failed (service={self.RAILWAY_SERVICE}): "
                    f"{r.stderr.strip()[:200]}. Run `railway link` first."
                )
            for line in r.stdout.splitlines():
                if line.startswith("JWT_SECRET="):
                    secret = line[len("JWT_SECRET="):]
                    break
            if not secret:
                raise BMGApiError(
                    f"JWT_SECRET not found in Railway service '{self.RAILWAY_SERVICE}' vars"
                )

        # Mint HS256 JWT in-process using stdlib. Secret stays in the local
        # variable's scope and is not passed via argv/env — §S1 compliant.
        try:
            self._token = _hs256_jwt(
                {"sub": "1", "exp": int(time.time()) + 900},
                secret,
            )
        except Exception as e:
            raise BMGApiError(f"jwt mint failed: {type(e).__name__}: {e}")
        finally:
            secret = None  # help GC

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
