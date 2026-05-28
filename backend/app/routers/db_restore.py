from __future__ import annotations
import base64
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin", tags=["admin"])

_SECRET = "bmg-restore-2026-xK9q"


class RestoreRequest(BaseModel):
    secret: str
    db_b64: str


@router.post("/restore-db")
def restore_db(body: RestoreRequest):
    if body.secret != _SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        db_path = Path(db_url.replace("sqlite:///", ""))
    else:
        raise HTTPException(status_code=500, detail="Not a SQLite database")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(body.db_b64)
    db_path.write_bytes(data)

    return {"ok": True, "path": str(db_path), "size": len(data)}
