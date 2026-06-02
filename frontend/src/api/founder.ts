import client from "./client";

// ─── Investor types ────────────────────────────────────────────────────────────

export interface Investor {
  id: number;
  name: string;
  firm: string;
  role: string;
  contact_email: string | null;
  twitter_handle: string | null;
  linkedin_url: string | null;
  intro_path: "cold" | "warm" | "referral";
  status: string;
  last_contact_at: string | null;
  next_action: string | null;
  notes_md: string;
  check_size_target: string | null;
  stage_focus: string | null;
  created_at: string;
  updated_at: string;
}

export interface FollowUpDue {
  investor: Investor;
  follow_up_type: "follow_up_due" | "thank_you_due" | "decision_due";
  days_overdue: number;
}

export interface EmailTemplate {
  id: string;
  name: string;
  subject: string;
  body: string;
}

export interface DailySummary {
  day_number: number;
  investor_pipeline: { total: number; meetings_this_week: number; follow_ups_due: number };
  content: { unfilled_slots_today: number; scheduled_count: number };
  waitlist: { total: number; today_count: number };
  playbook_task: { title: string; description: string; priority: string } | null;
}

// ─── Investor CRUD ─────────────────────────────────────────────────────────────

export const getInvestors = () => client.get<Investor[]>("/founder/investors").then(r => r.data);
export const createInvestor = (data: Partial<Investor>) => client.post<Investor>("/founder/investors", data).then(r => r.data);
export const updateInvestor = (id: number, data: Partial<Investor>) => client.patch<Investor>(`/founder/investors/${id}`, data).then(r => r.data);
export const deleteInvestor = (id: number) => client.delete(`/founder/investors/${id}`);
export const getFollowUpsDue = () => client.get<FollowUpDue[]>("/founder/investors/follow-up-due").then(r => r.data);
export const getEmailTemplates = () => client.get<EmailTemplate[]>("/founder/email-templates").then(r => r.data);
export const personalizeTemplate = (template_id: string, investor_id: number) =>
  client.post<{ subject: string; body: string }>("/founder/email-templates/personalize", { template_id, investor_id }).then(r => r.data);
export const seedFounder = () => client.post("/founder/seed").then(r => r.data);
export const getDailySummary = () => client.get<DailySummary>("/founder/daily-summary").then(r => r.data);

// ─── Waitlist types ────────────────────────────────────────────────────────────

export interface WaitlistSourceRow {
  source: string;
  count: number;
}

export interface WaitlistStats {
  total: number;
  today: number;
  this_week: number;
  viral_k: number;
  activation_rate: number;
  top_sources: WaitlistSourceRow[];
}

export interface WaitlistGrowthPoint {
  date: string;
  count: number;
}

export interface WaitlistLeaderEntry {
  email: string;
  referral_count: number;
  position_in_queue: number;
}

// ─── Waitlist API ──────────────────────────────────────────────────────────────

export const getWaitlistStats = () =>
  client.get<WaitlistStats>("/founder/waitlist/stats").then(r => r.data);

export const getWaitlistGrowth = () =>
  client.get<WaitlistGrowthPoint[]>("/founder/waitlist/growth").then(r => r.data);

export const getWaitlistLeaderboard = () =>
  client.get<WaitlistLeaderEntry[]>("/founder/waitlist/leaderboard").then(r => r.data);

export const getWaitlistSignups = (page?: number) =>
  client.get("/founder/waitlist/signups", { params: { page } }).then(r => r.data);

export const addWaitlistSignup = (email: string, source: string) =>
  client.post("/founder/waitlist/signups", { email, source }).then(r => r.data);

// ─── Content types ─────────────────────────────────────────────────────────────

export interface ContentPost {
  id: number;
  platform: string;
  content_type: string;
  title: string;
  body_md: string;
  scheduled_for: string | null;
  posted_at: string | null;
  status: string;
  compliance_issues: { phrase: string; severity: string }[];
  compliance_checked: boolean;
}

// ─── Content API ───────────────────────────────────────────────────────────────

export const getContentPosts = (params?: { status?: string; platform?: string }) =>
  client.get<ContentPost[]>("/founder/content", { params }).then(r => r.data);

export const createContentPost = (data: Partial<ContentPost>) =>
  client.post<ContentPost>("/founder/content", data).then(r => r.data);

export const updateContentPost = (id: number, data: Partial<ContentPost>) =>
  client.patch<ContentPost>(`/founder/content/${id}`, data).then(r => r.data);

export const deleteContentPost = (id: number) =>
  client.delete(`/founder/content/${id}`);

export const checkCompliance = (id: number) =>
  client.post<{ issues: { phrase: string; severity: string }[] }>(`/founder/content/${id}/check-compliance`).then(r => r.data);

export const getDraftVault = () =>
  client.get<ContentPost[]>("/founder/content/drafts").then(r => r.data);
