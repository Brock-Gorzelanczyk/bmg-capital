interface MarketData {
  indices: Array<{ symbol: string; name: string; change_pct: number; price: number }>;
  sectors: Array<{ sector: string; change_pct: number }>;
  topNews: string[];
}

function isMarketOpen(date: Date): boolean {
  const et = new Date(date.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay(); // 0 = Sun, 6 = Sat
  const mins = et.getHours() * 60 + et.getMinutes();
  return day >= 1 && day <= 5 && mins >= 570 && mins < 960; // 9:30–4:00 ET
}

function isWeekend(date: Date): boolean {
  const et = new Date(date.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay();
  return day === 0 || day === 6;
}

function lastTradingDay(date: Date): string {
  const et = new Date(date.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay();
  // Saturday → Friday, Sunday → Friday, any weekday after close → same day
  const offset = day === 6 ? 1 : day === 0 ? 2 : 0;
  const last = new Date(et);
  last.setDate(last.getDate() - offset);
  return last.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
}

export function generateMorningBrief(data: MarketData, date: Date): string {
  const dayLabel = date.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const sp = data.indices.find((i) => i.symbol === "SPY");
  const qqq = data.indices.find((i) => i.symbol === "QQQ");
  const spChange = sp?.change_pct ?? 0;
  const qqqChange = qqq?.change_pct ?? 0;

  const sortedSectors = [...data.sectors].filter((s) => s.change_pct !== undefined);
  const bestSector = sortedSectors.length
    ? [...sortedSectors].sort((a, b) => b.change_pct - a.change_pct)[0]
    : null;
  const worstSector = sortedSectors.length
    ? [...sortedSectors].sort((a, b) => a.change_pct - b.change_pct)[0]
    : null;

  const spDesc = spChange > 0 ? `up ${spChange.toFixed(2)}%` : `down ${Math.abs(spChange).toFixed(2)}%`;
  const qqqDesc = qqqChange > 0 ? `gaining ${qqqChange.toFixed(2)}%` : `falling ${Math.abs(qqqChange).toFixed(2)}%`;

  const sectorLine =
    bestSector && worstSector && bestSector.sector !== worstSector.sector
      ? `${bestSector.sector.replace("Select Sector SPDR Fund", "").replace("SPDR", "").trim()} led Friday's gainers (+${bestSector.change_pct.toFixed(1)}%) while ${worstSector.sector.replace("Select Sector SPDR Fund", "").replace("SPDR", "").trim()} lagged (${worstSector.change_pct.toFixed(1)}%). `
      : "";

  const newsLine = data.topNews[0]
    ? `In the news: ${data.topNews[0].slice(0, 120)}${data.topNews[0].length > 120 ? "..." : ""}`
    : "";

  // Weekend — show last close recap instead of live market language
  if (isWeekend(date)) {
    const lastDay = lastTradingDay(date);
    const lines = [
      `Markets are closed today (${dayLabel}). `,
      `At ${lastDay}'s close, the S&P 500 finished ${spDesc} and the Nasdaq was ${qqqDesc}. `,
      sectorLine,
      newsLine,
    ];
    return lines.filter(Boolean).join("");
  }

  // Weekday pre-market or after-hours
  const et = new Date(date.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const mins = et.getHours() * 60 + et.getMinutes();
  const isPreMarket = mins < 570;
  const isAfterHours = mins >= 960;

  if (isPreMarket) {
    const lines = [
      `Good morning — markets open in ${Math.floor((570 - mins) / 60)}h ${(570 - mins) % 60}m. `,
      `At yesterday's close, the S&P 500 was ${spDesc} and the Nasdaq was ${qqqDesc}. `,
      sectorLine,
      newsLine,
    ];
    return lines.filter(Boolean).join("");
  }

  if (isAfterHours) {
    const lines = [
      `Markets closed for the day (${dayLabel}). `,
      `The S&P 500 finished ${spDesc} and the Nasdaq closed ${qqqDesc}. `,
      sectorLine,
      newsLine,
    ];
    return lines.filter(Boolean).join("");
  }

  // Market hours — live language
  const marketSentiment: "risk-on" | "risk-off" | "mixed" =
    spChange > 0.5 ? "risk-on" : spChange < -0.5 ? "risk-off" : "mixed";

  const sentimentOpener: Record<"risk-on" | "risk-off" | "mixed", string> = {
    "risk-on": `Markets are pushing higher this ${dayLabel}. `,
    "risk-off": `Markets are under pressure this ${dayLabel}. `,
    mixed: `Markets are mixed this ${dayLabel}. `,
  };

  const liveSectorLine =
    bestSector && worstSector && bestSector.sector !== worstSector.sector
      ? `${bestSector.sector.replace("Select Sector SPDR Fund", "").replace("SPDR", "").trim()} leads today's gainers (+${bestSector.change_pct.toFixed(1)}%) while ${worstSector.sector.replace("Select Sector SPDR Fund", "").replace("SPDR", "").trim()} lags (${worstSector.change_pct.toFixed(1)}%). `
      : "";

  return [
    sentimentOpener[marketSentiment],
    `The S&P 500 is ${spDesc}, while the Nasdaq is ${qqqDesc}. `,
    liveSectorLine,
    newsLine,
  ].filter(Boolean).join("");
}
