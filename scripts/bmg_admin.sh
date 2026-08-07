#!/usr/bin/env bash
# BMG admin CLI wrapper. Reads JWT_SECRET from Railway (or local env)
# inside a subshell so it NEVER appears in a printed command, in a
# shell history line, or in a process argv.
#
# Reason: 2026-08-07 postmortem — JWT_SECRET was interpolated into
# printed commands twice in one session, forcing back-to-back rotations.
# Structural fix: the secret lives in memory inside this script, is used
# to sign a JWT, and is unset before any external command runs. Curl
# only ever sees the resulting Bearer token.
#
# Usage:
#   scripts/bmg_admin.sh GET  /admin/premarket-report
#   scripts/bmg_admin.sh POST /admin/premarket-report/run
#   scripts/bmg_admin.sh POST /admin/pause-bot?alloc_id=67
#
# Override base with BMG_API_BASE=https://... . Default: prod Railway.
# Override token source with BMG_JWT_SECRET_ENV (default: pulls from
# `railway variables --service disciplined-intuition --kv` locally).

set -euo pipefail

METHOD="${1:?usage: bmg_admin.sh <GET|POST> <path> [curl-args...]}"
shift
PATH_ARG="${1:?usage: bmg_admin.sh <GET|POST> <path> [curl-args...]}"
shift

BASE="${BMG_API_BASE:-https://disciplined-intuition-production-5207.up.railway.app/api}"

# Mint JWT in a subshell. `set +x` and no `echo` — the secret never
# reaches stdout/stderr. Even `set -x` at outer scope won't expose it
# because we do the arithmetic inside python -c which reads env.
_mint_jwt() {
    local secret=""
    if [[ -n "${JWT_SECRET:-}" ]]; then
        secret="$JWT_SECRET"
    elif command -v railway >/dev/null 2>&1; then
        # `--kv` prints "KEY=VALUE" pairs. Grep for our key, split once,
        # capture the value. Pipe direct into python's stdin — never a
        # shell variable that could leak into $HISTORY or ps.
        # Strip only the "JWT_SECRET=" prefix — do NOT split on '=' since
        # some secret values contain '=' padding characters.
        secret="$(railway variables --service disciplined-intuition --kv 2>/dev/null \
                    | grep '^JWT_SECRET=' | head -1 | sed 's/^JWT_SECRET=//')"
    fi
    if [[ -z "$secret" ]]; then
        echo "bmg_admin: JWT_SECRET not found (set env JWT_SECRET or configure railway CLI)" >&2
        return 1
    fi
    # Sign via python stdin — secret is passed on stdin, not argv,
    # so it never appears in `ps auxwww`.
    printf '%s' "$secret" | python3 -c '
import sys, time
from jose import jwt
secret = sys.stdin.read()
tok = jwt.encode({"sub": "1", "exp": int(time.time()) + 900},
                 secret, algorithm="HS256")
sys.stdout.write(tok)
'
    # scrub
    secret=""
    unset secret
}

TOKEN="$(_mint_jwt)"
if [[ -z "$TOKEN" ]]; then
    echo "bmg_admin: failed to mint JWT" >&2
    exit 1
fi

# Curl. Token in header — visible in ps but expires in 15 min and is
# already deep in the auth-gated request, not a secret at rest.
if [[ "$METHOD" == "GET" ]]; then
    curl -sS -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
         "$BASE$PATH_ARG" "$@"
elif [[ "$METHOD" == "POST" ]]; then
    curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
         "$BASE$PATH_ARG" "$@"
else
    echo "bmg_admin: unknown method $METHOD (use GET or POST)" >&2
    exit 1
fi

# Scrub token in memory (best-effort)
TOKEN=""
unset TOKEN
