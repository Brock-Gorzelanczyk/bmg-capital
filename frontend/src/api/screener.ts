import client from "./client";
import type { FilterConfig, FilterChip, ScreenResult, ScreenResponse, Suggestion } from "@/types/screener";

export async function runScreen(filters: FilterConfig[]): Promise<ScreenResponse> {
  const { data } = await client.post<ScreenResponse>("/screener/run", { filters });
  return {
    results: Array.isArray(data?.results) ? data.results : [],
    count: data?.count ?? 0,
    universe_count: data?.universe_count ?? 0,
    data_as_of: data?.data_as_of ?? null,
  };
}

export async function runPreset(name: string): Promise<ScreenResponse> {
  const { data } = await client.post<ScreenResponse>(`/screener/presets/${name}`);
  return {
    results: Array.isArray(data?.results) ? data.results : [],
    count: data?.count ?? 0,
    universe_count: data?.universe_count ?? 0,
    data_as_of: data?.data_as_of ?? null,
  };
}

export async function suggestAlternatives(filters: FilterConfig[]): Promise<Suggestion[]> {
  const { data } = await client.post<{ suggestions: Suggestion[] }>("/screener/suggest", { filters });
  return Array.isArray(data?.suggestions) ? data.suggestions : [];
}

export async function getPresets(): Promise<string[]> {
  const { data } = await client.get<{ presets: string[] }>("/screener/presets");
  return Array.isArray(data?.presets) ? data.presets : [];
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

export interface NLParseResult {
  filters: FilterChip[];
  explanation: string;
  merge: boolean;
}

export async function parseNaturalLanguage(
  query: string,
  existingFilters?: FilterChip[],
): Promise<NLParseResult> {
  const body: { query: string; existing_filters?: FilterChip[] } = { query };
  if (existingFilters && existingFilters.length > 0) {
    body.existing_filters = existingFilters;
  }
  const { data } = await client.post<NLParseResult>("/screener/parse-natural-language", body);
  return data;
}
