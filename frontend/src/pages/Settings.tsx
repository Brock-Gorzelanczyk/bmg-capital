import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  LogOut, User, Crown, Zap, Star, ExternalLink, AlertCircle, TrendingUp,
  Bell, Shield, Eye, Palette, CreditCard, Database, Monitor, ChevronRight,
  Check, Copy, Trash2, Download, Lock, Key, Smartphone, Globe, BarChart2,
  Moon, Sun, Sliders, RefreshCw, AlertTriangle, Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import { getMyTier, createPortal } from "@/api/tiers";
import { useTierStore } from "@/store/tierStore";
import { getNotifSettings, updateNotifSettings } from "@/api/notifications";
import type { TierName } from "@/api/tiers";
import { toast } from "sonner";

const TIER_META: Record<TierName, { label: string; Icon: typeof Star; color: string; bg: string }> = {
  free:    { label: "Free",    Icon: Star,  color: "text-[var(--text-secondary)]",  bg: "bg-[var(--bg-elevated-2)]" },
  plus:    { label: "Plus",    Icon: Zap,   color: "text-[var(--accent-positive)]", bg: "bg-[var(--accent-positive)]/10" },
  premium: { label: "Premium", Icon: Crown, color: "text-[#F59E0B]",               bg: "bg-[#F59E0B]/10" },
};

const SECTIONS = [
  { id: "profile",       label: "Profile",       Icon: User      },
  { id: "appearance",    label: "Appearance",    Icon: Palette   },
  { id: "trading",       label: "Trading",       Icon: BarChart2 },
  { id: "notifications", label: "Notifications", Icon: Bell      },
  { id: "privacy",       label: "Privacy & Data",Icon: Eye       },
  { id: "security",      label: "Security",      Icon: Shield    },
  { id: "subscription",  label: "Subscription",  Icon: CreditCard},
  { id: "danger",        label: "Sign out",      Icon: LogOut    },
] as const;

type SectionId = typeof SECTIONS[number]["id"];

// ── Preference helpers ────────────────────────────────────────────────────────

const PREFS_KEY = "bmg_ui_prefs";
function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}"); } catch { return {}; }
}
function savePrefs(patch: Record<string, unknown>) {
  const current = loadPrefs();
  localStorage.setItem(PREFS_KEY, JSON.stringify({ ...current, ...patch }));
}
function applyPrefs(patch: Record<string, unknown>) {
  const html = document.documentElement;
  if ("theme" in patch && patch.theme)     html.dataset.theme   = patch.theme as string;
  if ("density" in patch && patch.density) html.dataset.density = patch.density as string;
}

// ── Sub-sections ──────────────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-5">
      <h2 className="text-base font-bold text-[var(--text-primary)]">{title}</h2>
      {subtitle && <p className="text-[var(--text-tertiary)] text-sm mt-0.5">{subtitle}</p>}
    </div>
  );
}

function SettingRow({
  label, sublabel, children, last,
}: {
  label: string; sublabel?: string; children: React.ReactNode; last?: boolean;
}) {
  return (
    <div className={cn(
      "flex items-center justify-between px-4 py-3 gap-4 min-h-[52px]",
      !last && "border-b border-[var(--border-subtle)]/60"
    )}>
      <div className="min-w-0">
        <div className="text-sm text-[var(--text-primary)]">{label}</div>
        {sublabel && <div className="text-xs text-[var(--text-tertiary)] mt-0.5">{sublabel}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={cn(
        "relative w-10 h-5.5 rounded-full transition-colors focus:outline-none",
        value ? "bg-[var(--accent-positive)]" : "bg-[#334155]"
      )}
      style={{ height: "22px", width: "40px" }}
    >
      <span className={cn(
        "absolute top-0.5 left-0.5 w-4.5 h-4.5 bg-white rounded-full shadow transition-transform",
        value ? "translate-x-[18px]" : "translate-x-0"
      )} style={{ height: "18px", width: "18px" }} />
    </button>
  );
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn(
      "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden",
      className
    )}>
      {children}
    </div>
  );
}

// ── Profile ───────────────────────────────────────────────────────────────────

