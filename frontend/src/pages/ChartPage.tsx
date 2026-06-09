import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { LayoutList } from "lucide-react";
import TvTopBar from "@/components/chart/TvTopBar";
import WatchlistPanel from "@/components/panels/WatchlistPanel";
import TradingViewWidget from "@/components/TradingViewWidget";
import { mapToTvSymbol } from "@/lib/chart/tvSymbolMap";

function getStoredSymbol() {
  try { return localStorage.getItem("bmg_symbol") ?? "AAPL"; } catch { return "AAPL"; }
}

const _CRYPTO_BASES = new Set([
  "BTC","ETH","SOL","BNB","XRP","ADA","AVAX","DOGE","DOT","MATIC","LINK","UNI",
  "ATOM","LTC","ETC","BCH","NEAR","APT","OP","ARB","SUI","SHIB","TRX","TON",
]);

function normalizeCryptoSymbol(s: string): string {
  const upper = s.toUpperCase().trim();
  if (upper.includes("/")) {
    const [base, quote] = upper.split("/");
    return `${base}-${["USDT","BUSD","USDC"].includes(quote) ? "USD" : quote}`;
  }
  if (_CRYPTO_BASES.has(upper)) return `${upper}-USD`;
  return upper;
}

export default function ChartPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [symbol, setSymbol] = useState(
    () => normalizeCryptoSymbol(searchParams.get("symbol") ?? getStoredSymbol())
  );
  const [showWatchlist, setShowWatchlist] = useState(true);

  const handleSymbolChange = (s: string) => {
    const normalized = normalizeCryptoSymbol(s);
    setSymbol(normalized);
    setSearchParams({ symbol: normalized });
    try { localStorage.setItem("bmg_symbol", normalized); } catch {}
  };

  return (
    <div className="flex flex-col flex-1 overflow-hidden bg-[var(--bg-base)] text-[var(--text-secondary)]">
      <TvTopBar
        symbol={symbol}
        chartType="candle"
        onSymbolChange={handleSymbolChange}
        onChartTypeChange={() => {}}
        onIndicatorsClick={() => {}}
        onWatchlistToggle={() => setShowWatchlist((v) => !v)}
        showWatchlist={showWatchlist}
      />

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 overflow-hidden">
          <TradingViewWidget
            symbol={mapToTvSymbol(symbol)}
            interval="D"
            theme="dark"
          />
        </div>

        {showWatchlist ? (
          <WatchlistPanel
            activeSymbol={symbol}
            onSymbolClick={handleSymbolChange}
            onClose={() => setShowWatchlist(false)}
          />
        ) : (
          <button
            onClick={() => setShowWatchlist(true)}
            title="Show watchlist"
            className="w-8 shrink-0 flex flex-col items-center justify-center border-l border-[var(--border-subtle)] bg-[var(--bg-base)] hover:bg-[var(--bg-elevated)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors gap-1"
          >
            <LayoutList size={14} />
          </button>
        )}
      </div>
    </div>
  );
}
