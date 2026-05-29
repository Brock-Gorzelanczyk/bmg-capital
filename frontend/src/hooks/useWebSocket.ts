/**
 * Persistent WebSocket singleton — connection is established once at module-load
 * time and survives all React route transitions. Status is stored in useWsStore
 * so any component can read it without owning the connection.
 *
 * useWebSocket() may be called from any component; it simply returns helpers to
 * subscribe/unsubscribe symbols. Calling the hook never tears down the socket.
 */
import { useCallback } from "react";
import { WS_URL } from "@/config";
import { useMarketStore, useAlertStore, useWsStore } from "@/store";
import type { Quote, LiveBar } from "@/types/market";

// ─── Singleton state ──────────────────────────────────────────────────────────

let _ws: WebSocket | null = null;
let _retryDelay = 1000; // ms; doubles on each failure, capped at 30 s
let _retryTimer: ReturnType<typeof setTimeout> | null = null;
let _started = false; // guard against double-init in StrictMode

function getSetStatus() {
  return useWsStore.getState().setStatus;
}

function scheduleReconnect() {
  if (_retryTimer !== null) return; // already scheduled
  const delay = Math.min(_retryDelay, 30_000);
  _retryDelay = Math.min(_retryDelay * 2, 30_000);
  _retryTimer = setTimeout(() => {
    _retryTimer = null;
    openSocket();
  }, delay);
}

function openSocket() {
  // Don't open a second socket if one is already live or connecting.
  if (
    _ws !== null &&
    (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }

  getSetStatus()("connecting");
  const ws = new WebSocket(WS_URL);
  _ws = ws;

  ws.onopen = () => {
    getSetStatus()("connected");
    _retryDelay = 1000; // reset backoff on successful connect
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data as string);
      const marketState = useMarketStore.getState();
      const alertState = useAlertStore.getState();

      if (msg.type === "quote") {
        marketState.updateQuote(msg.symbol, msg as Quote);
        marketState.setLastQuoteTime(Date.now());
      } else if (msg.type === "bar") {
        marketState.updateBar(msg.symbol, msg as LiveBar);
      } else if (msg.type === "alert" || msg.type === "signal") {
        alertState.addNotification({
          symbol: msg.symbol,
          signal_type: msg.signal_type || msg.type,
          message: msg.message || `${msg.signal_type} on ${msg.symbol}`,
          value: msg.value,
          timestamp: new Date().toISOString(),
        });
      }
    } catch {
      // ignore parse errors
    }
  };

  ws.onerror = () => {
    getSetStatus()("error");
  };

  ws.onclose = () => {
    getSetStatus()("disconnected");
    scheduleReconnect();
  };
}

/** Initialise the singleton (idempotent — safe to call multiple times). */
function ensureStarted() {
  if (_started) return;
  _started = true;
  openSocket();
}

// ─── React hook ───────────────────────────────────────────────────────────────

export function useWebSocket() {
  // Start the singleton the first time any component calls this hook.
  ensureStarted();

  const subscribe = useCallback((symbols: string[]) => {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ action: "subscribe", symbols }));
    }
  }, []);

  const unsubscribe = useCallback((symbols: string[]) => {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ action: "unsubscribe", symbols }));
    }
  }, []);

  return { subscribe, unsubscribe };
}
