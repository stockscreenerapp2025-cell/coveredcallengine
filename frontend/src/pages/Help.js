import { useState } from 'react';
import { ChevronDown, ChevronRight, BookOpen, BarChart3, TrendingUp, Settings, CreditCard, Star, HelpCircle } from 'lucide-react';

const sections = [
  {
    id: 'getting-started',
    icon: <BookOpen className="w-5 h-5 text-emerald-400" />,
    title: 'Getting Started',
    color: 'emerald',
    articles: [
      {
        q: 'What is a Covered Call strategy?',
        a: 'A covered call is an income strategy where you own shares and sell call options against them to generate regular cash flow.'
      },
      {
        q: 'What is the goal of CCE?',
        a: 'Generate consistent income from US optionable stocks. CCE is not about short-term speculation or win/loss trading.'
      },
      {
        q: 'Do I need to own stocks before using CCE?',
        a: 'No. You can start even without owning stocks by using Cash Secured Puts (get paid to enter positions) or using PMCC (capital-efficient alternative to owning shares).'
      },
      {
        q: 'Does CCE support all markets?',
        a: 'No. CCE currently focuses only on US optionable stocks, where liquidity and options availability are strongest.'
      },
      {
        q: 'How does CCE help me?',
        a: 'CCE helps you find high-probability income trades, analyse risk vs reward, and manage trades using rules and AI guidance.'
      },
      {
        q: 'Do I need options experience to use CCE?',
        a: 'No. CCE is designed for beginners as well as experienced users, with guided insights and simplified metrics.'
      },
      {
        q: 'What happens if the stock price falls?',
        a: 'CCE follows an income-first approach. You can continue selling calls, you are not required to book losses, and the focus remains on long-term income generation.'
      },
      {
        q: 'What is "premium income"?',
        a: 'Premium is the cash you receive immediately when selling an option. This is your primary income source.'
      },
    ]
  },
  {
    id: 'using-platform',
    icon: <BarChart3 className="w-5 h-5 text-sky-400" />,
    title: 'Using the Platform',
    color: 'sky',
    articles: [
      {
        q: 'What is AI Score?',
        a: 'AI Score is a simplified rating that evaluates a trade based on income potential, risk characteristics, market conditions, and strategy suitability. It helps you compare opportunities quickly — not a guarantee.'
      },
      {
        q: 'Should I only pick trades with high AI Score?',
        a: 'No. AI Score is a guide. You should also consider your risk tolerance, capital allocation, and stock preference.'
      },
      {
        q: 'What does "Realised Gain" mean?',
        a: 'Profit that has already been locked in — for example, option premiums received or closed trades.'
      },
      {
        q: 'What is "Unrealised P/L"?',
        a: 'Profit or loss based on the current market price of open positions.'
      },
      {
        q: 'Why don\'t you show Win Rate %?',
        a: 'CCE focuses on income generation, not trade accuracy. A strategy can remain profitable even if positions go temporarily negative.'
      },
      {
        q: 'What is the difference between Covered Call, CSP, and PMCC?',
        a: 'Covered Call — Own shares and sell a call. Collar — Own shares, sell a call, and buy a put for insurance. Cash Secured Put (CSP) — Get paid to buy stock. PMCC — Use LEAPS instead of shares for a capital-efficient approach.'
      },
      {
        q: 'What is "Roll" in options?',
        a: 'Rolling means adjusting your position by extending the duration or changing the strike. It is used to manage trades instead of closing at a loss.'
      },
      {
        q: 'What does "Avoid Early Close" mean?',
        a: 'It prevents closing positions prematurely and supports an income-focused strategy.'
      },
      {
        q: 'Can I override AI or rules?',
        a: 'Yes. CCE provides guidance, but final decisions are always yours.'
      },
    ]
  },
  {
    id: 'strategy-analysis',
    icon: <TrendingUp className="w-5 h-5 text-violet-400" />,
    title: 'Strategy & Analysis',
    color: 'violet',
    articles: [
      {
        q: 'How is AI analysis generated?',
        a: 'CCE uses a combination of quantitative models, market indicators, strategy-based logic, and multiple reliable market data sources. The exact methodology is proprietary.'
      },
      {
        q: 'What data sources does CCE use?',
        a: 'We source data from multiple reliable market providers to ensure consistency and accuracy.'
      },
      {
        q: 'Is the data real-time?',
        a: 'Data is near real-time or slightly delayed depending on your plan and exchange availability.'
      },
      {
        q: 'How accurate is the AI Score?',
        a: 'AI Score is directional — not predictive. It improves decision-making but does not guarantee outcomes.'
      },
      {
        q: 'What factors influence AI Score?',
        a: 'It may consider premium yield, risk exposure, volatility, market sentiment, and strategy fit. Exact weighting is proprietary.'
      },
      {
        q: 'What is capital efficiency (PMCC)?',
        a: 'It measures how much capital you save compared to owning shares directly.'
      },
      {
        q: 'What is a synthetic position?',
        a: 'A synthetic position replicates stock ownership using options — for example, using LEAPS.'
      },
      {
        q: 'Why does ROI look high sometimes?',
        a: 'ROI is based on option premium relative to capital used. It does not account for all market risks.'
      },
      {
        q: 'Should I always choose highest ROI trades?',
        a: 'No. High ROI often comes with higher risk and lower probability. Balance is key.'
      },
      {
        q: 'How does CCE handle market downturns?',
        a: 'CCE supports rolling strategies, income continuation, and position management instead of forced exits.'
      },
    ]
  },
  {
    id: 'rules-intelligence',
    icon: <Settings className="w-5 h-5 text-amber-400" />,
    title: 'Platform, Rules & Intelligence',
    color: 'amber',
    articles: [
      {
        q: 'What are "Rules" in CCE?',
        a: 'Rules automate trade management such as rolling, closing, and adjusting positions based on your configured thresholds.'
      },
      {
        q: 'Do rules execute trades automatically?',
        a: 'No. Rules provide guidance and simulation unless explicitly integrated with execution.'
      },
      {
        q: 'What is "Manage AI"?',
        a: 'It provides suggested actions based on current trade status, market conditions, and your strategy rules.'
      },
      {
        q: 'Can rules conflict with each other?',
        a: 'Some combinations may not be compatible. The system flags these to avoid unintended behaviour.'
      },
      {
        q: 'What is Trade Lifecycle?',
        a: 'Trade Lifecycle tracks a position from entry through adjustments to exit, with logical grouping of trades over time.'
      },
      {
        q: 'Why are trades grouped?',
        a: 'To reflect real-world strategy management. One position may involve multiple actions over time, so grouping shows the full picture.'
      },
    ]
  },
  {
    id: 'billing-policy',
    icon: <CreditCard className="w-5 h-5 text-blue-400" />,
    title: 'Billing, Policy & Support',
    color: 'blue',
    articles: [
      {
        q: 'Is there a free trial?',
        a: 'This depends on the plan offered at the time of subscription.'
      },
      {
        q: 'What is your refund policy?',
        a: 'All subscriptions are non-refundable once activated.'
      },
      {
        q: 'Can I cancel anytime?',
        a: 'Yes. You can cancel future renewals anytime from your account settings.'
      },
      {
        q: 'Will I lose access after cancellation?',
        a: 'You will retain access until the end of your billing cycle.'
      },
      {
        q: 'Do you provide financial advice?',
        a: 'No. CCE is an analytical and educational tool. All decisions are user driven.'
      },
      {
        q: 'Is my data secure?',
        a: 'Yes. We follow industry-standard practices to protect user data.'
      },
    ]
  },
  {
    id: 'best-practices',
    icon: <Star className="w-5 h-5 text-rose-400" />,
    title: 'Best Practices',
    color: 'rose',
    articles: [
      {
        q: 'What is the best way to use CCE?',
        a: 'Start simple: choose strong US optionable stocks, sell conservative calls, and focus on consistent income.'
      },
      {
        q: 'Can I use this strategy without owning stocks initially?',
        a: 'Yes. You can start with Cash Secured Puts or use PMCC for lower capital entry, then transition into covered calls over time.'
      },
      {
        q: 'What mistakes should I avoid?',
        a: 'Chasing high premium blindly, ignoring downside risk, overtrading, and not managing positions are the most common mistakes to avoid.'
      },
      {
        q: 'What is a good beginner strategy?',
        a: 'Covered Calls — simple, stable, and income-focused. Start with stocks you already know and sell calls with 21–45 days to expiry at a conservative delta.'
      },
    ]
  },
];

const colorMap = {
  emerald: 'border-emerald-500/30 bg-emerald-500/5',
  sky:     'border-sky-500/30 bg-sky-500/5',
  violet:  'border-violet-500/30 bg-violet-500/5',
  amber:   'border-amber-500/30 bg-amber-500/5',
  blue:    'border-blue-500/30 bg-blue-500/5',
  rose:    'border-rose-500/30 bg-rose-500/5',
  zinc:    'border-zinc-500/30 bg-zinc-500/5',
};

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
          <p className="text-zinc-300 text-sm leading-relaxed">{article.a}</p>
        </div>
      )}
    </div>
  );
}

export default function Help() {
  const [activeSection, setActiveSection] = useState('getting-started');
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
          Frequently Asked Questions
        </h1>
        <p className="text-zinc-400 text-sm mt-1">Everything you need to know about Covered Call Engine</p>
      </div>

      <div className="flex gap-6">
        {/* Sidebar nav */}
        <div className="w-52 flex-shrink-0">
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
                <span className="ml-auto text-xs text-zinc-500">{current.articles.length} questions</span>
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
