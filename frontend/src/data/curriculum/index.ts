import type { Track, Course, Lesson } from "@/types/learn";
import * as investingFundamentals from "./tracks/investing-fundamentals";
import * as technicalAnalysis from "./tracks/technical-analysis";
import * as fundamentalAnalysis from "./tracks/fundamental-analysis";
import * as optionsBasics from "./tracks/options-basics";
import * as portfolioRisk from "./tracks/portfolio-risk";
import * as behavioralFinance from "./tracks/behavioral-finance";
import * as taxes from "./tracks/taxes";
import * as crypto from "./tracks/crypto";
import * as macro from "./tracks/macro";

const ALL_MODULES = [
  investingFundamentals,
  technicalAnalysis,
  fundamentalAnalysis,
  optionsBasics,
  portfolioRisk,
  behavioralFinance,
  taxes,
  crypto,
  macro,
];

export const TRACKS: Track[] = ALL_MODULES.map((m) => m.track);

export const COURSES: Course[] = ALL_MODULES.flatMap((m) => m.courses);

export const LESSONS: Lesson[] = ALL_MODULES.flatMap((m) => m.lessons);

// O(1) lookup maps
export const TRACK_MAP: Record<string, Track> = Object.fromEntries(TRACKS.map((t) => [t.id, t]));
export const COURSE_MAP: Record<string, Course> = Object.fromEntries(COURSES.map((c) => [c.id, c]));
export const LESSON_MAP: Record<string, Lesson> = Object.fromEntries(LESSONS.map((l) => [l.id, l]));

/** All lessons belonging to a course */
export function lessonsForCourse(courseId: string): Lesson[] {
  const course = COURSE_MAP[courseId];
  if (!course) return [];
  return course.lessonIds.map((id) => LESSON_MAP[id]).filter(Boolean);
}

/** All courses belonging to a track */
export function coursesForTrack(trackId: string): Course[] {
  const track = TRACK_MAP[trackId];
  if (!track) return [];
  return track.courseIds.map((id) => COURSE_MAP[id]).filter(Boolean);
}

/** All lessons belonging to a track (flattened) */
export function lessonsForTrack(trackId: string): Lesson[] {
  return coursesForTrack(trackId).flatMap((c) => lessonsForCourse(c.id));
}

/** Total XP available in a track */
export function trackTotalXP(trackId: string): number {
  return coursesForTrack(trackId).reduce((sum, c) => sum + c.xpTotal, 0);
}

/** Fraction of a track completed (0–1) */
export function trackProgress(trackId: string, completedIds: string[]): number {
  const lessonIds = lessonsForTrack(trackId).map((l) => l.id);
  if (!lessonIds.length) return 0;
  const done = lessonIds.filter((id) => completedIds.includes(id)).length;
  return done / lessonIds.length;
}

/** Fraction of a course completed (0–1) */
export function courseProgress(courseId: string, completedIds: string[]): number {
  const ids = lessonsForCourse(courseId).map((l) => l.id);
  if (!ids.length) return 0;
  const done = ids.filter((id) => completedIds.includes(id)).length;
  return done / ids.length;
}

/** Next incomplete lesson in a track (for "Resume" CTA) */
export function nextLesson(trackId: string, completedIds: string[]): Lesson | null {
  return lessonsForTrack(trackId).find((l) => !completedIds.includes(l.id)) ?? null;
}

/** All lesson IDs in the curriculum (for total count) */
export const TOTAL_LESSON_COUNT = LESSONS.length;
