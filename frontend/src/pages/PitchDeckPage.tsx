import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  Maximize2,
  X,
  Check,
  ExternalLink,
  Users,
  TrendingUp,
  Zap,
  Brain,
  BarChart2,
  DollarSign,
  Calendar,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Slide {
  id: number;
  type: string;
  data: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Slide data
// ---------------------------------------------------------------------------
const SLIDES: Slide[] = [
  // 1 — Cover
  {
    id: 1,
    type: "cover",
    data: {},
  },
  // 2 — Problem
  {
    id: 2,
    type: "two-column",
    data: {
      headline: "Retail investors are flying blind",
      problems: [
        {
          title: "Tools built for institutions",
          body: "Bloomberg costs $25K/yr. Retail gets watered-down apps with no real edge.",
        },
        {
          title: "Signal overload",
          body: "The average trader gets 200+ alerts/week. 96% are noise.",
        },
        {
          title: "No feedback loop",
          body: "Platforms track trades but never tell you why you're winning or losing.",
        },
      ],
    },
  },
  // 3 — Solution
  {
    id: 3,
    type: "solution",
    data: {
      headline: "BMG gives retail investors institutional-grade intelligence",
      pillars: [
        {
          icon: "zap",
          title: "AI Signal Engine",
          body: "25 scanner types, AI priority scoring, zero noise",
        },
        {
          icon: "barchart",
          title: "Strategy Autopilot",
          body: "44 pre-built strategies with live P&L tracking",
        },
        {
          icon: "brain",
          title: "BMG Score",
          body: "6-factor intelligence score on every stock, in real time",
        },
      ],
    },
  },
  // 4 — Product
  {
    id: 4,
    type: "product",
    data: {
      headline: "Built for the serious investor",
      bullets: [
        "Real-time alerts with AI priority scoring",
        "44 strategy templates + custom builder",
        "Options flow, dark pool, congressional trades",
        "No-code scanner builder with live backtest",
      ],
    },
  },
  // 5 — Traction
  {
    id: 5,
    type: "traction",
    data: {
      headline: "Early traction is strong",
      stats: [
        { value: "47,000", label: "Beta Users" },
        { value: "89%", label: "30-day retention" },
        { value: "$2,400", label: "Avg portfolio tracked" },
        { value: "4.2×", label: "Avg alpha vs SPY" },
      ],
      growthPoints: [800, 2100, 6400, 14000, 28000, 47000],
    },
  },
  // 6 — Market
  {
    id: 6,
    type: "market",
    data: {
      headline: "A $2.4 trillion market hiding in plain sight",
      rings: [
        { label: "$2.4T TAM", sub: "Global retail trading market", r: 160, opacity: 0.15 },
        { label: "$340B SAM", sub: "Active US retail investors using 3+ tools", r: 110, opacity: 0.25 },
        { label: "$28B SOM", sub: "Premium analytics subscribers, Year 5", r: 65, opacity: 1 },
      ],
      bullets: [
        "47M Americans actively trade stocks",
        "Only 2% use professional-grade tools",
        "Average trader pays $180/yr across 3+ apps",
      ],
    },
  },
  // 7 — Business model
  {
    id: 7,
    type: "business-model",
    data: {
      headline: "Simple, scalable SaaS",
      tiers: [
        {
          name: "Free",
          price: "$0/mo",
          features: "Basic alerts, 5 strategies, paper trading",
          highlight: false,
        },
        {
          name: "Plus",
          price: "$29/mo",
          features: "All 44 strategies, 12 scanners, AI scoring",
          tag: "Most Popular",
          highlight: true,
        },
        {
          name: "Premium",
          price: "$79/mo",
          features: "Options flow, dark pool, API access, webhooks",
          highlight: false,
        },
      ],
    },
  },
  // 8 — Competition quadrant
  {
    id: 8,
    type: "quadrant",
    data: {
      headline: "We own the quadrant no one else has built for",
      competitors: [
        { name: "Robinhood", x: 0.18, y: 0.82 },
        { name: "Webull", x: 0.28, y: 0.73 },
        { name: "TradingView", x: 0.62, y: 0.5 },
        { name: "Bloomberg", x: 0.88, y: 0.15 },
        { name: "Benzinga Pro", x: 0.48, y: 0.42 },
      ],
    },
  },
  // 9 — GTM
  {
    id: 9,
    type: "gtm",
    data: {
      headline: "Distribution that doesn't cost $1M",
      phases: [
        {
          done: true,
          label: "Phase 1",
          title: "Community-led growth",
          body: "Reddit, X/Twitter, Discord · 47K users organically",
        },
        {
          current: true,
          label: "Phase 2",
          title: "Creator partnerships",
          body: "Finance YouTubers, TikTok traders · $0 cost, rev-share",
        },
        {
          label: "Phase 3",
          title: "Institutional white-label",
          body: "Prop firms, family offices · $50K+ ACV",
        },
      ],
    },
  },
  // 10 — Team
  {
    id: 10,
    type: "team",
    data: {
      headline: "Built by traders, for traders",
      members: [
        {
          name: "Brock G.",
          role: "Founder & CEO",
          bio: "Former prop trader · Built BMG from scratch",
          initials: "BG",
        },
        {
          name: "Advisor",
          role: "Risk Management",
          bio: "15 years quant at Two Sigma",
          initials: "RM",
        },
        {
          name: "Advisor",
          role: "Growth",
          bio: "Scaled fintech from 0 to 2M users",
          initials: "GR",
        },
      ],
    },
  },
  // 11 — Tech
  {
    id: 11,
    type: "tech",
    data: {
      headline: "Infrastructure built to scale",
      layers: [
        { label: "Frontend", items: ["React + TypeScript", "Real-time WebSocket", "PWA/iOS"] },
        { label: "Backend", items: ["FastAPI Python", "Railway", "PostgreSQL", "Redis"] },
        { label: "Data & AI", items: ["Alpaca", "Polygon", "Anthropic Claude", "Chainlink"] },
      ],
      differentiators: [
        {
          title: "AI Priority Scorer",
          body: "Learns per-user dismiss patterns weekly",
        },
        {
          title: "Inline Alert Backtest",
          body: "Prevents bad alerts before they're created",
        },
        {
          title: "BMG Score Engine",
          body: "6-factor deterministic scoring, sub-100ms",
        },
      ],
    },
  },
  // 12 — Financials
  {
    id: 12,
    type: "financials",
    data: {
      headline: "Path to profitability is clear",
      rows: [
        { year: "2026", users: "50K", arr: "$180K", margin: "82%" },
        { year: "2027", users: "280K", arr: "$2.4M", margin: "85%" },
        { year: "2028", users: "900K", arr: "$9.8M", margin: "87%" },
      ],
    },
  },
  // 13 — Use of funds
  {
    id: 13,
    type: "use-of-funds",
    data: {
      headline: "Raising $1.2M to reach 500K users",
      segments: [
        { label: "Engineering", pct: 40, color: "#4ade80", detail: "Hire 2 senior engineers, ML infra" },
        { label: "Growth", pct: 25, color: "#60A5FA", detail: "Creator partnerships, paid acquisition test" },
        { label: "Infrastructure", pct: 20, color: "#FBBF24", detail: "Scaling Railway → AWS, data costs" },
        { label: "Operations", pct: 15, color: "#71717A", detail: "Legal, compliance, office" },
      ],
    },
  },
  // 14 — Roadmap
  {
    id: 14,
    type: "roadmap",
    data: {
      headline: "What gets built with the raise",
      quarters: [
        {
          label: "Q3 2026",
          items: ["Mobile app (iOS)", "Live trading integration", "Social features"],
        },
        {
          label: "Q4 2026",
          items: ["Options autopilot", "Crypto full coverage", "API launch"],
        },
        {
          label: "Q1 2027",
          items: ["White-label B2B", "Institutional data feeds", "Series A"],
        },
        {
          label: "Q2 2027",
          items: ["International expansion", "DeFi yield optimizer", "1M users"],
        },
      ],
    },
  },
  // 15 — Vision
  {
    id: 15,
    type: "vision",
    data: {},
  },
];

// ---------------------------------------------------------------------------
// Slide renderers
// ---------------------------------------------------------------------------

function SlideWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-full h-full flex flex-col items-center justify-center px-16 md:px-20 py-10 max-w-6xl mx-auto">
      {children}
    </div>
  );
}

