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
    {
        "name": "get_technical_indicators",
        "description": "Compute RSI-14, MACD(12,26,9), Bollinger Bands, and moving averages for a stock or crypto symbol using 1 year of daily price data. Returns overbought/oversold interpretation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker e.g. AAPL, SBUX, BTC-USD, ETH-USD"},
            },
            "required": ["symbol"],
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

If asked about something outside your tools, answer from your training knowledge but note it may not be real-time.

When making specific factual claims about financial data (revenue figures, earnings, price moves, ratios), add a bracketed citation like [1], [2] inline after the claim. At the end of your response, add a "---" separator followed by a "Sources:" section listing each citation number with a brief source label, e.g.:
[1] Yahoo Finance / yfinance data
[2] SEC filings via yfinance
[3] Analyst consensus
Keep citations minimal — only for specific numerical claims, not general statements."""


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

            elif name == "get_technical_indicators":
                import asyncio as _asyncio
                import pandas as _pd
                import yfinance as _yf

                raw_sym = inp["symbol"].upper().strip()
                # Normalize: SBUX → SBUX, BTC/USD → BTC-USD, BTC → BTC-USD
                yf_sym = raw_sym.replace("/USD", "-USD").replace("/USDT", "-USDT")
                if "-" not in yf_sym and not any(c.isdigit() for c in yf_sym):
                    # Might be a bare crypto base — try with -USD suffix if it looks like one
                    _CRYPTO_SET = {"BTC","ETH","SOL","AVAX","DOGE","ADA","BNB","XRP","MATIC","LINK"}
                    if yf_sym in _CRYPTO_SET:
                        yf_sym = f"{yf_sym}-USD"

                def _compute_indicators_sync() -> dict:
                    ticker = _yf.Ticker(yf_sym)
                    hist = ticker.history(period="1y")
                    if hist.empty or len(hist) < 30:
                        return {"error": f"Insufficient price history for {raw_sym}"}
                    close = hist["Close"]
                    current = float(close.iloc[-1])

                    # RSI-14
                    delta = close.diff()
                    gain = delta.clip(lower=0).rolling(14).mean()
                    loss = (-delta.clip(upper=0)).rolling(14).mean()
                    rs = gain / loss.replace(0, float("nan"))
                    rsi_s = 100 - 100 / (1 + rs)
                    rsi = round(float(rsi_s.iloc[-1]), 1) if not _pd.isna(rsi_s.iloc[-1]) else None

                    # MACD(12,26,9)
                    ema12 = close.ewm(span=12, adjust=False).mean()
                    ema26 = close.ewm(span=26, adjust=False).mean()
                    macd_line = ema12 - ema26
                    sig_line = macd_line.ewm(span=9, adjust=False).mean()
                    hist_line = macd_line - sig_line
                    macd_bullish = float(hist_line.iloc[-1]) > 0

                    # Bollinger Bands(20)
                    ma20 = close.rolling(20).mean()
                    std20 = close.rolling(20).std()
                    bb_u = float(ma20.iloc[-1] + 2 * std20.iloc[-1])
                    bb_l = float(ma20.iloc[-1] - 2 * std20.iloc[-1])
                    bb_pct = (current - bb_l) / (bb_u - bb_l) if (bb_u - bb_l) > 0 else 0.5

                    # Moving averages
                    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
                    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

                    # 52-week
                    high_52w = float(close.max())
                    low_52w = float(close.min())

                    rsi_label = (
                        "oversold (<30)" if rsi is not None and rsi < 30
                        else "overbought (>70)" if rsi is not None and rsi > 70
                        else "neutral (30–70)"
                    )

                    return {
                        "symbol": raw_sym,
                        "current_price": round(current, 2),
                        "rsi_14": rsi,
                        "rsi_interpretation": rsi_label,
                        "macd": {
                            "macd": round(float(macd_line.iloc[-1]), 4),
                            "signal": round(float(sig_line.iloc[-1]), 4),
                            "histogram": round(float(hist_line.iloc[-1]), 4),
                            "crossover": "bullish" if macd_bullish else "bearish",
                        },
                        "bollinger_bands": {
                            "upper": round(bb_u, 2),
                            "lower": round(bb_l, 2),
                            "pct_b": round(bb_pct, 3),
                            "position": (
                                "above_upper_band" if current > bb_u
                                else "below_lower_band" if current < bb_l
                                else "within_bands"
                            ),
                        },
                        "moving_averages": {
                            "ma_50": round(ma50, 2) if ma50 else None,
                            "ma_200": round(ma200, 2) if ma200 else None,
                            "above_ma50": bool(current > ma50) if ma50 else None,
                            "above_ma200": bool(current > ma200) if ma200 else None,
                            "golden_cross": bool(ma50 > ma200) if (ma50 and ma200) else None,
                        },
                        "range_52w": {
                            "high": round(high_52w, 2),
                            "low": round(low_52w, 2),
                            "pct_from_high": round((current - high_52w) / high_52w * 100, 1),
                        },
                    }

                try:
                    result = await _asyncio.wait_for(
                        _asyncio.to_thread(_compute_indicators_sync),
                        timeout=20.0,
                    )
                    return result
                except _asyncio.TimeoutError:
                    return {"error": f"Indicator computation timed out for {raw_sym}. Answer from general knowledge."}

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
        yield _sse({"type": "error", "message": "AI features are not available right now. Check back soon."})
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
