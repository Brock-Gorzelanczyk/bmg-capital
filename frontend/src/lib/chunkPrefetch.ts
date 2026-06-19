/**
 * Hover-triggered chunk prefetch registry.
 * Each entry fires a dynamic import so the browser fetches the JS chunk
 * before the user clicks, eliminating the chunk-load delay on first visit.
 */
export const chunkPrefetch: Record<string, () => void> = {
  // Core routes (now lazy-loaded)
  "/":              () => { import("@/pages/Dashboard"); },
  "/dashboard":     () => { import("@/pages/Dashboard"); },
  "/chart":         () => { import("@/pages/ChartPage"); },
  "/screener":      () => { import("@/pages/Screener"); },
  // Strategy
  "/strategy":      () => { import("@/pages/StrategyLab"); },
  "/strategy/scout":     () => { import("@/pages/StrategyScoutPage"); },
  "/strategy/workshop":  () => { import("@/pages/StrategyWorkshopPage"); },
  "/strategy/forge":     () => { import("@/pages/ForgeBuilderPage"); },
  // Markets
  "/markets":       () => { import("@/pages/MarketsPage"); },
  "/news":          () => { import("@/pages/News"); },
  "/research":      () => { import("@/pages/Research"); },
  "/discovery":     () => { import("@/pages/Discovery"); },
  // Intel (admin)
  "/admin/smart-money": () => { import("@/pages/SmartMoneyPage"); },
  "/admin/flow":        () => { import("@/pages/OptionsFlowPage"); },
  "/admin/macro":       () => { import("@/pages/MacroDashboardPage"); },
  "/admin/candidates":  () => { import("@/pages/CandidatesPage"); },
  // Fund
  "/fund":          () => { import("@/pages/FundPage"); },
  "/research-feed": () => { import("@/pages/ResearchFeedPage"); },
  // Learn
  "/learn/tracks":  () => { import("@/pages/learn/LearnPage"); },
  "/learn/certificates": () => { import("@/pages/CertificatesPage"); },
  // Other
  "/portfolio":     () => { import("@/pages/Portfolio"); },
  "/watchlist":     () => { import("@/pages/WatchlistPage"); },
  "/options":       () => { import("@/pages/OptionsLab"); },
  "/crypto":        () => { import("@/pages/CryptoLab"); },
  "/journal":       () => { import("@/pages/JournalPage"); },
  "/analytics":     () => { import("@/pages/AnalyticsPage"); },
  "/morning-brief": () => { import("@/pages/MorningBriefPage"); },
  "/settings":      () => { import("@/pages/Settings"); },
  "/pods":          () => { import("@/pages/PodsPage"); },
  "/alerts":        () => { import("@/pages/Alerts"); },
  "/earnings":      () => { import("@/pages/Earnings"); },
  "/social":        () => { import("@/pages/Social"); },
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
  "/risk-console":   () => { import("@/pages/RiskConsolePage"); },
  "/activity":       () => { import("@/pages/ActivityPage"); },
};
