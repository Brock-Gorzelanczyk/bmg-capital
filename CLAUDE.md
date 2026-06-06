# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**BMG Capital** — a personal trading platform with automated paper-trading bots, portfolio analytics, stock/crypto screener, trade journal, and AI-powered features. Single-user in production (Railway), multi-user capable in code.

## Commands

### Development

```bash
# Backend — from /backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend — from /frontend
cd frontend
npm run dev -- --port 5174 --host

# Both together (auto-restarts on crash)
bash keep_alive.sh   # logs: /tmp/bmg_backend.log, /tmp/bmg_frontend.log
```

### Frontend

```bash
cd frontend
npm run build     # tsc -b && vite build → dist/
npm run lint      # eslint
npm run preview   # preview production build locally
```

### Backend

```bash
cd backend
source .venv/bin/activate
pytest tests/                          # all tests
pytest tests/test_screener.py -v       # single test file
pytest tests/ -k "test_rsi"            # single test by name
```

### Database

SQLite dev DB lives at `backend/bmg_capital.db`. There is no migration runner command — `app/db/migration.py:run_migrations()` is called automatically at startup via the FastAPI lifespan hook. To reset local state, delete the `.db` file and restart.

### Deployment

Railway builds via `Dockerfile` (multi-stage: Node → Python). Push to `main` triggers a Railway deploy. No manual migration step needed — migrations run on startup.

## Architecture

### Stack

| Layer | Tech |
|---|---|
| Frontend | React 19 + TypeScript + Vite, React Router v7, TanStack React Query, Zustand, Tailwind CSS |
| Backend | FastAPI (Python 3.11), SQLAlchemy 2 ORM, SQLite (dev & prod via Railway volume) |
| Market data | Alpaca (paper trading + live quotes/bars via WebSocket), yfinance (screener), FMP |
| AI | Anthropic Claude (`anthropic` SDK, `ANTHROPIC_API_KEY`) |
| Payments | Stripe (subscriptions/tiers) |
| Real-time | Alpaca WebSocket stream → `app/alpaca/stream.py` → `app/ws/manager.py` → browser |

### Backend layout

```
backend/
  app/
    main.py              # FastAPI app, 60+ router includes, lifespan startup automation
    config.py            # Pydantic Settings — all env vars with defaults
    core/
      canonical.py       # THE canonical compute layer — see below
    db/
      session.py         # SQLAlchemy engine + get_db() dependency
      base.py            # declarative Base
      models/            # 46+ SQLAlchemy model files (one domain per file)
      migration.py       # idempotent column/table migrations run at startup
    routers/             # 67 router files — one per feature domain
    screener/
      filters.py         # filter classes (RSIFilter, MACrossFilter, etc.)
      runner.py          # run_screen() — bar cache with 1-hour TTL
      scheduler.py       # APScheduler — daily screen jobs
    alpaca/
      stream.py          # WebSocket stream manager
      assets.py          # universe symbol list (falls back to DEFAULT_UNIVERSE)
    ws/
      manager.py         # broadcast to connected browser clients
```

### Frontend layout

```
frontend/src/
  App.tsx                # all routes; critical pages static, rest lazy-loaded
  api/                   # axios client modules — one file per backend domain
  pages/                 # 85+ page components
  components/
    layout/AppShell.tsx  # sidebar + top bar shell
    ui/                  # shared primitives
    CoPilot.tsx          # AI chat drawer
  hooks/
    useWebSocket.ts      # live Alpaca quotes subscription
    useBars.ts           # chart OHLCV data hook
    useCoPilot.ts        # AI feature toggle hook
  store/
    authStore.ts         # Zustand — JWT token + user
  config/                # API_BASE ("/api"), WS_URL
```

### Request flow

```
Browser → React Query → axios (/api/*) → FastAPI router → SQLAlchemy → SQLite
                                                         → canonical.py (metrics)
Browser ← WebSocket ← app/ws/manager.py ← app/alpaca/stream.py ← Alpaca WS
```

Auth: JWT (HS256, 30-day expiry) stored in Zustand + localStorage. Every request sends `Authorization: Bearer <token>`. Backend `get_current_user` dependency validates and attaches the user.

---

## Canonical compute pattern (CRITICAL)

**Every endpoint that shows portfolio value, P&L, or position counts must call `canonical.py` — never inline the same calculation.**

`app/core/canonical.py` exposes three functions:

```python
compute_bot_snapshot(alloc, profile, db) -> BotSnapshot
compute_portfolio_snapshot(port, allocs_with_profiles, db) -> PortfolioSnapshot
compute_strategy_lab_aggregate(user_id, db) -> dict
```

**Data source priority inside canonical.py:**
1. `BotDailyPnL.portfolio_value_eod_cents` — EOD snapshots written by the executor
2. `BotDailyPnL.realized_cents + unrealized_cents` — daily P&L components
3. `BotAllocation.starting_capital_cents` — baseline fallback

