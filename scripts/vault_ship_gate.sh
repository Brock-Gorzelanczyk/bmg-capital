#!/usr/bin/env bash
# vault_ship_gate.sh — the pre-ship gate for any vault research deliverable.
#
# Runs, in order:
#   1. scripts/vault_provenance_check.py   (Rule 7 — marker-to-sources set equality)
#   2. scripts/local/falsified_audit.py    (falsified-claim audit)
#   3. scripts/local/state_current_regen.py --shipped <path>  (state write)
#   4. commit state/current.md in the vault
#
# Optional gates, run separately when the deliverable is a screen (provider export):
#   scripts/screen_integrity_check.py  (Rule 9 — filter satisfaction)
#
# Exit 0 = shippable AND state was rewritten. Any non-zero exit = NOT shippable.
#
# CLAUDE.md Rule 7 forbids "explaining away" a non-zero exit in prose. If any
# gate fails, the deliverable does not ship and state is not touched.
#
# Rationale for stage 3+4 (2026-09-12):
#   TEST 3 proved the "SESSION END — rewrite state/current.md" trigger in
#   CLAUDE.md has never fired in the state file's lifetime. Per §V8 the
#   response is automation, not a stronger rule. State now updates whenever
#   work actually ships, rather than depending on someone noticing the
#   session ended.
#
# Usage:
#     scripts/vault_ship_gate.sh path/to/note.md

set -u

