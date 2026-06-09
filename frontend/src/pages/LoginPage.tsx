import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Zap, Eye, EyeOff } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { DEMO_EMAIL, DEMO_PASSWORD } from "@/lib/demoMode";

// ─── Background ticker tape ────────────────────────────────────────────────────

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
      <div
        className="flex gap-8 whitespace-nowrap text-[10px] font-mono text-[#84cc16]/18"
        style={{ animation: "bmg-ticker 60s linear infinite" }}
      >
        {items.map((t, i) => (
          <span key={i}>{t}</span>
        ))}
      </div>
    </div>
  );
}

// ─── Grid / radial background ─────────────────────────────────────────────────

function GridBg() {
  return (
    <>
      {/* Grid lines */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(rgba(132,204,22,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(132,204,22,0.04) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }}
      />
      {/* Radial spotlight */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% 20%, rgba(132,204,22,0.07) 0%, transparent 70%)",
        }}
      />
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

// ─── Simulated 30-second voice demo conversation ─────────────────────────────

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
    <div className="relative w-full max-w-md hidden lg:block">
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
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-fadeIn`}>
              {msg.role === "ai" && (
                <div className="w-6 h-6 rounded-full bg-[#84cc16] flex items-center justify-center mr-2 mt-0.5 shrink-0">
                  <Zap className="w-3 h-3 text-black" />
                </div>
              )}
              <div className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-[#1e40af]/40 text-blue-100 rounded-br-sm border border-blue-500/20"
                  : "bg-[#84cc16]/8 text-slate-200 rounded-bl-sm border-l-2 border-[#84cc16]/60"
              }`}>
                {msg.text}
              </div>
              {msg.role === "user" && (
                <div className="w-6 h-6 rounded-full bg-[#1e40af] flex items-center justify-center ml-2 mt-0.5 shrink-0">
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
      <div className="absolute -bottom-3 -left-3 bg-[#0a0f1e] border border-blue-500/30 rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-blue-400 text-xs font-bold">8 bots · paper only</span>
      </div>
    </div>
  );
}

