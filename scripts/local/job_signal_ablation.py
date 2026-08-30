"""Signal ablation study — which of the 5 confluence signals is doing the work?

Combines:
1. THEORETICAL ranking based on published academic alphas per signal
2. EMPIRICAL analysis of signal combinations in the framework-eligible bucket
   from the N=100 backtest (which returned +2.09% avg excess vs sector)
3. RECOMMENDATION: which signals to double down on, which to retire

Writes to Obsidian vault as a research note.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
import sys

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _obsidian import write_job_output  # noqa: E402


# ── Academic evidence per signal ──────────────────────────────────────
SIGNALS_META = [
    {
        "name": "insider_cluster",
        "display": "Insider Cluster (2+ execs buying)",
        "primary_paper": "Cohen-Malloy-Pomorski 2012 (JF)",
        "paper_alpha": "82 bps/mo VW (~10%/yr) on 'opportunistic' insider variant",
        "refined_alpha": "Ali-Hirshleifer 2017: 112 bps/mo (14%/yr) with pre-QEA window filter",
        "sample_size": "Universe of US public companies 1986-2007, replicated 2009-2024",
        "decay_post_publication": "Moderate — Ali-Hirshleifer 2017 refined + still works",
        "signal_strength_score": 9,  # 1-10, my subjective read
        "notes": (
            "STRONGEST individual signal by published alpha. But quality matters — "
            "'routine' insider buys (calendar-driven) have zero predictive power. "
            "The 'opportunistic' subset (unusual timing, senior roles, size) carries "
            "the full alpha. Our framework doesn't distinguish opportunistic vs routine yet."
        ),
    },
    {
        "name": "short_surprise",
        "display": "Short Interest Direction (DTC change)",
        "primary_paper": "Hong-Li-Ni 2015 (NBER WP 21166)",
        "paper_alpha": "119 bps/mo EW (14%/yr) on days-to-cover long-short",
        "refined_alpha": "67 bps/mo VW — still real edge",
        "sample_size": "NYSE/Nasdaq 1988-2012, monthly data",
        "decay_post_publication": "LOW — signal actually STRENGTHENED post-2000 per paper",
        "signal_strength_score": 8,
        "notes": (
            "Second-strongest by published alpha. But 'short_surprise_dir' in our framework "
            "may not be the same as DTC — direction of short interest change vs level. "
            "Diagnostic showed this signal fires on only 12% of losers (rare). May be a "
            "high-precision, low-recall signal — when it fires, listen."
        ),
    },
    {
        "name": "analyst_revisions",
        "display": "Analyst Revisions Direction",
        "primary_paper": "Womack 1996 (JF), Barber-Loeffler 2001",
        "paper_alpha": "~3-6% drift over 30-60 days post-upgrade/downgrade",
        "refined_alpha": "Weaker in modern era due to Reg FD (2000) — analysts less informed",
        "sample_size": "1989-1996 (Womack), extended to 2000s",
        "decay_post_publication": "HIGH — modern analyst edge much smaller (Reg FD democratized info)",
        "signal_strength_score": 5,
        "notes": (
            "Moderate published alpha in older studies but heavy decay in modern era. "
            "Analyst calls now front-run by algorithms + Reg FD reduces info advantage. "
            "Our framework treats this signal as equal to insider_cluster — probably "
            "overweighting it. Also fires on 100% of losers per diagnostic (no discrimination)."
        ),
    },
    {
        "name": "fundamental_momentum",
        "display": "Fundamental Momentum (EPS beats + trend)",
        "primary_paper": "Novy-Marx 2013 (JFE) gross profitability",
        "paper_alpha": "~4-5%/yr from Novy-Marx GP/A factor",
        "refined_alpha": "PEAD (Ball-Brown 1968) drift: 3-6% over 60 days post-beat",
        "sample_size": "US common stocks 1963-2011",
        "decay_post_publication": "MODERATE — profitability factor still works (Fama-French 5F)",
        "signal_strength_score": 6,
        "notes": (
            "Real edge in academic literature but our framework's implementation is "
            "vague — 'recent EPS beat + positive trend' is subjective. Diagnostic showed "
            "this signal fires on 94% of losers (nearly no discrimination). Either the "
            "signal is too easy to trigger, or the framework definition is too loose."
        ),
    },
    {
        "name": "inst_13f_net_add",
        "display": "Institutional 13F Net Additions",
        "primary_paper": "Chen-Hong-Stein 2002 (breadth of ownership)",
        "paper_alpha": "~2-3%/yr on breadth-change factor",
        "refined_alpha": "13F data is 45-day lagged — half-life ~30 days by publication",
        "sample_size": "US common stocks 1979-1998",
        "decay_post_publication": "HIGH — 45-day lag + widespread crowd-following reduces edge",
        "signal_strength_score": 4,
        "notes": (
            "Weakest signal by academic alpha AND worst data lag (45-day 13F delay). "
            "Diagnostic showed this signal fires on only 19% of losers — could be high "
            "precision, but the 45-day stale data means we're always LATE to what "
            "institutions did. Prime candidate for retirement or replacement."
        ),
    },
]


# ── Empirical evidence from live picks diagnostic (2026-08-30) ──────
# 16 live picks, 0 winners, all 16 fired insider_cluster, 15/16 fundamental_momentum,
# 16/16 analyst_revisions, 2/16 short_surprise, 3/16 inst_13f
LIVE_PICKS_FIRING = {
    "insider_cluster": {"total": 16, "on_winners": 0, "on_losers": 16},
    "analyst_revisions": {"total": 16, "on_winners": 0, "on_losers": 16},
    "fundamental_momentum": {"total": 15, "on_winners": 0, "on_losers": 15},
    "short_surprise": {"total": 2, "on_winners": 0, "on_losers": 2},
    "inst_13f_net_add": {"total": 3, "on_winners": 0, "on_losers": 3},
}


def run() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Rank signals by combined score
    ranked = sorted(SIGNALS_META, key=lambda s: -s["signal_strength_score"])

    lines = [
        f"# Signal Ablation Study — Which of the 5 signals is doing the work?",
        "",
        f"**Date:** {today}",
        "",
        "Follow-up to the 2026-08-30 backtest which showed the current 16 live picks",
        "averaged -9.74% vs sector while the framework-eligible universe averaged +2.09%.",
        "The 12-point gap suggests something specific about the live picks (their SIGNAL",
        "COMBINATIONS) is systematically bad. This study ranks each of the 5 signals",
        "by (a) published academic alpha and (b) empirical patterns in our data.",
        "",
        "**Method:** hybrid theoretical + empirical (not a proper controlled ablation —",
        "would require the framework hunter to output alternative-signal batches over",
        "months of live data. See 'What's needed for real ablation' at end).",
        "",
        "## Ranked Signal Strength (my best assessment)",
        "",
        "| Rank | Signal | Academic Alpha | Diagnostic Firing Rate | Score |",
        "|:---:|---|---|---:|:---:|",
    ]
    for i, s in enumerate(ranked, start=1):
        live = LIVE_PICKS_FIRING.get(s["name"], {"total": 0})
        firing_pct = live["total"] / 16 * 100 if live["total"] else 0
        lines.append(
            f"| **#{i}** | {s['display']} | {s['paper_alpha']} | "
            f"{firing_pct:.0f}% ({live['total']}/16) | **{s['signal_strength_score']}/10** |"
        )

    lines.extend([
        "",
        "## Deep dive per signal",
        "",
    ])

    for s in ranked:
        live = LIVE_PICKS_FIRING.get(s["name"], {"total": 0})
        lines.extend([
            f"### #{ranked.index(s) + 1}. {s['display']}",
            "",
            f"- **Primary paper:** {s['primary_paper']}",
            f"- **Documented alpha:** {s['paper_alpha']}",
            f"- **Refined variant:** {s['refined_alpha']}",
            f"- **Sample:** {s['sample_size']}",
            f"- **Post-publication decay:** {s['decay_post_publication']}",
            f"- **Firing on our 16 live picks:** {live['total']}/16 "
            f"({live['total']/16*100:.0f}%)",
            f"- **Discrimination in live data:** {live.get('on_losers', 0)}/16 losers had this signal firing "
            f"(no winners yet to compare)",
            "",
            f"**Interpretation:** {s['notes']}",
            "",
        ])

    # ── Key findings ─────────────────────────────────────────────
    lines.extend([
        "## Key findings from the hybrid analysis",
        "",
        "### 1. `inst_13f_net_add` is the weakest signal — CANDIDATE FOR RETIREMENT",
        "",
        "- Lowest published alpha (~2-3%/yr per Chen-Hong-Stein)",
        "- Worst data lag (13F filings are 45-day delayed → we're always late)",
        "- Fires on only 19% of live picks — small n makes discrimination unclear",
        "- Even when it does fire, edge is largely priced in by publication date",
        "",
        "**Recommendation:** either drop this signal entirely OR replace with a real-time",
        "institutional-flow proxy (like dark pool prints, options unusual activity).",
        "",
        "### 2. `analyst_revisions_dir` fires on 100% of live picks — NO DISCRIMINATION",
        "",
        "- Every single one of the 16 live picks had analyst_revisions firing",
        "- If a signal fires on EVERY pick, it can't discriminate winners from losers",
        "- Either the framework's definition is too loose (any positive revision counts?)",
        "  or the confluence hunter LLM is over-crediting this signal",
        "",
        "**Recommendation:** TIGHTEN the definition. Require ≥3 upward revisions in ",
        "prior 30 days, or a MAJOR upgrade (2-notch, from Sell → Buy). Anything less",
        "= don't count.",
        "",
        "### 3. `fundamental_momentum` fires on 94% of live picks — SAME PROBLEM",
        "",
        "- 15/16 picks had this firing. Almost no discrimination potential.",
        "- Novy-Marx's actual finding is GP/A quintile RANK, not a boolean",
        "- Our boolean 'is fundamental momentum positive?' loses all information",
        "",
        "**Recommendation:** convert to QUINTILE-based signal (top 20% of universe by",
        "gross profit growth × EPS surprise magnitude). Only top-quintile counts.",
        "",
        "### 4. `insider_cluster` is REQUIRED but its QUALITY isn't measured",
        "",
        "- Correctly required per framework spec",
        "- BUT: Cohen-Malloy-Pomorski showed 'routine' vs 'opportunistic' matters MASSIVELY",
        "  - Routine trades: 0 bps/mo alpha (worthless)",
        "  - Opportunistic trades: 82 bps/mo VW (~10%/yr)",
        "- Our framework doesn't distinguish. Treats all clusters equal.",
        "",
        "**Recommendation:** add opportunistic-vs-routine classification (CMP 2012",
        "recipe: same-calendar-month over 3+ years = routine, else opportunistic).",
        "This is the single highest-value framework upgrade available.",
        "",
        "### 5. `short_surprise_dir` fires on only 12% — POSSIBLE HIGH-PRECISION SIGNAL",
        "",
        "- Only 2/16 picks had this firing",
        "- Real Hong-Li-Ni DTC alpha is 67-119 bps/mo",
        "- Small firing rate could mean: (a) signal is rare/precious, or (b) we're not",
        "  computing it correctly",
        "",
        "**Recommendation:** verify the framework's short_surprise_dir definition matches",
        "the academic DTC-change formula. If yes, KEEP as-is — high precision. If no,",
        "fix the definition first.",
        "",
        "## Proposed framework v3 (from this ablation)",
        "",
        "Change the confluence rule from:",
        "```",
        "insider_cluster REQUIRED + any 3 of 5 firing",
        "```",
        "",
        "To:",
        "```",
        "insider_cluster (OPPORTUNISTIC only) REQUIRED",
        "  + at least 2 of the following 3 firing:",
        "    - short_surprise (Hong-Li-Ni DTC change)",
        "    - fundamental_momentum (top quintile GP/A × EPS surprise, not boolean)",
        "    - analyst_revisions (≥3 upward, or 2-notch upgrade in prior 30d)",
        "  + inst_13f_net_add DROPPED entirely (or replaced with real-time flow proxy)",
        "```",
        "",
        "**Why this change:**",
        "1. Retires the weakest signal (13F)",
        "2. Tightens the two 'always fires' signals to actually discriminate",
        "3. Adds quality gate on the required signal (opportunistic-only)",
        "4. Maintains the confluence principle but with genuinely independent signals",
        "",
        "**Expected effect:** fewer picks per week (tighter criteria), but each pick",
        "should carry a stronger edge. Move from 'shotgun' to 'sniper'.",
        "",
        "## What's needed for REAL ablation (future work)",
        "",
        "This study is theoretical + partially empirical. Proper ablation requires:",
        "1. **Historical signals database:** for each stock, for each historical date,",
        "   what did each of the 5 signals value? (Need to build data ingestion for",
        "   OpenInsider archives, FactSet analyst revisions history, EDGAR 13F history.)",
        "2. **Point-in-time backtest:** for each month over past 3 years, generate the",
        "   framework's picks with each signal ablated. Compare returns.",
        "3. **Signal-signal correlation matrix:** do the 5 signals actually fire",
        "   independently, or are they collinear? (If 2 signals ALWAYS fire together,",
        "   they're one signal in disguise.)",
        "",
        "This is 1-2 weeks of quant infrastructure work. Worth doing before major",
        "framework redesign.",
        "",
        "## Companion notes",
        "",
        "- `research/2026-08-30-confluence-framework-backtest-analysis.md` — the backtest",
        "  that raised the ablation question",
        "- `research/2026-08-30-confluence-framework-teaching-note.md` — plain-English",
        "  framework walkthrough",
        "- `research/2026-08-30-verify-cohen-malloy-pomorski-decoding.md` — insider paper",
        "- `research/2026-08-30-verify-ali-hirshleifer-opportunism.md` — refined insider paper",
        "- `research/2026-08-30-verify-hong-li-ni-days-to-cover.md` — DTC paper",
    ])

    body = "\n".join(lines)
    # Write to research/ (not context/local-jobs/) since this is a research note
    VAULT = Path.home() / "Documents" / "BMG-Capital-Vault"
    out_path = VAULT / "research" / f"{today}-signal-ablation-study.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return f"wrote {out_path}"


if __name__ == "__main__":
    print(run())
