import { useState } from 'react';
import { ChevronDown, ChevronRight, BookOpen, BarChart3, TrendingUp, Play, Wallet, Search, HelpCircle } from 'lucide-react';

const sections = [
  {
    id: 'getting-started',
    icon: <BookOpen className="w-5 h-5 text-emerald-400" />,
    title: 'Getting Started',
    color: 'emerald',
    articles: [
      {
        title: 'What is a Covered Call?',
        content: `A covered call is an options strategy where you own 100 shares of a stock and sell a call option against those shares.

**How it works:**
1. You own 100 shares of a stock (e.g. AAPL at $180)
2. You sell a call option at a higher strike price (e.g. $185 strike, 30 days out)
3. You collect a premium immediately (e.g. $150)
4. If the stock stays below $185 at expiry → option expires worthless, you keep the $150
5. If the stock rises above $185 → your shares get "called away" at $185 (you profit from stock gain + premium)

**Best used when:** You own stock and want to generate monthly income while you hold it.`
      },
      {
        title: 'What is a PMCC (Poor Man\'s Covered Call)?',
        content: `A PMCC (Poor Man's Covered Call) lets you replicate a covered call without owning 100 shares.

**How it works:**
1. Buy a deep ITM LEAPS call (180+ days out, delta 0.65+) — this acts like owning the stock at a fraction of the cost
2. Sell a short-term OTM call (21–60 days, delta 0.15–0.30) against it
3. Collect premium every month by rolling the short call

**Example:**
- Stock at $150
- Buy LEAPS: $130 strike, 9 months out, costs $2,800
- Sell short call: $155 strike, 30 days out, collect $150
- Net capital at risk: $2,650 (vs $15,000 to own 100 shares)

**Best used when:** You want covered call income but don't have capital to buy 100 shares.`
      },
      {
        title: 'How to use the platform — step by step',
        content: `**Step 1 — Screener**
Go to the Screener page. The engine scans 900+ stocks nightly and shows the best covered call setups. Look for:
- High IV Rank (above 50% is good)
- Delta between 0.20–0.35 (safer OTM)
- DTE between 21–45 days
- Premium Yield above 1%

**Step 2 — Add to Simulator**
Click SIMULATE on any opportunity. This adds it to your Simulator as a paper trade so you can track it without risking real money.

**Step 3 — Monitor in Simulator**
Go to Simulator. Your trades are sorted by Annualized ROI. Use the 🤖 Manage button for AI analysis on any open trade.

**Step 4 — Portfolio (for real trades)**
If you have real IBKR trades, go to Portfolio → Import CSV to upload your IBKR Activity Statement. The engine will automatically group your trades into covered call cycles.`
      }
    ]
  },
  {
    id: 'screener',
    icon: <Search className="w-5 h-5 text-sky-400" />,
    title: 'Screener',
    color: 'sky',
    articles: [
      {
        title: 'Understanding the Screener columns',
        content: `**Symbol** — Stock ticker

**Stock Price** — Current price of the underlying stock

**Strike** — The call option strike price being suggested

**Expiry / DTE** — Days to expiration. 21–45 days is the sweet spot for covered calls (theta decay is fastest)

**Delta** — Probability the option expires ITM. 0.20–0.35 = conservative (20–35% chance of assignment). Higher delta = more premium but higher assignment risk

**IV / IV Rank** — Implied Volatility. IV Rank shows where current IV sits relative to the past year. Above 50 = elevated IV = good time to sell options

**Bid / Premium Yield** — Bid is what you'd receive. Premium Yield = bid / stock price × 100. Above 1% per month is solid

**Score** — Our composite score (0–100). Combines ROI, IV Rank, delta quality, and liquidity. Above 60 = strong setup`
      },
      {
        title: 'How to filter for the best setups',
        content: `**For income-focused trades:**
- IV Rank > 40
- Delta 0.20–0.30 (less assignment risk)
- DTE 28–45
- Premium Yield > 1%

**For more aggressive yield:**
- IV Rank > 60
- Delta 0.30–0.40
- DTE 21–30

**For ETFs (safer):**
- Filter by ETF toggle
- SPY, QQQ, IWM — lower premium but very liquid

**Red flags to avoid:**
- Very wide bid-ask spreads (illiquid)
- IV Rank below 20 (cheap premiums)
- Earnings within DTE window (huge risk — avoid selling options into earnings)`
      }
    ]
  },
  {
    id: 'pmcc',
    icon: <TrendingUp className="w-5 h-5 text-violet-400" />,
    title: 'PMCC Scanner',
    color: 'violet',
    articles: [
      {
        title: 'Understanding PMCC results',
        content: `**LEAP Strike / Ask** — The deep ITM long call you'd buy. Look for delta 0.65+ (deeper ITM = more like owning shares)

**LEAP DTE** — Should be 180–730 days. Longer = more time, higher cost but less time decay pressure

**Short Strike / Bid** — The OTM call you'd sell each cycle. This is your income

**Net Debit** — Total cost = LEAP Ask − Short Bid. This is your capital at risk

**ROI Cycle** — Short premium / Net Debit × 100. This is your return for this cycle (typically 30 days)

**ROI Annualized** — ROI Cycle × (365 / DTE). Annualized comparison

**Synthetic Premium %** — How much above stock price you're paying for the LEAPS position. Under 5% is good

**Score** — Composite quality score. Above 60 = solid PMCC setup`
      },
      {
        title: 'PMCC risk management',
        content: `**The golden rule:** Short call strike must always be above your LEAP breakeven (LEAP strike + net debit)

**Assignment risk:** If the short call goes deep ITM before expiry, you may be assigned. For PMCC this is bad — you'd have to buy shares to cover. Always roll before assignment.

**When to roll the short call:**
- DTE reaches 7–14 days (time to roll to next month)
- Delta exceeds 0.50 (stock moving against you)
- Use the Simulator Manage button for AI roll suggestions

**When to close the entire PMCC:**
- Short call is deep ITM and can't be rolled for a credit
- LEAP value has dropped significantly
- Fundamentals of the stock have changed`
      }
    ]
  },
  {
    id: 'simulator',
    icon: <Play className="w-5 h-5 text-blue-400" />,
    title: 'Simulator',
    color: 'blue',
    articles: [
      {
        title: 'How the Simulator works',
        content: `The Simulator is a paper trading tracker. It does not use real money.

**Adding trades:**
Click SIMULATE on any Screener or PMCC result. The trade is saved with your entry price, strike, expiry, and premium.

**Prices update automatically:**
Every time you load the Simulator, prices refresh. You'll see current stock price, current delta, DTE remaining, and unrealized P/L.

**Trade lifecycle:**
- Open → trade is active
- Rolled → you rolled the short call to a new expiry
- Expired → option expired worthless (win)
- Assigned → stock called away (neutral to win for CC)
- Closed → manually closed

**Columns explained:**
- **Capital Used** — Total capital deployed in the trade
- **Stock P/L** — Gain/loss on the underlying stock movement
- **Prem Earned** — Total premium received (includes all rolls)
- **Prem Yield** — Premium / Capital × 100
- **P/L** — Total unrealized (open) or realized (closed) profit/loss
- **ROI** — Return on capital deployed
- **Quality** — High Yield (>20% ann. ROI) / Good Income (10–20%) / Low Return (<10%) / Losing`
      },
      {
        title: 'Using the AI Trade Manager',
        content: `The 🤖 Manage button on any open trade calls the AI Trade Manager (costs 5 credits).

**What it does:**
1. Analyses your trade (stock price, delta, DTE, P/L)
2. Checks your configured rules (Rules tab)
3. Returns a structured recommendation with reasoning

**Available actions:**
- **Hold** — Keep the trade open, no action needed
- **Close** — Buy back the short call to lock in profit (typically when 80% of max profit captured)
- **Roll Out** — Buy back current call, sell same strike next month
- **Roll Up & Out** — Buy back, sell higher strike next month (when stock has risen)
- **Roll Down & Out** — Buy back, sell lower strike next month (defensive)

**Executing actions:**
Select an action from the dropdown and click Execute. This updates the trade in your Simulator.`
      },
      {
        title: 'Configuring Rules',
        content: `Go to Simulator → Rules tab.

**Hard rules (always enforced by AI):**
- **Close at % capture** — AI will suggest close when X% of max profit is reached (default 80%)
- **Roll DTE trigger** — AI will suggest roll when DTE drops below this (default 21 days)
- **Avoid assignment** — AI prioritises rolling before assignment
- **No debit roll** — AI will not suggest rolling at a debit (net cost)

**Optional controls:**
- **Roll ITM Near Expiry** — Auto-roll if short call is ITM within 7 days
- **Roll Based on Delta** — Roll if delta exceeds your max delta threshold
- **Market-Aware Suggestions** — AI factors in overall market conditions

**Strategy filter:** Use the CC / WHEEL / PMCC / DEFENSIVE buttons to show rules relevant to each strategy type.

**Reset to Defaults** — Restores all controls to recommended starting settings.`
      }
    ]
  },
  {
    id: 'portfolio',
    icon: <Wallet className="w-5 h-5 text-amber-400" />,
    title: 'Portfolio',
    color: 'amber',
    articles: [
      {
        title: 'Importing IBKR trades',
        content: `The Portfolio tab tracks your real Interactive Brokers trades.

**How to export from IBKR:**
1. Log in to IBKR Client Portal or TWS
2. Go to Reports → Activity → Activity Statement
3. Set date range (e.g. last 12 months)
4. Format: CSV
5. Download the file

**How to import:**
1. Go to Portfolio → Import CSV
2. Upload your IBKR Activity Statement CSV
3. The engine automatically:
   - Parses all stock purchases, call sells, assignments, and expirations
   - Groups transactions into covered call cycles
   - Calculates P/L per cycle

**Supported strategies:**
- Covered Call (CC)
- Wheel (sell puts, get assigned, sell calls)
- Cash Secured Put (CSP)
- PMCC`
      },
      {
        title: 'Reading the lifecycle view',
        content: `Each cycle shows the full life of a covered call position:

**Cycle status:**
- Open - Covered Call Active — You own shares, have a short call open
- Open - Uncovered — You own shares, no call sold yet
- Closed — Position fully exited

**Metrics per cycle:**
- **Shares** — Number of shares held
- **Avg Cost** — Average cost basis of your shares
- **Premium Collected** — Total options income from this cycle
- **Stock P/L** — Gain/loss on shares (sold price − cost basis)
- **Total P/L** — Stock P/L + all premiums collected
- **Strategy** — CC, WHEEL, or CSP badge

**Linked options:** Each cycle shows all the options sold against the shares, with their individual P/L.`
      }
    ]
  },
  {
    id: 'faq',
    icon: <HelpCircle className="w-5 h-5 text-zinc-400" />,
    title: 'FAQ',
    color: 'zinc',
    articles: [
      {
        title: 'How often does the screener update?',
        content: `The screener runs every weeknight after market close (approximately 6–8 PM ET). Results are available the next morning.

Results show the best covered call setups for the following trading day based on closing prices, IV, and option chain data for 900+ US stocks and ETFs.`
      },
      {
        title: 'What does the score mean?',
        content: `The score (0–100) is a composite quality rating:

- **70–100** — Excellent setup. Strong premium, good liquidity, ideal IV
- **50–70** — Good setup. Worth considering
- **30–50** — Marginal. Review carefully before trading
- **Below 30** — Weak setup. Low premium or poor liquidity

The score factors in: ROI per cycle, IV Rank, option liquidity (OI), bid-ask spread, and delta quality.`
      },
      {
        title: 'What are AI credits used for?',
        content: `AI credits power the AI Trade Manager in the Simulator.

**Costs:**
- Analyse a trade (🤖 Manage button) — 5 credits
- Execute an AI-suggested action — 2 credits

**Getting credits:**
- New accounts receive starter credits
- Purchase credit packs from the AI Wallet page

Credits never expire.`
      },
      {
        title: 'Is this financial advice?',
        content: `No. Covered Call Engine is an analytical and educational tool only.

All scan results, AI recommendations, and simulator outputs are for informational purposes only. They do not constitute financial, investment, or trading advice.

Always do your own research and consult a licensed financial advisor before making real trading decisions. Options trading involves significant risk of loss.`
      }
    ]
  }
];

