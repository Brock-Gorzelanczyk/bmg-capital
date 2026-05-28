import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { DEMO_EMAIL, DEMO_PASSWORD } from "@/lib/demoMode";

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const { login, register } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (mode === "register") {
      if (password !== confirm) { setError("Passwords do not match"); return; }
      if (password.length < 1) { setError("Password required"); return; }
    }

    setLoading(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, username, password);
      }
      navigate("/");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(detail ?? "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleTryDemo = async () => {
    setError("");
    setLoading(true);
    try {
      await login(DEMO_EMAIL, DEMO_PASSWORD);
      navigate("/");
    } catch {
      setError("Demo account unavailable. Please create a free account.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#020617] flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[#3B82F6] to-[#8B5CF6] mx-auto mb-4 flex items-center justify-center font-bold text-[var(--text-primary)] text-xl shadow-lg shadow-blue-500/20">
            B
          </div>
          <h1 className="text-[var(--text-primary)] text-2xl font-bold tracking-tight">BMG Capital</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-1">Algorithmic paper trading platform</p>
        </div>

        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-6">
          {/* Tabs */}
          <div className="flex gap-1 mb-6 bg-[#020617] rounded-lg p-1">
            <button
              onClick={() => { setMode("login"); setError(""); }}
              className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                mode === "login"
                  ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              }`}
            >
              Sign in
            </button>
            <button
              onClick={() => { setMode("register"); setError(""); }}
              className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                mode === "register"
                  ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              }`}
            >
              Create account
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-[var(--text-tertiary)] mb-1.5 font-medium">
                {mode === "login" ? "Username or email" : "Email"}
              </label>
              <input
                type={mode === "register" ? "email" : "text"}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="username"
                placeholder={mode === "login" ? "username or email" : "you@example.com"}
                className="w-full bg-[#020617] border border-[var(--border-subtle)] text-[var(--text-primary)] text-sm rounded-lg px-3 py-2.5 outline-none focus:border-[#3B82F6] placeholder-[#334155] transition-colors"
              />
            </div>

            {mode === "register" && (
              <div>
                <label className="block text-xs text-[var(--text-tertiary)] mb-1.5 font-medium">Username</label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoComplete="username"
                  placeholder="your_username"
                  className="w-full bg-[#020617] border border-[var(--border-subtle)] text-[var(--text-primary)] text-sm rounded-lg px-3 py-2.5 outline-none focus:border-[#3B82F6] placeholder-[#334155] transition-colors"
                />
              </div>
            )}

            <div>
              <label className="block text-xs text-[var(--text-tertiary)] mb-1.5 font-medium">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                placeholder="••••••••"
                className="w-full bg-[#020617] border border-[var(--border-subtle)] text-[var(--text-primary)] text-sm rounded-lg px-3 py-2.5 outline-none focus:border-[#3B82F6] placeholder-[#334155] transition-colors"
              />
            </div>

            {mode === "register" && (
              <div>
                <label className="block text-xs text-[var(--text-tertiary)] mb-1.5 font-medium">Confirm password</label>
                <input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                  autoComplete="new-password"
                  placeholder="••••••••"
                  className="w-full bg-[#020617] border border-[var(--border-subtle)] text-[var(--text-primary)] text-sm rounded-lg px-3 py-2.5 outline-none focus:border-[#3B82F6] placeholder-[#334155] transition-colors"
                />
              </div>
            )}

            {error && (
              <p className="text-[var(--accent-negative)] text-xs bg-[var(--accent-negative-bg)] border border-[var(--accent-negative)]/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[var(--accent-positive)] hover:brightness-110 text-[var(--text-primary)] text-sm font-semibold rounded-lg py-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed mt-2"
            >
              {loading ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          {/* Divider */}
          {mode === "login" && (
            <>
              <div className="flex items-center gap-3 my-4">
                <div className="flex-1 h-px bg-[var(--bg-elevated-2)]" />
                <span className="text-[10px] text-[var(--border-emphasis)] uppercase tracking-widest">or</span>
                <div className="flex-1 h-px bg-[var(--bg-elevated-2)]" />
              </div>

              {/* Try Demo button */}
              <button
                onClick={handleTryDemo}
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 border border-[var(--border-emphasis)] bg-transparent hover:bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-sm font-medium rounded-lg py-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse" />
                Try live demo
              </button>

              <p className="text-center text-[10px] text-[var(--border-emphasis)] mt-3">
                No account needed · pre-loaded with 7 positions
              </p>
            </>
          )}
        </div>

        <p className="text-center text-[var(--border-emphasis)] text-xs mt-6">
          Paper trading only · not financial advice
        </p>
      </div>
    </div>
  );
}
