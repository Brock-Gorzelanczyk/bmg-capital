---
description: Run the full Planner → Coder → Tester → Reviewer pipeline on a feature request
argument-hint: <feature description>
---

# Ship Feature Pipeline

You are orchestrating the 4-agent dev team for BMG Capital. Feature request:

**$ARGUMENTS**

# Pipeline steps — execute in strict order

## 0. Setup

1. Verify current directory is the BMG repo root (check for CLAUDE.md and ~/Documents/BMG-Capital-Vault/ existence)
2. Verify on a clean working branch — if main is dirty, ask Brock if you should create a feature branch or stash
3. Create feature branch: `git checkout -b feature/$(date +%Y%m%d-%H%M)-<short-slug>` where short-slug is 2-3 words from the feature request
4. Wipe `.pipeline/` folder contents (but keep the folder + .gitignore)
5. Print: "Pipeline started. Feature: $ARGUMENTS"

## 1. Planner

1. Dispatch the `planner` agent with $ARGUMENTS as the feature request
2. Wait for completion
3. Verify `.pipeline/01-spec.md` exists and has content
4. If Planner wrote "QUESTIONS — needs Brock input before continuing", STOP and show the questions to Brock. Do not continue until Brock answers.
5. Print Planner's spec summary (first 10 lines of `.pipeline/01-spec.md`)
6. Print: "Planner complete. Spec at .pipeline/01-spec.md"

## 2. Coder

1. Dispatch the `coder` agent
2. Wait for completion
3. Verify `.pipeline/02-changes.md` exists with "Ready for Tester: YES"
4. If "Ready for Tester: NO", show the Coder's open questions to Brock. Do not continue.
5. Print files modified and line counts from `.pipeline/02-changes.md`
6. Print: "Coder complete. Changes at .pipeline/02-changes.md"

## 3. Tester

1. Dispatch the `tester` agent
2. Wait for completion
3. Verify `.pipeline/03-tests.md` exists with "Ready for Reviewer: YES"
4. If "Ready for Reviewer: NO" (tests failing), show test failures to Brock. Ask: dispatch Coder again to fix, or kill the pipeline?
5. Print test count and pass/fail summary
6. Print: "Tester complete. Tests at .pipeline/03-tests.md"

## 4. Reviewer

1. Dispatch the `reviewer` agent
2. Wait for completion
3. Verify `.pipeline/04-review.md` exists with a VERDICT line
4. Read the verdict
5. Print the full verdict to chat

## 5. Final action based on verdict

- **APPROVE** — Print: "Reviewer approved. Awaiting Brock's merge command." Show Brock the merge command from `.pipeline/04-review.md`. Do NOT auto-merge.
- **REQUEST_CHANGES** — Print: "Reviewer requested changes. Issues:" + list. Ask Brock: dispatch Coder to fix these specific items, or kill the pipeline?
- **REJECT** — Print: "Reviewer rejected the work. Reason:" + reasoning. Ask Brock: dispatch Planner to rewrite spec, or kill the pipeline?

# Logging

After each agent completes, post a one-line status update to chat so Brock can monitor:
- "✅ Planner complete (X questions, Y file paths)"
- "✅ Coder complete (X files modified, +Y/-Z lines)"
- "✅ Tester complete (X tests passed, Y failed)"
- "✅ Reviewer complete: APPROVE / REQUEST_CHANGES / REJECT"

# Error handling

- If any agent fails to write its pipeline file, STOP and report which agent + error
- If git operations fail (dirty branch, conflicts), STOP and ask Brock
- If a test framework isn't found, ask Brock for which to use

# What this command does NOT do

- Does NOT merge to main (always requires Brock's explicit greenlight)
- Does NOT deploy to Railway (separate workflow)
- Does NOT skip agents — every feature goes through all 4
- Does NOT proceed past failures silently

# Quick mode

If Brock prefixes the request with `/quick`, skip the Tester step (Planner → Coder → Reviewer only). Use sparingly for tiny changes.
