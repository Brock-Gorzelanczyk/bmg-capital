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

        existing = db.query(BotProfile).filter(BotProfile.name == name).first()
        if existing:
            existing.description = description
            existing.asset_class = asset_class
            existing.config_json = config
            existing.enabled = True
            logger.debug("Updated BotProfile: %s", name)
        else:
            db.add(BotProfile(
                name=name,
                description=description,
                asset_class=asset_class,
                config_json=config,
                enabled=True,
            ))
            logger.info("Seeded BotProfile: %s", name)

    try:
        db.commit()
        logger.info("strategy_lab: bot profile seeds committed (%d profiles)", len(yaml_files))
    except Exception as exc:
        db.rollback()
        logger.error("Failed to commit bot profile seeds: %s", exc)
