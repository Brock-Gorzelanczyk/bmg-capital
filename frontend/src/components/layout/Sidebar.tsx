import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, LineChart, Filter, BookMarked, Briefcase, Bell,
  FlaskConical, LogOut, Newspaper, Calendar, Microscope, PlayCircle, Search,
  GraduationCap, Layers, Inbox, Compass, BookOpen, Users, Crown, Settings, Bitcoin,
  Droplets, ShieldCheck,
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
  { to: "/defi", label: "DeFi", Icon: Droplets },
  { to: "/security", label: "Security", Icon: ShieldCheck },
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

// show(expanded): visible when expanded OR on lg+ screens
function show(expanded: boolean) {
  return expanded ? "block" : "hidden lg:block";
}

function NavSection({ label, items, expanded }: { label: string; items: typeof NAV_PRIMARY; expanded: boolean }) {
  return (
    <div>
      <div className={cn("px-3 mb-1.5", show(expanded))}>
        <span className="text-[10px] font-semibold text-[var(--border-emphasis)] uppercase tracking-[0.12em]">{label}</span>
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
                ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)] px-3"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] px-3"
            )
          }
        >
          <Icon size={17} />
          <span className={show(expanded)}>{label}</span>
        </NavLink>
      ))}
    </div>
  );
}

interface Props {
  onOpenPalette?: () => void;
  onClose?: () => void;
  expanded?: boolean;
}

export default function Sidebar({ onOpenPalette, onClose, expanded = false }: Props) {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const streak = useLearnStore((s) => s.progress?.streak ?? 0);
  const notifUnread = useNotificationStore((s) => s.unreadCount);
  const tier = useTierStore((s) => s.tier);

  const handleLogout = () => {
    logout();
    navigate("/login");
    onClose?.();
  };

  const initials = user?.username?.[0]?.toUpperCase() ?? "?";

  return (
    <aside className={cn(
      "h-screen bg-[var(--bg-base)] border-r border-[var(--border-subtle)] flex flex-col py-4 shrink-0 transition-[width] duration-300",
      expanded ? "w-56" : "w-14 lg:w-56"
    )}>
      {/* Logo */}
      <div className="px-3 mb-5 flex items-center gap-3">
        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[#2563EB] to-[#7C3AED] flex items-center justify-center text-xs font-bold text-[var(--text-primary)] shrink-0 shadow-lg shadow-blue-900/30">
          B
        </div>
        <span className={cn("text-[#F1F5F9] font-bold tracking-tight text-sm", show(expanded))}>BMG Capital</span>
      </div>

      {/* Cmd+K */}
      <div className="px-2 mb-4">
        <button
          onClick={onOpenPalette}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--bg-elevated)]/80 border border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:border-[var(--border-emphasis)] transition-colors duration-150 text-xs cursor-pointer backdrop-blur-sm"
        >
          <Search size={13} className="flex-shrink-0" />
          <span className={cn("flex-1 text-left", show(expanded))}>Ask BMG Intelligence…</span>
          <kbd className={cn("text-[10px] bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] px-1.5 py-0.5 rounded font-mono", show(expanded))}>⌘K</kbd>
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto min-h-0 px-2">
        <div className="space-y-4 pb-2">
          <NavSection label="TRADING" items={NAV_PRIMARY} expanded={expanded} />
          <NavSection label="MARKETS" items={NAV_MARKETS} expanded={expanded} />

          {/* ACCOUNT */}
          <div>
            <div className={cn("px-3 mb-1.5", show(expanded))}>
              <span className="text-[10px] font-semibold text-[var(--border-emphasis)] uppercase tracking-[0.12em]">Account</span>
            </div>
            {NAV_ACCOUNT.map(({ to, label, Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 py-2 rounded-lg text-sm font-medium transition-colors duration-150 cursor-pointer",
                    isActive
                      ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)] px-3"
                      : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] px-3"
                  )
                }
              >
                <Icon size={17} />
                <span className={cn("flex-1", show(expanded))}>{label}</span>
                {to === "/notifications" && notifUnread > 0 && (
                  <span className={cn("bg-[var(--accent-negative)] text-[var(--text-primary)] text-[9px] font-bold rounded-full w-4 h-4 items-center justify-center", expanded ? "flex" : "hidden lg:flex")}>
                    {notifUnread > 9 ? "9+" : notifUnread}
                  </span>
                )}
              </NavLink>
            ))}
            <button
              onClick={handleLogout}
              className="flex items-center gap-3 py-2 px-3 w-full rounded-lg text-sm font-medium text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] hover:bg-[var(--accent-negative)]/8 transition-colors duration-150 cursor-pointer"
            >
              <LogOut size={17} />
              <span className={show(expanded)}>Sign out</span>
            </button>
          </div>

          <NavSection label="COMMUNITY" items={NAV_COMMUNITY} expanded={expanded} />

          {/* LEARN */}
          <div>
            <div className={cn("px-3 mb-1.5 flex items-center justify-between", show(expanded))}>
              <span className="text-[10px] font-semibold text-[var(--border-emphasis)] uppercase tracking-[0.12em]">Learn</span>
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
                        : "text-[#F59E0B]/60 hover:text-[#F59E0B] hover:bg-[var(--bg-elevated)] px-3"
                      : isActive
                      ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)] px-3"
                      : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] px-3"
                  )
                }
              >
                <Icon size={17} />
                <span className={show(expanded)}>{label}</span>
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      {/* User row */}
      <div className="px-2 mt-2 pt-3 border-t border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5 px-3 py-2">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--accent-positive)] to-[#A78BFA] flex items-center justify-center text-xs text-[var(--text-primary)] font-bold shrink-0">
            {initials}
          </div>
          <div className={cn("flex flex-col flex-1 min-w-0", show(expanded))}>
            <span className="text-[var(--text-secondary)] text-xs font-medium truncate">{user?.username ?? ""}</span>
            {tier !== "free" && (
              <span className={cn(
                "text-[9px] font-bold uppercase tracking-wider",
                tier === "premium" ? "text-[#F59E0B]" : "text-[var(--accent-positive)]"
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
