import api from "./client";

export interface TaxOpportunity {
  opportunity: string;
  action: string;
  estimated_savings_dollars: number;
  priority: "high" | "medium" | "low";
}

export interface TaxAnalysisResult {
  agi: number;
  filing_status: string;
  taxable_income: number;
  total_tax: number;
  w2_wages: number | null;
  qualified_dividends: number | null;
  capital_gains: number | null;
  effective_rate_pct: number;
  marginal_bracket: string;
  opportunities: TaxOpportunity[];
  disclaimer: string;
}

export const analyzeTaxReturn = (file: File): Promise<TaxAnalysisResult> => {
  const fd = new FormData();
  fd.append("file", file);
  return api
    .post("/tax/analyze", fd, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 60000,
    })
    .then((r) => r.data);
};
