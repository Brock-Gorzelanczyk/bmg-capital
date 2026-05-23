import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getAlerts, createAlert, deleteAlert, getTriggers, testAlert } from "@/api/alerts";
import { Trash2, Plus, Zap, Bell, BellOff, Clock } from "lucide-react";
import { COMPANY_INFO } from "@/data/companyInfo";
import SectorPill from "@/components/ui/SectorPill";
import { cn } from "@/lib/utils";

const SIGNAL_META: Record<string, { label: string; desc: string; color: string }> = {
  golden_cross:    { label: "Golden Cross",     desc: "50-day MA crosses above 200-day MA — long-term bullish",              color: "text-[#22C55E]" },
  death_cross:     { label: "Death Cross",      desc: "50-day MA crosses below 200-day MA — long-term bearish",              color: "text-[#EF4444]" },
  rsi_oversold:    { label: "RSI Oversold",     desc: "14-day RSI drops below 30 — potential reversal buy signal",          color: "text-blue-400" },
  rsi_overbought:  { label: "RSI Overbought",   desc: "14-day RSI rises above 70 — potential reversal sell signal",         color: "text-orange-400" },
  macd_bull:       { label: "MACD Bullish",     desc: "MACD line crosses above signal line — momentum turning positive",    color: "text-[#22C55E]" },
  macd_bear:       { label: "MACD Bearish",     desc: "MACD line crosses below signal line — momentum turning negative",   color: "text-[#EF4444]" },
  volume_breakout: { label: "Volume Breakout",  desc: "Volume spikes to 2× average — unusual institutional activity",      color: "text-purple-400" },
  breakout_52w:    { label: "52-Week High",     desc: "Price reaches a new 52-week high — strong relative strength",       color: "text-yellow-400" },
};

const SIGNAL_TYPES = Object.keys(SIGNAL_META);

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor(diff / 60_000);
  if (h >= 24) return `${Math.floor(h / 24)}d ago`;
  if (h >= 1) return `${h}h ago`;
  return `${m}m ago`;
}

