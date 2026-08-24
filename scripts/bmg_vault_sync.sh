#!/bin/bash
# Vault sync — pulls /data/audits/*.md + /data/postmortems-stub/*.md
# from the Railway container to ~/Documents/BMG-Capital-Vault/, then
# commits + pushes to the vault GitHub repo, then POSTs a ping to the
# container so I28 knows the sync actually ran.
#
# 2026-08-18 Brock: vault repo is the durable copy — laptop failure or
# missed cron won't lose history. I28's freshness signal is the ping
# timestamp, not the container's /data/audits mtime (which lies because
# the container auto-writes those daily regardless).
#
# Usage:
#   scripts/bmg_vault_sync.sh          # one-shot pull + push + ping
#   scripts/bmg_vault_sync.sh --dry    # show what would be pulled, no writes/push/ping
#   scripts/bmg_vault_sync.sh --no-push  # pull + ping, skip git push
#
# Suggested launchd (once/day at noon local):
#   ~/Library/LaunchAgents/com.bmg.vault-sync.plist
#     StartCalendarInterval: Hour=12 Minute=0
#     ProgramArguments: /bin/bash -c "cd ~/my-new-project && scripts/bmg_vault_sync.sh"

set -euo pipefail
cd "$(dirname "$0")/.."

# 2026-08-20 Brock: Obsidian on his Mac opens the iCloud-synced vault by default,
# not the ~/Documents/BMG-Capital-Vault git-tracked one. To avoid two disconnected
# vaults (empty iCloud + populated local), sync targets the iCloud vault which
# also gets his Obsidian mobile sync for free.
_ICLOUD_VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/BMG Capital"
if [ -z "${VAULT_DIR:-}" ] && [ -d "$_ICLOUD_VAULT" ]; then
    VAULT_DIR="$_ICLOUD_VAULT"
fi
VAULT_DIR="${VAULT_DIR:-$HOME/Documents/BMG-Capital-Vault}"
AUDIT_DEST="$VAULT_DIR/daily-audits"
STUB_DEST="$VAULT_DIR/postmortems-stub-inbox"  # separate from postmortems/ so Brock reviews before promoting

DRY=""
NO_PUSH=""
for arg in "$@"; do
  case "$arg" in
    --dry)     DRY="1" ;;
    --no-push) NO_PUSH="1" ;;
  esac
done

mkdir -p "$AUDIT_DEST" "$STUB_DEST"

echo "[vault-sync] pulling audits list..."
AUDITS_JSON=$(scripts/bmg_admin.sh GET /admin/audits/list)
NEW_FILES=0
if command -v jq >/dev/null 2>&1; then
  # Endpoint returns {"files":[{"name": "...md", ...}]}. Prior version
  # queried .audits[].date which never matched — silent no-op that kept
  # the vault stale for 6+ days (only 2 files locally vs 13 in container).
  while read -r fname; do
    [ -z "$fname" ] && continue
    dest="$AUDIT_DEST/${fname}"
    if [ -f "$dest" ]; then
      # Skip if local exists (assume same content; audits are append-only per day).
      continue
    fi
    if [ -n "$DRY" ]; then
      echo "  [dry] would fetch $fname"
      continue
    fi
    content=$(scripts/bmg_admin.sh GET "/admin/audits/${fname}" | jq -r '.content // empty')
    if [ -n "$content" ]; then
      echo "$content" > "$dest"
      echo "  [pulled] $fname -> $dest"
      NEW_FILES=$((NEW_FILES+1))
    fi
  done < <(echo "$AUDITS_JSON" | jq -r '.files[]?.name // empty')
else
  echo "[vault-sync] jq not installed — skipping audit sync"
fi

echo "[vault-sync] pulling postmortem stubs..."
STUBS_JSON=$(scripts/bmg_admin.sh GET /admin/postmortem-stubs/list)
if command -v jq >/dev/null 2>&1; then
  while read -r name; do
    [ -z "$name" ] && continue
    dest="$STUB_DEST/$name"
    if [ -n "$DRY" ]; then
      echo "  [dry] would fetch stub $name"
      continue
    fi
    content=$(scripts/bmg_admin.sh GET "/admin/postmortem-stubs/${name}" | jq -r '.content // empty')
    if [ -n "$content" ]; then
      # Only bump NEW_FILES if the file didn't exist before OR content changed.
      if [ ! -f "$dest" ] || [ "$(cat "$dest")" != "$content" ]; then
        echo "$content" > "$dest"
        echo "  [pulled stub] $name -> $dest"
        NEW_FILES=$((NEW_FILES+1))
      fi
    fi
  done < <(echo "$STUBS_JSON" | jq -r '.stubs[]?.filename // empty')
else
  echo "[vault-sync] jq not installed — skipping stub sync"
fi

# Commit + push to vault repo (durable copy). Only if there are changes.
COMMIT_SHA=""
PUSHED="false"
if [ -z "$DRY" ] && [ -d "$VAULT_DIR/.git" ]; then
  ( cd "$VAULT_DIR"
    if [ -n "$(git status --porcelain)" ]; then
      git add -A
      MSG="vault-sync $(date -u +%Y-%m-%dT%H:%MZ) — $NEW_FILES new/changed"
      git commit -m "$MSG" >/dev/null 2>&1 || true
      if [ -z "$NO_PUSH" ]; then
        # Only push if there's a remote configured; failure non-fatal.
        if git remote get-url origin >/dev/null 2>&1; then
          if git push origin HEAD 2>&1 | tail -3; then
            echo "  [git] pushed to origin"
          else
            echo "  [git] push failed (non-fatal — commit still local)"
          fi
        else
          echo "  [git] no 'origin' remote configured — commit stayed local"
        fi
      fi
    fi
  )
  COMMIT_SHA=$(cd "$VAULT_DIR" && git rev-parse --short HEAD 2>/dev/null || echo "")
  if [ -z "$NO_PUSH" ] && [ -n "$COMMIT_SHA" ]; then
    # Check if HEAD is on origin (proxy for "pushed")
    if (cd "$VAULT_DIR" && git branch --contains HEAD -r 2>/dev/null | grep -q origin); then
      PUSHED="true"
    fi
  fi
fi

# Report the ping to the container. This is what I28 reads.
if [ -z "$DRY" ]; then
  echo "[vault-sync] pinging /admin/vault-sync-ping..."
  PING_PAYLOAD=$(printf '{"git_commit_sha":"%s","git_pushed":%s}' "$COMMIT_SHA" "$PUSHED")
  # bmg_admin.sh POST forwards extra args to curl; use -d for JSON body.
  scripts/bmg_admin.sh POST /admin/vault-sync-ping \
      -H "Content-Type: application/json" \
      -d "$PING_PAYLOAD" >/dev/null 2>&1 && \
    echo "  [ping] recorded (commit=$COMMIT_SHA pushed=$PUSHED)" || \
    echo "  [ping] failed — I28 will still see last successful ping (non-fatal)"
fi

echo "[vault-sync] done. new_files=$NEW_FILES"
