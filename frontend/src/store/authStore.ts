import { create } from "zustand";
import client from "@/api/client";

interface AuthUser {
  id: number;
  email: string;
  username: string;
}

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string) => Promise<void>;
  logout: () => void;
  hydrate: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: localStorage.getItem("bmg_token"),
  isLoading: false,

  login: async (email, password) => {
    const res = await client.post("/auth/login", { email, password });
    const { access_token, user } = res.data;
    localStorage.setItem("bmg_token", access_token);
    localStorage.removeItem("REACT_QUERY_OFFLINE_CACHE");
    set({ token: access_token, user });
  },

  register: async (email, username, password) => {
    const res = await client.post("/auth/register", { email, username, password });
    const { access_token, user } = res.data;
    localStorage.setItem("bmg_token", access_token);
    localStorage.removeItem("REACT_QUERY_OFFLINE_CACHE");
    set({ token: access_token, user });
  },

  logout: () => {
    localStorage.removeItem("bmg_token");
    set({ token: null, user: null });
  },

  hydrate: async () => {
    const token = get().token;
    if (!token) return;
    set({ isLoading: true });
    try {
      const res = await client.get("/auth/me", { timeout: 15_000 });
      set({ user: res.data });
    } catch (err: any) {
      const status = err?.response?.status;
      if (status === 401) {
        // Explicit invalid/expired token — log the user out
        localStorage.removeItem("bmg_token");
        set({ token: null, user: null });
      } else {
        // Network timeout, 500, cold-start delay — keep the token.
        // Set a placeholder so ProtectedRoute stops showing the spinner.
        // API calls will still carry the JWT; they'll surface real errors if needed.
        if (!get().user) {
          set({ user: { id: 0, email: "", username: "—" } });
        }
      }
    } finally {
      set({ isLoading: false });
    }
  },
}));
