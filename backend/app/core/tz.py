"""Timezone-safe ISO serialization helpers.

The BMG DB models were mostly authored with SQLAlchemy `DateTime` columns
without `timezone=True` — Postgres stores them as `timestamp WITHOUT time
zone`. Writes come from `datetime.now(timezone.utc)` and get their tz info
stripped at insert. On read, the value is a naive Python datetime.

Calling `.isoformat()` on a naive datetime produces "2026-07-03T01:22:15"
with no timezone marker. Per ECMAScript spec, JS `new Date()` on such a
string is interpreted as LOCAL BROWSER TIME. For a Central-time user
(UTC-5) viewing a UTC 01:22 trade, the browser reads "01:22 local" and
renders the date as "Jul 3" — a full day off from the wall clock they
just saw.

`iso_utc()` and `iso_naive_utc()` fix this at the serialization layer:
naive datetime → tagged as UTC → produces "2026-07-03T01:22:15+00:00"
which every browser parses correctly.

## Why not fix the DB schema?

Changing `DateTime` → `DateTime(timezone=True)` requires a migration
across every table + every write site. High blast radius. Doing it once
at serialization time is safe, targeted, and reversible.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Return ISO string tagged as UTC, or None.

    - `None` → `None`
    - Naive datetime → assumed UTC, output includes +00:00
    - Aware datetime → output preserves original tz (usually already UTC)
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
