import client from "./client";

export interface BotProfile {
  id: number;
  name: string;           // stock_swing, stock_day, etc.
  description: string;
  asset_class: "stock" | "crypto" | "options" | "quant";
  position_cap: number;
  cadence: string;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  paper_only: true;
  enabled: boolean;
  config?: Record<string, unknown>;
}

export interface BotAllocation {
  id: number;
  profile_id: number;
  capital_pct: number;
  starting_capital_cents?: number;
  risk_profile: "conservative" | "standard" | "aggressive";
  paper_mode: true;        // always true in v1
  go_live_requested: boolean;
  enabled: boolean;
  paused_reason?: string | null;
}

export interface BotListItem {
  profile: BotProfile;
  allocation: BotAllocation | null;
  stats: {
    return_30d_pct: number;
    today_pnl: number;
    open_positions: number;
    total_trades: number;
    win_rate_pct: number;
    all_time_pnl_pct: number | null;
    all_time_pnl_usd: number | null;
    starting_capital_usd: number | null;
    current_equity_usd: number | null;
  };
}

export interface BotSignal {
  id: number;
  ts: string;
  symbol: string;
  side: "buy" | "sell" | "long" | "short" | "hold";
  confidence: number;
  reason: string;
  strategy: string;
}

export interface BotPosition {
  id: number;
  symbol: string;
  qty: number;
  avg_cost_cents: number;
  avg_cost?: number | null;
  opened_at: string;
  is_paper: true;
  current_price?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  unrealized_pnl_pct?: number | null;
}

export const getBots = () =>
  client.get<{ bots: any[] }>("/bots").then((r) => ({
    bots: (r.data?.bots ?? []).filter((b: any) => !!b?.name).map(_rawBotToListItem),
  }));

export const getBot = (name: string) =>
  client.get<any>(`/bots/${name}`).then((r) => {
    const b = r.data;
    return {
      profile: {
        id: b.id,
        name: b.name,
        description: b.description ?? "",
        asset_class: b.asset_class ?? "stock",
        position_cap: b.config?.position_cap ?? 10,
        cadence: b.config?.cadence ?? "daily",
        stop_loss_pct: b.config?.stop_loss_pct ?? null,
        take_profit_pct: b.config?.take_profit_pct ?? null,
        paper_only: true as const,
        enabled: b.enabled ?? true,
        config: b.config ?? {},
      } as BotProfile,
      allocation: b.allocation as BotAllocation | null,
      positions: (b.open_positions ?? []) as BotPosition[],
      signals: (b.recent_signals ?? []) as BotSignal[],
      stats: {
        return_30d_pct: b.return_30d_pct ?? 0,
        today_pnl: b.today_pnl_usd ?? 0,
        open_positions: Array.isArray(b.open_positions) ? b.open_positions.length : 0,
        win_rate_pct: b.win_rate_pct ?? 0,
        equity_curve: b.equity_curve ?? [],
        all_time_return_pct: b.all_time_return_pct ?? null,
        portfolio_value_cents: b.portfolio_value_cents ?? null,
      },
    };
  });

export const allocateBot = (
  name: string,
  data: { capital_pct: number; risk_profile: string; enabled: boolean }
) => client.post<BotAllocation>(`/bots/${name}/allocate`, data).then((r) => r.data);

export const joinWaitlist = (name: string) =>
  client.post(`/bots/waitlist/${name}`).then((r) => r.data);

export const leaveWaitlist = (name: string) =>
  client.delete(`/bots/waitlist/${name}`).then((r) => r.data);

export const migrateLegacyPositions = () =>
  client.post<{ status: string; migrated: Record<string, number>; message: string }>("/bots/migrate-legacy").then((r) => r.data);

export const getBotBacktest = (
  name: string,
  params: { from: string; to: string; capital: number }
) => client.get(`/bots/${name}/backtest`, { params }).then((r) => r.data);

// ─── New API additions ────────────────────────────────────────────────────────

export interface RegimeData {
  vix_regime: string;
  trend_regime: string;
  vol_pctile: number;
  btc_dominance: number;
  btc_funding_rate: number;
  ts: string;
}

