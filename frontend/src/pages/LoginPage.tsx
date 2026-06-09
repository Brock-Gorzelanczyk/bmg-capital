import { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Zap, Eye, EyeOff, TrendingUp, Cpu, BarChart2 } from "lucide-react";
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

// ─── Section 2: Capital Pods ──────────────────────────────────────────────────

const PODS = [
  { icon: <Cpu className="w-4 h-4" />, label: "QUANT",   c: { bg: "rgba(139,92,246,0.2)",  text: "#c4b5fd" }, desc: "Pure factor + mean-reversion. Market-neutral targets.", capital: "$312K", bots: "3 bots", ret: "+18.4%" },
  { icon: <Zap className="w-4 h-4" />, label: "CRYPTO",  c: { bg: "rgba(245,158,11,0.2)",  text: "#fcd34d" }, desc: "24/7 cross-exchange momentum and alpha capture.",       capital: "$248K", bots: "3 bots", ret: "+31.7%" },
  { icon: <TrendingUp className="w-4 h-4" />, label: "STOCKS",  c: { bg: "rgba(14,165,233,0.2)",  text: "#7dd3fc" }, desc: "US equity swing, momentum, and earnings edge.",        capital: "$418K", bots: "3 bots", ret: "+14.2%" },
  { icon: <BarChart2 className="w-4 h-4" />, label: "OPTIONS", c: { bg: "rgba(16,185,129,0.2)",  text: "#6ee7b7" }, desc: "Volatility surface strategies. Theta decay + skew.",    capital: "$188K", bots: "3 bots", ret: "+9.8%"  },
];

function ShowcaseCapitalPods() {
  const { ref, visible } = useReveal();
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12 border-b border-[var(--bmg-green-border)]/20"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">Capital Pods</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        4 isolated pods.<br />
        <span style={{ color: "var(--bmg-green)" }}>Zero cross-contamination.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-8 max-w-sm leading-relaxed">
        Each pod runs its own strategy class with independent risk budgets.
        A drawdown in crypto can't touch your equity pod.
      </p>
      <div className="grid grid-cols-2 gap-3">
        {PODS.map(pod => (
          <BMGCard key={pod.label} padding="sm" className="flex flex-col gap-2.5">
            <div className="flex items-center gap-2">
              <span className="p-1.5 rounded-lg flex-shrink-0" style={{ background: pod.c.bg, color: pod.c.text }}>{pod.icon}</span>
              <span className="text-[10px] font-bold tracking-widest font-mono" style={{ color: pod.c.text }}>{pod.label}</span>
            </div>
            <p className="text-[11px] text-[var(--bmg-text-muted)] leading-snug">{pod.desc}</p>
            <div className="grid grid-cols-3 gap-1 text-center pt-1 border-t border-[var(--bmg-green-border)]/30">
              {(["Capital", "Bots", "Return"] as const).map((k, ki) => (
                <div key={k}>
                  <p className="text-[9px] text-[var(--bmg-text-label)] font-mono uppercase tracking-wider">{k}</p>
                  <p className="text-[11px] font-mono" style={{ color: ki === 2 ? "var(--bmg-green)" : "var(--bmg-text)" }}>
                    {ki === 0 ? pod.capital : ki === 1 ? pod.bots : pod.ret}
                  </p>
                </div>
              ))}
            </div>
          </BMGCard>
        ))}
      </div>
    </div>
  );
}

// ─── Section 3: 12 Bot Strategies ────────────────────────────────────────────

const BOTS = [
  { id: "qmr", cat: "quant",   label: "Mean Reversion",  status: "active"   },
  { id: "qfm", cat: "quant",   label: "Factor Momentum", status: "active"   },
  { id: "qsa", cat: "quant",   label: "Stat Arb",        status: "paused"   },
  { id: "cbm", cat: "crypto",  label: "BTC Momentum",    status: "active"   },
  { id: "ces", cat: "crypto",  label: "ETH Swing",       status: "active"   },
  { id: "cab", cat: "crypto",  label: "Alt Breakout",    status: "active"   },
  { id: "ssc", cat: "stocks",  label: "Swing Classic",   status: "active"   },
  { id: "sef", cat: "stocks",  label: "Earnings Fade",   status: "active"   },
  { id: "ssr", cat: "stocks",  label: "Sector Rotate",   status: "disabled" },
  { id: "ovl", cat: "options", label: "VIX Long",        status: "active"   },
  { id: "otd", cat: "options", label: "Theta Decay",     status: "active"   },
  { id: "osa", cat: "options", label: "Skew Arb",        status: "paused"   },
];
const CAT_BG:   Record<string, string> = { quant: "rgba(139,92,246,0.2)", crypto: "rgba(245,158,11,0.2)", stocks: "rgba(14,165,233,0.2)", options: "rgba(16,185,129,0.2)" };
const CAT_TEXT: Record<string, string> = { quant: "#c4b5fd", crypto: "#fcd34d", stocks: "#7dd3fc", options: "#6ee7b7" };

