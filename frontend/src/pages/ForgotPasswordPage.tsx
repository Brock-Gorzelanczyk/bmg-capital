import { useState } from "react";
import { Link } from "react-router-dom";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // POST /api/auth/forgot-password is not yet implemented.
    // Show the email-us fallback immediately.
    setSubmitted(true);
  };

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
            Enter your email and we'll send reset instructions.
          </p>

          {submitted ? (
            <div className="space-y-4">
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg px-4 py-3 text-sm text-blue-300 leading-relaxed">
                Password reset is coming soon. Email{" "}
                <a
                  href="mailto:support@bmgcapital.com"
                  className="underline underline-offset-2 hover:text-white transition-colors"
                >
                  support@bmgcapital.com
                </a>{" "}
                to reset your password.
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs text-slate-500 mb-1.5 font-medium">
                  Email address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  placeholder="you@example.com"
                  className="w-full bg-[#020617] border border-[#1e293b] text-white text-sm rounded-lg px-3 py-2.5 outline-none focus:border-[#3B82F6] placeholder-slate-600 transition-colors"
                />
              </div>
              <button
                type="submit"
                className="w-full bg-[#3B82F6] hover:bg-[#2563eb] text-white text-sm font-semibold rounded-lg py-2.5 transition-colors"
              >
                Send reset instructions
              </button>
            </form>
          )}
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
