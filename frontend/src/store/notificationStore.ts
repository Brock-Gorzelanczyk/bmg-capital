import { create } from "zustand";
import type { AppNotification } from "@/types/notifications";

interface NotificationState {
  notifications: AppNotification[];
  panelOpen: boolean;
  unreadCount: number;
  setNotifications: (n: AppNotification[]) => void;
  addNotification: (n: AppNotification) => void;
  markRead: (id: number) => void;
  markAllRead: () => void;
  removeNotification: (id: number) => void;
  clearAll: () => void;
  openPanel: () => void;
  closePanel: () => void;
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  panelOpen: false,
  unreadCount: 0,

  setNotifications: (notifications) => {
    const safe = Array.isArray(notifications) ? notifications : [];
    set({ notifications: safe, unreadCount: safe.filter((n) => !n.is_read).length });
  },

  addNotification: (n) =>
    set((s) => {
      const prev = Array.isArray(s.notifications) ? s.notifications : [];
      const notifications = [n, ...prev];
      return { notifications, unreadCount: notifications.filter((x) => !x.is_read).length };
    }),

  markRead: (id) =>
    set((s) => {
      const prev = Array.isArray(s.notifications) ? s.notifications : [];
      const notifications = prev.map((n) =>
        n.id === id ? { ...n, is_read: true } : n
      );
      return { notifications, unreadCount: notifications.filter((n) => !n.is_read).length };
    }),

  markAllRead: () =>
    set((s) => {
      const prev = Array.isArray(s.notifications) ? s.notifications : [];
      return { notifications: prev.map((n) => ({ ...n, is_read: true })), unreadCount: 0 };
    }),

  removeNotification: (id) =>
    set((s) => {
      const prev = Array.isArray(s.notifications) ? s.notifications : [];
      const notifications = prev.filter((n) => n.id !== id);
      return { notifications, unreadCount: notifications.filter((n) => !n.is_read).length };
    }),

  clearAll: () => set({ notifications: [], unreadCount: 0 }),

  openPanel: () => set({ panelOpen: true }),
  closePanel: () => set({ panelOpen: false }),
}));
