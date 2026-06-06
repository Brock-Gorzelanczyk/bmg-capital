import { useNavigate, Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { Bot, BarChart2, TrendingUp, Briefcase, BookOpen, Map, ArrowRight } from "lucide-react";

// ─── Feature grid data ────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: Bot,
    title: "8 AI Trading Bots",
    desc: "Stock, Crypto & Options strategies",
  },
  {
    icon: BarChart2,
    title: "Strategy Lab",
    desc: "P&L · Sharpe ratio · Win rate",
  },
  {
    icon: TrendingUp,
    title: "Real Signals",
    desc: "Live market data feeds",
  },
  {
    icon: Briefcase,
    title: "Capital Pods",
    desc: "Allocate capital by asset class",
  },
  {
    icon: BookOpen,
    title: "TA Workshop",
    desc: "Learn chart patterns interactively",
  },
  {
    icon: Map,
    title: "Mission Control",
    desc: "Cross-asset portfolio overview",
  },
];

const STATS = [
  "$0 Risk",
  "8 Strategies",
  "Real Market Data",
  "Paper Mode Always On",
];

const STEPS = [
  {
    num: "01",
    title: "Sign up free",
    desc: "No credit card required",
  },
  {
    num: "02",
    title: "Activate your bots",
    desc: "8 strategies start scanning instantly",
  },
  {
    num: "03",
    title: "Track performance",
    desc: "Real signals, paper trades, full audit trail",
  },
];

// ─── Mock dashboard preview ───────────────────────────────────────────────────

