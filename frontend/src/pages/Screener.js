import { useState, useEffect } from 'react';
import { screenerApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Slider } from '../components/ui/slider';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { Switch } from '../components/ui/switch';
import { Checkbox } from '../components/ui/checkbox';
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
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '../components/ui/tabs';
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
  Gauge
} from 'lucide-react';
import { toast } from 'sonner';

const Screener = () => {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [sortField, setSortField] = useState('score');
  const [sortDirection, setSortDirection] = useState('desc');
  const [savedFilters, setSavedFilters] = useState([]);
  const [filterName, setFilterName] = useState('');
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  // Expiration Filters
  const [expirationFilters, setExpirationFilters] = useState({
    minDte: 1,
    maxDte: 45,
    weeklyOnly: false,
    monthlyOnly: false,
  });

  // Stock Filters
  const [stockFilters, setStockFilters] = useState({
    minPrice: 10,
    maxPrice: 500,
    securityTypes: ['stock', 'etf'],
  });

  // Options Filters
  const [optionsFilters, setOptionsFilters] = useState({
    minVolume: 0,
    minOpenInterest: 100,
    moneyness: 'all', // 'itm', 'atm', 'otm', 'all'
  });

  // Greeks Filters
  const [greeksFilters, setGreeksFilters] = useState({
    minDelta: 0.15,
    maxDelta: 0.45,
    minTheta: -999,
    maxTheta: 0,
  });

  // Probability Filters
  const [probabilityFilters, setProbabilityFilters] = useState({
    minProbAssignment: 0,
    maxProbAssignment: 100,
    minProbNotAssignment: 0,
    maxProbNotAssignment: 100,
  });

  // Technical Filters
  const [technicalFilters, setTechnicalFilters] = useState({
    aboveSma50: false,
    aboveSma200: false,
    minRsi: 0,
    maxRsi: 100,
    macdSignal: 'all', // 'bullish', 'bearish', 'all'
    minAdx: 0,
    signalStrength: 'all', // 'bullish', 'bearish', 'neutral', 'all'
  });

  // Fundamental Filters
  const [fundamentalFilters, setFundamentalFilters] = useState({
    minAnalystCoverage: 0,
    minBuyRatings: 0,
    minPe: 0,
    maxPe: 100,
    minRoe: 0,
  });

  // ROI Filters
  const [roiFilters, setRoiFilters] = useState({
    minRoi: 0.5,
    minAnnualizedRoi: 10,
  });

  useEffect(() => {
    fetchOpportunities();
    fetchSavedFilters();
  }, []);

  const fetchOpportunities = async () => {
    setLoading(true);
    try {
      const response = await screenerApi.getCoveredCalls({
        min_roi: roiFilters.minRoi,
        max_dte: expirationFilters.maxDte,
        min_delta: greeksFilters.minDelta,
        max_delta: greeksFilters.maxDelta,
        min_iv_rank: 0,
        min_price: stockFilters.minPrice,
        max_price: stockFilters.maxPrice,
        min_volume: optionsFilters.minVolume,
        min_open_interest: optionsFilters.minOpenInterest,
        weekly_only: expirationFilters.weeklyOnly,
        monthly_only: expirationFilters.monthlyOnly,
      });
      
      let results = response.data.opportunities || [];
      
      // Client-side filtering for additional criteria
      if (stockFilters.securityTypes.length < 3) {
        // Filter by security type when implemented
      }
      
      if (optionsFilters.moneyness !== 'all') {
        results = results.filter(o => {
          const moneyness = (o.strike - o.stock_price) / o.stock_price;
          if (optionsFilters.moneyness === 'itm') return moneyness < -0.02;
          if (optionsFilters.moneyness === 'atm') return Math.abs(moneyness) <= 0.02;
          if (optionsFilters.moneyness === 'otm') return moneyness > 0.02;
          return true;
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
    setExpirationFilters({ minDte: 1, maxDte: 45, weeklyOnly: false, monthlyOnly: false });
    setStockFilters({ minPrice: 10, maxPrice: 500, securityTypes: ['stock', 'etf'] });
    setOptionsFilters({ minVolume: 0, minOpenInterest: 100, moneyness: 'all' });
    setGreeksFilters({ minDelta: 0.15, maxDelta: 0.45, minTheta: -999, maxTheta: 0 });
    setProbabilityFilters({ minProbAssignment: 0, maxProbAssignment: 100, minProbNotAssignment: 0, maxProbNotAssignment: 100 });
    setTechnicalFilters({ aboveSma50: false, aboveSma200: false, minRsi: 0, maxRsi: 100, macdSignal: 'all', minAdx: 0, signalStrength: 'all' });
    setFundamentalFilters({ minAnalystCoverage: 0, minBuyRatings: 0, minPe: 0, maxPe: 100, minRoe: 0 });
    setRoiFilters({ minRoi: 0.5, minAnnualizedRoi: 10 });
    toast.success('Filters reset to defaults');
  };

  const exportToCSV = () => {
    const headers = ['Symbol', 'Stock Price', 'Strike', 'Expiry', 'DTE', 'Premium', 'ROI %', 'Delta', 'Theta', 'IV', 'IV Rank', 'Volume', 'OI', 'Score'];
    const rows = sortedOpportunities.map(o => [
      o.symbol, o.stock_price, o.strike, o.expiry, o.dte, o.premium, o.roi_pct, o.delta, o.theta || 0, o.iv, o.iv_rank, o.volume, o.open_interest, o.score
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

  // Calculate probability based on delta
  const getProbAssignment = (delta) => Math.round(delta * 100);
  const getProbNotAssignment = (delta) => Math.round((1 - delta) * 100);

  return (
    <div className="space-y-6" data-testid="screener-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Search className="w-8 h-8 text-emerald-500" />
            Covered Call Screener
          </h1>
          <p className="text-zinc-400 mt-1">Advanced filtering for optimal premium opportunities</p>
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
            onClick={fetchOpportunities}
            className="bg-emerald-600 hover:bg-emerald-700 text-white"
            data-testid="apply-filters-btn"
          >
            <Search className="w-4 h-4 mr-2" />
            Scan
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
              <Accordion type="multiple" defaultValue={["expiration", "greeks", "roi"]} className="w-full">
                
                {/* Days to Expiration */}
                <AccordionItem value="expiration" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Calendar className="w-4 h-4 text-emerald-400" />
                      Days to Expiration
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">DTE Range: {expirationFilters.minDte} - {expirationFilters.maxDte} days</Label>
                      <div className="flex gap-2 mt-2">
                        <Input
                          type="number"
                          value={expirationFilters.minDte}
                          onChange={(e) => setExpirationFilters(f => ({ ...f, minDte: parseInt(e.target.value) || 1 }))}
                          className="input-dark w-20"
                          min={1}
                          data-testid="min-dte-input"
                        />
                        <span className="text-zinc-500 self-center">to</span>
                        <Input
                          type="number"
                          value={expirationFilters.maxDte}
                          onChange={(e) => setExpirationFilters(f => ({ ...f, maxDte: parseInt(e.target.value) || 45 }))}
                          className="input-dark w-20"
                          data-testid="max-dte-input"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <Label className="text-xs">Weekly Expirations Only</Label>
                        <Switch
                          checked={expirationFilters.weeklyOnly}
                          onCheckedChange={(checked) => setExpirationFilters(f => ({ ...f, weeklyOnly: checked, monthlyOnly: false }))}
                          data-testid="weekly-only-switch"
                        />
                      </div>
                      <div className="flex items-center justify-between">
                        <Label className="text-xs">Monthly Expirations Only</Label>
                        <Switch
                          checked={expirationFilters.monthlyOnly}
                          onCheckedChange={(checked) => setExpirationFilters(f => ({ ...f, monthlyOnly: checked, weeklyOnly: false }))}
                          data-testid="monthly-only-switch"
                        />
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Stock Price */}
                <AccordionItem value="stock" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <DollarSign className="w-4 h-4 text-emerald-400" />
                      Stock Price & Type
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Price Range: ${stockFilters.minPrice} - ${stockFilters.maxPrice}</Label>
                      <div className="flex gap-2 mt-2">
                        <Input
                          type="number"
                          value={stockFilters.minPrice}
                          onChange={(e) => setStockFilters(f => ({ ...f, minPrice: parseFloat(e.target.value) || 0 }))}
                          className="input-dark w-24"
                          placeholder="Min"
                          data-testid="min-price-input"
                        />
                        <span className="text-zinc-500 self-center">to</span>
                        <Input
                          type="number"
                          value={stockFilters.maxPrice}
                          onChange={(e) => setStockFilters(f => ({ ...f, maxPrice: parseFloat(e.target.value) || 1000 }))}
                          className="input-dark w-24"
                          placeholder="Max"
                          data-testid="max-price-input"
                        />
                      </div>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400 mb-2 block">Security Type</Label>
                      <div className="space-y-2">
                        {['stock', 'etf', 'index'].map((type) => (
                          <div key={type} className="flex items-center gap-2">
                            <Checkbox
                              id={`type-${type}`}
                              checked={stockFilters.securityTypes.includes(type)}
                              onCheckedChange={(checked) => {
                                if (checked) {
                                  setStockFilters(f => ({ ...f, securityTypes: [...f.securityTypes, type] }));
                                } else {
                                  setStockFilters(f => ({ ...f, securityTypes: f.securityTypes.filter(t => t !== type) }));
                                }
                              }}
                            />
                            <Label htmlFor={`type-${type}`} className="text-xs capitalize">{type}</Label>
                          </div>
                        ))}
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Options Volume & OI */}
                <AccordionItem value="options" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <BarChart3 className="w-4 h-4 text-emerald-400" />
                      Volume & Open Interest
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Min Option Volume</Label>
                      <Input
                        type="number"
                        value={optionsFilters.minVolume}
                        onChange={(e) => setOptionsFilters(f => ({ ...f, minVolume: parseInt(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="0"
                        data-testid="min-volume-input"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Min Open Interest</Label>
                      <Input
                        type="number"
                        value={optionsFilters.minOpenInterest}
                        onChange={(e) => setOptionsFilters(f => ({ ...f, minOpenInterest: parseInt(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="100"
                        data-testid="min-oi-input"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Moneyness</Label>
                      <Select
                        value={optionsFilters.moneyness}
                        onValueChange={(value) => setOptionsFilters(f => ({ ...f, moneyness: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="moneyness-select">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All</SelectItem>
                          <SelectItem value="itm">In The Money (ITM)</SelectItem>
                          <SelectItem value="atm">At The Money (ATM)</SelectItem>
                          <SelectItem value="otm">Out of The Money (OTM)</SelectItem>
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
                      <Label className="text-xs text-zinc-400">Delta Range: {greeksFilters.minDelta.toFixed(2)} - {greeksFilters.maxDelta.toFixed(2)}</Label>
                      <div className="flex gap-2 mt-2">
                        <Input
                          type="number"
                          step="0.05"
                          value={greeksFilters.minDelta}
                          onChange={(e) => setGreeksFilters(f => ({ ...f, minDelta: parseFloat(e.target.value) || 0 }))}
                          className="input-dark w-20"
                          data-testid="min-delta-input"
                        />
                        <span className="text-zinc-500 self-center">to</span>
                        <Input
                          type="number"
                          step="0.05"
                          value={greeksFilters.maxDelta}
                          onChange={(e) => setGreeksFilters(f => ({ ...f, maxDelta: parseFloat(e.target.value) || 1 }))}
                          className="input-dark w-20"
                          data-testid="max-delta-input"
                        />
                      </div>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Max Theta (negative value)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        value={greeksFilters.maxTheta}
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
                      <Label className="text-xs text-zinc-400">Prob. of Assignment: {probabilityFilters.minProbAssignment}% - {probabilityFilters.maxProbAssignment}%</Label>
                      <Slider
                        value={[probabilityFilters.minProbAssignment, probabilityFilters.maxProbAssignment]}
                        onValueChange={([min, max]) => setProbabilityFilters(f => ({ ...f, minProbAssignment: min, maxProbAssignment: max }))}
                        min={0}
                        max={100}
                        step={5}
                        className="mt-2"
                        data-testid="prob-assignment-slider"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Prob. of NOT Assignment: {probabilityFilters.minProbNotAssignment}% - {probabilityFilters.maxProbNotAssignment}%</Label>
                      <Slider
                        value={[probabilityFilters.minProbNotAssignment, probabilityFilters.maxProbNotAssignment]}
                        onValueChange={([min, max]) => setProbabilityFilters(f => ({ ...f, minProbNotAssignment: min, maxProbNotAssignment: max }))}
                        min={0}
                        max={100}
                        step={5}
                        className="mt-2"
                        data-testid="prob-not-assignment-slider"
                      />
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Technicals */}
                <AccordionItem value="technicals" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-emerald-400" />
                      Technicals
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <Label className="text-xs">Price Above SMA 50</Label>
                        <Switch
                          checked={technicalFilters.aboveSma50}
                          onCheckedChange={(checked) => setTechnicalFilters(f => ({ ...f, aboveSma50: checked }))}
                          data-testid="above-sma50-switch"
                        />
                      </div>
                      <div className="flex items-center justify-between">
                        <Label className="text-xs">Price Above SMA 200</Label>
                        <Switch
                          checked={technicalFilters.aboveSma200}
                          onCheckedChange={(checked) => setTechnicalFilters(f => ({ ...f, aboveSma200: checked }))}
                          data-testid="above-sma200-switch"
                        />
                      </div>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">RSI Range: {technicalFilters.minRsi} - {technicalFilters.maxRsi}</Label>
                      <Slider
                        value={[technicalFilters.minRsi, technicalFilters.maxRsi]}
                        onValueChange={([min, max]) => setTechnicalFilters(f => ({ ...f, minRsi: min, maxRsi: max }))}
                        min={0}
                        max={100}
                        step={5}
                        className="mt-2"
                        data-testid="rsi-slider"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">MACD Signal</Label>
                      <Select
                        value={technicalFilters.macdSignal}
                        onValueChange={(value) => setTechnicalFilters(f => ({ ...f, macdSignal: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="macd-select">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All</SelectItem>
                          <SelectItem value="bullish">Bullish</SelectItem>
                          <SelectItem value="bearish">Bearish</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Min ADX (Trend Strength)</Label>
                      <Input
                        type="number"
                        value={technicalFilters.minAdx}
                        onChange={(e) => setTechnicalFilters(f => ({ ...f, minAdx: parseInt(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="25"
                        data-testid="min-adx-input"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Signal Strength</Label>
                      <Select
                        value={technicalFilters.signalStrength}
                        onValueChange={(value) => setTechnicalFilters(f => ({ ...f, signalStrength: value }))}
                      >
                        <SelectTrigger className="input-dark mt-2" data-testid="signal-strength-select">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800">
                          <SelectItem value="all">All</SelectItem>
                          <SelectItem value="bullish">Bullish</SelectItem>
                          <SelectItem value="bearish">Bearish</SelectItem>
                          <SelectItem value="neutral">Neutral</SelectItem>
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
                    <div>
                      <Label className="text-xs text-zinc-400">Min Analyst Coverage</Label>
                      <Input
                        type="number"
                        value={fundamentalFilters.minAnalystCoverage}
                        onChange={(e) => setFundamentalFilters(f => ({ ...f, minAnalystCoverage: parseInt(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="5"
                        data-testid="min-analyst-input"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Min Buy/Strong Buy Ratings</Label>
                      <Input
                        type="number"
                        value={fundamentalFilters.minBuyRatings}
                        onChange={(e) => setFundamentalFilters(f => ({ ...f, minBuyRatings: parseInt(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="10"
                        data-testid="min-buy-ratings-input"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">P/E Ratio Range</Label>
                      <div className="flex gap-2 mt-2">
                        <Input
                          type="number"
                          value={fundamentalFilters.minPe}
                          onChange={(e) => setFundamentalFilters(f => ({ ...f, minPe: parseFloat(e.target.value) || 0 }))}
                          className="input-dark w-20"
                          placeholder="0"
                          data-testid="min-pe-input"
                        />
                        <span className="text-zinc-500 self-center">to</span>
                        <Input
                          type="number"
                          value={fundamentalFilters.maxPe}
                          onChange={(e) => setFundamentalFilters(f => ({ ...f, maxPe: parseFloat(e.target.value) || 100 }))}
                          className="input-dark w-20"
                          placeholder="30"
                          data-testid="max-pe-input"
                        />
                      </div>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Min ROE (%)</Label>
                      <Input
                        type="number"
                        value={fundamentalFilters.minRoe}
                        onChange={(e) => setFundamentalFilters(f => ({ ...f, minRoe: parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="20"
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
                      <Label className="text-xs text-zinc-400">Min ROI (%): {roiFilters.minRoi}%</Label>
                      <Slider
                        value={[roiFilters.minRoi]}
                        onValueChange={([val]) => setRoiFilters(f => ({ ...f, minRoi: val }))}
                        min={0}
                        max={10}
                        step={0.25}
                        className="mt-2"
                        data-testid="min-roi-slider"
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Min Annualized ROI (%)</Label>
                      <Input
                        type="number"
                        value={roiFilters.minAnnualizedRoi}
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
                      <th>Expiry</th>
                      <SortHeader field="dte" label="DTE" />
                      <SortHeader field="premium" label="Premium" />
                      <SortHeader field="roi_pct" label="ROI %" />
                      <SortHeader field="delta" label="Delta" />
                      <th>Prob OTM</th>
                      <SortHeader field="iv" label="IV" />
                      <SortHeader field="iv_rank" label="IV Rank" />
                      <SortHeader field="volume" label="Vol" />
                      <SortHeader field="open_interest" label="OI" />
                      <SortHeader field="score" label="Score" />
                    </tr>
                  </thead>
                  <tbody>
                    {sortedOpportunities.map((opp, index) => (
                      <tr key={index} data-testid={`screener-row-${opp.symbol}`}>
                        <td className="font-semibold text-white">{opp.symbol}</td>
                        <td>${opp.stock_price?.toFixed(2)}</td>
                        <td>${opp.strike?.toFixed(2)}</td>
                        <td className="text-xs">{opp.expiry}</td>
                        <td>{opp.dte}d</td>
                        <td className="text-emerald-400">${opp.premium?.toFixed(2)}</td>
                        <td className="text-cyan-400 font-medium">{opp.roi_pct?.toFixed(2)}%</td>
                        <td>{opp.delta?.toFixed(2)}</td>
                        <td className="text-yellow-400">{getProbNotAssignment(opp.delta)}%</td>
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
    </div>
  );
};

export default Screener;
