import api from "./client";

export interface Proposal {
  id: string;
  title: string;
  summary: string;
  space_id: string;
  space_name: string;
  space_avatar: string;
  start: number;
  end: number;
  state: "active" | "pending" | "closed";
  choices: string[];
  scores: number[];
  scores_total: number;
  votes: number;
  quorum: number;
  author: string;
  url: string;
  top_choice: string;
  top_pct: number;
}

export const getGovernanceProposals = (
  state: "active" | "pending" | "closed" = "active",
  limit: number = 20,
  spaces?: string,
): Promise<{ proposals: Proposal[] }> =>
  api.get("/governance/proposals", { params: { state, limit, spaces } }).then((r) => r.data);

export const getSpaceProposals = (
  space_id: string,
  state = "active",
  limit = 5,
): Promise<{ proposals: Proposal[]; space_id: string }> =>
  api.get(`/governance/proposals/${space_id}`, { params: { state, limit } }).then((r) => r.data);
