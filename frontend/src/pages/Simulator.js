import { useState, useEffect } from 'react';
import { simulatorApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
  Play,
  RefreshCw,
  Trash2,
  TrendingUp,
  TrendingDown,
  DollarSign,
  BarChart3,
  Target,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Activity,
  Percent,
  Calendar,
  Layers,
  X
} from 'lucide-react';
import { toast } from 'sonner';
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from 'recharts';

const STATUS_COLORS = {
  'active': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'closed': 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
  'expired': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'assigned': 'bg-amber-500/20 text-amber-400 border-amber-500/30'
};

const STRATEGY_COLORS = {
  'covered_call': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'pmcc': 'bg-violet-500/20 text-violet-400 border-violet-500/30'
};

const CHART_COLORS = {
  covered_call: '#10b981',
  pmcc: '#8b5cf6',
  profit: '#10b981',
  loss: '#ef4444'
};

const Simulator = () => {
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [selectedTrade, setSelectedTrade] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  
  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [strategyFilter, setStrategyFilter] = useState('');
  
  // Pagination
  const [pagination, setPagination] = useState({
    page: 1,
    pages: 1,
    total: 0
  });

  useEffect(() => {
    fetchTrades();
    fetchSummary();
  }, [statusFilter, strategyFilter, pagination.page]);

  const fetchTrades = async () => {
    setLoading(true);
    try {
      const res = await simulatorApi.getTrades({
        status: statusFilter || undefined,
        strategy: strategyFilter || undefined,
        page: pagination.page,
        limit: 20
      });
      setTrades(res.data.trades || []);
      setPagination(prev => ({
        ...prev,
        pages: res.data.pages || 1,
        total: res.data.total || 0
      }));
    } catch (error) {
      console.error('Error fetching simulator trades:', error);
      toast.error('Failed to load simulator trades');
    } finally {
      setLoading(false);
    }
  };

  const fetchSummary = async () => {
    try {
      const res = await simulatorApi.getSummary();
      setSummary(res.data);
    } catch (error) {
      console.error('Error fetching summary:', error);
    }
  };

  const handleUpdatePrices = async () => {
    setUpdating(true);
    try {
      const res = await simulatorApi.updatePrices();
      toast.success(`Updated ${res.data.updated} trades. Expired: ${res.data.expired}, Assigned: ${res.data.assigned}`);
      fetchTrades();
      fetchSummary();
    } catch (error) {
      toast.error('Failed to update prices');
    } finally {
      setUpdating(false);
    }
  };

  const handleDeleteTrade = async (tradeId) => {
    if (!window.confirm('Are you sure you want to delete this simulated trade?')) return;
    
    try {
      await simulatorApi.deleteTrade(tradeId);
      toast.success('Trade deleted');
      fetchTrades();
      fetchSummary();
      setDetailOpen(false);
    } catch (error) {
      toast.error('Failed to delete trade');
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm('Are you sure you want to clear ALL simulator data? This cannot be undone.')) return;
    
    try {
      await simulatorApi.clearAll();
      toast.success('All simulator data cleared');
      fetchTrades();
      fetchSummary();
    } catch (error) {
      toast.error('Failed to clear data');
    }
  };

  const formatCurrency = (value) => {
    if (value === null || value === undefined) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(value);
  };

  const formatPercent = (value) => {
    if (value === null || value === undefined) return '-';
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
    } catch {
      return dateStr;
    }
  };

  const formatOptionContract = (expiry, strike) => {
    if (!expiry || !strike) return '-';
    try {
      const date = new Date(expiry);
      const day = date.getDate().toString().padStart(2, '0');
      const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
      const month = months[date.getMonth()];
      const year = date.getFullYear().toString().slice(-2);
      return `${day}${month}${year} $${strike} C`;
    } catch {
      return `$${strike} C`;
    }
  };

  // Prepare chart data
  const strategyDistribution = summary?.by_strategy ? Object.entries(summary.by_strategy).map(([key, value]) => ({
    name: key === 'covered_call' ? 'Covered Call' : 'PMCC',
    value: value.total,
    color: CHART_COLORS[key]
  })).filter(d => d.value > 0) : [];

  const pnlByStrategy = summary?.by_strategy ? Object.entries(summary.by_strategy).map(([key, value]) => ({
    name: key === 'covered_call' ? 'Covered Call' : 'PMCC',
    realized: value.realized_pnl,
    unrealized: value.unrealized_pnl
  })) : [];

  return (
    <div className="space-y-6" data-testid="simulator-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Play className="w-8 h-8 text-violet-500" />
            Trade Simulator
          </h1>
          <p className="text-zinc-400 mt-1">
            Forward-running simulation engine for strategy validation
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleUpdatePrices}
            disabled={updating}
            className="btn-outline"
            data-testid="update-prices-btn"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${updating ? 'animate-spin' : ''}`} />
            {updating ? 'Updating...' : 'Update Prices'}
          </Button>
          <Button
            variant="outline"
            onClick={handleClearAll}
            className="btn-outline text-red-400 hover:text-red-300"
            data-testid="clear-all-btn"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Clear All
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        {loading && !summary ? (
          Array(6).fill(0).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))
        ) : (
          <>
            <Card className="glass-card" data-testid="total-pnl-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <DollarSign className="w-4 h-4" />
                  Total P/L
                </div>
                <div className={`text-xl font-bold font-mono ${(summary?.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatCurrency(summary?.total_pnl || 0)}
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="win-rate-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <Target className="w-4 h-4" />
                  Win Rate
                </div>
                <div className="text-xl font-bold font-mono text-white">
                  {summary?.win_rate?.toFixed(1) || 0}%
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="active-trades-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <Activity className="w-4 h-4" />
                  Active Trades
                </div>
                <div className="text-xl font-bold font-mono text-blue-400">
                  {summary?.active_trades || 0}
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="capital-deployed-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <Layers className="w-4 h-4" />
                  Capital Deployed
                </div>
                <div className="text-xl font-bold font-mono text-white">
                  {formatCurrency(summary?.total_capital_deployed || 0)}
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="avg-return-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <Percent className="w-4 h-4" />
                  Avg Return
                </div>
                <div className="text-xl font-bold font-mono text-white">
                  {formatCurrency(summary?.avg_return_per_trade || 0)}
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="assignment-rate-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <AlertCircle className="w-4 h-4" />
                  Assignment Rate
                </div>
                <div className="text-xl font-bold font-mono text-amber-400">
                  {summary?.assignment_rate?.toFixed(1) || 0}%
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {/* Charts Row */}
      {summary && (summary.total_trades > 0) && (
        <div className="grid md:grid-cols-2 gap-6">
          {/* Strategy Distribution */}
          {strategyDistribution.length > 0 && (
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-violet-400" />
                  Strategy Distribution
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={strategyDistribution}
                        cx="50%"
                        cy="50%"
                        innerRadius={40}
                        outerRadius={70}
                        paddingAngle={2}
                        dataKey="value"
                        label={({ name, value }) => `${name}: ${value}`}
                        labelLine={false}
                      >
                        {strategyDistribution.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip 
                        contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex justify-center gap-4 mt-2">
                  <div className="flex items-center gap-1.5 text-xs">
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500"></div>
                    <span className="text-zinc-400">Covered Call</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs">
                    <div className="w-2.5 h-2.5 rounded-full bg-violet-500"></div>
                    <span className="text-zinc-400">PMCC</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* P&L by Strategy */}
          {pnlByStrategy.some(d => d.realized !== 0 || d.unrealized !== 0) && (
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                  P/L by Strategy
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={pnlByStrategy} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                      <XAxis type="number" tickFormatter={(v) => `$${v >= 1000 ? (v/1000).toFixed(1) + 'k' : v}`} stroke="#666" fontSize={10} />
                      <YAxis type="category" dataKey="name" stroke="#999" fontSize={10} width={80} />
                      <Tooltip 
                        contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                        formatter={(value) => formatCurrency(value)}
                      />
                      <Legend />
                      <Bar dataKey="realized" name="Realized" fill="#10b981" radius={[0, 4, 4, 0]} />
                      <Bar dataKey="unrealized" name="Unrealized" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Filters & Trades Table */}
      <Card className="glass-card" data-testid="trades-table-card">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <Activity className="w-5 h-5 text-violet-400" />
            Simulated Trades ({pagination.total})
          </CardTitle>
          <div className="flex gap-2">
            <Select value={statusFilter || "all"} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
              <SelectTrigger className="w-32 h-8 bg-zinc-800/50 border-zinc-700">
                <SelectValue placeholder="All Status" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-700">
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="closed">Closed</SelectItem>
                <SelectItem value="expired">Expired</SelectItem>
                <SelectItem value="assigned">Assigned</SelectItem>
              </SelectContent>
            </Select>
            <Select value={strategyFilter || "all"} onValueChange={(v) => setStrategyFilter(v === "all" ? "" : v)}>
              <SelectTrigger className="w-36 h-8 bg-zinc-800/50 border-zinc-700">
                <SelectValue placeholder="All Strategies" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-700">
                <SelectItem value="all">All Strategies</SelectItem>
                <SelectItem value="covered_call">Covered Call</SelectItem>
                <SelectItem value="pmcc">PMCC</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {Array(5).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : trades.length === 0 ? (
            <div className="text-center py-12">
              <Play className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-white mb-2">No Simulated Trades Yet</h3>
              <p className="text-zinc-400 text-sm mb-4">
                Add trades from the Screener or PMCC pages using the "SIMULATE" button
              </p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-zinc-500 border-b border-zinc-800">
                      <th className="pb-3 font-medium">Symbol</th>
                      <th className="pb-3 font-medium">Strategy</th>
                      <th className="pb-3 font-medium">Status</th>
                      <th className="pb-3 font-medium">Entry</th>
                      <th className="pb-3 font-medium">Contract</th>
                      <th className="pb-3 font-medium">DTE</th>
                      <th className="pb-3 font-medium">Capital</th>
                      <th className="pb-3 font-medium">P/L</th>
                      <th className="pb-3 font-medium">ROI</th>
                      <th className="pb-3 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((trade) => (
                      <tr 
                        key={trade.id}
                        className="border-b border-zinc-800/50 hover:bg-zinc-800/30 cursor-pointer"
                        onClick={() => {
                          setSelectedTrade(trade);
                          setDetailOpen(true);
                        }}
                        data-testid={`simulator-row-${trade.symbol}`}
                      >
                        <td className="py-3 font-semibold text-white">{trade.symbol}</td>
                        <td>
                          <Badge className={STRATEGY_COLORS[trade.strategy_type]}>
                            {trade.strategy_type === 'covered_call' ? 'CC' : 'PMCC'}
                          </Badge>
                        </td>
                        <td>
                          <Badge className={STATUS_COLORS[trade.status]}>
                            {trade.status}
                          </Badge>
                        </td>
                        <td className="text-zinc-300">${trade.entry_underlying_price?.toFixed(2)}</td>
                        <td className="font-mono text-xs text-zinc-400">
                          {formatOptionContract(trade.short_call_expiry, trade.short_call_strike)}
                        </td>
                        <td className={`${trade.dte_remaining <= 7 ? 'text-amber-400' : 'text-zinc-300'}`}>
                          {trade.status === 'active' ? `${trade.dte_remaining}d` : '-'}
                        </td>
                        <td className="text-zinc-300">{formatCurrency(trade.capital_deployed)}</td>
                        <td className={`font-mono ${
                          trade.status === 'active' 
                            ? (trade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                            : (trade.final_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                        }`}>
                          {trade.status === 'active' 
                            ? formatCurrency(trade.unrealized_pnl)
                            : formatCurrency(trade.final_pnl)
                          }
                        </td>
                        <td className={`font-mono ${
                          trade.status === 'active'
                            ? ((trade.unrealized_pnl / trade.capital_deployed * 100) >= 0 ? 'text-emerald-400' : 'text-red-400')
                            : (trade.roi_percent >= 0 ? 'text-emerald-400' : 'text-red-400')
                        }`}>
                          {trade.status === 'active'
                            ? formatPercent(trade.capital_deployed > 0 ? (trade.unrealized_pnl / trade.capital_deployed * 100) : 0)
                            : formatPercent(trade.roi_percent)
                          }
                        </td>
                        <td>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteTrade(trade.id);
                            }}
                            className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {pagination.pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-800">
                  <span className="text-sm text-zinc-500">
                    Page {pagination.page} of {pagination.pages}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPagination(p => ({ ...p, page: p.page - 1 }))}
                      disabled={pagination.page === 1}
                      className="btn-outline"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPagination(p => ({ ...p, page: p.page + 1 }))}
                      disabled={pagination.page === pagination.pages}
                      className="btn-outline"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Trade Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="bg-zinc-900 border-zinc-800 max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <span className="text-white">{selectedTrade?.symbol}</span>
              <Badge className={STRATEGY_COLORS[selectedTrade?.strategy_type]}>
                {selectedTrade?.strategy_type === 'covered_call' ? 'Covered Call' : 'PMCC'}
              </Badge>
              <Badge className={STATUS_COLORS[selectedTrade?.status]}>
                {selectedTrade?.status}
              </Badge>
            </DialogTitle>
          </DialogHeader>
          
          {selectedTrade && (
            <div className="space-y-6 pt-4">
              {/* Entry Details */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Entry Price</div>
                  <div className="text-lg font-semibold text-white">${selectedTrade.entry_underlying_price?.toFixed(2)}</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Current Price</div>
                  <div className="text-lg font-semibold text-white">${selectedTrade.current_underlying_price?.toFixed(2)}</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Breakeven</div>
                  <div className="text-lg font-semibold text-white">${selectedTrade.breakeven?.toFixed(2)}</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">{selectedTrade.status === 'active' ? 'Unrealized P/L' : 'Final P/L'}</div>
                  <div className={`text-lg font-semibold ${
                    selectedTrade.status === 'active'
                      ? (selectedTrade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                      : (selectedTrade.final_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                  }`}>
                    {selectedTrade.status === 'active' 
                      ? formatCurrency(selectedTrade.unrealized_pnl)
                      : formatCurrency(selectedTrade.final_pnl)
                    }
                  </div>
                </div>
              </div>

              {/* Option Details */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-zinc-500">Short Call:</span>
                  <span className="ml-2 text-white">
                    {formatOptionContract(selectedTrade.short_call_expiry, selectedTrade.short_call_strike)}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-500">Premium:</span>
                  <span className="ml-2 text-emerald-400">${selectedTrade.short_call_premium?.toFixed(2)}</span>
                </div>
                {selectedTrade.strategy_type === 'pmcc' && (
                  <>
                    <div>
                      <span className="text-zinc-500">LEAPS:</span>
                      <span className="ml-2 text-white">
                        {formatOptionContract(selectedTrade.leaps_expiry, selectedTrade.leaps_strike)}
                      </span>
                    </div>
                    <div>
                      <span className="text-zinc-500">LEAPS Cost:</span>
                      <span className="ml-2 text-amber-400">${selectedTrade.leaps_premium?.toFixed(2)}</span>
                    </div>
                  </>
                )}
                <div>
                  <span className="text-zinc-500">Contracts:</span>
                  <span className="ml-2 text-white">{selectedTrade.contracts}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Capital Deployed:</span>
                  <span className="ml-2 text-white">{formatCurrency(selectedTrade.capital_deployed)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Max Profit:</span>
                  <span className="ml-2 text-emerald-400">{formatCurrency(selectedTrade.max_profit)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Max Loss:</span>
                  <span className="ml-2 text-red-400">{formatCurrency(selectedTrade.max_loss)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Days Held:</span>
                  <span className="ml-2 text-white">{selectedTrade.days_held}</span>
                </div>
                <div>
                  <span className="text-zinc-500">DTE Remaining:</span>
                  <span className={`ml-2 ${selectedTrade.dte_remaining <= 7 ? 'text-amber-400' : 'text-white'}`}>
                    {selectedTrade.status === 'active' ? `${selectedTrade.dte_remaining}d` : '-'}
                  </span>
                </div>
              </div>

              {/* Action Log */}
              {selectedTrade.action_log && selectedTrade.action_log.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-zinc-400 mb-2 flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Action Log
                  </h4>
                  <div className="bg-zinc-800/50 rounded-lg p-3 space-y-2 max-h-32 overflow-y-auto">
                    {selectedTrade.action_log.map((log, idx) => (
                      <div key={idx} className="text-xs flex items-start gap-2">
                        <span className="text-zinc-500">{formatDate(log.timestamp)}</span>
                        <Badge className={log.action === 'opened' ? 'bg-blue-500/20 text-blue-400' : 'bg-emerald-500/20 text-emerald-400'}>
                          {log.action}
                        </Badge>
                        <span className="text-zinc-300">{log.details}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-end gap-2 pt-4 border-t border-zinc-800">
                <Button
                  variant="outline"
                  onClick={() => handleDeleteTrade(selectedTrade.id)}
                  className="text-red-400 hover:text-red-300"
                >
                  <Trash2 className="w-4 h-4 mr-2" />
                  Delete
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setDetailOpen(false)}
                  className="btn-outline"
                >
                  Close
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Simulator;
