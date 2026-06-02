import client from "./client";

export interface BriefSection {
  id: string;
  title: string;
  icon: string;
  content: string;
  symbols: string[];
}

export interface DailyBrief {
  date: string;
  reading_level: string;
  generated_at: string;
  sections: BriefSection[];
  watchlist_symbols: string[];
}

export const getLatestBrief = (reading_level = "investor") =>
  client.get<DailyBrief>("/daily-brief/latest", { params: { reading_level } }).then(r => r.data);
