import { useState, useEffect, useRef, useCallback } from 'react';
import { portfolioApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
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
  Wallet,
  Upload,
  RefreshCw,
  Trash2,
  TrendingUp,
  TrendingDown,
  DollarSign,
  BarChart3,
  FileSpreadsheet,
  ExternalLink,
  Brain,
  ChevronLeft,
  ChevronRight,
  Search,
  Filter,
  Clock,
  CheckCircle,
  AlertCircle,
  XCircle,
  Loader2
} from 'lucide-react';
import { toast } from 'sonner';

// Strategy type badges
const STRATEGY_COLORS = {
  'STOCK': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'ETF': 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  'INDEX': 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  'COVERED_CALL': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'PMCC': 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  'NAKED_PUT': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  'COLLAR': 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  'OPTION': 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  'OTHER': 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'
};

const STATUS_COLORS = {
  'Open': 'bg-emerald-500/20 text-emerald-400',
  'Closed': 'bg-zinc-500/20 text-zinc-400',
  'Assigned': 'bg-amber-500/20 text-amber-400'
};

// AI Action colors
const ACTION_COLORS = {
  'HOLD': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'CLOSE': 'bg-red-500/20 text-red-400 border-red-500/30',
  'ROLL_UP': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'ROLL_DOWN': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  'ROLL_OUT': 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  'N/A': 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'
};

