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
