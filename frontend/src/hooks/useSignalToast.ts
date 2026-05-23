import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useAlertStore } from "@/store";

export function useSignalToast() {
  const notifications = useAlertStore((s) => s.notifications);
  const prevLen = useRef(0);

  useEffect(() => {
    if (notifications.length > prevLen.current) {
      const newest = notifications[0];
      toast(`${newest.symbol}: ${newest.signal_type.replace(/_/g, " ")}`, {
        description: newest.message,
        duration: 5000,
      });
    }
    prevLen.current = notifications.length;
  }, [notifications]);
}
