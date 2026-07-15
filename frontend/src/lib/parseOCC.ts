/**
 * OCC option symbol parser + humanized formatter.
 *
 * OCC format: ROOT + YYMMDD + C|P + strike(8 digits, price × 1000).
 * Example: BABA260828C00111000
 *   → root=BABA, expiry=2026-08-28, type=CALL, strike=$111
 *
 * Reference: BMG Bot Detail.html → parseOCC()
 *
 * Also fixes the +214% / -1994% garbage: when computing P&L in the UI,
 * always use `pnlDollars(avgPremium, mark, contracts)` which applies the
 * ×100 contract multiplier the backend now includes.
 */

export interface ParsedOCC {
  root: string;
  expiry: Date;        // UTC-anchored midnight of the expiration date
  type: "CALL" | "PUT";
  strike: number;      // dollars, decimal
}

const OCC_RE = /^([A-Z][A-Z0-9]*)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/;

export function parseOCC(occ: string): ParsedOCC | null {
  if (!occ) return null;
  const m = occ.match(OCC_RE);
  if (!m) return null;
  const [, root, yy, mm, dd, cp, strikeRaw] = m;
  return {
    root,
    expiry: new Date(Date.UTC(2000 + +yy, +mm - 1, +dd)),
    type: cp === "C" ? "CALL" : "PUT",
    strike: (+strikeRaw) / 1000,
  };
}

const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

/** "BABA $111 CALL" — the primary line. Strike shown without decimals when whole. */
export function formatOCCLabel(occ: string): string {
  const o = parseOCC(occ);
  if (!o) return occ;
  const strikeStr = o.strike % 1 === 0 ? o.strike.toFixed(0) : o.strike.toFixed(2);
  return `${o.root} $${strikeStr} ${o.type}`;
}

/** "Aug 28 '26 · 44 DTE" — the sub line. */
export function formatOCCExpiryLine(occ: string, now: Date = new Date()): string {
  const o = parseOCC(occ);
  if (!o) return "";
  const mon = MON[o.expiry.getUTCMonth()];
  const day = o.expiry.getUTCDate();
  const yy = String(o.expiry.getUTCFullYear()).slice(2);
  const nowUTC = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const dte = Math.round((o.expiry.getTime() - nowUTC) / 86400000);
  return `${mon} ${day} '${yy} · ${dte} DTE`;
}

/** Number of days from today (UTC) to expiration. Negative = expired. */
export function dteFromOCC(occ: string, now: Date = new Date()): number | null {
  const o = parseOCC(occ);
  if (!o) return null;
  const nowUTC = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((o.expiry.getTime() - nowUTC) / 86400000);
}

/** DTE color per spec: amber ≤ 21d, red ≤ 7d, otherwise muted. */
export function dteColor(dte: number | null): string {
  if (dte === null) return "#64748b";
  if (dte <= 7) return "#f87171";
  if (dte <= 21) return "#f0b35a";
  return "#94a3b8";
}

/**
 * P&L math with the ×100 contract multiplier.
 *
 * cost_basis   = avgPremium × contracts × 100
 * market_value = mark × contracts × 100
 * open_pl      = market_value − cost_basis
 * open_pl_pct  = open_pl / cost_basis × 100
 *
 * This mirrors the fixed backend formula in
 * app/routers/portfolio.py:242-250. The bug it replaces produced +214%
 * / -1994% garbage because the ×100 was applied to market_value but the
 * quantity was dropped from cost_basis.
 */
export interface OptionPnL {
  cost: number;
  value: number;
  pl: number;
  plPct: number;      // pct, not fraction; capped at ±999 for display
  plPctRaw: number;   // pct, uncapped, for computation
}

export function optionPnL(
  avgPremium: number,
  mark: number,
  contracts: number,
): OptionPnL {
  const cost = avgPremium * contracts * 100;
  const value = mark * contracts * 100;
  const pl = value - cost;
  const plPctRaw = cost > 0 ? (pl / cost) * 100 : 0;
  // Cap display at ±999% per spec ("stop the -1994% class of nonsense
  // from ever rendering").
  const plPct = Math.max(-999, Math.min(999, plPctRaw));
  return { cost, value, pl, plPct, plPctRaw };
}
