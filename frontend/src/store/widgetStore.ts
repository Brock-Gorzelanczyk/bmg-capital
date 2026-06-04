import { create } from "zustand";
import { persist } from "zustand/middleware";
import { WIDGET_REGISTRY, type WidgetLayout } from "@/lib/widgetRegistry";

export interface WidgetInstance {
  id: string;
  widgetId: string;
  config: Record<string, unknown>;
}

export interface Workspace {
  id: string;
  backendId?: number;
  name: string;
  icon: string;
  layout: (WidgetLayout & { i: string })[];
  widgets: WidgetInstance[];
  isDefault: boolean;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

function makeDefaultWidgets(ids: string[]): { widgets: WidgetInstance[]; layout: (WidgetLayout & { i: string })[] } {
  const widgets: WidgetInstance[] = [];
  const layout: (WidgetLayout & { i: string })[] = [];
  for (const widgetId of ids) {
    const def = WIDGET_REGISTRY[widgetId];
    if (!def) continue;
    const inst: WidgetInstance = { id: uid(), widgetId, config: {} };
    widgets.push(inst);
    layout.push({ i: inst.id, ...def.defaultLayout });
  }
  return { widgets, layout };
}

const OVERVIEW_WIDGETS = [
  "morning-brief",
  "market-indices",
  "paper-account",
  "portfolio-summary",
  "strategy-signals",
  "daily-recap",
  "sector-performance",
  "market-news",
];

const TRADER_WIDGETS = [
  "morning-brief",
  "market-indices",
  "strategy-signals",
  "sector-performance",
  "market-news",
];

const LEARNING_WIDGETS = [
  "morning-brief",
  "paper-account",
  "portfolio-summary",
  "market-news",
];

function buildDefaultWorkspaces(): Workspace[] {
  const overview = makeDefaultWidgets(OVERVIEW_WIDGETS);
  const trader = makeDefaultWidgets(TRADER_WIDGETS);
  const learning = makeDefaultWidgets(LEARNING_WIDGETS);
  return [
    { id: uid(), name: "Overview", icon: "📊", ...overview, isDefault: true },
    { id: uid(), name: "Trader", icon: "⚡", ...trader, isDefault: false },
    { id: uid(), name: "Learning", icon: "🎓", ...learning, isDefault: false },
  ];
}

interface WidgetStore {
  workspaces: Workspace[];
  activeWorkspaceId: string;
  editMode: boolean;

  setEditMode: (on: boolean) => void;
  setActiveWorkspace: (id: string) => void;
  updateLayout: (workspaceId: string, layout: (WidgetLayout & { i: string })[]) => void;
  addWidget: (workspaceId: string, widgetId: string) => WidgetInstance;
  removeWidget: (workspaceId: string, instanceId: string) => void;
  addWorkspace: (name: string, icon: string, template?: string[]) => Workspace;
  removeWorkspace: (id: string) => void;
  renameWorkspace: (id: string, name: string, icon?: string) => void;
  syncFromBackend: (backendWorkspaces: { id: number; name: string; icon: string; layout_json: string; widgets_json: string; is_default: boolean }[]) => void;
  resetToDefaults: () => void;
}

export const useWidgetStore = create<WidgetStore>()(
  persist(
    (set, get) => {
      const defaults = buildDefaultWorkspaces();
      return {
        workspaces: defaults,
        activeWorkspaceId: defaults[0].id,
        editMode: false,

        setEditMode: (on) => set({ editMode: on }),

        setActiveWorkspace: (id) => set({ activeWorkspaceId: id }),

        updateLayout: (workspaceId, layout) =>
          set((s) => ({
            workspaces: s.workspaces.map((w) =>
              w.id === workspaceId ? { ...w, layout } : w
            ),
          })),

        addWidget: (workspaceId, widgetId) => {
          const def = WIDGET_REGISTRY[widgetId];
          if (!def) throw new Error(`Unknown widget: ${widgetId}`);
          const inst: WidgetInstance = { id: uid(), widgetId, config: {} };
          const ws = get().workspaces.find((w) => w.id === workspaceId);
          const wsLayout = ws?.layout ?? [];
          const maxY = wsLayout.length > 0 ? Math.max(0, ...wsLayout.map((l) => l.y + l.h)) : 0;
          const layoutItem = { i: inst.id, ...def.defaultLayout, y: maxY };
          set((s) => ({
            workspaces: s.workspaces.map((w) =>
              w.id === workspaceId
                ? { ...w, widgets: [...(w.widgets ?? []), inst], layout: [...(w.layout ?? []), layoutItem] }
                : w
            ),
          }));
          return inst;
        },

        removeWidget: (workspaceId, instanceId) =>
          set((s) => ({
            workspaces: s.workspaces.map((w) =>
              w.id === workspaceId
                ? {
                    ...w,
                    widgets: (w.widgets ?? []).filter((wi) => wi.id !== instanceId),
                    layout: (w.layout ?? []).filter((l) => l.i !== instanceId),
                  }
                : w
            ),
          })),

        addWorkspace: (name, icon, template) => {
          const { widgets, layout } = template ? makeDefaultWidgets(template) : { widgets: [], layout: [] };
          const ws: Workspace = { id: uid(), name, icon, widgets, layout, isDefault: false };
          set((s) => ({ workspaces: [...s.workspaces, ws], activeWorkspaceId: ws.id }));
          return ws;
        },

        removeWorkspace: (id) =>
          set((s) => {
            const remaining = s.workspaces.filter((w) => w.id !== id);
            const next = remaining[0]?.id ?? "";
            return { workspaces: remaining, activeWorkspaceId: next };
          }),

        renameWorkspace: (id, name, icon) =>
          set((s) => ({
            workspaces: s.workspaces.map((w) =>
              w.id === id ? { ...w, name, icon: icon ?? w.icon } : w
            ),
          })),

        syncFromBackend: (bws) => {
          if (!bws.length) return;
          set((s) => {
            const defaults = buildDefaultWorkspaces();
            const mapped: Workspace[] = bws.map((b, idx) => {
              const widgets: WidgetInstance[] = (() => {
                try { const p = JSON.parse(b.widgets_json); return Array.isArray(p) ? p : []; }
                catch { return []; }
              })();
              const layout = (() => {
                try { const p = JSON.parse(b.layout_json); return Array.isArray(p) ? p : []; }
                catch { return []; }
              })();
              // When a backend workspace has no widgets (e.g., was saved before widgets loaded),
              // fall back to the default workspace at the same index so the dashboard isn't blank.
              const fallback = defaults[idx] ?? defaults[0];
              return {
                id: b.id.toString(),
                backendId: b.id,
                name: b.name,
                icon: b.icon,
                layout: layout.length > 0 ? layout : fallback.layout,
                widgets: widgets.length > 0 ? widgets : fallback.widgets,
                isDefault: b.is_default,
              };
            });
            const activeId = mapped.find((w) => w.isDefault)?.id ?? mapped[0]?.id ?? s.activeWorkspaceId;
            return { workspaces: mapped, activeWorkspaceId: activeId };
          });
        },

        resetToDefaults: () => {
          const defaults = buildDefaultWorkspaces();
          set({ workspaces: defaults, activeWorkspaceId: defaults[0].id });
        },
      };
    },
    {
      name: "bmg-widget-store",
      version: 3,
      // v3: guard workspaces array against undefined during Zustand rehydration
      migrate: (_state, _version) => {
        const defaults = buildDefaultWorkspaces();
        return { workspaces: defaults, activeWorkspaceId: defaults[0].id, editMode: false };
      },
    }
  )
);
