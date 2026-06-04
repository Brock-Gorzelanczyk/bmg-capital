import client from "./client";
import type { AlertConfig, AlertTrigger } from "@/types/alerts";

export async function getAlerts(): Promise<AlertConfig[]> {
  const { data } = await client.get<{ alerts: AlertConfig[] }>("/alerts");
  return Array.isArray(data?.alerts) ? data.alerts : [];
}

export async function createAlert(symbol: string, signal_type: string, threshold?: number): Promise<AlertConfig> {
  const { data } = await client.post<AlertConfig>("/alerts", { symbol, signal_type, threshold });
  return data;
}

export async function deleteAlert(id: number): Promise<void> {
  await client.delete(`/alerts/${id}`);
}

export async function getTriggers(): Promise<AlertTrigger[]> {
  const { data } = await client.get<{ triggers: AlertTrigger[] }>("/alerts/triggers");
  return Array.isArray(data?.triggers) ? data.triggers : [];
}

export async function testAlert(symbol: string, signal_type: string, message = "Test alert"): Promise<void> {
  await client.post("/alerts/test", { symbol, signal_type, message });
}
