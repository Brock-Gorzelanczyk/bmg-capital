#!/usr/bin/env bash
# Regenerate the BMG codebase knowledge graph via graphify.
#
# Graphify turns the entire BMG repo into a queryable knowledge graph.
# You get:
#   graphify-out/graph.html    interactive visualization (open in browser)
#   graphify-out/GRAPH_REPORT.md   high-level summary
#   graphify-out/graph.json    raw graph for programmatic queries
#
# Requires Python 3.10+ and the `claude` CLI (zero-cost extraction via
# your Claude Code subscription, not the Anthropic API).
#
# First-time setup (pick one):
#
#   uv (recommended — brew install uv):
#     uv tool install "graphifyy[claude]"
#
#   pipx (brew install pipx):
#     pipx install "graphifyy[claude]"
#
# Then run:
#   scripts/graphify_bmg.sh
#
# Output is gitignored so re-runs don't bloat the repo.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Locate a working graphify binary.
GRAPHIFY_BIN=""
for candidate in \
    "$HOME/.local/bin/graphify" \
    "$HOME/.cargo/bin/graphify" \
    "/opt/homebrew/bin/graphify" \
    "graphify"; do
  if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
    GRAPHIFY_BIN="$candidate"
    break
  fi
done

if [ -z "$GRAPHIFY_BIN" ]; then
  cat <<'EOF' >&2
graphify not found on PATH.

Install (needs Python 3.10+):
  uv tool install "graphifyy[claude]"      # recommended
  # OR
  pipx install "graphifyy[claude]"

Then re-run this script.
EOF
  exit 1
fi

# claude CLI is the zero-cost backend (uses Claude Code subscription).
if ! command -v claude >/dev/null 2>&1; then
  cat <<'EOF' >&2
WARNING: 'claude' CLI not on PATH. Graphify will fall back to other backends
         and MAY hit your ANTHROPIC_API_KEY or OPENAI_API_KEY. Ctrl-C to
         abort if you don't want that.
EOF
  sleep 3
fi

echo "Running graphify at $REPO_ROOT"
echo "Output: graphify-out/{graph.html,GRAPH_REPORT.md,graph.json}"
echo ""

"$GRAPHIFY_BIN" . \
  --backend claude \
  --exclude "node_modules" \
  --exclude "dist" \
  --exclude ".venv" \
  --exclude "graphify-out" \
  --exclude "__pycache__" \
  --exclude "*.log" \
  --exclude "backend/data" \
  --exclude ".claude/worktrees" \
  "$@"

echo ""
echo "Done. Open graphify-out/graph.html to explore."
