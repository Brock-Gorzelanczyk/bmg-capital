import { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import {
  Eye, EyeOff, Mic, Zap, Search, Hammer, Bot, Trophy,
  TrendingUp, Shield, BarChart2, ChevronDown, ChevronUp,
  ArrowRight, Check, Star,
} from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { DEMO_EMAIL, DEMO_PASSWORD } from "@/lib/demoMode";

gsap.registerPlugin(ScrollTrigger);
gsap.registerPlugin(useGSAP);

// ─── Shared bg primitives ─────────────────────────────────────────────────────

const G = "#84cc16";

function GridBg() {
  return (
    <>
      <div className="absolute inset-0 pointer-events-none" style={{
        backgroundImage: "linear-gradient(rgba(132,204,22,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(132,204,22,0.04) 1px, transparent 1px)",
        backgroundSize: "60px 60px",
      }} />
      <div className="absolute inset-0 pointer-events-none" style={{
        background: "radial-gradient(ellipse 80% 60% at 50% 10%, rgba(132,204,22,0.07) 0%, transparent 70%)",
      }} />
    </>
  );
}

// ─── Loading screen ───────────────────────────────────────────────────────────

function LoadingScreen({ onDone }: { onDone: () => void }) {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const intervals = [
      { target: 35, delay: 0, duration: 400 },
      { target: 70, delay: 450, duration: 350 },
      { target: 92, delay: 850, duration: 300 },
      { target: 100, delay: 1200, duration: 200 },
    ];
    const timers: ReturnType<typeof setTimeout>[] = [];
    intervals.forEach(({ target, delay, duration }) => {
      const t = setTimeout(() => {
        const start = Date.now();
        const startVal = progress;
        const tick = () => {
          const elapsed = Date.now() - start;
          const frac = Math.min(elapsed / duration, 1);
          setProgress(Math.round(startVal + (target - startVal) * frac));
          if (frac < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }, delay);
      timers.push(t);
    });
    const done = setTimeout(onDone, 1700);
    timers.push(done);
    return () => timers.forEach(clearTimeout);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <motion.div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#020b02]"
      exit={{ opacity: 0 }}
      transition={{ duration: 0.5 }}
    >
      <GridBg />
      <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4 }}>
        <h1 className="text-3xl font-black tracking-[0.2em] uppercase text-center"
          style={{ color: G, textShadow: `0 0 40px rgba(132,204,22,0.5)` }}>
          BMG CAPITAL
        </h1>
        <p className="text-[10px] font-mono tracking-[0.5em] text-center mt-1" style={{ color: `${G}40` }}>
          QUANTITATIVE TRADING SYSTEM
        </p>
      </motion.div>
      <div className="mt-10 w-48">
        <div className="flex items-center justify-between text-[9px] font-mono mb-1" style={{ color: `${G}50` }}>
          <span>INITIALIZING</span>
          <span>{progress}%</span>
        </div>
        <div className="h-px bg-[#0f1a0f] w-full overflow-hidden">
          <motion.div className="h-full" style={{ background: G, width: `${progress}%`, transition: "width 0.1s linear" }} />
        </div>
      </div>
    </motion.div>
  );
}

// ─── Auth modal ───────────────────────────────────────────────────────────────

function CornerBrackets() {
  const s = { boxShadow: "0 0 8px rgba(132,204,22,0.5)" };
  return (
    <>
      <span className="absolute -top-px -left-px w-6 h-6 border-t-2 border-l-2 border-[#84cc16]" style={s} />
      <span className="absolute -top-px -right-px w-6 h-6 border-t-2 border-r-2 border-[#84cc16]" style={s} />
      <span className="absolute -bottom-px -left-px w-6 h-6 border-b-2 border-l-2 border-[#84cc16]" style={s} />
      <span className="absolute -bottom-px -right-px w-6 h-6 border-b-2 border-r-2 border-[#84cc16]" style={s} />
    </>
  );
}

