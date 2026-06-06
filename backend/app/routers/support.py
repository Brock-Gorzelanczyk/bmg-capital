from __future__ import annotations

import logging
import re
from typing import List

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import settings
from app.dependencies import get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/support", tags=["support"])

SYSTEM_PROMPT = """You are the built-in support agent for BMG Capital, a trading & investing platform. You know every feature inside and out and help users 24/7.

Here is a complete overview of every feature you support:

DASHBOARD — Market brief, index cards (S&P 500, NASDAQ, Dow, Russell), sector performance heatmap, market news, paper portfolio widget, strategy signals widget. Powered by BMG Intelligence for the morning brief.

CHART — Candlestick/bar/line/area/Heikin-Ashi chart types. Up to 50 indicators on Plus/Premium. Drawing tools: horizontal lines, trend lines, rectangles, Fibonacci retracements, text labels. Compare overlay (type a second symbol in the top bar). Pro Mode unlocks sub-pane indicators (RSI, MACD, ADX, Stochastic, Bollinger Bands, Volume, etc.) and drawing tools (requires Plus or Premium tier). Search any ticker in the top search bar. Click any symbol on the Dashboard/Portfolio/Strategy Lab to jump to its chart.

SCREENER — Filter stocks by 19 preset strategies (CAN SLIM Leaders, Stage 2 Breakout, Momentum Surge, High RS Momentum, Power Trend, Turtle Breakout, 12-Month Momentum, Darvas Box, Quality Dip Buy, Quality Oversold, RSI Oversold, Z-Score Reversion, Volatility Squeeze, EMA Stack, Momentum Continuation, Golden Cross, MACD Crossover, Volume Surge, 52-Week High). Results link directly to the Chart page.

STRATEGY LAB — Automated paper-trading strategy that watches 191 symbols. Scans nightly at 4:05 PM ET for entries. Manages stop-losses and profit targets automatically. Tracks an equity curve over time. Portfolio starts at $100,000. Open P&L uses last known prices when market is closed so the value persists across weekends. You can see open positions, candidates being watched, closed trades with P&L, and a daily log. You can also run historical backtests across all 19 strategies covering 3 years of data.

WATCHLIST — Add/remove symbols using the search bar. Symbols in your watchlist are monitored for strategy signals.

PORTFOLIO — Tracks your real investment positions. Add portfolios and positions manually. Links to Chart for any position. Shows allocation pie chart by symbol and sector.

PAPER TRADING — Practice trading with $100,000 virtual cash. Full order ticket supports Market and Limit orders, Long (Buy) and Short (Sell). View open positions with live P&L, order history, and transaction activity. "Seed Demo" loads sample positions to explore the interface. "Reset" wipes everything and returns to $100k cash.

OPTIONS LAB — Options chain viewer with expirations and strikes, showing calls and puts with Greeks (delta, gamma, theta, vega). Basic access on Plus, full Flow data (unusual options activity) on Premium.

ALERTS — Set price alerts (above/below a target), percent change alerts, or technical condition alerts. Free: 10 alerts. Plus: 100 alerts. Premium: unlimited. Triggered alerts appear in Notifications.

NOTIFICATIONS — All triggered alerts and system messages appear here. Mark as read, delete, or go to the chart for any symbol.

NEWS — Latest financial news feed from multiple sources, with source attribution and timestamps.

EARNINGS — Upcoming earnings calendar showing companies reporting soon, with consensus estimates and historical results.

RESEARCH — Deep-dive analysis, analyst ratings, price targets, and fundamental data for any stock.

DISCOVERY — Sector heatmaps, IPO calendar, insider transactions, and thematic investment themes.

TRADE JOURNAL — Manually log every trade you make. Record: symbol, entry/exit price, setup type (breakout, pullback, etc.), position size, mood (1-5), confidence (1-5), notes, lessons learned, and a star rating. Tracks: win rate, total P&L, average mood, percentage of entries with notes.

COMMUNITY FEED — Share trade ideas and market insights with other members of the platform.

LEARNING CENTER — Structured courses covering: Trading Fundamentals, Technical Analysis, Options Basics, and Trading Psychology. Features daily streaks, achievement badges, quizzes after each lesson, daily challenges, and completion certificates.

UPGRADE / PRICING:
- Free: 1yr chart history, 5 indicators, 1 watchlist, 10 alerts, community support
- Plus: $5.99/month or $59/year — 5yr history, 20 indicators, 10 watchlists, 100 alerts, email support, Pro Mode on charts, strategy backtesting, Options Basic
- Premium: $19.99/month or $199/year — 20yr history, 50 indicators, unlimited watchlists/alerts, live chat support, Level 2 quotes, Options Flow data
- FREE tier upgrade: Portfolio balance ≥ $10k → Plus free. ≥ $50k → Premium free.
- 7-day free trial available for Plus and Premium.

SETTINGS — Account info (username, email), subscription status, billing portal (manage/cancel Stripe subscription), sign out.

TIPS:
- To add an indicator: open Chart, click the indicators button in the toolbar (requires Pro Mode for sub-pane indicators).
- To set an alert: go to Alerts page, click "+" and fill in symbol, condition, and price target.
- To see your P&L: Paper Trading shows Day P&L and Total P&L in the stats bar. Portfolio shows unrealized P&L per position.
- The Strategy Lab runs automatically at 4:05 PM ET each trading day. You can also click "Run Now" to force a scan.
- Trade Journal entries are private to your account.

Answer concisely and helpfully. Use bullet points for multi-step answers. If a feature requires a higher tier, mention the upgrade path. Never give financial or investment advice. Do not speculate on future stock prices."""

