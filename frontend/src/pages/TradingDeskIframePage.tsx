import { useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import client from "@/api/client";

/**
 * TradingDeskIframePage — cinematic Trading Desk terminal UI.
 *
 * Iframe wrapper around /trading-desk.html (the Claude Design export). The
 * iframe self-renders the chart/tape/orderbook animations; this wrapper's
 * job is to inject LIVE bot activity so the toasts + BUY/SELL flashes
 * reflect real signals/fills instead of a scripted demo.
 *
 * Data plumbing:
 *   - Poll /api/live/bot-activity every 6s → td:signal / td:fill / td:summary
 *   - Poll /api/live/candles every 30s     → td:candles (when symbol is set)
 *   - Deep-link:  /fund/desk?bot=X&symbol=Y  → focus one bot+symbol on load
 *
 * Query params:
 *   ?symbol=AMD      — focuses chart on this symbol (candles + header)
 *   ?bot=stock_day   — labels the header with the bot's name
 *   ?tf=5m           — candle timeframe (default 5m; 1m|5m|15m|30m|1h|1d)
 */
export default function TradingDeskIframePage() {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const lastSignalIdRef = useRef<number>(0);
  const lastTradeIdRef = useRef<number>(0);
  const seededRef = useRef<boolean>(false);
  const [searchParams] = useSearchParams();

  const focusSymbol = searchParams.get("symbol")?.trim().toUpperCase() || "";
  const focusBot = searchParams.get("bot")?.trim() || "";
  const timeframe = (searchParams.get("tf")?.trim() || "5m") as
    | "1m" | "5m" | "15m" | "30m" | "1h" | "1d";

  // Human-friendly bot display name — the backend serves canonical slugs,
  // but the deep-link URL param uses the slug directly, so we prettify.
  const focusBotDisplay = useMemo(() => {
    if (!focusBot) return "";
    return focusBot.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }, [focusBot]);

  // ── Signal + fill + summary poller ─────────────────────────────────────────
  useEffect(() => {
    let stopped = false;
    let timerId: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      if (stopped) return;
      try {
        const res = await client.get("/api/live/bot-activity", {
          params: {
            since_signal_id: lastSignalIdRef.current,
            since_trade_id: lastTradeIdRef.current,
          },
        });
        const iframe = iframeRef.current;
        const win = iframe?.contentWindow;
        if (win && res.data) {
          const isSeeding = !seededRef.current;
          for (const sig of res.data.signals ?? []) {
            if (sig.id > lastSignalIdRef.current) lastSignalIdRef.current = sig.id;
            if (isSeeding) continue;
            // If focused on a specific bot, drop signals from other bots so
            // the desk stays coherent to what the user came to watch.
            if (focusBot && sig.bot_id !== focusBot) continue;
            win.postMessage({ type: "td:signal", data: sig }, window.location.origin);
          }
          for (const trade of res.data.trades ?? []) {
            if (trade.id > lastTradeIdRef.current) lastTradeIdRef.current = trade.id;
            if (isSeeding) continue;
            if (focusBot && trade.bot_id !== focusBot) continue;
            win.postMessage({ type: "td:fill", data: trade }, window.location.origin);
          }
          if (res.data.summary) {
            win.postMessage(
              { type: "td:summary", data: res.data.summary },
              window.location.origin,
            );
          }
          seededRef.current = true;
        }
      } catch {
        // Silent — scripted fallback in iframe stays alive.
      } finally {
        if (!stopped) timerId = setTimeout(poll, 6000);
      }
    }

    const startId = setTimeout(poll, 500);
    return () => {
      stopped = true;
      clearTimeout(startId);
      if (timerId) clearTimeout(timerId);
    };
  }, [focusBot]);

  // ── Candles poller (only when ?symbol=X is set) ────────────────────────────
  useEffect(() => {
    if (!focusSymbol) return;
    let stopped = false;
    let timerId: ReturnType<typeof setTimeout> | null = null;

    // Push symbol/bot label to iframe on mount (so header updates immediately
    // even before the first candle response lands).
    const pushSymbolHeader = () => {
      const win = iframeRef.current?.contentWindow;
      if (!win) return;
      win.postMessage(
        {
          type: "td:symbol",
          data: {
            symbol: focusSymbol,
            venue: focusSymbol.includes("/") ? "Crypto · " + timeframe : "Live · " + timeframe,
            bot_display_name: focusBotDisplay || undefined,
          },
        },
        window.location.origin,
      );
    };
    // Give the iframe a moment to boot before pushing.
    const headerId = setTimeout(pushSymbolHeader, 800);

    async function pollCandles() {
      if (stopped) return;
      try {
        const res = await client.get("/api/live/candles", {
          params: { symbol: focusSymbol, timeframe, limit: 64 },
        });
        const win = iframeRef.current?.contentWindow;
        if (win && res.data && Array.isArray(res.data.candles) && res.data.candles.length > 0) {
          win.postMessage({ type: "td:candles", data: res.data }, window.location.origin);
        }
      } catch {
        // Silent — chart keeps its internal walk if fetch fails.
      } finally {
        if (!stopped) timerId = setTimeout(pollCandles, 30_000);
      }
    }
    // Small delay so the iframe boots before first candle push.
    const startId = setTimeout(pollCandles, 1200);

    return () => {
      stopped = true;
      clearTimeout(headerId);
      clearTimeout(startId);
      if (timerId) clearTimeout(timerId);
    };
  }, [focusSymbol, timeframe, focusBotDisplay]);

  return (
    <div style={{ position: "absolute", inset: 0, background: "#04080a" }}>
      <iframe
        ref={iframeRef}
        src="/trading-desk.html"
        title="Trading Desk"
        loading="lazy"
        sandbox="allow-scripts allow-same-origin"
        style={{ width: "100%", height: "100%", border: "none", display: "block" }}
      />
    </div>
  );
}
