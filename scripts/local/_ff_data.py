"""Ken French Data Library downloader — free FF3 + UMD + FF5 monthly factors.

Downloads and caches Ken French's monthly research factors CSV from Dartmouth.
Pure stdlib (no pandas). Returns dict keyed by YYYY-MM string with each row's
factor values in decimal (NOT percent — Ken French publishes as percent, we
convert on read).

Ken French publishes MONTHLY updated data at:
- FF3: F-Research_Data_Factors_CSV.zip
- UMD: F-F_Momentum_Factor_CSV.zip
- FF5: F-F_Research_Data_5_Factors_2x3_CSV.zip

Cache lives at ~/Documents/BMG-Capital-Vault/data/ff_factors/*.csv
Refreshed weekly (if cache older than 7d, re-download).

Ref: vault/research/2026-08-31-verify-fama-french-3-factor.md
     vault/research/2026-08-31-verify-carhart-4-factor.md
"""
from __future__ import annotations

import io
import os
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Optional

CACHE_DIR = Path.home() / "Documents" / "BMG-Capital-Vault" / "data" / "ff_factors"
CACHE_MAX_AGE_SEC = 7 * 24 * 3600  # 7 days

FF3_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip"
UMD_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_CSV.zip"


def _download_and_extract(url: str, out_path: Path) -> None:
    """Download zip, extract single CSV inside, save to out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG ff_data)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        zip_bytes = resp.read()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".CSV") or n.endswith(".csv")]
        if not names:
            raise RuntimeError(f"no CSV inside {url}")
        with zf.open(names[0]) as f:
            out_path.write_bytes(f.read())


def _cached_path(url: str) -> Path:
    fname = url.rsplit("/", 1)[-1].replace(".zip", ".csv")
    return CACHE_DIR / fname


def _ensure_fresh(url: str) -> Path:
    path = _cached_path(url)
    if path.exists() and (time.time() - path.stat().st_mtime) < CACHE_MAX_AGE_SEC:
        return path
    try:
        _download_and_extract(url, path)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        if path.exists():
            return path  # fall back to stale cache
        raise RuntimeError(f"failed to download {url}: {e}")
    return path


def _parse_ken_french_csv(path: Path, monthly_only: bool = True) -> Dict[str, Dict[str, float]]:
    """Parse Ken French monthly factor CSV.

    Format (after Ken French's variable header):
      YYYYMM,Mkt-RF,SMB,HML,RF
      196307,-0.39,-0.44,-0.94,0.27
      ...

    Returns dict keyed by 'YYYY-MM' with float values in decimal (0.01 = 1%).
    Skips the annual section that follows the monthly section.
    """
    text = path.read_text(encoding="latin-1")  # Ken French uses latin-1
    lines = text.splitlines()

    # Find header line (first line starting with a date column header)
    hdr_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Header: first field empty or "" or numeric-like, followed by factor names
        parts = [p.strip() for p in stripped.split(",")]
        # Exact-token match on the factor names — substring match caught
        # words like "momentum" in the description text.
        FACTOR_TOKENS = {"mkt-rf", "smb", "hml", "rf", "umd", "mom", "rmw", "cma"}
        if len(parts) >= 2 and any(p.lower() in FACTOR_TOKENS for p in parts):
            hdr_idx = i
            break

    if hdr_idx is None:
        raise RuntimeError(f"could not find factor header in {path}")

    header = [p.strip() for p in lines[hdr_idx].split(",")]
    # Ken French sometimes has a blank first cell in the header row; date column is column 0
    if header and header[0] == "":
        header[0] = "date"

    factors: Dict[str, Dict[str, float]] = {}
    for line in lines[hdr_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        parts = [p.strip() for p in stripped.split(",")]
        # Monthly rows are 6-digit YYYYMM. Annual rows are 4-digit YYYY. Blank rows or
        # transition headers break the loop.
        first = parts[0]
        if not first or not first.isdigit():
            # Reached a non-data line (probably the annual-return section header)
            if monthly_only:
                break
            continue
        if monthly_only and len(first) != 6:
            break  # annual section starts
        # Parse the row
        try:
            row_vals = {header[i]: float(parts[i]) / 100.0 for i in range(1, min(len(header), len(parts)))}
        except ValueError:
            continue
        if len(first) == 6:
            key = f"{first[:4]}-{first[4:6]}"
        else:
            key = first
        factors[key] = row_vals
    return factors


def get_ff3_monthly() -> Dict[str, Dict[str, float]]:
    """Return {YYYY-MM: {Mkt-RF, SMB, HML, RF}} in decimal (0.01 = 1%)."""
    path = _ensure_fresh(FF3_URL)
    return _parse_ken_french_csv(path, monthly_only=True)


def get_umd_monthly() -> Dict[str, Dict[str, float]]:
    """Return {YYYY-MM: {Mom}} in decimal. Ken French names it 'Mom' (equivalent to UMD)."""
    path = _ensure_fresh(UMD_URL)
    return _parse_ken_french_csv(path, monthly_only=True)


def get_ff4_monthly() -> Dict[str, Dict[str, float]]:
    """Merge FF3 + UMD into a single {YYYY-MM: {Mkt-RF, SMB, HML, RF, UMD}} dict."""
    ff3 = get_ff3_monthly()
    umd = get_umd_monthly()
    merged: Dict[str, Dict[str, float]] = {}
    for key, ff3_row in ff3.items():
        umd_row = umd.get(key, {})
        # Ken French's momentum column is labeled 'Mom' — normalize to 'UMD'
        mom_val = None
        for k, v in umd_row.items():
            if k.lower() in ("mom", "umd"):
                mom_val = v
                break
        merged[key] = dict(ff3_row)
        if mom_val is not None:
            merged[key]["UMD"] = mom_val
    return merged


if __name__ == "__main__":
    # Smoke test
    print(f"Downloading FF3+UMD from Dartmouth...")
    data = get_ff4_monthly()
    keys = sorted(data.keys())
    print(f"Got {len(keys)} months, earliest {keys[0]}, latest {keys[-1]}")
    print(f"Latest row: {keys[-1]} → {data[keys[-1]]}")
