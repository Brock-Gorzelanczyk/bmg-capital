import { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Zap, Eye, EyeOff, TrendingUp, Cpu, BarChart2, Trophy, Search, Hammer, Bot, Target, ShieldCheck } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { DEMO_EMAIL, DEMO_PASSWORD } from "@/lib/demoMode";
import { BracketFrame, SectionLabel, BMGCard } from "@/components/design";

const ENABLE_SHOWCASE = import.meta.env.VITE_ENABLE_LOGIN_SHOWCASE === "true";

// ─── Shared ticker ────────────────────────────────────────────────────────────

const TICKER = [
  "BTC/USD $99,240 +2.31%", "ETH/USD $3,821 +1.42%", "SOL/USD $182.40 +4.07%",
  "NVDA $145.20 −1.18%", "AAPL $214.30 +0.82%", "SPY $592.40 +0.24%",
  "QQQ $510.10 +0.41%", "TSLA $248.90 −0.63%", "MSFT $420.15 +0.91%",
  "AMZN $218.40 +1.13%", "BNB/USD $610 +0.88%", "XRP/USD $0.58 +3.2%",
  "GLD $237.10 +0.44%", "TLT $91.30 −0.22%", "AVAX/USD $38.70 +2.91%",
];

function TickerBg() {
  const items = [...TICKER, ...TICKER];
  return (
    <div className="absolute bottom-0 inset-x-0 overflow-hidden h-7 pointer-events-none select-none">
      <div className="flex gap-8 whitespace-nowrap text-[10px] font-mono text-[#84cc16]/18"
        style={{ animation: "bmg-ticker 60s linear infinite" }}>
        {items.map((t, i) => <span key={i}>{t}</span>)}
      </div>
    </div>
  );
}

function GridBg() {
  return (
    <>
      <div className="absolute inset-0 pointer-events-none" style={{
        backgroundImage: "linear-gradient(rgba(132,204,22,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(132,204,22,0.04) 1px, transparent 1px)",
        backgroundSize: "60px 60px",
      }} />
      <div className="absolute inset-0 pointer-events-none" style={{
        background: "radial-gradient(ellipse 80% 60% at 50% 20%, rgba(132,204,22,0.07) 0%, transparent 70%)",
      }} />
    </>
  );
}

// ─── Corner brackets ──────────────────────────────────────────────────────────

const BRACKET_SIZE = "w-6 h-6";
const BRACKET_COLOR = "border-[#84cc16]";
const BRACKET_GLOW = { boxShadow: "0 0 8px rgba(132,204,22,0.5)" };

function CornerBrackets() {
  return (
    <>
      <span className={`absolute -top-px -left-px ${BRACKET_SIZE} border-t-2 border-l-2 ${BRACKET_COLOR}`} style={BRACKET_GLOW} />
      <span className={`absolute -top-px -right-px ${BRACKET_SIZE} border-t-2 border-r-2 ${BRACKET_COLOR}`} style={BRACKET_GLOW} />
      <span className={`absolute -bottom-px -left-px ${BRACKET_SIZE} border-b-2 border-l-2 ${BRACKET_COLOR}`} style={BRACKET_GLOW} />
      <span className={`absolute -bottom-px -right-px ${BRACKET_SIZE} border-b-2 border-r-2 ${BRACKET_COLOR}`} style={BRACKET_GLOW} />
    </>
  );
}

// ─── useReveal ────────────────────────────────────────────────────────────────

function useReveal(threshold = 0.12) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); obs.disconnect(); }
    }, { threshold });
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);
  return { ref, visible };
}

// ─── Voice demo ───────────────────────────────────────────────────────────────

const DEMO_SCRIPT = [
  { role: "user" as const, text: "Hey, how's my portfolio doing today?", delay: 500 },
  { role: "ai" as const,   text: "Your combined paper portfolio is up +$43.20 today (+0.43%). Stock Swing leads with +$31.80. Crypto Day is flat. No positions are near their stop levels.", delay: 2800 },
  { role: "user" as const, text: "Which position should I keep an eye on?", delay: 6200 },
  { role: "ai" as const,   text: "NVDA is approaching its +1 ATR pyramid add threshold — another $0.60 up and Stock Swing will add 25% to the position. Win rate on NVDA this month is 71%.", delay: 8800 },
  { role: "user" as const, text: "What's the VIX doing? Should I be worried?", delay: 13500 },
  { role: "ai" as const,   text: "VIX is at 18.4 — mid regime. All bots are running at full size. No catalyst blackouts in the next 2 hours. Next risk event: CPI release Thursday 8:30am ET.", delay: 16000 },
  { role: "user" as const, text: "Pause the crypto day bot for me.", delay: 21500 },
  { role: "ai" as const,   text: "Done — Crypto Day is paused. 3 open positions will hold until manual resume or their stop levels. I'll log this in the audit trail.", delay: 23800 },
];

