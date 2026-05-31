import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { Plus, Trash2, Sparkles, ChevronDown, Save, BookOpen, X, Check, Loader2, AlertTriangle, TrendingUp, TrendingDown, Minus as MinusIcon, Upload, Image as ImageIcon } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import CandlestickChart, { type ChartHandle } from "@/components/chart/CandlestickChart";
import RsiChart from "@/components/chart/RsiChart";
import MacdChart from "@/components/chart/MacdChart";
import TvTopBar from "@/components/chart/TvTopBar";
import TvBottomBar, { type Period, PERIOD_CONFIGS } from "@/components/chart/TvBottomBar";
import DrawingToolbar from "@/components/chart/DrawingToolbar";
import IndicatorsModal from "@/components/chart/IndicatorsModal";
import { useBars } from "@/hooks/useBars";
import { useMarketStore } from "@/store";
import { formatVolume, cn } from "@/lib/utils";
import type { ChartType, DrawingTool, HoveredBar, Drawing } from "@/types/chart";
import {
  listAnalyses,
  createAnalysis,
  updateAnalysis,
  deleteAnalysis,
  analyzeAndSave,
  analyzeChart,
  analyzeImage,
  type ChartAnalysis,
  type AIAnalysis,
  type ImageAnalysis,
  type ImageKeyLevel,
} from "@/api/workshop";

// ── Helpers ────────────────────────────────────────────────────────────────────

const OVERLAY_COLORS: Record<string, string> = {
  SMA_20: "#f59e0b", SMA_50: "#3b82f6", SMA_200: "#8b5cf6",
  EMA_20: "#fbbf24", EMA_50: "#60a5fa", EMA_200: "#a78bfa",
  DEMA_20: "#f472b6",
  VWAP: "#06b6d4",
  BB_20_upper: "#64748b", BB_20_middle: "#94a3b8", BB_20_lower: "#64748b",
  ICHI_tenkan: "#26a69a", ICHI_kijun: "#ef5350",
  PSAR: "#9c27b0",
  DONCHIAN_upper: "#607d8b", DONCHIAN_mid: "#90a4ae", DONCHIAN_lower: "#607d8b",
  KELTNER_upper: "#ff9800", KELTNER_mid: "#ffb74d", KELTNER_lower: "#ff9800",
};

function isOverlayKey(key: string): boolean {
  return key.startsWith("SMA_") || key.startsWith("EMA_") || key.startsWith("DEMA_")
    || key === "VWAP" || key === "PSAR"
    || key.startsWith("ICHI_") || key.startsWith("DONCHIAN_") || key.startsWith("KELTNER_")
    || key.endsWith("_upper") || key.endsWith("_middle") || key.endsWith("_lower");
}

function indicatorLabel(key: string): string {
  if (key === "VWAP") return "VWAP";
  return key.replace(/_/g, " ");
}

const toUnix = (t: string) => Math.floor(new Date(t).getTime() / 1000);

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

function getStoredSymbol() {
  try { return localStorage.getItem("bmg_symbol") ?? "AAPL"; } catch { return "AAPL"; }
}

function drawingTypeLabel(type: Drawing["type"]): string {
  const map: Record<string, string> = {
    hline: "H-Line", trendline: "Trend", rect: "Rectangle",
    fib: "Fibonacci", text: "Text", vline: "V-Line",
    channel: "Channel", longpos: "Long", shortpos: "Short", arrow: "Arrow",
  };
  return map[type] ?? type;
}

function DrawingTypeIcon({ type }: { type: Drawing["type"] }) {
  if (type === "longpos") return <TrendingUp size={11} className="text-[#22c55e]" />;
  if (type === "shortpos") return <TrendingDown size={11} className="text-[#ef4444]" />;
  if (type === "hline" || type === "vline") return <MinusIcon size={11} className="text-[#787b86]" />;
  return <div className="w-2.5 h-2.5 rounded-sm border border-current opacity-70" />;
}

const QUALITY_COLORS = {
  strong: "#22c55e",
  moderate: "#f59e0b",
  weak: "#ef4444",
} as const;

// ── Workshop Panel (right sidebar) ─────────────────────────────────────────────

interface WorkshopPanelProps {
  symbol: string;
  timeframe: string;
  currentPrice?: number;
  drawings: Drawing[];
  indicators: string[];
  onDeleteDrawing: (id: string) => void;
  onLoadDrawings: (drawings: Drawing[]) => void;
}

