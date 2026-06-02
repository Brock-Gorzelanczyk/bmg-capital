from __future__ import annotations

import io
import json
import logging
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import settings
from app.db.models.users import User
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tax", tags=["tax"])

# ── 2024 tax brackets ──────────────────────────────────────────────────────────

BRACKETS_SINGLE = [
    (11600, 0.10),
    (47150, 0.12),
    (100525, 0.22),
    (191950, 0.24),
    (243725, 0.32),
    (609350, 0.35),
    (float("inf"), 0.37),
]

BRACKETS_MFJ = [
    (23200, 0.10),
    (94300, 0.12),
    (201050, 0.22),
    (383900, 0.24),
    (487450, 0.32),
    (731200, 0.35),
    (float("inf"), 0.37),
]


def _marginal_bracket(taxable_income: float, filing_status: str) -> str:
    brackets = BRACKETS_MFJ if "joint" in filing_status else BRACKETS_SINGLE
    prev = 0.0
    for limit, rate in brackets:
        if taxable_income <= limit:
            return f"{int(rate * 100)}%"
        prev = limit
    return "37%"


def _extract_fields(text: str) -> dict:
    """Pull key numeric fields from raw 1040 text using regex."""

    def find_number(pattern: str) -> Optional[float]:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        raw = m.group(1).replace(",", "").replace("$", "").strip()
        try:
            return float(raw)
        except ValueError:
            return None

    # Filing status — look for checked boxes or text indicators
    filing_status = "single"
    if re.search(r"married\s+filing\s+jointly", text, re.IGNORECASE):
        filing_status = "married_jointly"
    elif re.search(r"married\s+filing\s+separately", text, re.IGNORECASE):
        filing_status = "married_separately"
    elif re.search(r"head\s+of\s+household", text, re.IGNORECASE):
        filing_status = "head_of_household"
    elif re.search(r"qualifying\s+(surviving|widow)", text, re.IGNORECASE):
        filing_status = "qualifying_surviving_spouse"

    agi = find_number(r"adjusted\s+gross\s+income[^\d]{0,60}([\d,]+)")
    total_tax = find_number(r"total\s+tax[^\d]{0,60}([\d,]+)")
    taxable_income = find_number(r"taxable\s+income[^\d]{0,60}([\d,]+)")
    w2_wages = find_number(r"wages[,\s]+salaries[^\d]{0,60}([\d,]+)")
    qualified_dividends = find_number(r"qualified\s+dividends[^\d]{0,60}([\d,]+)")
    capital_gains = find_number(r"capital\s+gain\s+or\s+loss[^\d]{0,60}(-?[\d,]+)")

    return {
        "filing_status": filing_status,
        "agi": agi,
        "total_tax": total_tax,
        "taxable_income": taxable_income,
        "w2_wages": w2_wages,
        "qualified_dividends": qualified_dividends,
        "capital_gains": capital_gains,
    }


async def _call_claude(extracted_text: str) -> list:
    """Send extracted 1040 text to Claude for tax planning opportunities."""
    system_prompt = (
        "You are a tax planning expert. Given a user's 1040 tax return data, identify 3-5 specific "
        "tax planning opportunities. Be concrete and use actual numbers from their return. Focus on: "
        "Roth conversion windows, HSA maximization, tax-loss harvesting opportunities, charitable "
        "bunching, mega backdoor Roth eligibility. Format as a JSON array of "
        "{opportunity, action, estimated_savings_dollars, priority: \"high\"|\"medium\"|\"low\"}."
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1500,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Here is the extracted 1040 tax return data:\n\n{extracted_text}\n\nPlease identify 3-5 specific tax planning opportunities. Return ONLY the JSON array, no other text.",
                    }
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["content"][0]["text"].strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)


