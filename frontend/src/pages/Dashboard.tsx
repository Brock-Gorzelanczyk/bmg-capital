import { useEffect, useRef, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, LayoutGrid, Bot } from "lucide-react";
import { getStreak } from "@/api/portfolio";
import { StreakBadgeDashboard } from "@/components/portfolio/MilestonesPanel";
import { Responsive, useContainerWidth, verticalCompactor, type LayoutItem, type Layout, type ResponsiveLayouts } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

import { getWorkspaces, createWorkspace, updateWorkspace } from "@/api/workspace";
import { useWidgetStore } from "@/store/widgetStore";
import { WIDGET_REGISTRY } from "@/lib/widgetRegistry";
import WidgetFrame from "@/components/widgets/WidgetFrame";
import WorkspaceSwitcher from "@/components/widgets/WorkspaceSwitcher";
import WidgetLibraryModal from "@/components/widgets/WidgetLibraryModal";
import AskAIDrawer from "@/components/ui/AskAIDrawer";

import MorningBriefWidget from "@/components/widgets/impl/MorningBriefWidget";
import MarketIndicesWidget from "@/components/widgets/impl/MarketIndicesWidget";
import PaperAccountWidget from "@/components/widgets/impl/PaperAccountWidget";
import PortfolioWidget from "@/components/widgets/impl/PortfolioWidget";
import StrategySignalsWidget from "@/components/widgets/impl/StrategySignalsWidget";
import DailyRecapWidget from "@/components/widgets/impl/DailyRecapWidget";
import SectorPerformanceWidget from "@/components/widgets/impl/SectorPerformanceWidget";
import MarketNewsWidget from "@/components/widgets/impl/MarketNewsWidget";
import WatchlistTableWidget from "@/components/widgets/impl/WatchlistTableWidget";
import TopMoversWidget from "@/components/widgets/impl/TopMoversWidget";
import DrawdownBudgetWidget from "@/components/widgets/impl/DrawdownBudgetWidget";
import { useState } from "react";

const WIDGET_COMPONENTS: Record<string, React.ComponentType> = {
  "morning-brief": MorningBriefWidget,
  "market-indices": MarketIndicesWidget,
  "paper-account": PaperAccountWidget,
  "portfolio-summary": PortfolioWidget,
  "strategy-signals": StrategySignalsWidget,
  "daily-recap": DailyRecapWidget,
  "sector-performance": SectorPerformanceWidget,
  "market-news": MarketNewsWidget,
  "watchlist-table": WatchlistTableWidget,
  "top-movers": TopMoversWidget,
  "drawdown-budget": DrawdownBudgetWidget,
};

function ComingSoonWidget({ name }: { name: string }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-2 text-center">
      <LayoutGrid size={28} className="text-[var(--border-emphasis)]" />
      <p className="text-sm font-medium text-[var(--text-tertiary)]">{name}</p>
      <p className="text-xs text-[var(--text-tertiary)] opacity-60">Coming soon</p>
    </div>
  );
}

