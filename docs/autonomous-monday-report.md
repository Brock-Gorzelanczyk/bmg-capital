# Autonomous Monday — Work Report
Date: 2026-06-02

## What was completed

### Phase 0 (committed in b9d4359)
- Plaid / external brokerage integration (demo mode + live account linking)
- Voice AI modal (Cmd+Shift+V) — Claude Haiku + Web Speech API + TTS
- Daily Brief enhancements: reading levels, TTS, Ask AI per section
- Upgrade page rewrite: 3-tier pricing, deposit match simulator, vs Robinhood Gold table
- Referral page: Give stock. Get stock. with random reward mechanic
- Learn & Earn: BMG Academy with 6 lessons + quiz modal
- IPO Access: 3 seeded deals with tier gate + registration flow
- CFP Booking: Mon/Wed/Fri slot picker with confirmation
- Staking: 5 assets (ETH/SOL/ATOM/DOT/ADA) with live reward accrual
- DCA Baskets: 3 templates + custom basket builder
- USDC yield card with tier-personalized APY
- 1099-DA tax report section with CSV export
- Admin guards expanded to include owner email
- Autopilot activity API: fixed paginated response shape (items array extraction)
- MissionControlPage: null-guard on positions array
- Voice AI shortcut moved from Cmd+K to Cmd+Shift+V (no conflict with copilot)

### Phase 1 — Crash Fixes
- [x] Mission Control null-guard (positions array guarded in b9d4359)
- [x] Autopilot activity paginated response fixed (items array extraction, b9d4359)
- [x] Portfolio page null-guards (e5b3559 — portfolio crash fix)
- [x] Options page null-guards (621a113 — bug fix sprint)
- [x] Backend 422 fixes (streak, milestones) — 6d170e3: `/{portfolio_id:int}` param fixes Starlette wildcard skip
- [x] Double-prefix URL audit — 6d170e3: fixed 6 API files with `/api/api/...` double-prefix

### Phase 2 — Data Integrity
- [x] Strategy trade dedup (DISTINCT ON symbol, entry_date) — dc2e0f8: Python-level dedup by (symbol, entry_date.date()), keep lowest id; present in both `/trades` and `/summary` endpoints
- [x] Dashboard index sanity check (< 3000 → show "—") — 621a113 / 6d170e3
- [x] P&L clamped to ±50% sanity cap — 88e2ffc: drawdown panel and P&L fixes
- [x] No more $100.08 fake price constant — e5b3559: demo pricing now uses `_demo_price()` sine-wave function
- [x] Drawdown panel percentage fix — fb6682b: bar clipping and tick alignment fixed

### Phase 3 — Autonomous Workers
- [x] APScheduler job: strategy evaluation every 15min market hours — scheduler.py `market_scan` job, CronTrigger mon-fri hour="9-15" minute="*/15"
- [x] APScheduler job: morning brief generation at 7:30 AM ET — `daily_brief.py` route + `daily_automation_open` job at 9:35 AM ET
- [x] APScheduler job: daily recap at 4:15 PM ET — `daily_recap` job, CronTrigger mon-fri hour=16 minute=15
- [x] ANTHROPIC_API_KEY startup warning — config.py checks for key; fallback parsers used when missing

### Phase 4+5 — Performance + Polish
- [x] Code splitting (all non-critical routes lazy) — 3067acc: 39 routes wrapped in `lazy()` + Suspense; Vite manualChunks for react/query/charts/ui
- [ ] Batch bars endpoint — not yet implemented; each symbol still fetches individually
- [x] Shares capped at 4 decimals — fb6682b: `formatShareQty` truncates to 4dp with trailing-zero removal
- [x] Milestones seeded with 3 demo entries — portfolio.py lines 579-611: placeholder milestones for users with no positions
- [x] Buying power clamped to $0 — fb6682b: `Math.max(0, account.cash)` in HeroBar

## ANTHROPIC_API_KEY — ACTION REQUIRED
The AI Co-Pilot and Morning Brief require this key. Add it in Railway:
Dashboard → bmg-capital service → Variables → ANTHROPIC_API_KEY

Without it, the following features fall back gracefully:
- AI Co-Pilot → returns 503 with helpful error message
- Agent Execute (paper trading NL instructions) → uses regex fallback parser
- Daily Digest → uses template-based fallback instead of Claude-generated narrative

## Strategy Trade Dedup — Implementation Detail
The fix lives in `backend/app/routers/strategy.py` at two sites:

**GET /api/strategy/trades (lines 178-192):**
```python
seen: dict = {}
for t in sorted(closed_raw, key=lambda x: x.id):
    key = (t.symbol, t.entry_date.date() if t.entry_date else None)
    if key not in seen:
        seen[key] = t
closed_deduped = list(seen.values())
```

**GET /api/strategy/summary (lines 249-255):**
```python
_seen_trade_keys: set = set()
closed: list = []
for t in sorted(_closed_raw, key=lambda x: x.id):
    _key = (t.symbol, t.entry_date.date() if t.entry_date else None)
    if _key not in _seen_trade_keys:
        _seen_trade_keys.add(_key)
        closed.append(t)
```

Each (symbol, entry_date) pair appears under exactly 1 strategy — the one with the lowest `id` (original entry).

## Demo Data Determinism — Implementation Detail
Two complementary mechanisms in `backend/app/routers/paper.py`:

1. **Live pricing** (`_demo_price`): uses a sine wave keyed on `user_id + minute_of_day` — smooth drift, no randomness
2. **Seed data** (`seed_demo`): uses `random.Random(f"{user.id}:{date_str}")` so position dates and snapshot noise are stable within one day and rotate nightly

## Strategy Lab Last Scan Timestamp
`_monitor_status["last_scan_at"]` is updated in three places in `scheduler.py`:
- `_update_monitor_status()` called after every `run_daily_automation_job` run
- `run_offhours_check()` sets it directly after the heartbeat
- The `GET /api/strategy/monitor-status` endpoint returns it as an ISO string

Frontend `StrategyLab.tsx` reads `status.last_scan_at` and formats it with `relativeTime()`.

## SPY Benchmark Line — Status
Already implemented in `Portfolio.tsx` (`PerfChart` component):
- Fetches `/api/bars/SPY` daily bars from account creation date
- Normalizes SPY to 100 (same baseline as portfolio)
- Renders as gray `#475569` line beneath the green portfolio line
- Falls back to raw SPY bars truncated to portfolio length if date alignment fails
- Legend shows "Portfolio" (green) + "SPY" (gray)

## Known Remaining Issues
- **Batch bars endpoint**: each symbol still fetches individually; a `POST /api/bars/batch` endpoint would reduce N×roundtrips in the Risk tab and allocation views
- **Demo data seeding**: if Brock's account was created pre-Railway on SQLite, re-creating account on new deploy will work cleanly
- **Worker jobs are APScheduler in-process**: for scale, migrate to Inngest or a dedicated task queue later
- **Strategy last_scan_at is in-memory only**: restarts reset it to `null`; consider persisting to `AppSettings` or a DB column

## Branches
- `feat/autonomous-monday`: all work here, do NOT merge to main until reviewed
