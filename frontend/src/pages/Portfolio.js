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
  ChevronDown,
  Search,
  Filter,
  Clock,
  CheckCircle,
  AlertCircle,
  XCircle,
  Loader2,
  Plus,
  Edit,
  X,
  Shield
} from 'lucide-react';
import { toast } from 'sonner';

// Strategy type badges
const STRATEGY_COLORS = {
  'STOCK': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'ETF': 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  'INDEX': 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  'COVERED_CALL': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'WHEEL': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  'CC': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'CSP': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
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
  const [closingTrade, setClosingTrade] = useState(false);
  const [closePrice, setClosePrice] = useState('');
  const fileInputRef = useRef(null);

  // Lifecycle override state
  const [overrideTrade, setOverrideTrade] = useState(null);
  const [overrideAction, setOverrideAction] = useState(null); // 'reclassify' | 'split' | 'merge'
  const [reclassifyStrategy, setReclassifyStrategy] = useState('');
  const [splitDate, setSplitDate] = useState('');
  const [mergeTargetId, setMergeTargetId] = useState('');
  const [overrideSaving, setOverrideSaving] = useState(false);

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
    // Collar - protective put fields
    put_strike: '',
    put_expiry: '',
    put_premium: '',
    put_quantity: '',
    put_date: '',
    notes: ''
  });

  // View mode: 'list' (flat table) or 'lifecycle' (grouped by symbol+cycle)
  const [viewMode, setViewMode] = useState('list');
  const [expandedSymbols, setExpandedSymbols] = useState({});
  const [expandedCycles, setExpandedCycles] = useState({});
  const [lifecycleData, setLifecycleData] = useState(null);
  const [lifecycleLoading, setLifecycleLoading] = useState(false);

  const toggleSymbol = (symbol) =>
    setExpandedSymbols(prev => ({ ...prev, [symbol]: !prev[symbol] }));
  const toggleCycle = (key) =>
    setExpandedCycles(prev => ({ ...prev, [key]: !prev[key] }));

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
    if (viewMode === 'lifecycle') fetchLifecycles();
  }, [filters, pagination.page, viewMode]);

  const fetchLifecycles = async () => {
    setLifecycleLoading(true);
    try {
      const params = {};
      if (filters.account) params.account = filters.account;
      if (filters.symbol) params.symbol = filters.symbol;
      const res = await portfolioApi.getLifecycles(params);
      setLifecycleData(res.data);
    } catch (err) {
      console.error('Lifecycle fetch error:', err);
    } finally {
      setLifecycleLoading(false);
    }
  };

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
      // WHEEL is a frontend pseudo-filter (CC + CSP cycles that are part of a wheel)
      const apiFilters = { ...filters };
      if (apiFilters.strategy === 'WHEEL') {
        delete apiFilters.strategy; // fetch all, filter client-side below
      }
      const res = await portfolioApi.getIBKRTrades({
        ...apiFilters,
        page: viewMode === 'lifecycle' ? 1 : pagination.page,
        limit: viewMode === 'lifecycle' ? 100 : 20
      });
      let allTrades = res.data.trades || [];
      // Client-side WHEEL filter: symbols that have both CC and CSP/NAKED_PUT lifecycles
      if (filters.strategy === 'WHEEL') {
        const wheelSymbols = new Set();
        const bySymbol = {};
        allTrades.forEach(t => {
          if (!bySymbol[t.symbol]) bySymbol[t.symbol] = new Set();
          bySymbol[t.symbol].add(t.strategy_type);
        });
        Object.entries(bySymbol).forEach(([sym, types]) => {
          if ((types.has('COVERED_CALL') || types.has('COLLAR')) && types.has('NAKED_PUT')) {
            wheelSymbols.add(sym);
          }
        });
        allTrades = allTrades.filter(t => wheelSymbols.has(t.symbol));
      }
      setTrades(allTrades);
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
      const { updated, skipped_cached, errors } = res.data;
      if (updated > 0 || skipped_cached > 0) {
        toast.success(res.data.message || `AI suggestions generated for ${updated} trades`);
        fetchTrades();
      } else if (errors && errors.length > 0) {
        // Check if the error is about AI provider not configured
        const firstErr = errors[0] || '';
        if (firstErr.includes('No AI provider') || firstErr.includes('not configured')) {
          toast.error('AI service is not configured on this server. Please contact support.');
        } else if (firstErr.includes('temporarily busy') || firstErr.includes('tokens have not been charged')) {
          toast.error('AI is temporarily busy. Please try again in a few minutes. Your tokens have not been charged.');
        } else {
          toast.error(`AI suggestions failed: ${firstErr}`);
        }
      } else {
        toast.error('No suggestions were generated. Check server logs for details.');
      }
    } catch (error) {
      const detail = error?.response?.data?.detail;
      if (detail?.error_code === 'INSUFFICIENT_TOKENS') {
        toast.error('Insufficient AI tokens. Please top up your AI Wallet.');
      } else {
        toast.error('Failed to generate AI suggestions');
      }
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
      // Collar - protective put fields
      put_strike: '',
      put_expiry: '',
      put_premium: '',
      put_quantity: '',
      put_date: '',
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
      // Auto-populate option_quantity for covered calls and collars (1 contract per 100 shares)
      option_quantity: (prev.trade_type === 'covered_call' || prev.trade_type === 'collar') && contracts > 0 ? contracts.toString() : prev.option_quantity,
      // For collar, also set put_quantity
      put_quantity: prev.trade_type === 'collar' && contracts > 0 ? contracts.toString() : prev.put_quantity
    }));
  };

  // Smart handler for PMCC LEAPS quantity - sync with short call quantity
  const handleLeapsQuantityChange = (value) => {
    setManualTrade(prev => ({
      ...prev,
      leaps_quantity: value,
      // Auto-sync option_quantity with leaps_quantity for PMCC
      option_quantity: prev.trade_type === 'pmcc' ? value : prev.option_quantity
    }));
  };

  // Get today's date in YYYY-MM-DD format for validation
  const getTodayDate = () => {
    return new Date().toISOString().split('T')[0];
  };

  // Validate date is not in the future (for purchase dates)
  const isValidPurchaseDate = (dateStr) => {
    if (!dateStr) return true; // Optional field
    return dateStr <= getTodayDate();
  };

  // Validate date is not in the past (for expiry dates)
  const isValidExpiryDate = (dateStr) => {
    if (!dateStr) return true; // Will be caught by required validation
    return dateStr >= getTodayDate();
  };

  const handleManualTradeSubmit = async () => {
    // Validation - Symbol is always required
    if (!manualTrade.symbol || manualTrade.symbol.trim() === '') {
      toast.error('Symbol is required');
      return;
    }

    // Date validation - Purchase dates cannot be in the future
    if (manualTrade.stock_date && !isValidPurchaseDate(manualTrade.stock_date)) {
      toast.error('Purchase date cannot be in the future');
      return;
    }
    if (manualTrade.option_date && !isValidPurchaseDate(manualTrade.option_date)) {
      toast.error('Option purchase date cannot be in the future');
      return;
    }
    if (manualTrade.leaps_date && !isValidPurchaseDate(manualTrade.leaps_date)) {
      toast.error('LEAPS purchase date cannot be in the future');
      return;
    }
    if (manualTrade.put_date && !isValidPurchaseDate(manualTrade.put_date)) {
      toast.error('Put purchase date cannot be in the future');
      return;
    }

    // Date validation - Expiry dates cannot be in the past
    if (manualTrade.expiry_date && !isValidExpiryDate(manualTrade.expiry_date)) {
      toast.error('Expiry date cannot be in the past');
      return;
    }
    if (manualTrade.leaps_expiry && !isValidExpiryDate(manualTrade.leaps_expiry)) {
      toast.error('LEAPS expiry date cannot be in the past');
      return;
    }
    if (manualTrade.put_expiry && !isValidExpiryDate(manualTrade.put_expiry)) {
      toast.error('Put expiry date cannot be in the past');
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
      // PMCC: Both legs must have same number of contracts
      const leapsQty = parseInt(manualTrade.leaps_quantity) || 1;
      const shortCallQty = parseInt(manualTrade.option_quantity) || 1;
      if (leapsQty !== shortCallQty) {
        toast.error('PMCC requires same number of contracts for both LEAPS and short call');
        return;
      }
    }

    // Collar validation
    if (manualTrade.trade_type === 'collar') {
      if (!manualTrade.stock_quantity || !manualTrade.stock_price) {
        toast.error('Stock quantity and price are required for collar');
        return;
      }
      if (!manualTrade.strike_price || !manualTrade.option_premium) {
        toast.error('Short call strike and premium are required for collar');
        return;
      }
      if (!manualTrade.expiry_date) {
        toast.error('Short call expiry date is required for collar');
        return;
      }
      if (!manualTrade.put_strike || !manualTrade.put_premium) {
        toast.error('Protective put strike and premium are required for collar');
        return;
      }
      if (!manualTrade.put_expiry) {
        toast.error('Protective put expiry date is required for collar');
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
        // Collar - protective put fields
        put_strike: manualTrade.put_strike ? parseFloat(manualTrade.put_strike) : null,
        put_expiry: manualTrade.put_expiry || null,
        put_premium: manualTrade.put_premium ? parseFloat(manualTrade.put_premium) : null,
        put_quantity: manualTrade.put_quantity ? parseInt(manualTrade.put_quantity) : 1,
        put_date: manualTrade.put_date || null,
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
      const detail = error.response?.data?.detail;
      if (error.response?.status === 402) {
        const bal = typeof detail === 'object' ? detail?.remaining_balance : null;
        toast.error(`Insufficient AI credits${bal !== null ? ` (balance: ${bal})` : ''}. Please top up your AI wallet.`);
      } else if (typeof detail === 'object' && detail?.error) {
        toast.error(`AI error: ${detail.error}`);
      } else if (typeof detail === 'string') {
        toast.error(detail);
      } else {
        toast.error('Failed to get AI suggestion — check server logs for details.');
      }
    } finally {
      setLoadingAI(false);
    }
  };

  const handleLifecycleOverride = async () => {
    if (!overrideTrade || !overrideAction) return;
    setOverrideSaving(true);
    try {
      if (overrideAction === 'reclassify') {
        if (!reclassifyStrategy) { toast.error('Select a strategy'); return; }
        await portfolioApi.reclassifyTrade(overrideTrade.id, reclassifyStrategy);
        toast.success('Lifecycle reclassified');
      } else if (overrideAction === 'split') {
        if (!splitDate) { toast.error('Enter split date'); return; }
        await portfolioApi.splitTrade(overrideTrade.id, splitDate);
        toast.success('Lifecycle split into two');
      } else if (overrideAction === 'merge') {
        if (!mergeTargetId) { toast.error('Enter target lifecycle ID'); return; }
        await portfolioApi.mergeTrades(overrideTrade.id, mergeTargetId);
        toast.success('Lifecycles merged');
      }
      setOverrideAction(null);
      setOverrideTrade(null);
      fetchTrades();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Override failed');
    } finally {
      setOverrideSaving(false);
    }
  };

  const handleCloseTrade = async () => {
    if (!selectedTrade || !closePrice) return;
    const price = parseFloat(closePrice);
    if (isNaN(price) || price <= 0) { toast.error('Enter a valid close price'); return; }
    setClosingTrade(true);
    try {
      await portfolioApi.closeTrade(selectedTrade.id, price);
      toast.success('Trade closed successfully');
      setTradeDetailOpen(false);
      setClosePrice('');
      fetchTrades();
      fetchSummary();
    } catch (error) {
      toast.error('Failed to close trade');
    } finally {
      setClosingTrade(false);
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
                <SelectItem value="NAKED_PUT">Cash Secured Put</SelectItem>
                <SelectItem value="COLLAR">Collar</SelectItem>
                <SelectItem value="WHEEL">Wheel (CC+CSP)</SelectItem>
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
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <FileSpreadsheet className="w-5 h-5 text-violet-400" />
              Trades ({pagination.total})
            </CardTitle>
            {trades.length > 0 && (
              <div className="flex items-center gap-1 bg-zinc-800 rounded-lg p-1">
                <button
                  onClick={() => setViewMode('lifecycle')}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                    viewMode === 'lifecycle'
                      ? 'bg-violet-600 text-white'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  Life Cycle
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                    viewMode === 'list'
                      ? 'bg-violet-600 text-white'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  List
                </button>
              </div>
            )}
          </div>
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
          ) : viewMode === 'lifecycle' ? (
            // LIFECYCLE ENGINE VIEW
            (() => {
              try {
              if (lifecycleLoading) return (
                <div className='flex items-center justify-center py-20'>
                  <Loader2 className='w-8 h-8 animate-spin text-violet-400' />
                  <span className='ml-3 text-zinc-400'>Building lifecycles...</span>
                </div>
              );
              if (!lifecycleData || !lifecycleData.lifecycles || Object.keys(lifecycleData.lifecycles).length === 0) return (
                <div className='text-center py-16 text-zinc-500'>No lifecycle data found. Import IBKR transactions first.</div>
              );

              const STATUS_COLOR = {
                'Open - Covered Call Active':  'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
                'Open - Uncovered':            'bg-zinc-700/50 text-zinc-400 border-zinc-600',
                'Open - Partial Coverage':     'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
                'Open - Put Entry Active':     'bg-violet-500/20 text-violet-400 border-violet-500/30',
                'Open - Short Call Active':    'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
                'Open - Waiting to Resell':    'bg-blue-500/20 text-blue-400 border-blue-500/30',
                'Open - LEAPS Only':           'bg-blue-500/20 text-blue-400 border-blue-500/30',
                'Partially Assigned':          'bg-amber-500/20 text-amber-400 border-amber-500/30',
                'Closed by Assignment':        'bg-red-500/20 text-red-400 border-red-500/30',
                'Closed by Share Sale':        'bg-zinc-600/40 text-zinc-400 border-zinc-600',
                'Closed':                      'bg-zinc-600/40 text-zinc-400 border-zinc-600',
                'Roll in Progress':            'bg-amber-500/20 text-amber-400 border-amber-500/30',
                'Assigned / Closing':          'bg-red-500/20 text-red-400 border-red-500/30',
              };

              const fmt = (n) => n == null ? '-' : `$${Number(n).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}`;
              const pnlColor = (n) => n > 0 ? 'text-emerald-400' : n < 0 ? 'text-red-400' : 'text-zinc-400';
              const symbols = Object.keys(lifecycleData.lifecycles).sort();

              return (
                <div className='space-y-6 p-4'>
                  {lifecycleData.summary && (
                    <div className='grid grid-cols-2 md:grid-cols-5 gap-3'>
                      {[
                        { label: 'Open Cycles',    value: lifecycleData.summary.open_cycles },
                        { label: 'Closed Cycles',  value: lifecycleData.summary.closed_cycles },
                        { label: 'Total Premium',  value: fmt(lifecycleData.summary.total_premium_received) },
                        { label: 'Realized P&L',   value: fmt(lifecycleData.summary.realized_pnl), pnl: lifecycleData.summary.realized_pnl },
                        { label: 'Unrealized P&L', value: fmt(lifecycleData.summary.unrealized_pnl), pnl: lifecycleData.summary.unrealized_pnl },
                      ].map(item => (
                        <div key={item.label} className='bg-zinc-800/60 rounded-lg p-3'>
                          <div className='text-xs text-zinc-500'>{item.label}</div>
                          <div className={`text-lg font-bold mt-1 ${item.pnl != null ? pnlColor(item.pnl) : 'text-white'}`}>{item.value}</div>
                        </div>
                      ))}
                    </div>
                  )}

                  {symbols.map(sym => {
                    const symData = lifecycleData.lifecycles[sym];
                    const ccCycles = symData.cc_cycles || [];
                    const pmccCycles = symData.pmcc_cycles || [];
                    if (ccCycles.length === 0 && pmccCycles.length === 0) return null;
                    const isExpanded = expandedSymbols[sym] !== false;

                    // Track which option IDs have already been rendered (for jointly managed dedup)
                    const renderedOptIds = new Set();

                    return (
                      <div key={sym} className='bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden'>
                        <button className='w-full flex items-center justify-between px-4 py-3 bg-zinc-800/60 hover:bg-zinc-800 transition-colors'
                          onClick={() => toggleSymbol(sym)}>
                          <div className='flex items-center gap-3'>
                            <span className='font-bold text-white text-lg'>{sym}</span>
                            <span className='text-xs text-zinc-500'>{ccCycles.length + pmccCycles.length} cycle{ccCycles.length + pmccCycles.length !== 1 ? 's' : ''}</span>
                            {ccCycles.some(c => c.jointly_managed_with && c.jointly_managed_with.length > 0) && (
                              <span className='text-xs bg-violet-500/20 text-violet-400 px-2 py-0.5 rounded'>Jointly Managed</span>
                            )}
                          </div>
                          <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                        </button>

                        {isExpanded && (
                          <div className='divide-y divide-zinc-800'>
                            {ccCycles.map((cycle) => {
                              const cycleKey = sym + '_' + cycle.cycle_id;
                              const isCycleOpen = expandedCycles[cycleKey] !== false;
                              const statusCls = STATUS_COLOR[cycle.status] || 'bg-zinc-700/50 text-zinc-400 border-zinc-600';
                              return (
                                <div key={cycle.cycle_id} className='p-4'>
                                  <div className='flex items-center justify-between mb-3'>
                                    <div className='flex items-center gap-2 flex-wrap'>
                                      <span className='text-sm font-semibold text-zinc-300'>{cycle.cycle_id}</span>
                                      {/* Strategy badge */}
                                      {cycle.strategy === 'WHEEL' && <span className='text-xs bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded border border-amber-500/30'>Wheel</span>}
                                      {cycle.strategy === 'CC' && <span className='text-xs bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded border border-emerald-500/30'>Covered Call</span>}
                                      {cycle.strategy === 'CSP' && <span className='text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded border border-blue-500/30'>Cash Secured Put</span>}
                                      <span className={`text-xs px-2 py-0.5 rounded border ${statusCls}`}>{cycle.status}</span>
                                      <span className='text-xs bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded'>
                                        {cycle.strategy === 'WHEEL' ? 'CSP → Assignment → CC' : cycle.entry_mode === 'PUT_ENTRY' ? 'CSP Entry' : 'Stock Buy'}
                                      </span>
                                      {cycle.jointly_managed_with && cycle.jointly_managed_with.length > 0 && (
                                        <span className='text-xs bg-violet-500/10 text-violet-400 px-2 py-0.5 rounded border border-violet-500/30'>Jointly managed with {cycle.jointly_managed_with.join(', ')}</span>
                                      )}
                                    </div>
                                    <button onClick={() => toggleCycle(cycleKey)} className='text-zinc-500 hover:text-zinc-300'>
                                      <ChevronDown className={`w-4 h-4 transition-transform ${isCycleOpen ? 'rotate-180' : ''}`} />
                                    </button>
                                  </div>
                                  <div className='grid grid-cols-2 md:grid-cols-4 lg:grid-cols-10 gap-2 text-xs mb-3'>
                                    {[
                                      { label: 'Shares', value: cycle.shares_current },
                                      { label: 'Covered', value: cycle.shares_covered_by_calls },
                                      { label: 'Uncovered', value: cycle.uncovered_shares },
                                      { label: 'Avg Cost', value: fmt(cycle.avg_cost) },
                                      { label: 'Eff. Cost', value: fmt(cycle.effective_avg_cost) },
                                      { label: 'Premium', value: fmt(cycle.total_premium_received) },
                                      { label: 'Realized P&L', value: fmt(cycle.realized_pnl), pnl: cycle.realized_pnl },
                                      { label: 'Unrealized P&L', value: cycle.unrealized_pnl != null ? fmt(cycle.unrealized_pnl) : '-', pnl: cycle.unrealized_pnl },
                                      { label: 'Rolls', value: cycle.number_of_rolls },
                                      { label: 'Cycle ROI', value: (cycle.avg_cost > 0 && cycle.total_shares_entered > 0) ? ((cycle.total_premium_received / (cycle.avg_cost * cycle.total_shares_entered)) * 100).toFixed(1) + '%' : '-' },
                                    ].map(m => (
                                      <div key={m.label} className='bg-zinc-800/50 rounded p-2'>
                                        <div className='text-zinc-500 mb-0.5'>{m.label}</div>
                                        <div className={`font-semibold ${m.pnl != null ? pnlColor(m.pnl) : 'text-white'}`}>{m.value != null ? m.value : '-'}</div>
                                      </div>
                                    ))}
                                  </div>
                                  {isCycleOpen && cycle.short_calls && cycle.short_calls.length > 0 && (() => {
                                    // Deduplicate: skip options already shown in a jointly-managed sibling cycle
                                    const uniqueOptIds = cycle.short_calls.filter(id => !renderedOptIds.has(id));
                                    uniqueOptIds.forEach(id => renderedOptIds.add(id));
                                    const isShared = cycle.jointly_managed_with && cycle.jointly_managed_with.length > 0;
                                    if (uniqueOptIds.length === 0) return (
                                      <div className='mt-2 text-xs text-zinc-600 italic'>
                                        Short calls shown in sibling cycle
                                      </div>
                                    );
                                    return (
                                      <div className='mt-2'>
                                        <div className='text-xs text-zinc-500 mb-1'>
                                          Short Call History ({uniqueOptIds.length} legs)
                                          {isShared && <span className='ml-2 text-violet-400'>(shared across jointly managed cycles)</span>}
                                        </div>
                                        <div className='space-y-1'>
                                          {uniqueOptIds.map(optId => {
                                            const opt = symData.options ? symData.options[optId] : null;
                                            if (!opt) return null;
                                            const oc = opt.status === 'EXPIRED' ? 'text-zinc-500' : opt.status === 'ASSIGNED' ? 'text-red-400' : 'text-emerald-400';
                                            return (
                                              <div key={optId} className='flex items-center gap-3 text-xs bg-zinc-800/30 rounded px-3 py-1.5'>
                                                <span className={`w-16 ${oc}`}>{opt.status}</span>
                                                <span className='text-zinc-300'>{opt.expiry} ${opt.strike}C</span>
                                                <span className='text-zinc-400'>{opt.contracts}x</span>
                                                <span className='text-emerald-400'>+{fmt(opt.open_premium * opt.contracts * 100)}</span>
                                                {opt.close_premium != null && <span className='text-red-400'>-{fmt(opt.close_premium * opt.contracts * 100)}</span>}
                                              </div>
                                            );
                                          })}
                                        </div>
                                      </div>
                                    );
                                  })()}

                                  {/* Short Puts (CSP legs of Wheel cycles) */}
                                  {isCycleOpen && cycle.short_puts && cycle.short_puts.length > 0 && (
                                    <div className='mt-2'>
                                      <div className='text-xs text-zinc-500 mb-1'>Put History ({cycle.short_puts.length} legs)</div>
                                      <div className='space-y-1'>
                                        {cycle.short_puts.map(optId => {
                                          const opt = symData.options ? symData.options[optId] : null;
                                          if (!opt) return null;
                                          const oc = opt.status === 'EXPIRED' ? 'text-zinc-500' : opt.status === 'ASSIGNED' ? 'text-amber-400' : 'text-blue-400';
                                          return (
                                            <div key={optId} className='flex items-center gap-3 text-xs bg-blue-500/5 border border-blue-500/20 rounded px-3 py-1.5'>
                                              <span className={`w-16 ${oc}`}>{opt.status}</span>
                                              <span className='text-zinc-300'>{opt.expiry} ${opt.strike}P</span>
                                              <span className='text-zinc-400'>{opt.contracts}x</span>
                                              <span className='text-emerald-400'>+{fmt(opt.open_premium * opt.contracts * 100)}</span>
                                              {opt.close_premium != null && <span className='text-red-400'>-{fmt(opt.close_premium * opt.contracts * 100)}</span>}
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  )}

                                  {/* Per-lot breakdown */}
                                  {isCycleOpen && cycle.lot_details && cycle.lot_details.length > 0 && (
                                    <div className='mt-2'>
                                      <div className='text-xs text-zinc-500 mb-1'>Lots ({cycle.lot_details.length})</div>
                                      <div className='space-y-1'>
                                        {cycle.lot_details.map((lot, i) => (
                                          <div key={lot.lot_id || i} className='flex items-center gap-3 text-xs bg-zinc-800/20 border border-zinc-700/40 rounded px-3 py-1.5'>
                                            <span className='text-zinc-500 w-20'>{lot.open_date}</span>
                                            <span className='text-zinc-400'>{lot.entry_type === 'PUT_ASSIGNMENT' ? 'Put Assigned' : 'Bought'}</span>
                                            <span className='text-zinc-300'>{lot.shares_open} shares</span>
                                            <span className='text-zinc-400'>Entry: {fmt(lot.entry_price)}</span>
                                            <span className='text-blue-300'>Eff: {fmt(lot.effective_entry)}</span>
                                            {lot.realized_pnl !== 0 && (
                                              <span className={lot.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                                                P&L: {fmt(lot.realized_pnl)}
                                              </span>
                                            )}
                                            {lot.shares_remaining > 0 && (
                                              <span className='text-zinc-500 ml-auto'>{lot.shares_remaining} remaining</span>
                                            )}
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              );
                            })}

                            {pmccCycles.map((cycle) => {
                              const cycleKey = sym + '_' + cycle.cycle_id;
                              const isCycleOpen = expandedCycles[cycleKey] !== false;
                              const statusCls = STATUS_COLOR[cycle.status] || 'bg-zinc-700/50 text-zinc-400 border-zinc-600';
                              return (
                                <div key={cycle.cycle_id} className='p-4 bg-blue-950/10'>
                                  <div className='flex items-center justify-between mb-3'>
                                    <div className='flex items-center gap-2'>
                                      <span className='text-sm font-semibold text-zinc-300'>{cycle.cycle_id}</span>
                                      <span className={`text-xs px-2 py-0.5 rounded border ${statusCls}`}>{cycle.status}</span>
                                      <span className='text-xs bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded border border-blue-500/20'>PMCC</span>
                                    </div>
                                    <button onClick={() => toggleCycle(cycleKey)} className='text-zinc-500 hover:text-zinc-300'>
                                      <ChevronDown className={`w-4 h-4 transition-transform ${isCycleOpen ? 'rotate-180' : ''}`} />
                                    </button>
                                  </div>
                                  <div className='grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 text-xs mb-3'>
                                    {[
                                      { label: 'Net Capital', value: fmt(cycle.net_capital_in_use) },
                                      { label: 'Debit Paid', value: fmt(cycle.total_debit_paid) },
                                      { label: 'Short Premium', value: fmt(cycle.total_short_premium_received) },
                                      { label: 'Close Cost', value: fmt(cycle.total_short_close_cost) },
                                      { label: 'Realized P&L', value: fmt(cycle.realized_pnl), pnl: cycle.realized_pnl },
                                      { label: 'Rolls', value: cycle.number_of_rolls },
                                    ].map(m => (
                                      <div key={m.label} className='bg-zinc-800/50 rounded p-2'>
                                        <div className='text-zinc-500 mb-0.5'>{m.label}</div>
                                        <div className={`font-semibold ${m.pnl != null ? pnlColor(m.pnl) : 'text-white'}`}>{m.value != null ? m.value : '-'}</div>
                                      </div>
                                    ))}
                                  </div>
                                  {isCycleOpen && (
                                    <div className='space-y-1 mt-2'>
                                      {(cycle.long_call_lots || []).map(lotId => {
                                        const lot = symData.long_call_lots ? symData.long_call_lots[lotId] : null;
                                        if (!lot) return null;
                                        return (
                                          <div key={lotId} className='flex items-center gap-3 text-xs bg-blue-500/5 border border-blue-500/20 rounded px-3 py-1.5'>
                                            <span className='text-blue-400 w-16'>{lot.status}</span>
                                            <span className='text-zinc-300'>LEAPS {lot.expiry} ${lot.strike}C</span>
                                            <span className='text-zinc-400'>{lot.contracts_open}x</span>
                                            <span className='text-red-400'>-{fmt(lot.total_cost)}</span>
                                            {lot.delta_at_open != null && <span className='text-zinc-500'>delta {lot.delta_at_open.toFixed(2)}</span>}
                                          </div>
                                        );
                                      })}
                                      {(cycle.short_calls || []).map(optId => {
                                        const opt = symData.options ? symData.options[optId] : null;
                                        if (!opt) return null;
                                        const oc = opt.status === 'EXPIRED' ? 'text-zinc-500' : opt.status === 'ASSIGNED' ? 'text-red-400' : 'text-emerald-400';
                                        return (
                                          <div key={optId} className='flex items-center gap-3 text-xs bg-zinc-800/30 rounded px-3 py-1.5'>
                                            <span className={`w-16 ${oc}`}>{opt.status}</span>
                                            <span className='text-zinc-300'>Short {opt.expiry} ${opt.strike}C</span>
                                            <span className='text-zinc-400'>{opt.contracts}x</span>
                                            <span className='text-emerald-400'>+{fmt(opt.open_premium * opt.contracts * 100)}</span>
                                            {opt.close_premium != null && <span className='text-red-400'>-{fmt(opt.close_premium * opt.contracts * 100)}</span>}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
              } catch (err) {
                return (
                  <div className='text-center py-16 text-red-400'>
                    Error rendering lifecycle view. Please re-import your IBKR CSV and try again.<br/>
                    <span className='text-xs text-zinc-500'>{String(err)}</span>
                  </div>
                );
              }
            })()
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
                      <TableHead className="text-zinc-400 text-right">
                        <span title="ROI = (Premium Received + Stock P&L) ÷ Capital Invested × 100. Capital = Entry Price × Shares.">Net ROI ⓘ</span>
                      </TableHead>
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
                              href={`https://www.tradingview.com/symbols/${trade.symbol}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-zinc-500 hover:text-violet-400"
                              title="View on TradingView"
                            >
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge className={STRATEGY_COLORS[trade.strategy_type] || STRATEGY_COLORS.OTHER}>
                            {trade.strategy_label || {
                              COVERED_CALL: 'Covered Call',
                              CC: 'Covered Call',
                              PMCC: 'PMCC',
                              NAKED_PUT: 'Cash Secured Put',
                              CSP: 'Cash Secured Put',
                              WHEEL: 'Wheel',
                              COLLAR: 'Collar',
                              NAKED_CALL: 'Naked Call',
                              LONG_CALL: 'Long Call',
                              LONG_PUT: 'Long Put',
                              PUT_SPREAD: 'Put Spread',
                              CALL_SPREAD: 'Call Spread',
                              ETF: 'ETF',
                              INDEX: 'Index',
                              STOCK: 'Stock',
                              OPTION: 'Option',
                            }[trade.strategy_type] || trade.strategy_type}
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
                        <TableCell className="text-zinc-400">
                          {trade.status === 'Closed' ? '-' : trade.dte > 0 ? `${trade.dte}d` : trade.dte === 0 ? <span className="text-orange-400 text-xs font-bold">0d</span> : '-'}
                        </TableCell>
                        <TableCell className="text-right text-zinc-300">{trade.shares || '-'}</TableCell>
                        <TableCell className="text-right text-zinc-300">{trade.entry_price ? formatCurrency(trade.entry_price) : '-'}</TableCell>
                        <TableCell className="text-right text-emerald-400">{trade.premium_received ? formatCurrency(trade.premium_received) : '-'}</TableCell>
                        <TableCell className="text-right text-zinc-300">
                          {(() => {
                            const be = trade.break_even || (trade.entry_price && trade.premium_received && trade.shares
                              ? trade.entry_price - (trade.premium_received / trade.shares)
                              : null);
                            return trade.status === 'Open' && be ? formatCurrency(be) : '-';
                          })()}
                        </TableCell>
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
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto bg-zinc-900 border-zinc-800">
          <DialogHeader>
            <DialogTitle className="text-lg flex items-center gap-2">
              <span className="text-white">{selectedTrade?.symbol}</span>
              <Badge className={STRATEGY_COLORS[selectedTrade?.strategy_type] || STRATEGY_COLORS.OTHER}>
                {/* If stock trade has put options sold → show Cash Secured Put */}
                {['STOCK', 'ETF', 'INDEX'].includes(selectedTrade?.strategy_type) &&
                  (selectedTrade?.transactions || []).some(tx => tx.is_option && (
                    tx.option_details?.option_type === 'Put' || /\bP$/.test((tx.description || '').trim())
                  ))
                  ? 'Cash Secured Put'
                  : (selectedTrade?.strategy_label || selectedTrade?.strategy_type)}
              </Badge>
              <Badge className={STATUS_COLORS[selectedTrade?.status] || STATUS_COLORS.Open}>
                {selectedTrade?.status}
              </Badge>
            </DialogTitle>
          </DialogHeader>

          {selectedTrade && (
            <div className="space-y-4">
              {/* Trade Summary */}
              <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
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
              <div className="grid grid-cols-2 gap-1.5 text-sm">
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
                  <span className="ml-2 text-white">{selectedTrade.days_in_trade ?? '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">DTE:</span>
                  <span className="ml-2 text-white">{selectedTrade.dte ?? '-'}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Shares:</span>
                  <span className="ml-2 text-white">{selectedTrade.shares || '-'}</span>
                </div>
                {(() => {
                  const _optSells = (selectedTrade.transactions || []).filter(tx => tx.is_option && tx.transaction_type === 'Sell');
                  const _totalWritten = _optSells.reduce((sum, tx) => {
                    const qty = Math.abs(tx.quantity || 0);
                    return sum + (qty >= 100 ? Math.round(qty / 100) : qty);
                  }, 0);
                  const _openContracts = selectedTrade.shares ? Math.round(selectedTrade.shares / 100) : (selectedTrade.contracts || null);
                  const _showSplit = _totalWritten > 0 && _openContracts && _openContracts !== _totalWritten;
                  return _showSplit ? (
                    <>
                      <div>
                        <span className="text-zinc-500">Open Contracts:</span>
                        <span className="ml-2 text-white">{_openContracts}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">Total Written:</span>
                        <span className="ml-2 text-white">{_totalWritten}</span>
                      </div>
                    </>
                  ) : (
                    <div>
                      <span className="text-zinc-500">Contracts:</span>
                      <span className="ml-2 text-white">{selectedTrade.contracts || '-'}</span>
                    </div>
                  );
                })()}
                <div>
                  <span className="text-zinc-500">Current Strike:</span>
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
                {selectedTrade.premium_received > 0 && selectedTrade.entry_price > 0 && selectedTrade.shares > 0 && (
                  <div>
                    <span className="text-zinc-500">Yield on Cost:</span>
                    <span className="ml-2 text-emerald-400">
                      {((selectedTrade.premium_received / (selectedTrade.entry_price * selectedTrade.shares)) * 100).toFixed(1)}%
                    </span>
                  </div>
                )}
              </div>

              {/* Trade Life Cycle */}
              {(() => {
                const isManual = selectedTrade.source === 'manual';
                const hasTxs = selectedTrade.transactions && selectedTrade.transactions.length > 0;
                if (!hasTxs && !isManual) return null;

                // For manual trades, build synthetic steps from trade fields
                if (isManual || !hasTxs) {
                  const steps = [];
                  const tradeType = selectedTrade.strategy_type || '';

                  // Step 1: CSP starts with Put Sold; CC/stock starts with Stock Bought; PMCC starts with LEAPS Bought
                  const isCspTrade = tradeType === 'NAKED_PUT' ||
                    (selectedTrade.strategy_label || '').toLowerCase().includes('cash secured') ||
                    (selectedTrade.strategy_label || '').toLowerCase().includes('csp');

                  if (isCspTrade) {
                    // Cash Secured Put: first step is selling the put
                    steps.push({
                      label: 'Put Sold',
                      date: selectedTrade.date_opened,
                      desc: `Strike $${selectedTrade.option_strike || selectedTrade.entry_price} exp ${formatDate(selectedTrade.option_expiry)}`,
                      amount: selectedTrade.premium_received ? Math.abs(selectedTrade.premium_received) : null,
                      price: selectedTrade.entry_price,
                      color: 'amber',
                      icon: 'sell',
                    });
                  } else if (selectedTrade.stock_price || (!selectedTrade.leaps_cost && selectedTrade.entry_price)) {
                    steps.push({
                      label: 'Stock Bought',
                      date: selectedTrade.stock_date || selectedTrade.date_opened,
                      desc: `${selectedTrade.shares || ''} shares @ ${formatCurrency(selectedTrade.stock_price || selectedTrade.entry_price)}`,
                      amount: null,
                      price: selectedTrade.stock_price || selectedTrade.entry_price,
                      color: 'emerald',
                      icon: 'open',
                    });
                  } else if (selectedTrade.leaps_cost) {
                    steps.push({
                      label: 'LEAPS Bought',
                      date: selectedTrade.leaps_date || selectedTrade.date_opened,
                      desc: `Strike $${selectedTrade.leaps_strike} exp ${formatDate(selectedTrade.leaps_expiry)}`,
                      amount: -Math.abs(selectedTrade.leaps_cost),
                      price: selectedTrade.leaps_cost,
                      color: 'blue',
                      icon: 'open',
                    });
                  }

                  // Step 2: Option sold (skip for CSP — already added as Put Sold in step 1)
                  if (!isCspTrade && (selectedTrade.premium_received || selectedTrade.option_strike)) {
                    const optionDate = selectedTrade.option_date || selectedTrade.date_opened;
                    steps.push({
                      label: tradeType === 'PMCC' ? 'Short Call Sold' : 'Call Sold',
                      date: optionDate,
                      desc: `Strike $${selectedTrade.option_strike} exp ${formatDate(selectedTrade.option_expiry)}`,
                      amount: selectedTrade.premium_received ? Math.abs(selectedTrade.premium_received) : null,
                      price: selectedTrade.premium_received,
                      color: 'violet',
                      icon: 'sell',
                    });
                  }

                  // Step 3: Protective put (collar)
                  if (tradeType === 'COLLAR' && selectedTrade.protective_put_strike) {
                    steps.push({
                      label: 'Put Bought',
                      date: selectedTrade.put_date || selectedTrade.date_opened,
                      desc: `Strike $${selectedTrade.protective_put_strike} exp ${formatDate(selectedTrade.protective_put_expiry)}`,
                      amount: selectedTrade.put_cost ? -Math.abs(selectedTrade.put_cost) : null,
                      color: 'amber',
                      icon: 'protect',
                    });
                  }

                  // Final step: status
                  if (selectedTrade.status === 'Open') {
                    steps.push({
                      label: 'Active',
                      date: null,
                      desc: `DTE: ${selectedTrade.dte ?? '—'} | B/E: ${selectedTrade.break_even ? formatCurrency(selectedTrade.break_even) : '—'}`,
                      amount: selectedTrade.unrealized_pnl,
                      color: 'violet',
                      icon: 'active',
                      current: true,
                    });
                  } else {
                    steps.push({
                      label: selectedTrade.status || 'Closed',
                      date: selectedTrade.date_closed,
                      desc: selectedTrade.close_reason || `Trade ${(selectedTrade.status || 'closed').toLowerCase()}`,
                      amount: selectedTrade.realized_pnl,
                      color: (selectedTrade.status || '').toLowerCase() === 'expired' ? 'zinc' :
                        (selectedTrade.status || '').toLowerCase() === 'assigned' ? 'amber' :
                        (selectedTrade.realized_pnl >= 0 ? 'emerald' : 'red'),
                      icon: 'close',
                    });
                  }

                  const colorMap = {
                    emerald: { dot: 'bg-emerald-500', text: 'text-emerald-400', border: 'border-emerald-500/40', line: 'bg-emerald-500/30' },
                    blue: { dot: 'bg-blue-500', text: 'text-blue-400', border: 'border-blue-500/40', line: 'bg-blue-500/30' },
                    amber: { dot: 'bg-amber-500', text: 'text-amber-400', border: 'border-amber-500/40', line: 'bg-amber-500/30' },
                    red: { dot: 'bg-red-500', text: 'text-red-400', border: 'border-red-500/40', line: 'bg-red-500/30' },
                    zinc: { dot: 'bg-zinc-500', text: 'text-zinc-400', border: 'border-zinc-500/40', line: 'bg-zinc-500/30' },
                    violet: { dot: 'bg-violet-500', text: 'text-violet-400', border: 'border-violet-500/40', line: 'bg-violet-500/30' },
                  };

                  return (
                    <div>
                      <h4 className="text-sm font-medium text-zinc-400 mb-3 flex items-center gap-2">
                        <Shield className="w-4 h-4 text-violet-400" />
                        Trade Life Cycle
                      </h4>
                      <div className="bg-zinc-800/50 rounded-lg p-4">
                        <div className="flex flex-wrap gap-1.5">
                          {steps.map((step, i) => {
                            const c = colorMap[step.color] || colorMap.zinc;
                            return (
                              <div key={i} className={`border rounded-lg p-2 ${c.border} bg-zinc-900/60`} style={{ minWidth: '90px', maxWidth: '130px' }}>
                                <div className={`text-xs font-semibold ${c.text} mb-0.5 flex items-center gap-1`}>
                                  <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${c.dot} ${step.current ? 'animate-pulse' : ''}`} />
                                  {step.label}
                                </div>
                                {step.date && (
                                  <div className="text-[10px] text-zinc-500 mb-0.5">{formatDate(step.date)}</div>
                                )}
                                {step.price != null && (
                                  <div className="text-[10px] text-zinc-400">@ {formatCurrency(step.price)}</div>
                                )}
                                {step.amount != null && (
                                  <div className={`text-[11px] font-medium ${step.amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {step.amount >= 0 ? '+' : ''}{formatCurrency(step.amount)}
                                  </div>
                                )}
                                <div className="text-[10px] text-zinc-500 mt-0.5 truncate" title={step.desc}>
                                  {step.desc?.length > 28 ? step.desc.slice(0, 28) + '…' : step.desc}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  );
                }

                // Build lifecycle steps from transactions — show each option cycle
                const allTxs = [...selectedTrade.transactions].sort((a, b) =>
                  (a.date || a.datetime || '').localeCompare(b.date || b.datetime || '')
                );

                const stockBuyTxns = allTxs.filter(tx => !tx.is_option && tx.transaction_type === 'Buy');
                const optionSellTxns = allTxs.filter(tx => tx.is_option && tx.transaction_type === 'Sell');
                const optionExpiryTxns = allTxs.filter(tx => tx.is_option &&
                  ['Expiry', 'Expire', 'Expiration', 'Expired'].includes(tx.transaction_type));
                const optionBuybackTxns = allTxs.filter(tx => tx.is_option && tx.transaction_type === 'Buy');
                const assignmentTxns = allTxs.filter(tx => tx.transaction_type === 'Assignment');

                const _today = new Date().toISOString().slice(0, 10);
                const steps = [];

                // Step 1: Stock purchase — only if shares were bought BEFORE any put/call was sold
                // (assignment-forced buys come AFTER put sells and should NOT appear as "Stock Bought")
                const firstOptSellDate = optionSellTxns.length > 0
                  ? (optionSellTxns.sort((a, b) => (a.date || '').localeCompare(b.date || ''))[0].date || '')
                  : '';
                const earlyStockBuys = firstOptSellDate
                  ? stockBuyTxns.filter(tx => (tx.date || tx.datetime || '') < firstOptSellDate)
                  : stockBuyTxns;
                if (earlyStockBuys.length > 0) {
                  const totalSh = earlyStockBuys.reduce((s, t) => s + Math.abs(t.quantity || 0), 0);
                  steps.push({
                    label: 'Stock Bought',
                    date: earlyStockBuys[0].date || earlyStockBuys[0].datetime,
                    desc: `${totalSh} shares @ ${formatCurrency(earlyStockBuys[0].price)}`,
                    amount: null,
                    price: earlyStockBuys[0].price,
                    color: 'emerald',
                  });
                } else if (optionSellTxns.length === 0) {
                  // Fallback: no transactions to group
                  steps.push({
                    label: 'Opened',
                    date: selectedTrade.date_opened,
                    desc: `${selectedTrade.strategy_label || selectedTrade.strategy_type || 'Trade'} opened`,
                    amount: null,
                    price: selectedTrade.entry_price,
                    color: 'emerald',
                  });
                }

                // Step 2+: One step per unique option contract (sell → expired/closed)
                const _cycleMap = new Map();
                optionSellTxns.forEach(tx => {
                  const desc = tx.description || '';
                  if (!_cycleMap.has(desc)) {
                    _cycleMap.set(desc, {
                      tx,
                      totalPremium: 0,
                      expiry: (tx.option_details || {}).expiry || '',
                    });
                  }
                  _cycleMap.get(desc).totalPremium += Math.abs(tx.net_amount || 0);
                });

                const _usedIds = new Set();
                [..._cycleMap.values()]
                  .sort((a, b) => (a.tx.date || '').localeCompare(b.tx.date || ''))
                  .forEach((cycle, idx, arr) => {
                    const isLastCycle = idx === arr.length - 1;
                    const contractKey = (cycle.tx.description || '').split(' ').slice(1, 4).join(' ');

                    // Try to find explicit expiry or buyback for this contract
                    const expEvent = optionExpiryTxns.find(
                      e => !_usedIds.has(e.id) && (e.description || '').includes(contractKey)
                    );
                    if (expEvent) _usedIds.add(expEvent.id);

                    const buybackEvent = optionBuybackTxns.find(
                      e => !_usedIds.has(e.id) && (e.description || '').includes(contractKey)
                    );
                    if (buybackEvent) _usedIds.add(buybackEvent.id);

                    // Infer expiry: if option expiry date < today and no explicit event
                    const inferExpired = !expEvent && !buybackEvent && cycle.expiry && cycle.expiry < _today;

                    // Detect if this is a put option via option_details (reliable) or description fallback
                    const _isPut = cycle.tx.option_details?.option_type === 'Put' || /\bP$/.test((cycle.tx.description || '').trim());
                    steps.push({
                      label: _isPut ? 'Sell Put' : 'Sell Call',
                      date: cycle.tx.date || cycle.tx.datetime,
                      desc: cycle.tx.description,
                      amount: cycle.totalPremium,
                      color: _isPut ? 'amber' : 'violet',
                    });

                    if (expEvent || (inferExpired && !isLastCycle)) {
                      steps.push({
                        label: 'Expired',
                        date: expEvent ? (expEvent.date || cycle.expiry) : cycle.expiry,
                        desc: 'Worthless',
                        amount: null,
                        color: 'zinc',
                      });
                    } else if (buybackEvent) {
                      steps.push({
                        label: 'Closed',
                        date: buybackEvent.date || buybackEvent.datetime,
                        desc: `Bought back @ ${formatCurrency(buybackEvent.price)}`,
                        amount: -Math.abs(buybackEvent.net_amount || 0),
                        color: 'amber',
                      });
                    } else if (assignmentTxns.length > 0 && isLastCycle) {
                      steps.push({
                        label: 'Assigned',
                        date: assignmentTxns[0].date,
                        desc: 'Shares called away',
                        amount: null,
                        color: 'amber',
                      });
                    }
                  });

                // Final state
                if (selectedTrade.status === 'Open') {
                  steps.push({
                    label: 'Active',
                    date: null,
                    desc: `DTE: ${selectedTrade.dte ?? '—'} | Unrealized: ${selectedTrade.unrealized_pnl != null ? (selectedTrade.unrealized_pnl >= 0 ? '+' : '') + '$' + Math.abs(selectedTrade.unrealized_pnl).toFixed(2) : '—'}`,
                    amount: selectedTrade.unrealized_pnl,
                    color: 'violet',
                    current: true,
                  });
                } else if (steps.length > 0 && steps[steps.length - 1].label !== 'Assigned') {
                  const statusLower = (selectedTrade.status || '').toLowerCase();
                  steps.push({
                    label: selectedTrade.status || 'Closed',
                    date: selectedTrade.date_closed,
                    desc: selectedTrade.close_reason || `Trade ${statusLower}`,
                    amount: selectedTrade.realized_pnl,
                    color: statusLower === 'expired' ? 'zinc' : statusLower === 'assigned' ? 'amber' :
                      (selectedTrade.realized_pnl >= 0 ? 'emerald' : 'red'),
                  });
                }

                const colorMap = {
                  emerald: { dot: 'bg-emerald-500', text: 'text-emerald-400', border: 'border-emerald-500/40', line: 'bg-emerald-500/30' },
                  blue: { dot: 'bg-blue-500', text: 'text-blue-400', border: 'border-blue-500/40', line: 'bg-blue-500/30' },
                  amber: { dot: 'bg-amber-500', text: 'text-amber-400', border: 'border-amber-500/40', line: 'bg-amber-500/30' },
                  red: { dot: 'bg-red-500', text: 'text-red-400', border: 'border-red-500/40', line: 'bg-red-500/30' },
                  zinc: { dot: 'bg-zinc-500', text: 'text-zinc-400', border: 'border-zinc-500/40', line: 'bg-zinc-500/30' },
                  violet: { dot: 'bg-violet-500', text: 'text-violet-400', border: 'border-violet-500/40', line: 'bg-violet-500/30' },
                };

                return (
                  <div>
                    <h4 className="text-sm font-medium text-zinc-400 mb-3 flex items-center gap-2">
                      <Shield className="w-4 h-4 text-violet-400" />
                      Trade Life Cycle
                    </h4>
                    <div className="bg-zinc-800/50 rounded-lg p-4">
                      <div className="flex flex-wrap gap-1.5">
                        {steps.map((step, i) => {
                          const c = colorMap[step.color] || colorMap.zinc;
                          return (
                            <div key={i} className={`border rounded-lg p-2 ${c.border} bg-zinc-900/60`} style={{ minWidth: '90px', maxWidth: '130px' }}>
                              <div className={`text-xs font-semibold ${c.text} mb-0.5 flex items-center gap-1`}>
                                <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${c.dot} ${step.current ? 'animate-pulse' : ''}`} />
                                {step.label}
                              </div>
                              {step.date && (
                                <div className="text-[10px] text-zinc-500 mb-0.5">{formatDate(step.date)}</div>
                              )}
                              {step.price != null && (
                                <div className="text-[10px] text-zinc-400">@ {formatCurrency(step.price)}</div>
                              )}
                              {step.amount != null && (
                                <div className={`text-[11px] font-medium ${step.amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {step.amount >= 0 ? '+' : ''}{formatCurrency(step.amount)}
                                </div>
                              )}
                              <div className="text-[10px] text-zinc-500 mt-0.5 truncate" title={step.desc}>
                                {step.desc?.length > 28 ? step.desc.slice(0, 28) + '…' : step.desc}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                );
              })()}

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

              {/* Close Trade */}
              {selectedTrade.status === 'Open' && (
                <div className="pt-4 border-t border-zinc-800">
                  <h4 className="text-sm font-medium text-zinc-400 mb-1 flex items-center gap-2">
                    <XCircle className="w-4 h-4 text-red-400" />
                    Close Trade
                  </h4>
                  <p className="text-xs text-zinc-500 mb-3">
                    Manually mark this trade as closed. Enter the price at which you exited (sold stock or bought back the option).
                    Realized P&L will be calculated as: <span className="text-zinc-400">(exit price − entry price) × shares + premium collected − fees</span>.
                  </p>
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <Label className="text-zinc-400 text-xs mb-1 block">Close / Exit Price ($)</Label>
                      <Input
                        type="number"
                        placeholder={selectedTrade.current_price ? String(selectedTrade.current_price) : 'Enter price'}
                        value={closePrice}
                        onChange={e => setClosePrice(e.target.value)}
                        className="bg-zinc-800 border-zinc-700 text-white"
                      />
                    </div>
                    <div className="pt-5">
                      <Button
                        onClick={handleCloseTrade}
                        disabled={closingTrade || !closePrice}
                        className="bg-red-600 hover:bg-red-700 text-white"
                      >
                        {closingTrade ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <XCircle className="w-4 h-4 mr-2" />}
                        Close Trade
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {/* External Links */}
              <div className="flex items-center gap-4 pt-4 border-t border-zinc-800">
                <span className="text-sm text-zinc-500">Quick Links:</span>
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
                  <SelectItem value="collar">Collar (Stock + Short Call + Long Put)</SelectItem>
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

            {/* Stock Leg - Show for covered_call, collar, and stock_only */}
            {(manualTrade.trade_type === 'covered_call' || manualTrade.trade_type === 'collar' || manualTrade.trade_type === 'stock_only') && (
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
                    {(manualTrade.trade_type === 'covered_call' || manualTrade.trade_type === 'collar') && manualTrade.stock_quantity && (
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
                      max={new Date().toISOString().split('T')[0]}
                    />
                    {manualTrade.stock_date && manualTrade.stock_date > new Date().toISOString().split('T')[0] && (
                      <p className="text-xs text-red-400">Purchase date cannot be in the future</p>
                    )}
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
                      min={new Date().toISOString().split('T')[0]}
                    />
                    {manualTrade.leaps_expiry && manualTrade.leaps_expiry < new Date().toISOString().split('T')[0] && (
                      <p className="text-xs text-red-400">Expiry date cannot be in the past</p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Contracts * <span className="text-violet-400">(synced with short call)</span></Label>
                    <Input
                      type="number"
                      value={manualTrade.leaps_quantity}
                      onChange={(e) => handleLeapsQuantityChange(e.target.value)}
                      placeholder="1"
                      className="bg-zinc-800 border-zinc-700"
                      min="1"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Short Call Leg - Show for covered_call, collar, pmcc, option_only */}
            {(manualTrade.trade_type === 'covered_call' || manualTrade.trade_type === 'collar' || manualTrade.trade_type === 'pmcc' || manualTrade.trade_type === 'option_only') && (
              <div className="space-y-4 p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
                <h4 className="text-sm font-medium text-emerald-400 flex items-center gap-2">
                  <DollarSign className="w-4 h-4" />
                  {manualTrade.trade_type === 'option_only' ? 'Option' : 'Short Call'}
                </h4>
                {manualTrade.trade_type === 'option_only' && (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-zinc-400 text-xs">Option Type *</Label>
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
                      <Label className="text-zinc-400 text-xs">Action *</Label>
                      <Select
                        value={manualTrade.option_action}
                        onValueChange={(value) => setManualTrade(prev => ({ ...prev, option_action: value }))}
                      >
                        <SelectTrigger className="bg-zinc-800 border-zinc-700">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-800 border-zinc-700">
                          <SelectItem value="buy">Buy (Long)</SelectItem>
                          <SelectItem value="sell">Sell (Short/Naked)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Strike Price ($) *</Label>
                    <Input
                      type="number"
                      step="0.5"
                      value={manualTrade.strike_price}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, strike_price: e.target.value }))}
                      placeholder="155.00"
                      className="bg-zinc-800 border-zinc-700"
                      min="0.01"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Premium ($) *</Label>
                    <Input
                      type="number"
                      step="0.01"
                      value={manualTrade.option_premium}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, option_premium: e.target.value }))}
                      placeholder="3.50"
                      className="bg-zinc-800 border-zinc-700"
                      min="0.01"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Expiry Date *</Label>
                    <Input
                      type="date"
                      value={manualTrade.expiry_date}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, expiry_date: e.target.value }))}
                      className="bg-zinc-800 border-zinc-700"
                      min={new Date().toISOString().split('T')[0]}
                    />
                    {manualTrade.expiry_date && manualTrade.expiry_date < new Date().toISOString().split('T')[0] && (
                      <p className="text-xs text-red-400">Expiry date cannot be in the past</p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">
                      Contracts {manualTrade.trade_type === 'option_only' ? '*' : ''}
                      {(manualTrade.trade_type === 'covered_call' || manualTrade.trade_type === 'collar') && manualTrade.stock_quantity && (
                        <span className="text-emerald-400 ml-1">(auto-calculated)</span>
                      )}
                      {manualTrade.trade_type === 'pmcc' && (
                        <span className="text-violet-400 ml-1">(synced with LEAPS)</span>
                      )}
                    </Label>
                    <Input
                      type="number"
                      value={manualTrade.option_quantity}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, option_quantity: e.target.value }))}
                      placeholder="1"
                      className="bg-zinc-800 border-zinc-700"
                      min="1"
                      disabled={manualTrade.trade_type === 'pmcc'}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Protective Put Leg - Show for collar only */}
            {manualTrade.trade_type === 'collar' && (
              <div className="space-y-4 p-4 rounded-lg bg-amber-500/10 border border-amber-500/30">
                <h4 className="text-sm font-medium text-amber-400 flex items-center gap-2">
                  <Shield className="w-4 h-4" />
                  Protective Put (Long Put)
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Strike Price ($) *</Label>
                    <Input
                      type="number"
                      step="0.5"
                      value={manualTrade.put_strike}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, put_strike: e.target.value }))}
                      placeholder="145.00"
                      className="bg-zinc-800 border-zinc-700"
                      min="0.01"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Premium Paid ($) *</Label>
                    <Input
                      type="number"
                      step="0.01"
                      value={manualTrade.put_premium}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, put_premium: e.target.value }))}
                      placeholder="2.00"
                      className="bg-zinc-800 border-zinc-700"
                      min="0.01"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">Expiry Date *</Label>
                    <Input
                      type="date"
                      value={manualTrade.put_expiry}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, put_expiry: e.target.value }))}
                      className="bg-zinc-800 border-zinc-700"
                      min={new Date().toISOString().split('T')[0]}
                    />
                    {manualTrade.put_expiry && manualTrade.put_expiry < new Date().toISOString().split('T')[0] && (
                      <p className="text-xs text-red-400">Expiry date cannot be in the past</p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs">
                      Contracts
                      {manualTrade.stock_quantity && (
                        <span className="text-amber-400 ml-1">(auto-calculated)</span>
                      )}
                    </Label>
                    <Input
                      type="number"
                      value={manualTrade.put_quantity}
                      onChange={(e) => setManualTrade(prev => ({ ...prev, put_quantity: e.target.value }))}
                      placeholder="1"
                      className="bg-zinc-800 border-zinc-700"
                      min="1"
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

      {/* ── Lifecycle Override Modal ────────────────────────────────── */}
      <Dialog open={!!overrideAction} onOpenChange={(o) => { if (!o) { setOverrideAction(null); setOverrideTrade(null); } }}>
        <DialogContent className="bg-zinc-900 border-zinc-700 max-w-md">
          <DialogHeader>
            <DialogTitle className="text-white">
              {overrideAction === 'reclassify' && 'Reclassify Lifecycle'}
              {overrideAction === 'split' && 'Split Lifecycle'}
              {overrideAction === 'merge' && 'Merge Lifecycles'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {overrideTrade && (
              <div className="text-xs text-zinc-400 bg-zinc-800 rounded px-3 py-2">
                <span className="font-mono">{overrideTrade.position_instance_id || overrideTrade.id}</span>
                {' — '}{overrideTrade.symbol} · {overrideTrade.strategy_type}
              </div>
            )}

            {overrideAction === 'reclassify' && (
              <div className="space-y-2">
                <label className="text-xs text-zinc-400">New Strategy Type</label>
                <select
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm text-white"
                  value={reclassifyStrategy}
                  onChange={e => setReclassifyStrategy(e.target.value)}
                >
                  <option value="">Select…</option>
                  {['COVERED_CALL','PMCC','NAKED_PUT','COLLAR','STOCK','ETF','INDEX','OPTION'].map(s => (
                    <option key={s} value={s}>{s.replace('_',' ')}</option>
                  ))}
                </select>
              </div>
            )}

            {overrideAction === 'split' && (
              <div className="space-y-2">
                <label className="text-xs text-zinc-400">Split at Date (transactions on or after this date go to new lifecycle)</label>
                <input
                  type="date"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm text-white"
                  value={splitDate}
                  onChange={e => setSplitDate(e.target.value)}
                />
              </div>
            )}

            {overrideAction === 'merge' && (
              <div className="space-y-2">
                <label className="text-xs text-zinc-400">Target Lifecycle ID (the lifecycle to merge into this one)</label>
                <input
                  type="text"
                  placeholder="Paste trade ID from URL or expand the other lifecycle"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm text-white placeholder-zinc-600"
                  value={mergeTargetId}
                  onChange={e => setMergeTargetId(e.target.value)}
                />
                <p className="text-[10px] text-zinc-500">The target lifecycle will be deleted after merging.</p>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" size="sm" className="border-zinc-700 text-zinc-400"
                onClick={() => { setOverrideAction(null); setOverrideTrade(null); }}>
                Cancel
              </Button>
              <Button size="sm" className="bg-blue-600 hover:bg-blue-700"
                onClick={handleLifecycleOverride} disabled={overrideSaving}>
                {overrideSaving ? 'Saving…' : 'Apply'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Portfolio;
