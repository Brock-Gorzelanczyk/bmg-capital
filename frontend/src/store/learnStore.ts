import { create } from "zustand";
import type { LearnProgress } from "@/types/learn";

interface LearnState {
  progress: LearnProgress | null;
  hydrated: boolean;
  setProgress: (p: LearnProgress) => void;
  markLesson: (lessonId: string, xp: number) => void;
  updateQuizBest: (lessonId: string, score: number) => void;
  addBadge: (badgeId: string) => void;
}

const DEFAULT_PROGRESS: LearnProgress = {
  xp: 0,
  level: 1,
  streak: 0,
  longestStreak: 0,
  streakFreezes: 2,
  lastActivityDate: null,
  selectedTrack: null,
  onboardingComplete: false,
  completedLessonIds: [],
  badges: [],
  quizBest: {},
};

export const useLearnStore = create<LearnState>((set, get) => ({
  progress: null,
  hydrated: false,

  setProgress: (p) => set({ progress: p, hydrated: true }),

  markLesson: (lessonId, xp) =>
    set((s) => {
      if (!s.progress) return s;
      const completedLessonIds = s.progress.completedLessonIds.includes(lessonId)
        ? s.progress.completedLessonIds
        : [...s.progress.completedLessonIds, lessonId];
      return {
        progress: { ...s.progress, xp: s.progress.xp + xp, completedLessonIds },
      };
    }),

  updateQuizBest: (lessonId, score) =>
    set((s) => {
      if (!s.progress) return s;
      const current = s.progress.quizBest[lessonId] ?? 0;
      if (score <= current) return s;
      return {
        progress: {
          ...s.progress,
          quizBest: { ...s.progress.quizBest, [lessonId]: score },
        },
      };
    }),

  addBadge: (badgeId) =>
    set((s) => {
      if (!s.progress || s.progress.badges.includes(badgeId)) return s;
      return {
        progress: { ...s.progress, badges: [...s.progress.badges, badgeId] },
      };
    }),
}));

export { DEFAULT_PROGRESS };
