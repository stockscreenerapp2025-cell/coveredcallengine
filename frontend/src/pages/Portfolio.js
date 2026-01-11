import { useState, useEffect, useRef, useCallback } from 'react';
import { portfolioApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { Textarea } from '../components/ui/textarea';
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
  Loader2,
  Plus,
  Edit,
  X
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
  'NAKED_CALL': 'bg-red-500/20 text-red-400 border-red-500/30',
  'LONG_CALL': 'bg-teal-500/20 text-teal-400 border-teal-500/30',
  'LONG_PUT': 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  'COLLAR': 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  'OPTION': 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  'OTHER': 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'
};

const STATUS_COLORS = {
  'Open': 'bg-emerald-500/20 text-emerald-400',
  'Closed': 'bg-zinc-500/20 text-zinc-400'
};

// AI Action colors
const ACTION_COLORS = {
  'HOLD': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'CLOSE': 'bg-red-500/20 text-red-400 border-red-500/30',
  'LET_EXPIRE': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'ROLL_UP': 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
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

  // Manual Trade Entry State
  const [manualTradeOpen, setManualTradeOpen] = useState(false);
  const [savingManualTrade, setSavingManualTrade] = useState(false);
  const [manualTrade, setManualTrade] = useState({
    symbol: '',
    trade_type: 'covered_call',
    stock_quantity: '',
    stock_price: '',
    stock_date: '',
    option_type: 'call',
    option_action: 'sell',
    strike_price: '',
    expiry_date: '',
    option_premium: '',
    option_quantity: '',
    option_date: '',
    leaps_strike: '',
    leaps_expiry: '',
    leaps_cost: '',
    leaps_quantity: '',
    leaps_date: '',
    notes: ''
  });

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

  // Manual Trade Entry Handlers
  const resetManualTradeForm = () => {
    setManualTrade({
      symbol: '',
      trade_type: 'covered_call',
      stock_quantity: '',
      stock_price: '',
      stock_date: '',
      option_type: 'call',
      option_action: 'sell',
      strike_price: '',
      expiry_date: '',
      option_premium: '',
      option_quantity: '',
      option_date: '',
      leaps_strike: '',
      leaps_expiry: '',
      leaps_cost: '',
      leaps_quantity: '',
      leaps_date: '',
      notes: ''
    });
  };

  // Smart handler for stock quantity changes - auto-calculate contracts
  const handleStockQuantityChange = (value) => {
    const shares = parseInt(value) || 0;
    const contracts = Math.floor(shares / 100);
    
    setManualTrade(prev => ({
      ...prev,
      stock_quantity: value,
      // Auto-populate option_quantity for covered calls (1 contract per 100 shares)
      option_quantity: prev.trade_type === 'covered_call' && contracts > 0 ? contracts.toString() : prev.option_quantity
    }));
  };

  const handleManualTradeSubmit = async () => {
    // Validation - Symbol is always required
    if (!manualTrade.symbol || manualTrade.symbol.trim() === '') {
      toast.error('Symbol is required');
      return;
    }

    // Covered Call validation
    if (manualTrade.trade_type === 'covered_call') {
      if (!manualTrade.stock_quantity || !manualTrade.stock_price) {
        toast.error('Stock quantity and price are required for covered calls');
        return;
      }
      if (!manualTrade.strike_price || !manualTrade.option_premium) {
        toast.error('Strike price and premium are required for covered calls');
        return;
      }
      if (!manualTrade.expiry_date) {
        toast.error('Expiry date is required for covered calls');
        return;
      }
    }

    // PMCC validation
    if (manualTrade.trade_type === 'pmcc') {
      if (!manualTrade.leaps_cost || !manualTrade.leaps_strike) {
        toast.error('LEAPS cost and strike are required for PMCC');
        return;
      }
      if (!manualTrade.leaps_expiry) {
        toast.error('LEAPS expiry date is required for PMCC');
        return;
      }
      if (!manualTrade.strike_price || !manualTrade.option_premium) {
        toast.error('Short call strike and premium are required for PMCC');
        return;
      }
      if (!manualTrade.expiry_date) {
        toast.error('Short call expiry date is required for PMCC');
        return;
      }
    }

    // Stock Only validation
    if (manualTrade.trade_type === 'stock_only') {
      if (!manualTrade.stock_quantity || !manualTrade.stock_price) {
        toast.error('Stock quantity and price are required');
        return;
      }
    }

    // Option Only validation
    if (manualTrade.trade_type === 'option_only') {
      if (!manualTrade.strike_price) {
        toast.error('Strike price is required');
        return;
      }
      if (!manualTrade.option_premium) {
        toast.error('Premium is required');
        return;
      }
      if (!manualTrade.expiry_date) {
        toast.error('Expiry date is required');
        return;
      }
      if (!manualTrade.option_quantity || parseInt(manualTrade.option_quantity) < 1) {
        toast.error('Number of contracts is required');
        return;
      }
    }

    setSavingManualTrade(true);
    try {
      // Prepare data - convert strings to numbers where needed
      const tradeData = {
        symbol: manualTrade.symbol.toUpperCase(),
        trade_type: manualTrade.trade_type,
        stock_quantity: manualTrade.stock_quantity ? parseInt(manualTrade.stock_quantity) : null,
        stock_price: manualTrade.stock_price ? parseFloat(manualTrade.stock_price) : null,
        stock_date: manualTrade.stock_date || null,
        option_type: manualTrade.option_type,
        option_action: manualTrade.option_action,
        strike_price: manualTrade.strike_price ? parseFloat(manualTrade.strike_price) : null,
        expiry_date: manualTrade.expiry_date || null,
        option_premium: manualTrade.option_premium ? parseFloat(manualTrade.option_premium) : null,
        option_quantity: manualTrade.option_quantity ? parseInt(manualTrade.option_quantity) : 1,
        option_date: manualTrade.option_date || null,
        leaps_strike: manualTrade.leaps_strike ? parseFloat(manualTrade.leaps_strike) : null,
        leaps_expiry: manualTrade.leaps_expiry || null,
        leaps_cost: manualTrade.leaps_cost ? parseFloat(manualTrade.leaps_cost) : null,
        leaps_quantity: manualTrade.leaps_quantity ? parseInt(manualTrade.leaps_quantity) : 1,
        leaps_date: manualTrade.leaps_date || null,
        notes: manualTrade.notes || null
      };

      await portfolioApi.addManualTrade(tradeData);
      toast.success('Trade added successfully!');
      setManualTradeOpen(false);
      resetManualTradeForm();
      fetchTrades();
      fetchSummary();
    } catch (error) {
      console.error('Error adding manual trade:', error);
      toast.error(error.response?.data?.detail || 'Failed to add trade');
    } finally {
      setSavingManualTrade(false);
    }
  };

  const handleDeleteTrade = async (tradeId) => {
    if (!window.confirm('Are you sure you want to delete this trade?')) {
      return;
    }
    try {
      await portfolioApi.deleteManualTrade(tradeId);
      toast.success('Trade deleted');
      fetchTrades();
      fetchSummary();
    } catch (error) {
      toast.error('Failed to delete trade');
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
        ai_suggestion: res.data.suggestion,
        ai_action: res.data.action
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
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="flex-shrink-0">
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Wallet className="w-8 h-8 text-violet-500" />
            Portfolio Tracker
          </h1>
          <p className="text-zinc-400 mt-1">Import and track your IBKR transactions</p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept=".csv"
            className="hidden"
          />
          <Button
            onClick={() => fileInputRef.current?.click()}
            className="bg-violet-600 hover:bg-violet-700 h-9 whitespace-nowrap"
            disabled={uploading}
          >
            {uploading ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Upload className="w-4 h-4 mr-2" />
            )}
            Import CSV
          </Button>
          <Button
            onClick={() => setManualTradeOpen(true)}
            className="bg-emerald-600 hover:bg-emerald-700 h-9 whitespace-nowrap"
            data-testid="add-manual-trade-btn"
          >
            <Plus className="w-4 h-4 mr-2" />
            Add Trade
          </Button>
          <Button
            onClick={fetchTrades}
            variant="outline"
            className="border-zinc-700 h-9 w-9 p-0"
          >
            <RefreshCw className="w-4 h-4" />
          </Button>
          {trades.length > 0 && (
            <>
              <Button
                onClick={generateAllSuggestions}
                disabled={generatingSuggestions}
                className="bg-emerald-600 hover:bg-emerald-700 h-9 whitespace-nowrap"
              >
                {generatingSuggestions ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Brain className="w-4 h-4 mr-2" />
                )}
                AI Suggest
              </Button>
              <Button
                onClick={handleClearData}
                variant="outline"
                className="border-red-700 text-red-400 hover:bg-red-500/10 h-9 w-9 p-0"
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </>
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
            // Comprehensive onboarding section
            <div className="py-6">
              {/* Welcome Banner */}
              <div className="text-center mb-8">
                <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-gradient-to-br from-violet-500/30 to-purple-500/30 flex items-center justify-center">
                  <Wallet className="w-10 h-10 text-violet-400" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">Portfolio Tracker</h2>
                <p className="text-zinc-400 max-w-2xl mx-auto">
                  Track your options trading performance with detailed P/L analysis and AI-powered suggestions. 
                  <span className="text-violet-400"> This is a bonus feature</span> to help you manage your covered call strategies.
                </p>
              </div>

              {/* Import Options Grid */}
              <div className="grid md:grid-cols-3 gap-6 mb-8">
                {/* Option 1: IBKR Import */}
                <Card className="glass-card border-emerald-500/30 hover:border-emerald-500/50 transition-colors flex flex-col">
                  <CardHeader className="pb-2">
                    <div className="w-12 h-12 rounded-lg bg-emerald-500/20 flex items-center justify-center mb-2">
                      <FileSpreadsheet className="w-6 h-6 text-emerald-400" />
                    </div>
                    <CardTitle className="text-lg text-emerald-400">Import from IBKR</CardTitle>
                    <CardDescription className="text-zinc-500">Recommended</CardDescription>
                  </CardHeader>
                  <CardContent className="text-sm text-zinc-400 space-y-3 flex-1 flex flex-col">
                    <p>If you have an existing Interactive Brokers account:</p>
                    <ol className="list-decimal list-inside space-y-2 text-zinc-500 flex-1">
                      <li>Log into your <span className="text-white">IBKR Dashboard</span></li>
                      <li>Go to <span className="text-white">Performance & Reports</span> menu</li>
                      <li>Click on <span className="text-white">Transaction History</span></li>
                      <li>Select your desired date range</li>
                      <li>Download as <span className="text-emerald-400">CSV file</span></li>
                      <li>Use the <span className="text-emerald-400">Import button</span> below</li>
                    </ol>
                    <Button
                      onClick={() => fileInputRef.current?.click()}
                      className="w-full bg-emerald-600 hover:bg-emerald-700 mt-auto"
                      disabled={uploading}
                    >
                      <Upload className="w-4 h-4 mr-2" />
                      Import IBKR CSV
                    </Button>
                  </CardContent>
                </Card>

                {/* Option 2: Open IBKR Account */}
                <Card className="glass-card border-blue-500/30 hover:border-blue-500/50 transition-colors flex flex-col">
                  <CardHeader className="pb-2">
                    <div className="w-12 h-12 rounded-lg bg-blue-500/20 flex items-center justify-center mb-2">
                      <ExternalLink className="w-6 h-6 text-blue-400" />
                    </div>
                    <CardTitle className="text-lg text-blue-400">New to IBKR?</CardTitle>
                    <CardDescription className="text-zinc-500">Open an account</CardDescription>
                  </CardHeader>
                  <CardContent className="text-sm text-zinc-400 space-y-3 flex-1 flex flex-col">
                    <p>Don't have an Interactive Brokers account yet? IBKR offers:</p>
                    <ul className="space-y-2 text-zinc-500 flex-1">
                      <li className="flex items-center gap-2">
                        <CheckCircle className="w-4 h-4 text-blue-400" />
                        Low commissions for options trading
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle className="w-4 h-4 text-blue-400" />
                        Access to global markets
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle className="w-4 h-4 text-blue-400" />
                        Professional-grade trading tools
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle className="w-4 h-4 text-blue-400" />
                        Detailed transaction history export
                      </li>
                    </ul>
                    <div className="mt-auto">
                      <Button
                        onClick={() => window.open('https://www.interactivebrokers.com', '_blank')}
                        className="w-full bg-blue-600 hover:bg-blue-700"
                        data-testid="open-ibkr-btn"
                      >
                        <ExternalLink className="w-4 h-4 mr-2" />
                        Open IBKR Account
                      </Button>
                      <p className="text-xs text-zinc-600 text-center mt-1">Opens in new window</p>
                    </div>
                  </CardContent>
                </Card>

                {/* Option 3: Manual Entry */}
                <Card className="glass-card border-emerald-500/30 hover:border-emerald-500/50 transition-colors flex flex-col">
                  <CardHeader className="pb-2">
                    <div className="w-12 h-12 rounded-lg bg-emerald-500/20 flex items-center justify-center mb-2">
                      <Edit className="w-6 h-6 text-emerald-400" />
                    </div>
                    <CardTitle className="text-lg text-emerald-400">Manual Entry</CardTitle>
                    <CardDescription className="text-zinc-500">Add trades manually</CardDescription>
                  </CardHeader>
                  <CardContent className="text-sm text-zinc-400 space-y-3 flex-1 flex flex-col">
                    <p>Track trades from any broker by entering them manually:</p>
                    <div className="p-3 rounded-lg bg-zinc-800/50 border border-zinc-700/50 flex-1">
                      <ul className="space-y-2 text-zinc-500 text-xs">
                        <li className="flex items-center gap-2">
                          <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                          Covered Call positions
                        </li>
                        <li className="flex items-center gap-2">
                          <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                          PMCC (Poor Man's Covered Call)
                        </li>
                        <li className="flex items-center gap-2">
                          <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                          Stock-only positions
                        </li>
                        <li className="flex items-center gap-2">
                          <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                          Individual options
                        </li>
                      </ul>
                    </div>
                    <Button
                      onClick={() => setManualTradeOpen(true)}
                      className="w-full bg-emerald-600 hover:bg-emerald-700 mt-auto"
                      data-testid="manual-entry-btn"
                    >
                      <Plus className="w-4 h-4 mr-2" />
                      Add Manual Trade
                    </Button>
                  </CardContent>
                </Card>
              </div>

              {/* Info Note */}
              <div className="p-4 rounded-lg bg-zinc-800/50 border border-zinc-700/50 max-w-2xl mx-auto">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                  <div className="text-sm">
                    <p className="text-zinc-300 font-medium mb-1">Note about this feature</p>
                    <p className="text-zinc-500">
                      Portfolio tracking is a <span className="text-violet-400">bonus feature</span> designed for users with IBKR accounts. 
                      The main value of this platform is in the <span className="text-emerald-400">Screener</span> and <span className="text-emerald-400">PMCC</span> opportunity scanners. 
                      If you don't use IBKR, you can still fully benefit from all other features!
                    </p>
                  </div>
                </div>
              </div>
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
                      <TableHead className="text-zinc-400">AI Suggestion</TableHead>
                      <TableHead className="text-zinc-400">Opened</TableHead>
                      <TableHead className="text-zinc-400">Closed</TableHead>
                      <TableHead className="text-zinc-400">DTE</TableHead>
                      <TableHead className="text-zinc-400 text-right">Shares</TableHead>
                      <TableHead className="text-zinc-400 text-right">Entry</TableHead>
                      <TableHead className="text-zinc-400 text-right">Premium</TableHead>
                      <TableHead className="text-zinc-400 text-right">B/E</TableHead>
                      <TableHead className="text-zinc-400 text-right">Current</TableHead>
                      <TableHead className="text-zinc-400 text-right">Unrealized</TableHead>
                      <TableHead className="text-zinc-400 text-right">Realized</TableHead>
                      <TableHead className="text-zinc-400 text-right">Net ROI</TableHead>
                      <TableHead className="text-zinc-400 w-12"></TableHead>
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
                        <TableCell>
                          {trade.status === 'Open' ? (
                            trade.ai_action ? (
                              <Badge className={ACTION_COLORS[trade.ai_action] || ACTION_COLORS['N/A']}>
                                {trade.ai_action.replace('_', ' ')}
                              </Badge>
                            ) : (
                              <span className="text-zinc-500 text-xs">-</span>
                            )
                          ) : (
                            <span className="text-zinc-600 text-xs">-</span>
                          )}
                        </TableCell>
                        <TableCell className="text-zinc-300">{formatDate(trade.date_opened)}</TableCell>
                        <TableCell className="text-zinc-300">{formatDate(trade.date_closed) || '-'}</TableCell>
                        <TableCell className="text-zinc-400">{trade.dte ?? '-'}</TableCell>
                        <TableCell className="text-right text-zinc-300">{trade.shares || '-'}</TableCell>
                        <TableCell className="text-right text-zinc-300">{trade.entry_price ? formatCurrency(trade.entry_price) : '-'}</TableCell>
                        <TableCell className="text-right text-emerald-400">{trade.premium_received ? formatCurrency(trade.premium_received) : '-'}</TableCell>
                        <TableCell className="text-right text-zinc-300">{trade.break_even ? formatCurrency(trade.break_even) : '-'}</TableCell>
                        <TableCell className="text-right text-zinc-300">
                          {trade.status === 'Open' && trade.current_price ? formatCurrency(trade.current_price) : '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          {/* Unrealized P/L - only for open trades */}
                          {trade.status === 'Open' && trade.unrealized_pnl !== null && trade.unrealized_pnl !== undefined ? (
                            <span className={trade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                              {formatCurrency(trade.unrealized_pnl)}
                            </span>
                          ) : '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          {/* Realized P/L - only for closed trades */}
                          {trade.status === 'Closed' && trade.realized_pnl !== null && trade.realized_pnl !== undefined ? (
                            <span className={trade.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                              {formatCurrency(trade.realized_pnl)}
                            </span>
                          ) : '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          {trade.roi !== null && trade.roi !== undefined ? (
                            <span className={trade.roi >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                              {formatPercent(trade.roi)}
                            </span>
                          ) : '-'}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteTrade(trade.id);
                            }}
                            className="h-8 w-8 p-0 text-zinc-500 hover:text-red-400 hover:bg-red-500/10"
                            title="Delete trade"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
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
                {selectedTrade.close_reason && (
                  <div>
                    <span className="text-zinc-500">Close Reason:</span>
                    <span className="ml-2 text-amber-400">{selectedTrade.close_reason}</span>
                  </div>
                )}
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

      {/* Manual Trade Entry Dialog */}
      <Dialog open={manualTradeOpen} onOpenChange={setManualTradeOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto bg-zinc-900 border-zinc-800">
          <DialogHeader>
            <DialogTitle className="text-xl flex items-center gap-3">
              <Plus className="w-6 h-6 text-emerald-400" />
              Add Manual Trade
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-6 py-4">
            {/* Trade Type Selection */}
            <div className="space-y-2">
              <Label className="text-zinc-300">Trade Type</Label>
              <Select
                value={manualTrade.trade_type}
                onValueChange={(value) => setManualTrade(prev => ({ ...prev, trade_type: value }))}
              >
                <SelectTrigger className="bg-zinc-800 border-zinc-700">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-zinc-800 border-zinc-700">
                  <SelectItem value="covered_call">Covered Call (Stock + Short Call)</SelectItem>
                  <SelectItem value="pmcc">PMCC (LEAPS + Short Call)</SelectItem>
                  <SelectItem value="stock_only">Stock Only</SelectItem>
                  <SelectItem value="option_only">Option Only</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Symbol */}
            <div className="space-y-2">
              <Label className="text-zinc-300">Symbol *</Label>
              <Input
                value={manualTrade.symbol}
                onChange={(e) => setManualTrade(prev => ({ ...prev, symbol: e.target.value.toUpperCase() }))}
                placeholder="e.g., AAPL"
                className="bg-zinc-800 border-zinc-700 uppercase"
                maxLength={10}
              />
            </div>

            {/* Stock Leg - Show for covered_call and stock_only */}
            {(manualTrade.trade_type === 'covered_call' || manualTrade.trade_type === 'stock_only') && (
              <div className="space-y-4 p-4 rounded-lg bg-blue-500/10 border border-blue-500/30">
                <h4 className="text-sm font-medium text-blue-400 flex items-center gap-2">
                  <TrendingUp className="w-4 h-4" />
                  Stock Position
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Quantity (shares) *</Label>
                    <Input
                      type="number"
                      value={manualTrade.stock_quantity}
                      onChange={(e) => handleStockQuantityChange(e.target.value)}
                      placeholder="100"
                      className="bg-zinc-800 border-zinc-700"
                      min="1"
                    />
                    {manualTrade.trade_type === 'covered_call' && manualTrade.stock_quantity && (
                      <p className="text-xs text-zinc-500">
                        = {Math.floor(parseInt(manualTrade.stock_quantity) / 100)} contracts
                      </p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Purchase Price ($) *</Label>
                    <Input
                      type="number"
                      step="0.01"
                      value={manualTrade.stock_price}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, stock_price: e.target.value }))}
                      placeholder="150.00"
                      className="bg-zinc-800 border-zinc-700"
                      min="0.01"
                    />
                  </div>
                  <div className="space-y-2 col-span-2">
                    <Label className="text-zinc-400 text-xs">Purchase Date</Label>
                    <Input
                      type="date"
                      value={manualTrade.stock_date}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, stock_date: e.target.value }))}
                      className="bg-zinc-800 border-zinc-700"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* LEAPS Leg - Show for PMCC */}
            {manualTrade.trade_type === 'pmcc' && (
              <div className="space-y-4 p-4 rounded-lg bg-violet-500/10 border border-violet-500/30">
                <h4 className="text-sm font-medium text-violet-400 flex items-center gap-2">
                  <TrendingUp className="w-4 h-4" />
                  LEAPS (Long Call)
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Strike Price ($) *</Label>
                    <Input
                      type="number"
                      step="0.5"
                      value={manualTrade.leaps_strike}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, leaps_strike: e.target.value }))}
                      placeholder="120.00"
                      className="bg-zinc-800 border-zinc-700"
                      min="0.01"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Premium Paid ($) *</Label>
                    <Input
                      type="number"
                      step="0.01"
                      value={manualTrade.leaps_cost}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, leaps_cost: e.target.value }))}
                      placeholder="25.00"
                      className="bg-zinc-800 border-zinc-700"
                      min="0.01"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Expiry Date *</Label>
                    <Input
                      type="date"
                      value={manualTrade.leaps_expiry}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, leaps_expiry: e.target.value }))}
                      className="bg-zinc-800 border-zinc-700"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Contracts</Label>
                    <Input
                      type="number"
                      value={manualTrade.leaps_quantity}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, leaps_quantity: e.target.value }))}
                      placeholder="1"
                      className="bg-zinc-800 border-zinc-700"
                      min="1"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Short Call Leg - Show for covered_call, pmcc, option_only */}
            {(manualTrade.trade_type === 'covered_call' || manualTrade.trade_type === 'pmcc' || manualTrade.trade_type === 'option_only') && (
              <div className="space-y-4 p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
                <h4 className="text-sm font-medium text-emerald-400 flex items-center gap-2">
                  <DollarSign className="w-4 h-4" />
                  {manualTrade.trade_type === 'option_only' ? 'Option' : 'Short Call'}
                </h4>
                {manualTrade.trade_type === 'option_only' && (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-zinc-400 text-xs">Option Type</Label>
                      <Select
                        value={manualTrade.option_type}
                        onValueChange={(value) => setManualTrade(prev => ({ ...prev, option_type: value }))}
                      >
                        <SelectTrigger className="bg-zinc-800 border-zinc-700">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-800 border-zinc-700">
                          <SelectItem value="call">Call</SelectItem>
                          <SelectItem value="put">Put</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-zinc-400 text-xs">Action</Label>
                      <Select
                        value={manualTrade.option_action}
                        onValueChange={(value) => setManualTrade(prev => ({ ...prev, option_action: value }))}
                      >
                        <SelectTrigger className="bg-zinc-800 border-zinc-700">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-800 border-zinc-700">
                          <SelectItem value="buy">Buy</SelectItem>
                          <SelectItem value="sell">Sell</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Strike Price ($)</Label>
                    <Input
                      type="number"
                      step="0.5"
                      value={manualTrade.strike_price}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, strike_price: e.target.value }))}
                      placeholder="155.00"
                      className="bg-zinc-800 border-zinc-700"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Premium ($)</Label>
                    <Input
                      type="number"
                      step="0.01"
                      value={manualTrade.option_premium}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, option_premium: e.target.value }))}
                      placeholder="3.50"
                      className="bg-zinc-800 border-zinc-700"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Expiry Date</Label>
                    <Input
                      type="date"
                      value={manualTrade.expiry_date}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, expiry_date: e.target.value }))}
                      className="bg-zinc-800 border-zinc-700"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Contracts</Label>
                    <Input
                      type="number"
                      value={manualTrade.option_quantity}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, option_quantity: e.target.value }))}
                      placeholder="1"
                      className="bg-zinc-800 border-zinc-700"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Notes */}
            <div className="space-y-2">
              <Label className="text-zinc-300">Notes (optional)</Label>
              <Textarea
                value={manualTrade.notes}
                onChange={(e) => setManualTrade(prev => ({ ...prev, notes: e.target.value }))}
                placeholder="Add any notes about this trade..."
                className="bg-zinc-800 border-zinc-700 min-h-[80px]"
              />
            </div>

            {/* Action Buttons */}
            <div className="flex justify-end gap-3 pt-4 border-t border-zinc-800">
              <Button
                variant="outline"
                onClick={() => {
                  setManualTradeOpen(false);
                  resetManualTradeForm();
                }}
                className="border-zinc-700"
              >
                Cancel
              </Button>
              <Button
                onClick={handleManualTradeSubmit}
                disabled={savingManualTrade}
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                {savingManualTrade ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4 mr-2" />
                )}
                Add Trade
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Portfolio;
