const NASDAQ = new Set([
  "AAPL","MSFT","GOOGL","GOOG","AMZN","META","NVDA","TSLA","AMD","NFLX",
  "INTC","CSCO","ADBE","CMCSA","PEP","COST","QCOM","TXN","AVGO","SBUX",
  "MU","BKNG","PYPL","PANW","KLAC","LRCX","MRVL","SNPS","CDNS","ASML",
  "ADP","REGN","GILD","BIIB","MRNA","ABNB","DDOG","CRWD","ZM","TEAM",
  "OKTA","SPLK","WDAY","VEEV","HUBS","DOCU","ZS","NET","SNOW","PLTR",
]);

export function mapToTvSymbol(symbol: string): string {
  const s = symbol.toUpperCase().trim();

  // Already in EXCHANGE:SYMBOL format
  if (s.includes(":")) return s;

  // Crypto: BTC-USD → BINANCE:BTCUSDT, ETH-USD → BINANCE:ETHUSDT
  if (s.endsWith("-USD") || s.endsWith("-USDT")) {
    const base = s.replace(/-USD(T)?$/, "");
    return `BINANCE:${base}USDT`;
  }
  // BTC/USD slash format
  if (s.includes("/")) {
    const base = s.split("/")[0];
    return `BINANCE:${base}USDT`;
  }

  return NASDAQ.has(s) ? `NASDAQ:${s}` : `NYSE:${s}`;
}
