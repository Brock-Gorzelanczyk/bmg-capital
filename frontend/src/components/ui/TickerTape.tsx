import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useTickerTape, type TickerData } from "@/hooks/useTickerTape";
import { TICKER_NAMES } from "@/data/tickerNames";

// ── Logo component ─────────────────────────────────────────────────────────────

// Hand-mapped static logos — for tickers that don't resolve via any online
// logo service (synthetic private-company tickers, etc.). Checked BEFORE
// the Clearbit/favicon lookup.
const HAND_MAPPED_LOGOS: Record<string, string> = {
  SPCX: "/logos/spcx.svg",
};

// Domain map for Clearbit logos — companies where the domain is non-obvious from ticker
const TICKER_DOMAIN: Record<string, string> = {
  AAPL: "apple.com",       MSFT: "microsoft.com",   NVDA: "nvidia.com",
  AMZN: "amazon.com",      GOOGL: "google.com",      META: "meta.com",
  TSLA: "tesla.com",       AVGO: "broadcom.com",     JPM: "jpmorganchase.com",
  LLY:  "lilly.com",       UNH:  "unitedhealthgroup.com", V: "visa.com",
  XOM:  "exxonmobil.com",  MA:   "mastercard.com",   COST: "costco.com",
  HD:   "homedepot.com",   PG:   "pg.com",            JNJ:  "jnj.com",
  ABBV: "abbvie.com",      NFLX: "netflix.com",       BAC:  "bankofamerica.com",
  CRM:  "salesforce.com",  KO:   "coca-cola.com",     ORCL: "oracle.com",
  CVX:  "chevron.com",     AMD:  "amd.com",           MRK:  "merck.com",
  WMT:  "walmart.com",     PEP:  "pepsico.com",       CSCO: "cisco.com",
  ADBE: "adobe.com",       TMO:  "thermofisher.com",  ABT:  "abbott.com",
  ACN:  "accenture.com",   MCD:  "mcdonalds.com",     TXN:  "ti.com",
  NOW:  "servicenow.com",  DIS:  "disney.com",         IBM:  "ibm.com",
  AMGN: "amgen.com",       GE:   "ge.com",             CAT:  "caterpillar.com",
  INTU: "intuit.com",      AXP:  "americanexpress.com", GS: "goldmansachs.com",
  MS:   "morganstanley.com", BLK: "blackrock.com",    T:    "att.com",
  BA:   "boeing.com",      WFC:  "wellsfargo.com",    AMAT: "appliedmaterials.com",
  PYPL: "paypal.com",      UBER: "uber.com",          PANW: "paloaltonetworks.com",
  CL:   "colgate.com",     C:    "citi.com",          PM:   "pmi.com",
};

const AVATAR_COLORS = [
  "#3B82F6","#8B5CF6","#EC4899","#F59E0B","#10B981",
  "#EF4444","#6366F1","#14B8A6","#F97316","#84CC16",
];

