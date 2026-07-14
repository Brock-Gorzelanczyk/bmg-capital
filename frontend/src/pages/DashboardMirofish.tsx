import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";

// ─── 5×7 dot-matrix font map ───────────────────────────────────────────────
// One row = 1 byte per column (7 rows). 1 = dot on, 0 = off. Left-to-right.
const FONT_5x7: Record<string, number[]> = {
  "0": [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
  "1": [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
  "2": [0b01110, 0b10001, 0b00001, 0b00110, 0b01000, 0b10000, 0b11111],
  "3": [0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110],
  "4": [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
  "5": [0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110],
  "6": [0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
  "7": [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
  "8": [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
  "9": [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100],
  "$": [0b00100, 0b01111, 0b10100, 0b01110, 0b00101, 0b11110, 0b00100],
  ",": [0b00000, 0b00000, 0b00000, 0b00000, 0b00110, 0b00100, 0b01000],
  ".": [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00110, 0b00110],
  "-": [0b00000, 0b00000, 0b00000, 0b11111, 0b00000, 0b00000, 0b00000],
  "+": [0b00000, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0b00000],
  " ": [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000],
  "%": [0b11001, 0b11010, 0b00100, 0b00100, 0b01011, 0b10011, 0b00000],
};

function DotMatrix({
  text,
  colorHex,
  dotSize = 6,
  gap = 2,
}: {
  text: string;
  colorHex: string;
  dotSize?: number;
  gap?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const chars = text.split("");
    const w = chars.length * (5 * (dotSize + gap) + gap * 3);
    const h = 7 * (dotSize + gap);
    c.width = w * (window.devicePixelRatio || 1);
    c.height = h * (window.devicePixelRatio || 1);
    c.style.width = `${w}px`;
    c.style.height = `${h}px`;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
    ctx.fillStyle = "#0b120b";
    ctx.fillRect(0, 0, w, h);
    let x = gap;
    for (const ch of chars) {
      const glyph = FONT_5x7[ch] ?? FONT_5x7[" "];
      for (let row = 0; row < 7; row++) {
        for (let col = 0; col < 5; col++) {
          const on = (glyph[row] >> (4 - col)) & 1;
          ctx.fillStyle = on ? colorHex : "#122012";
          ctx.beginPath();
          ctx.arc(
            x + col * (dotSize + gap) + dotSize / 2,
            row * (dotSize + gap) + dotSize / 2,
            dotSize / 2,
            0,
            Math.PI * 2,
          );
          ctx.fill();
        }
      }
      x += 5 * (dotSize + gap) + gap * 3;
    }
  }, [text, colorHex, dotSize, gap]);
  return <canvas ref={canvasRef} />;
}

// ─── Hooks / data ──────────────────────────────────────────────────────────
interface HeroStats {
  realized_pnl_cents: number;
  realized_pnl_today_cents: number;
  trades_closed_alltime: number;
  win_rate: number | null;
  sharpe_30d: number | null;
  updated_at: string;
}
interface SessionMeta {
  sleeve_last_scan_at: Record<string, string>;
  pr_next_rebalance_at: Record<string, string | null>;
  as_of: string;
}
interface ReconResp {
  verdict: string;
  divergence_severity: string;
  broker_positions_count: number;
  db_positions_count: number;
}
interface TopTrade {
  trade_id: number;
  bot: string;
  sleeve: string;
  symbol: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl_usd: number;
  pnl_pct: number;
  opened_at: string;
  closed_at: string;
  daily_marks?: number[];
}
interface ClosedTrade {
  id: number;
  closed_at: string;
  symbol: string;
  pnl_usd: number;
  bot: string;
  sleeve: string;
}
interface RidgeSlice {
  date: string;
  pnl_cents: number;
}

const useHero = () =>
  useQuery({
    queryKey: ["mirofish", "hero"],
    queryFn: async () =>
      (await client.get<HeroStats>("/dashboard/hero-stats")).data,
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
  });

const useSession = () =>
  useQuery({
    queryKey: ["mirofish", "session"],
    queryFn: async () =>
      (await client.get<SessionMeta>("/dashboard/session-meta")).data,
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
  });

const useRecon = () =>
  useQuery({
    queryKey: ["mirofish", "recon"],
    queryFn: async () =>
      (await client.get<ReconResp>("/admin/reconcile/broker")).data,
    refetchInterval: 30_000,
    retry: false,
  });

const useTopTrades = (dir: "wins" | "losses") =>
  useQuery({
    queryKey: ["mirofish", "top", dir],
    queryFn: async () =>
      (
        await client.get<{ trades: TopTrade[] }>("/trades/top", {
          params: { dir, window: "month", limit: 5 },
        })
      ).data.trades,
    refetchInterval: 60_000,
    retry: false,
  });

const useTradeStream = () =>
  useQuery({
    queryKey: ["mirofish", "closed-trades"],
    queryFn: async () =>
      (
        await client.get<{ trades: ClosedTrade[]; next_cursor: number }>(
          "/trades/closed",
          { params: { limit: 500 } },
        )
      ).data,
    refetchInterval: 30_000,
    retry: false,
  });

// Reuses the existing /api/dashboard/v2 batch for signals + bot activity +
// sleeves + regime — one call powers ~half the page.
interface DashV2 {
  portfolio: {
    total_value_cents: number;
    today_pnl_cents: number;
    today_pnl_pct: number;
    return_30d_pct: number;
    return_all_time_pct?: number;
  };
  regime: {
    vix_regime: string;
    trend_regime: string;
    btc_dominance: number;
    label: string;
    description: string;
  };
  sleeves: Record<
    string,
    {
      today_pnl_pct?: number;
      today_pnl_usd?: number;
      value_cents?: number;
      bots_active?: number;
      bots_total?: number;
    }
  >;
  health: {
    bots_active: number;
    bots_total: number;
    status: string;
  };
  recent_signals: Array<{
    id: number;
    ts: string;
    bot_name: string;
    display_name?: string;
    symbol: string;
    side: string;
    strategy?: string;
    reason?: string;
  }>;
}
const useDashV2 = () =>
  useQuery({
    queryKey: ["mirofish", "dashv2"],
    queryFn: async () => (await client.get<DashV2>("/dashboard/v2")).data,
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
  });

interface FunnelResp {
  scanned: number;
  passed_filter: number;
  executed: number;
  winners: number;
  win_pct: number;
  discipline_edge_pct: number;
}
const useSignalFunnel = () =>
  useQuery({
    queryKey: ["mirofish", "funnel"],
    queryFn: async () =>
      (await client.get<FunnelResp>("/dashboard/signal-funnel-today")).data,
    refetchInterval: 30_000,
    retry: false,
  });

interface QuoteMap {
  quotes: Record<string, { last: number }>;
}
const useLiveQuotes = (symbols: string[]) =>
  useQuery({
    queryKey: ["mirofish", "live-quotes", symbols.join(",")],
    queryFn: async () =>
      (
        await client.get<QuoteMap>("/dashboard/live-quotes", {
          params: { symbols: symbols.join(",") },
        })
      ).data.quotes,
    refetchInterval: 15_000,
    retry: false,
  });

interface BotListItem {
  name: string;
  display_name?: string;
  asset_class: string;
  enabled: boolean;
  starting_capital_usd?: number | null;
}
const useBots = () =>
  useQuery({
    queryKey: ["mirofish", "bots"],
    queryFn: async () => {
      const res = await client.get<{ bots: BotListItem[] }>("/bots");
      return res.data.bots ?? [];
    },
    refetchInterval: 15_000,
    retry: false,
  });

const useRidgeline = () =>
  useQuery({
    queryKey: ["mirofish", "ridgeline"],
    queryFn: async () =>
      (
        await client.get<{ sleeves: Record<string, RidgeSlice[]> }>(
          "/pnl/daily-distribution",
          { params: { sessions: 30, group: "sleeve" } },
        )
      ).data.sleeves,
    refetchInterval: 60 * 60 * 1000, // hourly
    retry: false,
  });

// ─── Utils ─────────────────────────────────────────────────────────────────
function fmtUsd(cents: number, signed = false): string {
  const dollars = cents / 100;
  const sign = signed && dollars >= 0 ? "+" : "";
  return `${sign}$${Math.round(dollars).toLocaleString()}`;
}
function fmtHms(d: Date): string {
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(
    d.getUTCMinutes(),
  ).padStart(2, "0")}:${String(d.getUTCSeconds()).padStart(2, "0")} UTC`;
}
function secondsSince(iso?: string | null): number | null {
  if (!iso) return null;
  try {
    return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  } catch {
    return null;
  }
}
function untilString(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const diff = new Date(iso).getTime() - Date.now();
    if (diff <= 0) return "due";
    const h = Math.floor(diff / 3600_000);
    const d = Math.floor(h / 24);
    if (d >= 1) return `${d}d ${h % 24}h`;
    const m = Math.floor((diff % 3600_000) / 60_000);
    return `${h}h ${m}m`;
  } catch {
    return "—";
  }
}
function nearestRebalance(map: Record<string, string | null>): string | null {
  let best: string | null = null;
  let bestT = Infinity;
  for (const iso of Object.values(map)) {
    if (!iso) continue;
    const t = new Date(iso).getTime();
    if (t > Date.now() && t < bestT) {
      bestT = t;
      best = iso;
    }
  }
  return best;
}

// ─── Panel: Hero dot-matrix P&L ────────────────────────────────────────────
function HeroPanel({ hero }: { hero?: HeroStats }) {
  const cents = hero?.realized_pnl_today_cents ?? 0;
  const dollars = cents / 100;
  const positive = dollars >= 0;
  const displayText = fmtUsd(cents, true);
  const color = positive ? "#4ade80" : "#f87171";

  const winRateStr =
    hero?.win_rate !== null && hero?.win_rate !== undefined
      ? `${(hero.win_rate * 100).toFixed(0)}%`
      : "—";
  const sharpeStr =
    hero?.sharpe_30d !== null && hero?.sharpe_30d !== undefined
      ? hero.sharpe_30d.toFixed(2)
      : "—";

  return (
    <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/10 p-6">
      <div className="text-xs uppercase tracking-widest text-emerald-400/80 mb-3">
        Realized P&L Today
      </div>
      <div className="overflow-x-auto">
        <DotMatrix text={displayText} colorHex={color} dotSize={9} gap={2} />
      </div>
      <div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Closed Trades", value: hero?.trades_closed_alltime ?? 0 },
          { label: "Win Rate", value: winRateStr },
          { label: "Sharpe 30d", value: sharpeStr },
          {
            label: "Realized All-Time",
            value: hero ? fmtUsd(hero.realized_pnl_cents, true) : "—",
          },
        ].map((chip) => (
          <div
            key={chip.label}
            className="border border-slate-800 bg-slate-950/40 rounded px-3 py-2"
          >
            <div className="text-[10px] uppercase tracking-widest text-slate-500">
              {chip.label}
            </div>
            <div className="text-lg font-mono text-slate-200 tabular-nums">
              {chip.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Panel: session bar ────────────────────────────────────────────────────
function SessionBar({
  session,
  recon,
  reconStale,
}: {
  session?: SessionMeta;
  recon?: ReconResp;
  reconStale: boolean;
}) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const isSynced = recon?.verdict === "SYNCED";
  const dotColor = isSynced && !reconStale ? "#4ade80" : "#f59e0b";
  const label = isSynced
    ? `LIVE · RECON SYNCED n=${recon?.broker_positions_count ?? "?"}`
    : `SIM · RECON ${recon?.verdict ?? "PENDING"} n=${
        recon?.broker_positions_count ?? "?"
      }`;

  const nextRebal = session ? nearestRebalance(session.pr_next_rebalance_at) : null;
  const sleeves = ["stocks", "crypto", "options", "quant"] as const;

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border border-slate-800 bg-slate-950/40 rounded px-4 py-2 text-xs font-mono">
      <span className="text-emerald-300">{fmtHms(now)}</span>
      {sleeves.map((s) => {
        const secs = secondsSince(session?.sleeve_last_scan_at?.[s]);
        return (
          <span key={s} className="text-slate-400">
            <span className="text-slate-500 uppercase mr-1">{s}</span>
            {secs !== null ? `${secs}s` : "—"}
          </span>
        );
      })}
      <span className="flex items-center gap-1">
        <span
          className="inline-block w-2 h-2 rounded-full animate-pulse"
          style={{ backgroundColor: dotColor }}
        />
        <span className="text-slate-300">{label}</span>
      </span>
      <span className="text-slate-400 ml-auto">
        <span className="text-slate-500 uppercase mr-1">Next rebal</span>
        {untilString(nextRebal)}
      </span>
    </div>
  );
}

// ─── Panel: top wins/losses with auto-cycle ────────────────────────────────
function TopTradesCard() {
  const [dir, setDir] = useState<"wins" | "losses">("wins");
  const [idx, setIdx] = useState(0);
  const { data: trades } = useTopTrades(dir);

  useEffect(() => {
    setIdx(0);
  }, [dir]);
  useEffect(() => {
    if (!trades || trades.length === 0) return;
    const t = setInterval(() => setIdx((i) => (i + 1) % trades.length), 6000);
    return () => clearInterval(t);
  }, [trades]);

  const trade = trades && trades.length > 0 ? trades[idx] : null;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4 h-full">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs uppercase tracking-widest text-slate-400">
          Top {dir === "wins" ? "Wins" : "Losses"} · Month
        </div>
        <div className="flex gap-1">
          {(["wins", "losses"] as const).map((d) => (
            <button
              key={d}
              onClick={() => setDir(d)}
              className={`px-2 py-0.5 text-[10px] font-mono uppercase rounded ${
                d === dir
                  ? d === "wins"
                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                    : "bg-red-500/20 text-red-300 border border-red-500/40"
                  : "text-slate-500 border border-transparent hover:border-slate-700"
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      {trade ? (
        <div className="space-y-3">
          <div className="flex items-baseline justify-between">
            <div>
              <div className="text-slate-200 font-mono text-base">
                {trade.symbol}
              </div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">
                {trade.bot} · {trade.sleeve}
              </div>
            </div>
            <div className="text-right">
              <div
                className={`text-xl font-mono tabular-nums ${
                  trade.pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {trade.pnl_usd >= 0 ? "+" : ""}${trade.pnl_usd.toFixed(2)}
              </div>
              <div className="text-[10px] text-slate-500">
                {(trade.pnl_pct * 100).toFixed(2)}%
              </div>
            </div>
          </div>

          <div className="text-[10px] text-slate-500 font-mono">
            ${trade.entry_price.toFixed(4)} → ${trade.exit_price.toFixed(4)}
          </div>

          {trade.daily_marks && trade.daily_marks.length > 1 && (
            <Sparkline
              values={trade.daily_marks}
              color={trade.pnl_usd >= 0 ? "#4ade80" : "#f87171"}
            />
          )}

          <div className="flex gap-1 justify-center mt-3">
            {trades!.map((_, i) => (
              <span
                key={i}
                className={`w-1.5 h-1.5 rounded-full ${
                  i === idx ? "bg-emerald-400" : "bg-slate-700"
                }`}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className="text-slate-500 text-xs text-center py-8">
          no {dir} in the last 30 days
        </div>
      )}
    </div>
  );
}

function Sparkline({
  values,
  color,
  width = 260,
  height = 40,
}: {
  values: number[];
  color: string;
  width?: number;
  height?: number;
}) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1e-9, max - min);
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} className="block">
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ─── Panel: Trade Lattice (Galton histogram) ───────────────────────────────
function TradeLattice({ trades }: { trades: ClosedTrade[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dotsRef = useRef<
    Array<{ x: number; y: number; targetY: number; color: string; vy: number }>
  >([]);
  const rafRef = useRef<number | null>(null);
  const sizeRef = useRef({ w: 0, h: 0, ready: false });
  const CAP = 500;

  // Compute layout once when canvas mounts. Cap retry loop at 60 attempts to
  // prevent the "uncapped rAF blank page" bug the spec warns about.
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    let attempts = 0;
    const tryLayout = () => {
      attempts++;
      const w = c.clientWidth || 0;
      const h = c.clientHeight || 0;
      if (w > 10 && h > 10) {
        const dpr = window.devicePixelRatio || 1;
        c.width = w * dpr;
        c.height = h * dpr;
        const ctx = c.getContext("2d");
        if (ctx) ctx.scale(dpr, dpr);
        sizeRef.current = { w, h, ready: true };
        drawStatic();
        return;
      }
      if (attempts < 60) requestAnimationFrame(tryLayout);
    };
    tryLayout();
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Build the target positions whenever the trades change.
  useEffect(() => {
    if (!sizeRef.current.ready) return;
    const { w, h } = sizeRef.current;
    // Bin width — divide the visible x range into 41 bins (-20..+20) around $0
    const N_BINS = 41;
    const cap = trades.slice(-CAP);
    const maxAbs = Math.max(1, ...cap.map((t) => Math.abs(t.pnl_usd || 0)));
    const binCounts = new Array(N_BINS).fill(0);
    const binX = (i: number) => ((i + 0.5) / N_BINS) * w;
    const DOT_R = 3;
    const newDots: typeof dotsRef.current = [];
    for (const t of cap) {
      const pnl = t.pnl_usd || 0;
      // normalize to [-1, 1]
      const norm = Math.max(-1, Math.min(1, pnl / maxAbs));
      const bin = Math.max(
        0,
        Math.min(N_BINS - 1, Math.floor(((norm + 1) / 2) * N_BINS)),
      );
      const stackIndex = binCounts[bin];
      binCounts[bin]++;
      const targetY = h - 20 - stackIndex * (DOT_R * 2 + 1);
      newDots.push({
        x: binX(bin),
        y: -20,
        targetY,
        color: pnl >= 0 ? "#4ade80" : "#f87171",
        vy: 0,
      });
    }
    dotsRef.current = newDots;
    // Kick off a rAF loop that self-halts when all dots have settled.
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    const step = () => {
      const c = canvasRef.current;
      if (!c) return;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      const { w: cw, h: ch } = sizeRef.current;
      ctx.clearRect(0, 0, cw, ch);
      drawStatic();
      let anyMoving = false;
      for (const d of dotsRef.current) {
        if (d.y < d.targetY) {
          d.vy = Math.min(6, d.vy + 0.4);
          d.y += d.vy;
          if (d.y >= d.targetY) d.y = d.targetY;
          else anyMoving = true;
        }
        ctx.fillStyle = d.color;
        ctx.beginPath();
        ctx.arc(d.x, d.y, DOT_R, 0, Math.PI * 2);
        ctx.fill();
      }
      if (anyMoving) rafRef.current = requestAnimationFrame(step);
      else rafRef.current = null;
    };
    rafRef.current = requestAnimationFrame(step);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trades]);

  function drawStatic() {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const { w, h } = sizeRef.current;
    ctx.fillStyle = "#040804";
    ctx.fillRect(0, 0, w, h);
    // baseline
    ctx.strokeStyle = "#1c2b1c";
    ctx.beginPath();
    ctx.moveTo(0, h - 15);
    ctx.lineTo(w, h - 15);
    ctx.stroke();
    // center line ($0)
    ctx.strokeStyle = "#2a3a2a";
    ctx.beginPath();
    ctx.moveTo(w / 2, 0);
    ctx.lineTo(w / 2, h - 15);
    ctx.stroke();
    // labels
    ctx.fillStyle = "#4b5f4b";
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillText("$0", w / 2 + 4, h - 4);
    ctx.fillText("loss", 4, h - 4);
    ctx.textAlign = "right";
    ctx.fillText("gain", w - 4, h - 4);
    ctx.textAlign = "left";
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="text-xs uppercase tracking-widest text-slate-400 mb-2">
        Trade Lattice · closed trades this session
      </div>
      <canvas ref={canvasRef} className="w-full h-56 block" />
    </div>
  );
}

// ─── Panel: Ridgeline ──────────────────────────────────────────────────────
function RidgelinePanel({
  sleeves,
}: {
  sleeves?: Record<string, RidgeSlice[]>;
}) {
  const [open, setOpen] = useState(true);

  const rows = useMemo(() => {
    if (!sleeves) return [];
    const order = ["stocks", "crypto", "options", "quant"];
    return order
      .filter((k) => (sleeves[k]?.length ?? 0) > 0)
      .map((k) => ({ key: k, points: sleeves[k]! }));
  }, [sleeves]);

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-xs uppercase tracking-widest text-slate-400 hover:text-slate-200"
      >
        <span>Sleeve P&L Ridgeline · last 30d</span>
        <span className="text-slate-500">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="p-4 space-y-6">
          {rows.length === 0 && (
            <div className="text-slate-500 text-xs">no daily P&L yet</div>
          )}
          {rows.map((r) => (
            <Ridge key={r.key} label={r.key} points={r.points} />
          ))}
        </div>
      )}
    </div>
  );
}

function Ridge({ label, points }: { label: string; points: RidgeSlice[] }) {
  const width = 720;
  const height = 60;
  const vals = points.map((p) => p.pnl_cents);
  const min = Math.min(0, ...vals);
  const max = Math.max(0, ...vals);
  const range = Math.max(1, max - min);
  const zeroY = height - ((0 - min) / range) * (height - 6) - 3;
  const pts = points
    .map((p, i) => {
      const x = (i / Math.max(1, points.length - 1)) * width;
      const y = height - ((p.pnl_cents - min) / range) * (height - 6) - 3;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const areaPts = `${pts} ${width},${height} 0,${height}`;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <div className="text-[10px] uppercase tracking-widest text-slate-500">
          {label}
        </div>
        <div className="text-[10px] font-mono text-slate-500">
          min ${(min / 100).toFixed(0)} · max ${(max / 100).toFixed(0)}
        </div>
      </div>
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="block">
        <line
          x1={0}
          x2={width}
          y1={zeroY}
          y2={zeroY}
          stroke="#2a3a2a"
          strokeDasharray="2 3"
        />
        <polygon points={areaPts} fill="rgba(74,222,128,0.10)" />
        <polyline points={pts} fill="none" stroke="#4ade80" strokeWidth={1.5} />
      </svg>
    </div>
  );
}

// ─── Additional panels matching the mock ──────────────────────────────────

function PortfolioValueHero({ v2 }: { v2?: DashV2 }) {
  const pv = v2?.portfolio.total_value_cents ?? 0;
  const allTimePct = v2?.portfolio.return_all_time_pct;
  const allTimeUsd =
    v2?.portfolio.total_value_cents && v2?.portfolio.return_all_time_pct !== undefined
      ? (v2.portfolio.total_value_cents / 100) *
        (v2.portfolio.return_all_time_pct / (100 + v2.portfolio.return_all_time_pct))
      : null;
  const positive = (allTimePct ?? 0) >= 0;
  return (
    <div className="rounded-lg border border-emerald-500/30 bg-emerald-950/10 p-5">
      <div className="flex items-center justify-between text-[10px] uppercase tracking-widest">
        <span className="text-emerald-400/80">Portfolio Value · Paper</span>
        <span className="text-slate-500">All Systems Normal</span>
      </div>
      <div className="mt-2 text-4xl font-mono tabular-nums text-emerald-300">
        ${(pv / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </div>
      <div className={`mt-1 text-xs font-mono ${positive ? "text-emerald-400" : "text-red-400"}`}>
        {positive ? "▲" : "▼"}{" "}
        {allTimeUsd !== null
          ? `${allTimeUsd >= 0 ? "+" : ""}$${Math.abs(allTimeUsd).toLocaleString("en-US", { maximumFractionDigits: 0 })} all-time · `
          : ""}
        {allTimePct !== undefined ? `${(allTimePct >= 0 ? "+" : "") + allTimePct.toFixed(2)}%` : "—"}
      </div>
    </div>
  );
}

function LiveFiringNow({ v2 }: { v2?: DashV2 }) {
  const signals = (v2?.recent_signals ?? []).slice(0, 6);
  const distinctBots = new Set(signals.map((s) => s.bot_name)).size;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4 h-full">
      <div className="flex items-baseline justify-between mb-3">
        <div className="text-xs uppercase tracking-widest text-slate-400">
          Live Firing Now
        </div>
        <div className="text-[10px] text-slate-500">across {distinctBots} bots</div>
      </div>
      {signals.length === 0 ? (
        <div className="text-slate-500 text-xs text-center py-6">
          no signals in the last window
        </div>
      ) : (
        <div className="space-y-2">
          {signals.map((s) => {
            const long = ["buy", "long"].includes(s.side.toLowerCase());
            return (
              <div key={s.id} className="flex items-center gap-3 text-xs">
                <span
                  className={`inline-block px-2 py-0.5 font-mono rounded text-[10px] ${
                    long
                      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                      : "bg-red-500/20 text-red-300 border border-red-500/40"
                  }`}
                >
                  {long ? "LONG" : "SHORT"}
                </span>
                <span className="font-mono text-slate-200 min-w-[75px]">{s.symbol}</span>
                <span className="text-slate-500 truncate flex-1">
                  {s.display_name ?? s.bot_name} · {s.strategy ?? "—"}
                </span>
                <span className="text-[10px] text-slate-600 font-mono">
                  {new Date(s.ts).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                    hour12: false,
                  })}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function BotActivity({ v2, bots }: { v2?: DashV2; bots?: BotListItem[] }) {
  // Real per-bot list from /api/bots (upgraded 2026-07-14). Shows first 12
  // enabled bots with sleeve + funded state. Matches mock's per-row layout.
  const armed = v2?.health.bots_active ?? 0;
  const total = v2?.health.bots_total ?? 0;
  const rows = (bots ?? [])
    .filter((b) => b.enabled)
    .slice(0, 12)
    .map((b) => {
      const funded = (b.starting_capital_usd ?? 0) > 0;
      return {
        name: b.display_name ?? b.name,
        sleeve: b.asset_class,
        state: funded ? "armed" : "idle",
      };
    });
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4 h-full">
      <div className="flex items-baseline justify-between mb-3">
        <div className="text-xs uppercase tracking-widest text-slate-400">Bot Activity</div>
        <div className="text-[10px] font-mono text-emerald-400">
          {armed} / {total} ARMED
        </div>
      </div>
      <div className="grid grid-cols-2 gap-1.5 max-h-64 overflow-y-auto">
        {rows.length === 0 && (
          <div className="col-span-2 text-slate-500 text-xs text-center py-4">
            no active bots
          </div>
        )}
        {rows.map((r) => (
          <div
            key={r.name}
            className="flex items-center justify-between border border-slate-800 rounded px-2 py-1"
          >
            <div className="truncate flex-1">
              <div className="text-[11px] text-slate-300 truncate">{r.name}</div>
              <div className="text-[9px] text-slate-500 uppercase">{r.sleeve}</div>
            </div>
            <div
              className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ml-2 ${
                r.state === "armed"
                  ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                  : "bg-slate-700/50 text-slate-400 border border-slate-600"
              }`}
            >
              {r.state}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SignalFunnel({ funnel }: { funnel?: FunnelResp }) {
  const stages = [
    { label: "Scanned", value: funnel?.scanned ?? 0 },
    { label: "Passed Filter", value: funnel?.passed_filter ?? 0 },
    { label: "Executed", value: funnel?.executed ?? 0 },
    { label: "Winners", value: funnel?.winners ?? 0 },
  ];
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4 h-full">
      <div className="text-xs uppercase tracking-widest text-slate-400 mb-3">
        Today · Signal Funnel
      </div>
      <div className="grid grid-cols-4 gap-2">
        {stages.map((s) => (
          <div key={s.label} className="border border-slate-800 rounded p-3 text-center">
            <div className="text-[9px] uppercase text-slate-500 tracking-widest">{s.label}</div>
            <div className="text-2xl font-mono text-emerald-300 mt-1 tabular-nums">{s.value}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 text-[10px] text-slate-500 text-center">
        discipline edge · {funnel?.discipline_edge_pct?.toFixed(2) ?? "0.00"}% of scanned signals
        reach execution · win {funnel?.win_pct?.toFixed(1) ?? "0.0"}%
      </div>
    </div>
  );
}

function SleeveTiles({ v2 }: { v2?: DashV2 }) {
  const order = ["stocks", "crypto", "options", "quant"] as const;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {order.map((k) => {
        const s = v2?.sleeves[k];
        const pct = s?.today_pnl_pct ?? 0;
        const positive = pct >= 0;
        return (
          <div
            key={k}
            className={`rounded border p-3 ${
              positive
                ? "border-emerald-500/30 bg-emerald-950/10"
                : "border-red-500/30 bg-red-950/10"
            }`}
          >
            <div className="text-xs text-slate-300 capitalize">{k}</div>
            <div
              className={`mt-1 text-lg font-mono tabular-nums ${
                positive ? "text-emerald-300" : "text-red-300"
              }`}
            >
              TODAY {pct >= 0 ? "+" : ""}
              {pct.toFixed(2)}%
            </div>
          </div>
        );
      })}
    </div>
  );
}

function MarketRegime({ v2 }: { v2?: DashV2 }) {
  const r = v2?.regime;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4 h-full">
      <div className="text-xs uppercase tracking-widest text-slate-400 mb-2">
        Market Regime
      </div>
      <div className="text-xl font-mono text-emerald-300">
        {r?.label ?? "—"}
      </div>
      <div className="mt-2 text-[10px] text-slate-500">{r?.description ?? ""}</div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[10px] font-mono text-slate-400">
        <div>
          <span className="text-slate-500 mr-1">VIX</span>
          {r?.vix_regime ?? "—"}
        </div>
        <div>
          <span className="text-slate-500 mr-1">BTC.D</span>
          {r?.btc_dominance !== undefined ? `${r.btc_dominance.toFixed(0)}%` : "—"}
        </div>
        <div>
          <span className="text-slate-500 mr-1">TREND</span>
          {r?.trend_regime ?? "—"}
        </div>
      </div>
    </div>
  );
}

const TICKER_SYMBOLS = [
  "SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "AMZN",
  "BTC/USD", "ETH/USD", "SOL/USD",
];

function TickerTape() {
  const { data: quotes } = useLiveQuotes(TICKER_SYMBOLS);
  return (
    <div className="border border-slate-800 bg-slate-950/60 rounded overflow-hidden">
      <style>{`
        @keyframes mirofish-marquee {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
      <div className="flex items-center gap-3 px-3 py-2 text-[10px] font-mono">
        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 rounded">
          <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" /> LIVE
        </span>
        <div className="flex-1 overflow-hidden">
          <div
            className="whitespace-nowrap flex gap-8 text-slate-400"
            style={{
              animation: "mirofish-marquee 60s linear infinite",
              width: "max-content",
            }}
          >
            {[...TICKER_SYMBOLS, ...TICKER_SYMBOLS].map((s, i) => {
              const q = quotes?.[s];
              const price = q?.last;
              return (
                <span key={i} className="flex items-baseline gap-2">
                  <span className="text-slate-300">{s}</span>
                  <span className="text-slate-400 tabular-nums">
                    {price !== undefined
                      ? price.toLocaleString("en-US", {
                          minimumFractionDigits: price < 10 ? 4 : 2,
                          maximumFractionDigits: price < 10 ? 4 : 2,
                        })
                      : "—"}
                  </span>
                </span>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function QuickLinkCards() {
  const links = [
    { to: "/strategy/library", title: "Strategy Library", subtitle: "100+ strategies built" },
    { to: "/fund/tear-sheet", title: "Fund Tear Sheet", subtitle: "LP-grade performance" },
    { to: "/fund/floor", title: "Walk the Fund Floor", subtitle: "meet your agents" },
  ];
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      {links.map((l) => (
        <a
          key={l.to}
          href={l.to}
          className="rounded border border-slate-800 bg-slate-950/40 p-3 hover:border-emerald-500/40 hover:bg-emerald-950/20 transition-colors flex items-center justify-between"
        >
          <div>
            <div className="text-sm text-slate-200 font-mono">{l.title}</div>
            <div className="text-[10px] text-slate-500">{l.subtitle}</div>
          </div>
          <div className="text-emerald-400 text-lg">→</div>
        </a>
      ))}
    </div>
  );
}

// ─── Page ──────────────────────────────────────────────────────────────────
export default function DashboardMirofish() {
  const hero = useHero();
  const session = useSession();
  const recon = useRecon();
  const closed = useTradeStream();
  const ridges = useRidgeline();
  const v2 = useDashV2();
  const funnel = useSignalFunnel();
  const bots = useBots();

  const reconStale =
    recon.isError || (recon.dataUpdatedAt > 0 && Date.now() - recon.dataUpdatedAt > 5 * 60 * 1000);

  return (
    <div className="min-h-screen bg-[#040804] text-slate-200 p-6 space-y-4">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-lg font-mono tracking-widest text-emerald-400">
            BMG · MIROFISH DASHBOARD
          </h1>
          <p className="text-[10px] text-slate-500 mt-1">
            every figure traces to an API field · no fake numbers
          </p>
        </div>
        <div className="text-[10px] text-slate-500 font-mono">
          hero {hero.dataUpdatedAt > 0 ? new Date(hero.dataUpdatedAt).toLocaleTimeString() : "—"}
        </div>
      </div>

      <SessionBar
        session={session.data}
        recon={recon.data}
        reconStale={reconStale}
      />
      <TickerTape />

      {/* Row: Portfolio Value + Realized P&L Today */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PortfolioValueHero v2={v2.data} />
        <HeroPanel hero={hero.data} />
      </div>

      {/* Row: LIVE FIRING NOW + BOT ACTIVITY */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <LiveFiringNow v2={v2.data} />
        <BotActivity v2={v2.data} bots={bots.data} />
      </div>

      {/* Row: Trade Lattice full-width */}
      <TradeLattice trades={closed.data?.trades ?? []} />

      {/* Row: Signal Funnel + Top Wins/Losses */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SignalFunnel funnel={funnel.data} />
        <TopTradesCard />
      </div>

      {/* Row: Sleeve tiles + Market Regime */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SleeveTiles v2={v2.data} />
        <MarketRegime v2={v2.data} />
      </div>

      <RidgelinePanel sleeves={ridges.data} />

      <QuickLinkCards />

      <div className="text-[10px] text-slate-600 text-center font-mono">
        hero+session+v2 ~5s · recon ~30s · lattice ~30s · ridgeline hourly
      </div>
    </div>
  );
}
