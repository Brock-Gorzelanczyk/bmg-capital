from __future__ import annotations

# Import all models so Alembic can discover them via Base.metadata
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.db.models.portfolio import Portfolio, Position
from app.db.models.alert import AlertConfig, AlertTrigger, SignalState
from app.db.models.screen import SavedScreen
from app.db.models.bar_cache import BarCache
from app.db.models.strategy import StrategyTrade, DailyLog, DailyEquitySnapshot, StrategyQuizCompletion
from app.db.models.users import User
from app.db.models.paper import PaperAccount, PaperPosition, PaperOrder, PaperTransaction, PaperDailySnapshot
from app.db.models.learn import UserProgress, LessonCompletion, QuizAttempt, UserBadge, DailyChallenge
from app.db.models.notifications import Notification, NotificationPrefs
from app.db.models.profile import UserProfile
from app.db.models.journal import JournalEntry
from app.db.models.social import Post, PostLike, Comment, UserFollow
from app.db.models.tier import UserTier
from app.db.models.chart_drawings import ChartDrawing
from app.db.models.chart_analysis import ChartAnalysis
from app.db.models.recap import DailyRecap
from app.db.models.strategy_definition import StrategyDefinition
from app.db.models.workspace import UserWorkspace
from app.db.models.monitoring import MonitoringResult, AuditLog, LoginAttempt
from app.db.models.net_worth import NetWorthAccount, NetWorthSnapshot
from app.db.models.rule import UserRule
from app.db.models.pod import Pod, PodPosition
from app.db.models.estate import BeneficiaryRecord, DigitalAssetRecord
from app.db.models.engagement import MarketChallenge, MarketChallengeAttempt, LeagueCohort, LeaguePoints  # noqa: F401
from app.db.models.robo import RiskProfile, RoboGoal, CorePortfolio, DirectIndexPortfolio, RebalanceLog, WashSaleGuard  # noqa: F401
from app.db.models.autonomous import AutonomousAction, AutonomousGuardrail, AutonomousDigest  # noqa: F401
from app.db.models.autopilot import AutopilotPolicy, AutopilotGuardrail, AutopilotAction  # noqa: F401

__all__ = [
    "Watchlist", "WatchlistItem", "Portfolio", "Position",
    "AlertConfig", "AlertTrigger", "SignalState", "SavedScreen",
    "BarCache", "StrategyTrade", "DailyLog", "DailyEquitySnapshot", "StrategyQuizCompletion", "User",
    "PaperAccount", "PaperPosition", "PaperOrder", "PaperTransaction", "PaperDailySnapshot",
    "UserProgress", "LessonCompletion", "QuizAttempt", "UserBadge", "DailyChallenge",
    "Notification", "NotificationPrefs",
    "UserProfile", "JournalEntry",
    "Post", "PostLike", "Comment", "UserFollow",
    "UserTier",
    "ChartDrawing",
    "ChartAnalysis",
    "DailyRecap",
    "StrategyDefinition",
    "UserWorkspace",
    "MonitoringResult", "AuditLog", "LoginAttempt",
    "NetWorthAccount", "NetWorthSnapshot",
    "UserRule",
    "Pod", "PodPosition",
    "BeneficiaryRecord", "DigitalAssetRecord",
    "MarketChallenge", "MarketChallengeAttempt", "LeagueCohort", "LeaguePoints",
    "RiskProfile", "RoboGoal", "CorePortfolio", "DirectIndexPortfolio", "RebalanceLog", "WashSaleGuard",
    "AutonomousAction", "AutonomousGuardrail", "AutonomousDigest",
    "AutopilotPolicy", "AutopilotGuardrail", "AutopilotAction",
]
