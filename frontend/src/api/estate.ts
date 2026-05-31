import api from "./client";

export interface BeneficiaryRecord {
  id: number;
  account_name: string;
  account_type: string | null;
  beneficiary_name: string | null;
  beneficiary_relationship: string | null;
  beneficiary_pct: number;
  has_tod: boolean;
  has_pod: boolean;
  last_reviewed: string | null;
  notes: string | null;
  created_at: string | null;
}

export interface DigitalAssetRecord {
  id: number;
  asset_type: string | null;
  description: string | null;
  location_hint: string | null;
  recovery_contact: string | null;
  created_at: string | null;
}

export interface EstateHealthCheck {
  issues: string[];
}

// Beneficiary CRUD
export const listBeneficiaries = () =>
  api.get("/estate/beneficiaries").then((r) => r.data as { beneficiaries: BeneficiaryRecord[] });

export const createBeneficiary = (body: Omit<BeneficiaryRecord, "id" | "created_at">) =>
  api.post("/estate/beneficiaries", body).then((r) => r.data as BeneficiaryRecord);

export const updateBeneficiary = (id: number, body: Partial<Omit<BeneficiaryRecord, "id" | "created_at">>) =>
  api.put(`/estate/beneficiaries/${id}`, body).then((r) => r.data as BeneficiaryRecord);

export const deleteBeneficiary = (id: number) =>
  api.delete(`/estate/beneficiaries/${id}`).then((r) => r.data);

// Health check
export const getEstateHealthCheck = () =>
  api.get("/estate/health-check").then((r) => r.data as EstateHealthCheck);

// Digital assets CRUD
export const listDigitalAssets = () =>
  api.get("/estate/digital-assets").then((r) => r.data as { digital_assets: DigitalAssetRecord[] });

export const createDigitalAsset = (body: Omit<DigitalAssetRecord, "id" | "created_at">) =>
  api.post("/estate/digital-assets", body).then((r) => r.data as DigitalAssetRecord);

export const deleteDigitalAsset = (id: number) =>
  api.delete(`/estate/digital-assets/${id}`).then((r) => r.data);
