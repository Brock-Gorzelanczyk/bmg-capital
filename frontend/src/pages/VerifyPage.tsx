import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, ShieldX, GraduationCap, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface VerifyResult {
  found: boolean;
  valid: boolean;
  recipient_name: string | null;
  display_title: string | null;
  score_pct: number | null;
  issued_at: string | null;
  cert_id: string | null;
  is_revoked: boolean;
  revoked_reason: string | null;
}

export default function VerifyPage() {
  const { certId } = useParams<{ certId: string }>();

  const { data, isLoading, isError } = useQuery<VerifyResult>({
    queryKey: ["verify-cert", certId],
    queryFn: async () => {
      const res = await fetch(`/api/verify/${certId}`);
      if (!res.ok) throw new Error("Verification failed");
      return res.json();
    },
    enabled: !!certId,
    staleTime: 60_000,
  });

  const issueDate = data?.issued_at
    ? new Date(data.issued_at).toLocaleDateString(undefined, {
        month: "long",
        day: "numeric",
        year: "numeric",
      })
    : null;

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        {/* Brand header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-3">
            <GraduationCap size={22} className="text-lime-400" />
            <span className="text-white font-bold text-lg">BMG Capital</span>
          </div>
          <p className="text-zinc-500 text-sm">Certificate Verification</p>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-10 text-center space-y-4">
            <div className="w-12 h-12 border-2 border-lime-400 border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm text-zinc-400">Verifying certificate…</p>
          </div>
        )}

        {/* Error */}
        {isError && (
          <div className="bg-zinc-900 border border-red-500/20 rounded-2xl p-8 text-center space-y-3">
            <AlertTriangle size={32} className="text-red-400 mx-auto" />
            <p className="text-sm text-red-400 font-medium">Verification failed</p>
            <p className="text-xs text-zinc-500">
              Unable to reach the verification server. Please try again.
            </p>
          </div>
        )}

        {/* Result */}
        {data && (
          <div
            className={cn(
              "bg-zinc-900 border rounded-2xl overflow-hidden",
              data.valid
                ? "border-lime-500/30"
                : data.is_revoked
                ? "border-amber-500/30"
                : "border-red-500/30"
            )}
          >
            {/* Status banner */}
            <div
              className={cn(
                "px-6 py-5 flex items-center gap-4",
                data.valid
                  ? "bg-lime-500/10"
                  : data.is_revoked
                  ? "bg-amber-500/10"
                  : "bg-red-500/10"
              )}
            >
              <div
                className={cn(
                  "w-12 h-12 rounded-full flex items-center justify-center shrink-0",
                  data.valid
                    ? "bg-lime-500/20"
                    : data.is_revoked
                    ? "bg-amber-500/20"
                    : "bg-red-500/20"
                )}
              >
                {data.valid ? (
                  <ShieldCheck size={24} className="text-lime-400" />
                ) : data.is_revoked ? (
                  <AlertTriangle size={24} className="text-amber-400" />
                ) : (
                  <ShieldX size={24} className="text-red-400" />
                )}
              </div>
              <div>
                <p
                  className={cn(
                    "text-base font-bold",
                    data.valid ? "text-lime-400" : data.is_revoked ? "text-amber-400" : "text-red-400"
                  )}
                >
                  {data.valid
                    ? "Valid Certificate"
                    : data.is_revoked
                    ? "Certificate Revoked"
                    : data.found
                    ? "Certificate Invalid"
                    : "Certificate Not Found"}
                </p>
                <p className="text-xs text-zinc-400 mt-0.5">
                  {data.valid
                    ? "This certificate has been verified as authentic."
                    : data.is_revoked
                    ? data.revoked_reason ?? "This certificate has been revoked."
                    : data.found
                    ? "This certificate failed integrity verification."
                    : "No certificate exists with this ID."}
                </p>
              </div>
            </div>

            {/* Details */}
            {data.found && (
              <div className="px-6 py-5 space-y-4">
                <Row label="Certificate ID" value={data.cert_id ?? certId ?? "—"} mono />
                <Row label="Recipient" value={data.recipient_name ?? "—"} />
                <Row label="Certificate" value={data.display_title ?? "—"} />
                {data.score_pct != null && (
                  <Row label="Score" value={`${data.score_pct.toFixed(1)}%`} />
                )}
                {issueDate && <Row label="Issued" value={issueDate} />}
              </div>
            )}
          </div>
        )}

        {/* Cert ID being verified */}
        {certId && (
          <p className="text-center text-[10px] text-zinc-600 font-mono">
            Verifying: {certId}
          </p>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-xs text-zinc-500 shrink-0">{label}</span>
      <span className={cn("text-xs text-zinc-200 text-right break-all", mono && "font-mono")}>
        {value}
      </span>
    </div>
  );
}
