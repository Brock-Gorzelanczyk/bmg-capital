import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Mic, TrendingUp, Shield, Zap, Eye, EyeOff } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { DEMO_EMAIL, DEMO_PASSWORD } from "@/lib/demoMode";

// ─── Simulated 30-second voice demo conversation ─────────────────────────────

const DEMO_SCRIPT = [
  {
    role: "user" as const,
    text: "Hey, how's my portfolio doing today?",
    delay: 500,
  },
  {
    role: "ai" as const,
    text: "Your combined paper portfolio is up +$43.20 today (+0.43%). Stock Swing leads with +$31.80. Crypto Day is flat. No positions are near their stop levels.",
    delay: 2800,
  },
  {
    role: "user" as const,
    text: "Which position should I keep an eye on?",
    delay: 6200,
  },
  {
    role: "ai" as const,
    text: "NVDA is approaching its +1 ATR pyramid add threshold — another $0.60 up and Stock Swing will add 25% to the position. Win rate on NVDA this month is 71%.",
    delay: 8800,
  },
  {
    role: "user" as const,
    text: "What's the VIX doing? Should I be worried?",
    delay: 13500,
  },
  {
    role: "ai" as const,
    text: "VIX is at 18.4 — mid regime. All bots are running at full size. No catalyst blackouts in the next 2 hours. Next risk event: CPI release Thursday 8:30am ET.",
    delay: 16000,
  },
  {
    role: "user" as const,
    text: "Pause the crypto day bot for me.",
    delay: 21500,
  },
  {
    role: "ai" as const,
    text: "Done — Crypto Day is paused. 3 open positions will hold until manual resume or their stop levels. I'll log this in the audit trail.",
    delay: 23800,
  },
];

