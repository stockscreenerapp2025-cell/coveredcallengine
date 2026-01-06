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
  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      const [indicesRes, newsRes, oppsRes, portfolioRes] = await Promise.all([
        stocksApi.getIndices(),
        newsApi.getNews({ limit: 6 }),
        screenerApi.getCoveredCalls({ min_roi: 1.5 }),
        portfolioApi.getSummary()
      ]);

      setIndices(indicesRes.data);
      setNews(newsRes.data);
      setOpportunities(oppsRes.data.opportunities?.slice(0, 5) || []);
      setPortfolio(portfolioRes.data);
    } catch (error) {
      console.error('Dashboard fetch error:', error);
      toast.error('Failed to load dashboard data');
    } finally {
      setLoading(false);
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
          <CardTitle className="text-lg flex items-center gap-2">
            <Target className="w-5 h-5 text-emerald-400" />
            Top Covered Call Opportunities
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/screener')}
            className="text-emerald-400 hover:text-emerald-300"
          >
            View All <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array(5).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : opportunities.length === 0 ? (
            <div className="text-center py-8 text-zinc-500">
              No opportunities found. Try adjusting your filters.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>Strike</th>
                    <th>Expiry</th>
                    <th>Premium</th>
                    <th>ROI</th>
                    <th>Delta</th>
                    <th>IV Rank</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.map((opp, index) => (
                    <tr key={index} className="cursor-pointer hover:bg-zinc-800/50" data-testid={`opportunity-${opp.symbol}`}>
                      <td className="font-semibold text-white">{opp.symbol}</td>
                      <td>${opp.stock_price?.toFixed(2)}</td>
                      <td>${opp.strike?.toFixed(2)}</td>
                      <td>{opp.expiry}</td>
                      <td className="text-emerald-400">${opp.premium?.toFixed(2)}</td>
                      <td className="text-cyan-400">{opp.roi_pct?.toFixed(2)}%</td>
                      <td>{opp.delta?.toFixed(2)}</td>
                      <td>{opp.iv_rank?.toFixed(0)}%</td>
                      <td>
                        <Badge className={`${opp.score >= 80 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : opp.score >= 60 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' : 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'}`}>
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

      {/* Mock Data Notice */}
      <div className="glass-card p-4 border-l-4 border-yellow-500">
        <div className="flex items-center gap-3">
          <Activity className="w-5 h-5 text-yellow-400" />
          <div>
            <div className="text-sm font-medium text-yellow-400">Using Mock Data</div>
            <div className="text-xs text-zinc-500">
              Configure your Polygon.io API key in Admin settings for live market data
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
