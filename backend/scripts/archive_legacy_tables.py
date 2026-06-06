"""
Archive legacy personal-portfolio and paper-trading tables.

Renames:
  portfolios          → portfolios_archived
  positions           → positions_archived
  paper_accounts      → paper_accounts_archived
  paper_positions     → paper_positions_archived
  paper_orders        → paper_orders_archived
  paper_transactions  → paper_transactions_archived
  paper_daily_snapshots → paper_daily_snapshots_archived

Data is preserved. Run once; idempotent (skips if already renamed).

Usage:
    railway run --environment production .venv/bin/python3 scripts/archive_legacy_tables.py
"""
import os, sys, sqlite3

# Read DATABASE_URL from env — expected: sqlite:////data/bmg_capital.db
db_url = os.environ.get("DATABASE_URL", "")
if not db_url.startswith("sqlite:///"):
    print(f"ERROR: Expected sqlite:/// URL, got: {db_url!r}")
    sys.exit(1)

db_path = db_url.replace("sqlite:///", "")
print(f"Connecting to: {db_path}")

RENAMES = [
    ("portfolios",            "portfolios_archived"),
    ("positions",             "positions_archived"),
    ("paper_accounts",        "paper_accounts_archived"),
    ("paper_positions",       "paper_positions_archived"),
    ("paper_orders",          "paper_orders_archived"),
    ("paper_transactions",    "paper_transactions_archived"),
    ("paper_daily_snapshots", "paper_daily_snapshots_archived"),
]

conn = sqlite3.connect(db_path)
cur = conn.cursor()

def table_exists(name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

for src, dst in RENAMES:
    if not table_exists(src):
        if table_exists(dst):
            print(f"  SKIP  {src} → already archived as {dst}")
        else:
            print(f"  WARN  {src} not found and {dst} not found — skipping")
        continue
    cur.execute(f'ALTER TABLE "{src}" RENAME TO "{dst}"')
    conn.commit()
    print(f"  OK    {src} → {dst}")

conn.close()
print("\nDone. Data intact in *_archived tables.")
