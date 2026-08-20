#!/usr/bin/env bash
# BMG status snapshot — bypasses the Railway CLI (which stalls or reports
# stale state when the platform is under load).
#
# Reads:
#   - Live HTTP status via curl against prod URL
#   - Alpaca account + positions direct (broker truth)
#   - Off-volume backup age via /admin/offvolume-backup-status
#   - Invariants summary via /admin/invariants/run
#   - Recent trades count via /admin/conversion-24h-diagnostic
#
# Never touches Railway CLI. Never prompts for auth (uses bmg_admin.sh for
# JWT-gated endpoints; Alpaca creds from backend/.env).
#
# Usage:
#   scripts/bmg_status.sh          # full snapshot
#   scripts/bmg_status.sh --json   # machine-readable
#
# Task #81. Ships 2026-08-20 as part of Brock autonomous work order Phase F.

set -euo pipefail

JSON_MODE=0
if [[ "${1:-}" == "--json" ]]; then JSON_MODE=1; fi

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ADMIN="$HERE/bmg_admin.sh"
BASE="${BMG_API_BASE_PUBLIC:-https://bmg-capital-production.up.railway.app}"

# Load ONLY the Alpaca creds from .env; whole-file source breaks on any
# value containing shell metacharacters (URLs, etc).
if [[ -f "$REPO/backend/.env" ]]; then
    for k in ALPACA_API_KEY ALPACA_SECRET_KEY ALPACA_PAPER_KEY ALPACA_PAPER_SECRET; do
        v=$(/usr/bin/grep -E "^${k}=" "$REPO/backend/.env" 2>/dev/null | /usr/bin/head -1 | /usr/bin/cut -d= -f2- | /usr/bin/tr -d '"' | /usr/bin/tr -d "'")
        if [[ -n "$v" ]]; then export "$k=$v"; fi
    done
fi

_hdr() { [[ "$JSON_MODE" == "1" ]] || echo "=== $1 ==="; }
_kv()  { [[ "$JSON_MODE" == "1" ]] || printf "  %-28s %s\n" "$1" "$2"; }

# ── 1. HTTP reachability ─────────────────────────────────────────────────
_hdr "HTTP"
HTTP_ROOT="$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" -m 5 "$BASE/" 2>/dev/null || echo err)"
HTTP_HEALTH="$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" -m 5 "$BASE/health" 2>/dev/null || echo err)"
_kv "root ($BASE/)"    "$HTTP_ROOT"
_kv "health"           "$HTTP_HEALTH"

# ── 2. Alpaca broker truth ───────────────────────────────────────────────
_hdr "Alpaca (broker truth)"
K="${ALPACA_API_KEY:-${ALPACA_PAPER_KEY:-}}"
S="${ALPACA_SECRET_KEY:-${ALPACA_PAPER_SECRET:-}}"
if [[ -n "$K" && -n "$S" ]]; then
    ACCT="$(/usr/bin/curl -sS -m 10 \
        -H "APCA-API-KEY-ID: $K" -H "APCA-API-SECRET-KEY: $S" \
        "https://paper-api.alpaca.markets/v2/account" 2>/dev/null || echo '{}')"
    POSITIONS="$(/usr/bin/curl -sS -m 10 \
        -H "APCA-API-KEY-ID: $K" -H "APCA-API-SECRET-KEY: $S" \
        "https://paper-api.alpaca.markets/v2/positions" 2>/dev/null || echo '[]')"
    /usr/bin/python3 -c "
import json, sys
try:
    a = json.loads('''$ACCT''')
    p = json.loads('''$POSITIONS''')
    eq = float(a.get('equity',0))
    last = float(a.get('last_equity',0))
    today = eq - last
    print(f\"  {'equity_usd':<28} \${eq:,.2f}\")
    print(f\"  {'last_equity_usd':<28} \${last:,.2f}\")
    print(f\"  {'today_pnl_usd':<28} \${today:+,.2f}\")
    print(f\"  {'cash_usd':<28} \${float(a.get('cash',0)):,.2f}\")
    print(f\"  {'position_count':<28} {len(p)}\")
    print(f\"  {'trading_blocked':<28} {a.get('trading_blocked')}\")
except Exception as e:
    print(f'  alpaca parse err: {e}', file=sys.stderr)
" 2>&1
else
    _kv "alpaca_creds" "MISSING (skipping)"
fi

# ── 3. BMG admin endpoints (JWT-gated) ───────────────────────────────────
_hdr "BMG admin"
INV_RESULT="$("$ADMIN" POST "/admin/invariants/run?fresh=false" 2>/dev/null || echo '{"error":"failed"}')"
/usr/bin/python3 -c "
import json
try:
    d = json.loads('''$INV_RESULT''')
    s = d.get('summary',{}) or {}
    print(f\"  {'invariants_green':<28} {s.get('green','?')}\")
    print(f\"  {'invariants_amber':<28} {s.get('amber','?')}\")
    print(f\"  {'invariants_red':<28} {s.get('red','?')}\")
    reds = [r for r in d.get('all',[]) if r.get('level') == 'red']
    for r in reds[:5]:
        print(f\"    RED  {r.get('check_id')}  {(r.get('detail') or '')[:80]}\")
except Exception as e:
    print(f'  invariants parse err: {e}')
"

CONV="$("$ADMIN" GET "/admin/conversion-24h-diagnostic" 2>/dev/null || echo '{}')"
/usr/bin/python3 -c "
import json
try:
    d = json.loads('''$CONV''')
    rows = d.get('per_bot_rows') or d.get('per_bot') or []
    sig_total = sum(r.get('sigs_24h',0) for r in rows)
    trd_total = sum(r.get('trades_24h',0) for r in rows)
    print(f\"  {'signals_24h':<28} {sig_total}\")
    print(f\"  {'trades_24h':<28} {trd_total}\")
    print(f\"  {'conversion':<28} {round(trd_total/sig_total*100,2) if sig_total else 0}%\")
except Exception as e:
    print(f'  conv parse err: {e}')
"

BKUP="$("$ADMIN" GET "/admin/offvolume-backup-status" 2>/dev/null || echo '{}')"
/usr/bin/python3 -c "
import json
try:
    d = json.loads('''$BKUP''')
    print(f\"  {'offvolume_backup_exists':<28} {d.get('exists')}\")
    print(f\"  {'offvolume_backup_age_hrs':<28} {d.get('age_hours')}\")
except Exception as e:
    print(f'  backup parse err: {e}')
"

[[ "$JSON_MODE" == "1" ]] || echo ""
[[ "$JSON_MODE" == "1" ]] || echo "Snapshot at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
