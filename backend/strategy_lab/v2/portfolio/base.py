"""PortfolioConstructionModel — abstract base for all sizing components."""
from __future__ import annotations
from abc import ABC, abstractmethod
from ..types import Symbol, Insight, PortfolioTarget
from ..context import AlgorithmContext


class PortfolioConstructionModel(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def create_targets(
        self,
        ctx: AlgorithmContext,
        insights: list[Insight],
        current_positions: dict[Symbol, float],
        portfolio_value: float,
    ) -> list[PortfolioTarget]:
        """Convert insights into target position sizes."""
        ...