function AuthField({ label, type, value, onChange, autoComplete, placeholder, children }: {
  label: string; type: string; value: string; onChange: (v: string) => void;
  autoComplete?: string; placeholder?: string; children?: React.ReactNode;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <div className="relative">
      <label className="block text-[10px] font-mono tracking-[0.2em] uppercase mb-1.5" style={{ color: `${G}60` }}>{label}</label>
      <div className="relative">
        <input type={type} value={value} onChange={e => onChange(e.target.value)}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          autoComplete={autoComplete} placeholder={placeholder}
          className="w-full bg-transparent border-0 border-b text-white text-sm py-2 pr-8 outline-none placeholder-[#2a3a2a]"
          style={{ borderBottomColor: focused ? G : "#1e3a1e", transition: "border-color 0.2s" }} />
        {children}
      </div>
    </div>
  );
}

function AuthModal({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login, register } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (mode === "register" && password !== confirm) { setError("Passwords do not match"); return; }
    setLoading(true);
    try {
      if (mode === "login") await login(email, password); else await register(email, username, password);
      navigate("/");
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Authentication failed. Try again.");
    } finally { setLoading(false); }
  };

  const handleDemo = async () => {
    setError(""); setLoading(true);
    try { await login(DEMO_EMAIL, DEMO_PASSWORD); navigate("/"); }
    catch { setError("Demo account unavailable."); }
    finally { setLoading(false); }
  };

  return (
    <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <motion.div className="relative z-10 w-full max-w-sm"
        initial={{ scale: 0.92, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.92, y: 20 }}
        transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}>
        <div className="relative p-8 rounded-sm" style={{ background: "rgba(2,11,2,0.95)", backdropFilter: "blur(16px)", border: "1px solid rgba(132,204,22,0.2)" }}>
          <CornerBrackets />
          <div className="mb-6 text-center">
            <h2 className="text-lg font-black tracking-[0.15em] uppercase" style={{ color: G }}>BMG CAPITAL</h2>
            <p className="text-[9px] font-mono tracking-[0.4em] mt-0.5" style={{ color: `${G}30` }}>QUANTITATIVE TRADING SYSTEM</p>
          </div>
          <p className="text-[10px] font-mono tracking-[0.3em] mb-5 uppercase" style={{ color: `${G}40` }}>
            {mode === "login" ? "// AUTHENTICATE" : "// NEW ACCOUNT"}
          </p>
          <form onSubmit={handleSubmit} className="space-y-4">
            <AuthField label="Email" type={mode === "login" ? "text" : "email"} value={email} onChange={setEmail}
              autoComplete="username" placeholder={mode === "login" ? "username or email" : "you@example.com"} />
            {mode === "register" && (
              <AuthField label="Username" type="text" value={username} onChange={setUsername} autoComplete="username" placeholder="your_username" />
            )}
            <AuthField label="Password" type={showPw ? "text" : "password"} value={password} onChange={setPassword}
              autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder="••••••••">
              <button type="button" onClick={() => setShowPw(v => !v)} tabIndex={-1}
                className="absolute right-0 top-1/2 -translate-y-1/2 transition-colors" style={{ color: "#2a4a2a" }}>
                {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </AuthField>
            {mode === "register" && (
              <AuthField label="Confirm Password" type={showConfirm ? "text" : "password"} value={confirm} onChange={setConfirm}
                autoComplete="new-password" placeholder="••••••••">
                <button type="button" onClick={() => setShowConfirm(v => !v)} tabIndex={-1}
                  className="absolute right-0 top-1/2 -translate-y-1/2" style={{ color: "#2a4a2a" }}>
                  {showConfirm ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </AuthField>
            )}
            {mode === "login" && (
              <div className="flex justify-end -mt-2">
                <Link to="/forgot-password" onClick={onClose} className="text-[10px] font-mono tracking-widest uppercase" style={{ color: "#2a4a2a" }}>
                  Forgot password?
                </Link>
              </div>
            )}
            <AnimatePresence>
              {error && (
                <motion.p initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  className="text-xs font-mono text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                  {error}
                </motion.p>
              )}
            </AnimatePresence>
            <button type="submit" disabled={loading}
              className="relative w-full overflow-hidden rounded border text-sm font-mono tracking-[0.2em] uppercase py-3 transition-all disabled:opacity-50"
              style={{ background: "rgba(132,204,22,0.1)", borderColor: "rgba(132,204,22,0.4)", color: G }}>
              <span>{loading ? "AUTHENTICATING…" : mode === "login" ? "AUTHENTICATE" : "CREATE ACCOUNT"}</span>
            </button>
            {mode === "login" && (
              <>
                <div className="flex items-center gap-3">
                  <div className="flex-1 h-px bg-[#1e3a1e]" />
                  <span className="text-[9px] font-mono text-[#2a4a2a] tracking-widest">OR</span>
                  <div className="flex-1 h-px bg-[#1e3a1e]" />
                </div>
                <button type="button" onClick={handleDemo} disabled={loading}
                  className="w-full flex items-center justify-center gap-2 border border-[#1e3a1e] text-[10px] font-mono tracking-widest uppercase py-2.5 rounded transition-all disabled:opacity-50"
                  style={{ color: "#2a6a2a" }}>
                  <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: G }} />
                  LIVE DEMO — NO ACCOUNT
                </button>
              </>
            )}
          </form>
          <div className="mt-5 pt-4 border-t border-[#1e3a1e] text-center">
            <p className="text-[10px] font-mono tracking-widest uppercase" style={{ color: "#2a4a2a" }}>
              {mode === "login" ? (
                <>NO ACCOUNT?{" "}
                  <button type="button" onClick={() => { setMode("register"); setError(""); }} style={{ color: `${G}50` }}>
                    SIGN UP FREE
                  </button>
                </>
              ) : (
                <>HAVE AN ACCOUNT?{" "}
                  <button type="button" onClick={() => { setMode("login"); setError(""); }} style={{ color: `${G}50` }}>
                    SIGN IN
                  </button>
                </>
              )}
            </p>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ─── Section 1: Hero ──────────────────────────────────────────────────────────