export const getRegime = (): Promise<RegimeData> =>
  client
    .get<RegimeData>("/bots/regime")
    .then((r) => r.data)
    .catch(() => ({
      vix_regime: "mid",
      trend_regime: "chop",
      vol_pctile: 50,
      btc_dominance: 50,
      btc_funding_rate: 0,
      ts: new Date().toISOString(),
    }));

export interface WatchlistItem {
  symbol: string;
  score: number;
  rank: number | null;
  reasons: Record<string, number> | null;
  status: string;
  last_evaluated_at: string | null;
}

export const getBotWatchlist = (name: string): Promise<WatchlistItem[]> =>
  client
    .get(`/bots/${name}/watchlist`)
    .then((r) => {
      const d = r.data;
      if (Array.isArray(d)) return d;
      if (d && Array.isArray(d.watchlist)) return d.watchlist;
      return [];
    })
    .catch(() => []);

export interface ReadinessRow {
  symbol: string;
  current_price: number | null;
  change_24h_pct: number;
  strategy_being_evaluated: string;
  criteria_summary: string;
  criteria_status: string; // "triggered" | "watching"
  distance_to_trigger_pct: number;
  distance_to_trigger_label: string;
  distance_color: "green" | "yellow" | "gray";
  confidence_now: number;
  confidence_threshold: number;
  signal_strength_pct: number;
  last_scanned_at: string | null;
  rsi: number | null;
  zscore: number | null;
  criteria_need: string;
  criteria_current: string;
  gap_human: string;
  axis_current: number;
  axis_target: number;
  axis_unit: string;
  tier: "triggered" | "about_to_enter" | "close" | "waiting";
}

export interface ReadinessResponse {
  profile_name: string;
  rows: ReadinessRow[];
  cadence: string;
  no_universe?: boolean;
}

export const getBotWatchlistReadiness = (name: string): Promise<ReadinessResponse> =>
  client
    .get<ReadinessResponse>(`/bots/${name}/watchlist-readiness`)
    .then((r) => r.data);

export const runBacktest = (
  name: string,
  params: { start?: string; end?: string; capital?: number }
) =>
  client
    .get<any>(`/bots/${name}/backtest`, { params })
    .then((r) => r.data);

export const pauseAllBots = () =>
  client.post("/bots/pause-all").then((r) => r.data);

// ── Strategy trace ─────────────────────────────────────────────────────────────

export interface ConditionTrace {
  name: string;
  current_value: number;
  operator: string;
  required_value: number | number[] | null;
  unit: string;
  passed: boolean;
  to_pass: string;
  error?: string;
}

export interface StrategyTrace {
  name: string;
  key: string;
  weight: number;
  score: number;
  fired: boolean;
  side: "buy" | "sell" | "long" | "short" | null;
  summary: string;
  conditions: ConditionTrace[];
  error?: string;
}

export interface StrategyTraceResult {
  bot: string;
  symbol: string;
  scanned_at: string | null;
  scan_age_seconds: number | null;
  current_price: number | null;
  composite_score: number;
  threshold_to_fire: number;
  strategies_firing: number;
  total_strategies: number;
  would_fire: boolean;
  strategies: StrategyTrace[];
  error?: string;
}

export const getBotStrategyTrace = (
  botName: string,
  symbol: string,
): Promise<StrategyTraceResult> =>
  client
    .get<StrategyTraceResult>(`/bots/${botName}/strategy-trace`, { params: { symbol } })
    .then((r) => r.data);

export const getBotStrategyTraceBulk = (
  botName: string,
): Promise<{ bot: string; traces: StrategyTraceResult[] }> =>
  client
    .get<{ bot: string; traces: StrategyTraceResult[] }>(`/bots/${botName}/strategy-trace-bulk`)
    .then((r) => r.data);

export const resumeAllBots = () =>
  client.post("/bots/resume-all").then((r) => r.data);

export const activateAllBots = (): Promise<{ ok: boolean; total_profiles: number; activated: number }> =>
  client.post("/bots/activate-all").then((r) => r.data);

export interface StrategyPortfolio {
  id: number;
  name: string;
  asset_class: "stocks" | "crypto" | "options" | "quant";
  emoji: string;
  color_hex: string;
  starting_capital_cents: number;
  current_value_cents: number;
  pnl_cents: number;
  pnl_pct: number;
  enabled: boolean;
  bots: BotListItem[];
}

