interface MarketData {
  indices: Array<{ symbol: string; name: string; change_pct: number; price: number }>;
  sectors: Array<{ sector: string; change_pct: number }>;
  topNews: string[]; // headlines
}

export function generateMorningBrief(data: MarketData, date: Date): string {
  const day = date.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const sp = data.indices.find((i) => i.symbol === "SPY");
  const qqq = data.indices.find((i) => i.symbol === "QQQ");
  const spChange = sp?.change_pct ?? 0;
  const qqqChange = qqq?.change_pct ?? 0;

  // Sort sectors
  const sortedSectors = [...data.sectors].filter((s) => s.change_pct !== undefined);
  const bestSector = sortedSectors.length
    ? [...sortedSectors].sort((a, b) => b.change_pct - a.change_pct)[0]
    : null;
  const worstSector = sortedSectors.length
    ? [...sortedSectors].sort((a, b) => a.change_pct - b.change_pct)[0]
    : null;

  const marketSentiment: "risk-on" | "risk-off" | "mixed" =
    spChange > 0.5 ? "risk-on" : spChange < -0.5 ? "risk-off" : "mixed";

  const spDesc =
    spChange > 0
      ? `up ${spChange.toFixed(2)}%`
      : `down ${Math.abs(spChange).toFixed(2)}%`;
  const qqqDesc =
    qqqChange > 0
      ? `gaining ${qqqChange.toFixed(2)}%`
      : `falling ${Math.abs(qqqChange).toFixed(2)}%`;

  const sentimentTemplates: Record<"risk-on" | "risk-off" | "mixed", string> = {
    "risk-on": `Markets are showing strength this ${day}. `,
    "risk-off": `Markets are under pressure this ${day}. `,
    mixed: `Markets are trading in a mixed fashion this ${day}. `,
  };

  const sectorLine =
    bestSector && worstSector && bestSector.sector !== worstSector.sector
      ? `${bestSector.sector.replace("Select Sector SPDR Fund", "").replace("SPDR", "").trim()} leads today's gainers (+${bestSector.change_pct.toFixed(1)}%) while ${worstSector.sector.replace("Select Sector SPDR Fund", "").replace("SPDR", "").trim()} lags (${worstSector.change_pct.toFixed(1)}%). `
      : "";

  const newsLine = data.topNews[0]
    ? `In the news: ${data.topNews[0].slice(0, 120)}${data.topNews[0].length > 120 ? "..." : ""}`
    : "";

  const lines = [
    sentimentTemplates[marketSentiment],
    `The S&P 500 is ${spDesc}, while the Nasdaq is ${qqqDesc}. `,
    sectorLine,
    newsLine,
  ];

  return lines.filter(Boolean).join("");
}
