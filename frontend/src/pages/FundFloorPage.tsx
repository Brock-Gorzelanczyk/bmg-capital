/**
 * FundFloorPage — BMG Capital Fund Floor pixel-art interface.
 *
 * Wires backend data (briefing board, agent overlays, veto SSE) into the canvas.
 * Canvas IIFE ported from Fund Floor.dc.html into FundFloorCanvas.ts.
 *
 * window.BMGFloor surface:
 *   setCost(who, c)     — daily LLM cost per NPC (who = short name e.g. 'brick')
 *   setBriefing(who, t) — SPACE TALK overlay text; who='board' for briefing board
 *   setDecision(who, t) — last decision/action item
 *   setStale(list)      — array of agent short names to mark stale
 *   setBudget(spent,cap)— bottom HUD meter
 *   vetoFlash()         — triggers amber veto barrier flash
 */
import { useEffect, useRef } from 'react';
import { useQuery, useQueries } from '@tanstack/react-query';
import client from '@/api/client';
import { initFundFloor } from '@/components/FundFloorCanvas';
// Window.BMGFloor types live in src/types/bmg-floor.d.ts and are picked up
// automatically via tsconfig.json's `include` glob. The previous runtime
// side-effect import `import '@/types/bmg-floor'` failed Vite's rolldown
// build because .d.ts files have no runtime code to emit.

interface CIOBriefing {
  briefing_id: string;
  meeting_id: string;
  posted_at: string | null;
  markdown_body: string;
  summary_one_liner: string;
  vetoes_used: number;
  needs_brock: boolean;
}

interface AgentOverlay {
  agent_id: string;
  display_name: string;
  role: string;
  status: 'active' | 'degraded' | 'down';
  last_opening_read: {
    meeting_id: string;
    what_im_seeing: string;
    confidence_in_book: string;
  } | null;
  last_decision: {
    action: string;
    deadline: string;
    status: string;
  } | null;
  daily_cost_usd: number;
  line: string;
}

const AGENT_IDS = [
  'portfolio_manager', 'chief_risk_officer', 'equity_researcher', 'quant_researcher',
  'macro_strategist', 'data_quality_watcher', 'execution_auditor', 'operations', 'sentinel_devops',
];

// Map role_id → short name used by canvas M[] dict
const NPC_KEY_BY_ROLE: Record<string, string> = {
  portfolio_manager: 'brick',
  chief_risk_officer: 'dick',
  equity_researcher: 'nick',
  quant_researcher: 'mick',
  macro_strategist: 'rick',
  data_quality_watcher: 'vick',
  execution_auditor: 'slick',
  operations: 'wick',
  sentinel_devops: 'patrick',
};