function _rawBotToListItem(b: any): BotListItem {
  return {
    profile: {
      id: b.id,
      name: b.name,
      description: b.description ?? "",
      asset_class: b.asset_class ?? "stock",
      position_cap: b.config?.position_cap ?? 10,
      cadence: b.config?.cadence ?? "daily",
      stop_loss_pct: b.config?.stop_loss_pct ?? null,
      take_profit_pct: b.config?.take_profit_pct ?? null,
      paper_only: true,
      enabled: b.enabled ?? true,
    },
    allocation: b.allocation ?? null,
    stats: {
      return_30d_pct: b.return_30d_pct ?? b.metrics?.return_30d ?? 0,
      today_pnl: b.today_pnl_usd ?? 0,
      open_positions: Array.isArray(b.open_positions) ? b.open_positions.length : 0,
      total_trades: b.total_trades ?? 0,
      win_rate_pct: b.win_rate_pct ?? 0,
      all_time_pnl_pct: b.all_time_pnl_pct ?? b.all_time_return_pct ?? null,
      all_time_pnl_usd: b.all_time_pnl_usd ?? null,
      starting_capital_usd: b.starting_capital_usd ?? null,
      current_equity_usd: b.current_equity_usd ?? null,
    },
  };
}

export const getPortfolios = (): Promise<{ portfolios: StrategyPortfolio[] }> =>
  client.get("/bots/portfolios").then((r) => {
    const raw = r.data as { portfolios: any[] };
    return {
      portfolios: (raw.portfolios ?? []).map((p: any) => ({
        ...p,
        bots: (p.bots ?? []).filter((b: any) => !!b?.name).map(_rawBotToListItem),
      })),
    };
  });

export const setupPortfolios = (): Promise<{ ok: boolean; portfolios: number }> =>
  client.post("/bots/portfolios/setup").then((r) => r.data);

export interface CatalystEvent {
  id: string | number;
  event_type: string;
  symbol: string | null;
  event_ts: string;
  description?: string;
}

export const getCatalysts = (): Promise<CatalystEvent[]> =>
  client
    .get<CatalystEvent[]>("/bots/catalysts")
    .then((r) => Array.isArray(r.data) ? r.data : [])
    .catch(() => []);

// ─── Activity ─────────────────────────────────────────────────────────────────

export interface ActivityEvent {
  id: string | number;
  ts: string;
  category: "signal" | "fill" | "skip" | string;
  symbol: string;
  side?: "buy" | "sell" | "long" | "short" | "hold";
  strategy?: string;
  reason?: string;
  result?: "filled" | "skipped" | "error";
  // fill-category extras
  qty?: number;
  fill_price?: number;
  pnl_usd?: number | null;
}

export const getActivity = (
  name: string,
  params?: { category?: string; limit?: number; page?: number }
): Promise<{ items: ActivityEvent[]; total: number }> =>
  client
    .get<any>(`/bots/${name}/activity`, { params })
    .then((r) => {
      const d = r.data as any;
      if (Array.isArray(d)) return { items: d as ActivityEvent[], total: d.length };
      return { items: (d?.items ?? []) as ActivityEvent[], total: d?.total ?? 0 };
    })
    .catch(() => ({ items: [], total: 0 }));

// ─── Strategy weights ─────────────────────────────────────────────────────────

export interface StrategyWeight {
  strategy: string;
  weight_pct: number;
  wins_30d: number;
  losses_30d: number;
  locked: boolean;
}

export const getStrategyWeights = (name: string): Promise<StrategyWeight[]> =>
  client
    .get<StrategyWeight[]>(`/bots/${name}/strategy-weights`)
    .then((r) => Array.isArray(r.data) ? r.data : [])
    .catch(() => []);

export const updateStrategyWeight = (
  name: string,
  strategy: string,
  data: { locked?: boolean; weight_pct?: number }
) =>
  client
    .patch<StrategyWeight>(`/bots/${name}/strategy-weights/${strategy}`, data)
    .then((r) => r.data);

// ─── Cross-bot positions ──────────────────────────────────────────────────────

