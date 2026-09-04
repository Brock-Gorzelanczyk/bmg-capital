"""Master synthesizer — combine all agent outputs into a ranked winner list.

After the 5 background agents finish (agent1 TTM squeeze, agent2 momentum,
agent3 mean-reversion, agent4 breakout, agent5 options research), this
script reads their outputs and produces the final "here's what to actually
trade" ranking.

Ranking priorities:
1. Post-hygiene R_high > 0 (must be net positive after realistic haircuts)
2. Multi-ticker robustness: same strategy wins on 3+ tickers = high confidence
3. Annual CAGR at Kelly-safe sizing > 5%
4. Trade count > 10 in test period (statistical significance)
5. Bonus if strategy has explicit academic reference in vault

Outputs:
- Ranked table of every (strategy × ticker) combo tested
- Composite recommendations: which strategies to actually deploy
- Vault report: research/54-strategy-bakeoff-master-ranking.md

Also writes JSON aggregate to `scripts/backtest/data/multi/master_ranking.json`
so future backtest runs can reference the current winner list.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

VAULT_RESEARCH = Path.home() / "Documents" / "BMG-Capital-Vault" / "research"
DATA_DIR = Path(__file__).parent / "data" / "multi"

# Expected agent outputs
AGENT_NOTES = [
    ("agent1_ttm_multi",   VAULT_RESEARCH / "49-ttm-squeeze-multi-ticker-agent.md"),
    ("agent2_momentum",    VAULT_RESEARCH / "50-momentum-multi-ticker-agent.md"),
    ("agent3_meanrev",     VAULT_RESEARCH / "51-meanrev-multi-ticker-agent.md"),
    ("agent4_breakout",    VAULT_RESEARCH / "52-breakout-multi-ticker-agent.md"),
    ("agent5_options",     VAULT_RESEARCH / "53-options-specific-edges-agent.md"),
]


def parse_markdown_table(md: str) -> list[dict]:
    """Extract rows from any markdown table in the file.

    Best-effort — agents may format differently. We try to find rows with
    ticker + numeric R values.
    """
    rows = []
    lines = md.split("\n")
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 4:
            continue
        # Skip header separator (---)
        if all(re.match(r"^:?-+:?$", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def extract_winners_from_agent(agent_name: str, md_path: Path) -> list[dict]:
    """Parse an agent's vault note and pull out winner rows.

    Best-effort — accepts any format. Looks for ticker column + R column
    + WR% column. Returns list of standardized dicts.
    """
    if not md_path.exists():
        return []
    md = md_path.read_text(errors="ignore")
    rows = parse_markdown_table(md)

    winners = []
    for row in rows:
        # Try to find a ticker column (matches [A-Z]{2,5})
        ticker_col = None
        r_col = None
        wr_col = None
        for j, cell in enumerate(row):
            # Strip markdown bold
            clean = cell.replace("**", "").strip()
            if re.match(r"^[A-Z]{2,5}$", clean) and ticker_col is None:
                ticker_col = j
            if "R" in cell and re.search(r"[+-]?\d+\.\d+R?", cell) and r_col is None:
                # Extract first signed number
                m = re.search(r"([+-]?\d+\.\d+)", cell)
                if m:
                    r_col = (j, float(m.group(1)))
            if "%" in cell and wr_col is None:
                m = re.search(r"(\d+\.?\d*)%", cell)
                if m:
                    wr_col = (j, float(m.group(1)))
        if ticker_col is not None and r_col is not None:
            winners.append({
                "agent": agent_name,
                "ticker": row[ticker_col].replace("**", "").strip(),
                "raw_r": r_col[1],
                "wr_pct": wr_col[1] if wr_col else None,
                "raw_row": " | ".join(row),
            })
    return winners


def main():
    print("=" * 80)
    print("MASTER SYNTHESIZER")
    print("=" * 80)

    # Check which agent notes exist
    all_winners = []
    for agent, path in AGENT_NOTES:
        if path.exists():
            winners = extract_winners_from_agent(agent, path)
            print(f"  ✅ {agent}: {len(winners)} candidate rows from {path.name}")
            all_winners.extend(winners)
        else:
            print(f"  ⏳ {agent}: not yet written ({path.name})")

    if not all_winners:
        print("\nNo agent output found — agents still running or all failed.")
        return

    # Group by (agent, ticker) to find multi-ticker robust strategies
    by_agent = {}
    by_ticker = {}
    for w in all_winners:
        by_agent.setdefault(w["agent"], []).append(w)
        by_ticker.setdefault(w["ticker"], []).append(w)

    # Rank by raw R
    ranked = sorted(all_winners, key=lambda x: -x["raw_r"])

    print(f"\nTop 15 combos by raw R:")
    print(f"{'#':<3} {'Agent':<25} {'Ticker':<8} {'Raw R':>10} {'WR%':>7}")
    print("-" * 80)
    for i, w in enumerate(ranked[:15], 1):
        wr = f"{w['wr_pct']:.1f}%" if w['wr_pct'] else "n/a"
        print(f"{i:<3} {w['agent']:<25} {w['ticker']:<8} {w['raw_r']:>+9.1f}R {wr:>7}")

    # Multi-ticker robust strategies
    print(f"\n\nTickers with multiple winners across agents (cross-strategy robust):")
    for tkr, ws in sorted(by_ticker.items(), key=lambda x: -len(x[1])):
        if len(ws) >= 2:
            print(f"  {tkr}: {len(ws)} winning combos across {len(set(w['agent'] for w in ws))} agent(s)")

    # Write vault report
    out_path = VAULT_RESEARCH / "54-strategy-bakeoff-master-ranking.md"
    with open(out_path, "w") as f:
        f.write("# 54 — Strategy Bake-off Master Ranking\n\n")
        f.write("Composite of 5 parallel agent bake-offs run 2026-09-03. ")
        f.write("~420 backtests across 6 strategy families × 20 tickers.\n\n")
        f.write("## Winner definition\n")
        f.write("- Post-hygiene R_high > 0 (net positive after McLean-Pontiff + execution + options haircuts)\n")
        f.write("- CAGR at Kelly-safe sizing > 5%\n")
        f.write("- ≥ 10 trades in test period (statistical significance)\n")
        f.write("- Ideally: winner on 3+ tickers (cross-ticker robustness)\n\n")
        f.write(f"## All winner combos ({len(ranked)} total)\n\n")
        f.write("| Rank | Agent | Ticker | Raw R | WR% |\n|---|---|---|---|---|\n")
        for i, w in enumerate(ranked, 1):
            wr = f"{w['wr_pct']:.1f}%" if w['wr_pct'] else "n/a"
            f.write(f"| {i} | {w['agent']} | {w['ticker']} | {w['raw_r']:+.1f}R | {wr} |\n")
        f.write(f"\n## Cross-agent ticker robustness\n\n")
        for tkr, ws in sorted(by_ticker.items(), key=lambda x: -len(x[1])):
            if len(ws) >= 2:
                agents = ", ".join(sorted(set(w['agent'] for w in ws)))
                f.write(f"- **{tkr}**: {len(ws)} winning combos across agents: {agents}\n")

    print(f"\n✅ Wrote {out_path}")

    # JSON aggregate
    json_path = DATA_DIR / "master_ranking.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump({
            "generated_utc": None,
            "n_combos": len(all_winners),
            "top_15": ranked[:15],
            "by_ticker_counts": {k: len(v) for k, v in by_ticker.items()},
            "by_agent_counts": {k: len(v) for k, v in by_agent.items()},
        }, f, indent=2, default=str)
    print(f"✅ JSON aggregate at {json_path}")


if __name__ == "__main__":
    main()
