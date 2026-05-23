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

  setNotifications: (notifications) =>
    set({ notifications, unreadCount: notifications.filter((n) => !n.is_read).length }),

  addNotification: (n) =>
    set((s) => {
      const notifications = [n, ...s.notifications];
      return { notifications, unreadCount: notifications.filter((x) => !x.is_read).length };
    }),

  markRead: (id) =>
    set((s) => {
      const notifications = s.notifications.map((n) =>
        n.id === id ? { ...n, is_read: true } : n
      );
      return { notifications, unreadCount: notifications.filter((n) => !n.is_read).length };
    }),

  markAllRead: () =>
    set((s) => ({
      notifications: s.notifications.map((n) => ({ ...n, is_read: true })),
      unreadCount: 0,
    })),

  removeNotification: (id) =>
    set((s) => {
      const notifications = s.notifications.filter((n) => n.id !== id);
      return { notifications, unreadCount: notifications.filter((n) => !n.is_read).length };
    }),

  clearAll: () => set({ notifications: [], unreadCount: 0 }),

  openPanel: () => set({ panelOpen: true }),
  closePanel: () => set({ panelOpen: false }),
}));
