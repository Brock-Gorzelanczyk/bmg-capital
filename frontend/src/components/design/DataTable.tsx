import { cn } from "@/lib/utils";
import { useState } from "react";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  numeric?: boolean;
  width?: string;
  render?: (row: T, idx: number) => React.ReactNode;
  sortable?: boolean;
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  getKey?: (row: T, idx: number) => string | number;
  onRowClick?: (row: T) => void;
  loading?: boolean;
  emptyMessage?: string;
  stickyHeader?: boolean;
  className?: string;
  rowClassName?: (row: T, idx: number) => string;
}

type SortDir = "asc" | "desc";

export function DataTable<T extends Record<string, unknown>>({
  columns,
  rows,
  getKey,
  onRowClick,
  loading = false,
  emptyMessage = "No data",
  stickyHeader = false,
  className,
  rowClassName,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const sorted = sortKey
    ? [...rows].sort((a, b) => {
        const av = a[sortKey] as number;
        const bv = b[sortKey] as number;
        if (av == null) return 1;
        if (bv == null) return -1;
        return sortDir === "desc" ? bv - av : av - bv;
      })
    : rows;

  return (
    <div className={cn("bg-t-bg1 border border-t-dim rounded-sm overflow-hidden", className)}>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead className={cn(stickyHeader && "sticky top-0 z-10", "bg-t-bg0")}>
            <tr className="border-b border-t-dim">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={cn(
                    "px-3 py-2 text-[10px] font-mono-t uppercase tracking-widest text-t-muted whitespace-nowrap",
                    col.numeric && "text-right",
                    col.sortable && "cursor-pointer select-none hover:text-t-mid2 transition-colors",
                    col.width,
                  )}
                  onClick={col.sortable ? () => toggleSort(col.key) : undefined}
                >
                  {col.header}
                  {col.sortable && sortKey === col.key && (
                    <span className="ml-1 text-t-green">{sortDir === "desc" ? "↓" : "↑"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-t-dim/50">
                  {columns.map((col) => (
                    <td key={col.key} className="px-3 py-3">
                      <div className="h-4 bg-t-bg2 rounded animate-pulse w-full" />
                    </td>
                  ))}
                </tr>
              ))
            ) : sorted.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-10 text-center text-t-muted text-xs font-mono-t"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              sorted.map((row, idx) => (
                <tr
                  key={getKey ? getKey(row, idx) : idx}
                  className={cn(
                    "border-b border-t-dim/50 last:border-b-0 transition-colors duration-100",
                    "hover:bg-t-bg2/60",
                    onRowClick && "cursor-pointer",
                    rowClassName?.(row, idx),
                  )}
                  onClick={() => onRowClick?.(row)}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn(
                        "px-3 py-2.5 whitespace-nowrap",
                        col.numeric && "text-right font-mono-t tabular-nums",
                      )}
                    >
                      {col.render
                        ? col.render(row, idx)
                        : (row[col.key] as React.ReactNode)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
