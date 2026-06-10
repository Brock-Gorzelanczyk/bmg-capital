import { Link } from "react-router-dom";

interface Props {
  replacedBy?: { label: string; to: string };
}

export default function RetiredBanner({ replacedBy }: Props) {
  return (
    <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl px-4 py-3 mb-4 flex items-center justify-between gap-4 flex-wrap mx-4 mt-4">
      <div className="flex items-center gap-2">
        <span className="text-amber-400 text-sm">⚠</span>
        <p className="text-amber-300 text-sm font-medium">This page is being retired.</p>
        <p className="text-amber-400/70 text-xs">Scheduled for removal in 2 weeks.</p>
      </div>
      {replacedBy && (
        <Link
          to={replacedBy.to}
          className="text-xs font-semibold text-amber-400 hover:text-amber-300 border border-amber-500/30 rounded-lg px-3 py-1.5 transition-colors whitespace-nowrap"
        >
          Go to {replacedBy.label} →
        </Link>
      )}
    </div>
  );
}
