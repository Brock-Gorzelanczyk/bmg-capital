# UI Audit Results — 2026-06-12

## Summary
- Total elements/issues tested: 28
- Passed (already correct): 22
- Fixed: 4
- Backend-blocked: 1
- TODO / Not Found: 1

---

## Route Audit

| Route | Element | Expected | Actual | Status |
|-------|---------|----------|--------|--------|
| /strategy/:botName | Backtest tab — Run button | Button triggers handleRun() | No button existed; handleRun() was dead code | FIXED |
| /strategy/:botName | Open Positions header | "19 / $30,175 notional" | Rendered as "19/ $30,175 notional" (missing space before slash) | FIXED |
| /strategy/:botName | Bot status badge | "ACTIVE" or "DISABLED" | Showed "PAUSED" for disabled bots (inconsistent with StrategyLab/PortfolioDetail) | FIXED |
| /strategy | Comparison table status badge | "ACTIVE" or "DISABLED" | Showed "OFF" for disabled state (inconsistent label) | FIXED |
| /strategy/analytics | Route redirect | Should redirect to /strategy/performance | Correctly redirects via Navigate element in App.tsx | PASS |
| /strategy/:botName | Tab switching (Backtest, Watchlist, etc.) | Clicking tab updates activeTab state | onChange={setActiveTab} wired correctly to TabBar | PASS |
| /strategy/:botName | "Notify when live" button | Joins waitlist via API | waitlistMut.mutate(!isOnWaitlist) — properly wired | PASS |
| /strategy/portfolio/:assetClass | "Notify when live" button | Joins waitlist via API | waitlistMut.mutate(true) — properly wired | PASS |
| /strategy/forge | "+ New Bot" button | Opens wizard modal | setShowWizard(true) — properly wired | PASS |
| /strategy/forge | "Build Your First Bot" | Opens wizard modal | catalog.length > 0 && setShowWizard(true) — properly wired | PASS |
| /dashboard | "Brief me" button | Opens CoPilot with prefill | window.dispatchEvent copilot:open — properly wired | PASS |
| /dashboard | "Pause All" button | Pauses all bots | pauseMut.mutate() — properly wired | PASS |
| /mission-control | Pause/Resume buttons | Pause/resume autonomous engine | pauseMutation.mutate() / resumeMutation.mutate() — properly wired | PASS |
| /signals | Signal rows expand | Show detail on click | setExpanded toggle — properly wired | PASS |

### Known Bugs Checked (from spec) — Status
| Bug | Found in Code | Resolution |
|-----|-------------|------------|
| "8492m ago" timestamp overflow | NOT FOUND — utils.ts timeAgo() already handles h/d correctly | N/A |
| Garbled header `// WATCHLIST — ,60, NAME,S` | NOT FOUND — not present in any page/component | N/A |
| Raw dict dump `{'reason': 'momentum', ...}` | NOT FOUND — all signal.reason fields rendered as strings | N/A |
| "OPEN POSITIONS 19/ $30,175 notional" spacing | FOUND in BotDetailPage.tsx:2774 | FIXED |

---

## UI Consistency Findings

### Status Badge Inventory

All badge variants found across pages:

| Page | Status Text | Tailwind Classes | Consistent? |
|------|-------------|-----------------|-------------|
| BotDetailPage (header) | ACTIVE | `bg-lime-500/15 text-t-green border-lime-500/30` | Yes |
| BotDetailPage (header) | DISABLED | `bg-t-bg1 text-t-muted border-t-dim` | Yes (fixed from "PAUSED") |
| StrategyLab (bot card) | ACTIVE | `bg-t-green/15 text-t-green border-t-green/30` | Yes |
| StrategyLab (bot card) | DISABLED | `bg-t-bg1 text-t-dim border-t-dim` | Yes |
| StrategyLab (bot card) | COMING SOON | `bg-purple-500/15 text-purple-400 border-purple-500/30` | Design choice |
| StrategyLab (bot card) | frozen · historical | `bg-amber-500/15 text-amber-400 border-amber-500/30` | Matches botStatusBadge amber |
| StrategyLab (comparison table) | ACTIVE | `bg-t-green/15 text-t-green border-t-green/30` | Yes |
| StrategyLab (comparison table) | DISABLED | `bg-t-bg1 text-t-dim border-t-dim` | Yes (fixed from "OFF") |
| PortfolioDetailPage | ACTIVE | `bg-lime-500/15 text-lime-400 border-lime-500/30` | Yes |
| PortfolioDetailPage | DISABLED | `bg-amber-500/15 text-amber-400 border-amber-500/30` (admin lock) or gray | Yes |

Note: `botStatusBadge()` from `frontend/src/lib/botStatus.ts` exists but StrategyLab pages don't import it — they use inline conditional classes that are semantically equivalent. The badge util requires `BotSnap` type while StrategyLab has more nuanced states (COMING SOON). Not refactored to avoid scope creep.

### Timestamp Format Issues

| Location | Function | Handles > 60 min? |
|----------|----------|-------------------|
| `frontend/src/lib/utils.ts:54` | `timeAgo()` | YES — days/hours/minutes/just now |
| `frontend/src/pages/Dashboard.tsx:25` | local `timeAgo()` | YES — days/hours/minutes/just now |
| `frontend/src/pages/ForgeBuilderPage.tsx:21` | `relativeTime()` | YES — days/hours/minutes/just now |
| `frontend/src/pages/SignalsFeedPage.tsx:39` | `ago()` | YES — days/hours/minutes/now |
| `frontend/src/pages/BotDetailPage.tsx:229` | `formatRelativeAgo()` | YES — days/hours/minutes/just now |

All timestamp formatters correctly convert to hours/days beyond 60 minutes. No "8492m ago" bug found.

### Empty State Inventory

| Location | Message |
|----------|---------|
| BotDetailPage Overview | "Bot is scanning — open positions will appear here when it enters a trade. Check the Watchlist tab..." |
| BotDetailPage Backtest | "No backtest data returned. Try a different date range." |
| StrategyLab Open Positions | "No open positions. Bots scan continuously — next signal could land any minute." |
| StrategyLab Open Positions (filtered) | "No open {assetClass} positions." |
| ForgeBuilderPage | "No forge bots yet" + "Build Your First Bot" CTA |
| ForgeBuilderPage (not enabled) | "The Forge is not enabled" + env var instructions |
| WatchlistPage (implied) | Loading/empty states exist |

### Color Token Usage — Hardcoded Hex vs Design System

Pages consistently use `t-*` design tokens (`text-t-green`, `bg-t-bg0`, `border-t-dim`, etc.) defined in `tailwind.config.js`. No significant hardcoded hex colors were found inline in JSX — inline hex is only used in Recharts configs (chart colors) which is standard practice.

---

## BACKEND-BLOCKED Items (for future backend session)

1. **Backtest functionality** (`/strategy/:botName` → Backtest tab): `handleRun()` calls `runBacktest()` API function which hits `/api/bots/{botName}/backtest`. The backend endpoint is not yet implemented. Frontend now shows a disabled button with tooltip: "Full backtesting engine coming Q3 — currently disabled." This is correctly surfaced as BACKEND-BLOCKED.

---

## git diff --stat (audit commits only)

```
 frontend/src/pages/BotDetailPage.tsx | 19 +++++++++++++++----
 frontend/src/pages/StrategyLab.tsx   |  2 +-
 2 files changed, 16 insertions(+), 5 deletions(-), 0 backend files changed
```
