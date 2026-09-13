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

if [ $GATE1 -ne 0 ] || [ $GATE2 -ne 0 ] || [ $GATE3 -ne 0 ]; then
    echo "[FAIL] ship gate stopped after checks: provenance=$GATE1 falsified_audit=$GATE2 derivation=$GATE3"
    echo "       state/current.md NOT rewritten — document is not shippable."
    if [ $GATE1 -ne 0 ]; then exit $GATE1; fi
    if [ $GATE2 -ne 0 ]; then exit $GATE2; fi
    exit $GATE3
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
