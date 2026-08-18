#!/bin/bash
# Cost watchdog — poll Railway status hourly, log to /tmp/bmg_cost.log.
# 2026-08-13: added daily summary marker so Brock can grep for it.

set -euo pipefail
LOG=/tmp/bmg_cost.log
DAILY_MARK=/tmp/bmg_cost_last_day

last_day=$(cat "$DAILY_MARK" 2>/dev/null || echo "")

while true; do
  ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  today=$(date -u '+%Y-%m-%d')

  # Server up/down
  code=$(curl -sS -m 10 -o /dev/null -w "%{http_code}" \
    "https://disciplined-intuition-production-5207.up.railway.app/health" 2>&1 || echo "000")

  # Railway status (Online/Failed/etc.)
  rstatus=$(railway status 2>&1 | grep -oE "status:\s+\S+ \S+" | awk '{print $NF}' || echo "unknown")

  # Deployment id — tells us if a restart happened silently
  dep=$(railway status 2>&1 | grep -oE "deployment ID:\s+\S+" | awk '{print $NF}' || echo "unknown")

  echo "$ts  status=$rstatus  http=$code  dep=${dep:0:8}" >> "$LOG"

  # Daily boundary — emit a summary marker Brock can grep.
  # Note: Railway doesn't expose live-spend via CLI. Brock reads the
  # dashboard for the actual $ number; this marker just says "one day
  # elapsed, check railway.com/workspace/usage".
  if [ "$today" != "$last_day" ]; then
    echo "$ts  === DAY BOUNDARY $today === (check railway.com/workspace/usage for spend)" >> "$LOG"
    echo "$today" > "$DAILY_MARK"
    last_day="$today"
  fi

  sleep 3600
done
