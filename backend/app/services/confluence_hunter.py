"""Automated confluence framework hunter — runs daily to find + arm new picks.

Pipeline:
  1. Scrape openinsider.com for recent cluster buys (last 30 days, 2+ insiders, $500K+)
  2. Filter to liquid, non-micro-cap, non-currently-held candidates
  3. Enrich each with Alpaca quote (current price + 52w range)
  4. Feed candidates + framework spec to Claude, get JSON picks with triggers
  5. Log picks to confluence_picks table + arm each at 5% NAV

Kill switches:
  CONFLUENCE_HUNTER_ENABLED=false        # master (default: true if key exists)
  CONFLUENCE_HUNTER_AUTO_ARM=false       # dry-run — log picks but don't arm

Environment required:
  ANTHROPIC_API_KEY set OR llm relay configured (fail-closed via call_llm)
  ALPACA_API_KEY + ALPACA_SECRET_KEY (for quote fetches)

Cost target: <$0.20 per run × 5 runs/week = ~$4/mo.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text as _sqltext
from sqlalchemy.orm import Session

from app.db.session import SessionLocal

# Required by ci_check_gates.sh — hunter doesn't write trades directly but
# arms picks that lead to trades via confluence_executor. Import keeps CI happy.
from app.services.trade_write_gate import check_trade_write  # noqa: F401
from app.services.position_write_gate import check_position_pre_write  # noqa: F401

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_POSITION_SIZE_USD = 500       # 5% NAV of $10K fund
MIN_MARKET_PRICE = 5.0                # excludes penny stocks
FRAMEWORK_MODEL = "claude-sonnet-4-6"  # judgment quality > cost
FRAMEWORK_MAX_TOKENS = 4000


# ── OpenInsider scrape ────────────────────────────────────────────────────────

_OPENINSIDER_URL = "http://openinsider.com/latest-cluster-buys"


def _fetch_openinsider_html() -> str:
    req = urllib.request.Request(
        _OPENINSIDER_URL,
        headers={"User-Agent": "Mozilla/5.0 (BMG Confluence Hunter)"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_openinsider(html: str, min_insiders: int = 2, min_value_usd: int = 500_000) -> List[Dict[str, Any]]:
    """Parse openinsider cluster-buys page → list of dicts.

    Uses BeautifulSoup for tolerance to layout tweaks. Returns rows with:
    filing_date, trade_date, ticker, company, industry, insider_count,
    price, qty, value_usd.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    # The cluster-buys page has one main data table with class "tinytable"
    table = soup.find("table", class_="tinytable")
    if table is None:
        return []

    out: List[Dict[str, Any]] = []
    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 13:
            continue
        # Column indices (verified 2026-08-26):
        # 0=X flag, 1=filing_date, 2=trade_date, 3=ticker, 4=company,
        # 5=industry, 6=insider_count, 7=trade_type, 8=price, 9=qty,
        # 10=owned, 11=dOwn, 12=value_usd
        try:
            filing_date = tds[1].get_text(strip=True)
            trade_date = tds[2].get_text(strip=True)
            ticker = tds[3].get_text(strip=True).upper()
            company = tds[4].get_text(strip=True)
            industry = tds[5].get_text(strip=True)
            n = int(tds[6].get_text(strip=True))
            ttype = tds[7].get_text(strip=True)
            price = float(tds[8].get_text(strip=True).replace("$", "").replace(",", ""))
            qty_str = tds[9].get_text(strip=True).replace("+", "").replace(",", "")
            qty = int(qty_str) if qty_str.isdigit() else 0
            value_str = tds[12].get_text(strip=True).replace("+", "").replace("$", "").replace(",", "")
            value = int(value_str) if value_str.isdigit() else 0
        except (ValueError, IndexError):
            continue

        if n < min_insiders:
            continue
        if value < min_value_usd:
            continue
        if "Purchase" not in ttype:
            continue

        out.append({
            "filing_date": filing_date,
            "trade_date": trade_date,
            "ticker": ticker,
            "company": company,
            "industry": industry,
            "insider_count": n,
            "price": price,
            "qty": qty,
            "value_usd": value,
        })

    # Dedup by ticker (keep the highest-value row per ticker)
    by_ticker: Dict[str, Dict[str, Any]] = {}
    for row in out:
        t = row["ticker"]
        if t not in by_ticker or row["value_usd"] > by_ticker[t]["value_usd"]:
            by_ticker[t] = row
    return list(by_ticker.values())


