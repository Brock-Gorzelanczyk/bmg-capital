import { useEffect, useRef, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface GeneratedWidget {
  type: string;
  title: string;
  grid_x: number;
  grid_y: number;
  w: number;
  h: number;
  config: Record<string, unknown>;
}

interface AIWorkspaceAnimatorProps {
  isActive: boolean;
  prompt: string;
  workspaceName: string;
  widgets: GeneratedWidget[];
  onComplete: () => void;
  onSave: () => void;
  onRefine: () => void;
  soundEnabled?: boolean;
}

// ── Widget priority for reveal storytelling ────────────────────────────────────

const WIDGET_PRIORITY: Record<string, number> = {
  "equity-curve": 0,
  "watchlist": 1,
  "position-blotter": 2,
  "pnl-calendar": 3,
  "daily-recap": 4,
};

const WIDGET_ICONS: Record<string, string> = {
  "equity-curve": "📈",
  "position-blotter": "📋",
  "watchlist": "👁",
  "pnl-calendar": "📅",
  "daily-recap": "☀️",
};

// ── CSS keyframes injected once ───────────────────────────────────────────────

const STYLES = `
@keyframes bmg-scan-line {
  0%   { transform: translateX(-100vw); }
  100% { transform: translateX(100vw); }
}
@keyframes bmg-logo-pulse {
  0%, 100% { transform: scale(0.8); opacity: 0.8; }
  50%       { transform: scale(0.88); opacity: 1; }
}
@keyframes bmg-widget-mount {
  0%   { opacity: 0; transform: scale(0.92) translateY(4px); filter: blur(8px); }
  85%  { opacity: 1; transform: scale(1.005) translateY(1px); filter: blur(0px); }
  100% { opacity: 1; transform: scale(1) translateY(0px); filter: blur(0px); }
}
@keyframes bmg-border-flash {
  0%   { box-shadow: 0 0 0 1px #84cc16; }
  60%  { box-shadow: 0 0 0 1px #84cc1680; }
  100% { box-shadow: 0 0 0 0px transparent; }
}
@keyframes bmg-toast-up {
  0%   { transform: translateX(-50%) translateY(100%); opacity: 0; }
  100% { transform: translateX(-50%) translateY(0); opacity: 1; }
}
@keyframes bmg-fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
`;

let stylesInjected = false;
function injectStyles() {
  if (stylesInjected) return;
  stylesInjected = true;
  const el = document.createElement("style");
  el.textContent = STYLES;
  document.head.appendChild(el);
}

// ── Sound helpers (lazy AudioContext — created only after user gesture) ────────

function playTick(audioCtx: AudioContext) {
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.connect(gain);
  gain.connect(audioCtx.destination);
  osc.frequency.value = 800;
  gain.gain.setValueAtTime(0.02, audioCtx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.08);
  osc.start();
  osc.stop(audioCtx.currentTime + 0.08);
}

function playChord(audioCtx: AudioContext, frequencies: number[], duration: number) {
  frequencies.forEach((f) => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.frequency.value = f;
    gain.gain.setValueAtTime(0.025, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
    osc.start();
    osc.stop(audioCtx.currentTime + duration);
  });
}

// ── Parsing step labels ───────────────────────────────────────────────────────

const PARSING_STEPS = [
  "→ Identifying assets",
  "→ Matching widgets",
  "→ Composing layout",
];

// ── Main component ────────────────────────────────────────────────────────────

export default function AIWorkspaceAnimator({
  isActive,
  prompt,
  workspaceName,
  widgets,
  onComplete,
  onSave,
  onRefine,
  soundEnabled = false,
}: AIWorkspaceAnimatorProps) {
  const [phase, setPhase] = useState<0 | 1 | 2 | 3 | 4 | 5>(0);
  const [parsingStep, setParsingStep] = useState(0);
  const [mountedWidgets, setMountedWidgets] = useState<number[]>([]);
  const [toastVisible, setToastVisible] = useState(false);
  const [overlayHidden, setOverlayHidden] = useState(false);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    injectStyles();
  }, []);

  // Clear all pending timers on unmount
  useEffect(() => {
    return () => {
      timersRef.current.forEach(clearTimeout);
    };
  }, []);

  function t(fn: () => void, ms: number) {
    const id = setTimeout(fn, ms);
    timersRef.current.push(id);
    return id;
  }

  function getAudioCtx(): AudioContext | null {
    if (!soundEnabled) return null;
    if (!audioCtxRef.current) {
      try {
        audioCtxRef.current = new AudioContext();
      } catch {
        return null;
      }
    }
    return audioCtxRef.current;
  }

  // Sort widgets by priority for reveal storytelling
  const sortedWidgets = [...widgets].sort(
    (a, b) => (WIDGET_PRIORITY[a.type] ?? 9) - (WIDGET_PRIORITY[b.type] ?? 9)
  );

  useEffect(() => {
    if (!isActive) {
      setPhase(0);
      setMountedWidgets([]);
      setToastVisible(false);
      setOverlayHidden(false);
      setParsingStep(0);
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      return;
    }

    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReducedMotion) {
      setPhase(4);
      t(() => {
        setMountedWidgets(sortedWidgets.map((_, i) => i));
        setPhase(5);
        setToastVisible(true);
        t(() => {
          setOverlayHidden(true);
          onComplete();
        }, 2000);
        t(() => setToastVisible(false), 8000);
      }, 400);
      return;
    }

    // Full cinematic sequence
    setPhase(1);

    // Phase 1 intro chord (created after user gesture — isActive flip is user-driven)
    const ctx = getAudioCtx();
    if (ctx) playChord(ctx, [220, 277, 330], 0.8);

    t(() => {
      // Phase 2: PARSING
      setPhase(2);
      let step = 0;
      const tickInterval = setInterval(() => {
        step = (step + 1) % 3;
        setParsingStep(step);
        const ctx2 = getAudioCtx();
        if (ctx2) playTick(ctx2);
      }, 220);

      t(() => {
        clearInterval(tickInterval);
        // Phase 3: CAMERA PAN
        setPhase(3);

        t(() => {
          // Phase 4: WIDGET MOUNT
          setPhase(4);
          sortedWidgets.forEach((_, i) => {
            t(() => {
              setMountedWidgets((prev) => [...prev, i]);
            }, i * 200);
          });

          const allMountedAt = sortedWidgets.length * 200 + 400;

          t(() => {
            // Phase 5: CONFIRMATION
            setPhase(5);
            setToastVisible(true);

            const ctx3 = getAudioCtx();
            if (ctx3) playChord(ctx3, [261, 330, 392], 1.2);

            t(() => {
              setOverlayHidden(true);
              onComplete();
            }, 2000);

            t(() => setToastVisible(false), 8000);
          }, allMountedAt);
        }, 1500); // pan duration
      }, 700); // parsing duration
    }, 800); // initiation duration
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive]);

  if (!isActive || phase === 0) return null;

  const overlayOpacity =
    phase <= 2 ? 1 : phase === 3 ? 0.85 : phase === 4 ? 0.4 : 0;

  const truncatedPrompt =
    prompt.length > 50 ? prompt.slice(0, 50) + "…" : prompt;

  return (
    <>
      {/* ── MAIN OVERLAY ── */}
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 200,
          background:
            "radial-gradient(ellipse at center, transparent 20%, rgba(0,0,0,0.85) 100%)",
          display: overlayHidden ? "none" : "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          opacity: overlayOpacity,
          transition: phase === 5 ? "opacity 800ms ease" : undefined,
          animation: phase === 1 ? "bmg-fade-in 400ms ease forwards" : undefined,
          pointerEvents: phase >= 4 ? "none" : "auto",
        }}
      >
        {/* Scan line (phase 2) */}
        {phase === 2 && (
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: 0,
              width: "100%",
              height: 1,
              background:
                "linear-gradient(90deg, transparent, #84cc16, transparent)",
              animation: "bmg-scan-line 1.2s linear infinite",
            }}
          />
        )}

        {/* BMG logo circle (phases 1-2) */}
        {(phase === 1 || phase === 2) && (
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: "50%",
              border: "1.5px solid #84cc16",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              animation: "bmg-logo-pulse 1.2s ease-in-out infinite",
              boxShadow: "0 0 24px #84cc1640",
              position: "relative",
              zIndex: 1,
            }}
          >
            <span
              style={{
                fontFamily: "monospace",
                fontSize: 20,
                color: "#84cc16",
                fontWeight: 700,
              }}
            >
              B
            </span>
          </div>
        )}

        {/* Phase 1 label */}
        {phase === 1 && (
          <p
            style={{
              marginTop: 16,
              fontFamily: "monospace",
              fontSize: 13,
              color: "#84cc16",
              letterSpacing: "0.05em",
              position: "relative",
              zIndex: 1,
            }}
          >
            Configuring workspace...
          </p>
        )}

        {/* Phase 2 parsing detail */}
        {phase === 2 && (
          <div
            style={{
              marginTop: 16,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
              position: "relative",
              zIndex: 1,
            }}
          >
            <p
              style={{
                fontFamily: "monospace",
                fontSize: 13,
                color: "#84cc16",
                letterSpacing: "0.04em",
              }}
            >
              Analyzing: &ldquo;{truncatedPrompt}&rdquo;
            </p>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                marginTop: 8,
              }}
            >
              {PARSING_STEPS.map((label, i) => (
                <p
                  key={i}
                  style={{
                    fontFamily: "monospace",
                    fontSize: 11,
                    color: "#84cc16",
                    opacity: parsingStep === i ? 1 : 0.2,
                    transition: "opacity 220ms",
                    letterSpacing: "0.04em",
                  }}
                >
                  {label}
                </p>
              ))}
            </div>
          </div>
        )}

        {/* Phase 3 pan label */}
        {phase === 3 && (
          <p
            style={{
              fontFamily: "monospace",
              fontSize: 13,
              color: "#84cc16",
              letterSpacing: "0.05em",
              opacity: 0.8,
            }}
          >
            Building layout...
          </p>
        )}

        {/* Phase 4: widget mount preview */}
        {phase >= 4 && phase < 5 && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              flexWrap: "wrap",
              alignContent: "flex-start",
              gap: 8,
              padding: "24px 32px",
            }}
          >
            <div
              style={{
                width: "100%",
                marginBottom: 8,
                fontFamily: "monospace",
                fontSize: 11,
                color: "#84cc16",
                letterSpacing: "0.08em",
                opacity: 0.7,
              }}
            >
              ✦ {workspaceName}
            </div>
            {sortedWidgets.map((widget, i) => {
              const isMounted = mountedWidgets.includes(i);
              const widthPct = (widget.w / 12) * 100;
              const heightPx = widget.h * 48;
              return (
                <div
                  key={i}
                  style={{
                    width: `calc(${widthPct}% - 8px)`,
                    height: heightPx,
                    background: "rgba(15, 23, 42, 0.9)",
                    border: "1px solid #1e293b",
                    borderRadius: 8,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 6,
                    opacity: isMounted ? 1 : 0,
                    transform: isMounted
                      ? "scale(1) translateY(0)"
                      : "scale(0.92) translateY(4px)",
                    filter: isMounted ? "blur(0px)" : "blur(8px)",
                    animation: isMounted
                      ? "bmg-widget-mount 300ms cubic-bezier(0.16, 1, 0.3, 1) forwards, bmg-border-flash 400ms ease forwards"
                      : undefined,
                    transition: "opacity 300ms, transform 300ms, filter 300ms",
                  }}
                >
                  <span style={{ fontSize: 22 }}>
                    {WIDGET_ICONS[widget.type] ?? "📦"}
                  </span>
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontSize: 11,
                      color: "#94a3b8",
                      letterSpacing: "0.04em",
                    }}
                  >
                    {widget.title}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── CONFIRMATION TOAST ── */}
      {toastVisible && (
        <div
          style={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            zIndex: 201,
            background: "#1E293B",
            border: "1px solid #334155",
            borderRadius: 12,
            padding: "12px 16px",
            display: "flex",
            alignItems: "center",
            gap: 12,
            animation:
              "bmg-toast-up 400ms cubic-bezier(0.16, 1, 0.3, 1) forwards",
            minWidth: 300,
          }}
        >
          <span
            style={{
              color: "#84cc16",
              fontSize: 12,
              fontFamily: "monospace",
            }}
          >
            ✦ Configured by Co-Pilot
          </span>
          <span style={{ color: "#475569", fontSize: 12 }}>·</span>
          <span style={{ color: "#94a3b8", fontSize: 12 }}>looks good?</span>
          <div
            style={{ marginLeft: "auto", display: "flex", gap: 8 }}
          >
            <button
              onClick={onSave}
              style={{
                background: "#3B82F6",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                padding: "4px 10px",
                fontSize: 11,
                fontFamily: "monospace",
                cursor: "pointer",
              }}
            >
              Save workspace
            </button>
            <button
              onClick={onRefine}
              style={{
                background: "transparent",
                color: "#94a3b8",
                border: "1px solid #334155",
                borderRadius: 6,
                padding: "4px 10px",
                fontSize: 11,
                cursor: "pointer",
              }}
            >
              Refine
            </button>
          </div>
        </div>
      )}
    </>
  );
}
