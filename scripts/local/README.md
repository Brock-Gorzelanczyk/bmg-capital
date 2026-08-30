# Local Job Runner

**Why:** the Obsidian-brain architecture. Analytics/reports/research run on
Brock's Mac instead of Railway, cutting the Railway bill from $107/mo to
~$5-10/mo without giving up any features. See vault:context for background.

## Architecture

```
┌─── RAILWAY (small, always-on) ──────────────┐
│  Web frontend + trade executor + Alpaca     │
│  reconciliation + DB + API                  │
│  RAILWAY_ROLE=executor_only  →  skips       │
│  Category B jobs at scheduler.py startup    │
└─────────────────────────────────────────────┘
                    ↑ HTTPS API calls
                    │
┌─── MAC (scripts/local/) ────────────────────┐
│  launchd fires run.py every 15 min          │
│  run.py checks schedule.yaml                │
│  Runs due jobs → writes to Obsidian         │
└─────────────────────────────────────────────┘
                    ↓ markdown files
┌─── OBSIDIAN VAULT ──────────────────────────┐
│  context/local-jobs/YYYY-MM-DD-*.md         │
│  All analytics history, git-backed          │
└─────────────────────────────────────────────┘
```

## Install (one-time)

Prereqs on Mac:
- Python 3.9+ (`python3 --version`)
- Railway CLI (`brew install railway` + `railway link` in project root)
- Obsidian vault at `~/Documents/BMG-Capital-Vault/` (already there)

```bash
bash scripts/local/install_launchd.sh
```

Verify:
```bash
launchctl list | grep bmg
# should show: com.bmg.localjobs

python3 scripts/local/run.py --list
# should show configured jobs

python3 scripts/local/run.py --job job_daily_recap
# should write ~/Documents/BMG-Capital-Vault/context/local-jobs/YYYY-MM-DD-daily_recap.md
```

## Adding a new job

1. Create `scripts/local/job_<name>.py` with:
   ```python
   from _bmg_api import get_client
   from _obsidian import write_job_output

   def run() -> str:
       api = get_client()
       # ... do work ...
       write_job_output("my_job", markdown_body)
       return "ok"
   ```

2. Add to `schedule.yaml`:
   ```yaml
   - name: job_my_name
     cron: "0 10 * * 1-5"
     catchup: true
     description: what it does
   ```

That's it. Next `run.py` tick picks it up.

## When Mac is asleep

`catchup: true` in schedule.yaml means missed runs are picked up on next tick
(within 24h). Sleep 8am → wake 6pm → morning_brief (7:30am) fires at 6:15pm.

For jobs that MUST fire at a specific time regardless (e.g. 2am ET DB rollup),
keep them on Railway.

## Uninstall

```bash
bash scripts/local/uninstall_launchd.sh
```

## Debugging

```bash
tail -f ~/Library/Logs/bmg-localjobs.log
tail -f ~/Library/Logs/bmg-localjobs.err
python3 scripts/local/run.py --dry-run  # show what would run right now
```

## Category A jobs (STILL on Railway)

These MUST stay always-on:
- Execution: confluence_executor_tick, market_scan, options_scan, crypto_automation, strategy_signal_scan, bot_execution
- Safety: capital_invariant_watchdog, drawdown_circuit_breaker, portfolio_equity_snapshot, auto_pause_degraded
- Reconciliation: broker_reconcile_daily, bar_cache_evict
- Rollup (unreliable on Mac): compute_bot_stats_daily (2am), compute_ic_metrics_daily (2:30am), populate_blackouts_daily (5am)
- Pipeline: candidate_pipeline_worker (60s)
- Memory: memory_janitor (added 2026-08-30)

## Category B jobs (MOVED to local)

Currently ported:
- daily_recap
- morning_brief
- weekly_promotion (includes rule scorecard)

Not-yet-ported (still fire on Railway until we build local versions):
- offhours_check, ta_pattern_daily, autonomous_digest, tax_scan
- research_job, learning_job, journal_job, quarterly_review_job, money_job
- daily_autonomous_recap, llm_log_retention, relay_health_monitor

**When `RAILWAY_ROLE=executor_only` is set on Railway, ALL Category B jobs
skip registration** — even not-yet-ported ones. They'll just silently not
fire until we port them. Fine for MVP; we'll port more as needed.
