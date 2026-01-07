import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { stocksApi, newsApi, screenerApi, portfolioApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Skeleton } from '../components/ui/skeleton';
import { Badge } from '../components/ui/badge';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Newspaper,
  Target,
  ArrowRight,
  RefreshCw,
  DollarSign,
  Search,
  CheckCircle,
  AlertCircle
} from 'lucide-react';
import { toast } from 'sonner';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

const Dashboard = () => {
  const navigate = useNavigate();
  const [indices, setIndices] = useState({});
  const [news, setNews] = useState([]);
  const [opportunities, setOpportunities] = useState([]);
  const [opportunitiesInfo, setOpportunitiesInfo] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [oppsLoading, setOppsLoading] = useState(false);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    setLoading(true);
    setOppsLoading(true);
    try {
      const [indicesRes, newsRes, portfolioRes] = await Promise.all([
        stocksApi.getIndices(),
        newsApi.getNews({ limit: 6 }),
        portfolioApi.getSummary()
      ]);

      setIndices(indicesRes.data);
      setNews(newsRes.data);
      setPortfolio(portfolioRes.data);
      
      // Fetch dashboard opportunities separately (may take longer)
      try {
        const oppsRes = await screenerApi.getDashboardOpportunities();
        setOpportunities(oppsRes.data.opportunities || []);
        setOpportunitiesInfo(oppsRes.data);
      } catch (oppsError) {
        console.error('Dashboard opportunities error:', oppsError);
        const fallbackRes = await screenerApi.getCoveredCalls({ min_roi: 1.5, min_price: 30, max_price: 90 });
        setOpportunities(fallbackRes.data.opportunities?.slice(0, 10) || []);
        setOpportunitiesInfo({ is_live: fallbackRes.data.is_live, fallback: true });
      }
      setOppsLoading(false);
      
    } catch (error) {
      console.error('Dashboard fetch error:', error);
      toast.error('Failed to load dashboard data');
    } finally {
      setLoading(false);
      setOppsLoading(false);
    }
  };

  // Generate mock chart data
  const chartData = Array.from({ length: 30 }, (_, i) => ({
    day: i + 1,
    value: 450 + Math.random() * 50 - (i > 15 ? -10 : 10) + i * 0.5
  }));

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(value);
  };

  const formatPercent = (value) => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value?.toFixed(2)}%`;
  };

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Search className="w-8 h-8 text-emerald-500" />
            Dashboard
          </h1>
          <p className="text-zinc-400 mt-1">Real-time market overview and opportunities</p>
        </div>
        <Button
          onClick={fetchDashboardData}
          variant="outline"
          className="btn-outline"
          data-testid="refresh-dashboard-btn"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Market Indices */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {loading ? (
          Array(5).fill(0).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))
        ) : (
          Object.entries(indices).map(([symbol, data]) => (
            <Card key={symbol} className="glass-card card-hover" data-testid={`index-${symbol}`}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-zinc-500">{data.name}</span>
                  {data.change >= 0 ? (
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  )}
                </div>
                <div className="text-xl font-bold font-mono text-white">
                  ${data.price?.toFixed(2)}
                </div>
                <div className={`text-sm font-mono ${data.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatPercent(data.change_pct)}
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Main Grid */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* Portfolio Summary */}
        <Card className="glass-card lg:col-span-2" data-testid="portfolio-summary-card">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-emerald-400" />
              Portfolio Overview
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/portfolio')}
              className="text-violet-400 hover:text-violet-300"
            >
              View All <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-4">
                <Skeleton className="h-32" />
                <div className="grid grid-cols-2 gap-4">
                  <Skeleton className="h-20" />
                  <Skeleton className="h-20" />
                </div>
              </div>
            ) : (
              <>
                <div className="h-40 mb-6">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData}>
                      <defs>
                        <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                          <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="day" hide />
                      <YAxis hide domain={['dataMin - 10', 'dataMax + 10']} />
                      <Tooltip
                        contentStyle={{
                          background: '#18181b',
                          border: '1px solid rgba(255,255,255,0.1)',
                          borderRadius: '8px'
                        }}
                        labelStyle={{ color: '#71717a' }}
                      />
                      <Area
                        type="monotone"
                        dataKey="value"
                        stroke="#10b981"
                        strokeWidth={2}
                        fillOpacity={1}
                        fill="url(#colorValue)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Total Value</div>
                    <div className="text-xl font-bold font-mono text-white">
                      {formatCurrency(portfolio?.total_value || 0)}
                    </div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Unrealized P/L</div>
                    <div className={`text-xl font-bold font-mono ${(portfolio?.unrealized_pl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {formatCurrency(portfolio?.unrealized_pl || 0)}
                    </div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Premium Collected</div>
                    <div className="text-xl font-bold font-mono text-cyan-400">
                      {formatCurrency(portfolio?.total_premium_collected || 0)}
                    </div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Positions</div>
                    <div className="text-xl font-bold font-mono text-white">
                      {portfolio?.positions_count || 0}
                    </div>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* News Feed */}
        <Card className="glass-card" data-testid="news-feed-card">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Newspaper className="w-5 h-5 text-emerald-400" />
              Market News
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <div className="p-4 space-y-4">
                {Array(4).fill(0).map((_, i) => (
                  <Skeleton key={i} className="h-16" />
                ))}
              </div>
            ) : (
              <div className="divide-y divide-white/5">
                {news.map((item, index) => (
                  <div key={index} className="news-item">
                    <div className="title">{item.title}</div>
                    <div className="meta">
                      <span>{item.source}</span>
                      <span>•</span>
                      <span>{item.time || 'Recent'}</span>
                      {item.sentiment && (
                        <Badge className={`ml-2 ${
                          item.sentiment === 'positive' ? 'badge-success' :
                          item.sentiment === 'negative' ? 'badge-danger' : 'badge-info'
                        }`}>
                          {item.sentiment}
                        </Badge>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Top Opportunities */}
      <Card className="glass-card" data-testid="opportunities-card">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-lg flex items-center gap-2">
              <Target className="w-5 h-5 text-emerald-400" />
              Top 10 Covered Call Opportunities
            </CardTitle>
            <p className="text-xs text-zinc-500 mt-1">
              $25-$100 stocks • ATM/OTM strikes • Positive trends • Weekly ≥0.8% ROI, Monthly ≥2.5% ROI
            </p>
          </div>
          <div className="flex items-center gap-2">
            {opportunitiesInfo?.is_live && (
              <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
                <CheckCircle className="w-3 h-3 mr-1" />
                Live Data
              </Badge>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/screener')}
              className="text-emerald-400 hover:text-emerald-300"
            >
              View All <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading || oppsLoading ? (
            <div className="space-y-3">
              {Array(10).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : opportunities.length === 0 ? (
            <div className="text-center py-8 text-zinc-500">
              <AlertCircle className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No opportunities match the criteria.</p>
              <p className="text-sm mt-2">Try the full screener for more results.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>Strike</th>
                    <th>Type</th>
                    <th>DTE</th>
                    <th>Premium</th>
                    <th>ROI</th>
                    <th>Delta</th>
                    <th>IV</th>
                    <th>6M</th>
                    <th>12M</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.map((opp, index) => (
                    <tr key={index} className="cursor-pointer hover:bg-zinc-800/50" data-testid={`opportunity-${opp.symbol}`}>
                      <td className="font-semibold text-white">
                        {opp.symbol}
                        {opp.has_dividend && <span className="ml-1 text-yellow-400 text-xs">💰</span>}
                      </td>
                      <td>${opp.stock_price?.toFixed(2)}</td>
                      <td>
                        <div className="flex items-center gap-1">
                          ${opp.strike?.toFixed(2)}
                          <Badge className={opp.moneyness === 'ATM' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs' : 'bg-blue-500/20 text-blue-400 border-blue-500/30 text-xs'}>
                            {opp.moneyness || (opp.strike_pct !== undefined ? (opp.strike_pct >= -2 && opp.strike_pct <= 2 ? 'ATM' : 'OTM') : '')}
                          </Badge>
                        </div>
                      </td>
                      <td>
                        <Badge className={opp.expiry_type === 'weekly' ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30' : 'bg-violet-500/20 text-violet-400 border-violet-500/30'}>
                          {opp.expiry_type || (opp.dte <= 7 ? 'Weekly' : 'Monthly')}
                        </Badge>
                      </td>
                      <td>{opp.dte}d</td>
                      <td className="text-emerald-400">${opp.premium?.toFixed(2)}</td>
                      <td className="text-cyan-400 font-medium">{opp.roi_pct?.toFixed(2)}%</td>
                      <td>{opp.delta?.toFixed(2)}</td>
                      <td>{opp.iv?.toFixed(0)}%</td>
                      <td className={opp.trend_6m >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        {opp.trend_6m !== undefined ? `${opp.trend_6m >= 0 ? '+' : ''}${opp.trend_6m?.toFixed(0)}%` : '-'}
                      </td>
                      <td className={opp.trend_12m >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        {opp.trend_12m !== undefined ? `${opp.trend_12m >= 0 ? '+' : ''}${opp.trend_12m?.toFixed(0)}%` : '-'}
                      </td>
                      <td>
                        <Badge className={`${opp.score >= 70 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : opp.score >= 50 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' : 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'}`}>
                          {opp.score?.toFixed(0)}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* PMCC Opportunities */}
      <Card className="glass-card" data-testid="pmcc-card">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-lg flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-violet-400" />
              Top 10 PMCC Opportunities
            </CardTitle>
            <p className="text-xs text-zinc-500 mt-1">
              Buy LEAPS (12-24mo, δ0.80-0.90) • Sell Short Calls (7-30d, δ0.20-0.30) • $30-$500 stocks
            </p>
          </div>
          <div className="flex items-center gap-2">
            {pmccInfo?.is_live && (
              <Badge className="bg-violet-500/20 text-violet-400 border-violet-500/30">
                <CheckCircle className="w-3 h-3 mr-1" />
                Live Data
              </Badge>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/pmcc')}
              className="text-violet-400 hover:text-violet-300"
            >
              View All <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading || pmccLoading ? (
            <div className="space-y-3">
              {Array(5).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : pmccOpportunities.length === 0 ? (
            <div className="text-center py-8 text-zinc-500">
              <AlertCircle className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No PMCC opportunities found.</p>
              <p className="text-sm mt-2">LEAPS options may not be available for all stocks.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table text-sm">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>LEAPS Strike</th>
                    <th>LEAPS Cost</th>
                    <th>Short Strike</th>
                    <th>Premium</th>
                    <th>Net Debit</th>
                    <th>ROI/Cycle</th>
                    <th>Ann. ROI</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {pmccOpportunities.map((opp, index) => (
                    <tr key={index} className="cursor-pointer hover:bg-zinc-800/50" data-testid={`pmcc-${opp.symbol}`}>
                      <td className="font-semibold text-white">{opp.symbol}</td>
                      <td>${opp.stock_price?.toFixed(2)}</td>
                      <td>
                        <div className="flex flex-col">
                          <span>${opp.leaps_strike?.toFixed(0)}</span>
                          <span className="text-xs text-zinc-500">{opp.leaps_dte}d • δ{opp.leaps_delta?.toFixed(2)}</span>
                        </div>
                      </td>
                      <td className="text-red-400">${opp.leaps_cost?.toLocaleString()}</td>
                      <td>
                        <div className="flex flex-col">
                          <span>${opp.short_strike?.toFixed(0)}</span>
                          <span className="text-xs text-zinc-500">{opp.short_dte}d • δ{opp.short_delta?.toFixed(2)}</span>
                        </div>
                      </td>
                      <td className="text-emerald-400">${opp.short_premium?.toFixed(0)}</td>
                      <td className="text-cyan-400">${opp.net_debit?.toLocaleString()}</td>
                      <td className="text-yellow-400 font-medium">{opp.roi_per_cycle?.toFixed(1)}%</td>
                      <td className="text-emerald-400 font-medium">{opp.annualized_roi?.toFixed(0)}%</td>
                      <td>
                        <Badge className={`${opp.score >= 70 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : opp.score >= 50 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' : 'bg-violet-500/20 text-violet-400 border-violet-500/30'}`}>
                          {opp.score?.toFixed(0)}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Data Source Notice */}
      {(opportunitiesInfo || pmccInfo) && (
        <div className={`glass-card p-4 border-l-4 ${(opportunitiesInfo?.is_live || pmccInfo?.is_live) ? 'border-emerald-500' : 'border-yellow-500'}`}>
          <div className="flex items-center gap-3">
            {(opportunitiesInfo?.is_live || pmccInfo?.is_live) ? (
              <CheckCircle className="w-5 h-5 text-emerald-400" />
            ) : (
              <Activity className="w-5 h-5 text-yellow-400" />
            )}
            <div>
              <div className={`text-sm font-medium ${(opportunitiesInfo?.is_live || pmccInfo?.is_live) ? 'text-emerald-400' : 'text-yellow-400'}`}>
                {(opportunitiesInfo?.is_live || pmccInfo?.is_live) ? 'Live Market Data' : 'Using Mock Data'}
              </div>
              <div className="text-xs text-zinc-500">
                {(opportunitiesInfo?.is_live || pmccInfo?.is_live)
                  ? 'Data from Massive.com API • Covered Calls & PMCC strategies'
                  : 'Configure your API key in Admin settings for live market data'}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;
