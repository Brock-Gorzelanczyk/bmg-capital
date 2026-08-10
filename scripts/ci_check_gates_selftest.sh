#!/usr/bin/env bash
# Self-test for ci_check_gates.sh: create a temp file that constructs
# BotTrade without importing trade_write_gate, and verify the gate check FAILS.
# Restores state after.
#
# Acceptance for ledger #32 Layer 2: "A test commit that adds an ungated
# BotTrade( call FAILS CI."

set -euo pipefail

ROOT="${1:-$(pwd)}"
SENTINEL="$ROOT/backend/_gate_selftest_violation.py"

cleanup() {
    rm -f "$SENTINEL"
}
trap cleanup EXIT

cat > "$SENTINEL" <<'EOF'
# Deliberate ungated BotTrade construction — should trip the gate check.
from app.db.models.bots import BotTrade

def bad_write():
    return BotTrade(allocation_id=1, symbol="X", side="buy", qty=1,
                    fill_price_cents=1, fees_cents=0, ts=None,
                    origin="BROKER_FILL")
EOF

if bash "$ROOT/scripts/ci_check_gates.sh" "$ROOT" >/dev/null 2>&1; then
    echo "SELFTEST FAIL: gate script accepted an ungated BotTrade site" >&2
    exit 1
fi

echo "SELFTEST OK — gate script correctly rejects an ungated BotTrade site"
