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
