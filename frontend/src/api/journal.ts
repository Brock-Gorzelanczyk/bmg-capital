import client from "./client";

export interface JournalEntry {
  id: number;
  paper_order_id: number | null;
  symbol: string;
  trade_date: string;
  side: string;
  qty: number;
  entry_price: number;
  exit_price: number | null;
  pnl: number | null;
  setup: string | null;
  mood: number | null;
  confidence: number | null;
  notes: string | null;
  lessons: string | null;
  rating: number | null;
  created_at: string | null;
}

export interface JournalStats {
  total_entries: number;
  entries_with_notes: number;
  total_pnl: number;
  win_rate: number;
  avg_mood: number;
}

export interface CreateEntryBody {
  symbol: string;
  trade_date: string;
  side: string;
  qty?: number;
  entry_price?: number;
  exit_price?: number | null;
  pnl?: number | null;
  paper_order_id?: number | null;
  setup?: string | null;
  mood?: number | null;
  confidence?: number | null;
  notes?: string | null;
  lessons?: string | null;
  rating?: number | null;
}

export const getEntries = (symbol?: string): Promise<JournalEntry[]> =>
  client.get("/journal", { params: symbol ? { symbol } : {} }).then((r) => r.data);

export const getStats = (): Promise<JournalStats> =>
  client.get("/journal/stats").then((r) => r.data);

export const createEntry = (body: CreateEntryBody): Promise<JournalEntry> =>
  client.post("/journal", body).then((r) => r.data);

export const updateEntry = (id: number, body: CreateEntryBody): Promise<JournalEntry> =>
  client.patch(`/journal/${id}`, body).then((r) => r.data);

export const deleteEntry = (id: number): Promise<{ ok: boolean }> =>
  client.delete(`/journal/${id}`).then((r) => r.data);

// ── Pre-Mortem ─────────────────────────────────────────────────────────────

export interface PreMortemCreateBody {
  symbol: string;
  direction: string;
  thesis: string;
  position_size?: number | null;
  entry_price?: number | null;
}

export interface PreMortemEntry extends JournalEntry {
  entry_type: string | null;
}

export const createPreMortem = (body: PreMortemCreateBody): Promise<PreMortemEntry> =>
  client.post("/journal/pre-mortem", body).then((r) => r.data);

export const listPreMortems = (): Promise<PreMortemEntry[]> =>
  client.get("/journal/pre-mortems").then((r) => r.data);
