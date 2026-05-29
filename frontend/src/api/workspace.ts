import api from "./client";

export interface WorkspaceData {
  id: number;
  name: string;
  icon: string;
  layout_json: string;
  widgets_json: string;
  is_default: boolean;
  sort_order: number;
}

export const getWorkspaces = () => api.get<WorkspaceData[]>("/workspaces").then((r) => r.data);

export const createWorkspace = (data: Partial<WorkspaceData>) =>
  api.post<WorkspaceData>("/workspaces", data).then((r) => r.data);

export const updateWorkspace = (id: number, data: Partial<WorkspaceData>) =>
  api.put<WorkspaceData>(`/workspaces/${id}`, data).then((r) => r.data);

export const deleteWorkspace = (id: number) =>
  api.delete(`/workspaces/${id}`).then((r) => r.data);
