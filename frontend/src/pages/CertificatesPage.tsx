import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { GraduationCap, Download, ExternalLink } from "lucide-react";
import client from "@/api/client";

interface Certificate {
  id: string;
  cert_type: string;
  display_title: string;
  score_pct: number;
  issued_at: string | null;
  pdf_url: string;
}

function CertCard({ cert }: { cert: Certificate }) {
  const issueDate = cert.issued_at
    ? new Date(cert.issued_at).toLocaleDateString(undefined, {
        month: "long",
        day: "numeric",
        year: "numeric",
      })
    : "—";

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex items-start justify-between gap-4">
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-xl bg-lime-500/10 flex items-center justify-center shrink-0">
          <GraduationCap size={22} className="text-lime-400" />
        </div>
        <div className="space-y-1">
          <h3 className="text-sm font-semibold text-white">{cert.display_title}</h3>
          <p className="text-xs text-zinc-400">Certificate ID: {cert.id}</p>
          <p className="text-xs text-zinc-500">Issued: {issueDate}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs bg-lime-500/10 text-lime-400 border border-lime-500/20 px-2 py-0.5 rounded-full font-medium">
              Score: {cert.score_pct.toFixed(1)}%
            </span>
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-2 shrink-0">
        <a
          href={`/api/exams/certificates/${cert.id}/download`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-lime-500 hover:bg-lime-400 text-black text-xs font-semibold transition-all"
        >
          <Download size={12} />
          Download
        </a>
        <a
          href={`/verify/${cert.id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-medium transition-all"
        >
          <ExternalLink size={12} />
          Verify
        </a>
      </div>
    </div>
  );
}

export default function CertificatesPage() {
  const { data: certs, isLoading } = useQuery<Certificate[]>({
    queryKey: ["my-certificates"],
    queryFn: async () => {
      const res = await client.get("/api/exams/certificates");
      return res.data;
    },
    staleTime: 30_000,
  });

  return (
    <div className="max-w-2xl mx-auto py-6 px-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <GraduationCap size={20} className="text-lime-400" />
            My Certificates
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Certificates earned by completing the IMCP Learning Center exam.
          </p>
        </div>
        <Link
          to="/learn/exam"
          className="px-4 py-2 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-xs font-medium transition-colors shrink-0"
        >
          Take Exam
        </Link>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-3">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="h-28 bg-zinc-900 border border-zinc-800 rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : certs && certs.length > 0 ? (
        <div className="space-y-3">
          {certs.map((cert) => (
            <CertCard key={cert.id} cert={cert} />
          ))}
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-10 text-center space-y-4">
          <div className="w-16 h-16 rounded-full bg-zinc-800 flex items-center justify-center mx-auto">
            <GraduationCap size={28} className="text-zinc-500" />
          </div>
          <div>
            <p className="text-sm font-medium text-zinc-300">No certificates yet</p>
            <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
              Complete the Learning Center exam to earn your certificate.
              <br />
              You need a score of 90% or higher to pass.
            </p>
          </div>
          <Link
            to="/learn/exam"
            className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-lime-500 hover:bg-lime-400 text-black text-sm font-semibold transition-all"
          >
            Take Final Exam
          </Link>
        </div>
      )}
    </div>
  );
}
