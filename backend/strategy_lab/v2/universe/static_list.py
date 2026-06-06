"""StaticListUniverse — the simplest universe: a hardcoded list of symbols.

Use this for bots where the investable set never changes (e.g. crypto_lt
holds the same 5 coins indefinitely, unlike stock bots that rebuild from
a Russell 1000 screen every day).
"""
from __future__ import annotations
from .base import UniverseSelectionModel
from ..types import Symbol
from ..context import AlgorithmContext


class StaticListUniverse(UniverseSelectionModel):
    """Returns the same fixed list every iteration."""

    def __init__(self, symbols: list[Symbol]) -> None:
        if not symbols:
            raise ValueError("StaticListUniverse requires at least one symbol")
        self._symbols = list(symbols)

    @property
    def name(self) -> str:
        return f"static_list({len(self._symbols)})"

    async def select_symbols(self, ctx: AlgorithmContext) -> list[Symbol]:
        return list(self._symbols)
