/**
 * Persistent legal disclaimer footer. Renders on every authenticated
 * page in the shell. Fixed to the bottom on desktop; sticky on mobile.
 *
 * Item #5 from Brock's 2026-07-03 audit — compliance requirement.
 */
export default function LegalFooter() {
  return (
    <footer
      className="w-full border-t border-t-dim bg-t-bg1/80 backdrop-blur-sm py-2 px-4 text-center"
      role="contentinfo"
      aria-label="Legal disclaimer"
    >
      <p className="text-[10px] md:text-[11px] text-t-muted font-ui-t leading-tight">
        <span className="font-bold text-t-mid2">PAPER TRADING SIMULATION</span>
        <span className="mx-2 opacity-40">·</span>
        <span>Not financial advice</span>
        <span className="mx-2 opacity-40">·</span>
        <span>Past performance is not indicative of future results</span>
        <span className="mx-2 opacity-40 hidden md:inline">·</span>
        <span className="hidden md:inline">Bots run autonomously — review risk parameters before deployment</span>
      </p>
    </footer>
  );
}
