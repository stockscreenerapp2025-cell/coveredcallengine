"""
Knowledge Base Seed Script
Inserts all 30 KB articles into the knowledge_base collection.
Run inside the backend Docker container:
  docker exec -it cce_prod-backend-1 python scripts/seed_knowledge_base.py
"""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from motor.motor_asyncio import AsyncIOMotorClient
import os

MONGO_URL = os.getenv("MONGO_URL", "mongodb://cce_prod_user:ProdPass123@cce_prod-mongo-1:27017/cce_prod_db?authSource=admin")
DB_NAME = os.getenv("DB_NAME", "cce_prod_db")

ARTICLES = [
    # ── GETTING STARTED ─────────────────────────────────────────────────────
    {
        "question": "What is Covered Call Engine?",
        "category": "how_it_works",
        "answer": (
            "Covered Call Engine is a research and scanning platform designed to help users identify option strategies "
            "such as Covered Calls and Poor Man's Covered Calls.\n\n"
            "• It provides market scans, filters, and analytics\n"
            "• It does not place trades or issue buy/sell signals\n"
            "• Outputs are informational, not recommendations\n\n"
            "Important: All results require independent due diligence by the user. No strategy guarantees profits."
        ),
    },
    {
        "question": "Is Covered Call Engine a Trading Signal Platform?",
        "category": "how_it_works",
        "answer": (
            "No. Covered Call Engine is not a signal service and does not provide guaranteed trading outcomes.\n\n"
            "• Results are based on predefined research criteria\n"
            "• Market conditions can change rapidly\n"
            "• Execution decisions remain fully with the user\n\n"
            "Important: Users are responsible for validating suitability with their own risk tolerance."
        ),
    },
    {
        "question": "Who Is This Platform Suitable For?",
        "category": "how_it_works",
        "answer": (
            "The platform is suitable for users who understand basic options concepts and want decision support, not automation.\n\n"
            "• Best for educational, analytical, and income-focused traders\n"
            "• Not suitable for users seeking guaranteed or automated returns"
        ),
    },
    {
        "question": "Why Do Scan Results Change During the Day?",
        "category": "how_it_works",
        "answer": (
            "Options prices, IV, and liquidity change continuously during market hours.\n\n"
            "• Real-time market activity impacts scans\n"
            "• Bid-ask spreads and volume fluctuate\n"
            "• Results may differ from earlier snapshots"
        ),
    },
    {
        "question": "What Due Diligence Is Required Before Trading?",
        "category": "how_it_works",
        "answer": (
            "Users must independently validate every trade idea.\n\n"
            "• Confirm pricing with your broker\n"
            "• Assess personal risk and capital requirements\n"
            "• Review earnings, news, and market conditions"
        ),
    },

    # ── STRATEGY ────────────────────────────────────────────────────────────
    {
        "question": "What Is a Covered Call Strategy?",
        "category": "educational",
        "answer": (
            "A Covered Call involves owning shares and selling a call option against them.\n\n"
            "• Generates option premium income\n"
            "• Limits upside beyond the strike price\n"
            "• Still carries downside stock risk\n\n"
            "Important: Not risk-free and not suitable in all market conditions."
        ),
    },
    {
        "question": "What Is a Poor Man's Covered Call (PMCC)?",
        "category": "educational",
        "answer": (
            "PMCC is a diagonal spread using a long-dated call instead of stock ownership.\n\n"
            "• Lower capital requirement than traditional Covered Calls\n"
            "• Higher complexity and risk\n"
            "• Sensitive to volatility and time decay"
        ),
    },
    {
        "question": "What Does \"Slightly Bullish\" Mean?",
        "category": "educational",
        "answer": (
            "It means expecting modest price appreciation or sideways movement.\n\n"
            "• Ideal for income-focused option selling\n"
            "• Not suitable for strong bullish breakouts"
        ),
    },
    {
        "question": "When Are Covered Calls Less Suitable?",
        "category": "educational",
        "answer": (
            "Covered Calls may underperform in strong bullish or highly bearish markets.\n\n"
            "• Upside can be capped\n"
            "• Downside risk remains on the underlying stock"
        ),
    },
    {
        "question": "Are These Strategies Guaranteed to Make Money?",
        "category": "educational",
        "answer": (
            "No. There are no guaranteed returns in options trading.\n\n"
            "• Losses are possible\n"
            "• Past performance does not predict future outcomes"
        ),
    },
    {
        "question": "Does the Platform Adjust for Personal Risk Tolerance?",
        "category": "educational",
        "answer": (
            "No. Risk tolerance must be assessed by the user.\n\n"
            "• The platform provides research filters only\n"
            "• Users decide suitability and execution"
        ),
    },

    # ── SCANS & FILTERS ──────────────────────────────────────────────────────
    {
        "question": "How Do Pre-Built Scans Work?",
        "category": "screener",
        "answer": (
            "Pre-built scans apply predefined criteria to market data.\n\n"
            "• Designed for common option strategies\n"
            "• Criteria are educational, not predictive"
        ),
    },
    {
        "question": "Why Does a Scan Sometimes Return No Results?",
        "category": "screener",
        "answer": (
            "Market conditions may not meet the selected criteria.\n\n"
            "• Low liquidity\n"
            "• Inadequate IV\n"
            "• Insufficient option chains"
        ),
    },
    {
        "question": "What Is Implied Volatility (IV)?",
        "category": "screener",
        "answer": (
            "IV reflects the market's expectation of future price movement.\n\n"
            "• Higher IV often increases option premiums\n"
            "• IV can change rapidly"
        ),
    },
    {
        "question": "What Is Delta Used For?",
        "category": "screener",
        "answer": (
            "Delta estimates how much an option price may change relative to the stock.\n\n"
            "• Used for probability approximation\n"
            "• Not a guarantee of outcome"
        ),
    },
    {
        "question": "Why Are Liquidity Filters Important?",
        "category": "screener",
        "answer": (
            "Liquidity impacts trade execution quality.\n\n"
            "• Wider spreads increase cost\n"
            "• Low volume can delay execution"
        ),
    },
    {
        "question": "Can I Rely on a Single Scan Result?",
        "category": "screener",
        "answer": (
            "No. Scan results should be starting points for analysis.\n\n"
            "• Always validate manually\n"
            "• Combine with news, charts, and fundamentals"
        ),
    },

    # ── TROUBLESHOOTING ──────────────────────────────────────────────────────
    {
        "question": "Why Is Options Data Loading Slowly?",
        "category": "technical",
        "answer": (
            "Options chains are data-heavy and depend on market conditions.\n\n"
            "• High market activity increases load times\n"
            "• Network and browser factors may apply"
        ),
    },
    {
        "question": "Why Don't Prices Match My Broker Exactly?",
        "category": "technical",
        "answer": (
            "Different data sources and update timings can cause variations.\n\n"
            "• Brokers may use proprietary pricing\n"
            "• Minor discrepancies are normal"
        ),
    },
    {
        "question": "Why Did a Stock Disappear From a Scan?",
        "category": "technical",
        "answer": (
            "It may no longer meet the scan criteria.\n\n"
            "• Changes in IV, volume, or price\n"
            "• Filters dynamically re-evaluate results"
        ),
    },
    {
        "question": "What Should I Do If Data Looks Incorrect?",
        "category": "technical",
        "answer": (
            "Refresh the page and verify with an external source.\n\n"
            "• Temporary delays can occur\n"
            "• Contact support if issues persist"
        ),
    },
    {
        "question": "Does the Platform Work Outside Market Hours?",
        "category": "technical",
        "answer": (
            "Yes, but data may reflect the previous market close.\n\n"
            "• No live updates on weekends or holidays"
        ),
    },
    {
        "question": "Is This a Technical Issue or Market Behavior?",
        "category": "technical",
        "answer": (
            "Most discrepancies are market-driven, not system errors.\n\n"
            "• Volatility and liquidity change rapidly\n"
            "• Always cross-check before acting"
        ),
    },

    # ── BILLING ──────────────────────────────────────────────────────────────
    {
        "question": "Does a Subscription Guarantee Profits?",
        "category": "billing",
        "answer": (
            "No. A subscription provides access to tools, not outcomes."
        ),
    },
    {
        "question": "What Happens When My Trial Ends?",
        "category": "billing",
        "answer": (
            "Access may be limited unless upgraded.\n\n"
            "• No automatic trade execution occurs"
        ),
    },
    {
        "question": "Can I Cancel My Subscription Anytime?",
        "category": "billing",
        "answer": (
            "Yes, cancellations stop future billing.\n\n"
            "• Past usage fees are not refunded unless stated otherwise"
        ),
    },
    {
        "question": "Are There Refunds for Trading Losses?",
        "category": "billing",
        "answer": (
            "No. Trading decisions and outcomes are solely the user's responsibility."
        ),
    },

    # ── DATA & CALCULATIONS ──────────────────────────────────────────────────
    {
        "question": "Where Does Market Data Come From?",
        "category": "educational",
        "answer": (
            "The platform uses third-party market data providers.\n\n"
            "• Data accuracy depends on provider availability\n"
            "• Delays and revisions may occur"
        ),
    },
    {
        "question": "Are Probabilities Exact?",
        "category": "educational",
        "answer": (
            "No. Probabilities are estimates, not guarantees.\n\n"
            "• Based on market assumptions\n"
            "• Real-world outcomes can differ"
        ),
    },
    {
        "question": "Is Historical Data Predictive?",
        "category": "educational",
        "answer": (
            "No. Historical data is informational only.\n\n"
            "• Market conditions evolve\n"
            "• Past performance does not ensure future results"
        ),
    },
]


async def seed():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    existing = await db.knowledge_base.count_documents({})
    if existing > 0:
        print(f"⚠  knowledge_base already has {existing} articles. Clearing before re-seeding...")
        await db.knowledge_base.delete_many({})

    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for art in ARTICLES:
        docs.append({
            "id": str(uuid4()),
            "question": art["question"],
            "answer": art["answer"],
            "category": art["category"],
            "active": True,
            "created_at": now,
            "updated_at": now,
            "usage_count": 0,
        })

    result = await db.knowledge_base.insert_many(docs)
    print(f"✅  Inserted {len(result.inserted_ids)} KB articles into '{DB_NAME}.knowledge_base'")

    # Print summary by category
    from collections import Counter
    cats = Counter(d["category"] for d in docs)
    for cat, count in sorted(cats.items()):
        print(f"   {cat}: {count} articles")

    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
