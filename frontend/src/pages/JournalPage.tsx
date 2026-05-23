import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Edit2, TrendingUp, TrendingDown, BookOpen, BarChart2, Star } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { getEntries, getStats, createEntry, updateEntry, deleteEntry } from "@/api/journal";
import type { JournalEntry, CreateEntryBody } from "@/api/journal";

// ── helpers ─────────────────────────────────────────────────────────────────

function fmt$(n: number) {
  return (n >= 0 ? "+" : "") + "$" + Math.abs(n).toFixed(2);
}

function moodLabel(v: number) {
  return ["", "😞", "😕", "😐", "😊", "😄"][v] ?? "—";
}

function timeAgo(iso: string | null) {
  if (!iso) return "";
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d === 0) return "Today";
  if (d === 1) return "Yesterday";
  return `${d}d ago`;
}

// ── Entry form modal ─────────────────────────────────────────────────────────

const BLANK: CreateEntryBody = {
  symbol: "",
  trade_date: new Date().toISOString().slice(0, 10),
  side: "buy",
  qty: 0,
  entry_price: 0,
  exit_price: null,
  pnl: null,
  setup: null,
  mood: 3,
  confidence: 3,
  notes: null,
  lessons: null,
  rating: null,
};

const SETUPS = ["Breakout", "Pullback", "Reversal", "Gap Fill", "Trend Follow", "Earnings Play", "Other"];

