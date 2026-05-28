from __future__ import annotations

import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# In-memory TTL cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        del _cache[key]
        return None
    return value


def _set_cached(key: str, value: Any, ttl_seconds: float) -> None:
    _cache[key] = (time.monotonic() + ttl_seconds, value)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SNAPSHOT_GQL = "https://hub.snapshot.org/graphql"
_TIMEOUT = 20.0

DEFAULT_SPACES: list[str] = [
    "uniswap.eth",
    "aave.eth",
    "compound-governance.eth",
    "arbitrumfoundation.eth",
    "optimismfoundation.eth",
    "curve.eth",
    "makerdao.eth",
    "lido-snapshot.eth",
    "gmx.eth",
    "dydx.eth",
    "gitcoindao.eth",
    "ens.eth",
]

# ---------------------------------------------------------------------------
# GraphQL query template
# ---------------------------------------------------------------------------

_PROPOSALS_QUERY = """
query Proposals($spaces: [String!]!, $state: String!, $first: Int!) {
  proposals(
    first: $first,
    skip: 0,
    where: { space_in: $spaces, state: $state },
    orderBy: "end",
    orderDirection: desc
  ) {
    id
    title
    body
    start
    end
    state
    author
    choices
    scores
    scores_total
    votes
    quorum
    type
    space {
      id
      name
      avatar
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_proposal(raw: dict) -> dict:
    """Normalise a Snapshot proposal into the canonical shape."""
    space = raw.get("space") or {}
    space_id: str = space.get("id", "")
    proposal_id: str = raw.get("id", "")

    body: str = raw.get("body") or ""
    summary = body[:200].strip()

    choices: list[str] = raw.get("choices") or []
    scores: list[float] = [float(s) for s in (raw.get("scores") or [])]
    scores_total: float = float(raw.get("scores_total") or 0)

    # Determine winning choice
    top_choice = ""
    top_pct = 0.0
    if choices and scores:
        max_idx = scores.index(max(scores))
        top_choice = choices[max_idx] if max_idx < len(choices) else ""
        if scores_total > 0:
            top_pct = round(scores[max_idx] / scores_total * 100, 2)

    return {
        "id": proposal_id,
        "title": raw.get("title", ""),
        "summary": summary,
        "space_id": space_id,
        "space_name": space.get("name", ""),
        "space_avatar": space.get("avatar", ""),
        "start": raw.get("start") or 0,
        "end": raw.get("end") or 0,
        "state": raw.get("state", ""),
        "choices": choices,
        "scores": scores,
        "scores_total": scores_total,
        "votes": int(raw.get("votes") or 0),
        "quorum": float(raw.get("quorum") or 0),
        "author": raw.get("author", ""),
        "url": f"https://snapshot.org/#/{space_id}/proposal/{proposal_id}",
        "top_choice": top_choice,
        "top_pct": top_pct,
    }


async def _fetch_proposals(
    spaces: list[str],
    state: str,
    limit: int,
) -> list[dict]:
    """Execute the Snapshot GraphQL query and return parsed proposals."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _SNAPSHOT_GQL,
                json={
                    "query": _PROPOSALS_QUERY,
                    "variables": {
                        "spaces": spaces,
                        "state": state,
                        "first": limit,
                    },
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        raw_proposals: list[dict] = (
            (data.get("data") or {}).get("proposals") or []
        )
        return [_parse_proposal(p) for p in raw_proposals]

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_active_proposals(
    spaces: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Fetch active DAO proposals from Snapshot GraphQL API.

    Uses *DEFAULT_SPACES* if *spaces* is None.  Results are cached for
    5 minutes.  Returns an empty list on any error.
    """
    if spaces is None:
        spaces = DEFAULT_SPACES

    cache_key = f"proposals:active:{'|'.join(sorted(spaces))}:{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    results = await _fetch_proposals(spaces=spaces, state="active", limit=limit)
    _set_cached(cache_key, results, 300)  # 5 minutes
    return results


async def get_closed_proposals(
    spaces: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Fetch recently closed DAO proposals from Snapshot GraphQL API.

    Same shape as *get_active_proposals*.  Cached 15 minutes.
    """
    if spaces is None:
        spaces = DEFAULT_SPACES

    cache_key = f"proposals:closed:{'|'.join(sorted(spaces))}:{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    results = await _fetch_proposals(spaces=spaces, state="closed", limit=limit)
    _set_cached(cache_key, results, 900)  # 15 minutes
    return results


async def get_space_proposals(
    space_id: str,
    state: str = "active",
    limit: int = 5,
) -> list[dict]:
    """
    Fetch proposals for a specific DAO space.

    *state* can be "active", "pending", or "closed".
    Cached 5 minutes.
    """
    cache_key = f"proposals:space:{space_id}:{state}:{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    results = await _fetch_proposals(spaces=[space_id], state=state, limit=limit)
    _set_cached(cache_key, results, 300)  # 5 minutes
    return results