function ProfileSection() {
  const { user } = useAuthStore();
  const [copied, setCopied] = useState(false);

  const initials = (user?.username ?? "?").slice(0, 2).toUpperCase();
  const colors = ["#3B82F6", "#10B981", "#8B5CF6", "#F59E0B", "#EF4444"];
  const colorIdx = (user?.username?.charCodeAt(0) ?? 0) % colors.length;
  const avatarColor = colors[colorIdx];

  const copyId = () => {
    navigator.clipboard.writeText(String(user?.id ?? ""));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Profile" subtitle="Your account information" />

      <Card>
        {/* Avatar + name */}
        <div className="flex items-center gap-4 px-5 py-5 border-b border-[var(--border-subtle)]/60">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center text-xl font-bold text-white shrink-0"
            style={{ background: avatarColor }}
          >
            {initials}
          </div>
          <div>
            <div className="text-[var(--text-primary)] font-semibold text-base">{user?.username ?? "—"}</div>
            <div className="text-[var(--text-tertiary)] text-sm">{user?.email ?? "—"}</div>
            <div className="text-[var(--text-tertiary)] text-xs mt-1">Member since {new Date().getFullYear()}</div>
          </div>
        </div>

        <SettingRow label="Username">
          <span className="text-sm text-[var(--text-secondary)] font-mono">{user?.username ?? "—"}</span>
        </SettingRow>
        <SettingRow label="Email">
          <span className="text-sm text-[var(--text-secondary)]">{user?.email ?? "—"}</span>
        </SettingRow>
        <SettingRow label="User ID" last>
          <button
            onClick={copyId}
            className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors font-mono"
          >
            #{user?.id}
            {copied ? <Check size={11} className="text-[var(--accent-positive)]" /> : <Copy size={11} />}
          </button>
        </SettingRow>
      </Card>

      <div className="flex items-start gap-2.5 px-1">
        <Info size={12} className="text-[var(--text-tertiary)] shrink-0 mt-0.5" />
        <p className="text-xs text-[var(--text-tertiary)]">
          To change your email or username, contact support. Profile photos coming soon.
        </p>
      </div>
    </div>
  );
}

// ── Appearance ────────────────────────────────────────────────────────────────

const DENSITY_OPTIONS = [
  { value: "compact",  label: "Compact",  desc: "Dense rows, smaller text" },
  { value: "default",  label: "Default",  desc: "Balanced spacing" },
  { value: "spacious", label: "Spacious", desc: "More breathing room" },
];

const CHART_STYLE_OPTIONS = [
  { value: "candles", label: "Candlesticks" },
  { value: "bars",    label: "OHLC Bars" },
  { value: "line",    label: "Line" },
  { value: "area",    label: "Area" },
];

const TIMEZONE_OPTIONS = [
  { value: "America/New_York",   label: "Eastern (ET)" },
  { value: "America/Chicago",    label: "Central (CT)" },
  { value: "America/Denver",     label: "Mountain (MT)" },
  { value: "America/Los_Angeles",label: "Pacific (PT)" },
  { value: "UTC",                label: "UTC" },
  { value: "Europe/London",      label: "London (GMT)" },
  { value: "Europe/Berlin",      label: "Berlin (CET)" },
  { value: "Asia/Tokyo",         label: "Tokyo (JST)" },
];

