"""
AI Analyst — generates Claude-powered theses for every bot watchlist symbol.

POST /api/analyst/analyze           — analyze a single symbol for a bot
GET  /api/analyst/watchlist/:bot_id — latest analyses for all symbols on a bot's watchlist
GET  /api/analyst/symbol/:symbol    — cross-bot view of a symbol
GET  /api/analyst/thesis/:symbol    — lightweight thesis card (6h module-level cache)
POST /api/analyst/refresh/:bot_id   — re-analyze all symbols (background)
GET  /api/analyst/runs              — AnalystDailyRun history
GET  /api/analyst/summary           — today's aggregate summary across all bots
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.config import settings
from app.dependencies import get_db, get_current_user
from app.db.models.bots import (
    BotProfile, BotAllocation, BotWatchlist, BotSignal,
    WatchlistAnalysis, AnalystDailyRun, CatalystEvent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analyst", tags=["analyst"])

# ── Module-level thesis cache (6-hour TTL) ─────────────────────────────────────
# { symbol.upper(): {"data": {...}, "cached_at": datetime} }
_THESIS_CACHE: dict[str, dict] = {}
_THESIS_TTL_HOURS = 6

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are BMG's AI Equity Analyst. You produce honest, actionable research notes grounded in the data provided. Never invent facts. Never speculate beyond the inputs. If data is missing, say so.

Format your response as valid JSON only — no markdown fences, no commentary outside the JSON:
{
  "thesis": "4-6 sentence plain-English thesis explaining why this name is interesting (or not). Reference the actual data provided.",
  "conviction": 1,
  "reasons_to_own": ["reason tied to a data point", "reason 2", "reason 3"],
  "risks": ["risk tied to a data point", "risk 2", "risk 3"],
  "suggested_hold": "specific timeframe like '5-15 days' or '3-6 months'",
  "concerns_flag": false
}

conviction is an integer 1-5 where: 1=avoid, 2=weak, 3=neutral, 4=bullish, 5=high conviction.
concerns_flag is true if: earnings within 5 days, halt risk, fraud signal, sector crash, or major lawsuit."""

# ── Technical indicator helper ─────────────────────────────────────────────────

def _compute_technicals(symbol: str, current_price: Optional[float] = None) -> dict:
    """Compute RSI, MACD, MA50/200, 52w distance from yfinance bars."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y")
        if hist.empty or len(hist) < 30:
            return {}

        close = hist["Close"]
        current = float(close.iloc[-1])

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi_series = 100 - 100 / (1 + rs)
        rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_val = float(macd_line.iloc[-1])
        sig_val = float(signal_line.iloc[-1])
        macd_signal = "bullish_crossover" if macd_val > sig_val else "bearish_crossover"

        # MA 50 / 200
        ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
        ma_aligned = bool(ma50 > ma200) if (ma50 and ma200) else None

        # 52-week high distance
        high_52w = float(close.rolling(252).max().iloc[-1]) if len(close) >= 50 else float(close.max())
        dist_52w = round((high_52w - current) / high_52w * 100, 1) if high_52w > 0 else None

        # Volume vs 20d avg
        if "Volume" in hist.columns and len(hist) >= 20:
            vol_avg_20d = float(hist["Volume"].rolling(20).mean().iloc[-1])
            vol_today = float(hist["Volume"].iloc[-1])
            vol_ratio = round(vol_today / vol_avg_20d, 2) if vol_avg_20d > 0 else None
        else:
            vol_ratio = None

        return {
            "rsi_14": round(rsi, 1) if rsi is not None else None,
            "macd_signal": macd_signal,
            "ma_50_above_ma_200": ma_aligned,
            "distance_from_52w_high_pct": dist_52w,
            "current_price": round(current_price or current, 2),
            "volume_vs_20d_avg": vol_ratio,
        }
    except Exception as e:
        logger.warning(f"Technicals failed for {symbol}: {e}")
        return {}


def _get_fundamentals(symbol: str) -> dict:
    """Fetch fundamentals from FMP if API key is set, else return {}."""
    api_key = getattr(settings, "fmp_api_key", None) or os.getenv("FMP_API_KEY", "")
    if not api_key:
        return {}
    try:
        import requests
        url = f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{symbol}?apikey={api_key}&limit=1"
        r = requests.get(url, timeout=5)
        data = r.json()
        if not data or not isinstance(data, list):
            return {}
        m = data[0]
        return {
            "pe_ttm": round(float(m.get("peRatioTTM", 0) or 0), 1) or None,
            "roic": round(float(m.get("roicTTM", 0) or 0), 3) or None,
            "debt_to_equity": round(float(m.get("debtToEquityTTM", 0) or 0), 2) or None,
            "revenue_growth_yoy": None,  # needs different endpoint
        }
    except Exception as e:
        logger.warning(f"FMP fundamentals failed for {symbol}: {e}")
        return {}


def _get_strategy_votes(symbol: str, profile_id: int, db: Session) -> list:
    """Pull recent BotSignal rows for this symbol/profile."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = db.execute(
        select(BotSignal)
        .join(BotAllocation, BotSignal.allocation_id == BotAllocation.id)
        .where(
            BotAllocation.profile_id == profile_id,
            BotSignal.symbol == symbol,
            BotSignal.ts >= cutoff,
        )
        .order_by(BotSignal.ts.desc())
        .limit(5)
    ).scalars().all()

    return [
        {
            "strategy": r.strategy or "unknown",
            "score": round(r.confidence, 2),
            "reason": r.reason or "",
            "side": r.side,
        }
        for r in rows
    ]


