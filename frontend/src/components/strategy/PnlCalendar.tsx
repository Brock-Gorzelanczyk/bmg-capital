import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPnlCalendar, type PnlDay } from "@/api/strategy";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight, X, TrendingUp, TrendingDown } from "lucide-react";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DAYS   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

function fmt$(n: number) {
  const abs = Math.abs(n);
  return (n < 0 ? "-" : "+") + "$" + abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n: number) {
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

interface DayModalProps {
  day: PnlDay;
  onClose: () => void;
}

function DayModal({ day, onClose }: DayModalProps) {
  const d = new Date(day.date + "T12:00:00");
  const label = d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  const isUp = day.day_pnl >= 0;

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-[#0F172A] border border-[#1E293B] rounded-2xl shadow-2xl p-5">
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-xs text-[#475569] uppercase tracking-widest mb-1">Daily Recap</div>
            <div className="text-sm font-semibold text-white">{label}</div>
          </div>
          <button onClick={onClose} className="text-[#475569] hover:text-white transition-colors cursor-pointer mt-0.5">
            <X size={16} />
          </button>
        </div>

        {/* P&L summary */}
        <div className={cn("rounded-xl p-4 mb-4 flex items-center justify-between", isUp ? "bg-emerald-900/20 border border-emerald-500/20" : "bg-red-900/20 border border-red-500/20")}>
          <div>
            <div className="text-xs text-[#475569] mb-1">Day P&L</div>
            <div className={cn("text-2xl font-bold font-mono", isUp ? "text-emerald-400" : "text-red-400")}>
              {fmt$(day.day_pnl)}
            </div>
            <div className={cn("text-sm font-mono", isUp ? "text-emerald-500" : "text-red-500")}>
              {fmtPct(day.day_pnl_pct)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-[#475569] mb-1">Portfolio Value</div>
            <div className="text-sm font-mono text-[#94A3B8]">${day.portfolio_value.toLocaleString("en-US", { minimumFractionDigits: 2 })}</div>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          {[
            { label: "New Entries", value: day.new_entries },
            { label: "Exits", value: day.exits_today },
            { label: "Open Positions", value: day.open_positions },
          ].map(({ label, value }) => (
            <div key={label} className="bg-[#1E293B] rounded-lg px-3 py-2 text-center">
              <div className="text-[10px] text-[#475569] uppercase tracking-wider">{label}</div>
              <div className="text-lg font-bold text-white font-mono mt-0.5">{value}</div>
            </div>
          ))}
        </div>

        {/* Trade events */}
        {day.trades.length > 0 ? (
          <div>
            <div className="text-xs text-[#475569] uppercase tracking-widest mb-2">Trades</div>
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {day.trades.map((t, i) => {
                const isEntry = t.event_type.includes("entry");
                return (
                  <div key={i} className="flex items-center gap-2.5 bg-[#1E293B] rounded-lg px-3 py-2">
                    <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded uppercase", isEntry ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400")}>
                      {isEntry ? "BUY" : "SELL"}
                    </span>
                    <span className="font-mono font-bold text-white text-sm">{t.symbol}</span>
                    {t.price != null && <span className="text-xs text-[#475569] font-mono">${t.price.toFixed(2)}</span>}
                    <span className="text-xs text-[#334155] flex-1 truncate">{t.preset_label}</span>
                    {t.pnl_pct != null && (
                      <span className={cn("text-xs font-mono", t.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(1)}%
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <p className="text-xs text-[#334155] text-center py-2">No trade events recorded for this day</p>
        )}
      </div>
    </>
  );
}

export default function PnlCalendar() {
  const today = new Date();
  const [month, setMonth] = useState(today.getMonth());
  const [year, setYear] = useState(today.getFullYear());
  const [selected, setSelected] = useState<PnlDay | null>(null);

  const { data } = useQuery({
    queryKey: ["pnl-calendar"],
    queryFn: getPnlCalendar,
    staleTime: 300_000,
  });

  const dayMap = new Map<string, PnlDay>();
  (data?.days ?? []).forEach((d) => dayMap.set(d.date, d));

  // Build calendar grid
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  // Pad to complete last row
  while (cells.length % 7 !== 0) cells.push(null);

  function prevMonth() {
    if (month === 0) { setMonth(11); setYear(y => y - 1); }
    else setMonth(m => m - 1);
  }
  function nextMonth() {
    if (month === 11) { setMonth(0); setYear(y => y + 1); }
    else setMonth(m => m + 1);
  }

  const todayStr = today.toISOString().slice(0, 10);

  return (
    <div className="bg-[#0F172A] border border-[#1E293B] rounded-2xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-semibold text-[#64748B] uppercase tracking-widest">P&L Calendar</span>
        <div className="flex items-center gap-2">
          <button onClick={prevMonth} className="text-[#475569] hover:text-white transition-colors cursor-pointer p-1">
            <ChevronLeft size={14} />
          </button>
          <span className="text-sm font-semibold text-white w-28 text-center">{MONTHS[month]} {year}</span>
          <button onClick={nextMonth} className="text-[#475569] hover:text-white transition-colors cursor-pointer p-1">
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {/* Day-of-week headers */}
      <div className="grid grid-cols-7 mb-1">
        {DAYS.map(d => (
          <div key={d} className="text-center text-[10px] text-[#334155] uppercase tracking-widest py-1">{d}</div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((day, i) => {
          if (day === null) return <div key={i} />;
          const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
          const dow = new Date(year, month, day).getDay(); // 0=Sun, 6=Sat
          const isWeekend = dow === 0 || dow === 6;
          const pnlDay = isWeekend ? undefined : dayMap.get(dateStr);
          const isToday = dateStr === todayStr;
          const isUp = pnlDay && pnlDay.day_pnl >= 0;
          const isBigUp = pnlDay && pnlDay.day_pnl_pct > 1;
          const isBigDown = pnlDay && pnlDay.day_pnl_pct < -1;

          return (
            <button
              key={i}
              onClick={() => pnlDay && setSelected(pnlDay)}
              className={cn(
                "relative aspect-square rounded-lg flex flex-col items-center justify-center transition-all text-[11px] font-medium",
                pnlDay ? "cursor-pointer" : "cursor-default",
                isToday && "ring-1 ring-[#3B82F6]",
                !pnlDay && "text-[#334155]",
                pnlDay && isUp && !isBigUp && "bg-emerald-900/25 text-emerald-400 hover:bg-emerald-900/40",
                pnlDay && isBigUp && "bg-emerald-900/50 text-emerald-300 hover:bg-emerald-900/60",
                pnlDay && !isUp && !isBigDown && "bg-red-900/25 text-red-400 hover:bg-red-900/40",
                pnlDay && isBigDown && "bg-red-900/50 text-red-300 hover:bg-red-900/60",
                !pnlDay && "text-[#334155] hover:bg-[#1E293B]/40",
              )}
            >
              <span>{day}</span>
              {pnlDay && (
                <>
                  <span className="text-[9px] font-mono leading-none mt-0.5 opacity-90">
                    {pnlDay.day_pnl >= 0 ? "+" : "-"}${Math.abs(pnlDay.day_pnl) >= 1000 ? (Math.abs(pnlDay.day_pnl) / 1000).toFixed(1) + "k" : Math.abs(pnlDay.day_pnl).toFixed(0)}
                  </span>
                  <span className="text-[8px] font-mono leading-none opacity-70">
                    {pnlDay.day_pnl_pct >= 0 ? "+" : ""}{pnlDay.day_pnl_pct.toFixed(1)}%
                  </span>
                </>
              )}
            </button>
          );
        })}
      </div>

      {/* Monthly summary */}
      {data && data.days.length > 0 && (() => {
        const monthDays = data.days.filter(d => d.date.startsWith(`${year}-${String(month + 1).padStart(2, "0")}`));
        if (!monthDays.length) return null;
        const monthPnl = monthDays.reduce((s, d) => s + d.day_pnl, 0);
        const upDays = monthDays.filter(d => d.day_pnl > 0).length;
        const downDays = monthDays.filter(d => d.day_pnl < 0).length;
        return (
          <div className="mt-3 pt-3 border-t border-[#1E293B] flex items-center justify-between text-xs">
            <span className="text-[#475569]">{upDays}W · {downDays}L</span>
            <span className={cn("font-mono font-semibold", monthPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
              {fmt$(monthPnl)} this month
            </span>
          </div>
        );
      })()}

      {selected && <DayModal day={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
