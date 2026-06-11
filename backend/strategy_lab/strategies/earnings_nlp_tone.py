"""
Earnings NLP Tone Strategy — BLOCKED (transcript feed not connected).

Loughran & McDonald (2011) "When Is a Liability Not a Liability? Textual
Analysis, Dictionaries, and 10-Ks", Journal of Finance 66(1): 35-65.

Strategy concept:
  - Parse earnings call transcripts with LM sentiment dictionary
  - Compute "tone delta" = (positive words / total words) - (negative words / total words)
  - Rank S&P 500 reporters by tone improvement vs. prior quarter
  - Long top-decile tone improvement stocks at next open
  - Hold 1-3 days (post-earnings drift window)
  - Exit at target 8% or stop -5%

BLOCKED REASON: No earnings transcript data source is connected.
Required: earnings transcript API (e.g. Seeking Alpha Premium, Motley Fool Pro,
          Refinitiv Earnings Transcripts, or Sentieo).
          Also need: earnings calendar feed to know which symbols are reporting.

This stub returns [] immediately and logs a DEBUG message so the scheduler
runs cleanly without raising exceptions.

Strategy name: earnings_nlp_tone
"""
from __future__ import annotations

import logging
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "earnings_nlp_tone"

BLOCKED_REASON = (
    "earnings_nlp_tone: BLOCKED — transcript feed not connected. "
    "Requires earnings transcript API (Seeking Alpha, Motley Fool Pro, "
    "Refinitiv, or similar). Wire transcript feed, then implement "
    "Loughran-McDonald tone delta scoring."
)


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """BLOCKED stub — returns empty list until transcript feed is wired.

    Full implementation plan:
      1. Query earnings calendar API for today's reporters
      2. Fetch transcript for each reporter
      3. Score each transcript with LM dictionary (positive / negative / total word counts)
      4. Compute tone_delta = this_quarter_tone - last_quarter_tone
      5. Rank by tone_delta descending
      6. Return buy signals for top decile (confidence ∝ tone_delta percentile)
    """
    logger.debug(BLOCKED_REASON)
    return []
