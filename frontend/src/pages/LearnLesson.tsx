import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, CheckCircle2, Clock, Zap,
  BookOpen, Video, FlaskConical, Trophy, ExternalLink, Award, Bot,
} from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { completeLesson, submitQuiz } from "@/api/learn";
import { useLearnStore } from "@/store/learnStore";
import { LESSON_MAP, COURSE_MAP, TRACK_MAP, lessonsForCourse } from "@/data/curriculum";
import { BADGE_META } from "@/types/learn";
import QuizBlock from "@/components/learn/QuizBlock";
import XPToast from "@/components/learn/XPToast";
import CertificateGenerator from "@/components/learn/CertificateGenerator";
import { cn } from "@/lib/utils";

function sanitizeHtml(html: string): string {
  // Remove script tags and event handlers
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/\son\w+\s*=\s*["'][^"']*["']/gi, '')
    .replace(/javascript:/gi, '');
}

const TYPE_ICON: Record<string, React.ReactNode> = {
  article: <BookOpen size={14} />,
  video: <Video size={14} />,
  challenge: <FlaskConical size={14} />,
  interactive: <Zap size={14} />,
};

export default function LearnLesson() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { progress, setProgress, markLesson, updateQuizBest, addBadge } = useLearnStore();
  const bodyRef = useRef<HTMLDivElement>(null);

  const [quizDone, setQuizDone] = useState(false);
  const [quizScore, setQuizScore] = useState<number | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [showXP, setShowXP] = useState(false);
  const [earnedXP, setEarnedXP] = useState(0);
  const [newBadges, setNewBadges] = useState<string[]>([]);
  const [lessonComplete, setLessonComplete] = useState(false);
  const [showCert, setShowCert] = useState(false);

  const lesson = lessonId ? LESSON_MAP[lessonId] : null;
  const course = lesson ? COURSE_MAP[lesson.courseId] : null;
  const track = course ? TRACK_MAP[course.trackId] : null;
  const siblings = course ? lessonsForCourse(course.id) : [];
  const siblingIdx = siblings.findIndex((l) => l.id === lesson?.id);
  const prevLesson = siblings[siblingIdx - 1] ?? null;
  const nextLessonItem = siblings[siblingIdx + 1] ?? null;

  const completedIds = progress?.completedLessonIds ?? [];
  const alreadyComplete = lesson ? completedIds.includes(lesson.id) : false;

  useEffect(() => {
    if (alreadyComplete) setLessonComplete(true);
    if (lesson?.quiz.length === 0) setQuizDone(true);
    // Scroll to top on lesson change
    bodyRef.current?.scrollTo(0, 0);
  }, [lessonId, alreadyComplete]);

  const completeMut = useMutation({
    mutationFn: ({ id, xp }: { id: string; xp: number }) => completeLesson(id, xp),
    onSuccess: (d) => {
      if (d.progress) {
        setProgress(d.progress);
        qc.invalidateQueries({ queryKey: ["learn-progress"] });
      }
      if (d.newBadges?.length) {
        setNewBadges(d.newBadges);
        d.newBadges.forEach((b: string) => addBadge(b));
      }
    },
  });

  const quizMut = useMutation({
    mutationFn: ({ id, score }: { id: string; score: number }) => submitQuiz(id, score),
    onSuccess: (d, vars) => {
      updateQuizBest(vars.id, vars.score);
      if (d.newBadges?.length) {
        setNewBadges((prev) => [...prev, ...d.newBadges]);
        d.newBadges.forEach((b: string) => addBadge(b));
      }
    },
  });

  const handleQuizComplete = (score: number) => {
    setQuizScore(score);
    setQuizDone(true);
    if (lesson) quizMut.mutate({ id: lesson.id, score });
  };

  const handleMarkComplete = () => {
    if (!lesson || alreadyComplete) return;
    setLessonComplete(true);
    setEarnedXP(lesson.xp);
    setShowXP(true);
    markLesson(lesson.id, lesson.xp);
    completeMut.mutate({ id: lesson.id, xp: lesson.xp });
  };

  if (!lesson || !course || !track) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--text-tertiary)]">
        Lesson not found.{" "}
        <button className="ml-2 text-[var(--text-primary)] underline" onClick={() => navigate("/learn")}>
          Back to Learn
        </button>
      </div>
    );
  }

  const canComplete = !alreadyComplete && (lesson.quiz.length === 0 || quizDone);

  return (
    <div className="max-w-2xl mx-auto pb-20 md:pb-8">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)] mb-6">
        <button onClick={() => navigate("/learn")} className="hover:text-[var(--text-primary)] transition-colors">Learn</button>
        <ChevronRight size={12} />
        <button onClick={() => navigate(`/learn/${track.id}`)} className="hover:text-[var(--text-primary)] transition-colors">{track.title}</button>
        <ChevronRight size={12} />
        <span className="text-[var(--text-tertiary)]">{course.title}</span>
      </div>

      {/* Lesson header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <span className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">
            {TYPE_ICON[lesson.type]} {lesson.type}
          </span>
          <span className="text-[var(--text-tertiary)]">·</span>
          <span className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)]">
            <Clock size={10} /> {lesson.durationMin} min
          </span>
          <span className="text-[var(--text-tertiary)]">·</span>
          <span className="flex items-center gap-1 text-[10px] text-amber-400">
            <Zap size={10} /> +{lesson.xp} XP
          </span>
          {alreadyComplete && (
            <span className="flex items-center gap-1 text-[10px] text-[var(--accent-positive)] ml-auto">
              <CheckCircle2 size={10} /> Completed
            </span>
          )}
        </div>
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">{lesson.title}</h1>
          <button
            onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors shrink-0"
          >
            <Bot size={12} /> Ask AI
          </button>
        </div>
      </div>

      {/* Body */}
      <div
        ref={bodyRef}
        className="lesson-body"
        dangerouslySetInnerHTML={{ __html: sanitizeHtml(lesson.body) }}
      />

      {/* Quiz */}
      {lesson.quiz.length > 0 && (
        <div className="mt-8">
          <h2 className="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-widest mb-4">
            Knowledge Check
          </h2>
          {!quizDone ? (
            <QuizBlock
              questions={lesson.quiz}
              lessonId={lesson.id}
              onComplete={handleQuizComplete}
            />
          ) : (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl p-4 flex items-center gap-3">
              <CheckCircle2 size={18} className="text-[var(--accent-positive)] shrink-0" />
              <div>
                <p className="text-[var(--text-primary)] font-semibold text-sm">Quiz complete</p>
                {quizScore !== null && (
                  <p className="text-[var(--text-tertiary)] text-xs">Score: {Math.round(quizScore * 100)}%</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Paper challenge */}
      {lesson.challenge && (
        <div className="mt-6 bg-amber-500/5 border border-amber-500/20 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <FlaskConical size={16} className="text-amber-400" />
            <p className="font-semibold text-[var(--text-primary)] text-sm">Paper Trading Challenge</p>
          </div>
          <p className="text-[var(--text-secondary)] text-sm leading-relaxed">{lesson.challenge.description}</p>
          <p className="text-[var(--text-secondary)] text-sm">{lesson.challenge.task}</p>
          {lesson.challenge.successCriteria && (
            <p className="text-[var(--text-tertiary)] text-xs border-l-2 border-amber-500/30 pl-3">
              ✓ {lesson.challenge.successCriteria}
            </p>
          )}
          <button
            onClick={() => navigate("/paper")}
            className="flex items-center gap-1.5 text-amber-400 text-sm hover:text-amber-300 transition-colors"
          >
            Open Paper Trading <ExternalLink size={13} />
          </button>
        </div>
      )}

      {/* Complete CTA */}
      {!lessonComplete && (
        <div className="mt-8 pt-6 border-t border-[var(--border-subtle)]">
          <button
            onClick={handleMarkComplete}
            disabled={!canComplete || completeMut.isPending}
            className={cn(
              "w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm transition-all",
              canComplete
                ? "bg-[#22C55E] hover:bg-[#22C55E] text-black"
                : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] cursor-not-allowed"
            )}
          >
            {completeMut.isPending ? (
              "Saving…"
            ) : canComplete ? (
              <><CheckCircle2 size={16} /> Mark complete · +{lesson.xp} XP</>
            ) : (
              "Complete the quiz to finish this lesson"
            )}
          </button>
        </div>
      )}

      {lessonComplete && (
        <div className="mt-8 pt-6 border-t border-[var(--border-subtle)]">
          <div className="flex items-center gap-2 text-[var(--accent-positive)] mb-4">
            <CheckCircle2 size={18} />
            <p className="font-semibold text-sm">Lesson complete!</p>
          </div>
          {nextLessonItem ? (
            <button
              onClick={() => navigate(`/learn/lesson/${nextLessonItem.id}`)}
              className="w-full flex items-center justify-center gap-2 py-3 bg-[var(--accent-positive)] text-[var(--text-primary)] rounded-xl font-semibold text-sm hover:brightness-110 active:scale-[0.98] transition-all shadow-lg shadow-blue-900/30"
            >
              Next: {nextLessonItem.title} <ChevronRight size={16} />
            </button>
          ) : (
            <div className="text-center space-y-3">
              <div className="w-16 h-16 rounded-full bg-amber-400/10 flex items-center justify-center mx-auto">
                <Trophy size={32} className="text-amber-400" />
              </div>
              <p className="text-[var(--text-primary)] font-bold text-lg">Course complete!</p>
              <p className="text-[var(--text-tertiary)] text-sm">You've finished every lesson in this course.</p>
              <button
                onClick={() => setShowCert(true)}
                className="w-full flex items-center justify-center gap-2 py-3 bg-gradient-to-r from-amber-500 to-amber-400 text-black font-semibold rounded-xl text-sm hover:brightness-110 transition-all"
              >
                <Award size={16} /> View & Download Certificate
              </button>
              <button
                onClick={() => navigate(`/learn/${track.id}`)}
                className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] text-sm transition-colors"
              >
                Back to {track.title}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Lesson nav */}
      <div className="flex items-center justify-between mt-8 pt-4 border-t border-[var(--border-subtle)]">
        {prevLesson ? (
          <button
            onClick={() => navigate(`/learn/lesson/${prevLesson.id}`)}
            className="flex items-center gap-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs transition-colors"
          >
            <ChevronLeft size={14} /> {prevLesson.title}
          </button>
        ) : <div />}
        {nextLessonItem && !lessonComplete && (
          <button
            onClick={() => navigate(`/learn/lesson/${nextLessonItem.id}`)}
            className="flex items-center gap-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs transition-colors"
          >
            {nextLessonItem.title} <ChevronRight size={14} />
          </button>
        )}
      </div>

      {/* XP toast */}
      {showXP && (
        <XPToast
          xp={earnedXP}
          newBadges={newBadges}
          onDone={() => setShowXP(false)}
        />
      )}

      {/* Certificate modal */}
      {showCert && course && (
        <CertificateGenerator
          courseName={course.title}
          onClose={() => setShowCert(false)}
        />
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title={`Ask about "${lesson.title}"`}
        context={`Learning: ${lesson.title}. Course: ${course?.title ?? "BMG Academy"}`}
        suggestedQuestions={[
          `Can you explain "${lesson.title}" in simpler terms?`,
          "Give me a real-world example of this concept",
          "What's the most important thing to remember from this lesson?",
          "How does this relate to actual trading decisions?",
          "What should I learn next after this topic?",
        ]}
      />
    </div>
  );
}
