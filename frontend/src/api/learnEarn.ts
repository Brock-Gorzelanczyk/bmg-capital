import client from "./client";

export interface LearnLesson {
  lesson_id: string;
  title: string;
  description: string;
  sponsor: string | null;
  reward_amount: number;
  reward_symbol: string;
  question_count: number;
  already_completed: boolean;
}

export interface LessonDetail {
  lesson_id: string;
  title: string;
  description: string;
  sponsor: string | null;
  reward_amount: number;
  reward_symbol: string;
  quiz_questions: Array<{ question: string; options: string[] }>;
}

export interface CompleteResult {
  passed: boolean;
  score: number;
  total_questions: number;
  reward_amount: number | null;
  reward_symbol: string | null;
  correct_answers: number[];
  explanations: string[];
}

export interface EarnRewardItem {
  lesson_id: string;
  reward_amount: number | null;
  reward_symbol: string | null;
  status: string;
  earned_at: string;
}

export interface LearnEarnStats {
  total_earned: number;
  lessons_completed: number;
  lessons_available: number;
}

export const getLessons = () =>
  client.get<LearnLesson[]>("/learn-earn/lessons").then(r => r.data);

export const getLessonDetail = (id: string) =>
  client.get<LessonDetail>(`/learn-earn/lessons/${id}`).then(r => r.data);

export const completeLesson = (id: string, answers: number[]) =>
  client.post<CompleteResult>(`/learn-earn/lessons/${id}/complete`, { answers }).then(r => r.data);

export const getMyRewards = () =>
  client.get<EarnRewardItem[]>("/learn-earn/my-rewards").then(r => r.data);

export const getLearnEarnStats = () =>
  client.get<LearnEarnStats>("/learn-earn/stats").then(r => r.data);
