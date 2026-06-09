import { useEffect, useRef, memo } from "react";

type Props = {
  symbol: string;     // e.g. "NASDAQ:AAPL" or "BINANCE:BTCUSDT"
  interval?: string;  // "1","5","15","60","240","D","W"
  theme?: "light" | "dark";
};

function TradingViewWidget({ symbol, interval = "D", theme = "dark" }: Props) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    container.current.innerHTML = "";

    const widgetDiv = document.createElement("div");
    widgetDiv.className = "tradingview-widget-container__widget";
    widgetDiv.style.height = "calc(100% - 32px)";
    widgetDiv.style.width = "100%";

    const copyright = document.createElement("div");
    copyright.className = "tradingview-widget-copyright";
    copyright.innerHTML =
      '<a href="https://www.tradingview.com/" rel="noopener nofollow" target="_blank">' +
      '<span style="color:#2962FF">Track all markets on TradingView</span></a>';

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.textContent = JSON.stringify({
      autosize: true,
      symbol,
      interval,
      timezone: "America/New_York",
      theme,
      style: "1",
      locale: "en",
      toolbar_bg: theme === "dark" ? "#0a0a0a" : "#F8F9FA",
      enable_publishing: false,
      allow_symbol_change: true,
      save_image: true,
      details: true,
      hotlist: true,
      calendar: true,
      studies: ["STD;SMA", "STD;Volume"],
      support_host: "https://www.tradingview.com",
    });

    container.current.appendChild(widgetDiv);
    container.current.appendChild(copyright);
    container.current.appendChild(script);
  }, [symbol, interval, theme]);

  return (
    <div
      ref={container}
      className="tradingview-widget-container"
      style={{ height: "100%", width: "100%" }}
    />
  );
}

export default memo(TradingViewWidget);
