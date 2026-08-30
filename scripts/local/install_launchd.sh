#!/bin/bash
# Install BMG local job runner as a Mac launchd agent.
#
# What this does:
#   1. Renders com.bmg.localjobs.plist.template with your paths
#   2. Copies to ~/Library/LaunchAgents/com.bmg.localjobs.plist
#   3. Loads it via launchctl
#   4. Verifies it's registered
#
# After install: runs every 15 min. Missed runs (Mac was asleep) are
# picked up on next tick via the runner's catchup logic.
#
# Uninstall: bash scripts/local/uninstall_launchd.sh
#
# Logs: tail -f ~/Library/Logs/bmg-localjobs.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEMPLATE="$SCRIPT_DIR/com.bmg.localjobs.plist.template"
TARGET="$HOME/Library/LaunchAgents/com.bmg.localjobs.plist"

# Find python3 — prefer homebrew, fall back to system
PYTHON_PATH="$(command -v python3)"
if [ -z "$PYTHON_PATH" ]; then
    echo "❌ python3 not found in PATH. Install Python 3.9+ first."
    exit 1
fi
echo "→ using python: $PYTHON_PATH"

# Verify railway CLI (needed to pull JWT_SECRET)
if ! command -v railway >/dev/null 2>&1; then
    echo "❌ railway CLI not found. Install: brew install railway"
    echo "   Then link project: railway link"
    exit 1
fi
echo "→ railway CLI: $(command -v railway)"

# Ensure LaunchAgents dir exists
mkdir -p "$HOME/Library/LaunchAgents"

# Render template
echo "→ rendering plist to $TARGET"
sed \
    -e "s|__PYTHON_PATH__|$PYTHON_PATH|g" \
    -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    -e "s|__HOME__|$HOME|g" \
    "$TEMPLATE" > "$TARGET"

# Unload if already loaded (idempotent install)
if launchctl list | grep -q "com.bmg.localjobs"; then
    echo "→ unloading existing agent"
    launchctl unload "$TARGET" 2>/dev/null || true
fi

# Load
echo "→ loading agent"
launchctl load "$TARGET"

# Verify
if launchctl list | grep -q "com.bmg.localjobs"; then
    echo "✓ com.bmg.localjobs registered"
    echo ""
    echo "Next steps:"
    echo "  1. Test with: python3 $SCRIPT_DIR/run.py --list"
    echo "  2. Force-run one job: python3 $SCRIPT_DIR/run.py --job job_daily_recap"
    echo "  3. Watch runs: tail -f ~/Library/Logs/bmg-localjobs.log"
    echo ""
    echo "Runner fires every 15 min. First scheduled run within 15 min from now."
else
    echo "❌ launchctl load failed. Check plist syntax:"
    plutil -lint "$TARGET"
    exit 1
fi
