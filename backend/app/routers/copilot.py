from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, List

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from app.config import settings
from app.dependencies import get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/copilot", tags=["copilot"])

_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_quote",
        "description": "Get the current price, change %, volume and key stats for a stock or crypto symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "Ticker e.g. AAPL, BTC-USD"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "run_screener",
        "description": "Run one of the preset screener strategies and return matching stocks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "description": "e.g. momentum_surge, golden_cross, rsi_oversold, stage_2_breakout, can_slim"},
                "limit": {"type": "integer"},
            },
            "required": ["strategy"],
        },
    },
    {
        "name": "get_news",
        "description": "Get latest market news, optionally filtered by symbol.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_strategy_summary",
        "description": "Get the user's Strategy Lab: total equity, win rate, open positions count, P&L.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_candidates",
        "description": "List stocks currently watched by the Strategy Lab as entry candidates.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_portfolio",
        "description": "Get the user's paper trading portfolio: positions, cash, total equity.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_crypto_market",
        "description": "Get top cryptocurrencies by market cap with price and 24h change.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "check_token_security",
        "description": "Check if a crypto token contract is safe: rug pull risk, honeypot detection, tax rates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contract_address": {"type": "string"},
                "chain": {"type": "string", "description": "ethereum, bsc, polygon, arbitrum, base"},
            },
            "required": ["contract_address", "chain"],
        },
    },
    {
        "name": "get_defi_yields",
        "description": "Get top DeFi yield opportunities across staking and lending protocols.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "get_governance_proposals",
        "description": "Get active DAO governance proposals from Uniswap, Aave, Compound, MakerDAO, etc.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "get_themes",
        "description": "Get thematic investment baskets (AI, Clean Energy, Semiconductors) with performance.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_earnings",
        "description": "Get upcoming earnings announcements with dates and consensus estimates.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "get_insider_trades",
        "description": "Get recent insider buying/selling from SEC EDGAR Form 4 filings.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "explain_term",
        "description": "Explain a financial or crypto term in plain English with technical detail.",
        "input_schema": {
            "type": "object",
            "properties": {"term": {"type": "string"}},
            "required": ["term"],
        },
    },
]

SYSTEM_PROMPT = """You are BMG Intelligence — the AI co-pilot built into BMG Capital, a professional trading and investing platform. You have access to live market tools and can look up real-time data.

Persona:
- Expert, concise, direct — like a Bloomberg terminal that can talk
- Never give specific "buy X" investment advice, but freely share data, analysis, and setups
- Use markdown: **bold** key numbers, bullet lists for multiple items
- When you use a tool, briefly narrate what you found before presenting results
- Keep responses under 300 words unless the user asks for more
- Answer casual questions conversationally without tools

If asked about something outside your tools, answer from your training knowledge but note it may not be real-time."""


# ── Tool executor (calls internal API endpoints) ──────────────────────────────

async def _api(client: httpx.AsyncClient, method: str, path: str, token: str, **kwargs) -> Any:
    base = f"http://localhost:{settings.port}"
    headers = {"Authorization": f"Bearer {token}"}
    if method == "GET":
        r = await client.get(f"{base}{path}", headers=headers, timeout=15.0, **kwargs)
    else:
        r = await client.post(f"{base}{path}", headers=headers, timeout=15.0, **kwargs)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    return r.json()


