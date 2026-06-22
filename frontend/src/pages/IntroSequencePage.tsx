import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { X } from "lucide-react";

/**
 * IntroSequencePage — the 8-scene cinematic intro from the design canvas.
 *
 * Embeds /intro/index.html in a full-viewport iframe. The static HTML is the
 * verbatim dc-runtime design doc with self-hosted React UMD bundles, so the
 * animation is preserved pixel-perfect. The host (this component) handles
 * the entry/exit lifecycle:
 *
 *   - Reads `location.state.from` so PLAY INTRO from the topbar returns the
 *     user to whatever page they came from (not /login). Anonymous visitors
 *     hitting /intro directly default to /login.
 *   - Listens for the iframe's `intro:done` postMessage and navigates back
 *     to `from`.
 *   - Escape key closes the intro and navigates back to `from`.
 *   - Visible "× CLOSE" button top-right (above the iframe) provides an
 *     unmissable exit.
 *   - Writes localStorage.bmg_intro_seen on any exit path so the IntroGate
 *     doesn't re-trap users on the next /login visit.
 */
export default function IntroSequencePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // Where to return after the intro finishes or the user bails.
  // PLAY INTRO from the topbar passes { from: pathname }. Direct visitors
  // (anonymous, first-time) default to /login so the auth flow resumes.
  const returnTo = (location.state as { from?: string } | null)?.from ?? "/login";

  const exit = (markSeen: boolean) => {
    if (markSeen) {
      try { localStorage.setItem("bmg_intro_seen", "1"); } catch { /* ignore */ }
    }
    navigate(returnTo, { replace: true });
  };

  // Iframe postMessage listener — fires when the cinematic completes.
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as { type?: string } | null;
      if (!data || data.type !== "intro:done") return;
      exit(true);
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [navigate, returnTo]);

  // Escape key → close + return to source. Same effect as the close button.
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") exit(true);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [navigate, returnTo]);

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

      {/* Prominent close — always visible, top-right above the iframe.
          Backed by Escape key for keyboard users. */}
      <button
        onClick={() => exit(true)}
        aria-label="Close intro and return"
        title="Close (Escape)"
        style={{
          position: "fixed",
          top: 14,
          right: 14,
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          letterSpacing: "0.1em",
          color: "#dce8dc",
          background: "rgba(8,13,8,0.85)",
          border: "1px solid rgba(74,222,128,0.35)",
          borderRadius: 4,
          padding: "7px 12px",
          cursor: "pointer",
          zIndex: 10000,
          backdropFilter: "blur(4px)",
        }}
      >
        <X size={12} />
        CLOSE
      </button>
    </div>
  );
}
