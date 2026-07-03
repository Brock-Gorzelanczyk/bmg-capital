"""Seed bot profiles from YAML files.

Runs at every startup.  Upserts based on the 'name' field — safe to re-run.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_PROFILES_DIR = Path(__file__).parent / "profiles"

_PROFILE_DESCRIPTIONS = {
    "stock_swing": "Multi-day swing trades on Russell 1000 stocks using momentum, mean reversion, and RSI signals. Holds 1–30 days.",
    "stock_day": "Intraday US equity trades using opening range breakout and VWAP reversion. Flat by market close.",
    "stock_lt": "Monthly long-term factor-blend allocations across Russell 1000. 30–365 day holds. No hard stops.",
    "crypto_swing": "4-hour cadence crypto swing trades on top 20 coins. Wide stops and targets for high-volatility assets.",
    "crypto_day": "Minute-by-minute crypto scalping using VWAP reversion and momentum. 24/7 operation.",
    "crypto_lt": "Weekly DCA accumulation into top 10 crypto assets. Long-term conviction approach, no stops.",
    "options_income": "Wheel strategy, covered calls, cash-secured puts, iron condors — premium collection on high-IV stocks.",
    "options_directional": "Credit spreads, debit spreads, LEAPS — directional options plays on momentum stocks.",
    "crypto_quant_aggressive": "8-strategy high-turnover quant on 20 coins. 5m bars, VWAP fade, BB breakout, momentum, volume z-score, range break, orderflow imbalance, funding arb, Donchian. $40k.",
    "crypto_onchain": "On-chain flow analysis — large wallet movements, DEX volume anomalies, L2 bridge activity on top 20 chains.",
    "crypto_quant_scalper": "5-strategy 1m scalper on liquid majors. Micro breakout, OB imbalance, tape acceleration, VWAP band reject, volume spike continuation. $30k.",
    "crypto_quant_mean_reversion": "6-strategy mean reversion on 10 mid-cap coins. BB extreme fade, RSI oversold bounce, RSI overbought short, z-score reversion, Keltner fade, pin bar rejection. $30k.",
    "tsmom_multi_asset": "Multi-asset time-series momentum across 12 ETFs + crypto. 252d signal, weekly rebalance, inverse-vol sizing. Moskowitz, Ooi & Pedersen (2012). ~0.7 expected Sharpe after 30% haircut.",
    "quality_factor": "Long-only quality factor (GP/A + ROE + low leverage proxy). Top quintile S&P 500, quarterly rebalance, max 25 names. Novy-Marx (2013). ~0.5 expected Sharpe.",
    "value_quality": "Cheap-and-good combo (value z + quality z). AQR QMJ-style. Top decile, 20 names, quarterly. ~0.9 expected Sharpe after 30% haircut.",
    "crypto_meanrev_2163": "21-63 day crypto mean reversion on top-20 coins. 30d z-score entry, falling-knife filter, 5-day time stop. Complements intraday MR bots at weekly horizon.",
    "earnings_nlp": "BLOCKED: earnings call tone delta (LM sentiment). Long top-decile tone improvement, hold 1-3 days. Needs transcript API feed.",
    "crypto_quant_alt_focus": "Alt-focused variant of Quant Aggressive. 8-strategy stack on Tier B/C/D coins (AVAX/DOT/LINK/ARB/OP/SUI/DOGE etc). 5m bars, tighter position sizing than aggressive. $40k, funded from halted mean-reversion.",
    "crypto_quant_scalp_1m": "1-minute scalper on BTC/ETH/SOL/BNB/XRP. 4 quant strategies, 2min cadence, 30min max hold, 0.4% stops, 0.8% targets. $30k, funded from halted scalper.",
    "crypto_dca_btc_eth": "Weekly DCA into BTC + ETH. No strategy alpha claimed — 'stayed-invested' baseline for benchmarking discretionary bots. $30k, weekly Monday 10 UTC.",
    "crypto_quant_universe_top6": "Concentrated liquidity variant of Aggressive. Same 8-strategy stack, universe scoped to BTC/ETH/SOL/BNB/XRP/ADA only. 5m cadence. $20k.",
    "crypto_quant_defi_l2": "DeFi + L2 basket (ARB/OP/INJ/SUI/APT/LINK/NEAR/DOT). Full 8-strategy stack. Alpha comes from universe diversification vs Aggressive. 5m. $20k.",
    "crypto_quant_meme_tier": "Meme/high-beta tier (DOGE/SHIB/PEPE/AVAX/POL). 8-strategy stack, wider stops (3%), smaller size (1.5%). Bounded meme exposure. $20k.",
    "crypto_quant_10m": "10-minute timeframe variant of Aggressive. Same 8-strategy stack, full 20-coin universe. Tests whether 5m edge holds at 10m. $20k.",
    "crypto_quant_15m": "15-minute timeframe variant of Aggressive. Same stack, longer holds (up to 24h). Tests scaling of Aggressive's edge with holding period. $20k.",
    "stock_quant_day_momentum": "Intraday momentum day-trader on 19 mega-cap tech + momentum leaders. 5m cadence 9-15 ET. Pure momentum + breakout family. $15k.",
    "stock_quant_day_meanrev": "Intraday mean-reversion day-trader on 20 liquid large-caps. Wider mix — mean_reversion / rsi / vwap / camarilla / bollinger / gex_pin. $15k.",
    "stock_quant_swing_growth": "Growth + momentum swing on 24 tech / AI infra names. Daily bars, 3:30 PM ET fire, up to 21-day hold. $15k.",
    "stock_quant_swing_value": "Value / dividend / defensive swing on 30 quality names. Factor + factor_blend + momentum_12_1 mix. 4 PM ET fire, up to 45-day hold. $15k.",
    "stock_gap_fade": "Opening gap fade (day trader). Fades >2% opening gaps on 30 large-caps. Entry 9:35-10 ET, EOD flat. $20k.",
    "stock_orb_breakout": "Opening Range Breakout (day trader). Buys break of 9:30-10 AM high with volume confirm on top-100 Russell names. EOD flat. $20k.",
    "stock_momentum_breakout": "Momentum breakout swing trader. Close above 20-day high + volume 1.5x + RSI>60. 5-15 day hold. $20k.",
    "stock_pead": "Post-Earnings Announcement Drift. T+1 entry on earnings beats >5%, 30-45 day hold, -8% hard stop. $20k.",
}


def load_profile(profile_name: str) -> dict:
    """Load a single bot profile YAML by name.

    Returns the parsed config dict, or an empty dict if not found.
    """
    yaml_path = _PROFILES_DIR / f"{profile_name}.yaml"
    if not yaml_path.exists():
        # Try iterating all profiles to find by 'name' field
        for p in sorted(_PROFILES_DIR.glob("*.yaml")):
            try:
                with p.open("r") as fh:
                    config = yaml.safe_load(fh)
                if config and config.get("name") == profile_name:
                    return config
            except Exception:
                continue
        logger.warning("load_profile: profile '%s' not found in %s", profile_name, _PROFILES_DIR)
        return {}
    try:
        with yaml_path.open("r") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.error("load_profile: failed to load %s: %s", yaml_path.name, exc)
        return {}


def seed_bot_profiles(db: Session) -> None:
    """Upsert all six BotProfile rows from the profiles/ YAML directory."""
    from app.db.models.bots import BotProfile

    yaml_files = sorted(_PROFILES_DIR.glob("*.yaml"))
    if not yaml_files:
        logger.warning("strategy_lab: no profile YAML files found in %s", _PROFILES_DIR)
        return

    for yaml_path in yaml_files:
        try:
            with yaml_path.open("r") as fh:
                config = yaml.safe_load(fh)
        except Exception as exc:
            logger.error("Failed to load profile %s: %s", yaml_path.name, exc)
            continue

        name = config.get("name")
        if not name:
            logger.warning("Skipping %s — no 'name' field", yaml_path.name)
            continue

        asset_class = config.get("asset_class", "stock")
        description = _PROFILE_DESCRIPTIONS.get(name, f"{name} trading bot profile")

        # Respect the YAML enabled flag; default True if absent (existing bots have no field)
        yaml_enabled = bool(config.get("enabled", True))

        existing = db.query(BotProfile).filter(BotProfile.name == name).first()
        if existing:
            existing.description = description
            existing.asset_class = asset_class
            existing.config_json = config
            existing.enabled = yaml_enabled
            logger.debug("Updated BotProfile: %s (enabled=%s)", name, yaml_enabled)
        else:
            db.add(BotProfile(
                name=name,
                description=description,
                asset_class=asset_class,
                config_json=config,
                enabled=yaml_enabled,
            ))
            logger.info("Seeded BotProfile: %s (enabled=%s)", name, yaml_enabled)

    try:
        db.commit()
        logger.info("strategy_lab: bot profile seeds committed (%d profiles)", len(yaml_files))
    except Exception as exc:
        db.rollback()
        logger.error("Failed to commit bot profile seeds: %s", exc)
