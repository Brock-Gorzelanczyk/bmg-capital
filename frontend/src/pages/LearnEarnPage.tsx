import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Star, Check, X, ChevronRight, Trophy } from "lucide-react";
import { toast } from "sonner";
import {
  getLessons, getLessonDetail, completeLesson, getMyRewards, getLearnEarnStats,
  type LearnLesson, type LessonDetail, type CompleteResult,
} from "@/api/learnEarn";

export default function LearnEarnPage() {
  const qc = useQueryClient();
  const [activeLesson, setActiveLesson] = useState<string | null>(null);
  const [lessonDetail, setLessonDetail] = useState<LessonDetail | null>(null);
  const [answers, setAnswers] = useState<number[]>([]);
  const [result, setResult] = useState<CompleteResult | null>(null);
  const [tab, setTab] = useState<"lessons" | "rewards">("lessons");

  const { data: lessons = [] } = useQuery({ queryKey: ["learn-earn-lessons"], queryFn: getLessons });
  const { data: stats } = useQuery({ queryKey: ["learn-earn-stats"], queryFn: getLearnEarnStats });
  const { data: rewards = [] } = useQuery({ queryKey: ["learn-earn-rewards"], queryFn: getMyRewards });

  const openLesson = async (id: string) => {
    const detail = await getLessonDetail(id);
    setLessonDetail(detail);
    setAnswers(new Array(detail.quiz_questions.length).fill(-1));
    setResult(null);
    setActiveLesson(id);
  };

  const submitMutation = useMutation({
    mutationFn: () => completeLesson(activeLesson!, answers),
    onSuccess: (data) => {
      setResult(data);
      qc.invalidateQueries({ queryKey: ["learn-earn-lessons"] });
      qc.invalidateQueries({ queryKey: ["learn-earn-stats"] });
      qc.invalidateQueries({ queryKey: ["learn-earn-rewards"] });
      if (data.passed) toast.success(`+$${data.reward_amount} ${data.reward_symbol} earned!`);
    },
  });

  const closeModal = () => { setActiveLesson(null); setLessonDetail(null); setResult(null); };

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div className="rounded-2xl border border-[#84cc16]/30 bg-[#84cc16]/5 p-6">
          <div className="flex items-center gap-3 mb-2">
            <BookOpen className="w-6 h-6 text-[#84cc16]" />
            <h1 className="text-2xl font-black text-[var(--text-primary)]">BMG Academy</h1>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">Learn. Quiz. Earn fractional shares.</p>
          {stats && (
            <div className="flex gap-6 mt-4">
              <div><div className="text-2xl font-black font-mono text-[#84cc16]">${stats.total_earned.toFixed(2)}</div><div className="text-xs text-[var(--text-secondary)]">total earned</div></div>
              <div><div className="text-2xl font-black font-mono text-[var(--text-primary)]">{stats.lessons_completed}/{stats.lessons_available}</div><div className="text-xs text-[var(--text-secondary)]">completed</div></div>
            </div>
          )}
        </div>

        {/* Tabs */}
        <div className="flex gap-2">
          {(["lessons", "rewards"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 rounded-lg text-sm font-semibold capitalize transition-colors ${tab === t ? "bg-[#84cc16] text-black" : "bg-[var(--bg-elevated)] text-[var(--text-secondary)]"}`}>{t}</button>
          ))}
        </div>

        {tab === "lessons" && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {lessons.map((lesson: LearnLesson) => (
              <button
                key={lesson.lesson_id}
                onClick={() => !lesson.already_completed && openLesson(lesson.lesson_id)}
                disabled={lesson.already_completed}
                className={`relative rounded-2xl border ${lesson.already_completed ? "border-[var(--border-subtle)] opacity-60" : "border-[var(--border-subtle)] hover:border-[#84cc16]/40"} bg-[var(--bg-elevated)] p-5 text-left transition-all space-y-3`}
              >
                {lesson.already_completed && (
                  <div className="absolute top-3 right-3 w-6 h-6 rounded-full bg-[#84cc16]/20 flex items-center justify-center">
                    <Check className="w-3.5 h-3.5 text-[#84cc16]" />
                  </div>
                )}
                {lesson.sponsor && <div className="text-xs text-[var(--text-secondary)] font-medium">Sponsored by {lesson.sponsor}</div>}
                <div className="font-bold text-[var(--text-primary)]">{lesson.title}</div>
                <div className="text-xs text-[var(--text-secondary)] line-clamp-2">{lesson.description}</div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <Star className="w-3.5 h-3.5 text-[#84cc16]" />
                    <span className="text-sm font-bold text-[#84cc16]">+${lesson.reward_amount} {lesson.reward_symbol}</span>
                  </div>
                  {!lesson.already_completed && <ChevronRight className="w-4 h-4 text-[var(--text-secondary)]" />}
                </div>
              </button>
            ))}
          </div>
        )}

        {tab === "rewards" && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
            {rewards.length === 0 ? (
              <div className="p-8 text-center text-[var(--text-secondary)] text-sm">Complete lessons to earn rewards.</div>
            ) : (
              <table className="w-full text-sm">
                <thead><tr className="text-xs text-[var(--text-secondary)] border-b border-[var(--border-subtle)]"><th className="text-left p-4">Lesson</th><th className="text-center p-4">Status</th><th className="text-right p-4">Reward</th></tr></thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {rewards.map((r, i) => (
                    <tr key={i}>
                      <td className="p-4 text-[var(--text-secondary)]">{r.lesson_id.replace(/-/g, " ")}</td>
                      <td className="p-4 text-center"><span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${r.status === "credited" ? "bg-green-500/20 text-green-400" : "bg-[#84cc16]/20 text-[#84cc16]"}`}>{r.status}</span></td>
                      <td className="p-4 text-right font-mono font-bold text-[#84cc16]">{r.reward_amount ? `$${r.reward_amount} ${r.reward_symbol}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* Lesson Modal */}
      {activeLesson && lessonDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-5 border-b border-[var(--border-subtle)] shrink-0">
              <div>
                <div className="font-bold text-[var(--text-primary)]">{lessonDetail.title}</div>
                <div className="text-xs text-[#84cc16] mt-0.5">Earn +${lessonDetail.reward_amount} {lessonDetail.reward_symbol}</div>
              </div>
              <button onClick={closeModal} className="p-1 rounded hover:bg-[var(--bg-base)] text-[var(--text-secondary)]"><X className="w-4 h-4" /></button>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {!result ? (
                <>
                  <p className="text-sm text-[var(--text-secondary)]">{lessonDetail.description}</p>
                  <p className="text-xs text-[var(--text-secondary)]">Answer 2 of 3 correctly to earn your reward.</p>
                  {lessonDetail.quiz_questions.map((q, qi) => (
                    <div key={qi} className="space-y-2">
                      <div className="text-sm font-semibold text-[var(--text-primary)]">{qi + 1}. {q.question}</div>
                      {q.options.map((opt, oi) => (
                        <button
                          key={oi}
                          onClick={() => setAnswers(a => { const n = [...a]; n[qi] = oi; return n; })}
                          className={`w-full text-left px-4 py-2.5 rounded-lg text-sm transition-colors border ${answers[qi] === oi ? "border-[#84cc16] bg-[#84cc16]/10 text-[var(--text-primary)]" : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[#84cc16]/40"}`}
                        >
                          {opt}
                        </button>
                      ))}
                    </div>
                  ))}
                  <button
                    onClick={() => submitMutation.mutate()}
                    disabled={answers.some(a => a === -1) || submitMutation.isPending}
                    className="w-full py-3 rounded-xl bg-[#84cc16] text-black font-bold text-sm hover:bg-[#a3e635] transition-colors disabled:opacity-50"
                  >
                    {submitMutation.isPending ? "Grading…" : "Submit Quiz"}
                  </button>
                </>
              ) : (
                <div className="space-y-4">
                  <div className={`rounded-xl p-4 text-center ${result.passed ? "bg-[#84cc16]/10 border border-[#84cc16]/30" : "bg-red-500/10 border border-red-500/30"}`}>
                    {result.passed ? <Trophy className="w-8 h-8 text-[#84cc16] mx-auto mb-2" /> : <X className="w-8 h-8 text-red-400 mx-auto mb-2" />}
                    <div className="font-bold text-lg text-[var(--text-primary)]">{result.passed ? "Passed!" : "Not quite"}</div>
                    <div className="text-sm text-[var(--text-secondary)]">{result.score}/{result.total_questions} correct</div>
                    {result.passed && <div className="text-[#84cc16] font-bold mt-1">+${result.reward_amount} {result.reward_symbol} earned</div>}
                  </div>
                  {lessonDetail.quiz_questions.map((q, i) => (
                    <div key={i} className="text-sm space-y-1">
                      <div className="font-medium text-[var(--text-primary)]">{q.question}</div>
                      <div className={`text-xs ${answers[i] === result.correct_answers[i] ? "text-green-400" : "text-red-400"}`}>
                        Your answer: {q.options[answers[i]]} {answers[i] === result.correct_answers[i] ? "✓" : `✗ (correct: ${q.options[result.correct_answers[i]]})`}
                      </div>
                      <div className="text-xs text-[var(--text-secondary)]">{result.explanations[i]}</div>
                    </div>
                  ))}
                  <button onClick={closeModal} className="w-full py-2.5 rounded-xl bg-[var(--bg-base)] text-[var(--text-primary)] text-sm font-semibold hover:bg-[var(--border-subtle)] transition-colors">Close</button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