export default function Alerts() {
  const qc = useQueryClient();
  const { data: alerts = [] } = useQuery({ queryKey: ["alerts"], queryFn: getAlerts });
  const { data: triggers = [] } = useQuery({ queryKey: ["triggers"], queryFn: getTriggers, refetchInterval: 30_000 });
  const [form, setForm] = useState({ symbol: "", signal_type: "rsi_oversold", threshold: "" });
  const [showCreate, setShowCreate] = useState(false);

  const createMut = useMutation({
    mutationFn: () => createAlert(
      form.symbol.toUpperCase(),
      form.signal_type,
      form.threshold ? parseFloat(form.threshold) : undefined
    ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] });
      setForm({ symbol: "", signal_type: "rsi_oversold", threshold: "" });
      setShowCreate(false);
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteAlert,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const testMut = useMutation({
    mutationFn: ({ symbol, signal_type }: { symbol: string; signal_type: string }) =>
      testAlert(symbol, signal_type),
  });

  const meta = SIGNAL_META[form.signal_type];

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Alerts</h1>
          <p className="text-[#475569] text-sm mt-0.5">Get notified when technical signals fire</p>
        </div>
        <button
          onClick={() => setShowCreate((s) => !s)}
          className="flex items-center gap-1.5 bg-[#3B82F6] hover:bg-[#2563EB] text-[#F8FAFC] font-semibold text-sm px-3 py-1.5 rounded-lg"
        >
          <Plus size={14} /> New Alert
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl p-4 space-y-4">
          <h2 className="text-xs font-semibold text-[#475569] uppercase tracking-widest">Configure Alert</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-[#475569] mb-1 block">Symbol</label>
              <input
                value={form.symbol}
                onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })}
                placeholder="AAPL"
                className="w-full bg-[#020617] border border-[#334155] text-white text-base md:text-sm px-3 py-2 rounded-lg placeholder-zinc-600 focus:outline-none focus:border-zinc-600 uppercase"
              />
            </div>
            <div>
              <label className="text-xs text-[#475569] mb-1 block">Signal</label>
              <select
                value={form.signal_type}
                onChange={(e) => setForm({ ...form, signal_type: e.target.value })}
                className="w-full bg-[#020617] border border-[#334155] text-white text-base md:text-sm px-3 py-2 rounded-lg focus:outline-none focus:border-zinc-600"
              >
                {SIGNAL_TYPES.map((st) => (
                  <option key={st} value={st}>{SIGNAL_META[st]?.label ?? st}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-[#475569] mb-1 block">Threshold <span className="text-[#475569]">(optional)</span></label>
              <input
                type="number"
                value={form.threshold}
                onChange={(e) => setForm({ ...form, threshold: e.target.value })}
                placeholder="e.g. 70"
                className="w-full bg-[#020617] border border-[#334155] text-white text-base md:text-sm px-3 py-2 rounded-lg placeholder-zinc-600 focus:outline-none focus:border-zinc-600"
              />
            </div>
          </div>
          {meta && (
            <div className="text-xs text-[#475569] bg-[#1E293B]/50 rounded-lg px-3 py-2 flex items-start gap-2">
              <Zap size={12} className={cn("mt-0.5 shrink-0", meta.color)} />
              {meta.desc}
            </div>
          )}
          <div className="flex gap-2">
            <button
              onClick={() => createMut.mutate()}
              disabled={!form.symbol || createMut.isPending}
              className="bg-[#3B82F6] hover:bg-[#2563EB] disabled:opacity-50 text-[#F8FAFC] font-semibold text-sm px-4 py-2 rounded-lg"
            >
              {createMut.isPending ? "Creating…" : "Create Alert"}
            </button>
            <button onClick={() => setShowCreate(false)} className="text-[#475569] hover:text-[#F8FAFC] text-sm px-3 py-2">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Active alerts */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1E293B] flex items-center justify-between">
          <span className="text-xs font-semibold text-[#475569] uppercase tracking-widest flex items-center gap-1.5">
            <Bell size={12} /> Active Alerts
          </span>
          <span className="text-xs text-[#475569]">{alerts.length} configured</span>
        </div>
        {alerts.length === 0 ? (
          <div className="py-10 text-center">
            <BellOff size={24} className="text-zinc-800 mx-auto mb-2" />
            <p className="text-[#475569] text-sm">No alerts configured.</p>
            <button onClick={() => setShowCreate(true)} className="mt-2 text-white hover:underline text-xs">
              Create your first alert →
            </button>
          </div>
        ) : (
          alerts.map((a: any) => {
            const sigMeta = SIGNAL_META[a.signal_type];
            return (
              <div key={a.id} className="flex items-center px-4 py-3 min-h-[44px] border-b border-[#1E293B]/50 last:border-0 hover:bg-[#1E293B]/40">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono font-bold text-white">{a.symbol}</span>
                    <SectorPill symbol={a.symbol} />
                    {COMPANY_INFO[a.symbol] && (
                      <span className="text-xs text-[#475569]">{COMPANY_INFO[a.symbol].name}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={cn("text-xs font-semibold", sigMeta?.color ?? "text-[#94A3B8]")}>
                      {sigMeta?.label ?? a.signal_type.replace(/_/g, " ")}
                    </span>
                    {a.threshold && (
                      <span className="text-xs text-[#475569]">@ {a.threshold}</span>
                    )}
                    {sigMeta && (
                      <span className="text-[11px] text-[#475569] hidden sm:inline">{sigMeta.desc}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => testMut.mutate({ symbol: a.symbol, signal_type: a.signal_type })}
                    className="text-[#475569] hover:text-[#F8FAFC] transition-colors p-1"
                    title="Test alert now"
                  >
                    <Zap size={14} />
                  </button>
                  <button
                    onClick={() => deleteMut.mutate(a.id)}
                    className="text-[#475569] hover:text-[#EF4444] transition-colors p-1"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Recent triggers */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1E293B] flex items-center gap-1.5">
          <Clock size={12} className="text-[#475569]" />
          <span className="text-xs font-semibold text-[#475569] uppercase tracking-widest">Recent Triggers</span>
        </div>
        {triggers.length === 0 ? (
          <div className="py-8 text-center text-[#475569] text-sm">No alerts triggered yet.</div>
        ) : (
          triggers.slice(0, 20).map((t: any) => {
            const sigMeta = SIGNAL_META[t.signal_type];
            return (
              <div key={t.id} className="flex items-center justify-between px-4 py-3 border-b border-[#1E293B]/50 last:border-0">
                <div className="flex items-center gap-3">
                  <Zap size={13} className={cn("shrink-0", sigMeta?.color ?? "text-[#475569]")} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-white text-sm">{t.symbol}</span>
                      <SectorPill symbol={t.symbol} />
                    </div>
                    <div className="text-xs text-[#475569] mt-0.5">
                      {sigMeta?.label ?? t.signal_type.replace(/_/g, " ")}
                      {t.message && <span className="ml-1.5 text-[#475569]">{t.message}</span>}
                    </div>
                  </div>
                </div>
                <span className="text-xs text-[#475569] shrink-0">{timeAgo(t.triggered_at)}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
