"""RiskManagementModel — abstract base for all risk veto/resize components."""
from __future__ import annotations
from abc import ABC, abstractmethod
from ..types import Symbol, PortfolioTarget
from ..context import AlgorithmContext


class RiskManagementModel(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def manage_risk(
        self,
        ctx: AlgorithmContext,
        targets: list[PortfolioTarget],
        current_positions: dict[Symbol, float],
        portfolio_value: float,
    ) -> list[PortfolioTarget]:
        """Filter or resize targets. Return surviving targets (may be empty)."""
        ...