export default function FundFloorPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Latest briefing
  const { data: briefing } = useQuery<CIOBriefing>({
    queryKey: ['fund-floor/briefing'],
    queryFn: async () => (await client.get('/api/fund-floor/cio-briefing-board')).data,
    refetchInterval: 30000,
    retry: (failureCount, error: unknown) =>
      (error as { response?: { status?: number } })?.response?.status !== 404,
  });

  // CIO meeting card for budget meter
  const { data: meetingCard } = useQuery({
    queryKey: ['cio-meeting-card'],
    queryFn: async () => (await client.get('/api/monitoring/cio-meeting-card')).data,
    refetchInterval: 60000,
  });

  // All 9 agent overlays in parallel
  const agentQueries = useQueries({
    queries: AGENT_IDS.map((agentId) => ({
      queryKey: ['fund-floor/agent-overlay', agentId],
      queryFn: async (): Promise<AgentOverlay> =>
        (await client.get(`/api/fund-floor/agent-overlay?agent_name=${agentId}`)).data,
      refetchInterval: 60000,
      retry: (failureCount: number, error: unknown) =>
        (error as { response?: { status?: number } })?.response?.status !== 404,
    })),
  });

  // Init canvas on mount
  useEffect(() => {
    if (!canvasRef.current) return;
    // Re-query DOM overlays in case the page rendered them
    const cleanup = initFundFloor(canvasRef.current);
    cleanupRef.current = cleanup;

    // SSE subscription for veto flash
    const sse = new EventSource('/api/fund-floor/veto-stream', { withCredentials: true });
    sse.onmessage = () => {
      window.BMGFloor?.vetoFlash?.();
    };
    sse.onerror = () => {
      // Reconnect handled automatically by EventSource
    };

    return () => {
      sse.close();
      cleanup();
    };
  }, []);

  // Wire briefing data into canvas
  useEffect(() => {
    if (!briefing || !window.BMGFloor) return;
    window.BMGFloor.setBriefing?.(
      'board',
      briefing.summary_one_liner || briefing.markdown_body.slice(0, 400),
    );
  }, [briefing]);

  // Wire budget meter
  useEffect(() => {
    if (!meetingCard || !window.BMGFloor) return;
    window.BMGFloor.setBudget?.(
      meetingCard.daily_budget_spent_usd,
      meetingCard.daily_budget_cap_usd,
    );
  }, [meetingCard]);

  // Wire agent overlays into canvas NPCs
  useEffect(() => {
    agentQueries.forEach((q) => {
      const overlay = q.data;
      if (!overlay || !window.BMGFloor) return;
      const npcKey = NPC_KEY_BY_ROLE[overlay.agent_id];
      if (!npcKey) return;

      // Briefing text: last opening read
      if (overlay.last_opening_read?.what_im_seeing) {
        window.BMGFloor.setBriefing?.(npcKey, overlay.last_opening_read.what_im_seeing.slice(0, 300));
      }

      // Decision text: last commitment
      if (overlay.last_decision?.action) {
        window.BMGFloor.setDecision?.(npcKey, overlay.last_decision.action.slice(0, 200));
      }

      // Daily cost
      if (overlay.daily_cost_usd != null) {
        window.BMGFloor.setCost?.(npcKey, overlay.daily_cost_usd.toFixed(4));
      }
    });

    // Mark degraded/down agents as stale
    const staleKeys = agentQueries
      .filter((q) => q.data?.status !== 'active')
      .map((q) => NPC_KEY_BY_ROLE[q.data?.agent_id || ''])
      .filter(Boolean);
    if (staleKeys.length > 0) {
      window.BMGFloor?.setStale?.(staleKeys);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentQueries.map((q) => q.data).join(',')]);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'radial-gradient(120% 80% at 50% 0%, #0a1410 0%, #05080a 60%)',
        fontFamily: "'Pixelify Sans', sans-serif",
        color: '#dce8dc',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Top bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14, padding: '9px 18px',
        borderBottom: '1px solid rgba(74,222,128,0.16)', background: 'rgba(6,11,6,0.6)',
      }}>
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 13, color: '#eafbe9' }}>
          BMG CAPITAL
        </span>
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 10, letterSpacing: '0.08em', color: '#4ade80' }}>
          // FUND FLOOR
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#7e8e7e', letterSpacing: '0.04em' }}>
          ◄►▲▼ MOVE · SPACE TALK
        </span>
        <span style={{
          display: 'flex', alignItems: 'center', gap: 6, fontFamily: "'Silkscreen', monospace",
          fontSize: 9, color: '#fbbf24', border: '1px solid rgba(251,191,36,0.28)',
          borderRadius: 3, padding: '4px 8px',
        }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#fbbf24', boxShadow: '0 0 6px rgba(251,191,36,0.8)', display: 'inline-block' }} />
          PAPER MODE
        </span>
      </div>

      {/* Game stage */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 14 }}>
        <div id="ff-wrap" style={{
          position: 'relative', aspectRatio: '320/208', height: '100%', maxHeight: '100%',
          width: 'auto', maxWidth: '100%',
          boxShadow: '0 0 0 3px #0c1a12, 0 0 40px rgba(74,222,128,0.18), 0 18px 60px rgba(0,0,0,0.6)',
          borderRadius: 4, overflow: 'hidden',
        }}>
          <canvas
            ref={canvasRef}
            width={320}
            height={208}
            id="ff-canvas"
            style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%',
              display: 'block', background: '#0c1a10', imageRendering: 'pixelated',
            }}
          />
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', background: 'repeating-linear-gradient(0deg, rgba(0,0,0,0.16) 0px, rgba(0,0,0,0.16) 1px, transparent 1px, transparent 3px)', opacity: 0.5 }} />
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', background: 'radial-gradient(120% 90% at 50% 45%, transparent 55%, rgba(2,5,3,0.6) 100%)' }} />

          {/* API budget wall meter */}
          <div id="ff-budget" style={{
            position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)',
            display: 'flex', flexDirection: 'column', gap: 4,
            background: 'rgba(6,17,11,0.9)', border: '2px solid rgba(74,222,128,0.4)',
            borderRadius: 4, padding: '6px 11px', boxShadow: '0 0 14px rgba(74,222,128,0.2)', minWidth: 188,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 8, letterSpacing: '0.08em', color: '#7e8e7e' }}>DAILY API BUDGET</span>
              <span id="ff-budget-val" style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#4ade80' }}>$0.00 / $3.00</span>
            </div>
            <div style={{ height: 5, background: '#0c1a10', border: '1px solid rgba(74,222,128,0.2)', borderRadius: 2, overflow: 'hidden' }}>
              <div id="ff-budget-fill" style={{ height: '100%', width: '0%', background: 'linear-gradient(90deg,#4ade80,#9cffc4)', boxShadow: '0 0 6px rgba(74,222,128,0.6)', transition: 'width 0.4s ease' }} />
            </div>
          </div>

          {/* Interaction hint */}
          <div id="ff-hint" style={{
            position: 'absolute', left: '50%', bottom: 14, transform: 'translateX(-50%)',
            display: 'none', alignItems: 'center', gap: 8,
            fontFamily: "'Silkscreen', monospace", fontSize: 10,
            color: '#04150b', background: '#4ade80', border: '2px solid #eafbe9',
            boxShadow: '0 0 14px rgba(74,222,128,0.5)', borderRadius: 3, padding: '6px 12px',
            whiteSpace: 'nowrap',
          }} />

          {/* GBA dialog box */}
          <div id="ff-dialog" style={{
            position: 'absolute', left: 10, right: 10, bottom: 10, display: 'none',
            background: '#0a1f14', border: '3px solid #4ade80', borderRadius: 5,
            boxShadow: '0 0 0 2px #04120a, 0 0 22px rgba(74,222,128,0.35)',
            padding: '13px 15px 15px', maxHeight: '62%', overflowY: 'auto',
          }} />
        </div>
      </div>

      {/* Roster legend */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14, padding: '8px 18px',
        borderTop: '1px solid rgba(74,222,128,0.16)', background: 'rgba(6,11,6,0.6)', overflowX: 'auto',
      }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
          <span style={{ width: 9, height: 9, background: '#1f8a5b', borderRadius: 2, display: 'inline-block' }} />
          <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#dce8dc' }}>BROCK · CIO (you)</span>
        </span>
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#4ade80', whiteSpace: 'nowrap' }}>LEADERSHIP:</span>
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#9fb0a0', whiteSpace: 'nowrap' }}>Brick · Dick</span>
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#a78bfa', whiteSpace: 'nowrap' }}>RESEARCH:</span>
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#9fb0a0', whiteSpace: 'nowrap' }}>Nick · Mick · Rick</span>
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#38bdf8', whiteSpace: 'nowrap' }}>OPS &amp; AUDIT:</span>
        <span style={{ fontFamily: "'Silkscreen', monospace", fontSize: 9, color: '#9fb0a0', whiteSpace: 'nowrap' }}>Vick · Slick · Wick · Patrick</span>
      </div>
    </div>
  );
}
