import { Link } from "react-router-dom";

export default function ForgotPasswordPage() {
  // Self-service password reset isn't wired yet (no backend endpoint and no
  // email integration). Surface that honestly rather than rendering a form
  // that silently no-ops — the prior implementation accepted an email,
  // claimed success, and never sent anything. Users got locked out thinking
  // they'd done the right thing.
  return (
    <div className="min-h-screen bg-[#020617] flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#3B82F6] to-[#8B5CF6] flex items-center justify-center font-bold text-white text-sm">
            B
          </div>
          <span className="text-white font-bold tracking-tight">BMG Capital</span>
        </div>

        <div className="bg-[#0a0f1e] border border-[#1e293b] rounded-2xl p-6">
          <h1 className="text-white font-bold text-lg mb-1">Reset your password</h1>
          <p className="text-slate-500 text-sm mb-6">
            Self-service password reset is coming soon.
          </p>

          <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg px-4 py-3 text-sm text-blue-300 leading-relaxed">
            Email{" "}
            <a
              href="mailto:support@bmgcapital.com"
              className="underline underline-offset-2 hover:text-white transition-colors"
            >
              support@bmgcapital.com
            </a>{" "}
            from the address on your account and we'll reset it for you.
          </div>
        </div>

        <p className="text-center mt-4">
          <Link
            to="/login"
            className="text-slate-500 hover:text-slate-300 text-sm transition-colors"
          >
            ← Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