const TICKER = [
  "BTC/USD $99,240 +2.31%", "ETH/USD $3,821 +1.42%", "SOL/USD $182.40 +4.07%",
  "NVDA $145.20 −1.18%", "AAPL $214.30 +0.82%", "SPY $592.40 +0.24%",
  "QQQ $510.10 +0.41%", "TSLA $248.90 −0.63%", "MSFT $420.15 +0.91%",
];

function HeroSection({ onAuth }: { onAuth: () => void }) {
  const items = [...TICKER, ...TICKER];
  return (
    <section className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden bg-[#020b02] px-4">
      <GridBg />
      {/* Ticker */}
      <div className="absolute bottom-0 inset-x-0 overflow-hidden h-7 pointer-events-none select-none border-t border-[#0f1a0f]">
        <div className="flex gap-8 whitespace-nowrap text-[10px] font-mono text-[#84cc16]/18"
          style={{ animation: "bmg-ticker 60s linear infinite" }}>
          {items.map((t, i) => <span key={i}>{t}</span>)}
        </div>
      </div>

      <div className="relative z-10 max-w-3xl mx-auto text-center space-y-6">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7 }}>
          <div className="flex items-center justify-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: G }} />
            <span className="text-[10px] font-mono tracking-[0.4em] uppercase" style={{ color: `${G}60` }}>
              Paper trading only · not financial advice
            </span>
          </div>
          <h1 className="text-5xl sm:text-6xl font-black tracking-[0.1em] uppercase leading-none"
            style={{ color: G, textShadow: "0 0 60px rgba(132,204,22,0.3), 0 0 120px rgba(132,204,22,0.1)" }}>
            BMG CAPITAL
          </h1>
          <p className="text-[11px] font-mono tracking-[0.5em] mt-2 uppercase" style={{ color: `${G}30` }}>
            Quantitative Trading System
          </p>
        </motion.div>

        <motion.p initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.2 }}
          className="text-xl text-slate-400 max-w-xl mx-auto leading-relaxed">
          AI-scored setups. Automated bots. Strategy leaderboard.
          <br />
          <span style={{ color: G }}>The full edge — paper trading.</span>
        </motion.p>

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.35 }}
          className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
          <button onClick={onAuth}
            className="w-full sm:w-auto px-8 py-3.5 rounded font-mono text-sm tracking-[0.15em] uppercase font-bold transition-all duration-300"
            style={{ background: `linear-gradient(135deg, ${G} 0%, #65a30d 100%)`, color: "#020b02", boxShadow: "0 0 30px rgba(132,204,22,0.35)" }}>
            Get Started Free <ArrowRight className="inline w-4 h-4 ml-1" />
          </button>
          <button onClick={onAuth}
            className="w-full sm:w-auto px-8 py-3.5 rounded font-mono text-sm tracking-[0.15em] uppercase transition-all duration-300 border"
            style={{ borderColor: `${G}40`, color: `${G}80`, background: "transparent" }}>
            Sign In
          </button>
        </motion.div>

        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.6, delay: 0.5 }}
          className="flex items-center justify-center gap-6 pt-4">
          {["12 Active Bots", "500+ Symbols Scanned", "Real-time Signals"].map(tag => (
            <div key={tag} className="flex items-center gap-1.5">
              <Check className="w-3 h-3" style={{ color: G }} />
              <span className="text-[11px] font-mono text-slate-500">{tag}</span>
            </div>
          ))}
        </motion.div>
      </div>

      {/* Scroll cue */}
      <div className="absolute bottom-10 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1"
        style={{ animation: "bounce 2s ease-in-out infinite" }}>
        <span className="text-[9px] font-mono tracking-widest uppercase" style={{ color: `${G}30` }}>EXPLORE</span>
        <ChevronDown className="w-4 h-4" style={{ color: `${G}40` }} />
      </div>
    </section>
  );
}