function AppearanceSection() {
  const prefs = loadPrefs();
  const [theme, setTheme]        = useState<string>(prefs.theme      ?? "dark");
  const [density, setDensity]    = useState<string>(prefs.density    ?? "default");
  const [chartStyle, setChart]   = useState<string>(prefs.chartStyle ?? "candles");
  const [timezone, setTimezone]  = useState<string>(prefs.timezone   ?? "America/New_York");
  const [colorblind, setColorblind] = useState<boolean>(prefs.colorblind ?? false);
  const [animations, setAnimations] = useState<boolean>(prefs.animations ?? true);

  const persist = (patch: Record<string, unknown>) => {
    savePrefs(patch);
    applyPrefs(patch);
    toast.success("Preference saved");
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Appearance" subtitle="Customize how BMG looks and feels" />

      {/* Theme */}
      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Theme</span>
        </div>
        <div className="px-4 py-4 flex items-center gap-3">
          {[
            { value: "dark",  Icon: Moon,  label: "Dark" },
            { value: "light", Icon: Sun,   label: "Light" },
            { value: "system",Icon: Monitor,label: "System" },
          ].map(({ value, Icon, label }) => (
            <button
              key={value}
              onClick={() => { setTheme(value); persist({ theme: value }); }}
              className={cn(
                "flex-1 flex flex-col items-center gap-1.5 py-3 rounded-xl border text-xs font-medium transition-colors",
                theme === value
                  ? "bg-[var(--bg-elevated-2)] border-[var(--accent-positive)] text-[var(--accent-positive)]"
                  : "border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              )}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>
      </Card>

      {/* Density */}
      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Density</span>
        </div>
        <div className="px-4 py-3 space-y-2">
          {DENSITY_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => { setDensity(opt.value); persist({ density: opt.value }); }}
              className={cn(
                "w-full flex items-center justify-between px-3 py-2.5 rounded-lg border text-left transition-colors",
                density === opt.value
                  ? "border-[var(--accent-positive)] bg-[var(--accent-positive)]/5"
                  : "border-transparent hover:bg-[var(--bg-elevated-2)]"
              )}
            >
              <div>
                <div className={cn("text-sm font-medium", density === opt.value ? "text-[var(--accent-positive)]" : "text-[var(--text-secondary)]")}>{opt.label}</div>
                <div className="text-xs text-[var(--text-tertiary)]">{opt.desc}</div>
              </div>
              {density === opt.value && <Check size={14} className="text-[var(--accent-positive)]" />}
            </button>
          ))}
        </div>
      </Card>

      {/* Chart & display */}
      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Chart & Display</span>
        </div>
        <SettingRow label="Default chart style">
          <select
            value={chartStyle}
            onChange={(e) => { setChart(e.target.value); persist({ chartStyle: e.target.value }); }}
            className="bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-xs rounded-lg px-2 py-1.5 focus:outline-none"
          >
            {CHART_STYLE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </SettingRow>
        <SettingRow label="Timezone">
          <select
            value={timezone}
            onChange={(e) => { setTimezone(e.target.value); persist({ timezone: e.target.value }); }}
            className="bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-xs rounded-lg px-2 py-1.5 focus:outline-none"
          >
            {TIMEZONE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </SettingRow>
        <SettingRow label="Colorblind-friendly mode" sublabel="Replaces red/green with blue/orange">
          <Toggle value={colorblind} onChange={(v) => { setColorblind(v); persist({ colorblind: v }); }} />
        </SettingRow>
        <SettingRow label="UI animations" sublabel="Disable for better performance" last>
          <Toggle value={animations} onChange={(v) => { setAnimations(v); persist({ animations: v }); }} />
        </SettingRow>
      </Card>
    </div>
  );
}

// ── Trading Preferences ────────────────────────────────────────────────────────

const ORDER_TYPE_OPTIONS = ["market", "limit", "stop_limit"];
const RISK_OPTIONS = ["0.5", "1", "1.5", "2", "2.5", "3", "5"];

function TradingSection() {
  const prefs = loadPrefs();
  const [riskPct, setRiskPct]        = useState<string>(prefs.riskPerTrade     ?? "1");
  const [orderType, setOrderType]    = useState<string>(prefs.defaultOrder     ?? "market");
  const [confirmOrders, setConfirm]  = useState<boolean>(prefs.confirmOrders   ?? true);
  const [showPnL, setShowPnL]        = useState<boolean>(prefs.showPnL         ?? true);
  const [extended, setExtended]      = useState<boolean>(prefs.extendedHours   ?? false);

  const persist = (patch: Record<string, unknown>) => {
    savePrefs(patch);
    toast.success("Trading preference saved");
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Trading" subtitle="Defaults for orders" />

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Risk Management</span>
        </div>
        <SettingRow label="Risk per trade" sublabel="% of account risked per position" last>
          <select
            value={riskPct}
            onChange={(e) => { setRiskPct(e.target.value); persist({ riskPerTrade: e.target.value }); }}
            className="bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-xs rounded-lg px-2 py-1.5 focus:outline-none"
          >
            {RISK_OPTIONS.map((v) => (
              <option key={v} value={v}>{v}%</option>
            ))}
          </select>
        </SettingRow>
      </Card>

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Order Defaults</span>
        </div>
        <SettingRow label="Default order type">
          <div className="flex items-center gap-1 bg-[var(--bg-elevated-2)] rounded-lg p-0.5">
            {ORDER_TYPE_OPTIONS.map((ot) => (
              <button
                key={ot}
                onClick={() => { setOrderType(ot); persist({ defaultOrder: ot }); }}
                className={cn(
                  "px-2.5 py-1 rounded-md text-xs font-medium capitalize transition-colors",
                  orderType === ot
                    ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow"
                    : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                )}
              >
                {ot.replace("_", " ")}
              </button>
            ))}
          </div>
        </SettingRow>
        <SettingRow label="Order confirmation dialog" sublabel="Show confirm before submitting orders">
          <Toggle value={confirmOrders} onChange={(v) => { setConfirm(v); persist({ confirmOrders: v }); }} />
        </SettingRow>
        <SettingRow label="Show unrealized P&L" sublabel="Display open position gains/losses">
          <Toggle value={showPnL} onChange={(v) => { setShowPnL(v); persist({ showPnL: v }); }} />
        </SettingRow>
        <SettingRow label="Extended hours trading" sublabel="Pre-market & after-hours orders" last>
          <Toggle value={extended} onChange={(v) => { setExtended(v); persist({ extendedHours: v }); }} />
        </SettingRow>
      </Card>
    </div>
  );
}

// ── Notifications ─────────────────────────────────────────────────────────────

const QUICK_NOTIFS: { key: string; label: string; desc: string }[] = [
  { key: "signal_fired",   label: "Signal alerts",      desc: "When a configured alert fires" },
  { key: "entry",          label: "Strategy entries",   desc: "When a strategy opens a position" },
  { key: "exit",           label: "Strategy exits",     desc: "When a position closes" },
  { key: "price_target",   label: "Price targets",      desc: "When a watchlist target is hit" },
  { key: "news_event",     label: "Breaking news",      desc: "Market-moving news for holdings" },
  { key: "earnings",       label: "Earnings reminders", desc: "24h before earnings releases" },
];

function NotificationsSection() {
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

  // ── In-app toggles ────────────────────────────────────────────────────────
  const toggle = (eventKey: string) => {
    if (!data) return;
    const updated = JSON.parse(JSON.stringify(data.prefs ?? {}));
    const current = updated[eventKey]?.in_app ?? true;
    updated[eventKey] = { ...updated[eventKey], in_app: !current };
    mut.mutate(updated);
  };

  // ── Email digest ──────────────────────────────────────────────────────────
  const [emailEnabled, setEmailEnabled] = useState<boolean>(() => loadPrefs().emailDigestEnabled ?? false);

  const toggleEmail = () => {
    const next = !emailEnabled;
    setEmailEnabled(next);
    savePrefs({ emailDigestEnabled: next });
    if (data) {
      const updated = JSON.parse(JSON.stringify(data.prefs ?? {}));
      updated._email_digest = next;
      mut.mutate(updated);
    }
    toast.success(next ? "Daily email digest enabled" : "Email digest disabled");
  };

  // ── Push notifications ────────────────────────────────────────────────────
  const [pushEnabled, setPushEnabled] = useState<boolean>(() => {
    if (typeof Notification === "undefined") return false;
    return Notification.permission === "granted" && (loadPrefs().pushEnabled ?? false);
  });
  const [pushDenied, setPushDenied] = useState<boolean>(() =>
    typeof Notification !== "undefined" && Notification.permission === "denied"
  );

  const togglePush = async () => {
    if (pushEnabled) {
      savePrefs({ pushEnabled: false });
      setPushEnabled(false);
      toast.success("Push notifications disabled");
      return;
    }
    if (pushDenied) {
      toast.error("Notifications are blocked — enable them in your browser site settings");
      return;
    }
    if (typeof Notification === "undefined") {
      toast.error("Push notifications are not supported in this browser");
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      savePrefs({ pushEnabled: true });
      setPushEnabled(true);
      new Notification("BMG Capital", {
        body: "You'll now receive real-time alerts here.",
        icon: "/favicon.ico",
      });
      toast.success("Push notifications enabled!");
    } else if (permission === "denied") {
      setPushDenied(true);
      toast.error("Notifications blocked — check browser settings to allow them");
    }
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Notifications" subtitle="Choose what you hear about" />

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">In-App Notifications</span>
        </div>
        {isLoading ? (
          <div className="px-4 py-8 text-center text-[var(--text-tertiary)] text-sm animate-pulse">Loading…</div>
        ) : (
          QUICK_NOTIFS.map((n, i) => {
            const enabled = (data?.prefs as any)?.[n.key]?.in_app ?? true;
            return (
              <SettingRow key={n.key} label={n.label} sublabel={n.desc} last={i === QUICK_NOTIFS.length - 1}>
                <Toggle value={enabled} onChange={() => toggle(n.key)} />
              </SettingRow>
            );
          })
        )}
      </Card>

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Delivery Channels</span>
        </div>
        <SettingRow label="Email digests" sublabel="Daily summary of signals and activity sent to your email">
          <Toggle value={emailEnabled} onChange={toggleEmail} />
        </SettingRow>
        <SettingRow
          label="Push notifications"
          sublabel={pushDenied ? "Blocked in browser — click to learn how to enable" : "Browser notifications for real-time alerts"}
          last
        >
          {pushDenied ? (
            <button
              onClick={togglePush}
              className="text-xs text-[var(--accent-negative)] bg-[var(--accent-negative-bg)] border border-[var(--accent-negative)]/20 px-2.5 py-1 rounded-lg hover:brightness-110 transition-colors"
            >
              Blocked
            </button>
          ) : (
            <Toggle value={pushEnabled} onChange={togglePush} />
          )}
        </SettingRow>
      </Card>
    </div>
  );
}

// ── Privacy & Data ────────────────────────────────────────────────────────────

function PrivacySection() {
  const [clearing, setClearing] = useState(false);

  const clearCache = () => {
    setClearing(true);
    ["BMG_QUERY_CACHE_v4", "bmg_ui_prefs", "bmg_tour_state"].forEach((k) => {
      try { localStorage.removeItem(k); } catch {}
    });
    setTimeout(() => {
      setClearing(false);
      toast.success("Cache cleared — reloading…");
      setTimeout(() => window.location.reload(), 1000);
    }, 500);
  };

  const exportData = () => {
    const data = {
      exported_at: new Date().toISOString(),
      localStorage: Object.fromEntries(
        Object.keys(localStorage)
          .filter((k) => k.startsWith("bmg_"))
          .map((k) => [k, localStorage.getItem(k)])
      ),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `bmg-data-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Data exported");
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Privacy & Data" subtitle="Control your data and local cache" />

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Local Data</span>
        </div>
        <SettingRow label="Export my data" sublabel="Download a JSON copy of your local preferences">
          <button
            onClick={exportData}
            className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--bg-elevated-2)] hover:bg-[#334155] border border-[var(--border-emphasis)] px-3 py-1.5 rounded-lg transition-colors"
          >
            <Download size={12} />
            Export
          </button>
        </SettingRow>
        <SettingRow label="Clear app cache" sublabel="Clears cached queries and preferences. App will reload." last>
          <button
            onClick={clearCache}
            disabled={clearing}
            className="flex items-center gap-1.5 text-xs font-semibold text-[var(--accent-negative)] hover:text-[#EF4444] bg-[var(--accent-negative-bg)] hover:bg-[#EF4444]/20 border border-[var(--accent-negative)]/20 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={cn(clearing && "animate-spin")} />
            {clearing ? "Clearing…" : "Clear cache"}
          </button>
        </SettingRow>
      </Card>

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Privacy</span>
        </div>
        <SettingRow label="Analytics" sublabel="Help improve BMG by sending anonymous usage data">
          <span className="text-xs font-medium text-[var(--accent-positive)]">Enabled</span>
        </SettingRow>
        <SettingRow label="Data retention" sublabel="How long trade and journal history is kept" last>
          <span className="text-xs text-[var(--text-secondary)]">Indefinitely</span>
        </SettingRow>
      </Card>

      <div className="flex items-start gap-2.5 px-1">
        <Shield size={12} className="text-[var(--text-tertiary)] shrink-0 mt-0.5" />
        <p className="text-xs text-[var(--text-tertiary)]">
          Your data is encrypted in transit and at rest. BMG does not sell personal data.
          See our <span className="text-[var(--accent-positive)] cursor-pointer">privacy policy</span> for details.
        </p>
      </div>
    </div>
  );
}

// ── Security ──────────────────────────────────────────────────────────────────

function SecuritySection() {
  const [showPwForm, setShowPwForm] = useState(false);
  const [pwForm, setPwForm]         = useState({ current: "", next: "", confirm: "" });
  const [pwLoading, setPwLoading]   = useState(false);

  const handleChangePw = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pwForm.next !== pwForm.confirm) {
      toast.error("Passwords don't match");
      return;
    }
    if (pwForm.next.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    setPwLoading(true);
    // Placeholder — backend endpoint not yet wired
    await new Promise((r) => setTimeout(r, 800));
    setPwLoading(false);
    toast.success("Password change coming soon!");
    setShowPwForm(false);
  };

  const sessions = [
    { device: "MacBook Pro", location: "Chicago, IL", last: "Active now",  current: true },
    { device: "iPhone 15",   location: "Chicago, IL", last: "2 hours ago", current: false },
  ];

  return (
    <div className="space-y-4">
      <SectionHeader title="Security" subtitle="Manage your credentials and active sessions" />

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Password</span>
        </div>
        {!showPwForm ? (
          <SettingRow label="Password" sublabel="Last changed: unknown" last>
            <button
              onClick={() => setShowPwForm(true)}
              className="text-xs font-semibold text-[var(--accent-positive)] hover:text-[#60A5FA] transition-colors"
            >
              Change
            </button>
          </SettingRow>
        ) : (
          <form onSubmit={handleChangePw} className="px-4 py-4 space-y-3">
            {[
              { key: "current", placeholder: "Current password" },
              { key: "next",    placeholder: "New password (8+ chars)" },
              { key: "confirm", placeholder: "Confirm new password" },
            ].map(({ key, placeholder }) => (
              <input
                key={key}
                type="password"
                value={pwForm[key as keyof typeof pwForm]}
                onChange={(e) => setPwForm({ ...pwForm, [key]: e.target.value })}
                placeholder={placeholder}
                className="w-full bg-[#020617] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
              />
            ))}
            <div className="flex gap-2 pt-1">
              <button
                type="submit"
                disabled={pwLoading}
                className="bg-[var(--accent-positive)] hover:brightness-110 disabled:opacity-50 text-[var(--text-primary)] text-sm font-semibold px-4 py-2 rounded-lg"
              >
                {pwLoading ? "Saving…" : "Update password"}
              </button>
              <button
                type="button"
                onClick={() => setShowPwForm(false)}
                className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm px-3 py-2"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </Card>

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Two-Factor Authentication</span>
        </div>
        <SettingRow label="Authenticator app" sublabel="TOTP via Google Authenticator or Authy" last>
          <span className="text-xs font-medium text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] px-2.5 py-1 rounded-lg">Coming soon</span>
        </SettingRow>
      </Card>

      <Card>
        <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]/60">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Active Sessions</span>
        </div>
        {sessions.map((s, i) => (
          <div
            key={s.device}
            className={cn(
              "flex items-center justify-between px-4 py-3 gap-3",
              i < sessions.length - 1 && "border-b border-[var(--border-subtle)]/60"
            )}
          >
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-[var(--bg-elevated-2)] flex items-center justify-center">
                <Smartphone size={14} className="text-[var(--text-tertiary)]" />
              </div>
              <div>
                <div className="text-sm text-[var(--text-primary)] flex items-center gap-2">
                  {s.device}
                  {s.current && (
                    <span className="text-[10px] bg-[var(--accent-positive)]/10 text-[var(--accent-positive)] px-1.5 py-0.5 rounded font-semibold">
                      This device
                    </span>
                  )}
                </div>
                <div className="text-xs text-[var(--text-tertiary)] flex items-center gap-1.5 mt-0.5">
                  <Globe size={10} />
                  {s.location} · {s.last}
                </div>
              </div>
            </div>
            {!s.current && (
              <button className="text-xs text-[var(--accent-negative)] hover:text-[#EF4444] transition-colors">
                Revoke
              </button>
            )}
          </div>
        ))}
      </Card>
    </div>
  );
}

// ── Subscription ──────────────────────────────────────────────────────────────

function SubscriptionSection({ navigate }: { navigate: ReturnType<typeof useNavigate> }) {
  const [portalLoading, setPortalLoading] = useState(false);
  const { data: tierData } = useQuery({
    queryKey: ["tier-me"],
    queryFn: getMyTier,
    staleTime: 60_000,
  });
  useEffect(() => {
    if (tierData) useTierStore.getState().setTierData(tierData);
  }, [tierData]);

  const tier   = tierData?.tier ?? "free";
  const status = tierData?.status ?? "active";
  const meta   = TIER_META[tier];
  const TierIcon = meta.Icon;

  const statusLabel = status === "trialing"
    ? `Trial ends ${tierData?.trial_ends_at ? new Date(tierData.trial_ends_at).toLocaleDateString() : ""}`
    : status === "past_due" ? "Payment past due"
    : status === "cancelled" ? "Cancels at period end"
    : tier === "free" ? "No active subscription"
    : `Renews ${tierData?.current_period_end ? new Date(tierData.current_period_end).toLocaleDateString() : ""}`;

  const handleBilling = async () => {
    setPortalLoading(true);
    try {
      const { url } = await createPortal();
      window.location.href = url;
    } catch (e: any) {
      setPortalLoading(false);
      toast.error(e?.response?.data?.detail ?? "Could not open billing portal");
    }
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Subscription" subtitle="Manage your plan and billing" />

      <Card>
        <div className="p-4 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", meta.bg)}>
                <TierIcon size={18} className={meta.color} />
              </div>
              <div>
                <div className="text-[var(--text-primary)] font-semibold">{meta.label}</div>
                <div className={cn("text-xs", status === "past_due" ? "text-[var(--accent-negative)]" : "text-[var(--text-tertiary)]")}>
                  {statusLabel}
                </div>
              </div>
            </div>
            {tier !== "premium" && (
              <button
                onClick={() => navigate("/upgrade")}
                className="text-xs font-bold text-[var(--accent-positive)] hover:text-[#60A5FA] flex items-center gap-1 transition-colors"
              >
                Upgrade <ChevronRight size={12} />
              </button>
            )}
          </div>

          {status === "past_due" && (
            <div className="flex items-start gap-2 bg-[var(--accent-negative-bg)] border border-[var(--accent-negative)]/20 rounded-xl px-3 py-2.5">
              <AlertCircle size={14} className="text-[var(--accent-negative)] shrink-0 mt-0.5" />
              <p className="text-xs text-[var(--accent-negative)]">Payment failed. Update your payment method to restore access.</p>
            </div>
          )}

          {tierData?.cancel_at_period_end && (
            <div className="flex items-start gap-2 bg-[#F59E0B]/10 border border-[#F59E0B]/20 rounded-xl px-3 py-2.5">
              <AlertCircle size={14} className="text-[#F59E0B] shrink-0 mt-0.5" />
              <p className="text-xs text-[#F59E0B]">
                Subscription cancels {tierData.current_period_end ? `on ${new Date(tierData.current_period_end).toLocaleDateString()}` : "at end of period"}.
              </p>
            </div>
          )}

          {tierData?.aum_override && (
            <div className="flex items-start gap-2 bg-[var(--accent-positive-bg)] border border-[var(--accent-positive)]/20 rounded-xl px-3 py-2.5">
              <TrendingUp size={14} className="text-[var(--accent-positive)] shrink-0 mt-0.5" />
              <p className="text-xs text-[var(--accent-positive)]">{meta.label} included free based on your portfolio balance.</p>
            </div>
          )}

          {tierData?.has_stripe && (
            <button
              onClick={handleBilling}
              disabled={portalLoading}
              className="flex items-center gap-2 w-full bg-[var(--bg-elevated-2)] hover:bg-[#334155] border border-[var(--border-emphasis)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-sm font-medium rounded-xl px-4 py-2.5 transition-colors disabled:opacity-50"
            >
              <ExternalLink size={14} />
              {portalLoading ? "Opening portal…" : "Manage billing & invoices"}
            </button>
          )}
        </div>
      </Card>

      <div className="flex items-start gap-2.5 px-1">
        <CreditCard size={12} className="text-[var(--text-tertiary)] shrink-0 mt-0.5" />
        <p className="text-xs text-[var(--text-tertiary)]">
          $10k+ portfolio → Plus free. $50k+ portfolio → Premium free. Checked daily.
        </p>
      </div>
    </div>
  );
}

// ── Sign Out ──────────────────────────────────────────────────────────────────

function DangerSection({ navigate }: { navigate: ReturnType<typeof useNavigate> }) {
  const { logout } = useAuthStore();
  const [confirming, setConfirming] = useState(false);

  const handleSignOut = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Session" subtitle="Sign out or close your session" />

      <Card>
        <div className="p-4 space-y-3">
          {!confirming ? (
            <button
              onClick={() => setConfirming(true)}
              className="flex items-center gap-2.5 w-full bg-[var(--accent-negative-bg)] hover:bg-[#EF4444]/20 border border-[var(--accent-negative)]/20 hover:border-[#EF4444]/40 text-[var(--accent-negative)] text-sm font-semibold rounded-xl px-4 py-3 transition-colors"
            >
              <LogOut size={16} />
              Sign out
            </button>
          ) : (
            <div className="space-y-3">
              <div className="flex items-start gap-2 bg-[var(--accent-negative-bg)] border border-[var(--accent-negative)]/20 rounded-xl px-3 py-3">
                <AlertTriangle size={14} className="text-[var(--accent-negative)] shrink-0 mt-0.5" />
                <p className="text-sm text-[var(--accent-negative)]">Are you sure you want to sign out?</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleSignOut}
                  className="flex-1 bg-[var(--accent-negative)] hover:brightness-110 text-white text-sm font-bold py-2.5 rounded-xl transition-colors"
                >
                  Yes, sign out
                </button>
                <button
                  onClick={() => setConfirming(false)}
                  className="flex-1 bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-sm font-medium py-2.5 rounded-xl border border-[var(--border-emphasis)] transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  const navigate   = useNavigate();
  const [active, setActive] = useState<SectionId>("profile");

  const renderSection = () => {
    switch (active) {
      case "profile":       return <ProfileSection />;
      case "appearance":    return <AppearanceSection />;
      case "trading":       return <TradingSection />;
      case "notifications": return <NotificationsSection />;
      case "privacy":       return <PrivacySection />;
      case "security":      return <SecuritySection />;
      case "subscription":  return <SubscriptionSection navigate={navigate} />;
      case "danger":        return <DangerSection navigate={navigate} />;
    }
  };

  return (
    <div className="max-w-5xl mx-auto pb-20 md:pb-8">
      <h1 className="text-xl font-bold text-[var(--text-primary)] mb-5">Settings</h1>

      <div className="flex gap-6 items-start">
        {/* Sidebar nav */}
        <nav className="hidden md:flex flex-col w-48 shrink-0 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden sticky top-4">
          {SECTIONS.map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => setActive(id)}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2.5 text-sm font-medium text-left transition-colors",
                id === active
                  ? "bg-[var(--accent-positive)]/10 text-[var(--accent-positive)]"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)]",
                id === "danger" && id !== active && "text-[var(--accent-negative)]/70 hover:text-[var(--accent-negative)]"
              )}
            >
              <Icon size={15} className="shrink-0" />
              {label}
            </button>
          ))}
        </nav>

        {/* Mobile horizontal tab strip */}
        <div className="md:hidden w-full mb-4">
          <div className="flex overflow-x-auto gap-1 pb-1 scrollbar-none" style={{ scrollbarWidth: "none" }}>
            {SECTIONS.map(({ id, label, Icon }) => (
              <button
                key={id}
                onClick={() => setActive(id)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap shrink-0 transition-colors",
                  id === active
                    ? "bg-[var(--accent-positive)] text-[var(--text-primary)]"
                    : "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-tertiary)]"
                )}
              >
                <Icon size={12} />
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {renderSection()}
        </div>
      </div>
    </div>
  );
}