export default function Dashboard() {
  const qc = useQueryClient();
  const {
    workspaces, activeWorkspaceId, editMode,
    setEditMode, setActiveWorkspace, updateLayout,
    addWidget, removeWidget, syncFromBackend, resetToDefaults,
  } = useWidgetStore();

  const [libraryOpen, setLibraryOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { containerRef, width, mounted } = useContainerWidth();

  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId) ?? workspaces[0];

  // Load workspaces from backend on mount
  const { data: backendWorkspaces } = useQuery({
    queryKey: ["workspaces"],
    queryFn: getWorkspaces,
    staleTime: 300_000,
    retry: 1,
  });

  useEffect(() => {
    if (backendWorkspaces && backendWorkspaces.length > 0) {
      syncFromBackend(backendWorkspaces);
    }
  }, [backendWorkspaces]);

  // Debounced backend save
  const saveToBackend = useCallback(async () => {
    if (!activeWorkspace) return;
    const payload = {
      name: activeWorkspace.name,
      icon: activeWorkspace.icon,
      layout_json: JSON.stringify(activeWorkspace.layout),
      widgets_json: JSON.stringify(activeWorkspace.widgets),
      is_default: activeWorkspace.isDefault,
      sort_order: workspaces.indexOf(activeWorkspace),
    };

    try {
      if (activeWorkspace.backendId) {
        await updateWorkspace(activeWorkspace.backendId, payload);
      } else {
        const created = await createWorkspace(payload);
        // Update store with backend ID
        useWidgetStore.setState((s) => ({
          workspaces: s.workspaces.map((w) =>
            w.id === activeWorkspace.id ? { ...w, backendId: created.id } : w
          ),
        }));
      }
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    } catch {
      // silently fail — localStorage still has it
    }
  }, [activeWorkspace, workspaces, qc]);

  // Trigger debounced save when layout changes
  useEffect(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(saveToBackend, 1500);
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
  }, [activeWorkspace?.layout, activeWorkspace?.widgets, saveToBackend]);

  function handleLayoutChange(layout: Layout, _layouts: ResponsiveLayouts) {
    if (!activeWorkspace) return;
    updateLayout(activeWorkspace.id, layout as LayoutItem[]);
  }

  function handleAddWidget(widgetId: string) {
    if (!activeWorkspace) return;
    addWidget(activeWorkspace.id, widgetId);
    setLibraryOpen(false);
  }

  function handleRemoveWidget(instanceId: string) {
    if (!activeWorkspace) return;
    removeWidget(activeWorkspace.id, instanceId);
  }

  if (!activeWorkspace) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--text-tertiary)]">
        <div className="text-center space-y-3">
          <p>No workspace configured.</p>
          <button onClick={resetToDefaults} className="px-4 py-2 rounded-lg bg-[var(--accent-positive)] text-[#0a0a0a] text-sm font-semibold cursor-pointer">
            Reset to defaults
          </button>
        </div>
      </div>
    );
  }

  const layouts = { lg: activeWorkspace.layout, md: activeWorkspace.layout };

  // Streak badge data
  const { data: streakData } = useQuery({
    queryKey: ["portfolio-streak"],
    queryFn: getStreak,
    staleTime: 120_000,
  });

  return (
    <div className="max-w-[1600px] mx-auto pb-20 md:pb-6">
      {/* Dashboard header */}
      <div className="flex items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight font-display">Dashboard</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">
            {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {streakData && <StreakBadgeDashboard streak={streakData.current_streak_weeks} />}
          <button onClick={() => setAiOpen(true)} className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
            <Bot size={12} /> Ask AI
          </button>
          {editMode && (
            <button
              onClick={() => setLibraryOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-all cursor-pointer"
            >
              <Plus size={14} /> Add Widget
            </button>
          )}
        </div>
      </div>

      {/* Workspace switcher */}
      <div className="mb-5">
        <WorkspaceSwitcher editMode={editMode} onToggleEdit={() => setEditMode(!editMode)} />
      </div>

      {/* Edit mode hint */}
      {editMode && (
        <div className="mb-4 px-4 py-2.5 bg-[var(--accent-positive)]/8 border border-[var(--accent-positive)]/20 rounded-xl text-xs text-[var(--accent-positive)] flex items-center gap-2">
          <LayoutGrid size={13} />
          Drag widgets by the handle bar · Resize from corners · Click × to remove
        </div>
      )}

      {/* Grid */}
      {activeWorkspace.widgets.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
          <LayoutGrid size={40} className="text-[var(--border-emphasis)]" />
          <div>
            <p className="text-[var(--text-secondary)] font-medium">This workspace is empty</p>
            <p className="text-[var(--text-tertiary)] text-sm mt-1">Click "Edit Layout" then "+ Add Widget" to get started</p>
          </div>
          <button
            onClick={() => { setEditMode(true); setLibraryOpen(true); }}
            className="px-4 py-2 rounded-xl bg-[var(--accent-positive)] text-[#0a0a0a] text-sm font-semibold cursor-pointer"
          >
            Add Widgets
          </button>
        </div>
      ) : (
        <div ref={containerRef}>
          {mounted && (
            <Responsive
              width={width}
              className="layout"
              layouts={layouts}
              breakpoints={{ lg: 1200, md: 768, sm: 480, xs: 0 }}
              cols={{ lg: 12, md: 8, sm: 4, xs: 2 }}
              rowHeight={80}
              dragConfig={{ enabled: editMode, handle: ".widget-drag-handle", bounded: false, threshold: 3 }}
              resizeConfig={{ enabled: editMode, handles: ["se"] as const }}
              onLayoutChange={handleLayoutChange}
              margin={[16, 16] as const}
              containerPadding={[0, 0] as const}
              compactor={verticalCompactor}
            >
              {activeWorkspace.widgets.map((inst) => {
                const def = WIDGET_REGISTRY[inst.widgetId];
                const WidgetComp = WIDGET_COMPONENTS[inst.widgetId];
                const title = def?.name ?? inst.widgetId;

                return (
                  <div key={inst.id}>
                    <WidgetFrame
                      title={title}
                      instanceId={inst.id}
                      editMode={editMode}
                      onRemove={() => handleRemoveWidget(inst.id)}
                      className="h-full"
                    >
                      {WidgetComp ? (
                        <WidgetComp />
                      ) : (
                        <ComingSoonWidget name={title} />
                      )}
                    </WidgetFrame>
                  </div>
                );
              })}
            </Responsive>
          )}
        </div>
      )}

      {/* Widget library modal */}
      {libraryOpen && (
        <WidgetLibraryModal
          workspaceId={activeWorkspace.id}
          existingWidgetIds={activeWorkspace.widgets.map((w) => w.widgetId)}
          onAdd={handleAddWidget}
          onClose={() => setLibraryOpen(false)}
        />
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        context="BMG Capital Dashboard — overview of portfolio, market indices, and daily brief"
        suggestions={[
          "What's moving the market today?",
          "How do I interpret the morning brief?",
          "What should I add to my watchlist right now?",
          "Explain today's market sentiment",
          "What are the key levels to watch this week?",
        ]}
      />
    </div>
  );
}

