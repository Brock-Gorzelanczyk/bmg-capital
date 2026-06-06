import { useState, useRef, useEffect } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, LineChart, BookMarked, Briefcase, BookOpen, BarChart2,
  FlaskConical, Layers, Bitcoin, PenTool,
  Filter, Newspaper, Calendar, Microscope, Compass,
  Droplets, ShieldCheck, Activity,
  GraduationCap, Users, ScanSearch, Scale,
  Search, Bell, Settings, LogOut, HelpCircle, ChevronUp, Inbox, Crown,
  Wallet, ScrollText, Building2, ArrowLeftRight, ClipboardList,
  Grid3X3, Zap, Globe, Eye, TestTube2, Cpu,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { getStatus as getAutonomousStatus, getLatestDigest } from "@/api/autonomous";
import { getBots, getStrategyLabPortfolio } from "@/api/bots";
import { getWatchlists } from "@/api/watchlist";
import { getPortfolios } from "@/api/portfolio";
import { getNews } from "@/api/market";
import { getEntries as getJournalEntries, getStats as getJournalStats } from "@/api/journal";
import { chunkPrefetch } from "@/lib/chunkPrefetch";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import { useLearnStore } from "@/store/learnStore";
import { useNotificationStore } from "@/store/notificationStore";
import { useTierStore } from "@/store/tierStore";
import { useUiStore } from "@/store/uiStore";
import StreakBadge from "@/components/learn/StreakBadge";

// ─── Hover prefetch map ───────────────────────────────────────────────────────

const PREFETCH_MAP: Record<string, (qc: QueryClient) => void> = {
  "/strategy": (qc) => {
    qc.prefetchQuery({ queryKey: ["bots-v2"], queryFn: getBots, staleTime: 30_000 });
    qc.prefetchQuery({ queryKey: ["strategy-lab-portfolio"], queryFn: getStrategyLabPortfolio, staleTime: 30_000 });
  },
  "/watchlist": (qc) => {
    qc.prefetchQuery({ queryKey: ["watchlists"], queryFn: getWatchlists, staleTime: 30_000 });
  },
  "/portfolio": (qc) => {
    qc.prefetchQuery({ queryKey: ["portfolios"], queryFn: getPortfolios, staleTime: 30_000 });
  },
  "/news": (qc) => {
    qc.prefetchQuery({ queryKey: ["news"], queryFn: () => getNews(), staleTime: 30_000 });
  },
  "/journal": (qc) => {
    qc.prefetchQuery({ queryKey: ["journal-entries"], queryFn: () => getJournalEntries(), staleTime: 30_000 });
    qc.prefetchQuery({ queryKey: ["journal-stats"], queryFn: getJournalStats, staleTime: 30_000 });
  },
};

// ─── Nav item definitions ─────────────────────────────────────────────────────

const NAV_TRADE = [
  { to: "/",                 label: "Dashboard",       Icon: LayoutDashboard },
  { to: "/net-worth",        label: "Net Worth",       Icon: Globe },
  { to: "/mission-control",  label: "Mission Control", Icon: Cpu },
  { to: "/autopilot",        label: "Autopilot",       Icon: Zap },
  { to: "/chart",            label: "Chart",           Icon: LineChart },
  { to: "/portfolio",        label: "Portfolio",       Icon: Briefcase },
  { to: "/pods",             label: "Capital Pods",    Icon: Layers },
  { to: "/watchlist",        label: "Watchlist",       Icon: BookMarked },
  { to: "/journal",          label: "Trade Journal",   Icon: BookOpen },
  { to: "/analytics",        label: "Analytics",       Icon: BarChart2 },
];

const NAV_LABS = [
  { to: "/strategy", label: "Strategy Lab",  Icon: FlaskConical },
  { to: "/options",  label: "Options Lab",   Icon: Layers },
  { to: "/crypto",   label: "Crypto Lab",    Icon: Bitcoin },
  { to: "/workshop", label: "TA Workshop",   Icon: PenTool },
  { to: "/paper",    label: "Paper Trading", Icon: Wallet },
];

const NAV_MARKETS = [
  { to: "/screener",  label: "Screener",  Icon: Filter },
  { to: "/news",      label: "News",      Icon: Newspaper },
  { to: "/earnings",  label: "Earnings",  Icon: Calendar },
  { to: "/research",  label: "Research",  Icon: Microscope },
  { to: "/discovery", label: "Discovery", Icon: Compass },
  { to: "/alerts",    label: "Alerts",    Icon: Bell },
];

const NAV_CRYPTO_PLUS = [
  { to: "/defi",     label: "DeFi",     Icon: Droplets },
  { to: "/security", label: "Security", Icon: ShieldCheck },
];

