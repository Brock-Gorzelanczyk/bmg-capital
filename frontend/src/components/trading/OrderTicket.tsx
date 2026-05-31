import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { X, ChevronDown, Settings2, Check, AlertCircle, RefreshCw } from "lucide-react";
import { getAccount, placeOrder } from "@/api/paper";
import type { PlaceOrderBody } from "@/api/paper";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import KellySizerModal from "./KellySizerModal";
import PreMortemModal from "./PreMortemModal";

type OrderType = "market" | "limit" | "stop" | "stop_limit" | "bracket" | "trailing_stop";
type TIF = "day" | "gtc" | "ioc" | "fok";
type InputMode = "dollars" | "shares";
type TicketState = "idle" | "reviewing" | "placing" | "filled" | "error";

interface OrderTicketProps {
  symbol: string;
  defaultSide?: "buy" | "sell";
  onClose?: () => void;
  compact?: boolean;
}

const ORDER_TYPE_LABELS: Record<OrderType, string> = {
  market: "Market",
  limit: "Limit",
  stop: "Stop",
  stop_limit: "Stop-Limit",
  bracket: "Bracket",
  trailing_stop: "Trailing Stop",
};

const TIF_LABELS: Record<TIF, string> = {
  day: "Day",
  gtc: "GTC",
  ioc: "IOC",
  fok: "FOK",
};