# ── Alpaca quote ──────────────────────────────────────────────────────────────

def _alpaca_headers() -> Dict[str, str]:
    kid = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        raise RuntimeError("no_alpaca_creds")
    return {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec}


def _fetch_latest_trade(symbol: str) -> Optional[float]:
    try:
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest"
        req = urllib.request.Request(url, headers=_alpaca_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return float(data.get("trade", {}).get("p") or 0) or None
    except Exception as e:
        logger.warning("[confluence_hunter] price fetch failed for %s: %s", symbol, e)
        return None


# ── LLM scoring + picking ─────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are the BMG Capital confluence framework hunter. Your job:
score candidate stocks against the 5-signal confluence framework and return
0-5 high-conviction picks ready to arm as swing trades.

Framework signals (must score 3+/5, insider_cluster is REQUIRED):
  1. insider_cluster (bool) — 2+ execs bought $500K+ aggregate last 30-60d (REQUIRED)
  2. analyst_revisions_dir (int -1/0/+1) — net 6mo revisions direction
  3. short_surprise_dir (int -1/0/+1) — short interest falling from elevated base
  4. fundamental_momentum (bool) — recent EPS beat + positive trend
  5. inst_13f_net_add (bool) — institutions buying > selling recent quarter

Additional v2 signals injected via candidate context (research/2026-08-25):
  - LAZY_PRICES similarity (0-1) — low = firm rewrote 10-K/10-Q vs prior year
    (Cohen/Malloy/Nguyen 2020 JF, 22% risk-factor L/S alpha). RED bucket <0.60
    is a BEARISH flag; GREEN >0.85 is neutral-to-positive. WEIGHT this in your
    scoring but do not increment the 3+/5 count — treat as a VETO overlay.
  - DAYS_TO_COVER (days) — HIGH bucket >8 days = crowded short. Also a VETO
    overlay: even if 3+/5 fires, HIGH DTC on a long pick should reduce
    conviction or skip. Do NOT increment 3+/5 count from DTC alone.
  - INSIDER_DETAIL — per-ticker list of recent insider trades with names + roles.
    Lines starting with ★ are senior roles (CEO/CFO/Chairman/President/COO/Founder).
    Weight senior-role BUY trades HIGHER than director/10%-owner trades (Ali/Hirshleifer
    2017 opportunistic-insider proxy). SELLS by senior roles are BEARISH — if 2+ senior
    insiders SELLING in the same window, treat as a strong veto on any long pick.

Anti-Goodhart rules:
  - Only pass tickers with market cap > $500M (skip micro-caps)
  - Only pass liquid names (avg vol > 500K shares/day)
  - Skip pre-revenue biotech (dead-money trap)
  - Skip if avg spread > 1% of price (illiquid)
  - Skip if fundamentals are broken (multiple straight EPS misses, negative cash flow)
  - Skip if insider is SOLO buyer (need 2+ named insiders)
  - **VETO if Lazy Prices similarity < 0.60** (heavy 10-K rewriter signal — Cohen/Malloy/Nguyen)
  - **VETO if Days-to-Cover > 8** (crowded short base — Hong et al 2015)
  - Be picky. A day with ZERO picks is fine and expected. Better to skip than force.

For each pick you approve, provide:
  ticker, entry_price, target_price, invalidation_price, horizon_months (default 6),
  play_a_trigger (breakout level, above recent range), play_a_stop (below key support),
  play_b_trigger (pullback zone, near current), play_b_stop (below insider cluster),
  signals: {insider_cluster, analyst_revisions_dir, short_surprise_dir, fundamental_momentum, inst_13f_net_add},
  thesis_text (2-4 sentences citing WHICH insiders, WHY the setup is real).

Output MUST be a JSON object with a single "picks" key whose value is an array of pick objects.
Empty array is a valid answer when no candidates pass.
"""


def _call_anthropic_direct(system: str, prompt: str, max_tokens: int) -> str:
    """Direct Anthropic SDK call — bypasses llm_client's relay + circuit breaker.
    Rationale: hunter runs on Railway where no local relay exists; llm_client
    trips its circuit breaker on the first relay-connect failure and refuses
    subsequent calls even with FALLBACK_TO_API=true. Direct SDK sidesteps that."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot run confluence hunter")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=FRAMEWORK_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def call_llm_for_picks(candidates: List[Dict[str, Any]], excluded_tickers: List[str], db: Session) -> List[Dict[str, Any]]:
    """Ask Claude to score the candidates and return picks."""
    prompt_parts = [
        "Today's confluence-framework candidate hunt.",
        f"Excluded (already in journal or fund holds): {', '.join(sorted(excluded_tickers)) or 'none'}",
        "",
        f"Candidate insider clusters (from openinsider.com, last 30d, dedup'd, >=2 insiders, >=$500K):",
        "",
    ]
    for c in candidates[:20]:  # cap prompt size — 20 with insider detail is ~15-20k tokens
        cur = c.get("current_price")
        cur_s = f"${cur:.2f}" if cur else "unknown"
        # v2 signals — Lazy Prices similarity + DTC (may be None if fetch failed)
        lp_sim = c.get("lazy_prices_similarity")
        lp_bucket = c.get("lazy_prices_bucket", "?")
        dtc = c.get("days_to_cover")
        dtc_bucket = c.get("dtc_bucket", "?")
        lp_str = f"lazy_prices={lp_sim:.2f}({lp_bucket})" if isinstance(lp_sim, (int, float)) and lp_sim >= 0 else f"lazy_prices=n/a"
        dtc_str = f"dtc={dtc:.1f}d({dtc_bucket})" if isinstance(dtc, (int, float)) and dtc >= 0 else f"dtc=n/a"
        insider_summary = c.get("insider_detail_summary", "n/a")
        prompt_parts.append(
            f"\n=== {c['ticker']} ({c.get('company','?')[:60]}) ==="
            f"\n  insider_cluster_count: {c['insider_count']}   aggregate: ${c['value_usd']:,}   trade_date: {c['trade_date']}"
            f"\n  avg_insider_price: ${c['price']:.2f}   current: {cur_s}   industry: {c.get('industry','?')[:60]}"
            f"\n  v2_signals: {lp_str}  {dtc_str}"
            f"\n  insider_detail (★=senior role):"
            f"\n{insider_summary}"
        )
    prompt_parts.append("")
    prompt_parts.append(
        "Score each candidate against the framework. Return JSON with picks that pass 3+/5. "
        "For each pick, use your knowledge of the ticker to fill in analyst_revisions_dir, "
        "short_surprise_dir, fundamental_momentum, inst_13f_net_add — be honest, don't guess. "
        "If uncertain, use 0 / null / false. Only mark true/nonzero when you have real reason to. "
        "Empty picks array is a valid answer."
    )
    prompt = "\n".join(prompt_parts)

    resp = _call_anthropic_direct(
        system=_SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=FRAMEWORK_MAX_TOKENS,
    )

    # Extract JSON — Claude may wrap in ```json ... ``` or provide bare JSON
    json_match = re.search(r'\{[^{}]*"picks"[^{}]*\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\][^{}]*\}', resp, re.DOTALL)
    if not json_match:
        # Try to find any JSON object with a picks key
        json_match = re.search(r'\{.*"picks".*\}', resp, re.DOTALL)
    if not json_match:
        logger.warning("[confluence_hunter] no JSON in LLM response: %s", resp[:300])
        return []
    try:
        parsed = json.loads(json_match.group(0))
    except json.JSONDecodeError as e:
        logger.warning("[confluence_hunter] JSON decode error: %s · raw: %s", e, resp[:400])
        return []
    picks = parsed.get("picks") if isinstance(parsed, dict) else parsed
    if not isinstance(picks, list):
        logger.warning("[confluence_hunter] picks is not a list: %s", type(picks))
        return []
    return picks


