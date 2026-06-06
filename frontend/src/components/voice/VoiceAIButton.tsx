import { Mic } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getVoiceUsage } from "@/api/voice";

interface Props {
  onClick: () => void;
}

export default function VoiceAIButton({ onClick }: Props) {
  const { data: usage } = useQuery({
    queryKey: ["voice-usage"],
    queryFn: getVoiceUsage,
    staleTime: 30_000,
  });

  return (
    <button
      onClick={onClick}
      className="fixed z-50 flex items-center gap-2 px-4 py-3 rounded-full bg-[#84cc16] text-black font-semibold text-sm shadow-lg hover:bg-[#a3e635] transition-all hover:scale-105 active:scale-95 bottom-[calc(5rem+env(safe-area-inset-bottom))] left-4 md:bottom-6 md:left-auto md:right-6"
      title="Voice AI (⌘⇧V)"
    >
      <Mic className="w-4 h-4" />
      <span className="hidden sm:inline">
        {usage?.unlimited ? "∞" : "10 min"} Voice AI
      </span>
    </button>
  );
}
