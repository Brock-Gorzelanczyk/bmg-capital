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
    set({ token: access_token, user });
  },

  register: async (email, username, password) => {
    const res = await client.post("/auth/register", { email, username, password });
    const { access_token, user } = res.data;
    localStorage.setItem("bmg_token", access_token);
    set({ token: access_token, user });
  },

  logout: () => {
    localStorage.removeItem("bmg_token");
    set({ token: null, user: null });
  },

  hydrate: async () => {
    const token = get().token;
    if (!token) return;
    try {
      set({ isLoading: true });
      const res = await client.get("/auth/me", { timeout: 6000 });
      set({ user: res.data });
    } catch {
      localStorage.removeItem("bmg_token");
      set({ token: null, user: null });
    } finally {
      set({ isLoading: false });
    }
  },
}));
