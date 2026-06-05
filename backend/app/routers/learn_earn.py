from __future__ import annotations
from datetime import timezone, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.earn_rewards import LearnEarnLesson, EarnReward

router = APIRouter(prefix="/api/learn-earn", tags=["learn-earn"])

SEED_LESSONS = [
    {
        "lesson_id": "etf-basics",
        "title": "What is an ETF?",
        "description": "Learn how Exchange-Traded Funds work, why they're popular, and how to evaluate them.",
        "sponsor": "iShares",
        "reward_amount": 3.0,
        "reward_symbol": "SPY",
        "quiz_questions": [
            {
                "question": "What does ETF stand for?",
                "options": ["Exchange-Traded Fund", "Equity Transfer Fund", "Electronic Trading Framework", "Extended Term Finance"],
                "correct_idx": 0,
                "explanation": "ETF stands for Exchange-Traded Fund — a basket of securities that trades on an exchange like a stock."
            },
            {
                "question": "Which of the following is a key advantage of ETFs over mutual funds?",
                "options": ["Higher guaranteed returns", "Can be traded intraday like stocks", "Always actively managed", "No expense ratios"],
                "correct_idx": 1,
                "explanation": "ETFs trade on exchanges throughout the day, unlike mutual funds which only price at end of day."
            },
            {
                "question": "The expense ratio of an ETF represents:",
                "options": ["The broker's commission", "The annual cost as a % of assets", "The bid-ask spread", "The tax on dividends"],
                "correct_idx": 1,
                "explanation": "The expense ratio is the annual fee charged by the fund, expressed as a percentage of your investment."
            }
        ]
    },
    {
        "lesson_id": "dca-strategy",
        "title": "Dollar-Cost Averaging Explained",
        "description": "How investing a fixed amount regularly can reduce risk and build wealth over time.",
        "sponsor": "Vanguard",
        "reward_amount": 5.0,
        "reward_symbol": "QQQ",
        "quiz_questions": [
            {
                "question": "Dollar-cost averaging means:",
                "options": ["Buying only when prices are low", "Investing a fixed amount at regular intervals", "Averaging your portfolio returns", "Splitting investments across currencies"],
                "correct_idx": 1,
                "explanation": "DCA means investing a fixed dollar amount at regular intervals, regardless of price."
            },
            {
                "question": "When prices fall, DCA causes you to automatically:",
                "options": ["Buy fewer shares", "Stop investing", "Buy more shares for the same dollar amount", "Sell existing shares"],
                "correct_idx": 2,
                "explanation": "When prices fall, your fixed dollar amount buys more shares — naturally buying more when stocks are cheaper."
            },
            {
                "question": "The main psychological benefit of DCA is:",
                "options": ["Guaranteeing profits", "Removing the pressure to time the market", "Eliminating all investment risk", "Maximizing short-term gains"],
                "correct_idx": 1,
                "explanation": "DCA removes the stress of trying to time the market — you invest consistently regardless of conditions."
            }
        ]
    },
    {
        "lesson_id": "bonds-vs-equities",
        "title": "Bonds vs Equities",
        "description": "Understand the risk/return tradeoffs between stocks and bonds in a balanced portfolio.",
        "sponsor": None,
        "reward_amount": 3.0,
        "reward_symbol": "BND",
        "quiz_questions": [
            {
                "question": "Which asset class typically has higher long-term returns but more volatility?",
                "options": ["Government bonds", "Equities (stocks)", "Money market funds", "Treasury bills"],
                "correct_idx": 1,
                "explanation": "Equities historically outperform bonds over long periods, but with significantly more short-term volatility."
            },
            {
                "question": "When interest rates rise, bond prices generally:",
                "options": ["Rise as well", "Stay the same", "Fall", "Become more liquid"],
                "correct_idx": 2,
                "explanation": "Bond prices move inversely to interest rates — when rates rise, existing bonds become less attractive, pushing prices down."
            },
            {
                "question": "A 60/40 portfolio refers to:",
                "options": ["60% bonds / 40% stocks", "60% stocks / 40% bonds", "60% US / 40% international", "60% large cap / 40% small cap"],
                "correct_idx": 1,
                "explanation": "The classic 60/40 portfolio is 60% stocks and 40% bonds — balancing growth potential with stability."
            }
        ]
    },
    {
        "lesson_id": "options-basics",
        "title": "Options Basics: Calls & Puts",
        "description": "An introduction to options contracts — what they are, how they're priced, and basic strategies.",
        "sponsor": None,
        "reward_amount": 10.0,
        "reward_symbol": "SPY",
        "quiz_questions": [
            {
                "question": "A call option gives you the right to:",
                "options": ["Sell shares at a set price", "Buy shares at a set price", "Receive dividends", "Short a stock"],
                "correct_idx": 1,
                "explanation": "A call option gives the holder the right (not obligation) to BUY shares at the strike price before expiration."
            },
            {
                "question": "What does 'in the money' mean for a call option?",
                "options": ["The option has expired", "The stock price is above the strike price", "The option costs more than $1", "The stock price is below the strike price"],
                "correct_idx": 1,
                "explanation": "A call option is 'in the money' when the current stock price is above the strike price — it has intrinsic value."
            },
            {
                "question": "Options lose value as expiration approaches due to:",
                "options": ["Delta decay", "Theta decay (time decay)", "Vega compression", "Gamma squeeze"],
                "correct_idx": 1,
                "explanation": "Theta represents time decay — options lose value daily as expiration approaches, all else equal."
            }
        ]
    },
    {
        "lesson_id": "reit-basics",
        "title": "What is a REIT?",
        "description": "Real Estate Investment Trusts — how to invest in real estate without owning property.",
        "sponsor": None,
        "reward_amount": 5.0,
        "reward_symbol": "VNQ",
        "quiz_questions": [
            {
                "question": "REITs are required to distribute what percentage of taxable income as dividends?",
                "options": ["50%", "75%", "90%", "100%"],
                "correct_idx": 2,
                "explanation": "REITs must distribute at least 90% of taxable income to shareholders as dividends — that's what makes their yields high."
            },
            {
                "question": "Which type of REIT owns actual physical properties?",
                "options": ["Mortgage REIT", "Equity REIT", "Hybrid REIT", "Synthetic REIT"],
                "correct_idx": 1,
                "explanation": "Equity REITs own and operate income-producing properties. Mortgage REITs invest in real estate debt."
            },
            {
                "question": "REITs are most sensitive to changes in:",
                "options": ["Oil prices", "Interest rates", "Gold prices", "Currency exchange rates"],
                "correct_idx": 1,
                "explanation": "REITs are rate-sensitive — rising interest rates increase borrowing costs and make their yields less competitive."
            }
        ]
    },
    {
        "lesson_id": "crypto-btc-eth",
        "title": "Crypto: Bitcoin vs Ethereum",
        "description": "The two largest cryptocurrencies — their differences, use cases, and investment considerations.",
        "sponsor": None,
        "reward_amount": 5.0,
        "reward_symbol": "BTC",
        "quiz_questions": [
            {
                "question": "Bitcoin's primary value proposition is:",
                "options": ["Smart contract platform", "Digital gold / store of value", "Decentralized social network", "Gaming currency"],
                "correct_idx": 1,
                "explanation": "Bitcoin is designed primarily as a scarce, decentralized store of value — often called 'digital gold'."
            },
            {
                "question": "Ethereum's 'Proof of Stake' upgrade (The Merge) primarily:",
                "options": ["Increased transaction fees", "Reduced energy consumption by ~99.5%", "Doubled ETH supply", "Removed smart contracts"],
                "correct_idx": 1,
                "explanation": "The Merge switched Ethereum from energy-intensive Proof of Work to Proof of Stake, cutting energy use by ~99.5%."
            },
            {
                "question": "Bitcoin's maximum supply is capped at:",
                "options": ["10 million", "21 million", "100 million", "Unlimited"],
                "correct_idx": 1,
                "explanation": "Bitcoin has a hard cap of 21 million coins — this scarcity is central to its value proposition."
            }
        ]
    },
]

