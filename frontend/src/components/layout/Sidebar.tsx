import { useState, useRef, useEffect } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, LineChart, BookMarked, Briefcase, BookOpen, BarChart2,
  FlaskConical, Layers, Bitcoin, PenTool, Radio,
  Filter, Newspaper, Microscope, Compass,
  Droplets, ShieldCheck, Activity,
  GraduationCap, Users, ScanSearch, Scale, Award,
  Search, Bell, Settings, LogOut, HelpCircle, ChevronUp, Inbox, Crown,
  Wallet, ScrollText, Building2, ArrowLeftRight, ClipboardList,
  Grid3X3, Zap, Globe, Eye, TestTube2, Cpu, SlidersHorizontal, Beaker,
  Radar, Hammer, ShieldAlert,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { getStatus as getAutonomousStatus, getLatestDigest } from "@/api/autonomous";
import { getBots, getStrategyLabPortfolio } from "@/api/bots";
import { getWatchlists } from "@/api/watchlist";
import { getPortfolios } from "@/api/bots";
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
  { to: "/",                label: "Dashboard",       Icon: LayoutDashboard },
  { to: "/mission-control", label: "Mission Control", Icon: Cpu },
  { to: "/risk-console",    label: "Risk Console",    Icon: ShieldAlert },
  { to: "/portfolio",       label: "Portfolio",       Icon: Briefcase },
  { to: "/markets",         label: "Markets",         Icon: Globe },
];

const NAV_LABS = [
  { to: "/strategy", label: "Strategy Lab", Icon: FlaskConical },
];

const NAV_BUILD = [
  { to: "/strategy/scout", label: "Strategy Scout", Icon: Radar  },
  { to: "/strategy/forge", label: "The Forge",      Icon: Hammer },
];

const NAV_MARKETS = [
  { to: "/screener",  label: "Screener",  Icon: Filter },
  { to: "/news",      label: "News",      Icon: Newspaper },
  { to: "/research",  label: "Research",  Icon: Microscope },
  { to: "/discovery", label: "Discovery", Icon: Compass },
];

const NAV_CRYPTO_PLUS = [
  { to: "/defi",     label: "DeFi",     Icon: Droplets },
  { to: "/security", label: "Security", Icon: ShieldCheck },
];

