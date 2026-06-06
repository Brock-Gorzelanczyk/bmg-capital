"""TopCryptoByCap — dynamic universe of the top N coins by market cap.

Fetches from CoinGecko (server-side 1-minute cache), so it refreshes
automatically as market cap rankings change.  Excludes stablecoins.
"""
from __future__ import annotations
import logging
from .base import UniverseSelectionModel
from ..types import Symbol
from ..context import AlgorithmContext

logger = logging.getLogger(__name__)

_STABLECOINS = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "FRAX", "LUSD"}


class TopCryptoByCap(UniverseSelectionModel):
    """Top N coins by market cap, excluding stablecoins.

    Symbols are returned in "BASE/USD" format: "BTC/USD", "ETH/USD", etc.
    """

    def __init__(self, n: int = 20, exclude_stablecoins: bool = True) -> None:
        self._n = n
        self._exclude_stablecoins = exclude_stablecoins

    @property
    def name(self) -> str:
        return f"top_crypto_by_mcap(n={self._n})"

    async def select_symbols(self, ctx: AlgorithmContext) -> list[Symbol]:
        try:
            from app.services import coingecko as cg
            coins = cg.get_top_coins()
        except Exception as exc:
            ctx.log("warning", f"CoinGecko fetch failed: {exc}")
            return []

        symbols: list[Symbol] = []
        for coin in coins:
            sym = (coin.get("symbol") or "").upper()
            if not sym:
                continue
            if self._exclude_stablecoins and sym in _STABLECOINS:
                continue
            symbols.append(f"{sym}/USD")
            if len(symbols) >= self._n:
                break

        ctx.log("info", f"TopCryptoByCap: {len(symbols)} symbols selected")
        return symbols