if [ $# -lt 1 ]; then
    echo "usage: $0 <path-to-doc.md>" >&2
    exit 64
fi

DOC="$1"

if [ ! -f "$DOC" ]; then
    echo "[fail] doc not found: $DOC" >&2
    exit 3
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAULT_ROOT="${VAULT_ROOT:-$HOME/Documents/BMG-Capital-Vault}"

echo "=== Gate 0/4: position disclosure check (M17) ==="
# Every research note with v2 frontmatter must have position_disclosed_since
# set to an ISO date, NONE, or UNVERIFIED. Blank or UNVERIFIED fails.
# Filed 2026-09-13 after ORCL 005 opened coverage on an asserted-but-
# unverified position. See reference/method/M17.md.
POS_LINE="$(grep -E '^position_disclosed_since:' "$DOC" | head -1 | sed 's/^position_disclosed_since:[[:space:]]*//' | tr -d '\"' | tr -d "'" | sed 's/[[:space:]]*$//')"
if [ -z "$POS_LINE" ]; then
    # Only enforce for notes that also have a position field — coverage /
    # research helpers without position frontmatter are exempt.
    if grep -qE '^position:' "$DOC"; then
        echo "[FAIL] position_disclosed_since is blank — must be ISO date, NONE, or UNVERIFIED (M17)"
        exit 30
    fi
elif [ "$POS_LINE" = "UNVERIFIED" ]; then
    echo "[FAIL] position_disclosed_since is UNVERIFIED — brokerage-record check required before ship (M17)"
    exit 30
elif [ "$POS_LINE" = "TBD-BROCK-TO-CONFIRM" ]; then
    echo "[FAIL] position_disclosed_since is a placeholder — replace with ISO date or NONE per M17 verification"
    exit 30
elif echo "$POS_LINE" | grep -qE '^TBD|^PENDING$|^UNKNOWN$'; then
    echo "[FAIL] position_disclosed_since is a placeholder ($POS_LINE) — replace with ISO date, NONE, or UNVERIFIED per M17"
    exit 30
else
    # Accepts ISO date (past OR future — future dates paired with
    # position: OPENING per M17 for queued-order publications).
    echo "[ok]   position_disclosed_since = $POS_LINE"
fi
echo

echo "=== Gate 0b/4: calibration parameters check (M22) ==="
# Every rated call (direction: BUY | SELL | HOLD, status: OPEN)
# must carry the seven M22 calibration fields at ship time, with
# benchmark_entry_date == entry_price_date. Missing or mismatched
# fields fail the gate.
#
# Rated notes are identified by presence of `direction:` field in
# frontmatter with value BUY, SELL, or HOLD.

DIRECTION_LINE="$(grep -E '^direction:' "$DOC" | head -1 | sed 's/^direction:[[:space:]]*//' | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*$//')"

if echo "$DIRECTION_LINE" | grep -qiE '^(BUY|SELL|HOLD)$'; then
    STATUS_LINE="$(grep -E '^status:' "$DOC" | head -1 | sed 's/^status:[[:space:]]*//' | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*$//')"
    if [ "$STATUS_LINE" = "OPEN" ]; then
        M22_ERRORS=0
        for field in benchmark benchmark_entry benchmark_entry_date entry_price_date horizon_months evaluation_date thesis_mechanism parameters_set_retroactively; do
            if ! grep -qE "^${field}:" "$DOC"; then
                echo "[FAIL] M22 field missing: $field"
                M22_ERRORS=$((M22_ERRORS + 1))
            fi
        done
        # entry_price_date == benchmark_entry_date (calibration anchor date)
        ENTRY_DATE="$(grep -E '^entry_price_date:' "$DOC" | head -1 | sed 's/^[^:]*:[[:space:]]*//' | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*$//')"
        BENCH_DATE="$(grep -E '^benchmark_entry_date:' "$DOC" | head -1 | sed 's/^[^:]*:[[:space:]]*//' | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*$//')"
        if [ -n "$ENTRY_DATE" ] && [ -n "$BENCH_DATE" ] && [ "$ENTRY_DATE" != "$BENCH_DATE" ]; then
            echo "[FAIL] M22 date-basis mismatch: entry_price_date=$ENTRY_DATE != benchmark_entry_date=$BENCH_DATE"
            M22_ERRORS=$((M22_ERRORS + 1))
        fi
        if [ $M22_ERRORS -gt 0 ]; then
            echo "[FAIL] Gate 0b failed with $M22_ERRORS M22 error(s) — document is NOT shippable."
            exit 22
        fi
        echo "[ok]   M22 fields present; benchmark_entry_date=$BENCH_DATE matches entry basis."
    else
        echo "[skip] status=$STATUS_LINE (M22 applies to status:OPEN rated calls)"
    fi
else
    echo "[skip] direction=$DIRECTION_LINE (M22 applies to rated BUY/SELL/HOLD notes)"
fi
echo

echo "=== Gate 1/4: provenance check (marker set equality) ==="
python3 "$REPO_ROOT/scripts/vault_provenance_check.py" "$DOC"
GATE1=$?
echo

echo "=== Gate 2/4: falsified-claim audit ==="
python3 "$REPO_ROOT/scripts/local/falsified_audit.py" "$DOC"
GATE2=$?
echo

echo "=== Gate 3/4: derivation arithmetic check ==="
python3 "$REPO_ROOT/scripts/local/derivation_check.py" "$DOC"
GATE3=$?
echo

# --- Gate 3.5: per-artifact audit (M19) ---
# Every path listed under `artifacts:` in the note's frontmatter is a
# downstream deliverable and must pass the same falsified-claim audit as
# the source note, plus the artifact_consistency check for
# headline/table multiple drift. A correction applied to the source note
# is not propagated until the downstream artifact re-passes.
#
# Frontmatter form:
#   artifacts:
#     - deliverables/foo/foo-one-pager.html
#     - deliverables/foo/foo-deck.pdf
# Paths are relative to $VAULT_ROOT.
#
# Filed 2026-09-13 after GATX one-pager v5 carried FALS-02, FALS-04, and
# a 20x/17.8x multiple drift for two days after source-note correction.
# See reference/method/M19.md.

GATE_ARTIFACTS=0
ARTIFACT_PATHS="$(awk '
    /^artifacts:/ { in_arts = 1; next }
    in_arts && /^  *- / { sub(/^  *- */, ""); print; next }
    in_arts && /^[^ ]/ { in_arts = 0 }
' "$DOC")"

if [ -n "$ARTIFACT_PATHS" ]; then
    echo "=== Gate 3.5/4: downstream artifact audit (M19) ==="
    while IFS= read -r rel_path; do
        [ -z "$rel_path" ] && continue
        abs_path="$VAULT_ROOT/$rel_path"
        if [ ! -f "$abs_path" ]; then
            echo "[fail] artifact registered in frontmatter not found: $rel_path"
            GATE_ARTIFACTS=2
            continue
        fi
        echo "  --- artifact: $rel_path"
        python3 "$REPO_ROOT/scripts/local/falsified_audit.py" "$abs_path"
        A_FALS=$?
        python3 "$REPO_ROOT/scripts/local/artifact_consistency.py" "$abs_path" --quiet
        A_CONS=$?
        if [ $A_FALS -ne 0 ] || [ $A_CONS -ne 0 ]; then
            echo "[fail] artifact $rel_path failed: falsified_audit=$A_FALS consistency=$A_CONS"
            GATE_ARTIFACTS=2
        fi
    done <<< "$ARTIFACT_PATHS"
    if [ $GATE_ARTIFACTS -eq 0 ]; then
        echo "[ok]   all registered artifacts passed falsified_audit + consistency."
    fi
    echo
fi

if [ $GATE1 -ne 0 ] || [ $GATE2 -ne 0 ] || [ $GATE3 -ne 0 ] || [ $GATE_ARTIFACTS -ne 0 ]; then
    echo "[FAIL] ship gate stopped after checks: provenance=$GATE1 falsified_audit=$GATE2 derivation=$GATE3 artifacts=$GATE_ARTIFACTS"
    echo "       state/current.md NOT rewritten — document is not shippable."
    if [ $GATE1 -ne 0 ]; then exit $GATE1; fi
    if [ $GATE2 -ne 0 ]; then exit $GATE2; fi
    if [ $GATE3 -ne 0 ]; then exit $GATE3; fi
    exit $GATE_ARTIFACTS
fi

# --- Stage 3: rewrite state/current.md ---------------------------------
# Compute the shipped path relative to the vault so the state file records
# a portable reference.
DOC_ABS="$(cd "$(dirname "$DOC")" && pwd)/$(basename "$DOC")"
case "$DOC_ABS" in
    "$VAULT_ROOT"/*)
        SHIPPED_REL="${DOC_ABS#$VAULT_ROOT/}"
        ;;
    *)
        SHIPPED_REL="$DOC_ABS"
        ;;
esac

echo "=== Stage 4/5: rewrite state/current.md ==="
python3 "$REPO_ROOT/scripts/local/state_current_regen.py" \
    --vault "$VAULT_ROOT" \
    --shipped "$SHIPPED_REL"
STAGE3=$?
echo

if [ $STAGE3 -ne 0 ]; then
    echo "[FAIL] state rewrite failed with exit $STAGE3 — refuse to declare ship."
    exit $STAGE3
fi

# --- Stage 4: commit state/current.md in the vault ---------------------
echo "=== Stage 5/5: commit state/current.md ==="
if [ ! -d "$VAULT_ROOT/.git" ]; then
    echo "[warn] $VAULT_ROOT is not a git repo — state was rewritten but not committed."
    exit 0
fi

cd "$VAULT_ROOT" || { echo "[fail] cannot cd to vault"; exit 3; }

# Only stage state/current.md — never sweep other uncommitted changes into
# this commit. If the user has research/ edits waiting, those are theirs to
# commit.
if git diff --quiet -- state/current.md && git diff --cached --quiet -- state/current.md; then
    echo "[ok]   no state/current.md changes to commit (already current)."
    exit 0
fi

git add state/current.md
git commit -m "state: shipped $SHIPPED_REL via vault_ship_gate.sh" >/dev/null
COMMIT_RC=$?
if [ $COMMIT_RC -ne 0 ]; then
    echo "[fail] git commit returned $COMMIT_RC"
    exit $COMMIT_RC
fi
NEW_SHA="$(git rev-parse --short HEAD)"
echo "[ok]   committed state/current.md at $NEW_SHA"
echo
echo "[OK]   ship gate passed — provenance clean, falsified-audit clean, state rewritten + committed."
exit 0
