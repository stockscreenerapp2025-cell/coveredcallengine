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
  AlertCircle,
  Upload,
  Briefcase,
  PieChart
} from 'lucide-react';
import { toast } from 'sonner';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart as RechartsPie, Pie, Cell, Legend, BarChart, Bar, CartesianGrid } from 'recharts';
import StockDetailModal from '../components/StockDetailModal';

const Dashboard = () => {
  const navigate = useNavigate();
  const [indices, setIndices] = useState({});
  const [news, setNews] = useState([]);
  const [opportunities, setOpportunities] = useState([]);
  const [opportunitiesInfo, setOpportunitiesInfo] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [ibkrSummary, setIbkrSummary] = useState(null);
  const [ibkrTrades, setIbkrTrades] = useState([]);
  const [selectedStock, setSelectedStock] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
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
      
      // Fetch IBKR portfolio data
      try {
        const [ibkrSummaryRes, ibkrTradesRes] = await Promise.all([
          portfolioApi.getIBKRSummary(),
          portfolioApi.getIBKRTrades({ status: 'Open', limit: 5 })
        ]);
        setIbkrSummary(ibkrSummaryRes.data);
        setIbkrTrades(ibkrTradesRes.data.trades || []);
      } catch (ibkrError) {
        console.log('No IBKR data loaded:', ibkrError);
        setIbkrSummary(null);
        setIbkrTrades([]);
      }
      
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
            ) : ibkrSummary && ibkrSummary.total_trades > 0 ? (
              <>
                {/* IBKR Portfolio Stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Total Invested</div>
                    <div className="text-xl font-bold font-mono text-white">
                      {formatCurrency(ibkrSummary?.total_invested || 0)}
                    </div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Premium Collected</div>
                    <div className="text-xl font-bold font-mono text-cyan-400">
                      {formatCurrency(ibkrSummary?.total_premium || 0)}
                    </div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Open Trades</div>
                    <div className="text-xl font-bold font-mono text-emerald-400">
                      {ibkrSummary?.open_trades || 0}
                    </div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Closed Trades</div>
                    <div className="text-xl font-bold font-mono text-zinc-400">
                      {ibkrSummary?.closed_trades || 0}
                    </div>
                  </div>
                </div>
                
                {/* Recent Open Trades */}
                {ibkrTrades.length > 0 && (
                  <div className="mt-4">
                    <h4 className="text-sm text-zinc-500 mb-3 flex items-center gap-2">
                      <Briefcase className="w-4 h-4" />
                      Recent Open Positions
                    </h4>
                    <div className="space-y-2">
                      {ibkrTrades.slice(0, 4).map((trade, idx) => (
                        <div key={idx} className="flex items-center justify-between p-3 bg-zinc-800/30 rounded-lg hover:bg-zinc-800/50 transition-colors">
                          <div className="flex items-center gap-3">
                            <span className="font-semibold text-white">{trade.symbol}</span>
                            <Badge className="bg-violet-500/20 text-violet-400 text-xs">
                              {trade.strategy_label || trade.strategy_type}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-4 text-sm">
                            <div className="text-right">
                              <div className="text-zinc-400">{trade.shares} shares</div>
                              <div className="text-zinc-500 text-xs">Entry: {formatCurrency(trade.entry_price || 0)}</div>
                            </div>
                            {trade.current_price && (
                              <div className={`text-right ${(trade.unrealized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                <div>{formatCurrency(trade.unrealized_pnl || 0)}</div>
                                <div className="text-xs text-zinc-500">@ {formatCurrency(trade.current_price)}</div>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              // Mockup for users without IBKR data
              <div className="text-center py-8">
                <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-violet-500/20 flex items-center justify-center">
                  <Upload className="w-8 h-8 text-violet-400" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">Track Your Portfolio</h3>
                <p className="text-zinc-400 text-sm mb-6 max-w-md mx-auto">
                  Import your Interactive Brokers transaction history to see your trades, P/L, and AI-powered suggestions.
                </p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Sample: Total Invested</div>
                    <div className="text-xl font-bold font-mono text-zinc-600">$50,000</div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Sample: Premium</div>
                    <div className="text-xl font-bold font-mono text-zinc-600">$2,500</div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Sample: Open Trades</div>
                    <div className="text-xl font-bold font-mono text-zinc-600">12</div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-800/30">
                    <div className="text-xs text-zinc-500 mb-1">Sample: Closed</div>
                    <div className="text-xl font-bold font-mono text-zinc-600">8</div>
                  </div>
                </div>
                <Button
                  onClick={() => navigate('/portfolio')}
                  className="bg-violet-600 hover:bg-violet-700"
                >
                  <Upload className="w-4 h-4 mr-2" />
                  Import IBKR Data
                </Button>
              </div>
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
                    <tr 
                      key={index} 
                      className="cursor-pointer hover:bg-zinc-800/50 transition-colors" 
                      data-testid={`opportunity-${opp.symbol}`}
                      onClick={() => {
                        setSelectedStock(opp.symbol);
                        setIsModalOpen(true);
                      }}
                      title={`Click to view ${opp.symbol} details`}
                    >
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

      {/* Stock Detail Modal */}
      <StockDetailModal 
        symbol={selectedStock}
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setSelectedStock(null);
        }}
      />

      {/* Data Source Notice */}
      {opportunitiesInfo && (
        <div className={`glass-card p-4 border-l-4 ${opportunitiesInfo?.is_live ? 'border-emerald-500' : 'border-yellow-500'}`}>
          <div className="flex items-center gap-3">
            {opportunitiesInfo?.is_live ? (
              <CheckCircle className="w-5 h-5 text-emerald-400" />
            ) : (
              <Activity className="w-5 h-5 text-yellow-400" />
            )}
            <div>
              <div className={`text-sm font-medium ${opportunitiesInfo?.is_live ? 'text-emerald-400' : 'text-yellow-400'}`}>
                {opportunitiesInfo?.is_live ? 'Live Market Data' : 'Using Mock Data'}
              </div>
              <div className="text-xs text-zinc-500">
                {opportunitiesInfo?.is_live
                  ? 'Data from Massive.com API • Includes SMA, trend analysis, and dividend data'
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
