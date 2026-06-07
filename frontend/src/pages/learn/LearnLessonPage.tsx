import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, Clock, CheckCircle2,
  BookOpen, FlaskConical, ArrowLeft, ArrowRight,
} from "lucide-react";
import { getLesson, completeLesson } from "@/api/learning";
import type { QuizQuestion } from "@/api/learning";
import { cn } from "@/lib/utils";

// ── Minimal markdown → HTML renderer ─────────────────────────────────────────
// Handles headings, bold, italic, lists, blockquotes, horizontal rules,
// and paragraphs. No external dependency.

function markdownToHtml(md: string): string {
  if (!md) return "";
  const lines = md.split("\n");
  const out: string[] = [];
  let inUl = false;
  let inOl = false;

  function closeLists() {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  }

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];

    // Headings
    const h4 = line.match(/^####\s+(.*)/);
    const h3 = line.match(/^###\s+(.*)/);
    const h2 = line.match(/^##\s+(.*)/);
    const h1 = line.match(/^#\s+(.*)/);

    if (h1) { closeLists(); out.push(`<h1 class="imcp-h1">${inline(h1[1])}</h1>`); continue; }
    if (h2) { closeLists(); out.push(`<h2 class="imcp-h2">${inline(h2[1])}</h2>`); continue; }
    if (h3) { closeLists(); out.push(`<h3 class="imcp-h3">${inline(h3[1])}</h3>`); continue; }
    if (h4) { closeLists(); out.push(`<h4 class="imcp-h4">${inline(h4[1])}</h4>`); continue; }

    // Horizontal rule
    if (/^---+$/.test(line.trim())) { closeLists(); out.push("<hr class=\"imcp-hr\" />"); continue; }

    // Blockquote
    if (line.startsWith("> ")) {
      closeLists();
      out.push(`<blockquote class="imcp-bq">${inline(line.slice(2))}</blockquote>`);
      continue;
    }

    // Unordered list
    const ulItem = line.match(/^[-*]\s+(.*)/);
    if (ulItem) {
      if (!inUl) { if (inOl) { out.push("</ol>"); inOl = false; } out.push('<ul class="imcp-ul">'); inUl = true; }
      out.push(`<li>${inline(ulItem[1])}</li>`);
      continue;
    }

    // Ordered list
    const olItem = line.match(/^\d+\.\s+(.*)/);
    if (olItem) {
      if (!inOl) { if (inUl) { out.push("</ul>"); inUl = false; } out.push('<ol class="imcp-ol">'); inOl = true; }
      out.push(`<li>${inline(olItem[1])}</li>`);
      continue;
    }

    // Empty line — close lists, paragraph break
    if (line.trim() === "") {
      closeLists();
      out.push("<br />");
      continue;
    }

    // Paragraph
    closeLists();
    out.push(`<p class="imcp-p">${inline(line)}</p>`);
  }
  closeLists();
  return out.join("\n");
}

function inline(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, '<code class="imcp-code">$1</code>')
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a class="imcp-link" href="$2" target="_blank" rel="noopener">$1</a>');
}

// ── Quiz component ────────────────────────────────────────────────────────────

function Quiz({
  questions,
  onComplete,
}: {
  questions: QuizQuestion[];
  onComplete: (score: number) => void;
}) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit() {
    if (Object.keys(answers).length < questions.length) return;
    setSubmitted(true);
    const correct = questions.filter((q, i) => answers[i] === q.correct).length;
    onComplete(Math.round((correct / questions.length) * 100));
  }

  return (
    <div className="space-y-5">
      {questions.map((q, qi) => {
        const selected = answers[qi];
        const isCorrect = submitted && selected === q.correct;
        const isWrong = submitted && selected !== undefined && selected !== q.correct;

        return (
          <div key={qi} className="space-y-2.5">
            <p className="text-sm font-medium text-[var(--text-primary)]">
              {qi + 1}. {q.question}
            </p>
            <div className="space-y-1.5">
              {q.options.map((opt, oi) => {
                const isSelected = selected === oi;
                const isCorrectOpt = q.correct === oi;

                let cls = "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-emphasis)] hover:text-[var(--text-primary)]";
                if (submitted) {
                  if (isCorrectOpt) cls = "border-[var(--accent-positive)] bg-[var(--accent-positive)]/8 text-[var(--accent-positive)]";
                  else if (isSelected && !isCorrectOpt) cls = "border-[var(--accent-negative)] bg-[var(--accent-negative)]/8 text-[var(--accent-negative)]";
                  else cls = "border-[var(--border-subtle)] text-[var(--text-tertiary)]";
                } else if (isSelected) {
                  cls = "border-[var(--accent-positive)]/60 bg-[var(--accent-positive)]/6 text-[var(--text-primary)]";
                }

                return (
                  <label
                    key={oi}
                    className={cn(
                      "flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors duration-100",
                      cls,
                      submitted && "cursor-default"
                    )}
                  >
                    <input
                      type="radio"
                      name={`q${qi}`}
                      value={oi}
                      disabled={submitted}
                      checked={isSelected}
                      onChange={() => setAnswers((prev) => ({ ...prev, [qi]: oi }))}
                      className="accent-[var(--accent-positive)] shrink-0"
                    />
                    <span className="text-sm">{opt}</span>
                    {submitted && isCorrectOpt && (
                      <CheckCircle2 size={14} className="ml-auto text-[var(--accent-positive)] shrink-0" />
                    )}
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}

      {!submitted ? (
        <button
          onClick={handleSubmit}
          disabled={Object.keys(answers).length < questions.length}
          className={cn(
            "w-full py-2.5 rounded-lg text-sm font-semibold transition-colors",
            Object.keys(answers).length < questions.length
              ? "bg-zinc-800 text-zinc-500 cursor-not-allowed"
              : "bg-[var(--accent-positive)] text-black hover:bg-[var(--accent-positive)]/90"
          )}
        >
          Submit Answers
        </button>
      ) : (
        <div className="bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-lg p-4 text-center">
          <p className="font-semibold text-[var(--text-primary)]">
            {questions.filter((q, i) => answers[i] === q.correct).length} / {questions.length} correct
          </p>
          <p className="text-xs text-[var(--text-tertiary)] mt-0.5">
            Quiz complete — well done.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Main lesson page ──────────────────────────────────────────────────────────

export default function LearnLessonPage() {
  const { trackSlug, moduleSlug, lessonSlug } = useParams<{
    trackSlug: string;
    moduleSlug: string;
    lessonSlug: string;
  }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const startTime = useRef(Date.now());
  const [quizScore, setQuizScore] = useState<number | null>(null);

  const { data: lesson, isLoading } = useQuery({
    queryKey: ["learning-lesson", trackSlug, moduleSlug, lessonSlug],
    queryFn: () => getLesson(trackSlug!, moduleSlug!, lessonSlug!),
    enabled: !!(trackSlug && moduleSlug && lessonSlug),
    staleTime: 5 * 60_000,
  });

  // Reset quiz score when lesson changes
  useEffect(() => {
    setQuizScore(null);
    startTime.current = Date.now();
  }, [lessonSlug]);

  const completeMut = useMutation({
    mutationFn: (score: number | null) =>
      completeLesson(lesson!.id, {
        quiz_score: score ?? undefined,
        time_spent_seconds: Math.round((Date.now() - startTime.current) / 1000),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["learning-lesson", trackSlug, moduleSlug, lessonSlug] });
      qc.invalidateQueries({ queryKey: ["learning-module", trackSlug, moduleSlug] });
      qc.invalidateQueries({ queryKey: ["learning-track", trackSlug] });
      qc.invalidateQueries({ queryKey: ["learning-tracks"] });
    },
  });

  if (isLoading) {
    return (
      <div className="max-w-2xl mx-auto space-y-4">
        <div className="h-6 w-48 bg-[var(--bg-elevated-2)] rounded animate-pulse" />
        <div className="h-8 w-64 bg-[var(--bg-elevated-2)] rounded animate-pulse" />
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div
              key={i}
              className={cn("h-4 bg-[var(--bg-elevated-2)] rounded animate-pulse", i % 3 === 2 ? "w-3/4" : "w-full")}
            />
          ))}
        </div>
      </div>
    );
  }

  if (!lesson) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--text-tertiary)]">
        Lesson not found.{" "}
        <button
          className="ml-2 text-[var(--text-primary)] underline"
          onClick={() => navigate(`/learn/tracks/${trackSlug}/${moduleSlug}`)}
        >
          Back to module
        </button>
      </div>
    );
  }

  const htmlContent = lesson.content_md ? markdownToHtml(lesson.content_md) : "";
  const htmlExercise = lesson.exercise_md ? markdownToHtml(lesson.exercise_md) : "";

  return (
    <div className="max-w-2xl mx-auto space-y-6 pb-20 md:pb-8">
      {/* Breadcrumb nav */}
      <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
        <button
          className="hover:text-[var(--text-primary)] transition-colors"
          onClick={() => navigate("/learn/tracks")}
        >
          Learning Center
        </button>
        <ChevronRight size={12} />
        <button
          className="hover:text-[var(--text-primary)] transition-colors"
          onClick={() => navigate(`/learn/tracks/${trackSlug}`)}
        >
          {trackSlug?.replace(/-/g, " ")}
        </button>
        <ChevronRight size={12} />
        <button
          className="hover:text-[var(--text-primary)] transition-colors"
          onClick={() => navigate(`/learn/tracks/${trackSlug}/${moduleSlug}`)}
        >
          {moduleSlug?.replace(/-/g, " ")}
        </button>
        <ChevronRight size={12} />
        <span className="text-[var(--text-secondary)] truncate">{lesson.title}</span>
      </div>

      {/* Lesson header */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          {lesson.completed && (
            <CheckCircle2 size={18} className="text-[var(--accent-positive)] shrink-0" />
          )}
          <h1 className="text-xl font-bold text-[var(--text-primary)]">{lesson.title}</h1>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-[var(--text-tertiary)]">
          {lesson.estimated_minutes && (
            <span className="flex items-center gap-1">
              <Clock size={11} /> {lesson.estimated_minutes} min
            </span>
          )}
          {lesson.quiz_json && lesson.quiz_json.length > 0 && (
            <span className="flex items-center gap-1">
              <BookOpen size={11} /> {lesson.quiz_json.length} quiz questions
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      {htmlContent && (
        <div
          className="imcp-content"
          dangerouslySetInnerHTML={{ __html: htmlContent }}
        />
      )}

      {/* Exercise */}
      {lesson.exercise_md && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--accent-positive)]/20 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <FlaskConical size={15} className="text-[var(--accent-positive)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Exercise</h3>
          </div>
          <div
            className="imcp-content text-[var(--text-secondary)]"
            dangerouslySetInnerHTML={{ __html: htmlExercise }}
          />
          <div className="flex flex-wrap gap-2 pt-1">
            {[
              { label: "Open Chart", path: "/chart" },
              { label: "Open Screener", path: "/screener" },
              { label: "Open Journal", path: "/journal" },
              { label: "Open Strategy Lab", path: "/strategy" },
            ].map((btn) => (
              <button
                key={btn.path}
                onClick={() => navigate(btn.path)}
                className="text-xs font-medium px-3 py-1.5 rounded-lg bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--accent-positive)]/30 transition-colors"
              >
                {btn.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Quiz */}
      {lesson.quiz_json && lesson.quiz_json.length > 0 && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <BookOpen size={15} className="text-blue-400" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Quiz</h3>
          </div>
          <Quiz
            questions={lesson.quiz_json}
            onComplete={(score) => setQuizScore(score)}
          />
        </div>
      )}

      {/* Mark complete */}
      {!lesson.completed && (
        <button
          onClick={() => completeMut.mutate(quizScore)}
          disabled={completeMut.isPending}
          className={cn(
            "w-full py-3 rounded-xl text-sm font-semibold transition-all",
            completeMut.isPending
              ? "bg-zinc-800 text-zinc-500 cursor-not-allowed"
              : "bg-[var(--accent-positive)] text-black hover:bg-[var(--accent-positive)]/90"
          )}
        >
          {completeMut.isPending ? "Saving…" : "Mark Complete"}
        </button>
      )}

      {lesson.completed && (
        <div className="flex items-center justify-center gap-2 py-3 text-[var(--accent-positive)] text-sm font-medium">
          <CheckCircle2 size={16} />
          Lesson complete
        </div>
      )}

      {/* Prev / Next navigation */}
      {(lesson.prev_lesson || lesson.next_lesson) && (
        <div className="flex items-center justify-between gap-3 pt-2 border-t border-[var(--border-subtle)]">
          {lesson.prev_lesson ? (
            <button
              onClick={() =>
                navigate(`/learn/tracks/${trackSlug}/${moduleSlug}/${lesson.prev_lesson!.slug}`)
              }
              className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group"
            >
              <ArrowLeft size={15} className="shrink-0 group-hover:-translate-x-0.5 transition-transform" />
              <span className="truncate max-w-[180px]">{lesson.prev_lesson.title}</span>
            </button>
          ) : (
            <div />
          )}
          {lesson.next_lesson ? (
            <button
              onClick={() =>
                navigate(`/learn/tracks/${trackSlug}/${moduleSlug}/${lesson.next_lesson!.slug}`)
              }
              className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group ml-auto"
            >
              <span className="truncate max-w-[180px]">{lesson.next_lesson.title}</span>
              <ArrowRight size={15} className="shrink-0 group-hover:translate-x-0.5 transition-transform" />
            </button>
          ) : (
            <div />
          )}
        </div>
      )}
    </div>
  );
}
