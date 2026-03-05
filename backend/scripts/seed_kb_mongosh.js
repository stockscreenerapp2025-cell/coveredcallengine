// Knowledge Base Seed Script (mongosh)
// Run on the production server:
//   docker exec -it cce_prod-mongo-1 mongosh "mongodb://cce_prod_user:ProdPass123@localhost:27017/cce_prod_db?authSource=admin" --file /tmp/seed_kb_mongosh.js
//
// Or copy-paste into an interactive mongosh session.

const now = new Date().toISOString();

function makeArticle(question, answer, category) {
  return {
    id: UUID().toString(),
    question,
    answer,
    category,
    active: true,
    created_at: now,
    updated_at: now,
    usage_count: 0
  };
}

const articles = [
  // ── GETTING STARTED ──────────────────────────────────────────────────────
  makeArticle(
    "What is Covered Call Engine?",
    "Covered Call Engine is a research and scanning platform designed to help users identify option strategies such as Covered Calls and Poor Man's Covered Calls.\n\n• It provides market scans, filters, and analytics\n• It does not place trades or issue buy/sell signals\n• Outputs are informational, not recommendations\n\nImportant: All results require independent due diligence by the user. No strategy guarantees profits.",
    "how_it_works"
  ),
  makeArticle(
    "Is Covered Call Engine a Trading Signal Platform?",
    "No. Covered Call Engine is not a signal service and does not provide guaranteed trading outcomes.\n\n• Results are based on predefined research criteria\n• Market conditions can change rapidly\n• Execution decisions remain fully with the user\n\nImportant: Users are responsible for validating suitability with their own risk tolerance.",
    "how_it_works"
  ),
  makeArticle(
    "Who Is This Platform Suitable For?",
    "The platform is suitable for users who understand basic options concepts and want decision support, not automation.\n\n• Best for educational, analytical, and income-focused traders\n• Not suitable for users seeking guaranteed or automated returns",
    "how_it_works"
  ),
  makeArticle(
    "Why Do Scan Results Change During the Day?",
    "Options prices, IV, and liquidity change continuously during market hours.\n\n• Real-time market activity impacts scans\n• Bid-ask spreads and volume fluctuate\n• Results may differ from earlier snapshots",
    "how_it_works"
  ),
  makeArticle(
    "What Due Diligence Is Required Before Trading?",
    "Users must independently validate every trade idea.\n\n• Confirm pricing with your broker\n• Assess personal risk and capital requirements\n• Review earnings, news, and market conditions",
    "how_it_works"
  ),

  // ── STRATEGY ─────────────────────────────────────────────────────────────
  makeArticle(
    "What Is a Covered Call Strategy?",
    "A Covered Call involves owning shares and selling a call option against them.\n\n• Generates option premium income\n• Limits upside beyond the strike price\n• Still carries downside stock risk\n\nImportant: Not risk-free and not suitable in all market conditions.",
    "educational"
  ),
  makeArticle(
    "What Is a Poor Man's Covered Call (PMCC)?",
    "PMCC is a diagonal spread using a long-dated call instead of stock ownership.\n\n• Lower capital requirement than traditional Covered Calls\n• Higher complexity and risk\n• Sensitive to volatility and time decay",
    "educational"
  ),
  makeArticle(
    'What Does "Slightly Bullish" Mean?',
    "It means expecting modest price appreciation or sideways movement.\n\n• Ideal for income-focused option selling\n• Not suitable for strong bullish breakouts",
    "educational"
  ),
  makeArticle(
    "When Are Covered Calls Less Suitable?",
    "Covered Calls may underperform in strong bullish or highly bearish markets.\n\n• Upside can be capped\n• Downside risk remains on the underlying stock",
    "educational"
  ),
  makeArticle(
    "Are These Strategies Guaranteed to Make Money?",
    "No. There are no guaranteed returns in options trading.\n\n• Losses are possible\n• Past performance does not predict future outcomes",
    "educational"
  ),
  makeArticle(
    "Does the Platform Adjust for Personal Risk Tolerance?",
    "No. Risk tolerance must be assessed by the user.\n\n• The platform provides research filters only\n• Users decide suitability and execution",
    "educational"
  ),

  // ── SCANS & FILTERS ───────────────────────────────────────────────────────
  makeArticle(
    "How Do Pre-Built Scans Work?",
    "Pre-built scans apply predefined criteria to market data.\n\n• Designed for common option strategies\n• Criteria are educational, not predictive",
    "screener"
  ),
  makeArticle(
    "Why Does a Scan Sometimes Return No Results?",
    "Market conditions may not meet the selected criteria.\n\n• Low liquidity\n• Inadequate IV\n• Insufficient option chains",
    "screener"
  ),
  makeArticle(
    "What Is Implied Volatility (IV)?",
    "IV reflects the market's expectation of future price movement.\n\n• Higher IV often increases option premiums\n• IV can change rapidly",
    "screener"
  ),
  makeArticle(
    "What Is Delta Used For?",
    "Delta estimates how much an option price may change relative to the stock.\n\n• Used for probability approximation\n• Not a guarantee of outcome",
    "screener"
  ),
  makeArticle(
    "Why Are Liquidity Filters Important?",
    "Liquidity impacts trade execution quality.\n\n• Wider spreads increase cost\n• Low volume can delay execution",
    "screener"
  ),
  makeArticle(
    "Can I Rely on a Single Scan Result?",
    "No. Scan results should be starting points for analysis.\n\n• Always validate manually\n• Combine with news, charts, and fundamentals",
    "screener"
  ),

  // ── TROUBLESHOOTING ───────────────────────────────────────────────────────
  makeArticle(
    "Why Is Options Data Loading Slowly?",
    "Options chains are data-heavy and depend on market conditions.\n\n• High market activity increases load times\n• Network and browser factors may apply",
    "technical"
  ),
  makeArticle(
    "Why Don't Prices Match My Broker Exactly?",
    "Different data sources and update timings can cause variations.\n\n• Brokers may use proprietary pricing\n• Minor discrepancies are normal",
    "technical"
  ),
  makeArticle(
    "Why Did a Stock Disappear From a Scan?",
    "It may no longer meet the scan criteria.\n\n• Changes in IV, volume, or price\n• Filters dynamically re-evaluate results",
    "technical"
  ),
  makeArticle(
    "What Should I Do If Data Looks Incorrect?",
    "Refresh the page and verify with an external source.\n\n• Temporary delays can occur\n• Contact support if issues persist",
    "technical"
  ),
  makeArticle(
    "Does the Platform Work Outside Market Hours?",
    "Yes, but data may reflect the previous market close.\n\n• No live updates on weekends or holidays",
    "technical"
  ),
  makeArticle(
    "Is This a Technical Issue or Market Behavior?",
    "Most discrepancies are market-driven, not system errors.\n\n• Volatility and liquidity change rapidly\n• Always cross-check before acting",
    "technical"
  ),

  // ── BILLING ───────────────────────────────────────────────────────────────
  makeArticle(
    "Does a Subscription Guarantee Profits?",
    "No. A subscription provides access to tools, not outcomes.",
    "billing"
  ),
  makeArticle(
    "What Happens When My Trial Ends?",
    "Access may be limited unless upgraded.\n\n• No automatic trade execution occurs",
    "billing"
  ),
  makeArticle(
    "Can I Cancel My Subscription Anytime?",
    "Yes, cancellations stop future billing.\n\n• Past usage fees are not refunded unless stated otherwise",
    "billing"
  ),
  makeArticle(
    "Are There Refunds for Trading Losses?",
    "No. Trading decisions and outcomes are solely the user's responsibility.",
    "billing"
  ),

  // ── DATA & CALCULATIONS ───────────────────────────────────────────────────
  makeArticle(
    "Where Does Market Data Come From?",
    "The platform uses third-party market data providers.\n\n• Data accuracy depends on provider availability\n• Delays and revisions may occur",
    "educational"
  ),
  makeArticle(
    "Are Probabilities Exact?",
    "No. Probabilities are estimates, not guarantees.\n\n• Based on market assumptions\n• Real-world outcomes can differ",
    "educational"
  ),
  makeArticle(
    "Is Historical Data Predictive?",
    "No. Historical data is informational only.\n\n• Market conditions evolve\n• Past performance does not ensure future results",
    "educational"
  ),
];

// Clear existing and insert fresh
const existing = db.knowledge_base.countDocuments({});
if (existing > 0) {
  print(`Clearing ${existing} existing articles...`);
  db.knowledge_base.deleteMany({});
}

const result = db.knowledge_base.insertMany(articles);
print(`\n✅ Inserted ${result.insertedIds ? Object.keys(result.insertedIds).length : articles.length} KB articles\n`);

// Summary by category
const cats = db.knowledge_base.aggregate([
  { $group: { _id: "$category", count: { $sum: 1 } } },
  { $sort: { _id: 1 } }
]).toArray();

cats.forEach(c => print(`   ${c._id}: ${c.count} articles`));
