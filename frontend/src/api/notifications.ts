import client from "./client";
import type { AppNotification, NotifSettings, NotifPrefs } from "@/types/notifications";

export const getNotifications = (limit = 50): Promise<AppNotification[]> =>
  client.get("/api/notifications", { params: { limit } }).then((r) => r.data);

export const getUnreadCount = (): Promise<{ count: number }> =>
  client.get("/api/notifications/unread-count").then((r) => r.data);

export const markRead = (id: number): Promise<void> =>
  client.post(`/api/notifications/${id}/read`).then((r) => r.data);

export const markAllRead = (): Promise<void> =>
  client.post("/api/notifications/read-all").then((r) => r.data);

export const deleteNotification = (id: number): Promise<void> =>
  client.delete(`/api/notifications/${id}`).then((r) => r.data);

export const clearAllNotifications = (): Promise<void> =>
  client.delete("/api/notifications").then((r) => r.data);

export const getNotifSettings = (): Promise<NotifSettings> =>
  client.get("/api/notifications/settings").then((r) => r.data);

export const updateNotifSettings = (prefs: NotifPrefs): Promise<void> =>
  client.put("/api/notifications/settings", { prefs }).then((r) => r.data);