export interface CrossBotPosition {
  symbol: string;
  total_qty: number;
  bots_holding: string[];
  exposure_pct: number;
  pnl: number;
}

export const getCrossBotPositions = (): Promise<CrossBotPosition[]> =>
  client
    .get<any>("/bots/cross-bot-positions")
    .then((r) => {
      const raw = Array.isArray(r.data) ? r.data
        : Array.isArray(r.data?.positions) ? r.data.positions
        : [];
      return raw.map((p: any): CrossBotPosition => ({
        symbol: p.symbol ?? "",
        total_qty: p.total_qty ?? 0,
        bots_holding: Array.isArray(p.bots_holding) ? p.bots_holding : Object.keys(p.by_bot ?? {}),
        exposure_pct: p.exposure_pct ?? p.net_exposure_pct ?? 0,
        pnl: p.pnl ?? 0,
      }));
    })
    .catch(() => []);

export interface CrossBotWatchlistItem {
  symbol: string;
  bots_watching: string[];
  score: number;
  status: string;
  reasons: string[];
  added_at: string | null;
}

export const getCrossBotWatchlist = (): Promise<CrossBotWatchlistItem[]> =>
  client
    .get<any>("/bots/cross-bot-watchlist")
    .then((r) => {
      const raw = Array.isArray(r.data) ? r.data : [];
      return raw.map((w: any): CrossBotWatchlistItem => ({
        symbol: w.symbol ?? "",
        bots_watching: Array.isArray(w.bots_watching) ? w.bots_watching : [],
        score: w.score ?? 0,
        status: w.status ?? "active",
        reasons: Array.isArray(w.reasons) ? w.reasons : [],
        added_at: w.added_at ?? null,
      }));
    })
    .catch(() => []);

// ─── Pending reviews (borderline signals) ────────────────────────────────────

export interface PendingReview {
  id: string | number;
  bot_name: string;
  symbol: string;
  ts: string;
  confidence: number;
  side: "buy" | "sell" | "long" | "short" | "hold";
  reason?: string;
}

export const getPendingReviews = (): Promise<PendingReview[]> =>
  client
    .get<PendingReview[]>("/bots/pending-reviews")
    .then((r) => Array.isArray(r.data) ? r.data : [])
    .catch(() => []);

// ─── Strategy Lab aggregate portfolio ────────────────────────────────────────

export interface PortfolioLeaderboardEntry {
  rank: number;
  profile: string;
  name: string;
  return_30d_pct: number;
  today_pnl_cents: number;
  watchlist_count: number;
  portfolio_value_cents: number;
}

export interface PortfolioData {
  total_value_cents: number;
  yesterday_value_cents: number;
  today_pnl_cents: number;
  today_pnl_pct: number;
  return_30d_pct: number;
  return_30d_value_cents: number;
  return_all_time_pct: number;
  sharpe_30d: number;
  total_open_positions: number;
  total_watchlist_count: number;
  equity_curve: Array<{ date: string; value_cents: number }>;
  leaderboard: PortfolioLeaderboardEntry[];
  best_performer: { profile: string; return_30d_pct: number } | null;
  worst_performer: { profile: string; return_30d_pct: number } | null;
}

// ─── Dashboard-specific types + fetchers ─────────────────────────────────────

export interface DashboardHealth {
  status: "ok" | "warn" | "critical";
  message: string;
  bots_active: number;
  bots_paused: number;
  bots_total: number;
  paused_bots: Array<{ name: string; reason: string }>;
}

export const getDashboardHealth = (): Promise<DashboardHealth> =>
  client
    .get<DashboardHealth>("/bots/dashboard-health")
    .then((r) => r.data)
    .catch((): DashboardHealth => ({
      status: "warn",
      message: "Could not load health",
      bots_active: 0,
      bots_paused: 0,
      bots_total: 0,
      paused_bots: [],
    }));

export interface RecentSignal {
  id: number;
  ts: string;
  bot_name: string;
  display_name: string;
  symbol: string;
  side: "buy" | "sell" | "long" | "short" | "hold";
  confidence: number;
  reason: string;
  strategy: string;
}

