import { COMPANY_INFO, SECTOR_COLOR } from "@/data/companyInfo";

interface Props {
  symbol: string;
  className?: string;
}

export default function SectorPill({ symbol, className }: Props) {
  const info = COMPANY_INFO[symbol];
  if (!info?.sector) return null;

  const color = SECTOR_COLOR[info.sector] ?? "#6b7280";
  return (
    <span
      className={`inline-block text-[10px] font-medium px-1.5 py-0.5 rounded-full leading-tight ${className ?? ""}`}
      style={{ backgroundColor: color + "22", color }}
    >
      {info.sector}
    </span>
  );
}
