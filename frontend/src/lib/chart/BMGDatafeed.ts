/**
 * TradingView Advanced Charts datafeed adapter.
 * Connects the TV library to BMG Capital's backend API.
 */

const TF_MAP: Record<string, string> = {
  "1":   "1Min",
  "5":   "5Min",
  "15":  "15Min",
  "30":  "30Min",
  "60":  "1Hour",
  "240": "4Hour",
  "1D":  "1Day",
  "1W":  "1Week",
  "1M":  "1Month",
};

// Polling interval per timeframe (ms) for live bar updates
const POLL_INTERVAL: Record<string, number> = {
  "1Min":   5_000,
  "5Min":  15_000,
  "15Min": 30_000,
  "30Min": 60_000,
  "1Hour": 60_000,
  "4Hour": 120_000,
  "1Day":  60_000,
  "1Week": 300_000,
  "1Month": 600_000,
};

async function apiFetch<T>(url: string): Promise<T> {
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json() as Promise<T>;
}

export class BMGDatafeed {
  private subs: Record<string, ReturnType<typeof setInterval>> = {};

  onReady(cb: (config: object) => void): void {
    setTimeout(
      () =>
        cb({
          supported_resolutions: ["1", "5", "15", "30", "60", "240", "1D", "1W", "1M"],
          supports_search: true,
          supports_marks: true,
          supports_timescale_marks: true,
          supports_time: true,
          exchanges: [
            { value: "", name: "All Exchanges", desc: "" },
            { value: "NYSE", name: "NYSE", desc: "New York Stock Exchange" },
            { value: "NASDAQ", name: "NASDAQ", desc: "NASDAQ" },
            { value: "CRYPTO", name: "Crypto", desc: "Crypto" },
          ],
          symbols_types: [
            { value: "", name: "All types" },
            { value: "stock", name: "Stock" },
            { value: "crypto", name: "Crypto" },
            { value: "etf", name: "ETF" },
          ],
        }),
      0,
    );
  }

  async searchSymbols(
    input: string,
    exchange: string,
    symbolType: string,
    onResult: (results: object[]) => void,
  ): Promise<void> {
    try {
      const url =
        `/api/symbols/search?q=${encodeURIComponent(input)}` +
        `&exchange=${exchange || ""}&type=${symbolType || ""}`;
      const data = await apiFetch<{ results: any[] }>(url);
      onResult(
        (data.results || []).map((s) => ({
          symbol: s.symbol,
          full_name: `${s.exchange}:${s.symbol}`,
          description: s.name || s.description || s.symbol,
          exchange: s.exchange,
          ticker: s.symbol,
          type: s.type || "stock",
        })),
      );
    } catch {
      onResult([]);
    }
  }

  async resolveSymbol(
    symbolName: string,
    onResolve: (info: object) => void,
    onError: (err: string) => void,
  ): Promise<void> {
    try {
      const ticker = symbolName.includes(":") ? symbolName.split(":")[1] : symbolName;
      const r = await apiFetch<any>(`/api/symbols/${encodeURIComponent(ticker)}/info`);
      const isCrypto = r.type === "crypto" || ticker.includes("-");
      onResolve({
        name: r.symbol,
        ticker: r.symbol,
        description: r.name || r.symbol,
        type: r.type || "stock",
        session: isCrypto ? "24x7" : "0930-1600",
        timezone: "America/New_York",
        exchange: r.exchange || "NYSE",
        listed_exchange: r.exchange || "NYSE",
        minmov: 1,
        pricescale: r.pricescale ?? (isCrypto ? 100000 : 100),
        has_intraday: true,
        has_daily: true,
        has_weekly_and_monthly: true,
        supported_resolutions: ["1", "5", "15", "30", "60", "240", "1D", "1W", "1M"],
        volume_precision: 0,
        data_status: "streaming",
      });
    } catch (e) {
      onError(String(e));
    }
  }

