import { useLocation, useNavigate, Link } from "react-router-dom";
import { GraduationCap, Trophy, XCircle, Download, ChevronDown, ChevronUp, AlertTriangle } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

interface ModuleBreakdown {
  module_slug: string;
  correct: number;
  total: number;
}

interface FailedQuestion {
  body: string;
  your_answer: string;
  correct_answer: string;
  explanation: string;
  module_slug: string;
}

interface ExamResult {
  passed: boolean;
  score_pct: number;
  questions_correct: number;
  questions_total: number;
  breakdown_by_module: ModuleBreakdown[];
  certificate_id: string | null;
  failed_questions: FailedQuestion[];
  disqualified?: boolean;
}

function ModuleBreakdownRow({ item }: { item: ModuleBreakdown }) {
  const pct = item.total > 0 ? (item.correct / item.total) * 100 : 0;
  const good = pct >= 90;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-zinc-400 w-36 shrink-0 capitalize">
        {item.module_slug.replace(/-/g, " ")}
      </span>
      <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", good ? "bg-lime-500" : "bg-red-500")}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className={cn("text-xs font-medium w-16 text-right", good ? "text-lime-400" : "text-red-400")}>
        {item.correct}/{item.total}
      </span>
    </div>
  );
}

function FailedQuestionItem({ q }: { q: FailedQuestion }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-4 py-3 flex items-start justify-between gap-3 hover:bg-zinc-800 transition-colors"
      >
        <p className="text-sm text-zinc-200 leading-snug flex-1">{q.body}</p>
        {open ? (
          <ChevronUp size={14} className="text-zinc-500 mt-0.5 shrink-0" />
        ) : (
          <ChevronDown size={14} className="text-zinc-500 mt-0.5 shrink-0" />
        )}
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-2 border-t border-zinc-800 pt-3">
          <div className="flex gap-2 text-xs">
            <span className="text-zinc-500 shrink-0">Your answer:</span>
            <span className="text-red-400">{q.your_answer || "(no answer)"}</span>
          </div>
          <div className="flex gap-2 text-xs">
            <span className="text-zinc-500 shrink-0">Correct answer:</span>
            <span className="text-lime-400">{q.correct_answer}</span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed border-t border-zinc-800 pt-2 mt-2">
            {q.explanation}
          </p>
        </div>
      )}
    </div>
  );
}

export default function ExamResultPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const result = location.state as ExamResult | null;
  const [showFailed, setShowFailed] = useState(false);

  if (!result) {
    return (
      <div className="max-w-lg mx-auto mt-24 text-center space-y-4">
        <p className="text-zinc-400 text-sm">No exam result found.</p>
        <button
          onClick={() => navigate("/learn/tracks")}
          className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-white text-sm transition-colors"
        >
          Back to Learning Center
        </button>
      </div>
    );
  }

  const { passed, score_pct, questions_correct, questions_total, breakdown_by_module, certificate_id, failed_questions, disqualified } = result;

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-8">
      {/* Result hero */}
      <div className="text-center space-y-4">
        <div
          className={cn(
            "inline-flex items-center justify-center w-20 h-20 rounded-full mx-auto",
            disqualified
              ? "bg-amber-500/10"
              : passed
              ? "bg-lime-500/10"
              : "bg-red-500/10"
          )}
        >
          {disqualified ? (
            <AlertTriangle size={36} className="text-amber-400" />
          ) : passed ? (
            <Trophy size={36} className="text-lime-400" />
          ) : (
            <XCircle size={36} className="text-red-400" />
          )}
        </div>

        <div>
          <h1
            className={cn(
              "text-3xl font-bold",
              disqualified ? "text-amber-400" : passed ? "text-lime-400" : "text-red-400"
            )}
          >
            {disqualified ? "Disqualified" : passed ? "Passed!" : "Not Passed"}
          </h1>
          {!disqualified && (
            <p className="text-zinc-400 text-sm mt-1">
              {passed
                ? "Congratulations — you've earned your BMG Capital Learning Center Certificate."
                : "You need 90% to pass. Review the explanations below and try again."}
            </p>
          )}
          {disqualified && (
            <p className="text-zinc-400 text-sm mt-1">
              Your exam was disqualified due to excessive tab switching.
            </p>
          )}
        </div>

        {!disqualified && (
          <div className="text-6xl font-extrabold text-white">
            {score_pct.toFixed(1)}%
          </div>
        )}

        {!disqualified && (
          <p className="text-sm text-zinc-400">
            {questions_correct} / {questions_total} correct
          </p>
        )}
      </div>

      {/* Certificate download */}
      {passed && certificate_id && (
        <div className="bg-lime-500/5 border border-lime-500/20 rounded-2xl p-5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <GraduationCap size={22} className="text-lime-400 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-white">Certificate Earned</p>
              <p className="text-xs text-zinc-400 mt-0.5">ID: {certificate_id}</p>
            </div>
          </div>
          <a
            href={`/api/exams/certificates/${certificate_id}/download`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-lime-500 hover:bg-lime-400 text-black text-xs font-semibold transition-all"
          >
            <Download size={13} />
            Download PDF
          </a>
        </div>
      )}

      {/* Module breakdown */}
      {breakdown_by_module.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-4">
          <h2 className="text-sm font-semibold text-white">Score by Module</h2>
          <div className="space-y-3">
            {breakdown_by_module.map((item) => (
              <ModuleBreakdownRow key={item.module_slug} item={item} />
            ))}
          </div>
        </div>
      )}

      {/* Failed questions */}
      {failed_questions && failed_questions.length > 0 && (
        <div className="space-y-3">
          <button
            onClick={() => setShowFailed((v) => !v)}
            className="flex items-center gap-2 text-sm font-semibold text-zinc-300 hover:text-white transition-colors"
          >
            {showFailed ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            Review {failed_questions.length} missed question
            {failed_questions.length !== 1 ? "s" : ""}
          </button>
          {showFailed && (
            <div className="space-y-2">
              {failed_questions.map((q, i) => (
                <FailedQuestionItem key={i} q={q} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3 flex-wrap">
        <Link
          to="/learn/tracks"
          className="px-4 py-2.5 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-sm font-medium transition-colors"
        >
          Back to Learning Center
        </Link>
        {!passed && !disqualified && (
          <Link
            to="/learn/exam"
            className="px-4 py-2.5 rounded-xl bg-zinc-700 hover:bg-zinc-600 text-white text-sm font-medium transition-colors"
          >
            Check Eligibility for Retry
          </Link>
        )}
        {passed && (
          <Link
            to="/learn/certificates"
            className="px-4 py-2.5 rounded-xl bg-lime-500 hover:bg-lime-400 text-black text-sm font-semibold transition-colors"
          >
            View My Certificates
          </Link>
        )}
      </div>
    </div>
  );
}
