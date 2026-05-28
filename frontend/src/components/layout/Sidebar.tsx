import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, LineChart, Filter, BookMarked, Briefcase, Bell,
  FlaskConical, LogOut, Newspaper, Calendar, Microscope, PlayCircle, Search,
  GraduationCap, Layers, Inbox, Compass, BookOpen, Users, Crown, Settings, Bitcoin,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import { useLearnStore } from "@/store/learnStore";
import { useNotificationStore } from "@/store/notificationStore";
import { useTierStore } from "@/store/tierStore";
import StreakBadge from "@/components/learn/StreakBadge";

const NAV_PRIMARY = [
  { to: "/", label: "Dashboard", Icon: LayoutDashboard },
  { to: "/chart", label: "Chart", Icon: LineChart },
  { to: "/screener", label: "Screener", Icon: Filter },
  { to: "/strategy", label: "Strategy Lab", Icon: FlaskConical },
  { to: "/options", label: "Options Lab", Icon: Layers },
  { to: "/crypto", label: "Crypto Lab", Icon: Bitcoin },
];

const NAV_MARKETS = [
  { to: "/news", label: "News", Icon: Newspaper },
  { to: "/earnings", label: "Earnings", Icon: Calendar },
  { to: "/research", label: "Research", Icon: Microscope },
  { to: "/discovery", label: "Discovery", Icon: Compass },
];

const NAV_ACCOUNT = [
  { to: "/watchlist", label: "Watchlist", Icon: BookMarked },
  { to: "/portfolio", label: "Portfolio", Icon: Briefcase },
  { to: "/paper", label: "Paper Trading", Icon: PlayCircle },
  { to: "/journal", label: "Trade Journal", Icon: BookOpen },
  { to: "/settings", label: "Settings", Icon: Settings },
  { to: "/alerts", label: "Alerts", Icon: Bell },
  { to: "/notifications", label: "Notifications", Icon: Inbox },
];

const NAV_COMMUNITY = [
  { to: "/social", label: "Community Feed", Icon: Users },
];

const NAV_LEARN = [
  { to: "/learn", label: "Learning Center", Icon: GraduationCap },
  { to: "/upgrade", label: "Upgrade", Icon: Crown },
];

function NavSection({ label, items }: { label: string; items: typeof NAV_PRIMARY }) {
  return (
    <div>
      <div className="px-3 mb-1.5 hidden lg:block">
        <span className="text-[10px] font-semibold text-[#334155] uppercase tracking-[0.12em]">{label}</span>
      </div>
      {items.map(({ to, label, Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 py-2 rounded-lg text-sm font-medium transition-colors duration-150 cursor-pointer",
              isActive
                ? "bg-[#1E293B] text-[#F8FAFC] px-3"
                : "text-[#64748B] hover:text-[#94A3B8] hover:bg-[#0F172A] px-3"
            )
          }
        >
          <Icon size={17} />
          <span className="hidden lg:block">{label}</span>
        </NavLink>
      ))}
    </div>
  );
}

interface Props {
  onOpenPalette?: () => void;
  onClose?: () => void;
}

