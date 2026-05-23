export type NotifEventType =
  | "price_alert"
  | "signal"
  | "paper_fill"
  | "earnings"
  | "news"
  | "streak"
  | "xp_levelup"
  | "badge"
  | "system";

export type NotifChannel = "in_app" | "email" | "push";

export interface AppNotification {
  id: number;
  event_type: NotifEventType;
  title: string;
  body: string;
  is_read: boolean;
  meta: Record<string, unknown>;
  created_at: string;
}

export type NotifPrefs = Record<NotifEventType, Record<NotifChannel, boolean>>;

export interface NotifSettings {
  prefs: NotifPrefs;
  event_types: NotifEventType[];
  channels: NotifChannel[];
}

export const EVENT_LABELS: Record<NotifEventType, string> = {
  price_alert: "Price Alerts",
  signal: "Strategy Signals",
  paper_fill: "Paper Trade Fills",
  earnings: "Earnings Reminders",
  news: "Breaking News",
  streak: "Streak Milestones",
  xp_levelup: "Level Ups",
  badge: "New Badges",
  system: "System Messages",
};

export const EVENT_ICONS: Record<NotifEventType, string> = {
  price_alert: "🔔",
  signal: "⚡",
  paper_fill: "📄",
  earnings: "📅",
  news: "📰",
  streak: "🔥",
  xp_levelup: "⭐",
  badge: "🏅",
  system: "ℹ️",
};