def _get_catalysts(symbol: str, db: Session) -> list:
    """Get upcoming catalyst events for this symbol + macro events."""
    now = datetime.now(timezone.utc)
    future_cutoff = now + timedelta(days=60)
    rows = db.execute(
        select(CatalystEvent)
        .where(
            CatalystEvent.event_ts >= now,
            CatalystEvent.event_ts <= future_cutoff,
        )
        .where(
            (CatalystEvent.symbol == symbol) |
            (CatalystEvent.symbol.is_(None))
        )
        .order_by(CatalystEvent.event_ts)
        .limit(5)
    ).scalars().all()

    result = []
    for r in rows:
        days_out = max(0, (r.event_ts.replace(tzinfo=timezone.utc) - now).days)
        result.append({
            "event": r.event_type,
            "date": r.event_ts.strftime("%Y-%m-%d"),
            "days_out": days_out,
            "symbol": r.symbol,
        })
    return result


def _has_earnings_soon(catalysts: list, days: int = 5) -> bool:
    for c in catalysts:
        if c.get("event", "").lower() in ("earnings", "earnings_report") and c.get("days_out", 999) <= days:
            return True
    return False


def _call_claude(context: dict, model: str = "claude-haiku-4-5-20251001", cache_key_extra: str = "") -> tuple[str, float]:
    """Call Claude via relay and return (response_text, estimated_cost_usd).
    SHIP 3: routes through call_llm / call_llm_cached.
    """
    from app.services.llm_client import call_llm, call_llm_cached
    user_content = json.dumps(context, indent=2)
    symbol = context.get("symbol", "unknown")
    profile_id = context.get("profile_id", "unknown")
    ck = cache_key_extra or f"{symbol}_{profile_id}"
    if model == "claude-sonnet-4-6":
        # Forced Sonnet — no cache per spec
        text = call_llm(model=model, prompt=user_content, system_prompt=_SYSTEM_PROMPT,
                        max_tokens=1024, agent_name="analyst_forced")
    else:
        text = call_llm_cached(model=model, prompt=user_content, system_prompt=_SYSTEM_PROMPT,
                               max_tokens=1024, ttl_seconds=21600,
                               cache_key_extra=ck, agent_name="analyst")
    return text, 0.0


def _parse_claude_response(text: str) -> dict:
    """Parse JSON from Claude response, return defaults on failure."""
    try:
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(cleaned)
    except Exception as e:
        logger.warning(f"Claude JSON parse failed: {e}\nRaw: {text[:200]}")
        return {
            "thesis": text[:500] if text else "Analysis unavailable.",
            "conviction": 3,
            "reasons_to_own": [],
            "risks": [],
            "suggested_hold": "unknown",
            "concerns_flag": False,
        }


