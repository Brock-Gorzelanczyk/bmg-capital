"""ExecutionModel — abstract base for all order submission components."""
from __future__ import annotations
from abc import ABC, abstractmethod
from ..types import Symbol, PortfolioTarget, Order
from ..context import AlgorithmContext


class ExecutionModel(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def execute(
        self,
        ctx: AlgorithmContext,
        targets: list[PortfolioTarget],
        current_positions: dict[Symbol, float],
    ) -> list[Order]:
        """Convert final targets into orders and submit them to the broker."""
        ...
