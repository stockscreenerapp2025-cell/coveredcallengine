import { useState } from 'react';
import { ChevronDown, ChevronRight, BookOpen, BarChart3, TrendingUp, Settings, CreditCard, Star, HelpCircle, DollarSign } from 'lucide-react';

/* ── Rich content helpers ─────────────────────────────────────────────────── */
function RichAnswer({ children }) {
  return <div className="text-zinc-300 text-sm leading-relaxed space-y-3">{children}</div>;
}
function Block({ title, children }) {
  return (
    <div>
      {title && <p className="text-white font-semibold mb-1">{title}</p>}
      {children}
    </div>
  );
}
function Bullets({ items }) {
  return (
    <ul className="space-y-1 pl-3">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2"><span className="text-zinc-500 mt-0.5">•</span><span>{item}</span></li>
      ))}
    </ul>
  );
}
function Scenario({ label, lines }) {
  return (
    <div className="bg-zinc-800/60 rounded-lg p-3">
      <p className="text-zinc-400 text-xs font-semibold uppercase tracking-wider mb-1">{label}</p>
      {lines.map((l, i) => <p key={i}>{l}</p>)}
    </div>
  );
}
function Insight({ title, children }) {
  return (
    <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-3">
      <p className="text-emerald-400 font-semibold text-xs uppercase tracking-wider mb-1">{title}</p>
      <div className="text-zinc-300">{children}</div>
    </div>
  );
}
function ProTip({ children }) {
  return (
    <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3">
      <p className="text-blue-400 font-semibold text-xs uppercase tracking-wider mb-1">Pro Tip</p>
      <div className="text-zinc-300">{children}</div>
    </div>
  );
}