def _run_analysis(
    symbol: str,
    profile: BotProfile,
    wl_item: Optional[BotWatchlist],
    db: Session,
    model: str = "claude-haiku-4-5-20251001",
) -> WatchlistAnalysis:
    """Orchestrate data fetch + Claude call, return a WatchlistAnalysis (not yet committed)."""
    # 1. Technicals
    technicals = _compute_technicals(symbol)
    current_price = technicals.get("current_price")

    # 2. Fundamentals
    fundamentals = _get_fundamentals(symbol) if not profile.name.startswith("crypto") else {}

    # 3. Strategy votes
    votes = _get_strategy_votes(symbol, profile.id, db)

    # 4. Catalysts
    catalysts = _get_catalysts(symbol, db)

    # 5. Bot horizon
    config = profile.config_json or {}
    horizon = config.get("horizon", "1-30 days") if not profile.name.endswith("_lt") else "3-12 months"
    if profile.name.endswith("_day"):
        horizon = "intraday (same day)"

    # 6. Regime
    from app.db.models.bots import RegimeSnapshot
    regime_row = db.execute(
        select(RegimeSnapshot).order_by(RegimeSnapshot.ts.desc()).limit(1)
    ).scalar()
    regime = {
        "vix": regime_row.vix_regime if regime_row else "mid",
        "trend": regime_row.trend_regime if regime_row else "chop",
    }

    # 7. Build context
    wl_score = wl_item.score if wl_item else None
    wl_reasons = wl_item.reasons if wl_item else {}
    context = {
        "symbol": symbol,
        "asset_class": profile.asset_class,
        "current_price": current_price,
        "fundamentals": fundamentals or None,
        "technicals": technicals or None,
        "strategy_votes": votes,
        "catalysts_next_60d": catalysts,
        "current_regime": regime,
        "bot_assigning_watchlist": profile.name,
        "bot_strategy_horizon": horizon,
        "watchlist_score": wl_score,
        "watchlist_reasons": wl_reasons,
    }

    # 8. Call Claude
    raw, cost = _call_claude(context, model=model)
    parsed = _parse_claude_response(raw)

    concerns = parsed.get("concerns_flag", False) or _has_earnings_soon(catalysts)

    return WatchlistAnalysis(
        bot_profile_id=profile.id,
        symbol=symbol,
        ts=datetime.now(timezone.utc),
        thesis_md=parsed.get("thesis", ""),
        conviction_score=max(1, min(5, int(parsed.get("conviction", 3)))),
        reasons_to_own=parsed.get("reasons_to_own", []),
        risks=parsed.get("risks", []),
        suggested_hold=parsed.get("suggested_hold", ""),
        concerns_flag=bool(concerns),
        inputs_snapshot=context,
        model_used=model,
        cost_usd=cost,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/analyze")
def analyze_symbol(
    symbol: str = Body(...),
    bot_profile_id: int = Body(...),
    force: bool = Body(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Run AI analysis for one symbol. Skips if analyzed within 6h unless force=True."""
    profile = db.get(BotProfile, bot_profile_id)
    if not profile:
        raise HTTPException(404, "Bot profile not found")

    # Cache check: skip if analyzed in last 6h
    if not force:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        existing = db.execute(
            select(WatchlistAnalysis)
            .where(
                WatchlistAnalysis.bot_profile_id == bot_profile_id,
                WatchlistAnalysis.symbol == symbol.upper(),
                WatchlistAnalysis.ts >= cutoff,
            )
            .order_by(WatchlistAnalysis.ts.desc())
            .limit(1)
        ).scalar()
        if existing:
            return _analysis_to_dict(existing)

    wl_item = db.execute(
        select(BotWatchlist).where(
            BotWatchlist.profile_id == profile.id,
            BotWatchlist.symbol == symbol.upper(),
        )
    ).scalar()

    try:
        model = "claude-sonnet-4-6" if force else "claude-haiku-4-5-20251001"
        analysis = _run_analysis(symbol.upper(), profile, wl_item, db, model=model)
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        return _analysis_to_dict(analysis)
    except Exception as e:
        logger.error(f"Analyst failed for {symbol}: {e}", exc_info=True)
        # Return a graceful stub so the UI doesn't break
        stub = WatchlistAnalysis(
            bot_profile_id=bot_profile_id,
            symbol=symbol.upper(),
            ts=datetime.now(timezone.utc),
            thesis_md=f"Analysis unavailable: {str(e)[:120]}",
            conviction_score=None,
            reasons_to_own=[],
            risks=[],
            suggested_hold=None,
            concerns_flag=False,
            inputs_snapshot={},
            model_used=None,
            cost_usd=0.0,
        )
        db.add(stub)
        db.commit()
        db.refresh(stub)
        return _analysis_to_dict(stub)


@router.get("/watchlist/{bot_profile_id}")
def get_watchlist_analyses(
    bot_profile_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Latest analysis for each symbol currently on a bot's watchlist."""
    profile = db.get(BotProfile, bot_profile_id)
    if not profile:
        raise HTTPException(404, "Bot profile not found")

    # Get all active watchlist symbols for this bot
    wl_rows = db.execute(
        select(BotWatchlist).where(
            BotWatchlist.profile_id == bot_profile_id,
            BotWatchlist.status.in_(["active", "watching", "pending_entry"]),
        )
    ).scalars().all()

    symbols = [w.symbol for w in wl_rows]
    if not symbols:
        return []

    # Get latest analysis per symbol (subquery approach)
    analyses = {}
    for sym in symbols:
        row = db.execute(
            select(WatchlistAnalysis)
            .where(
                WatchlistAnalysis.bot_profile_id == bot_profile_id,
                WatchlistAnalysis.symbol == sym,
            )
            .order_by(WatchlistAnalysis.ts.desc())
            .limit(1)
        ).scalar()
        if row:
            analyses[sym] = row

    return [_analysis_to_dict(analyses[s]) for s in symbols if s in analyses]


@router.get("/symbol/{symbol}")
def get_symbol_analysis(
    symbol: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Cross-bot view: latest analysis per bot + consensus."""
    rows = db.execute(
        select(WatchlistAnalysis)
        .where(WatchlistAnalysis.symbol == symbol.upper())
        .order_by(WatchlistAnalysis.ts.desc())
        .limit(20)
    ).scalars().all()

    # Latest per bot_profile_id
    seen: dict[int, WatchlistAnalysis] = {}
    for r in rows:
        if r.bot_profile_id not in seen:
            seen[r.bot_profile_id] = r

    per_bot = [_analysis_to_dict(r) for r in seen.values()]

    scores = [r.conviction_score for r in seen.values() if r.conviction_score is not None]
    avg_conviction = round(sum(scores) / len(scores), 1) if scores else None

    return {
        "symbol": symbol.upper(),
        "per_bot": per_bot,
        "consensus": {
            "avg_conviction": avg_conviction,
            "bot_count": len(per_bot),
            "concerns_flagged": sum(1 for r in seen.values() if r.concerns_flag),
        },
    }


@router.get("/thesis/{symbol}")
def get_thesis(
    symbol: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Lightweight thesis card for a symbol. Uses a module-level 6-hour cache.
    Returns: { symbol, thesis, bullish_points, bearish_points, verdict, cached_at }
    Verdict is one of: BULLISH, BEARISH, NEUTRAL
    """
    sym = symbol.upper()
    now = datetime.now(timezone.utc)

    # Check module-level cache
    cached = _THESIS_CACHE.get(sym)
    if cached:
        age = (now - cached["cached_at"]).total_seconds() / 3600
        if age < _THESIS_TTL_HOURS:
            return cached["data"]

    # Check DB for a recent analysis (within 6h)
    cutoff = now - timedelta(hours=_THESIS_TTL_HOURS)
    db_row = db.execute(
        select(WatchlistAnalysis)
        .where(
            WatchlistAnalysis.symbol == sym,
            WatchlistAnalysis.ts >= cutoff,
        )
        .order_by(WatchlistAnalysis.ts.desc())
        .limit(1)
    ).scalar()

    if db_row and db_row.thesis_md:
        conviction = db_row.conviction_score or 3
        if conviction >= 4:
            verdict = "BULLISH"
        elif conviction <= 2:
            verdict = "BEARISH"
        else:
            verdict = "NEUTRAL"

        result = {
            "symbol": sym,
            "thesis": db_row.thesis_md,
            "bullish_points": db_row.reasons_to_own or [],
            "bearish_points": db_row.risks or [],
            "verdict": verdict,
            "cached_at": db_row.ts.isoformat(),
        }
        _THESIS_CACHE[sym] = {"data": result, "cached_at": now}
        return result

    # Generate fresh via relay
    try:
        from app.services.llm_client import call_llm_cached
        system = "You are a quantitative analyst. Analyze the given stock symbol and provide a concise investment thesis. Be specific, factual, and balanced."
        user = (
            f'Provide an investment thesis for {sym}. Include: 3 bullish points, 3 bearish points, '
            f'and a one-sentence verdict. Format as JSON: {{"thesis": str, "bullish": [str], "bearish": [str], "verdict": str}}'
        )
        raw = call_llm_cached(
            model="claude-haiku-4-5-20251001",
            prompt=user,
            system_prompt=system,
            max_tokens=800,
            ttl_seconds=21600,
            cache_key_extra=f"{sym}_{profile_id}",
            agent_name="analyst",
        )
        parsed = _parse_claude_response(raw)

        # Derive verdict from parsed response or default
        raw_verdict = parsed.get("verdict", "")
        verdict_upper = raw_verdict.upper() if raw_verdict else ""
        if "BULLISH" in verdict_upper:
            verdict = "BULLISH"
        elif "BEARISH" in verdict_upper:
            verdict = "BEARISH"
        else:
            verdict = "NEUTRAL"

        result = {
            "symbol": sym,
            "thesis": parsed.get("thesis", raw[:400] if raw else "Analysis unavailable."),
            "bullish_points": parsed.get("bullish", parsed.get("reasons_to_own", [])),
            "bearish_points": parsed.get("bearish", parsed.get("risks", [])),
            "verdict": verdict,
            "cached_at": now.isoformat(),
        }
        _THESIS_CACHE[sym] = {"data": result, "cached_at": now}
        return result

    except Exception as e:
        logger.error(f"Thesis generation failed for {sym}: {e}", exc_info=True)
        raise HTTPException(503, f"Analysis unavailable — check API key")


@router.post("/refresh/{bot_profile_id}")
def refresh_bot_watchlist(
    bot_profile_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Queue re-analysis for all watchlist symbols (synchronous, up to 20 symbols)."""
    profile = db.get(BotProfile, bot_profile_id)
    if not profile:
        raise HTTPException(404, "Bot profile not found")

    wl_rows = db.execute(
        select(BotWatchlist).where(
            BotWatchlist.profile_id == bot_profile_id,
            BotWatchlist.status.in_(["active", "watching", "pending_entry"]),
        ).limit(20)
    ).scalars().all()

    if not wl_rows:
        return {"analyzed": 0, "cost_usd": 0.0}

    run = AnalystDailyRun(
        run_date=date.today(),
        bot_profile_id=bot_profile_id,
        num_analyzed=0,
        num_high_conviction=0,
        num_flagged_concerns=0,
        total_cost_usd=0.0,
    )
    db.add(run)
    db.flush()

    analyzed = 0
    total_cost = 0.0
    high_conv = 0
    flagged = 0

    for wl in wl_rows:
        try:
            analysis = _run_analysis(wl.symbol, profile, wl, db, model="claude-haiku-4-5-20251001")
            db.add(analysis)
            db.flush()
            total_cost += analysis.cost_usd or 0.0
            analyzed += 1
            if (analysis.conviction_score or 0) >= 4:
                high_conv += 1
            if analysis.concerns_flag:
                flagged += 1
        except Exception as e:
            logger.warning(f"Analyst skip {wl.symbol}: {e}")

    run.num_analyzed = analyzed
    run.num_high_conviction = high_conv
    run.num_flagged_concerns = flagged
    run.total_cost_usd = round(total_cost, 6)
    run.completed_at = datetime.now(timezone.utc)
    db.commit()

    return {"analyzed": analyzed, "cost_usd": round(total_cost, 6)}


@router.get("/runs")
def get_runs(
    bot_profile_id: Optional[int] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = select(AnalystDailyRun).order_by(AnalystDailyRun.run_date.desc()).limit(limit)
    if bot_profile_id:
        q = q.where(AnalystDailyRun.bot_profile_id == bot_profile_id)
    rows = db.execute(q).scalars().all()
    return [
        {
            "id": r.id,
            "date": r.run_date.isoformat(),
            "bot_profile_id": r.bot_profile_id,
            "num_analyzed": r.num_analyzed,
            "num_high_conviction": r.num_high_conviction,
            "num_flagged_concerns": r.num_flagged_concerns,
            "total_cost_usd": r.total_cost_usd,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


@router.get("/summary")
def get_today_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Aggregate summary across all bots for today's (or most recent) analyses."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = db.execute(
        select(WatchlistAnalysis)
        .where(WatchlistAnalysis.ts >= cutoff)
        .order_by(WatchlistAnalysis.ts.desc())
    ).scalars().all()

    # Latest per symbol across all bots
    seen: dict[str, WatchlistAnalysis] = {}
    for r in rows:
        key = f"{r.bot_profile_id}:{r.symbol}"
        if key not in seen:
            seen[key] = r

    all_rows = list(seen.values())
    total = len(all_rows)
    high_conv = [r for r in all_rows if (r.conviction_score or 0) >= 4]
    flagged = [r for r in all_rows if r.concerns_flag]

    # Top 10 by conviction
    top = sorted(all_rows, key=lambda r: (r.conviction_score or 0), reverse=True)[:10]

    # Fetch profile names
    profile_ids = list({r.bot_profile_id for r in all_rows})
    profiles = {
        p.id: p.name
        for p in db.execute(select(BotProfile).where(BotProfile.id.in_(profile_ids))).scalars()
    }

    def _summary_dict(r: WatchlistAnalysis) -> dict:
        return {
            "id": r.id,
            "symbol": r.symbol,
            "bot_name": profiles.get(r.bot_profile_id, "unknown"),
            "bot_profile_id": r.bot_profile_id,
            "conviction_score": r.conviction_score,
            "concerns_flag": r.concerns_flag,
            "thesis_preview": (r.thesis_md or "")[:120],
            "suggested_hold": r.suggested_hold,
            "ts": r.ts.isoformat(),
        }

    return {
        "total_analyzed": total,
        "num_high_conviction": len(high_conv),
        "num_flagged": len(flagged),
        "top_picks": [_summary_dict(r) for r in top],
        "concerns": [_summary_dict(r) for r in sorted(flagged, key=lambda r: r.conviction_score or 0, reverse=True)[:10]],
    }


@router.get("/highlights")
def get_highlights(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Top high-conviction picks for the Dashboard analyst highlights row."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    rows = db.execute(
        select(WatchlistAnalysis)
        .where(WatchlistAnalysis.ts >= cutoff)
        .order_by(WatchlistAnalysis.conviction_score.desc(), WatchlistAnalysis.ts.desc())
    ).scalars().all()

    # Deduplicate to latest per symbol
    seen: dict[str, WatchlistAnalysis] = {}
    for r in rows:
        if r.symbol not in seen:
            seen[r.symbol] = r

    def _conviction_label(score: int | None) -> str:
        if score is None:
            return "LOW"
        if score >= 4:
            return "HIGH"
        if score >= 3:
            return "MED"
        return "LOW"

    highlights = [
        {
            "symbol": r.symbol,
            "conviction": _conviction_label(r.conviction_score),
            "thesis": (r.thesis_md or "")[:120],
        }
        for r in list(seen.values())[:10]
    ]
    return {"highlights": highlights}


# ── Serialiser ──────────────────────────────────────────────────────────────────

def _analysis_to_dict(r: WatchlistAnalysis) -> dict:
    return {
        "id": r.id,
        "bot_profile_id": r.bot_profile_id,
        "symbol": r.symbol,
        "ts": r.ts.isoformat() if r.ts else None,
        "thesis_md": r.thesis_md or "",
        "conviction_score": r.conviction_score,
        "reasons_to_own": r.reasons_to_own or [],
        "risks": r.risks or [],
        "suggested_hold": r.suggested_hold or "",
        "concerns_flag": r.concerns_flag,
        "model_used": r.model_used,
        "cost_usd": r.cost_usd,
    }
