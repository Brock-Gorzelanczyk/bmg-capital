"""
LLM News Sentiment Signal — Priority 7.

Extracts directional sentiment from financial news headlines and
summaries using the Anthropic Claude API (claude-haiku-4-5 for speed
and cost).  Returns a sentiment score in [-1, 1] per symbol.

Usage
-----
sig = LLMNewsSignal()
result = await sig.score_async(symbol="AAPL", headlines=[...])
# result: {"symbol": "AAPL", "score": 0.65, "label": "bullish", "confidence": "high"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Cache scored headlines for 15 minutes to avoid re-scoring on repeated calls
_SCORE_CACHE: dict[str, tuple[float, dict]] = {}  # symbol → (expires_at, result)
_CACHE_TTL = 900


class LLMNewsSignal:
    """
    Claude-powered news sentiment scorer.

    Falls back to keyword heuristic if ANTHROPIC_API_KEY is missing.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model
        self._api_key = os.getenv("ANTHROPIC_API_KEY", "")

    # ── Public API ──────────────────────────────────────────────────────────

    async def score_async(
        self,
        symbol: str,
        headlines: list[str],
        max_headlines: int = 10,
    ) -> dict:
        """
        Score news sentiment for a symbol asynchronously.

        Parameters
        ----------
        symbol : ticker symbol
        headlines : list of recent news headline strings
        max_headlines : cap to control token usage

        Returns
        -------
        dict with: symbol, score (−1 to 1), label, confidence, headlines_used
        """
        if not headlines:
            return self._neutral(symbol, reason="no headlines")

        cache_key = f"{symbol}:{hash(tuple(sorted(headlines[:max_headlines])))}"
        cached = _SCORE_CACHE.get(cache_key)
        if cached and time.time() < cached[0]:
            return cached[1]

        trimmed = headlines[:max_headlines]

        if not self._api_key:
            result = self._heuristic_score(symbol, trimmed)
        else:
            try:
                result = await self._claude_score(symbol, trimmed)
            except Exception as exc:
                logger.warning("[llm_news] Claude API error: %s — falling back to heuristic", exc)
                result = self._heuristic_score(symbol, trimmed)

        _SCORE_CACHE[cache_key] = (time.time() + _CACHE_TTL, result)
        return result

    def score_sync(self, symbol: str, headlines: list[str]) -> dict:
        """Synchronous wrapper for use in non-async contexts."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't run async from sync inside running loop — use heuristic
                return self._heuristic_score(symbol, headlines[:10])
            return loop.run_until_complete(self.score_async(symbol, headlines))
        except RuntimeError:
            return self._heuristic_score(symbol, headlines[:10])

    # ── Claude inference ────────────────────────────────────────────────────

    async def _claude_score(self, symbol: str, headlines: list[str]) -> dict:
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package not installed")

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        headlines_text = "\n".join(f"- {h}" for h in headlines)

        prompt = (
            f"You are a financial sentiment analyst. Analyze these news headlines for {symbol} "
            f"and return a JSON object with exactly these keys:\n"
            f"  score: float from -1.0 (very bearish) to 1.0 (very bullish)\n"
            f"  label: one of 'very_bullish', 'bullish', 'neutral', 'bearish', 'very_bearish'\n"
            f"  confidence: one of 'high', 'medium', 'low'\n"
            f"  reasoning: one sentence max\n\n"
            f"Headlines:\n{headlines_text}\n\n"
            f"Return only valid JSON, no markdown."
        )

        message = await client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        text = message.content[0].text.strip()
        parsed = json.loads(text)
        return {
            "symbol": symbol,
            "score": float(parsed.get("score", 0.0)),
            "label": parsed.get("label", "neutral"),
            "confidence": parsed.get("confidence", "low"),
            "reasoning": parsed.get("reasoning", ""),
            "headlines_used": len(headlines),
            "source": "claude",
        }

    # ── Heuristic fallback ───────────────────────────────────────────────────

    def _heuristic_score(self, symbol: str, headlines: list[str]) -> dict:
        BULLISH_TERMS = {
            "beat", "beats", "exceeded", "record", "upgraded", "raised", "growth",
            "partnership", "contract", "buyback", "dividend", "acquisition", "rally",
            "surge", "soars", "breakthrough", "approval", "win", "positive",
        }
        BEARISH_TERMS = {
            "miss", "misses", "missed", "downgraded", "lowered", "loss", "losses",
            "investigation", "lawsuit", "recall", "delay", "cut", "slump", "plunges",
            "declines", "warning", "risk", "negative", "fraud", "breach", "default",
        }

        score = 0.0
        for headline in headlines:
            words = set(headline.lower().split())
            b = len(words & BULLISH_TERMS)
            br = len(words & BEARISH_TERMS)
            score += (b - br) * 0.15

        score = max(-1.0, min(1.0, score))
        if score > 0.3:
            label = "bullish"
        elif score > 0.6:
            label = "very_bullish"
        elif score < -0.3:
            label = "bearish"
        elif score < -0.6:
            label = "very_bearish"
        else:
            label = "neutral"

        return {
            "symbol": symbol,
            "score": round(score, 3),
            "label": label,
            "confidence": "low",
            "reasoning": "keyword heuristic",
            "headlines_used": len(headlines),
            "source": "heuristic",
        }

    def _neutral(self, symbol: str, reason: str = "") -> dict:
        return {
            "symbol": symbol,
            "score": 0.0,
            "label": "neutral",
            "confidence": "low",
            "reasoning": reason,
            "headlines_used": 0,
            "source": "default",
        }


_signal = LLMNewsSignal()


def get_news_signal() -> LLMNewsSignal:
    return _signal
