import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import client from "@/api/client";
import type { GeneratedWidget } from "./AIWorkspaceAnimator";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AIWorkspaceBuilderProps {
  labId: string;
  onWorkspaceGenerated: (result: {
    workspaceName: string;
    widgets: GeneratedWidget[];
    reasoning: string;
  }) => void;
  onClose: () => void;
}

interface GenerateResponse {
  workspace_name: string;
  reasoning: string;
  widgets: GeneratedWidget[];
}

// ── Quick prompts by lab ───────────────────────────────────────────────────────

const QUICK_PROMPTS: Record<string, string[]> = {
  strategy: [
    "NVDA earnings tomorrow",
    "Swing trading semis",
    "Momentum scan setup",
    "Full position tracker",
  ],
  options: [
    "Options flow for AAPL",
    "Iron condor setup",
    "Earnings straddle",
    "Greeks dashboard",
  ],
  crypto: [
    "Memecoin sniping",
    "BTC dominance watch",
    "DeFi yield scan",
    "Altseason tracker",
  ],
  "ta-workshop": [
    "Chart pattern scanner",
    "RSI divergence setup",
    "Breakout detector",
    "Full TA suite",
  ],
};

const LAB_LABELS: Record<string, string> = {
  strategy: "Strategy Lab",
  options: "Options Lab",
  crypto: "Crypto Lab",
  "ta-workshop": "TA Workshop",
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function AIWorkspaceBuilder({
  labId,
  onWorkspaceGenerated,
  onClose,
}: AIWorkspaceBuilderProps) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const quickPrompts = QUICK_PROMPTS[labId] ?? QUICK_PROMPTS["strategy"];
  const labLabel = LAB_LABELS[labId] ?? "Lab";

  async function handleBuild() {
    const q = prompt.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await client.post<GenerateResponse>(
        "/api/workspaces/generate",
        { prompt: q, lab_id: labId }
      );
      onWorkspaceGenerated({
        workspaceName: data.workspace_name,
        widgets: data.widgets,
        reasoning: data.reasoning,
      });
    } catch (err) {
      console.error("Workspace generation error:", err);
      setError("Co-Pilot hit a snag.");
    } finally {
      setLoading(false);
    }
  }

  function handleQuickPrompt(p: string) {
    setPrompt(p);
    setError(null);
  }

  return (
    /* Backdrop */
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 190,
        background: "rgba(0,0,0,0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Modal card */}
      <div
        style={{
          width: 420,
          background: "#0f172a",
          border: "1px solid #1e293b",
          borderRadius: 16,
          padding: "20px 20px 16px",
          fontFamily: "monospace",
          boxShadow: "0 25px 60px rgba(0,0,0,0.7)",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 4,
          }}
        >
          <span style={{ fontSize: 14, color: "#f1f5f9", fontWeight: 700 }}>
            🤖 AI Workspace Builder
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "#475569",
              display: "flex",
              alignItems: "center",
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Sub-label */}
        <p style={{ fontSize: 11, color: "#64748b", marginBottom: 16 }}>
          {labLabel} · 4–6 widgets
        </p>

        <div
          style={{
            height: 1,
            background: "#1e293b",
            marginBottom: 16,
          }}
        />

        {/* Prompt input */}
        <p style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>
          What do you need?
        </p>
        <textarea
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value);
            setError(null);
          }}
          placeholder="Build me a workspace for..."
          rows={2}
          style={{
            width: "100%",
            background: "#1e293b",
            border: "1px solid #334155",
            borderRadius: 8,
            padding: "10px 12px",
            fontSize: 13,
            color: "#f1f5f9",
            resize: "none",
            outline: "none",
            fontFamily: "monospace",
            boxSizing: "border-box",
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleBuild();
            }
          }}
        />

        {/* Quick prompts */}
        <p
          style={{
            fontSize: 11,
            color: "#64748b",
            marginTop: 12,
            marginBottom: 6,
          }}
        >
          Quick prompts:
        </p>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            marginBottom: 16,
          }}
        >
          {quickPrompts.map((p) => (
            <button
              key={p}
              onClick={() => handleQuickPrompt(p)}
              style={{
                background: prompt === p ? "#1d4ed8" : "#1e293b",
                border: `1px solid ${prompt === p ? "#3b82f6" : "#334155"}`,
                borderRadius: 20,
                padding: "4px 10px",
                fontSize: 11,
                color: prompt === p ? "#bfdbfe" : "#94a3b8",
                cursor: "pointer",
                transition: "all 150ms",
                fontFamily: "monospace",
              }}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Build button */}
        <button
          onClick={() => void handleBuild()}
          disabled={!prompt.trim() || loading}
          style={{
            width: "100%",
            background:
              !prompt.trim() || loading
                ? "#1e293b"
                : "linear-gradient(135deg, #1d4ed8, #7c3aed)",
            border: "none",
            borderRadius: 10,
            padding: "11px 0",
            fontSize: 13,
            color: !prompt.trim() || loading ? "#475569" : "#fff",
            cursor: !prompt.trim() || loading ? "not-allowed" : "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            fontFamily: "monospace",
            fontWeight: 700,
            transition: "all 200ms",
          }}
        >
          {loading ? (
            <>
              <Loader2
                size={14}
                style={{
                  animation: "spin 1s linear infinite",
                }}
              />
              Building...
            </>
          ) : (
            "✦ Build Workspace"
          )}
        </button>

        {/* Error state */}
        {error && (
          <div
            style={{
              marginTop: 10,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 11, color: "#f87171" }}>{error}</span>
            <button
              onClick={() => void handleBuild()}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: 11,
                color: "#60a5fa",
                textDecoration: "underline",
                fontFamily: "monospace",
              }}
            >
              Try again
            </button>
          </div>
        )}

        <div
          style={{ height: 1, background: "#1e293b", margin: "14px 0 10px" }}
        />

        {/* Footer tagline */}
        <p
          style={{
            fontSize: 11,
            color: "#475569",
            textAlign: "center",
            lineHeight: 1.5,
          }}
        >
          &ldquo;I&apos;ll pick the best widgets for your goal and arrange them
          automatically&rdquo;
        </p>
      </div>

      {/* Inline keyframe for the Loader2 spin (lucide doesn't animate by default) */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
