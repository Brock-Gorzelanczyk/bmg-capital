import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, Trash2, CheckCheck } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { useNotificationStore } from "@/store/notificationStore";
import {
  getNotifications,
  getNotifSettings,
  updateNotifSettings,
  markRead as apiMarkRead,
  markAllRead as apiMarkAllRead,
  deleteNotification as apiDelete,
  clearAllNotifications,
} from "@/api/notifications";
import { EVENT_ICONS, EVENT_LABELS } from "@/types/notifications";
import type { AppNotification, NotifPrefs, NotifEventType, NotifChannel } from "@/types/notifications";


const CHANNEL_LABELS: Record<NotifChannel, string> = {
  in_app: "In-App",
  email: "Email",
  push: "Push",
};

function SettingsGrid() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["notif-settings"],
    queryFn: getNotifSettings,
    staleTime: 60_000,
  });

  const mut = useMutation({
    mutationFn: updateNotifSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notif-settings"] }),
  });

  if (isLoading || !data) {
    return <div className="text-[var(--text-tertiary)] text-sm animate-pulse">Loading settings…</div>;
  }

  const { prefs, event_types, channels } = data;

  const toggle = (event: NotifEventType, channel: NotifChannel) => {
    const updated: NotifPrefs = JSON.parse(JSON.stringify(prefs));
    updated[event] = { ...updated[event], [channel]: !updated[event]?.[channel] };
    mut.mutate(updated);
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border-emphasis)]">
            <th className="text-left py-2 px-3 text-[var(--text-tertiary)] font-medium w-48">Event</th>
            {channels.map((ch) => (
              <th key={ch} className="text-center py-2 px-4 text-[var(--text-tertiary)] font-medium">
                <div>{CHANNEL_LABELS[ch]}</div>
                {ch !== "in_app" && (
                  <div className="text-[9px] text-[var(--text-tertiary)] font-normal">coming soon</div>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {event_types.map((event) => (
            <tr key={event} className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/30 transition-colors">
              <td className="py-2.5 px-3">
                <span className="mr-2">{EVENT_ICONS[event]}</span>
                <span className="text-[var(--text-secondary)]">{EVENT_LABELS[event]}</span>
              </td>
              {channels.map((ch) => (
                <td key={ch} className="text-center py-2.5 px-4">
                  <button
                    onClick={() => toggle(event, ch)}
                    disabled={ch !== "in_app"}
                    className={cn(
                      "w-10 h-5 rounded-full transition-colors relative shrink-0",
                      prefs[event]?.[ch]
                        ? ch === "in_app" ? "bg-[#16A34A]" : "bg-zinc-600"
                        : "bg-[#334155]",
                      ch !== "in_app" && "opacity-40 cursor-not-allowed"
                    )}
                  >
                    <span
                      className={cn(
                        "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                        prefs[event]?.[ch] ? "translate-x-5" : "translate-x-0.5"
                      )}
                    />
                  </button>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InboxTab({ notifications }: { notifications: AppNotification[] }) {
  const { markRead, markAllRead, removeNotification, clearAll } = useNotificationStore();
  const qc = useQueryClient();
  const unread = notifications.filter((n) => !n.is_read).length;

  const readMut = useMutation({
    mutationFn: apiMarkRead,
    onSuccess: (_, id) => { markRead(id); qc.invalidateQueries({ queryKey: ["notifications"] }); },
  });
  const readAllMut = useMutation({
    mutationFn: apiMarkAllRead,
    onSuccess: () => { markAllRead(); qc.invalidateQueries({ queryKey: ["notifications"] }); },
  });
  const deleteMut = useMutation({
    mutationFn: apiDelete,
    onSuccess: (_, id) => { removeNotification(id); qc.invalidateQueries({ queryKey: ["notifications"] }); },
  });
  const clearMut = useMutation({
    mutationFn: clearAllNotifications,
    onSuccess: () => { clearAll(); qc.invalidateQueries({ queryKey: ["notifications"] }); },
  });

  if (notifications.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3 text-[var(--text-tertiary)]">
        <Bell size={40} />
        <p className="text-sm">No notifications</p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between pb-3">
        <span className="text-[var(--text-tertiary)] text-sm">{unread} unread</span>
        <div className="flex items-center gap-3">
          {unread > 0 && (
            <button
              onClick={() => readAllMut.mutate()}
              className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <CheckCheck size={13} /> Mark all read
            </button>
          )}
          <button
            onClick={() => clearMut.mutate()}
            className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors"
          >
            <Trash2 size={13} /> Clear all
          </button>
        </div>
      </div>
      {notifications.map((n) => (
        <div
          key={n.id}
          onClick={() => { if (!n.is_read) readMut.mutate(n.id); }}
          className={cn(
            "group flex items-start gap-3 px-4 py-3 rounded-xl cursor-pointer transition-colors",
            n.is_read
              ? "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:border-[var(--border-emphasis)]"
              : "bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] hover:border-[var(--border-emphasis)]"
          )}
        >
          <span className="text-lg mt-0.5 shrink-0">{EVENT_ICONS[n.event_type] ?? "🔔"}</span>
          <div className="flex-1 min-w-0">
            <div className={cn("text-sm leading-snug", n.is_read ? "text-[var(--text-secondary)]" : "text-[var(--text-primary)] font-medium")}>
              {n.title}
            </div>
            {n.body && <div className="text-xs text-[var(--text-tertiary)] mt-0.5">{n.body}</div>}
            <div className="text-[10px] text-[var(--text-tertiary)] mt-1">{timeAgo(n.created_at)}</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {!n.is_read && <span className="w-2 h-2 rounded-full bg-blue-500" />}
            <button
              onClick={(e) => { e.stopPropagation(); deleteMut.mutate(n.id); }}
              className="opacity-0 group-hover:opacity-100 text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-all"
            >
              <Trash2 size={13} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function NotificationsPage() {
  const [tab, setTab] = useState<"inbox" | "settings">("inbox");
  const qc = useQueryClient();
  const { setNotifications } = useNotificationStore();

  const { data: notifications = [], isLoading } = useQuery<AppNotification[]>({
    queryKey: ["notifications"],
    queryFn: () => getNotifications(),
    staleTime: 30_000,
    select: (data) => { setNotifications(data); return data; },
  });

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-[var(--text-primary)]">Notifications</h1>
        <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Manage your alerts and notification preferences</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-lg w-fit">
        {(["inbox", "settings"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-1.5 rounded-md text-sm font-medium capitalize transition-colors",
              tab === t ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {t === "inbox" ? `Inbox${notifications.filter((n) => !n.is_read).length > 0 ? ` (${notifications.filter((n) => !n.is_read).length})` : ""}` : "Settings"}
          </button>
        ))}
      </div>

      {tab === "inbox" ? (
        isLoading ? (
          <div className="text-[var(--text-tertiary)] text-sm animate-pulse">Loading…</div>
        ) : (
          <InboxTab notifications={notifications} />
        )
      ) : (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
          <p className="text-xs text-[var(--text-tertiary)] mb-4">
            Choose which events notify you and via which channels. Email and push are coming soon.
          </p>
          <SettingsGrid />
        </div>
      )}
    </div>
  );
}