const NAV_LEARN = [
  { to: "/learn/tracks", label: "Learning Center", Icon: GraduationCap },
  { to: "/learn/certificates", label: "Certificates", Icon: Award },
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
  { to: "/admin",              label: "Bot Config",      Icon: SlidersHorizontal },
  { to: "/admin/monitoring",   label: "Monitoring",      Icon: Activity   },
  { to: "/admin/heatmap",      label: "Heat Map",        Icon: Grid3X3    },
  { to: "/admin/flow",         label: "Options Flow",    Icon: Zap        },
  { to: "/admin/macro",        label: "Macro Dashboard", Icon: Globe      },
  { to: "/admin/backtest",     label: "Backtest Lab",    Icon: TestTube2  },
  { to: "/admin/candidates",   label: "Candidates",      Icon: Beaker     },
  { to: "/admin/smart-money",  label: "Smart Money",     Icon: Eye        },
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
          "relative flex items-center gap-3 py-1.5 pl-3 pr-3 text-sm font-medium transition-colors duration-150 cursor-pointer",
          isActive
            ? "text-[var(--green)]"
            : "text-[var(--text-mid)] hover:text-[var(--text-hi)] hover:bg-[rgba(74,222,128,0.04)]"
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* Left accent bar */}
          {isActive && (
            <span className="absolute left-0 top-1 bottom-1 w-[3px] bg-[var(--green)]" />
          )}
          {/* Icon wrapper with optional dot */}
          <span className="relative shrink-0">
            <Icon size={15} />
            {pulseDot && (
              <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-[var(--green)] animate-pulse" />
            )}
            {staticDot && !pulseDot && (
              <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-[var(--green)]" />
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
        <span style={{ fontFamily: 'var(--font-mono-t)', fontSize: 9, letterSpacing: '0.15em', color: 'var(--text-dim)', textTransform: 'uppercase' }}>
          // {label}
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
          "absolute left-0 right-0 bottom-full mb-2 border border-[var(--border-mid)] shadow-2xl shadow-black/60 overflow-hidden z-50",
          expanded ? "w-full" : "w-52 left-0"
        )} style={{ background: 'var(--bg-2)' }}>
          {/* User identity header */}
          <div className="px-4 py-3 border-b border-[var(--border-dim)]">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[var(--accent-positive)] to-[#A78BFA] flex items-center justify-center text-xs font-bold text-white shrink-0">
                {initials}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[var(--text-primary)] truncate">{user?.username ?? "User"}</p>
                <p className="text-[10px] text-[var(--text-tertiary)] truncate">{user?.email ?? ""}</p>
                <span className={cn("inline-block mt-0.5 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full", tierColor)}>
                  {tierLabel}
                </span>
              </div>
            </div>
          </div>

          {/* Menu items */}
          <div className="py-1">
            <DropdownItem icon={Inbox} label="Notifications" badge={notifUnread} onClick={() => go("/notifications")} />
            <DropdownItem icon={Settings} label="Settings" onClick={() => go("/settings")} />
            <DropdownItem icon={HelpCircle} label="Help & Support" onClick={() => go("/support")} />
          </div>

          <div className="border-t border-[var(--border-dim)] py-1">
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
      "h-screen border-r border-[var(--border-subtle)] flex flex-col py-4 shrink-0 transition-[width] duration-300",
      expanded ? "w-56" : "w-14 lg:w-56"
    )} style={{ background: '#060a06' }}>
      {/* Logo — text wordmark */}
      <div className={cn("px-3 mb-4 flex items-center gap-1.5 h-9", show(expanded))}>
        <span style={{ fontFamily: 'var(--font-mono-t)', fontSize: 11, fontWeight: 700, letterSpacing: '0.18em', color: 'var(--green)' }}>
          // BMG CAPITAL
        </span>
        <span style={{ display: 'inline-block', width: 2, height: 13, background: 'var(--green)', animation: 'bmg-pulse 1.2s steps(1) infinite' }} />
      </div>
      {/* Icon mark — collapsed */}
      <div className={cn("px-3 mb-4 h-9 flex items-center", expanded ? "hidden" : "block lg:hidden")}>
        <svg viewBox="0 0 32 32" fill="none" className="w-7 h-7 shrink-0">
          <polyline points="3,25 9,17 14,21 22,8" stroke="#4ade80" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="22" cy="8" r="3" fill="#4ade80" />
        </svg>
      </div>

      {/* Search / ⌘K */}
      <div className="px-2 mb-4">
        <button
          onClick={onOpenPalette}
          className="w-full flex items-center gap-2 px-3 py-2 border border-[var(--border-dim)] text-[var(--text-dim)] hover:text-[var(--text-mid)] hover:border-[var(--border-mid)] transition-colors duration-150 text-xs cursor-pointer"
          style={{ background: 'var(--bg-2)', fontFamily: 'var(--font-mono-t)' }}
        >
          <Search size={12} className="shrink-0" />
          <span className={cn("flex-1 text-left truncate", show(expanded))}>ask bmg…</span>
          <kbd className={cn(
            "text-[10px] border border-[var(--border-dim)] px-1.5 py-0.5 font-mono",
            show(expanded)
          )} style={{ background: 'var(--bg-1)', color: 'var(--green)' }}>⌘K</kbd>
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

        <NavSection label="Build" items={NAV_BUILD} expanded={expanded} />

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
      <div className="px-2 pt-3 border-t border-[var(--border-dim)] space-y-1.5">
        {/* Upgrade button — only for non-premium users */}
        {tier !== "premium" && (
          <NavLink
            to="/upgrade"
            className={({ isActive }) => cn(
              "flex items-center gap-2.5 px-3 py-2 text-xs font-bold transition-all cursor-pointer w-full border border-[var(--border-mid)] hover:border-[var(--border-hot)] hover:bg-[rgba(74,222,128,0.06)]",
              isActive
                ? "bg-[rgba(74,222,128,0.10)] text-[var(--green)] border-[var(--border-hot)]"
                : "text-[var(--green)]"
            )}
            style={{ fontFamily: 'var(--font-mono-t)', letterSpacing: '0.08em' }}
          >
            <Crown size={13} className="shrink-0" />
            <span className={show(expanded)}>
              {tier === "plus" ? "// UPGRADE → PREMIUM" : "// UPGRADE → PLUS"}
            </span>
          </NavLink>
        )}

        {/* Avatar dropdown */}
        <AvatarDropdown expanded={expanded} onLogout={handleLogout} onClose={onClose} />

        {/* Build stamp */}
        {expanded && (
          <p className="text-[9px] text-zinc-700 px-3 pb-1 font-mono select-none">
            build 2026-06-12-A
          </p>
        )}
      </div>
    </aside>
  );
}
