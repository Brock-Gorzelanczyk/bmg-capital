import client from "./client";
import type { FilterConfig, ScreenResult } from "@/types/screener";

export async function runScreen(filters: FilterConfig[]): Promise<ScreenResult[]> {
  const { data } = await client.post<{ results: ScreenResult[]; count: number }>("/screener/run", { filters });
  return data.results;
}

export async function runPreset(name: string): Promise<ScreenResult[]> {
  const { data } = await client.post<{ results: ScreenResult[]; count: number }>(`/screener/presets/${name}`);
  return data.results;
}

export async function getPresets(): Promise<string[]> {
  const { data } = await client.get<{ presets: string[] }>("/screener/presets");
  return data.presets;
}

export interface SavedScreen {
  id: number;
  name: string;
  filters: FilterConfig[];
  created_at: string;
}

export async function getSavedScreens(): Promise<SavedScreen[]> {
  const { data } = await client.get<SavedScreen[]>("/screens");
  return data;
}

export async function saveScreen(name: string, filters: FilterConfig[]): Promise<SavedScreen> {
  const { data } = await client.post<SavedScreen>("/screens", { name, filters });
  return data;
}

export async function deleteSavedScreen(id: number): Promise<void> {
  await client.delete(`/screens/${id}`);
}
