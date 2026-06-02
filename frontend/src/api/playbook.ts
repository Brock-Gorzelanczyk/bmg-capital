import client from "@/api/client";

export interface PlaybookTask {
  id: number;
  week_id: number;
  day_focus: string;
  title: string;
  description: string;
  effort_hours: number;
  priority: string;
  status: string;
  completion_note: string | null;
  completed_at: string | null;
  sort_order: number;
}

export interface PlaybookWeek {
  id: number;
  phase_id: number;
  week_number: number;
  title: string;
  day_start: number;
  day_end: number;
  outcome_target: string;
  status: string;
  tasks: PlaybookTask[];
}

export interface PlaybookPhase {
  id: number;
  phase_number: number;
  name: string;
  day_start: number;
  day_end: number;
  outcome_target: string;
  weeks: PlaybookWeek[];
}

export interface PlaybookStatus {
  day_number: number;
  current_phase: string | null;
  current_week: string | null;
  total_tasks: number;
  completed_tasks: number;
  completion_pct: number;
  started_at: string | null;
}

export interface Decision {
  question: string;
  answer: string;
}

export async function getPlaybookStatus(): Promise<PlaybookStatus> {
  const { data } = await client.get("/playbook/status");
  return data;
}

export async function getPlaybookPhases(): Promise<PlaybookPhase[]> {
  const { data } = await client.get("/playbook/phases");
  return data;
}

export async function patchPlaybookTask(
  taskId: number,
  body: { status?: string; completion_note?: string }
): Promise<PlaybookTask> {
  const { data } = await client.patch(`/playbook/tasks/${taskId}`, body);
  return data;
}

export async function createPlaybookTask(body: {
  week_id: number;
  title: string;
  description?: string;
  effort_hours?: number;
  priority?: string;
  day_focus?: string;
}): Promise<PlaybookTask> {
  const { data } = await client.post("/playbook/tasks", body);
  return data;
}

export async function getDoNotDo(): Promise<{ items: string[] }> {
  const { data } = await client.get("/playbook/do-not-do");
  return data;
}

export async function getDecisions(): Promise<{ decisions: Decision[] }> {
  const { data } = await client.get("/playbook/decisions");
  return data;
}

export async function initPlaybook(): Promise<{ seeded: boolean; phases: number }> {
  const { data } = await client.post("/playbook/init");
  return data;
}