const NAV_LEARN = [
  { to: "/learn", label: "Learning Center", Icon: GraduationCap },
];

const NAV_TOOLS = [
  { to: "/tax-xray",       label: "Tax X-Ray",      Icon: ScanSearch },
  { to: "/risk-parity",    label: "Risk Parity",     Icon: Scale },
  { to: "/smart-transfers",label: "Smart Transfers", Icon: ArrowLeftRight },
  { to: "/rsu-console",    label: "RSU Console",     Icon: ClipboardList },
  { to: "/estate",         label: "Estate Plan",     Icon: Building2 },
  { to: "/rules",          label: "Trading Rules",   Icon: ScrollText },
];

const NAV_COMMUNITY = [
  { to: "/social", label: "Community Feed", Icon: Users },
];

const NAV_ADMIN = [
  { to: "/admin/monitoring",   label: "Monitoring",     Icon: Activity   },
  { to: "/admin/heatmap",      label: "Heat Map",        Icon: Grid3X3    },
  { to: "/admin/flow",         label: "Options Flow",    Icon: Zap        },
  { to: "/admin/macro",        label: "Macro Dashboard", Icon: Globe      },
  { to: "/admin/smart-money",  label: "Smart Money",     Icon: Eye        },
  { to: "/admin/backtest",     label: "Backtest Lab",    Icon: TestTube2  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function show(expanded: boolean) {
  return expanded ? "block" : "hidden lg:block";
}

function showFlex(expanded: boolean) {
  return expanded ? "flex" : "hidden lg:flex";
}

// ─── NavItem — single nav link with active left-bar ──────────────────────────

function NavItem({
  to,
  label,
  Icon,
  expanded,
  badge,
  end: endProp,
  pulseDot,
  staticDot,
  prefetchFn,
}: {
  to: string;
  label: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
  expanded: boolean;
  badge?: number;
  end?: boolean;
  /** If true, show an animated lime dot (engine live) */
  pulseDot?: boolean;
  /** If true, show a static lime dot (digest available) */
  staticDot?: boolean;
  /** Called on hover — fires chunk + data prefetch for this route */
  prefetchFn?: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={endProp ?? to === "/"}
      onMouseEnter={prefetchFn}
      className={({ isActive }) =>
        cn(
          "relative flex items-center gap-3 py-2 pl-3 pr-3 rounded-lg text-sm font-medium transition-colors duration-150 cursor-pointer",
          isActive
            ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]"
            : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]"
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* Left accent bar */}
          {isActive && (
            <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 bg-[var(--accent-positive)] rounded-full" />
          )}
          {/* Icon wrapper with optional dot */}
          <span className="relative shrink-0">
            <Icon size={16} />
            {pulseDot && (
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-[#84cc16] animate-pulse" />
            )}
            {staticDot && !pulseDot && (
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-[#84cc16]" />
            )}
          </span>
          <span className={cn("flex-1 truncate", show(expanded))}>{label}</span>
          {badge != null && badge > 0 && (
            <span className={cn(
              "bg-[var(--accent-negative)] text-white text-[9px] font-bold rounded-full w-4 h-4 items-center justify-center shrink-0",
              showFlex(expanded)
            )}>
              {badge > 9 ? "9+" : badge}
            </span>
          )}
        </>
      )}
    </NavLink>
  );
}

// ─── NavSection ───────────────────────────────────────────────────────────────

function NavSection({
  label,
  items,
  expanded,
  headerRight,
  itemDots,
}: {
  label: string;
  items: { to: string; label: string; Icon: React.ComponentType<{ size?: number; className?: string }> }[];
  expanded: boolean;
  headerRight?: React.ReactNode;
  itemDots?: Record<string, { pulse?: boolean; static?: boolean }>;
}) {
  const qc = useQueryClient();
  return (
    <div>
      <div className={cn("px-3 mb-1 flex items-center justify-between", show(expanded))}>
        <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em]">
          {label}
        </span>
        {headerRight}
      </div>
      <div className="space-y-0.5">
        {items.map(({ to, label: itemLabel, Icon }) => (
          <NavItem
            key={to}
            to={to}
            label={itemLabel}
            Icon={Icon}
            expanded={expanded}
            pulseDot={itemDots?.[to]?.pulse}
            staticDot={itemDots?.[to]?.static}
            prefetchFn={() => {
              chunkPrefetch[to]?.();
              PREFETCH_MAP[to]?.(qc);
            }}
          />
        ))}
      </div>
    </div>
  );
}

// ─── Avatar dropdown ──────────────────────────────────────────────────────────

