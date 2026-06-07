import { Eye } from "lucide-react";
import { useIsViewer } from "@/store/authStore";

export default function ViewerBanner() {
  const isViewer = useIsViewer();
  if (!isViewer) return null;

  return (
    <div className="w-full bg-amber-500/10 border-b border-amber-500/20 px-4 py-2 flex items-center justify-center gap-2 text-xs text-amber-300 z-50 flex-shrink-0">
      <Eye size={13} className="flex-shrink-0" />
      <span>
        You're viewing BMG Capital in demo mode. Browse anything — you can't make changes.
        Like what you see? Ask the admin for full access.
      </span>
    </div>
  );
}
