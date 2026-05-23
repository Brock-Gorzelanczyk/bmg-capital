import { type ReactNode, useEffect } from "react";
import { Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token, user, isLoading, hydrate } = useAuthStore();

  useEffect(() => {
    if (token && !user) {
      hydrate();
    }
  }, [token, user, hydrate]);

  if (!token) return <Navigate to="/login" replace />;

  // Show spinner while we're fetching /auth/me
  if (isLoading || (token && !user)) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 bg-white rounded-lg flex items-center justify-center text-xs font-bold text-black">B</div>
          <div className="text-zinc-500 text-sm">Loading…</div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
