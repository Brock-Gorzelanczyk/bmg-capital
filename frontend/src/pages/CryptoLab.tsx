import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, RefreshCw, X, Bitcoin } from "lucide-react";
import { toast } from "sonner";
import { getCryptoMarket, type CoinData } from "@/api/crypto";
import { getAccount, placeOrder } from "@/api/paper";
import { cn } from "@/lib/utils";

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtPrice(n: number | null, symbol: string): string {
  if (n == null) return "—";
  if (symbol === "SHIB-USD" || n < 0.01) {
    return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 6, maximumFractionDigits: 8 });
  }
  if (n < 1) return "$" + n.toFixed(4);
  if (n >= 10_000) return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtMarketCap(n: number): string {
  if (!n) return "—";
  if (n >= 1e12) return "$" + (n / 1e12).toFixed(2) + "T";
  if (n >= 1e9)  return "$" + (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6)  return "$" + (n / 1e6).toFixed(1) + "M";
  return "$" + n.toLocaleString();
}

// ── Order Modal ───────────────────────────────────────────────────────────────

interface OrderModalProps {
  coin: CoinData;
  cash: number;
  onClose: () => void;
  onFilled: () => void;
}

function OrderModal({ coin, cash, onClose, onFilled }: OrderModalProps) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [mode, setMode] = useState<"notional" | "qty">("notional");
  const [notional, setNotional] = useState("100");
  const [qty, setQty] = useState("");

  const price = coin.last ?? 0;
  const qtyPreview = mode === "notional" && notional && price
    ? (parseFloat(notional) / price).toFixed(8)
    : null;
  const notionalPreview = mode === "qty" && qty && price
    ? (parseFloat(qty) * price).toFixed(2)
    : null;

  const mutation = useMutation({
    mutationFn: () => {
      const body: Parameters<typeof placeOrder>[0] = {
        symbol: coin.symbol,
        side,
        order_type: "market",
        tif: "gtc",
      };
      if (mode === "notional") {
        body.notional = parseFloat(notional);
      } else {
        body.qty = parseFloat(qty);
      }
      return placeOrder(body);
    },
    onSuccess: () => {
      toast.success(`${side === "buy" ? "Bought" : "Sold"} ${coin.slug}`);
      onFilled();
      onClose();
    },
    onError: (e: any) => {
      toast.error(e?.response?.data?.detail ?? "Order failed");
    },
  });

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-sm bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl shadow-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-xs text-[var(--text-tertiary)] uppercase tracking-widest mb-0.5">Trade Crypto</div>
            <div className="text-base font-bold text-[var(--text-primary)]">{coin.name} <span className="text-[var(--text-tertiary)]">{coin.slug}</span></div>
          </div>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer">
            <X size={16} />
          </button>
        </div>

        {/* Price */}
        <div className="text-2xl font-bold font-mono text-[var(--text-primary)] mb-4">
          {fmtPrice(coin.last, coin.symbol)}
          {coin.change_pct != null && (
            <span className={cn("text-sm ml-2 font-normal", coin.change_pct >= 0 ? "text-emerald-400" : "text-red-400")}>
              {coin.change_pct >= 0 ? "+" : ""}{coin.change_pct.toFixed(2)}%
            </span>
          )}
        </div>

        {/* Buy/Sell toggle */}
        <div className="flex gap-1 mb-4 bg-[var(--bg-elevated-2)] p-1 rounded-lg">
          {(["buy", "sell"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSide(s)}
              className={cn(
                "flex-1 py-1.5 rounded-md text-sm font-semibold transition-all capitalize",
                side === s
                  ? s === "buy" ? "bg-emerald-600 text-[var(--text-primary)]" : "bg-red-600 text-[var(--text-primary)]"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
              )}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Mode toggle */}
        <div className="flex gap-2 mb-3 text-xs">
          {(["notional", "qty"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={cn(
                "px-3 py-1 rounded-full border transition-colors",
                mode === m ? "border-[#3B82F6] text-[var(--accent-positive)] bg-[var(--accent-positive)]/10" : "border-[var(--border-subtle)] text-[var(--text-tertiary)]"
              )}
            >
              {m === "notional" ? "$ Amount" : "Coin Qty"}
            </button>
          ))}
        </div>

        {/* Input */}
        {mode === "notional" ? (
          <div className="mb-1">
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm">$</span>
              <input
                type="number"
                value={notional}
                onChange={(e) => setNotional(e.target.value)}
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-lg pl-7 pr-4 py-2.5 text-[var(--text-primary)] text-sm font-mono focus:outline-none focus:border-[#3B82F6]"
                placeholder="100"
                min="1"
              />
            </div>
            {qtyPreview && <p className="text-xs text-[var(--text-tertiary)] mt-1 font-mono">≈ {qtyPreview} {coin.slug}</p>}
          </div>
        ) : (
          <div className="mb-1">
            <div className="relative">
              <input
                type="number"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-lg pl-4 pr-16 py-2.5 text-[var(--text-primary)] text-sm font-mono focus:outline-none focus:border-[#3B82F6]"
                placeholder="0.001"
                step="0.0001"
                min="0"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-xs">{coin.slug}</span>
            </div>
            {notionalPreview && <p className="text-xs text-[var(--text-tertiary)] mt-1 font-mono">≈ ${notionalPreview}</p>}
          </div>
        )}

        <p className="text-xs text-[var(--border-emphasis)] mb-4">Cash available: ${cash.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>

        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || (mode === "notional" ? !notional || parseFloat(notional) <= 0 : !qty || parseFloat(qty) <= 0)}
          className={cn(
            "w-full py-2.5 rounded-xl text-sm font-bold transition-all",
            side === "buy"
              ? "bg-emerald-600 hover:bg-emerald-500 text-[var(--text-primary)] disabled:opacity-40"
              : "bg-red-600 hover:bg-red-500 text-[var(--text-primary)] disabled:opacity-40",
            mutation.isPending && "opacity-60 cursor-wait"
          )}
        >
          {mutation.isPending ? "Placing…" : `Place ${side.toUpperCase()} Order`}
        </button>
      </div>
    </>
  );
}

// ── Coin Card ─────────────────────────────────────────────────────────────────

function CoinCard({ coin, onTrade }: { coin: CoinData; onTrade: (coin: CoinData) => void }) {
  const up = (coin.change_pct ?? 0) >= 0;
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-3 hover:border-[var(--border-emphasis)] transition-colors">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-bold text-[var(--text-primary)] text-sm">{coin.slug}</div>
          <div className="text-xs text-[var(--text-tertiary)]">{coin.name}</div>
        </div>
        <div className={cn(
          "flex items-center gap-1 text-xs font-mono font-semibold px-2 py-1 rounded-lg",
          up ? "bg-emerald-900/30 text-emerald-400" : "bg-red-900/30 text-red-400"
        )}>
          {up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          {coin.change_pct != null ? `${coin.change_pct >= 0 ? "+" : ""}${coin.change_pct.toFixed(2)}%` : "—"}
        </div>
      </div>

      <div>
        <div className="text-lg font-bold font-mono text-[var(--text-primary)]">{fmtPrice(coin.last, coin.symbol)}</div>
        <div className="text-[11px] text-[var(--text-tertiary)] mt-0.5">Mkt Cap {fmtMarketCap(coin.market_cap)}</div>
      </div>

      <button
        onClick={() => onTrade(coin)}
        disabled={coin.last == null}
        className="w-full py-1.5 rounded-lg bg-[var(--bg-elevated-2)] hover:bg-[#334155] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-xs font-semibold transition-colors disabled:opacity-30 cursor-pointer"
      >
        Trade
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CryptoLab() {
  const qc = useQueryClient();
  const [tradingCoin, setTradingCoin] = useState<CoinData | null>(null);

  const { data: market, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["crypto-market"],
    queryFn: getCryptoMarket,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: account } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 30_000,
  });

  const coins = market?.coins ?? [];
  const cryptoPositions = (account?.positions ?? []).filter(p => p.symbol.includes("-USD"));
  const cash = account?.cash ?? 0;

  const totalCryptoPnl = cryptoPositions.reduce((s, p) => s + p.unrealized_pnl, 0);
  const totalCryptoValue = cryptoPositions.reduce((s, p) => s + p.market_value, 0);

  return (
    <div className="space-y-5 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-orange-500 to-yellow-500 flex items-center justify-center shadow-lg shadow-orange-900/30">
            <Bitcoin size={18} className="text-[var(--text-primary)]" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)]">Crypto Lab</h1>
            <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Paper trade crypto 24/7</p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer px-3 py-1.5 rounded-lg bg-[var(--bg-elevated-2)] hover:bg-[#334155]"
        >
          <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* Crypto holdings strip */}
      {cryptoPositions.length > 0 && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">My Crypto Holdings</span>
            <div className="flex items-center gap-3 text-xs font-mono">
              <span className="text-[var(--text-tertiary)]">Value: <span className="text-[var(--text-primary)] font-semibold">${totalCryptoValue.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span></span>
              <span className={cn("font-semibold", totalCryptoPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                {totalCryptoPnl >= 0 ? "+" : ""}{totalCryptoPnl.toFixed(2)} unrealized
              </span>
            </div>
          </div>
          <div className="space-y-2">
            {cryptoPositions.map((p) => (
              <div key={p.id} className="flex items-center gap-3 bg-[var(--bg-elevated-2)] rounded-lg px-3 py-2.5">
                <span className="font-bold text-[var(--text-primary)] text-sm font-mono w-20">{p.symbol.replace("-USD", "")}</span>
                <span className="text-xs text-[var(--text-tertiary)] flex-1">
                  {p.qty.toFixed(6)} coins · avg ${p.avg_cost.toFixed(p.avg_cost < 1 ? 6 : 2)}
                </span>
                <span className="text-sm font-mono text-[var(--text-primary)]">${p.market_value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                <span className={cn("text-xs font-mono font-semibold", p.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {p.unrealized_pnl >= 0 ? "+" : ""}{p.unrealized_pnl_pct.toFixed(2)}%
                </span>
                <button
                  onClick={() => {
                    const coinData = coins.find(c => c.symbol === p.symbol);
                    if (coinData) setTradingCoin(coinData);
                  }}
                  className="text-[10px] px-2 py-1 rounded bg-red-900/30 text-red-400 hover:bg-red-900/50 cursor-pointer font-semibold"
                >
                  Sell
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Coin grid */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Top Coins</span>
          {market?.cached && <span className="text-[10px] text-[var(--border-emphasis)]">cached</span>}
        </div>
        {isLoading ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {Array.from({ length: 15 }).map((_, i) => (
              <div key={i} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 h-32 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {coins.map((coin) => (
              <CoinCard key={coin.symbol} coin={coin} onTrade={setTradingCoin} />
            ))}
          </div>
        )}
      </div>

      {/* 24/7 note */}
      <p className="text-xs text-[var(--border-emphasis)] text-center">Crypto markets trade 24/7 · Paper trading only · Prices via Yahoo Finance</p>

      {/* Order modal */}
      {tradingCoin && (
        <OrderModal
          coin={tradingCoin}
          cash={cash}
          onClose={() => setTradingCoin(null)}
          onFilled={() => {
            qc.invalidateQueries({ queryKey: ["paper-account"] });
          }}
        />
      )}
    </div>
  );
}
