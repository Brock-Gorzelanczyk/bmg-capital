import { Link } from "react-router-dom";
import { COMPANY_INFO } from "@/data/companyInfo";
import { TICKER_NAMES } from "@/data/tickerNames";

interface Props {
  symbol: string;
  /** If provided, wraps the ticker in a router <Link> to this path. */
  linkTo?: string;
  /** Color for the ticker text (link color). Default emerald green. */
  color?: string;
  /** Show name inline (default) or on a second line ("stacked"). */
  layout?: "inline" | "stacked";
  /** Max characters of the name to show before truncating. Default 32. */
  maxNameLen?: number;
}

/**
 * Renders a ticker with its company name pulled from COMPANY_INFO or
 * TICKER_NAMES. Silently degrades to just the ticker if we don't have
 * the name. Used everywhere in the app that shows a ticker.
 *
 * Layouts:
 *   inline:  "SPG · Simon Property"      (default — for tables)
 *   stacked: "SPG"                        (for detail views / cards)
 *            "Simon Property"
 */
export default function TickerWithName({
  symbol,
  linkTo,
  color = "#4ade80",
  layout = "inline",
  maxNameLen = 32,
}: Props) {
  const sym = symbol.toUpperCase();
  const name = COMPANY_INFO[sym]?.name ?? TICKER_NAMES[sym] ?? null;
  const truncated = name && name.length > maxNameLen
    ? name.slice(0, maxNameLen - 1) + "…"
    : name;

  const tickerEl = linkTo ? (
    <Link
      to={linkTo}
      style={{ color, textDecoration: "none", fontWeight: 600 }}
      title={name || undefined}
    >
      {sym}
    </Link>
  ) : (
    <span style={{ color, fontWeight: 600 }} title={name || undefined}>
      {sym}
    </span>
  );

  if (layout === "stacked") {
    return (
      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
        {tickerEl}
        {truncated && (
          <span style={{ color: "#71717a", fontSize: "0.75em", fontWeight: 400 }}>
            {truncated}
          </span>
        )}
      </div>
    );
  }

  // inline
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 6 }}>
      {tickerEl}
      {truncated && (
        <span style={{ color: "#71717a", fontSize: "0.85em", fontWeight: 400 }}>
          · {truncated}
        </span>
      )}
    </span>
  );
}
