"""UniverseSelectionModel — abstract base for all universe components."""
from __future__ import annotations
from abc import ABC, abstractmethod
from ..types import Symbol
from ..context import AlgorithmContext


class UniverseSelectionModel(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def select_symbols(self, ctx: AlgorithmContext) -> list[Symbol]:
        """Return the tradeable set for this iteration."""
        ...
