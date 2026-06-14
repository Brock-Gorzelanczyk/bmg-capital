export type DeployPhase = 1 | 2 | 3 | 4 | 5 | 6 | 7;
export type AgentStatus = "active" | "degraded" | "not_built" | "offline";
export type OrgTier = "A" | "B" | "C" | "Mixed";

export interface FundRole {
  id: string;
  title: string;
  agentName: string;
  isHuman?: boolean;
  tier: OrgTier;
  status: AgentStatus;
  expectedDeployPhase?: DeployPhase;
  description: string;
  authority: {
    tierA: string[];
    tierB: string[];
    tierC: string[];
  };
  reportsTo: string;
  inputsFrom: string[];
  outputsTo: string[];
  discordChannels: { name: string; purpose: string }[];
}

export const FUND_ROLES: FundRole[] = [
  {
    id: "cio",
    title: "CHIEF INVESTMENT OFFICER",
    agentName: "Brock",
    isHuman: true,
    tier: "Mixed",
    status: "active",
    description:
      "Final authority on all capital allocation and strategy decisions. Sets the overall investment mandate, approves Tier B proposals, and holds override power on any automated action. The only seat that can authorize live trading or capital movements.",
    authority: {
      tierA: ["Read any agent output", "Observe all bus channels"],
      tierB: ["Approve or veto any Tier B proposal from any agent"],
      tierC: ["Live trading authorization", "Capital withdrawals", "New account openings", "Strategy mandate changes"],
    },
    reportsTo: "N/A",
    inputsFrom: [
      "Portfolio Manager (Queen) — daily briefs and proposals",
      "Chief Risk Officer (Risk Sentinel) — risk reports and veto actions",
      "All agents — escalation paths",
    ],
    outputsTo: [
      "#queen-proposals — approval reactions (✅/❌/🕐)",
      "#bmg-sentinel-ops — oversight",
    ],
    discordChannels: [
      { name: "#queen-proposals", purpose: "Reviews and approves Tier B proposals" },
      { name: "#bmg-sentinel-ops", purpose: "Observes fleet health" },
    ],
  },
  {
    id: "portfolio_manager",
    title: "PORTFOLIO MANAGER",
    agentName: "Queen",
    tier: "Mixed",
    status: "active",
    description:
      "Hierarchical coordinator for the entire BMG Capital strategy system. Runs 6 scheduled sessions daily — morning brief, midday pulse, EOD report, evening watch, weekend crypto recap, and Sunday weekly digest. Aggregates output from all sub-agents and publishes to Discord.",
    authority: {
      tierA: [
        "Morning/midday/EOD/evening/weekly briefings",
        "IC and regime data collection",
        "P&L snapshot aggregation",
        "Regime alert detection and posting",
      ],
      tierB: [
        "Allocation weight increase/decrease proposals",
        "Strategy promotion to live pipeline",
        "Risk threshold adjustment recommendations",
      ],
      tierC: [
        "Live trade execution",
        "Capital withdrawals",
        "New strategy deployments without CIO approval",
      ],
    },
    reportsTo: "CIO (Brock)",
    inputsFrom: [
      "Researcher — daily findings via bus",
      "Strategy Monitor — fleet health and P&L",
      "Risk Sentinel — veto signals (Deploy 2)",
    ],
    outputsTo: [
      "#bmg-dev-log — all 6 session embeds",
      "#queen-proposals — Tier B proposals (Deploy 4)",
      "agent_messages bus — session summaries",
    ],
    discordChannels: [
      { name: "#bmg-dev-log", purpose: "All 6 daily session embeds" },
      { name: "#queen-proposals", purpose: "Tier B proposal posts (Deploy 4)" },
    ],
  },
  {
    id: "chief_risk_officer",
    title: "CHIEF RISK OFFICER",
    agentName: "Risk Sentinel",
    tier: "Mixed",
    status: "offline",
    description:
      "Autonomous Tier A risk watchdog that monitors drawdown, VaR, and position concentration across all bots. Holds veto power over Portfolio Manager — can halt the fleet or block a proposal without CIO approval. Escalates critical breaches to Discord immediately.",
    authority: {
      tierA: [
        "Continuous drawdown monitoring",
        "VaR and position concentration checks",
        "Daily risk metric generation",
        "Fleet health status classification",
      ],
      tierB: [
        "Fleet-wide pause and unpause",
        "Risk threshold tightening",
        "Veto on Queen allocation proposals that exceed risk limits",
      ],
      tierC: [
        "Forced position closure without CIO approval",
        "Capital removal from accounts",
      ],
    },
    reportsTo: "CIO (Brock)",
    inputsFrom: [
      "Strategy Monitor — bot health, P&L, signals",
      "Data Quality Watcher — data feed integrity",
      "Execution Auditor — fill quality alerts",
    ],
    outputsTo: [
      "#bmg-sentinel-ops — risk alerts",
      "agent_messages bus — SENTINEL_BREACH, SENTINEL_HEALTH channels",
      "Queen — veto signals",
    ],
    discordChannels: [
      { name: "#bmg-sentinel-ops", purpose: "Risk alerts and fleet health" },
    ],
  },
  {
    id: "equity_researcher",
    title: "EQUITY RESEARCHER",
    agentName: "Researcher",
    tier: "A",
    status: "active",
    description:
      "Daily market research and strategy analysis engine. Detects market regime from DB snapshots, computes rolling 63-day Information Coefficient (IC) per bot, scores WFA pipeline candidates, and produces actionable research directives for the Portfolio Manager each morning.",
    authority: {
      tierA: [
        "IC calculation across 13 active bots",
        "Regime classification from VIX/trend/BTC dominance data",
        "WFA candidate scoring and ranking",
        "Research directive generation",
      ],
      tierB: [
        "Candidate promotion recommendations to Queen",
      ],
      tierC: [],
    },
    reportsTo: "Portfolio Manager (Queen)",
    inputsFrom: [
      "RegimeSnapshot DB table — VIX, trend, BTC dominance",
      "BotTrade records — realized P&L for IC calculations",
      "strategy_wfa_results — WFA pipeline candidates",
    ],
    outputsTo: [
      "agent_messages bus — RESEARCHER_FINDINGS channel",
      "Queen — daily research dict (regime, IC, candidates, directives)",
    ],
    discordChannels: [],
  },
  {
    id: "quant_researcher",
    title: "QUANT RESEARCHER",
    agentName: "Quant Research",
    tier: "Mixed",
    status: "not_built",
    expectedDeployPhase: 6,
    description:
      "Specialized agent for systematic strategy research. Runs backtests, Walk Forward Analysis, and parameter optimization on strategy candidates. Maintains the researcher memory store and surfaces new alpha signals for the PM to review.",
    authority: {
      tierA: [
        "Backtesting and WFA job submission",
        "Parameter grid search and optimization",
        "Sharpe, PBO, DSR scoring of candidates",
        "Researcher memory store read/write",
      ],
      tierB: [
        "Promotion of candidates from pipeline to live",
      ],
      tierC: [],
    },
    reportsTo: "Portfolio Manager (Queen)",
    inputsFrom: [
      "Candidates pipeline DB",
      "Historical price and signal data",
      "Researcher memory store",
    ],
    outputsTo: [
      "agent_messages bus — QUANT_CANDIDATE channel",
      "Queen — candidate promotion proposals",
    ],
    discordChannels: [],
  },
  {
    id: "macro_strategist",
    title: "MACRO STRATEGIST",
    agentName: "Macro Strategist",
    tier: "Mixed",
    status: "not_built",
    expectedDeployPhase: 6,
    description:
      "Monitors macro regime indicators including FedWatch probabilities, yield curve shape, credit spreads, and global risk sentiment. Generates regime-based allocation proposals and flags macro tail risks to the CRO. Updates the regime snapshot used by the Researcher.",
    authority: {
      tierA: [
        "FedWatch and rate probability pulls",
        "Yield curve and credit spread monitoring",
        "Regime classification updates",
        "Macro event calendar ingestion",
      ],
      tierB: [
        "Regime-based sleeve allocation proposals",
        "Risk-off mode activation recommendations",
      ],
      tierC: [],
    },
    reportsTo: "Portfolio Manager (Queen)",
    inputsFrom: [
      "External macro APIs (FRED, CME FedWatch)",
      "RegimeSnapshot table",
      "News and economic calendar feeds",
    ],
    outputsTo: [
      "agent_messages bus — MACRO_UPDATE channel",
      "Queen — macro directives",
      "Risk Sentinel — tail risk alerts",
    ],
    discordChannels: [],
  },
  {
    id: "data_quality_watcher",
    title: "DATA QUALITY WATCHER",
    agentName: "Data Quality Watcher",
    tier: "A",
    status: "offline",
    description:
      "Autonomous Tier A sentinel that monitors data feed freshness, validates price data integrity, and detects missing or anomalous inputs before they can corrupt bot signals. Raises DQ alerts to the Risk Sentinel when data is stale or malformed.",
    authority: {
      tierA: [
        "Price and volume data freshness checks",
        "Feed validation against expected schemas",
        "Anomalous data pattern detection",
        "DQ alert generation",
      ],
      tierB: [],
      tierC: [],
    },
    reportsTo: "Chief Risk Officer (Risk Sentinel)",
    inputsFrom: [
      "Market data feeds",
      "Bot signal tables",
      "RegimeSnapshot ingestion pipelines",
    ],
    outputsTo: [
      "agent_messages bus — DQ_ALERT channel",
      "Risk Sentinel — data quality alerts",
    ],
    discordChannels: [
      { name: "#bmg-sentinel-ops", purpose: "Data quality alerts" },
    ],
  },
  {
    id: "execution_auditor",
    title: "EXECUTION AUDITOR",
    agentName: "Execution Auditor",
    tier: "A",
    status: "offline",
    description:
      "Tracks fill quality, slippage, and execution drift across all bot trades. Compares expected vs. actual fills, flags outlier slippage, and generates daily execution quality reports. Alerts the CRO when execution degrades beyond acceptable bounds.",
    authority: {
      tierA: [
        "Fill quality analysis against expected prices",
        "Slippage bps calculation per bot",
        "Execution drift trend detection",
        "Daily execution metrics report",
      ],
      tierB: [],
      tierC: [],
    },
    reportsTo: "Chief Risk Officer (Risk Sentinel)",
    inputsFrom: [
      "BotTrade records — fill prices and expected prices",
      "BotSignal records — entry/exit targets",
    ],
    outputsTo: [
      "agent_messages bus — EXEC_AUDIT channel",
      "Risk Sentinel — execution quality alerts",
    ],
    discordChannels: [
      { name: "#bmg-sentinel-ops", purpose: "Execution quality alerts" },
    ],
  },
  {
    id: "operations",
    title: "OPERATIONS / BACK OFFICE",
    agentName: "Operations",
    tier: "A",
    status: "offline",
    description:
      "Daily reconciliation, fee attribution, and P&L reporting across all sleeves. Produces end-of-period operational summaries, verifies that account balances match strategy allocations, and maintains the audit trail for all automated actions.",
    authority: {
      tierA: [
        "Daily P&L attribution by sleeve and bot",
        "Fee and cost tracking",
        "Allocation-to-account reconciliation",
        "Operational digest generation",
      ],
      tierB: [
        "End-of-period summary reports to CIO",
      ],
      tierC: [
        "Capital movements",
        "External audit responses",
      ],
    },
    reportsTo: "Portfolio Manager (Queen)",
    inputsFrom: [
      "BotTrade and BotDailyPnl records",
      "BotAllocation and StrategyPortfolio tables",
      "Alpaca account data",
    ],
    outputsTo: [
      "agent_messages bus — OPS_REPORT channel",
      "Queen — operational digest",
    ],
    discordChannels: [],
  },
  {
    id: "sentinel_devops",
    title: "SENTINEL DEVOPS",
    agentName: "Sentinel DevOps",
    tier: "A",
    status: "active",
    description:
      "Infrastructure and agent health monitoring. Tracks error rates, memory pressure, scheduler health, and agent uptime across the entire fleet. Escalates critical failures to Discord and maintains the circuit breaker state for automated fixes.",
    authority: {
      tierA: [
        "Agent error rate and uptime monitoring",
        "Scheduler health checks",
        "Circuit breaker state management",
        "Error fingerprinting and deduplication",
      ],
      tierB: [
        "Critical failure escalation to Discord",
        "Automated fix proposals (small scope)",
      ],
      tierC: [
        "Code changes and deployments",
        "Infrastructure modifications",
      ],
    },
    reportsTo: "Chief Risk Officer (Risk Sentinel)",
    inputsFrom: [
      "agent_events and agent_fixes tables",
      "Application error logs",
      "Agent heartbeat signals",
    ],
    outputsTo: [
      "#bmg-sentinel-ops — critical alerts and escalations",
      "agent_messages bus — SYSTEM_HEARTBEAT channel",
    ],
    discordChannels: [
      { name: "#bmg-sentinel-ops", purpose: "Critical infrastructure alerts" },
    ],
  },
];

export const ROLE_BY_ID = Object.fromEntries(FUND_ROLES.map((r) => [r.id, r]));