function EntryModal({
  initial,
  onClose,
  onSave,
}: {
  initial?: JournalEntry | null;
  onClose: () => void;
  onSave: (body: CreateEntryBody) => void;
}) {
  const [form, setForm] = useState<CreateEntryBody>(
    initial
      ? {
          symbol: initial.symbol,
          trade_date: initial.trade_date,
          side: initial.side,
          qty: initial.qty,
          entry_price: initial.entry_price,
          exit_price: initial.exit_price,
          pnl: initial.pnl,
          setup: initial.setup,
          mood: initial.mood,
          confidence: initial.confidence,
          notes: initial.notes,
          lessons: initial.lessons,
          rating: initial.rating,
        }
      : BLANK
  );

  function set<K extends keyof CreateEntryBody>(k: K, v: CreateEntryBody[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  const autoCalcPnl = () => {
    if (form.entry_price && form.exit_price != null && form.qty) {
      const mult = form.side === "buy" ? 1 : -1;
      const pnl = mult * (form.exit_price - form.entry_price) * form.qty;
      set("pnl", parseFloat(pnl.toFixed(2)));
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#020617]/80 backdrop-blur-sm p-4">
      <div className="bg-[#0F172A] border border-[#334155] rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#1E293B]">
          <span className="text-white font-semibold">{initial ? "Edit Entry" : "New Journal Entry"}</span>
          <button onClick={onClose} className="text-[#475569] hover:text-[#F8FAFC]">✕</button>
        </div>

        <div className="p-5 space-y-4">
          {/* Symbol + Date + Side row */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-1">Symbol</label>
              <input
                value={form.symbol}
                onChange={(e) => set("symbol", e.target.value.toUpperCase())}
                placeholder="AAPL"
                className="w-full bg-[#1E293B] border border-[#334155] text-white text-sm px-3 py-2 rounded-lg font-mono focus:outline-none focus:border-[#3B82F6]"
              />
            </div>
            <div>
              <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-1">Date</label>
              <input
                type="date"
                value={form.trade_date}
                onChange={(e) => set("trade_date", e.target.value)}
                className="w-full bg-[#1E293B] border border-[#334155] text-white text-sm px-3 py-2 rounded-lg focus:outline-none focus:border-[#3B82F6]"
              />
            </div>
            <div>
              <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-1">Side</label>
              <div className="flex gap-1.5 mt-1">
                {(["buy", "sell"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => set("side", s)}
                    className={cn(
                      "flex-1 py-1.5 text-xs font-bold rounded-lg transition-colors",
                      form.side === s
                        ? s === "buy" ? "bg-emerald-900 text-[#22C55E]" : "bg-rose-900 text-[#EF4444]"
                        : "bg-[#1E293B] text-[#475569]"
                    )}
                  >
                    {s.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Prices row */}
          <div className="grid grid-cols-3 gap-3">
            {(["qty", "entry_price", "exit_price"] as const).map((k) => (
              <div key={k}>
                <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-1">
                  {k === "qty" ? "Qty / Shares" : k === "entry_price" ? "Entry $" : "Exit $"}
                </label>
                <input
                  type="number"
                  value={form[k] ?? ""}
                  onChange={(e) => set(k, e.target.value ? parseFloat(e.target.value) : null as never)}
                  onBlur={autoCalcPnl}
                  placeholder="0"
                  className="w-full bg-[#1E293B] border border-[#334155] text-white text-sm px-3 py-2 rounded-lg font-mono focus:outline-none focus:border-[#3B82F6]"
                />
              </div>
            ))}
          </div>

          {/* P&L */}
          <div>
            <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-1">P&amp;L ($)</label>
            <input
              type="number"
              value={form.pnl ?? ""}
              onChange={(e) => set("pnl", e.target.value ? parseFloat(e.target.value) : null)}
              placeholder="Auto-calculated or override"
              className="w-full bg-[#1E293B] border border-[#334155] text-white text-sm px-3 py-2 rounded-lg font-mono focus:outline-none focus:border-[#3B82F6]"
            />
          </div>

          {/* Setup */}
          <div>
            <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-2">Setup</label>
            <div className="flex flex-wrap gap-1.5">
              {SETUPS.map((s) => (
                <button
                  key={s}
                  onClick={() => set("setup", form.setup === s ? null : s)}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-full transition-colors",
                    form.setup === s
                      ? "bg-[#3B82F6] text-white"
                      : "bg-[#1E293B] text-[#94A3B8] hover:bg-[#334155]"
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Mood + Confidence */}
          <div className="grid grid-cols-2 gap-4">
            {([
              { key: "mood", label: "Mood", emojis: ["😞", "😕", "😐", "😊", "😄"] },
              { key: "confidence", label: "Confidence", emojis: ["1", "2", "3", "4", "5"] },
            ] as const).map(({ key, label, emojis }) => (
              <div key={key}>
                <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-2">{label}</label>
                <div className="flex gap-1">
                  {emojis.map((e, i) => (
                    <button
                      key={i}
                      onClick={() => set(key, (i + 1) as 1 | 2 | 3 | 4 | 5)}
                      className={cn(
                        "flex-1 h-8 text-sm rounded-lg transition-colors",
                        form[key] === i + 1
                          ? "bg-[#3B82F6] text-white"
                          : "bg-[#1E293B] text-[#475569] hover:bg-[#334155]"
                      )}
                    >
                      {e}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Notes */}
          <div>
            <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-1">Trade Notes</label>
            <textarea
              value={form.notes ?? ""}
              onChange={(e) => set("notes", e.target.value || null)}
              rows={3}
              placeholder="What happened? Why did you enter/exit?"
              className="w-full bg-[#1E293B] border border-[#334155] text-white text-sm px-3 py-2 rounded-lg focus:outline-none focus:border-[#3B82F6] resize-none"
            />
          </div>

          {/* Lessons */}
          <div>
            <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-1">Lessons Learned</label>
            <textarea
              value={form.lessons ?? ""}
              onChange={(e) => set("lessons", e.target.value || null)}
              rows={2}
              placeholder="What would you do differently?"
              className="w-full bg-[#1E293B] border border-[#334155] text-white text-sm px-3 py-2 rounded-lg focus:outline-none focus:border-[#3B82F6] resize-none"
            />
          </div>

          {/* Rating */}
          <div>
            <label className="text-[10px] text-[#475569] uppercase tracking-wider block mb-2">Trade Rating</label>
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map((r) => (
                <button
                  key={r}
                  onClick={() => set("rating", form.rating === r ? null : r)}
                  className={cn("text-lg transition-colors", form.rating != null && form.rating >= r ? "text-[#F59E0B]" : "text-[#334155]")}
                >
                  ★
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="px-5 pb-5 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-xl bg-[#1E293B] text-[#94A3B8] text-sm font-medium hover:bg-[#334155] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => { if (form.symbol) onSave(form); }}
            className="flex-1 py-2.5 rounded-xl bg-[#3B82F6] text-white text-sm font-semibold hover:bg-[#2563EB] transition-colors"
          >
            {initial ? "Save Changes" : "Add Entry"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function JournalPage() {
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<JournalEntry | null>(null);
  const [filterSymbol, setFilterSymbol] = useState("");

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["journal", filterSymbol],
    queryFn: () => getEntries(filterSymbol || undefined),
    staleTime: 30_000,
  });

  const { data: stats } = useQuery({
    queryKey: ["journal-stats"],
    queryFn: getStats,
    staleTime: 30_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["journal"] });
    qc.invalidateQueries({ queryKey: ["journal-stats"] });
  };

  const createMut = useMutation({
    mutationFn: createEntry,
    onSuccess: () => { toast.success("Entry added"); setModalOpen(false); invalidate(); },
    onError: () => toast.error("Failed to save entry"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: CreateEntryBody }) => updateEntry(id, body),
    onSuccess: () => { toast.success("Entry updated"); setEditing(null); invalidate(); },
    onError: () => toast.error("Failed to update entry"),
  });

  const deleteMut = useMutation({
    mutationFn: deleteEntry,
    onSuccess: () => { toast.success("Entry deleted"); invalidate(); },
  });

  const openNew = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (e: JournalEntry) => { setEditing(e); setModalOpen(true); };

  return (
    <div className="space-y-4 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Trade Journal</h1>
          <p className="text-[#475569] text-sm mt-0.5">Document and reflect on every trade</p>
        </div>
        <button
          onClick={openNew}
          className="flex items-center gap-2 bg-[#3B82F6] hover:bg-[#2563EB] text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors"
        >
          <Plus size={15} />
          New Entry
        </button>
      </div>

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[
            { label: "Total Entries", value: stats.total_entries, icon: BookOpen, color: "text-[#94A3B8]" },
            { label: "Win Rate", value: `${stats.win_rate}%`, icon: BarChart2, color: "text-[#3B82F6]" },
            { label: "Total P&L", value: fmt$(stats.total_pnl), icon: stats.total_pnl >= 0 ? TrendingUp : TrendingDown, color: stats.total_pnl >= 0 ? "text-[#22C55E]" : "text-[#EF4444]" },
            { label: "Avg Mood", value: moodLabel(Math.round(stats.avg_mood)), icon: Star, color: "text-[#F59E0B]" },
            { label: "With Notes", value: stats.entries_with_notes, icon: BookOpen, color: "text-[#8B5CF6]" },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="bg-[#0F172A] border border-[#1E293B] rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <Icon size={13} className={color} />
                <span className="text-[#475569] text-[10px] uppercase tracking-wider">{label}</span>
              </div>
              <div className={cn("text-xl font-bold font-mono", color)}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filter */}
      <div className="flex items-center gap-3">
        <input
          value={filterSymbol}
          onChange={(e) => setFilterSymbol(e.target.value.toUpperCase())}
          placeholder="Filter by symbol…"
          className="bg-[#0F172A] border border-[#1E293B] text-white text-sm px-3 py-2 rounded-lg w-40 placeholder-[#475569] focus:outline-none focus:border-[#334155] font-mono"
        />
        {filterSymbol && (
          <button onClick={() => setFilterSymbol("")} className="text-[#475569] hover:text-[#F8FAFC] text-xs">
            Clear
          </button>
        )}
        <span className="text-[#475569] text-xs ml-auto">{entries.length} entries</span>
      </div>

      {/* Entries list */}
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 bg-[#0F172A] border border-[#1E293B] rounded-xl animate-pulse" />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl p-12 text-center">
          <BookOpen size={32} className="text-[#334155] mx-auto mb-3" />
          <p className="text-[#475569] text-sm">No journal entries yet</p>
          <p className="text-[#334155] text-xs mt-1">Click "New Entry" to log your first trade</p>
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map((e) => (
            <div key={e.id} className="bg-[#0F172A] border border-[#1E293B] rounded-xl px-4 py-3 flex items-start gap-4 hover:border-[#334155] transition-colors group">
              {/* Side badge */}
              <div className={cn(
                "text-[11px] font-bold px-2 py-1 rounded-lg shrink-0 mt-0.5",
                e.side === "buy" ? "bg-emerald-900/60 text-[#22C55E]" : "bg-rose-900/60 text-[#EF4444]"
              )}>
                {e.side.toUpperCase()}
              </div>

              {/* Main content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-white font-bold font-mono">{e.symbol}</span>
                  {e.setup && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#1E293B] text-[#94A3B8]">{e.setup}</span>
                  )}
                  {e.rating && (
                    <span className="text-[#F59E0B] text-xs">{"★".repeat(e.rating)}</span>
                  )}
                  <span className="text-[#475569] text-xs ml-auto">{timeAgo(e.created_at)} · {e.trade_date}</span>
                </div>

                <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                  {e.qty > 0 && (
                    <span className="text-[#475569] text-xs font-mono">{e.qty} shares</span>
                  )}
                  {e.entry_price > 0 && (
                    <span className="text-[#94A3B8] text-xs font-mono">@ ${e.entry_price.toFixed(2)}</span>
                  )}
                  {e.exit_price != null && (
                    <span className="text-[#94A3B8] text-xs font-mono">→ ${e.exit_price.toFixed(2)}</span>
                  )}
                  {e.pnl != null && (
                    <span className={cn("text-sm font-bold font-mono", e.pnl >= 0 ? "text-[#22C55E]" : "text-[#EF4444]")}>
                      {fmt$(e.pnl)}
                    </span>
                  )}
                  {e.mood && (
                    <span className="text-base" title={`Mood: ${e.mood}/5`}>{moodLabel(e.mood)}</span>
                  )}
                </div>

                {e.notes && (
                  <p className="text-[#475569] text-xs mt-1.5 line-clamp-2">{e.notes}</p>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                <button
                  onClick={() => openEdit(e)}
                  className="text-[#475569] hover:text-[#94A3B8] transition-colors"
                >
                  <Edit2 size={13} />
                </button>
                <button
                  onClick={() => deleteMut.mutate(e.id)}
                  className="text-[#475569] hover:text-[#EF4444] transition-colors"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {modalOpen && (
        <EntryModal
          initial={editing}
          onClose={() => { setModalOpen(false); setEditing(null); }}
          onSave={(body) => {
            if (editing) {
              updateMut.mutate({ id: editing.id, body });
            } else {
              createMut.mutate(body);
            }
          }}
        />
      )}
    </div>
  );
}
