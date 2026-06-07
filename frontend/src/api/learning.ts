import client from "./client";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface LessonSummary {
  id: number;
  slug: string;
  title: string;
  estimated_minutes: number | null;
  order: number;
  completed: boolean;
}

export interface ModuleSummary {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  order: number;
  estimated_hours: number | null;
  is_published: boolean;
  lesson_count: number;
  completed_count: number;
  lessons: LessonSummary[];
}

export interface LearningTrack {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  order: number;
  cert_tier: string | null;
  prereq_track_slugs: string[];
  estimated_hours: number | null;
  modules: ModuleSummary[];
  total_lessons: number;
  completed_lessons: number;
}

export interface LessonDetail {
  id: number;
  slug: string;
  title: string;
  content_md: string | null;
  video_url: string | null;
  exercise_md: string | null;
  quiz_json: QuizQuestion[] | null;
  estimated_minutes: number | null;
  order: number;
  completed: boolean;
  quiz_score: number | null;
  module_slug: string;
  track_slug: string;
  prev_lesson: { id: number; slug: string; title: string } | null;
  next_lesson: { id: number; slug: string; title: string } | null;
}

export interface QuizQuestion {
  question: string;
  options: string[];
  correct: number;
}

export interface LearningProgress {
  completed_lesson_ids: number[];
  completed_per_track: Record<string, number>;
  total_per_track: Record<string, number>;
  cert_eligibility: Record<string, boolean>;
}

// ── API functions ─────────────────────────────────────────────────────────────

export const getTracks = (): Promise<LearningTrack[]> =>
  client.get("/learning/tracks").then((r) => r.data);

export const getTrack = (trackSlug: string): Promise<LearningTrack> =>
  client.get(`/learning/tracks/${trackSlug}`).then((r) => r.data);

export const getModule = (trackSlug: string, moduleSlug: string): Promise<ModuleSummary> =>
  client.get(`/learning/tracks/${trackSlug}/modules/${moduleSlug}`).then((r) => r.data);

export const getLesson = (
  trackSlug: string,
  moduleSlug: string,
  lessonSlug: string
): Promise<LessonDetail> =>
  client
    .get(`/learning/tracks/${trackSlug}/modules/${moduleSlug}/lessons/${lessonSlug}`)
    .then((r) => r.data);

export const completeLesson = (
  lessonId: number,
  payload: { quiz_score?: number; time_spent_seconds?: number }
): Promise<{ ok: boolean; completed_at: string }> =>
  client.post(`/learning/lessons/${lessonId}/complete`, payload).then((r) => r.data);

export const getLearningProgress = (): Promise<LearningProgress> =>
  client.get("/learning/progress").then((r) => r.data);