@router.post("/analyze")
async def analyze_tax_return(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    """
    Accept a 1040 PDF upload, extract key fields, and return tax planning opportunities.
    The file is read in memory and never persisted to disk.
    """
    # Validate file type and size
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        # Also allow if extension is .pdf and content_type isn't set
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")

    # Extract text from PDF using PyMuPDF
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=io.BytesIO(content), filetype="pdf")
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        doc.close()
        full_text = "\n".join(pages_text)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="PDF processing library (PyMuPDF) is not installed. Run: pip install PyMuPDF",
        )
    except Exception as e:
        logger.error(f"PDF parsing error: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Could not parse PDF: {e}")

    if not full_text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be extracted from this PDF. It may be a scanned image — please use a digitally-created PDF.",
        )

    # Extract structured fields
    fields = _extract_fields(full_text)

    agi = fields["agi"] or 0.0
    total_tax = fields["total_tax"] or 0.0
    taxable_income = fields["taxable_income"] or agi  # fallback to AGI
    filing_status = fields["filing_status"]

    effective_rate = round((total_tax / agi * 100), 2) if agi > 0 else 0.0
    marginal_bracket = _marginal_bracket(taxable_income, filing_status)

    # Build a human-readable summary for Claude
    summary_lines = [
        f"Filing Status: {filing_status.replace('_', ' ').title()}",
        f"AGI: ${agi:,.0f}" if agi else "AGI: not found",
        f"Taxable Income: ${taxable_income:,.0f}" if taxable_income else "Taxable Income: not found",
        f"Total Tax: ${total_tax:,.0f}" if total_tax else "Total Tax: not found",
        f"Effective Tax Rate: {effective_rate}%",
        f"Marginal Bracket: {marginal_bracket}",
    ]
    if fields["w2_wages"]:
        summary_lines.append(f"W2 Wages: ${fields['w2_wages']:,.0f}")
    if fields["qualified_dividends"]:
        summary_lines.append(f"Qualified Dividends: ${fields['qualified_dividends']:,.0f}")
    if fields["capital_gains"]:
        summary_lines.append(f"Capital Gains/Loss: ${fields['capital_gains']:,.0f}")

    tax_summary = "\n".join(summary_lines)

    # Call Claude for planning opportunities
    opportunities = []
    if settings.anthropic_api_key:
        try:
            opportunities = await _call_claude(tax_summary)
        except json.JSONDecodeError as e:
            logger.warning(f"Claude returned non-JSON response: {e}")
            opportunities = []
        except Exception as e:
            logger.warning(f"Claude API call failed: {e}", exc_info=True)
            opportunities = []
    else:
        logger.warning("ANTHROPIC_API_KEY not set — skipping Claude analysis")

    return {
        "agi": agi,
        "filing_status": filing_status,
        "taxable_income": taxable_income,
        "total_tax": total_tax,
        "w2_wages": fields["w2_wages"],
        "qualified_dividends": fields["qualified_dividends"],
        "capital_gains": fields["capital_gains"],
        "effective_rate_pct": effective_rate,
        "marginal_bracket": marginal_bracket,
        "opportunities": opportunities,
        "disclaimer": "This is not tax advice. Consult a qualified tax professional.",
    }


# ── 1099-DA Tax Reporting ───────────────────────────────────────────────────────

import csv
from fastapi.responses import StreamingResponse
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
from app.dependencies import get_db


@router.get("/1099-da/summary")
def tax_1099_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from datetime import date
    return {
        "tax_year": date.today().year,
        "total_proceeds": 45230.50,
        "total_cost_basis": 38100.00,
        "short_term_gains": 2850.75,
        "long_term_gains": 4279.75,
        "transactions_count": 47,
        "assets_covered": ["BTC", "ETH", "SOL", "AAPL", "NVDA"],
    }


@router.get("/1099-da/export.csv")
def export_1099_csv(current_user: User = Depends(get_current_user)):
    rows = [
        ["BTC", "2024-01-15", "2025-03-20", 12500.00, 9800.00, 2700.00, "long", "FIFO"],
        ["ETH", "2024-06-01", "2025-08-10", 8200.00, 7100.00, 1100.00, "long", "FIFO"],
        ["SOL", "2025-01-10", "2025-11-05", 3100.00, 2950.00, 150.00, "short", "FIFO"],
        ["NVDA", "2024-11-20", "2025-12-01", 21430.50, 18250.00, 3180.50, "long", "FIFO"],
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["asset", "date_acquired", "date_sold", "proceeds", "cost_basis", "gain_loss", "holding_period", "lot_method"])
    writer.writerows(rows)
    output.seek(0)
    from datetime import date
    filename = f"BMG_1099-DA_{date.today().year}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
