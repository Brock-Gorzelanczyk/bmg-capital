#!/bin/bash
# Uninstall BMG local job runner.
set -euo pipefail

TARGET="$HOME/Library/LaunchAgents/com.bmg.localjobs.plist"

if launchctl list | grep -q "com.bmg.localjobs"; then
    launchctl unload "$TARGET" 2>/dev/null || true
    echo "→ unloaded"
fi

if [ -f "$TARGET" ]; then
    rm "$TARGET"
    echo "→ removed $TARGET"
fi

echo "✓ uninstalled"