function VoiceDemo() {
  const [visibleMessages, setVisibleMessages] = useState<typeof DEMO_SCRIPT>([]);
  const [isListening, setIsListening] = useState(false);
  const [cycle, setCycle] = useState(0);

  useEffect(() => {
    setVisibleMessages([]);
    let active = true;
    const timers: ReturnType<typeof setTimeout>[] = [];
    DEMO_SCRIPT.forEach((msg) => {
      const t = setTimeout(() => {
        if (!active) return;
        if (msg.role === "user") {
          setIsListening(true);
          setTimeout(() => { if (active) setIsListening(false); }, 900);
        }
        setVisibleMessages(prev => [...prev, msg]);
      }, msg.delay);
      timers.push(t);
    });
    const restart = setTimeout(() => {
      if (!active) return;
      setVisibleMessages([]);
      setCycle(c => c + 1);
    }, 32_000);
    timers.push(restart);
    return () => { active = false; timers.forEach(clearTimeout); };
  }, [cycle]);

  return (
    <div className="relative w-full max-w-md">
      <div className="relative bg-[#05080f] border border-[#1e293b] rounded-2xl overflow-hidden shadow-2xl shadow-[#84cc16]/5">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-[#1e293b]">
          <div className={`w-2.5 h-2.5 rounded-full transition-all duration-300 ${isListening ? "bg-[#84cc16] animate-pulse scale-125" : "bg-[#84cc16]"}`} />
          <span className="text-sm font-semibold text-white">BMG Voice AI</span>
          <span className="ml-auto text-xs text-slate-500 font-mono">{isListening ? "Listening…" : "Paper trading"}</span>
        </div>
        <div className={`overflow-hidden transition-all duration-300 ${isListening ? "max-h-10 opacity-100" : "max-h-0 opacity-0"}`}>
          <div className="flex items-center justify-center gap-1 py-2 bg-[#84cc16]/5">
            {[1,2,3,4,5,6,7].map(i => (
              <div key={i} className="w-0.5 bg-[#84cc16] rounded-full"
                style={{ height: `${10 + (i % 3) * 8}px`, animation: `pulse ${0.4 + i * 0.08}s ease-in-out infinite alternate` }} />
            ))}
          </div>
        </div>
        <div className="p-4 space-y-3 min-h-[280px]">
          {visibleMessages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              {msg.role === "ai" && (
                <div className="w-6 h-6 rounded-full bg-[#84cc16] flex items-center justify-center mr-2 mt-0.5 shrink-0">
                  <Zap className="w-3 h-3 text-black" />
                </div>
              )}
              <div className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-[var(--bmg-green-dim)] text-[var(--bmg-text)] rounded-br-sm border border-[var(--bmg-green-border)]"
                  : "bg-[#84cc16]/8 text-slate-200 rounded-bl-sm border-l-2 border-[#84cc16]/60"
              }`}>
                {msg.text}
              </div>
              {msg.role === "user" && (
                <div className="w-6 h-6 rounded-full bg-[var(--bmg-green-dim)] border border-[var(--bmg-green-border)] flex items-center justify-center ml-2 mt-0.5 shrink-0">
                  <Mic className="w-3 h-3 text-white" />
                </div>
              )}
            </div>
          ))}
          {visibleMessages.length > 0 && visibleMessages[visibleMessages.length - 1].role === "user" && (
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-full bg-[#84cc16] flex items-center justify-center shrink-0">
                <Zap className="w-3 h-3 text-black" />
              </div>
              <div className="flex gap-1 px-3 py-2">
                {[0,1,2].map(i => (
                  <div key={i} className="w-1.5 h-1.5 rounded-full bg-[#84cc16]/60 animate-bounce"
                    style={{ animationDelay: `${i * 150}ms` }} />
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="px-4 py-3 border-t border-[#1e293b] flex items-center gap-2">
          <div className="flex-1 bg-[#0f172a] border border-[#1e293b] rounded-lg px-3 py-2 text-xs text-slate-600">
            Ask anything about your portfolio…
          </div>
          <div className="w-8 h-8 rounded-lg bg-[#84cc16] flex items-center justify-center">
            <Mic className="w-4 h-4 text-black" />
          </div>
        </div>
      </div>
      <div className="absolute -top-3 -right-3 bg-[#0a0f1e] border border-[#84cc16]/30 rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-[#84cc16] text-xs font-bold">+0.43% today</span>
      </div>
      <div className="absolute -bottom-3 -left-3 bg-[var(--bmg-bg-base)] border border-[var(--bmg-green-border)] rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-[var(--bmg-green)] text-xs font-bold font-mono">8 bots · paper only</span>
      </div>
    </div>
  );
}

// ─── Auth form ────────────────────────────────────────────────────────────────

function AuthField({
  label, type, value, onChange, autoComplete, placeholder, children,
}: {
  label: string; type: string; value: string;
  onChange: (v: string) => void;
  autoComplete?: string; placeholder?: string;
  children?: React.ReactNode;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <div className="relative">
      <label className="block text-[10px] font-mono tracking-[0.2em] uppercase text-[#84cc16]/60 mb-1.5">{label}</label>
      <div className="relative group">
        <input
          type={type} value={value}
          onChange={e => onChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          autoComplete={autoComplete} placeholder={placeholder}
          className="w-full bg-transparent border-0 border-b text-white text-sm py-2 pr-8 outline-none placeholder-[#2a3a2a] transition-all duration-300"
          style={{
            borderBottomColor: focused ? "#84cc16" : "#1e3a1e",
            boxShadow: focused ? "0 1px 0 0 rgba(132,204,22,0.6)" : "none",
          }}
        />
        {focused && (
          <div className="absolute inset-0 pointer-events-none overflow-hidden" style={{ borderBottom: "1px solid transparent" }}>
            <div className="h-full w-16 bg-gradient-to-r from-transparent via-[#84cc16]/10 to-transparent"
              style={{ animation: "bmg-scan 1.5s linear infinite" }} />
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

function LoginForm() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [scanning, setScanning] = useState(false);
  const { login, register } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (mode === "register") {
      if (password !== confirm) { setError("Passwords do not match"); return; }
      if (password.length < 1) { setError("Password required"); return; }
    }
    setLoading(true); setScanning(true);
    await new Promise(r => setTimeout(r, 900));
    try {
      if (mode === "login") { await login(email, password); } else { await register(email, username, password); }
      navigate("/");
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Authentication failed. Try again.");
      setScanning(false);
    } finally { setLoading(false); }
  };

  const handleTryDemo = async () => {
    setError(""); setLoading(true); setScanning(true);
    await new Promise(r => setTimeout(r, 700));
    try { await login(DEMO_EMAIL, DEMO_PASSWORD); navigate("/"); }
    catch { setError("Demo account unavailable. Please create a free account."); setScanning(false); }
    finally { setLoading(false); }
  };

  const isLogin = mode === "login";
  return (
    <div className="w-full">
      <p className="text-[10px] font-mono tracking-[0.3em] text-[#84cc16]/40 mb-6 uppercase">
        {isLogin ? "// AUTHENTICATE" : "// NEW ACCOUNT"}
      </p>
      <form onSubmit={handleSubmit} className="space-y-5">
        <AuthField label="Email" type={isLogin ? "text" : "email"} value={email} onChange={setEmail}
          autoComplete="username" placeholder={isLogin ? "username or email" : "you@example.com"} />
        {!isLogin && (
          <AuthField label="Username" type="text" value={username} onChange={setUsername}
            autoComplete="username" placeholder="your_username" />
        )}
        <AuthField label="Password" type={showPassword ? "text" : "password"} value={password} onChange={setPassword}
          autoComplete={isLogin ? "current-password" : "new-password"} placeholder="••••••••">
          <button type="button" onClick={() => setShowPassword(v => !v)} tabIndex={-1}
            className="absolute right-0 top-1/2 -translate-y-1/2 text-[#2a4a2a] hover:text-[#84cc16] transition-colors">
            {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </AuthField>
        {!isLogin && (
          <AuthField label="Confirm Password" type={showConfirm ? "text" : "password"} value={confirm} onChange={setConfirm}
            autoComplete="new-password" placeholder="••••••••">
            <button type="button" onClick={() => setShowConfirm(v => !v)} tabIndex={-1}
              className="absolute right-0 top-1/2 -translate-y-1/2 text-[#2a4a2a] hover:text-[#84cc16] transition-colors">
              {showConfirm ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </AuthField>
        )}
        {isLogin && (
          <div className="flex justify-end -mt-2">
            <Link to="/forgot-password" className="text-[10px] font-mono text-[#2a4a2a] hover:text-[#84cc16]/60 transition-colors tracking-widest uppercase">
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
          className="relative w-full overflow-hidden rounded border border-[#84cc16]/40 text-sm font-mono tracking-[0.2em] uppercase py-3 transition-all duration-300 disabled:opacity-50"
          style={{
            background: scanning ? "rgba(132,204,22,0.15)" : "linear-gradient(135deg, rgba(132,204,22,0.1) 0%, rgba(132,204,22,0.05) 100%)",
            color: "#84cc16",
            boxShadow: "0 0 20px rgba(132,204,22,0.15), inset 0 1px 0 rgba(132,204,22,0.1)",
          }}>
          {scanning && (
            <div className="absolute inset-0 pointer-events-none" style={{ animation: "bmg-scan-btn 1s linear infinite" }}>
              <div className="absolute inset-y-0 w-12 bg-gradient-to-r from-transparent via-[#84cc16]/30 to-transparent" />
            </div>
          )}
          <span className="relative">{scanning ? "AUTHENTICATING…" : isLogin ? "AUTHENTICATE" : "CREATE ACCOUNT"}</span>
        </button>
        {isLogin && (
          <>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-[#1e3a1e]" />
              <span className="text-[9px] font-mono text-[#2a4a2a] tracking-widest">OR</span>
              <div className="flex-1 h-px bg-[#1e3a1e]" />
            </div>
            <button type="button" onClick={handleTryDemo} disabled={loading}
              className="w-full flex items-center justify-center gap-2 border border-[#1e3a1e] bg-transparent hover:border-[#84cc16]/20 text-[#2a6a2a] hover:text-[#84cc16]/60 text-xs font-mono tracking-widest uppercase py-2.5 rounded transition-all duration-300 disabled:opacity-50">
              <span className="w-1.5 h-1.5 rounded-full bg-[#84cc16] animate-pulse" />
              LIVE DEMO — NO ACCOUNT
            </button>
          </>
        )}
      </form>
      <div className="mt-6 pt-4 border-t border-[#1e3a1e] text-center">
        <p className="text-[10px] font-mono text-[#2a4a2a] tracking-widest uppercase">
          {isLogin ? (
            <>NO ACCOUNT?{" "}
              <button type="button" onClick={() => { setMode("register"); setError(""); }}
                className="text-[#84cc16]/50 hover:text-[#84cc16] transition-colors">SIGN UP FREE</button>
            </>
          ) : (
            <>HAVE AN ACCOUNT?{" "}
              <button type="button" onClick={() => { setMode("login"); setError(""); }}
                className="text-[#84cc16]/50 hover:text-[#84cc16] transition-colors">SIGN IN</button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}

// ─── Showcase helpers ─────────────────────────────────────────────────────────

const REVEAL_STYLE = (visible: boolean, delay = 0): React.CSSProperties => ({
  opacity: visible ? 1 : 0,
  transform: visible ? "none" : "translateY(28px)",
  transition: `opacity 0.7s ease ${delay}s, transform 0.7s cubic-bezier(0.22,1,0.36,1) ${delay}s`,
});

// ─── Section 1: Voice AI ──────────────────────────────────────────────────────

function ShowcaseVoiceAI() {
  const { ref, visible } = useReveal(0.05);
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12 border-b border-[var(--bmg-green-border)]/20"
      style={REVEAL_STYLE(visible)}>
      <SectionLabel className="mb-3">Voice AI Interface</SectionLabel>
      <h2 className="text-3xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        Talk to your portfolio.<br />
        <span style={{ color: "var(--bmg-green)" }}>Get answers instantly.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-8 max-w-sm leading-relaxed">
        Natural language commands. Full portfolio awareness.
        Control bots, query positions, and get risk alerts — all by voice.
      </p>
      <div className="flex gap-2 flex-wrap mb-10">
        {["Natural language", "Portfolio awareness", "Bot control", "Risk alerts"].map(tag => (
          <span key={tag} className="text-[10px] font-mono px-2.5 py-1 rounded-full bg-[var(--bmg-green-dim)] text-[var(--bmg-green)] border border-[var(--bmg-green-border)]">{tag}</span>
        ))}
      </div>
      <VoiceDemo />
      <p className="text-[var(--bmg-text-label)] text-xs font-mono mt-8">↑ 30-second demo · replays automatically</p>
    </div>
  );
}

// ─── Section 2: Strategy Lab Hub ─────────────────────────────────────────────

const LAB_FEATURES = [
  {
    icon: <Search className="w-4 h-4" />,
    label: "STRATEGY SCOUT",
    c: { bg: "rgba(139,92,246,0.2)", text: "#c4b5fd" },
    desc: "AI-scored trade setups with entry, stop, and target — delivered before the open.",
    stat: "87% avg confidence",
  },
  {
    icon: <Hammer className="w-4 h-4" />,
    label: "THE FORGE",
    c: { bg: "rgba(245,158,11,0.2)", text: "#fcd34d" },
    desc: "Build custom trading bots in a guided wizard. No code. Deploy in under 5 minutes.",
    stat: "30+ configurable params",
  },
  {
    icon: <Bot className="w-4 h-4" />,
    label: "SMART BOTS",
    c: { bg: "rgba(14,165,233,0.2)", text: "#7dd3fc" },
    desc: "12 pre-built strategies across stocks, crypto, and quant — live paper trading 24/7.",
    stat: "12 active strategies",
  },
  {
    icon: <Trophy className="w-4 h-4" />,
    label: "LEADERBOARD",
    c: { bg: "rgba(16,185,129,0.2)", text: "#6ee7b7" },
    desc: "Real-time dollar-weighted strategy rankings. Know what's working before you allocate.",
    stat: "Dollar-weighted returns",
  },
];

function ShowcaseStrategyLabHub() {
  const { ref, visible } = useReveal();
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12 border-b border-[var(--bmg-green-border)]/20"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">Strategy Lab</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        One hub. Every edge.<br />
        <span style={{ color: "var(--bmg-green)" }}>Scout → Build → Deploy → Rank.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-8 max-w-sm leading-relaxed">
        Strategy Lab is the full lifecycle — from AI-scored signals to custom bot deployment
        and live performance rankings.
      </p>
      <div className="grid grid-cols-2 gap-3">
        {LAB_FEATURES.map(f => (
          <BMGCard key={f.label} padding="sm" className="flex flex-col gap-2.5">
            <div className="flex items-center gap-2">
              <span className="p-1.5 rounded-lg flex-shrink-0" style={{ background: f.c.bg, color: f.c.text }}>{f.icon}</span>
              <span className="text-[9px] font-bold tracking-widest font-mono" style={{ color: f.c.text }}>{f.label}</span>
            </div>
            <p className="text-[11px] text-[var(--bmg-text-muted)] leading-snug">{f.desc}</p>
            <div className="pt-1 border-t border-[var(--bmg-green-border)]/30">
              <span className="text-[9px] font-mono" style={{ color: f.c.text }}>{f.stat}</span>
            </div>
          </BMGCard>
        ))}
      </div>
    </div>
  );
}

// ─── Section 3: Strategy Scout demo ──────────────────────────────────────────

const SCOUT_SIGNALS = [
  { sym: "NVDA",     side: "LONG",  strat: "Momentum Breakout", entry: "$145.20", stop: "$141.80", target: "$152.40", rr: "2.1:1", conf: 87, cat: "stocks",  explain: "NVDA is clearing 3-week consolidation above the $145 supply zone on above-average volume. Earnings catalyst blackout lifts Friday — risk/reward favors continuation." },
  { sym: "BTC/USD",  side: "LONG",  strat: "BTC Trend Follow",  entry: "$99,240", stop: "$96,800", target: "$105,000", rr: "2.4:1", conf: 81, cat: "crypto", explain: "Bitcoin reclaimed the 21-day EMA after a 3-day pullback. On-chain accumulation signal active. Next resistance cluster at $105K." },
  { sym: "SPY",      side: "SHORT", strat: "Macro Hedge",       entry: "$592.10", stop: "$596.50", target: "$582.00", rr: "2.3:1", conf: 73, cat: "stocks",  explain: "Bearish divergence on daily RSI while VIX term structure inverted. Hedge position ahead of CPI print Thursday." },
];

const SCOUT_CAT: Record<string, { bg: string; text: string }> = {
  stocks: { bg: "rgba(14,165,233,0.2)",  text: "#7dd3fc" },
  crypto: { bg: "rgba(245,158,11,0.2)",  text: "#fcd34d" },
};

function ShowcaseScoutDemo() {
  const { ref, visible } = useReveal();
  const [active, setActive] = useState(0);
  const sig = SCOUT_SIGNALS[active];
  const isLong = sig.side === "LONG";

  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12 border-b border-[var(--bmg-green-border)]/20"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">Strategy Scout</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        AI scans the tape.<br />
        <span style={{ color: "var(--bmg-green)" }}>You get the setups.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-6 max-w-sm leading-relaxed">
        Scout scores 500+ symbols every 15 minutes and surfaces the highest-conviction
        setups with entry, stop, target, and an AI trade briefing.
      </p>
      {/* Signal selector */}
      <div className="flex gap-2 mb-4">
        {SCOUT_SIGNALS.map((s, i) => (
          <button key={i} onClick={() => setActive(i)}
            className="text-[10px] font-mono px-2.5 py-1 rounded-full border transition-all"
            style={{
              background: i === active ? "rgba(132,204,22,0.15)" : "transparent",
              borderColor: i === active ? "#84cc16" : "rgba(132,204,22,0.2)",
              color: i === active ? "#84cc16" : "var(--bmg-text-muted)",
            }}>
            {s.sym}
          </button>
        ))}
      </div>
      {/* Signal card */}
      <BMGCard padding="sm" className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-base font-bold text-[var(--bmg-text)]">{sig.sym}</span>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded"
              style={{ background: isLong ? "rgba(132,204,22,0.15)" : "rgba(239,68,68,0.15)", color: isLong ? "var(--bmg-green)" : "var(--bmg-red)" }}>
              {sig.side}
            </span>
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded"
              style={{ background: SCOUT_CAT[sig.cat].bg, color: SCOUT_CAT[sig.cat].text }}>
              {sig.strat}
            </span>
          </div>
          <span className="text-[10px] font-mono font-bold" style={{ color: sig.conf >= 80 ? "var(--bmg-green)" : "#fcd34d" }}>
            {sig.conf}% conf
          </span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[["Entry", sig.entry, false], ["Stop", sig.stop, false], ["Target", sig.target, true]].map(([k, v, green]) => (
            <div key={String(k)} className="bg-[var(--bmg-bg-input)] rounded-lg p-2 text-center border border-[var(--bmg-green-border)]/20">
              <p className="text-[9px] text-[var(--bmg-text-label)] font-mono uppercase tracking-wider mb-0.5">{k}</p>
              <p className="text-[11px] font-mono font-semibold" style={{ color: green ? "var(--bmg-green)" : "var(--bmg-text)" }}>{v}</p>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono text-[var(--bmg-text-muted)]">
          <span><Target className="w-3 h-3 inline mr-1" style={{ color: "var(--bmg-green)" }} />R:R {sig.rr}</span>
          <span><ShieldCheck className="w-3 h-3 inline mr-1 text-yellow-400" />Risk-defined</span>
        </div>
        <div className="border-t border-[var(--bmg-green-border)]/20 pt-2">
          <p className="text-[9px] font-mono text-[var(--bmg-green)]/60 mb-1 uppercase tracking-widest">⚒ AI Brief</p>
          <p className="text-[11px] text-[var(--bmg-text-muted)] leading-relaxed">{sig.explain}</p>
        </div>
      </BMGCard>
    </div>
  );
}

// ─── Section 4: Discord Signals ───────────────────────────────────────────────

const SIGNALS = [
  { time: "09:31", bot: "BTC_MOMENTUM", action: "LONG",  sym: "BTC/USD", price: "$99,240", conf: "0.83", col: "var(--bmg-green)" },
  { time: "09:34", bot: "ETH_SWING",    action: "LONG",  sym: "ETH/USD", price: "$3,821",  conf: "0.76", col: "var(--bmg-green)" },
  { time: "09:41", bot: "STOCKS_SWING", action: "LONG",  sym: "NVDA",    price: "$145.20", conf: "0.91", col: "var(--bmg-green)" },
  { time: "10:02", bot: "STOCKS_SWING", action: "ADD",   sym: "NVDA",    price: "$145.80", conf: "0.91", col: "#fcd34d" },
  { time: "10:15", bot: "QUANT_MEAN",   action: "SHORT", sym: "SPY",     price: "$592.10", conf: "0.68", col: "var(--bmg-red)" },
  { time: "10:47", bot: "ETH_SWING",    action: "CLOSE", sym: "ETH/USD", price: "$3,858",  conf: "—",    col: "#7dd3fc" },
  { time: "11:03", bot: "BTC_MOMENTUM", action: "SCALE", sym: "BTC/USD", price: "$99,890", conf: "0.83", col: "#fcd34d" },
  { time: "11:22", bot: "THETA_DECAY",  action: "SELL",  sym: "SPX PUT", price: "$14.20",  conf: "0.77", col: "var(--bmg-red)" },
];

function ShowcaseDiscordSignals() {
  const { ref, visible } = useReveal();
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12 border-b border-[var(--bmg-green-border)]/20"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">Signal Feed</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        Every trade, audited.<br />
        <span style={{ color: "var(--bmg-green)" }}>Streamed to Discord.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-8 max-w-sm leading-relaxed">
        All signals, fills, and bot events flow into a private Discord server.
        Full audit trail, instant mobile alerts — no dashboard required.
      </p>
      <BMGCard padding="sm" className="overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--bmg-green-border)]/30 mb-1">
          <span className="w-2 h-2 rounded-full bg-[var(--bmg-green)] animate-pulse" />
          <span className="text-[10px] font-mono text-[var(--bmg-text-muted)]">#bmg-signals · live</span>
          <span className="ml-auto text-[10px] font-mono text-[var(--bmg-text-label)]">today</span>
        </div>
        {SIGNALS.map((s, i) => (
          <div key={i} className="flex items-center gap-2 px-3 py-1.5 hover:bg-[var(--bmg-green-dim)]/30 transition-colors text-[11px] font-mono">
            <span className="text-[var(--bmg-text-label)] w-10 flex-shrink-0">{s.time}</span>
            <span className="font-bold px-1.5 py-0.5 rounded text-[9px] flex-shrink-0"
              style={{ background: `color-mix(in srgb, ${s.col} 20%, transparent)`, color: s.col }}>{s.action}</span>
            <span className="text-[var(--bmg-text)] font-semibold">{s.sym}</span>
            <span className="text-[var(--bmg-text-muted)]">@ {s.price}</span>
            {s.conf !== "—" && <span className="ml-auto text-[var(--bmg-text-label)]">conf {s.conf}</span>}
          </div>
        ))}
      </BMGCard>
    </div>
  );
}

// ─── Section 5: The Forge wizard demo ────────────────────────────────────────

const FORGE_STEPS = [
  {
    num: "01",
    label: "Pick a base strategy",
    content: (
      <div className="grid grid-cols-2 gap-2 mt-2">
        {[
          { id: "mb", name: "Momentum Breakout", active: true },
          { id: "mr", name: "Mean Reversion",    active: false },
          { id: "tf", name: "Trend Follow",      active: false },
          { id: "ee", name: "Earnings Edge",     active: false },
        ].map(s => (
          <div key={s.id} className="rounded-lg px-2.5 py-2 text-[10px] font-mono border transition-all cursor-default"
            style={{
              background: s.active ? "rgba(132,204,22,0.12)" : "var(--bmg-bg-input)",
              borderColor: s.active ? "#84cc16" : "rgba(132,204,22,0.15)",
              color: s.active ? "#84cc16" : "var(--bmg-text-muted)",
            }}>
            {s.active && <span className="text-[8px] mr-1">✓</span>}{s.name}
          </div>
        ))}
      </div>
    ),
  },
  {
    num: "02",
    label: "Configure parameters",
    content: (
      <div className="mt-2 space-y-2">
        <div className="flex items-center justify-between text-[10px] font-mono">
          <span className="text-[var(--bmg-text-muted)]">Risk per trade</span>
          <div className="flex gap-1">
            {["0.5%","1%","2%"].map(v => (
              <span key={v} className="px-2 py-0.5 rounded border text-[9px]"
                style={{ background: v === "1%" ? "rgba(132,204,22,0.15)" : "transparent", borderColor: v === "1%" ? "#84cc16" : "rgba(132,204,22,0.2)", color: v === "1%" ? "#84cc16" : "var(--bmg-text-label)" }}>
                {v}
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between text-[10px] font-mono">
          <span className="text-[var(--bmg-text-muted)]">Timeframe</span>
          <div className="flex gap-1">
            {["5m","15m","1h","4h"].map(v => (
              <span key={v} className="px-2 py-0.5 rounded border text-[9px]"
                style={{ background: v === "15m" ? "rgba(132,204,22,0.15)" : "transparent", borderColor: v === "15m" ? "#84cc16" : "rgba(132,204,22,0.2)", color: v === "15m" ? "#84cc16" : "var(--bmg-text-label)" }}>
                {v}
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between text-[10px] font-mono">
          <span className="text-[var(--bmg-text-muted)]">Universe</span>
          <span className="text-[var(--bmg-green)] text-[9px]">Stocks + ETFs</span>
        </div>
      </div>
    ),
  },
  {
    num: "03",
    label: "Deploy bot",
    content: (
      <div className="mt-2 rounded-lg border border-[var(--bmg-green)] bg-[rgba(132,204,22,0.07)] p-3 flex items-start gap-3">
        <div className="w-6 h-6 rounded-full bg-[var(--bmg-green)] flex items-center justify-center flex-shrink-0 mt-0.5">
          <span className="text-black text-xs font-bold">✓</span>
        </div>
        <div>
          <p className="text-[10px] font-mono font-bold text-[var(--bmg-green)]">NVDA_MOMENTUM_v1 created</p>
          <p className="text-[9px] text-[var(--bmg-text-muted)] mt-0.5">Paper trading · $10,000 allocated · Signals streaming</p>
        </div>
      </div>
    ),
  },
];

function ShowcaseForgeDemo() {
  const { ref, visible } = useReveal();
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12 border-b border-[var(--bmg-green-border)]/20"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">The Forge</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        Build your bot.<br />
        <span style={{ color: "var(--bmg-green)" }}>No code. 5 minutes.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-8 max-w-sm leading-relaxed">
        A guided wizard walks you through picking a strategy, tuning parameters,
        and deploying a live paper-trading bot — all without touching code.
      </p>
      <div className="space-y-3">
        {FORGE_STEPS.map((step, i) => (
          <div key={step.num} style={{ opacity: i < 2 ? 0.7 : 1 }}>
          <BMGCard padding="sm"
            className={i === 2 ? "border-[rgba(132,204,22,0.5)]" : ""}>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono font-bold" style={{ color: i === 2 ? "var(--bmg-green)" : "var(--bmg-text-label)" }}>
                {step.num}
              </span>
              <span className="text-[11px] font-mono font-semibold text-[var(--bmg-text)]">{step.label}</span>
              {i < 2 && <span className="ml-auto text-[9px] font-mono text-[var(--bmg-green)]">✓</span>}
            </div>
            {step.content}
          </BMGCard>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Section 6: Strategy Leaderboard preview ─────────────────────────────────

const LEADERBOARD_ROWS = [
  { rank: 1, name: "Momentum Breakout", cat: "stocks",  ret: "+31.4%", pnl: "+$9,420", wr: "72%", trades: 58, bots: 4 },
  { rank: 2, name: "BTC Trend Follow",  cat: "crypto",  ret: "+28.7%", pnl: "+$7,180", wr: "68%", trades: 41, bots: 2 },
  { rank: 3, name: "Mean Reversion",    cat: "quant",   ret: "+19.2%", pnl: "+$4,800", wr: "61%", trades: 87, bots: 3 },
  { rank: 4, name: "Earnings Edge",     cat: "stocks",  ret: "+17.8%", pnl: "+$3,560", wr: "65%", trades: 29, bots: 2 },
  { rank: 5, name: "ETH Swing",         cat: "crypto",  ret: "+14.1%", pnl: "+$2,820", wr: "58%", trades: 52, bots: 2 },
];

const LB_CAT: Record<string, { bg: string; text: string }> = {
  stocks: { bg: "rgba(14,165,233,0.2)",  text: "#7dd3fc" },
  crypto: { bg: "rgba(245,158,11,0.2)",  text: "#fcd34d" },
  quant:  { bg: "rgba(139,92,246,0.2)",  text: "#c4b5fd" },
};

function ShowcaseLeaderboardPreview() {
  const { ref, visible } = useReveal();
  const [period, setPeriod] = useState<"7d"|"30d"|"90d">("30d");
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">Strategy Leaderboard</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        Know what's working.<br />
        <span style={{ color: "var(--bmg-green)" }}>Dollar-weighted, always honest.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-6 max-w-sm leading-relaxed">
        Every strategy ranked by actual $ P&L across all bots and users.
        No cherry-picked win rates. Dollar-weighted returns show what's making money.
      </p>
      {/* Period selector */}
      <div className="flex gap-2 mb-4">
        {(["7d","30d","90d"] as const).map(p => (
          <button key={p} onClick={() => setPeriod(p)}
            className="text-[10px] font-mono px-3 py-1 rounded-full border transition-all"
            style={{
              background: period === p ? "rgba(132,204,22,0.15)" : "transparent",
              borderColor: period === p ? "#84cc16" : "rgba(132,204,22,0.2)",
              color: period === p ? "#84cc16" : "var(--bmg-text-muted)",
            }}>
            {p}
          </button>
        ))}
      </div>
      <BMGCard padding="sm" className="overflow-hidden">
        {/* Header */}
        <div className="grid grid-cols-[24px_1fr_56px_40px] gap-2 px-2 pb-2 border-b border-[var(--bmg-green-border)]/20">
          {["#","Strategy","Return","W/R"].map(h => (
            <span key={h} className="text-[9px] font-mono text-[var(--bmg-text-label)] uppercase tracking-widest">{h}</span>
          ))}
        </div>
        {/* Rows */}
        {LEADERBOARD_ROWS.map(row => (
          <div key={row.rank} className="grid grid-cols-[24px_1fr_56px_40px] gap-2 items-center px-2 py-2 border-b border-[var(--bmg-green-border)]/10 last:border-0">
            <span className="text-[10px] font-mono text-[var(--bmg-text-label)]">{row.rank}</span>
            <div className="min-w-0">
              <p className="text-[11px] font-mono font-semibold text-[var(--bmg-text)] truncate">{row.name}</p>
              <span className="text-[8px] font-mono px-1.5 py-0.5 rounded"
                style={{ background: LB_CAT[row.cat].bg, color: LB_CAT[row.cat].text }}>
                {row.cat}
              </span>
            </div>
            <span className="text-[11px] font-mono font-bold" style={{ color: "var(--bmg-green)" }}>{row.ret}</span>
            <span className="text-[10px] font-mono text-[var(--bmg-text-muted)]">{row.wr}</span>
          </div>
        ))}
      </BMGCard>
    </div>
  );
}

// ─── Auth card (reusable) ─────────────────────────────────────────────────────

function AuthCard() {
  return (
    <div className="relative z-10 w-full px-8 xl:px-10 py-12">
      <motion.div
        initial={{ opacity: 0, scale: 0.94 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        className="mb-8 text-center"
      >
        <h1 className="text-2xl font-black tracking-[0.15em] uppercase"
          style={{ color: "#84cc16", textShadow: "0 0 30px rgba(132,204,22,0.4), 0 0 60px rgba(132,204,22,0.15)" }}>
          BMG CAPITAL
        </h1>
        <p className="mt-1.5 text-[10px] font-mono tracking-[0.4em] text-[#84cc16]/30 uppercase">
          Quantitative Trading System
        </p>
      </motion.div>
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="relative p-8 rounded-sm" style={{ background: "rgba(2,11,2,0.85)", backdropFilter: "blur(12px)" }}>
          <CornerBrackets />
          <LoginForm />
        </div>
      </motion.div>
    </div>
  );
}

// ─── Showcase login page ──────────────────────────────────────────────────────

function ShowcaseLoginPage() {
  return (
    <div className="bg-[#020b02]">
      {/* Mobile: simple centered layout */}
      <div className="lg:hidden relative min-h-screen overflow-hidden">
        <GridBg /><TickerBg />
        <div className="relative z-10 flex items-center justify-between px-6 py-4 border-b border-[#0f1a0f]">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-[#84cc16] animate-pulse" />
            <span className="text-[10px] font-mono text-[#84cc16]/40 tracking-[0.3em] uppercase">BMG Capital</span>
          </div>
        </div>
        <div className="relative z-10 flex flex-col items-center justify-center min-h-[calc(100vh-56px)] px-4 py-12">
          <div className="mb-8 text-center">
            <h1 className="text-3xl font-black tracking-[0.15em] uppercase"
              style={{ color: "#84cc16", textShadow: "0 0 30px rgba(132,204,22,0.4)" }}>
              BMG CAPITAL
            </h1>
            <p className="mt-2 text-[10px] font-mono tracking-[0.4em] text-[#84cc16]/30 uppercase">Quantitative Trading System</p>
          </div>
          <div className="w-full max-w-sm">
            <div className="relative p-8 rounded-sm" style={{ background: "rgba(2,11,2,0.85)", backdropFilter: "blur(12px)" }}>
              <CornerBrackets /><LoginForm />
            </div>
          </div>
        </div>
      </div>

      {/* Desktop: split layout */}
      <div className="hidden lg:flex" style={{ height: "100vh", overflow: "hidden" }}>
        {/* Left: scrollable showcase */}
        <div className="flex-1 relative overflow-y-auto">
          <div className="sticky top-0 z-20 flex items-center gap-2 px-12 py-4 border-b border-[var(--bmg-green-border)]/20 bg-[#020b02]/90 backdrop-blur-sm">
            <span className="w-2 h-2 rounded-full bg-[var(--bmg-green)] animate-pulse" />
            <span className="text-[10px] font-mono text-[var(--bmg-green)]/60 tracking-[0.3em] uppercase">BMG Capital</span>
            <span className="ml-auto text-[9px] font-mono text-[var(--bmg-text-label)] tracking-widest uppercase hidden xl:block">
              Paper trading only · not financial advice
            </span>
          </div>
          <div className="relative">
            <GridBg />
            <div className="relative z-10">
              <ShowcaseStrategyLabHub />
              <ShowcaseVoiceAI />
              <ShowcaseScoutDemo />
              <ShowcaseForgeDemo />
              <ShowcaseLeaderboardPreview />
              <ShowcaseDiscordSignals />
            </div>
          </div>
          <TickerBg />
        </div>

        {/* Right: sticky auth */}
        <div className="w-[400px] xl:w-[440px] flex-shrink-0 relative border-l border-[var(--bmg-green-border)]/30 flex flex-col items-center justify-center overflow-y-auto">
          <GridBg /><TickerBg />
          <AuthCard />
        </div>
      </div>
    </div>
  );
}

// ─── Simple login page (default) ─────────────────────────────────────────────

function SimpleLoginPage() {
  return (
    <div className="relative min-h-screen bg-[#020b02] overflow-hidden">
      <GridBg /><TickerBg />
      <div className="relative z-10 flex items-center justify-between px-6 py-4 border-b border-[#0f1a0f]">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[#84cc16] animate-pulse" />
          <span className="text-[10px] font-mono text-[#84cc16]/40 tracking-[0.3em] uppercase">BMG Capital</span>
        </div>
        <span className="text-[9px] font-mono text-[#1e3a1e] tracking-widest uppercase hidden sm:block">
          Paper trading only — not financial advice
        </span>
      </div>
      <div className="relative z-10 flex flex-col items-center justify-center min-h-[calc(100vh-56px)] px-4 py-12">
        <motion.div
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="mb-10 text-center"
        >
          <h1 className="text-3xl sm:text-4xl font-black tracking-[0.15em] uppercase"
            style={{ color: "#84cc16", textShadow: "0 0 30px rgba(132,204,22,0.4), 0 0 60px rgba(132,204,22,0.15)" }}>
            BMG CAPITAL
          </h1>
          <p className="mt-2 text-[10px] font-mono tracking-[0.4em] text-[#84cc16]/30 uppercase">Quantitative Trading System</p>
        </motion.div>
        <div className="flex flex-col lg:flex-row items-center gap-16 w-full max-w-5xl">
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.7, delay: 0.2 }}
            className="flex-1 flex flex-col gap-4"
          >
            <div className="hidden lg:block">
              <p className="text-xs font-mono text-[#84cc16]/40 tracking-widest uppercase mb-1">Voice AI Interface</p>
              <p className="text-slate-500 text-sm">Ask your AI anything about your portfolio — in plain English.</p>
            </div>
            <div className="hidden lg:block"><VoiceDemo /></div>
            <p className="hidden lg:block text-slate-700 text-xs font-mono text-center">↑ 30-second demo · replays automatically</p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
            className="w-full lg:max-w-sm flex-shrink-0"
          >
            <div className="relative p-8 rounded-sm" style={{ background: "rgba(2,11,2,0.85)", backdropFilter: "blur(12px)" }}>
              <CornerBrackets />
              <LoginForm />
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

// ─── Default export ───────────────────────────────────────────────────────────

export default function LoginPage() {
  return ENABLE_SHOWCASE ? <ShowcaseLoginPage /> : <SimpleLoginPage />;
}
