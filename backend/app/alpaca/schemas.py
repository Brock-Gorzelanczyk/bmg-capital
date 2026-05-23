from __future__ import annotations

from pydantic import BaseModel, Field


class BarData(BaseModel):
    symbol: str
    t: str
    o: float
    h: float
    l: float
    c: float
    v: float


class QuoteData(BaseModel):
    symbol: str
    bp: float
    ap: float
    bs: int
    as_: int = Field(alias="as")
    t: str

    class Config:
        populate_by_name = True


class SnapshotData(BaseModel):
    symbol: str
    price: float
    change: float
    change_pct: float
    volume: float
    prev_close: float