// ─── Section 2: Bento grid ────────────────────────────────────────────────────

const BENTO_TILES = [
  { col: "col-span-2 row-span-2", icon: <Search className="w-5 h-5" />, label: "Strategy Scout", accent: "rgba(139,92,246,0.3)", textAccent: "#c4b5fd",
    body: "AI scans 500+ symbols every 15 minutes. Surfaces the highest-conviction setups with entry, stop, target, and an AI-generated trade briefing.",
    stat: "87% avg confidence", wide: true },
  { col: "col-span-1 row-span-1", icon: <Hammer className="w-4 h-4" />, label: "The Forge", accent: "rgba(245,158,11,0.25)", textAccent: "#fcd34d",
    body: "Build custom bots with a guided wizard. No code required. Deploy in under 5 minutes." },
  { col: "col-span-1 row-span-1", icon: <Bot className="w-4 h-4" />, label: "Smart Bots", accent: "rgba(14,165,233,0.25)", textAccent: "#7dd3fc",
    body: "12 pre-built strategies across stocks, crypto, and quant. Live paper trading 24/7." },
  { col: "col-span-1 row-span-2", icon: <Trophy className="w-5 h-5" />, label: "Leaderboard", accent: "rgba(16,185,129,0.25)", textAccent: "#6ee7b7",
    body: "Dollar-weighted strategy rankings across all bots. Know what's making money before you allocate.",
    stat: "Real-time rankings", tall: true },
  { col: "col-span-1 row-span-1", icon: <Mic className="w-4 h-4" />, label: "Voice AI", accent: "rgba(132,204,22,0.2)", textAccent: "#84cc16",
    body: "Natural language portfolio control. Ask anything. Pause bots. Get instant P&L." },
  { col: "col-span-1 row-span-1", icon: <BarChart2 className="w-4 h-4" />, label: "Performance", accent: "rgba(239,68,68,0.2)", textAccent: "#fca5a5",
    body: "Sharpe, Sortino, drawdown, win rate, and equity curves — per bot or portfolio-wide." },
  { col: "col-span-1 row-span-1", icon: <Shield className="w-4 h-4" />, label: "Risk Rules", accent: "rgba(245,158,11,0.2)", textAccent: "#fcd34d",
    body: "Hot-swappable YAML risk rules. Max loss, position sizing, and blackout windows." },
  { col: "col-span-1 row-span-1", icon: <TrendingUp className="w-4 h-4" />, label: "Markets", accent: "rgba(14,165,233,0.2)", textAccent: "#7dd3fc",
    body: "Live crypto + stock screener. Sparklines, % changes, and one-click Scout integration." },
];

