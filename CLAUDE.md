# CLAUDE.md

Before any work on BMG Capital, read the Obsidian vault at:
~/Documents/BMG-Capital-Vault/

REQUIRED reads every session (non-negotiable):
- 00-INDEX.md
- context/01-brock-profile.md (communication style, what to avoid)
- context/02-bmg-overview.md (what BMG is)
- context/04-bot-fleet.md (current allocations, position sizing rules)
- context/05-known-issues.md (recurring bugs and traps — READ IN FULL)
- context/06-decision-history.md (standing decisions, don't reopen)
- context/08-conflict-log.md (open theory-vs-data disputes)
- context/09-realized-pnl-rebuild-spec.md (approved active spec — read if session task is realized-P&L or leaderboard math)
- context/10-roadmap.md (goals, standing decisions, strategy pipeline — WHY the ledger looks the way it does)

Task-specific reads:
- Writing a paste-ready → skills/01-paste-ready-format.md
- Spec'ing a new strategy → skills/02-trading-strategy-design.md
- Running an app audit → skills/03-audit-playbook.md
- Database/SQL/migration work → skills/04-database-schema-reference.md
- Frontend/React work → skills/05-react-component-conventions.md
- Discord posting/routing → skills/06-discord-routing.md
- Architecture questions → context/03-architecture.md

GROWTH RULE: If you notice yourself making the same mistake twice, add the lesson to the relevant vault file. If a needed skill or context file is MISSING, ASK BROCK to add it before proceeding rather than guessing.

## VAULT DISCIPLINE (added 2026-08-06)

These rules are non-negotiable and inherit across every session — they live here so a fresh Claude Code process picks them up with zero pasting.

### V1. Session start
Read `context/05-known-issues.md` before taking any task. In your first message, state the top 3 OPEN issues by severity. If the requested task is lower priority than an open P0, say so before starting.

### V2. Session end
Update the vault. What shipped (commit hash + acceptance number). What's still open. Anything new discovered. **An issue leaves `known-issues.md` only with the commit that closed it — never through silent removal.**

### V3. Weekly / on "status"
Answer F3 unprompted — "what do I believe is broken that nobody has flagged?" — with evidence, not theories.

### V4. Conflict rule
When your explanation contradicts observed data (yours or PM Claude's), log both in `context/08-conflict-log.md` and mark the question OPEN. Never present a theory as the root cause without a verifying query.

### V5. Compounding rule (added 2026-08-06 as part of VAULT v2)
No incident closes without a PREVENTION entry in the known-issues ledger. Prevention must be an invariant ID (I1–I10), a DB constraint, or a pre-trade gate. **"A human remembers" is not prevention — propose the structural check instead.** Incidents that recur despite a listed prevention reopen automatically as P0.

### V6. Postmortems
Each major incident gets a file in `postmortems/YYYY-MM-DD-slug.md` with five lines: what happened, root cause, how long undetected, what detected it, what prevents it now. These are also the Baird case-study raw material — write them clean.

### V7. Nightly self-audit
One line per day appended to `daily-audits/YYYY-MM-DD.md`:
`invariants=red/amber/green | open_issues=N | vault_mtime=YYYY-MM-DD HH:MM`
A missing day is itself a V1 fail.

### V8. Twice-failed disciplines become automation, not stronger rules (added 2026-08-18)

**Any discipline in this file that has failed twice becomes automation, not a stronger rule.**

Adding a stronger rule to a discipline that has already failed twice is doing the same thing and expecting a different result. The failure is not "the rule was too weak" — it's "the rule required a human/Claude to remember," and remembering is not a reliable prevention mechanism (see §V5).

**Test:** if the closing prevention entry for a ledger issue is a §V-style rule OR a "standing rule" that requires reading and remembering, and the class has recurred, escalate to automation (invariant, DB constraint, pre-execution gate, CI check, cron-generated artifact) before the third recurrence.

**Reference cases:**
- §V7 nightly self-audit failed 11+ times in the month of August — replaced by container-side `/data/audits/*.md` writer + host-side sync + I28 freshness invariant (Aug 2026-08-18, ledger #39).
- §S2 "shipped means observed" was already restated once (§M1 mechanical clause) — the "M1 artifact: NONE / PARTIAL / applied" field is the automation.

Rules that are load-bearing on human memory are technical debt. Convert them.

### V0. Destructive ops require a recent OFF-VOLUME backup (added 2026-08-09)
Any endpoint that destroys, quarantines-at-scale, migrates data, VACUUMs, or otherwise touches the DB in a way that could lose state MUST verify a fresh off-volume backup exists first. **An on-volume `.bak` does NOT count** — the 2026-08-09 P0 (Railway alerted /data at 98% before BMG's own invariants; 3.85 GB of backups on the same 4.6 GB volume as the live DB) proved backups on the same volume die with the disk.

Verification pattern:
```
scripts/bmg_admin.sh GET /admin/offvolume-backup-status
# must return { exists: true, age_hours: < 24 (or task-appropriate) }
```

Endpoints that ship the backup off-volume:
- `POST /admin/backup-sqlite-offvolume` — gzips fresh snapshot, PUTs to `OFFVOLUME_BACKUP_URL_TEMPLATE` env URL (R2/B2/Backblaze/MinIO/pre-signed S3). Writes `/data/last_offvolume_backup.json` marker.

Ledger #16 (no backup on the *actual* prod DB) stays OPEN until the marker exists and a first off-volume dump has been verified round-trip.

## Growth-through-vault-loop acceptance
A fresh session with no pasted context must be able to open its first message with: (a) the top 3 open issues by severity, and (b) the prevention rule from the most recent postmortem. If it can't, the vault is broken — fix the vault before touching code.

## SECRETS DISCIPLINE (added 2026-08-07 — DO NOT RELITIGATE)

### S1. NEVER interpolate a secret into a printed command. EVER.
Every command you print appears in the chat transcript, Claude Code logs, shell history, `ps auxwww`, and (via terminal scrollback) potentially on-screen sharing tools. A `JWT_SECRET="abc123..."` line is a permanent leak. Rotation costs Brock's time and breaks live sessions; the fix is to never print the value at all.

**Forbidden patterns** (past incidents that forced JWT_SECRET rotation):
- `JWT_SECRET="<literal>" && python3 -c "..."`
- `railway variables --kv | grep JWT_SECRET` (the value goes to stdout, which lands in the transcript)
- `echo $JWT_SECRET | ...` or any pipe that echoes the value
- Passing a secret as a CLI arg (`python3 -c "import jwt; jwt.encode(..., '<literal>')"`)

**Approved pattern** — always use `scripts/bmg_admin.sh`:
```
scripts/bmg_admin.sh GET  /admin/premarket-report
scripts/bmg_admin.sh POST /admin/pause-bot?alloc_id=67
```
The helper reads JWT_SECRET from env or the Railway CLI *inside the script*, pipes it into `python3` on stdin (not argv, not env var — invisible to `ps`), mints a 15-minute JWT, and calls `curl` with only the Bearer token in the header. The secret value never touches the terminal, transcript, shell variable, or file.

**If bmg_admin.sh isn't enough for a case**: extend the helper, don't inline the secret. Adding a flag to the wrapper is always cheaper than rotating the secret again.

### S2. "Shipped" claims require post-state verification in the same message.
Every "shipped" / "retired" / "disabled" / "closed" claim must include the verifying query output in the same reply. Not the intent, not the endpoint call — the returned state after the change. "Alloc 67 tombstoned" is not evidence; `SELECT enabled FROM bot_allocations WHERE id=67 → 0` is.
Reason: 2026-08-07 pre-market report showed `crypto_quant_scalp_1m` still enabled despite a previous session's "retired" claim. Structural fix: state must be observed, not asserted.

## OPTIONS RISK MEASUREMENT (added 2026-08-07 — fourth instance of the class)

### O1. Any risk metric on options must net hedged legs before measuring.
Naked-leg measurement is a bug, not conservatism. A short leg with a long leg above/below it on the same underlying + expiry is a defined-risk spread; measuring the short leg's `|market_value|` in isolation over-reports the position's true max loss by 10-100×.

**This rule applies to PM Claude's analysis as well.** Any options risk claim in a paste-ready, dashboard alert, or human-facing report must show the netted structure BEFORE the number. "5 long calls, −$25,300, 26% NAV" without naming the paired short is a §O1 violation regardless of who wrote it.

**Confirmed instances:**
1. Ledger #19 (2026-08-06) — `deployed_cents` summed gross leg abs, double-counting bull spreads.
2. m082 span-aware margin (2026-08-07 audit patch) — sleeve deployed used per-leg notional.
3. Ledger #29 (2026-08-07) — I7 per-position concentration used per-leg `|market_value|`, false-red'd BABA at 28.4% NAV on a defined-risk 111/112 vertical whose true max loss was 1.6% NAV.
4. Ledger #31 (2026-08-09) — PM Claude report flagged META 260828C00655000 as "5 naked long calls, −$25,300 unrealized, 26% NAV". Actually a 655/660 bull call spread × 5. Real max loss $3,875 (4% NAV). Brock's own escalation self-classified as the 4th instance.

**Rule:** before you compute *any* risk aggregate (exposure, deployed, margin, concentration, max loss, VaR, sleeve total), group option legs by `(underlying_root, expiration, right)` and:
- Long/short pair on same key → net debit for spread, or width × contracts × 100 (capped for verticals).
- Unpaired long → premium paid = `avg_entry × abs(qty) × 100`.
- Unpaired short → cash-secured margin = `strike × abs(qty) × 100`.

Then attribute to the underlying. The `_check_i7_exposure_caps` function in `services/invariant_engine.py:336` is the reference implementation — copy its structure for any new risk metric.

**Failure mode to watch:** the naked measurement produces conservative-looking numbers (higher risk shown than exists). It looks defensible and gets shipped. It then triggers wasteful de-risking trades that reduce a hedged position's already-low max loss at the cost of real slippage. If you're about to recommend trimming an options position, first verify the metric is spread-aware.

## PRE-FLIGHT DISCIPLINE (added 2026-08-10 — Claude self-named failure class)

### M1. Write the expected-state artifact BEFORE writing code that produces state.

Applies to any change touching:
- (a) accounting math or aggregations
- (b) DB queries against a model
- (c) response payloads consumed by a downstream route
- (d) multi-source partitioning

Cost: 2–10 min of thinking before the first Edit. Return: catches a class of failures that otherwise ship and are found only by §S2 / Brock's audits / recurrence.

**Artifact by change type:**

- **Accounting / aggregation:** write the identity in cents on paper.
  ```
  # expected: sum(A) + sum(B) + cash + unattributed == long_MV + short_MV + cash
  # buckets in A: portfolio_snapshots.pv (allocs in returned portfolios)
  # buckets in B: orphan_alloc.pv (allocs not in any returned portfolio)
  # unattributed: alpaca positions no user-scoped alloc claims
  ```
  Then write code to satisfy it. Post-deploy §S2 compares the code output to the written identity.

- **DB queries:** open the model file and quote every field name you'll use.
  ```
  # BotSignal fields (backend/app/db/models/bots.py:56):
  #   id, allocation_id, ts, symbol, side, confidence,
  #   size_hint, reason, strategy, entry_price, stop_price,
  #   target_price, discord_posted_at, discord_message_id,
  #   is_test, executed_at
  # NOTE: no created_at. Use ts.
  ```
  Same for the sample row shape you expect the query to return.

- **Response payloads:** trace the end-consumer route. If handler explicitly whitelists fields (like `/portfolio/summary`), the pass-through list must be updated too.
  ```
  # canonical.compute_strategy_lab_aggregate returns {..., new_field: X}
  # /portfolio/summary handler at routers/portfolio.py:144 whitelists response —
  #   MUST add new_field to the return dict there too or it's silently dropped.
  ```

- **Partitions:** enumerate every bucket before summing. Prove exhaustiveness on paper.
  ```
  # partition of all_allocs:
  #   1. allocs in a returned portfolio_snapshot → sleeve_sum
  #   2. allocs NOT in any returned portfolio → orphan_alloc bucket
  # UNION = all_allocs. INTERSECTION = ∅. verified.
  ```

**Self-honesty check:** if the "artifact" is just the code without the paper step, the discipline was skipped. Retrospective §S2 will surface the miss; that's a discipline failure, not a §S2 win.

**Honesty clause (added 2026-08-10):** if the paper artifact was NOT written before the code, say so explicitly in the change report. Do not retrofit the artifact after the fact and claim §M1 was followed. Format: `§M1: SKIPPED (reason)` or `§M1: applied — artifact: <link/quote>`. Retrofitting hides the discipline gap and prevents the class from being detected + closed.

**Mechanical enforcement (added 2026-08-10, Brock #5):** every §S2 report — every claim of "shipped" that verifies state — MUST include a `§M1 artifact:` line as its first or second field. Values:
- `§M1 artifact: <link to spec / vault path / inline identity quote>` — applied cleanly
- `§M1 artifact: PARTIAL — <what was done, what was skipped>` — honest partial
- `§M1 artifact: NONE — <reason>` — skipped, e.g. "trivial 1-line comment change" or "hotfix for prod incident, no time"

A §S2 report without the field is itself a discipline violation. This is stronger than the honesty clause: a missing artifact is a knowable gap; an UNSTATED absence is worse because it hides the gap. First-session tracking will show my compliance rate.

**Reference incidents this rule closes (2026-08-09 session):**
- `BotSignal.created_at` — a schema quote would have shown only `ts` exists.
- `/portfolio/summary` field passthrough — a consumer trace would have shown the handler whitelist.
- Sleeve reconciliation drift (3 iterations) — an identity-in-cents artifact would have shown fund_pv includes Alpaca margin/unsettled and doesn't equal position_sum + cash; would have listed orphan_allocs as a required bucket; would have shown user-scoping of the claim query as required for the partition to be exhaustive.

**When NOT to invoke this rule:** trivial single-field UI edits, cosmetic renames, comment-only changes. Anything that touches money math or a scheduled job's behavior counts.

## PROVENANCE (added 2026-08-10 — ledger #32)

### W1. BMG never writes a row that impersonates a broker fact.
Any row BMG generates must be labeled AT THE SCHEMA LEVEL as generated. If a bug requires deleting rows to fix, the real fix is preventing that row category from being created — **deletion is triage, not a fix.**

**Enforcement (three layers):**

1. **Schema (m099)** — `bot_trades.origin` and `bot_positions.origin` are ENUM-constrained by SQLite trigger. Values: `BROKER_FILL` | `ADOPTED` | `RECONCILE` | `REBUILD` | `BACKFILL`. Any INSERT/UPDATE without a valid origin fails at the DB layer. See `app/services/provenance.py` for the single source of truth.

2. **Consumers** — trade counts, round-trips, win rate, Sharpe, realized P&L filter to `origin='BROKER_FILL'`. Position / exposure / valuation include ALL origins (they're real holdings regardless of who wrote the row). UI trade blotter defaults to BROKER_FILL with a separate "system activity" view.

3. **CI (`scripts/ci_check_gates.sh`)** — any file constructing `BotTrade(...)` or `BotPosition(...)` must import the corresponding gate (`trade_write_gate` / `position_write_gate`). Grep-based. Fails the build. Run via `.github/workflows/gate-enforcement.yml`. Self-test at `scripts/ci_check_gates_selftest.sh` proves the guard catches an ungated commit.

**Reference incidents (five deletions before this rule):**
- Sim quarantine (ledger #26)
- Phantom purge (ledger #2)
- Adopter rollback (ledger #23)
- Reconcile close (multiple)
- Restart dupes (ledger #21, #23)

Each one deleted rows without preventing the category. This rule prevents the category.

### W2. today_pnl must be session-honest.
Outside RTH, `today_pnl_cents` is `None` (frontend renders "—" per NULL≠$0). Inside RTH, `today_pnl_cents = alpaca.equity - alpaca.last_equity`. The `today_pnl_label` field on `/portfolio/summary` says `"live"` | `"market_closed"` | `"unavailable"`.

**Ban:** never show a numeric today_pnl outside RTH. At 3 AM Monday with markets closed, a −$5,161 today_pnl reading is a §W2 violation.

**Scope discipline (added 2026-08-10 after regression):** session-honest applies to **`today` only**. `all_time`, `mtd`, `wtd` are period-baselined and independent of session state — they compute regardless of whether the market is open. Do NOT extend session-nulling to other periods; if you do, you'll silently zero the fund's historical P&L any time the market is closed.

## §ADOPT-BOUND (added 2026-08-11, Brock overnight #5)

### An adopter run is bounded by its own dry-run diff. No adopter may exceed its predicted delta.

**Rule:** if dry_run says N adds, the live run adds exactly N or it aborts. Additionally, before creating a catchall/unresolved-attribution row for (symbol, side), the adopter MUST check whether ANY active BMG allocation already owns that (symbol, side). If yes, SKIP (don't create the duplicate). No "we'll dedupe later."

**Reason (2026-08-10 overnight):** adopt-missing-alpaca-positions added 83 catchall rows overnight, 20 of which duplicated positions already owned by real bots. Result: bot_sum_pv inflated $16K vs fund_pv, I24 red for a day, position drift 17.

**Reference implementation:** `admin.py::adopt_missing_alpaca_positions` — the `_already_owned` pre-check at the top of the per-position loop.

**Family:** same class as ledger #32 provenance and §W1 — BMG's record must match broker reality, not create parallel truth on catchall allocs.

## §LEDGER-33 (added 2026-08-11, Brock overnight #1)

### Trades book from FILL confirmation, never from submitted limit.

Any code path that writes a BotTrade with `fill_price_cents = int(limit_price * 100)` at submit time is a bug of the same family as sim/phantom/adopter. The trade must be written from the Alpaca fill event's `filled_avg_price`, after status='filled'.

**Reference implementation:** `admin.py::confirm_alpaca_fill_and_close` — polls Alpaca, refuses if not filled, uses `filled_avg_price` for the write.

**Prohibited pattern:**
```python
BotTrade(..., fill_price_cents=int(round(limit_price * 100)), alpaca_order_id=submitted_id)
```
This encodes intent, not fact. If the order fills at a different price (e.g., opening auction), the recorded fill price is wrong.

**Required pattern:**
```python
# 1. Submit → get order_id
# 2. Poll status until filled|canceled|rejected
# 3. If filled: read filled_avg_price + filled_qty from the response
# 4. THEN write BotTrade with those fill values
```

Detected callers (fixed): `admin.py::admin_close_limit` (removed the write; caller must invoke `/admin/confirm-alpaca-fill-and-close`); `jobs/iwm_trim_2026_08_11.py::_book_bmg_fill` (only called from filled-branch with `filled_avg_price`).

## MONEY-MATH ACCEPTANCE (added 2026-08-10, Brock regression rule)

Any change touching P&L, valuation, or period-return math must include a **post-deploy acceptance print** of `pnl.{all_time, mtd, wtd, today}` and confirm each field is either a plausible number OR an explicit `null` with a `reason` field. **Zero is neither** — a `.cents == 0` on a live funded fund is always a bug, never a value.

Enforced structurally by invariant **I23**: any exact-zero pnl window on a fund with `funded_capital > 0` and `age > 1 day` → RED. Applies to `all_time`, `mtd`, `wtd` always; to `today` only during RTH.

# 2026-08-18: deploy-probe commit (whitespace only) — test whether any
# new deploy succeeds vs 2f957065 specifically. See ledger #36 investigation.
