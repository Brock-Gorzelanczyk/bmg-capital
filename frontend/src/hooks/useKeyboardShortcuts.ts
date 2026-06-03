import { useEffect } from "react";
import type { NavigateFunction } from "react-router-dom";

const BOT_ROUTES: Record<string, string> = {
  "1": "stock_day",
  "2": "stock_swing",
  "3": "stock_lt",
  "4": "crypto_day",
  "5": "crypto_swing",
  "6": "crypto_lt",
};

interface ShortcutCallbacks {
  onPause?: () => void;
  onFocusSearch?: () => void;
  onToggleShortcutOverlay?: () => void;
  onOpenCoPilot?: () => void;
}

/**
 * Global keyboard shortcut registry.
 *
 * Shortcuts:
 *   Cmd+K / Ctrl+K → open CoPilot
 *   1-6            → navigate to bot by index
 *   P              → pause current bot (if on BotDetailPage)
 *   /              → focus activity search input
 *   ?              → show/hide shortcut overlay
 *   Esc            → go back to Command Center if on detail page
 *
 * Ignores shortcuts when user is typing in an input/textarea/select.
 */
export function useKeyboardShortcuts(
  navigate: NavigateFunction,
  currentBotName: string | undefined,
  callbacks: ShortcutCallbacks = {}
) {
  const { onPause, onFocusSearch, onToggleShortcutOverlay, onOpenCoPilot } = callbacks;

  useEffect(() => {
    function isTyping(e: KeyboardEvent): boolean {
      const target = e.target as HTMLElement | null;
      if (!target) return false;
      const tag = target.tagName.toLowerCase();
      return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
    }

    function handler(e: KeyboardEvent) {
      // Cmd+K / Ctrl+K → CoPilot (handled in useCoPilot, but callback bridge for consumers)
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onOpenCoPilot?.();
        return;
      }

      // Remaining shortcuts require no meta keys and no active text input
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTyping(e)) return;

      // 1-6 → navigate to bot
      if (BOT_ROUTES[e.key]) {
        e.preventDefault();
        navigate(`/strategy/${BOT_ROUTES[e.key]}`);
        return;
      }

      // P → pause current bot
      if ((e.key === "p" || e.key === "P") && currentBotName) {
        e.preventDefault();
        onPause?.();
        return;
      }

      // / → focus search
      if (e.key === "/") {
        e.preventDefault();
        onFocusSearch?.();
        return;
      }

      // ? → shortcut overlay
      if (e.key === "?") {
        e.preventDefault();
        onToggleShortcutOverlay?.();
        return;
      }

      // Esc → back to Command Center if on detail page
      if (e.key === "Escape" && currentBotName) {
        // Only navigate back if no modal is open (modals handle their own Esc)
        navigate("/strategy");
        return;
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate, currentBotName, onPause, onFocusSearch, onToggleShortcutOverlay, onOpenCoPilot]);
}