/* ── Sections data ────────────────────────────────────────────────────────── */
const sections = [
  /* ── 1. INTRODUCING INCOME STRATEGIES ── */
  {
    id: 'income-strategies',
    icon: <DollarSign className="w-5 h-5 text-cyan-400" />,
    title: 'Income Strategies',
    color: 'cyan',
    articles: [
      {
        q: 'What is a Covered Call strategy?',
        a: (
          <RichAnswer>
            <p>A covered call is a strategy where you generate income from stocks you already own — or intentionally buy to create income.</p>
            <Block title="How it works">
              <Bullets items={[
                'You own 100 shares of a stock (e.g. AAPL at $180)',
                'You sell a call option at a higher price — the strike (e.g. $185, 30 days out)',
                'You collect premium upfront (e.g. $150 cash)',
              ]} />
            </Block>
            <Block title="What happens next?">
              <div className="space-y-2">
                <Scenario label="Scenario 1 — Stock stays below $185" lines={[
                  'Option expires worthless',
                  'You keep the $150 income',
                  'You continue holding the shares',
                ]} />
                <Scenario label="Scenario 2 — Stock goes above $185" lines={[
                  'Your shares are sold at $185',
                  'You earn: stock profit ($180 → $185) + premium ($150)',
                ]} />
              </div>
            </Block>
            <Insight title="Income Strategy Insight">
              <p>You don't always need to already own the stock. You can buy shares specifically to run covered calls and generate regular cash flow — turning your portfolio into a yield-generating asset.</p>
            </Insight>
            <Block title="When to use it">
              <Bullets items={[
                'You own the stock or are willing to buy it',
                'You are neutral to slightly bullish',
                'You want regular monthly income',
              ]} />
            </Block>
          </RichAnswer>
        ),
      },
      {
        q: 'What is a PMCC (Poor Man\'s Covered Call)?',
        a: (
          <RichAnswer>
            <p>A PMCC is a capital-efficient version of a covered call. Instead of buying 100 shares, you use an option to simulate ownership.</p>
            <Block title="How it works">
              <Bullets items={[
                'Buy a deep ITM long-term call (LEAPS)',
                'Sell a short-term call against it',
                'Repeat monthly to generate income',
              ]} />
            </Block>
            <Block title="Example — Stock at $150">
              <div className="space-y-2">
                <Scenario label="Step 1 — Buy LEAPS" lines={['$130 strike, 9 months out', 'Cost = $2,800']} />
                <Scenario label="Step 2 — Sell Short Call" lines={['$155 strike, 30 days', 'Premium = $150', 'Net capital used = $2,650 (vs $15,000 for 100 shares)']} />
              </div>
            </Block>
            <Block title="Why this works">
              <Bullets items={[
                'LEAPS behaves like stock (delta ~0.65–0.80)',
                'Short calls generate recurring income each cycle',
                'Much lower capital required than owning shares',
              ]} />
            </Block>
            <Block title="Key difference vs Covered Call">
              <Bullets items={[
                'Covered Call = Own shares (or buy shares)',
                'PMCC = Own a LEAPS option instead of shares',
              ]} />
            </Block>
            <Block title="When to use it">
              <Bullets items={[
                'You want covered call income with less capital',
                'You are moderately bullish on the stock',
                'You want capital efficiency',
              ]} />
            </Block>
          </RichAnswer>
        ),
      },
      {
        q: 'What is a Collar (Defensive) strategy?',
        a: (
          <RichAnswer>
            <p>A collar is a defensive strategy used to protect your stock while still generating some income.</p>
            <Block title="How it works">
              <Bullets items={[
                'You own 100 shares of a stock',
                'You sell a call option (generates income)',
                'You buy a put option (provides protection)',
                'This creates a price range — a "collar" — for your stock',
              ]} />
            </Block>
            <Block title="Example — Stock at $100">
              <div className="space-y-2">
                <Scenario label="Sell Call" lines={['$105 strike → collect $2']} />
                <Scenario label="Buy Put" lines={['$95 strike → pay $1', 'Net premium = +$1 income']} />
              </div>
            </Block>
            <Block title="What happens next?">
              <div className="space-y-2">
                <Scenario label="Scenario 1 — Stock stays between $95–$105" lines={['Both options expire', 'You keep the $1 income']} />
                <Scenario label="Scenario 2 — Stock rises above $105" lines={['Shares are called away at $105', 'Profit is capped, but you keep the premium']} />
                <Scenario label="Scenario 3 — Stock falls below $95" lines={['Put option protects you', 'You can sell shares at $95 — loss is limited']} />
              </div>
            </Block>
            <Insight title="Protection Insight">
              <p>A collar is like insurance + income on your stock. The call pays you. The put protects you.</p>
            </Insight>
            <Block title="When to use it">
              <Bullets items={[
                'You already own the stock',
                'You want to protect downside risk',
                'You are okay with limited upside',
              ]} />
            </Block>
          </RichAnswer>
        ),
      },
      {
        q: 'What is a Cash Secured Put (CSP)?',
        a: (
          <RichAnswer>
            <p>A cash secured put is a strategy to get paid while waiting to buy a stock at a lower price.</p>
            <Block title="How it works">
              <Bullets items={[
                'You sell a put option on a stock you want to own',
                'You keep enough cash aside to buy the shares if assigned',
                'You are agreeing to buy the stock at a lower price — and get paid for it',
              ]} />
            </Block>
            <Block title="Example — Stock at $100">
              <div className="space-y-2">
                <Scenario label="Sell Put" lines={['$90 strike, 30 days', 'Premium = $2', 'Set aside $9,000 (to buy shares if needed)']} />
              </div>
            </Block>
            <Block title="What happens next?">
              <div className="space-y-2">
                <Scenario label="Scenario 1 — Stock stays above $90" lines={['Option expires worthless', 'You keep the $200 income', 'No shares bought']} />
                <Scenario label="Scenario 2 — Stock falls below $90" lines={['You are assigned shares at $90', 'Effective cost = $88 ($90 − $2 premium)']} />
              </div>
            </Block>
            <Insight title="Entry Strategy Insight">
              <p>A CSP is a smart way to enter a stock at a discount while earning income. Instead of buying at $100, you get paid to potentially buy at $90.</p>
            </Insight>
            <Block title="The Wheel Strategy">
              <p className="mb-1">CSP often leads naturally into Covered Calls:</p>
              <Bullets items={[
                'Sell Put → Get assigned shares',
                'Now you own stock → Start selling calls',
                'This cycle is called the Wheel Strategy',
              ]} />
            </Block>
            <Block title="When to use it">
              <Bullets items={[
                'You want to buy a stock at a lower price',
                'You are bullish or neutral on the stock',
                'You are happy to own the stock if assigned',
              ]} />
            </Block>
          </RichAnswer>
        ),
      },
    ],
  },

  /* ── 2. OPTIONS TRADING BASICS ── */
  {
    id: 'options-basics',
    icon: <TrendingUp className="w-5 h-5 text-violet-400" />,
    title: 'Options Trading Basics',
    color: 'violet',
    articles: [
      {
        q: 'What is options trading?',
        a: (
          <RichAnswer>
            <p>Options trading is a way to buy or sell the <span className="text-white font-semibold">right — but not the obligation</span> — to trade a stock at a fixed price within a certain time period.</p>
            <Insight title="Key Point">
              <p>Unlike buying stocks, you are not forced to complete the trade. You simply pay a small upfront cost called a <span className="text-emerald-400 font-semibold">premium</span> to hold that right.</p>
            </Insight>
            <Bullets items={[
              'Options give you flexibility — you choose whether to act',
              'You always pay a small upfront cost called a premium',
              'Options have an expiry date — after which they become worthless',
              'They can be used to generate income, hedge risk, or speculate',
            ]} />
          </RichAnswer>
        ),
      },
      {
        q: 'What is a Call Option?',
        a: (
          <RichAnswer>
            <p>A <span className="text-emerald-400 font-semibold">call option</span> gives you the right to <span className="text-white font-semibold">BUY</span> a stock at a fixed price (called the strike price) before a certain date.</p>
            <Block title="When do you use it?">
              <p>When you believe the stock price will go <span className="text-emerald-400 font-semibold">UP</span>.</p>
            </Block>
            <Block title="Simple Example">
              <div className="space-y-2">
                <Scenario label="Setup" lines={[
                  'Stock price today = $100',
                  'You buy a call option at strike $105',
                  'You pay a small premium upfront',
                ]} />
                <Scenario label="Stock goes to $120 — You profit" lines={[
                  'You can still buy at $105 (your locked-in price)',
                  'Immediately worth $120 in the market',
                  'Profit = $120 − $105 = $15 per share',
                ]} />
                <Scenario label="Stock stays below $105 — Small loss" lines={[
                  'You let the option expire — no obligation',
                  'You only lose the small premium you paid',
                ]} />
              </div>
            </Block>
            <Insight title="Key Idea">
              <p>Call options benefit when the stock goes <span className="text-emerald-400 font-semibold">UP</span>. Your maximum loss is limited to the premium paid.</p>
            </Insight>
          </RichAnswer>
        ),
      },
      {
        q: 'What is a Put Option?',
        a: (
          <RichAnswer>
            <p>A <span className="text-red-400 font-semibold">put option</span> gives you the right to <span className="text-white font-semibold">SELL</span> a stock at a fixed price before a certain date.</p>
            <Block title="When do you use it?">
              <p>When you believe the stock price will go <span className="text-red-400 font-semibold">DOWN</span>.</p>
            </Block>
            <Block title="Simple Example">
              <div className="space-y-2">
                <Scenario label="Setup" lines={[
                  'Stock price today = $100',
                  'You buy a put option at strike $95',
                  'You pay a small premium upfront',
                ]} />
                <Scenario label="Stock falls to $80 — You profit" lines={[
                  'You can still sell at $95 (your locked-in price)',
                  'Even though market price is only $80',
                  'Profit = $95 − $80 = $15 per share',
                ]} />
                <Scenario label="Stock stays above $95 — Small loss" lines={[
                  'You let the option expire — no obligation',
                  'You only lose the small premium you paid',
                ]} />
              </div>
            </Block>
            <Insight title="Key Idea">
              <p>Put options benefit when the stock goes <span className="text-red-400 font-semibold">DOWN</span>. Your maximum loss is limited to the premium paid.</p>
            </Insight>
          </RichAnswer>
        ),
      },
      {
        q: 'Quick Summary — Call vs Put',
        a: (
          <RichAnswer>
            <div className="space-y-2">
              <div className="bg-zinc-800/60 rounded-lg p-3 flex items-start gap-3">
                <span className="text-emerald-400 font-bold text-lg mt-0.5">↑</span>
                <div>
                  <p className="text-white font-semibold">Call Option — Bullish</p>
                  <p className="text-zinc-400 text-xs mt-0.5">Right to BUY · Profit when stock goes UP · Loss limited to premium paid</p>
                </div>
              </div>
              <div className="bg-zinc-800/60 rounded-lg p-3 flex items-start gap-3">
                <span className="text-red-400 font-bold text-lg mt-0.5">↓</span>
                <div>
                  <p className="text-white font-semibold">Put Option — Bearish</p>
                  <p className="text-zinc-400 text-xs mt-0.5">Right to SELL · Profit when stock goes DOWN · Loss limited to premium paid</p>
                </div>
              </div>
            </div>
            <ProTip>On Covered Call Engine, you are always the <span className="text-white font-semibold">seller</span> of options — you collect the premium as income rather than paying it.</ProTip>
          </RichAnswer>
        ),
      },
    ],
  },

  /* ── 3. GETTING STARTED ── */
  {
    id: 'getting-started',
    icon: <BookOpen className="w-5 h-5 text-emerald-400" />,
    title: 'Getting Started',
    color: 'emerald',
    articles: [
      {
        q: 'What is the recommended workflow in CCE?',
        a: (
          <RichAnswer>
            <p>CCE is designed around a simple end-to-end flow:</p>
            <Block>
              <Bullets items={[
                '1. Dashboard → Understand market conditions',
                '2. Screener / PMCC → Find trade opportunities',
                '3. Simulator → Test trades without risk',
                '4. Execute with your own broker at your own risk',
                '5. Portfolio → Track real performance',
                '6. Watchlist → Monitor future opportunities',
                '7. AI Wallet → Optimise decisions with AI',
              ]} />
            </Block>
            <Insight title="Important">
              <p>CCE provides the tools and technology to help you find good opportunities. All trade execution is done independently through your own broker. CCE does not provide financial advice.</p>
            </Insight>
          </RichAnswer>
        ),
      },
      {
        q: 'How do I use the Dashboard?',
        a: (
          <RichAnswer>
            <p>The Dashboard gives you a snapshot of market conditions and your portfolio at a glance.</p>
            <Block title="What it shows">
              <Bullets items={[
                'Market indicators — S&P 500, Nasdaq, Dow Jones, VIX',
                'Portfolio overview — total invested, premium collected',
                'Strategy distribution — how your trades are spread',
                'Top opportunities and market news',
              ]} />
            </Block>
            <Block title="How to use it effectively">
              <Bullets items={[
                'Start your day here — check VIX (higher = better premiums)',
                'Review Portfolio Overview for a quick health check',
                'Check Strategy Distribution — avoid overexposure to one strategy',
                'Use Top Opportunities as a quick entry point to trades',
              ]} />
            </Block>
            <ProTip>
              <p>Use the Dashboard as a decision filter. If VIX is high, focus on income strategies. If market is calm, be selective with entries.</p>
            </ProTip>
          </RichAnswer>
        ),
      },
      {
        q: 'How do I use the Screener to find trades?',
        a: (
          <RichAnswer>
            <p>The Screener scans 1,000+ optionable stocks to find high-quality Covered Call setups.</p>
            <Block title="Key filters to focus on">
              <Bullets items={[
                'Delta (0.20–0.35) — safer strikes, lower assignment risk',
                'DTE 5–14 days (weekly) or 15–45 days (monthly)',
                'IV Rank above 50% — better premiums',
                'ROI / Yield — income quality indicator',
              ]} />
            </Block>
            <Block title="Quick Scans (pre-defined)">
              <Bullets items={[
                'Income Guard (Low Risk) — stable, large-cap stocks',
                'Steady Income (Balanced) — best default for most users',
                'Premium Hunter (Aggressive) — higher yield, higher risk',
              ]} />
            </Block>
            <Block title="Recommended approach by experience">
              <Bullets items={[
                'Beginners — Use Quick Scans only',
                'Intermediate — Add IV Rank > 60 and Delta < 0.30',
                'Advanced — Use manual filters to fine-tune',
              ]} />
            </Block>
            <Insight title="Action">
              <p>Click Simulate to send a trade to the Simulator and check expected performance before executing.</p>
            </Insight>
          </RichAnswer>
        ),
      },
      {
        q: 'How do I use the PMCC page?',
        a: (
          <RichAnswer>
            <p>The PMCC page finds capital-efficient trades using LEAPS + short call combinations.</p>
            <Block title="Key metrics to focus on">
              <Bullets items={[
                'Cap Efficiency — how much capital is saved vs owning shares',
                'Income per Cycle — expected monthly income',
                'Payback Period — how quickly you recover the LEAPS cost',
                'Score / Verdict — overall trade quality rating',
              ]} />
            </Block>
            <Block title="Strategy modes">
              <Bullets items={[
                'Capital Efficient — safest, focus on capital saving',
                'Leveraged Income — balanced risk and income',
                'Max Yield Diagonal — aggressive, highest yield',
              ]} />
            </Block>
            <Block title="What to avoid">
              <Bullets items={[
                'Skip trades where capital saving is minimal',
                'Avoid payback periods longer than 18 months',
              ]} />
            </Block>
            <ProTip><p>Click Details then Simulate before entering any PMCC trade.</p></ProTip>
          </RichAnswer>
        ),
      },
      {
        q: 'How do I track my real trades in Portfolio?',
        a: (
          <RichAnswer>
            <p>The Portfolio tracks all your real trades imported from your broker.</p>
            <Block title="How to import">
              <Bullets items={[
                '1. Go to Portfolio → Import CSV',
                '2. Upload your IBKR Transaction Statement',
                '3. System auto-detects strategy type — Covered Call, Collar, CSP, PMCC',
              ]} />
            </Block>
            <Block title="What to monitor">
              <Bullets items={[
                'B/E (Breakeven) — your true position cost after premium',
                'Premium Collected — your primary income source',
                'Unrealised vs Realised P&L',
                'Net ROI per trade',
              ]} />
            </Block>
            <Insight title="Key Insight">
              <p>Premium is your primary income. Stock movement is secondary — it represents capital gain or loss, not your income strategy outcome.</p>
            </Insight>
            <ProTip><p>Use Portfolio to identify underperforming trades and decide when to roll or exit.</p></ProTip>
          </RichAnswer>
        ),
      },
      {
        q: 'How do I use the Simulator?',
        a: (
          <RichAnswer>
            <p>The Simulator lets you test strategies and track paper trades without risking real money.</p>
            <Block title="Key metrics tracked">
              <Bullets items={[
                'Total P&L and ROI',
                'Assignment Rate',
                'Active Trades and Capital Deployed',
                'Strategy Distribution',
              ]} />
            </Block>
            <Block title="Recommended workflow">
              <Bullets items={[
                '1. Find a trade in Dashboard, Screener, or PMCC page',
                '2. Click Simulate to add it to the Simulator',
                '3. Monitor performance over time',
                '4. Use Manage AI to get trade suggestions and optimise exits',
              ]} />
            </Block>
            <Block title="Tabs available">
              <Bullets items={[
                'Trades — view all simulated positions',
                'Rules — set automated management rules',
                'Logs — see all events and rule alerts',
                'PMCC Tracker — monitor PMCC trades specifically',
                'Analyzer — full performance and risk breakdown',
              ]} />
            </Block>
            <ProTip><p>The Simulator is your learning engine. The more you use it, the better your real strategy becomes.</p></ProTip>
          </RichAnswer>
        ),
      },
      {
        q: 'What is the Watchlist for?',
        a: (
          <RichAnswer>
            <p>The Watchlist tracks your selected stocks and alerts you to new covered call opportunities.</p>
            <Block title="What it shows">
              <Bullets items={[
                'Current price and movement since you added the stock',
                'Available option opportunities with strike and premium',
                'AI Score and analyst rating',
                'DTE, IV Rank, and ROI for each opportunity',
              ]} />
            </Block>
            <Block title="How to use it">
              <Bullets items={[
                'Add stocks you follow or already own',
                'Monitor when IV increases and premiums improve',
                'Use it as your personal opportunity pipeline',
              ]} />
            </Block>
            <ProTip><p>Build a core watchlist of 10–20 quality stocks and trade only from this list. Consistency improves when you know the stocks well.</p></ProTip>
          </RichAnswer>
        ),
      },
      {
        q: 'What is the AI Wallet?',
        a: (
          <RichAnswer>
            <p>The AI Wallet manages your AI usage credits for AI-powered features across the platform.</p>
            <Block title="Used for">
              <Bullets items={[
                'AI trade analysis and scoring',
                'Trade management suggestions in Simulator',
                'Strategy optimisation recommendations',
              ]} />
            </Block>
            <Block title="How to manage it">
              <Bullets items={[
                'Monitor your token balance on the AI Wallet page',
                'Free tokens are included with your plan and reset monthly',
                'Additional tokens can be purchased in packs if needed',
              ]} />
            </Block>
            <ProTip><p>Use AI for managing open trades and reviewing underperforming positions — not for every decision. Save tokens for high-value moments.</p></ProTip>
          </RichAnswer>
        ),
      },
    ],
  },

  /* ── 3. USING THE PLATFORM ── */
  {
    id: 'using-platform',
    icon: <BarChart3 className="w-5 h-5 text-sky-400" />,
    title: 'Using the Platform',
    color: 'sky',
    articles: [
      {
        q: 'What is AI Score?',
        a: 'AI Score is a simplified rating that evaluates a trade based on income potential, risk characteristics, market conditions, and strategy suitability. It helps you compare opportunities quickly — not a guarantee.',
      },
      {
        q: 'Should I only pick trades with high AI Score?',
        a: 'No. AI Score is a guide. You should also consider your risk tolerance, capital allocation, and stock preference.',
      },
      {
        q: 'What does "Realised Gain" mean?',
        a: 'Profit that has already been locked in — for example, option premiums received or closed trades.',
      },
      {
        q: 'What is "Unrealised P/L"?',
        a: 'Profit or loss based on the current market price of open positions.',
      },
      {
        q: 'Why don\'t you show Win Rate %?',
        a: 'CCE focuses on income generation, not trade accuracy. A strategy can remain profitable even if positions go temporarily negative.',
      },
      {
        q: 'What is the difference between Covered Call, CSP, and PMCC?',
        a: 'Covered Call — Own shares and sell a call. Collar — Own shares, sell a call, and buy a put for insurance. Cash Secured Put (CSP) — Get paid to buy stock. PMCC — Use LEAPS instead of shares for a capital-efficient approach.',
      },
      {
        q: 'What is "Roll" in options?',
        a: 'Rolling means adjusting your position by extending the duration or changing the strike. It is used to manage trades instead of closing at a loss.',
      },
      {
        q: 'What does "Avoid Early Close" mean?',
        a: 'It prevents closing positions prematurely and supports an income-focused strategy.',
      },
      {
        q: 'Can I override AI or rules?',
        a: 'Yes. CCE provides guidance, but final decisions are always yours.',
      },
    ],
  },

  /* ── 4. STRATEGY & ANALYSIS ── */
  {
    id: 'strategy-analysis',
    icon: <TrendingUp className="w-5 h-5 text-violet-400" />,
    title: 'Strategy & Analysis',
    color: 'violet',
    articles: [
      {
        q: 'How is AI analysis generated?',
        a: 'CCE uses a combination of quantitative models, market indicators, strategy-based logic, and multiple reliable market data sources. The exact methodology is proprietary.',
      },
      {
        q: 'What data sources does CCE use?',
        a: 'We source data from multiple reliable market providers to ensure consistency and accuracy.',
      },
      {
        q: 'Is the data real-time?',
        a: 'Core data (prices, P&L, screener results) is based on the previous market close. Integrated charts are near real-time based on US Stock exchange availability.',
      },
      {
        q: 'How accurate is the AI Score?',
        a: 'AI Score is directional — not predictive. It improves decision-making but does not guarantee outcomes.',
      },
      {
        q: 'What factors influence AI Score?',
        a: 'It may consider premium yield, risk exposure, volatility, market sentiment, and strategy fit. Exact weighting is proprietary.',
      },
      {
        q: 'What is capital efficiency (PMCC)?',
        a: 'It measures how much capital you save compared to owning shares directly.',
      },
      {
        q: 'What is a synthetic position?',
        a: 'A synthetic position replicates stock ownership using options — for example, using LEAPS.',
      },
      {
        q: 'Why does ROI look high sometimes?',
        a: 'ROI is based on option premium relative to capital used. It does not account for all market risks.',
      },
      {
        q: 'Should I always choose highest ROI trades?',
        a: 'No. High ROI often comes with higher risk and lower probability. Balance is key.',
      },
      {
        q: 'How does CCE handle market downturns?',
        a: 'CCE supports rolling strategies, income continuation, and position management instead of forced exits.',
      },
    ],
  },

  /* ── 5. PLATFORM, RULES & INTELLIGENCE ── */
  {
    id: 'rules-intelligence',
    icon: <Settings className="w-5 h-5 text-amber-400" />,
    title: 'Platform, Rules & Intelligence',
    color: 'amber',
    articles: [
      {
        q: 'What are "Rules" in CCE?',
        a: 'Rules automate trade management such as rolling, closing, and adjusting positions based on your configured thresholds.',
      },
      {
        q: 'Do rules execute trades automatically?',
        a: 'No. Rules provide guidance and simulation unless explicitly integrated with execution.',
      },
      {
        q: 'What is "Manage AI"?',
        a: 'It provides suggested actions based on current trade status, market conditions, and your strategy rules.',
      },
      {
        q: 'Can rules conflict with each other?',
        a: 'Some combinations may not be compatible. The system flags these to avoid unintended behaviour.',
      },
      {
        q: 'What is Trade Lifecycle?',
        a: 'Trade Lifecycle tracks a position from entry through adjustments to exit, with logical grouping of trades over time.',
      },
      {
        q: 'Why are trades grouped?',
        a: 'To reflect real-world strategy management. One position may involve multiple actions over time, so grouping shows the full picture.',
      },
    ],
  },

  /* ── 6. BILLING, POLICY & SUPPORT ── */
  {
    id: 'billing-policy',
    icon: <CreditCard className="w-5 h-5 text-blue-400" />,
    title: 'Billing, Policy & Support',
    color: 'blue',
    articles: [
      {
        q: 'Is there a free trial?',
        a: 'This depends on the plan offered at the time of subscription.',
      },
      {
        q: 'What is your refund policy?',
        a: 'All subscriptions are non-refundable once activated.',
      },
      {
        q: 'Can I cancel anytime?',
        a: 'Yes. You can cancel future renewals anytime from your account settings.',
      },
      {
        q: 'Will I lose access after cancellation?',
        a: 'You will retain access until the end of your billing cycle.',
      },
      {
        q: 'Do you provide financial advice?',
        a: 'No. CCE is an analytical and educational tool. All decisions are user driven.',
      },
      {
        q: 'Is my data secure?',
        a: 'Yes. We follow industry-standard practices to protect user data.',
      },
    ],
  },

  /* ── 7. BEST PRACTICES ── */
  {
    id: 'best-practices',
    icon: <Star className="w-5 h-5 text-rose-400" />,
    title: 'Best Practices',
    color: 'rose',
    articles: [
      {
        q: 'What is the best way to use CCE?',
        a: 'Start simple: choose strong US optionable stocks, sell conservative calls, and focus on consistent income.',
      },
      {
        q: 'Can I use this strategy without owning stocks initially?',
        a: 'Yes. You can start with Cash Secured Puts or use PMCC for lower capital entry, then transition into covered calls over time.',
      },
      {
        q: 'What mistakes should I avoid?',
        a: 'Chasing high premium blindly, ignoring downside risk, overtrading, and not managing positions are the most common mistakes to avoid.',
      },
      {
        q: 'What is a good beginner strategy?',
        a: 'Covered Calls — simple, stable, and income-focused. Start with stocks you already know and sell calls with 21–45 days to expiry at a conservative delta.',
      },
    ],
  },
];

