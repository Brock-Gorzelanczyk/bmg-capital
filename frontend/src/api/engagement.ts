import client from "./client";

export interface TodayChallenge {
  challenge_id: number;
  challenge_type: "chart_pattern" | "predict_close" | "earnings_beat" | "10k_translation" | "strategy_fit" | "risk_check" | "greek_check";
  question: string;
  options: string[];
  category: string;
  difficulty: "beginner" | "intermediate" | "advanced";
  already_answered: boolean;
  result: {
    choice_idx: number;
    correct: boolean;
    explanation: string;
    share_emoji: string;
  } | null;
}

export interface AttemptResult {
  correct: boolean;
  explanation: string;
  xp_earned: number;
  new_streak: number;
  share_emoji: string;
  badges_earned: string[];
}

export interface StreakState {
  current_streak: number;
  longest_streak: number;
  freezes_remaining: number;
  last_activity_date: string | null;
  total_active_days: number;
  active_this_month: number;
}

export interface Achievement {
  id: string;
  name: string;
  description: string;
  category: string;
  icon_emoji: string;
  unlocked: boolean;
  unlocked_at: string | null;
  progress: number;
  max_progress: number;
}

export interface LeagueState {
  tier: string;
  cohort_rank: number;
  points_this_week: number;
  promotion_zone: boolean;
  demotion_zone: boolean;
  next_reset_at: string;
  cohort: Array<{ username: string; points: number; rank: number; is_me: boolean }>;
}

export interface WeeklyRecap {
  week_label: string;
  trades_count: number;
  lessons_completed: number;
  challenges_correct: number;
  challenges_attempted: number;
  streak_days: number;
  points_earned: number;
  top_mover: { symbol: string; pct: number } | null;
  journal_entries: number;
}

export interface AnnualRecap {
  year: number;
  total_trades: number;
  learning_hours: number;
  most_watched_ticker: string | null;
  best_position: { symbol: string; pct_gain: number } | null;
  avg_hold_days: number;
  sector_personality: string;
  longest_streak: number;
  total_active_days: number;
  achievements_count: number;
  shareable_text: string;
}

export const getTodayChallenge = () =>
  client.get<TodayChallenge>("/engagement/challenge/today").then(r => r.data);

export const submitChallengeAttempt = (challenge_id: number, choice_idx: number) =>
  client.post<AttemptResult>("/engagement/challenge/attempt", { challenge_id, choice_idx }).then(r => r.data);

export const getStreak = () =>
  client.get<StreakState>("/engagement/streak").then(r => r.data);

export const logActivity = (activity_type: string) =>
  client.post<{ streak_updated: boolean; current_streak: number; points_earned: number }>("/engagement/streak/activity", { activity_type }).then(r => r.data);

export const getAchievements = () =>
  client.get<{ achievements: Achievement[] }>("/engagement/achievements").then(r => r.data);

export const getLeague = () =>
  client.get<LeagueState>("/engagement/leagues/me").then(r => r.data);

export const getWeeklyRecap = () =>
  client.get<WeeklyRecap>("/engagement/recap/weekly").then(r => r.data);

export const getAnnualRecap = () =>
  client.get<AnnualRecap>("/engagement/recap/annual").then(r => r.data);
