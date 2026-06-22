import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

/**
 * IntroSequencePage — the 8-scene cinematic intro from the design canvas.
 *
 * The intro is shipped as a self-contained static HTML at /intro/index.html
 * (uses canvas, Web Audio API, and the dc-runtime parser). Embedding via
 * iframe preserves the designer's animation pixel-perfect at the cost of one
 * React+ReactDOM CDN load on first visit. Since the intro only runs ONCE per
 * user (gated by localStorage.bmg_intro_seen), the cost is paid exactly once.
 *
 * Flow:
 *   1. iframe loads /intro/index.html
 *   2. animation plays (~25 seconds, skip / replay buttons available)
 *   3. iframe postMessages { type: 'intro:done' } when complete
 *   4. host writes localStorage flag + navigates to /login
 */
export default function IntroSequencePage() {
  const navigate = useNavigate();
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // Trust only messages coming from our own iframe — no origin check
      // needed since same-origin (/intro/index.html is served by us).
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as { type?: string } | null;
      if (!data || data.type !== "intro:done") return;
      try { localStorage.setItem("bmg_intro_seen", "1"); } catch { /* ignore */ }
      navigate("/login", { replace: true });
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [navigate]);

  // Escape hatch: bypass the iframe entirely. The intro file has its own
  // SKIP button, but this catches the rare case where the iframe can't load
  // (e.g. CDN React blocked by an ad blocker on first paint).
  const handleBypass = () => {
    try { localStorage.setItem("bmg_intro_seen", "1"); } catch { /* ignore */ }
    navigate("/login", { replace: true });
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "#020402",
        zIndex: 9999,
      }}
    >
      <iframe
        ref={iframeRef}
        src="/intro/index.html"
        title="BMG Capital — Intro"
        style={{ width: "100%", height: "100%", border: "0", display: "block" }}
        allow="autoplay"
      />
      {/* Tiny fallback bypass — only relevant if the iframe doesn't load.
          The animation has its own SKIP button overlaid on the canvas. */}
      <button
        onClick={handleBypass}
        style={{
          position: "fixed",
          bottom: 12,
          right: 12,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
          letterSpacing: "0.08em",
          color: "rgba(126,142,126,0.6)",
          background: "transparent",
          border: "1px solid rgba(74,222,128,0.1)",
          borderRadius: 4,
          padding: "5px 9px",
          cursor: "pointer",
          zIndex: 10000,
        }}
        aria-label="Bypass intro and continue to login"
      >
        BYPASS ↦
      </button>
    </div>
  );
}
