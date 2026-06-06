"""AlgorithmRunner — wires the 5 LEAN-style components together.

Usage:
    from strategy_lab.v2.profiles.crypto_lt import crypto_lt_definition
    from strategy_lab.v2.runner import AlgorithmRunner

    runner = AlgorithmRunner(crypto_lt_definition)
    result = await runner.run_iteration(ctx)

The runner is stateless — all state lives in the context and DB.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any

from .types import Symbol, Bar, Insight, PortfolioTarget, Order, RunResult
from .context import AlgorithmContext

logger = logging.getLogger(__name__)


@dataclass
class AlgorithmDefinition:
    """Configuration object that names and wires the 5 components.

    One AlgorithmDefinition per bot profile.  Shadow mode is on by
    default so no orders are submitted until explicitly disabled.
    """
    bot_id: str
    universe: Any    # UniverseSelectionModel
    alphas: list     # list[AlphaModel] — may be an ensemble
    portfolio: Any   # PortfolioConstructionModel
    risk: list       # list[RiskManagementModel] — applied in order
    execution: Any   # ExecutionModel
    shadow_mode: bool = True  # True: log only; False: live execute


class AlgorithmRunner:
    """Orchestrates one full iteration of the 5-stage pipeline.

    Iteration order:
      1. Universe Selection  → list[Symbol]
      2. Bar fetch            → dict[Symbol, list[Bar]]   (via context.cache)
      3. Alpha generation     → list[Insight]
      4. Portfolio targets    → list[PortfolioTarget]
      5. Risk filtering       → list[PortfolioTarget]  (each model applied in order)
      6. Execution            → list[Order]
      7. Audit emit
    """

    def __init__(self, definition: AlgorithmDefinition) -> None:
        self.definition = definition

    async def run_iteration(self, ctx: AlgorithmContext) -> RunResult:
        start_ms = time.monotonic_ns() // 1_000_000
        ts = datetime.now(timezone.utc)
        defn = self.definition
        mode_tag = "SHADOW" if defn.shadow_mode else "LIVE"
        ctx.log("info", f"=== [{mode_tag}] iteration start ===")

        try:
            # ── 1. Universe selection ──────────────────────────────────────────
            universe: list[Symbol] = await defn.universe.select_symbols(ctx)
            ctx.log("info", f"Universe: {len(universe)} symbols — {universe[:5]}{'…' if len(universe) > 5 else ''}")
            if not universe:
                return self._empty_result(defn.bot_id, ts, start_ms, "universe empty")

            # ── 2. Fetch bars for universe (populates ctx.cache) ───────────────
            await self._fetch_bars(ctx, universe)

            # ── 3. Alpha generation ────────────────────────────────────────────
            all_insights: list[Insight] = []
            for alpha in defn.alphas:
                bars_map = {sym: ctx.cache.get_bars(sym) for sym in universe}
                insights = await alpha.generate_insights(ctx, universe, bars_map)
                ctx.log("info", f"Alpha [{alpha.name}]: {len(insights)} insights")
                all_insights.extend(insights)

            if not all_insights:
                ctx.log("info", "No insights generated — no action this cycle")
                return RunResult(
                    bot_id=defn.bot_id, ts=ts, universe_size=len(universe),
                    insights=[], targets=[], orders=[], shadow_mode=defn.shadow_mode,
                    duration_ms=self._elapsed(start_ms),
                )

            # ── 4. Portfolio construction ──────────────────────────────────────
            positions = await ctx.broker.get_positions()
            portfolio_value = await ctx.broker.get_portfolio_value()
            targets: list[PortfolioTarget] = await defn.portfolio.create_targets(
                ctx, all_insights, positions, portfolio_value
            )
            ctx.log("info", f"Portfolio targets: {len(targets)}")

            # ── 5. Risk filtering ─────────────────────────────────────────────
            for risk_model in defn.risk:
                pre = len(targets)
                targets = await risk_model.manage_risk(ctx, targets, positions, portfolio_value)
                post = len(targets)
                ctx.log("info", f"Risk [{risk_model.name}]: {pre} → {post} targets")

            if not targets:
                ctx.log("info", "All targets vetoed by risk models — no orders")
                return RunResult(
                    bot_id=defn.bot_id, ts=ts, universe_size=len(universe),
                    insights=all_insights, targets=[], orders=[],
                    shadow_mode=defn.shadow_mode,
                    duration_ms=self._elapsed(start_ms),
                )

            # ── 6. Execution ───────────────────────────────────────────────────
            if defn.shadow_mode:
                orders = self._shadow_execute(ctx, targets)
            else:
                orders = await defn.execution.execute(ctx, targets, positions)
            ctx.log("info", f"{'[SHADOW] Would submit' if defn.shadow_mode else 'Submitted'} {len(orders)} orders")

            # ── 7. Audit emit ──────────────────────────────────────────────────
            ctx.emit("iteration_complete", {
                "universe_size": len(universe),
                "insights_generated": len(all_insights),
                "targets_final": len(targets),
                "orders_submitted": len(orders),
                "shadow_mode": defn.shadow_mode,
            })

            return RunResult(
                bot_id=defn.bot_id, ts=ts,
                universe_size=len(universe),
                insights=all_insights,
                targets=targets,
                orders=orders,
                shadow_mode=defn.shadow_mode,
                duration_ms=self._elapsed(start_ms),
            )

        except Exception as exc:
            ctx.log("error", f"run_iteration failed: {exc}")
            return RunResult(
                bot_id=defn.bot_id, ts=ts, universe_size=0,
                insights=[], targets=[], orders=[],
                shadow_mode=defn.shadow_mode,
                duration_ms=self._elapsed(start_ms),
                error=str(exc),
            )

    async def _fetch_bars(self, ctx: AlgorithmContext, universe: list[Symbol]) -> None:
        """Populate ctx.cache with price data for each symbol in the universe.

        Currently fetches last-known prices via the crypto quote endpoint.
        Replace with a full bar-fetch once the data-feed is wired.
        """
        try:
            from app.services import coingecko as cg
            # Map our symbol format (BTC/USD) → CoinGecko format (btc-usd style)
            coin_data = cg.get_top_coins()  # cached, so no rate-limit risk
            price_by_symbol: dict[str, float] = {}
            for coin in coin_data:
                # CoinGecko symbol is uppercase, e.g. "BTC"
                cg_sym = coin.get("symbol", "").upper()
                # Match "BTC/USD" → "BTC"
                price = coin.get("current_price")
                if cg_sym and price:
                    price_by_symbol[f"{cg_sym}/USD"] = float(price)
                    price_by_symbol[cg_sym] = float(price)

            for sym in universe:
                price = price_by_symbol.get(sym)
                if price:
                    ctx.cache.set_price(sym, price)
                    ctx.log("debug", f"Bar cache: {sym} @ ${price:,.2f}")
                else:
                    ctx.log("debug", f"Bar cache: {sym} price not found in CoinGecko top100")
        except Exception as exc:
            ctx.log("warning", f"_fetch_bars failed: {exc} — prices will be missing")

    def _shadow_execute(self, ctx: AlgorithmContext, targets: list[PortfolioTarget]) -> list[Order]:
        """In shadow mode, convert targets to Order objects but don't submit."""
        from .types import Order
        orders = []
        for t in targets:
            if abs(t.target_qty) < 1e-8:
                continue
            side = "buy" if t.target_qty > 0 else "sell"
            price = ctx.cache.get_price(t.symbol)
            orders.append(Order(
                symbol=t.symbol,
                side=side,
                qty=abs(t.target_qty),
                order_type="market",
                time_in_force="gtc",
                tag=f"v2:{self.definition.bot_id}:shadow",
                estimated_fill_usd=abs(t.target_qty) * price if price else None,
            ))
        return orders

    def _empty_result(self, bot_id: str, ts: datetime, start_ms: int, reason: str) -> RunResult:
        logger.info("[v2:%s] early exit: %s", bot_id, reason)
        return RunResult(
            bot_id=bot_id, ts=ts, universe_size=0,
            insights=[], targets=[], orders=[],
            shadow_mode=self.definition.shadow_mode,
            duration_ms=self._elapsed(start_ms),
            metadata={"skip_reason": reason},
        )

    @staticmethod
    def _elapsed(start_ms: int) -> int:
        return time.monotonic_ns() // 1_000_000 - start_ms
