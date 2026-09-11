# Coverage Monitor

A daily job that runs against the vault, checks EDGAR for new filings on
every covered ticker, and flags "company X filed, your thesis has not been
updated in N days." Alerts split into two tiers (parallel to the invariant
engine's safety-vs-reporting split): SAFETY alerts individually (10-K/Q,
8-K, 13D/G, S-1/3, 424B, DEF 14A, Form 4 open-market purchase, insider
selling cluster, stale thesis) and REPORTING roll up (routine Form 4s).

Zero marginal cost — SEC EDGAR only.

## What it does

For every ticker with an OPEN v2 call in the vault (`research/*.md` with the
BMG v2 frontmatter — `ticker`, `direction`, `published_price`):

1. Resolves the ticker to its SEC CIK via `company_tickers.json` (cached
   locally for 7 days).
2. Reads the note file's most recent git commit timestamp = thesis update
   age in days.
3. Fetches recent filings from `data.sec.gov/submissions/CIK{padded}.json`.
   Only tracks material filing types: 10-K, 10-Q, 8-K, S-1/3, 424B, DEF 14A,
   13D/G, Form 4.
4. Parses Form 4 XML for open-market purchases (code=P) and insider selling
   clusters (3+ distinct insiders, code=S, within a 30-day window,
   excluding 10b5-1 plans and tax withholding).
5. Compares filings against `data/state.json` (filings we've seen in prior
   runs). New filings are what raises an alert.

## Alert tiers

The monitor splits alerts into two tiers so the individual alerts stay
signal-heavy:

**SAFETY (individual alerts, prominent):**
- **NEW MATERIAL FILING** — 10-K, 10-Q, 8-K, 13D/G, DEF 14A, S-1/3, 424B
  appeared since the last run.
- **INSIDER PURCHASE** — a Form 4 with transaction code P (open-market
  purchase). Rare, high-signal.
- **INSIDER SELLING CLUSTER** — 3+ distinct insiders selling (code=S)
  within a 30-day window, excluding 10b5-1 planned sales and code=F tax
  withholding.
- **STALE THESIS** — thesis is more than 60 days old while the call is
  OPEN.

**REPORTING (summary lines, no alerts):**
- Individual Form 4s from routine vesting, 10b5-1 sales, tax withholding.
- Filings the monitor has already seen in prior runs.
- Historical context.

## Why no yfinance earnings date

An earlier draft called `yfinance.Ticker(symbol).calendar` and alerted
NEAR EARNINGS when the next date was within 21 days. Removed 2026-09-10
because:
1. yfinance is an unofficial scraper — the earnings date field has broken
   more than once and returns silently-wrong data when Yahoo restructures
   its HTML.
2. Earnings-date "kill by 2026-10-27" is a calendar-based invalidation.
   Vault research/001-GATX.md now specifies event-based criteria only
   ("Q3 2026 EPS below $2.20" — no date). The monitor's job is to watch
   for the SEC filing when it comes (8-K "Sets Date for..." plus the
   actual earnings 8-K), not to guess when.

The status line shows "TBD (watching for announcement 8-K)" until an
8-K sets the date, at which point the analyst reads it and updates the
note.

## Output

- **stdout**: readable report, alerts prominently at top.
- **`~/Documents/BMG-Capital-Vault/coverage-status.md`**: same content in
  the vault so you can read it in Obsidian.
- **exit code**: 0 = no alerts, 1 = staleness/earnings alerts, 2 = new
  filings present. Cron / launchd can use the exit code to decide whether
  to send a push notification.

## Files

- `check.py` — main entry
- `data/company_tickers.json` — SEC ticker → CIK cache
- `data/state.json` — last-check timestamp + set of seen accession numbers

## Usage

```bash
python3 check.py
```

Cron entry (runs at 09:15 CT weekdays, after SEC's overnight batch):
```
15 9 * * 1-5 cd /path/to/scripts/local/coverage_monitor && python3 check.py
```

Or macOS launchd — plist template in `com.bmg.coverage_monitor.plist.sample`
if we build one later.

## Design decisions worth flagging

- **State lives in `data/state.json`, not SQLite.** A dict of {ticker:
  [accession_numbers]} is trivially small and human-inspectable.
- **The vault is the coverage list.** No separate config file for tickers.
  If it's in an OPEN v2 note, it's covered. Delete the note or close the
  call → the ticker drops from coverage on the next run.
- **Rate limit**: 100ms sleep between SEC calls (~10 req/sec upper bound
  per SEC access policy). User-Agent set per SEC requirement.
- **No push notifications built in.** Report goes to stdout + vault. If
  you want a Discord/email nudge on alerts, wrap the script and check the
  exit code.

## yfinance blast radius

`yfinance` is an unofficial Yahoo Finance scraper. Yahoo has broken it
multiple times without notice, and the fields it exposes (especially
`.calendar`) sometimes return silently-wrong data.

**Current blast radius in this project:** ZERO as of 2026-09-10.

- `check.py` — was using `yfinance.Ticker(symbol).calendar` for the next
  earnings date. Removed 2026-09-10. Replaced with an SEC-only workflow:
  the monitor watches for the "Sets Date for Q_ Earnings Release" 8-K,
  the earnings-release 8-K itself, and the 10-Q that follows.
- `scripts/local/bmg_v2_site/daily_prices.py` — was the other yfinance
  caller. Migrated to Alpaca Market Data v2 (IEX feed on free tier) on
  2026-09-10.

**Do not reintroduce yfinance.** For prices, use Alpaca. For earnings
dates, use the SEC 8-K plus the company's own IR page — the company
files the announcement itself.

## What this does NOT do

- Does not fetch or parse filing bodies. Alert points you at the filing;
  you go read it.
- Does not track the peer set. Just names on OPEN v2 calls.
- Does not compute expected vs actual earnings. That's the analyst's job
  once you go read the release.
- Does not enforce anything. If a filing goes unreviewed, no automated
  action happens. It's a scoreboard, not a gatekeeper.
