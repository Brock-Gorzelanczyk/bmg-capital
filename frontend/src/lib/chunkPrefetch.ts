/**
 * Hover-triggered chunk prefetch registry.
 * Each entry fires a dynamic import so the browser fetches the JS chunk
 * before the user clicks, eliminating the chunk-load delay on first visit.
 */
export const chunkPrefetch: Record<string, () => void> = {
  "/strategy":      () => { import("@/pages/StrategyLab"); },
  "/portfolio":     () => { import("@/pages/Portfolio"); },
  // /screener and /chart are statically imported in App.tsx — no chunk to prefetch
  "/watchlist":     () => { import("@/pages/WatchlistPage"); },
  "/news":          () => { import("@/pages/News"); },
  "/options":       () => { import("@/pages/OptionsLab"); },
  "/crypto":        () => { import("@/pages/CryptoLab"); },
  "/paper":         () => { import("@/pages/PaperTrading"); },
  "/journal":       () => { import("@/pages/JournalPage"); },
  "/analytics":     () => { import("@/pages/AnalyticsPage"); },
  "/morning-brief": () => { import("@/pages/MorningBriefPage"); },
  "/learn":         () => { import("@/pages/LearnHome"); },
  "/settings":      () => { import("@/pages/Settings"); },
  "/pods":          () => { import("@/pages/PodsPage"); },
  "/workshop":      () => { import("@/pages/WorkshopPage"); },
  "/alerts":        () => { import("@/pages/Alerts"); },
  "/earnings":      () => { import("@/pages/Earnings"); },
  "/research":      () => { import("@/pages/Research"); },
  "/social":        () => { import("@/pages/Social"); },
  "/discovery":     () => { import("@/pages/Discovery"); },
  "/defi":          () => { import("@/pages/DeFi"); },
  "/tax-xray":      () => { import("@/pages/TaxXRayPage"); },
  "/risk-parity":   () => { import("@/pages/RiskParityPage"); },
  "/smart-transfers":() => { import("@/pages/SmartTransfersPage"); },
  "/rsu-console":   () => { import("@/pages/RSUConsolePage"); },
  "/estate":        () => { import("@/pages/EstatePage"); },
  "/rules":         () => { import("@/pages/RulesPage"); },
  "/net-worth":     () => { import("@/pages/NetWorthPage"); },
  "/autopilot":     () => { import("@/pages/AutopilotPage"); },
  "/mission-control":() => { import("@/pages/MissionControlPage"); },
};
