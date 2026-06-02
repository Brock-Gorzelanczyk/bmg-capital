import client from "./client";

export interface RiskProfile {
  time_horizon: string;
  goal_type: string;
  income_bracket: string;
  savings_rate: number;
  loss_tolerance: string;
  experience: string;
  has_emergency_fund: boolean;
  risk_score: number;
  target_allocation: Record<string, number>;
}

export interface RoboGoal {
  id: number;
  name: string;
  goal_type: string;
  target_amount: number;
  target_date: string | null;
  current_balance: number;
  monthly_contribution: number;
  status: "on_track" | "behind" | "ahead" | "completed";
  probability_pct: number;
  glide_path: Array<{ date: string; equity: number; bonds: number; cash: number }>;
}

export interface RoboDashboard {
  total_value: number;
  core: {
    value: number;
    allocation_pct: number;
    ytd_return_pct: number;
    rebalance_needed: boolean;
    goals: Array<{ name: string; value: number; target: number; probability_pct: number }>;
    direct_index_enabled: boolean;
  };
  active: {
    value: number;
    allocation_pct: number;
    ytd_return_pct: number;
    paper_value: number;
    holdings_value: number;
    crypto_value: number;
  };
  suggested_split: string;
  risk_profile: RiskProfile | null;
}

export interface RebalanceSimulation {
  trigger: string;
  trades: Array<{ symbol: string; action: string; qty_needed: number; estimated_value: number }>;
  summary: string;
  taxes_triggered: number;
}

export const getRoboDashboard = () =>
  client.get<RoboDashboard>("/robo/dashboard").then((r) => r.data);

export const getRoboProfile = () =>
  client.get<{ profile: RiskProfile | null }>("/robo/profile").then((r) => r.data);

export const submitQuiz = (answers: object) =>
  client
    .post<{
      risk_score: number;
      target_allocation: Record<string, number>;
      portfolio_type: string;
      message: string;
    }>("/robo/quiz", answers)
    .then((r) => r.data);

export const getGoals = () =>
  client.get<{ goals: RoboGoal[] }>("/robo/goals").then((r) => r.data);

export const createGoal = (data: object) =>
  client.post<RoboGoal>("/robo/goals", data).then((r) => r.data);

export const updateGoal = (id: number, data: object) =>
  client.put<RoboGoal>(`/robo/goals/${id}`, data).then((r) => r.data);

export const deleteGoal = (id: number) => client.delete(`/robo/goals/${id}`);

export const getGoalProjection = (id: number) =>
  client
    .get<{
      probability_pct: number;
      expected_value: number;
      percentile_10: number;
      percentile_50: number;
      percentile_90: number;
      monthly_needed_for_90pct: number;
    }>(`/robo/goals/${id}/projection`)
    .then((r) => r.data);

export const simulateRebalance = (deposit?: number) =>
  client
    .post<RebalanceSimulation>("/robo/rebalance/simulate", {
      deposit_amount: deposit,
    })
    .then((r) => r.data);

export const getRebalanceHistory = () =>
  client.get<{ logs: object[] }>("/robo/rebalance/history").then((r) => r.data);

export const getAiExplanation = (context: string, data: object) =>
  client
    .post<{ explanation: string }>("/robo/ai/explain", { context, data })
    .then((r) => r.data);
