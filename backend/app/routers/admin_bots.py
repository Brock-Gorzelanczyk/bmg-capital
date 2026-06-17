"""Admin bot configuration endpoints — runtime knobs without a redeploy.

All endpoints require the caller's email to be the founder account.
Overrides are written to bot_config_overrides; audit trail goes to bot_config_audit.
YAML profiles remain the source-of-truth defaults.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-bots"])

_ADMIN_EMAIL = "32bgorzelanczyk@gmail.com"

_BOT_IDS = [
    "crypto_quant_scalper",
    "crypto_quant_aggressive",
    "crypto_quant_mean_reversion",
    "crypto_meanrev_2163",
    "crypto_day",
    "crypto_swing",
    "crypto_lt",
    "crypto_onchain",
    "stock_day",
    "stock_swing",
    "stock_lt",
    "options_directional",
    "options_income",
]

_BOT_CATEGORIES = {
    "crypto_quant_scalper": "quant",
    "crypto_quant_aggressive": "quant",
    "crypto_quant_mean_reversion": "quant",
    "crypto_meanrev_2163": "quant",
    "crypto_day": "crypto",
    "crypto_swing": "crypto",
    "crypto_lt": "crypto",
    "crypto_onchain": "crypto",
    "stock_day": "stocks",
    "stock_swing": "stocks",
    "stock_lt": "stocks",
    "options_directional": "stocks",
    "options_income": "stocks",
}

# ── Auth ──────────────────────────────────────────────────────────────────────


def require_bot_admin(user: User = Depends(get_current_user)) -> User:
    if user.email != _ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# ── Validation ────────────────────────────────────────────────────────────────

_CRYPTO_SYMBOL_RE = re.compile(r"^[A-Z]{2,10}/(USD|USDT|USDC)$")
_EQUITY_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")

_KEY_VALIDATORS: dict[str, Any] = {
    "risk.deployment_target_pct":   ("float", 0.0, 1.0),
    "risk.target_position_count":   ("int", 1, 100),
    "risk.max_position_pct":        ("float", 0.0, 1.0),
    "risk.max_total_deployed_pct":  ("float", 0.0, 1.0),
    "confidence_threshold":         ("float", 0.0, 1.0),
    "cooldown_minutes":             ("int", 0, 1440),
    "enabled":                      ("bool",),
    "paused":                       ("bool",),
}


def _validate_value(key: str, value: Any) -> Any:
    """Validate and coerce a config value; raise HTTPException on bad input."""
    # per-strategy confidence: strategy.{name}.confidence_threshold
    if key.startswith("strategy.") and key.endswith(".confidence_threshold"):
        spec = ("float", 0.0, 1.0)
    else:
        spec = _KEY_VALIDATORS.get(key)

    if spec is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown config key '{key}'. Allowed: {list(_KEY_VALIDATORS)}",
        )

    kind = spec[0]
    if kind == "bool":
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=422, detail=f"'{key}' must be a boolean"
            )
        return value
    elif kind == "float":
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail=f"'{key}' must be a number"
            )
        lo, hi = spec[1], spec[2]
        if not (lo <= v <= hi):
            raise HTTPException(
                status_code=422,
                detail=f"'{key}' must be between {lo} and {hi}, got {v}",
            )
        return v
    elif kind == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail=f"'{key}' must be an integer"
            )
        lo, hi = spec[1], spec[2]
        if not (lo <= v <= hi):
            raise HTTPException(
                status_code=422,
                detail=f"'{key}' must be between {lo} and {hi}, got {v}",
            )
        return v
    return value


def _validate_symbol(symbol: str, bot_id: str) -> str:
    s = symbol.strip().upper()
    cat = _BOT_CATEGORIES.get(bot_id, "")
    if cat == "stocks":
        if not _EQUITY_SYMBOL_RE.match(s):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid equity symbol '{s}'. Expected 1–5 uppercase letters.",
            )
    elif cat in ("crypto", "quant"):
        if not _CRYPTO_SYMBOL_RE.match(s):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid crypto symbol '{s}'. Expected format: BTC/USD",
            )
    else:
        if not _EQUITY_SYMBOL_RE.match(s) and not _CRYPTO_SYMBOL_RE.match(s):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid symbol '{s}'.",
            )
    return s


# ── Helpers ───────────────────────────────────────────────────────────────────


def _require_bot(bot_id: str) -> None:
    if bot_id not in _BOT_IDS:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")


def _write_override(db, bot_id: str, key: str, value: Any, email: str) -> None:
    from app.db.models.bot_config import BotConfigOverride, BotConfigAudit
    from strategy_lab.core.effective_config import invalidate_cache

    now = datetime.now(timezone.utc)

    existing = (
        db.query(BotConfigOverride)
        .filter(BotConfigOverride.bot_id == bot_id, BotConfigOverride.key == key)
        .first()
    )
    old_val = existing.value if existing else None

    if existing:
        existing.value = value
        existing.updated_at = now
        existing.updated_by = email
    else:
        db.add(BotConfigOverride(
            bot_id=bot_id, key=key, value=value,
            updated_at=now, updated_by=email,
        ))

    db.add(BotConfigAudit(
        bot_id=bot_id, key=key,
        old_value=old_val, new_value=value,
        changed_at=now, changed_by=email,
    ))
    db.commit()
    invalidate_cache(bot_id)


def _delete_override(db, bot_id: str, key: str, email: str) -> None:
    from app.db.models.bot_config import BotConfigOverride, BotConfigAudit
    from strategy_lab.core.effective_config import invalidate_cache

    row = (
        db.query(BotConfigOverride)
        .filter(BotConfigOverride.bot_id == bot_id, BotConfigOverride.key == key)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No override for key '{key}'")

    db.add(BotConfigAudit(
        bot_id=bot_id, key=key,
        old_value=row.value, new_value=None,
        changed_at=datetime.now(timezone.utc), changed_by=email,
    ))
    db.delete(row)
    db.commit()
    invalidate_cache(bot_id)


def _bot_status(bot_id: str, db) -> dict:
    """Resolve enabled/paused state — overrides win over alloc row."""
    from app.db.models.bots import BotAllocation, BotProfile, BotPosition
    from app.db.models.bot_config import BotConfigOverride

    bp = db.query(BotProfile).filter(BotProfile.name == bot_id).first()
    if not bp:
        return {"enabled": True, "paused": False, "open_positions": 0}

    alloc = (
        db.query(BotAllocation)
        .filter(BotAllocation.profile_id == bp.id)
        .first()
    )

    enabled_override = (
        db.query(BotConfigOverride)
        .filter(BotConfigOverride.bot_id == bot_id, BotConfigOverride.key == "enabled")
        .first()
    )
    paused_override = (
        db.query(BotConfigOverride)
        .filter(BotConfigOverride.bot_id == bot_id, BotConfigOverride.key == "paused")
        .first()
    )

    enabled = bool(enabled_override.value) if enabled_override else (alloc.enabled if alloc else True)
    paused = bool(paused_override.value) if paused_override else bool(alloc and alloc.paused_reason)

    open_pos = 0
    if alloc:
        open_pos = (
            db.query(BotPosition)
            .filter(
                BotPosition.allocation_id == alloc.id,
                BotPosition.closed_at.is_(None),
                BotPosition.quarantined_at.is_(None),
            )
            .count()
        )

    return {"enabled": enabled, "paused": paused, "open_positions": open_pos}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/bots")
def list_bots(
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    """List all production bots with status and open position count."""
    from app.db.models.bot_config import BotConfigOverride

    result = []
    for bot_id in _BOT_IDS:
        status = _bot_status(bot_id, db)
        result.append({
            "bot_id": bot_id,
            "category": _BOT_CATEGORIES[bot_id],
            **status,
        })
    return {"bots": result}


@router.get("/bots/{bot_id}/config")
def get_bot_config(
    bot_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    """Return effective config (YAML defaults merged with DB overrides)."""
    _require_bot(bot_id)
    from strategy_lab.core.effective_config import load_effective_config
    from app.db.models.bot_config import BotConfigOverride

    cfg = load_effective_config(bot_id, db)

    overrides = (
        db.query(BotConfigOverride)
        .filter(BotConfigOverride.bot_id == bot_id)
        .all()
    )
    return {
        "bot_id": bot_id,
        "config": cfg,
        "overrides": [
            {"key": r.key, "value": r.value, "updated_at": r.updated_at.isoformat(), "updated_by": r.updated_by}
            for r in overrides
        ],
    }


@router.patch("/bots/{bot_id}/config")
def patch_bot_config(
    bot_id: str = Path(...),
    body: dict = Body(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    """Write one config override. Body: {"key": "cooldown_minutes", "value": 20}"""
    _require_bot(bot_id)
    key = body.get("key")
    if not key or not isinstance(key, str):
        raise HTTPException(status_code=422, detail="'key' is required")
    value = body.get("value")
    if value is None:
        raise HTTPException(status_code=422, detail="'value' is required")

    validated = _validate_value(key, value)
    # Read current value for before_val
    cur_val = None
    try:
        from app.db.models.bots import BotConfigOverride
        row = db.query(BotConfigOverride).filter(
            BotConfigOverride.bot_id == bot_id,
            BotConfigOverride.key == key,
        ).first()
        cur_val = row.value if row else None
    except Exception:
        pass
    _write_override(db, bot_id, key, validated, admin.email)
    try:
        from app.services.audit_trail import post_audit_event
        post_audit_event(db, actor=admin.email, action="config_change", entity_type="bot",
                         entity_id=bot_id, before_val={key: cur_val}, after_val={key: validated})
    except Exception:
        pass
    return {"ok": True, "bot_id": bot_id, "key": key, "value": validated}


@router.delete("/bots/{bot_id}/config/{key:path}")
def delete_bot_config(
    bot_id: str = Path(...),
    key: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    """Remove an override — reverts that key to YAML default."""
    _require_bot(bot_id)
    _delete_override(db, bot_id, key, admin.email)
    return {"ok": True, "bot_id": bot_id, "key": key, "reverted_to_yaml": True}


@router.post("/bots/{bot_id}/enable")
def enable_bot(
    bot_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    _require_bot(bot_id)
    _write_override(db, bot_id, "enabled", True, admin.email)
    from app.db.models.bots import BotAllocation, BotProfile
    bp = db.query(BotProfile).filter(BotProfile.name == bot_id).first()
    if bp:
        db.query(BotAllocation).filter(BotAllocation.profile_id == bp.id).update({
            "enabled": True, "paused_reason": None,
        })
        db.commit()
    try:
        from app.services.audit_trail import post_audit_event
        post_audit_event(db, actor=admin.email, action="enable", entity_type="bot",
                         entity_id=bot_id, before_val=False, after_val=True)
    except Exception:
        pass
    return {"ok": True, "bot_id": bot_id, "enabled": True}


@router.post("/bots/{bot_id}/disable")
def disable_bot(
    bot_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    _require_bot(bot_id)
    _write_override(db, bot_id, "enabled", False, admin.email)
    from app.db.models.bots import BotAllocation, BotProfile
    bp = db.query(BotProfile).filter(BotProfile.name == bot_id).first()
    if bp:
        db.query(BotAllocation).filter(BotAllocation.profile_id == bp.id).update({
            "enabled": False, "paused_reason": "admin_lock",
        })
        db.commit()
    try:
        from app.services.audit_trail import post_audit_event
        post_audit_event(db, actor=admin.email, action="disable", entity_type="bot",
                         entity_id=bot_id, before_val=True, after_val=False)
    except Exception:
        pass
    return {"ok": True, "bot_id": bot_id, "enabled": False}


@router.post("/bots/{bot_id}/pause")
def pause_bot(
    bot_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    _require_bot(bot_id)
    _write_override(db, bot_id, "paused", True, admin.email)
    try:
        from app.services.audit_trail import post_audit_event
        post_audit_event(db, actor=admin.email, action="pause", entity_type="bot",
                         entity_id=bot_id, before_val="running", after_val="paused")
    except Exception:
        pass
    return {"ok": True, "bot_id": bot_id, "paused": True}


@router.post("/bots/{bot_id}/resume")
def resume_bot(
    bot_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    _require_bot(bot_id)
    _write_override(db, bot_id, "paused", False, admin.email)
    try:
        from app.services.audit_trail import post_audit_event
        post_audit_event(db, actor=admin.email, action="resume", entity_type="bot",
                         entity_id=bot_id, before_val="paused", after_val="running")
    except Exception:
        pass
    return {"ok": True, "bot_id": bot_id, "paused": False}


@router.get("/bots/{bot_id}/watchlist")
def get_watchlist(
    bot_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    _require_bot(bot_id)
    from app.db.models.bots import BotProfile, BotWatchlist

    bp = db.query(BotProfile).filter(BotProfile.name == bot_id).first()
    if not bp:
        return {"bot_id": bot_id, "symbols": []}

    rows = db.query(BotWatchlist).filter(BotWatchlist.profile_id == bp.id).all()
    return {
        "bot_id": bot_id,
        "symbols": [r.symbol for r in rows],
    }


@router.post("/bots/{bot_id}/watchlist")
def add_watchlist_symbol(
    bot_id: str = Path(...),
    body: dict = Body(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    _require_bot(bot_id)
    symbol = _validate_symbol(body.get("symbol", ""), bot_id)

    from app.db.models.bots import BotProfile, BotWatchlist

    bp = db.query(BotProfile).filter(BotProfile.name == bot_id).first()
    if not bp:
        raise HTTPException(status_code=404, detail=f"BotProfile '{bot_id}' not in DB yet")

    existing = (
        db.query(BotWatchlist)
        .filter(BotWatchlist.profile_id == bp.id, BotWatchlist.symbol == symbol)
        .first()
    )
    if existing:
        return {"ok": True, "bot_id": bot_id, "symbol": symbol, "already_present": True}

    db.add(BotWatchlist(profile_id=bp.id, symbol=symbol))
    db.commit()
    return {"ok": True, "bot_id": bot_id, "symbol": symbol, "added": True}


@router.delete("/bots/{bot_id}/watchlist/{symbol:path}")
def remove_watchlist_symbol(
    bot_id: str = Path(...),
    symbol: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    _require_bot(bot_id)
    symbol = symbol.strip().upper()

    from app.db.models.bots import BotProfile, BotWatchlist

    bp = db.query(BotProfile).filter(BotProfile.name == bot_id).first()
    if not bp:
        raise HTTPException(status_code=404, detail=f"BotProfile '{bot_id}' not in DB")

    row = (
        db.query(BotWatchlist)
        .filter(BotWatchlist.profile_id == bp.id, BotWatchlist.symbol == symbol)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not in watchlist")

    db.delete(row)
    db.commit()
    return {"ok": True, "bot_id": bot_id, "symbol": symbol, "removed": True}


@router.get("/bots/{bot_id}/audit")
def get_audit_log(
    bot_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_bot_admin),
):
    _require_bot(bot_id)
    from app.db.models.bot_config import BotConfigAudit

    rows = (
        db.query(BotConfigAudit)
        .filter(BotConfigAudit.bot_id == bot_id)
        .order_by(BotConfigAudit.changed_at.desc())
        .limit(50)
        .all()
    )
    return {
        "bot_id": bot_id,
        "entries": [
            {
                "id": r.id,
                "key": r.key,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "changed_at": r.changed_at.isoformat(),
                "changed_by": r.changed_by,
            }
            for r in rows
        ],
    }