function ShowcaseBotStrategies() {
  const { ref, visible } = useReveal();
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12 border-b border-[var(--bmg-green-border)]/20"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">Bot Strategies</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        12 independent strategies.<br />
        <span style={{ color: "var(--bmg-green)" }}>Zero human override needed.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-8 max-w-sm leading-relaxed">
        YAML-configured risk rules. Position sizing, deployment targets, and confidence
        thresholds are hot-swappable without code deploys.
      </p>
      <div className="grid grid-cols-3 gap-2">
        {BOTS.map(bot => (
          <BMGCard key={bot.id} padding="sm" className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${bot.status === "active" ? "bg-[var(--bmg-green)]" : bot.status === "paused" ? "bg-yellow-400" : "bg-red-500"}`} />
              <span className="text-[10px] font-mono font-semibold text-[var(--bmg-text)] leading-tight truncate">{bot.label}</span>
            </div>
            <span className="text-[9px] font-bold tracking-widest font-mono px-1.5 py-0.5 rounded self-start"
              style={{ background: CAT_BG[bot.cat], color: CAT_TEXT[bot.cat] }}>
              {bot.cat.toUpperCase()}
            </span>
          </BMGCard>
        ))}
      </div>
      <div className="flex gap-4 mt-4 text-xs font-mono text-[var(--bmg-text-muted)]">
        <span><span style={{ color: "var(--bmg-green)" }}>●</span> {BOTS.filter(b => b.status === "active").length} active</span>
        <span><span className="text-yellow-400">●</span> {BOTS.filter(b => b.status === "paused").length} paused</span>
        <span><span className="text-red-500">●</span> {BOTS.filter(b => b.status === "disabled").length} disabled</span>
      </div>
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

// ─── Section 5: Backtest P&L ──────────────────────────────────────────────────

const EQUITY_DATA = [0, 4, 11, 7, 16, 22, 17, 28, 35, 29, 42, 51, 45, 58, 67, 61, 76, 87, 81, 98, 112, 105, 128, 147];

function EquityCurve() {
  const W = 560; const H = 100; const P = 6;
  const maxV = 147;
  const pts = EQUITY_DATA.map((v, i) => ({
    x: P + (i / (EQUITY_DATA.length - 1)) * (W - P * 2),
    y: H - P - (v / maxV) * (H - P * 2),
  }));
  const line = pts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)} ${pts.map(p => `L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")} L${pts[pts.length-1].x.toFixed(1)},${H} L${pts[0].x.toFixed(1)},${H} Z`;
  const last = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#4ade80" stopOpacity="0.25" />
          <stop offset="100%" stopColor="#4ade80" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#eq-fill)" />
      <polyline points={line} fill="none" stroke="#4ade80" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last.x.toFixed(1)} cy={last.y.toFixed(1)} r="3" fill="#4ade80" />
    </svg>
  );
}

function ShowcaseBacktestPnL() {
  const { ref, visible } = useReveal();
  const stats: [string, string, boolean][] = [
    ["Total return",  "+147.3%", true],
    ["Sharpe ratio",  "2.14",    false],
    ["Max drawdown",  "−8.2%",   false],
    ["Win rate",      "67.4%",   false],
    ["Profit factor", "2.31",    false],
    ["Avg trade",     "+0.61%",  true],
  ];
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12 border-b border-[var(--bmg-green-border)]/20"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">Backtest Performance</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        Walk-forward validated.<br />
        <span style={{ color: "var(--bmg-green)" }}>Out-of-sample tested.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-6 max-w-sm leading-relaxed">
        All strategies backtested on 3+ years of data with realistic slippage,
        commissions, and held-out test periods.
      </p>
      <BMGCard padding="sm" className="mb-4">
        <div className="flex items-center justify-between px-1 pb-2">
          <SectionLabel className="text-[9px]">Cumulative P&L · 24 months</SectionLabel>
          <span className="text-[10px] font-mono" style={{ color: "var(--bmg-green)" }}>+147.3%</span>
        </div>
        <div className="h-24"><EquityCurve /></div>
        <div className="flex items-center justify-between px-1 pt-1 text-[9px] font-mono text-[var(--bmg-text-label)]">
          <span>Jan 2023</span><span>Jan 2024</span><span>Dec 2024</span>
        </div>
      </BMGCard>
      <div className="grid grid-cols-3 gap-2">
        {stats.map(([label, val, green]) => (
          <div key={label} className="bg-[var(--bmg-bg-input)] rounded-lg p-2 text-center border border-[var(--bmg-green-border)]/30">
            <p className="text-[9px] text-[var(--bmg-text-label)] font-mono uppercase tracking-wider mb-0.5">{label}</p>
            <p className="text-sm font-mono font-semibold" style={{ color: green ? "var(--bmg-green)" : "var(--bmg-text)" }}>{val}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Section 6: Mission Control ───────────────────────────────────────────────

const POSITIONS = [
  { sym: "BTC/USD", side: "LONG",  entry: "$99,240", size: "$12,400", pnl: "+$840" },
  { sym: "NVDA",    side: "LONG",  entry: "$145.20", size: "$8,200",  pnl: "+$312" },
  { sym: "ETH/USD", side: "LONG",  entry: "$3,821",  size: "$6,800",  pnl: "+$204" },
  { sym: "SPY",     side: "SHORT", entry: "$592.10", size: "$5,100",  pnl: "+$128" },
  { sym: "AAPL",    side: "LONG",  entry: "$214.30", size: "$4,800",  pnl: "+$96"  },
];

function ShowcaseMissionControl() {
  const { ref, visible } = useReveal();
  const kpis: [string, string, boolean][] = [
    ["Portfolio value",  "$1,247,830",       true],
    ["Today's P&L",      "+$5,420 (+0.44%)", true],
    ["Open positions",   "18",               false],
    ["Active bots",      "10 / 12",          false],
  ];
  return (
    <div ref={ref} className="min-h-screen flex flex-col justify-center py-20 px-12"
      style={REVEAL_STYLE(visible, 0.05)}>
      <SectionLabel className="mb-3">Mission Control</SectionLabel>
      <h2 className="text-2xl font-black text-[var(--bmg-text)] mb-3 leading-tight">
        Full portfolio visibility.<br />
        <span style={{ color: "var(--bmg-green)" }}>Real-time, always.</span>
      </h2>
      <p className="text-[var(--bmg-text-muted)] text-sm mb-6 max-w-sm leading-relaxed">
        One dashboard for every position, every bot, every P&L line.
        Daily digest to Discord every morning at market open.
      </p>
      <div className="grid grid-cols-2 gap-2 mb-4">
        {kpis.map(([label, val, green]) => (
          <BMGCard key={label} padding="sm">
            <p className="text-[9px] text-[var(--bmg-text-label)] font-mono uppercase tracking-wider mb-1">{label}</p>
            <p className="text-base font-mono font-bold" style={{ color: green ? "var(--bmg-green)" : "var(--bmg-text)" }}>{val}</p>
          </BMGCard>
        ))}
      </div>
      <BMGCard padding="sm">
        <SectionLabel className="text-[9px] mb-2 px-1">Top Open Positions</SectionLabel>
        <div className="divide-y divide-[var(--bmg-green-border)]/20">
          {POSITIONS.map(p => (
            <div key={p.sym} className="flex items-center gap-2 py-1.5 px-1 text-[11px] font-mono">
              <span className="text-[var(--bmg-text)] font-semibold w-16">{p.sym}</span>
              <span className="text-[9px] px-1.5 py-0.5 rounded" style={{
                background: p.side === "LONG" ? "var(--bmg-green-dim)" : "rgba(239,68,68,0.15)",
                color: p.side === "LONG" ? "var(--bmg-green)" : "var(--bmg-red)",
              }}>{p.side}</span>
              <span className="text-[var(--bmg-text-muted)]">{p.entry}</span>
              <span className="ml-auto text-[var(--bmg-text-muted)]">{p.size}</span>
              <span style={{ color: "var(--bmg-green)" }}>{p.pnl}</span>
            </div>
          ))}
        </div>
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
              <ShowcaseVoiceAI />
              <ShowcaseCapitalPods />
              <ShowcaseBotStrategies />
              <ShowcaseDiscordSignals />
              <ShowcaseBacktestPnL />
              <ShowcaseMissionControl />
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
