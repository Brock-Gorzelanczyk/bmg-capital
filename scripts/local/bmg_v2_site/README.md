# BMG Capital v2 — Public Equity Research Site

Static site generator for the public research portfolio. Renders published
notes from the Obsidian vault as HTML, tracks calls against a benchmark,
and documents the process.

## Design

- **Source of truth: the vault.** Notes live in `~/Documents/BMG-Capital-Vault/research/`
  with YAML frontmatter. The build reads them directly. No database.
- **Git is the ledger.** Publishing = a commit in the vault repo. The commit
  timestamp IS the publication date. Corrections are new commits.
- **Prices are refreshed daily.** `daily_prices.py` writes `data/prices.json`
  with a `fetched_at` timestamp. The Track Record page shows the timestamp.
- **Four pages, no more.** Landing, Research Library, Track Record, Process.

## Structure

```
scripts/local/bmg_v2_site/
├── build.py            # main static generator
├── daily_prices.py     # cron: pull latest + pub-day close for every call
├── templates/          # jinja2 layouts
│   ├── base.html
│   ├── landing.html
│   ├── library.html
│   ├── track_record.html
│   ├── process.html
│   └── note.html       # per-note rendered page
├── static/
│   └── style.css       # mobile-first, minimal
├── data/
│   └── prices.json     # produced by daily_prices.py (gitignored)
└── out/                # generated site (gitignored)
```

## Publishing a new call

1. Create `~/Documents/BMG-Capital-Vault/research/NNN-TICKER.md` with the frontmatter:
   ```yaml
   ---
   ticker: XYZ
   direction: BUY
   published_price: 42.50
   price_target: 55.00
   horizon_months: 12
   benchmark: IWM
   conviction: 4
   thesis: "one line — the specific claim being made"
   kill_criteria:
     - "specific observable that would invalidate the thesis"
     - "another one"
   status: OPEN
   ---
   ```
2. Write the note body in markdown.
3. Commit the file to the vault repo:
   ```
   cd ~/Documents/BMG-Capital-Vault
   git add research/NNN-TICKER.md
   git commit -m "publish call NNN: XYZ BUY \$42.50 -> \$55 (12mo)"
   ```
4. Rebuild the site:
   ```
   cd ~/my-new-project/scripts/local/bmg_v2_site
   python3 build.py
   ```

## Closing a call

Add these fields to the frontmatter:
```yaml
status: CLOSED_TARGET   # or CLOSED_KILL, CLOSED_HORIZON, CLOSED_MANUAL
closed_price: 55.20
closed_reason: "hit price target on X quarter results"
thesis_attribution: THESIS_CORRECT  # or RIGHT_WRONG_REASON | WRONG | UNRESOLVED
```
`RIGHT_WRONG_REASON` is a miss, not a win. It gets recorded as luck.

Commit and rebuild.

## Correcting a published note

Commit a NEW change, referencing the original. Never `git commit --amend` or
`git push --force` a published note. The history is the credibility.

## Daily job

Wire `daily_prices.py` into launchd (or cron) to run once a day after market
close. It reads all v2 calls from the vault, fetches prices for each ticker
+ benchmark, and writes `data/prices.json`. Rebuild the site after.

```
# Example crontab entry
0 17 * * 1-5 cd ~/my-new-project/scripts/local/bmg_v2_site && python3 daily_prices.py && python3 build.py
```

## Deployment

The `out/` folder is a fully static site. Deploy anywhere:

- **GitHub Pages**: push `out/` to a `gh-pages` branch of a new repo
- **Cloudflare Pages**: direct upload from `out/`
- **Netlify**: same
- **Local test**: `python3 build.py --serve` → http://localhost:8000

## Anti-pattern guard

No Sharpe / t-stat / IR / significance test in this codebase. Counts and
honest descriptions only. "X of Y" not "60%".
