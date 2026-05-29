import { useState } from "react";
import { Plus, Pencil, Trash2, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWidgetStore, type Workspace } from "@/store/widgetStore";

const WORKSPACE_TEMPLATES = [
  { label: "Overview", icon: "📊", widgets: ["morning-brief","market-indices","portfolio-summary","strategy-signals","sector-performance","market-news"] },
  { label: "Trader", icon: "⚡", widgets: ["morning-brief","market-indices","strategy-signals","sector-performance","market-news"] },
  { label: "Learning", icon: "🎓", widgets: ["morning-brief","paper-account","portfolio-summary","market-news"] },
  { label: "Markets", icon: "📈", widgets: ["market-indices","sector-performance","daily-recap","market-news"] },
  { label: "Blank", icon: "🗒️", widgets: [] },
];

const ICONS = ["📊", "⚡", "🎓", "📈", "🗒️", "💼", "🔭", "🧪", "💡", "🏆"];

interface Props {
  editMode: boolean;
  onToggleEdit: () => void;
}

export default function WorkspaceSwitcher({ editMode, onToggleEdit }: Props) {
  const { workspaces, activeWorkspaceId, setActiveWorkspace, addWorkspace, removeWorkspace, renameWorkspace } = useWidgetStore();
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [newTemplate, setNewTemplate] = useState(0);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");

  function handleCreate() {
    if (!newName.trim()) return;
    const tpl = WORKSPACE_TEMPLATES[newTemplate];
    addWorkspace(newName.trim(), tpl.icon, tpl.widgets);
    setShowNew(false);
    setNewName("");
    setNewTemplate(0);
  }

  function startRename(ws: Workspace) {
    setRenamingId(ws.id);
    setRenameVal(ws.name);
  }

  function commitRename() {
    if (renamingId && renameVal.trim()) {
      renameWorkspace(renamingId, renameVal.trim());
    }
    setRenamingId(null);
  }

  return (
    <div className="space-y-3">
      {/* Tab row */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-1 flex-wrap">
          {workspaces.map((ws) => (
            <div key={ws.id} className="flex items-center gap-0.5 group">
              {renamingId === ws.id ? (
                <div className="flex items-center gap-1 px-2">
                  <input
                    autoFocus
                    value={renameVal}
                    onChange={(e) => setRenameVal(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setRenamingId(null); }}
                    className="bg-transparent border-b border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm outline-none w-24 py-0.5"
                  />
                  <button onClick={commitRename} className="text-[var(--accent-positive)] hover:opacity-80 cursor-pointer"><Check size={12} /></button>
                  <button onClick={() => setRenamingId(null)} className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] cursor-pointer"><X size={12} /></button>
                </div>
              ) : (
                <>
                  <button
                    onClick={() => setActiveWorkspace(ws.id)}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all",
                      ws.id === activeWorkspaceId
                        ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)] shadow-sm"
                        : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                    )}
                  >
                    <span>{ws.icon}</span>
                    <span>{ws.name}</span>
                  </button>
                  {editMode && ws.id === activeWorkspaceId && (
                    <div className="flex items-center gap-0.5 ml-0.5">
                      <button onClick={() => startRename(ws)} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] p-0.5 rounded cursor-pointer transition-colors"><Pencil size={11} /></button>
                      {workspaces.length > 1 && (
                        <button onClick={() => removeWorkspace(ws.id)} className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] p-0.5 rounded cursor-pointer transition-colors"><Trash2 size={11} /></button>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}

          {/* New workspace button */}
          <button
            onClick={() => setShowNew((v) => !v)}
            className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
          >
            <Plus size={14} />
          </button>
        </div>

        {/* Edit mode toggle */}
        <button
          onClick={onToggleEdit}
          className={cn(
            "px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all cursor-pointer",
            editMode
              ? "bg-[var(--accent-positive)] text-[#0a0a0a] border-transparent"
              : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)]"
          )}
        >
          {editMode ? "✓ Done" : "Edit Layout"}
        </button>
      </div>

      {/* New workspace form */}
      {showNew && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3 max-w-sm">
          <div className="text-xs font-semibold text-[var(--text-primary)] uppercase tracking-wider">New Workspace</div>
          <input
            autoFocus
            placeholder="Workspace name…"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); if (e.key === "Escape") setShowNew(false); }}
            className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--border-emphasis)] placeholder:text-[var(--text-tertiary)]"
          />
          <div>
            <div className="text-[10px] text-[var(--text-tertiary)] mb-1.5 uppercase tracking-wider">Start from template</div>
            <div className="flex flex-wrap gap-1.5">
              {WORKSPACE_TEMPLATES.map((t, i) => (
                <button
                  key={t.label}
                  onClick={() => setNewTemplate(i)}
                  className={cn(
                    "flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border transition-all cursor-pointer",
                    newTemplate === i
                      ? "bg-[var(--accent-positive)]/10 border-[var(--accent-positive)] text-[var(--accent-positive)]"
                      : "bg-[var(--bg-elevated-2)] border-[var(--border-subtle)] text-[var(--text-secondary)]"
                  )}
                >
                  {t.icon} {t.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={handleCreate} disabled={!newName.trim()} className="flex-1 py-1.5 rounded-lg text-xs font-semibold bg-[var(--accent-positive)] text-[#0a0a0a] disabled:opacity-40 cursor-pointer">Create</button>
            <button onClick={() => setShowNew(false)} className="px-3 py-1.5 rounded-lg text-xs text-[var(--text-tertiary)] border border-[var(--border-subtle)] cursor-pointer hover:text-[var(--text-primary)]">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
