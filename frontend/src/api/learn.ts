import client from "./client";
import type { LearnProgress, LeaderboardEntry } from "@/types/learn";

export const getProgress = (): Promise<LearnProgress> =>
  client.get("/learn/progress").then((r) => r.data);

export const completeLesson = (lessonId: string, xpEarned: number) =>
  client.post(`/learn/complete/${lessonId}`, { xp_earned: xpEarned }).then((r) => r.data);

export const submitQuiz = (lessonId: string, score: number) =>
  client.post(`/learn/quiz/${lessonId}`, { score }).then((r) => r.data);

export const getBadges = (): Promise<string[]> =>
  client.get("/learn/badges").then((r) => r.data);

export const completeOnboarding = (trackId: string) =>
  client.post("/learn/onboarding", { track_id: trackId }).then((r) => r.data);

export const getLeaderboard = (): Promise<LeaderboardEntry[]> =>
  client.get("/learn/leaderboard").then((r) => r.data);

export const getDailyChallenge = () =>
  client.get("/learn/daily").then((r) => r.data);

export const useStreakFreeze = () =>
  client.post("/learn/freeze").then((r) => r.data);
