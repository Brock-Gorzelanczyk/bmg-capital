import { create } from "zustand";
import type { Notification } from "@/types/alerts";

interface AlertState {
  notifications: Notification[];
  unreadCount: number;
  addNotification: (n: Omit<Notification, "id" | "read">) => void;
  markAllRead: () => void;
}

export const useAlertStore = create<AlertState>((set) => ({
  notifications: [],
  unreadCount: 0,
  addNotification: (n) => {
    const notification: Notification = {
      ...n,
      id: crypto.randomUUID(),
      read: false,
    };
    set((s) => ({
      notifications: [notification, ...s.notifications].slice(0, 50),
      unreadCount: s.unreadCount + 1,
    }));
  },
  markAllRead: () => set({ unreadCount: 0, notifications: [] }),
}));