function SlideHeadline({ text }: { text: string }) {
  return (
    <h2 className="text-4xl md:text-5xl font-black text-white text-center mb-10 leading-tight">
      {text}
    </h2>
  );
}

// SLIDE 1 — Cover
function CoverSlide() {
  return (
    <div
      className="w-full h-full flex flex-col items-center justify-center relative overflow-hidden"
      style={{
        background:
          "radial-gradient(ellipse 60% 60% at 50% 50%, rgba(74,222,128,0.07) 0%, transparent 70%), #0a0a0f",
      }}
    >
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center font-black text-5xl mb-8 shadow-2xl"
        style={{ background: "#4ade80", color: "#0a0a0f", boxShadow: "0 0 80px rgba(74,222,128,0.35)" }}
      >
        B
      </div>
      <h1 className="text-7xl md:text-8xl font-black text-white text-center mb-5 tracking-tight leading-none">
        BMG Capital
      </h1>
      <p className="text-xl md:text-2xl text-zinc-400 text-center max-w-2xl mb-10 leading-relaxed">
        Intelligent Trading Infrastructure for the Next Generation of Investors
      </p>
      <div className="flex items-center gap-3 flex-wrap justify-center">
        {["Seed Round", "May 2026", "Confidential"].map((tag) => (
          <span
            key={tag}
            className="px-4 py-1.5 rounded-full text-sm font-semibold border"
            style={{ border: "1px solid rgba(74,222,128,0.4)", color: "#4ade80", background: "rgba(74,222,128,0.07)" }}
          >
            {tag}
          </span>
        ))}
      </div>
    </div>
  );
}

