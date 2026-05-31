import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useAuthStore } from "@/store/authStore";
import { useDemoStore } from "@/lib/demo/demoStore";
import type { DemoData } from "@/lib/demo/fixtures";
import client from "@/api/client";

// ── Context ───────────────────────────────────────────────────────────────────

const DemoContext = createContext<DemoData | null>(null);

export function useDemoData(): DemoData | null {
  return useContext(DemoContext);
}

// ── Provider ──────────────────────────────────────────────────────────────────

interface DemoAuthProviderProps {
  children: ReactNode;
}

export default function DemoAuthProvider({ children }: DemoAuthProviderProps) {
  const data = useDemoStore((s) => s.data);

  // Seed authStore with demo user on mount and whenever persona changes
  useEffect(() => {
    useAuthStore.setState({
      user: { id: data.user.id, email: data.user.email, username: data.user.username },
      token: "demo-token-not-real",
      isLoading: false,
    });
    // Also persist a fake token so ProtectedRoute passes
    localStorage.setItem("bmg_token", "demo-token-not-real");
  }, [data]);

  // Intercept axios: no-op POST /auth/login and /auth/register, return fake token
  useEffect(() => {
    const interceptorId = client.interceptors.request.use((config) => {
      const url = config.url ?? "";
      if (
        config.method?.toUpperCase() === "POST" &&
        (url.includes("/auth/login") || url.includes("/auth/register"))
      ) {
        // Abort the real request by throwing a cancelled signal and resolve via response interceptor
        // Instead, we override the adapter to return a mock response
        config.adapter = async () => {
          return {
            data: { access_token: "demo-token-not-real", user: data.user },
            status: 200,
            statusText: "OK",
            headers: {},
            config,
          };
        };
      }
      // Always inject demo token for auth header
      config.headers.Authorization = "Bearer demo-token-not-real";
      return config;
    });

    return () => {
      client.interceptors.request.eject(interceptorId);
    };
  }, [data]);

  return <DemoContext.Provider value={data}>{children}</DemoContext.Provider>;
}
