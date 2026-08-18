#!/bin/bash
# Vault sync — pulls /data/audits/*.md + /data/postmortems-stub/*.md
# from the Railway container to ~/Documents/BMG-Capital-Vault/.
#
# Runs on Brock's Mac via cron/launchd. Ledger #39 / §V8 — replaces
# "human writes the daily audit line" with an automatic pull.
#
# Usage:
#   scripts/bmg_vault_sync.sh          # one-shot pull
#   scripts/bmg_vault_sync.sh --dry    # show what would be pulled
#
# Suggested launchd (once/day at noon local):
#   ~/Library/LaunchAgents/com.bmg.vault-sync.plist
#     StartCalendarInterval: Hour=12 Minute=0
#     ProgramArguments: /bin/bash -c "cd ~/my-new-project && scripts/bmg_vault_sync.sh"

set -euo pipefail
cd "$(dirname "$0")/.."

VAULT_DIR="${VAULT_DIR:-$HOME/Documents/BMG-Capital-Vault}"
AUDIT_DEST="$VAULT_DIR/daily-audits"
STUB_DEST="$VAULT_DIR/postmortems-stub-inbox"  # separate from postmortems/ so Brock reviews before promoting

DRY=""
if [[ "${1:-}" == "--dry" ]]; then DRY="1"; fi

mkdir -p "$AUDIT_DEST" "$STUB_DEST"

echo "[vault-sync] pulling audits list..."
AUDITS_JSON=$(scripts/bmg_admin.sh GET /admin/audits/list)
NEW=0
if command -v jq >/dev/null 2>&1; then
  echo "$AUDITS_JSON" | jq -r '.audits[]?.date // empty' | while read -r date; do
    [ -z "$date" ] && continue
    dest="$AUDIT_DEST/${date}.md"
    if [ -f "$dest" ]; then
      # Skip if local exists (assume same content; audits are append-only per day).
      continue
    fi
    if [ -n "$DRY" ]; then
      echo "  [dry] would fetch $date"
      continue
    fi
    content=$(scripts/bmg_admin.sh GET "/admin/audits/${date}" | jq -r '.content // empty')
    if [ -n "$content" ]; then
      echo "$content" > "$dest"
      echo "  [pulled] $date -> $dest"
      NEW=$((NEW+1))
    fi
  done
else
  echo "[vault-sync] jq not installed — skipping audit sync"
fi

echo "[vault-sync] pulling postmortem stubs..."
STUBS_JSON=$(scripts/bmg_admin.sh GET /admin/postmortem-stubs/list)
if command -v jq >/dev/null 2>&1; then
  echo "$STUBS_JSON" | jq -r '.stubs[]?.filename // empty' | while read -r name; do
    [ -z "$name" ] && continue
    dest="$STUB_DEST/$name"
    if [ -f "$dest" ]; then
      # Overwrite: stubs are append-only server-side, always take latest.
      :
    fi
    if [ -n "$DRY" ]; then
      echo "  [dry] would fetch stub $name"
      continue
    fi
    content=$(scripts/bmg_admin.sh GET "/admin/postmortem-stubs/${name}" | jq -r '.content // empty')
    if [ -n "$content" ]; then
      echo "$content" > "$dest"
      echo "  [pulled stub] $name -> $dest"
    fi
  done
else
  echo "[vault-sync] jq not installed — skipping stub sync"
fi

# Freshness check — surface I28 status locally too.
NEWEST_HOURS=$(echo "$AUDITS_JSON" | jq -r '.newest_age_hours // "n/a"' 2>/dev/null || echo "n/a")
echo "[vault-sync] newest audit age: ${NEWEST_HOURS}h"
if [ "$NEWEST_HOURS" != "n/a" ] && [ "$NEWEST_HOURS" != "null" ]; then
  # bash float compare via awk
  IS_STALE=$(awk -v v="$NEWEST_HOURS" 'BEGIN { print (v+0 > 48) ? "1" : "0" }')
  if [ "$IS_STALE" = "1" ]; then
    echo "[vault-sync] WARN: newest audit is ${NEWEST_HOURS}h old (>48h → I28 RED)"
  fi
fi

echo "[vault-sync] done."
