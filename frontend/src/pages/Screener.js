import { useState, useEffect } from 'react';
import { screenerApi } from '../lib/api';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { Checkbox } from '../components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '../components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '../components/ui/accordion';
import {
  Search,
  Filter,
  Save,
  RefreshCw,
  Download,
  ChevronDown,
  ChevronUp,
  X,
  Calendar,
  DollarSign,
  Activity,
  TrendingUp,
  BarChart3,
  Percent,
  Target,
  Gauge,
  Clock,
  Moon
} from 'lucide-react';
import { toast } from 'sonner';
import StockDetailModal from '../components/StockDetailModal';

const Screener = () => {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [sortField, setSortField] = useState('score');
  const [sortDirection, setSortDirection] = useState('desc');
  const [savedFilters, setSavedFilters] = useState([]);
  const [filterName, setFilterName] = useState('');
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [selectedStock, setSelectedStock] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [marketStatus, setMarketStatus] = useState(null);
  const [dataInfo, setDataInfo] = useState(null);

  // Format option contract display like "16JAN26 41.5 C"
  const formatOptionContract = (expiry, strike, optionType = 'call') => {
    if (!expiry && !strike) return '-';
    try {
      const date = new Date(expiry);
      const day = date.getDate().toString().padStart(2, '0');
      const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
      const month = months[date.getMonth()];
      const year = date.getFullYear().toString().slice(-2);
      const type = optionType?.toLowerCase() === 'put' ? 'P' : 'C';
      return `${day}${month}${year} ${strike?.toFixed(1)} ${type}`;
    } catch {
      const type = optionType?.toLowerCase() === 'put' ? 'P' : 'C';
      return `${strike?.toFixed(1)} ${type}`;
    }
  };

  // Expiration Filters - Empty defaults with placeholders
  const [expirationFilters, setExpirationFilters] = useState({
    minDte: '',
    maxDte: '',
    expirationType: 'all', // 'all', 'weekly', 'monthly'
  });

  // Stock Filters - Empty defaults
  const [stockFilters, setStockFilters] = useState({
    minPrice: '',
    maxPrice: '',
    includeStocks: true,
    includeETFs: true,
    includeIndex: false,
  });

  // Options Filters
  const [optionsFilters, setOptionsFilters] = useState({
    minVolume: '',
    minOpenInterest: '',
    moneyness: 'all', // 'all', 'itm', 'atm', 'otm'
  });

  // Greeks Filters - Empty defaults
  const [greeksFilters, setGreeksFilters] = useState({
    minDelta: '',
    maxDelta: '',
    minTheta: '',
    maxTheta: '',
  });

  // Probability Filters
  const [probabilityFilters, setProbabilityFilters] = useState({
    minProbOTM: '',
    maxProbOTM: '',
  });

  // Technical Filters
  const [technicalFilters, setTechnicalFilters] = useState({
    smaFilter: 'none', // 'none', 'above_sma50', 'above_sma200', 'above_both'
    rsiFilter: 'all', // 'all', 'oversold', 'neutral', 'overbought'
    macdSignal: 'all', // 'all', 'bullish', 'bearish'
    trendStrength: 'all', // 'all', 'strong', 'moderate', 'weak'
    overallSignal: 'all', // 'all', 'bullish', 'bearish', 'neutral'
  });

  // Fundamental Filters
  const [fundamentalFilters, setFundamentalFilters] = useState({
    analystRating: 'all', // 'all', 'strong_buy', 'buy', 'hold', 'sell'
    minAnalystCount: '',
    peRatio: 'all', // 'all', 'under_15', '15_to_25', '25_to_40', 'over_40'
    minRoe: '',
  });

  // ROI Filters - Empty defaults
  const [roiFilters, setRoiFilters] = useState({
    minRoi: '',
    minAnnualizedRoi: '',
  });

  useEffect(() => {
    fetchOpportunities();
    fetchSavedFilters();
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

  const fetchOpportunities = async (bypassCache = false) => {
    setLoading(true);
    try {
      // Only pass filter values that are set (not empty strings)
      const params = { bypass_cache: bypassCache };
      
      if (roiFilters.minRoi !== '' && roiFilters.minRoi !== undefined) params.min_roi = roiFilters.minRoi;
      if (expirationFilters.maxDte !== '' && expirationFilters.maxDte !== undefined) params.max_dte = expirationFilters.maxDte;
      if (greeksFilters.minDelta !== '' && greeksFilters.minDelta !== undefined) params.min_delta = greeksFilters.minDelta;
      if (greeksFilters.maxDelta !== '' && greeksFilters.maxDelta !== undefined) params.max_delta = greeksFilters.maxDelta;
      if (stockFilters.minPrice !== '' && stockFilters.minPrice !== undefined) params.min_price = stockFilters.minPrice;
      if (stockFilters.maxPrice !== '' && stockFilters.maxPrice !== undefined) params.max_price = stockFilters.maxPrice;
      if (optionsFilters.minVolume !== '' && optionsFilters.minVolume !== undefined) params.min_volume = optionsFilters.minVolume;
      if (optionsFilters.minOpenInterest !== '' && optionsFilters.minOpenInterest !== undefined) params.min_open_interest = optionsFilters.minOpenInterest;
      if (expirationFilters.expirationType === 'weekly') params.weekly_only = true;
      if (expirationFilters.expirationType === 'monthly') params.monthly_only = true;
      
      const response = await screenerApi.getCoveredCalls(params);
      
      let results = response.data.opportunities || [];
      setDataInfo({
        from_cache: response.data.from_cache,
        market_closed: response.data.market_closed,
        is_last_trading_day: response.data.is_last_trading_day
      });
      
      // Client-side filtering for moneyness
      if (optionsFilters.moneyness !== 'all') {
        results = results.filter(o => {
          const moneyness = (o.strike - o.stock_price) / o.stock_price;
          if (optionsFilters.moneyness === 'itm') return moneyness < -0.02;
          if (optionsFilters.moneyness === 'atm') return Math.abs(moneyness) <= 0.02;
          if (optionsFilters.moneyness === 'otm') return moneyness > 0.02;
          return true;
        });
      }

      // Filter by probability OTM (only if filters are set)
      if (probabilityFilters.minProbOTM !== '' || probabilityFilters.maxProbOTM !== '') {
        results = results.filter(o => {
          const probOTM = Math.round((1 - o.delta) * 100);
          const minProb = probabilityFilters.minProbOTM !== '' ? probabilityFilters.minProbOTM : 0;
          const maxProb = probabilityFilters.maxProbOTM !== '' ? probabilityFilters.maxProbOTM : 100;
          return probOTM >= minProb && probOTM <= maxProb;
        });
      }
      
      setOpportunities(results);
    } catch (error) {
      console.error('Screener fetch error:', error);
      toast.error('Failed to load opportunities');
    } finally {
      setLoading(false);
    }
  };

  const fetchSavedFilters = async () => {
    try {
      const response = await screenerApi.getFilters();
      setSavedFilters(response.data || []);
    } catch (error) {
      console.error('Failed to load saved filters:', error);
    }
  };

  const handleRefreshData = async () => {
    setRefreshing(true);
    toast.info('Fetching fresh market data... This may take a minute.');
    try {
      await fetchOpportunities(true);
      toast.success('Fresh market data loaded successfully!');
    } catch (error) {
      toast.error('Failed to refresh market data');
    } finally {
      setRefreshing(false);
    }
  };

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const sortedOpportunities = [...opportunities].sort((a, b) => {
    const aVal = a[sortField] || 0;
    const bVal = b[sortField] || 0;
    return sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
  });

  const saveFilter = async () => {
    if (!filterName.trim()) {
      toast.error('Please enter a filter name');
      return;
    }

    try {
      await screenerApi.saveFilter({
        name: filterName,
        filters: {
          expiration: expirationFilters,
          stock: stockFilters,
          options: optionsFilters,
          greeks: greeksFilters,
          probability: probabilityFilters,
          technical: technicalFilters,
          fundamental: fundamentalFilters,
          roi: roiFilters,
        }
      });
      toast.success('Filter saved successfully');
      setSaveDialogOpen(false);
      setFilterName('');
      fetchSavedFilters();
    } catch (error) {
      toast.error('Failed to save filter');
    }
  };

  const loadFilter = (savedFilter) => {
    const f = savedFilter.filters;
    if (f.expiration) setExpirationFilters(f.expiration);
    if (f.stock) setStockFilters(f.stock);
    if (f.options) setOptionsFilters(f.options);
    if (f.greeks) setGreeksFilters(f.greeks);
    if (f.probability) setProbabilityFilters(f.probability);
    if (f.technical) setTechnicalFilters(f.technical);
    if (f.fundamental) setFundamentalFilters(f.fundamental);
    if (f.roi) setRoiFilters(f.roi);
    toast.success(`Loaded filter: ${savedFilter.name}`);
  };

  const deleteFilter = async (filterId) => {
    try {
      await screenerApi.deleteFilter(filterId);
      toast.success('Filter deleted');
      fetchSavedFilters();
    } catch (error) {
      toast.error('Failed to delete filter');
    }
  };

  const resetFilters = () => {
    setExpirationFilters({ minDte: 1, maxDte: 45, expirationType: 'all' });
    setStockFilters({ minPrice: 10, maxPrice: 500, includeStocks: true, includeETFs: true, includeIndex: false });
    setOptionsFilters({ minVolume: 0, minOpenInterest: 100, moneyness: 'all' });
    setGreeksFilters({ minDelta: 0.15, maxDelta: 0.45, minTheta: -999, maxTheta: 0 });
    setProbabilityFilters({ minProbOTM: 50, maxProbOTM: 100 });
    setTechnicalFilters({ smaFilter: 'none', rsiFilter: 'all', macdSignal: 'all', trendStrength: 'all', overallSignal: 'all' });
    setFundamentalFilters({ analystRating: 'all', minAnalystCount: 0, peRatio: 'all', minRoe: 0 });
    setRoiFilters({ minRoi: 0.5, minAnnualizedRoi: 10 });
    toast.success('Filters reset to defaults');
  };

  const exportToCSV = () => {
    const headers = ['Symbol', 'Stock Price', 'Strike', 'Expiry', 'DTE', 'Premium', 'ROI %', 'Delta', 'Prob OTM', 'IV', 'IV Rank', 'Volume', 'OI', 'Score'];
    const rows = sortedOpportunities.map(o => [
      o.symbol, o.stock_price, o.strike, o.expiry, o.dte, o.premium, o.roi_pct, o.delta, Math.round((1-o.delta)*100), o.iv, o.iv_rank, o.volume, o.open_interest, o.score
    ]);
    
    const csv = [headers, ...rows].map(row => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'covered_calls_screener.csv';
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Exported to CSV');
  };

  const SortHeader = ({ field, label }) => (
    <th
      className="cursor-pointer hover:text-white transition-colors"
      onClick={() => handleSort(field)}
    >
      <div className="flex items-center gap-1">
        {label}
        {sortField === field && (
          sortDirection === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
        )}
      </div>
    </th>
  );

  return (
    <div className="space-y-6" data-testid="screener-page">
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
            Covered Call Screener
          </h1>
          <p className="text-zinc-400 mt-1">
            {dataInfo?.from_cache && marketStatus && !marketStatus.is_open 
              ? "Showing data from last market session" 
              : "Advanced filtering for optimal premium opportunities"}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="outline"
            onClick={() => setFiltersOpen(!filtersOpen)}
            className="btn-outline"
          >
            <Filter className="w-4 h-4 mr-2" />
            {filtersOpen ? 'Hide' : 'Show'} Filters
          </Button>
          <Button
            variant="outline"
            onClick={resetFilters}
            className="btn-outline"
          >
            <X className="w-4 h-4 mr-2" />
            Reset
          </Button>
          <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="btn-outline">
                <Save className="w-4 h-4 mr-2" />
                Save
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-zinc-900 border-zinc-800">
              <DialogHeader>
                <DialogTitle>Save Filter Preset</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 pt-4">
                <div>
                  <Label>Filter Name</Label>
                  <Input
                    value={filterName}
                    onChange={(e) => setFilterName(e.target.value)}
                    placeholder="My Custom Filter"
                    className="input-dark mt-2"
                    data-testid="filter-name-input"
                  />
                </div>
                <Button onClick={saveFilter} className="w-full bg-emerald-600 hover:bg-emerald-700" data-testid="save-filter-btn">
                  Save Filter
                </Button>
              </div>
            </DialogContent>
          </Dialog>
          <Button
            variant="outline"
            onClick={exportToCSV}
            className="btn-outline"
            data-testid="export-csv-btn"
          >
            <Download className="w-4 h-4 mr-2" />
            Export
          </Button>
          <Button
            onClick={() => fetchOpportunities(false)}
            className="bg-emerald-600 hover:bg-emerald-700 text-white"
            data-testid="apply-filters-btn"
          >
            <Search className="w-4 h-4 mr-2" />
            Scan
          </Button>
          <Button
            variant="outline"
            onClick={handleRefreshData}
            disabled={refreshing || loading}
            className="btn-outline"
            data-testid="refresh-data-btn"
            title="Fetch fresh data from market (bypasses cache)"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing...' : 'Refresh Data'}
          </Button>
        </div>
      </div>

      <div className="grid lg:grid-cols-4 gap-6">
        {/* Filters Panel */}
        {filtersOpen && (
          <Card className="glass-card lg:col-span-1 max-h-[calc(100vh-200px)] overflow-y-auto" data-testid="filters-panel">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg flex items-center gap-2">
                <Filter className="w-5 h-5 text-emerald-400" />
                Filters
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Accordion type="multiple" defaultValue={[]} className="w-full">
                
                {/* Days to Expiration */}
                <AccordionItem value="expiration" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Calendar className="w-4 h-4 text-emerald-400" />
                      Expiration
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    {/* Expiration Type Selection */}
                    <div>
                      <Label className="text-xs text-zinc-400 mb-3 block">Expiration Type</Label>
                      <RadioGroup 
                        value={expirationFilters.expirationType} 
                        onValueChange={(value) => setExpirationFilters(f => ({ ...f, expirationType: value }))}
                        className="space-y-2"
                      >
                        <div className="flex items-center space-x-3 p-2 rounded-lg hover:bg-zinc-800/50">
                          <RadioGroupItem value="all" id="exp-all" className="border-emerald-500 text-emerald-500" />
                          <Label htmlFor="exp-all" className="text-sm cursor-pointer">All Expirations</Label>
                        </div>
                        <div className="flex items-center space-x-3 p-2 rounded-lg hover:bg-zinc-800/50">
                          <RadioGroupItem value="weekly" id="exp-weekly" className="border-emerald-500 text-emerald-500" />
                          <Label htmlFor="exp-weekly" className="text-sm cursor-pointer">Weekly Options Only</Label>
                        </div>
                        <div className="flex items-center space-x-3 p-2 rounded-lg hover:bg-zinc-800/50">
                          <RadioGroupItem value="monthly" id="exp-monthly" className="border-emerald-500 text-emerald-500" />
                          <Label htmlFor="exp-monthly" className="text-sm cursor-pointer">Monthly Options Only</Label>
                        </div>
                      </RadioGroup>
                    </div>

                    {/* DTE Range */}
                    <div className="pt-2 border-t border-zinc-800">
                      <Label className="text-xs text-zinc-400">Days to Expiration Range</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          value={expirationFilters.minDte || ''}
                          onChange={(e) => setExpirationFilters(f => ({ ...f, minDte: parseInt(e.target.value) || 1 }))}
                          className="input-dark w-20 text-center"
                          placeholder="Min"
                          min={1}
                          data-testid="min-dte-input"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          value={expirationFilters.maxDte || ''}
                          onChange={(e) => setExpirationFilters(f => ({ ...f, maxDte: parseInt(e.target.value) || 45 }))}
                          className="input-dark w-20 text-center"
                          placeholder="Max"
                          data-testid="max-dte-input"
                        />
                        <span className="text-zinc-500 text-sm">days</span>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Stock Price & Type */}
                <AccordionItem value="stock" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <DollarSign className="w-4 h-4 text-emerald-400" />
                      Stock Price & Type
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    {/* Price Range */}
                    <div>
                      <Label className="text-xs text-zinc-400">Stock Price Range ($)</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          value={stockFilters.minPrice || ""} placeholder="Min"
                          onChange={(e) => setStockFilters(f => ({ ...f, minPrice: parseFloat(e.target.value) || 0 }))}
                          className="input-dark w-24 text-center"
                          placeholder="Min"
                          data-testid="min-price-input"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          value={stockFilters.maxPrice || ""} placeholder="Max"
                          onChange={(e) => setStockFilters(f => ({ ...f, maxPrice: parseFloat(e.target.value) || 1000 }))}
                          className="input-dark w-24 text-center"
                          placeholder="Max"
                          data-testid="max-price-input"
                        />
                      </div>
                    </div>

                    {/* Security Type Checkboxes */}
                    <div className="pt-2 border-t border-zinc-800">
                      <Label className="text-xs text-zinc-400 mb-3 block">Security Type</Label>
                      <div className="space-y-2">
                        <div className="flex items-center space-x-3 p-2 rounded-lg hover:bg-zinc-800/50">
                          <Checkbox
                            id="type-stock"
                            checked={stockFilters.includeStocks}
                            onCheckedChange={(checked) => setStockFilters(f => ({ ...f, includeStocks: checked }))}
                            className="border-emerald-500 data-[state=checked]:bg-emerald-500"
                          />
                          <Label htmlFor="type-stock" className="text-sm cursor-pointer">Stocks</Label>
                        </div>
                        <div className="flex items-center space-x-3 p-2 rounded-lg hover:bg-zinc-800/50">
                          <Checkbox
                            id="type-etf"
                            checked={stockFilters.includeETFs}
                            onCheckedChange={(checked) => setStockFilters(f => ({ ...f, includeETFs: checked }))}
                            className="border-emerald-500 data-[state=checked]:bg-emerald-500"
                          />
                          <Label htmlFor="type-etf" className="text-sm cursor-pointer">ETFs</Label>
                        </div>
                        <div className="flex items-center space-x-3 p-2 rounded-lg hover:bg-zinc-800/50">
                          <Checkbox
                            id="type-index"
                            checked={stockFilters.includeIndex}
                            onCheckedChange={(checked) => setStockFilters(f => ({ ...f, includeIndex: checked }))}
                            className="border-emerald-500 data-[state=checked]:bg-emerald-500"
                          />
                          <Label htmlFor="type-index" className="text-sm cursor-pointer">Index Options</Label>
                        </div>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Volume & Open Interest */}
                <AccordionItem value="options" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <BarChart3 className="w-4 h-4 text-emerald-400" />
                      Volume & Moneyness
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Minimum Option Volume</Label>
                      <Input
                        type="number"
                        value={optionsFilters.minVolume || ""} placeholder="Min"
                        onChange={(e) => setOptionsFilters(f => ({ ...f, minVolume: parseInt(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="0"
                        data-testid="min-volume-input"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Minimum Open Interest</Label>
                      <Input
                        type="number"
                        value={optionsFilters.minOpenInterest || ""} placeholder="Min"
                        onChange={(e) => setOptionsFilters(f => ({ ...f, minOpenInterest: parseInt(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="100"
                        data-testid="min-oi-input"
                      />
                    </div>
                    
                    {/* Moneyness Dropdown */}
                    <div className="pt-2 border-t border-zinc-800">
                      <Label className="text-xs text-zinc-400">Moneyness</Label>
                      <Select
                        value={optionsFilters.moneyness}
                        onValueChange={(value) => setOptionsFilters(f => ({ ...f, moneyness: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="moneyness-select">
                          <SelectValue placeholder="Select moneyness" />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All Options</SelectItem>
                          <SelectItem value="otm">Out of The Money (OTM)</SelectItem>
                          <SelectItem value="atm">At The Money (ATM)</SelectItem>
                          <SelectItem value="itm">In The Money (ITM)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Greeks */}
                <AccordionItem value="greeks" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Activity className="w-4 h-4 text-emerald-400" />
                      Delta & Theta
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Delta Range</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          step="0.05"
                          value={greeksFilters.minDelta || ""} placeholder="Min"
                          onChange={(e) => setGreeksFilters(f => ({ ...f, minDelta: parseFloat(e.target.value) || 0 }))}
                          className="input-dark w-20 text-center"
                          data-testid="min-delta-input"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          step="0.05"
                          value={greeksFilters.maxDelta || ""} placeholder="Max"
                          onChange={(e) => setGreeksFilters(f => ({ ...f, maxDelta: parseFloat(e.target.value) || 1 }))}
                          className="input-dark w-20 text-center"
                          data-testid="max-delta-input"
                        />
                      </div>
                      <p className="text-xs text-zinc-500 mt-1">Typical range: 0.20 - 0.35 for covered calls</p>
                    </div>
                    <div className="pt-2 border-t border-zinc-800">
                      <Label className="text-xs text-zinc-400">Maximum Theta (daily decay)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        value={greeksFilters.maxTheta || ""} placeholder="Max"
                        onChange={(e) => setGreeksFilters(f => ({ ...f, maxTheta: parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="-0.05"
                        data-testid="max-theta-input"
                      />
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Probability */}
                <AccordionItem value="probability" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Percent className="w-4 h-4 text-emerald-400" />
                      Probability
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Probability of Expiring OTM (Not Assigned)</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          value={probabilityFilters.minProbOTM || ""} placeholder="Min"
                          onChange={(e) => setProbabilityFilters(f => ({ ...f, minProbOTM: parseInt(e.target.value) || 0 }))}
                          className="input-dark w-20 text-center"
                          data-testid="min-prob-otm-input"
                        />
                        <span className="text-zinc-500">% to</span>
                        <Input
                          type="number"
                          value={probabilityFilters.maxProbOTM || ""} placeholder="Max"
                          onChange={(e) => setProbabilityFilters(f => ({ ...f, maxProbOTM: parseInt(e.target.value) || 100 }))}
                          className="input-dark w-20 text-center"
                          data-testid="max-prob-otm-input"
                        />
                        <span className="text-zinc-500">%</span>
                      </div>
                      <p className="text-xs text-zinc-500 mt-1">Higher = less likely to be assigned</p>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Technicals */}
                <AccordionItem value="technicals" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-emerald-400" />
                      Technical Indicators
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    {/* Moving Average Filter */}
                    <div>
                      <Label className="text-xs text-zinc-400">Moving Average Filter</Label>
                      <Select
                        value={technicalFilters.smaFilter}
                        onValueChange={(value) => setTechnicalFilters(f => ({ ...f, smaFilter: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="sma-filter-select">
                          <SelectValue placeholder="Select MA filter" />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="none">No Filter</SelectItem>
                          <SelectItem value="above_sma50">Price Above SMA 50</SelectItem>
                          <SelectItem value="above_sma200">Price Above SMA 200</SelectItem>
                          <SelectItem value="above_both">Price Above Both SMA 50 & 200</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {/* RSI Filter */}
                    <div>
                      <Label className="text-xs text-zinc-400">RSI Condition</Label>
                      <Select
                        value={technicalFilters.rsiFilter}
                        onValueChange={(value) => setTechnicalFilters(f => ({ ...f, rsiFilter: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="rsi-filter-select">
                          <SelectValue placeholder="Select RSI condition" />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All RSI Levels</SelectItem>
                          <SelectItem value="oversold">Oversold (RSI &lt; 30)</SelectItem>
                          <SelectItem value="neutral">Neutral (RSI 30-70)</SelectItem>
                          <SelectItem value="overbought">Overbought (RSI &gt; 70)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {/* MACD Signal */}
                    <div>
                      <Label className="text-xs text-zinc-400">MACD Signal</Label>
                      <Select
                        value={technicalFilters.macdSignal}
                        onValueChange={(value) => setTechnicalFilters(f => ({ ...f, macdSignal: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="macd-signal-select">
                          <SelectValue placeholder="Select MACD signal" />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All Signals</SelectItem>
                          <SelectItem value="bullish">Bullish (MACD Above Signal)</SelectItem>
                          <SelectItem value="bearish">Bearish (MACD Below Signal)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {/* Trend Strength (ADX) */}
                    <div>
                      <Label className="text-xs text-zinc-400">Trend Strength (ADX)</Label>
                      <Select
                        value={technicalFilters.trendStrength}
                        onValueChange={(value) => setTechnicalFilters(f => ({ ...f, trendStrength: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="trend-strength-select">
                          <SelectValue placeholder="Select trend strength" />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All Trend Strengths</SelectItem>
                          <SelectItem value="strong">Strong Trend (ADX &gt; 25)</SelectItem>
                          <SelectItem value="moderate">Moderate Trend (ADX 15-25)</SelectItem>
                          <SelectItem value="weak">Weak/No Trend (ADX &lt; 15)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {/* Overall Signal */}
                    <div>
                      <Label className="text-xs text-zinc-400">Overall Technical Signal</Label>
                      <Select
                        value={technicalFilters.overallSignal}
                        onValueChange={(value) => setTechnicalFilters(f => ({ ...f, overallSignal: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="overall-signal-select">
                          <SelectValue placeholder="Select overall signal" />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All Signals</SelectItem>
                          <SelectItem value="bullish">Bullish</SelectItem>
                          <SelectItem value="neutral">Neutral</SelectItem>
                          <SelectItem value="bearish">Bearish</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Fundamentals */}
                <AccordionItem value="fundamentals" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Gauge className="w-4 h-4 text-emerald-400" />
                      Fundamentals
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    {/* Analyst Rating */}
                    <div>
                      <Label className="text-xs text-zinc-400">Analyst Rating</Label>
                      <Select
                        value={fundamentalFilters.analystRating}
                        onValueChange={(value) => setFundamentalFilters(f => ({ ...f, analystRating: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="analyst-rating-select">
                          <SelectValue placeholder="Select analyst rating" />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All Ratings</SelectItem>
                          <SelectItem value="strong_buy">Strong Buy</SelectItem>
                          <SelectItem value="buy">Buy</SelectItem>
                          <SelectItem value="hold">Hold</SelectItem>
                          <SelectItem value="sell">Sell / Underperform</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div>
                      <Label className="text-xs text-zinc-400">Minimum Analyst Coverage</Label>
                      <Input
                        type="number"
                        value={fundamentalFilters.minAnalystCount || ""} placeholder="Min"
                        onChange={(e) => setFundamentalFilters(f => ({ ...f, minAnalystCount: parseInt(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="5"
                        data-testid="min-analyst-input"
                      />
                    </div>

                    {/* P/E Ratio */}
                    <div>
                      <Label className="text-xs text-zinc-400">P/E Ratio</Label>
                      <Select
                        value={fundamentalFilters.peRatio}
                        onValueChange={(value) => setFundamentalFilters(f => ({ ...f, peRatio: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="pe-ratio-select">
                          <SelectValue placeholder="Select P/E range" />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All P/E Ratios</SelectItem>
                          <SelectItem value="under_15">Value (P/E &lt; 15)</SelectItem>
                          <SelectItem value="15_to_25">Fair Value (P/E 15-25)</SelectItem>
                          <SelectItem value="25_to_40">Growth (P/E 25-40)</SelectItem>
                          <SelectItem value="over_40">High Growth (P/E &gt; 40)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div>
                      <Label className="text-xs text-zinc-400">Minimum ROE (%)</Label>
                      <Input
                        type="number"
                        value={fundamentalFilters.minRoe || ""} placeholder="Min"
                        onChange={(e) => setFundamentalFilters(f => ({ ...f, minRoe: parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="15"
                        data-testid="min-roe-input"
                      />
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* ROI */}
                <AccordionItem value="roi" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Target className="w-4 h-4 text-emerald-400" />
                      Return on Investment
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Minimum ROI per Trade (%)</Label>
                      <Input
                        type="number"
                        step="0.25"
                        value={roiFilters.minRoi || ""} placeholder="Min"
                        onChange={(e) => setRoiFilters(f => ({ ...f, minRoi: parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="0.5"
                        data-testid="min-roi-input"
                      />
                      <p className="text-xs text-zinc-500 mt-1">Premium / Stock Price</p>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Minimum Annualized ROI (%)</Label>
                      <Input
                        type="number"
                        value={roiFilters.minAnnualizedRoi || ""} placeholder="Min"
                        onChange={(e) => setRoiFilters(f => ({ ...f, minAnnualizedRoi: parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="10"
                        data-testid="min-annual-roi-input"
                      />
                    </div>
                  </AccordionContent>
                </AccordionItem>

              </Accordion>

              {/* Saved Filters */}
              {savedFilters.length > 0 && (
                <div className="pt-4 border-t border-zinc-800">
                  <Label className="text-xs text-zinc-400 mb-2 block">Saved Presets</Label>
                  <div className="space-y-2">
                    {savedFilters.map((filter) => (
                      <div
                        key={filter.id}
                        className="flex items-center justify-between p-2 rounded-lg bg-zinc-800/30 hover:bg-zinc-800/50"
                      >
                        <button
                          onClick={() => loadFilter(filter)}
                          className="text-sm text-zinc-300 hover:text-white truncate flex-1 text-left"
                        >
                          {filter.name}
                        </button>
                        <button
                          onClick={() => deleteFilter(filter.id)}
                          className="text-zinc-500 hover:text-red-400 ml-2"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Results Table */}
        <Card className={`glass-card ${filtersOpen ? 'lg:col-span-3' : 'lg:col-span-4'}`} data-testid="results-table">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-lg flex items-center gap-2">
              Results
              <Badge className="ml-2 bg-emerald-500/20 text-emerald-400 border-emerald-500/30">{opportunities.length}</Badge>
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchOpportunities}
              className="text-zinc-400 hover:text-white"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {Array(10).fill(0).map((_, i) => (
                  <Skeleton key={i} className="h-12" />
                ))}
              </div>
            ) : opportunities.length === 0 ? (
              <div className="text-center py-12 text-zinc-500">
                <Search className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>No opportunities match your criteria</p>
                <p className="text-sm mt-2">Try adjusting your filters</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <SortHeader field="symbol" label="Symbol" />
                      <SortHeader field="stock_price" label="Price" />
                      <SortHeader field="strike" label="Strike" />
                      <SortHeader field="dte" label="DTE" />
                      <SortHeader field="premium" label="Premium" />
                      <SortHeader field="roi_pct" label="ROI %" />
                      <SortHeader field="delta" label="Delta" />
                      <th>Prob OTM</th>
                      <SortHeader field="iv" label="IV" />
                      <SortHeader field="iv_rank" label="IV Rank" />
                      <SortHeader field="volume" label="Vol" />
                      <SortHeader field="open_interest" label="OI" />
                      <SortHeader field="score" label="AI Score" />
                    </tr>
                  </thead>
                  <tbody>
                    {sortedOpportunities.map((opp, index) => (
                      <tr 
                        key={index} 
                        data-testid={`screener-row-${opp.symbol}`}
                        className="cursor-pointer hover:bg-zinc-800/50 transition-colors"
                        onClick={() => {
                          setSelectedStock(opp.symbol);
                          setIsModalOpen(true);
                        }}
                        title={`Click to view ${opp.symbol} details`}
                      >
                        <td className="font-semibold text-white">{opp.symbol}</td>
                        <td>${opp.stock_price?.toFixed(2)}</td>
                        <td>
                          <span className="font-mono text-sm">{formatOptionContract(opp.expiry, opp.strike, opp.option_type || 'call')}</span>
                        </td>
                        <td>{opp.dte}d</td>
                        <td className="text-emerald-400">${opp.premium?.toFixed(2)}</td>
                        <td className="text-cyan-400 font-medium">{opp.roi_pct?.toFixed(2)}%</td>
                        <td>{opp.delta?.toFixed(2)}</td>
                        <td className="text-yellow-400">{Math.round((1 - opp.delta) * 100)}%</td>
                        <td>{(opp.iv * 100)?.toFixed(1)}%</td>
                        <td>{opp.iv_rank?.toFixed(0)}%</td>
                        <td>{opp.volume?.toLocaleString()}</td>
                        <td>{opp.open_interest?.toLocaleString()}</td>
                        <td>
                          <Badge className={`${
                            opp.score >= 80 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                            opp.score >= 60 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' : 
                            'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'
                          }`}>
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
      </div>

      {/* Stock Detail Modal */}
      <StockDetailModal 
        symbol={selectedStock}
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setSelectedStock(null);
        }}
      />
    </div>
  );
};

export default Screener;