function AvatarDropdown({
  expanded,
  onLogout,
  onClose,
}: {
  expanded: boolean;
  onLogout: () => void;
  onClose?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const notifUnread = useNotificationStore((s) => s.unreadCount);
  const tier = useTierStore((s) => s.tier);

  const initials = user?.username?.[0]?.toUpperCase() ?? "?";

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function go(path: string) {
    navigate(path);
    setOpen(false);
    onClose?.();
  }

  function handleLogout() {
    setOpen(false);
    onLogout();
  }

  const tierLabel = tier === "premium" ? "Premium" : tier === "plus" ? "Plus" : "Free";
  const tierColor = tier === "premium"
    ? "text-[#F59E0B] bg-[#F59E0B]/10"
    : tier === "plus"
    ? "text-[var(--accent-positive)] bg-[var(--accent-positive)]/10"
    : "text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)]";

  return (
    <div ref={ref} className="relative">
      {/* Dropdown menu — opens upward */}
      {open && (
        <div className={cn(
          "absolute left-0 right-0 bottom-full mb-2 bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl shadow-2xl shadow-black/40 overflow-hidden z-50",
          expanded ? "w-full" : "w-52 left-0"
        )}>
          {/* User identity header */}
          <div className="px-4 py-3 border-b border-[var(--border-subtle)]">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[var(--accent-positive)] to-[#A78BFA] flex items-center justify-center text-xs font-bold text-white shrink-0">
                {initials}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[var(--text-primary)] truncate">{user?.username ?? "User"}</p>
                <p className="text-[10px] text-[var(--text-tertiary)] truncate">{user?.email ?? ""}</p>
              </div>
              <span className={cn("text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full shrink-0", tierColor)}>
                {tierLabel}
              </span>
            </div>
          </div>

          {/* Menu items */}
          <div className="py-1">
            <DropdownItem icon={Inbox} label="Notifications" badge={notifUnread} onClick={() => go("/notifications")} />
            <DropdownItem icon={Settings} label="Settings" onClick={() => go("/settings")} />
            <DropdownItem icon={HelpCircle} label="Help & Support" onClick={() => go("/support")} />
          </div>

          <div className="border-t border-[var(--border-subtle)] py-1">
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-3 px-4 py-2 text-sm text-[var(--accent-negative)] hover:bg-[var(--accent-negative)]/8 transition-colors cursor-pointer"
            >
              <LogOut size={15} />
              <span>Sign out</span>
            </button>
          </div>
        </div>
      )}

      {/* Trigger row */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "w-full flex items-center gap-2.5 px-3 py-2 rounded-xl hover:bg-[var(--bg-elevated)] transition-colors cursor-pointer group",
          open && "bg-[var(--bg-elevated)]"
        )}
      >
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--accent-positive)] to-[#A78BFA] flex items-center justify-center text-xs text-white font-bold shrink-0">
          {initials}
        </div>
        <div className={cn("flex flex-col flex-1 min-w-0 text-left", show(expanded))}>
          <span className="text-[var(--text-secondary)] text-xs font-medium truncate">{user?.username ?? ""}</span>
          <span className={cn(
            "text-[9px] font-bold uppercase tracking-wider",
            tier === "premium" ? "text-[#F59E0B]" : tier === "plus" ? "text-[var(--accent-positive)]" : "text-[var(--text-tertiary)]"
          )}>
            {tierLabel}
          </span>
        </div>
        <ChevronUp
          size={13}
          className={cn(
            "shrink-0 text-[var(--text-tertiary)] transition-transform duration-200",
            show(expanded),
            open ? "rotate-180" : "rotate-0"
          )}
        />
        {/* Unread dot when collapsed */}
        {notifUnread > 0 && (
          <span className={cn(
            "absolute top-1 right-1 w-2 h-2 bg-[var(--accent-negative)] rounded-full",
            expanded ? "hidden" : "block lg:hidden"
          )} />
        )}
      </button>
    </div>
  );
}

function DropdownItem({
  icon: Icon,
  label,
  badge,
  onClick,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  badge?: number;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)] transition-colors cursor-pointer"
    >
      <Icon size={15} className="shrink-0" />
      <span className="flex-1 text-left">{label}</span>
      {badge != null && badge > 0 && (
        <span className="bg-[var(--accent-negative)] text-white text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
          {badge > 9 ? "9+" : badge}
        </span>
      )}
    </button>
  );
}

// ─── Main Sidebar ─────────────────────────────────────────────────────────────

interface Props {
  onOpenPalette?: () => void;
  onClose?: () => void;
  expanded?: boolean;
}

