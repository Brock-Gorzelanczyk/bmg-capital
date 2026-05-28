#!/bin/bash
# BMG Capital - keeps backend (8000) and frontend (5174) running

BACKEND_DIR="/Users/brockgorzelanczyk/my-new-project/backend"
FRONTEND_DIR="/Users/brockgorzelanczyk/my-new-project/frontend"
VENV="$BACKEND_DIR/.venv/bin/uvicorn"

log() { echo "[$(date '+%H:%M:%S')] $1"; }

while true; do
  # --- Backend ---
  if ! lsof -ti:8000 >/dev/null 2>&1; then
    log "Backend down — restarting..."
    nohup bash -c "cd $BACKEND_DIR && $VENV app.main:app --host 0.0.0.0 --port 8000" \
      >> /tmp/bmg_backend.log 2>&1 &
    sleep 5
    if lsof -ti:8000 >/dev/null 2>&1; then
      log "Backend started OK"
    else
      log "Backend FAILED to start — check /tmp/bmg_backend.log"
    fi
  fi

  # --- Frontend ---
  FRONTEND_PID=$(lsof -ti:5174 2>/dev/null)
  if [ -z "$FRONTEND_PID" ]; then
    log "Frontend down — restarting..."
    nohup bash -c "cd $FRONTEND_DIR && npm run dev -- --port 5174 --host" \
      >> /tmp/bmg_frontend.log 2>&1 &
    sleep 8
    if lsof -ti:5174 >/dev/null 2>&1; then
      log "Frontend started OK"
    else
      log "Frontend FAILED to start — check /tmp/bmg_frontend.log"
    fi
  fi

  sleep 15
done
