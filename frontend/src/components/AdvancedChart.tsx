/**
 * TradingView Advanced Charts widget wrapper.
 *
 * PREREQUISITE: The charting_library bundle must be installed at
 *   frontend/public/charting_library/
 * Extract charting_library.zip there and restart the dev server.
 * The directory is .gitignored (proprietary license).
 */
import { useEffect, useRef } from "react";
import { BMGDatafeed } from "@/lib/chart/BMGDatafeed";
import { getBmgCustomIndicators } from "@/lib/chart/customIndicators";

declare global {
  interface Window {
    TradingView: any;
  }
}

interface AdvancedChartProps {
  symbol?: string;
  theme?: "dark" | "light";
  interval?: string;
  onSymbolChange?: (symbol: string) => void;
}

const LIBRARY_PATH = "/charting_library/";
const LIBRARY_SCRIPT = `${LIBRARY_PATH}charting_library.js`;

export function AdvancedChart({
  symbol = "AAPL",
  theme = "dark",
  interval = "1D",
  onSymbolChange,
}: AdvancedChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const initWidget = () => {
      if (!window.TradingView?.widget) {
        setTimeout(initWidget, 100);
        return;
      }

      if (widgetRef.current) {
        try { widgetRef.current.remove(); } catch {}
        widgetRef.current = null;
      }

      const container = containerRef.current!;

      const widget = new window.TradingView.widget({
        // Required
        container,
        library_path: LIBRARY_PATH,
        datafeed: new BMGDatafeed(),
        symbol,
        interval,
        locale: "en",
        timezone: "America/New_York",
        autosize: true,
        theme,

        // Layout persistence
        load_last_chart: true,
        save_load_adapter: {
          getAllCharts: () =>
            fetch("/api/users/me/chart-layouts", { credentials: "include" })
              .then((r) => r.json())
              .then((r) => r.charts || [])
              .catch(() => []),

          saveChart: (chartData: any) =>
            fetch("/api/users/me/chart-layouts", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              credentials: "include",
              body: JSON.stringify({ name: chartData.name || "My Chart", content: chartData }),
            })
              .then((r) => r.json())
              .then((r) => r.id)
              .catch(() => null),

          removeChart: (id: number) =>
            fetch(`/api/users/me/chart-layouts/${id}`, {
              method: "DELETE",
              credentials: "include",
            }).catch(() => {}),

          getChartContent: (id: number) =>
            fetch(`/api/users/me/chart-layouts/${id}`, { credentials: "include" })
              .then((r) => r.json())
              .then((r) => r.content || {})
              .catch(() => ({})),
        },

        // BMG brand
        logo: { image: "", link: "/" },

        // Feature flags
        enabled_features: [
          "study_templates",
          "use_localstorage_for_settings",
          "side_toolbar_in_fullscreen_mode",
          "header_in_fullscreen_mode",
          "header_screenshot",
          "header_compare",
          "header_indicators",
          "header_chart_type",
          "header_settings",
          "header_resolutions",
          "header_undo_redo",
          "header_saveload",
          "control_bar",
          "edit_buttons_in_legend",
          "context_menus",
          "main_series_scale_menu",
          "create_volume_indicator_by_default",
          "legend_widget",
          "display_market_status",
          "symbol_info",
          "symbol_search_hot_key",
          "left_toolbar",
          "timeframes_toolbar",
          "show_dom_first_time",
        ],

        disabled_features: ["study_dialog_search_control"],

        // BMG color overrides
        overrides: {
          "paneProperties.background": theme === "dark" ? "#0a0a0a" : "#F8F9FA",
          "paneProperties.backgroundType": "solid",
          "mainSeriesProperties.candleStyle.upColor": "#10B981",
          "mainSeriesProperties.candleStyle.downColor": "#EF4444",
          "mainSeriesProperties.candleStyle.borderUpColor": "#10B981",
          "mainSeriesProperties.candleStyle.borderDownColor": "#EF4444",
          "mainSeriesProperties.candleStyle.wickUpColor": "#10B981",
          "mainSeriesProperties.candleStyle.wickDownColor": "#EF4444",
          "scalesProperties.textColor": theme === "dark" ? "#9CA3AF" : "#374151",
          "scalesProperties.lineColor": theme === "dark" ? "#27272A" : "#E5E7EB",
          "paneProperties.vertGridProperties.color": theme === "dark" ? "#18181B" : "#F3F4F6",
          "paneProperties.horzGridProperties.color": theme === "dark" ? "#18181B" : "#F3F4F6",
        },

        studies_overrides: {
          "volume.volume.color.0": "#EF444466",
          "volume.volume.color.1": "#10B98166",
        },

        // BMG custom indicators
        custom_indicators_getter: (PineJS: any) =>
          Promise.resolve(getBmgCustomIndicators(PineJS)),
      });

      widget.onChartReady(() => {
        // Symbol change callback
        if (onSymbolChange) {
          try {
            widget.activeChart().onSymbolChanged().subscribe(null, () => {
              const sym = widget.activeChart().symbol();
              if (sym) onSymbolChange(sym);
            });
          } catch {}
        }
      });

      widgetRef.current = widget;
    };

    // Load the charting library script if not already loaded
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${LIBRARY_SCRIPT}"]`,
    );
    if (!existing) {
      const script = document.createElement("script");
      script.src = LIBRARY_SCRIPT;
      script.async = true;
      script.onload = initWidget;
      script.onerror = () => {
        console.error(
          "[AdvancedChart] Failed to load charting_library.js.\n" +
          "Extract charting_library.zip to frontend/public/charting_library/ and restart.",
        );
      };
      document.head.appendChild(script);
    } else if (window.TradingView?.widget) {
      initWidget();
    } else {
      existing.addEventListener("load", initWidget);
    }

    return () => {
      if (widgetRef.current) {
        try { widgetRef.current.remove(); } catch {}
        widgetRef.current = null;
      }
    };
    // Re-init only when theme changes. Symbol/interval changes are handled via widget API.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  // Update symbol via widget API when prop changes (no re-mount)
  useEffect(() => {
    if (!widgetRef.current || !symbol) return;
    try {
      widgetRef.current.onChartReady(() => {
        widgetRef.current?.activeChart()?.setSymbol(symbol, "1D", () => {});
      });
    } catch {}
  }, [symbol]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full"
      style={{ minHeight: 400 }}
    />
  );
}

export default AdvancedChart;