export default function OrderTicket({ symbol, defaultSide = "buy", onClose, compact = false }: OrderTicketProps) {
  const qc = useQueryClient();
  const quotes = useMarketStore((s) => s.quotes);
  const currentPrice = quotes[symbol]?.price ?? 0;

  // Mode
  const [proMode, setProMode] = useState(false);
  const [side, setSide] = useState<"buy" | "sell">(defaultSide);
  const [inputMode, setInputMode] = useState<InputMode>("dollars");
  const [ticketState, setTicketState] = useState<TicketState>("idle");

  // Simple mode fields
  const [dollarAmount, setDollarAmount] = useState("");
  const [sharesAmount, setSharesAmount] = useState("");

  // Pro mode fields
  const [orderType, setOrderType] = useState<OrderType>("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [takeProfitPrice, setTakeProfitPrice] = useState("");
  const [stopLossPrice, setStopLossPrice] = useState("");
  const [trailingAmount, setTrailingAmount] = useState("");
  const [trailingType, setTrailingType] = useState<"amount" | "percent">("percent");
  const [tif, setTif] = useState<TIF>("day");
  const [extendedHours, setExtendedHours] = useState(false);

  // Result
  const [fillPrice, setFillPrice] = useState<number | null>(null);
  const [fillQty, setFillQty] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [kellyOpen, setKellyOpen] = useState(false);

  // Pre-mortem flow
  const [preMortemOpen, setPreMortemOpen] = useState(false);
  const [pendingOrderBody, setPendingOrderBody] = useState<PlaceOrderBody | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const idempotencyKeyRef = useRef(crypto.randomUUID());
  const [submitting, setSubmitting] = useState(false);

  const { data: account } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 10_000,
  });

  const buyingPower = account?.cash ?? 0;

  // Derived share estimate
  const estimatedShares =
    inputMode === "dollars" && dollarAmount && currentPrice > 0
      ? parseFloat(dollarAmount) / currentPrice
      : null;

  const estimatedDollars =
    inputMode === "shares" && sharesAmount && currentPrice > 0
      ? parseFloat(sharesAmount) * currentPrice
      : null;

  useEffect(() => {
    if (ticketState === "idle") {
      inputRef.current?.focus();
    }
  }, [ticketState, side]);

  const mutation = useMutation({
    mutationFn: (body: PlaceOrderBody) => placeOrder(body),
    onMutate: () => {
      setSubmitting(true);
      setTicketState("placing");
    },
    onSuccess: (order) => {
      qc.invalidateQueries({ queryKey: ["paper-account"] });
      qc.invalidateQueries({ queryKey: ["paper-orders"] });
      qc.invalidateQueries({ queryKey: ["paper-transactions"] });
      setFillPrice(order.fill_price);
      setFillQty(order.fill_qty);
      setTicketState("filled");
      // Reset idempotency key after successful order
      idempotencyKeyRef.current = crypto.randomUUID();
      setSubmitting(false);
      const qty = order.fill_qty ?? order.qty;
      const price = order.fill_price;
      const sideLabel = order.side === "buy" ? "Bought" : "Sold";
      if (price) {
        toast.success(`Filled: ${sideLabel} ${qty} ${order.symbol} @ ${formatCurrency(price)}`);
      } else {
        toast.success(`Order placed: ${sideLabel} ${qty} ${order.symbol}`);
      }
    },
    onError: (e: Error & { response?: { data?: { detail?: string } } }) => {
      setErrorMsg(e?.response?.data?.detail ?? "Order failed. Please try again.");
      setTicketState("error");
      setSubmitting(false);
    },
  });

  function buildOrderBody(): PlaceOrderBody {
    const sym = symbol.trim().toUpperCase();
    const body: PlaceOrderBody = { symbol: sym, side, tif, extended_hours: extendedHours };
    body.idempotency_key = idempotencyKeyRef.current;

    if (proMode) {
      body.order_type = orderType === "bracket" ? "market" : orderType;
      if (inputMode === "dollars" && dollarAmount) body.notional = parseFloat(dollarAmount);
      else if (sharesAmount) body.qty = parseFloat(sharesAmount);

      if (orderType === "limit" && limitPrice) body.limit_price = parseFloat(limitPrice);
      if (orderType === "stop" && stopPrice) body.stop_price = parseFloat(stopPrice);
      if (orderType === "stop_limit") {
        if (stopPrice) body.stop_price = parseFloat(stopPrice);
        if (limitPrice) body.limit_price = parseFloat(limitPrice);
      }
      if (orderType === "bracket") {
        if (takeProfitPrice) body.take_profit_price = parseFloat(takeProfitPrice);
        if (stopLossPrice) body.stop_loss_price = parseFloat(stopLossPrice);
      }
      if (orderType === "trailing_stop") {
        if (trailingAmount) body.trailing_amount = parseFloat(trailingAmount);
        body.trailing_type = trailingType;
      }
    } else {
      body.order_type = "market";
      if (inputMode === "dollars" && dollarAmount) body.notional = parseFloat(dollarAmount);
      else if (sharesAmount) body.qty = parseFloat(sharesAmount);
    }

    return body;
  }

  function handleReview() {
    setErrorMsg("");
    setTicketState("reviewing");
  }

  function handleConfirm() {
    const body = buildOrderBody();
    // Show pre-mortem modal before placing the order
    setPendingOrderBody(body);
    setPreMortemOpen(true);
  }

  function handlePreMortemSave(preMortemId: number) {
    setPreMortemOpen(false);
    if (pendingOrderBody) {
      // Attach the pre-mortem id as metadata (passed through if backend supports it)
      mutation.mutate({ ...pendingOrderBody, premortem_id: preMortemId } as PlaceOrderBody);
    }
  }

  function handlePreMortemSkip() {
    setPreMortemOpen(false);
    if (pendingOrderBody) {
      mutation.mutate(pendingOrderBody);
    }
  }

  function handleReset() {
    setTicketState("idle");
    setDollarAmount("");
    setSharesAmount("");
    setErrorMsg("");
    setFillPrice(null);
    setFillQty(null);
    setSubmitting(false);
  }

  // Validation
  const hasAmount =
    inputMode === "dollars"
      ? !!dollarAmount && parseFloat(dollarAmount) > 0
      : !!sharesAmount && parseFloat(sharesAmount) > 0;

  const isBuy = side === "buy";

  const buyClasses = {
    tab: "text-emerald-400 border-emerald-400",
    surface: "bg-emerald-900/20 border-emerald-800/50",
    btn: "bg-[#22C55E] hover:bg-emerald-400 text-black font-bold",
    ring: "focus:border-emerald-600",
  };
  const sellClasses = {
    tab: "text-red-400 border-red-400",
    surface: "bg-rose-900/20 border-rose-800/50",
    btn: "bg-[#EF4444] hover:bg-red-400 text-[var(--text-primary)] font-bold",
    ring: "focus:border-red-600",
  };
  const theme = isBuy ? buyClasses : sellClasses;

  // ── Review screen ─────────────────────────────────────────────────────────────
  if (ticketState === "reviewing") {
    const qty = inputMode === "dollars" ? estimatedShares : parseFloat(sharesAmount || "0");
    const notional =
      inputMode === "dollars"
        ? parseFloat(dollarAmount || "0")
        : (parseFloat(sharesAmount || "0") * currentPrice);
    return (
      <div className={cn("bg-[var(--bg-elevated)] rounded-2xl flex flex-col", compact ? "p-4" : "p-5")}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-widest">Review Order</span>
          {onClose && (
            <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors">
              <X size={16} />
            </button>
          )}
        </div>

        <div className={cn("rounded-xl border p-4 space-y-3 mb-5", theme.surface)}>
          {[
            { label: "Symbol", value: symbol },
            { label: "Side", value: side.toUpperCase(), colored: true },
            { label: "Order Type", value: proMode ? ORDER_TYPE_LABELS[orderType] : "Market" },
            { label: "Est. Shares", value: qty ? qty.toFixed(4) : "—" },
            { label: "Est. Total", value: notional ? formatCurrency(notional) : "—" },
            ...(proMode && orderType === "limit" && limitPrice ? [{ label: "Limit Price", value: formatCurrency(parseFloat(limitPrice)) }] : []),
            ...(proMode && (orderType === "stop" || orderType === "stop_limit") && stopPrice ? [{ label: "Stop Price", value: formatCurrency(parseFloat(stopPrice)) }] : []),
            ...(proMode && orderType === "bracket" && takeProfitPrice ? [{ label: "Take Profit", value: formatCurrency(parseFloat(takeProfitPrice)) }] : []),
            ...(proMode && orderType === "bracket" && stopLossPrice ? [{ label: "Stop Loss", value: formatCurrency(parseFloat(stopLossPrice)) }] : []),
            { label: "TIF", value: proMode ? TIF_LABELS[tif] : "Day" },
          ].map(({ label, value, colored }) => (
            <div key={label} className="flex items-center justify-between text-sm">
              <span className="text-[var(--text-tertiary)]">{label}</span>
              <span className={cn("font-mono font-semibold",
                colored
                  ? isBuy ? "text-emerald-400" : "text-red-400"
                  : "text-[var(--text-primary)]"
              )}>{value}</span>
            </div>
          ))}
        </div>

        {orderType === "limit" && (
          <div className="flex items-start gap-2 bg-[#F59E0B]/10 border border-[#F59E0B]/20 rounded-lg px-3 py-2 mt-2">
            <AlertCircle size={12} className="text-[#F59E0B] shrink-0 mt-0.5" />
            <span className="text-[10px] text-[#F59E0B]">Limit orders may not fill immediately. Your order will remain open until the price reaches your limit.</span>
          </div>
        )}

        <div className="text-xs text-[var(--text-tertiary)] text-center mb-4">
          Market orders fill immediately at the live price. Estimated total may vary slightly.
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setTicketState("idle")}
            className="flex-1 py-2.5 rounded-xl text-sm bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            Back
          </button>
          <button
            onClick={handleConfirm}
            disabled={mutation.isPending || submitting}
            className={cn("flex-1 py-2.5 rounded-xl text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed", theme.btn)}
          >
            Confirm {isBuy ? "Buy" : "Sell"}
          </button>
        </div>
      </div>
    );
  }

  // ── Placing / loading ─────────────────────────────────────────────────────────
  if (ticketState === "placing") {
    return (
      <div className={cn("bg-[var(--bg-elevated)] rounded-2xl flex flex-col items-center justify-center", compact ? "p-8" : "p-12")}>
        <div className="w-10 h-10 rounded-full border-2 border-[var(--border-emphasis)] border-t-[#3B82F6] animate-spin mb-4" />
        <p className="text-[var(--text-secondary)] text-sm">Placing order…</p>
      </div>
    );
  }

  // ── Filled / success ──────────────────────────────────────────────────────────
  if (ticketState === "filled") {
    return (
      <div className={cn("bg-[var(--bg-elevated)] rounded-2xl flex flex-col items-center justify-center text-center", compact ? "p-6" : "p-10")}>
        <div className="w-14 h-14 rounded-full bg-emerald-900/40 border border-emerald-700 flex items-center justify-center mb-4 animate-in zoom-in-50 duration-300">
          <Check size={28} className="text-emerald-400" />
        </div>
        <p className="text-[var(--text-primary)] font-semibold text-lg mb-1">Order Filled</p>
        {fillPrice && (
          <p className="text-[var(--text-secondary)] text-sm mb-1">
            {fillQty} {symbol} @ <span className="font-mono text-[var(--text-primary)]">{formatCurrency(fillPrice)}</span>
          </p>
        )}
        <p className="text-[var(--text-tertiary)] text-xs mb-6">
          Total: {fillPrice && fillQty ? formatCurrency(fillPrice * fillQty) : "—"}
        </p>
        <div className="flex gap-2 w-full">
          <button
            onClick={handleReset}
            className="flex-1 py-2.5 rounded-xl text-sm bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            New Order
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="flex-1 py-2.5 rounded-xl text-sm bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              Close
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────────
  if (ticketState === "error") {
    return (
      <div className={cn("bg-[var(--bg-elevated)] rounded-2xl flex flex-col items-center justify-center text-center", compact ? "p-6" : "p-10")}>
        <div className="w-14 h-14 rounded-full bg-red-950/40 border border-red-800 flex items-center justify-center mb-4">
          <AlertCircle size={28} className="text-red-400" />
        </div>
        <p className="text-[var(--text-primary)] font-semibold text-lg mb-2">Order Failed</p>
        <p className="text-[var(--text-secondary)] text-sm mb-6 max-w-[240px]">{errorMsg}</p>
        <button
          onClick={handleReset}
          className="flex items-center gap-2 py-2.5 px-5 rounded-xl text-sm bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
        >
          <RefreshCw size={14} /> Try Again
        </button>
      </div>
    );
  }

  // ── Idle / input ─────────────────────────────────────────────────────────────
  return (
    <div id="order-panel" className={cn("bg-[var(--bg-elevated)] rounded-2xl flex flex-col", compact ? "p-4" : "p-5")}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-[var(--text-primary)]">{symbol}</span>
          {currentPrice > 0 && (
            <span className="text-[var(--text-tertiary)] text-sm font-mono">{formatCurrency(currentPrice)}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setProMode((p) => !p)}
            className={cn(
              "flex items-center gap-1 text-xs px-2 py-1 rounded-lg transition-colors",
              proMode ? "bg-[#3B82F6]/20 text-[#3B82F6] border border-[#3B82F6]/30" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
            title="Toggle Pro Mode"
          >
            <Settings2 size={12} />
            Pro
          </button>
          {onClose && (
            <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors">
              <X size={16} />
            </button>
          )}
        </div>
      </div>

      {/* Buy / Sell tabs */}
      <div role="tablist" aria-label="Order side" className="flex mb-4 border-b border-[var(--border-subtle)]">
        {(["buy", "sell"] as const).map((s) => (
          <button
            key={s}
            role="tab"
            aria-selected={side === s}
            aria-controls="order-panel"
            onClick={() => setSide(s)}
            className={cn(
              "flex-1 pb-2.5 text-sm font-semibold transition-all duration-150 border-b-2 -mb-px",
              side === s
                ? s === "buy"
                  ? "text-emerald-400 border-emerald-400"
                  : "text-red-400 border-red-400"
                : "text-[var(--text-tertiary)] border-transparent hover:text-[var(--text-secondary)]"
            )}
          >
            {s === "buy" ? "Buy" : "Sell"}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {/* Amount input */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-[var(--text-tertiary)]">
              {inputMode === "dollars" ? "Dollar Amount" : "Shares"}
            </label>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setKellyOpen(true)}
                className="text-xs text-[#3B82F6] hover:text-blue-300 transition-colors"
              >
                Kelly Size
              </button>
              <span className="text-[var(--text-tertiary)] text-xs">·</span>
              <button
                onClick={() => setInputMode((m) => m === "dollars" ? "shares" : "dollars")}
                className="text-xs text-[#3B82F6] hover:text-blue-300 transition-colors"
              >
                Switch to {inputMode === "dollars" ? "shares" : "$"}
              </button>
            </div>
          </div>
          <div className="relative">
            {inputMode === "dollars" && (
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm font-mono">$</span>
            )}
            <input
              ref={inputRef}
              type="number"
              min="0"
              step="any"
              value={inputMode === "dollars" ? dollarAmount : sharesAmount}
              onChange={(e) => {
                if (inputMode === "dollars") setDollarAmount(e.target.value);
                else setSharesAmount(e.target.value);
              }}
              placeholder="0.00"
              className={cn(
                "w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] font-mono text-sm rounded-xl py-2.5 pr-3 placeholder-[#334155] outline-none transition-colors duration-150",
                inputMode === "dollars" ? "pl-7" : "pl-3",
                theme.ring
              )}
            />
          </div>
          {/* Estimate hint */}
          {inputMode === "dollars" && estimatedShares !== null && estimatedShares > 0 && (
            <p className="text-xs text-[var(--text-tertiary)] mt-1 font-mono">
              ≈ {estimatedShares.toFixed(4)} shares
            </p>
          )}
          {inputMode === "shares" && estimatedDollars !== null && estimatedDollars > 0 && (
            <p className="text-xs text-[var(--text-tertiary)] mt-1 font-mono">
              ≈ {formatCurrency(estimatedDollars)}
            </p>
          )}
        </div>

        {/* Pro mode extras */}
        {proMode && (
          <>
            {/* Order type */}
            <div>
              <label className="text-xs text-[var(--text-tertiary)] mb-1.5 block">Order Type</label>
              <div className="relative">
                <select
                  value={orderType}
                  onChange={(e) => setOrderType(e.target.value as OrderType)}
                  className="w-full appearance-none bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm rounded-xl py-2.5 pl-3 pr-8 outline-none focus:border-[#475569] transition-colors cursor-pointer"
                >
                  {(Object.entries(ORDER_TYPE_LABELS) as [OrderType, string][]).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
                <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] pointer-events-none" />
              </div>
            </div>

            {/* Conditional price inputs */}
            {(orderType === "limit" || orderType === "stop_limit") && (
              <div>
                <label className="text-xs text-[var(--text-tertiary)] mb-1.5 block">Limit Price</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm font-mono">$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={limitPrice}
                    onChange={(e) => setLimitPrice(e.target.value)}
                    placeholder={currentPrice > 0 ? currentPrice.toFixed(2) : "0.00"}
                    className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] font-mono text-sm rounded-xl py-2.5 pl-7 pr-3 placeholder-[#334155] outline-none focus:border-[#475569] transition-colors"
                  />
                </div>
              </div>
            )}

            {(orderType === "stop" || orderType === "stop_limit") && (
              <div>
                <label className="text-xs text-[var(--text-tertiary)] mb-1.5 block">Stop Price</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm font-mono">$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={stopPrice}
                    onChange={(e) => setStopPrice(e.target.value)}
                    placeholder={currentPrice > 0 ? currentPrice.toFixed(2) : "0.00"}
                    className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] font-mono text-sm rounded-xl py-2.5 pl-7 pr-3 placeholder-[#334155] outline-none focus:border-[#475569] transition-colors"
                  />
                </div>
              </div>
            )}

            {orderType === "bracket" && (
              <>
                <div>
                  <label className="text-xs text-emerald-500 mb-1.5 block">Take Profit Price</label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm font-mono">$</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={takeProfitPrice}
                      onChange={(e) => setTakeProfitPrice(e.target.value)}
                      placeholder="0.00"
                      className="w-full bg-emerald-900/10 border border-emerald-900/50 text-[var(--text-primary)] font-mono text-sm rounded-xl py-2.5 pl-7 pr-3 placeholder-[#334155] outline-none focus:border-emerald-700 transition-colors"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-xs text-red-400 mb-1.5 block">Stop Loss Price</label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm font-mono">$</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={stopLossPrice}
                      onChange={(e) => setStopLossPrice(e.target.value)}
                      placeholder="0.00"
                      className="w-full bg-rose-900/10 border border-rose-900/50 text-[var(--text-primary)] font-mono text-sm rounded-xl py-2.5 pl-7 pr-3 placeholder-[#334155] outline-none focus:border-red-700 transition-colors"
                    />
                  </div>
                </div>
              </>
            )}

            {orderType === "trailing_stop" && (
              <div>
                <label className="text-xs text-[var(--text-tertiary)] mb-1.5 block">Trailing Amount</label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    {trailingType === "amount" && (
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm font-mono">$</span>
                    )}
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={trailingAmount}
                      onChange={(e) => setTrailingAmount(e.target.value)}
                      placeholder="0.00"
                      className={cn(
                        "w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] font-mono text-sm rounded-xl py-2.5 pr-3 placeholder-[#334155] outline-none focus:border-[#475569] transition-colors",
                        trailingType === "amount" ? "pl-7" : "pl-3"
                      )}
                    />
                  </div>
                  <div className="flex rounded-xl overflow-hidden border border-[var(--border-emphasis)]">
                    {(["percent", "amount"] as const).map((t) => (
                      <button
                        key={t}
                        onClick={() => setTrailingType(t)}
                        className={cn(
                          "px-3 py-2 text-xs font-semibold transition-colors",
                          trailingType === t
                            ? "bg-[#334155] text-[var(--text-primary)]"
                            : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                        )}
                      >
                        {t === "percent" ? "%" : "$"}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* TIF pills */}
            <div>
              <label className="text-xs text-[var(--text-tertiary)] mb-1.5 block">Time in Force</label>
              <div className="flex gap-1.5">
                {(Object.entries(TIF_LABELS) as [TIF, string][]).map(([v, l]) => (
                  <button
                    key={v}
                    onClick={() => setTif(v)}
                    className={cn(
                      "flex-1 py-1.5 rounded-lg text-xs font-semibold transition-colors",
                      tif === v
                        ? "bg-[#334155] text-[var(--text-primary)]"
                        : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                    )}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>

            {/* Extended hours */}
            <label className="flex items-center gap-2.5 cursor-pointer group">
              <div
                onClick={() => setExtendedHours((v) => !v)}
                className={cn(
                  "w-8 h-4 rounded-full transition-colors relative",
                  extendedHours ? "bg-[#3B82F6]" : "bg-[#334155]"
                )}
              >
                <div className={cn(
                  "absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform",
                  extendedHours ? "translate-x-4" : "translate-x-0.5"
                )} />
              </div>
              <span className="text-xs text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)] transition-colors">Extended hours</span>
            </label>
          </>
        )}

        {/* Buying power */}
        <div className={cn("rounded-xl border px-3 py-2.5 flex items-center justify-between", theme.surface)}>
          <span className="text-xs text-[var(--text-tertiary)]">
            {isBuy ? "Buying Power" : "Shares Available"}
          </span>
          <span className="text-xs font-mono text-[var(--text-secondary)]">
            {isBuy ? formatCurrency(buyingPower) : "—"}
          </span>
        </div>

        {/* Submit */}
        <button
          onClick={handleReview}
          disabled={!hasAmount || !symbol}
          className={cn(
            "w-full py-3 rounded-xl text-sm transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed",
            theme.btn
          )}
        >
          {isBuy ? `Buy ${symbol}` : `Sell ${symbol}`}
        </button>

        <p className="text-[10px] text-[var(--text-tertiary)] text-center">
          Orders execute at live market price. Simulated only.
        </p>
      </div>

      {kellyOpen && (
        <KellySizerModal
          onClose={() => setKellyOpen(false)}
          initialAccountSize={buyingPower > 0 ? buyingPower : undefined}
        />
      )}

      {preMortemOpen && (
        <PreMortemModal
          symbol={symbol}
          direction={side === "buy" ? "long" : "short"}
          positionSize={
            inputMode === "shares" && sharesAmount ? parseFloat(sharesAmount) : estimatedShares ?? undefined
          }
          entryPrice={currentPrice > 0 ? currentPrice : undefined}
          accountValue={account?.equity ?? buyingPower}
          onSave={handlePreMortemSave}
          onSkip={handlePreMortemSkip}
          onClose={() => setPreMortemOpen(false)}
        />
      )}
    </div>
  );
}
