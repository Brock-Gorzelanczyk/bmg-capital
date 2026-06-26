# Coder summary — Strategy Lab BotCard $ allocation alongside % of sleeve

## Files modified
- backend/app/routers/bots.py — +25/-3 lines (added `sleeve_pct` to allocation payload; SUM-of-children divisor)
- frontend/src/api/bots.ts — +1/-0 lines (added `sleeve_pct: number | null` to `BotAllocation` interface)
- frontend/src/pages/StrategyLab.tsx — +22/-2 lines (added `formatDollarsWhole` helper; replaced Capital Allocated stat block with `$X · Y.Z% of sleeve` per spec, with fallback chain)

## New files
- None for the spec's COMMIT 1/2/3. (Tester will add `backend/tests/test_bots_sleeve_pct.py` in Phase 3.)

## Deviations from spec
- None of substance. Followed every DO/DO NOT.
- Q1 (sleeve precision) and Q2 (label text) defaults adopted per spec: one decimal (`40.7%`) and keeping "Capital Allocated" label.

## Commands run
- `npx tsc --noEmit` (in /frontend) → 0 errors
- `python3 -c "import ast; ast.parse(open('app/routers/bots.py').read())"` → OK (full pytest deferred to Tester phase)
- `git diff --stat` (scoped to SHIP 2 files):
  - backend/app/routers/bots.py | 28 ++++++++++++++++++++++++++---
  - frontend/src/api/bots.ts    |  1 +
  - frontend/src/pages/StrategyLab.tsx | 24 +++++++++++++++++++++++-

## Implementation notes
- `_allocation_to_dict(a, sleeve_pct=None)` — preserves backwards compat for any other caller.
- `_profile_to_dict(p, allocation, sleeve_pct=None)` — threaded through cleanly (option (a) per spec).
- Sleeve totals computed ONCE outside the per-profile loop. Divisor filters by `enabled=True` and `portfolio_id IS NOT NULL`.
- `sleeve_pct` returned as Python None (JSON null) when sleeve_total is 0 or starting is 0 — distinguishes "no sleeve / no data" from "0%".
- Frontend `_rawBotToListItem` already exposes `b.starting_capital_usd` via `stats.starting_capital_usd` — reused per spec ("No new field required if we use this path"). Cents-to-dollars conversion happens at API layer (router serializer), not in JSX.
- BotCard fallback chain matches spec exactly: canonical (dollars + sleeve_pct) → dollars-only → sleeve_pct-only → legacy `capital_pct`.

## Out of scope / not touched
- Did NOT modify the unrelated `frontend/src/components/layout/Sidebar.tsx` change present in working tree (predates SHIP 2).
- Did NOT touch `BotAllocation.capital_pct` write path.
- Did NOT touch other BotCard variants (StrategyLibraryPage, PortfolioDetailPage, AdminBotsPage).

## Open questions
- None.

## Ready for Tester
YES
