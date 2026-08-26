/**
 * PositionDetailPage — /positions/symbol/:symbol
 *
 * Shows a candlestick chart with the confluence framework's price levels
 * overlaid (Play A trigger, Play A stop, Play B trigger, Play B stop,
 * invalidation, target 1, target 2, insider cluster zone) — same info
 * the Pine editor scripts on Brock's desktop show in TradingView, now
 * rendered natively in the app.
 *
 * Data sources:
 *   - Bars: existing /bars/{symbol} endpoint (Alpaca-backed)
 *   - Position: /portfolio/open-positions (existing)
 *   - Pick: /admin/confluence/journal (find matching ticker)
 */
import { useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";
import { getOpenPositions, type OpenPosition } from "@/api/bots";
import { fetchBars } from "@/api/bars";
import TradePriceChart, { type ConfluenceLevels } from "@/components/chart/TradePriceChart";

const GREEN = "#4ade80";
const RED = "#f87171";
const MUTED = "#7e8e7e";

interface ConfluencePick {
  id: number;
  ticker: string;
  entry_date: string;
  entry_price: number;
  spy_at_entry: number;
  signals: {
    insider_cluster: boolean;
    short_surprise_dir: number | null;
    analyst_revisions_dir: number | null;
    fundamental_momentum: boolean | null;
    inst_13f_net_add: boolean | null;
    count: number;
  };
  thesis: string;
  target_price: number | null;
  invalidation_price: number | null;
  horizon_months: number;
  arm_state?: string;
  arm_mode?: string;
  play_a_trigger_price?: number | null;
  play_a_stop_price?: number | null;
  play_b_trigger_price?: number | null;
  play_b_stop_price?: number | null;
  target_1?: number | null;
  target_2?: number | null;
  filled_at?: string | null;
  filled_price?: number | null;
  notes?: string | null;
}

interface Journal { open_picks: ConfluencePick[] }

export default function PositionDetailPage() {
  const { symbol: rawSymbol } = useParams<{ symbol: string }>();
  const symbol = (rawSymbol || "").toUpperCase();

  // 6 months of daily bars — enough for the confluence framework's holding period
  const barsQ = useQuery({
    queryKey: ["position-bars", symbol],
    queryFn: () => fetchBars(symbol, "1Day", undefined, undefined, 180),
    enabled: !!symbol,
  });

  const positionsQ = useQuery({
    queryKey: ["open-positions"],
    queryFn: getOpenPositions,
    refetchInterval: 30_000,
  });

  const journalQ = useQuery({
    queryKey: ["confluence-journal"],
    queryFn: (): Promise<Journal> =>
      client.get<Journal>("/admin/confluence/journal").then(r => r.data),
  });

  const position: OpenPosition | undefined = useMemo(
    () => positionsQ.data?.positions.find(p => p.symbol.toUpperCase() === symbol),
    [positionsQ.data, symbol],
  );
  const pick: ConfluencePick | undefined = useMemo(
    () => journalQ.data?.open_picks.find(p => p.ticker.toUpperCase() === symbol),
    [journalQ.data, symbol],
  );

  const confluenceLevels: ConfluenceLevels | undefined = useMemo(() => {
    if (!pick) return undefined;
    return {
      playATrigger: pick.play_a_trigger_price ?? undefined,
      playAStop: pick.play_a_stop_price ?? undefined,
      playBTrigger: pick.play_b_trigger_price ?? undefined,
      playBStop: pick.play_b_stop_price ?? undefined,
      invalidation: pick.invalidation_price ?? undefined,
      target2: pick.target_2 ?? undefined,
    };
  }, [pick]);

  const entryPrice = position?.entry_price ?? pick?.filled_price ?? pick?.entry_price ?? 0;
  const entryTime = position?.opened_at ?? pick?.filled_at ?? null;
  const takeProfit = pick?.target_1 ?? pick?.target_price ?? null;
  // stop = play A stop for FILLED_A, play B stop for FILLED_B, else invalidation
  const stopLoss = useMemo(() => {
    if (!pick) return null;
    const st = pick.arm_state || "";
    if (st === "FILLED_A") return pick.play_a_stop_price ?? pick.invalidation_price ?? null;
    if (st === "FILLED_B") return pick.play_b_stop_price ?? pick.invalidation_price ?? null;
    return pick.invalidation_price ?? null;
  }, [pick]);

  if (!symbol) {
    return <div style={{ padding: 40, color: MUTED }}>No symbol.</div>;
  }

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px 22px" }}>
      {/* Header */}
      <div style={{ marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 16 }}>
        <div>
          <Link to="/strategy" style={{ color: MUTED, fontSize: 12, textDecoration: "none" }}>← Strategy Lab</Link>
          <h1 style={{ margin: "4px 0 0", fontSize: 32, fontWeight: 700, color: "#f4f8f4", letterSpacing: "-0.02em" }}>
            {symbol}
            {pick && (
              <span style={{ marginLeft: 12, fontSize: 12, color: MUTED, fontWeight: 400 }}>
                · confluence #{pick.id} · {pick.signals.count}/5 signals · {pick.arm_state || "?"}
              </span>
            )}
          </h1>
        </div>
        {position && (
          <div style={{ textAlign: "right", fontFamily: "'JetBrains Mono', monospace" }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: "#f4f8f4" }}>${position.current_price.toFixed(2)}</div>
            <div style={{ fontSize: 14, color: position.unrealized_pnl_usd >= 0 ? GREEN : RED, fontWeight: 600 }}>
              {position.unrealized_pnl_usd >= 0 ? "+" : "−"}${Math.abs(position.unrealized_pnl_usd).toFixed(2)} ({position.unrealized_pnl_pct >= 0 ? "+" : ""}{position.unrealized_pnl_pct.toFixed(2)}%)
            </div>
            <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>
              {position.qty} shares · avg ${position.entry_price.toFixed(2)} · MV ${position.current_value_usd.toFixed(2)}
            </div>
          </div>
        )}
      </div>

      {/* Chart */}
      <div style={{
        border: "1px solid rgba(74,222,128,0.14)",
        borderRadius: 8,
        background: "#18181B",
        padding: 12,
        height: 560,
        marginBottom: 20,
      }}>
        {barsQ.isLoading && <div style={{ color: MUTED, padding: 20 }}>Loading chart...</div>}
        {barsQ.error && <div style={{ color: RED, padding: 20 }}>Chart load failed.</div>}
        {barsQ.data && barsQ.data.bars.length > 0 && (
          <TradePriceChart
            bars={barsQ.data.bars}
            entryPrice={entryPrice}
            entryTime={entryTime}
            side={position?.side || "buy"}
            qty={position?.qty || 0}
            symbol={symbol}
            stopLoss={stopLoss}
            takeProfit={takeProfit}
            livePrice={position?.current_price ?? null}
            confluenceLevels={confluenceLevels}
          />
        )}
      </div>

      {/* Pick metadata panel */}
      {pick && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 16,
        }}>
          {/* Thesis */}
          <div style={{
            border: "1px solid rgba(74,222,128,0.14)",
            borderRadius: 8,
            background: "rgba(10,15,10,0.55)",
            padding: 16,
          }}>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: MUTED, letterSpacing: "0.08em", marginBottom: 8 }}>// THESIS</div>
            <div style={{ color: "#e5e7eb", fontSize: 13, lineHeight: 1.65, whiteSpace: "pre-wrap" }}>
              {pick.thesis}
            </div>
            {pick.notes && (
              <>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: MUTED, letterSpacing: "0.08em", marginTop: 16, marginBottom: 8 }}>// NOTES</div>
                <div style={{ color: "#c9d1c9", fontSize: 12, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>{pick.notes}</div>
              </>
            )}
          </div>

          {/* Signals + Levels */}
          <div style={{
            border: "1px solid rgba(74,222,128,0.14)",
            borderRadius: 8,
            background: "rgba(10,15,10,0.55)",
            padding: 16,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 12,
          }}>
            <div style={{ fontSize: 11, color: MUTED, letterSpacing: "0.08em", marginBottom: 12 }}>// SIGNALS ({pick.signals.count}/5)</div>
            <SignalRow label="insider_cluster" val={pick.signals.insider_cluster} />
            <SignalRow label="analyst_revisions" val={pick.signals.analyst_revisions_dir} />
            <SignalRow label="short_surprise" val={pick.signals.short_surprise_dir} />
            <SignalRow label="fundamental_momentum" val={pick.signals.fundamental_momentum} />
            <SignalRow label="13F_net_add" val={pick.signals.inst_13f_net_add} />
            <div style={{ fontSize: 11, color: MUTED, letterSpacing: "0.08em", marginTop: 16, marginBottom: 8 }}>// LEVELS</div>
            <LevelRow label="entry" val={pick.entry_price} />
            <LevelRow label="target 1" val={pick.target_1} color={GREEN} />
            <LevelRow label="target 2" val={pick.target_2} color={GREEN} />
            <LevelRow label="play A trigger" val={pick.play_a_trigger_price} color="#f87171" />
            <LevelRow label="play A stop" val={pick.play_a_stop_price} color="#fb923c" />
            <LevelRow label="play B trigger" val={pick.play_b_trigger_price} color={GREEN} />
            <LevelRow label="play B stop" val={pick.play_b_stop_price} color="#a78bfa" />
            <LevelRow label="invalidation" val={pick.invalidation_price} color={RED} />
            {pick.filled_price && (
              <>
                <div style={{ fontSize: 11, color: MUTED, letterSpacing: "0.08em", marginTop: 16, marginBottom: 8 }}>// FILL</div>
                <LevelRow label="fill price" val={pick.filled_price} color="#3b82f6" />
                {pick.filled_at && (
                  <div style={{ color: MUTED, fontSize: 11, marginTop: 4 }}>filled {pick.filled_at.slice(0, 10)}</div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {!pick && !journalQ.isLoading && (
        <div style={{ color: MUTED, padding: 20, textAlign: "center" }}>
          No confluence pick found for {symbol}. This position may have been opened outside the framework.
        </div>
      )}
    </div>
  );
}

function SignalRow({ label, val }: { label: string; val: boolean | number | null | undefined }) {
  let display = "—";
  let color = MUTED;
  if (val === true) { display = "PASS"; color = GREEN; }
  else if (val === false) { display = "fail"; color = MUTED; }
  else if (typeof val === "number") {
    if (val > 0) { display = "+1"; color = GREEN; }
    else if (val < 0) { display = "−1"; color = RED; }
    else { display = "0"; color = MUTED; }
  }
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0" }}>
      <span style={{ color: "#c9d1c9" }}>{label}</span>
      <span style={{ color, fontWeight: 600 }}>{display}</span>
    </div>
  );
}

function LevelRow({ label, val, color = "#e5e7eb" }: { label: string; val: number | null | undefined; color?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0" }}>
      <span style={{ color: MUTED }}>{label}</span>
      <span style={{ color, fontVariantNumeric: "tabular-nums" }}>{val ? `$${val.toFixed(2)}` : "—"}</span>
    </div>
  );
}
