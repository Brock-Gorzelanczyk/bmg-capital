import client from "./client";

export interface IPODeal {
  id: number;
  company_name: string;
  ticker: string | null;
  expected_date: string | null;
  price_range_low: number | null;
  price_range_high: number | null;
  description: string;
  sector: string;
  lead_underwriter: string | null;
  status: string;
  min_tier: string;
}

export interface IPORegistration {
  id: number;
  status: string;
  requested_amount: number;
  deal: IPODeal | null;
}

export const getIPODeals = () =>
  client.get<IPODeal[]>("/ipo/deals").then(r => r.data);

export const registerIPO = (deal_id: number, requested_amount: number) =>
  client.post(`/ipo/deals/${deal_id}/register`, { requested_amount }).then(r => r.data);

export const getMyIPORegistrations = () =>
  client.get<IPORegistration[]>("/ipo/my-registrations").then(r => r.data);

export const cancelIPORegistration = (id: number) =>
  client.delete(`/ipo/my-registrations/${id}`);