function avatarColor(sym: string): string {
  let h = 0;
  for (let i = 0; i < sym.length; i++) h = (h * 31 + sym.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function Logo({ symbol }: { symbol: string }) {
  const [err, setErr] = useState(false);
  const handMapped = HAND_MAPPED_LOGOS[symbol];
  const domain = TICKER_DOMAIN[symbol];
  const color = avatarColor(symbol);

  if (handMapped && !err) {
    return (
      <img
        src={handMapped}
        alt={symbol}
        className="w-5 h-5 rounded-full object-contain shrink-0"
        onError={() => setErr(true)}
        loading="lazy"
      />
    );
  }

  if (!domain || err) {
    return (
      <div
        className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-black text-white shrink-0"
        style={{ background: color }}
      >
        {symbol[0]}
      </div>
    );
  }

  // Google's favicon service — reliable, no API key, no CORS
  const src = `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;

  return (
    <img
      src={src}
      alt={symbol}
      className="w-5 h-5 rounded-full object-contain shrink-0"
      onError={() => setErr(true)}
      loading="lazy"
    />
  );
}

// ── Single ticker item ─────────────────────────────────────────────────────────

function TickerItem({ t, onClick }: { t: TickerData; onClick: () => void }) {
  const isUp = t.changePct >= 0;
  const sign = isUp ? "+" : "";

  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 px-3 shrink-0 hover:bg-white/5 rounded-md transition-colors cursor-pointer h-full"
    >
      <Logo symbol={t.symbol} />
      <span className="text-xs font-bold text-zinc-200">{t.symbol}</span>
      <span className="text-xs font-mono text-zinc-300">
        ${t.price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </span>
      <span className={cn("text-xs font-mono font-semibold", isUp ? "text-emerald-400" : "text-red-400")}>
        {sign}{t.changePct.toFixed(2)}%
      </span>
      <span className="text-zinc-700 text-xs select-none">·</span>
    </button>
  );
}

// ── Fallback static data (shown before first API response) ─────────────────────

const STATIC_FALLBACK: TickerData[] = [
  { symbol: "AAPL",  price: 213.49, prevClose: 211.21, changePct:  1.08, changeAbs:  2.28 },
  { symbol: "MSFT",  price: 449.26, prevClose: 444.92, changePct:  0.98, changeAbs:  4.34 },
  { symbol: "NVDA",  price: 135.72, prevClose: 131.38, changePct:  3.30, changeAbs:  4.34 },
  { symbol: "AMZN",  price: 228.04, prevClose: 224.81, changePct:  1.44, changeAbs:  3.23 },
  { symbol: "GOOGL", price: 182.63, prevClose: 180.94, changePct:  0.93, changeAbs:  1.69 },
  { symbol: "META",  price: 607.92, prevClose: 601.15, changePct:  1.13, changeAbs:  6.77 },
  { symbol: "TSLA",  price: 247.10, prevClose: 249.20, changePct: -0.84, changeAbs: -2.10 },
  { symbol: "AVGO",  price: 244.18, prevClose: 240.33, changePct:  1.60, changeAbs:  3.85 },
  { symbol: "JPM",   price: 266.18, prevClose: 263.44, changePct:  1.04, changeAbs:  2.74 },
  { symbol: "V",     price: 357.52, prevClose: 354.80, changePct:  0.77, changeAbs:  2.72 },
  { symbol: "XOM",   price: 112.31, prevClose: 113.02, changePct: -0.63, changeAbs: -0.71 },
  { symbol: "MA",    price: 563.27, prevClose: 558.44, changePct:  0.86, changeAbs:  4.83 },
  { symbol: "COST",  price: 923.44, prevClose: 916.71, changePct:  0.73, changeAbs:  6.73 },
  { symbol: "HD",    price: 388.92, prevClose: 385.10, changePct:  0.99, changeAbs:  3.82 },
  { symbol: "NFLX",  price: 1258.40,prevClose:1241.20, changePct:  1.39, changeAbs: 17.20 },
  { symbol: "AMD",   price: 168.44, prevClose: 170.21, changePct: -1.04, changeAbs: -1.77 },
  { symbol: "BA",    price: 211.37, prevClose: 208.95, changePct:  1.16, changeAbs:  2.42 },
  { symbol: "DIS",   price: 113.44, prevClose: 112.83, changePct:  0.54, changeAbs:  0.61 },
  { symbol: "IBM",   price: 265.88, prevClose: 263.21, changePct:  1.01, changeAbs:  2.67 },
  { symbol: "PYPL",  price: 84.66,  prevClose: 85.91,  changePct: -1.46, changeAbs: -1.25 },
];

// ── Main TickerTape component ──────────────────────────────────────────────────

export default function TickerTape() {
  const liveData = useTickerTape();
  const tickers = liveData.length > 0 ? liveData : STATIC_FALLBACK;
  const [paused, setPaused] = useState(false);
  const stripRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // Duplicate for seamless loop
  const doubled = [...tickers, ...tickers];
  // Animation duration: ~40px per item at desired speed
  const duration = Math.max(40, tickers.length * 3.5);

  return (
    <div
      className="relative w-full overflow-hidden bg-zinc-950 border-b border-zinc-800/60 select-none"
      style={{ height: 36 }}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      {/* Left fade */}
      <div className="absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-zinc-950 to-transparent z-10 pointer-events-none" />
      {/* Right fade */}
      <div className="absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-zinc-950 to-transparent z-10 pointer-events-none" />

      <style>{`
        @keyframes ticker-scroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>

      <div
        ref={stripRef}
        className="flex items-center h-full w-max"
        style={{
          animation: `ticker-scroll ${duration}s linear infinite`,
          animationPlayState: paused ? "paused" : "running",
        }}
      >
        {doubled.map((t, i) => (
          <TickerItem
            key={`${t.symbol}-${i}`}
            t={t}
            onClick={() => navigate(`/chart?symbol=${t.symbol}`)}
          />
        ))}
      </div>
    </div>
  );
}