export const getRecentSignals = (limit = 20): Promise<{ signals: RecentSignal[] }> =>
  client
    .get<{ signals: RecentSignal[] }>("/bots/signals/recent", { params: { limit } })
    .then((r) => r.data)
    .catch(() => ({ signals: [] }));

export interface WatchlistMover {
  symbol: string;
  change_pct: number;
  portfolio: string;
  status: string;
  score: number;
}

export const getWatchlistMovers = (limit = 4): Promise<{ movers: WatchlistMover[] }> =>
  client
    .get<{ movers: WatchlistMover[] }>("/bots/watchlist/movers", { params: { limit } })
    .then((r) => r.data)
    .catch(() => ({ movers: [] }));

export const runBotNow = (profileName: string): Promise<{ ok: boolean; message: string }> =>
  client.post(`/bots/${profileName}/run-now`).then((r) => r.data);

export interface OpenPosition {
  position_id: number;
  trade_id: number;
  bot_name: string;
  bot_display: string;
  bot_color: string;
  asset_class: "stock" | "crypto" | "options" | "quant";
  symbol: string;
  side: "buy" | "sell" | "long" | "short";
  qty: number;
  entry_price: number;
  current_price: number;
  current_value_usd: number;
  unrealized_pnl_usd: number;
  unrealized_pnl_pct: number;
  price_source: "kraken" | "alpaca" | "stale" | "unavailable" | string;
  price_fetched_at: string;
  opened_at: string;
  held_seconds: number;
}

export interface OpenPositionsResponse {
  positions: OpenPosition[];
  total_unrealized_usd: number;
  total_unrealized_pct: number;
  position_count: number;
  distinct_bots: number;
  fetched_at: string;
}

export const getOpenPositions = (): Promise<OpenPositionsResponse> =>
  client
    .get<OpenPositionsResponse>("/portfolio/open-positions")
    .then((r) => r.data)
    .catch((): OpenPositionsResponse => ({
      positions: [],
      total_unrealized_usd: 0,
      total_unrealized_pct: 0,
      position_count: 0,
      distinct_bots: 0,
      fetched_at: new Date().toISOString(),
    }));

export const getStrategyLabPortfolio = (): Promise<PortfolioData> =>
  client
    .get<PortfolioData>("/strategy-lab/portfolio")
    .then((r) => r.data)
    .catch((err): PortfolioData => {
      console.error("[strategy-lab/portfolio] failed to load aggregate:", err);
      return {
        total_value_cents: 0,
        yesterday_value_cents: 0,
        today_pnl_cents: 0,
        today_pnl_pct: 0,
        return_30d_pct: 0,
        return_30d_value_cents: 0,
        return_all_time_pct: 0,
        sharpe_30d: 0,
        total_open_positions: 0,
        total_watchlist_count: 0,
        equity_curve: [],
        leaderboard: [],
        best_performer: null,
        worst_performer: null,
      };
    });

export interface TradeDetail {
  trade_id: number;
  position_id: number | null;
  symbol: string;
  side: string;
  qty: number;
  entry_price_usd: number;
  entry_time: string | null;
  status: "open" | "closed";
  stop_loss_usd: number | null;
  take_profit_usd: number | null;
  bot_profile: string | null;
  bot_display_name: string | null;
  strategy: string | null;
  reason: string | null;
  confidence: number | null;
  alpaca_order_id: string | null;
  discord_message_url: string | null;
  close_time: string | null;
  exit_price_usd: number | null;
  realized_pnl_usd: number | null;
}

export const getTradeDetail = (tradeId: number): Promise<TradeDetail> =>
  client.get<TradeDetail>(`/bots/trade/${tradeId}`).then((r) => r.data);

// ─── Signal feed (Mission Control Activity Feed) ──────────────────────────────

export interface SignalFeedItem {
  id: number;
  bot: string;
  bot_display: string;
  symbol: string;
  side: string;
  strategy: string;
  confidence: number;
  reason: string;
  entry_price: number | null;
  ts: string | null;
}

export const getSignalsFeed = (limit = 20): Promise<{ signals: SignalFeedItem[] }> =>
  client
    .get<{ signals: SignalFeedItem[] }>("/bots/signals/recent", { params: { limit } })
    .then((r) => r.data)
    .catch(() => ({ signals: [] }));
