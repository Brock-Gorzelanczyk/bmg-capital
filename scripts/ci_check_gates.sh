#!/usr/bin/env bash
# ci_check_gates.sh — grep-based enforcement that any file constructing
# BotTrade(...) or BotPosition(...) also imports the corresponding gate.
#
# Ledger #32 Layer 2 (Brock 2026-08-10): "any new BotTrade / BotPosition
# / submit_order call site that doesn't import the corresponding gate"
# fails the build. Catches the class of failure that let the 2026-07 sim
# leak run for a month and the 2026-08-07 SNOW-catchall pass the risk gate.
#
# Approach: pure text grep. No AST parsing. Files exempt from the check:
#   - the gate modules themselves (obviously)
#   - the model definitions (class BotTrade(Base) is the tablename)
#   - tests (they intentionally exercise unguarded paths)
#
# Exit codes:
#   0 = every constructor call site has a corresponding gate import
#   1 = at least one file violates; details on stderr

set -euo pipefail

ROOT="${1:-$(pwd)}"
FAIL=0

# Files exempt from BotTrade check
_TRADE_EXEMPT=(
    "backend/app/services/trade_write_gate.py"
    "backend/app/db/models/bots.py"
    # regime_tag.py: helper module — the only BotTrade( match is in a docstring
    # code example. It doesn't actually construct BotTrade.
    "backend/app/services/regime_tag.py"
)
# Files exempt from BotPosition check
_POS_EXEMPT=(
    "backend/app/services/position_write_gate.py"
    "backend/app/db/models/bots.py"
)

_is_exempt() {
    local file="$1"; shift
    for e in "$@"; do
        [[ "$file" == *"$e" ]] && return 0
    done
    # Tests, migrations that reference class only, __pycache__
    [[ "$file" == *"/tests/"* ]] && return 0
    [[ "$file" == *"/__pycache__/"* ]] && return 0
    return 1
}

echo "[gate-check] scanning under $ROOT ..."

# Every .py file that CONSTRUCTS a BotTrade — must import trade_write_gate
while IFS= read -r file; do
    _is_exempt "$file" "${_TRADE_EXEMPT[@]}" && continue
    if grep -qE '(from\s+app\.services\.trade_write_gate\s+import|import\s+app\.services\.trade_write_gate)' "$file"; then
        continue
    fi
    # No import — this is a violation UNLESS the BotTrade( is inside a comment/docstring only
    if grep -nE '(^|[^A-Za-z_])BotTrade\s*\(' "$file" | grep -vE '^\s*[0-9]+:\s*#|^\s*[0-9]+:\s*"""' | grep -q .; then
        echo "FAIL: $file constructs BotTrade(...) but does NOT import trade_write_gate" >&2
        grep -nE 'BotTrade\s*\(' "$file" | head -5 | sed 's/^/  /' >&2
        FAIL=1
    fi
done < <(find "$ROOT/backend" -name '*.py' -type f 2>/dev/null)

# Every .py file that CONSTRUCTS a BotPosition — must import position_write_gate
while IFS= read -r file; do
    _is_exempt "$file" "${_POS_EXEMPT[@]}" && continue
    if grep -qE '(from\s+app\.services\.position_write_gate\s+import|import\s+app\.services\.position_write_gate)' "$file"; then
        continue
    fi
    if grep -nE '(^|[^A-Za-z_])BotPosition\s*\(' "$file" | grep -vE '^\s*[0-9]+:\s*#|^\s*[0-9]+:\s*"""' | grep -q .; then
        echo "FAIL: $file constructs BotPosition(...) but does NOT import position_write_gate" >&2
        grep -nE 'BotPosition\s*\(' "$file" | head -5 | sed 's/^/  /' >&2
        FAIL=1
    fi
done < <(find "$ROOT/backend" -name '*.py' -type f 2>/dev/null)

if [[ "$FAIL" -eq 0 ]]; then
    echo "[gate-check] OK — every constructor site has its gate import"
else
    echo "" >&2
    echo "[gate-check] FAILED — see above. Fix by importing the gate:" >&2
    echo "  from app.services.trade_write_gate import check_trade_write" >&2
    echo "  from app.services.position_write_gate import check_position_pre_write" >&2
    echo "" >&2
    echo "Even if you don't invoke them (backfill scripts, etc), the IMPORT is required" >&2
    echo "so the discipline is grep-visible. Ledger #32 §W1 rule." >&2
fi

exit "$FAIL"
