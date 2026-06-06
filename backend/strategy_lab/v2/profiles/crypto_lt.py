"""crypto_lt — LEAN v2 definition for the Crypto Long-Term DCA bot.

Component wiring:
  Universe  : StaticListUniverse (5 blue-chip coins, fixed)
  Alpha     : DcaWeekly         (always buy, no timing)
  Portfolio : TargetWeightPortfolio (BTC=40%, ETH=30%, SOL=15%, AVAX=10%, LINK=5%)
  Risk      : DrawdownCircuit(25%) → no new buys if peak drawdown >25%
  Execution : MarketImmediateExecution (via PaperBrokerAdapter, shadow mode)

Running in shadow_mode=True until 7 consecutive days of output match the
v1 runner.  Flip shadow_mode=False to go live.
"""
from __future__ import annotations

from ..runner import AlgorithmDefinition
from ..universe.static_list import StaticListUniverse
from ..alphas.dca_weekly import DcaWeekly
from ..portfolio.target_weight import TargetWeightPortfolio
from ..risk.drawdown_circuit import DrawdownCircuit
from ..execution.market_immediate import MarketImmediateExecution

# Target weights match the YAML profile
_TARGET_WEIGHTS = {
    "BTC/USD":  0.40,
    "ETH/USD":  0.30,
    "SOL/USD":  0.15,
    "AVAX/USD": 0.10,
    "LINK/USD": 0.05,
}

crypto_lt_definition = AlgorithmDefinition(
    bot_id="crypto_lt",

    universe=StaticListUniverse(list(_TARGET_WEIGHTS.keys())),

    alphas=[
        DcaWeekly(period="30d"),
    ],

    portfolio=TargetWeightPortfolio(
        target_weights=_TARGET_WEIGHTS,
        weekly_dca_pct=1.0,     # deploy full deficit each cycle
        min_order_usd=5.0,      # crypto allows fractional, so low floor
    ),

    risk=[
        DrawdownCircuit(pct=0.25),   # halt entries at 25% drawdown from HWM
    ],

    execution=MarketImmediateExecution(time_in_force="gtc"),

    shadow_mode=True,  # SHADOW — outputs logged, no orders submitted
)
