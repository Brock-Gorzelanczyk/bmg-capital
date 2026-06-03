"""PositionState enum — lifecycle states for a bot-managed position."""
from __future__ import annotations

from enum import Enum


class PositionState(str, Enum):
    PENDING   = "pending"    # Signal fired; order not yet filled
    OPEN      = "open"       # Position is live
    STOPPED   = "stopped"    # Exited via stop-loss
    TARGETED  = "targeted"   # Exited via take-profit
    EXPIRED   = "expired"    # Hold window elapsed; exited at market
    CLOSED    = "closed"     # Manually closed or end-of-day flat
