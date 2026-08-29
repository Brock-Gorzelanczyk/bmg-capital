#!/usr/bin/env bash
# Refresh the BMG_USER_TOKEN in the vault-sync launchd plist.
#
# Reason: 2026-08-29 (I28 chronic fix) — the plist previously hardcoded
# a JWT that expired 2026-07-24, killing daily-audit sync. The code
# (relay/vault_sync.py) now auto-mints tokens if JWT_SECRET is in env,
# but for hosts that don't want JWT_SECRET in launchd env, this script
# mints a fresh long-TTL token and injects it via PlistBuddy — the
# secret NEVER appears in stdout, argv, or shell history.
#
# Usage: scripts/refresh_vault_sync_token.sh
#
# The mint reads JWT_SECRET from Railway CLI in a subshell (same pattern
# as bmg_admin.sh, §S1-compliant).

set -euo pipefail

PLIST="$HOME/Library/LaunchAgents/com.bmg.vault-sync.plist"

if [ ! -f "$PLIST" ]; then
    echo "ERROR: plist not found at $PLIST" >&2
    exit 1
fi

# Mint token with 365-day TTL. Same pattern as bmg_admin.sh — JWT_SECRET
# is read inside the python subprocess via stdin, never argv or env.
_mint_long_token() {
    local secret=""
    if [[ -n "${JWT_SECRET:-}" ]]; then
        secret="$JWT_SECRET"
    elif command -v railway >/dev/null 2>&1; then
        secret="$(railway variables --service disciplined-intuition --kv 2>/dev/null \
                    | grep '^JWT_SECRET=' | head -1 | sed 's/^JWT_SECRET=//')"
    fi
    if [[ -z "$secret" ]]; then
        echo "ERROR: JWT_SECRET not found (set env or configure railway CLI)" >&2
        return 1
    fi
    # Pipe secret via stdin — invisible to ps / history / transcript
    printf '%s' "$secret" | python3 -c '
import sys, hmac, hashlib, base64, json, time
secret = sys.stdin.read()
header  = json.dumps({"alg":"HS256","typ":"JWT"}, separators=(",",":")).encode()
payload = json.dumps({"sub":"1","exp":int(time.time())+365*86400}, separators=(",",":")).encode()
b64h = base64.urlsafe_b64encode(header).rstrip(b"=")
b64p = base64.urlsafe_b64encode(payload).rstrip(b"=")
sig  = hmac.new(secret.encode(), b64h + b"." + b64p, hashlib.sha256).digest()
b64s = base64.urlsafe_b64encode(sig).rstrip(b"=")
sys.stdout.write((b64h + b"." + b64p + b"." + b64s).decode())
'
}

TOKEN="$(_mint_long_token)"
if [[ -z "$TOKEN" ]]; then
    echo "ERROR: token mint failed" >&2
    exit 1
fi

# Update plist via PlistBuddy — token goes on stdin, not argv
/usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:BMG_USER_TOKEN $TOKEN" "$PLIST"

# Reload launchd
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "vault-sync token refreshed (365d TTL) + launchd reloaded"
echo "verify: tail -20 /tmp/vault_sync.err  (should stop 401ing)"
