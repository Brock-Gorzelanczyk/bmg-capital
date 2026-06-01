import { useRef, useState, useCallback, useEffect } from "react";
import { DockviewReact, type DockviewReadyEvent, type DockviewApi } from "dockview";
import "dockview/dist/styles/dockview.css";
import { Lock, Unlock, Plus, MoreHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/store/workspaceStore";
import type { LabId } from "@/types/workspace";
import { WIDGET_REGISTRY, WIDGET_CATALOG } from "./widgetRegistry";
import { DEFAULT_LAYOUT, ANALYSIS_LAYOUT } from "./defaultLayouts";

interface LabShellProps {
  labId: LabId;
}

function getDefaultLayout(workspaceName: string) {
  if (workspaceName === "Analysis") return ANALYSIS_LAYOUT;
  return DEFAULT_LAYOUT;
}

// Context menu state
interface ContextMenu {
  x: number;
  y: number;
  workspaceId: string;
}

export default function LabShell({ labId }: LabShellProps) {
  const store = useWorkspaceStore();
  const workspaces = store.getWorkspaces(labId);
  const activeId = store.getActiveId(labId);
  const [locked, setLocked] = useState(false);
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [addWidgetOpen, setAddWidgetOpen] = useState(false);
  const dockviewApiRef = useRef<DockviewApi | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Ensure workspace init
  useEffect(() => {
    if (workspaces.length === 0) return;
    if (!store.getActiveId(labId)) {
      store.setActiveWorkspace(labId, workspaces[0].id);
    }
  }, []);

  const activeWorkspace = workspaces.find((w) => w.id === activeId) ?? workspaces[0];

  const handleDockviewReady = useCallback(
    (event: DockviewReadyEvent) => {
      dockviewApiRef.current = event.api;

      // Restore saved layout or load default
      const layout = activeWorkspace?.layout;
      if (layout && (layout as unknown as { grid: unknown }).grid) {
        try {
          event.api.fromJSON(layout as unknown as Parameters<DockviewApi["fromJSON"]>[0]);
          return;
        } catch {
          // Fall through to default
        }
      }

      // Load a sensible default
      const defaultLayout = getDefaultLayout(activeWorkspace?.name ?? "");
      try {
        event.api.fromJSON(defaultLayout as Parameters<DockviewApi["fromJSON"]>[0]);
      } catch {
        // Manual panel add as fallback
        event.api.addPanel({ id: "position-blotter", component: "position-blotter", title: "Position Blotter" });
        event.api.addPanel({ id: "equity-curve", component: "equity-curve", title: "Equity Curve" });
      }
    },
    [activeWorkspace]
  );

  function handleTabClick(id: string) {
    if (id === activeId) return;
    // Save current layout before switching
    if (dockviewApiRef.current && activeId) {
      try {
        const json = dockviewApiRef.current.toJSON();
        store.saveLayout(labId, activeId, json as unknown as import("@/types/workspace").WorkspaceLayout);
      } catch {}
    }
    store.setActiveWorkspace(labId, id);
  }

  function handleAdd() {
    if (workspaces.length >= 9) return;
    store.addWorkspace(labId);
  }

  function handleContextMenu(e: React.MouseEvent, id: string) {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, workspaceId: id });
  }

  function closeContextMenu() {
    setContextMenu(null);
  }

  function startRename(id: string) {
    const ws = workspaces.find((w) => w.id === id);
    setRenameDraft(ws?.name ?? "");
    setRenameId(id);
    closeContextMenu();
  }

  function commitRename() {
    if (renameId && renameDraft.trim()) {
      store.renameWorkspace(labId, renameId, renameDraft.trim());
    }
    setRenameId(null);
  }

  function handleDuplicate(id: string) {
    store.duplicateWorkspace(labId, id);
    closeContextMenu();
  }

  function handleDelete(id: string) {
    store.deleteWorkspace(labId, id);
    closeContextMenu();
  }

  function addWidget(componentId: string) {
    const api = dockviewApiRef.current;
    if (!api) return;
    const catalog = WIDGET_CATALOG.find((w) => w.id === componentId);
    if (!catalog) return;
    const uniqueId = `${componentId}-${Date.now()}`;
    api.addPanel({
      id: uniqueId,
      component: componentId,
      title: catalog.title,
    });
    setAddWidgetOpen(false);
  }

  return (
    <div className="flex flex-col h-full" ref={containerRef}>
      {/* Main dockview area */}
      <div className="flex-1 min-h-0 relative dv-bmg-theme">
        <DockviewReact
          key={activeId} // re-mount on workspace switch
          className="dockview-theme-bmg"
          components={WIDGET_REGISTRY}
          onReady={handleDockviewReady}
          disableDnd={locked}
        />
      </div>

      {/* Workspace tab bar */}
      <div className="shrink-0 flex items-center bg-[var(--bg-base)] border-t border-[var(--border-subtle)] px-2 gap-1 h-9 overflow-x-auto">
        {workspaces.map((ws) => {
          const isActive = ws.id === activeId;
          return (
            <div
              key={ws.id}
              className="relative shrink-0"
              onContextMenu={(e) => handleContextMenu(e, ws.id)}
            >
              {renameId === ws.id ? (
                <input
                  autoFocus
                  value={renameDraft}
                  onChange={(e) => setRenameDraft(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRename();
                    if (e.key === "Escape") setRenameId(null);
                  }}
                  className="text-xs px-2 py-1 rounded bg-[var(--bg-elevated-2)] text-[var(--text-primary)] border border-[#BEF264]/50 outline-none w-28"
                />
              ) : (
                <button
                  onClick={() => handleTabClick(ws.id)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1 rounded-t text-xs font-medium transition-colors relative",
                    isActive
                      ? "text-[var(--text-primary)] bg-[var(--bg-elevated)]"
                      : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]/50"
                  )}
                >
                  <span>{ws.icon}</span>
                  <span>{ws.name}</span>
                  {/* Active underline */}
                  {isActive && (
                    <span className="absolute bottom-0 left-2 right-2 h-[2px] rounded-full bg-[#BEF264]" />
                  )}
                </button>
              )}
            </div>
          );
        })}

        {/* Add workspace */}
        {workspaces.length < 9 && (
          <button
            onClick={handleAdd}
            className="shrink-0 flex items-center justify-center w-6 h-6 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-colors"
            title="Add workspace"
          >
            <Plus size={12} />
          </button>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Add widget */}
        <button
          onClick={() => setAddWidgetOpen((v) => !v)}
          className="shrink-0 flex items-center gap-1 px-2 py-1 text-[10px] rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-colors"
          title="Add widget"
        >
          <MoreHorizontal size={12} />
          <span className="hidden sm:inline">Widgets</span>
        </button>

        {/* Lock toggle */}
        <button
          onClick={() => setLocked((v) => !v)}
          className={cn(
            "shrink-0 flex items-center justify-center w-6 h-6 rounded transition-colors",
            locked
              ? "text-[#BEF264] hover:bg-[#BEF264]/10"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]"
          )}
          title={locked ? "Unlock layout" : "Lock layout"}
        >
          {locked ? <Lock size={12} /> : <Unlock size={12} />}
        </button>
      </div>

      {/* Add widget panel (slide up from tab bar) */}
      {addWidgetOpen && (
        <div className="absolute bottom-9 right-2 z-50 bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl shadow-2xl p-3 w-72">
          <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-2">
            Add Widget
          </div>
          <div className="space-y-1">
            {WIDGET_CATALOG.map((w) => (
              <button
                key={w.id}
                onClick={() => addWidget(w.id)}
                className="w-full flex items-center gap-3 px-2 py-2 rounded-lg text-left hover:bg-[var(--bg-elevated-2)] transition-colors group"
              >
                <span className="text-lg shrink-0">{w.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-[var(--text-primary)]">{w.title}</div>
                  <div className="text-[10px] text-[var(--text-tertiary)] truncate">{w.description}</div>
                </div>
                <span className="text-[10px] text-[var(--text-tertiary)] shrink-0">{w.category}</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => setAddWidgetOpen(false)}
            className="mt-2 w-full text-[10px] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] text-center"
          >
            Close
          </button>
        </div>
      )}

      {/* Right-click context menu */}
      {contextMenu && (
        <>
          <div className="fixed inset-0 z-40" onClick={closeContextMenu} />
          <div
            className="fixed z-50 bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl shadow-2xl py-1 min-w-36"
            style={{ left: contextMenu.x, top: contextMenu.y - 100 }}
          >
            <button
              onClick={() => startRename(contextMenu.workspaceId)}
              className="w-full px-4 py-2 text-left text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-elevated-2)] hover:text-[var(--text-primary)] transition-colors"
            >
              Rename
            </button>
            <button
              onClick={() => handleDuplicate(contextMenu.workspaceId)}
              className="w-full px-4 py-2 text-left text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-elevated-2)] hover:text-[var(--text-primary)] transition-colors"
            >
              Duplicate
            </button>
            {workspaces.length > 1 && (
              <button
                onClick={() => handleDelete(contextMenu.workspaceId)}
                className="w-full px-4 py-2 text-left text-xs text-red-400 hover:bg-red-500/10 transition-colors"
              >
                Delete
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