// SLIDE 2 — Problem (two-column)
function TwoColumnSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const problems = data.problems as Array<{ title: string; body: string }>;
  return (
    <SlideWrapper>
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
        {/* Left */}
        <div>
          <h2 className="text-4xl md:text-5xl font-black text-white mb-8 leading-tight">{headline}</h2>
          <div className="space-y-4">
            {problems.map((p) => (
              <div
                key={p.title}
                className="p-5 rounded-2xl border"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              >
                <p className="font-bold text-white mb-1">{p.title}</p>
                <p className="text-zinc-400 text-sm leading-relaxed">{p.body}</p>
              </div>
            ))}
          </div>
        </div>
        {/* Right — confused-trader SVG */}
        <div className="flex items-center justify-center">
          <svg width="280" height="280" viewBox="0 0 280 280" fill="none">
            {/* Monitor */}
            <rect x="60" y="80" width="160" height="100" rx="8" fill="none" stroke="#3F3F46" strokeWidth="3" />
            <rect x="60" y="80" width="160" height="100" rx="8" fill="rgba(74,222,128,0.04)" />
            {/* Screen lines (noise) */}
            <line x1="80" y1="105" x2="200" y2="105" stroke="#FB7185" strokeWidth="2" opacity="0.5" strokeDasharray="6 3" />
            <line x1="80" y1="120" x2="160" y2="120" stroke="#4ade80" strokeWidth="2" opacity="0.3" strokeDasharray="4 4" />
            <line x1="80" y1="135" x2="185" y2="135" stroke="#60A5FA" strokeWidth="2" opacity="0.4" strokeDasharray="5 2" />
            <line x1="80" y1="150" x2="130" y2="150" stroke="#FBBF24" strokeWidth="2" opacity="0.4" strokeDasharray="3 5" />
            {/* Stand */}
            <rect x="125" y="180" width="30" height="14" rx="2" fill="#3F3F46" />
            <rect x="105" y="194" width="70" height="8" rx="4" fill="#3F3F46" />
            {/* Body */}
            <circle cx="140" cy="50" r="22" fill="none" stroke="#4ade80" strokeWidth="2.5" />
            {/* Confused face */}
            <circle cx="132" cy="46" r="2.5" fill="#4ade80" />
            <circle cx="148" cy="46" r="2.5" fill="#4ade80" />
            <path d="M132 58 Q140 54 148 58" stroke="#4ade80" strokeWidth="2" fill="none" />
            {/* Question marks */}
            <text x="190" y="62" fill="rgba(74,222,128,0.6)" fontSize="22" fontWeight="bold">?</text>
            <text x="72" y="50" fill="rgba(74,222,128,0.4)" fontSize="16" fontWeight="bold">?</text>
            {/* Stick arms up (confused) */}
            <line x1="140" y1="72" x2="140" y2="78" stroke="#4ade80" strokeWidth="2.5" />
            <line x1="140" y1="78" x2="110" y2="65" stroke="#4ade80" strokeWidth="2.5" />
            <line x1="140" y1="78" x2="170" y2="65" stroke="#4ade80" strokeWidth="2.5" />
            {/* Legs */}
            <line x1="140" y1="78" x2="125" y2="100" stroke="#4ade80" strokeWidth="2.5" />
            <line x1="140" y1="78" x2="155" y2="100" stroke="#4ade80" strokeWidth="2.5" />
          </svg>
        </div>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 3 — Solution
function SolutionSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const pillars = data.pillars as Array<{ icon: string; title: string; body: string }>;
  const iconMap: Record<string, React.ReactNode> = {
    zap: <Zap size={28} />,
    barchart: <BarChart2 size={28} />,
    brain: <Brain size={28} />,
  };
  return (
    <SlideWrapper>
      <div className="text-center w-full">
        <div className="w-16 h-1 rounded-full mx-auto mb-6" style={{ background: "#4ade80" }} />
        <h2 className="text-4xl md:text-5xl font-black text-white mb-12 leading-tight max-w-3xl mx-auto">
          {headline}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {pillars.map((p) => (
            <div
              key={p.title}
              className="p-7 rounded-2xl text-left border flex flex-col gap-4"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center"
                style={{ background: "rgba(74,222,128,0.12)", color: "#4ade80" }}
              >
                {iconMap[p.icon] ?? <Zap size={28} />}
              </div>
              <p className="font-bold text-white text-lg">{p.title}</p>
              <p className="text-zinc-400 text-sm leading-relaxed">{p.body}</p>
            </div>
          ))}
        </div>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 4 — Product
function ProductSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const bullets = data.bullets as string[];
  return (
    <SlideWrapper>
      <h2 className="text-4xl md:text-5xl font-black text-white text-center mb-10 w-full">{headline}</h2>
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
        {/* Dashboard mockup SVG */}
        <div className="flex justify-center">
          <svg width="360" height="260" viewBox="0 0 360 260" fill="none">
            {/* Card bg */}
            <rect width="360" height="260" rx="16" fill="#18181B" stroke="#3F3F46" strokeWidth="1.5" />
            {/* Header bar */}
            <rect width="360" height="50" rx="16" fill="#27272A" />
            <rect x="0" y="34" width="360" height="16" fill="#27272A" />
            <text x="20" y="32" fill="#FAFAFA" fontSize="13" fontWeight="700">Portfolio Value</text>
            <text x="20" y="47" fill="#4ade80" fontSize="18" fontWeight="800">$72,226</text>
            <text x="290" y="32" fill="#4ade80" fontSize="11" fontWeight="600">+4.2%</text>
            {/* Sparkline 1 */}
            <rect x="16" y="66" width="100" height="56" rx="8" fill="#27272A" />
            <polyline points="26,108 40,96 54,100 68,88 82,92 96,80 110,76" stroke="#4ade80" strokeWidth="2" fill="none" />
            <text x="26" y="80" fill="#A1A1AA" fontSize="8">AAPL</text>
            <text x="26" y="118" fill="#4ade80" fontSize="9" fontWeight="700">+$1,220</text>
            {/* Sparkline 2 */}
            <rect x="126" y="66" width="100" height="56" rx="8" fill="#27272A" />
            <polyline points="136,100 150,108 164,96 178,104 192,92 206,86 220,80" stroke="#60A5FA" strokeWidth="2" fill="none" />
            <text x="136" y="80" fill="#A1A1AA" fontSize="8">MSFT</text>
            <text x="136" y="118" fill="#60A5FA" fontSize="9" fontWeight="700">+$890</text>
            {/* Sparkline 3 */}
            <rect x="236" y="66" width="108" height="56" rx="8" fill="#27272A" />
            <polyline points="246,95 260,102 274,90 288,98 302,86 316,80 330,76" stroke="#FB7185" strokeWidth="2" fill="none" />
            <text x="246" y="80" fill="#A1A1AA" fontSize="8">TSLA</text>
            <text x="246" y="118" fill="#FB7185" fontSize="9" fontWeight="700">-$340</text>
            {/* Strategy list label */}
            <text x="16" y="142" fill="#71717A" fontSize="9" fontWeight="600" letterSpacing="1">ACTIVE STRATEGIES</text>
            {/* Strategy rows */}
            <rect x="16" y="150" width="328" height="34" rx="6" fill="#27272A" />
            <text x="28" y="171" fill="#FAFAFA" fontSize="11" fontWeight="600">Momentum Surge</text>
            <text x="28" y="183" fill="#4ade80" fontSize="10">+$1,530 · 3 trades</text>
            <circle cx="323" cy="167" r="6" fill="rgba(74,222,128,0.2)" />
            <circle cx="323" cy="167" r="3" fill="#4ade80" />

            <rect x="16" y="190" width="328" height="34" rx="6" fill="#27272A" />
            <text x="28" y="211" fill="#FAFAFA" fontSize="11" fontWeight="600">Mean Reversion</text>
            <text x="28" y="223" fill="#A1A1AA" fontSize="10">+$380 · 1 trade</text>
            <circle cx="323" cy="207" r="6" fill="rgba(96,165,250,0.2)" />
            <circle cx="323" cy="207" r="3" fill="#60A5FA" />
          </svg>
        </div>
        {/* Bullets */}
        <div className="space-y-5">
          {bullets.map((b) => (
            <div key={b} className="flex items-start gap-4">
              <div
                className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                style={{ background: "rgba(74,222,128,0.15)", color: "#4ade80" }}
              >
                <Check size={14} />
              </div>
              <p className="text-zinc-300 text-base leading-relaxed">{b}</p>
            </div>
          ))}
        </div>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 5 — Traction
function TractionSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const stats = data.stats as Array<{ value: string; label: string }>;
  const pts = data.growthPoints as number[];
  // Build SVG path for growth curve
  const maxPt = Math.max(...pts);
  const W = 400;
  const H = 100;
  const pathPoints = pts.map((p, i) => {
    const x = (i / (pts.length - 1)) * W;
    const y = H - (p / maxPt) * H * 0.85 - 8;
    return `${x},${y}`;
  });
  const polyline = pathPoints.join(" ");
  const fillPath =
    "M" +
    pathPoints[0] +
    " L" +
    pathPoints.slice(1).join(" L") +
    ` L${W},${H} L0,${H} Z`;

  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 w-full mb-10">
        {stats.map((s) => (
          <div
            key={s.label}
            className="p-5 rounded-2xl border text-center"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
          >
            <p className="text-3xl font-black mb-1" style={{ color: "#4ade80" }}>
              {s.value}
            </p>
            <p className="text-sm text-zinc-400">{s.label}</p>
          </div>
        ))}
      </div>
      {/* Growth curve */}
      <div className="w-full max-w-xl">
        <svg width="100%" viewBox={`0 0 ${W} ${H + 10}`} preserveAspectRatio="none">
          <defs>
            <linearGradient id="growthGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4ade80" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#4ade80" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={fillPath} fill="url(#growthGrad)" />
          <polyline points={polyline} stroke="#4ade80" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <p className="text-center text-xs text-zinc-500 mt-2">
          Organic growth. Zero paid acquisition.
        </p>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 6 — Market
function MarketSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const rings = data.rings as Array<{ label: string; sub: string; r: number; opacity: number }>;
  const bullets = data.bullets as string[];
  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
        {/* Concentric rings SVG */}
        <div className="flex justify-center">
          <svg width="340" height="340" viewBox="0 0 340 340">
            {rings.map((ring, i) => (
              <circle
                key={i}
                cx="170"
                cy="170"
                r={ring.r}
                fill={i === rings.length - 1 ? "rgba(74,222,128,0.12)" : "none"}
                stroke={i === rings.length - 1 ? "#4ade80" : "rgba(74,222,128,0.3)"}
                strokeWidth={i === rings.length - 1 ? 2.5 : 1.5}
              />
            ))}
            {/* Labels */}
            <text x="170" y="165" fill="#4ade80" fontSize="13" fontWeight="800" textAnchor="middle">
              $28B SOM
            </text>
            <text x="170" y="181" fill="#4ade80" fontSize="9" textAnchor="middle" opacity="0.7">
              Year 5
            </text>
            <text x="170" y="255" fill="rgba(74,222,128,0.5)" fontSize="10" textAnchor="middle">
              $340B SAM
            </text>
            <text x="170" y="310" fill="rgba(74,222,128,0.3)" fontSize="10" textAnchor="middle">
              $2.4T TAM
            </text>
          </svg>
        </div>
        {/* Bullets */}
        <div className="space-y-5">
          {bullets.map((b) => (
            <div key={b} className="flex items-start gap-4">
              <div
                className="w-2 h-2 rounded-full mt-2 flex-shrink-0"
                style={{ background: "#4ade80" }}
              />
              <p className="text-zinc-300 text-lg leading-relaxed">{b}</p>
            </div>
          ))}
        </div>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 7 — Business model
function BusinessModelSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const tiers = data.tiers as Array<{ name: string; price: string; features: string; tag?: string; highlight: boolean }>;
  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5 w-full mb-8">
        {tiers.map((t) => (
          <div
            key={t.name}
            className={cn("p-6 rounded-2xl border flex flex-col gap-3 relative", t.highlight && "shadow-2xl")}
            style={{
              background: t.highlight ? "rgba(74,222,128,0.07)" : "rgba(255,255,255,0.04)",
              border: t.highlight ? "2px solid #4ade80" : "1px solid rgba(255,255,255,0.08)",
            }}
          >
            {t.tag && (
              <span
                className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full text-xs font-bold"
                style={{ background: "#4ade80", color: "#0a0a0f" }}
              >
                {t.tag}
              </span>
            )}
            <p className="font-bold text-zinc-400 text-sm">{t.name}</p>
            <p className="text-3xl font-black" style={{ color: t.highlight ? "#4ade80" : "#FAFAFA" }}>
              {t.price}
            </p>
            <p className="text-zinc-400 text-sm leading-relaxed">{t.features}</p>
          </div>
        ))}
      </div>
      <div
        className="w-full p-4 rounded-xl text-center text-sm text-zinc-400 border mb-4"
        style={{ border: "1px solid rgba(255,255,255,0.07)", background: "rgba(255,255,255,0.03)" }}
      >
        AUM-based auto-upgrade: $10K+ portfolio → Plus free · $50K+ → Premium free
      </div>
      <div className="flex gap-8 justify-center flex-wrap">
        {[
          { label: "LTV", value: "$890" },
          { label: "CAC", value: "$31" },
          { label: "LTV:CAC", value: "28×" },
        ].map((m) => (
          <div key={m.label} className="text-center">
            <p className="text-2xl font-black" style={{ color: "#4ade80" }}>{m.value}</p>
            <p className="text-xs text-zinc-500">{m.label}</p>
          </div>
        ))}
      </div>
    </SlideWrapper>
  );
}

// SLIDE 8 — Quadrant competition
function QuadrantSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const competitors = data.competitors as Array<{ name: string; x: number; y: number }>;
  const SIZE = 380;
  const HALF = SIZE / 2;

  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div className="flex justify-center w-full">
        <svg
          width={SIZE + 80}
          height={SIZE + 80}
          viewBox={`-40 -40 ${SIZE + 80} ${SIZE + 80}`}
          className="max-w-full"
        >
          {/* Quadrant dividers */}
          <line x1={HALF} y1={0} x2={HALF} y2={SIZE} stroke="rgba(255,255,255,0.12)" strokeWidth="1" />
          <line x1={0} y1={HALF} x2={SIZE} y2={HALF} stroke="rgba(255,255,255,0.12)" strokeWidth="1" />
          {/* Border */}
          <rect x={0} y={0} width={SIZE} height={SIZE} rx={16} fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.1)" strokeWidth="1" />

          {/* Quadrant labels */}
          <text x="15" y="24" fill="rgba(255,255,255,0.18)" fontSize="11">Easy but dumb</text>
          <text x={HALF + 12} y="24" fill="rgba(74,222,128,0.35)" fontSize="11" fontWeight="700">
            Easy AND smart
          </text>
          <text x={HALF + 12} y="40" fill="rgba(74,222,128,0.35)" fontSize="10">
            ← BMG lives here
          </text>
          <text x="15" y={SIZE - 12} fill="rgba(255,255,255,0.18)" fontSize="11">Hard AND dumb</text>
          <text x={HALF + 12} y={SIZE - 12} fill="rgba(255,255,255,0.18)" fontSize="11">Smart but inaccessible</text>

          {/* Axis labels */}
          <text x={SIZE / 2} y={SIZE + 26} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="12">
            Intelligence / AI →
          </text>
          <text
            x={-26}
            y={SIZE / 2}
            textAnchor="middle"
            fill="rgba(255,255,255,0.4)"
            fontSize="12"
            transform={`rotate(-90, -26, ${SIZE / 2})`}
          >
            Accessibility →
          </text>

          {/* Competitor dots */}
          {competitors.map((c) => {
            const cx = c.x * SIZE;
            const cy = (1 - c.y) * SIZE;
            return (
              <g key={c.name}>
                <circle cx={cx} cy={cy} r="8" fill="rgba(255,255,255,0.15)" stroke="rgba(255,255,255,0.4)" strokeWidth="1.5" />
                <text x={cx + 12} y={cy + 4} fill="rgba(255,255,255,0.55)" fontSize="10">
                  {c.name}
                </text>
              </g>
            );
          })}

          {/* BMG dot — large, pulsing via SVG animate */}
          <circle cx={SIZE * 0.85} cy={SIZE * 0.1} r="22" fill="rgba(74,222,128,0.12)" stroke="#4ade80" strokeWidth="0">
            <animate attributeName="r" values="22;28;22" dur="2.5s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="1;0.4;1" dur="2.5s" repeatCount="indefinite" />
          </circle>
          <circle cx={SIZE * 0.85} cy={SIZE * 0.1} r="14" fill="#4ade80" />
          <text x={SIZE * 0.85 + 20} y={SIZE * 0.1 - 8} fill="#4ade80" fontSize="12" fontWeight="800">
            BMG Capital
          </text>
          <text x={SIZE * 0.85 + 20} y={SIZE * 0.1 + 8} fill="rgba(74,222,128,0.6)" fontSize="10">
            You are here
          </text>
        </svg>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 9 — GTM
function GTMSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const phases = data.phases as Array<{ done?: boolean; current?: boolean; label: string; title: string; body: string }>;
  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div className="w-full flex flex-col md:flex-row gap-4 mb-10">
        {phases.map((p, i) => (
          <div
            key={p.label}
            className="flex-1 p-6 rounded-2xl border"
            style={{
              background: p.done
                ? "rgba(74,222,128,0.07)"
                : p.current
                ? "rgba(251,191,36,0.07)"
                : "rgba(255,255,255,0.04)",
              border: p.done
                ? "1.5px solid rgba(74,222,128,0.4)"
                : p.current
                ? "1.5px solid rgba(251,191,36,0.4)"
                : "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <div className="flex items-center gap-2 mb-3">
              <span
                className="text-xs font-bold px-2 py-0.5 rounded-full"
                style={{
                  background: p.done ? "rgba(74,222,128,0.15)" : p.current ? "rgba(251,191,36,0.15)" : "rgba(255,255,255,0.08)",
                  color: p.done ? "#4ade80" : p.current ? "#FBBF24" : "#71717A",
                }}
              >
                {p.done ? "✓ Done" : p.current ? "Current" : `Phase ${i + 1}`}
              </span>
              <span className="text-xs text-zinc-500">{p.label}</span>
            </div>
            <p className="font-bold text-white mb-2">{p.title}</p>
            <p className="text-zinc-400 text-sm leading-relaxed">{p.body}</p>
          </div>
        ))}
      </div>
      <div
        className="w-full p-4 rounded-xl border text-center text-sm"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
      >
        <span className="text-zinc-300 font-semibold">NPS: 71</span>
        <span className="text-zinc-600 mx-3">·</span>
        <span className="text-zinc-300 font-semibold">34% of new users</span>
        <span className="text-zinc-500"> come from existing users</span>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 10 — Team
function TeamSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const members = data.members as Array<{ name: string; role: string; bio: string; initials: string }>;
  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full mb-8">
        {members.map((m) => (
          <div
            key={m.name}
            className="p-6 rounded-2xl border text-center flex flex-col items-center gap-4"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
          >
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center font-black text-xl"
              style={{ background: "rgba(74,222,128,0.15)", color: "#4ade80", border: "2px solid rgba(74,222,128,0.3)" }}
            >
              {m.initials}
            </div>
            <div>
              <p className="font-bold text-white text-lg">{m.name}</p>
              <p className="text-sm font-semibold mb-2" style={{ color: "#4ade80" }}>{m.role}</p>
              <p className="text-zinc-400 text-sm leading-relaxed">{m.bio}</p>
            </div>
          </div>
        ))}
      </div>
      <p className="text-zinc-500 text-sm text-center">
        Advisory board from{" "}
        {["Goldman Sachs", "Citadel", "Andreessen Horowitz"].map((f, i, arr) => (
          <span key={f}>
            <span className="text-zinc-300">{f}</span>
            {i < arr.length - 1 ? ", " : ""}
          </span>
        ))}
      </p>
    </SlideWrapper>
  );
}

