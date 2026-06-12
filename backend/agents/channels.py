"""
Channel name constants for the BMG Capital agent message bus.

All inter-agent communication goes through agent_messages rows with one
of these channel strings. Consumers filter by channel + (optionally) to_agent.
"""

# Queen broadcast channels (Queen → all agents)
QUEEN_MORNING      = "queen.morning"       # morning brief payload
QUEEN_MIDDAY       = "queen.midday"        # midday pulse payload
QUEEN_CLOSE        = "queen.close"         # EOD report payload
QUEEN_EVENING      = "queen.evening"       # evening crypto watch payload
QUEEN_WEEKEND      = "queen.weekend"       # weekend recap payload
QUEEN_WEEKLY       = "queen.weekly"        # Sunday weekly digest payload
QUEEN_REGIME_ALERT = "queen.regime_alert"  # event-driven regime change

# Researcher → Queen
RESEARCHER_FINDINGS = "researcher.findings"  # daily research output dict

# Risk Sentinel → Queen / ops
SENTINEL_HEALTH    = "sentinel.health"      # fleet health snapshot
SENTINEL_BREACH    = "sentinel.breach"      # drawdown / VaR breach

# Data Quality Watcher
DQ_ALERT           = "dq.alert"            # stale/missing data alert

# Execution Auditor
EXEC_AUDIT         = "exec.audit"          # fill quality + slippage report

# Macro Strategist
MACRO_UPDATE       = "macro.update"        # macro regime / FedWatch update

# Quant Research
QUANT_CANDIDATE    = "quant.candidate"     # new WFA candidate promoted

# Operations / Back Office
OPS_REPORT         = "ops.report"          # daily ops / reconciliation digest

# System
SYSTEM_HEARTBEAT   = "system.heartbeat"    # periodic ping from each agent
