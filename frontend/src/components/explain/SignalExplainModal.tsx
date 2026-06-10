import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { BracketFrame } from "@/components/design";
import { explainSignal, type SignalSource } from "@/api/explain";

interface Props {
  signalId: number;
  source: SignalSource;
  onClose: () => void;
}

const SOURCE_LABEL: Record<SignalSource, string> = {
  bot: "BOT SIGNAL",
  scout: "SCOUT SIGNAL",
  forge: "FORGE SIGNAL",
};

export default function SignalExplainModal({ signalId, source, onClose }: Props) {
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    explainSignal(signalId, source)
      .then((r) => {
        if (!cancelled) {
          setText(r.explanation);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e?.response?.data?.detail ?? "Failed to generate explanation.");
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [signalId, source]);

  function handleCopy() {
    if (text) {
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  }

  const modal = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <BracketFrame className="p-5 space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest">
                ⚒ AI ANALYSIS // {SOURCE_LABEL[source]}
              </p>
              <p className="text-sm font-bold text-white mt-0.5">Reading the tape…</p>
            </div>
            <button
              onClick={onClose}
              className="text-zinc-600 hover:text-zinc-300 transition-colors text-lg leading-none"
            >
              ×
            </button>
          </div>

          {/* Body */}
          <div className="min-h-[80px]">
            {loading ? (
              <div className="space-y-2 animate-pulse">
                <div className="h-3 bg-zinc-800 rounded w-full" />
                <div className="h-3 bg-zinc-800 rounded w-5/6" />
                <div className="h-3 bg-zinc-800 rounded w-4/6" />
                <p className="text-[10px] text-zinc-600 mt-3">Haiku is reading the tape…</p>
              </div>
            ) : error ? (
              <p className="text-sm text-red-400">{error}</p>
            ) : (
              <p className="text-sm text-zinc-300 leading-relaxed">{text}</p>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center gap-2 pt-1 border-t border-zinc-800">
            <button
              onClick={handleCopy}
              disabled={!text}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-30"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
            <span className="text-zinc-800 text-xs">·</span>
            <span className="text-[10px] text-zinc-700 flex-1">
              claude-haiku · paper trading only
            </span>
            <button
              onClick={onClose}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Close
            </button>
          </div>
        </BracketFrame>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