function BentoSection() {
  const containerRef = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const tiles = containerRef.current?.querySelectorAll(".bento-tile");
    if (!tiles) return;
    tiles.forEach((tile, i) => {
      gsap.fromTo(tile,
        { opacity: 0, y: 30 },
        { opacity: 1, y: 0, duration: 0.6, delay: i * 0.06,
          scrollTrigger: { trigger: tile, start: "top 88%", toggleActions: "play none none none" } }
      );
    });
  }, { scope: containerRef });

  return (
    <section className="py-24 px-4 bg-[#020b02]" ref={containerRef}>
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-12">
          <p className="text-[10px] font-mono tracking-[0.4em] uppercase mb-2" style={{ color: `${G}50` }}>// PLATFORM</p>
          <h2 className="text-3xl font-black text-white">Everything you need to trade smarter.</h2>
        </div>
        <div className="grid grid-cols-3 gap-3 auto-rows-[120px]">
          {BENTO_TILES.map((tile, i) => (
            <div key={i} className={`bento-tile ${tile.col} rounded-2xl p-4 border border-white/5 flex flex-col justify-between overflow-hidden relative`}
              style={{ background: `color-mix(in srgb, ${tile.accent} 100%, #020b02)` }}>
              <div className="flex items-center gap-2 mb-1">
                <span style={{ color: tile.textAccent }}>{tile.icon}</span>
                <span className="text-[10px] font-bold tracking-widest font-mono" style={{ color: tile.textAccent }}>{tile.label}</span>
              </div>
              <p className="text-[11px] text-white/60 leading-snug">{tile.body}</p>
              {tile.stat && (
                <span className="text-[9px] font-mono mt-1" style={{ color: tile.textAccent }}>{tile.stat}</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Section 3: How it works (GSAP pin) ───────────────────────────────────────

const HOW_STEPS = [
  { num: "01", title: "Scout surfaces the setup", icon: <Search className="w-6 h-6" />, accent: "#c4b5fd",
    desc: "AI scans 500+ symbols every 15 minutes. High-conviction setups come with entry, stop, target, R:R, and an AI trade briefing. Never miss a setup again." },
  { num: "02", title: "Forge builds your bot", icon: <Hammer className="w-6 h-6" />, accent: "#fcd34d",
    desc: "Pick a strategy template, configure parameters (risk %, timeframe, universe), and deploy a live paper-trading bot in under 5 minutes. No code." },
  { num: "03", title: "Bot executes automatically", icon: <Zap className="w-6 h-6" />, accent: "#84cc16",
    desc: "Bots run 24/7, apply your risk rules, and push every signal to Discord. Full audit trail. You stay in control without watching every tick." },
  { num: "04", title: "Leaderboard shows the truth", icon: <Trophy className="w-6 h-6" />, accent: "#6ee7b7",
    desc: "Dollar-weighted rankings across every strategy. No cherry-picked metrics. Allocate more to what's working. Cut what's not." },
];

function HowItWorksSection() {
  const pinRef = useRef<HTMLDivElement>(null);
  const [activeStep, setActiveStep] = useState(0);

  useGSAP(() => {
    const steps = HOW_STEPS.map((_, i) => {
      return ScrollTrigger.create({
        trigger: pinRef.current,
        start: `top+=${i * 25}% center`,
        end: `top+=${(i + 1) * 25}% center`,
        onEnter: () => setActiveStep(i),
        onEnterBack: () => setActiveStep(i),
      });
    });
    return () => steps.forEach(s => s.kill());
  }, { scope: pinRef });

  return (
    <section className="py-24 px-4 bg-[#030f03] border-y border-[#0f1a0f]" ref={pinRef}>
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-16">
          <p className="text-[10px] font-mono tracking-[0.4em] uppercase mb-2" style={{ color: `${G}50` }}>// HOW IT WORKS</p>
          <h2 className="text-3xl font-black text-white">Scout → Build → Execute → Rank.</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* Steps */}
          <div className="space-y-4">
            {HOW_STEPS.map((step, i) => (
              <div key={step.num} onClick={() => setActiveStep(i)}
                className="rounded-xl p-4 border transition-all duration-300 cursor-pointer"
                style={{
                  borderColor: activeStep === i ? `${step.accent}60` : "rgba(255,255,255,0.05)",
                  background: activeStep === i ? `color-mix(in srgb, ${step.accent} 10%, transparent)` : "transparent",
                }}>
                <div className="flex items-center gap-3">
                  <span className="text-[10px] font-mono font-bold" style={{ color: activeStep === i ? step.accent : "#2a4a2a" }}>
                    {step.num}
                  </span>
                  <span style={{ color: activeStep === i ? step.accent : "#3a5a3a" }}>{step.icon}</span>
                  <span className="font-semibold text-sm" style={{ color: activeStep === i ? "white" : "#4a6a4a" }}>
                    {step.title}
                  </span>
                </div>
                <AnimatePresence>
                  {activeStep === i && (
                    <motion.p initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
                      className="text-sm text-slate-400 mt-3 leading-relaxed pl-10">
                      {step.desc}
                    </motion.p>
                  )}
                </AnimatePresence>
              </div>
            ))}
          </div>
          {/* Visual panel */}
          <div className="hidden md:flex items-center justify-center">
            <div className="w-full max-w-xs rounded-2xl border p-6 text-center"
              style={{ borderColor: `${HOW_STEPS[activeStep].accent}40`, background: `color-mix(in srgb, ${HOW_STEPS[activeStep].accent} 8%, #030f03)` }}>
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
                style={{ background: `color-mix(in srgb, ${HOW_STEPS[activeStep].accent} 20%, transparent)`, color: HOW_STEPS[activeStep].accent }}>
                {HOW_STEPS[activeStep].icon}
              </div>
              <p className="text-[10px] font-mono tracking-widest uppercase mb-2" style={{ color: `${HOW_STEPS[activeStep].accent}70` }}>
                STEP {HOW_STEPS[activeStep].num}
              </p>
              <p className="text-white font-bold text-lg">{HOW_STEPS[activeStep].title}</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Section 4: Stats block ───────────────────────────────────────────────────

const STATS = [
  { value: "12", label: "Active Bots", sub: "stocks, crypto, quant" },
  { value: "500+", label: "Symbols Scanned", sub: "every 15 minutes" },
  { value: "24/7", label: "Paper Trading", sub: "no sleep, no breaks" },
  { value: "87%", label: "Avg Scout Confidence", sub: "signal quality threshold" },
];

function StatsSection() {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    gsap.fromTo(ref.current?.querySelectorAll(".stat-card") ?? [],
      { opacity: 0, y: 20 },
      { opacity: 1, y: 0, stagger: 0.1, duration: 0.5,
        scrollTrigger: { trigger: ref.current, start: "top 80%" } }
    );
  }, { scope: ref });

  return (
    <section className="py-20 px-4 bg-[#020b02]" ref={ref}>
      <div className="max-w-4xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-4">
        {STATS.map(s => (
          <div key={s.label} className="stat-card text-center rounded-2xl p-6 border border-[#0f1a0f] bg-[#030f03]">
            <p className="text-4xl font-black font-mono" style={{ color: G }}>{s.value}</p>
            <p className="text-sm font-semibold text-white mt-1">{s.label}</p>
            <p className="text-[10px] text-slate-500 mt-0.5 font-mono">{s.sub}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

// ─── Section 5: Pricing ───────────────────────────────────────────────────────

const PLANS = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    accent: "#64748b",
    features: ["Dashboard + Portfolio", "Strategy Scout (10/day)", "5 pre-built bots", "Discord signal feed"],
    cta: "Get Started",
    highlight: false,
  },
  {
    name: "Pro",
    price: "$29",
    period: "/month",
    accent: G,
    features: ["Everything in Free", "Unlimited Scout signals", "12 bots + The Forge", "AI trade explanations", "Performance analytics", "Voice AI (beta)"],
    cta: "Start Pro",
    highlight: true,
    badge: "Most Popular",
  },
  {
    name: "Pro+",
    price: "$79",
    period: "/month",
    accent: "#c4b5fd",
    features: ["Everything in Pro", "Strategy leaderboard", "Custom bot builder", "Priority signal queue", "CFP booking", "White-glove onboarding"],
    cta: "Go Pro+",
    highlight: false,
  },
];

function PricingSection({ onAuth }: { onAuth: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    gsap.fromTo(ref.current?.querySelectorAll(".price-card") ?? [],
      { opacity: 0, y: 30 },
      { opacity: 1, y: 0, stagger: 0.12, duration: 0.6,
        scrollTrigger: { trigger: ref.current, start: "top 80%" } }
    );
  }, { scope: ref });

  return (
    <section className="py-24 px-4 bg-[#030f03] border-y border-[#0f1a0f]" ref={ref}>
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-12">
          <p className="text-[10px] font-mono tracking-[0.4em] uppercase mb-2" style={{ color: `${G}50` }}>// PRICING</p>
          <h2 className="text-3xl font-black text-white">Simple, transparent pricing.</h2>
          <p className="text-slate-400 mt-2 text-sm">Paper trading only. No financial advice.</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {PLANS.map(plan => (
            <div key={plan.name} className={`price-card rounded-2xl p-6 border flex flex-col relative`}
              style={{
                borderColor: plan.highlight ? `${plan.accent}60` : "rgba(255,255,255,0.07)",
                background: plan.highlight ? `color-mix(in srgb, ${plan.accent} 8%, #030f03)` : "#030f03",
                boxShadow: plan.highlight ? `0 0 40px rgba(132,204,22,0.1)` : "none",
              }}>
              {plan.badge && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-[9px] font-mono font-bold"
                  style={{ background: plan.accent, color: "#020b02" }}>
                  {plan.badge}
                </div>
              )}
              <div className="mb-5">
                <p className="text-[10px] font-mono tracking-widest uppercase mb-1" style={{ color: `${plan.accent}80` }}>{plan.name}</p>
                <div className="flex items-end gap-1">
                  <span className="text-4xl font-black font-mono" style={{ color: plan.highlight ? plan.accent : "white" }}>{plan.price}</span>
                  <span className="text-xs text-slate-500 mb-1 font-mono">{plan.period}</span>
                </div>
              </div>
              <div className="space-y-2 mb-6 flex-1">
                {plan.features.map(f => (
                  <div key={f} className="flex items-start gap-2 text-sm text-slate-300">
                    <Check className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" style={{ color: plan.accent }} />
                    {f}
                  </div>
                ))}
              </div>
              <button onClick={onAuth}
                className="w-full py-2.5 rounded font-mono text-sm tracking-widest uppercase font-bold transition-all"
                style={{
                  background: plan.highlight ? plan.accent : "transparent",
                  color: plan.highlight ? "#020b02" : plan.accent,
                  border: plan.highlight ? "none" : `1px solid ${plan.accent}40`,
                }}>
                {plan.cta}
              </button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Section 6: FAQ accordion ─────────────────────────────────────────────────

const FAQS = [
  { q: "Is this real money trading?", a: "No. BMG Capital is paper trading only. All positions are simulated with no real money involved. It's designed for strategy research and learning." },
  { q: "What is Strategy Scout?", a: "Scout is an AI engine that scans 500+ symbols every 15 minutes, scores setups by confidence, and generates trade briefings with entry, stop, and target levels. Signals are delivered in-app and to Discord." },
  { q: "What is The Forge?", a: "The Forge is a no-code bot builder. Choose a strategy template, configure risk parameters, and deploy a paper-trading bot in under 5 minutes — no programming required." },
  { q: "How does the Strategy Leaderboard work?", a: "The leaderboard aggregates every strategy across all bots using dollar-weighted returns (total P&L ÷ total capital deployed). No cherry-picked metrics — it shows what's actually making paper money." },
  { q: "Can I connect a real brokerage account?", a: "Not at this time. BMG Capital is purely paper trading. Alpaca integration powers the live data feed, but no real orders are placed." },
  { q: "What's included in the free tier?", a: "The free tier includes the Dashboard, Portfolio view, up to 10 Scout signals per day, 5 pre-built strategy bots, and access to the Discord signal feed." },
];

function FAQSection() {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="py-24 px-4 bg-[#020b02]">
      <div className="max-w-2xl mx-auto">
        <div className="text-center mb-12">
          <p className="text-[10px] font-mono tracking-[0.4em] uppercase mb-2" style={{ color: `${G}50` }}>// FAQ</p>
          <h2 className="text-3xl font-black text-white">Common questions.</h2>
        </div>
        <div className="space-y-2">
          {FAQS.map((faq, i) => (
            <div key={i} className="rounded-xl border border-[#0f1a0f] overflow-hidden">
              <button onClick={() => setOpen(open === i ? null : i)}
                className="w-full flex items-center justify-between p-4 text-left transition-colors hover:bg-[#030f03]">
                <span className="font-semibold text-sm text-white">{faq.q}</span>
                {open === i ? <ChevronUp className="w-4 h-4 flex-shrink-0 ml-2" style={{ color: G }} /> : <ChevronDown className="w-4 h-4 flex-shrink-0 ml-2 text-slate-600" />}
              </button>
              <AnimatePresence>
                {open === i && (
                  <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }}
                    style={{ overflow: "hidden" }}>
                    <p className="px-4 pb-4 text-sm text-slate-400 leading-relaxed border-t border-[#0f1a0f] pt-3">{faq.a}</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Section 7: Final CTA ─────────────────────────────────────────────────────

function FinalCTASection({ onAuth }: { onAuth: () => void }) {
  return (
    <section className="py-32 px-4 bg-[#030f03] border-t border-[#0f1a0f] relative overflow-hidden">
      <GridBg />
      <div className="relative z-10 max-w-xl mx-auto text-center space-y-6">
        <div className="flex items-center justify-center gap-2 mb-2">
          <Star className="w-4 h-4" style={{ color: G }} />
          <span className="text-[10px] font-mono tracking-[0.4em] uppercase" style={{ color: `${G}60` }}>START TODAY</span>
          <Star className="w-4 h-4" style={{ color: G }} />
        </div>
        <h2 className="text-4xl font-black text-white leading-tight">
          Your edge is waiting.<br />
          <span style={{ color: G }}>Deploy it.</span>
        </h2>
        <p className="text-slate-400 text-sm leading-relaxed">
          Free to start. No credit card. Full access to Scout, 5 bots, and the Discord feed.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center pt-2">
          <button onClick={onAuth}
            className="px-10 py-3.5 rounded font-mono text-sm tracking-[0.15em] uppercase font-bold transition-all"
            style={{ background: `linear-gradient(135deg, ${G} 0%, #65a30d 100%)`, color: "#020b02", boxShadow: "0 0 30px rgba(132,204,22,0.3)" }}>
            Get Started Free
          </button>
        </div>
      </div>
    </section>
  );
}

// ─── Footer ───────────────────────────────────────────────────────────────────

function Footer() {
  return (
    <footer className="py-10 px-4 bg-[#020b02] border-t border-[#0f1a0f]">
      <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: G }} />
          <span className="text-[10px] font-mono tracking-[0.3em] uppercase" style={{ color: `${G}50` }}>BMG Capital</span>
        </div>
        <div className="flex items-center gap-6">
          {[["Terms", "/terms"], ["Privacy", "/privacy"]].map(([label, to]) => (
            <Link key={label} to={to} className="text-[10px] font-mono text-slate-600 hover:text-slate-400 transition-colors uppercase tracking-widest">{label}</Link>
          ))}
        </div>
        <p className="text-[9px] font-mono text-slate-700 text-center">
          Paper trading only · Not financial advice · © 2025 BMG Capital
        </p>
      </div>
    </footer>
  );
}

// ─── Marquee strip ────────────────────────────────────────────────────────────

function MarqueeStrip() {
  const items = [
    "Strategy Scout", "The Forge", "Smart Bots", "Voice AI", "Leaderboard",
    "Performance Analytics", "Discord Signals", "Risk Rules", "Markets",
  ];
  const doubled = [...items, ...items, ...items];
  return (
    <div className="py-3 border-y border-[#0f1a0f] bg-[#020b02] overflow-hidden">
      <div className="flex gap-8 whitespace-nowrap" style={{ animation: "bmg-ticker 25s linear infinite" }}>
        {doubled.map((item, i) => (
          <span key={i} className="flex items-center gap-2 text-[10px] font-mono tracking-[0.2em] uppercase flex-shrink-0" style={{ color: `${G}40` }}>
            <span style={{ color: `${G}30` }}>◆</span>{item}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── Page assembly ────────────────────────────────────────────────────────────

export default function LoginV2Page() {
  const [showLoader, setShowLoader] = useState(true);
  const [loaderDone, setLoaderDone] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);

  return (
    <div className="bg-[#020b02] min-h-screen" style={{ fontFamily: "var(--font-sans)" }}>
      <AnimatePresence>
        {showLoader && (
          <LoadingScreen onDone={() => { setLoaderDone(true); setTimeout(() => setShowLoader(false), 520); }} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {authOpen && <AuthModal onClose={() => setAuthOpen(false)} />}
      </AnimatePresence>

      <motion.div initial={{ opacity: 0 }} animate={{ opacity: loaderDone ? 1 : 0 }} transition={{ duration: 0.5 }}>
        <HeroSection onAuth={() => setAuthOpen(true)} />
        <MarqueeStrip />
        <BentoSection />
        <HowItWorksSection />
        <StatsSection />
        <PricingSection onAuth={() => setAuthOpen(true)} />
        <FAQSection />
        <FinalCTASection onAuth={() => setAuthOpen(true)} />
        <Footer />
      </motion.div>
    </div>
  );
}
