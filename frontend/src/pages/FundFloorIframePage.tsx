import { useEffect, useRef } from "react";
import client from "@/api/client";

const ALLOWED_AGENTS = new Set([
  "portfolio_manager",
  "chief_risk_officer",
  "equity_researcher",
  "quant_researcher",
  "macro_strategist",
  "data_quality_watcher",
  "execution_auditor",
  "operations",
  "sentinel_devops",
]);

export default function FundFloorIframePage() {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    async function handleBriefing() {
      try {
        const res = await client.get("/api/fund-floor/cio-briefing-board");
        iframeRef.current?.contentWindow?.postMessage(
          { type: "ff_briefing", data: res.data },
          window.location.origin
        );
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 404) {
          // No briefing row yet — silently no-op.
          return;
        }
        console.warn("[FundFloor] briefing fetch failed", err);
      }
    }

    async function handleAgentOverlay(agentName: string) {
      try {
        const res = await client.get("/api/fund-floor/agent-overlay", {
          params: { agent_name: agentName },
        });
        iframeRef.current?.contentWindow?.postMessage(
          { type: "ff_agent_overlay", agent_name: agentName, data: res.data },
          window.location.origin
        );
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 404) {
          // No overlay row for this agent yet — silently no-op.
          return;
        }
        console.warn("[FundFloor] agent overlay fetch failed", agentName, err);
      }
    }

    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      if (event.source !== iframeRef.current?.contentWindow) return;

      const msg = (event.data ?? {}) as { type?: string; agent_name?: string };

      if (msg.type === "ff_request_briefing") {
        handleBriefing();
      } else if (msg.type === "ff_request_agent_overlay") {
        const agentName = msg.agent_name ?? "";
        if (!ALLOWED_AGENTS.has(agentName)) return;
        handleAgentOverlay(agentName);
      }
    }

    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, []);

  return (
    <div style={{ position: "absolute", inset: 0, background: "#05080a" }}>
      <iframe
        ref={iframeRef}
        src="/fund-floor.html"
        title="Trading Desk"
        loading="lazy"
        sandbox="allow-scripts allow-same-origin"
        style={{ width: "100%", height: "100%", border: "none", display: "block" }}
      />
    </div>
  );
}
