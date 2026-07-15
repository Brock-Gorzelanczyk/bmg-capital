/**
 * Contract Detail — single-option live view (Robinhood-style).
 *
 * Route: /contract/:positionId
 *
 * Reuses parseOCC + optionPnL from lib/parseOCC.ts so display math and
 * humanized labels are byte-identical to what Bot Detail shows. Backend
 * fetches live via /api/contract/positions/{id}, /api/contract/bars/{occ},
 * and /api/contract/quote/{occ} (2s poll for the tick tail).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { createChart, LineSeries, ColorType } from "lightweight-charts";
import type { IChartApi, UTCTimestamp, ISeriesApi } from "lightweight-charts";
import client from "@/api/client";
import { ArrowLeft } from "lucide-react";
import { parseOCC, dteColor, optionPnL } from "@/lib/parseOCC";

type Window = "1D" | "1W" | "1M" | "3M" | "YTD" | "ALL";

interface PositionDetail {
  position_id: number;
  bot: { name: string | null; asset_class: string | null; profile_id: number | null };
  occ_symbol: string | null;
  is_option: boolean;
  parsed: { root: string; expiry: string; type: "CALL" | "PUT"; strike: number } | null;
  underlying: string | null;
  spot: number | null;
  expiry_date: string | null;
  dte: number | null;
  contracts: number;
  side: "long" | "short" | string;
  avg_premium: number;
  cost_basis: number;
  mark: number | null;
  market_value: number | null;
  open_pl: number | null;
  open_pl_pct: number | null;
  breakeven: number | null;
  mark_source: string;
  fetched_at: string;
  opened_at: string | null;
  closed_at: string | null;
  entry_trade_id: number | null;
  alpaca_order_id: string | null;
}

interface BarRow { ts: string; o: number; h: number; l: number; c: number; }

// ─── Formatters ─────────────────────────────────────────────────────────────

function fmtUsd(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v < 0 ? "-$" : "$";
  return s + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${fmtUsd(v, digits)}`;
}
function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

const MONTHS_LONG = ["January","February","March","April","May","June","July","August","September","October","November","December"];
function fmtExpiryHuman(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS_LONG[m - 1]} ${d}, ${y}`;
}
function fmtFillTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function ContractDetailPage() {
  const { positionId } = useParams<{ positionId: string }>();
  const navigate = useNavigate();
  const [window, setWindow] = useState<Window>("1D");
  const [live, setLive] = useState(false);
  const [tickTail, setTickTail] = useState<Array<{ ts: number; mark: number }>>([]);

  // ── Position detail: 5s poll ─────────────────────────────────────────────
  const posQuery = useQuery({
    queryKey: ["contract", "position", positionId],
    queryFn: async (): Promise<PositionDetail> => {
      const r = await client.get<PositionDetail>(`/contract/positions/${positionId}`);
      return r.data;
    },
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
    enabled: Boolean(positionId),
  });

  // ── Bars: refetch on window change; 60s poll within window ───────────────
  const barsQuery = useQuery({
    queryKey: ["contract", "bars", posQuery.data?.occ_symbol, window],
    queryFn: async (): Promise<BarRow[]> => {
      const occ = posQuery.data?.occ_symbol;
      if (!occ) return [];
      const r = await client.get<{ bars: BarRow[] }>(`/contract/bars/${occ}`, { params: { window } });
      return r.data.bars || [];
    },
    refetchInterval: 60_000,
    enabled: Boolean(posQuery.data?.occ_symbol),
    retry: false,
  });

  // ── Quote tail: 3s poll while tab visible ─────────────────────────────────
  useEffect(() => {
    const occ = posQuery.data?.occ_symbol;
    if (!occ) return;
    let cancelled = false;
    let dropTimer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      if (cancelled) return;
      try {
        const r = await client.get<{ mark: number | null }>(`/contract/quote/${occ}`);
        const m = r.data.mark;
        if (typeof m === "number" && m > 0) {
          setLive(true);
          if (dropTimer) clearTimeout(dropTimer);
          setTickTail((prev) => {
            const next = [...prev, { ts: Date.now() / 1000, mark: m }];
            // Keep last ~120 points (~6min at 3s poll).
            return next.length > 120 ? next.slice(-120) : next;
          });
          // If no fresh tick for 15s, dim the LIVE dot.
          dropTimer = setTimeout(() => setLive(false), 15_000);
        }
      } catch {
        setLive(false);
      }
    }

    tick();
    const iv = setInterval(tick, 3_000);
    return () => { cancelled = true; clearInterval(iv); if (dropTimer) clearTimeout(dropTimer); };
  }, [posQuery.data?.occ_symbol]);

  // ── Live-recomputed values (server + tail) ───────────────────────────────
  const pos = posQuery.data;
  const liveMark = tickTail.length ? tickTail[tickTail.length - 1].mark : (pos?.mark ?? null);
  const live_pl = useMemo(() => {
    if (!pos || liveMark == null) return { pl: pos?.open_pl ?? null, pct: pos?.open_pl_pct ?? null, value: pos?.market_value ?? null };
    const p = optionPnL(pos.avg_premium, liveMark, pos.contracts);
    return { pl: p.pl, pct: p.plPct, value: p.value };
  }, [pos, liveMark]);

  // ── Chart wiring ─────────────────────────────────────────────────────────
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const entryLineRef = useRef<any>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = createChart(hostRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
        fontFamily: "ui-monospace, SFMono-Regular, monospace",
      },
      grid: {
        vertLines: { color: "rgba(148,163,184,0.06)" },
        horzLines: { color: "rgba(148,163,184,0.06)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
      autoSize: true,
      handleScroll: false,
      handleScale: false,
      crosshair: { mode: 1 },
    });
    const series = chart.addSeries(LineSeries, {
      color: "#34d399",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      entryLineRef.current = null;
    };
  }, []);

  // Set base bars series
  useEffect(() => {
    if (!seriesRef.current) return;
    const bars = barsQuery.data || [];
    const basePts = bars
      .map((b) => ({ time: Math.floor(new Date(b.ts).getTime() / 1000) as UTCTimestamp, value: b.c }))
      .sort((a, b) => (a.time as number) - (b.time as number));
    // Also append tick-tail points that come after the last bar.
    const lastBarTs = basePts.length ? (basePts[basePts.length - 1].time as number) : 0;
    const tailPts = tickTail
      .filter((t) => t.ts > lastBarTs)
      .map((t) => ({ time: Math.floor(t.ts) as UTCTimestamp, value: t.mark }));
    // De-dup by timestamp — most recent wins.
    const seen = new Map<number, number>();
    for (const p of [...basePts, ...tailPts]) seen.set(p.time as number, p.value);
    const merged = [...seen.entries()].sort((a, b) => a[0] - b[0]).map(([t, v]) => ({ time: t as UTCTimestamp, value: v }));
    seriesRef.current.setData(merged);

    // Entry reference line — dashed horizontal at avg_premium.
    if (pos?.avg_premium && seriesRef.current) {
      if (entryLineRef.current) {
        try { seriesRef.current.removePriceLine(entryLineRef.current); } catch {}
      }
      entryLineRef.current = seriesRef.current.createPriceLine({
        price: pos.avg_premium,
        color: "#94a3b8",
        lineWidth: 1,
        lineStyle: 2,   // dashed
        axisLabelVisible: true,
        title: `entry $${pos.avg_premium.toFixed(2)}`,
      });
    }

    // Line color reflects live P&L direction.
    if (pos && liveMark != null && seriesRef.current) {
      seriesRef.current.applyOptions({
        color: liveMark >= pos.avg_premium ? "#34d399" : "#f87171",
      });
    }
  }, [barsQuery.data, tickTail, pos, liveMark]);

  if (!positionId) return null;
  if (posQuery.isLoading) {
    return (
      <div className="min-h-screen bg-[#040804] text-slate-200 p-6">
        <div className="text-sm text-slate-500 font-mono">loading contract…</div>
      </div>
    );
  }
  if (posQuery.isError || !pos) {
    return (
      <div className="min-h-screen bg-[#040804] text-slate-200 p-6">
        <div className="text-sm text-red-400 font-mono">
          position #{positionId} not found or not accessible
        </div>
        <button onClick={() => navigate(-1)} className="mt-4 text-emerald-400 hover:underline text-sm">← back</button>
      </div>
    );
  }

  const isCall = pos.parsed?.type === "CALL";
  const changeVsEntry = liveMark != null ? liveMark - pos.avg_premium : null;
  const changePct = liveMark != null && pos.avg_premium > 0
    ? ((liveMark - pos.avg_premium) / pos.avg_premium) * 100
    : null;
  const heroColor = changeVsEntry != null && changeVsEntry >= 0 ? "#34d399" : "#f87171";
  const dteC = pos.dte != null ? dteColor(pos.dte) : "#94a3b8";

  return (
    <div className="min-h-screen bg-[#040804] text-slate-200 p-6">
      {/* Back nav */}
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-2 text-slate-400 hover:text-emerald-300 text-sm font-mono mb-4"
      >
        <ArrowLeft size={14} /> back
      </button>

      {/* Header — bot + OCC + LIVE dot */}
      <div className="mb-4 flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-mono tracking-wider text-emerald-300">
            {pos.parsed ? `${pos.parsed.root} $${pos.parsed.strike % 1 === 0 ? pos.parsed.strike.toFixed(0) : pos.parsed.strike.toFixed(2)}` : pos.occ_symbol}
          </h1>
          <div className="text-xs text-slate-500 mt-1 flex gap-2 items-center">
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${isCall ? "bg-emerald-900/50 text-emerald-300" : "bg-red-900/50 text-red-300"}`}>
              {pos.parsed?.type}
            </span>
            <span>{fmtExpiryHuman(pos.expiry_date)}</span>
            {pos.dte != null && (
              <span
                className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
                style={{ color: dteC, border: `1px solid ${dteC}40`, background: `${dteC}14` }}
              >
                {pos.dte}d
              </span>
            )}
            <span className="text-slate-600 ml-1 font-mono">{pos.occ_symbol}</span>
            {pos.bot?.name && (
              <>
                <span className="text-slate-600">·</span>
                <Link to={`/strategy/bot/${pos.bot.name}`} className="text-cyan-400 hover:underline">
                  {pos.bot.name}
                </Link>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`inline-block w-2 h-2 rounded-full ${live ? "bg-emerald-400 animate-pulse" : "bg-slate-600"}`}
          />
          <span className="text-slate-500">{live ? "LIVE" : "idle"}</span>
        </div>
      </div>

      {/* Hero — big mark, change since entry */}
      <div className="mb-6 border rounded-lg p-6" style={{ borderColor: `${heroColor}30`, background: `${heroColor}08` }}>
        <div className="text-xs uppercase tracking-widest text-slate-400 mb-2">Contract Mark</div>
        <div className="text-5xl font-mono tabular-nums" style={{ color: heroColor }}>
          {fmtUsd(liveMark, 2)}
        </div>
        <div className="mt-2 text-sm font-mono">
          <span style={{ color: heroColor }}>
            {fmtSigned(changeVsEntry, 2)} ({fmtPct(changePct, 2)})
          </span>
          <span className="text-slate-500 ml-2">since entry $${pos.avg_premium.toFixed(2)}</span>
        </div>
      </div>

      {/* Chart controls */}
      <div className="mb-2 flex gap-1">
        {(["1D","1W","1M","3M","YTD","ALL"] as Window[]).map((w) => (
          <button
            key={w}
            onClick={() => setWindow(w)}
            className={`px-3 py-1 text-xs font-mono rounded ${
              window === w
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                : "text-slate-400 border border-transparent hover:border-slate-700"
            }`}
          >
            {w}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="mb-6 border border-slate-800 rounded-lg p-4 bg-slate-950/40">
        <div ref={hostRef} className="h-72 w-full" />
        {(barsQuery.data?.length ?? 0) === 0 && !barsQuery.isLoading && (
          <div className="text-xs text-slate-500 font-mono text-center mt-2">
            no bars yet · live ticks will populate the chart as they arrive
          </div>
        )}
      </div>

      {/* Position tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Tile label="Contracts" value={String(pos.contracts)} />
        <Tile label="Cost basis" value={fmtUsd(pos.cost_basis, 2)} sub={`$${pos.avg_premium.toFixed(2)} × ${pos.contracts} × 100`} />
        <Tile label="Market value" value={fmtUsd(live_pl.value, 2)} />
        <Tile
          label="Open P&L"
          value={fmtSigned(live_pl.pl, 2)}
          sub={fmtPct(live_pl.pct, 2)}
          color={(live_pl.pl ?? 0) >= 0 ? "#34d399" : "#f87171"}
        />
      </div>

      {/* Contract card */}
      <div className="border border-slate-800 rounded-lg p-4 bg-slate-950/40 mb-6">
        <div className="text-xs uppercase tracking-widest text-slate-400 mb-3">Contract</div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-y-3 gap-x-6 text-sm font-mono">
          <Field k="Underlying" v={pos.underlying || "—"} />
          <Field k="Spot" v={pos.spot != null ? `$${pos.spot.toFixed(2)}` : "—"} />
          <Field k="Type" v={pos.parsed?.type || "—"} />
          <Field k="Strike" v={pos.parsed ? `$${pos.parsed.strike % 1 === 0 ? pos.parsed.strike.toFixed(0) : pos.parsed.strike.toFixed(2)}` : "—"} />
          <Field k="Expiry" v={`${fmtExpiryHuman(pos.expiry_date)}${pos.dte != null ? ` · ${pos.dte}d` : ""}`} />
          <Field k="Breakeven" v={pos.breakeven != null ? `$${pos.breakeven.toFixed(2)}` : "—"} />
          <Field k="Avg premium" v={`$${pos.avg_premium.toFixed(2)}`} />
          <Field k="Fill time" v={fmtFillTime(pos.opened_at)} />
          <Field k="Owning bot" v={pos.bot?.name || "—"} />
          <Field k="Side" v={<span className={pos.side === "short" ? "text-red-400" : "text-emerald-400"}>{(pos.side || "long").toUpperCase()}</span>} />
          <Field k="Alpaca order" v={pos.alpaca_order_id ? <span className="text-[10px] text-slate-500">{pos.alpaca_order_id.slice(0, 12)}…</span> : "—"} />
          <Field k="Mark source" v={<span className="text-[10px] text-slate-500">{pos.mark_source}</span>} />
        </div>
      </div>

      <div className="text-[10px] text-slate-600 text-center font-mono">
        polling contract quote every 3s · bars every 60s · position every 5s
      </div>
    </div>
  );
}

function Tile({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="border border-slate-800 rounded-lg p-4 bg-slate-950/40">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-xl font-mono tabular-nums mt-1" style={{ color: color || "#f4f8f4" }}>
        {value}
      </div>
      {sub && <div className="text-[10px] text-slate-500 font-mono mt-1">{sub}</div>}
    </div>
  );
}

function Field({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
      <div className="text-slate-200">{v}</div>
    </div>
  );
}
