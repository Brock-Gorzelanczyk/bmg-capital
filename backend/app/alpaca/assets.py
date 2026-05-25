from __future__ import annotations

import json
import logging
import os
from typing import List

logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE: List[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "UNH", "LLY",
    "JPM", "V", "AVGO", "XOM", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
    "COST", "ADBE", "KO", "PEP", "WMT", "BAC", "CRM", "TMO", "MCD", "CSCO",
    "ACN", "ABT", "NFLX", "DHR", "LIN", "AMD", "TXN", "ORCL", "WFC", "PM",
    "NEE", "INTC", "DIS", "RTX", "UPS", "AMGN", "BMY", "QCOM", "HON", "LOW",
]

# Path relative to the backend directory
_UNIVERSE_FILE = os.path.join(
    os.path.dirname(__file__),  # app/alpaca/
    "..",  # app/
    "..",  # backend/
    "data",
    "universe.json",
)


def get_universe() -> List[str]:
    """Return the stock universe symbol list.

    Tries to load from backend/data/universe.json first; falls back to
    DEFAULT_UNIVERSE if the file does not exist or cannot be parsed.
    """
    try:
        path = os.path.normpath(_UNIVERSE_FILE)
        if os.path.isfile(path):
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                logger.info(f"Loaded universe from {path}: {len(data)} symbols")
                return [str(s).upper() for s in data]
    except Exception as e:
        logger.warning(f"Could not load universe.json: {e} — using default universe", exc_info=True)
    return list(DEFAULT_UNIVERSE)
