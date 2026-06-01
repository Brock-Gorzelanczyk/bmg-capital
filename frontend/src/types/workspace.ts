export interface Workspace {
  id: string;
  name: string;
  icon: string;
  layout: WorkspaceLayout | null;
}

export interface WorkspaceLayout {
  panels: PanelConfig[];
}

export interface PanelConfig {
  id: string;
  component: string;
  title: string;
  params?: Record<string, unknown>;
}

export type LabId = "strategy" | "options" | "crypto" | "ta-workshop";
