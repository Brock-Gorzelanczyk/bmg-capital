import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Edit2, TrendingUp, TrendingDown, BookOpen, BarChart2, Star, Lock, Download, Bot } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { useIsViewer } from "@/store/authStore";
import { toast } from "sonner";
import { cn, timeAgo } from "@/lib/utils";
import { getEntries, getStats, createEntry, updateEntry, deleteEntry } from "@/api/journal";
import { getOrders, getTransactions } from "@/api/paper";
import type { JournalEntry, CreateEntryBody } from "@/api/journal";

// ── helpers ─────────────────────────────────────────────────────────────────

function fmt$(n: number) {
  return (n >= 0 ? "+" : "") + "$" + Math.abs(n).toFixed(2);
}

function moodLabel(v: number) {
  return ["", "😞", "😕", "😐", "😊", "😄"][v] ?? "—";
}


// ── Template system ──────────────────────────────────────────────────────────

const JOURNAL_TEMPLATES = [
  {
    id: "pre-trade",
    name: "Pre-Trade Plan",
    icon: "🎯",
    desc: "Plan before you enter",
    notes: `## Pre-Trade Plan\n\n**Ticker:** \n**Side:** Buy / Sell\n**Entry:** \n**Stop:** \n**Target:** \n**Size:** \n\n### Thesis\n\n\n### What invalidates it\n\n\n### R:R = \n**Confidence:** /10`,
  },
  {
    id: "post-trade",
    name: "Post-Trade Reflection",
    icon: "🔍",
    desc: "Review what happened",
    notes: `## Post-Trade Reflection\n\n**Outcome:** Win / Loss / Breakeven\n\n### What worked\n\n\n### What didn't work\n\n\n### Did I follow my plan? Yes / No\nIf no, why?\n\n\n### Mistake tags\nSized too big | Cut winner early | Held loser too long | Ignored stop | Chased entry | None\n\n### Lesson learned\n`,
  },
  {
    id: "weekly",
    name: "Weekly Review",
    icon: "📅",
    desc: "End-of-week summary",
    notes: `## Weekly Review — Week of \n\n**Trades:** \n**Net P&L:** \n**Win rate:** \n\n### Best decision\n\n\n### Worst decision\n\n\n### Patterns I noticed\n\n\n### Focus for next week\n`,
  },
  {
    id: "lesson",
    name: "Lesson Learned",
    icon: "💡",
    desc: "Capture a rule",
    notes: `## Lesson Learned\n\n### The lesson (one sentence rule)\n\n\n### The trade that taught it\n\n\n### The rule I'll follow\n`,
  },
  {
    id: "macro",
    name: "Macro View",
    icon: "🌍",
    desc: "Market regime notes",
    notes: `## Macro View\n\n**Regime:** Bull / Bear / Sideways / Volatile\n\n### Sectors I'm watching\n\n\n### Setups I'm tracking\n\n\n### How my positioning reflects this\n`,
  },
  {
    id: "mindset",
    name: "Mindset Check",
    icon: "🧠",
    desc: "Emotional state check",
    notes: `## Mindset Check\n\n### How am I feeling about the market?\n\n\n### Am I tilted, FOMO-ing, or fearful?\n\n\n### One thing I'll do to stay disciplined today\n`,
  },
] as const;

// ── Empty-state quick-start cards ────────────────────────────────────────────