function WorkshopPanel({
  symbol, timeframe, currentPrice, drawings, indicators, onDeleteDrawing, onLoadDrawings,
}: WorkshopPanelProps) {
  const [analyses, setAnalyses] = useState<ChartAnalysis[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [thesis, setThesis] = useState("");
  const [name, setName] = useState("");
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [aiResult, setAiResult] = useState<AIAnalysis | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  // Image upload state
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const [imageAnalyzing, setImageAnalyzing] = useState(false);
  const [imageAnalysis, setImageAnalysis] = useState<ImageAnalysis | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [showImagePanel, setShowImagePanel] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const symbolUpper = symbol.toUpperCase();

  // Load analyses for this symbol
  useEffect(() => {
    listAnalyses(symbolUpper)
      .then((list) => {
        setAnalyses(list);
        if (list.length > 0 && !activeId) {
          const first = list[0];
          setActiveId(first.id);
          setName(first.name);
          setThesis(first.thesis);
          onLoadDrawings(Array.isArray(first.drawings) ? first.drawings : []);
          if (first.ai_analysis && "thesis_summary" in first.ai_analysis) {
            setAiResult(first.ai_analysis as AIAnalysis);
          } else {
            setAiResult(null);
          }
        }
      })
      .catch(console.error);
  }, [symbolUpper]); // eslint-disable-line

  const safeAnalyses = Array.isArray(analyses) ? analyses : [];
  const activeAnalysis = safeAnalyses.find((a) => a.id === activeId);

  function switchTo(analysis: ChartAnalysis) {
    // Auto-save current before switching
    if (activeId && activeId !== analysis.id) {
      updateAnalysis(activeId, { thesis, drawings }).catch(console.error);
    }
    setActiveId(analysis.id);
    setName(analysis.name);
    setThesis(analysis.thesis);
    onLoadDrawings(Array.isArray(analysis.drawings) ? analysis.drawings : []);
    setAiResult(analysis.ai_analysis && "thesis_summary" in analysis.ai_analysis ? analysis.ai_analysis as AIAnalysis : null);
    setAiError(null);
    setShowDropdown(false);
  }

  async function handleSave() {
    if (!activeId) return;
    setSaving(true);
    try {
      await updateAnalysis(activeId, { name, thesis, drawings });
      setAnalyses((prev) => prev.map((a) => a.id === activeId ? { ...a, name, thesis, drawings } : a));
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1500);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateNew() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const result = await createAnalysis({
        symbol: symbolUpper,
        timeframe,
        name: newName.trim(),
        thesis: "",
        drawings: [],
      });
      const newAnalysis: ChartAnalysis = {
        id: result.id,
        symbol: symbolUpper,
        timeframe,
        name: newName.trim(),
        thesis: "",
        drawings: [],
        ai_analysis: {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setAnalyses((prev) => [newAnalysis, ...prev]);
      setActiveId(result.id);
      setName(newName.trim());
      setThesis("");
      onLoadDrawings([]);
      setAiResult(null);
      setNewName("");
      setShowNewForm(false);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this analysis?")) return;
    await deleteAnalysis(id);
    const remaining = analyses.filter((a) => a.id !== id);
    setAnalyses(remaining);
    if (activeId === id) {
      if (remaining.length > 0) {
        switchTo(remaining[0]);
      } else {
        setActiveId(null);
        setName("");
        setThesis("");
        onLoadDrawings([]);
        setAiResult(null);
      }
    }
  }

  async function handleAnalyze() {
    setAnalyzing(true);
    setAiError(null);
    try {
      const result = await (activeId
        ? analyzeAndSave(activeId, { symbol: symbolUpper, timeframe, current_price: currentPrice, drawings, indicators, thesis })
        : analyzeChart({ symbol: symbolUpper, timeframe, current_price: currentPrice, drawings, indicators, thesis }));
      setAiResult(result.analysis);
      if (activeId) {
        setAnalyses((prev) => prev.map((a) =>
          a.id === activeId ? { ...a, ai_analysis: result.analysis } : a
        ));
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "AI analysis failed";
      setAiError(msg);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    // Show preview
    const url = URL.createObjectURL(file);
    setUploadedImage(url);
    setImageAnalysis(null);
    setImageError(null);
    setShowImagePanel(true);
    setImageAnalyzing(true);
    try {
      const result = await analyzeImage(file);
      setImageAnalysis(result.analysis);
    } catch (err: unknown) {
      setImageError(err instanceof Error ? err.message : "Image analysis failed");
    } finally {
      setImageAnalyzing(false);
      // Reset file input so same file can be re-uploaded
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function importKeyLevels(levels: ImageKeyLevel[]) {
    const newDrawings: Drawing[] = levels
      .filter((l) => l.price != null)
      .map((l) => ({
        id: crypto.randomUUID(),
        type: "hline" as const,
        price: l.price,
        color: "#787b86",
        label: l.label,
      }));
    if (newDrawings.length > 0) onLoadDrawings([...drawings, ...newDrawings]);
  }

  return (
    <div className="w-72 shrink-0 flex flex-col border-l border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="hidden"
        onChange={handleImageUpload}
      />

      {/* Header */}
      <div className="px-3 py-2 border-b border-[var(--border-subtle)] flex items-center justify-between shrink-0">
        <span className="text-[11px] font-semibold text-[var(--text-secondary)] tracking-wider uppercase">TA Workshop</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--accent-primary)] transition-colors"
            title="Upload TA screenshot for AI reading"
          >
            <Upload size={11} />
            Import
          </button>
          <button
            onClick={() => setShowNewForm((s) => !s)}
            className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--accent-primary)] transition-colors"
            title="New analysis"
          >
            <Plus size={12} />
            New
          </button>
        </div>
      </div>

      {/* New analysis form */}
      {showNewForm && (
        <div className="px-3 py-2 border-b border-[var(--border-subtle)] bg-[var(--bg-base)] shrink-0">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreateNew();
              if (e.key === "Escape") setShowNewForm(false);
            }}
            placeholder="Analysis name…"
            className="w-full bg-transparent text-[var(--text-secondary)] text-xs outline-none border border-[var(--border-emphasis)] rounded px-2 py-1 placeholder:text-[var(--text-tertiary)]"
          />
          <div className="flex gap-1.5 mt-1.5">
            <button
              onClick={handleCreateNew}
              disabled={!newName.trim() || saving}
              className="flex-1 text-[10px] py-1 rounded bg-[var(--accent-primary)] text-white hover:opacity-90 disabled:opacity-40 transition-opacity"
            >
              Create
            </button>
            <button
              onClick={() => setShowNewForm(false)}
              className="flex-1 text-[10px] py-1 rounded border border-[var(--border-emphasis)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Analysis selector */}
      {safeAnalyses.length > 0 && (
        <div className="px-3 py-2 border-b border-[var(--border-subtle)] shrink-0 relative">
          <button
            onClick={() => setShowDropdown((s) => !s)}
            className="w-full flex items-center justify-between text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group"
          >
            <span className="truncate font-medium">{name || activeAnalysis?.name || "Select analysis"}</span>
            <ChevronDown size={12} className={cn("shrink-0 ml-1 transition-transform", showDropdown && "rotate-180")} />
          </button>
          {showDropdown && (
            <div className="absolute left-0 right-0 top-full z-50 bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-b shadow-xl overflow-hidden">
              {safeAnalyses.map((a) => (
                <div
                  key={a.id}
                  className={cn(
                    "flex items-center justify-between px-3 py-2 text-xs cursor-pointer hover:bg-[var(--bg-elevated)] transition-colors",
                    a.id === activeId && "text-[var(--accent-primary)] bg-[var(--accent-primary)]/5"
                  )}
                >
                  <span className="truncate flex-1" onClick={() => switchTo(a)}>{a.name}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(a.id); }}
                    className="shrink-0 ml-2 text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors"
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {safeAnalyses.length === 0 && !showNewForm && (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-4 text-center">
          <BookOpen size={28} className="text-[var(--text-tertiary)] opacity-40" />
          <p className="text-[11px] text-[var(--text-tertiary)]">
            Save named analyses for {symbol}.<br />Draw on the chart, name your thesis, let AI weigh in.
          </p>
          <button
            onClick={() => setShowNewForm(true)}
            className="text-[11px] px-3 py-1.5 rounded bg-[var(--accent-primary)] text-white hover:opacity-90 transition-opacity flex items-center gap-1"
          >
            <Plus size={12} />
            New Analysis
          </button>
        </div>
      )}

      {/* Analysis content */}
      {activeId && (
        <div className="flex-1 overflow-y-auto flex flex-col gap-0">
          {/* Name edit */}
          <div className="px-3 pt-3 pb-2 shrink-0">
            <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full mt-1 bg-transparent text-[var(--text-secondary)] text-xs outline-none border-b border-[var(--border-emphasis)] pb-0.5 placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent-primary)] transition-colors"
              placeholder="Analysis name…"
            />
          </div>

          {/* Thesis */}
          <div className="px-3 pb-2 shrink-0">
            <label className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Thesis</label>
            <textarea
              value={thesis}
              onChange={(e) => setThesis(e.target.value)}
              rows={3}
              placeholder="Write your thesis here…"
              className="w-full mt-1 bg-[var(--bg-base)] text-[var(--text-secondary)] text-[11px] outline-none border border-[var(--border-subtle)] rounded px-2 py-1.5 placeholder:text-[var(--text-tertiary)] resize-none focus:border-[var(--accent-primary)] transition-colors"
            />
          </div>

          {/* Save button */}
          <div className="px-3 pb-3 shrink-0">
            <button
              onClick={handleSave}
              disabled={saving}
              className={cn(
                "w-full flex items-center justify-center gap-1.5 text-[11px] py-1.5 rounded transition-all",
                savedFlash
                  ? "bg-[var(--accent-positive)]/15 text-[var(--accent-positive)] border border-[var(--accent-positive)]/30"
                  : "bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-secondary)] hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)]"
              )}
            >
              {saving ? <Loader2 size={11} className="animate-spin" /> : savedFlash ? <Check size={11} /> : <Save size={11} />}
              {savedFlash ? "Saved" : saving ? "Saving…" : "Save Analysis"}
            </button>
          </div>

          {/* Drawings list */}
          {drawings.length > 0 && (
            <div className="px-3 pb-3 shrink-0">
              <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1.5">
                Drawings ({drawings.length})
              </div>
              <div className="flex flex-col gap-0.5">
                {drawings.map((d) => (
                  <div
                    key={d.id}
                    className="flex items-center justify-between px-2 py-1 rounded hover:bg-[var(--bg-base)] group transition-colors"
                  >
                    <div className="flex items-center gap-1.5">
                      <DrawingTypeIcon type={d.type} />
                      <span className="text-[11px] text-[var(--text-secondary)]">{drawingTypeLabel(d.type)}</span>
                      {d.price != null && (
                        <span className="text-[10px] text-[var(--text-tertiary)]">${d.price.toFixed(2)}</span>
                      )}
                      {d.p1?.price != null && d.type !== "hline" && (
                        <span className="text-[10px] text-[var(--text-tertiary)]">${d.p1.price.toFixed(2)}</span>
                      )}
                    </div>
                    <button
                      onClick={() => onDeleteDrawing(d.id)}
                      className="opacity-0 group-hover:opacity-100 text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-all"
                    >
                      <X size={11} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI Analyze button */}
          <div className="px-3 pb-3 shrink-0 border-t border-[var(--border-subtle)] pt-3">
            <button
              onClick={handleAnalyze}
              disabled={analyzing}
              className="w-full flex items-center justify-center gap-1.5 text-[11px] py-2 rounded bg-gradient-to-r from-[#6366f1] to-[#8b5cf6] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {analyzing ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              {analyzing ? "Analyzing…" : "Analyze with AI"}
            </button>
            {aiError && (
              <p className="mt-2 text-[10px] text-[var(--accent-negative)] flex items-center gap-1">
                <AlertTriangle size={10} /> {aiError}
              </p>
            )}
          </div>

          {/* AI Result */}
          {aiResult && (
            <div className="px-3 pb-4 flex flex-col gap-3">
              {/* Quality badge */}
              <div className="flex items-center gap-2">
                <span
                  className="text-[10px] font-bold uppercase px-2 py-0.5 rounded"
                  style={{ color: QUALITY_COLORS[aiResult.setup_quality], background: `${QUALITY_COLORS[aiResult.setup_quality]}18` }}
                >
                  {aiResult.setup_quality} setup
                </span>
                <span className="text-[10px] text-[var(--text-tertiary)]">{aiResult.setup_quality_reason}</span>
              </div>

              {/* Thesis summary */}
              <div>
                <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Thesis read</div>
                <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{aiResult.thesis_summary}</p>
              </div>

              {/* Supporting */}
              {(aiResult.supporting ?? []).length > 0 && (
                <div>
                  <div className="text-[10px] text-[#22c55e] uppercase tracking-wider mb-1">Supporting</div>
                  <ul className="space-y-1">
                    {(aiResult.supporting ?? []).map((s, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-secondary)] flex gap-1.5">
                        <span className="text-[#22c55e] shrink-0 mt-0.5">+</span>
                        {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Counterarguments */}
              {(aiResult.counterarguments ?? []).length > 0 && (
                <div>
                  <div className="text-[10px] text-[#f59e0b] uppercase tracking-wider mb-1">Counter</div>
                  <ul className="space-y-1">
                    {(aiResult.counterarguments ?? []).map((c, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-secondary)] flex gap-1.5">
                        <span className="text-[#f59e0b] shrink-0 mt-0.5">−</span>
                        {c}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Invalidation */}
              <div>
                <div className="text-[10px] text-[#ef4444] uppercase tracking-wider mb-1">Invalidation</div>
                <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{aiResult.invalidation}</p>
              </div>

              {/* Suggestions */}
              {(aiResult.suggested_additions ?? []).length > 0 && (
                <div>
                  <div className="text-[10px] text-[#6366f1] uppercase tracking-wider mb-1">Add to chart</div>
                  <ul className="space-y-1">
                    {(aiResult.suggested_additions ?? []).map((s, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-secondary)] flex gap-1.5">
                        <span className="text-[#6366f1] shrink-0 mt-0.5">→</span>
                        {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Image Upload Analysis Panel ──────────────────────────────────────── */}
      {showImagePanel && (
        <div className="border-t border-[var(--border-subtle)] flex flex-col shrink-0">
          {/* Panel header */}
          <div className="px-3 py-2 flex items-center justify-between bg-[var(--bg-base)]">
            <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider flex items-center gap-1.5">
              <ImageIcon size={11} />
              TA Image Read
            </span>
            <button
              onClick={() => { setShowImagePanel(false); setUploadedImage(null); setImageAnalysis(null); }}
              className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
            >
              <X size={12} />
            </button>
          </div>

          {/* Preview thumbnail */}
          {uploadedImage && (
            <div className="px-3 pb-2">
              <img
                src={uploadedImage}
                alt="Uploaded TA"
                className="w-full rounded border border-[var(--border-subtle)] object-cover max-h-32"
              />
            </div>
          )}

          {/* Loading */}
          {imageAnalyzing && (
            <div className="px-3 pb-3 flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
              <Loader2 size={13} className="animate-spin" />
              AI is reading your chart…
            </div>
          )}

          {/* Error */}
          {imageError && (
            <div className="px-3 pb-3 text-[10px] text-[var(--accent-negative)] flex items-center gap-1">
              <AlertTriangle size={10} /> {imageError}
            </div>
          )}

          {/* Results */}
          {imageAnalysis && (
            <div className="px-3 pb-4 flex flex-col gap-3 overflow-y-auto max-h-96">
              {/* Detected asset / timeframe */}
              {(imageAnalysis.asset || imageAnalysis.timeframe) && (
                <div className="flex gap-2">
                  {imageAnalysis.asset && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] font-mono">
                      {imageAnalysis.asset}
                    </span>
                  )}
                  {imageAnalysis.timeframe && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)]">
                      {imageAnalysis.timeframe}
                    </span>
                  )}
                  <span
                    className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ml-auto"
                    style={{
                      color: QUALITY_COLORS[imageAnalysis.setup_quality],
                      background: `${QUALITY_COLORS[imageAnalysis.setup_quality]}18`,
                    }}
                  >
                    {imageAnalysis.setup_quality}
                  </span>
                </div>
              )}

              {/* Thesis */}
              <div>
                <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">AI reads your setup as</div>
                <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{imageAnalysis.thesis_summary}</p>
              </div>

              {/* Detected drawings */}
              {(imageAnalysis.drawings_detected ?? []).length > 0 && (
                <div>
                  <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
                    Drawings detected ({(imageAnalysis.drawings_detected ?? []).length})
                  </div>
                  <ul className="space-y-1">
                    {(imageAnalysis.drawings_detected ?? []).map((d, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-secondary)] flex gap-1.5">
                        <span className="text-[var(--accent-primary)] shrink-0 mt-0.5">·</span>
                        <span>
                          <span className="text-[var(--text-tertiary)] font-mono">{d.type}</span>
                          {" — "}
                          {d.description}
                          {d.price_level != null && (
                            <span className="text-[var(--text-tertiary)]"> @ ${d.price_level.toLocaleString()}</span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Key levels + import button */}
              {(imageAnalysis.key_levels ?? []).length > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Key levels</div>
                    <button
                      onClick={() => importKeyLevels(imageAnalysis.key_levels ?? [])}
                      className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--accent-primary)]/15 text-[var(--accent-primary)] hover:bg-[var(--accent-primary)]/25 transition-colors"
                    >
                      + Add to chart
                    </button>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    {(imageAnalysis.key_levels ?? []).map((l, i) => (
                      <div key={i} className="flex items-center justify-between text-[11px]">
                        <span className="text-[var(--text-tertiary)]">{l.label}</span>
                        <span className="font-mono text-[var(--text-secondary)]">${l.price.toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Supporting */}
              {(imageAnalysis.supporting ?? []).length > 0 && (
                <div>
                  <div className="text-[10px] text-[#22c55e] uppercase tracking-wider mb-1">Strengths</div>
                  <ul className="space-y-1">
                    {(imageAnalysis.supporting ?? []).map((s, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-secondary)] flex gap-1.5">
                        <span className="text-[#22c55e] shrink-0">+</span>{s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Counter */}
              {(imageAnalysis.counterarguments ?? []).length > 0 && (
                <div>
                  <div className="text-[10px] text-[#f59e0b] uppercase tracking-wider mb-1">Risks</div>
                  <ul className="space-y-1">
                    {(imageAnalysis.counterarguments ?? []).map((c, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-secondary)] flex gap-1.5">
                        <span className="text-[#f59e0b] shrink-0">−</span>{c}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Invalidation */}
              <div>
                <div className="text-[10px] text-[#ef4444] uppercase tracking-wider mb-1">Invalidation</div>
                <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{imageAnalysis.invalidation}</p>
              </div>

              {/* Suggested additions */}
              {(imageAnalysis.suggested_additions ?? []).length > 0 && (
                <div>
                  <div className="text-[10px] text-[#6366f1] uppercase tracking-wider mb-1">Suggested additions</div>
                  <ul className="space-y-1">
                    {(imageAnalysis.suggested_additions ?? []).map((s, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-secondary)] flex gap-1.5">
                        <span className="text-[#6366f1] shrink-0">→</span>{s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Upload another */}
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full flex items-center justify-center gap-1.5 text-[10px] py-1.5 rounded border border-dashed border-[var(--border-emphasis)] text-[var(--text-tertiary)] hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)] transition-colors"
              >
                <Upload size={11} />
                Upload another image
              </button>
            </div>
          )}
        </div>
      )}

      {/* Upload drop zone (shown when no image yet and panel is closed) */}
      {!showImagePanel && (
        <div className="px-3 py-3 border-t border-[var(--border-subtle)] shrink-0">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded border border-dashed border-[var(--border-emphasis)] text-[var(--text-tertiary)] hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)] transition-colors text-[11px]"
          >
            <Upload size={13} />
            Upload TA screenshot → AI reads it
          </button>
        </div>
      )}
    </div>
  );
}

// ── Main WorkshopPage ──────────────────────────────────────────────────────────

export default function WorkshopPage() {
  const [symbol, setSymbol] = useState(getStoredSymbol);
  const [period, setPeriod] = useState<Period>("1Y");
  const [chartType, setChartType] = useState<ChartType>("candle");
  const [activeIndicators, setActiveIndicators] = useState<Set<string>>(
    () => new Set(["SMA_20", "SMA_50", "SMA_200"])
  );
  const [activeTool, setActiveTool] = useState<DrawingTool>("cursor");
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [aiOpen, setAiOpen] = useState(false);
  const [pendingTrendStart, setPendingTrendStart] = useState<{ time: number; price: number } | null>(null);
  const [pendingRectStart, setPendingRectStart] = useState<{ time: number; price: number } | null>(null);
  const [pendingFibStart, setPendingFibStart] = useState<{ time: number; price: number } | null>(null);
  const [pendingTextPoint, setPendingTextPoint] = useState<{ time: number; price: number } | null>(null);
  const [textInputValue, setTextInputValue] = useState("");
  const [pendingChannelPoints, setPendingChannelPoints] = useState<{ time: number; price: number }[]>([]);
  const [pendingPosPoints, setPendingPosPoints] = useState<{ time: number; price: number }[]>([]);
  const [pendingArrowPoint, setPendingArrowPoint] = useState<{ time: number; price: number } | null>(null);
  const [arrowInputValue, setArrowInputValue] = useState("");
  const [hoveredBar, setHoveredBar] = useState<HoveredBar | null>(null);
  const [showIndicatorsModal, setShowIndicatorsModal] = useState(false);

  const chartRef = useRef<ChartHandle>(null);
  const liveBar = useMarketStore((s) => s.liveBars[symbol]);

  const { timeframe, start } = useMemo(() => {
    const cfg = PERIOD_CONFIGS[period];
    return { timeframe: cfg.timeframe, start: cfg.getStart() };
  }, [period]);

  const indicatorsParam = Array.from(activeIndicators).join(",");
  const { data, isLoading } = useBars(symbol, timeframe, indicatorsParam || undefined, start);
  const bars = data?.bars ?? [];
  const indicators = data?.indicators ?? {};

  useEffect(() => {
    if (liveBar && chartRef.current) {
      chartRef.current.updateBar({
        t: liveBar.timestamp, o: liveBar.open, h: liveBar.high,
        l: liveBar.low, c: liveBar.close, v: liveBar.volume,
      });
    }
  }, [liveBar]);

  const handleSymbolChange = (s: string) => {
    setSymbol(s);
    try { localStorage.setItem("bmg_symbol", s); } catch { /* ignore */ }
    setDrawings([]);
    setPendingTrendStart(null);
    setPendingChannelPoints([]);
    setPendingPosPoints([]);
    setPendingArrowPoint(null);
  };

  const handleAddDrawing = useCallback((partial: Omit<Drawing, "id">) => {
    if (partial.type === "trendline") {
      if (!pendingTrendStart) {
        setPendingTrendStart(partial.p1!);
      } else {
        setDrawings((prev) => [...prev, { id: crypto.randomUUID(), type: "trendline", p1: pendingTrendStart, p2: partial.p1!, color: "#2196f3" }]);
        setPendingTrendStart(null);
      }
    } else if (partial.type === "rect") {
      if (!pendingRectStart) {
        setPendingRectStart(partial.p1!);
      } else {
        setDrawings((prev) => [...prev, { id: crypto.randomUUID(), type: "rect", p1: pendingRectStart, p2: partial.p1!, color: "#f59e0b" }]);
        setPendingRectStart(null);
      }
    } else if (partial.type === "fib") {
      if (!pendingFibStart) {
        setPendingFibStart(partial.p1!);
      } else {
        setDrawings((prev) => [...prev, { id: crypto.randomUUID(), type: "fib", p1: pendingFibStart, p2: partial.p1!, color: "#9c27b0" }]);
        setPendingFibStart(null);
      }
    } else if (partial.type === "text") {
      setPendingTextPoint(partial.p1!);
      setTextInputValue("");
    } else if (partial.type === "channel") {
      setPendingChannelPoints((prev) => {
        const pts = [...prev, partial.p1!];
        if (pts.length < 3) return pts;
        setDrawings((d) => [...d, { id: crypto.randomUUID(), type: "channel", p1: pts[0], p2: pts[1], p3: pts[2], color: "#2196f3" }]);
        return [];
      });
    } else if (partial.type === "longpos" || partial.type === "shortpos") {
      const posType = partial.type;
      setPendingPosPoints((prev) => {
        const pts = [...prev, partial.p1!];
        if (pts.length < 3) return pts;
        setDrawings((d) => [...d, { id: crypto.randomUUID(), type: posType, p1: pts[0], p2: pts[1], p3: pts[2], color: "#2196f3" }]);
        return [];
      });
    } else if (partial.type === "arrow") {
      setPendingArrowPoint(partial.p1!);
      setArrowInputValue("");
    } else {
      setDrawings((prev) => [...prev, { id: crypto.randomUUID(), ...partial }]);
    }
  }, [pendingTrendStart, pendingRectStart, pendingFibStart]);

  const handleDeleteDrawing = useCallback((id: string) => {
    setDrawings((prev) => prev.filter((d) => d.id !== id));
  }, []);

  const handleClearDrawings = () => {
    setDrawings([]);
    setPendingTrendStart(null);
    setPendingRectStart(null);
    setPendingFibStart(null);
    setPendingTextPoint(null);
    setPendingChannelPoints([]);
    setPendingPosPoints([]);
    setPendingArrowPoint(null);
    setActiveTool("cursor");
  };

  const displayBar = hoveredBar ?? (bars.length > 0 ? {
    time: 0, open: bars.at(-1)!.o, high: bars.at(-1)!.h,
    low: bars.at(-1)!.l, close: bars.at(-1)!.c, volume: bars.at(-1)!.v,
  } : null);

  const isUp = displayBar ? displayBar.close >= displayBar.open : true;
  const priceColor = isUp ? "#26a69a" : "#ef5350";

  const hoveredIdx = useMemo(() => {
    if (!hoveredBar) return bars.length - 1;
    const idx = bars.findIndex((b) => toUnix(b.t) === hoveredBar.time);
    return idx >= 0 ? idx : bars.length - 1;
  }, [hoveredBar, bars]);

  const overlayIndicators = useMemo(() =>
    Object.entries(indicators).filter(([k]) => isOverlayKey(k)),
    [indicators]
  );

  const hasRsi = "RSI_14" in indicators;
  const hasMacd = "MACD_line" in indicators;

  const currentPrice = displayBar?.close;

  return (
    <div className="flex flex-col flex-1 overflow-hidden bg-[var(--bg-base)] text-[var(--text-secondary)]">
      {/* Top bar */}
      <TvTopBar
        symbol={symbol}
        chartType={chartType}
        onSymbolChange={handleSymbolChange}
        onChartTypeChange={setChartType}
        onIndicatorsClick={() => setShowIndicatorsModal(true)}
        onWatchlistToggle={() => {}}
        showWatchlist={false}
        proMode={true}
        onProModeToggle={() => {}}
        onTradeClick={() => {}}
        onAnalyzeClick={() => setAiOpen(true)}
      />

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left drawing toolbar — always visible in Workshop */}
        <DrawingToolbar
          activeTool={activeTool}
          onChange={setActiveTool}
          onClearAll={handleClearDrawings}
        />

        {/* Chart area */}
        <div className="flex-1 flex flex-col overflow-hidden relative">
          {/* OHLCV info overlay */}
          <div className="absolute top-0 left-0 z-10 pointer-events-none flex items-center gap-0 px-2 pt-1.5 flex-wrap">
            <span className="text-[var(--text-secondary)] font-semibold text-xs mr-2">{symbol}</span>
            {displayBar && (
              <>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">O</span>
                <span className="text-[11px] mr-2" style={{ color: priceColor }}>{displayBar.open.toFixed(2)}</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">H</span>
                <span className="text-[11px] mr-2" style={{ color: priceColor }}>{displayBar.high.toFixed(2)}</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">L</span>
                <span className="text-[11px] mr-2" style={{ color: priceColor }}>{displayBar.low.toFixed(2)}</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">C</span>
                <span className="text-[11px] font-semibold mr-2" style={{ color: priceColor }}>{displayBar.close.toFixed(2)}</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">V</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-3">{formatVolume(displayBar.volume)}</span>
              </>
            )}
            {overlayIndicators.map(([key, vals]) => {
              const val = vals[hoveredIdx];
              if (val == null) return null;
              const color = OVERLAY_COLORS[key] ?? "#94a3b8";
              return (
                <span key={key} className="flex items-center gap-0.5 mr-2">
                  <span style={{ color }} className="text-[9px] leading-none">●</span>
                  <span style={{ color }} className="text-[11px]">{indicatorLabel(key)} {val.toFixed(2)}</span>
                </span>
              );
            })}
            {/* Drawing instruction hints */}
            {pendingTrendStart && <span className="ml-3 text-[11px] text-[var(--text-secondary)]">Click second point to complete trend line</span>}
            {pendingRectStart && <span className="ml-3 text-[11px] text-[#F59E0B]">Click opposite corner to complete rectangle</span>}
            {pendingFibStart && <span className="ml-3 text-[11px] text-[#A78BFA]">Click second point to complete Fibonacci</span>}
            {pendingTextPoint && <span className="ml-3 text-[11px] text-[var(--text-secondary)]">Type label and press Enter</span>}
            {pendingChannelPoints.length === 1 && <span className="ml-3 text-[11px] text-[#2196f3]">Click second point for channel direction</span>}
            {pendingChannelPoints.length === 2 && <span className="ml-3 text-[11px] text-[#2196f3]">Click to offset second channel line</span>}
            {pendingPosPoints.length === 1 && <span className="ml-3 text-[11px] text-[#ef4444]">Click stop loss level</span>}
            {pendingPosPoints.length === 2 && <span className="ml-3 text-[11px] text-[#22c55e]">Click target level</span>}
            {pendingArrowPoint && <span className="ml-3 text-[11px] text-[var(--text-secondary)]">Type arrow label and press Enter</span>}
          </div>

          {/* Text input overlay */}
          {pendingTextPoint && (
            <div className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none">
              <div className="pointer-events-auto bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 flex items-center gap-2 shadow-xl">
                <input
                  autoFocus type="text" value={textInputValue}
                  onChange={(e) => setTextInputValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && textInputValue.trim()) {
                      setDrawings((prev) => [...prev, { id: crypto.randomUUID(), type: "text", p1: pendingTextPoint, color: "#d1d4dc", label: textInputValue.trim() }]);
                      setPendingTextPoint(null); setTextInputValue("");
                    } else if (e.key === "Escape") { setPendingTextPoint(null); setTextInputValue(""); }
                  }}
                  placeholder="Label text…"
                  className="bg-transparent text-[var(--text-secondary)] text-sm outline-none w-40 placeholder:text-[var(--text-tertiary)]"
                />
                <span className="text-[var(--text-tertiary)] text-[10px]">Enter ↵</span>
              </div>
            </div>
          )}

          {/* Arrow input overlay */}
          {pendingArrowPoint && (
            <div className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none">
              <div className="pointer-events-auto bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 flex items-center gap-2 shadow-xl">
                <input
                  autoFocus type="text" value={arrowInputValue}
                  onChange={(e) => setArrowInputValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && arrowInputValue.trim()) {
                      setDrawings((prev) => [...prev, { id: crypto.randomUUID(), type: "arrow", p1: pendingArrowPoint, color: "#d1d4dc", metadata: { label: arrowInputValue.trim() } }]);
                      setPendingArrowPoint(null); setArrowInputValue("");
                    } else if (e.key === "Escape") { setPendingArrowPoint(null); setArrowInputValue(""); }
                  }}
                  placeholder="Arrow label…"
                  className="bg-transparent text-[var(--text-secondary)] text-sm outline-none w-40 placeholder:text-[var(--text-tertiary)]"
                />
                <span className="text-[var(--text-tertiary)] text-[10px]">Enter ↵</span>
              </div>
            </div>
          )}

          {/* Chart */}
          <div className="flex-1 overflow-hidden relative">
            {isLoading ? (
              <div className="w-full h-full flex items-center justify-center text-[var(--text-tertiary)] text-sm">
                Loading {symbol}…
              </div>
            ) : (
              <CandlestickChart
                ref={chartRef}
                bars={bars}
                indicators={indicators}
                chartType={chartType}
                activeTool={activeTool}
                drawings={drawings}
                onCrosshairMove={setHoveredBar}
                onAddDrawing={handleAddDrawing}
              />
            )}
          </div>

          {/* Sub-panes */}
          {hasRsi && !isLoading && <RsiChart bars={bars} values={indicators.RSI_14} height={100} />}
          {hasMacd && !isLoading && (
            <MacdChart
              bars={bars}
              macdLine={indicators.MACD_line}
              macdSignal={indicators.MACD_signal ?? []}
              macdHist={indicators.MACD_hist ?? []}
              height={100}
            />
          )}
        </div>

        {/* Right panel: Workshop analyses + AI */}
        <WorkshopPanel
          symbol={symbol}
          timeframe={timeframe}
          currentPrice={currentPrice}
          drawings={drawings}
          indicators={Array.from(activeIndicators)}
          onDeleteDrawing={handleDeleteDrawing}
          onLoadDrawings={setDrawings}
        />
      </div>

      {/* Bottom bar */}
      <TvBottomBar
        period={period}
        onPeriodChange={setPeriod}
        symbol={symbol}
        displayPrice={displayBar?.close}
        displayVolume={displayBar?.volume}
        drawingCount={drawings.length}
      />

      {showIndicatorsModal && (
        <IndicatorsModal
          active={activeIndicators}
          onChange={setActiveIndicators}
          onClose={() => setShowIndicatorsModal(false)}
        />
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title={`BMG Analysis — ${symbol}`}
        context={`TA Workshop — technical analysis for ${symbol}`}
        suggestedQuestions={[
          `What's the current trend for ${symbol}?`,
          "What are the key support and resistance levels here?",
          "How do I read a descending triangle pattern?",
          "When is RSI divergence a reliable signal?",
          "Explain the significance of the 200-day moving average",
        ]}
      />
    </div>
  );
}
