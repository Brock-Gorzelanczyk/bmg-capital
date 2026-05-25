import client from "./client";

export interface PaperPosition {
  id: number;
  symbol: string;
  qty: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  cost_basis: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  day_pnl: number;
  day_pnl_pct: number;
  prev_close: number;
  opened_at: string;
}

export interface PaperAccount {
  cash: number;
  starting_balance: number;
  equity: number;
  day_pnl: number;
  day_pnl_pct: number;
  total_pnl: number;
  total_pnl_pct: number;
  created_at: string;
  positions: PaperPosition[];
}

export interface PaperOrder {
  id: number;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  notional: number | null;
  order_type: string;
  limit_price: number | null;
  stop_price: number | null;
  take_profit_price: number | null;
  stop_loss_price: number | null;
  tif: string;
  status: "working" | "filled" | "cancelled" | "rejected" | "expired";
  fill_price: number | null;
  fill_qty: number | null;
  slippage: number | null;
  total: number;
  reject_reason: string | null;
  filled_at: string | null;
  created_at: string;
}

export interface PlaceOrderBody {
  symbol: string;
  side: "buy" | "sell";
  qty?: number;
  notional?: number;
  order_type?: "market" | "limit" | "stop" | "stop_limit" | "bracket" | "oco" | "trailing_stop";
  limit_price?: number | null;
  stop_price?: number | null;
  take_profit_price?: number | null;
  stop_loss_price?: number | null;
  trailing_amount?: number | null;
  trailing_type?: "amount" | "percent" | null;
  tif?: "day" | "gtc" | "ioc" | "fok";
  extended_hours?: boolean;
  idempotency_key?: string;
}

export interface PaperTransaction {
  id: number;
  symbol: string;
  side: string;
  qty: number;
  fill_price: number;
  cost_basis: number;
  realized_pnl: number;
  created_at: string;
}

export interface DailySnapshot {
  date: string;
  equity: number;
  cash: number;
  positions_value: number;
  day_pnl: number;
}

export async function getAccount(): Promise<PaperAccount> {
  const { data } = await client.get<PaperAccount>("/paper/account");
  return data;
}

export async function placeOrder(body: PlaceOrderBody): Promise<PaperOrder> {
  const { data } = await client.post<PaperOrder>("/paper/orders", body);
  return data;
}

export async function getOrders(status?: string): Promise<PaperOrder[]> {
  const { data } = await client.get<PaperOrder[]>("/paper/orders", {
    params: status ? { status } : undefined,
  });
  return data;
}

export async function cancelOrder(id: number): Promise<{ ok: boolean }> {
  const { data } = await client.delete<{ ok: boolean }>(`/paper/orders/${id}`);
  return data;
}

export async function getTransactions(): Promise<PaperTransaction[]> {
  const { data } = await client.get<PaperTransaction[]>("/paper/transactions");
  return data;
}

export async function getSnapshots(): Promise<DailySnapshot[]> {
  const { data } = await client.get<DailySnapshot[]>("/paper/snapshots");
  return data;
}

export async function resetAccount(): Promise<{ ok: boolean }> {
  const { data } = await client.post<{ ok: boolean }>("/paper/reset");
  return data;
}

export async function seedDemo(): Promise<{ ok: boolean }> {
  const { data } = await client.post<{ ok: boolean }>("/paper/seed-demo");
  return data;
}