/* ── Color map ────────────────────────────────────────────────────────────── */
const colorMap = {
  cyan:    'border-cyan-500/30 bg-cyan-500/5',
  emerald: 'border-emerald-500/30 bg-emerald-500/5',
  sky:     'border-sky-500/30 bg-sky-500/5',
  violet:  'border-violet-500/30 bg-violet-500/5',
  amber:   'border-amber-500/30 bg-amber-500/5',
  blue:    'border-blue-500/30 bg-blue-500/5',
  rose:    'border-rose-500/30 bg-rose-500/5',
  zinc:    'border-zinc-500/30 bg-zinc-500/5',
};

/* ── FAQ Card ─────────────────────────────────────────────────────────────── */
function FAQCard({ article }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-zinc-800/50 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between p-4 text-left hover:bg-zinc-800/30 transition-colors"
        onClick={() => setOpen(!open)}
      >
        <span className="text-white font-medium text-sm pr-4">{article.q}</span>
        {open
          ? <ChevronDown className="w-4 h-4 text-zinc-400 flex-shrink-0" />
          : <ChevronRight className="w-4 h-4 text-zinc-400 flex-shrink-0" />
        }
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-zinc-800/50 pt-3">
          {typeof article.a === 'string'
            ? <p className="text-zinc-300 text-sm leading-relaxed">{article.a}</p>
            : article.a
          }
        </div>
      )}
    </div>
  );
}

/* ── Main component ───────────────────────────────────────────────────────── */
export default function Help() {
  const [activeSection, setActiveSection] = useState('income-strategies');
  const current = sections.find(s => s.id === activeSection);

  return (
    <div
      className="p-6 max-w-5xl mx-auto"
      style={{ userSelect: 'none', WebkitUserSelect: 'none', MozUserSelect: 'none', msUserSelect: 'none' }}
      onCopy={e => e.preventDefault()}
      onContextMenu={e => e.preventDefault()}
    >
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <HelpCircle className="w-6 h-6 text-emerald-400" />
          Help &amp; User Guide
        </h1>
        <p className="text-zinc-400 text-sm mt-1">Everything you need to know about Covered Call Engine</p>
      </div>

      <div className="flex gap-6">
        {/* Sidebar nav */}
        <div className="w-56 flex-shrink-0">
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
                <span className="truncate">{s.title}</span>
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
                <span className="ml-auto text-xs text-zinc-500">{current.articles.length} topics</span>
              </div>
              <div className="space-y-2">
                {current.articles.map((article, i) => (
                  <FAQCard key={i} article={article} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
