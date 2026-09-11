# Research Track Record Layer

**Purpose:** BMG Capital is a research operation. The product is a stack of
published research calls with documented reasoning and honest outcomes.
This layer makes that measurable and reviewable. It replaces the bot
leaderboard as the front page of the platform.

## Design rules (non-negotiable)

1. **Every outcome is benchmark-relative.** A call that returned 12% while
   its benchmark returned 15% was wrong. Absolute return on a handful of
   calls is noise. Default benchmark for small caps is `IWM`. The benchmark
   is stored per call and never changed retroactively.
2. **Thesis attribution is a separate field from outcome.** On close every
   call is classified: `THESIS_CORRECT`, `RIGHT_WRONG_REASON`, `WRONG`, or
   `UNRESOLVED`. RIGHT_WRONG_REASON is a miss, not a win. A call that pays
   off for a reason you did not identify is luck and must be recorded as luck.
3. **Kill-criteria compliance is tracked separately from performance.** When
   a criterion fires, we record whether it was obeyed. Disobedience is the
   most valuable data in the system.

## Anti-pattern guard

Do NOT compute Sharpe, t-statistic, information ratio, or any significance
test. Report counts and honest descriptions. `"3 of 5"` not `"60%"`.

## Files

- `_db.py` — SQLite schema init + connection helper
- `daily_evaluate.py` — daily cron: pull prices, evaluate machine-checkable
  kill criteria, close horizon-passed calls (does NOT auto-close on kill fire)
- `report.py` — dashboard-style output for terminal
- `cli.py` — enter / add-criterion / fire / close / list operations
- `backfill_gatx_001.py` — one-shot to seed call 001 from GATX v1 pitch
- `data/track_record.db` — SQLite storage (gitignored)

## Schema

Four objects:

- `research_calls` — one row per published call
- `kill_criteria` — 0+ per call, each with metric + threshold + action
- `daily_prices` — daily close snapshots for tickers and benchmarks
- `call_outcomes` — VIEW that computes return, benchmark_return,
  excess_return, days_held, target_hit on the fly

Outcomes are a view, not a table. Derived data is not persisted — it can
drift from source. It is recomputed on every query.

## Machine-checkable kill metrics

Supported values for `kill_criteria.metric`:

- `price_le <thr>` — fires when latest close ≤ threshold (dollars)
- `price_ge <thr>` — fires when latest close ≥ threshold (dollars)
- `drop_pct_ge <thr>` — fires when `(close - price_at_pub) / price_at_pub` ≤ -threshold
- `MANUAL` — human evaluates, fires via `cli.py fire`. Use for business
  metrics like LPI, utilization, guidance revisions

## Typical flow

**Enter a call:**
```
python3 cli.py enter \
  --ticker GATX --note interview-prep/02-stock-pitch-GATX.md \
  --direction BUY --date 2026-09-08 --price 178.00 --target 225.00 \
  --horizon 12 --thesis "GABX/Wells Fargo JV unlocks asset-light management economics" \
  --benchmark IWM
```

**Add a kill criterion:**
```
python3 cli.py add-criterion --call-id 1 \
  --description "LPI decelerates below +5% for two consecutive quarters" \
  --metric MANUAL --action EXIT
```

**Daily job (add to launchd):**
```
python3 daily_evaluate.py
```

**Fire a MANUAL criterion (recording obedience):**
```
python3 cli.py fire 3 --obeyed        # obeyed the criterion
python3 cli.py fire 3                 # did NOT obey — omit --obeyed flag
```

**Close a call with attribution:**
```
python3 cli.py close --call-id 1 --status target --date 2026-10-15 --price 225 \
  --reason "hit PT" --attribution THESIS_CORRECT
```

**View the dashboard:**
```
python3 report.py
```

## Backfill in place

Call 001 = GATX v1 pitch (`interview-prep/02-stock-pitch-GATX.md`), inserted
via `backfill_gatx_001.py`. BUY $178 @ 2026-09-08, target $225, 12mo horizon,
3 kill criteria (LPI ≥ +5%, utilization ≥ 95%, management commits to GABX
call option) — all MANUAL. v1 as written contains 3 sell signals, not 5.
Adding 2 more would be retro-fitting.