@router.get("/lessons")
def list_lessons(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lessons = db.query(LearnEarnLesson).filter_by(is_active=True).all()
    completed_ids = {r.lesson_id for r in db.query(EarnReward).filter_by(user_id=current_user.id).all()}
    return [
        {
            "lesson_id": l.lesson_id,
            "title": l.title,
            "description": l.description,
            "sponsor": l.sponsor,
            "reward_amount": l.reward_amount,
            "reward_symbol": l.reward_symbol,
            "question_count": len(l.quiz_questions or []),
            "already_completed": l.lesson_id in completed_ids,
        }
        for l in lessons
    ]

@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lesson = db.query(LearnEarnLesson).filter_by(lesson_id=lesson_id, is_active=True).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    return {
        "lesson_id": lesson.lesson_id,
        "title": lesson.title,
        "description": lesson.description,
        "sponsor": lesson.sponsor,
        "reward_amount": lesson.reward_amount,
        "reward_symbol": lesson.reward_symbol,
        "quiz_questions": [
            {"question": q["question"], "options": q["options"]}
            for q in (lesson.quiz_questions or [])
        ],
    }

class CompleteBody(BaseModel):
    answers: list[int]

@router.post("/lessons/{lesson_id}/complete")
def complete_lesson(lesson_id: str, body: CompleteBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lesson = db.query(LearnEarnLesson).filter_by(lesson_id=lesson_id, is_active=True).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    already = db.query(EarnReward).filter_by(user_id=current_user.id, lesson_id=lesson_id).first()
    if already:
        raise HTTPException(400, "Already completed this lesson")
    questions = lesson.quiz_questions or []
    correct_answers = [q["correct_idx"] for q in questions]
    explanations = [q["explanation"] for q in questions]
    score = sum(1 for i, a in enumerate(body.answers) if i < len(correct_answers) and a == correct_answers[i])
    passed = score >= 2
    reward_amount = lesson.reward_amount if passed else None
    reward_symbol = lesson.reward_symbol if passed else None
    reward = EarnReward(
        user_id=current_user.id,
        lesson_id=lesson_id,
        quiz_score=score,
        reward_amount=reward_amount,
        reward_symbol=reward_symbol,
        status="pending" if passed else "expired",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30) if passed else None,
    )
    db.add(reward)
    if passed:
        lesson.total_completions = (lesson.total_completions or 0) + 1
    db.commit()
    return {
        "passed": passed,
        "score": score,
        "total_questions": len(questions),
        "reward_amount": reward_amount,
        "reward_symbol": reward_symbol,
        "correct_answers": correct_answers,
        "explanations": explanations,
    }

@router.get("/my-rewards")
def get_rewards(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rewards = db.query(EarnReward).filter_by(user_id=current_user.id).order_by(EarnReward.earned_at.desc()).all()
    return [{"lesson_id": r.lesson_id, "reward_amount": r.reward_amount, "reward_symbol": r.reward_symbol, "status": r.status, "earned_at": r.earned_at.isoformat()} for r in rewards]

@router.get("/stats")
def get_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total = db.query(LearnEarnLesson).filter_by(is_active=True).count()
    rewards = db.query(EarnReward).filter_by(user_id=current_user.id).all()
    completed = len(rewards)
    total_earned = sum(r.reward_amount or 0 for r in rewards if r.status in ("pending", "credited"))
    return {"total_earned": round(total_earned, 2), "lessons_completed": completed, "lessons_available": total}

@router.post("/seed")
def seed_lessons(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.email not in {"demo@bmgcapital.com", "32bgorzelanczyk@gmail.com"}:
        raise HTTPException(403, "Admin only")
    for data in SEED_LESSONS:
        existing = db.query(LearnEarnLesson).filter_by(lesson_id=data["lesson_id"]).first()
        if not existing:
            db.add(LearnEarnLesson(**data))
    db.commit()
    return {"seeded": len(SEED_LESSONS)}
