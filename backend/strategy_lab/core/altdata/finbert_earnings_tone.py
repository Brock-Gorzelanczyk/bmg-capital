"""
FinBERT Earnings Call Tone Analysis — Weekend 8, Module 23.

Runs HuggingFace FinBERT on earnings call transcripts within 24h of release.
Features extracted:
  - forward_tone: management's forward-looking language sentiment
  - defensiveness: Q&A answer length / question length ratio
  - hedge_density: frequency of hedging words ("may", "could", "uncertain")
  - guidance_language: positive/negative guidance keywords

Model: ProsusAI/finbert (financial domain fine-tuned BERT)
Inference: Modal or Replicate (~$0.001/transcript)

Predictive edge strongest in mid/small caps where analyst coverage is sparse.
Decaying in large-caps (priced in by HFT within milliseconds).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

HEDGE_WORDS = frozenset({
    "may", "might", "could", "should", "uncertain", "uncertainty",
    "risk", "risks", "challenging", "challenges", "headwind", "headwinds",
    "if", "assuming", "approximately", "roughly", "subject to",
    "depends", "depending", "variable", "volatile", "volatility",
})

POSITIVE_GUIDANCE = frozenset({
    "accelerate", "accelerating", "outperform", "exceed", "strong",
    "record", "growth", "expand", "expanding", "confident", "momentum",
    "pipeline", "demand", "increase", "improving", "breakthrough",
})

NEGATIVE_GUIDANCE = frozenset({
    "decline", "declining", "pressure", "difficult", "below",
    "reduced", "reduction", "softer", "cautious", "caution",
    "weaker", "slowdown", "delay", "delays", "disappoint",
})


@dataclass
class EarningsTone:
    symbol: str
    fiscal_quarter: str         # "Q3 2025"
    forward_tone: float         # [-1, 1] management language sentiment
    defensiveness: float        # [0, inf] Q&A defensiveness ratio
    hedge_density: float        # [0, 1] fraction of hedging words
    guidance_score: float       # [-1, 1] guidance language sentiment
    composite_score: float      # [-1, 1] weighted combination
    label: str                  # "bullish" | "neutral" | "bearish"
    model_used: str


def _hedge_density(text: str) -> float:
    words = re.findall(r'\b\w+\b', text.lower())
    if not words:
        return 0.0
    hedge_count = sum(1 for w in words if w in HEDGE_WORDS)
    return round(hedge_count / len(words), 4)


def _guidance_score(text: str) -> float:
    words = set(re.findall(r'\b\w+\b', text.lower()))
    pos = len(words & POSITIVE_GUIDANCE)
    neg = len(words & NEGATIVE_GUIDANCE)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


def _defensiveness(qa_pairs: list[tuple[str, str]]) -> float:
    """
    Measure how defensive management is in Q&A.
    Ratio: avg(answer_words) / avg(question_words). Higher = more defensive.
    """
    if not qa_pairs:
        return 1.0
    ratios = []
    for q, a in qa_pairs:
        q_len = len(q.split())
        a_len = len(a.split())
        if q_len > 0:
            ratios.append(a_len / q_len)
    return round(sum(ratios) / len(ratios), 3) if ratios else 1.0


def _finbert_local(text: str) -> float:
    """
    Run FinBERT locally if transformers is installed.
    Returns sentiment score in [-1, 1].
    """
    try:
        from transformers import pipeline
        pipe = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            truncation=True,
            max_length=512,
        )
        # Chunk text to 512 tokens
        chunks = [text[i:i+1500] for i in range(0, min(len(text), 6000), 1500)]
        scores = []
        for chunk in chunks[:4]:
            result = pipe(chunk)[0]
            label = result["label"].lower()
            score = result["score"]
            if label == "positive":
                scores.append(score)
            elif label == "negative":
                scores.append(-score)
            else:
                scores.append(0.0)
        return round(sum(scores) / len(scores), 4) if scores else 0.0
    except ImportError:
        logger.debug("[finbert] transformers not installed — using heuristic")
        return _guidance_score(text)
    except Exception as exc:
        logger.warning("[finbert] local inference error: %s", exc)
        return 0.0


def analyze_transcript(
    symbol: str,
    fiscal_quarter: str,
    management_prepared_remarks: str,
    qa_pairs: Optional[list[tuple[str, str]]] = None,
    use_local_model: bool = True,
) -> EarningsTone:
    """
    Analyze an earnings call transcript for tone signals.

    Parameters
    ----------
    symbol : ticker
    fiscal_quarter : e.g. "Q3 2025"
    management_prepared_remarks : full text of prepared management remarks
    qa_pairs : list of (question, answer) string tuples from Q&A section
    use_local_model : run FinBERT locally (slower) vs heuristic fallback

    Returns
    -------
    EarningsTone with composite score and label
    """
    forward_tone = _finbert_local(management_prepared_remarks) if use_local_model else _guidance_score(management_prepared_remarks)
    hedge = _hedge_density(management_prepared_remarks)
    guidance = _guidance_score(management_prepared_remarks)
    defensive = _defensiveness(qa_pairs or [])

    # Weighted composite: forward_tone dominates
    composite = (
        forward_tone * 0.50
        + guidance * 0.25
        + (-hedge + 0.5) * 0.15      # lower hedge = more bullish
        + (1 / max(defensive, 0.5) - 0.5) * 0.10  # less defensive = better
    )
    composite = max(-1.0, min(1.0, composite))

    if composite > 0.2:
        label = "bullish"
    elif composite < -0.2:
        label = "bearish"
    else:
        label = "neutral"

    model = "finbert_local" if use_local_model else "heuristic"

    logger.info(
        "[finbert] %s %s — tone=%.3f hedge=%.3f guidance=%.3f defensive=%.2f composite=%.3f [%s]",
        symbol, fiscal_quarter, forward_tone, hedge, guidance, defensive, composite, label,
    )

    return EarningsTone(
        symbol=symbol,
        fiscal_quarter=fiscal_quarter,
        forward_tone=round(forward_tone, 4),
        defensiveness=round(defensive, 3),
        hedge_density=round(hedge, 4),
        guidance_score=round(guidance, 4),
        composite_score=round(composite, 4),
        label=label,
        model_used=model,
    )
