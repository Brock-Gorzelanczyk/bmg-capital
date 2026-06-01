import { useQuery } from "@tanstack/react-query";
import type { IDockviewPanelProps } from "dockview";
import { cn } from "@/lib/utils";
import { getPnlCalendar, type PnlDay } from "@/api/strategy";

const DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const fmt$ = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0 });

function buildCalendarMonth(year: number, month: number, days: PnlDay[]) {
  const dayMap = new Map(days.map((d) => [d.date, d]));
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: Array<{ date: string | null; day: PnlDay | null }> = [];

  for (let i = 0; i < firstDay; i++) cells.push({ date: null, day: null });
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    cells.push({ date: dateStr, day: dayMap.get(dateStr) ?? null });
  }
  return cells;
}

export default function PnLCalendarWidget(_props: IDockviewPanelProps) {
  const { data, isLoading, error } = useQuery<{ days: PnlDay[] }>({
    queryKey: ["strategy-pnl-calendar"],
    queryFn: getPnlCalendar,
    staleTime: 60_000,
  });

  const today = new Date();
  const todayStr = today.toISOString().slice(0, 10);

  const days = data?.days ?? [];

  // Determine which months to show (up to last 2 months)
  const months: Array<{ year: number; month: number }> = [];
  for (let offset = 1; offset >= 0; offset--) {
    const d = new Date(today.getFullYear(), today.getMonth() - offset, 1);
    months.push({ year: d.getFullYear(), month: d.getMonth() });
  }

  // Summary: current month P&L
  const thisMonthPrefix = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const thisMonthDays = days.filter((d) => d.date.startsWith(thisMonthPrefix));
  const monthPnl = thisMonthDays.reduce((sum, d) => sum + (d.day_pnl ?? 0), 0);
  const greenDays = thisMonthDays.filter((d) => (d.day_pnl ?? 0) > 0).length;
  const redDays = thisMonthDays.filter((d) => (d.day_pnl ?? 0) < 0).length;

  return (
    <div className="flex flex-col h-full bg-[var(--bg-elevated)] text-[var(--text-primary)] overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)] shrink-0">
        <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
          P&L Calendar
        </span>
        {thisMonthDays.length > 0 && (
          <div className="flex items-center gap-3 text-[10px]">
            <span className="text-emerald-400">{greenDays}W</span>
            <span className="text-red-400">{redDays}L</span>
            <span className={cn("font-mono font-bold", monthPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
              {monthPnl >= 0 ? "+" : ""}{fmt$(monthPnl)}
            </span>
          </div>
        )}
      </div>

      {isLoading && (
        <div className="flex items-center justify-center flex-1 text-[var(--text-tertiary)] text-xs">
          Loading…
        </div>
      )}
      {error && (
        <div className="flex items-center justify-center flex-1 text-red-400 text-xs">
          Failed to load calendar
        </div>
      )}

      {!isLoading && !error && (
        <div className="flex-1 overflow-auto px-3 py-2 space-y-4">
          {months.map(({ year, month }) => {
            const cells = buildCalendarMonth(year, month, days);
            return (
              <div key={`${year}-${month}`}>
                <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-2">
                  {MONTHS[month]} {year}
                </div>
                <div className="grid grid-cols-7 gap-0.5">
                  {DAYS.map((d) => (
                    <div key={d} className="text-center text-[9px] text-[var(--text-tertiary)] pb-1">
                      {d}
                    </div>
                  ))}
                  {cells.map((cell, idx) => {
                    if (!cell.date) {
                      return <div key={`empty-${idx}`} />;
                    }
                    const isToday = cell.date === todayStr;
                    const pnl = cell.day?.day_pnl ?? null;
                    const hasData = pnl !== null;
                    const dayNum = parseInt(cell.date.slice(8), 10);

                    return (
                      <div
                        key={cell.date}
                        title={hasData ? `${cell.date}: ${fmt$(pnl!)}` : cell.date}
                        className={cn(
                          "aspect-square rounded flex flex-col items-center justify-center text-[9px] font-mono transition-colors relative",
                          isToday && "ring-1 ring-[#BEF264]",
                          hasData && pnl! > 0 && "bg-emerald-500/20 text-emerald-300",
                          hasData && pnl! < 0 && "bg-red-500/20 text-red-300",
                          hasData && pnl! === 0 && "bg-zinc-700/50 text-zinc-400",
                          !hasData && "text-[var(--text-tertiary)] opacity-40"
                        )}
                      >
                        <span>{dayNum}</span>
                        {hasData && (
                          <span className="text-[7px] leading-none opacity-80">
                            {pnl! >= 0 ? "+" : ""}{pnl!.toFixed(0)}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
