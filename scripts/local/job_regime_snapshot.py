"""Daily regime snapshot — writes current market regime state to Obsidian.

Pulls all 3 regime detectors from trend_gate service and writes a compact
snapshot to the vault. Runs daily via launchd. Purpose: whenever you're
about to arm a pick (or manually evaluate one), you can just glance at the
snapshot to know what regime we're in without running any commands.

Also emits a one-line "what to do today" recommendation based on the
combined regime state.

Zero Railway cost — uses Yahoo Finance for all ETF pricing.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _obsidian import write_job_output  # noqa: E402


def _yahoo_closes(symbol: str, days_back: int = 200) -> Optional[list]:
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        r = data.get("chart", {}).get("result", [])
        if not r:
            return None
        return [c for c in r[0].get("indicators", {}).get("quote", [{}])[0].get("close", []) if c is not None]
    except Exception:
        return None


def _return_over(closes: list, days: int) -> Optional[float]:
    if not closes or len(closes) < days + 1:
        return None
    return (closes[-1] - closes[-days]) / closes[-days] * 100


def run() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Fetch all regime ETFs in parallel-ish (sequential but fast) ──
    print("Fetching regime ETFs...")
    spy = _yahoo_closes("SPY", 400)      # for SPY 200-SMA (need calendar → trading days buffer)
    iwm = _yahoo_closes("IWM", 200)      # small-cap
    iwf = _yahoo_closes("IWF", 200)      # large-cap growth
    iwd = _yahoo_closes("IWD", 200)      # large-cap value
    mtum = _yahoo_closes("MTUM", 150)    # momentum factor
    vlue = _yahoo_closes("VLUE", 150)    # value factor
    vix = _yahoo_closes("^VIX", 30)      # volatility

    # ── Compute regime signals ──
    # 1. Faber SMA gate: SPY above 10mo (200-day) SMA?
    faber_status = "UNKNOWN"
    if spy and len(spy) >= 200:
        sma200 = sum(spy[-200:]) / 200
        current = spy[-1]
        faber_status = "RISK-ON" if current > sma200 else "RISK-OFF"
        faber_detail = f"SPY ${current:.2f} vs 200-SMA ${sma200:.2f} ({(current/sma200-1)*100:+.1f}%)"
    else:
        faber_detail = "insufficient data"

    # 2. Growth vs Value regime (IWF vs IWD 6mo)
    gv_status = "UNKNOWN"
    gv_detail = "insufficient data"
    if iwf and iwd:
        lookback = min(120, len(iwf) - 1, len(iwd) - 1)
        iwf_ret = _return_over(iwf, lookback)
        iwd_ret = _return_over(iwd, lookback)
        if iwf_ret is not None and iwd_ret is not None:
            spread = iwf_ret - iwd_ret
            if spread > 5:
                gv_status = "GROWTH_DOMINANT"
            elif spread < -5:
                gv_status = "VALUE_DOMINANT"
            else:
                gv_status = "NEUTRAL"
            gv_detail = f"Growth (IWF) {iwf_ret:+.1f}% vs Value (IWD) {iwd_ret:+.1f}% = {spread:+.1f}% spread"

    # 3. Momentum vs Mean-Reversion regime (MTUM vs VLUE 3mo)
    mmr_status = "UNKNOWN"
    mmr_detail = "insufficient data"
    if mtum and vlue:
        lookback = min(60, len(mtum) - 1, len(vlue) - 1)
        mtum_ret = _return_over(mtum, lookback)
        vlue_ret = _return_over(vlue, lookback)
        if mtum_ret is not None and vlue_ret is not None:
            spread = mtum_ret - vlue_ret
            if spread > 3:
                mmr_status = "TREND_FOLLOWING"
            elif spread < -3:
                mmr_status = "MEAN_REVERSION"
            else:
                mmr_status = "NEUTRAL"
            mmr_detail = f"Momentum (MTUM) {mtum_ret:+.1f}% vs Value (VLUE) {vlue_ret:+.1f}% = {spread:+.1f}% spread"

    # 4. VIX regime
    vix_status = "UNKNOWN"
    vix_detail = "insufficient data"
    if vix and len(vix) > 0:
        current_vix = vix[-1]
        if current_vix < 15:
            vix_status = "LOW_VOL"
        elif current_vix < 25:
            vix_status = "NORMAL_VOL"
        elif current_vix < 35:
            vix_status = "ELEVATED_VOL"
        else:
            vix_status = "HIGH_VOL"
        vix_detail = f"VIX = {current_vix:.1f}"

    # 5. Large vs Small cap (SPY vs IWM 3mo)
    ls_status = "UNKNOWN"
    ls_detail = "insufficient data"
    if spy and iwm:
        spy_3mo = _return_over(spy, 60)
        iwm_3mo = _return_over(iwm, 60)
        if spy_3mo is not None and iwm_3mo is not None:
            spread = spy_3mo - iwm_3mo
            if spread > 3:
                ls_status = "LARGE_LEADING"
            elif spread < -3:
                ls_status = "SMALL_LEADING"
            else:
                ls_status = "NEUTRAL"
            ls_detail = f"Large (SPY) {spy_3mo:+.1f}% vs Small (IWM) {iwm_3mo:+.1f}% = {spread:+.1f}% spread"

    # ── Compose the "what to do today" recommendation ──
    recommendations = []
    if faber_status == "RISK-OFF":
        recommendations.append("⚠️ Faber gate: RISK-OFF — halve position sizes on new long picks")
    if mmr_status == "MEAN_REVERSION":
        recommendations.append("⚠️ Mean-reversion regime: DISABLE sector momentum gate (kills winners)")
        recommendations.append("→ Value picks favored; beaten-down names likely to rebound")
    elif mmr_status == "TREND_FOLLOWING":
        recommendations.append("✓ Trend-following regime: ENABLE sector momentum filter")
        recommendations.append("→ Momentum picks favored; avoid catching falling knives")
    if vix_status in ("ELEVATED_VOL", "HIGH_VOL"):
        recommendations.append(f"⚠️ VIX elevated ({vix_status}): reduce position sizes 20-30%")
    if gv_status == "GROWTH_DOMINANT":
        recommendations.append("→ Growth regime: reduce sizing on value-tilt picks")
    elif gv_status == "VALUE_DOMINANT":
        recommendations.append("→ Value regime: framework value-tilt is well-positioned")
    if ls_status == "SMALL_LEADING":
        recommendations.append("→ Small-caps leading: your mid/small-cap picks favored")

    if not recommendations:
        recommendations.append("✓ Neutral regime across all dimensions — trade normally")

    # ── Render ──
    lines = [
        f"# Market Regime Snapshot — {today}",
        "",
        f"*Generated: {datetime.now(timezone.utc).isoformat()}*",
        "",
        "## Quick Status",
        "",
        f"- **Faber SPY Trend:** `{faber_status}`",
        f"- **Growth vs Value (6mo):** `{gv_status}`",
        f"- **Momentum vs Mean-Reversion (3mo):** `{mmr_status}`",
        f"- **Large vs Small Cap (3mo):** `{ls_status}`",
        f"- **VIX Regime:** `{vix_status}`",
        "",
        "## What to do today",
        "",
    ]
    for rec in recommendations:
        lines.append(f"- {rec}")

    lines.extend([
        "",
        "## Detail",
        "",
        f"**Faber (200-day SMA on SPY):** {faber_detail}",
        f"**Growth/Value:** {gv_detail}",
        f"**Momentum/Mean-Reversion:** {mmr_detail}",
        f"**Large/Small:** {ls_detail}",
        f"**VIX:** {vix_detail}",
        "",
        "## How to use this",
        "",
        "Before arming any confluence pick or making a manual trade:",
        "1. Check `Faber SPY Trend` — if RISK-OFF, cut position sizes 50%",
        "2. Check `Momentum vs Mean-Reversion` — if MEAN_REVERSION, don't trust sector momentum",
        "3. Check `VIX` — if ELEVATED, reduce size further",
        "4. The framework's trend gates handle SPY-level regime automatically. This snapshot",
        "   is for MANUAL decisions and higher-level portfolio adjustments.",
        "",
        "*Companion note: `research/2026-08-30-confluence-framework-backtest-analysis.md`*",
    ])

    body = "\n".join(lines)
    path = write_job_output("regime_snapshot", body)
    return f"wrote {path} | regime: faber={faber_status} mmr={mmr_status} vix={vix_status}"


if __name__ == "__main__":
    print(run())
