import type { BotListItem } from "@/api/bots";

/**
 * Build the sleeve-card subtitle from per-bot starting capital.
 *
 * Cents-to-dollars conversion happens HERE (typed helper), not in JSX,
 * per skills/05-react-component-conventions.md.
 *
 * Examples:
 *   3 bots, all $100k         -> "3 bots · $100k each"
 *   3 bots, $70k/$90k/$110k   -> "3 bots · $70k–$110k"
 *   1 bot,  $100k             -> "1 bot · $100k"
 *   0 bots                    -> "0 bots"
 *   no allocation data        -> "N bot(s)"  (graceful fallback)
 */
export function formatSleeveSubtitle(bots: BotListItem[]): string {
  const n = bots.length;
  const botLabel = `${n} bot${n !== 1 ? "s" : ""}`;

  const startingKs: number[] = bots
    .map((b) => b.allocation?.starting_capital_cents)
    .filter((c): c is number => typeof c === "number" && c > 0)
    .map((cents) => Math.round(cents / 100 / 1000));

  if (startingKs.length === 0) {
    return botLabel;
  }

  const min = Math.min(...startingKs);
  const max = Math.max(...startingKs);

  if (min === max) {
    if (n === 1) {
      return `${botLabel} · $${min}k`;
    }
    return `${botLabel} · $${min}k each`;
  }

  return `${botLabel} · $${min}k–$${max}k`;
}