export default function Sidebar({ onOpenPalette, onClose, expanded = false }: Props) {
  const { logout, user } = useAuthStore();
  const navigate = useNavigate();
  const streak = useLearnStore((s) => s.progress?.streak ?? 0);
  const tier = useTierStore((s) => s.tier);
  const isAdmin = user?.is_admin === true;
  const mode = useUiStore((s) => s.mode);

  const { data: autoStatus } = useQuery({
    queryKey: ["autonomous-status"],
    queryFn: getAutonomousStatus,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: latestDigest } = useQuery({
    queryKey: ["autonomous-digest-latest"],
    queryFn: getLatestDigest,
    staleTime: 5 * 60 * 1000,
  });

  const todayStr = new Date().toISOString().slice(0, 10);
  const showAutonomousDot =
    autoStatus?.engine_running === true && autoStatus?.autonomous_paused !== true;
  const showDigestDot = latestDigest?.digest_date?.slice(0, 10) === todayStr;

  const handleLogout = () => {
    logout();
    navigate("/login");
    onClose?.();
  };

  return (
    <aside className={cn(
      "h-screen bg-[var(--bg-base)] border-r border-[var(--border-subtle)] flex flex-col py-4 shrink-0 transition-[width] duration-300",
      expanded ? "w-56" : "w-14 lg:w-56"
    )}>
      {/* Logo */}
      <div className="px-3 mb-5 flex items-center">
        {/* Full logo — shown when expanded or on lg+ */}
        <img
          src="/logo.png"
          alt="BMG Capital"
          className={cn("h-7 w-auto object-contain", show(expanded))}
        />
        {/* Icon mark — shown on tablet collapsed (md to lg, not expanded) */}
        <svg
          viewBox="0 0 32 32"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={cn("w-8 h-8 shrink-0", expanded ? "hidden" : "block lg:hidden")}
        >
          <polyline points="3,25 9,17 14,21 22,8" stroke="#3ECF8E" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="22" cy="8" r="3" fill="#3ECF8E" />
        </svg>
      </div>

      {/* Search / ⌘K */}
      <div className="px-2 mb-4">
        <button
          onClick={onOpenPalette}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--bg-elevated)]/80 border border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:border-[var(--border-emphasis)] transition-colors duration-150 text-xs cursor-pointer"
        >
          <Search size={13} className="shrink-0" />
          <span className={cn("flex-1 text-left", show(expanded))}>Ask BMG Intelligence…</span>
          <kbd className={cn(
            "text-[10px] bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] px-1.5 py-0.5 rounded font-mono text-[var(--accent-positive)] font-semibold",
            show(expanded)
          )}>⌘K</kbd>
        </button>
      </div>

      {/* Nav sections */}
      <nav className="flex-1 overflow-y-auto min-h-0 px-2 space-y-4 pb-2">
        <NavSection
          label="Trade"
          items={NAV_TRADE}
          expanded={expanded}
          itemDots={{
            "/":               { static: showDigestDot },
            "/mission-control":{ pulse: showAutonomousDot },
          }}
        />

        <NavSection label="Labs" items={NAV_LABS} expanded={expanded} />

        <NavSection label="Markets" items={NAV_MARKETS} expanded={expanded} />

        <NavSection label="Crypto+" items={NAV_CRYPTO_PLUS} expanded={expanded} />

        <NavSection
          label="Learn"
          items={NAV_LEARN}
          expanded={expanded}
          headerRight={streak > 0 ? <StreakBadge streak={streak} size="sm" /> : undefined}
        />

        {mode === "pro" && <NavSection label="Tools" items={NAV_TOOLS} expanded={expanded} />}

        {mode === "pro" && <NavSection label="Community" items={NAV_COMMUNITY} expanded={expanded} />}

        {isAdmin && <NavSection label="Admin" items={NAV_ADMIN} expanded={expanded} />}
      </nav>

      {/* Bottom: Upgrade + Avatar */}
      <div className="px-2 pt-3 border-t border-[var(--border-subtle)] space-y-1.5">
        {/* Upgrade button — only for non-premium users */}
        {tier !== "premium" && (
          <NavLink
            to="/upgrade"
            className={({ isActive }) => cn(
              "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-semibold transition-all cursor-pointer w-full",
              isActive
                ? "bg-[var(--accent-positive)]/15 text-[var(--accent-positive)]"
                : "bg-[var(--accent-positive)]/8 text-[var(--accent-positive)] hover:bg-[var(--accent-positive)]/15"
            )}
          >
            <Crown size={15} className="shrink-0" />
            <span className={show(expanded)}>
              {tier === "plus" ? "Upgrade to Premium" : "Upgrade to Plus"}
            </span>
          </NavLink>
        )}

        {/* Avatar dropdown */}
        <AvatarDropdown expanded={expanded} onLogout={handleLogout} onClose={onClose} />
      </div>
    </aside>
  );
}
