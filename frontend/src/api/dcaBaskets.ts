import client from "./client";

export interface DCABasketAsset { symbol: string; allocation_pct: number; asset_type: string; }
export interface DCABasket {
  id: number; name: string; total_amount: number; frequency: string;
  status: string; executions_count: number; total_invested: number;
  created_at: string; assets: DCABasketAsset[];
}
export interface DCATemplate { name: string; total_amount: number; frequency: string; assets: DCABasketAsset[]; }

export const getBaskets = () => client.get<DCABasket[]>("/dca-baskets/").then(r => r.data);
export const getTemplates = () => client.get<DCATemplate[]>("/dca-baskets/templates").then(r => r.data);
export const createBasket = (data: { name: string; total_amount: number; frequency: string; assets: DCABasketAsset[] }) =>
  client.post<DCABasket>("/dca-baskets/", data).then(r => r.data);
export const deleteBasket = (id: number) => client.delete(`/dca-baskets/${id}`);
export const pauseBasket = (id: number) => client.post(`/dca-baskets/${id}/pause`).then(r => r.data);
export const resumeBasket = (id: number) => client.post(`/dca-baskets/${id}/resume`).then(r => r.data);