**Why:** Before this layer existed, `get_portfolios` used `rng.gauss` random drift and showed +$5,769 while bot cards showed $0.00. The canonical layer makes Dashboard, Portfolio header, Bot cards, and Bot detail pages always agree.

If you add a new endpoint that shows any financial metric, import and call the appropriate canonical function — do not re-derive it from raw DB rows.

---

## Strategy Lab — bot system

### 3-portfolio structure

| Portfolio | Asset class | Bots | Starting capital |
|---|---|---|---|
| Stocks 📈 | `stocks` | stock_swing, stock_day, stock_lt | $50,000 paper |
| Crypto ₿ | `crypto` | crypto_swing, crypto_day, crypto_lt | $50,000 paper |
| Options ⚡ | `options` | options_income, options_directional | $50,000 paper |

### Bot profile names (snake_case, canonical)

`stock_swing`, `stock_day`, `stock_lt`, `crypto_swing`, `crypto_day`, `crypto_lt`, `options_income`, `options_directional`

Display names live in `canonical.py:DISPLAY_NAMES` — that is the only place they're defined.

### Data chain

`BotProfile` → `BotAllocation` (per-user enablement + capital %) → `BotPosition` / `BotTrade` / `BotDailyPnL`

`BotDailyPnL` is written once per day by the executor (`strategy_lab/bot_executor.py`). The canonical layer reads it — it never re-computes from positions at query time.

### Daily automation

On startup (`main.py:_startup_strategy_scan`), if today's `DailyEquitySnapshot` doesn't exist for a user, `run_daily_automation()` is triggered. This runs on weekdays only. APScheduler also fires it on a schedule.

---

## Naming conventions

- **Strategy module names:** `snake_case` (matches `BotProfile.name` in DB — never change these without a migration)
- **React components:** `PascalCase`
- **API route files:** `snake_case` matching their domain (e.g., `bots.py`, `strategy_lab.py`)
- **Frontend API modules:** `camelCase` functions in `src/api/` (e.g., `getBots`, `runPreset`)
- **Crypto yfinance symbols:** always `{BASE}-USD` format (e.g., `BTC-USD`, `ETH-USD`) — `_normalize_symbol()` in `bars.py` and `normalizeCryptoSymbol()` in `ChartPage.tsx` handle conversion

---

## Don't do X rules

**Never use placeholder/fake data in financial displays.** No hardcoded `$99.99`, `22.9M shares`, or `rng.gauss()` drift for P&L. Every dollar shown must be backed by a `BotTrade` or `BotDailyPnL` row.

**Never let a crypto strategy fire on a stock ticker.** The screener universe (`alpaca/assets.py`) contains stock symbols. Crypto bots operate on `ccxt` against their own symbol lists. Check `asset_class` before running any bot logic.

**Never compute the same metric two ways across endpoints.** If `get_portfolios` and `get_bot` both show "30d return", they must both call `canonical.py:compute_bot_snapshot`. Adding a third endpoint that derives it differently will cause surfaces to diverge — the bug that caused this rule.

**Never add a router without registering it in `main.py`.** The import line in `main.py` is the only registration mechanism.

**Never drop/rename a `BotProfile.name`.** These are foreign-keyed across 4+ tables and referenced by string in the frontend's `BOT_META` dict. Treat them as immutable IDs.

---

## Environment variables

Minimum to start (app boots without any — DB is SQLite at default path):

```
JWT_SECRET          # change from default in any shared env
ALPACA_API_KEY      # paper trading + live quotes
ALPACA_SECRET_KEY
ANTHROPIC_API_KEY   # AI features: CoPilot, chart analysis, NL screener
```

Full list in `backend/app/config.py`. All default to empty strings (features degrade gracefully when missing).

## Archive Notice

**2026-06-06**: Personal-portfolio and paper-trading tables were archived (renamed with `_archived` suffix).

Tables renamed (data intact):
- `portfolios` → `portfolios_archived`
- `positions` → `positions_archived`
- `paper_accounts` → `paper_accounts_archived`
- `paper_positions` → `paper_positions_archived`
- `paper_orders` → `paper_orders_archived`
- `paper_transactions` → `paper_transactions_archived`
- `paper_daily_snapshots` → `paper_daily_snapshots_archived`

To restore: rename back with `ALTER TABLE "portfolios_archived" RENAME TO "portfolios"` etc.

`/api/portfolio` now reads from the bot-aggregate (`BotAllocation` + `BotDailyPnL` + `BotPosition`) — same data source as `/api/strategy-lab/portfolio`.

SQLAlchemy models in `app/db/models/portfolio.py` and `app/db/models/paper.py` now point to the `*_archived` table names so existing service imports continue to compile.
