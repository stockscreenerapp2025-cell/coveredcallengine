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
  PieChart,
  Clock,
  Moon,
  Sun
} from 'lucide-react';
import { toast } from 'sonner';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart as RechartsPie, Pie, Cell, Legend, BarChart, Bar, CartesianGrid } from 'recharts';
import StockDetailModal from '../components/StockDetailModal';
import api from '../lib/api';

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
  const [marketStatus, setMarketStatus] = useState(null);

  useEffect(() => {
    fetchDashboardData();
    fetchMarketStatus();
  }, []);

  const fetchMarketStatus = async () => {
    try {
      const res = await api.get('/market-status');
      setMarketStatus(res.data);
    } catch (error) {
      console.log('Could not fetch market status:', error);
    }
  };

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
        const [ibkrSummaryRes, ibkrClosedRes] = await Promise.all([
          portfolioApi.getIBKRSummary(),
          portfolioApi.getIBKRTrades({ status: 'Closed', limit: 15 })
        ]);
        setIbkrSummary(ibkrSummaryRes.data);
        setIbkrTrades(ibkrClosedRes.data.trades || []);
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

  // Format option contract display like "26SEP25 49.5 C"
  const formatOptionContract = (expiry, strike, optionType = 'call') => {
    if (!expiry || !strike) return '-';
    try {
      const date = new Date(expiry);
      const day = date.getDate().toString().padStart(2, '0');
      const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
      const month = months[date.getMonth()];
      const year = date.getFullYear().toString().slice(-2);
      // C for Call, P for Put
      const type = optionType?.toLowerCase() === 'put' ? 'P' : 'C';
      return `${day}${month}${year} ${strike} ${type}`;
    } catch {
      const type = optionType?.toLowerCase() === 'put' ? 'P' : 'C';
      return `${strike} ${type}`;
    }
  };

  // Portfolio performance colors
  const STRATEGY_COLORS = {
    COVERED_CALL: '#10b981',
    STOCK: '#3b82f6',
    ETF: '#8b5cf6',
    NAKED_PUT: '#f59e0b',
    PMCC: '#06b6d4',
    OTHER: '#6b7280'
  };

  // Prepare strategy distribution data for pie chart
  const strategyData = ibkrSummary?.by_strategy ? Object.entries(ibkrSummary.by_strategy).map(([key, value]) => ({
    name: key.replace('_', ' '),
    value: value.count,
    invested: value.invested,
    premium: value.premium,
    color: STRATEGY_COLORS[key] || STRATEGY_COLORS.OTHER
  })) : [];

  // Prepare performance data for bar chart - closed positions by realized P/L
  const closedPositions = ibkrTrades
    .filter(t => t.realized_pnl !== null && t.realized_pnl !== undefined)
    .map(t => ({
      symbol: t.symbol,
      pnl: t.realized_pnl || 0,
      roi: t.roi || 0
    }))
    .sort((a, b) => b.pnl - a.pnl)
    .slice(0, 12);

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
                
                {/* Portfolio Performance Graph */}
                {(strategyData.length > 0 || closedPositions.length > 0) && (
                  <div className="mt-6">
                    <h4 className="text-sm text-zinc-500 mb-4 flex items-center gap-2">
                      <PieChart className="w-4 h-4" />
                      Portfolio Performance Overview
                    </h4>
                    <div className="grid md:grid-cols-2 gap-6">
                      {/* Strategy Distribution Pie Chart */}
                      {strategyData.length > 0 && (
                        <div className="bg-zinc-800/30 rounded-lg p-4">
                          <h5 className="text-xs text-zinc-400 mb-3">Strategy Distribution</h5>
                          <div className="h-48">
                            <ResponsiveContainer width="100%" height="100%">
                              <RechartsPie>
                                <Pie
                                  data={strategyData}
                                  cx="50%"
                                  cy="50%"
                                  innerRadius={40}
                                  outerRadius={70}
                                  paddingAngle={2}
                                  dataKey="value"
                                  label={({ name, value }) => `${name}: ${value}`}
                                  labelLine={false}
                                >
                                  {strategyData.map((entry, index) => (
                                    <Cell key={`cell-${index}`} fill={entry.color} />
                                  ))}
                                </Pie>
                                <Tooltip 
                                  contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                                  formatter={(value, name, props) => [
                                    `${value} trades | Invested: ${formatCurrency(props.payload.invested)} | Premium: ${formatCurrency(props.payload.premium)}`,
                                    props.payload.name
                                  ]}
                                />
                              </RechartsPie>
                            </ResponsiveContainer>
                          </div>
                          <div className="flex flex-wrap gap-2 mt-2 justify-center">
                            {strategyData.map((s, i) => (
                              <div key={i} className="flex items-center gap-1.5 text-xs">
                                <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }}></div>
                                <span className="text-zinc-400">{s.name}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      
                      {/* Closed Positions P/L Bar Chart */}
                      {closedPositions.length > 0 && (
                        <div className="bg-zinc-800/30 rounded-lg p-4">
                          <h5 className="text-xs text-zinc-400 mb-3">Closed Positions - Realized P/L</h5>
                          <div className="h-56">
                            <ResponsiveContainer width="100%" height="100%">
                              <BarChart data={closedPositions} layout="vertical" margin={{ left: 5, right: 10, top: 5, bottom: 5 }} barSize={12}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#333" horizontal={false} />
                                <XAxis type="number" tickFormatter={(v) => v >= 1000 || v <= -1000 ? `$${(v/1000).toFixed(1)}k` : `$${v.toFixed(0)}`} stroke="#666" fontSize={9} />
                                <YAxis type="category" dataKey="symbol" stroke="#999" fontSize={10} width={40} interval={0} />
                                <Tooltip 
                                  contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                                  formatter={(value, name, props) => [
                                    <span style={{ color: value >= 0 ? '#10b981' : '#ef4444' }}>{formatCurrency(value)}</span>,
                                    <span style={{ color: '#a1a1aa' }}>Realized P/L</span>
                                  ]}
                                  labelFormatter={(label) => <span style={{ color: '#fff' }}>{label}</span>}
                                />
                                <Bar dataKey="pnl" radius={[0, 3, 3, 0]} name="P/L">
                                  {closedPositions.map((entry, index) => (
                                    <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
                                  ))}
                                </Bar>
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                          <div className="flex justify-center gap-4 mt-2 text-xs">
                            <div className="flex items-center gap-1.5">
                              <div className="w-2.5 h-2.5 rounded-full bg-emerald-500"></div>
                              <span className="text-zinc-400">Profit</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <div className="w-2.5 h-2.5 rounded-full bg-red-500"></div>
                              <span className="text-zinc-400">Loss</span>
                            </div>
                          </div>
                        </div>
                      )}
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
                    <th>AI Score</th>
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
                        <div className="flex flex-col">
                          <span className="font-mono text-sm">{formatOptionContract(opp.expiry, opp.strike?.toFixed(1))}</span>
                          <Badge className={`mt-0.5 w-fit ${opp.moneyness === 'ATM' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs' : 'bg-blue-500/20 text-blue-400 border-blue-500/30 text-xs'}`}>
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
