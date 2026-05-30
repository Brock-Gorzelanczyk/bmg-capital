export interface Citation { num: number; label: string; }

// Parse "[1] Yahoo Finance / yfinance data\n[2] ..." from sources block
export function parseCitations(text: string): { body: string; citations: Citation[] } {
  const sep = text.indexOf("---");
  if (sep === -1) return { body: text, citations: [] };
  const body = text.slice(0, sep).trim();
  const sourceBlock = text.slice(sep + 3);
  const citations: Citation[] = [];
  const regex = /\[(\d+)\]\s*(.+)/g;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(sourceBlock)) !== null) {
    citations.push({ num: parseInt(m[1]), label: m[2].trim() });
  }
  return { body, citations };
}

// Render body text: replace [1] with a styled span marker
// Returns segments: { type: "text" | "cite", content: string, num?: number }[]
export type Segment = { type: "text"; content: string } | { type: "cite"; num: number };
export function parseSegments(body: string): Segment[] {
  const parts = body.split(/(\[\d+\])/);
  return parts.map((p) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (m) return { type: "cite" as const, num: parseInt(m[1]) };
    return { type: "text" as const, content: p };
  }).filter((s) => s.type === "cite" || (s.type === "text" && s.content));
}
