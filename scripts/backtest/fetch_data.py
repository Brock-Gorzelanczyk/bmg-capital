"""
Fetch SPY 15m bars (2018-2026) from Alpaca + VIX daily from yfinance.
Filters to RTH (9:30 AM - 4:00 PM ET). Saves to parquet.

Data periods covered:
  - 2018 Feb Volmageddon
  - 2020 COVID crash
  - 2022 bear market
  - 2023-2024 AI rally
  - 2025-2026 Trump 2.0 + tariffs
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import yfinance as yf

load_dotenv("/Users/brockgorzelanczyk/my-new-project/backend/.env")

DATA_DIR = Path("/Users/brockgorzelanczyk/my-new-project/scripts/backtest/data")
DATA_DIR.mkdir(exist_ok=True)

client = StockHistoricalDataClient(
    api_key=os.getenv("ALPACA_API_KEY"),
    secret_key=os.getenv("ALPACA_SECRET_KEY"),
)


def fetch_spy_15m(start_year=2018, end_year=2026, hard_end_date=datetime(2026, 6, 30)):
    """Fetch SPY 15m bars year-by-year, concatenate, filter RTH, save.
    hard_end_date caps requests to avoid Alpaca free-tier SIP restriction on recent data."""
    output = DATA_DIR / "spy_15m.parquet"
    if output.exists():
        df = pd.read_parquet(output)
        print(f"[cache] Loaded {len(df):,} SPY 15m bars from {df.index.min()} to {df.index.max()}")
        return df

    all_dfs = []
    for year in range(start_year, end_year + 1):
        # Chunk by 6 months to avoid huge requests
        for half in [(1, 7), (7, 13)]:
            start_month, end_month = half
            start = datetime(year, start_month, 1)
            if end_month == 13:
                end = datetime(year + 1, 1, 1)
            else:
                end = datetime(year, end_month, 1)
            if start > hard_end_date:
                break
            end_capped = min(end, hard_end_date)
            print(f"  Fetching SPY 15m {start.date()} → {end_capped.date()}...", flush=True)
            req = StockBarsRequest(
                symbol_or_symbols=["SPY"],
                timeframe=TimeFrame(15, TimeFrameUnit.Minute),
                start=start,
                end=end_capped,
            )
            try:
                bars = client.get_stock_bars(req).df
                if len(bars) > 0:
                    bars = bars.reset_index(level=0, drop=True)
                    all_dfs.append(bars)
                    print(f"    {len(bars):,} bars", flush=True)
                time.sleep(0.3)
            except Exception as e:
                print(f"    FAIL: {e}", flush=True)

    df = pd.concat(all_dfs)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='first')]

    # Filter to RTH (9:30-16:00 ET) — convert UTC index to ET
    df_et = df.tz_convert('America/New_York')
    rth_mask = (
        ((df_et.index.hour == 9) & (df_et.index.minute >= 30)) |
        ((df_et.index.hour > 9) & (df_et.index.hour < 16)) |
        ((df_et.index.hour == 16) & (df_et.index.minute == 0))
    )
    # But drop 16:00 bar (close bar shouldn't be included for TV parity)
    rth_mask = (
        ((df_et.index.hour == 9) & (df_et.index.minute >= 30)) |
        ((df_et.index.hour >= 10) & (df_et.index.hour < 16))
    )
    df_rth = df[rth_mask]
    # Drop weekends
    df_rth = df_rth[df_rth.index.dayofweek < 5]

    print(f"\nTotal: {len(df):,} raw bars, {len(df_rth):,} RTH bars ({len(df_rth)/len(df)*100:.1f}% RTH)")
    print(f"Range: {df_rth.index.min()} → {df_rth.index.max()}")

    df_rth.to_parquet(output)
    print(f"Saved to {output}")
    return df_rth


def fetch_vix_daily():
    """Fetch VIX daily close from yfinance."""
    output = DATA_DIR / "vix_daily.parquet"
    if output.exists():
        df = pd.read_parquet(output)
        print(f"[cache] Loaded {len(df):,} VIX daily bars")
        return df

    print("Fetching VIX daily (2018-2026)...")
    vix = yf.download('^VIX', start='2018-01-01', end='2026-09-04', progress=False, auto_adjust=False)
    # Flatten multi-level columns if present
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix = vix[['Open', 'High', 'Low', 'Close']]
    vix.columns = ['open', 'high', 'low', 'close']
    # Localize to naive dates (VIX close is EOD)
    vix.index = pd.to_datetime(vix.index).tz_localize(None)
    vix.to_parquet(output)
    print(f"Saved {len(vix):,} VIX bars to {output}")
    return vix


if __name__ == "__main__":
    print("=" * 60)
    print("Fetching SPY 15m + VIX daily (2018-2026)")
    print("=" * 60)
    spy = fetch_spy_15m(2018, 2026)
    vix = fetch_vix_daily()
    print("\n=== Summary ===")
    print(f"SPY 15m bars: {len(spy):,} covering {spy.index.min().date()} → {spy.index.max().date()}")
    print(f"VIX daily bars: {len(vix):,} covering {vix.index.min().date()} → {vix.index.max().date()}")