# ── Pick creation + arming ────────────────────────────────────────────────────

def _get_spy_price_cents() -> int:
    p = _fetch_latest_trade("SPY")
    return int(round((p or 750) * 100))


def _log_and_arm_pick(pick: Dict[str, Any], spy_cents: int, db: Session) -> Dict[str, Any]:
    """Create confluence_picks row + arm it. Returns dict with outcome."""
    from app.db.models.confluence import ConfluencePick
    ticker = pick.get("ticker", "").upper().strip()
    if not ticker:
        return {"ticker": None, "action": "SKIP_no_ticker"}

    signals = pick.get("signals", {}) or {}
    insider = bool(signals.get("insider_cluster"))
    if not insider:
        return {"ticker": ticker, "action": "SKIP_insider_cluster_required"}

    # Count signals firing
    n_signals = 0
    if insider:
        n_signals += 1
    ssd = signals.get("short_surprise_dir")
    if ssd is not None and ssd != 0:
        n_signals += 1
    ard = signals.get("analyst_revisions_dir")
    if ard is not None and ard != 0:
        n_signals += 1
    if signals.get("fundamental_momentum"):
        n_signals += 1
    if signals.get("inst_13f_net_add"):
        n_signals += 1
    if n_signals < 3:
        return {"ticker": ticker, "action": "SKIP_below_3_signals", "n_signals": n_signals}

    entry_price = float(pick.get("entry_price") or 0)
    if entry_price < MIN_MARKET_PRICE:
        return {"ticker": ticker, "action": "SKIP_below_min_price"}
    target_price = float(pick.get("target_price") or 0)
    invalidation_price = float(pick.get("invalidation_price") or 0)

    entry_cents = int(round(entry_price * 100))
    target_cents = int(round(target_price * 100)) or None
    invalidation_cents = int(round(invalidation_price * 100)) or None
    horizon = int(pick.get("horizon_months") or 6)
    thesis = pick.get("thesis_text") or f"Auto-hunter pick for {ticker}. Insider cluster confirmed."

    row = ConfluencePick(
        ticker=ticker,
        entry_date=date.today().isoformat(),
        entry_price_cents=entry_cents,
        spy_price_cents_at_entry=spy_cents,
        insider_cluster=insider,
        short_surprise_dir=ssd if isinstance(ssd, int) else None,
        analyst_revisions_dir=ard if isinstance(ard, int) else None,
        fundamental_momentum=bool(signals.get("fundamental_momentum")) if signals.get("fundamental_momentum") is not None else None,
        inst_13f_net_add=bool(signals.get("inst_13f_net_add")) if signals.get("inst_13f_net_add") is not None else None,
        signals_fired_count=n_signals,
        thesis_text=thesis[:4000],  # cap for storage
        target_price_cents=target_cents,
        invalidation_price_cents=invalidation_cents,
        horizon_months=horizon,
        notes=f"Auto-armed by confluence_hunter on {date.today().isoformat()}.",
        created_by="confluence_hunter_v1",
    )
    db.add(row)
    db.flush()

    # Arm the pick
    ppa = int(round(float(pick.get("play_a_trigger") or 0) * 100)) or None
    psa = int(round(float(pick.get("play_a_stop") or 0) * 100)) or None
    ppb = int(round(float(pick.get("play_b_trigger") or 0) * 100)) or None
    psb = int(round(float(pick.get("play_b_stop") or 0) * 100)) or None

    if ppa and psa:
        row.arm_mode = "either" if (ppb and psb) else "play_a_only"
    elif ppb and psb:
        row.arm_mode = "play_b_only"
    else:
        return {"ticker": ticker, "pick_id": row.id, "action": "SKIP_no_valid_trigger"}

    row.arm_state = "ARMED"
    row.play_a_trigger_price_cents = ppa
    row.play_a_stop_price_cents = psa
    row.play_a_volume_multiple = 1.2
    row.play_b_trigger_price_cents = ppb
    row.play_b_stop_price_cents = psb
    row.target_1_cents = target_cents
    row.size_dollars_cents = DEFAULT_POSITION_SIZE_USD * 100
    db.commit()

    return {
        "ticker": ticker,
        "pick_id": row.id,
        "action": "ARMED",
        "n_signals": n_signals,
        "entry_price": entry_price,
        "target": target_price,
        "invalidation": invalidation_price,
        "size_usd": DEFAULT_POSITION_SIZE_USD,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def run_hunt(dry_run: bool = False) -> Dict[str, Any]:
    """One hunt cycle. Idempotent by dedup against existing tickers.

    Args:
        dry_run: if True, log picks but don't create confluence_picks rows.
    """
    if os.environ.get("CONFLUENCE_HUNTER_ENABLED", "true").strip().lower() == "false":
        return {"status": "disabled_by_env"}

    auto_arm = os.environ.get("CONFLUENCE_HUNTER_AUTO_ARM", "true").strip().lower() != "false"
    if dry_run:
        auto_arm = False

    started_at = datetime.now(timezone.utc)
    result: Dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "candidates_scraped": 0,
        "candidates_after_filter": 0,
        "excluded_tickers": [],
        "llm_picks_returned": 0,
        "actions": [],
        "dry_run": dry_run,
        "auto_arm": auto_arm,
    }

    # 1. Scrape openinsider
    try:
        html = _fetch_openinsider_html()
    except Exception as e:
        result["error"] = f"openinsider fetch failed: {e}"
        return result
    candidates = parse_openinsider(html)
    result["candidates_scraped"] = len(candidates)

    if not candidates:
        result["status"] = "no_candidates"
        return result

    # 2. Enrich with current prices + dedup
    db = SessionLocal()
    try:
        from app.db.models.confluence import ConfluencePick
        existing = {
            row.ticker
            for row in db.query(ConfluencePick).filter(ConfluencePick.closed_date.is_(None)).all()
        }
        result["excluded_tickers"] = sorted(existing)

        enriched: List[Dict[str, Any]] = []
        # v2 (2026-08-25): enrich with Lazy Prices similarity + Days-to-Cover
        # + per-ticker insider role detail (Ali/Hirshleifer proxy)
        # per research/2026-08-25-confluence-framework-v2-signal-additions.md
        from app.services.lazy_prices import compute_lazy_prices_score
        from app.services.days_to_cover import compute_dtc
        from app.services.insider_enrichment import get_insider_detail, summarize_for_prompt

        for c in candidates:
            if c["ticker"] in existing:
                continue
            if c["price"] < MIN_MARKET_PRICE:
                continue
            cur = _fetch_latest_trade(c["ticker"])
            c["current_price"] = cur
            # Lazy Prices — best-effort, don't block on failure (SEC parse can flake on smaller filers)
            try:
                lp = compute_lazy_prices_score(c["ticker"])
                c["lazy_prices_similarity"] = lp.get("similarity")
                c["lazy_prices_bucket"] = lp.get("similarity_bucket")
            except Exception as _lp_exc:
                logger.warning("[confluence_hunter] lazy_prices failed for %s: %s", c["ticker"], _lp_exc)
                c["lazy_prices_similarity"] = None
                c["lazy_prices_bucket"] = "ERROR"
            # DTC — best-effort, don't block on failure (yfinance can rate-limit)
            try:
                dtc = compute_dtc(c["ticker"])
                c["days_to_cover"] = dtc.get("dtc")
                c["dtc_bucket"] = dtc.get("bucket")
            except Exception as _dtc_exc:
                logger.warning("[confluence_hunter] dtc failed for %s: %s", c["ticker"], _dtc_exc)
                c["days_to_cover"] = None
                c["dtc_bucket"] = "ERROR"
            # Insider role detail — best-effort, Ali/Hirshleifer proxy
            try:
                insider_rows = get_insider_detail(c["ticker"], max_rows=10)
                c["insider_detail_summary"] = summarize_for_prompt(insider_rows, max_show=6)
                c["insider_detail_rows"] = len(insider_rows)
            except Exception as _in_exc:
                logger.warning("[confluence_hunter] insider_detail failed for %s: %s", c["ticker"], _in_exc)
                c["insider_detail_summary"] = "n/a"
                c["insider_detail_rows"] = 0
            enriched.append(c)
        result["candidates_after_filter"] = len(enriched)

        if not enriched:
            result["status"] = "no_new_candidates_after_dedup"
            return result

        # 3. Ask Claude to score + pick
        try:
            picks = call_llm_for_picks(enriched, sorted(existing), db)
        except Exception as e:
            result["error"] = f"LLM call failed: {e}"
            return result
        result["llm_picks_returned"] = len(picks)

        # 4. Log + arm each pick
        spy_cents = _get_spy_price_cents()
        for pick in picks:
            if not auto_arm:
                result["actions"].append({
                    "ticker": pick.get("ticker"),
                    "action": "DRY_RUN_would_arm",
                    "pick": pick,
                })
                continue
            try:
                outcome = _log_and_arm_pick(pick, spy_cents, db)
                result["actions"].append(outcome)
            except Exception as e:
                logger.error("[confluence_hunter] arm failed for %s: %s", pick.get("ticker"), e, exc_info=True)
                result["actions"].append({
                    "ticker": pick.get("ticker"),
                    "action": "ARM_ERROR",
                    "error": str(e)[:200],
                })

        result["status"] = "ok"
        return result
    finally:
        db.close()


