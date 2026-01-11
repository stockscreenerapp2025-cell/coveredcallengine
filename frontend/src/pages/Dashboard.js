import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { stocksApi, newsApi, screenerApi, portfolioApi, simulatorApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Skeleton } from '../components/ui/skeleton';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
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
  Sun,
  Play
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
  const [openTrades, setOpenTrades] = useState([]);
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
        const [ibkrSummaryRes, ibkrClosedRes, ibkrOpenRes] = await Promise.all([
          portfolioApi.getIBKRSummary(),
          portfolioApi.getIBKRTrades({ status: 'Closed', limit: 15 }),
          portfolioApi.getIBKRTrades({ status: 'Open', limit: 15 })
        ]);
        setIbkrSummary(ibkrSummaryRes.data);
        setIbkrTrades(ibkrClosedRes.data.trades || []);
        setOpenTrades(ibkrOpenRes.data.trades || []);
      } catch (ibkrError) {
        console.log('No IBKR data loaded:', ibkrError);
        setIbkrSummary(null);
        setIbkrTrades([]);
        setOpenTrades([]);
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

  // Prepare performance data for bar chart - open positions by unrealized P/L or ROI
  const openPositions = openTrades
    .filter(t => t.unrealized_pnl !== null && t.unrealized_pnl !== undefined || t.roi !== null && t.roi !== undefined)
    .map(t => ({
      symbol: t.symbol,
      pnl: t.unrealized_pnl || 0,
      roi: t.roi || 0,
      current_price: t.current_price || 0,
      entry_price: t.entry_price || 0
    }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
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
      {/* Market Status Banner */}
      {marketStatus && !marketStatus.is_open && (
        <div className="glass-card p-3 flex items-center justify-between bg-zinc-800/50 border-amber-500/30">
          <div className="flex items-center gap-3">
            {marketStatus.is_weekend ? (
              <Moon className="w-5 h-5 text-amber-400" />
            ) : (
              <Clock className="w-5 h-5 text-amber-400" />
            )}
            <div>
              <span className="text-amber-400 font-medium">{marketStatus.reason}</span>
              <span className="text-zinc-400 ml-2 text-sm">• {marketStatus.data_note}</span>
            </div>
          </div>
          <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30">
            {marketStatus.current_time_et}
          </Badge>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Search className="w-8 h-8 text-emerald-500" />
            Dashboard
            {marketStatus && (
              <Badge className={`ml-2 ${marketStatus.is_open ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'}`}>
                {marketStatus.is_open ? (
                  <><Sun className="w-3 h-3 mr-1" /> Market Open</>
                ) : (
                  <><Moon className="w-3 h-3 mr-1" /> Market Closed</>
                )}
              </Badge>
            )}
          </h1>
          <p className="text-zinc-400 mt-1">
            {marketStatus && !marketStatus.is_open 
              ? "Showing data from last market session" 
              : "Real-time market overview and opportunities"}
          </p>
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

                      {/* Open Positions P/L Bar Chart - shows when no closed positions but has open positions */}
                      {closedPositions.length === 0 && openPositions.length > 0 && (
                        <div className="bg-zinc-800/30 rounded-lg p-4">
                          <h5 className="text-xs text-zinc-400 mb-3">Open Positions - Unrealized P/L</h5>
                          <div className="h-56">
                            <ResponsiveContainer width="100%" height="100%">
                              <BarChart data={openPositions} layout="vertical" margin={{ left: 5, right: 10, top: 5, bottom: 5 }} barSize={12}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#333" horizontal={false} />
                                <XAxis type="number" tickFormatter={(v) => v >= 1000 || v <= -1000 ? `$${(v/1000).toFixed(1)}k` : `$${v.toFixed(0)}`} stroke="#666" fontSize={9} />
                                <YAxis type="category" dataKey="symbol" stroke="#999" fontSize={10} width={40} interval={0} />
                                <Tooltip 
                                  contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                                  formatter={(value, name, props) => [
                                    <span style={{ color: value >= 0 ? '#10b981' : '#ef4444' }}>{formatCurrency(value)}</span>,
                                    <span style={{ color: '#a1a1aa' }}>Unrealized P/L</span>
                                  ]}
                                  labelFormatter={(label) => <span style={{ color: '#fff' }}>{label}</span>}
                                />
                                <Bar dataKey="pnl" radius={[0, 3, 3, 0]} name="P/L">
                                  {openPositions.map((entry, index) => (
                                    <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
                                  ))}
                                </Bar>
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                          <div className="flex justify-center gap-4 mt-2 text-xs">
                            <div className="flex items-center gap-1.5">
                              <div className="w-2.5 h-2.5 rounded-full bg-emerald-500"></div>
                              <span className="text-zinc-400">Gain</span>
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
              // Enhanced Mockup for users without IBKR data - colorful sample charts
              <div className="py-4">
                {/* Notification Banner */}
                <div className="mb-6 p-4 rounded-lg bg-gradient-to-r from-violet-500/20 via-purple-500/20 to-pink-500/20 border border-violet-500/30">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-full bg-violet-500/30 flex items-center justify-center flex-shrink-0">
                      <Upload className="w-5 h-5 text-violet-400" />
                    </div>
                    <div>
                      <h3 className="text-white font-semibold mb-1">📊 Sample Data Preview</h3>
                      <p className="text-zinc-400 text-sm">
                        Import your Interactive Brokers transaction history to see <span className="text-emerald-400 font-medium">your actual portfolio performance</span> here with real P/L, strategy breakdown, and AI-powered suggestions.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Sample Stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  <div className="p-4 rounded-lg bg-gradient-to-br from-blue-500/10 to-blue-600/5 border border-blue-500/20">
                    <div className="text-xs text-blue-400 mb-1">Total Invested</div>
                    <div className="text-xl font-bold font-mono text-blue-300">$52,450</div>
                    <div className="text-xs text-zinc-500 mt-1">Sample data</div>
                  </div>
                  <div className="p-4 rounded-lg bg-gradient-to-br from-cyan-500/10 to-cyan-600/5 border border-cyan-500/20">
                    <div className="text-xs text-cyan-400 mb-1">Premium Collected</div>
                    <div className="text-xl font-bold font-mono text-cyan-300">$3,280</div>
                    <div className="text-xs text-zinc-500 mt-1">Sample data</div>
                  </div>
                  <div className="p-4 rounded-lg bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border border-emerald-500/20">
                    <div className="text-xs text-emerald-400 mb-1">Open Trades</div>
                    <div className="text-xl font-bold font-mono text-emerald-300">14</div>
                    <div className="text-xs text-zinc-500 mt-1">Sample data</div>
                  </div>
                  <div className="p-4 rounded-lg bg-gradient-to-br from-amber-500/10 to-amber-600/5 border border-amber-500/20">
                    <div className="text-xs text-amber-400 mb-1">Realized P/L</div>
                    <div className="text-xl font-bold font-mono text-amber-300">+$1,845</div>
                    <div className="text-xs text-zinc-500 mt-1">Sample data</div>
                  </div>
                </div>

                {/* Sample Charts */}
                <div className="grid md:grid-cols-2 gap-6 mb-6">
                  {/* Sample Strategy Pie Chart */}
                  <div className="bg-zinc-800/30 rounded-lg p-4 border border-zinc-700/30">
                    <h5 className="text-xs text-zinc-400 mb-3">📈 Sample Strategy Distribution</h5>
                    <div className="h-48">
                      <ResponsiveContainer width="100%" height="100%">
                        <RechartsPie>
                          <Pie
                            data={[
                              { name: 'Covered Calls', value: 8, color: '#10b981' },
                              { name: 'PMCC', value: 4, color: '#06b6d4' },
                              { name: 'Stocks', value: 2, color: '#3b82f6' }
                            ]}
                            cx="50%"
                            cy="50%"
                            innerRadius={40}
                            outerRadius={70}
                            paddingAngle={2}
                            dataKey="value"
                            label={({ name, value }) => `${value}`}
                            labelLine={false}
                          >
                            <Cell fill="#10b981" />
                            <Cell fill="#06b6d4" />
                            <Cell fill="#3b82f6" />
                          </Pie>
                          <Tooltip 
                            contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                          />
                        </RechartsPie>
                      </ResponsiveContainer>
                    </div>
                    <div className="flex flex-wrap gap-3 mt-2 justify-center">
                      <div className="flex items-center gap-1.5 text-xs">
                        <div className="w-2.5 h-2.5 rounded-full bg-emerald-500"></div>
                        <span className="text-zinc-400">Covered Calls</span>
                      </div>
                      <div className="flex items-center gap-1.5 text-xs">
                        <div className="w-2.5 h-2.5 rounded-full bg-cyan-500"></div>
                        <span className="text-zinc-400">PMCC</span>
                      </div>
                      <div className="flex items-center gap-1.5 text-xs">
                        <div className="w-2.5 h-2.5 rounded-full bg-blue-500"></div>
                        <span className="text-zinc-400">Stocks</span>
                      </div>
                    </div>
                  </div>
                  
                  {/* Sample P/L Bar Chart */}
                  <div className="bg-zinc-800/30 rounded-lg p-4 border border-zinc-700/30">
                    <h5 className="text-xs text-zinc-400 mb-3">💰 Sample Realized P/L by Position</h5>
                    <div className="h-48">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart 
                          data={[
                            { symbol: 'AAPL', pnl: 520 },
                            { symbol: 'MSFT', pnl: 380 },
                            { symbol: 'AMD', pnl: 245 },
                            { symbol: 'NVDA', pnl: -120 },
                            { symbol: 'INTC', pnl: 410 },
                            { symbol: 'SPY', pnl: 310 }
                          ]} 
                          layout="vertical" 
                          margin={{ left: 5, right: 10, top: 5, bottom: 5 }} 
                          barSize={14}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="#333" horizontal={false} />
                          <XAxis type="number" tickFormatter={(v) => `$${v}`} stroke="#666" fontSize={9} />
                          <YAxis type="category" dataKey="symbol" stroke="#999" fontSize={10} width={40} interval={0} />
                          <Tooltip 
                            contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                            formatter={(value) => [`$${value}`, 'P/L']}
                          />
                          <Bar dataKey="pnl" radius={[0, 3, 3, 0]}>
                            {[520, 380, 245, -120, 410, 310].map((val, index) => (
                              <Cell key={`cell-${index}`} fill={val >= 0 ? '#10b981' : '#ef4444'} />
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
                </div>

                {/* CTA Button */}
                <div className="text-center">
                  <Button
                    onClick={() => navigate('/portfolio')}
                    className="bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-700 hover:to-purple-700 text-white px-6"
                  >
                    <Upload className="w-4 h-4 mr-2" />
                    Import Your IBKR Data
                  </Button>
                  <p className="text-zinc-500 text-xs mt-2">Replace sample data with your actual portfolio</p>
                </div>
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
