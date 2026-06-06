import { useState, useEffect, useRef } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { ArrowRight, ChevronDown, Shield, Zap, BookOpen, TrendingUp, Bot, BarChart2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Ticker strip data ──────────────────────────────────────────────────────────

const TICKERS = [
  { sym: "AAPL",    chg: "+1.24%", pos: true },
  { sym: "NVDA",    chg: "+3.11%", pos: true },
  { sym: "BTC",     chg: "+2.80%", pos: true },
  { sym: "ETH",     chg: "+1.95%", pos: true },
  { sym: "SPY",     chg: "+0.67%", pos: true },
  { sym: "META",    chg: "+2.43%", pos: true },
  { sym: "TSLA",    chg: "-0.88%", pos: false },
  { sym: "QQQ",     chg: "+0.92%", pos: true },
  { sym: "SOL",     chg: "+4.20%", pos: true },
  { sym: "MSFT",    chg: "+0.55%", pos: true },
  { sym: "AMD",     chg: "-0.31%", pos: false },
  { sym: "AMZN",    chg: "+1.77%", pos: true },
];

function TickerStrip() {
  return (
    <div className="relative overflow-hidden border-y border-zinc-800/50 bg-zinc-950/80 py-2">
      <div className="flex gap-8 animate-[ticker_30s_linear_infinite] whitespace-nowrap w-max">
        {[...TICKERS, ...TICKERS].map((t, i) => (
          <div key={i} className="flex items-center gap-1.5 shrink-0">
            <span className="text-zinc-300 text-xs font-bold font-mono">{t.sym}</span>
            <span className={cn("text-xs font-mono font-semibold", t.pos ? "text-emerald-400" : "text-red-400")}>
              {t.chg}
            </span>
            <span className="text-zinc-700 text-xs ml-2">·</span>
          </div>
        ))}
      </div>
      <div className="absolute inset-y-0 left-0 w-20 bg-gradient-to-r from-zinc-950 to-transparent pointer-events-none" />
      <div className="absolute inset-y-0 right-0 w-20 bg-gradient-to-l from-zinc-950 to-transparent pointer-events-none" />
    </div>
  );
}

// ── FAQ accordion ──────────────────────────────────────────────────────────────

const FAQ = [
  {
    q: "Is any real money at risk?",
    a: "No. BMG Capital is 100% paper trading. Every bot runs on simulated capital — you see real market signals, real P&L math, zero dollars on the line.",
  },
  {
    q: "How do the 8 AI bots work?",
    a: "Each bot runs a different institutional strategy: swing, day, long-term, crypto momentum, crypto day, options income, and options directional. They scan real market data around the clock, generate signals with plain-English reasoning, and paper-execute automatically.",
  },
  {
    q: "When does live trading launch?",
    a: "Live trading is coming after BMG completes RIA registration in Wisconsin. Pro+ subscribers get early access and reserved allocation.",
  },
  {
    q: "What data powers the signals?",
    a: "EOD price feeds, earnings calendars, macroeconomic regime indicators, on-chain crypto data, options flow, and technical indicators — all from licensed providers. Every signal decision is logged and auditable.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes. Cancel from Settings → Subscription in two clicks. No cancellation fees, no lock-in. Your data stays intact if you come back.",
  },
  {
    q: "What's included in the free plan?",
    a: "One paper bot, five strategies, and basic alerts. No credit card required — ever. Upgrade to Pro to unlock all 8 bots and 99 strategies.",
  },
];

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-zinc-800 last:border-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between w-full py-4 text-left text-sm font-medium text-zinc-200 hover:text-white transition-colors"
      >
        {q}
        <ChevronDown className={cn("w-4 h-4 text-zinc-500 shrink-0 ml-4 transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open && <p className="text-sm text-zinc-400 pb-5 leading-relaxed max-w-2xl">{a}</p>}
    </div>
  );
}

// ── Dashboard mockup ───────────────────────────────────────────────────────────

function DashboardMockup() {
  return (
    <div className="relative w-full max-w-lg">
      <div className="absolute inset-0 bg-emerald-500/5 blur-3xl rounded-3xl" />
      <div className="relative bg-[#0a0f1e] border border-[#1e293b] rounded-2xl overflow-hidden shadow-2xl shadow-black/50">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-[#1e293b]">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
          <span className="text-sm font-semibold text-white">Strategy Lab</span>
          <span className="ml-auto text-xs text-slate-500 font-mono">paper · live signals</span>
        </div>
        <div className="p-4 space-y-2">
          {[
            { name: "Stock Swing", pnl: "+$318.40", pct: "+1.24%", pos: true },
            { name: "Crypto Day",  pnl: "+$84.20",  pct: "+0.18%", pos: true },
            { name: "Options Flow",pnl: "-$42.10",  pct: "-0.34%", pos: false },
            { name: "LT Core",     pnl: "+$194.80", pct: "+0.77%", pos: true },
          ].map((bot) => (
            <div key={bot.name} className="flex items-center justify-between bg-[#0f172a] border border-[#1e293b] rounded-lg px-3 py-2">
              <div className="flex items-center gap-2">
                <div className={cn("w-1.5 h-1.5 rounded-full", bot.pos ? "bg-emerald-400" : "bg-red-400")} />
                <span className="text-xs text-slate-300 font-medium">{bot.name}</span>
              </div>
              <div className="text-right">
                <span className={cn("text-xs font-bold font-mono", bot.pos ? "text-emerald-400" : "text-red-400")}>{bot.pnl}</span>
                <span className={cn("text-[10px] font-mono ml-2", bot.pos ? "text-emerald-400" : "text-red-400")}>{bot.pct}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="px-4 pb-4 grid grid-cols-3 gap-2">
          {[
            { label: "Total P&L", val: "+$555.30" },
            { label: "Win Rate",  val: "71%" },
            { label: "Sharpe",    val: "1.58" },
          ].map((s) => (
            <div key={s.label} className="bg-[#0f172a] border border-[#1e293b] rounded-lg px-2 py-1.5 text-center">
              <p className="text-emerald-400 font-bold text-sm font-mono">{s.val}</p>
              <p className="text-slate-600 text-[10px] mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="absolute -top-3 -right-3 bg-[#0a0f1e] border border-emerald-500/30 rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-emerald-400 text-xs font-bold">+$555 today</span>
      </div>
      <div className="absolute -bottom-3 -left-3 bg-[#0a0f1e] border border-blue-500/30 rounded-xl px-3 py-1.5 shadow-lg">
        <span className="text-blue-400 text-xs font-bold">8 bots · paper only</span>
      </div>
    </div>
  );
}

// ── Scroll-aware nav ───────────────────────────────────────────────────────────

function useScrolled(threshold = 10) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > threshold);
    window.addEventListener("scroll", handler, { passive: true });
    return () => window.removeEventListener("scroll", handler);
  }, [threshold]);
  return scrolled;
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const navigate = useNavigate();
  const { token } = useAuthStore();
  const scrolled = useScrolled();
  const faqRef = useRef<HTMLElement>(null);

  if (token) return <Navigate to="/dashboard" replace />;

  const scrollToFaq = () => faqRef.current?.scrollIntoView({ behavior: "smooth" });

  return (
    <div className="min-h-screen bg-[#09090b] text-white overflow-x-hidden">
      {/* Ticker keyframe animation */}
      <style>{`
        @keyframes ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }
      `}</style>

      {/* Dot-grid background */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          backgroundImage: "radial-gradient(circle, #27272a 1px, transparent 1px)",
          backgroundSize: "28px 28px",
          opacity: 0.35,
        }}
      />

      {/* ── Sticky Nav ──────────────────────────────────────────────────────── */}
      <nav
        className={cn(
          "sticky top-0 z-50 flex items-center justify-between px-6 py-3.5 transition-all duration-200",
          scrolled ? "bg-zinc-950/90 backdrop-blur-md border-b border-zinc-800/70 shadow-lg" : "bg-transparent"
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <img src="/logo.png" alt="BMG Capital" className="h-7 w-auto object-contain" />
        </div>

        {/* Center nav links */}
        <div className="hidden md:flex items-center gap-6">
          {[
            { label: "Product",    href: "#features" },
            { label: "Pricing",    href: "/pricing" },
            { label: "Strategies", href: "#strategies" },
            { label: "FAQ",        action: scrollToFaq },
          ].map((item) => (
            <button
              key={item.label}
              onClick={() => item.action ? item.action() : (item.href?.startsWith("/") ? navigate(item.href) : document.getElementById(item.href!.slice(1))?.scrollIntoView({ behavior: "smooth" }))}
              className="text-sm text-zinc-400 hover:text-white transition-colors font-medium"
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* Right CTAs */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate("/login")}
            className="text-sm text-zinc-400 hover:text-white transition-colors font-medium hidden sm:block"
          >
            Log in
          </button>
          <button
            onClick={() => navigate("/login?signup=true")}
            className="flex items-center gap-1.5 bg-emerald-500 hover:bg-emerald-400 text-black font-bold text-sm rounded-lg px-4 py-2 transition-colors"
          >
            Sign up free
          </button>
        </div>
      </nav>

      {/* ── Ticker strip ────────────────────────────────────────────────────── */}
      <TickerStrip />

      {/* ── Hero ────────────────────────────────────────────────────────────── */}
      <section className="relative z-10 flex flex-col lg:flex-row items-center justify-center gap-16 px-6 py-20 max-w-7xl mx-auto w-full">
        <div className="flex-1 flex flex-col items-center lg:items-start gap-6 max-w-xl">
          {/* Badge */}
          <div className="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/25 rounded-full px-4 py-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-emerald-400 text-xs font-semibold">8 bots running · paper only · zero risk</span>
          </div>

          {/* Headline */}
          <div className="text-center lg:text-left">
            <h1 className="text-5xl sm:text-6xl font-black text-white leading-[1.05] tracking-tight">
              Trade like a hedge fund.{" "}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-blue-400">
                Risk like a student.
              </span>
            </h1>
            <p className="mt-5 text-zinc-400 text-lg leading-relaxed max-w-lg">
              Eight institutional AI bots run paper trades around the clock — real market signals, real P&L math, zero dollars on the line.
            </p>
          </div>

          {/* CTAs */}
          <div className="flex flex-wrap gap-3 justify-center lg:justify-start">
            <button
              onClick={() => navigate("/login?signup=true")}
              className="flex items-center gap-2 bg-emerald-500 hover:bg-emerald-400 text-black font-bold text-sm rounded-xl px-7 py-3.5 transition-colors shadow-lg shadow-emerald-500/20"
            >
              Start for free <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => navigate("/pricing")}
              className="flex items-center gap-2 bg-transparent border border-zinc-700 hover:border-zinc-500 text-zinc-300 hover:text-white font-semibold text-sm rounded-xl px-7 py-3.5 transition-colors"
            >
              See pricing
            </button>
          </div>

          {/* Trust micro-copy */}
          <p className="text-xs text-zinc-600 text-center lg:text-left">
            No credit card · No real money · Cancel anytime
          </p>
        </div>

        {/* Mockup */}
        <div className="flex-1 flex justify-center lg:justify-end max-w-lg w-full">
          <DashboardMockup />
        </div>
      </section>

      {/* ── Stats bar ───────────────────────────────────────────────────────── */}
      <section className="relative z-10 px-6 py-6 border-y border-zinc-800/60">
        <div className="max-w-5xl mx-auto flex flex-wrap items-center justify-center gap-x-10 gap-y-3">
          {[
            { val: "8",    label: "AI Strategies" },
            { val: "$0",   label: "Real Money at Risk" },
            { val: "99",   label: "Sub-strategies" },
            { val: "24/7", label: "Market Monitoring" },
          ].map((s) => (
            <div key={s.label} className="flex flex-col items-center">
              <span className="text-2xl font-black text-white">{s.val}</span>
              <span className="text-xs text-zinc-500 mt-0.5">{s.label}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── 3 Core Pillars ──────────────────────────────────────────────────── */}
      <section id="features" className="relative z-10 px-6 py-20 max-w-6xl mx-auto w-full">
        <p className="text-center text-zinc-500 text-xs font-semibold uppercase tracking-widest mb-3">
          Why BMG Capital
        </p>
        <h2 className="text-center text-3xl sm:text-4xl font-black text-white mb-14">
          Everything serious paper traders need
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            {
              icon: Bot,
              color: "text-emerald-400",
              bg: "bg-emerald-400/10 border-emerald-400/20",
              title: "Institutional AI Bots",
              desc: "Eight strategies — stock swing, day trading, long-term, crypto momentum, options income, and more — all running automatically with plain-English signal reasoning.",
            },
            {
              icon: BarChart2,
              color: "text-blue-400",
              bg: "bg-blue-400/10 border-blue-400/20",
              title: "Full Strategy Lab",
              desc: "Real P&L tracking, Sharpe ratio, win rate, equity curves, and cross-bot analysis. Know exactly which strategy outperforms across market regimes.",
            },
            {
              icon: BookOpen,
              color: "text-purple-400",
              bg: "bg-purple-400/10 border-purple-400/20",
              title: "Learn While You Trade",
              desc: "TA Workshop, chart pattern coach, and strategy explainers built in. Every bot signal comes with a full breakdown so you understand the why.",
            },
          ].map(({ icon: Icon, color, bg, title, desc }) => (
            <div
              key={title}
              className="bg-zinc-900/60 backdrop-blur-sm border border-zinc-800 rounded-2xl p-6 hover:border-zinc-700 transition-colors group"
            >
              <div className={cn("w-11 h-11 rounded-xl border flex items-center justify-center mb-4", bg)}>
                <Icon className={cn("w-5 h-5", color)} />
              </div>
              <p className="text-white font-bold text-base mb-2">{title}</p>
              <p className="text-zinc-500 text-sm leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Alternating feature rows ─────────────────────────────────────────── */}
      <section id="strategies" className="relative z-10 px-6 py-6 max-w-6xl mx-auto w-full space-y-24">

        {/* Row 1 */}
        <div className="flex flex-col lg:flex-row items-center gap-12">
          <div className="flex-1 space-y-4">
            <p className="text-xs font-bold uppercase tracking-widest text-emerald-400">Strategy Lab</p>
            <h3 className="text-2xl sm:text-3xl font-black text-white leading-snug">
              Track every bot like a quant desk
            </h3>
            <p className="text-zinc-400 leading-relaxed">
              Real-time P&L, 30-day return curves, Sharpe ratio, win rate, and open positions — all in one
              dashboard. Switch between bots instantly. Identify what's working before you ever deploy real capital.
            </p>
            <ul className="space-y-2 text-sm text-zinc-400">
              {["30-day equity curves", "Cross-bot position view", "Per-signal reason log", "Regime-aware analytics"].map((f) => (
                <li key={f} className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
          </div>
          <div className="flex-1 flex justify-center">
            <div className="w-full max-w-sm bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-3">
              <div className="flex items-center justify-between text-xs text-zinc-500 mb-2">
                <span className="font-semibold">30-day equity</span>
                <span className="text-emerald-400 font-bold">+14.3%</span>
              </div>
              {/* Mini sparkline mock */}
              <svg viewBox="0 0 200 60" className="w-full h-12 text-emerald-400">
                <polyline
                  points="0,55 20,48 40,50 60,42 80,38 100,32 120,28 140,22 160,18 180,12 200,8"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <defs>
                  <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#34d399" stopOpacity="0.3" />
                    <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <polyline
                  points="0,55 20,48 40,50 60,42 80,38 100,32 120,28 140,22 160,18 180,12 200,8 200,60 0,60"
                  fill="url(#grad)"
                />
              </svg>
              <div className="grid grid-cols-3 gap-2">
                {[{ l: "Win Rate", v: "71%" }, { l: "Sharpe", v: "1.58" }, { l: "Open", v: "6 pos" }].map((s) => (
                  <div key={s.l} className="bg-zinc-950 border border-zinc-800 rounded-lg py-2 text-center">
                    <p className="text-emerald-400 font-bold text-sm">{s.v}</p>
                    <p className="text-zinc-600 text-[10px]">{s.l}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Row 2 — reversed */}
        <div className="flex flex-col lg:flex-row-reverse items-center gap-12">
          <div className="flex-1 space-y-4">
            <p className="text-xs font-bold uppercase tracking-widest text-blue-400">Signal Engine</p>
            <h3 className="text-2xl sm:text-3xl font-black text-white leading-snug">
              Every signal has a reason — in plain English
            </h3>
            <p className="text-zinc-400 leading-relaxed">
              No black boxes. When a bot fires a buy or sell signal, you see exactly why: the technical pattern,
              the regime condition, the confidence score. Built for traders who want to learn, not just copy.
            </p>
            <ul className="space-y-2 text-sm text-zinc-400">
              {["Natural-language signal reasoning", "Confidence scoring 0–100", "Regime-filtered entries", "Full audit log"].map((f) => (
                <li key={f} className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
          </div>
          <div className="flex-1 flex justify-center">
            <div className="w-full max-w-sm bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-2.5">
              {[
                { sym: "NVDA", side: "BUY", reason: "Stage 2 breakout · vol +40%", conf: 87, color: "text-emerald-400 bg-emerald-400/10" },
                { sym: "BTC",  side: "BUY", reason: "Funding rate flip · whale acc.", conf: 79, color: "text-emerald-400 bg-emerald-400/10" },
                { sym: "TSLA", side: "SELL", reason: "VWAP rejection · gap fill", conf: 72, color: "text-red-400 bg-red-400/10" },
              ].map((sig) => (
                <div key={sig.sym} className="bg-zinc-950 border border-zinc-800 rounded-xl p-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-full", sig.color)}>{sig.side}</span>
                    <span className="text-sm font-bold text-white">{sig.sym}</span>
                    <span className="ml-auto text-xs text-zinc-500">conf {sig.conf}</span>
                  </div>
                  <p className="text-xs text-zinc-500">{sig.reason}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Safety section ───────────────────────────────────────────────────── */}
      <section className="relative z-10 px-6 py-20 max-w-5xl mx-auto w-full">
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-3xl p-10 sm:p-14 text-center">
          <div className="w-14 h-14 rounded-2xl bg-emerald-400/10 border border-emerald-400/20 flex items-center justify-center mx-auto mb-6">
            <Shield className="w-7 h-7 text-emerald-400" />
          </div>
          <h3 className="text-3xl font-black text-white mb-3">Safe by design</h3>
          <p className="text-zinc-400 max-w-xl mx-auto leading-relaxed mb-8">
            BMG Capital never touches real money. All bots run in paper mode — we simulate fills, track
            hypothetical P&L, and log every decision. Live trading comes later, after RIA registration is complete.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            {[
              { icon: Zap, label: "Paper mode always on" },
              { icon: Shield, label: "No real funds connected" },
              { icon: TrendingUp, label: "Real market data, simulated fills" },
            ].map(({ icon: Icon, label }) => (
              <div key={label} className="flex items-center gap-2 bg-zinc-900 border border-zinc-800 rounded-full px-4 py-2">
                <Icon className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-xs text-zinc-300 font-medium">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── FAQ ─────────────────────────────────────────────────────────────── */}
      <section ref={faqRef} className="relative z-10 px-6 py-16 max-w-3xl mx-auto w-full">
        <p className="text-center text-zinc-500 text-xs font-semibold uppercase tracking-widest mb-3">FAQ</p>
        <h2 className="text-center text-2xl sm:text-3xl font-black text-white mb-10">
          Common questions
        </h2>
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl px-6 py-2">
          {FAQ.map((item) => (
            <FAQItem key={item.q} q={item.q} a={item.a} />
          ))}
        </div>
      </section>

      {/* ── Final CTA ───────────────────────────────────────────────────────── */}
      <section className="relative z-10 px-6 py-20">
        <div className="max-w-2xl mx-auto text-center">
          <div className="relative bg-zinc-900/80 backdrop-blur-sm border border-zinc-800 rounded-3xl p-10 sm:p-14 overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-blue-500/5 pointer-events-none" />
            <div className="relative">
              <h3 className="text-3xl sm:text-4xl font-black text-white leading-tight mb-3">
                Start paper trading today.
              </h3>
              <p className="text-zinc-400 text-base mb-8">
                No credit card. No risk. Eight bots. Real market intelligence.
              </p>
              <div className="flex flex-wrap gap-3 justify-center">
                <button
                  onClick={() => navigate("/login?signup=true")}
                  className="inline-flex items-center gap-2 bg-emerald-500 hover:bg-emerald-400 text-black font-bold text-sm rounded-xl px-8 py-3.5 transition-colors shadow-lg shadow-emerald-500/20"
                >
                  Create free account <ArrowRight className="w-4 h-4" />
                </button>
                <button
                  onClick={() => navigate("/pricing")}
                  className="inline-flex items-center gap-2 border border-zinc-700 hover:border-zinc-500 text-zinc-300 hover:text-white font-semibold text-sm rounded-xl px-8 py-3.5 transition-colors"
                >
                  Compare plans
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────────────── */}
      <footer className="relative z-10 px-6 pt-8 pb-12 border-t border-zinc-800/60">
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Logo + links row */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <img src="/logo.png" alt="BMG Capital" className="h-6 w-auto object-contain opacity-70" />
            <div className="flex items-center gap-5">
              <button onClick={() => navigate("/pricing")} className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">Pricing</button>
              <a href="/terms"   className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">Terms</a>
              <a href="/privacy" className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">Privacy</a>
              <button onClick={() => navigate("/login")} className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">Login</button>
            </div>
          </div>

          {/* Compliance disclaimer */}
          <div className="text-xs text-zinc-700 leading-relaxed space-y-2 max-w-4xl">
            <p>
              <strong className="text-zinc-600">Important disclosures:</strong> BMG Capital is a paper-trading simulation platform.
              All positions, P&L figures, signals, and performance data shown are <strong className="text-zinc-600">hypothetical and simulated</strong>.
              No real money is deployed. No real securities are bought or sold on your behalf.
            </p>
            <p>
              Past simulated performance does not guarantee future results. Hypothetical or simulated performance results have certain limitations.
              Unlike actual performance records, simulated results do not represent actual trading and may not reflect the impact of material economic
              and market factors. BMG Capital is <strong className="text-zinc-600">not a registered investment adviser</strong>, broker-dealer,
              or financial institution. Nothing on this platform constitutes investment advice, a solicitation, or a recommendation to buy or sell
              any security.
            </p>
            <p>
              Live trading features are coming pending completion of RIA registration in the state of Wisconsin.
              Pro+ subscribers will receive first access. BMG Capital reserves the right to modify or discontinue any feature at any time.
            </p>
            <p>© 2026 BMG Capital LLC · Milwaukee, WI · Paper Trading Only · Not Investment Advice</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
