"""Chart PNG generator for approved conclave signals.

Draws a two-panel candle chart (1h + 1d) with horizontal lines for
entry, stop, and target. Saves to /tmp/conclave_charts/{signal_id}.png.

matplotlib is optional. If import fails or the render errors, this
returns None and the caller logs it. Never raises.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_OUT_DIR = "/tmp/conclave_charts"


def _fetch_bars(symbol: str, timeframe: str, n: int = 100) -> list[dict]:
    """Best-effort bar fetch. Reuses the canonical bar cache if available."""
    try:
        from app.core.canonical import _cached_live_prices  # noqa: F401
    except Exception:
        pass
    try:
        # crypto: use crypto bar fetcher
        if "/" in symbol:
            from app.services.crypto_bars import fetch_bars as _fb  # type: ignore
            return _fb(symbol, timeframe=timeframe, limit=n) or []
    except Exception:
        pass
    try:
        from app.services.bar_fetcher import fetch_bars as _fb  # type: ignore
        return _fb(symbol, timeframe=timeframe, limit=n) or []
    except Exception:
        pass
    try:
        from app.strategy_lab.bar_service import get_bars_cached as _fb  # type: ignore
        return _fb(symbol, timeframe, n) or []
    except Exception:
        pass
    return []


def generate_chart(
    signal_id: int,
    symbol: str,
    side: str,
    entry: Optional[float],
    stop: Optional[float],
    target: Optional[float],
) -> Optional[str]:
    """Generate a two-panel chart and return the file path.

    Returns None on any failure. Never raises.
    """
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
        import matplotlib.dates as mdates  # type: ignore
    except Exception as exc:
        logger.warning("[conclave.chart] matplotlib not available: %s", exc)
        return None

    try:
        os.makedirs(_OUT_DIR, exist_ok=True)
        out_path = os.path.join(_OUT_DIR, f"signal_{signal_id}.png")

        bars_1h = _fetch_bars(symbol, "1h", 60)
        bars_1d = _fetch_bars(symbol, "1d", 60)

        if not bars_1h and not bars_1d:
            logger.warning(
                "[conclave.chart] no bars for %s; skipping chart", symbol,
            )
            return None

        fig, axes = plt.subplots(
            2, 1, figsize=(9, 6), sharex=False,
            gridspec_kw={"height_ratios": [1, 1]},
        )

        for ax, bars, title in ((axes[0], bars_1h, f"{symbol} 1h"),
                                (axes[1], bars_1d, f"{symbol} 1d")):
            if not bars:
                ax.set_title(f"{title} (no data)")
                ax.axis("off")
                continue
            xs = list(range(len(bars)))
            closes = [float(b.get("c") or b.get("close") or 0) for b in bars]
            highs = [float(b.get("h") or b.get("high") or c) for b, c in zip(bars, closes)]
            lows = [float(b.get("l") or b.get("low") or c) for b, c in zip(bars, closes)]
            opens = [float(b.get("o") or b.get("open") or c) for b, c in zip(bars, closes)]
            for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
                color = "#4ade80" if c >= o else "#ef4444"
                ax.vlines(i, l, h, color=color, linewidth=0.9)
                ax.vlines(i, min(o, c), max(o, c), color=color, linewidth=3)
            if entry:
                ax.axhline(entry, color="#f0b35a", linewidth=1.0, linestyle="-")
                ax.text(len(xs) - 1, entry, f" entry {entry:.4g}",
                        color="#f0b35a", fontsize=8, va="center")
            if stop:
                ax.axhline(stop, color="#ef4444", linewidth=1.0, linestyle="--")
                ax.text(len(xs) - 1, stop, f" stop {stop:.4g}",
                        color="#ef4444", fontsize=8, va="center")
            if target:
                ax.axhline(target, color="#4ade80", linewidth=1.0, linestyle="--")
                ax.text(len(xs) - 1, target, f" target {target:.4g}",
                        color="#4ade80", fontsize=8, va="center")
            ax.set_title(title, fontsize=10, color="#dce8dc")
            ax.set_facecolor("#0a100a")
            ax.tick_params(colors="#9fb0a0", labelsize=7)
            for spine in ax.spines.values():
                spine.set_color("#1c2a1c")

        fig.patch.set_facecolor("#040705")
        fig.suptitle(
            f"Conclave: {symbol} {side.upper()} (signal {signal_id})",
            color="#dce8dc", fontsize=11,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        fig.savefig(out_path, dpi=110, facecolor=fig.get_facecolor())
        plt.close(fig)
        return out_path
    except Exception as exc:
        logger.warning("[conclave.chart] render failed for signal %d: %s",
                       signal_id, exc)
        return None
