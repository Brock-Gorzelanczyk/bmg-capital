import { useRef } from "react";
import { X, Download, Award } from "lucide-react";
import { useAuthStore } from "@/store/authStore";

interface Props {
  courseName: string;
  onClose: () => void;
}

export default function CertificateGenerator({ courseName, onClose }: Props) {
  const { user } = useAuthStore();
  const certRef = useRef<HTMLDivElement>(null);
  const today = new Date().toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const handlePrint = () => {
    window.print();
  };

  return (
    <>
      {/* Print styles — hides everything except #cert-printable */}
      <style>{`
        @media print {
          body > * { display: none !important; }
          #cert-printable-root { display: block !important; position: fixed; inset: 0; }
          #cert-printable-root * { display: revert !important; }
        }
      `}</style>

      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />

        <div className="relative bg-[#0F172A] border border-[#1E293B] rounded-2xl shadow-2xl w-full max-w-2xl">
          {/* Modal toolbar */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-[#1E293B]">
            <div className="flex items-center gap-2">
              <Award size={18} className="text-amber-400" />
              <span className="text-[#F8FAFC] font-semibold text-sm">Course Certificate</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handlePrint}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-[#1E293B] hover:bg-[#334155] text-[#94A3B8] hover:text-[#F8FAFC] rounded-lg transition-colors"
              >
                <Download size={13} /> Save / Print
              </button>
              <button onClick={onClose} className="text-[#475569] hover:text-[#F8FAFC] transition-colors p-1">
                <X size={18} />
              </button>
            </div>
          </div>

          {/* Certificate */}
          <div id="cert-printable-root" className="p-6">
            <div
              ref={certRef}
              className="bg-white rounded-xl overflow-hidden"
              style={{
                fontFamily: "'Inter', sans-serif",
                border: "2px solid #1e3a5f",
              }}
            >
              {/* Top gradient bar */}
              <div style={{ height: 8, background: "linear-gradient(90deg, #3B82F6, #8B5CF6, #EC4899)" }} />

              <div className="px-10 py-8 text-center" style={{ color: "#0f172a" }}>
                {/* Issuer */}
                <div className="flex items-center justify-center gap-2 mb-6">
                  <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold text-lg shrink-0"
                    style={{ background: "linear-gradient(135deg, #3B82F6, #8B5CF6)" }}
                  >
                    B
                  </div>
                  <div className="text-left">
                    <p style={{ fontSize: 15, fontWeight: 700, lineHeight: 1.2, color: "#0f172a" }}>BMG Capital</p>
                    <p style={{ fontSize: 10, color: "#64748b", letterSpacing: "0.1em", textTransform: "uppercase" }}>Learning Center</p>
                  </div>
                </div>

                {/* Gold seal */}
                <div
                  className="w-20 h-20 rounded-full mx-auto mb-5 flex items-center justify-center"
                  style={{ background: "linear-gradient(135deg, #F59E0B, #D97706)", boxShadow: "0 4px 16px rgba(245,158,11,0.3)" }}
                >
                  <Award size={38} color="white" />
                </div>

                <p style={{ fontSize: 12, letterSpacing: "0.2em", textTransform: "uppercase", color: "#64748b", marginBottom: 8 }}>
                  Certificate of Completion
                </p>
                <p style={{ fontSize: 14, color: "#475569", marginBottom: 6 }}>This certifies that</p>

                <p style={{ fontSize: 28, fontWeight: 800, color: "#0f172a", marginBottom: 6, letterSpacing: "-0.02em" }}>
                  {user?.username ?? "Student"}
                </p>

                <p style={{ fontSize: 14, color: "#475569", marginBottom: 4 }}>
                  has successfully completed
                </p>

                <p
                  style={{
                    fontSize: 20,
                    fontWeight: 700,
                    color: "#1e40af",
                    marginBottom: 20,
                    padding: "8px 24px",
                    background: "rgba(59,130,246,0.06)",
                    borderRadius: 8,
                    display: "inline-block",
                  }}
                >
                  {courseName}
                </p>

                <p style={{ fontSize: 12, color: "#94a3b8", marginBottom: 24 }}>
                  Completed on {today}
                </p>

                {/* Divider */}
                <div style={{ height: 1, background: "linear-gradient(90deg, transparent, #e2e8f0, transparent)", margin: "0 0 20px" }} />

                {/* Signatures row */}
                <div className="flex justify-center gap-16">
                  <div className="text-center">
                    <p style={{ fontSize: 16, fontWeight: 700, color: "#0f172a", fontStyle: "italic", marginBottom: 4 }}>
                      BMG Capital
                    </p>
                    <div style={{ height: 1, background: "#cbd5e1", marginBottom: 4 }} />
                    <p style={{ fontSize: 10, color: "#94a3b8", letterSpacing: "0.1em", textTransform: "uppercase" }}>Issuing Authority</p>
                  </div>
                </div>

                {/* Verification note */}
                <p style={{ fontSize: 10, color: "#cbd5e1", marginTop: 16 }}>
                  Verified credential · bmgcapital.com/verify
                </p>
              </div>

              {/* Bottom gradient bar */}
              <div style={{ height: 6, background: "linear-gradient(90deg, #3B82F6, #8B5CF6, #EC4899)" }} />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