function DashboardMockup() {
  return (
    <div className="relative w-full max-w-lg">
      {/* Glow effect behind mockup */}
      <div className="absolute inset-0 bg-[#a3e635]/5 blur-3xl rounded-3xl" />

      <div className="relative bg-[#0a0f1e] border border-[#1e293b] rounded-2xl overflow-hidden shadow-2xl shadow-black/50">
        {/* Top bar */}
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-[#1e293b]">
          <div className="w-2.5 h-2.5 rounded-full bg-[#a3e635]" />
          <span className="text-sm font-semibold text-white">Strategy Lab</span>
          <span className="ml-auto text-xs text-slate-500 font-mono">paper · live</span>
        </div>

        {/* Bot rows */}
        <div className="p-4 space-y-2">
          {[
            { name: "Stock Swing", pnl: "+$31.80", pct: "+1.24%", color: "text-[#a3e635]" },
            { name: "Crypto Day", pnl: "+$4.20", pct: "+0.18%", color: "text-[#a3e635]" },
            { name: "Options Flow", pnl: "-$8.50", pct: "-0.34%", color: "text-red-400" },
            { name: "Long-Term Core", pnl: "+$19.40", pct: "+0.77%", color: "text-[#a3e635]" },
          ].map((bot) => (
            <div
              key={bot.name}
              className="flex items-center justify-between bg-[#0f172a] border border-[#1e293b] rounded-lg px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-[#a3e635]" />
                <span className="text-xs text-slate-300 font-medium">{bot.name}</span>
              </div>
              <div className="text-right">
                <span className={`text-xs font-bold font-mono ${bot.color}`}>{bot.pnl}</span>
                <span className={`text-[10px] font-mono ml-2 ${bot.color}`}>{bot.pct}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Stats footer */}
        <div className="px-4 pb-4 grid grid-cols-3 gap-2">
          {[
            { label: "Total P&L", val: "+$46.90" },
            { label: "Win Rate", val: "68%" },
            { label: "Sharpe", val: "1.42" },
          ].map((s) => (
            <div key={s.label} className="bg-[#0f172a] border border-[#1e293b] rounded-lg px-2 py-1.5 text-center">
              <p className="text-[#a3e635] font-bold text-sm font-mono">{s.val}</p>
              <p className="text-slate-600 text-[10px] mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Floating chips */}
      <div className="absolute -top-3 -right-3 bg-[#0a0f1e] border border-[#a3e635]/30 rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-[#a3e635] text-xs font-bold">+$46.90 today</span>
      </div>
      <div className="absolute -bottom-3 -left-3 bg-[#0a0f1e] border border-blue-500/30 rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-blue-400 text-xs font-bold">8 bots · paper only</span>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const navigate = useNavigate();
  const { token } = useAuthStore();
  if (token) return <Navigate to="/dashboard" replace />;

  return (
    <div className="min-h-screen bg-[#09090b] text-white overflow-x-hidden">
      {/* Dot-grid background */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          backgroundImage:
            "radial-gradient(circle, #27272a 1px, transparent 1px)",
          backgroundSize: "28px 28px",
          opacity: 0.45,
        }}
      />

      {/* ── Nav ─────────────────────────────────────────────────────────── */}
      <nav className="relative z-10 flex items-center justify-between px-6 py-4 border-b border-zinc-800/60">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#3B82F6] to-[#8B5CF6] flex items-center justify-center font-bold text-white text-sm">
            B
          </div>
          <span className="text-white font-bold tracking-tight">BMG Capital</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-zinc-500 hidden sm:block">
            Live trading coming soon · join waitlist →
          </span>
          <button
            onClick={() => navigate("/login")}
            className="text-xs text-zinc-400 hover:text-white transition-colors font-medium"
          >
            Sign in
          </button>
        </div>
      </nav>

      {/* ── Section 1: Hero ──────────────────────────────────────────────── */}
      <section className="relative z-10 flex flex-col lg:flex-row items-center justify-center gap-16 px-6 py-20 max-w-7xl mx-auto w-full">
        {/* Left copy */}
        <div className="flex-1 flex flex-col items-center lg:items-start gap-6 max-w-xl">
          {/* Badge */}
          <div className="flex items-center gap-2 bg-[#a3e635]/10 border border-[#a3e635]/25 rounded-full px-4 py-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#a3e635] animate-pulse" />
            <span className="text-[#a3e635] text-xs font-semibold">AI-Powered Paper Trading</span>
          </div>

          {/* Headline */}
          <div className="text-center lg:text-left">
            <h1 className="text-5xl sm:text-6xl font-black text-white leading-[1.05] tracking-tight">
              BMG Capital
            </h1>
            <h2 className="mt-2 text-2xl sm:text-3xl font-bold leading-snug">
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#3B82F6] to-[#a3e635]">
                The AI trading co-pilot
              </span>
              <span className="text-zinc-300"> for serious paper traders.</span>
            </h2>
            <p className="mt-4 text-zinc-400 text-lg leading-relaxed">
              8 institutional-grade strategies. Real-time signals. Zero real money at risk.
            </p>
          </div>

          {/* CTAs */}
          <div className="flex flex-wrap gap-3 justify-center lg:justify-start">
            <button
              onClick={() => navigate("/login")}
              className="flex items-center gap-2 bg-[#a3e635] hover:bg-[#bef264] text-black font-bold text-sm rounded-xl px-6 py-3 transition-colors"
            >
              Start for Free <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => navigate("/login")}
              className="flex items-center gap-2 bg-transparent border border-zinc-700 hover:border-zinc-500 text-zinc-300 hover:text-white font-semibold text-sm rounded-xl px-6 py-3 transition-colors"
            >
              Watch the Demo
            </button>
          </div>
        </div>

        {/* Right mockup */}
        <div className="flex-1 flex justify-center lg:justify-end max-w-lg w-full">
          <DashboardMockup />
        </div>
      </section>

      {/* ── Section 2: Feature grid ──────────────────────────────────────── */}
      <section className="relative z-10 px-6 py-16 max-w-6xl mx-auto w-full">
        <p className="text-center text-zinc-500 text-xs font-semibold uppercase tracking-widest mb-3">
          Everything in one platform
        </p>
        <h3 className="text-center text-2xl sm:text-3xl font-bold text-white mb-10">
          Built for traders who take it seriously
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map(({ icon: Icon, title, desc }) => (
            <div
              key={title}
              className="bg-zinc-900/60 backdrop-blur-sm border border-zinc-800 rounded-2xl p-5 hover:border-zinc-700 transition-colors group"
            >
              <div className="w-10 h-10 rounded-xl bg-[#a3e635]/10 border border-[#a3e635]/20 flex items-center justify-center mb-3 group-hover:bg-[#a3e635]/15 transition-colors">
                <Icon className="w-5 h-5 text-[#a3e635]" />
              </div>
              <p className="text-white font-bold text-sm mb-1">{title}</p>
              <p className="text-zinc-500 text-sm">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Section 3: Stats bar ─────────────────────────────────────────── */}
      <section className="relative z-10 px-6 py-8 border-y border-zinc-800/60">
        <div className="max-w-4xl mx-auto flex flex-wrap items-center justify-center gap-4 sm:gap-8">
          {STATS.map((stat, i) => (
            <div key={stat} className="flex items-center gap-4">
              <span className="text-white font-bold text-sm sm:text-base">{stat}</span>
              {i < STATS.length - 1 && (
                <span className="text-zinc-700 hidden sm:block">·</span>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── Section 4: How it works ──────────────────────────────────────── */}
      <section className="relative z-10 px-6 py-16 max-w-5xl mx-auto w-full">
        <p className="text-center text-zinc-500 text-xs font-semibold uppercase tracking-widest mb-3">
          How it works
        </p>
        <h3 className="text-center text-2xl sm:text-3xl font-bold text-white mb-12">
          From zero to trading in 60 seconds
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 relative">
          {/* Connector line on desktop */}
          <div className="hidden sm:block absolute top-8 left-[calc(33%-0px)] right-[calc(33%-0px)] h-px bg-gradient-to-r from-zinc-700 via-[#a3e635]/40 to-zinc-700" />

          {STEPS.map(({ num, title, desc }) => (
            <div key={num} className="flex flex-col items-center text-center gap-3">
              <div className="relative w-16 h-16 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center z-10">
                <span className="text-[#a3e635] font-black text-xl font-mono">{num}</span>
              </div>
              <p className="text-white font-bold text-base">{title}</p>
              <p className="text-zinc-500 text-sm leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Section 5: CTA ───────────────────────────────────────────────── */}
      <section className="relative z-10 px-6 py-20">
        <div className="max-w-2xl mx-auto text-center">
          {/* Glow */}
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-64 bg-[#a3e635]/5 blur-3xl pointer-events-none" />
          <div className="relative bg-zinc-900/80 backdrop-blur-sm border border-zinc-800 rounded-3xl p-10 sm:p-14">
            <h3 className="text-3xl sm:text-4xl font-black text-white leading-tight mb-3">
              Start paper trading today.
            </h3>
            <p className="text-zinc-400 text-base mb-8">
              No credit card. No risk. Real market intelligence.
            </p>
            <button
              onClick={() => navigate("/login")}
              className="inline-flex items-center gap-2 bg-[#a3e635] hover:bg-[#bef264] text-black font-bold text-sm rounded-xl px-8 py-3.5 transition-colors"
            >
              Create Free Account <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </section>

      {/* ── Section 6: Footer ────────────────────────────────────────────── */}
      <footer className="relative z-10 px-6 py-8 border-t border-zinc-800/60">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-zinc-600 text-xs">
            © 2026 BMG Capital · Paper Trading Only — Not Investment Advice
          </p>
          <div className="flex items-center gap-5">
            <a href="/terms" className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">
              Terms
            </a>
            <a href="/privacy" className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">
              Privacy
            </a>
            <a href="/login" className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">
              Login
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
