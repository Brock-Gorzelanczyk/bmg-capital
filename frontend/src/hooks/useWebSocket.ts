import { useEffect, useRef, useCallback } from "react";
import { WS_URL } from "@/config";
import { useMarketStore, useAlertStore, useWsStore } from "@/store";
import type { Quote, LiveBar } from "@/types/market";

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const retryDelay = useRef(1000);
  const updateQuote = useMarketStore((s) => s.updateQuote);
  const updateBar = useMarketStore((s) => s.updateBar);
  const setLastQuoteTime = useMarketStore((s) => s.setLastQuoteTime);
  const addNotification = useAlertStore((s) => s.addNotification);
  const setStatus = useWsStore((s) => s.setStatus);

  const connect = useCallback(() => {
    setStatus("connecting");
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      retryDelay.current = 1000;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string);
        if (msg.type === "quote") {
          updateQuote(msg.symbol, msg as Quote);
          useMarketStore.getState().setLastQuoteTime(Date.now());
        } else if (msg.type === "bar") {
          updateBar(msg.symbol, msg as LiveBar);
        } else if (msg.type === "alert" || msg.type === "signal") {
          addNotification({
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

    ws.onerror = () => setStatus("error");

    ws.onclose = () => {
      setStatus("disconnected");
      const delay = Math.min(retryDelay.current, 30000);
      retryDelay.current = Math.min(retryDelay.current * 2, 30000);
      setTimeout(connect, delay);
    };
  }, [updateQuote, updateBar, addNotification, setStatus, setLastQuoteTime]);

  const subscribe = useCallback((symbols: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "subscribe", symbols }));
    }
  }, []);

  const unsubscribe = useCallback((symbols: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "unsubscribe", symbols }));
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { subscribe, unsubscribe };
}
