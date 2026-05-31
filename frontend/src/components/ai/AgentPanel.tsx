import { useState, useRef, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Bot,
  Send,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  PowerOff,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { agentExecute, type AgentExecuteResponse, type AgentPreviewOrder } from "@/api/paper";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AuditEntry {
  id: string;
  timestamp: string;
  instruction: string;
  result: string;
  success: boolean;
}

// ---------------------------------------------------------------------------
// AgentPanel
// ---------------------------------------------------------------------------

const AGENT_ENABLED_KEY = "bmg_agent_enabled";
const AGENT_AUDIT_KEY = "bmg_agent_audit";

function loadAudit(): AuditEntry[] {
  try {
    const raw = localStorage.getItem(AGENT_AUDIT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveAudit(entries: AuditEntry[]) {
  try {
    localStorage.setItem(AGENT_AUDIT_KEY, JSON.stringify(entries.slice(0, 10)));
  } catch {}
}

export default function AgentPanel() {
  const [enabled, setEnabled] = useState<boolean>(
    () => localStorage.getItem(AGENT_ENABLED_KEY) !== "false"
  );
  const [instruction, setInstruction] = useState("");
  const [preview, setPreview] = useState<AgentExecuteResponse | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>(loadAudit);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Sync enabled state to localStorage
  useEffect(() => {
    localStorage.setItem(AGENT_ENABLED_KEY, enabled ? "true" : "false");
  }, [enabled]);

  const previewMut = useMutation({
    mutationFn: () => agentExecute(instruction, false),
    onSuccess: (data) => {
      setPreview(data);
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(err?.response?.data?.detail || "Could not parse instruction");
    },
  });

  const executeMut = useMutation({
    mutationFn: () => agentExecute(instruction, true),
    onSuccess: (data) => {
      const entry: AuditEntry = {
        id: Date.now().toString(),
        timestamp: new Date().toISOString(),
        instruction,
        result: data.message,
        success: true,
      };
      const updated = [entry, ...audit];
      setAudit(updated);
      saveAudit(updated);
      toast.success(data.message, { duration: 5000 });
      setPreview(null);
      setInstruction("");
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const msg = err?.response?.data?.detail || "Execution failed";
      const entry: AuditEntry = {
        id: Date.now().toString(),
        timestamp: new Date().toISOString(),
        instruction,
        result: msg,
        success: false,
      };
      const updated = [entry, ...audit];
      setAudit(updated);
      saveAudit(updated);
      toast.error(msg);
    },
  });

  const previewOrder = preview?.order as AgentPreviewOrder | undefined;

  return (
    <div className="space-y-5">
      {/* Kill switch */}
      <div className={cn(
        "flex items-center justify-between p-4 rounded-xl border",
        enabled
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-red-500/30 bg-red-500/5"
      )}>
        <div className="flex items-center gap-3">
          <div className={cn(
            "w-8 h-8 rounded-lg flex items-center justify-center",
            enabled ? "bg-emerald-500/20" : "bg-red-500/20"
          )}>
            {enabled ? (
              <Zap size={16} className="text-emerald-400" />
            ) : (
              <PowerOff size={16} className="text-red-400" />
            )}
          </div>
          <div>
            <p className={cn("text-sm font-semibold", enabled ? "text-emerald-300" : "text-red-300")}>
              Agent {enabled ? "enabled" : "disabled"}
            </p>
            <p className="text-xs text-[var(--text-tertiary)]">
              {enabled ? "Ready to receive instructions" : "Agent is paused — no trades will execute"}
            </p>
          </div>
        </div>
        <button
          onClick={() => setEnabled((v) => !v)}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors",
            enabled
              ? "border-red-500/40 text-red-400 hover:bg-red-500/10"
              : "border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10"
          )}
        >
          <PowerOff size={12} />
          {enabled ? "Disable Agent" : "Enable Agent"}
        </button>
      </div>

      {/* Safety notice */}
      <div className="flex items-start gap-3 p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl">
        <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
        <p className="text-xs text-amber-300 leading-relaxed">
          <span className="font-semibold">Paper trading only.</span> The agent only executes paper trades.
          Real money execution requires manual confirmation in the broker platform.
          You can disable the agent at any time using the toggle above.
        </p>
      </div>

      {/* Input */}
      <div className={cn("space-y-3", !enabled && "opacity-40 pointer-events-none")}>
        <div>
          <label className="block text-xs font-medium text-[var(--text-tertiary)] mb-2">
            Tell the agent what to do
          </label>
          <textarea
            ref={textareaRef}
            value={instruction}
            onChange={(e) => {
              setInstruction(e.target.value);
              setPreview(null);
            }}
            placeholder="e.g. 'Buy $50 of QQQ' or 'Sell $200 of AAPL' or 'Buy $100 of GLD as a hedge'"
            rows={3}
            className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 text-sm text-[var(--text-primary)] placeholder-zinc-600 outline-none focus:border-blue-500 resize-none transition-colors"
          />
        </div>

        <div className="flex justify-end">
          <button
            onClick={() => previewMut.mutate()}
            disabled={!instruction.trim() || previewMut.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-400 disabled:opacity-40 disabled:pointer-events-none text-white text-sm font-semibold rounded-lg transition-colors"
          >
            <Send size={14} />
            {previewMut.isPending ? "Parsing…" : "Preview"}
          </button>
        </div>

        {/* Preview card */}
        {preview && previewOrder && (
          <div className="border border-[var(--border-emphasis)] rounded-xl overflow-hidden">
            <div className="px-4 py-3 bg-[var(--bg-elevated-2)] border-b border-[var(--border-subtle)]">
              <div className="flex items-center gap-2">
                <Bot size={15} className="text-blue-400" />
                <span className="text-sm font-semibold text-[var(--text-primary)]">Agent Preview</span>
              </div>
            </div>
            <div className="p-4 space-y-3">
              <p className="text-sm text-[var(--text-secondary)]">{preview.message}</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-[var(--bg-elevated)] rounded-lg p-3">
                  <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Symbol</div>
                  <div className="font-mono font-bold text-[var(--text-primary)]">{previewOrder.symbol}</div>
                </div>
                <div className="bg-[var(--bg-elevated)] rounded-lg p-3">
                  <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Action</div>
                  <div className={cn("font-semibold capitalize", previewOrder.action === "buy" ? "text-emerald-400" : "text-red-400")}>
                    {previewOrder.action} ${previewOrder.amount_dollars.toFixed(2)}
                  </div>
                </div>
                {previewOrder.current_price && (
                  <div className="bg-[var(--bg-elevated)] rounded-lg p-3">
                    <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Current Price</div>
                    <div className="font-mono text-[var(--text-primary)]">${previewOrder.current_price.toFixed(2)}</div>
                  </div>
                )}
                {previewOrder.approx_shares && (
                  <div className="bg-[var(--bg-elevated)] rounded-lg p-3">
                    <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Approx Shares</div>
                    <div className="font-mono text-[var(--text-primary)]">{previewOrder.approx_shares}</div>
                  </div>
                )}
              </div>
              {previewOrder.rationale && (
                <p className="text-xs text-[var(--text-tertiary)] bg-[var(--bg-elevated)] rounded-lg px-3 py-2">
                  {previewOrder.rationale}
                </p>
              )}
              <div className="pt-1">
                <p className="text-xs font-semibold text-[var(--text-primary)] mb-2">
                  Execute this paper trade?
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => executeMut.mutate()}
                    disabled={executeMut.isPending}
                    className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-sm font-semibold rounded-lg transition-colors"
                  >
                    <CheckCircle2 size={14} />
                    {executeMut.isPending ? "Executing…" : "Yes, execute"}
                  </button>
                  <button
                    onClick={() => { setPreview(null); setInstruction(""); }}
                    className="flex items-center gap-2 px-4 py-2 border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-sm font-semibold rounded-lg transition-colors"
                  >
                    <XCircle size={14} />
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Audit log */}
      {audit.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Agent Audit Log</h3>
            <button
              onClick={() => { setAudit([]); localStorage.removeItem(AGENT_AUDIT_KEY); }}
              className="text-xs text-[var(--text-tertiary)] hover:text-red-400 transition-colors"
            >
              Clear
            </button>
          </div>
          <div className="space-y-2">
            {audit.map((entry) => (
              <div
                key={entry.id}
                className={cn(
                  "flex items-start gap-3 p-3 rounded-xl border text-xs",
                  entry.success
                    ? "border-emerald-500/20 bg-emerald-500/5"
                    : "border-red-500/20 bg-red-500/5"
                )}
              >
                <div className="shrink-0 mt-0.5">
                  {entry.success
                    ? <CheckCircle2 size={13} className="text-emerald-400" />
                    : <XCircle size={13} className="text-red-400" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[var(--text-tertiary)] mb-0.5 truncate italic">"{entry.instruction}"</div>
                  <div className={entry.success ? "text-emerald-300" : "text-red-300"}>{entry.result}</div>
                </div>
                <div className="flex items-center gap-1 text-[var(--text-tertiary)] shrink-0">
                  <Clock size={10} />
                  <span>{new Date(entry.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
