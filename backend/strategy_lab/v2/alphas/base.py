"""AlphaModel — abstract base for all signal generation components."""
from __future__ import annotations
from abc import ABC, abstractmethod
from ..types import Symbol, Bar, Insight
from ..context import AlgorithmContext


class AlphaModel(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def generate_insights(
        self,
        ctx: AlgorithmContext,
        universe: list[Symbol],
        bars: dict[Symbol, list[Bar]],
    ) -> list[Insight]:
        """Given bars for the universe, emit directional insights."""
        ...
