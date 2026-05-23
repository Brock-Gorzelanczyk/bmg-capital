export type LessonType = "article" | "video" | "interactive" | "challenge";
export type Difficulty = "beginner" | "intermediate" | "advanced" | "pro";

export interface QuizQuestion {
  id: string;
  question: string;
  options: string[];
  answer: number; // 0-indexed correct option
  explanation?: string;
}

export interface PaperChallenge {
  description: string;
  symbol?: string;
  task: string;
  successCriteria?: string;
}

export interface Lesson {
  id: string;
  courseId: string;
  trackId: string;
  title: string;
  type: LessonType;
  xp: number;
  durationMin: number;
  body: string; // HTML
  videoUrl?: string;
  quiz: QuizQuestion[];
  challenge?: PaperChallenge;
  tags?: string[];
}

export interface Course {
  id: string;
  trackId: string;
  title: string;
  description: string;
  lessonIds: string[];
  xpTotal: number;
}

export interface Track {
  id: string;
  title: string;
  description: string;
  icon: string;
  difficulty: Difficulty;
  colorClass: string; // Tailwind text/bg color stem
  courseIds: string[];
}

// ── Progress (frontend shape, mirrored from API) ─────────────────────────────
export interface LearnProgress {
  xp: number;
  level: number;
  streak: number;
  longestStreak: number;
  streakFreezes: number;
  lastActivityDate: string | null; // YYYY-MM-DD UTC
  selectedTrack: string | null;
  onboardingComplete: boolean;
  completedLessonIds: string[];
  badges: string[];
  quizBest: Record<string, number>; // lessonId → best score 0-1
}

export interface LeaderboardEntry {
  userId: number;
  username: string;
  xp: number;
  streak: number;
  rank: number;
}

export const LEVEL_THRESHOLDS = [0, 150, 400, 800, 1500, 2500, 4000, 6000, 9000, 13000, 20000];

export function xpToLevel(xp: number): number {
  for (let i = LEVEL_THRESHOLDS.length - 1; i >= 0; i--) {
    if (xp >= LEVEL_THRESHOLDS[i]) return i + 1;
  }
  return 1;
}

export function xpProgressInLevel(xp: number): { level: number; pct: number; needed: number; floor: number } {
  const level = xpToLevel(xp);
  const floor = LEVEL_THRESHOLDS[level - 1] ?? 0;
  const ceiling = LEVEL_THRESHOLDS[level] ?? LEVEL_THRESHOLDS[LEVEL_THRESHOLDS.length - 1];
  const pct = ceiling === floor ? 100 : Math.min(100, ((xp - floor) / (ceiling - floor)) * 100);
  return { level, pct, needed: ceiling - xp, floor };
}

// Deterministic seeded shuffle for quiz options — scores are reproducible
export function shuffleQuizQuestion(q: QuizQuestion, seed: number): QuizQuestion {
  let s = seed;
  const rng = () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 0x100000000; };
  const idx = [0, 1, 2, 3].slice(0, q.options.length);
  for (let i = idx.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [idx[i], idx[j]] = [idx[j], idx[i]];
  }
  return {
    ...q,
    options: idx.map(i => q.options[i]),
    answer: idx.indexOf(q.answer),
  };
}

export const BADGE_META: Record<string, { label: string; icon: string; description: string }> = {
  first_lesson:    { label: "First Step",       icon: "🎯", description: "Completed your first lesson" },
  streak_3:        { label: "On a Roll",         icon: "🔥", description: "3-day learning streak" },
  streak_7:        { label: "Week Warrior",      icon: "⚡", description: "7-day learning streak" },
  streak_30:       { label: "Iron Discipline",   icon: "🏆", description: "30-day learning streak" },
  first_course:    { label: "Graduate",          icon: "🎓", description: "Completed a full course" },
  first_quiz_100:  { label: "Perfect Score",     icon: "💯", description: "100% on a quiz" },
  paper_trade:     { label: "Paper Hands",       icon: "📄", description: "Completed a paper trade challenge" },
  level_5:         { label: "Rising Analyst",    icon: "📈", description: "Reached Level 5" },
  level_10:        { label: "Market Scholar",    icon: "🦉", description: "Reached Level 10" },
  daily_challenge: { label: "Daily Grind",       icon: "📅", description: "Completed a daily challenge" },
};