const colorMap = {
  emerald: 'border-emerald-500/30 bg-emerald-500/5',
  sky: 'border-sky-500/30 bg-sky-500/5',
  violet: 'border-violet-500/30 bg-violet-500/5',
  blue: 'border-blue-500/30 bg-blue-500/5',
  amber: 'border-amber-500/30 bg-amber-500/5',
  zinc: 'border-zinc-500/30 bg-zinc-500/5',
};

function ArticleCard({ article }) {
  const [open, setOpen] = useState(false);

  const renderContent = (text) => {
    return text.split('\n').map((line, i) => {
      if (line.startsWith('**') && line.endsWith('**')) {
        return <p key={i} className="font-semibold text-white mt-3 mb-1">{line.slice(2, -2)}</p>;
      }
      if (line.match(/^\*\*.+\*\*/)) {
        const parts = line.split(/(\*\*[^*]+\*\*)/g);
        return (
          <p key={i} className="text-zinc-300 text-sm leading-relaxed">
            {parts.map((p, j) => p.startsWith('**') ? <strong key={j} className="text-white">{p.slice(2, -2)}</strong> : p)}
          </p>
        );
      }
      if (line.startsWith('- ')) {
        return <li key={i} className="text-zinc-300 text-sm ml-4 list-disc">{line.slice(2)}</li>;
      }
      if (line.match(/^\d+\. /)) {
        return <li key={i} className="text-zinc-300 text-sm ml-4 list-decimal">{line.replace(/^\d+\. /, '')}</li>;
      }
      if (line.trim() === '') return <div key={i} className="h-2" />;
      return <p key={i} className="text-zinc-300 text-sm leading-relaxed">{line}</p>;
    });
  };

  return (
    <div className="border border-zinc-800/50 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between p-4 text-left hover:bg-zinc-800/30 transition-colors"
        onClick={() => setOpen(!open)}
      >
        <span className="text-white font-medium text-sm">{article.title}</span>
        {open ? <ChevronDown className="w-4 h-4 text-zinc-400 flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-zinc-400 flex-shrink-0" />}
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-zinc-800/50 pt-3 space-y-1">
          {renderContent(article.content)}
        </div>
      )}
    </div>
  );
}

export default function Help() {
  const [activeSection, setActiveSection] = useState('getting-started');

  const current = sections.find(s => s.id === activeSection);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <BookOpen className="w-6 h-6 text-emerald-400" />
          User Guide
        </h1>
        <p className="text-zinc-400 text-sm mt-1">Everything you need to use Covered Call Engine effectively</p>
      </div>

      <div className="flex gap-6">
        {/* Sidebar nav */}
        <div className="w-48 flex-shrink-0">
          <nav className="space-y-1">
            {sections.map(s => (
              <button
                key={s.id}
                onClick={() => setActiveSection(s.id)}
                className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors text-left ${
                  activeSection === s.id
                    ? 'bg-zinc-800 text-white'
                    : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                }`}
              >
                {s.icon}
                {s.title}
              </button>
            ))}
          </nav>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {current && (
            <div className={`rounded-xl border p-5 ${colorMap[current.color]}`}>
              <div className="flex items-center gap-2 mb-4">
                {current.icon}
                <h2 className="text-lg font-semibold text-white">{current.title}</h2>
              </div>
              <div className="space-y-2">
                {current.articles.map((article, i) => (
                  <ArticleCard key={i} article={article} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