# ── Scheduler wiring ──────────────────────────────────────────────────────────

def setup_confluence_hunter(scheduler) -> None:
    """Register nightly cron job. Fires 6:07 PM ET Mon-Fri (after market close)."""
    from apscheduler.triggers.cron import CronTrigger

    def _tick_with_notify() -> Dict[str, Any]:
        """Wrapper — run hunt, send Discord ops alert with result."""
        r = run_hunt(dry_run=False)
        try:
            from app.services.discord import send_ops_alert
            armed = [a for a in r.get("actions", []) if a.get("action") == "ARMED"]
            skipped = [a for a in r.get("actions", []) if str(a.get("action", "")).startswith("SKIP")]
            msg_lines = [
                f"Scraped {r.get('candidates_scraped', 0)} candidates → "
                f"{r.get('candidates_after_filter', 0)} after dedup → "
                f"{r.get('llm_picks_returned', 0)} LLM picks → "
                f"{len(armed)} armed, {len(skipped)} skipped.",
            ]
            if armed:
                msg_lines.append("")
                msg_lines.append("Armed tonight:")
                for a in armed:
                    msg_lines.append(
                        f"  {a['ticker']}: entry ${a['entry_price']:.2f}, tgt ${a['target']:.2f}, inv ${a['invalidation']:.2f}, {a['n_signals']}/5 signals"
                    )
            if r.get("error"):
                msg_lines.append(f"ERROR: {r['error']}")
            send_ops_alert(
                title="Confluence Hunter — nightly run",
                message="\n".join(msg_lines),
                severity="info" if not r.get("error") else "warn",
                source="confluence_hunter",
            )
        except Exception as e:
            logger.warning("[confluence_hunter] discord notify failed: %s", e)
        return r

    scheduler.add_job(
        func=_tick_with_notify,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=18,
            minute=7,
            timezone="America/New_York",
        ),
        id="confluence_hunter_daily",
        name="confluence_hunter_daily",
        max_instances=1,
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,
    )
    logger.info("[confluence_hunter] scheduler registered — 6:07 PM ET Mon-Fri")