  async getBars(
    symbolInfo: any,
    resolution: string,
    periodParams: { from: number; to: number; countBack?: number; firstDataRequest?: boolean },
    onResult: (bars: object[], meta: { noData: boolean }) => void,
    onError: (err: string) => void,
  ): Promise<void> {
    const { from, to, countBack } = periodParams;
    const tf = TF_MAP[resolution] || "1Day";

    try {
      const url =
        `/api/bars/${encodeURIComponent(symbolInfo.ticker)}` +
        `?timeframe=${tf}&from=${from}&to=${to}` +
        `&limit=${countBack || 5000}&adjustment=split`;
      const data = await apiFetch<{ bars: any[] }>(url);
      const bars = (data.bars || []).map((b: any) => ({
        time: new Date(b.t).getTime(),
        open: b.o,
        high: b.h,
        low: b.l,
        close: b.c,
        volume: b.v || 0,
      }));
      onResult(bars, { noData: bars.length === 0 });
    } catch (e) {
      onError(String(e));
    }
  }

  subscribeBars(
    symbolInfo: any,
    resolution: string,
    onTick: (bar: object) => void,
    listenerGuid: string,
  ): void {
    const tf = TF_MAP[resolution] || "1Day";
    const pollMs = POLL_INTERVAL[tf] || 30_000;

    const interval = setInterval(async () => {
      try {
        const url =
          `/api/bars/${encodeURIComponent(symbolInfo.ticker)}` +
          `?timeframe=${tf}&limit=2&adjustment=split`;
        const data = await apiFetch<{ bars: any[] }>(url);
        const latest = data.bars?.[data.bars.length - 1];
        if (latest) {
          onTick({
            time: new Date(latest.t).getTime(),
            open: latest.o,
            high: latest.h,
            low: latest.l,
            close: latest.c,
            volume: latest.v || 0,
          });
        }
      } catch {
        // silent — network blip
      }
    }, pollMs);

    this.subs[listenerGuid] = interval;
  }

  unsubscribeBars(listenerGuid: string): void {
    clearInterval(this.subs[listenerGuid]);
    delete this.subs[listenerGuid];
  }

  async getMarks(
    symbolInfo: any,
    from: number,
    to: number,
    onDataCallback: (marks: object[]) => void,
    _resolution: string,
  ): Promise<void> {
    try {
      const url = `/api/bot-trades?symbol=${encodeURIComponent(symbolInfo.ticker)}&from=${from}&to=${to}`;
      const data = await apiFetch<{ trades: any[] }>(url);
      onDataCallback(
        (data.trades || []).map((t: any) => ({
          id: t.id,
          time: Math.floor(new Date(t.ts).getTime() / 1000),
          color: t.side === "buy" ? "green" : "red",
          text: `${t.bot_name} ${(t.side || "").toUpperCase()} ${t.qty ?? ""} @ $${Number(t.price || 0).toFixed(2)}`,
          label: t.side === "buy" ? "B" : "S",
          labelFontColor: "#fff",
          minSize: 22,
        })),
      );
    } catch {
      onDataCallback([]);
    }
  }

  async getTimescaleMarks(
    symbolInfo: any,
    from: number,
    to: number,
    onDataCallback: (marks: object[]) => void,
    _resolution: string,
  ): Promise<void> {
    try {
      const url = `/api/bot-signals?symbol=${encodeURIComponent(symbolInfo.ticker)}&from=${from}&to=${to}`;
      const data = await apiFetch<{ signals: any[] }>(url);
      onDataCallback(
        (data.signals || []).map((s: any) => ({
          id: s.id,
          time: Math.floor(new Date(s.ts).getTime() / 1000),
          color: s.side === "buy" ? "#9333EA" : "#F97316",
          label: (s.strategy || "").slice(0, 2).toUpperCase() || "SG",
          tooltip: [
            `${s.bot_name} · ${s.strategy || ""}`,
            `Confidence: ${((s.confidence || 0) * 100).toFixed(0)}%`,
            s.entry_price ? `Entry: $${s.entry_price}` : "",
            s.stop_price ? `Stop: $${s.stop_price}` : "",
            s.target_price ? `Target: $${s.target_price}` : "",
          ].filter(Boolean),
        })),
      );
    } catch {
      onDataCallback([]);
    }
  }

  getServerTime(cb: (ts: number) => void): void {
    cb(Math.floor(Date.now() / 1000));
  }
}