async def execute_tool(name: str, inp: dict, token: str) -> Any:
    async with httpx.AsyncClient() as c:
        try:
            if name == "get_quote":
                sym = inp["symbol"].upper()
                return await _api(c, "GET", f"/api/bars/quote/{sym}", token)

            elif name == "run_screener":
                params = {"strategy": inp["strategy"], "limit": inp.get("limit", 10)}
                return await _api(c, "GET", "/api/screener/run", token, params=params)

            elif name == "get_news":
                params: dict = {"limit": inp.get("limit", 5)}
                if "symbol" in inp:
                    params["symbol"] = inp["symbol"]
                data = await _api(c, "GET", "/api/news", token, params=params)
                if isinstance(data, dict) and "articles" in data:
                    data["articles"] = data["articles"][:inp.get("limit", 5)]
                return data

            elif name == "get_strategy_summary":
                return await _api(c, "GET", "/api/strategy/summary", token)

            elif name == "get_candidates":
                data = await _api(c, "GET", "/api/strategy/candidates", token)
                if isinstance(data, dict) and "candidates" in data:
                    data["candidates"] = data["candidates"][:15]
                return data

            elif name == "get_portfolio":
                return await _api(c, "GET", "/api/paper/account", token)

            elif name == "get_crypto_market":
                limit = inp.get("limit", 10)
                data = await _api(c, "GET", "/api/crypto/market", token, params={"limit": limit + 10})
                if isinstance(data, dict) and "coins" in data:
                    data["coins"] = [
                        {k: v for k, v in coin.items() if k != "sparkline_in_7d"}
                        for coin in data["coins"][:limit]
                    ]
                return data

            elif name == "check_token_security":
                chain = inp["chain"].lower()
                addr = inp["contract_address"]
                return await _api(c, "GET", f"/api/security/token/{chain}/{addr}", token)

            elif name == "get_defi_yields":
                limit = inp.get("limit", 10)
                return await _api(c, "GET", "/api/defi/yields", token, params={"limit": limit})

            elif name == "get_governance_proposals":
                limit = inp.get("limit", 10)
                data = await _api(c, "GET", "/api/governance/proposals", token, params={"limit": limit, "state": "active"})
                if isinstance(data, dict) and "proposals" in data:
                    data["proposals"] = data["proposals"][:limit]
                return data

            elif name == "get_themes":
                return await _api(c, "GET", "/api/discovery/themes", token)

            elif name == "get_earnings":
                limit = inp.get("limit", 10)
                data = await _api(c, "GET", "/api/earnings", token, params={"limit": limit})
                return data

            elif name == "get_insider_trades":
                limit = inp.get("limit", 10)
                data = await _api(c, "GET", "/api/discovery/insiders", token, params={"limit": limit})
                return data

            elif name == "explain_term":
                term = inp["term"]
                return await _api(c, "POST", "/api/explain", token, json={"term": term, "mode": "detailed"})

            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.warning(f"Tool {name} failed: {e}")
            return {"error": str(e)}


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _stream_copilot(messages: list, page: str, token: str) -> AsyncGenerator[str, None]:
    if not settings.anthropic_api_key:
        yield _sse({"type": "text_delta", "delta": "AI Co-Pilot requires ANTHROPIC_API_KEY in your environment."})
        yield _sse({"type": "done"})
        return

    hdrs = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    sys = SYSTEM_PROMPT + (f"\n\nUser is on the **{page}** page." if page else "")

    # Phase 1 — non-streaming: detect tool calls
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=hdrs,
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1024, "system": sys, "tools": TOOLS, "messages": messages},
            )
            r.raise_for_status()
            p1 = r.json()
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})
        return

    tool_uses = [b for b in p1.get("content", []) if b.get("type") == "tool_use"]

    if tool_uses:
        tool_results = []
        for tu in tool_uses:
            yield _sse({"type": "tool_start", "tool": tu["name"], "input": tu["input"]})
            result = await execute_tool(tu["name"], tu["input"], token)
            yield _sse({"type": "tool_result", "tool": tu["name"], "result": result})
            tool_results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": json.dumps(result)})

        final_msgs = messages + [
            {"role": "assistant", "content": p1["content"]},
            {"role": "user", "content": tool_results},
        ]

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST", "https://api.anthropic.com/v1/messages",
                    headers=hdrs,
                    json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1024, "system": sys, "messages": final_msgs, "stream": True},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            ev = json.loads(raw)
                        except Exception:
                            continue
                        if ev.get("type") == "content_block_delta":
                            delta = ev.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield _sse({"type": "text_delta", "delta": delta.get("text", "")})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
    else:
        # No tools — chunk-stream the text response
        text = "".join(b.get("text", "") for b in p1.get("content", []) if b.get("type") == "text")
        for i in range(0, len(text), 4):
            yield _sse({"type": "text_delta", "delta": text[i:i + 4]})
            await asyncio.sleep(0.008)

    yield _sse({"type": "done"})


# ── Request model & endpoint ──────────────────────────────────────────────────

class CopilotMessage(BaseModel):
    role: str
    content: str


class CopilotRequest(BaseModel):
    messages: List[CopilotMessage]
    page: str = ""


@router.post("/stream")
async def copilot_stream(
    body: CopilotRequest,
    current_user: User = Depends(get_current_user),
    token: str = Depends(_oauth2),
):
    messages = [{"role": m.role, "content": m.content} for m in body.messages[-20:]]
    return StreamingResponse(
        _stream_copilot(messages, body.page, token or ""),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Reading-level rewrite endpoint ───────────────────────────────────────────

_REWRITE_SYSTEM = """You are a financial content editor. Rewrite the given content at the requested reading level:
- pro: keep all technical language, add detail where helpful
- investor: clear, confident, focused on what matters for investment decisions
- beginner: plain language, define jargon inline, no assumptions
- eli5: extremely simple, one-syllable words where possible, use analogies

Return ONLY the rewritten content, no preamble."""


class RewriteRequest(BaseModel):
    content: str
    level: str  # "pro" | "investor" | "beginner" | "eli5"
    context: str = ""


class RewriteResponse(BaseModel):
    rewritten: str


@router.post("/rewrite-level", response_model=RewriteResponse)
async def rewrite_level(
    body: RewriteRequest,
    current_user: User = Depends(get_current_user),
):
    if not settings.anthropic_api_key:
        return RewriteResponse(rewritten=body.content)

    # Truncate to 2000 chars
    content = body.content[:2000]

    user_msg = f"Level: {body.level}\n\nContent:\n{content}"
    if body.context:
        user_msg = f"Context: {body.context}\n\n{user_msg}"

    hdrs = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=hdrs,
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "system": _REWRITE_SYSTEM,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            r.raise_for_status()
            data = r.json()
            rewritten = "".join(
                b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
            )
            return RewriteResponse(rewritten=rewritten or body.content)
    except Exception as e:
        logger.warning(f"rewrite-level failed: {e}")
        return RewriteResponse(rewritten=body.content)
