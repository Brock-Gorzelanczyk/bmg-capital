import client from "./client";
import type { AppNotification, NotifSettings, NotifPrefs } from "@/types/notifications";

export const getNotifications = (limit = 50): Promise<AppNotification[]> =>
  client.get("/notifications", { params: { limit } }).then((r) => r.data);

export const getUnreadCount = (): Promise<{ count: number }> =>
  client.get("/notifications/unread-count").then((r) => r.data);

export const markRead = (id: number): Promise<void> =>
  client.post(`/notifications/${id}/read`).then((r) => r.data);

export const markAllRead = (): Promise<void> =>
  client.post("/notifications/read-all").then((r) => r.data);

export const deleteNotification = (id: number): Promise<void> =>
  client.delete(`/notifications/${id}`).then((r) => r.data);

export const clearAllNotifications = (): Promise<void> =>
  client.delete("/notifications").then((r) => r.data);

export const getNotifSettings = (): Promise<NotifSettings> =>
  client.get("/notifications/settings").then((r) => r.data);

export const updateNotifSettings = (prefs: NotifPrefs): Promise<void> =>
  client.put("/notifications/settings", { prefs }).then((r) => r.data);
