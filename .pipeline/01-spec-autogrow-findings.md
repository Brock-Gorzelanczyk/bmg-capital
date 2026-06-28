# M027 PART 1 — Auto-grow audit findings

## Summary
Identified the root cause of the post-m025 capital inflation. It is a runtime
seed loop that ENFORCES A FLOOR on `bot_allocations.starting_capital_cents` on
every portfolio-related API call. m025 sets `crypto_onchain` to $50K → the
next portfolio fetch silently bumps it back to $100K. Multiplied across the
8 bots m025 sets below the floor, this is the inflation Brock observed.

## Root cause — single function with 3 auto-grow patterns

**File:** `backend/app/routers/bots.py`
**Function:** `_ensure_portfolios_for_user(db, user_id)` (line 109)

### Auto-grow pattern A — StrategyPortfolio sleeve total sync (lines 137-139)
```python
else:
    if existing.starting_capital_cents != target_capital:
        existing.starting_capital_cents = target_capital
```
Resets the sleeve-level `StrategyPortfolio.starting_capital_cents` to the
`target_capital` from `_PORTFOLIO_DEFS` on every call. If a migration changes
the sleeve total, the next API call reverts it.

### Auto-grow pattern B — capital_cents_within_portfolio floor bump (lines 175-177)
```python
if (alloc.capital_cents_within_portfolio or 0) < capital_cents:
    alloc.capital_cents_within_portfolio = capital_cents
    alloc.updated_at = now
```
Bumps the per-portfolio cap to `_BOT_CAPITAL = $100K` if it's below.

### Auto-grow pattern C — starting_capital_cents floor bump (lines 178-180)
```python
if (alloc.starting_capital_cents or 0) < capital_cents:
    alloc.starting_capital_cents = capital_cents
    alloc.updated_at = now
```
**This is the primary inflation source.** Bumps bot starting capital to
`_BOT_CAPITAL = $100K` floor on every portfolio fetch.

## _PORTFOLIO_DEFS floor values

`_BOT_CAPITAL = 10_000_000` (= $100K) and `_PORTFOLIO_DEFS` declares
- Stocks: $100K each (3 bots = $300K)
- Crypto: $100K each (4 bots = $400K)
- Options: $100K each (2 bots = $200K)
- Quant: $40K aggressive / $30K scalper / $30K mean_rev = $100K

## m025 spec vs floor — exactly which bots inflate

| Bot | m025 spec | floor | bumped to |
|---|---|---|---|
| stock_swing | $110K | $100K | $110K (no change — above floor) |
| stock_lt | $90K | $100K | **$100K** |
| stock_day | $70K | $100K | **$100K** |
| crypto_day | $90K | $100K | **$100K** |
| crypto_swing | $70K | $100K | **$100K** |
| crypto_lt | $60K | $100K | **$100K** |
| crypto_onchain | $50K | $100K | **$100K** |
| options_income | $50K | $100K | **$100K** |
| options_directional | $50K | $100K | **$100K** |
| crypto_quant_aggressive | $110K | $40K | $110K (above floor) |
| crypto_quant_mean_reversion | $80K | $30K | $80K (above floor) |
| crypto_quant_scalper | $70K | $30K | $70K (above floor) |
| cash_floor | $100K | (not in defs) | $100K (untouched — not in _PORTFOLIO_DEFS) |

Post-bump total: 8 bots × $100K + stock_swing $110K + 3 quants ($110+$80+$70K)
+ cash_floor $100K = **$1,360K**.

This matches the magnitude of inflation Brock reported ($1,696,154 — also
includes extras like `stock_momentum`, `crypto_arbitrage` etc. that m026 was
supposed to disable).

## Call sites (every portfolio-related endpoint triggers the seed loop)

- `backend/app/routers/bots.py:613` (get_bots)
- `backend/app/routers/bots.py:629` (one bot detail)
- `backend/app/routers/bots.py:1139` (another bot endpoint)
- `backend/app/routers/strategy_lab.py:381` (strategy lab portfolio)
- `backend/app/routers/portfolio.py:376` (portfolio snapshot)

So every Dashboard / Strategy Lab / Portfolio / bots-list fetch can inflate.

## Other audited paths (NOT auto-grow sources)

| File | Line | Verdict |
|---|---|---|
| `routers/bots.py:129, 139` | StrategyPortfolio create — first-seed only, not auto-grow |
| `routers/bots.py:179` | the inner alloc bump (covered above as pattern C) |
| `routers/clean_slate.py:259, 271` | Explicit reset endpoint — intended writes |
| `routers/strategy_lab.py:92` | First-seed BotAllocation creation, not auto-grow |
| `core/canonical.py:*` | All reads (variable assignment from row), never writes |
| `db/migration.py:*` | Migrations only — runs at startup, intended writes |
| `jobs/compute_bot_stats.py:171` | Writes `BotPerformanceStats.starting_capital_cents` — DIFFERENT TABLE |
| `services/performance_service.py:496, 688` | Reads, not writes |
| `strategy_lab/core/audit.py:59` | Postgres BRIDGE (separate discord-worker DB), not main DB |
| `server/scripts/bot_state_audit.py:71` | Standalone script, not called at runtime |
| `agents/executors/execute_allocation_change.py:92` | Writes `capital_pct` only — not the field that drives PV |
| `scripts/set_bot_capital_100k.py` | Manual script, not called at runtime |
| `scripts/backfill_bot_data.py:213` | Manual script, not called at runtime |

## Fix applied

Replace the three auto-grow patterns with strict immutability after first
seed. The seed loop now:
- Creates `StrategyPortfolio` rows if missing (unchanged)
- Creates `BotAllocation` rows if missing (unchanged)
- Does NOT update `starting_capital_cents`, `capital_cents_within_portfolio`,
  or sleeve `StrategyPortfolio.starting_capital_cents` after creation

starting_capital_cents is now immutable except via:
1. Explicit migration (m024/m025/m026/m027)
2. Explicit reset endpoint (`/api/admin/clean-slate/restart`)
3. First-time row creation

## Reviewer must verify

- `_ensure_portfolios_for_user` no longer writes capital fields on the `else`
  branch (when allocation already exists)
- `capital_audit_log` table exists and SQLAlchemy event listener fires on
  every UPDATE of `BotAllocation.starting_capital_cents`
- m027 migration is named `m027_force_clean_slate` (not m025/m026 — those
  short-circuit on existing schema_migrations rows)
- Capital invariant watchdog scheduled job is registered AND runs every 5 min