// ─── Auth form (new sci-fi input style) ───────────────────────────────────────

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
      <label className="block text-[10px] font-mono tracking-[0.2em] uppercase text-[#84cc16]/60 mb-1.5">
        {label}
      </label>
      <div className="relative group">
        <input
          type={type}
          value={value}
          onChange={e => onChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          autoComplete={autoComplete}
          placeholder={placeholder}
          className="w-full bg-transparent border-0 border-b text-white text-sm py-2 pr-8 outline-none placeholder-[#2a3a2a] transition-all duration-300"
          style={{
            borderBottomColor: focused ? "#84cc16" : "#1e3a1e",
            boxShadow: focused ? "0 1px 0 0 rgba(132,204,22,0.6)" : "none",
          }}
        />
        {/* Scanline shimmer when focused */}
        {focused && (
          <div
            className="absolute inset-0 pointer-events-none overflow-hidden"
            style={{ borderBottom: "1px solid transparent" }}
          >
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
    setLoading(true);
    setScanning(true);
    // Brief scanning animation before redirect
    await new Promise(r => setTimeout(r, 900));
    try {
      if (mode === "login") {
        await login(email, password);
        navigate("/");
      } else {
        await register(email, username, password);
        navigate("/");
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(detail ?? "Authentication failed. Try again.");
      setScanning(false);
    } finally {
      setLoading(false);
    }
  };

  const handleTryDemo = async () => {
    setError("");
    setLoading(true);
    setScanning(true);
    await new Promise(r => setTimeout(r, 700));
    try {
      await login(DEMO_EMAIL, DEMO_PASSWORD);
      navigate("/");
    } catch {
      setError("Demo account unavailable. Please create a free account.");
      setScanning(false);
    } finally {
      setLoading(false);
    }
  };

  const isLogin = mode === "login";

  return (
    <div className="w-full">
      {/* Mode indicator */}
      <p className="text-[10px] font-mono tracking-[0.3em] text-[#84cc16]/40 mb-6 uppercase">
        {isLogin ? "// AUTHENTICATE" : "// NEW ACCOUNT"}
      </p>

      <form onSubmit={handleSubmit} className="space-y-5">
        <AuthField
          label="Email"
          type={isLogin ? "text" : "email"}
          value={email}
          onChange={setEmail}
          autoComplete="username"
          placeholder={isLogin ? "username or email" : "you@example.com"}
        />

        {!isLogin && (
          <AuthField
            label="Username"
            type="text"
            value={username}
            onChange={setUsername}
            autoComplete="username"
            placeholder="your_username"
          />
        )}

        <AuthField
          label="Password"
          type={showPassword ? "text" : "password"}
          value={password}
          onChange={setPassword}
          autoComplete={isLogin ? "current-password" : "new-password"}
          placeholder="••••••••"
        >
          <button
            type="button"
            onClick={() => setShowPassword(v => !v)}
            tabIndex={-1}
            className="absolute right-0 top-1/2 -translate-y-1/2 text-[#2a4a2a] hover:text-[#84cc16] transition-colors"
          >
            {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </AuthField>

        {!isLogin && (
          <AuthField
            label="Confirm Password"
            type={showConfirm ? "text" : "password"}
            value={confirm}
            onChange={setConfirm}
            autoComplete="new-password"
            placeholder="••••••••"
          >
            <button
              type="button"
              onClick={() => setShowConfirm(v => !v)}
              tabIndex={-1}
              className="absolute right-0 top-1/2 -translate-y-1/2 text-[#2a4a2a] hover:text-[#84cc16] transition-colors"
            >
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

        {/* Error */}
        <AnimatePresence>
          {error && (
            <motion.p
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="text-xs font-mono text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2"
            >
              {error}
            </motion.p>
          )}
        </AnimatePresence>

        {/* Submit button */}
        <button
          type="submit"
          disabled={loading}
          className="relative w-full overflow-hidden rounded border border-[#84cc16]/40 text-sm font-mono tracking-[0.2em] uppercase py-3 transition-all duration-300 disabled:opacity-50"
          style={{
            background: scanning
              ? "rgba(132,204,22,0.15)"
              : "linear-gradient(135deg, rgba(132,204,22,0.1) 0%, rgba(132,204,22,0.05) 100%)",
            color: "#84cc16",
            boxShadow: "0 0 20px rgba(132,204,22,0.15), inset 0 1px 0 rgba(132,204,22,0.1)",
          }}
        >
          {/* Scanning sweep animation */}
          {scanning && (
            <div
              className="absolute inset-0 pointer-events-none"
              style={{ animation: "bmg-scan-btn 1s linear infinite" }}
            >
              <div className="absolute inset-y-0 w-12 bg-gradient-to-r from-transparent via-[#84cc16]/30 to-transparent" />
            </div>
          )}
          <span className="relative">
            {scanning ? "AUTHENTICATING…" : isLogin ? "AUTHENTICATE" : "CREATE ACCOUNT"}
          </span>
        </button>

        {isLogin && (
          <>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-[#1e3a1e]" />
              <span className="text-[9px] font-mono text-[#2a4a2a] tracking-widest">OR</span>
              <div className="flex-1 h-px bg-[#1e3a1e]" />
            </div>

            <button
              type="button"
              onClick={handleTryDemo}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 border border-[#1e3a1e] bg-transparent hover:border-[#84cc16]/20 text-[#2a6a2a] hover:text-[#84cc16]/60 text-xs font-mono tracking-widest uppercase py-2.5 rounded transition-all duration-300 disabled:opacity-50"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[#84cc16] animate-pulse" />
              LIVE DEMO — NO ACCOUNT
            </button>
          </>
        )}
      </form>

      <div className="mt-6 pt-4 border-t border-[#1e3a1e] text-center">
        <p className="text-[10px] font-mono text-[#2a4a2a] tracking-widest uppercase">
          {isLogin ? (
            <>
              NO ACCOUNT?{" "}
              <button type="button" onClick={() => { setMode("register"); setError(""); }}
                className="text-[#84cc16]/50 hover:text-[#84cc16] transition-colors">
                SIGN UP FREE
              </button>
            </>
          ) : (
            <>
              HAVE AN ACCOUNT?{" "}
              <button type="button" onClick={() => { setMode("login"); setError(""); }}
                className="text-[#84cc16]/50 hover:text-[#84cc16] transition-colors">
                SIGN IN
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function LoginPage() {
  return (
    <div className="relative min-h-screen bg-[#020b02] overflow-hidden">
      <GridBg />
      <TickerBg />

      {/* Top bar */}
      <div className="relative z-10 flex items-center justify-between px-6 py-4 border-b border-[#0f1a0f]">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[#84cc16] animate-pulse" />
          <span className="text-[10px] font-mono text-[#84cc16]/40 tracking-[0.3em] uppercase">BMG Capital</span>
        </div>
        <span className="text-[9px] font-mono text-[#1e3a1e] tracking-widest uppercase hidden sm:block">
          Paper trading only — not financial advice
        </span>
      </div>

      {/* Main content */}
      <div className="relative z-10 flex flex-col items-center justify-center min-h-[calc(100vh-56px)] px-4 py-12">

        {/* Logo reveal */}
        <motion.div
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="mb-10 text-center"
        >
          <h1 className="text-3xl sm:text-4xl font-black tracking-[0.15em] uppercase"
            style={{
              color: "#84cc16",
              textShadow: "0 0 30px rgba(132,204,22,0.4), 0 0 60px rgba(132,204,22,0.15)",
            }}>
            BMG CAPITAL
          </h1>
          <p className="mt-2 text-[10px] font-mono tracking-[0.4em] text-[#84cc16]/30 uppercase">
            Quantitative Trading System
          </p>
        </motion.div>

        <div className="flex flex-col lg:flex-row items-center gap-16 w-full max-w-5xl">

          {/* Voice demo — desktop only */}
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
            <VoiceDemo />
            <p className="hidden lg:block text-slate-700 text-xs font-mono text-center">↑ 30-second demo · replays automatically</p>
          </motion.div>

          {/* Auth card */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
            className="w-full lg:max-w-sm flex-shrink-0"
          >
            <div className="relative p-8 rounded-sm"
              style={{ background: "rgba(2, 11, 2, 0.85)", backdropFilter: "blur(12px)" }}>
              <CornerBrackets />
              <LoginForm />
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