function VoiceDemo() {
  const [visibleMessages, setVisibleMessages] = useState<typeof DEMO_SCRIPT>([]);
  const [isListening, setIsListening] = useState(false);
  const [cycle, setCycle] = useState(0);

  useEffect(() => {
    setVisibleMessages([]);
    let active = true;

    const timers: ReturnType<typeof setTimeout>[] = [];

    // Show each message at its scheduled delay
    DEMO_SCRIPT.forEach((msg, i) => {
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

    // Restart after full cycle (32s)
    const restart = setTimeout(() => {
      if (!active) return;
      setVisibleMessages([]);
      setCycle(c => c + 1);
    }, 32_000);
    timers.push(restart);

    return () => {
      active = false;
      timers.forEach(clearTimeout);
    };
  }, [cycle]);

  return (
    <div className="relative w-full max-w-md">
      {/* Phone / terminal frame */}
      <div className="relative bg-[#0a0f1e] border border-[#1e293b] rounded-2xl overflow-hidden shadow-2xl shadow-blue-500/10">
        {/* Top bar */}
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-[#1e293b]">
          <div
            className={`w-2.5 h-2.5 rounded-full transition-all duration-300 ${
              isListening ? "bg-[#84cc16] animate-pulse scale-125" : "bg-[#84cc16]"
            }`}
          />
          <span className="text-sm font-semibold text-white">BMG Voice AI</span>
          <span className="ml-auto text-xs text-slate-500 font-mono">
            {isListening ? "Listening…" : "Paper trading"}
          </span>
        </div>

        {/* Waveform when listening */}
        <div
          className={`overflow-hidden transition-all duration-300 ${
            isListening ? "max-h-10 opacity-100" : "max-h-0 opacity-0"
          }`}
        >
          <div className="flex items-center justify-center gap-1 py-2 bg-[#84cc16]/5">
            {[1, 2, 3, 4, 5, 6, 7].map(i => (
              <div
                key={i}
                className="w-0.5 bg-[#84cc16] rounded-full"
                style={{
                  height: `${10 + (i % 3) * 8}px`,
                  animation: `pulse ${0.4 + i * 0.08}s ease-in-out infinite alternate`,
                }}
              />
            ))}
          </div>
        </div>

        {/* Messages */}
        <div className="p-4 space-y-3 min-h-[280px]">
          {visibleMessages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-fadeIn`}
            >
              {msg.role === "ai" && (
                <div className="w-6 h-6 rounded-full bg-[#84cc16] flex items-center justify-center mr-2 mt-0.5 shrink-0">
                  <Zap className="w-3 h-3 text-black" />
                </div>
              )}
              <div
                className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-[#1e40af]/40 text-blue-100 rounded-br-sm border border-blue-500/20"
                    : "bg-[#84cc16]/8 text-slate-200 rounded-bl-sm border-l-2 border-[#84cc16]/60"
                }`}
              >
                {msg.text}
              </div>
              {msg.role === "user" && (
                <div className="w-6 h-6 rounded-full bg-[#1e40af] flex items-center justify-center ml-2 mt-0.5 shrink-0">
                  <Mic className="w-3 h-3 text-white" />
                </div>
              )}
            </div>
          ))}

          {/* Typing indicator between messages */}
          {visibleMessages.length > 0 &&
            visibleMessages[visibleMessages.length - 1].role === "user" && (
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-[#84cc16] flex items-center justify-center shrink-0">
                  <Zap className="w-3 h-3 text-black" />
                </div>
                <div className="flex gap-1 px-3 py-2">
                  {[0, 1, 2].map(i => (
                    <div
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-[#84cc16]/60 animate-bounce"
                      style={{ animationDelay: `${i * 150}ms` }}
                    />
                  ))}
                </div>
              </div>
            )}
        </div>

        {/* Bottom input (decorative) */}
        <div className="px-4 py-3 border-t border-[#1e293b] flex items-center gap-2">
          <div className="flex-1 bg-[#0f172a] border border-[#1e293b] rounded-lg px-3 py-2 text-xs text-slate-600">
            Ask anything about your portfolio…
          </div>
          <div className="w-8 h-8 rounded-lg bg-[#84cc16] flex items-center justify-center">
            <Mic className="w-4 h-4 text-black" />
          </div>
        </div>
      </div>

      {/* Floating stat chips */}
      <div className="absolute -top-3 -right-3 bg-[#0a0f1e] border border-[#84cc16]/30 rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-[#84cc16] text-xs font-bold">+0.43% today</span>
      </div>
      <div className="absolute -bottom-3 -left-3 bg-[#0a0f1e] border border-blue-500/30 rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-blue-400 text-xs font-bold">8 bots · paper only</span>
      </div>
    </div>
  );
}

// ─── Login form ───────────────────────────────────────────────────────────────

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
      setError(detail ?? "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleTryDemo = async () => {
    setError("");
    setLoading(true);
    try {
      await login(DEMO_EMAIL, DEMO_PASSWORD);
      navigate("/");
    } catch {
      setError("Demo account unavailable. Please create a free account.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-sm">
      <div className="bg-[#0a0f1e] border border-[#1e293b] rounded-2xl p-6">
        <h2 className="text-base font-semibold text-white mb-1">
          {mode === "login" ? "Sign in to BMG Capital" : "Create a free account"}
        </h2>
        <p className="text-xs text-slate-500 mb-6">
          {mode === "register"
            ? "Sign up to explore BMG Capital in read-only mode. Browse live paper trades, AI signals, and strategy performance. To run your own bots, contact the team."
            : "Welcome back. Enter your credentials to continue."}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-slate-500 mb-1.5 font-medium">
              {mode === "login" ? "Username or email" : "Email"}
            </label>
            <input
              type={mode === "register" ? "email" : "text"}
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoComplete="username"
              placeholder={mode === "login" ? "username or email" : "you@example.com"}
              className="w-full bg-[#020617] border border-[#1e293b] text-white text-sm rounded-lg px-3 py-2.5 outline-none focus:border-[#3B82F6] placeholder-slate-600 transition-colors"
            />
          </div>

          {mode === "register" && (
            <div>
              <label className="block text-xs text-slate-500 mb-1.5 font-medium">Username</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                required
                autoComplete="username"
                placeholder="your_username"
                className="w-full bg-[#020617] border border-[#1e293b] text-white text-sm rounded-lg px-3 py-2.5 outline-none focus:border-[#3B82F6] placeholder-slate-600 transition-colors"
              />
            </div>
          )}

          <div>
            <label className="block text-xs text-slate-500 mb-1.5 font-medium">Password</label>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                placeholder="••••••••"
                className="w-full bg-[#020617] border border-[#1e293b] text-white text-sm rounded-lg px-3 py-2.5 pr-10 outline-none focus:border-[#3B82F6] placeholder-slate-600 transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {mode === "login" && (
            <div className="flex justify-end -mt-2">
              <Link
                to="/forgot-password"
                className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                Forgot password?
              </Link>
            </div>
          )}

          {mode === "register" && (
            <div>
              <label className="block text-xs text-slate-500 mb-1.5 font-medium">Confirm password</label>
              <div className="relative">
                <input
                  type={showConfirm ? "text" : "password"}
                  value={confirm}
                  onChange={e => setConfirm(e.target.value)}
                  required
                  autoComplete="new-password"
                  placeholder="••••••••"
                  className="w-full bg-[#020617] border border-[#1e293b] text-white text-sm rounded-lg px-3 py-2.5 pr-10 outline-none focus:border-[#3B82F6] placeholder-slate-600 transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                  tabIndex={-1}
                >
                  {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
          )}

          {error && (
            <p className="text-red-400 text-xs bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#3B82F6] hover:bg-[#2563eb] text-white text-sm font-semibold rounded-lg py-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed mt-2"
          >
            {loading ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        {mode === "login" && (
          <>
            <div className="flex items-center gap-3 my-4">
              <div className="flex-1 h-px bg-[#1e293b]" />
              <span className="text-[10px] text-slate-600 uppercase tracking-widest">or</span>
              <div className="flex-1 h-px bg-[#1e293b]" />
            </div>

            <button
              onClick={handleTryDemo}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 border border-[#1e293b] bg-transparent hover:bg-[#0f172a] text-slate-400 hover:text-white text-sm font-medium rounded-lg py-2.5 transition-colors disabled:opacity-50"
            >
              <span className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse" />
              Try live demo — no account needed
            </button>
          </>
        )}

        <div className="mt-4 text-center">
          {mode === "login" ? (
            <p className="text-xs text-slate-500">
              Don't have an account?{" "}
              <button
                type="button"
                onClick={() => { setMode("register"); setError(""); }}
                className="text-blue-400 hover:text-blue-300 font-medium transition-colors"
              >
                Sign up free
              </button>
            </p>
          ) : (
            <p className="text-xs text-slate-500">
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => { setMode("login"); setError(""); }}
                className="text-blue-400 hover:text-blue-300 font-medium transition-colors"
              >
                Sign in
              </button>
            </p>
          )}
        </div>
      </div>

      <p className="text-center text-slate-700 text-xs mt-4">
        Paper trading only · not financial advice
      </p>
    </div>
  );
}

// ─── Feature pills ────────────────────────────────────────────────────────────

const FEATURES = [
  { icon: TrendingUp, label: "8 bots, 1 dashboard" },
  { icon: Shield,     label: "Paper trading — currently in beta" },
  { icon: Mic,        label: "Voice AI · ask anything" },
];

// ─── Main page ────────────────────────────────────────────────────────────────

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-[#020617] flex flex-col">
      {/* Nav */}
      <nav className="flex items-center justify-between px-6 py-4 border-b border-[#0f172a]">
        <img src="/logo.png" alt="BMG Capital" className="h-8 w-auto object-contain" />
        <span className="text-xs text-slate-600 hidden sm:block">
          Paper trading only — currently in beta
        </span>
      </nav>

      {/* Hero */}
      <div className="flex-1 flex flex-col lg:flex-row items-center justify-center gap-16 px-6 py-16 max-w-7xl mx-auto w-full">

        {/* Left: copy + Voice AI demo */}
        <div className="flex-1 flex flex-col items-center lg:items-start gap-8 max-w-lg">
          {/* Badge */}
          <div className="flex items-center gap-2 bg-[#84cc16]/10 border border-[#84cc16]/25 rounded-full px-4 py-1.5">
            <Mic className="w-3.5 h-3.5 text-[#84cc16]" />
            <span className="text-[#84cc16] text-xs font-semibold">Voice AI live now</span>
            <span className="w-1.5 h-1.5 rounded-full bg-[#84cc16] animate-pulse" />
          </div>

          {/* Headline */}
          <div className="text-center lg:text-left">
            <h1 className="text-4xl sm:text-5xl font-black text-white leading-[1.1] tracking-tight">
              Eight algorithmic bots.<br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#3B82F6] to-[#84cc16]">
                One voice command.
              </span>
            </h1>
            <p className="mt-4 text-slate-400 text-lg leading-relaxed">
              Paper-trade the full strategy playbook — intraday, swing, long-term, crypto —
              then ask your AI what it's doing and why.
            </p>
          </div>

          {/* Feature pills */}
          <div className="flex flex-wrap gap-2 justify-center lg:justify-start">
            {FEATURES.map(({ icon: Icon, label }) => (
              <div
                key={label}
                className="flex items-center gap-1.5 bg-[#0a0f1e] border border-[#1e293b] rounded-full px-3 py-1.5"
              >
                <Icon className="w-3.5 h-3.5 text-slate-400" />
                <span className="text-slate-300 text-xs font-medium">{label}</span>
              </div>
            ))}
          </div>

          {/* Voice demo */}
          <div className="w-full flex justify-center lg:justify-start">
            <VoiceDemo />
          </div>

          <p className="text-slate-600 text-xs text-center lg:text-left">
            ↑ Live 30-second demo · replays automatically
          </p>
        </div>

        {/* Right: login form */}
        <div className="w-full flex flex-col items-center gap-4 lg:max-w-sm">
          <p className="text-slate-500 text-sm font-medium">Get started — free</p>
          <LoginForm />
        </div>
      </div>
    </div>
  );
}
