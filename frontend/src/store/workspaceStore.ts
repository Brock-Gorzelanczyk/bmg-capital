import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { LabId, WorkspaceLayout } from "@/types/workspace";

export interface LabWorkspace {
  id: string;
  name: string;
  icon: string;
  layout: WorkspaceLayout | null;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

function makeDefaultWorkspaces(): LabWorkspace[] {
  return [
    { id: uid(), name: "Default", icon: "⚡", layout: null },
    { id: uid(), name: "Analysis", icon: "📊", layout: null },
  ];
}

type PerLabWorkspaces = Partial<Record<LabId, LabWorkspace[]>>;
type PerLabActive = Partial<Record<LabId, string>>;

interface WorkspaceStore {
  // Per-lab state
  labWorkspaces: PerLabWorkspaces;
  labActiveId: PerLabActive;

  // Actions
  getWorkspaces: (labId: LabId) => LabWorkspace[];
  getActiveId: (labId: LabId) => string;
  setActiveWorkspace: (labId: LabId, id: string) => void;
  addWorkspace: (labId: LabId, name?: string) => void;
  renameWorkspace: (labId: LabId, id: string, name: string) => void;
  duplicateWorkspace: (labId: LabId, id: string) => void;
  deleteWorkspace: (labId: LabId, id: string) => void;
  saveLayout: (labId: LabId, id: string, layout: WorkspaceLayout) => void;
}

export const useWorkspaceStore = create<WorkspaceStore>()(
  persist(
    (set, get) => {
      function ensureDefaults(labId: LabId, state: { labWorkspaces: PerLabWorkspaces; labActiveId: PerLabActive }) {
        if (!state.labWorkspaces[labId]) {
          const defaults = makeDefaultWorkspaces();
          return {
            labWorkspaces: { ...state.labWorkspaces, [labId]: defaults },
            labActiveId: { ...state.labActiveId, [labId]: defaults[0].id },
          };
        }
        return null;
      }

      return {
        labWorkspaces: {},
        labActiveId: {},

        getWorkspaces: (labId) => {
          const s = get();
          return s.labWorkspaces[labId] ?? makeDefaultWorkspaces();
        },

        getActiveId: (labId) => {
          const s = get();
          const workspaces = s.labWorkspaces[labId];
          if (!workspaces) return "";
          return s.labActiveId[labId] ?? workspaces[0]?.id ?? "";
        },

        setActiveWorkspace: (labId, id) => {
          set((s) => {
            const patch = ensureDefaults(labId, s);
            return {
              ...(patch ?? {}),
              labActiveId: { ...(patch?.labActiveId ?? s.labActiveId), [labId]: id },
            };
          });
        },

        addWorkspace: (labId, name) => {
          set((s) => {
            const patch = ensureDefaults(labId, s);
            const current = patch?.labWorkspaces[labId] ?? s.labWorkspaces[labId] ?? makeDefaultWorkspaces();
            if (current.length >= 9) return {};
            const newWs: LabWorkspace = {
              id: uid(),
              name: name ?? `Workspace ${current.length + 1}`,
              icon: "📋",
              layout: null,
            };
            const updated = [...current, newWs];
            return {
              ...(patch ?? {}),
              labWorkspaces: { ...(patch?.labWorkspaces ?? s.labWorkspaces), [labId]: updated },
              labActiveId: { ...(patch?.labActiveId ?? s.labActiveId), [labId]: newWs.id },
            };
          });
        },

        renameWorkspace: (labId, id, name) => {
          set((s) => {
            const current = s.labWorkspaces[labId] ?? [];
            return {
              labWorkspaces: {
                ...s.labWorkspaces,
                [labId]: current.map((w) => (w.id === id ? { ...w, name } : w)),
              },
            };
          });
        },

        duplicateWorkspace: (labId, id) => {
          set((s) => {
            const current = s.labWorkspaces[labId] ?? [];
            if (current.length >= 9) return {};
            const source = current.find((w) => w.id === id);
            if (!source) return {};
            const copy: LabWorkspace = {
              ...source,
              id: uid(),
              name: `${source.name} (copy)`,
            };
            const idx = current.findIndex((w) => w.id === id);
            const updated = [...current.slice(0, idx + 1), copy, ...current.slice(idx + 1)];
            return {
              labWorkspaces: { ...s.labWorkspaces, [labId]: updated },
              labActiveId: { ...s.labActiveId, [labId]: copy.id },
            };
          });
        },

        deleteWorkspace: (labId, id) => {
          set((s) => {
            const current = s.labWorkspaces[labId] ?? [];
            if (current.length <= 1) return {};
            const remaining = current.filter((w) => w.id !== id);
            const activeId = s.labActiveId[labId];
            const newActive = activeId === id ? remaining[0]?.id ?? "" : activeId ?? "";
            return {
              labWorkspaces: { ...s.labWorkspaces, [labId]: remaining },
              labActiveId: { ...s.labActiveId, [labId]: newActive },
            };
          });
        },

        saveLayout: (labId, id, layout) => {
          set((s) => {
            const current = s.labWorkspaces[labId] ?? [];
            return {
              labWorkspaces: {
                ...s.labWorkspaces,
                [labId]: current.map((w) => (w.id === id ? { ...w, layout } : w)),
              },
            };
          });
        },
      };
    },
    { name: "bmg-workspace-store-v1", version: 1 }
  )
);
