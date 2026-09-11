# Coverage Monitor

A daily job that runs against the vault, checks EDGAR for new filings on
every covered ticker, checks yfinance for next earnings dates, and flags
"company X filed, your thesis has not been updated in N days."

Zero marginal cost — SEC EDGAR (free, canonical) and yfinance (free).

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
4. Fetches next earnings date from `yfinance.Ticker(symbol).calendar`.
5. Compares filings against `data/state.json` (filings we've seen in prior
   runs). New filings are what raises an alert.

## Alert conditions

- **NEW FILING** — a material filing (10-K/10-Q/8-K/etc.) appeared since
  the last run.
- **NEAR EARNINGS** — next earnings date is within 21 days.
- **STALE THESIS** — thesis is more than 60 days old while the call is
  OPEN.

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
- **yfinance earnings dates are best-effort.** If the calendar returns
  nothing, the report shows "unknown" — better than making up a date.
- **No push notifications built in.** Report goes to stdout + vault. If
  you want a Discord/email nudge on alerts, wrap the script and check the
  exit code.

## What this does NOT do

- Does not fetch or parse filing bodies. Alert points you at the filing;
  you go read it.
- Does not track the peer set. Just names on OPEN v2 calls.
- Does not compute expected vs actual earnings. That's the analyst's job
  once you go read the release.
- Does not enforce anything. If a filing goes unreviewed, no automated
  action happens. It's a scoreboard, not a gatekeeper.
