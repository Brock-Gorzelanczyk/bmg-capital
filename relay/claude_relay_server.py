"""BMG Capital — Claude CLI relay server (SHIP 3).

Runs on Brock's Mac. Exposes /infer and /health.
Auth: Authorization: Bearer <RELAY_AUTH_TOKEN>
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="BMG Claude Relay", version="1.0.0")

LOG_PATH = Path(__file__).parent / "logs" / "requests.jsonl"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

RELAY_AUTH_TOKEN = os.getenv("RELAY_AUTH_TOKEN", "")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class InferRequest(BaseModel):
    model: str
    prompt: str
    system_prompt: str = ""
    max_tokens: int = 1024
    agent_name: str = "unknown"


class InferResponse(BaseModel):
    response_text: str
    model: str
    duration_ms: int
    source: str


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_auth(request: Request) -> None:
    if not RELAY_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="RELAY_AUTH_TOKEN not configured on Mac")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != RELAY_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


# ---------------------------------------------------------------------------
# ANSI strip
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/infer", response_model=InferResponse)
async def infer(body: InferRequest, request: Request) -> InferResponse:
    _check_auth(request)

    full_prompt = (body.system_prompt + "\n\n" + body.prompt) if body.system_prompt else body.prompt

    t0 = time.monotonic()
    status = "ok"
    response_text = ""

    try:
        proc = subprocess.run(
            ["claude", "--model", body.model, "--print", "--output-format=text"],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            status = "error"
            raise HTTPException(
                status_code=502,
                detail={"detail": "claude_cli_failed", "stderr": proc.stderr[:500]},
            )
        response_text = strip_ansi(proc.stdout).strip()
    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        status = "error"
        raise HTTPException(status_code=502, detail={"detail": "claude_cli_timeout"})
    except Exception as exc:
        status = "error"
        raise HTTPException(status_code=502, detail={"detail": str(exc)[:300]})
    finally:
        duration_ms = int((time.monotonic() - t0) * 1000)
        _log_request(
            agent=body.agent_name,
            model=body.model,
            prompt_chars=len(full_prompt),
            response_chars=len(response_text),
            duration_ms=duration_ms,
            status=status,
        )

    return InferResponse(
        response_text=response_text,
        model=body.model,
        duration_ms=duration_ms,
        source="claude_cli",
    )


@app.get("/health")
async def health() -> dict:
    try:
        which = subprocess.run(["which", "claude"], capture_output=True, text=True, timeout=5)
        if which.returncode != 0:
            return {"ok": False, "reason": "claude not found in PATH"}
        version_proc = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=5
        )
        if version_proc.returncode != 0:
            return {"ok": False, "reason": "claude --version failed"}
        version = strip_ansi(version_proc.stdout).strip()
        return {"ok": True, "claude_cli": "found", "version": version}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_request(*, agent: str, model: str, prompt_chars: int, response_chars: int,
                 duration_ms: int, status: str) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "model": model,
        "prompt_chars": prompt_chars,
        "response_chars": response_chars,
        "duration_ms": duration_ms,
        "status": status,
    }
    try:
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.warning("Failed to write relay log: %s", exc)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("claude_relay_server:app", host="127.0.0.1", port=8787, reload=False)