const Portfolio = () => {
  // State
  const [trades, setTrades] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [selectedTrade, setSelectedTrade] = useState(null);
  const [tradeDetailOpen, setTradeDetailOpen] = useState(false);
  const [loadingAI, setLoadingAI] = useState(false);
  const [generatingSuggestions, setGeneratingSuggestions] = useState(false);
  const fileInputRef = useRef(null);

  // Filters
  const [filters, setFilters] = useState({
    account: '',
    strategy: '',
    status: '',
    symbol: ''
  });

  // Pagination
  const [pagination, setPagination] = useState({
    page: 1,
    pages: 1,
    total: 0
  });

  // Fetch data on mount and filter change
  useEffect(() => {
    fetchAccounts();
  }, []);

  useEffect(() => {
    fetchTrades();
    fetchSummary();
  }, [filters, pagination.page]);

  const fetchAccounts = async () => {
    try {
      const res = await portfolioApi.getIBKRAccounts();
      setAccounts(res.data.accounts || []);
    } catch (error) {
      console.error('Error fetching accounts:', error);
    }
  };

  const fetchTrades = async () => {
    setLoading(true);
    try {
      const res = await portfolioApi.getIBKRTrades({
        ...filters,
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
      console.error('Error fetching trades:', error);
      toast.error('Failed to load trades');
    } finally {
      setLoading(false);
    }
  };

  const fetchSummary = async () => {
    try {
      const res = await portfolioApi.getIBKRSummary(filters.account || null);
      setSummary(res.data);
    } catch (error) {
      console.error('Error fetching summary:', error);
    }
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.csv')) {
      toast.error('Please upload a CSV file');
      return;
    }

    setUploading(true);
    try {
      const res = await portfolioApi.importIBKR(file);
      toast.success(res.data.message || 'CSV imported successfully');
      
      // Refresh data
      fetchAccounts();
      fetchTrades();
      fetchSummary();
    } catch (error) {
      console.error('Import error:', error);
      toast.error(error.response?.data?.detail || 'Failed to import CSV');
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleClearData = async () => {
    if (!window.confirm('Are you sure you want to clear all imported IBKR data? This cannot be undone.')) {
      return;
    }

    try {
      await portfolioApi.clearIBKRData();
      toast.success('All IBKR data cleared');
      setTrades([]);
      setAccounts([]);
      setSummary(null);
    } catch (error) {
      toast.error('Failed to clear data');
    }
  };

  const generateAllSuggestions = async () => {
    setGeneratingSuggestions(true);
    try {
      const res = await portfolioApi.generateAllSuggestions();
      toast.success(res.data.message || 'AI suggestions generated');
      // Refresh trades to show new suggestions
      fetchTrades();
    } catch (error) {
      toast.error('Failed to generate AI suggestions');
    } finally {
      setGeneratingSuggestions(false);
    }
  };

  const openTradeDetail = async (trade) => {
    try {
      const res = await portfolioApi.getIBKRTradeDetail(trade.id);
      setSelectedTrade(res.data);
      setTradeDetailOpen(true);
    } catch (error) {
      toast.error('Failed to load trade details');
    }
  };

  const getAISuggestion = async () => {
    if (!selectedTrade) return;
    
    setLoadingAI(true);
    try {
      const res = await portfolioApi.getAISuggestion(selectedTrade.id);
      setSelectedTrade(prev => ({
        ...prev,
        ai_suggestion: res.data.suggestion
      }));
      toast.success('AI suggestion generated');
    } catch (error) {
      toast.error('Failed to get AI suggestion');
    } finally {
      setLoadingAI(false);
    }
  };

  const formatCurrency = (value) => {
    if (value === null || value === undefined) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(value);
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString('en-AU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
      });
    } catch {
      return dateStr;
    }
  };

  const formatPercent = (value) => {
    if (value === null || value === undefined) return '-';
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  };

  return (
    <div className="space-y-6" data-testid="portfolio-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Wallet className="w-8 h-8 text-violet-500" />
            Portfolio Tracker
          </h1>
          <p className="text-zinc-400 mt-1">Import and track your IBKR transactions</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept=".csv"
            className="hidden"
          />
          <Button
            onClick={() => fileInputRef.current?.click()}
            className="bg-violet-600 hover:bg-violet-700"
            disabled={uploading}
          >
            {uploading ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Upload className="w-4 h-4 mr-2" />
            )}
            Import IBKR CSV
          </Button>
          <Button
            onClick={fetchTrades}
            variant="outline"
            className="border-zinc-700"
          >
            <RefreshCw className="w-4 h-4" />
          </Button>
          {trades.length > 0 && (
            <Button
              onClick={handleClearData}
              variant="outline"
              className="border-red-700 text-red-400 hover:bg-red-500/10"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          <Card className="glass-card">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-zinc-400 text-sm mb-1">
                <BarChart3 className="w-4 h-4" />
                Total Trades
              </div>
              <div className="text-2xl font-bold text-white">{summary.total_trades || 0}</div>
            </CardContent>
          </Card>
          <Card className="glass-card">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-zinc-400 text-sm mb-1">
                <CheckCircle className="w-4 h-4 text-emerald-400" />
                Open
              </div>
              <div className="text-2xl font-bold text-emerald-400">{summary.open_trades || 0}</div>
            </CardContent>
          </Card>
          <Card className="glass-card">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-zinc-400 text-sm mb-1">
                <XCircle className="w-4 h-4 text-zinc-400" />
                Closed
              </div>
              <div className="text-2xl font-bold text-zinc-300">{summary.closed_trades || 0}</div>
            </CardContent>
          </Card>
          <Card className="glass-card">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-zinc-400 text-sm mb-1">
                <DollarSign className="w-4 h-4 text-blue-400" />
                Invested
              </div>
              <div className="text-xl font-bold text-white">{formatCurrency(summary.total_invested)}</div>
            </CardContent>
          </Card>
          <Card className="glass-card">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-zinc-400 text-sm mb-1">
                <TrendingUp className="w-4 h-4 text-emerald-400" />
                Premium
              </div>
              <div className="text-xl font-bold text-emerald-400">{formatCurrency(summary.total_premium)}</div>
            </CardContent>
          </Card>
          <Card className="glass-card">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-zinc-400 text-sm mb-1">
                <AlertCircle className="w-4 h-4 text-amber-400" />
                Fees
              </div>
              <div className="text-xl font-bold text-amber-400">{formatCurrency(summary.total_fees)}</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filters */}
      <Card className="glass-card">
        <CardContent className="p-4">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-zinc-400" />
              <span className="text-sm text-zinc-400">Filters:</span>
            </div>
            
            {/* Account Filter */}
            {accounts.length > 0 && (
              <Select
                value={filters.account}
                onValueChange={(v) => setFilters(f => ({ ...f, account: v === 'all' ? '' : v }))}
              >
                <SelectTrigger className="w-48 bg-zinc-800 border-zinc-700">
                  <SelectValue placeholder="All Accounts" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Accounts</SelectItem>
                  {accounts.map(acc => (
                    <SelectItem key={acc} value={acc}>{acc}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}

            {/* Strategy Filter */}
            <Select
              value={filters.strategy}
              onValueChange={(v) => setFilters(f => ({ ...f, strategy: v === 'all' ? '' : v }))}
            >
              <SelectTrigger className="w-40 bg-zinc-800 border-zinc-700">
                <SelectValue placeholder="All Strategies" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Strategies</SelectItem>
                <SelectItem value="STOCK">Stock</SelectItem>
                <SelectItem value="ETF">ETF</SelectItem>
                <SelectItem value="COVERED_CALL">Covered Call</SelectItem>
                <SelectItem value="PMCC">PMCC</SelectItem>
                <SelectItem value="NAKED_PUT">Naked Put</SelectItem>
                <SelectItem value="COLLAR">Collar</SelectItem>
              </SelectContent>
            </Select>

            {/* Status Filter */}
            <Select
              value={filters.status}
              onValueChange={(v) => setFilters(f => ({ ...f, status: v === 'all' ? '' : v }))}
            >
              <SelectTrigger className="w-32 bg-zinc-800 border-zinc-700">
                <SelectValue placeholder="All Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="Open">Open</SelectItem>
                <SelectItem value="Closed">Closed</SelectItem>
                <SelectItem value="Assigned">Assigned</SelectItem>
              </SelectContent>
            </Select>

            {/* Symbol Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <Input
                placeholder="Search symbol..."
                value={filters.symbol}
                onChange={(e) => setFilters(f => ({ ...f, symbol: e.target.value }))}
                className="pl-9 w-40 bg-zinc-800 border-zinc-700"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Trades Table */}
      <Card className="glass-card">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-violet-400" />
            Trades ({pagination.total})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4, 5].map(i => (
                <Skeleton key={i} className="h-12 w-full bg-zinc-800" />
              ))}
            </div>
          ) : trades.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">
              <FileSpreadsheet className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p className="text-lg mb-2">No trades found</p>
              <p className="text-sm">Import your IBKR transaction CSV to get started</p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="border-zinc-800">
                      <TableHead className="text-zinc-400">Symbol</TableHead>
                      <TableHead className="text-zinc-400">Strategy</TableHead>
                      <TableHead className="text-zinc-400">Status</TableHead>
                      <TableHead className="text-zinc-400">Opened</TableHead>
                      <TableHead className="text-zinc-400">Days</TableHead>
                      <TableHead className="text-zinc-400">DTE</TableHead>
                      <TableHead className="text-zinc-400 text-right">Shares</TableHead>
                      <TableHead className="text-zinc-400 text-right">Entry</TableHead>
                      <TableHead className="text-zinc-400 text-right">Premium</TableHead>
                      <TableHead className="text-zinc-400 text-right">Fees</TableHead>
                      <TableHead className="text-zinc-400 text-right">Break-Even</TableHead>
                      <TableHead className="text-zinc-400 text-right">Current</TableHead>
                      <TableHead className="text-zinc-400 text-right">P/L</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {trades.map((trade) => (
                      <TableRow
                        key={trade.id}
                        className="border-zinc-800 hover:bg-zinc-800/50 cursor-pointer"
                        onClick={() => openTradeDetail(trade)}
                      >
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-white">{trade.symbol}</span>
                            <a
                              href={`https://finance.yahoo.com/quote/${trade.symbol}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-zinc-500 hover:text-violet-400"
                            >
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge className={STRATEGY_COLORS[trade.strategy_type] || STRATEGY_COLORS.OTHER}>
                            {trade.strategy_label || trade.strategy_type}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge className={STATUS_COLORS[trade.status] || STATUS_COLORS.Open}>
                            {trade.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-zinc-300">{formatDate(trade.date_opened)}</TableCell>
                        <TableCell className="text-zinc-400">{trade.days_in_trade || '-'}</TableCell>
                        <TableCell className="text-zinc-400">{trade.dte ?? '-'}</TableCell>
                        <TableCell className="text-right text-zinc-300">{trade.shares || '-'}</TableCell>
                        <TableCell className="text-right text-zinc-300">{formatCurrency(trade.entry_price)}</TableCell>
                        <TableCell className="text-right text-emerald-400">{formatCurrency(trade.premium_received)}</TableCell>
                        <TableCell className="text-right text-amber-400">{formatCurrency(trade.total_fees)}</TableCell>
                        <TableCell className="text-right text-zinc-300">{formatCurrency(trade.break_even)}</TableCell>
                        <TableCell className="text-right text-zinc-300">{formatCurrency(trade.current_price)}</TableCell>
                        <TableCell className="text-right">
                          {trade.unrealized_pnl !== null && trade.unrealized_pnl !== undefined ? (
                            <span className={trade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                              {formatCurrency(trade.unrealized_pnl)}
                            </span>
                          ) : '-'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Pagination */}
              {pagination.pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-800">
                  <div className="text-sm text-zinc-500">
                    Page {pagination.page} of {pagination.pages}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPagination(p => ({ ...p, page: p.page - 1 }))}
                      disabled={pagination.page <= 1}
                      className="border-zinc-700"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPagination(p => ({ ...p, page: p.page + 1 }))}
                      disabled={pagination.page >= pagination.pages}
                      className="border-zinc-700"
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
      <Dialog open={tradeDetailOpen} onOpenChange={setTradeDetailOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto bg-zinc-900 border-zinc-800">
          <DialogHeader>
            <DialogTitle className="text-xl flex items-center gap-3">
              <span className="text-white">{selectedTrade?.symbol}</span>
              <Badge className={STRATEGY_COLORS[selectedTrade?.strategy_type] || STRATEGY_COLORS.OTHER}>
                {selectedTrade?.strategy_label || selectedTrade?.strategy_type}
              </Badge>
              <Badge className={STATUS_COLORS[selectedTrade?.status] || STATUS_COLORS.Open}>
                {selectedTrade?.status}
              </Badge>
            </DialogTitle>
          </DialogHeader>

          {selectedTrade && (
            <div className="space-y-6">
              {/* Trade Summary */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <div className="text-xs text-zinc-500">Entry Price</div>
                  <div className="text-lg font-semibold text-white">{formatCurrency(selectedTrade.entry_price)}</div>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <div className="text-xs text-zinc-500">Current Price</div>
                  <div className="text-lg font-semibold text-white">{formatCurrency(selectedTrade.current_price)}</div>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <div className="text-xs text-zinc-500">Break-Even</div>
                  <div className="text-lg font-semibold text-white">{formatCurrency(selectedTrade.break_even)}</div>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <div className="text-xs text-zinc-500">Unrealized P/L</div>
                  <div className={`text-lg font-semibold ${selectedTrade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatCurrency(selectedTrade.unrealized_pnl)}
                  </div>
                </div>
              </div>

              {/* Trade Details */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-zinc-500">Account:</span>
                  <span className="ml-2 text-white">{selectedTrade.account}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Date Opened:</span>
                  <span className="ml-2 text-white">{formatDate(selectedTrade.date_opened)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Date Closed:</span>
                  <span className="ml-2 text-white">{formatDate(selectedTrade.date_closed) || '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Days in Trade:</span>
                  <span className="ml-2 text-white">{selectedTrade.days_in_trade || '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">DTE:</span>
                  <span className="ml-2 text-white">{selectedTrade.dte ?? '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Shares:</span>
                  <span className="ml-2 text-white">{selectedTrade.shares || '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Contracts:</span>
                  <span className="ml-2 text-white">{selectedTrade.contracts || '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Option Strike:</span>
                  <span className="ml-2 text-white">{selectedTrade.option_strike ? `$${selectedTrade.option_strike}` : '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Option Expiry:</span>
                  <span className="ml-2 text-white">{formatDate(selectedTrade.option_expiry) || '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Premium Received:</span>
                  <span className="ml-2 text-emerald-400">{formatCurrency(selectedTrade.premium_received)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">IBKR Fees:</span>
                  <span className="ml-2 text-amber-400">{formatCurrency(selectedTrade.total_fees)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">ROI:</span>
                  <span className={`ml-2 ${selectedTrade.roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {selectedTrade.roi !== null ? formatPercent(selectedTrade.roi) : '-'}
                  </span>
                </div>
              </div>

              {/* Transaction History */}
              {selectedTrade.transactions && selectedTrade.transactions.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-zinc-400 mb-2 flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Transaction History
                  </h4>
                  <div className="bg-zinc-800/50 rounded-lg overflow-hidden">
                    <Table>
                      <TableHeader>
                        <TableRow className="border-zinc-700">
                          <TableHead className="text-zinc-500 text-xs">Date</TableHead>
                          <TableHead className="text-zinc-500 text-xs">Type</TableHead>
                          <TableHead className="text-zinc-500 text-xs">Description</TableHead>
                          <TableHead className="text-zinc-500 text-xs text-right">Qty</TableHead>
                          <TableHead className="text-zinc-500 text-xs text-right">Price</TableHead>
                          <TableHead className="text-zinc-500 text-xs text-right">Net</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {selectedTrade.transactions.map((tx, idx) => (
                          <TableRow key={idx} className="border-zinc-700">
                            <TableCell className="text-xs text-zinc-300">{formatDate(tx.date)}</TableCell>
                            <TableCell className="text-xs">
                              <Badge variant="outline" className="text-xs border-zinc-600">
                                {tx.transaction_type}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-xs text-zinc-400 max-w-[200px] truncate">
                              {tx.description}
                            </TableCell>
                            <TableCell className="text-xs text-zinc-300 text-right">{tx.quantity || '-'}</TableCell>
                            <TableCell className="text-xs text-zinc-300 text-right">{formatCurrency(tx.price)}</TableCell>
                            <TableCell className={`text-xs text-right ${tx.net_amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {formatCurrency(tx.net_amount)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}

              {/* AI Suggestion */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-sm font-medium text-zinc-400 flex items-center gap-2">
                    <Brain className="w-4 h-4 text-violet-400" />
                    AI Suggestion
                  </h4>
                  <Button
                    size="sm"
                    onClick={getAISuggestion}
                    disabled={loadingAI}
                    className="bg-violet-600 hover:bg-violet-700"
                  >
                    {loadingAI ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Brain className="w-4 h-4 mr-2" />
                    )}
                    {selectedTrade.ai_suggestion ? 'Refresh' : 'Get Suggestion'}
                  </Button>
                </div>
                {selectedTrade.ai_suggestion ? (
                  <div className="bg-violet-500/10 border border-violet-500/30 rounded-lg p-4">
                    <p className="text-sm text-zinc-300 whitespace-pre-wrap">{selectedTrade.ai_suggestion}</p>
                  </div>
                ) : (
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center text-sm text-zinc-500">
                    Click "Get Suggestion" to receive AI-powered trade recommendations
                  </div>
                )}
              </div>

              {/* External Links */}
              <div className="flex items-center gap-4 pt-4 border-t border-zinc-800">
                <span className="text-sm text-zinc-500">Quick Links:</span>
                <a
                  href={`https://finance.yahoo.com/quote/${selectedTrade.symbol}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-violet-400 hover:underline flex items-center gap-1"
                >
                  Yahoo Finance <ExternalLink className="w-3 h-3" />
                </a>
                <a
                  href={`https://www.tradingview.com/symbols/${selectedTrade.symbol}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-violet-400 hover:underline flex items-center gap-1"
                >
                  TradingView <ExternalLink className="w-3 h-3" />
                </a>
                <a
                  href={`https://www.google.com/search?q=${selectedTrade.symbol}+stock+news`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-violet-400 hover:underline flex items-center gap-1"
                >
                  News <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Portfolio;
