# Coder summary — M024 Corrective Capital Reset

## Files modified
- `backend/app/main.py` — +7/-0 lines (m024 startup registration block after m023)

## New files
- `backend/app/db/migrations/m024_corrective_capital_reset.py` — 322 lines

## Deviations from spec
- None

## Commands run
- `git status` → 2 files changed (migration + main.py), CLAUDE.md left unstaged (not in scope)
- `git diff --stat` → 2 files changed, 329 insertions(+)
- `git log --oneline -3`:
  ```
  0210eba M024 corrective capital reset: recalibrate starting/inception/current per spec (user_id=1 only, idempotent)
  42c0c7b chore: add 4-agent dev team pipeline (Planner → Coder → Tester → Reviewer)
  55faa06 Hotfix: m021 was cross-merging across user_ids — partition by user
  ```
- `git diff main..HEAD --stat`:
  ```
  backend/app/db/migrations/m024_corrective_capital_reset.py | 322 +++++++++++++++++++++
  backend/app/main.py                                        |   7 +
  2 files changed, 329 insertions(+)
  ```

## Open questions
- None

## Ready for Tester
YES

---

# Coder summary — M024 Corrective Capital Reset — Iteration 2 (REQUEST_CHANGES fix)

## Issue addressed
Reviewer HIGH: Step 6 acceptance gate used `enabled = 1 AND p.name IN (...)` which
re-selected ALL duplicate enabled rows, not just the canonical MIN(id) row resolved
in Step 2. A duplicate enabled row carrying a stale value caused a false RuntimeError
AFTER the commit already landed — infinite re-entry loop on Railway boot (known-issue #3).

## Files modified
- `backend/app/db/migrations/m024_corrective_capital_reset.py` — Step 6 query only (+10/-5 lines)
  - Built `canonical_alloc_ids = list(name_to_alloc.values())` + `id_params`/`id_placeholders`
  - Replaced WHERE clause with `WHERE a.id IN (:aid0, :aid1, ...)` scoped to canonical set
  - Added inline comment explaining why the old filter was dangerous
- `backend/tests/test_m024_corrective_capital_reset.py` — `test_duplicate_alloc_ids_reported_picks_min` only
  - Flipped from `pytest.raises(RuntimeError)` to expect-success
  - Now asserts: `executed=True`, `duplicate_alloc_ids` present + contains `stock_swing`,
    canonical MIN(id) row carries correct spec value

## New files
- None

## Deviations from spec
- None. Fix is precisely as Reviewer recommended: scope by `name_to_alloc.values()`.

## Commands run
- `python3 -m pytest backend/tests/ -v` → 57 passed in 0.16s (all 57, including flipped test)
- `git log --oneline -3`:
  ```
  f75daf6 M024 fix: scope Step 6 read-back to canonical alloc_ids (Reviewer REQUEST_CHANGES)
  0210eba M024 corrective capital reset: recalibrate starting/inception/current per spec (user_id=1 only, idempotent)
  42c0c7b chore: add 4-agent dev team pipeline (Planner → Coder → Tester → Reviewer)
  ```
- `git diff main..HEAD --stat`:
  ```
  backend/app/db/migrations/m024_corrective_capital_reset.py | 328 +++
  backend/app/main.py                                        |   7 +
  backend/tests/test_m024_corrective_capital_reset.py        | 738 +++++++++++++++++++++
  3 files changed, 1073 insertions(+)
  ```

## Open questions
- None

## Ready for Reviewer
YES
