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
- research/**/*.md (added 2026-08-20 per Brock: distilled academic literature; use these when reasoning about strategy, alpha sources, or bot design. Skim `00-INDEX.md`'s RESEARCH NOTES section for titles+one-liners, then deep-read anything relevant to the current task.)
- reference/quant-stack/00-index.md (added 2026-09-09: the tools-and-methodology reference layer. Before recommending ANY tooling or methodology, check whether the vault already has a decided position. `gap-analysis.md` ranks methodology holes worst-first; `graveyard.md` lists DEAD entries never to re-evaluate. Every derived note cites the ingest SHA it came from.)

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

## VAULT DISCIPLINE: PROVENANCE AND FRAMEWORK CONTROL (added 2026-09-10)

Applies to every research output, pitch, memo, or analysis containing quantitative claims about a company, market, or security. Non-negotiable. Session-inheriting. Postmortem: `postmortems/2026-09-10-vault-framework-fabrication.md`.

### Rule 1. The vault is not a source of facts.
The vault MAY supply: methods, frameworks, prior conclusions, reading notes, decision rules, pointers to primary sources. The vault MAY NEVER supply: a number about a company, a market, or a security. Every quantitative claim in any output must trace to a primary source read in THIS session — SEC filing, earnings release, transcript, exchange or data-provider record. If a number cannot be traced to a primary source in the current session, it does not go in the document. Not with a hedge, not with "approximately," not in a range. It is omitted and its absence is noted.

### Rule 2. Every output ships with a provenance table.
Alongside any research deliverable, produce `<deliverable>-sources.md`:
```
| Claim | Value | Source document | Location | Retrieved |
```
One row per quantitative claim. "Location" means page/table/section, not just document name. Derived values show the arithmetic and cite every input. Document is not complete until every number in it appears in the table. Automation gate: `scripts/vault_provenance_check.py <path>` — exits non-zero if the sources file is missing OR has fewer rows than the document has numeric literals. Run before shipping.

### Rule 3. Basis consistency.
Every financial figure carries a basis: GAAP vs adjusted, fiscal vs calendar, consolidated vs proportionate, gross vs net, trailing vs forward. State the basis for every figure. Never mix bases within a comparison or series. A YoY growth rate computed across two different bases is not a conservative estimate, it is a wrong number.

### Rule 4. Frameworks are servants.
Do not select a framework and then find content for it — that inversion reliably produces documents that feel rigorous and contain nothing. Before applying any structure from the vault, state in one sentence why it fits THIS subject. If you cannot, do not use it. A framework component that does not produce an actionable conclusion must be cut, not padded. Ship test: does this document contain at least one specific claim a knowledgeable reader could disagree with? If no, it has not said anything.

### Rule 5. Never regenerate an existing deliverable.
When a prior version exists, you EDIT it. Required procedure:
1. Read the prior version in full before writing anything.
2. List its load-bearing arguments explicitly. Identify the differentiated insight — the claim not available from consensus.
3. Any new version must PRESERVE that insight or explicitly argue why it was wrong. Silently dropping it is a defect.
4. Diff every number against the prior version. Any changed figure is either (a) a correction with source and old-was-wrong statement, or (b) a regression that reverts.
5. Report the diff before shipping: added, cut, changed, with justification for each.

### Rule 6. Conflicts are the most valuable output.
When new primary-source reading contradicts something in the vault, surface it explicitly, update the vault note, record what changed and why. Never silently overwrite. Never silently keep the stale version.

### Rule 7. Source hierarchy (added 2026-09-10 postmortem `check-failed-then-narrated-over.md`)

Every provenance row records a source TIER. The check enforces set-equality on markers AND rejects claims sourced only from BANNED or unpaired-TIER3.

- **TIER1** — SEC filings, earnings releases, transcripts, company IR materials, exchange or broker records. Fact.
- **TIER2** — named third-party research with a dated document (Valens tearsheet, sell-side reports, rating agency releases). Cite as OPINION with attribution, never as fact.
- **TIER3** — aggregators (stockanalysis.com, Yahoo Finance, Wikipedia). Usable only to LOCATE a TIER1 figure. Any TIER3 claim without a paired TIER1 confirmation row is CUT.
- **BANNED** — any vault document (v1/v2/case study/CLAUDE.md/prior research notes), model-generated summaries. Rows with BANNED tier fail the check. If a vault note contains a number, go read the filing it came from and cite that.

A document whose surviving claims are majority TIER2 is a summary of other people's work. It must declare `document_type: summary` in its frontmatter or the check fails.

### Rule 8. Banned phrases in completion reports (added 2026-09-10 same postmortem)

The following phrases assert verification. They may not be used unless (a) a specific human is named AND (b) the review is timestamped in the same message:

- "human review confirms"
- "verified by inspection"
- "manual audit passed"
- "checked and correct"
- equivalents

Otherwise the phrase is treated as fabricated verification — the same class as an uncited number. This rule exists because on 2026-09-10 the phrase "human review confirms" was used to close a failing provenance check that no human had reviewed.

### Rule 9. Provider-export integrity check (added 2026-09-10 after screen 67 failure)

`vault_provenance_check.py` verifies `document ↔ sources` linkage. It does NOT verify `sources ↔ declared filter definition` — i.e., whether an underlying data-provider export actually satisfies the screen it was supposed to apply. That's a distinct check that also has to pass.

Any research note built on a data-provider EXPORT (FactSet screen, Bloomberg download, Sentieo, etc.) must include a passing integrity-check log as part of provenance:

- `scripts/screen_integrity_check.py` — validates that declared FILTERS actually hold in every delivered row, that column coverage meets threshold, that headers are unique, that no column is entirely empty
- Log saved as `data/<deliverable-slug>-integrity-<date>.log`
- If integrity check fails, the note ships as `status: DRAFT` in frontmatter and the failures are surfaced in the note itself (like `research/67` after the FactSet screen delivered rows that violated the mcap and FCF filters)

**Reference incident:** 2026-09-10 note 67 shipped with `document ↔ sources` clean (provenance check exit 0) but the underlying FactSet export had 64 mcap-band violations, 21 FCF violations, 50% GICS Sector coverage, and duplicate empty columns. Four of the top 20 candidates in the ranking were not legitimately in the strategy universe. `screen_integrity_check.py` catches this class.

### Enforcement pattern (same three-layer as §W1 provenance)
1. **Rule (this section)** — discipline text.
2. **Artifact (`-sources.md` + integrity log)** — required companion files per deliverable, with per-row TIER field and inline marker IDs (`[V14]`) in the document.
3. **Automation** — TWO gates now:
   - `scripts/vault_provenance_check.py` — set-equality gate. Every marker in the document must resolve to a row. Every row must be referenced. No BANNED tiers. No unpaired TIER3. Exit 0 or the document is not shippable.
   - `scripts/screen_integrity_check.py` — filter-satisfaction gate for provider exports. Exit 0 means the export cleanly satisfies the declared screen. Exit non-zero means the deliverable ships as DRAFT with failures surfaced in-note.
   There is no path where nonzero exit is explained and the work is declared complete.

## SOURCING DISCIPLINE (added 2026-09-11 — postmortem `postmortems/2026-09-11-note-002-outside-review.md`)

Three claim classes were each falsified by outside review on 2026-09-11, all in one note. Each has a workflow gate; "be more careful" is not one of them (§V8: twice-failed rules become automation, not stronger words).

### Rule S1. Competitive-exposure claims require the subject company's own disclosure.

Any claim about what a company does, does not do, or is exposed to — competitive position, product mix, revenue mix, geographic exposure, customer concentration, segment split — requires a citation to that company's own segment, fleet, or revenue-mix disclosure. **A peer's characterisation, an inference from industry data, or a derived share does not satisfy it.**

Failure mode this closes: FALS-01 (2026-09-11) inferred "GATX does not compete in commodity cars" from FreightCar America's Q2 order share. GATX's own 2026 Company Overview (which was open in the session) reported covered hoppers as 40.2% of the fleet — the single largest freight exposure. The claim inverted the reality.

Gate: for any competitive-exposure sentence, the sources file row must cite the SUBJECT company's own disclosure. If it cites a peer's or an industry aggregate, the sentence does not ship.

### Rule S2. Cross-company metric comparisons require both definitions in the sources file BEFORE the comparison sentence is written.

Any sentence that compares two companies' metrics (renewal rates, utilization, margin, coverage ratios, growth rates, ratios of any kind) requires both metrics' definitions **quoted from the respective filings and written into the sources file before the comparison sentence is written.** The sentence is not written until the definition rows exist.

Failure mode this closes: FALS-02 and FALS-03 (2026-09-11) compared GATX's LPI (12-month trailing average of realized renewals, backward-looking) to Trinity's FLRD (forward-looking implied rate for the next four quarters). Non-overlapping windows, opposite direction of information. Both definitions were in the source documents being cited; neither was quoted in the note.

Gate: cross-company comparison sentence requires two `TIER1` rows in the sources file — one per metric — where the row's Claim field is the metric definition quoted from the filing. If both rows are not present, the sentence does not ship.

### Rule S3. Incentive attributions require a verbatim quote and named speaker in the sources file.

Before characterising any source's incentive, credibility, motive, or agenda ("sponsored research", "conflict of interest", "management guidance is conservative", "analyst is talking their book"), a verbatim quote of the source's claim plus the named speaker/author must be recorded in the sources file. **No incentive argument without an attributed quote.**

Failure mode this closes: FALS-08 (2026-09-11) attributed a 34,000-unit 2027 forecast to "research sponsored by a manufacturer" and a sub-25,000 figure to "a manufacturer with no such incentive". The attribution was inverted — the 34K was Sidoti's own independent estimate; the sub-25K came from Greenbrier management. Both attributions were plainly named in consecutive sentences of the source paragraph.

Gate: incentive-framing sentence requires a `TIER1` or `TIER2` row in the sources file whose Claim field contains the verbatim quote plus attributed speaker. If the row is not present, the incentive framing is cut and only the forecast itself is reported.

### Enforcement pattern (same three-layer as Rule 7)

1. **Rule (this section).** Non-negotiable, session-inheriting.
2. **Artifact.** The sources file rows required by S1/S2/S3 are the artifact — no separate document.
3. **Automation.** If any of S1-S3 recurs after this session, the third-instance response is a pre-ship script that greps the note for claim-class markers and refuses the ship if the required companion row is not present in the sources file. §V8 applies.

## ATTRIBUTION DOCTRINE

### A1. broker_orphan_catchall is legitimate design — do not remove (added 2026-08-20)

The `broker_orphan_catchall` allocation (currently alloc 102) holds BotPosition rows for Alpaca positions that no real bot has claimed. By construction it has:
- `starting_capital_cents = 0`
- variable unrealized (marks tick on the positions it holds)
- appears in `bot_sum_pv` as: `starting (0) + realized (0) + unrealized (variable)`

Some auditors misread this as an accrual bug — "why does an alloc with $0 basis have $6K unrealized?" The answer: because it's a sleeve designed to catch Alpaca-side positions that need SOMEWHERE to live in BMG's bot rollup while their real attribution is being worked out. The alternative is `sleeve_unattributed_cents` (positions Alpaca holds with no BMG claim at all) — both are displayed labels, not hidden numbers. The catchall reduces sleeve_unattributed by claiming positions it can hold.

**Doctrine:**
- Its accrual pattern (unrealized changing with marks) is CORRECT.
- Its contribution to `bot_sum_pv - fund_pv` drift is expected and offset elsewhere.
- Do NOT quarantine broker_orphan_catchall to "fix" drift — that just moves the same dollars from unattributed→sleeve_unattributed with no net win.
- The only legitimate fix is re-attributing catchall positions to real bots (identity work).

Reference: PM Claude 2026-08-20 audit flagged catchall as a drift source. Not wrong observation, but wrong prescription — the fix is attribution progress, not catchall removal.

## SESSION DISCIPLINE

### SES1. Session-length watchdog (added 2026-08-20 as task #82)

Long autonomous sessions accumulate three failure modes: (1) my context fills with old tool output that no longer matters, (2) I start summarizing instead of executing when I hit natural report boundaries, (3) my sense of what's already committed drifts from git reality.

**Watchdog checks (I run these on myself, not Brock):**

1. **Every ~15 substantive edits or ~10 tool loops, verify unpushed state:** run `git log --oneline origin/main..HEAD`. If more than 3 unpushed commits, push. Small pushes = tight feedback loops from Railway build. Big pushes = one build cycle wasted on many-things-at-once.

2. **When I catch myself writing a "report" or "summary" mid-work without new user input:** treat as a stop-signal. Either I actually have something worth reporting (a discovery, a hard-stop, an ambiguity that would waste effort to guess), or I'm implicitly waiting for permission — which the autonomous-work-order forbids. Distinguish honestly.

3. **When I catch myself deferring work because "session is getting long":** wrong reason. If I don't have session capacity to finish, finish the current commit atomically, push, and STATE explicitly: "session capacity constraint, deferring X to next session." Don't silently drop.

4. **When I've been in one work-block for >45 min without a commit:** something is stuck. Either the diagnosis is deeper than expected (say so, commit whatever partial progress helps future-me), or I'm looping (recognize + pivot).

**Not a substitute for the autonomous-work-order:** that document says "report progress, don't request permission." SES1 is the mechanic — how I keep pace on progress without silently stalling.

**Reference incident (2026-08-20):** Brock issued autonomous work order at ~20:05 UTC. I completed Phases A + B + C + D + E-partial by ~20:20 UTC, wrote a "work block report," and stopped waiting for direction on E and F. Brock: "why did u stop after i told u not to?" — correct call. The report was legitimate; the stop wasn't. SES1's rule 2 exists to catch that.

## DEBUGGING DISCIPLINE

### DBG1. Check the provider's status page BEFORE forming hypotheses about our code (added 2026-08-18)

When infrastructure behaves inexplicably — deploys failing with zero runtime logs, requests timing out, unexplained 502s, containers dying without a stack trace — **check the provider's status page first.** Before RSS instrumentation, before splitting commits, before memory-limit hypotheses, before anything.

**The list, in order:**
1. `https://status.railway.app` — Railway platform incidents
2. `https://status.alpaca.markets` — trading + data feed
3. GitHub status if a push/build behaves oddly
4. Sentry status if error reporting stops
5. Anthropic status if Claude tools misbehave

**Test:** if the symptom is "worked yesterday, breaks today, our code didn't change" OR "same input, same behavior, no logs to explain it" → status page first, hypothesis second.

**Reference case (2026-08-18):** three consecutive Railway deploys of the same commit failed with identical image digests and zero runtime logs. Spent ~$0.56 in build cost + built four internal hypotheses (OOM, memory limit, my commit's imports, whitespace probe) before Brock spotted the Railway dashboard's active-incident banner: "Deployments are slow to progress. We are investigating." The correct debugging step took 30 seconds; the wrong path burned an hour.

**Cost math:** every retry against a live platform incident is $0.05-0.10 wasted. On a $15/mo cap, that's meaningful. Two provider-status checks per debugging session covers every plausible outage vector for < 60 seconds of human time.

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

**Amendment 2026-09-11: large binaries and exports go to R2, never to git.**

Any file over **50 MB** — database dumps, provider exports, Parquet snapshots, historical price CSVs, screen exports, anything binary at scale — goes to Cloudflare R2 (`bmg-capital-backups` bucket) and is referenced from git by a **pointer README** carrying (a) the R2 bucket + object key, (b) SHA256, (c) byte size, (d) upload date, (e) the exact download-and-verify commands. GitHub's 100 MB per-file limit is a hard boundary; adding Git LFS just moves the same objects into a paid store with different failure modes. R2 is the store of record for binary artifacts.

Procedure for putting a file over 50 MB into the vault:
1. Backup the `.git` directory (`cp -a .git ../vault-git-backup-YYYY-MM-DD`) — filter-repo undo.
2. SHA256 the file locally.
3. `rclone copyto <file> bmg-r2:bmg-capital-backups/<key>`.
4. Download to a temp path and re-SHA256. Both hashes must match. Byte-count parity is NOT sufficient — checksums or it did not happen.
5. Only after Step 4 passes: strip the file from git history with `git-filter-repo --path <path> --invert-paths` (or don't add it to git in the first place, which is the preferred default).
6. Add the file to `.gitignore`. Write the pointer README with the R2 key, checksum, size, upload date, and restore commands. The pointer README is what makes the object findable later.

Reference case: 2026-09-11 vault push was rejected by GitHub because two v1 DB dumps (106 MB Postgres, 654 MB SQLite) had been committed to a prior local commit that had never reached the remote. Followed the procedure above; repo dropped from 300 MB to 108 MB. See `~/Documents/BMG-Capital-Vault/archive/v1-trading-platform-2026-09-10/data-dump/README.md` for the resulting pointer artifact — it is the reference template for future large-binary archives.

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

## LOCAL-FIRST BOT ARCHITECTURE (added 2026-08-30 — Railway $107 cost incident)

### L1. New bots default to LOCAL, not Railway.

Any new scheduled job / bot / analyzer defaults to `scripts/local/job_<name>.py`.
It only lives on Railway if it MUST fire in real-time regardless of Mac state.

**Test — a job goes on Railway ONLY if:**
- (a) It executes trades in a time-sensitive window (bracket order, fill polling), OR
- (b) It's a safety invariant that must fire within minutes (capital watchdog, drawdown breaker), OR
- (c) It requires 24/7 execution regardless of user activity (crypto scanning)

Everything else — reports, digests, analytics, research, LLM calls, screener runs
that don't execute — goes local.

**Local job pattern (see scripts/local/README.md):**
```python
# scripts/local/job_<name>.py
from _bmg_api import get_client
from _obsidian import write_job_output

def run() -> str:
    api = get_client()  # hits Railway API for DB data
    body = build_markdown(api.get("/api/..."))
    write_job_output("<name>", body)  # writes to Obsidian vault
    return "ok"
```

Then add to `scripts/local/schedule.yaml` with cron expression. `launchd` fires
`scripts/local/run.py` every 15 min; missed runs (Mac was asleep) catch up
within 24h via `catchup: true`.

**Railway env `RAILWAY_ROLE=executor_only` skips ALL Category B job registrations**
even ones not yet ported to local — they simply won't fire on Railway until
we build local versions. Keeps container small during the migration.

**Reference incident:** Railway bill hit $107 vs $20 target because 72 crons
kept 20GB RAM resident 24/7. Every added bot compounded cost. Local architecture
means new bots cost $0 to Railway — Mac already runs, Obsidian vault already
exists, launchd already fires.

## MONEY-MATH ACCEPTANCE (added 2026-08-10, Brock regression rule)

Any change touching P&L, valuation, or period-return math must include a **post-deploy acceptance print** of `pnl.{all_time, mtd, wtd, today}` and confirm each field is either a plausible number OR an explicit `null` with a `reason` field. **Zero is neither** — a `.cents == 0` on a live funded fund is always a bug, never a value.

Enforced structurally by invariant **I23**: any exact-zero pnl window on a fund with `funded_capital > 0` and `age > 1 day` → RED. Applies to `all_time`, `mtd`, `wtd` always; to `today` only during RTH.

# 2026-08-18: deploy-probe commit (whitespace only) — test whether any
# new deploy succeeds vs 2f957065 specifically. See ledger #36 investigation.