# ─── Rule-based fallback ──────────────────────────────────────────────────────

_QA: list[tuple[list[str], str]] = [
    (["hello", "hi", "hey", "howdy", "sup", "what's up"],
     "Hi! I'm your BMG Capital support agent, available 24/7. What can I help you with today?"),

    (["what can you do", "what do you know", "help", "what features"],
     "I can answer questions about any feature in BMG Capital — Charts, Paper Trading, Strategy Lab, Portfolio, Screener, Alerts, Watchlist, Trade Journal, Learning Center, and your subscription. What would you like to know?"),

    (["pro mode", "promode", "pro tier", "sub-pane", "rsi indicator", "macd indicator"],
     "**Pro Mode** is a chart enhancement available on **Plus and Premium** plans.\n\nIt unlocks:\n- **Sub-pane indicators**: RSI, MACD, ADX, Stochastic, Bollinger Bands, Volume\n- **Drawing tools**: horizontal lines, trend lines, rectangles, Fibonacci retracements, text labels\n- **Compare overlay**: type a second symbol to overlay it on the same chart\n\nToggle Pro Mode using the **Simple/Pro** button in the top bar. Upgrade to Plus ($5.99/mo) to unlock it."),

    (["chart", "candle", "indicator", "drawing", "technicals", "ta"],
     "The **Chart** page supports candlestick, bar, line, area, and Heikin-Ashi types. Search any ticker in the top bar or click a symbol anywhere in the app.\n\n**Pro Mode** (Plus/Premium) unlocks:\n- Sub-pane indicators: RSI, MACD, ADX, Stochastic, Bollinger Bands, Volume\n- Drawing tools: horizontal lines, trend lines, rectangles, Fibonacci, text labels\n- Compare overlay: type a second symbol to overlay it\n\nFree users get basic price display with up to 5 indicators."),

    (["paper trad", "paper account", "virtual", "practice", "fake money", "demo"],
     "**Paper Trading** gives you $100,000 in virtual cash to practice with.\n\n- Place **Market** or **Limit** orders, buy or sell any symbol\n- Track open positions with live P&L, day P&L, and total return\n- View order history and transaction log\n- **Seed Demo** loads sample positions to explore\n- **Reset** wipes the account back to $100k\n\nThe floating **+** button opens a new order ticket from any tab."),

    (["strategy lab", "strategy", "automated", "signals", "candidates", "19 strategies", "scan"],
     "**Strategy Lab** is an automated paper-trading engine that:\n\n- Watches 191 symbols across 19 proven strategies (CAN SLIM, Momentum, Breakout, Mean Reversion, and more)\n- Scans every evening at 4:05 PM ET for entry signals\n- Automatically manages stop-losses and profit targets\n- Tracks an equity curve and full trade history\n- Starts with a $100,000 paper portfolio\n\nYou can also click **Run Now** to force a scan, or **Historical Backtests** to see 3-year performance across all strategies."),

    (["backtest", "historical", "past performance", "3 year", "returns"],
     "**Strategy Backtests** simulate all 19 strategies against 3 years of historical data. Access it from the Strategy Lab page — click the 'Historical Backtests' tab. Results show total return, CAGR, win rate, average win/loss, max drawdown, and Sharpe ratio for each strategy. This feature requires **Plus or Premium**."),

    (["screener", "filter", "scan stocks", "find stocks"],
     "The **Screener** lets you filter stocks by 19 preset strategies including:\n- CAN SLIM Leaders, Stage 2 Breakout, Momentum Surge\n- Golden Cross, MACD Crossover, 52-Week High\n- RSI Oversold, Quality Dip Buy, Volatility Squeeze\n\nClick any result to open its chart. Results update daily."),

    (["alert", "notification", "notify", "price target"],
     "**Alerts** notify you when a stock hits your target:\n\n1. Go to **Alerts** in the sidebar\n2. Click **+** to add a new alert\n3. Enter symbol, condition (above/below price, % change, or technical trigger), and your target\n\nTriggered alerts appear in **Notifications** (bell icon). Limits: Free = 10, Plus = 100, Premium = unlimited."),

    (["watchlist", "watch", "follow", "track symbol"],
     "To add a symbol to your **Watchlist**:\n1. Go to the **Watchlist** section\n2. Type a ticker in the search bar and click Add\n\nSymbols on your watchlist are monitored for strategy signals. Free accounts get 1 watchlist; Plus gets 10; Premium gets unlimited."),

    (["portfolio", "position", "holding", "real trades", "real money"],
     "**Portfolio** tracks your actual investment positions (not paper trades).\n\n- Add a portfolio and then add positions manually\n- Shows market value, day P&L, unrealized P&L, and total return\n- Allocation charts break down by symbol and sector\n- Click any symbol to open its chart\n\nThis is separate from Paper Trading — use Portfolio to track real-world holdings."),

    (["journal", "trade log", "log trade", "record trade"],
     "**Trade Journal** lets you log every trade in detail:\n\n- Symbol, entry/exit price, setup type (breakout, pullback, etc.)\n- Position size, mood rating (1-5), confidence (1-5)\n- Notes, lessons learned, and a star rating\n\nYour journal tracks: win rate, total P&L, average mood, and % of entries with notes. It's private to your account — great for building discipline."),

    (["learn", "course", "education", "lesson", "quiz", "streak", "badge", "certificate"],
     "The **Learning Center** has structured courses on:\n- Trading Fundamentals\n- Technical Analysis\n- Options Basics\n- Trading Psychology\n\nEach lesson ends with a quiz. Complete lessons to build your daily streak, earn badges, and unlock completion certificates. Daily challenges keep you engaged. Find it under **Learn** in the bottom nav."),

    (["options", "calls", "puts", "greeks", "delta", "theta", "flow"],
     "**Options Lab** shows the options chain for any symbol — all expirations and strikes with calls and puts, plus Greeks (delta, gamma, theta, vega).\n\n- Basic access: **Plus** tier\n- Options Flow (unusual options activity): **Premium** tier\n\nSearch a symbol, select an expiration date, and explore the chain."),

    (["news", "feed", "headlines"],
     "The **News** page shows real-time market news from multiple sources with timestamps. You can also see the latest 8 headlines directly on the Dashboard in the Morning Brief section."),

    (["earnings", "calendar", "reporting", "estimates"],
     "The **Earnings** page shows upcoming earnings announcements with:\n- Expected report date\n- Analyst consensus estimates (EPS, revenue)\n- Historical actuals for past quarters\n\nGreat for planning trades around earnings events."),

    (["research", "analyst", "rating", "target price", "fundamental"],
     "**Research** provides deep-dive data for any stock:\n- Analyst ratings and consensus\n- Price targets (high/low/average)\n- Key fundamental metrics\n\nSearch a symbol in the Research section to pull up its data."),

    (["discovery", "sector", "heatmap", "ipo", "insider", "theme"],
     "**Discovery** shows market-wide data:\n- **Sector Heatmap** — see which sectors are moving\n- **IPO Calendar** — upcoming and recent IPOs\n- **Insider Transactions** — recent insider buys/sells\n- **Thematic Themes** — AI, Clean Energy, Semiconductors, and more"),

    (["community", "social", "feed", "share idea", "post"],
     "The **Community Feed** lets you share trade ideas and market insights with other BMG Capital users. Post your setups, comment on others' ideas, and follow top contributors."),

    (["price", "cost", "subscription", "free", "plus", "premium", "tier", "plan", "upgrade", "how much", "pricing"],
     "**BMG Capital Plans:**\n\n🆓 **Free** — 1yr chart history, 5 indicators, 1 watchlist, 10 alerts\n\n⚡ **Plus** — $5.99/mo or $59/yr\n- 5yr history, 20 indicators, 10 watchlists, 100 alerts\n- Pro Mode charts, strategy backtesting, Options Basic\n\n👑 **Premium** — $19.99/mo or $199/yr\n- 20yr history, 50 indicators, unlimited watchlists/alerts\n- Level 2 quotes, Options Flow, live chat support\n\n✨ **Free upgrade**: Portfolio ≥ $10k → Plus free. ≥ $50k → Premium free.\n7-day free trial available on all paid plans."),

    (["cancel", "unsubscribe", "billing", "invoice", "refund"],
     "To manage your subscription:\n1. Go to **Settings** (gear icon or bottom nav)\n2. Click **Manage billing & invoices** — this opens the Stripe billing portal\n3. From there you can cancel, update payment method, or download invoices\n\nCancellations take effect at the end of your current billing period."),

    (["sign out", "logout", "log out", "sign off"],
     "To sign out:\n1. Go to **Settings** (gear icon)\n2. Scroll to **Session** section\n3. Click the red **Sign out** button\n\nYou'll be taken back to the login screen."),

    (["password", "change password", "forgot password", "reset password"],
     "Password management is handled at account creation. If you've forgotten your password, use the login screen's \"Forgot password\" flow. To change it, please contact support."),

    (["p&l", "pnl", "profit", "loss", "return", "gain"],
     "P&L is tracked in multiple places:\n\n- **Paper Trading** → top bar shows Total Equity, Day's P&L, Total P&L, and Cash Available\n- **Portfolio** → each position shows Day P&L and Total Return with % change\n- **Strategy Lab** → tracks Open P&L, Day's P&L, Win Rate, Expectancy, and Max Drawdown\n\nDay P&L resets at market open each session (compares current price vs. previous close)."),

    (["weekend", "market closed", "after hours", "p&l zero", "strategy not updating"],
     "When the market is closed (weekends, holidays), live prices aren't available. The app uses **last known prices** so your P&L doesn't show $0 over the weekend — it carries over the Friday closing values. The Strategy Lab also persists all trades and shows last known P&L until the market reopens."),

    (["how does", "what is", "explain", "tell me about"],
     "I'd be happy to explain! Could you be more specific about which feature you'd like to understand? For example:\n- How does the Strategy Lab work?\n- What is the Screener?\n- How does Paper Trading work?\n- What is Pro Mode?"),
]


