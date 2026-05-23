import { useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { X, Bell, Trash2, CheckCheck, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { useNotificationStore } from "@/store/notificationStore";
import {
  getNotifications,
  markRead as apiMarkRead,
  markAllRead as apiMarkAllRead,
  deleteNotification as apiDelete,
} from "@/api/notifications";
import { EVENT_ICONS } from "@/types/notifications";
import type { AppNotification } from "@/types/notifications";

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  const h = Math.floor(diff / 3_600_000);
  const d = Math.floor(diff / 86_400_000);
  if (d >= 1) return `${d}d ago`;
  if (h >= 1) return `${h}h ago`;
  if (m >= 1) return `${m}m ago`;
  return "just now";
}

function groupByDay(notifications: AppNotification[]) {
  const groups: { label: string; items: AppNotification[] }[] = [];
  const map = new Map<string, AppNotification[]>();
  for (const n of notifications) {
    const date = new Date(n.created_at);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    let label: string;
    if (date.toDateString() === today.toDateString()) label = "Today";
    else if (date.toDateString() === yesterday.toDateString()) label = "Yesterday";
    else label = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    if (!map.has(label)) { map.set(label, []); groups.push({ label, items: map.get(label)! }); }
    map.get(label)!.push(n);
  }
  return groups;
}

export default function NotificationPanel() {
  const { panelOpen, closePanel, setNotifications, markRead, markAllRead, removeNotification } =
    useNotificationStore();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: rawData, isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => getNotifications(),
    staleTime: 30_000,
    enabled: panelOpen,
  });
  const data = Array.isArray(rawData) ? rawData : [];

  useEffect(() => {
    if (data.length > 0) setNotifications(data);
  }, [data, setNotifications]);

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

  // Close on Escape
  useEffect(() => {
    if (!panelOpen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") closePanel(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [panelOpen, closePanel]);

  const groups = groupByDay(data);
  const unread = data.filter((n) => !n.is_read).length;

  return (
    <>
      {/* Backdrop */}
      {panelOpen && (
        <div
          className="fixed inset-0 z-40 bg-[#020617]/40 backdrop-blur-sm"
          onClick={closePanel}
        />
      )}

      {/* Panel */}
      <div
        className={cn(
          "fixed top-0 right-0 h-full w-[380px] max-w-full bg-[#0F172A] border-l border-[#1E293B] z-50 flex flex-col transition-transform duration-300",
          panelOpen ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#1E293B] shrink-0">
          <div className="flex items-center gap-2">
            <Bell size={15} className="text-[#94A3B8]" />
            <span className="text-white font-semibold text-sm">Notifications</span>
            {unread > 0 && (
              <span className="bg-[#EF4444] text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                {unread}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {unread > 0 && (
              <button
                onClick={() => readAllMut.mutate()}
                title="Mark all read"
                className="text-[#475569] hover:text-[#F8FAFC] transition-colors"
              >
                <CheckCheck size={15} />
              </button>
            )}
            <button
              onClick={() => { closePanel(); navigate("/notifications"); }}
              title="Settings"
              className="text-[#475569] hover:text-[#F8FAFC] transition-colors"
            >
              <Settings size={15} />
            </button>
            <button onClick={closePanel} className="text-[#475569] hover:text-[#F8FAFC] transition-colors">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="p-6 text-center text-[#475569] text-sm animate-pulse">Loading…</div>
          ) : data.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-[#475569]">
              <Bell size={32} />
              <p className="text-sm">No notifications yet</p>
            </div>
          ) : (
            <div className="p-3 space-y-4">
              {groups.map(({ label, items }) => (
                <div key={label}>
                  <div className="text-[10px] font-semibold text-[#475569] uppercase tracking-wider px-2 mb-1.5">
                    {label}
                  </div>
                  <div className="space-y-1">
                    {items.map((n) => (
                      <NotifRow
                        key={n.id}
                        notif={n}
                        onRead={() => { if (!n.is_read) readMut.mutate(n.id); }}
                        onDelete={() => deleteMut.mutate(n.id)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function NotifRow({
  notif,
  onRead,
  onDelete,
}: {
  notif: AppNotification;
  onRead: () => void;
  onDelete: () => void;
}) {
  const icon = EVENT_ICONS[notif.event_type] ?? "🔔";
  return (
    <div
      onClick={onRead}
      className={cn(
        "group flex items-start gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-colors",
        notif.is_read ? "hover:bg-[#1E293B]" : "bg-[#1E293B] hover:bg-[#334155]"
      )}
    >
      <span className="text-base mt-0.5 shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className={cn("text-sm leading-snug", notif.is_read ? "text-[#94A3B8]" : "text-white font-medium")}>
          {notif.title}
        </div>
        {notif.body && (
          <div className="text-xs text-[#475569] mt-0.5 line-clamp-2">{notif.body}</div>
        )}
        <div className="text-[10px] text-[#475569] mt-1">{timeAgo(notif.created_at)}</div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {!notif.is_read && <span className="w-2 h-2 rounded-full bg-blue-500" />}
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="opacity-0 group-hover:opacity-100 text-[#475569] hover:text-[#EF4444] transition-all"
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}