// SLIDE 11 — Tech
function TechSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const layers = data.layers as Array<{ label: string; items: string[] }>;
  const diff = data.differentiators as Array<{ title: string; body: string }>;
  const layerColors = ["rgba(74,222,128,0.1)", "rgba(96,165,250,0.1)", "rgba(251,191,36,0.1)"];
  const layerBorders = ["rgba(74,222,128,0.3)", "rgba(96,165,250,0.3)", "rgba(251,191,36,0.3)"];
  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-10 items-start">
        {/* Stack diagram */}
        <div className="space-y-3">
          {layers.map((layer, i) => (
            <div
              key={layer.label}
              className="p-4 rounded-xl border"
              style={{ background: layerColors[i], border: `1px solid ${layerBorders[i]}` }}
            >
              <p className="text-xs font-bold mb-2 uppercase tracking-widest" style={{ color: i === 0 ? "#4ade80" : i === 1 ? "#60A5FA" : "#FBBF24" }}>
                {layer.label}
              </p>
              <div className="flex flex-wrap gap-2">
                {layer.items.map((item) => (
                  <span
                    key={item}
                    className="px-3 py-1 rounded-full text-xs font-semibold text-zinc-300"
                    style={{ background: "rgba(255,255,255,0.07)" }}
                  >
                    {item}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
        {/* Differentiators */}
        <div className="space-y-4">
          {diff.map((d) => (
            <div
              key={d.title}
              className="p-5 rounded-xl border"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              <p className="font-bold text-white mb-1">{d.title}</p>
              <p className="text-zinc-400 text-sm leading-relaxed">{d.body}</p>
            </div>
          ))}
        </div>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 12 — Financials
function FinancialsSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const rows = data.rows as Array<{ year: string; users: string; arr: string; margin: string }>;
  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div
        className="w-full max-w-2xl rounded-2xl overflow-hidden border mb-8"
        style={{ border: "1px solid rgba(255,255,255,0.1)" }}
      >
        {/* Table header */}
        <div
          className="grid grid-cols-4 px-6 py-3 text-xs font-bold uppercase tracking-widest text-zinc-500"
          style={{ background: "rgba(255,255,255,0.06)" }}
        >
          {["Year", "Users", "ARR", "Gross Margin"].map((h) => (
            <span key={h}>{h}</span>
          ))}
        </div>
        {rows.map((r, i) => (
          <div
            key={r.year}
            className="grid grid-cols-4 px-6 py-4 border-t text-sm"
            style={{
              borderColor: "rgba(255,255,255,0.06)",
              background: i % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent",
            }}
          >
            <span className="font-bold text-white">{r.year}</span>
            <span className="text-zinc-300">{r.users}</span>
            <span className="font-bold" style={{ color: "#4ade80" }}>{r.arr}</span>
            <span className="text-zinc-300">{r.margin}</span>
          </div>
        ))}
      </div>
      <div className="text-center space-y-2">
        <p className="text-zinc-400 text-sm">
          Conversion: free to paid — <span className="text-white font-semibold">8% Year 1 → 14% Year 3</span>
        </p>
        <p className="text-zinc-400 text-sm">
          Profitable at{" "}
          <span className="font-bold" style={{ color: "#4ade80" }}>18K paid subscribers</span>{" "}
          (~Month 22)
        </p>
      </div>
    </SlideWrapper>
  );
}

// SLIDE 13 — Use of funds
function UseOfFundsSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const segments = data.segments as Array<{ label: string; pct: number; color: string; detail: string }>;
  // Build donut SVG
  const R = 80;
  const CX = 100;
  const CY = 100;
  const circumference = 2 * Math.PI * R;
  let cumulative = 0;
  const arcs = segments.map((s) => {
    const start = cumulative;
    cumulative += s.pct;
    return { ...s, start, end: cumulative };
  });

  function arcPath(startPct: number, endPct: number) {
    const startAngle = (startPct / 100) * 2 * Math.PI - Math.PI / 2;
    const endAngle = (endPct / 100) * 2 * Math.PI - Math.PI / 2;
    const x1 = CX + R * Math.cos(startAngle);
    const y1 = CY + R * Math.sin(startAngle);
    const x2 = CX + R * Math.cos(endAngle);
    const y2 = CY + R * Math.sin(endAngle);
    const largeArc = endPct - startPct > 50 ? 1 : 0;
    return `M ${x1} ${y1} A ${R} ${R} 0 ${largeArc} 1 ${x2} ${y2}`;
  }

  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <p className="text-3xl font-black mb-8" style={{ color: "#4ade80" }}>
        $1,200,000 Seed Round
      </p>
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
        {/* Donut */}
        <div className="flex justify-center">
          <svg width="200" height="200" viewBox="0 0 200 200">
            <circle cx={CX} cy={CY} r={R} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="32" />
            {arcs.map((arc) => (
              <path
                key={arc.label}
                d={arcPath(arc.start, arc.end)}
                stroke={arc.color}
                strokeWidth="32"
                fill="none"
                strokeLinecap="butt"
              />
            ))}
            <text x={CX} y={CY - 6} fill="#FAFAFA" fontSize="14" fontWeight="800" textAnchor="middle">
              $1.2M
            </text>
            <text x={CX} y={CY + 12} fill="#71717A" fontSize="9" textAnchor="middle">
              seed round
            </text>
          </svg>
        </div>
        {/* Legend */}
        <div className="space-y-3">
          {segments.map((s) => (
            <div key={s.label} className="flex items-start gap-3">
              <div
                className="w-3 h-3 rounded-full mt-1 flex-shrink-0"
                style={{ background: s.color }}
              />
              <div>
                <p className="font-semibold text-white text-sm">
                  {s.pct}% {s.label}
                </p>
                <p className="text-zinc-400 text-xs">{s.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
      <p className="mt-8 text-zinc-500 text-sm text-center">
        18-month runway · Series A target: Month 20
      </p>
    </SlideWrapper>
  );
}

// SLIDE 14 — Roadmap
function RoadmapSlide({ data }: { data: Record<string, unknown> }) {
  const headline = data.headline as string;
  const quarters = data.quarters as Array<{ label: string; items: string[] }>;
  return (
    <SlideWrapper>
      <SlideHeadline text={headline} />
      <div className="w-full grid grid-cols-1 md:grid-cols-4 gap-4">
        {quarters.map((q, i) => (
          <div key={q.label} className="flex flex-col">
            {/* Timeline connector */}
            <div className="flex items-center gap-2 mb-4">
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
                style={{
                  background: i === 0 ? "rgba(74,222,128,0.15)" : "rgba(255,255,255,0.06)",
                  border: `1.5px solid ${i === 0 ? "#4ade80" : "rgba(255,255,255,0.12)"}`,
                  color: i === 0 ? "#4ade80" : "#71717A",
                }}
              >
                {i + 1}
              </div>
              {i < quarters.length - 1 && (
                <div
                  className="flex-1 h-px"
                  style={{ background: "rgba(255,255,255,0.1)" }}
                />
              )}
            </div>
            <div
              className="p-5 rounded-2xl border flex-1"
              style={{
                background: i === 0 ? "rgba(74,222,128,0.05)" : "rgba(255,255,255,0.03)",
                border: i === 0 ? "1px solid rgba(74,222,128,0.25)" : "1px solid rgba(255,255,255,0.07)",
              }}
            >
              <p
                className="text-xs font-bold mb-3 uppercase tracking-widest"
                style={{ color: i === 0 ? "#4ade80" : "#71717A" }}
              >
                {q.label}
              </p>
              <ul className="space-y-2">
                {q.items.map((item) => (
                  <li key={item} className="flex items-start gap-2 text-sm text-zinc-300">
                    <Calendar size={12} className="mt-0.5 flex-shrink-0 text-zinc-600" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ))}
      </div>
    </SlideWrapper>
  );
}

// SLIDE 15 — Vision
function VisionSlide() {
  const navigate = useNavigate();
  return (
    <div className="w-full h-full flex flex-col items-center justify-center relative overflow-hidden">
      {/* Ambient orb */}
      <div
        className="absolute rounded-full"
        style={{
          width: 400,
          height: 400,
          background:
            "radial-gradient(ellipse at center, rgba(74,222,128,0.55) 0%, rgba(16,185,129,0.2) 40%, transparent 70%)",
          animation: "orbPulse 4s ease-in-out infinite",
          zIndex: 0,
          filter: "blur(40px)",
        }}
      />
      <div className="relative z-10 flex flex-col items-center text-center px-8">
        <h2
          className="text-6xl md:text-7xl font-black text-white mb-5 leading-tight max-w-3xl"
        >
          Every investor deserves an edge.
        </h2>
        <p className="text-2xl md:text-3xl font-bold mb-8" style={{ color: "#4ade80" }}>
          BMG Capital is that edge.
        </p>
        <p className="text-zinc-500 text-sm mb-10">
          Brock Gorzelanczyk · 32bgorzelanczyk@gmail.com
        </p>
        <div className="flex flex-col sm:flex-row gap-4">
          <a
            href="mailto:32bgorzelanczyk@gmail.com?subject=BMG Capital — Let's Talk"
            className="px-8 py-4 rounded-xl font-bold text-base transition-all duration-200 hover:scale-105"
            style={{ background: "#4ade80", color: "#0a0a0f", boxShadow: "0 0 32px rgba(74,222,128,0.3)" }}
          >
            Schedule a Call →
          </a>
          <button
            onClick={() => {
              toast.success("Opening Data Room...");
              navigate("/pitch");
            }}
            className="px-8 py-4 rounded-xl font-bold text-base border transition-all duration-200 hover:scale-105 flex items-center gap-2"
            style={{
              border: "1px solid rgba(255,255,255,0.2)",
              color: "#FAFAFA",
              background: "rgba(255,255,255,0.05)",
            }}
          >
            View Data Room
            <ExternalLink size={16} />
          </button>
        </div>
      </div>
      <style>{`
        @keyframes orbPulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.05); opacity: 0.8; }
        }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main renderer
// ---------------------------------------------------------------------------
function renderSlide(slide: Slide, _isActive: boolean) {
  switch (slide.type) {
    case "cover":
      return <CoverSlide />;
    case "two-column":
      return <TwoColumnSlide data={slide.data} />;
    case "solution":
      return <SolutionSlide data={slide.data} />;
    case "product":
      return <ProductSlide data={slide.data} />;
    case "traction":
      return <TractionSlide data={slide.data} />;
    case "market":
      return <MarketSlide data={slide.data} />;
    case "business-model":
      return <BusinessModelSlide data={slide.data} />;
    case "quadrant":
      return <QuadrantSlide data={slide.data} />;
    case "gtm":
      return <GTMSlide data={slide.data} />;
    case "team":
      return <TeamSlide data={slide.data} />;
    case "tech":
      return <TechSlide data={slide.data} />;
    case "financials":
      return <FinancialsSlide data={slide.data} />;
    case "use-of-funds":
      return <UseOfFundsSlide data={slide.data} />;
    case "roadmap":
      return <RoadmapSlide data={slide.data} />;
    case "vision":
      return <VisionSlide />;
    default:
      return (
        <div className="flex items-center justify-center h-full text-zinc-500">
          Unknown slide type: {slide.type}
        </div>
      );
  }
}

// ---------------------------------------------------------------------------
// PitchDeckPage
// ---------------------------------------------------------------------------
export default function PitchDeckPage() {
  const navigate = useNavigate();
  const [current, setCurrent] = useState(0);
  const [visible, setVisible] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const total = SLIDES.length;

  const goTo = useCallback(
    (idx: number) => {
      if (idx < 0 || idx >= total) return;
      setVisible(false);
      setTimeout(() => {
        setCurrent(idx);
        setVisible(true);
      }, 150);
    },
    [total]
  );

  const next = useCallback(() => goTo(current + 1), [current, goTo]);
  const prev = useCallback(() => goTo(current - 1), [current, goTo]);

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen().catch(() => {
        toast.error("Fullscreen not available");
      });
    } else {
      document.exitFullscreen();
    }
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        next();
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        prev();
      }
      if (e.key === "Escape") navigate("/pitch");
      if (e.key === "f" || e.key === "F") toggleFullscreen();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [current, next, prev, navigate, toggleFullscreen]);

  const progressPct = ((current + 1) / total) * 100;

  return (
    <div
      ref={containerRef}
      className="h-screen w-screen flex flex-col relative select-none overflow-hidden"
      style={{ background: "#0a0a0f", color: "#FAFAFA" }}
    >
      {/* Top bar */}
      <div
        className="flex items-center justify-between px-6 py-3 z-20 relative"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
      >
        {/* Logo */}
        <div className="flex items-center gap-2">
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center font-black text-sm"
            style={{ background: "#4ade80", color: "#0a0a0f" }}
          >
            B
          </div>
          <span className="text-sm font-bold text-white">BMG Capital</span>
        </div>
        {/* Actions */}
        <div className="flex items-center gap-3">
          <span className="text-sm font-mono text-zinc-500">
            {current + 1} / {total}
          </span>
          <button
            onClick={toggleFullscreen}
            className="w-8 h-8 flex items-center justify-center rounded-lg transition-colors hover:bg-white/10 text-zinc-400"
            title="Fullscreen (F)"
          >
            <Maximize2 size={16} />
          </button>
          <button
            onClick={() => navigate("/pitch")}
            className="w-8 h-8 flex items-center justify-center rounded-lg transition-colors hover:bg-white/10 text-zinc-400"
            title="Exit (ESC)"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Slide area */}
      <div className="flex-1 relative overflow-hidden">
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{
            opacity: visible ? 1 : 0,
            transition: "opacity 150ms ease",
          }}
        >
          {renderSlide(SLIDES[current], true)}
        </div>
      </div>

      {/* Bottom nav bar */}
      <div
        className="flex items-center justify-between px-6 py-3 z-20 relative"
        style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
      >
        <button
          onClick={prev}
          disabled={current === 0}
          className={cn(
            "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-all",
            current === 0
              ? "text-zinc-700 cursor-not-allowed"
              : "text-zinc-300 hover:text-white hover:bg-white/10"
          )}
        >
          <ChevronLeft size={16} />
          Prev
        </button>

        {/* Keyboard hint */}
        <p className="text-xs text-zinc-600 hidden md:block">
          ← → navigate · F fullscreen · ESC exit
        </p>

        <button
          onClick={next}
          disabled={current === total - 1}
          className={cn(
            "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-all",
            current === total - 1
              ? "text-zinc-700 cursor-not-allowed"
              : "text-zinc-300 hover:text-white hover:bg-white/10"
          )}
        >
          Next
          <ChevronRight size={16} />
        </button>
      </div>

      {/* Progress bar */}
      <div
        className="absolute bottom-0 left-0 h-0.5 z-30 transition-all duration-300"
        style={{ width: `${progressPct}%`, background: "#4ade80" }}
      />
    </div>
  );
}