const QUICK_START = [
  JOURNAL_TEMPLATES[0], // Pre-Trade Plan
  JOURNAL_TEMPLATES[1], // Post-Trade Reflection
  JOURNAL_TEMPLATES[2], // Weekly Review
];

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
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)]">
          <span className="text-[var(--text-primary)] font-semibold">{initial ? "Edit Entry" : "New Journal Entry"}</span>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)]">✕</button>
        </div>

        <div className="p-5 space-y-4">
          {/* Template selector (new entries only) */}
          {!initial && (
            <div>
              <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-2">Template</label>
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => set("notes", null)}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-full transition-colors",
                    !form.notes
                      ? "bg-[var(--accent-positive)] text-[var(--text-primary)]"
                      : "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:bg-[#334155]"
                  )}
                >
                  Blank
                </button>
                {JOURNAL_TEMPLATES.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => set("notes", t.notes)}
                    className={cn(
                      "text-xs px-2.5 py-1 rounded-full transition-colors",
                      form.notes === t.notes
                        ? "bg-[var(--accent-positive)] text-[var(--text-primary)]"
                        : "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:bg-[#334155]"
                    )}
                    title={t.desc}
                  >
                    {t.icon} {t.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Symbol + Date + Side row */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-1">Symbol</label>
              <input
                value={form.symbol}
                onChange={(e) => set("symbol", e.target.value.toUpperCase())}
                placeholder="AAPL"
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg font-mono focus:outline-none focus:border-[#3B82F6]"
              />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-1">Date</label>
              <input
                type="date"
                value={form.trade_date}
                onChange={(e) => set("trade_date", e.target.value)}
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg focus:outline-none focus:border-[#3B82F6]"
              />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-1">Side</label>
              <div className="flex gap-1.5 mt-1">
                {(["buy", "sell"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => set("side", s)}
                    className={cn(
                      "flex-1 py-1.5 text-xs font-bold rounded-lg transition-colors",
                      form.side === s
                        ? s === "buy" ? "bg-emerald-900 text-[var(--accent-positive)]" : "bg-rose-900 text-[var(--accent-negative)]"
                        : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)]"
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
                <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-1">
                  {k === "qty" ? "Qty / Shares" : k === "entry_price" ? "Entry $" : "Exit $"}
                </label>
                <input
                  type="number"
                  value={form[k] ?? ""}
                  onChange={(e) => set(k, e.target.value ? parseFloat(e.target.value) : null as never)}
                  onBlur={autoCalcPnl}
                  placeholder="0"
                  className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg font-mono focus:outline-none focus:border-[#3B82F6]"
                />
              </div>
            ))}
          </div>

          {/* P&L */}
          <div>
            <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-1">P&amp;L ($)</label>
            <input
              type="number"
              value={form.pnl ?? ""}
              onChange={(e) => set("pnl", e.target.value ? parseFloat(e.target.value) : null)}
              placeholder="Auto-calculated or override"
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg font-mono focus:outline-none focus:border-[#3B82F6]"
            />
          </div>

          {/* Setup */}
          <div>
            <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-2">Setup</label>
            <div className="flex flex-wrap gap-1.5">
              {SETUPS.map((s) => (
                <button
                  key={s}
                  onClick={() => set("setup", form.setup === s ? null : s)}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-full transition-colors",
                    form.setup === s
                      ? "bg-[var(--accent-positive)] text-[var(--text-primary)]"
                      : "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:bg-[#334155]"
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
                <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-2">{label}</label>
                <div className="flex gap-1">
                  {emojis.map((e, i) => (
                    <button
                      key={i}
                      onClick={() => set(key, (i + 1) as 1 | 2 | 3 | 4 | 5)}
                      className={cn(
                        "flex-1 h-8 text-sm rounded-lg transition-colors",
                        form[key] === i + 1
                          ? "bg-[var(--accent-positive)] text-[var(--text-primary)]"
                          : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] hover:bg-[#334155]"
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
            <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-1">Trade Notes</label>
            <textarea
              value={form.notes ?? ""}
              onChange={(e) => set("notes", e.target.value || null)}
              rows={6}
              placeholder="What happened? Why did you enter/exit?"
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg focus:outline-none focus:border-[#3B82F6] resize-none font-mono"
            />
          </div>

          {/* Lessons */}
          <div>
            <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-1">Lessons Learned</label>
            <textarea
              value={form.lessons ?? ""}
              onChange={(e) => set("lessons", e.target.value || null)}
              rows={2}
              placeholder="What would you do differently?"
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg focus:outline-none focus:border-[#3B82F6] resize-none"
            />
          </div>

          {/* Rating */}
          <div>
            <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider block mb-2">Trade Rating</label>
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map((r) => (
                <button
                  key={r}
                  onClick={() => set("rating", form.rating === r ? null : r)}
                  className={cn("text-lg transition-colors", form.rating != null && form.rating >= r ? "text-[#F59E0B]" : "text-[var(--border-emphasis)]")}
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
            className="flex-1 py-2.5 rounded-xl bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] text-sm font-medium hover:bg-[#334155] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => { if (form.symbol) onSave(form); }}
            className="flex-1 py-2.5 rounded-xl bg-[var(--accent-positive)] text-[var(--text-primary)] text-sm font-semibold hover:brightness-110 transition-colors"
          >
            {initial ? "Save Changes" : "Add Entry"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── AI Quarterly Review card ─────────────────────────────────────────────────

const UNLOCK_THRESHOLD = 20;

function AIReviewCard({ entryCount }: { entryCount: number }) {
  const locked = entryCount < UNLOCK_THRESHOLD;
  const progress = Math.min(entryCount / UNLOCK_THRESHOLD, 1);

  const now = new Date();
  const quarter = Math.ceil((now.getMonth() + 1) / 3);
  const year = now.getFullYear();

  return (
    <div className="bg-[var(--bg-elevated)] border-l-4 border-[var(--accent-positive)] border-t border-r border-b border-[var(--border-subtle)] rounded-xl px-5 py-4 mb-2">
      <div className="flex items-center justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[var(--accent-positive)] text-xs font-bold uppercase tracking-wider">AI Quarterly Review</span>
            {locked && (
              <Lock size={12} className="text-[var(--text-tertiary)]" />
            )}
          </div>

          {locked ? (
            <>
              <p className="text-[var(--text-secondary)] text-sm">
                Unlocks at {UNLOCK_THRESHOLD} entries — you have {entryCount}/{UNLOCK_THRESHOLD}
              </p>
              <div className="mt-2 h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden w-48">
                <div
                  className="h-full bg-[var(--accent-positive)] rounded-full transition-all"
                  style={{ width: `${progress * 100}%` }}
                />
              </div>
            </>
          ) : (
            <p className="text-[var(--text-secondary)] text-sm">
              Q{quarter} {year} Review is ready — get AI insights on your trading patterns.
            </p>
          )}
        </div>

        {!locked && (
          <button
            onClick={() => toast.info("AI Quarterly Review coming soon")}
            className="shrink-0 text-xs font-semibold px-3 py-1.5 rounded-lg bg-[var(--accent-positive)] text-[var(--text-primary)] hover:brightness-110 transition-colors"
          >
            Generate Review
          </button>
        )}
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onOpenWithTemplate }: { onOpenWithTemplate: (notes: string) => void }) {
  return (
    <div className="space-y-5">
      {/* Collapsed KPI banner */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-5 py-4">
        <p className="text-[var(--text-secondary)] text-sm text-center">
          Your edge starts here. Log your first trade to begin tracking your win rate, P&L, mood patterns, and what's actually working.
        </p>
      </div>

      {/* Quick start template cards */}
      <div>
        <p className="text-[var(--text-tertiary)] text-xs uppercase tracking-wider mb-3">Quick start with a template</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {QUICK_START.map((t) => (
            <button
              key={t.id}
              onClick={() => onOpenWithTemplate(t.notes)}
              className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] rounded-xl p-4 text-left transition-colors group"
            >
              <div className="text-2xl mb-2">{t.icon}</div>
              <div className="text-[var(--text-primary)] font-semibold text-sm mb-1 group-hover:text-[var(--accent-positive)] transition-colors">
                {t.name}
              </div>
              <p className="text-[var(--text-tertiary)] text-xs">{t.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Faded AI Quarterly Review preview */}
      <div className="relative rounded-xl border border-[var(--border-subtle)] overflow-hidden mt-4">
        <div className="absolute inset-0 bg-[var(--bg-base)]/60 z-10 flex items-center justify-center backdrop-blur-[2px]">
          <div className="text-center px-4">
            <p className="text-[var(--text-secondary)] text-xs font-medium">AI Quarterly Review</p>
            <p className="text-[var(--text-tertiary)] text-[11px] mt-1">Unlocks at 20 entries</p>
          </div>
        </div>
        <div className="px-5 py-4 select-none">
          <div className="text-[var(--text-primary)] font-semibold text-sm mb-1">Q2 2025 Trading Review</div>
          <p className="text-[var(--text-tertiary)] text-xs leading-relaxed">This quarter you placed 47 trades, journaled 38 times. Your biggest pattern: winning trades were held an average of 3.2 days; losing trades were held 8.7 days. Your best setup: breakout plays on high-volume days win at 71%...</p>
        </div>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function JournalPage() {
  const qc = useQueryClient();
  const isViewer = useIsViewer();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<JournalEntry | null>(null);
  const [filterSymbol, setFilterSymbol] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [prefillNotes, setPrefillNotes] = useState<string | null>(null);
  const [importingPaper, setImportingPaper] = useState(false);

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
    onSuccess: () => {
      toast.success("Entry added");
      setModalOpen(false);
      setPrefillNotes(null);
      invalidate();
    },
    onError: () => toast.error("Failed to save entry"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: CreateEntryBody }) => updateEntry(id, body),
    onSuccess: () => { toast.success("Entry updated"); setEditing(null); setModalOpen(false); invalidate(); },
    onError: () => toast.error("Failed to update entry"),
  });

  const deleteMut = useMutation({
    mutationFn: deleteEntry,
    onSuccess: () => { toast.success("Entry deleted"); invalidate(); },
  });

  const openNew = (notes?: string | null) => {
    setEditing(null);
    setPrefillNotes(notes ?? null);
    setModalOpen(true);
  };
  const openEdit = (e: JournalEntry) => { setEditing(e); setPrefillNotes(null); setModalOpen(true); };

  // Auto-import last paper trade
  const handleAutoImport = async () => {
    setImportingPaper(true);
    try {
      const [orders, transactions] = await Promise.all([
        getOrders("filled"),
        getTransactions(),
      ]);

      if (!orders.length) {
        toast.error("No filled paper trades found");
        return;
      }

      // Most recent filled order (API returns newest first or we sort)
      const order = orders.sort((a, b) =>
        new Date(b.filled_at ?? b.created_at).getTime() - new Date(a.filled_at ?? a.created_at).getTime()
      )[0];

      // Find matching transaction for realized PnL
      const tx = transactions.find(
        (t) => t.symbol === order.symbol && t.side === order.side
      );

      const prefill: CreateEntryBody = {
        ...BLANK,
        symbol: order.symbol,
        side: order.side,
        qty: order.fill_qty ?? order.qty,
        entry_price: order.fill_price ?? 0,
        trade_date: (order.filled_at ?? order.created_at).slice(0, 10),
        pnl: tx?.realized_pnl ?? null,
      };

      setEditing(null);
      // We open with the prefill directly via a synthetic JournalEntry-shaped object
      // by setting prefillNotes to signal that we have a full prefill
      setPrefillNotes(prefill.notes ?? null);
      // Override BLANK using state trick: store everything via editing flow by setting editing to a cast
      // Instead, we use a dedicated prefill state
      setModalOpen(true);
      // Store full prefill in a separate piece of state
      setPaperPrefill(prefill);
      toast.success(`Pre-filled from paper trade: ${order.symbol}`);
    } catch {
      toast.error("Failed to import paper trade");
    } finally {
      setImportingPaper(false);
    }
  };

  // Dedicated state for full paper prefill
  const [paperPrefill, setPaperPrefill] = useState<CreateEntryBody | null>(null);

  const handleModalClose = () => {
    setModalOpen(false);
    setEditing(null);
    setPrefillNotes(null);
    setPaperPrefill(null);
  };

  // Determine which initial value to pass to modal
  const getModalInitial = (): JournalEntry | null => {
    if (editing) return editing;
    if (paperPrefill) return paperPrefill as unknown as JournalEntry;
    if (prefillNotes != null) return { ...BLANK, notes: prefillNotes } as unknown as JournalEntry;
    return null;
  };

  const isEmpty = !isLoading && entries.length === 0;

  return (
    <div className="space-y-4 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Trade Journal</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Document and reflect on every trade</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-2 rounded-xl transition-colors"
          >
            <Bot size={13} /> Ask AI
          </button>
          {!isViewer && (
            <>
              <button
                onClick={handleAutoImport}
                disabled={importingPaper}
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-emphasis)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-50"
              >
                <Download size={13} />
                {importingPaper ? "Importing…" : "Import last paper trade"}
              </button>
              <button
                onClick={() => openNew()}
                className="flex items-center gap-2 bg-[var(--accent-positive)] hover:brightness-110 text-[var(--text-primary)] text-sm font-semibold px-4 py-2 rounded-xl transition-colors"
              >
                <Plus size={15} />
                New Entry
              </button>
            </>
          )}
        </div>
      </div>

      {/* Stats row — shown when entries exist */}
      {stats && entries.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[
            { label: "Total Entries", value: stats.total_entries, icon: BookOpen, color: "text-[var(--text-secondary)]" },
            { label: "Win Rate", value: `${stats.win_rate}%`, icon: BarChart2, color: "text-[var(--accent-positive)]" },
            { label: "Total P&L", value: fmt$(stats.total_pnl), icon: stats.total_pnl >= 0 ? TrendingUp : TrendingDown, color: stats.total_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]" },
            { label: "Avg Mood", value: moodLabel(Math.round(stats.avg_mood)), icon: Star, color: "text-[#F59E0B]" },
            { label: "With Notes", value: stats.entries_with_notes, icon: BookOpen, color: "text-[#8B5CF6]" },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <Icon size={13} className={color} />
                <span className="text-[var(--text-tertiary)] text-[10px] uppercase tracking-wider">{label}</span>
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
          className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg w-40 placeholder-[#475569] focus:outline-none focus:border-[var(--border-emphasis)] font-mono"
        />
        {filterSymbol && (
          <button onClick={() => setFilterSymbol("")} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs">
            Clear
          </button>
        )}
        <span className="text-[var(--text-tertiary)] text-xs ml-auto">{entries.length} entries</span>
      </div>

      {/* AI Quarterly Review card — always at top of journal content area */}
      {!isLoading && <AIReviewCard entryCount={entries.length} />}

      {/* Entries list */}
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl animate-pulse" />
          ))}
        </div>
      ) : isEmpty ? (
        <EmptyState onOpenWithTemplate={(notes) => openNew(notes)} />
      ) : (
        <div className="space-y-2">

          {entries.map((e) => (
            <div key={e.id} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex items-start gap-4 hover:border-[var(--border-emphasis)] transition-colors group">
              {/* Side badge */}
              <div className={cn(
                "text-[11px] font-bold px-2 py-1 rounded-lg shrink-0 mt-0.5",
                e.side === "buy" ? "bg-emerald-900/60 text-[var(--accent-positive)]" : "bg-rose-900/60 text-[var(--accent-negative)]"
              )}>
                {e.side.toUpperCase()}
              </div>

              {/* Main content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[var(--text-primary)] font-bold font-mono">{e.symbol}</span>
                  {e.setup && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-elevated-2)] text-[var(--text-secondary)]">{e.setup}</span>
                  )}
                  {e.rating && (
                    <span className="text-[#F59E0B] text-xs">{"★".repeat(e.rating)}</span>
                  )}
                  <span className="text-[var(--text-tertiary)] text-xs ml-auto">{timeAgo(e.created_at)} · {e.trade_date}</span>
                </div>

                <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                  {e.qty > 0 && (
                    <span className="text-[var(--text-tertiary)] text-xs font-mono">{e.qty} shares</span>
                  )}
                  {e.entry_price > 0 && (
                    <span className="text-[var(--text-secondary)] text-xs font-mono">@ ${e.entry_price.toFixed(2)}</span>
                  )}
                  {e.exit_price != null && (
                    <span className="text-[var(--text-secondary)] text-xs font-mono">→ ${e.exit_price.toFixed(2)}</span>
                  )}
                  {e.pnl != null && (
                    <span className={cn("text-sm font-bold font-mono", e.pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                      {fmt$(e.pnl)}
                    </span>
                  )}
                  {e.mood && (
                    <span className="text-base" title={`Mood: ${e.mood}/5`}>{moodLabel(e.mood)}</span>
                  )}
                </div>

                {e.notes && (
                  <p className="text-[var(--text-tertiary)] text-xs mt-1.5 line-clamp-2">{e.notes}</p>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                <button
                  onClick={() => openEdit(e)}
                  className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
                >
                  <Edit2 size={13} />
                </button>
                <button
                  onClick={() => deleteMut.mutate(e.id)}
                  className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors"
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
          initial={getModalInitial()}
          onClose={handleModalClose}
          onSave={(body) => {
            if (editing) {
              updateMut.mutate({ id: editing.id, body });
            } else {
              createMut.mutate(body);
            }
          }}
        />
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Trading"
        context="Trade Journal — reviewing trades, psychology, and patterns"
        suggestedQuestions={[
          "What patterns should I look for in my trade history?",
          "How can I improve my risk management?",
          "What does a healthy win rate look like for swing trading?",
          "How do I identify if I'm overtrading?",
          "What journal metrics matter most for improving as a trader?",
        ]}
      />
    </div>
  );
}
