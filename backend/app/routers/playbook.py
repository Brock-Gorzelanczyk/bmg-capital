"""
BMG Capital — Founder Launch Playbook Router
Prefix: /api/playbook
Admin-only: all endpoints require current_user.email == "demo@bmgcapital.com"
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.playbook import PlaybookPhase, PlaybookWeek, PlaybookTask, PlaybookStart

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/playbook", tags=["playbook"])

ADMIN_EMAILS = {"demo@bmgcapital.com", "32bgorzelanczyk@gmail.com"}

# ── Admin guard ───────────────────────────────────────────────────────────────

def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TaskOut(BaseModel):
    id: int
    week_id: int
    day_focus: str
    title: str
    description: str
    effort_hours: float
    priority: str
    status: str
    completion_note: Optional[str]
    completed_at: Optional[datetime]
    sort_order: int

    model_config = {"from_attributes": True}


class WeekOut(BaseModel):
    id: int
    phase_id: int
    week_number: int
    title: str
    day_start: int
    day_end: int
    outcome_target: str
    status: str
    tasks: list[TaskOut] = []

    model_config = {"from_attributes": True}


class PhaseOut(BaseModel):
    id: int
    phase_number: int
    name: str
    day_start: int
    day_end: int
    outcome_target: str
    weeks: list[WeekOut] = []

    model_config = {"from_attributes": True}


class StatusOut(BaseModel):
    day_number: int
    current_phase: Optional[str]
    current_week: Optional[str]
    total_tasks: int
    completed_tasks: int
    completion_pct: float
    started_at: Optional[datetime]


class TaskPatch(BaseModel):
    status: Optional[str] = None
    completion_note: Optional[str] = None


class TaskCreate(BaseModel):
    week_id: int
    title: str
    description: str = ""
    effort_hours: float = 4.0
    priority: str = "P1"
    day_focus: str = ""


# ── Static data ───────────────────────────────────────────────────────────────

DO_NOT_DO = [
    "Build a native mobile app before Series A",
    "Add real-money trading (brokerage license required)",
    "Hire a full engineering team pre-product-market-fit",
    "Build social features that distract from core value prop",
    "Pursue enterprise sales before self-serve is working",
    "Add gamification points/badges just to increase DAU",
    "Launch paid tiers before 100 active beta users",
    "Rewrite the stack because of tech debt anxiety",
    "Spend on paid acquisition before organic retention is proven",
    "Partner with another startup before your own house is in order",
]

DECISIONS = [
    {
        "question": "Should I add a feature an investor requested?",
        "answer": "Only if it's already on the roadmap. Investor-requested features rarely align with what users need. Politely acknowledge, then redirect to the demo.",
    },
    {
        "question": "A bug appeared during a live demo — what do I do?",
        "answer": "Acknowledge it calmly ('good catch, we're on it'), pivot to a working feature, and fix it within 24 hours. Never apologize excessively.",
    },
    {
        "question": "An investor wants a pilot with their portfolio company. Do I take it?",
        "answer": "Yes, but only if it won't delay the seed close by more than 30 days. Set a 60-day pilot with clear success metrics up front.",
    },
    {
        "question": "Should I lower the valuation cap to close faster?",
        "answer": "Not before Day 60. If meetings are happening and feedback is positive, hold the cap. Desperation repricing signals weakness.",
    },
    {
        "question": "A competitor just launched something similar. How do I respond?",
        "answer": "Say nothing publicly. Internally, assess the delta, then accelerate one differentiated feature. Investors back teams, not features.",
    },
    {
        "question": "Should I take a revenue deal that requires custom work?",
        "answer": "Only if it's under 20 hours of engineering and converts to a repeatable product feature. Otherwise it's consulting, not product.",
    },
    {
        "question": "I got a warm intro to a top-tier VC. When do I take the meeting?",
        "answer": "After Day 46 (Launch Prep phase). Before then, you risk burning the intro on a non-demo-ready product. Ask to schedule in 4–6 weeks.",
    },
    {
        "question": "Should I pivot if Day 45 demo feedback is consistently negative?",
        "answer": "Only if 3+ independent investors cite the same core objection. One data point is noise. Three is a signal. Document each objection verbatim.",
    },
]


# ── Seed data ─────────────────────────────────────────────────────────────────

_SEED: list[dict] = [
    {
        "phase_number": 1,
        "name": "Stabilize",
        "day_start": 1,
        "day_end": 14,
        "outcome_target": "BMG is demo-credible. App stops looking broken.",
        "weeks": [
            {
                "week_number": 1,
                "title": "Bug & Performance Sprint",
                "day_start": 1,
                "day_end": 7,
                "outcome_target": "All P0 bugs fixed, performance baseline set",
                "tasks": [
                    {
                        "day_focus": "Day 1-2",
                        "title": "Performance Sprint",
                        "description": "Brotli compression, cache headers, fix /api/tiers/me 500, /portfolio/streak 422, double /api/ prefix bug, /options crash",
                        "effort_hours": 8,
                        "priority": "P0",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 3-5",
                        "title": "Strategy Lab Bug Sprint",
                        "description": "Demo data non-determinism, Drawdown panel rebuild, Dashboard index values",
                        "effort_hours": 12,
                        "priority": "P0",
                        "sort_order": 1,
                    },
                    {
                        "day_focus": "Day 6-7",
                        "title": "Demo Personas + API Key",
                        "description": "Set ANTHROPIC_API_KEY on Railway. Seed 4 deterministic demo personas.",
                        "effort_hours": 6,
                        "priority": "P0",
                        "sort_order": 2,
                    },
                ],
            },
            {
                "week_number": 2,
                "title": "Visual Polish",
                "day_start": 8,
                "day_end": 14,
                "outcome_target": "Demo-ready visual quality across core screens",
                "tasks": [
                    {
                        "day_focus": "Day 8-10",
                        "title": "Visual Polish Trifecta",
                        "description": "Tabular figures, Mercury 3-tier surfaces, ambient lime orb on balance cards",
                        "effort_hours": 6,
                        "priority": "P1",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 11-12",
                        "title": "Market Status Badges",
                        "description": "Asset-class-aware status badge, replace coral Offline with amber",
                        "effort_hours": 4,
                        "priority": "P1",
                        "sort_order": 1,
                    },
                    {
                        "day_focus": "Day 13-14",
                        "title": "Demo Loop Dry Run",
                        "description": "Walk demo loop 3x, time it, fix blockers",
                        "effort_hours": 4,
                        "priority": "P0",
                        "sort_order": 2,
                    },
                ],
            },
        ],
    },
    {
        "phase_number": 2,
        "name": "Differentiate",
        "day_start": 15,
        "day_end": 45,
        "outcome_target": "Five demo wow moments live",
        "weeks": [
            {
                "week_number": 3,
                "title": "Daily Challenge + Streak",
                "day_start": 15,
                "day_end": 21,
                "outcome_target": "Wordle-style market puzzle, streak counter, shareable result",
                "tasks": [
                    {
                        "day_focus": "Day 15-16",
                        "title": "Build Puzzle Primitive",
                        "description": "Core daily challenge question engine with randomized selection and deterministic daily seed",
                        "effort_hours": 6,
                        "priority": "P1",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 16",
                        "title": "Seed 50 Questions",
                        "description": "Author 50 market trivia / analysis questions across 5 categories",
                        "effort_hours": 4,
                        "priority": "P1",
                        "sort_order": 1,
                    },
                    {
                        "day_focus": "Day 17-18",
                        "title": "Streak Counter",
                        "description": "Track daily completions, calculate streak, show fire animation on milestone days",
                        "effort_hours": 4,
                        "priority": "P1",
                        "sort_order": 2,
                    },
                    {
                        "day_focus": "Day 19-20",
                        "title": "Shareable Result Card",
                        "description": "Generate shareable image card with score, streak, and BMG branding",
                        "effort_hours": 5,
                        "priority": "P1",
                        "sort_order": 3,
                    },
                    {
                        "day_focus": "Day 21",
                        "title": "Dashboard Tile",
                        "description": "Add challenge widget to dashboard showing today's streak and quick-start button",
                        "effort_hours": 2,
                        "priority": "P1",
                        "sort_order": 4,
                    },
                ],
            },
            {
                "week_number": 4,
                "title": "AI Co-Pilot Proper",
                "day_start": 22,
                "day_end": 28,
                "outcome_target": "Cmd+K from anywhere, streaming, conversation history",
                "tasks": [
                    {
                        "day_focus": "Day 22-23",
                        "title": "Cmd+K Modal",
                        "description": "Global keyboard shortcut (Cmd+K / Ctrl+K) opens co-pilot modal with context-aware prompt",
                        "effort_hours": 8,
                        "priority": "P0",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 23-24",
                        "title": "Tool Call Pills",
                        "description": "Inline pill indicators when AI calls tools (search, chart, portfolio read)",
                        "effort_hours": 5,
                        "priority": "P0",
                        "sort_order": 1,
                    },
                    {
                        "day_focus": "Day 24",
                        "title": "Citations",
                        "description": "Source attribution for AI claims — link to data source inline",
                        "effort_hours": 3,
                        "priority": "P0",
                        "sort_order": 2,
                    },
                    {
                        "day_focus": "Day 25-26",
                        "title": "Streaming Typewriter",
                        "description": "Real-time token streaming with typewriter effect, cancel button",
                        "effort_hours": 6,
                        "priority": "P0",
                        "sort_order": 3,
                    },
                    {
                        "day_focus": "Day 27-28",
                        "title": "History Per User",
                        "description": "Persist conversation history per user, last 20 messages, searchable",
                        "effort_hours": 5,
                        "priority": "P0",
                        "sort_order": 4,
                    },
                ],
            },
            {
                "week_number": 5,
                "title": "Mission Control",
                "day_start": 29,
                "day_end": 35,
                "outcome_target": "Real-time activity feed live",
                "tasks": [
                    {
                        "day_focus": "Day 29-30",
                        "title": "/mission-control Route",
                        "description": "Create full-page mission control route with live WebSocket connection",
                        "effort_hours": 6,
                        "priority": "P0",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 31-32",
                        "title": "Live Activity Feed",
                        "description": "Real-time scrolling feed of platform events — trades, alerts, AI actions, logins",
                        "effort_hours": 8,
                        "priority": "P0",
                        "sort_order": 1,
                    },
                    {
                        "day_focus": "Day 33",
                        "title": "'BMG Did N Things' Hero",
                        "description": "Animated counter showing total platform actions in last 24h / 7d / 30d",
                        "effort_hours": 3,
                        "priority": "P0",
                        "sort_order": 2,
                    },
                    {
                        "day_focus": "Day 34-35",
                        "title": "Filterable Log",
                        "description": "Filter activity by event type, user, date range. Export to CSV.",
                        "effort_hours": 5,
                        "priority": "P0",
                        "sort_order": 3,
                    },
                ],
            },
            {
                "week_number": 6,
                "title": "Pitch Mode in Settings",
                "day_start": 36,
                "day_end": 45,
                "outcome_target": "Pitch hub with deck, personas, scripts",
                "tasks": [
                    {
                        "day_focus": "Day 36-37",
                        "title": "/settings/pitch Hub",
                        "description": "Admin-only settings section with pitch hub landing — links to deck, personas, scripts",
                        "effort_hours": 4,
                        "priority": "P0",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 38-41",
                        "title": "15-Slide Deck",
                        "description": "Full interactive pitch deck: problem, solution, market, product, traction, team, ask",
                        "effort_hours": 16,
                        "priority": "P0",
                        "sort_order": 1,
                    },
                    {
                        "day_focus": "Day 42",
                        "title": "Video Player",
                        "description": "Embed demo video with chapter markers and auto-advance to relevant section",
                        "effort_hours": 4,
                        "priority": "P0",
                        "sort_order": 2,
                    },
                    {
                        "day_focus": "Day 43",
                        "title": "Talking Points",
                        "description": "Per-slide talking points visible in presenter mode only",
                        "effort_hours": 3,
                        "priority": "P0",
                        "sort_order": 3,
                    },
                    {
                        "day_focus": "Day 44-45",
                        "title": "Persona Switcher",
                        "description": "Quick-switch between 4 demo personas — loads different portfolio profiles",
                        "effort_hours": 5,
                        "priority": "P0",
                        "sort_order": 4,
                    },
                ],
            },
        ],
    },
    {
        "phase_number": 3,
        "name": "Launch Prep",
        "day_start": 46,
        "day_end": 75,
        "outcome_target": "Inbound investor meetings booked, beta users active",
        "weeks": [
            {
                "week_number": 7,
                "title": "Landing Page + Waitlist",
                "day_start": 46,
                "day_end": 52,
                "outcome_target": "One page live, waitlist capturing emails",
                "tasks": [
                    {
                        "day_focus": "Day 46-47",
                        "title": "Landing Page Build",
                        "description": "Single-page site: hero, product screenshot, 3 value props, waitlist form. Deploy to Vercel.",
                        "effort_hours": 8,
                        "priority": "P1",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 48-52",
                        "title": "Waitlist Email Automation",
                        "description": "Confirm email → add to list → weekly drip with 1 insight/week until beta invite",
                        "effort_hours": 4,
                        "priority": "P1",
                        "sort_order": 1,
                    },
                ],
            },
            {
                "week_number": 8,
                "title": "Demo Video",
                "day_start": 53,
                "day_end": 59,
                "outcome_target": "90-second demo recorded, edited, uploaded",
                "tasks": [
                    {
                        "day_focus": "Day 53-55",
                        "title": "Record Demo Video",
                        "description": "Screen record 90-second product walkthrough hitting 5 wow moments. Use Loom or ScreenFlow.",
                        "effort_hours": 6,
                        "priority": "P0",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 56-59",
                        "title": "Edit + Publish",
                        "description": "Add captions, zoom effects, BMG branding overlay. Upload to YouTube (unlisted) + landing page.",
                        "effort_hours": 8,
                        "priority": "P0",
                        "sort_order": 1,
                    },
                ],
            },
            {
                "week_number": 9,
                "title": "Investor Outreach Begins",
                "day_start": 60,
                "day_end": 66,
                "outcome_target": "15 first meetings booked",
                "tasks": [
                    {
                        "day_focus": "Day 60-62",
                        "title": "Build Target List",
                        "description": "50 investors: seed-stage fintech VCs, angels with trading/fintech background. Score by fit.",
                        "effort_hours": 6,
                        "priority": "P0",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 63-66",
                        "title": "Send First 25 Intros",
                        "description": "Warm intro via mutual connections first. Cold outreach with personalized 3-sentence email. Track responses.",
                        "effort_hours": 8,
                        "priority": "P0",
                        "sort_order": 1,
                    },
                ],
            },
            {
                "week_number": 10,
                "title": "Pitch Rehearsal",
                "day_start": 67,
                "day_end": 73,
                "outcome_target": "Deck iterated 3x based on feedback",
                "tasks": [
                    {
                        "day_focus": "Day 67-70",
                        "title": "First Round Meetings",
                        "description": "Run first 5-8 investor meetings. Record objections verbatim. Score each meeting 1-5.",
                        "effort_hours": 20,
                        "priority": "P1",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 71-73",
                        "title": "Iterate Deck",
                        "description": "Update pitch based on recurring objections. Remove slides that kill energy. Add missing traction data.",
                        "effort_hours": 5,
                        "priority": "P1",
                        "sort_order": 1,
                    },
                ],
            },
            {
                "week_number": 11,
                "title": "Beta Waitlist Activation",
                "day_start": 74,
                "day_end": 75,
                "outcome_target": "10 users off waitlist, bugs documented",
                "tasks": [
                    {
                        "day_focus": "Day 74-75",
                        "title": "Activate 10 Beta Users",
                        "description": "Invite first 10 from waitlist. 30-min onboarding call each. Document every bug and friction point.",
                        "effort_hours": 10,
                        "priority": "P1",
                        "sort_order": 0,
                    },
                ],
            },
        ],
    },
    {
        "phase_number": 4,
        "name": "Close",
        "day_start": 76,
        "day_end": 90,
        "outcome_target": "One signed term sheet OR clear pivot signal",
        "weeks": [
            {
                "week_number": 12,
                "title": "Investor Meetings + Close",
                "day_start": 76,
                "day_end": 90,
                "outcome_target": "Term sheet by Day 90",
                "tasks": [
                    {
                        "day_focus": "Day 76-82",
                        "title": "Multiple Meetings Per Week",
                        "description": "Target 3+ investor meetings/week. Use social proof from earlier meetings to create urgency.",
                        "effort_hours": 30,
                        "priority": "P0",
                        "sort_order": 0,
                    },
                    {
                        "day_focus": "Day 76-90",
                        "title": "Demo → Pitch → Follow-Up Within 24h",
                        "description": "Send follow-up email within 24h of every meeting. Include one new data point or traction update.",
                        "effort_hours": 10,
                        "priority": "P0",
                        "sort_order": 1,
                    },
                    {
                        "day_focus": "Day 83-87",
                        "title": "Iterate Pitch Each Round",
                        "description": "After each batch of 5 meetings, update deck. Focus on tightening the narrative arc.",
                        "effort_hours": 5,
                        "priority": "P0",
                        "sort_order": 2,
                    },
                    {
                        "day_focus": "Day 88-90",
                        "title": "Target Term Sheet",
                        "description": "Push for commitment from top 3 leads. If no term sheet, document lessons and set new 30-day goal.",
                        "effort_hours": 8,
                        "priority": "P0",
                        "sort_order": 3,
                    },
                ],
            },
        ],
    },
]


def _seed_playbook(db: Session) -> None:
    """Idempotent seed — only runs if no phases exist."""
    if db.query(PlaybookPhase).count() > 0:
        return

    for phase_data in _SEED:
        weeks_data = phase_data.pop("weeks", [])
        phase = PlaybookPhase(**phase_data)
        db.add(phase)
        db.flush()

        for week_data in weeks_data:
            tasks_data = week_data.pop("tasks", [])
            week = PlaybookWeek(phase_id=phase.id, **week_data)
            db.add(week)
            db.flush()

            for task_data in tasks_data:
                task = PlaybookTask(week_id=week.id, **task_data)
                db.add(task)

        # restore for next iteration safety
        phase_data["weeks"] = weeks_data

    # Seed the start row
    if db.query(PlaybookStart).count() == 0:
        db.add(PlaybookStart())

    db.commit()
    logger.info("Playbook seeded successfully")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusOut)
def get_status(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> StatusOut:
    start = db.query(PlaybookStart).first()
    started_at = start.started_at if start else None

    if started_at:
        delta = (datetime.utcnow() - started_at).days + 1
        day_number = min(delta, 90)
    else:
        day_number = 1

    # Find current phase
    current_phase_name: Optional[str] = None
    current_week_title: Optional[str] = None

    phase = (
        db.query(PlaybookPhase)
        .filter(PlaybookPhase.day_start <= day_number, PlaybookPhase.day_end >= day_number)
        .first()
    )
    if phase:
        current_phase_name = phase.name
        week = (
            db.query(PlaybookWeek)
            .filter(PlaybookWeek.phase_id == phase.id, PlaybookWeek.day_start <= day_number, PlaybookWeek.day_end >= day_number)
            .first()
        )
        if week:
            current_week_title = week.title

    total = db.query(PlaybookTask).count()
    completed = db.query(PlaybookTask).filter(PlaybookTask.status == "complete").count()
    pct = round(completed / total * 100, 1) if total else 0.0

    return StatusOut(
        day_number=day_number,
        current_phase=current_phase_name,
        current_week=current_week_title,
        total_tasks=total,
        completed_tasks=completed,
        completion_pct=pct,
        started_at=started_at,
    )


@router.get("/phases", response_model=list[PhaseOut])
def get_phases(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[PhaseOut]:
    phases = db.query(PlaybookPhase).order_by(PlaybookPhase.phase_number).all()
    result = []
    for phase in phases:
        weeks_out = []
        for week in phase.weeks:
            weeks_out.append(WeekOut(
                id=week.id,
                phase_id=week.phase_id,
                week_number=week.week_number,
                title=week.title,
                day_start=week.day_start,
                day_end=week.day_end,
                outcome_target=week.outcome_target,
                status=week.status,
                tasks=[TaskOut.model_validate(t) for t in week.tasks],
            ))
        result.append(PhaseOut(
            id=phase.id,
            phase_number=phase.phase_number,
            name=phase.name,
            day_start=phase.day_start,
            day_end=phase.day_end,
            outcome_target=phase.outcome_target,
            weeks=weeks_out,
        ))
    return result


@router.get("/phases/{phase_id}/weeks", response_model=list[WeekOut])
def get_phase_weeks(
    phase_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[WeekOut]:
    phase = db.get(PlaybookPhase, phase_id)
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")
    return [
        WeekOut(
            id=w.id,
            phase_id=w.phase_id,
            week_number=w.week_number,
            title=w.title,
            day_start=w.day_start,
            day_end=w.day_end,
            outcome_target=w.outcome_target,
            status=w.status,
            tasks=[TaskOut.model_validate(t) for t in w.tasks],
        )
        for w in phase.weeks
    ]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: int,
    body: TaskPatch,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> TaskOut:
    task = db.get(PlaybookTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if body.status is not None:
        task.status = body.status
        if body.status == "complete" and task.completed_at is None:
            task.completed_at = datetime.utcnow()
        elif body.status != "complete":
            task.completed_at = None

    if body.completion_note is not None:
        task.completion_note = body.completion_note

    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.post("/tasks", response_model=TaskOut)
def create_task(
    body: TaskCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> TaskOut:
    week = db.get(PlaybookWeek, body.week_id)
    if not week:
        raise HTTPException(status_code=404, detail="Week not found")

    max_order = max((t.sort_order for t in week.tasks), default=-1)
    task = PlaybookTask(
        week_id=body.week_id,
        title=body.title,
        description=body.description,
        effort_hours=body.effort_hours,
        priority=body.priority,
        day_focus=body.day_focus,
        sort_order=max_order + 1,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.get("/do-not-do")
def get_do_not_do(_admin: User = Depends(_require_admin)) -> dict:
    return {"items": DO_NOT_DO}


@router.get("/decisions")
def get_decisions(_admin: User = Depends(_require_admin)) -> dict:
    return {"decisions": DECISIONS}


@router.post("/init")
def init_playbook(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> dict:
    _seed_playbook(db)
    total = db.query(PlaybookPhase).count()
    return {"seeded": True, "phases": total}
