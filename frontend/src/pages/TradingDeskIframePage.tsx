import { useEffect, useRef } from "react";
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
 *   - Poll /api/live/bot-activity every 6s
 *   - Diff against last-seen event ids; postMessage new events into iframe
 *   - Iframe listens for `td:signal` / `td:fill` / `td:position` messages
 *     and drives its scripted animations from them
 *
 * The chart itself is still driven by the iframe's internal price walk
 * (Phase 3 will wire real candles). Trades/toasts/session P&L are live.
 */
export default function TradingDeskIframePage() {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const lastSignalIdRef = useRef<number>(0);
  const lastTradeIdRef = useRef<number>(0);

  const seededRef = useRef<boolean>(false);

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
          // First-poll behavior: silently seed watermarks so the client
          // doesn't spam the desk with 50 historical toasts on load. The
          // backend's cold-start returns the last N recent items (not the
          // oldest N) so we advance to the true tail. Real events start
          // firing as toasts from the NEXT poll onwards.
          const isSeeding = !seededRef.current;

          for (const sig of res.data.signals ?? []) {
            if (sig.id > lastSignalIdRef.current) lastSignalIdRef.current = sig.id;
            if (!isSeeding) {
              win.postMessage({ type: "td:signal", data: sig }, window.location.origin);
            }
          }
          for (const trade of res.data.trades ?? []) {
            if (trade.id > lastTradeIdRef.current) lastTradeIdRef.current = trade.id;
            if (!isSeeding) {
              win.postMessage({ type: "td:fill", data: trade }, window.location.origin);
            }
          }
          // Summary always flows — even on seed poll — so session P&L + bot
          // count populate immediately instead of showing +$0.00 for 6s.
          if (res.data.summary) {
            win.postMessage(
              { type: "td:summary", data: res.data.summary },
              window.location.origin,
            );
          }

          seededRef.current = true;
        }
      } catch (err) {
        // Silent — never break the app if the endpoint is unavailable.
        // The scripted fallback in the iframe keeps things looking alive.
      } finally {
        if (!stopped) timerId = setTimeout(poll, 6000);
      }
    }

    // First poll fires ~500ms after iframe mounts to give it time to boot
    // its animation loop before we start injecting events.
    const startId = setTimeout(poll, 500);

    return () => {
      stopped = true;
      clearTimeout(startId);
      if (timerId) clearTimeout(timerId);
    };
  }, []);

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
