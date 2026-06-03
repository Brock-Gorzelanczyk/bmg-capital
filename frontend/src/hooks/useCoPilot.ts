import { useState, useEffect } from "react";

export function useCoPilot() {
  const [isOpen, setIsOpen] = useState(false);
  const [prefillQuery, setPrefillQuery] = useState<string>("");

  useEffect(() => {
    function keyHandler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setIsOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", keyHandler);
    return () => window.removeEventListener("keydown", keyHandler);
  }, []);

  // Listen for external open requests (e.g. "Ask Co-Pilot" buttons)
  useEffect(() => {
    function openHandler(e: Event) {
      const { query = "" } = (e as CustomEvent<{ query?: string }>).detail ?? {};
      setPrefillQuery(query);
      setIsOpen(true);
    }
    window.addEventListener("copilot:open", openHandler);
    return () => window.removeEventListener("copilot:open", openHandler);
  }, []);

  return {
    isOpen,
    prefillQuery,
    open: (q?: string) => {
      if (q) setPrefillQuery(q);
      setIsOpen(true);
    },
    close: () => {
      setIsOpen(false);
      setPrefillQuery("");
    },
  };
}