export default function Sidebar({ onOpenPalette, onClose }: Props) {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const streak = useLearnStore((s) => s.progress?.streak ?? 0);
  const notifUnread = useNotificationStore((s) => s.unreadCount);
  const tier = useTierStore((s) => s.tier);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const initials = user?.username?.[0]?.toUpperCase() ?? "?";

  return (
    <aside className="w-14 lg:w-56 h-screen bg-[#0B1120] border-r border-[#1E293B] flex flex-col py-4 shrink-0">
      {/* Logo area */}
      <div className="px-3 mb-5 flex items-center gap-3">
        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[#2563EB] to-[#7C3AED] flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-lg shadow-blue-900/30">
          B
        </div>
        <span className="text-[#F1F5F9] font-bold tracking-tight hidden lg:block text-sm">BMG Capital</span>
      </div>

      {/* Cmd+K search trigger */}
      <div className="px-2 mb-4">
        <button
          onClick={onOpenPalette}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-[#0F172A]/80 border border-[#1E293B] text-[#475569] hover:text-[#94A3B8] hover:border-[#334155] transition-colors duration-150 text-xs cursor-pointer backdrop-blur-sm"
        >
          <Search size={13} />
          <span className="hidden lg:block flex-1 text-left">Search…</span>
          <kbd className="hidden lg:block text-[10px] bg-[#1E293B] border border-[#334155] px-1.5 py-0.5 rounded font-mono">⌘K</kbd>
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto min-h-0 px-2">
        <div className="space-y-4 pb-2">
        <NavSection label="TRADING" items={NAV_PRIMARY} />
        <NavSection label="MARKETS" items={NAV_MARKETS} />

        {/* ACCOUNT section with unread badge on Notifications */}
        <div>
          <div className="px-3 mb-1.5 hidden lg:block">
            <span className="text-[10px] font-semibold text-[#334155] uppercase tracking-[0.12em]">Account</span>
          </div>
          {NAV_ACCOUNT.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 py-2 rounded-lg text-sm font-medium transition-colors duration-150 cursor-pointer",
                  isActive
                    ? "bg-[#1E293B] text-[#F8FAFC] px-3"
                    : "text-[#64748B] hover:text-[#94A3B8] hover:bg-[#0F172A] px-3"
                )
              }
            >
              <Icon size={17} />
              <span className="hidden lg:block flex-1">{label}</span>
              {to === "/notifications" && notifUnread > 0 && (
                <span className="hidden lg:flex bg-[#EF4444] text-white text-[9px] font-bold rounded-full w-4 h-4 items-center justify-center">
                  {notifUnread > 9 ? "9+" : notifUnread}
                </span>
              )}
            </NavLink>
          ))}
          {/* Sign out — directly below Settings */}
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 py-2 px-3 w-full rounded-lg text-sm font-medium text-[#475569] hover:text-[#EF4444] hover:bg-[#EF4444]/8 transition-colors duration-150 cursor-pointer"
          >
            <LogOut size={17} />
            <span className="hidden lg:block">Sign out</span>
          </button>
        </div>

        {/* COMMUNITY section */}
        <NavSection label="COMMUNITY" items={NAV_COMMUNITY} />

        {/* LEARN section with streak badge */}
        <div>
          <div className="px-3 mb-1.5 hidden lg:flex items-center justify-between">
            <span className="text-[10px] font-semibold text-[#334155] uppercase tracking-[0.12em]">Learn</span>
            {streak > 0 && <StreakBadge streak={streak} size="sm" />}
          </div>
          {NAV_LEARN.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 py-2 rounded-lg text-sm font-medium transition-colors duration-150 cursor-pointer",
                  to === "/upgrade"
                    ? isActive
                      ? "bg-[#F59E0B]/10 text-[#F59E0B] px-3"
                      : "text-[#F59E0B]/60 hover:text-[#F59E0B] hover:bg-[#0F172A] px-3"
                    : isActive
                    ? "bg-[#1E293B] text-[#F8FAFC] px-3"
                    : "text-[#64748B] hover:text-[#94A3B8] hover:bg-[#0F172A] px-3"
                )
              }
            >
              <Icon size={17} />
              <span className="hidden lg:block">{label}</span>
            </NavLink>
          ))}
        </div>
        </div>
      </nav>

      {/* Bottom: user row */}
      <div className="px-2 mt-2 pt-3 border-t border-[#1E293B]">
        <div className="flex items-center gap-2.5 px-3 py-2">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[#3B82F6] to-[#8B5CF6] flex items-center justify-center text-xs text-white font-bold shrink-0">
            {initials}
          </div>
          <div className="hidden lg:flex flex-col flex-1 min-w-0">
            <span className="text-[#94A3B8] text-xs font-medium truncate">{user?.username ?? ""}</span>
            {tier !== "free" && (
              <span className={cn(
                "text-[9px] font-bold uppercase tracking-wider",
                tier === "premium" ? "text-[#F59E0B]" : "text-[#3B82F6]"
              )}>
                {tier === "premium" ? "Premium" : "Plus"}
              </span>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
