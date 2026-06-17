"""
Macro Strategist Agent — regime classification + rich Discord commentary for BMG Capital.

Posting triggers (4h cooldown applies to all):
  A — regime name changed vs last post
  B — VIX crossed a tier boundary (20 / 25 / 30)
  C — SPY flipped above/below 200-day MA
  D — BTC dominance crossed 50%

Daily brief (7:00 AM ET, is_daily_brief=True): posts regardless of triggers,
  unless already posted within the cooldown window.

Silent refreshes: regime classification + snapshot saved every call.
  Discord is only posted when a trigger fires or daily brief runs.

Called by: POST /api/agents/macro-strategist/run-classification
           Queen Agent daily standup at 7 AM ET (is_daily_brief=True)
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone, date
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Regime display ─────────────────────────────────────────────────────────────

_REGIME_EMOJI = {
    "bull_trending":  "🟢",
    "bear_trending":  "🔴",
    "choppy":         "🟡",
    "crisis":         "🔴",
    "complacency":    "🟠",
    "neutral":        "⚪",
    "unknown":        "❓",
}

_REGIME_LABEL = {
    "bull_trending":  "Bull Trending",
    "bear_trending":  "Bear Trending",
    "choppy":         "Choppy / Sideways",
    "crisis":         "Crisis / Risk-Off",
    "complacency":    "Complacency / Low-Vol",
    "neutral":        "Neutral",
    "unknown":        "Unknown",
}

_VIX_THRESHOLDS = {
    "crisis":      30,
    "elevated":    20,
    "normal":      15,
    "complacency": 12,
}

_VIX_TIER_LABELS = {0: "below 20", 1: "20–25 range", 2: "25–30 range", 3: "above 30"}

_COOLDOWN_HOURS = 4

# ── Bot implication templates ──────────────────────────────────────────────────

_STOCK_IMPLICATIONS = {
    "bull_trending":  "Bias toward long positions; momentum signals more reliable",
    "bear_trending":  "Fewer new long entries expected; defensive sizing likely",
    "choppy":         "Reduced position sizing; mean-reversion over momentum",
    "crisis":         "Risk-off — equity bots likely reducing or pausing exposure",
    "complacency":    "Low volatility may reduce signal frequency; range-bound trades",
    "neutral":        "Standard parameters; watching for a directional break",
}

_CRYPTO_IMPLICATIONS = {
    "bull_trending":  "Equity strength typically leads crypto by 1–2 weeks; watch BTC",
    "bear_trending":  "Equity weakness often precedes crypto selloffs; defensive posture",
    "choppy":         "Crypto volatility is independent; follow BTC dominance and on-chain data",
    "crisis":         "Risk-off events historically cause sharp crypto drops; elevated caution",
    "complacency":    "Low equity vol sometimes precedes crypto breakouts; monitor closely",
    "neutral":        "Standard crypto parameters; following BTC trend",
}

_OPTIONS_IMPLICATIONS = {
    "bull_trending":  "VIX dropping → less premium available; favor income over hedging",
    "bear_trending":  "Rising fear → better premium for income sellers; manage delta risk",
    "choppy":         "Range-bound → favorable for theta strategies (selling premium)",
    "crisis":         "VIX > 30 → short-vol strategies dangerous; long-vol hedges in play",
    "complacency":    "VIX below 12 → premium compressed; reduced income opportunity",
    "neutral":        "Moderate implied volatility; standard parameters",
}

# ── Discord helpers ────────────────────────────────────────────────────────────

def _get_macro_channel() -> tuple[str, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_MACRO_VIEW", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
        or os.getenv("DISCORD_CH_DAILY_DIGEST", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
        channel_id = (
            getattr(settings, "discord_ch_macro_view", "")
            or settings.discord_ch_dev_log
            or settings.discord_ch_daily_digest
            or channel_id
        )
    except Exception:
        pass
    return token, channel_id


def _post_discord(token: str, channel_id: str, embed: dict) -> bool:
    if not channel_id or not token:
        return False
    try:
        import httpx
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
            },
            json={"embeds": [embed]},
            timeout=10,
        )
        return resp.is_success
    except Exception as exc:
        logger.warning("[macro_strategist] Discord post failed: %s", exc)
        return False


# ── yfinance fetch helpers ─────────────────────────────────────────────────────

def _yf_fetch_with_retry(fn, label: str, retries: int = 3, backoff: float = 2.0):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            logger.warning("[macro_strategist] %s attempt %d/%d failed: %s", label, attempt, retries, exc)
            if attempt < retries:
                time.sleep(backoff)
    logger.error("[macro_strategist] %s gave up after %d attempts: %s", label, retries, last_exc)
    return None


def _fetch_yfinance_indicators() -> dict:
    """
    Fetch VIX, SPY vs 200MA, VIX 1-week-ago, and BTC price from Yahoo Finance.
    Each ticker gets 3 attempts with 2s backoff. Missing data is never silent.
    Returns empty dict on total failure — caller guards against null records.
    """
    result: dict = {}
    try:
        import yfinance as yf

        # ── VIX current (fast_info, with history fallback) ────────────────────
        logger.info("[regime] Fetching ^VIX (fast_info, 3 retries)")
        def _vix_fast():
            val = getattr(yf.Ticker("^VIX").fast_info, "last_price", None)
            if val is None:
                raise ValueError("fast_info.last_price is None")
            return round(float(val), 2)

        vix_val = _yf_fetch_with_retry(_vix_fast, "^VIX fast_info")
        if vix_val is not None:
            result["vix"] = vix_val
            logger.info("[regime] ^VIX=%.2f (fast_info)", vix_val)

        # ── VIX 15-day history — get current (if fast_info failed) + 1wk ago ──
        logger.info("[regime] Fetching ^VIX 15d history for prior-week comparison")
        def _vix_hist():
            hist = yf.Ticker("^VIX").history(period="15d", auto_adjust=False)
            if hist.empty:
                raise ValueError("^VIX history empty")
            return hist

        vix_hist = _yf_fetch_with_retry(_vix_hist, "^VIX 15d history")
        if vix_hist is not None:
            if result.get("vix") is None and not vix_hist.empty:
                result["vix"] = round(float(vix_hist["Close"].iloc[-1]), 2)
                logger.info("[regime] ^VIX=%.2f (history fallback)", result["vix"])
            # Approx 5 trading days ago = 1 calendar week ago
            if len(vix_hist) >= 6:
                result["vix_1w_ago"] = round(float(vix_hist["Close"].iloc[-6]), 2)
        else:
            if result.get("vix") is None:
                logger.error("[regime] ^VIX unavailable from all yfinance sources")

        # ── SPY 250-day history — 200MA trend + MA value ─────────────────────
        logger.info("[regime] Fetching SPY 250d history for 200MA trend")
        def _spy_hist():
            hist = yf.Ticker("SPY").history(period="250d", auto_adjust=True)
            if hist.empty:
                raise ValueError("SPY history empty")
            if len(hist) < 200:
                raise ValueError(f"SPY history only {len(hist)} rows (need 200)")
            return hist

        spy_df = _yf_fetch_with_retry(_spy_hist, "SPY history")
        if spy_df is not None:
            spy_close = float(spy_df["Close"].iloc[-1])
            ma200 = float(spy_df["Close"].rolling(200).mean().iloc[-1])
            ratio = spy_close / ma200
            result["spy_price"] = round(spy_close, 2)
            result["spy_200ma"] = round(ma200, 2)
            result["spx_200ma_ratio"] = round(ratio, 4)
            if ratio >= 1.02:
                result["trend_regime"] = "bull_trending"
            elif ratio <= 0.98:
                result["trend_regime"] = "bear_trending"
            else:
                result["trend_regime"] = "choppy"
            logger.info("[regime] SPY=%.2f 200MA=%.2f ratio=%.4f trend=%s", spy_close, ma200, ratio, result["trend_regime"])
        else:
            logger.error("[regime] SPY trend unavailable — yfinance failed after all retries")

        # ── BTC-USD — current price + 7d change ──────────────────────────────
        logger.info("[regime] Fetching BTC-USD 10d history")
        def _btc_fetch():
            hist = yf.Ticker("BTC-USD").history(period="10d", auto_adjust=True)
            if hist.empty or len(hist) < 2:
                raise ValueError("BTC-USD history empty or too short")
            price = round(float(hist["Close"].iloc[-1]))
            change_7d = None
            if len(hist) >= 6:
                price_7d_ago = float(hist["Close"].iloc[-6])
                if price_7d_ago > 0:
                    change_7d = round((price - price_7d_ago) / price_7d_ago * 100, 1)
            return price, change_7d

        btc_data = _yf_fetch_with_retry(_btc_fetch, "BTC-USD history")
        if btc_data is not None:
            result["btc_price"] = btc_data[0]
            if btc_data[1] is not None:
                result["btc_7d_pct"] = btc_data[1]
            logger.info("[regime] BTC=$%d (7d=%s%%)", btc_data[0], btc_data[1])

    except ImportError:
        logger.warning("[macro_strategist] yfinance not installed — skipping live fetch")

    return result


def _read_live_indicators(db: Session) -> dict:
    """
    Merge yfinance (fresh) with most recent DB RegimeSnapshot (supplements btc_dominance).
    DB values only win where yfinance returned None — fresh market data takes precedence.
    """
    merged = _fetch_yfinance_indicators()

    try:
        from app.db.models.bots import RegimeSnapshot as LiveSnap
        snap = db.query(LiveSnap).order_by(LiveSnap.ts.desc()).first()
        if snap:
            db_fields = {
                "vix":       getattr(snap, "vix_value", None),
                "btc_dom":   getattr(snap, "btc_dominance", None),
                "as_of":     snap.ts.isoformat() if snap.ts else None,
            }
            for k, v in db_fields.items():
                if v is not None and k not in merged:
                    merged[k] = v
        else:
            logger.warning("[macro_strategist] No RegimeSnapshot row — relying solely on yfinance")
    except Exception as exc:
        logger.warning("[macro_strategist] DB indicators read failed: %s", exc)

    if not merged.get("vix"):
        logger.warning("[macro_strategist] Final indicators missing VIX")
    if not merged.get("trend_regime"):
        logger.warning("[macro_strategist] Final indicators missing trend_regime")

    return merged


# ── Last-post state table ──────────────────────────────────────────────────────

def _ensure_macro_last_post_table(db: Session) -> None:
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS macro_last_post (
                id         INTEGER PRIMARY KEY,
                regime_name TEXT,
                vix_value   REAL,
                spy_trend   TEXT,
                btc_dominance REAL,
                posted_at   TEXT
            )
        """))
        db.commit()
    except Exception as exc:
        logger.warning("[macro_strategist] macro_last_post table ensure failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def _read_last_post(db: Session) -> Optional[dict]:
    try:
        row = db.execute(text(
            "SELECT regime_name, vix_value, spy_trend, btc_dominance, posted_at "
            "FROM macro_last_post WHERE id = 1"
        )).fetchone()
        if row is None:
            return None
        return {
            "regime_name":   row[0],
            "vix_value":     row[1],
            "spy_trend":     row[2],
            "btc_dominance": row[3],
            "posted_at":     row[4],
        }
    except Exception as exc:
        logger.warning("[macro_strategist] _read_last_post failed: %s", exc)
        return None


def _save_last_post(db: Session, regime: str, vix: Optional[float],
                    spy_trend: Optional[str], btc_dom: Optional[float]) -> None:
    try:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        db.execute(text("""
            INSERT INTO macro_last_post (id, regime_name, vix_value, spy_trend, btc_dominance, posted_at)
            VALUES (1, :regime, :vix, :spy, :btc, :now)
            ON CONFLICT(id) DO UPDATE SET
                regime_name   = excluded.regime_name,
                vix_value     = excluded.vix_value,
                spy_trend     = excluded.spy_trend,
                btc_dominance = excluded.btc_dominance,
                posted_at     = excluded.posted_at
        """), {"regime": regime, "vix": vix, "spy": spy_trend, "btc": btc_dom, "now": now_str})
        db.commit()
    except Exception as exc:
        logger.warning("[macro_strategist] _save_last_post failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


# ── Trigger detection helpers ──────────────────────────────────────────────────

def _vix_tier(vix: float) -> int:
    """0 = below 20, 1 = 20–25, 2 = 25–30, 3 = above 30."""
    if vix >= 30: return 3
    if vix >= 25: return 2
    if vix >= 20: return 1
    return 0


def _spy_trend_side(ratio: Optional[float]) -> Optional[str]:
    if ratio is None:
        return None
    return "above" if ratio >= 1.0 else "below"


def _within_cooldown(last_post: Optional[dict]) -> bool:
    if last_post is None:
        return False
    posted_str = last_post.get("posted_at")
    if not posted_str:
        return False
    try:
        posted_at = datetime.fromisoformat(str(posted_str).replace(" ", "T"))
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        elapsed_h = (datetime.now(timezone.utc) - posted_at).total_seconds() / 3600
        return elapsed_h < _COOLDOWN_HOURS
    except Exception:
        return False


def _check_triggers(
    regime: str,
    indicators: dict,
    last_post: Optional[dict],
) -> tuple[bool, list[str]]:
    """
    Returns (should_post, trigger_reasons).
    Compares current state vs last POSTED state (not last snapshot).
    """
    if last_post is None:
        return True, ["Trigger A: first post — no prior state recorded"]

    reasons: list[str] = []

    # A: regime name changed
    if regime != last_post.get("regime_name"):
        prev = last_post.get("regime_name", "unknown")
        reasons.append(f"Trigger A: regime {prev} → {regime}")

    # B: VIX crossed a tier threshold (20 / 25 / 30)
    vix_now = indicators.get("vix")
    vix_last = last_post.get("vix_value")
    if vix_now is not None and vix_last is not None:
        if _vix_tier(vix_now) != _vix_tier(vix_last):
            tier = _vix_tier(vix_now)
            reasons.append(f"Trigger B: VIX moved to {_VIX_TIER_LABELS[tier]} ({vix_now:.1f})")

    # C: SPY flipped above/below 200-day MA
    ratio = indicators.get("spx_200ma_ratio")
    spy_side_now = _spy_trend_side(ratio)
    spy_side_last = last_post.get("spy_trend")
    if spy_side_now and spy_side_last and spy_side_now != spy_side_last:
        reasons.append(f"Trigger C: SPY flipped {spy_side_last} → {spy_side_now} 200-day MA")

    # D: BTC dominance crossed 50%
    btc_dom_now = indicators.get("btc_dom") or indicators.get("btc_dominance")
    btc_dom_last = last_post.get("btc_dominance")
    if btc_dom_now is not None and btc_dom_last is not None:
        if (btc_dom_now >= 50) != (btc_dom_last >= 50):
            direction = "above" if btc_dom_now >= 50 else "below"
            reasons.append(f"Trigger D: BTC dominance crossed {direction} 50% ({btc_dom_now:.1f}%)")

    return len(reasons) > 0, reasons


# ── Active sleeve detection ────────────────────────────────────────────────────

def _get_active_sleeves(db: Session) -> set[str]:
    """Return the set of sleeve types that have at least one enabled T1/T2/T3 bot."""
    try:
        rows = db.execute(text("""
            SELECT
                CASE
                    WHEN bp.name LIKE '%options%' THEN 'options'
                    WHEN bp.asset_class = 'crypto' THEN 'crypto'
                    WHEN bp.asset_class = 'quant'  THEN 'quant'
                    ELSE 'stocks'
                END AS sleeve
            FROM bot_allocations ba
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE ba.enabled = 1
              AND ba.tier IN ('T1', 'T2', 'T3')
        """)).fetchall()
        return {r[0] for r in rows}
    except Exception as exc:
        logger.warning("[macro_strategist] _get_active_sleeves failed: %s", exc)
        return {"stocks", "crypto"}  # safe default


# ── Rich embed builders ────────────────────────────────────────────────────────

def _build_plain_headline(
    regime: str,
    prev_regime: Optional[str],
    is_transition: bool,
    trigger_reasons: list[str],
    indicators: dict,
) -> str:
    vix = indicators.get("vix")

    # Crisis overrides everything
    if vix and vix >= 30:
        return f"Extreme Fear — VIX Above 30 ({vix:.1f})"

    # Regime transition headlines
    if is_transition and prev_regime:
        _transitions = {
            ("choppy",       "bull_trending"):  "Stocks Climbing Out of a Choppy Stretch",
            ("bear_trending","bull_trending"):  "Markets Reversing — Uptrend Forming",
            ("neutral",      "bull_trending"):  "Markets Gaining Momentum — Uptrend Emerging",
            ("bull_trending","bear_trending"):  "Bull Trend Breaking Down",
            ("bull_trending","choppy"):         "Momentum Fading — Markets Going Sideways",
            ("neutral",      "bear_trending"):  "Markets Shifting Bearish",
            ("crisis",       "bull_trending"):  "Fear Easing — Markets Stabilizing",
            ("crisis",       "neutral"):        "Volatility Retreating — Markets Finding Footing",
            ("bull_trending","crisis"):         "Sharp Selloff — Markets Entering Risk-Off Mode",
            ("choppy",       "crisis"):         "Volatility Spike — Markets Entering Crisis Mode",
        }
        key = (prev_regime, regime)
        if key in _transitions:
            return _transitions[key]
        # Fallback
        regime_plain = {
            "bull_trending": "an uptrend", "bear_trending": "a downtrend",
            "choppy": "choppy conditions", "crisis": "risk-off / crisis mode",
            "complacency": "low-volatility complacency", "neutral": "neutral conditions",
        }
        return f"Market Conditions Shifted to {regime_plain.get(regime, regime).title()}"

    # Specific trigger headlines
    for r in trigger_reasons:
        if "Trigger B" in r:
            if vix and vix >= 25:
                return f"Fear Building — VIX in Elevated Territory ({vix:.1f})"
            if vix and vix < 20:
                return f"Volatility Easing — VIX Back Below 20 ({vix:.1f})"
            return f"Volatility Shift — VIX at {vix:.1f}"
        if "Trigger C" in r:
            return ("S&P 500 Reclaims Its 200-Day Moving Average"
                    if "below → above" in r or "below" in last_part(r, "→") is False
                    else "S&P 500 Drops Below Its 200-Day Moving Average")
        if "Trigger D" in r:
            btc_dom = indicators.get("btc_dom") or indicators.get("btc_dominance")
            if btc_dom:
                direction = "above" if btc_dom >= 50 else "below"
                return f"Bitcoin Dominance Crosses {direction} 50% ({btc_dom:.1f}%)"

    # Regime description headlines for daily briefs
    _regime_headlines = {
        "bull_trending":  "Stocks in a Confirmed Uptrend",
        "bear_trending":  "Markets in a Downtrend",
        "choppy":         "Choppy, Range-Bound Conditions",
        "crisis":         "Crisis Conditions — Volatility Elevated",
        "complacency":    "Unusually Calm — Complacency Watch",
        "neutral":        "Mixed Signals Across Indicators",
    }
    return _regime_headlines.get(regime, "Market Conditions Update")


def last_part(s: str, sep: str) -> str:
    """Helper to extract the last part of a string split by sep."""
    parts = s.split(sep)
    return parts[-1].strip() if parts else ""


def _build_what_changed(
    regime: str,
    prev_regime: Optional[str],
    is_transition: bool,
    indicators: dict,
    trigger_reasons: list[str],
) -> str:
    vix = indicators.get("vix")
    vix_1w = indicators.get("vix_1w_ago")
    spy = indicators.get("spy_price")
    ma200 = indicators.get("spy_200ma")
    ratio = indicators.get("spx_200ma_ratio")
    spy_side = "above" if (ratio and ratio >= 1.0) else "below"

    if is_transition and prev_regime:
        spy_detail = ""
        if spy and ma200:
            spy_detail = f" S&P 500 is now {spy_side} its 200-day average (${spy:,.0f} vs ${ma200:,.0f} MA)."

        _transitions = {
            ("choppy", "bull_trending"): (
                f"Markets shifted from a choppy, sideways pattern into a clear upward trend.{spy_detail}"
            ),
            ("bear_trending", "bull_trending"): (
                f"A significant reversal — equity markets recovered from a downtrend into positive momentum."
                + (f" S&P 500 is now at ${spy:,.0f}." if spy else "")
            ),
            ("bull_trending", "bear_trending"): (
                "The bull trend has broken down. Selling pressure increased and markets shifted bearish."
                + (f" S&P 500 is at ${spy:,.0f}" + (f", below its 200-day MA at ${ma200:,.0f}" if ma200 else "") + "." if spy else "")
            ),
            ("bull_trending", "crisis"): (
                f"Volatility spiked sharply — VIX jumped to {vix:.1f}. Markets entered risk-off mode with broad-based selling."
                if vix else "Markets entered crisis conditions with elevated volatility."
            ),
            ("choppy", "crisis"): (
                f"A spike in volatility ended the sideways chop — VIX hit {vix:.1f}, signaling a sharp shift to risk-off."
                if vix else "A volatility spike shifted markets from choppy to crisis conditions."
            ),
            ("crisis", "bull_trending"): (
                f"Fear is receding — VIX dropped to {vix:.1f}" + (f" from {vix_1w:.1f} a week ago" if vix_1w else "") +
                ". Equity markets are stabilizing and recovering."
            ),
            ("crisis", "neutral"): (
                f"Volatility is retreating — VIX is now {vix:.1f}" + (f" vs {vix_1w:.1f} last week" if vix_1w else "") +
                ". Markets are finding footing after the risk-off period."
            ),
            ("neutral", "bull_trending"): (
                f"Markets broke out of neutral territory into a clear uptrend.{spy_detail}"
            ),
            ("bull_trending", "choppy"): (
                f"Momentum is fading. Markets have shifted from a clean uptrend into choppy, range-bound trading.{spy_detail}"
            ),
        }
        key = (prev_regime, regime)
        text = _transitions.get(key)
        if text:
            return text.strip()

    # Trigger-specific descriptions
    for r in trigger_reasons:
        if "Trigger B" in r:
            tier = _vix_tier(vix) if vix else 0
            tier_desc = {
                0: "back into calmer territory (below 20)",
                1: "into the elevated caution zone (20–25)",
                2: "into the high-fear zone (25–30)",
                3: "into extreme fear territory (above 30)",
            }[tier]
            vix_str = f"VIX moved to {vix:.1f}" if vix else "Volatility shifted"
            vix_1w_str = f" from {vix_1w:.1f} a week ago" if vix_1w else ""
            return f"{vix_str}{vix_1w_str}, entering {tier_desc}."

        if "Trigger C" in r:
            if "below → above" in r or "above" in r.split("→")[-1]:
                return (
                    f"S&P 500 crossed above its 200-day moving average"
                    + (f" (${spy:,.0f} vs ${ma200:,.0f} MA)" if spy and ma200 else "")
                    + " — a key bullish technical signal."
                )
            return (
                f"S&P 500 dropped below its 200-day moving average"
                + (f" (${spy:,.0f} vs ${ma200:,.0f} MA)" if spy and ma200 else "")
                + " — a key bearish technical signal."
            )

        if "Trigger D" in r:
            btc_dom = indicators.get("btc_dom") or indicators.get("btc_dominance")
            if btc_dom:
                direction = "above" if btc_dom >= 50 else "below"
                rotation = "into Bitcoin from altcoins" if btc_dom >= 50 else "into altcoins and risk assets"
                return f"Bitcoin dominance crossed {direction} 50% ({btc_dom:.1f}%), signaling a rotation {rotation}."

    # Daily brief or generic
    _regime_descs = {
        "bull_trending":  "Markets remain in an uptrend with equity momentum positive.",
        "bear_trending":  "Markets are in a downtrend with selling pressure sustained.",
        "choppy":         "Markets are trading in a choppy, range-bound pattern with no clear directional bias.",
        "crisis":         "Markets remain in risk-off mode with volatility elevated.",
        "complacency":    "Volatility is unusually suppressed — historically a caution signal.",
        "neutral":        "Indicators are mixed with no dominant trend signal.",
    }
    return _regime_descs.get(regime, "Market conditions updated based on latest indicators.")


def _build_why_happening(indicators: dict) -> str:
    bullets: list[str] = []

    vix = indicators.get("vix")
    vix_1w = indicators.get("vix_1w_ago")
    if vix is not None:
        vix_interp = (
            "investors calm" if vix < 15 else
            "low volatility" if vix < 20 else
            "elevated caution" if vix < 25 else
            "fear building" if vix < 30 else
            "extreme fear / risk-off"
        )
        vix_1w_str = f" vs **{vix_1w:.1f}** a week ago" if vix_1w else ""
        bullets.append(f"**Volatility (VIX):** {vix:.1f}{vix_1w_str} — {vix_interp}")

    spy = indicators.get("spy_price")
    ma200 = indicators.get("spy_200ma")
    ratio = indicators.get("spx_200ma_ratio")
    if spy and ma200 and ratio:
        side = "above" if ratio >= 1.0 else "below"
        pct_diff = abs(ratio - 1.0) * 100
        sign = "+" if ratio >= 1.0 else "-"
        trend_interp = "trend confirmed positive" if ratio >= 1.0 else "trend broken — watch for support"
        bullets.append(f"**S&P 500:** ${spy:,.0f} — **{side}** 200-day MA at ${ma200:,.0f} ({sign}{pct_diff:.1f}% | {trend_interp})")
    elif spy:
        bullets.append(f"**S&P 500:** ${spy:,.0f}")

    btc_price = indicators.get("btc_price")
    btc_7d = indicators.get("btc_7d_pct")
    btc_dom = indicators.get("btc_dom") or indicators.get("btc_dominance")
    if btc_price:
        btc_7d_str = f" ({btc_7d:+.1f}% 7d)" if btc_7d is not None else ""
        btc_dom_str = f", dominance {btc_dom:.1f}%" if btc_dom else ""
        bullets.append(f"**Bitcoin:** ${btc_price:,}{btc_7d_str}{btc_dom_str}")
    elif btc_dom:
        bullets.append(f"**BTC Dominance:** {btc_dom:.1f}%")

    return "\n".join(f"• {b}" for b in bullets) if bullets else "_No indicator data available_"


def _build_bot_implications(regime: str, active_sleeves: set[str]) -> str:
    lines: list[str] = []
    if "stocks" in active_sleeves:
        lines.append(f"• **Stock bots:** {_STOCK_IMPLICATIONS.get(regime, 'Standard parameters')}")
    if "crypto" in active_sleeves:
        lines.append(f"• **Crypto bots:** {_CRYPTO_IMPLICATIONS.get(regime, 'Standard parameters')}")
    if "options" in active_sleeves:
        lines.append(f"• **Options bots:** {_OPTIONS_IMPLICATIONS.get(regime, 'Standard parameters')}")
    if "quant" in active_sleeves:
        lines.append("• **Quant bots:** Algorithm-driven; less regime-sensitive (standard parameters)")
    return "\n".join(lines) if lines else "• No active bot sleeves detected"


def _build_rich_embed(
    regime: str,
    prev_regime: Optional[str],
    is_transition: bool,
    trigger_reasons: list[str],
    indicators: dict,
    active_sleeves: set[str],
    started: datetime,
    elapsed_ms: int,
    is_daily_brief: bool = False,
) -> dict:
    headline = _build_plain_headline(regime, prev_regime, is_transition, trigger_reasons, indicators)
    prefix = "📊 DAILY MARKET BRIEF" if is_daily_brief else "📈 MARKET UPDATE"
    title = f"{prefix} — {headline}"

    what_changed = _build_what_changed(regime, prev_regime, is_transition, indicators, trigger_reasons)
    why_happening = _build_why_happening(indicators)
    bot_implications = _build_bot_implications(regime, active_sleeves)

    description = (
        f"**WHAT CHANGED**\n{what_changed}\n\n"
        f"**WHY IT'S HAPPENING**\n{why_happening}\n\n"
        f"**WHAT THIS MEANS FOR YOUR BOTS**\n{bot_implications}"
    )

    color = {
        "bull_trending":  0x4ADE80,
        "bear_trending":  0xF87171,
        "crisis":         0xEF4444,
        "choppy":         0xFBBF24,
        "complacency":    0xFB923C,
        "neutral":        0x94A3B8,
    }.get(regime, 0x64748B)

    return {
        "title":       title[:256],
        "description": description[:4096],
        "color":       color,
        "footer":      {"text": f"Rick (Macro Strategist) · {started.strftime('%Y-%m-%d %H:%M')} UTC"},
    }


# ── Regime classification (unchanged logic) ────────────────────────────────────

def _read_yesterday_regime(db: Session) -> Optional[str]:
    try:
        from app.db.models.bots import RegimeSnapshot as LiveSnap
        row = db.query(LiveSnap).order_by(LiveSnap.ts.desc()).first()
        return getattr(row, "trend_regime", None) if row else None
    except Exception:
        return None


def _classify_regime(indicators: dict) -> tuple[str, float, dict]:
    vix    = indicators.get("vix")
    trend  = (indicators.get("trend_regime") or "unknown").lower()
    vix_r  = (indicators.get("vix_regime") or "unknown").lower()
    vol_p  = indicators.get("vol_pctile")

    signals: dict = {
        "vix":          vix,
        "trend_regime": trend,
        "vix_regime":   vix_r,
        "vol_pctile":   vol_p,
        "btc_dom":      indicators.get("btc_dom"),
        "btc_funding":  indicators.get("btc_funding"),
    }

    confidence = 0.60

    if vix is not None and vix > _VIX_THRESHOLDS["crisis"]:
        regime, confidence = "crisis", 0.90
    elif vix is not None and vix < _VIX_THRESHOLDS["complacency"]:
        regime, confidence = "complacency", 0.80
    elif "bull" in trend:
        regime = "bull_trending"
        confidence = 0.75 if (vol_p is None or vol_p < 0.60) else 0.65
    elif "bear" in trend:
        regime, confidence = "bear_trending", 0.75
    elif "chop" in vix_r or "sideways" in trend:
        regime, confidence = "choppy", 0.70
    elif vix is not None and vix > _VIX_THRESHOLDS["elevated"]:
        regime, confidence = "bear_trending", 0.55
    else:
        regime, confidence = "neutral", 0.50

    if regime == "bull_trending" and "bull" in vix_r:
        confidence = min(confidence + 0.10, 0.95)
    if regime == "bear_trending" and "bear" in vix_r:
        confidence = min(confidence + 0.10, 0.95)

    signals["classified_regime"] = regime
    signals["confidence"] = round(confidence, 3)

    return regime, round(confidence, 3), signals


def _build_synthesis(regime: str, prev_regime: Optional[str], indicators: dict, confidence: float) -> str:
    label = _REGIME_LABEL.get(regime, regime)
    vix_str = f" (VIX {indicators['vix']:.1f})" if indicators.get("vix") else ""
    trans = ""
    if prev_regime and prev_regime != regime:
        prev_label = _REGIME_LABEL.get(prev_regime, prev_regime)
        trans = f" Transition from {prev_label}."
    return f"Regime: **{label}**{vix_str}.{trans} Confidence: {confidence * 100:.0f}%."


def _save_snapshot(
    db: Session,
    regime: str,
    raw_regime: str,
    confidence: float,
    indicators: dict,
    synthesis: str,
    transition_to: Optional[str],
) -> bool:
    try:
        from app.db.models.regime_history import RegimeSnapshot as HistSnap
        today = date.today()

        signals_payload = {
            **indicators,
            "synthesis": synthesis,
            "transition_to": transition_to,
            "classified_by": "macro_strategist",
        }

        existing = db.query(HistSnap).filter(HistSnap.snapshot_date == today).first()
        if existing:
            existing.regime = regime
            existing.raw_regime = raw_regime
            existing.confidence = confidence
            existing.vix_level = indicators.get("vix")
            existing.signals_json = json.dumps(signals_payload)
        else:
            snap = HistSnap(
                snapshot_date=today,
                regime=regime,
                raw_regime=raw_regime,
                confidence=confidence,
                vix_level=indicators.get("vix"),
                signals_json=json.dumps(signals_payload),
            )
            db.add(snap)

        db.commit()
        return True
    except Exception as exc:
        logger.warning("[macro_strategist] snapshot save failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _publish_heartbeat(db: Session, result: dict) -> None:
    try:
        db.execute(text("""
            INSERT INTO agent_messages (from_agent, channel, msg_type, subject, payload, created_at)
            VALUES (:agent, :channel, :mtype, :subject, :payload, :ts)
        """), {
            "agent":   "macro_strategist",
            "channel": "agent_heartbeats",
            "mtype":   "heartbeat",
            "subject": f"regime:{result.get('regime', 'unknown')}",
            "payload": json.dumps(result),
            "ts":      datetime.now(timezone.utc).isoformat(),
        })
        db.commit()
    except Exception as exc:
        logger.warning("[macro_strategist] heartbeat publish failed: %s", exc)


# ── Main entry point ───────────────────────────────────────────────────────────

def run_macro_classification(db: Session, is_daily_brief: bool = False) -> dict:
    """
    Classify regime, save snapshot + heartbeat, then conditionally post to Discord.

    Snapshot is ALWAYS saved. Discord is only posted when:
      - A trigger fires (regime/VIX/SPY/BTC change), OR
      - is_daily_brief=True AND more than 4h since last post.
    """
    started = datetime.now(timezone.utc)
    logger.info("[macro_strategist] Running regime classification (daily_brief=%s)", is_daily_brief)

    _ensure_macro_last_post_table(db)

    indicators = _read_live_indicators(db)

    if indicators.get("vix") is None and indicators.get("trend_regime") is None:
        logger.error(
            "[regime] All data sources failed (VIX=None, trend=None) — "
            "skipping snapshot write. Gaps are better than null records."
        )
        return {
            "regime":         "unknown",
            "snapshot_saved": False,
            "skipped":        True,
            "reason":         "all fetch sources returned None",
            "classified_at":  started.isoformat(),
        }

    prev_regime = _read_yesterday_regime(db)
    regime, confidence, signals = _classify_regime(indicators)
    is_transition = prev_regime is not None and prev_regime != regime

    synthesis = _build_synthesis(regime, prev_regime, indicators, confidence)

    saved = _save_snapshot(
        db,
        regime=regime,
        raw_regime=signals.get("trend_regime", "unknown"),
        confidence=confidence,
        indicators=indicators,
        synthesis=synthesis,
        transition_to=regime if is_transition else None,
    )

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    result = {
        "regime":         regime,
        "prev_regime":    prev_regime,
        "is_transition":  is_transition,
        "confidence":     confidence,
        "synthesis":      synthesis,
        "indicators":     indicators,
        "snapshot_saved": saved,
        "elapsed_ms":     elapsed_ms,
        "classified_at":  started.isoformat(),
    }

    _publish_heartbeat(db, result)

    # ── Posting decision ────────────────────────────────────────────────────────
    last_post = _read_last_post(db)

    if is_daily_brief:
        should_post = not _within_cooldown(last_post)
        trigger_reasons = ["daily brief"] if should_post else []
        if not should_post:
            logger.info("[macro_strategist] Daily brief skipped — within %dh cooldown", _COOLDOWN_HOURS)
    else:
        should_post, trigger_reasons = _check_triggers(regime, indicators, last_post)
        if should_post and _within_cooldown(last_post):
            logger.info(
                "[macro_strategist] Trigger(s) fired but within %dh cooldown — suppressing post: %s",
                _COOLDOWN_HOURS, trigger_reasons,
            )
            should_post = False
            trigger_reasons = []

    result["trigger_reasons"] = trigger_reasons
    result["discord_posted"] = False

    if not should_post:
        logger.info(
            "[macro_strategist] Silent refresh — regime=%s confidence=%.2f (no triggers, no post)",
            regime, confidence,
        )
        return result

    # Build and post rich embed
    active_sleeves = _get_active_sleeves(db)
    embed = _build_rich_embed(
        regime, prev_regime, is_transition, trigger_reasons,
        indicators, active_sleeves, started, elapsed_ms, is_daily_brief,
    )

    token, channel_id = _get_macro_channel()
    logger.info("[macro_strategist] Posting to channel %s (triggers: %s)", channel_id, trigger_reasons)
    posted = _post_discord(token, channel_id, embed)
    result["discord_posted"] = posted

    if posted:
        _save_last_post(
            db,
            regime=regime,
            vix=indicators.get("vix"),
            spy_trend=_spy_trend_side(indicators.get("spx_200ma_ratio")),
            btc_dom=indicators.get("btc_dom") or indicators.get("btc_dominance"),
        )

    logger.info(
        "[macro_strategist] Done — regime=%s transition=%s triggers=%s discord=%s elapsed=%dms",
        regime, is_transition, trigger_reasons, posted, elapsed_ms,
    )
    return result
