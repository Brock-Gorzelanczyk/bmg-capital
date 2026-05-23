from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Set

from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream

from app.config import settings

logger = logging.getLogger(__name__)


class StreamManager:
    MAX_SYMBOLS = 30

    def __init__(self) -> None:
        self._stream: StockDataStream | None = None
        self._task: asyncio.Task | None = None
        self._subscribed: Set[str] = set()
        self._quote_callbacks: List[Callable] = []
        self._bar_callbacks: List[Callable] = []
        self._running = False

    async def start(self) -> None:
        if not settings.alpaca_api_key:
            logger.warning("No Alpaca API key — stream disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._stream:
            try:
                await self._stream.stop_ws()
            except Exception as e:
                logger.error(f"Error stopping stream: {e}")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while self._running:
            try:
                self._stream = StockDataStream(
                    api_key=settings.alpaca_api_key,
                    secret_key=settings.alpaca_secret_key,
                    feed=DataFeed.IEX,
                )
                if self._subscribed:
                    await self._stream.subscribe_quotes(self._on_quote, *self._subscribed)
                    await self._stream.subscribe_bars(self._on_bar, *self._subscribed)
                await self._stream._run_forever()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stream error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def subscribe(self, symbols: List[str]) -> None:
        new = set(symbols) - self._subscribed
        if not new:
            return
        slots = self.MAX_SYMBOLS - len(self._subscribed)
        to_add = list(new)[:slots]
        self._subscribed.update(to_add)
        if self._stream and to_add:
            try:
                await self._stream.subscribe_quotes(self._on_quote, *to_add)
                await self._stream.subscribe_bars(self._on_bar, *to_add)
            except Exception as e:
                logger.error(f"Subscribe error: {e}")

    async def unsubscribe(self, symbols: List[str]) -> None:
        to_remove = set(symbols) & self._subscribed
        self._subscribed -= to_remove
        if self._stream and to_remove:
            try:
                await self._stream.unsubscribe_quotes(*to_remove)
                await self._stream.unsubscribe_bars(*to_remove)
            except Exception as e:
                logger.error(f"Unsubscribe error: {e}")

    def on_quote(self, cb: Callable) -> None:
        self._quote_callbacks.append(cb)

    def on_bar(self, cb: Callable) -> None:
        self._bar_callbacks.append(cb)

    async def _on_quote(self, data: Any) -> None:
        bid = float(data.bid_price) if data.bid_price else 0.0
        ask = float(data.ask_price) if data.ask_price else 0.0
        mid = float((data.bid_price + data.ask_price) / 2) if data.bid_price and data.ask_price else 0.0
        msg: Dict[str, Any] = {
            "type": "quote",
            "symbol": data.symbol,
            "bid": bid,
            "ask": ask,
            "price": mid,
            "timestamp": data.timestamp.isoformat(),
        }
        for cb in self._quote_callbacks:
            try:
                await cb(data.symbol, msg)
            except Exception as e:
                logger.error(f"Quote callback error: {e}")

    async def _on_bar(self, data: Any) -> None:
        msg: Dict[str, Any] = {
            "type": "bar",
            "symbol": data.symbol,
            "open": float(data.open),
            "high": float(data.high),
            "low": float(data.low),
            "close": float(data.close),
            "volume": float(data.volume),
            "timestamp": data.timestamp.isoformat(),
        }
        for cb in self._bar_callbacks:
            try:
                await cb(data.symbol, msg)
            except Exception as e:
                logger.error(f"Bar callback error: {e}")


stream_manager = StreamManager()
