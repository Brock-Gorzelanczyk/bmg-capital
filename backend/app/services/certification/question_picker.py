from __future__ import annotations

import random
from collections import defaultdict

from sqlalchemy.orm import Session

from app.db.models.exams import ExamQuestion


def pick_questions(db: Session, track_slug: str, n: int = 50, seed: int | None = None) -> list[int]:
    """
    Weighted random selection of n questions from the active pool for track_slug.
    Stratified: proportional representation across difficulty levels (1-5).
    Returns list of question IDs in randomized order.
    """
    rng = random.Random(seed)

    # Load all active questions for this track
    questions = (
        db.query(ExamQuestion)
        .filter(
            ExamQuestion.track_slug == track_slug,
            ExamQuestion.is_active.is_(True),
        )
        .all()
    )

    if not questions:
        return []

    # Group by difficulty
    by_difficulty: dict[int, list[ExamQuestion]] = defaultdict(list)
    for q in questions:
        by_difficulty[q.difficulty].append(q)

    total_available = len(questions)
    n = min(n, total_available)

    # Proportional allocation across difficulty levels
    selected_ids: list[int] = []

    if n == total_available:
        # Take everything
        selected_ids = [q.id for q in questions]
    else:
        # Proportional stratified sampling
        allocated: dict[int, int] = {}
        total_allocated = 0
        for diff, qs in sorted(by_difficulty.items()):
            proportion = len(qs) / total_available
            count = max(1, round(proportion * n))
            allocated[diff] = min(count, len(qs))
            total_allocated += allocated[diff]

        # Adjust to exactly n
        while total_allocated > n:
            # Remove from the largest group
            largest = max(allocated, key=lambda d: allocated[d])
            if allocated[largest] > 1:
                allocated[largest] -= 1
                total_allocated -= 1
            else:
                break

        while total_allocated < n:
            # Add from groups that have room
            candidates = [
                d for d, cnt in allocated.items()
                if cnt < len(by_difficulty[d])
            ]
            if not candidates:
                break
            chosen = rng.choice(candidates)
            allocated[chosen] += 1
            total_allocated += 1

        for diff, count in allocated.items():
            pool = by_difficulty[diff]
            selected_ids.extend([q.id for q in rng.sample(pool, min(count, len(pool)))])

    rng.shuffle(selected_ids)
    return selected_ids