def _rule_based_reply(question: str) -> str | None:
    q = question.lower()
    for keywords, answer in _QA:
        if any(kw in q for kw in keywords):
            return answer
    return None


# ─── Router ────────────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class SupportBody(BaseModel):
    messages: List[Message]


@router.post("/chat")
async def support_chat(
    body: SupportBody,
    _: User = Depends(get_current_user),
):
    messages = [{"role": m.role, "content": m.content} for m in body.messages[-12:]]
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )

    # Try Anthropic first (fastest, most capable)
    if settings.anthropic_api_key:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 500,
                        "system": SYSTEM_PROMPT,
                        "messages": messages,
                    },
                )
                resp.raise_for_status()
                return {"reply": resp.json()["content"][0]["text"]}
        except Exception as e:
            logger.warning(f"Support chat Anthropic error: {e}", exc_info=True)

    # Try OpenAI fallback
    if settings.openai_api_key:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "max_tokens": 500,
                        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                    },
                )
                resp.raise_for_status()
                return {"reply": resp.json()["choices"][0]["message"]["content"]}
        except Exception as e:
            logger.warning(f"Support chat OpenAI error: {e}", exc_info=True)

    # Rule-based fallback — works with no API keys
    reply = _rule_based_reply(last_user)
    if reply:
        return {"reply": reply}

    # Generic catch-all
    return {
        "reply": (
            "I can help with any feature in BMG Capital! Here are some things you can ask me about:\n\n"
            "• **Charts & Indicators** — how to add indicators, drawing tools, Pro Mode\n"
            "• **Paper Trading** — placing orders, viewing P&L, resetting your account\n"
            "• **Strategy Lab** — how it works, backtests, reading signals\n"
            "• **Alerts & Watchlists** — setting up price alerts, managing symbols\n"
            "• **Pricing & Plans** — Free vs Plus vs Premium, how to upgrade\n"
            "• **Portfolio & Trade Journal** — tracking positions and logging trades\n\n"
            "What would you like to know?"
        )
    }
