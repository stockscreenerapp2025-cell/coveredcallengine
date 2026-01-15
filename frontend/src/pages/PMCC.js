import { useState, useEffect } from 'react';
import { screenerApi, simulatorApi, scansApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
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
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '../components/ui/accordion';
import {
  LineChart,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Info,
  CheckCircle,
  Filter,
  Search,
  DollarSign,
  Calendar,
  Activity,
  Target,
  ChevronDown,
  ChevronUp,
  Play,
  Zap,
  Shield,
  BarChart3,
  Flame,
  X
} from 'lucide-react';
import { toast } from 'sonner';
import StockDetailModal from '../components/StockDetailModal';

// Sort Header component - moved outside to avoid recreation on each render
const SortHeader = ({ field, label, sortField, sortDirection, onSort }) => (
  <th
    className="cursor-pointer hover:text-white transition-colors"
    onClick={() => onSort(field)}
  >
    <div className="flex items-center gap-1">
      {label}
      {sortField === field && (
        sortDirection === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
      )}
    </div>
  </th>
);

const PMCC = () => {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [apiInfo, setApiInfo] = useState(null);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [selectedStock, setSelectedStock] = useState(null);
  const [selectedScanData, setSelectedScanData] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [sortField, setSortField] = useState('score');
  const [sortDirection, setSortDirection] = useState('desc');
  
  // Pre-computed scans state
  const [availableScans, setAvailableScans] = useState(null);
  const [activeScan, setActiveScan] = useState(null);
  const [scanLoading, setScanLoading] = useState(false);
  
  // Simulator state
  const [simulateModalOpen, setSimulateModalOpen] = useState(false);
  const [simulateOpp, setSimulateOpp] = useState(null);
  const [simulateContracts, setSimulateContracts] = useState(1);
  const [simulateLoading, setSimulateLoading] = useState(false);

  // Helper to normalize PMCC data from both custom API (leaps_*) and pre-computed API (long_*)
  const normalizeOpp = (opp) => {
    if (!opp) return null;
    const leapsDte = opp.leaps_dte || opp.long_dte;
    const leapsStrike = opp.leaps_strike || opp.long_strike;
    const leapsPremium = opp.leaps_premium || opp.long_premium;
    const leapsCost = opp.leaps_cost || (leapsPremium ? leapsPremium * 100 : 0);
    const leapsDelta = opp.leaps_delta || opp.long_delta;
    const leapsExpiry = opp.leaps_expiry || opp.long_expiry;
    const shortPremium = opp.short_premium || 0;
    const shortPremiumTotal = shortPremium < 10 ? shortPremium * 100 : shortPremium; // Normalize to total
    const netDebit = opp.net_debit || (leapsCost - shortPremiumTotal);
    const strikeWidth = opp.strike_width || (opp.short_strike && leapsStrike ? opp.short_strike - leapsStrike : 0);
    const roiPerCycle = opp.roi_per_cycle || opp.roi_pct || (netDebit > 0 ? (shortPremiumTotal / netDebit) * 100 : 0);
    const annualizedRoi = opp.annualized_roi || (opp.short_dte > 0 ? roiPerCycle * (365 / opp.short_dte) : 0);
    
    return {
      ...opp,
      leaps_dte: leapsDte,
      leaps_strike: leapsStrike,
      leaps_premium: leapsPremium,
      leaps_cost: leapsCost,
      leaps_delta: leapsDelta,
      leaps_expiry: leapsExpiry,
      short_premium_total: shortPremiumTotal,
      net_debit: netDebit,
      strike_width: strikeWidth,
      roi_per_cycle: roiPerCycle,
      annualized_roi: annualizedRoi,
    };
  };

  // Handle adding to simulator
  const handleSimulate = async () => {
    if (!simulateOpp) return;
    
    setSimulateLoading(true);
    try {
      // Normalize the data first
      const norm = normalizeOpp(simulateOpp);
      
      // PMCC data uses leaps_cost (total cost) - convert to per-share premium for backend
      const leapsPremiumPerShare = norm.leaps_cost ? norm.leaps_cost / 100 : norm.leaps_premium;
      
      const tradeData = {
        symbol: norm.symbol,
        strategy_type: 'pmcc',
        underlying_price: norm.stock_price,
        short_call_strike: norm.short_strike,
        short_call_expiry: norm.short_expiry || norm.leaps_expiry, // Fallback
        short_call_premium: norm.short_premium,
        short_call_delta: norm.short_delta,
        short_call_iv: norm.short_iv,
        leaps_strike: norm.leaps_strike,
        leaps_expiry: norm.leaps_expiry,
        leaps_premium: leapsPremiumPerShare,
        leaps_delta: norm.leaps_delta,
        contracts: simulateContracts,
        scan_parameters: {
          score: norm.score,
          net_debit: norm.net_debit,
          max_profit: norm.max_profit,
          leaps_dte: norm.leaps_dte,
          short_dte: norm.short_dte,
          leaps_cost: norm.leaps_cost
        }
      };
      
      await simulatorApi.addTrade(tradeData);
      toast.success(`Added ${norm.symbol} PMCC to Simulator!`);
      setSimulateModalOpen(false);
      setSimulateOpp(null);
      setSimulateContracts(1);
    } catch (error) {
      const msg = error.response?.data?.detail || 'Failed to add to simulator';
      toast.error(msg);
    } finally {
      setSimulateLoading(false);
    }
  };

  // PMCC Filters - blank by default for best opportunities
  const [filters, setFilters] = useState({
    // Stock filters
    minPrice: '',
    maxPrice: '',
    // LEAPS filters
    minLeapsDelta: '',
    maxLeapsDelta: '',
    minLeapsDte: '',
    maxLeapsDte: '',
    // Short leg filters
    minShortDelta: '',
    maxShortDelta: '',
    minShortDte: '',
    maxShortDte: '',
    // ROI filters
    minRoiPerCycle: '',
    minAnnualizedRoi: '',
  });

  useEffect(() => {
    // On initial load, fetch available scans and auto-load the balanced pre-computed scan
    // This ensures users always see data (from previous market close)
    const initializeData = async () => {
      try {
        const res = await scansApi.getAvailable();
        setAvailableScans(res.data.scans);
        
        // Auto-load balanced pre-computed scan for best initial UX
        // If balanced has data, use it; otherwise try others
        const pmccScans = res.data.scans?.pmcc || [];
        const balancedScan = pmccScans.find(s => s.risk_profile === 'balanced');
        const conservativeScan = pmccScans.find(s => s.risk_profile === 'conservative');
        const aggressiveScan = pmccScans.find(s => s.risk_profile === 'aggressive');
        
        if (balancedScan?.available && balancedScan?.count > 0) {
          loadPrecomputedScan('balanced');
        } else if (conservativeScan?.available && conservativeScan?.count > 0) {
          loadPrecomputedScan('conservative');
        } else if (aggressiveScan?.available && aggressiveScan?.count > 0) {
          loadPrecomputedScan('aggressive');
        } else {
          // Fallback to custom scan only if no pre-computed data exists
          fetchOpportunities();
        }
      } catch (error) {
        console.log('Could not fetch available scans, falling back to custom:', error);
        fetchOpportunities();
      }
    };
    
    initializeData();
  }, []);

  const fetchAvailableScans = async () => {
    try {
      const res = await scansApi.getAvailable();
      setAvailableScans(res.data.scans);
    } catch (error) {
      console.log('Could not fetch available scans:', error);
    }
  };

  const loadPrecomputedScan = async (riskProfile) => {
    setScanLoading(true);
    setActiveScan(riskProfile);
    try {
      const res = await scansApi.getPMCCScan(riskProfile);
      setOpportunities(res.data.opportunities || []);
      setApiInfo({
        from_cache: false,
        is_precomputed: true,
        computed_at: res.data.computed_at,
        risk_profile: riskProfile,
        label: res.data.label
      });
      toast.success(`Loaded ${res.data.label} PMCC scan: ${res.data.total} opportunities`);
    } catch (error) {
      const msg = error.response?.data?.detail || 'Failed to load PMCC scan';
      toast.error(msg);
      setActiveScan(null);
    } finally {
      setScanLoading(false);
      setLoading(false);
    }
  };

  const clearActiveScan = () => {
    setActiveScan(null);
    fetchOpportunities();
  };

  const fetchOpportunities = async (bypassCache = false) => {
    setLoading(true);
    try {
      // Only pass non-empty filter values
      const params = {};
      if (filters.minPrice) params.min_price = filters.minPrice;
      if (filters.maxPrice) params.max_price = filters.maxPrice;
      if (filters.minLeapsDelta) params.min_leaps_delta = filters.minLeapsDelta;
      if (filters.maxLeapsDelta) params.max_leaps_delta = filters.maxLeapsDelta;
      if (filters.minLeapsDte) params.min_leaps_dte = filters.minLeapsDte;
      if (filters.maxLeapsDte) params.max_leaps_dte = filters.maxLeapsDte;
      if (filters.minShortDelta) params.min_short_delta = filters.minShortDelta;
      if (filters.maxShortDelta) params.max_short_delta = filters.maxShortDelta;
      if (filters.minShortDte) params.min_short_dte = filters.minShortDte;
      if (filters.maxShortDte) params.max_short_dte = filters.maxShortDte;
      if (filters.minRoiPerCycle) params.min_roi = filters.minRoiPerCycle;
      if (filters.minAnnualizedRoi) params.min_annualized_roi = filters.minAnnualizedRoi;
      if (bypassCache) params.bypass_cache = true;
      
      const response = await screenerApi.getPMCC(params);
      let opportunities = response.data.opportunities || [];
      
      // Deduplicate by symbol - keep only the entry with highest score
      const symbolMap = {};
      for (const opp of opportunities) {
        const symbol = opp.symbol;
        if (!symbolMap[symbol] || (opp.score || 0) > (symbolMap[symbol].score || 0)) {
          symbolMap[symbol] = opp;
        }
      }
      opportunities = Object.values(symbolMap);
      
      setOpportunities(opportunities);
      setApiInfo(response.data);
    } catch (error) {
      console.error('PMCC fetch error:', error);
      toast.error('Failed to load PMCC opportunities');
    } finally {
      setLoading(false);
    }
  };

  const resetFilters = () => {
    setFilters({
      minPrice: '',
      maxPrice: '',
      minLeapsDelta: '',
      maxLeapsDelta: '',
      minLeapsDte: '',
      maxLeapsDte: '',
      minShortDelta: '',
      maxShortDelta: '',
      minShortDte: '',
      maxShortDte: '',
      minRoiPerCycle: '',
      minAnnualizedRoi: '',
    });
  };

  const handleRefreshData = async () => {
    setRefreshing(true);
    toast.info('Fetching fresh market data... This may take a few minutes.');
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

  // Format option contract display like "26SEP25 49.5 C"
  const formatOptionContract = (expiry, strike, optionType = 'call') => {
    if (!expiry && !strike) return '-';
    try {
      // Handle DTE (days) input - convert to date
      let dateStr = '';
      if (typeof expiry === 'number') {
        const date = new Date();
        date.setDate(date.getDate() + expiry);
        const day = date.getDate().toString().padStart(2, '0');
        const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
        const month = months[date.getMonth()];
        const year = date.getFullYear().toString().slice(-2);
        dateStr = `${day}${month}${year}`;
      } else if (expiry) {
        const date = new Date(expiry);
        const day = date.getDate().toString().padStart(2, '0');
        const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
        const month = months[date.getMonth()];
        const year = date.getFullYear().toString().slice(-2);
        dateStr = `${day}${month}${year}`;
      }
      // C for Call, P for Put
      const type = optionType?.toLowerCase() === 'put' ? 'P' : 'C';
      return `${dateStr} ${strike?.toFixed(0) || ''} ${type}`;
    } catch {
      const type = optionType?.toLowerCase() === 'put' ? 'P' : 'C';
      return `${strike?.toFixed(0) || ''} ${type}`;
    }
  };

  const sortedOpportunities = [...opportunities].sort((a, b) => {
    const aVal = a[sortField] || 0;
    const bVal = b[sortField] || 0;
    return sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
  });

  return (
    <div className="space-y-6" data-testid="pmcc-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <LineChart className="w-8 h-8 text-violet-500" />
            Poor Man&apos;s Covered Call (PMCC)
          </h1>
          <p className="text-zinc-400 mt-1">
            {apiInfo?.is_precomputed 
              ? `Showing ${apiInfo.label} pre-computed PMCC results`
              : "LEAPS-based covered call strategy with lower capital requirement"}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="outline"
            onClick={handleRefreshData}
            disabled={refreshing || loading}
            className="btn-outline"
            data-testid="refresh-pmcc-btn"
            title="Fetch fresh data from market (bypasses cache)"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing...' : 'Refresh Data'}
          </Button>
          <Button
            variant="outline"
            onClick={() => setFiltersOpen(!filtersOpen)}
            className="btn-outline"
          >
            <Filter className="w-4 h-4 mr-2" />
            {filtersOpen ? 'Hide' : 'Show'} Filters
          </Button>
          <Button
            onClick={() => { setActiveScan(null); fetchOpportunities(false); }}
            className="bg-violet-600 hover:bg-violet-700 text-white"
            data-testid="custom-pmcc-scan-btn"
          >
            <Search className="w-4 h-4 mr-2" />
            Custom Scan
          </Button>
        </div>
      </div>

      {/* Strategy Explanation - Compact Version */}
      <Card className="glass-card border-violet-500/30">
        <CardContent className="py-4">
          <div className="grid md:grid-cols-2 gap-4">
            <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp className="w-4 h-4 text-emerald-400" />
                <span className="font-medium text-emerald-400 text-sm">Long Leg (LEAPS)</span>
              </div>
              <ul className="space-y-1 text-xs text-zinc-400">
                <li>• <span className="text-white">12–24 months</span> expiration, deep ITM (δ0.80–0.90)</li>
                <li>• Acts as stock substitute at lower cost</li>
                <li>• <span className="text-emerald-400">Roll at 6 months remaining</span></li>
              </ul>
            </div>
            <div className="p-3 rounded-lg bg-cyan-500/5 border border-cyan-500/20">
              <div className="flex items-center gap-2 mb-2">
                <TrendingDown className="w-4 h-4 text-cyan-400" />
                <span className="font-medium text-cyan-400 text-sm">Short Leg (Sell Calls)</span>
              </div>
              <ul className="space-y-1 text-xs text-zinc-400">
                <li>• <span className="text-white">7–45 days</span> expiration, OTM (δ0.15–0.40)</li>
                <li>• Repeat to collect premium income</li>
                <li>• <span className="text-cyan-400">Roll at 50% profit or 21 DTE</span></li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Pre-Computed PMCC Scan Buttons */}
      <Card className="glass-card" data-testid="pmcc-precomputed-scans">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Zap className="w-5 h-5 text-violet-400" />
            Quick PMCC Scans
            <Badge className="ml-2 bg-violet-500/20 text-violet-400 border-violet-500/30 text-xs">
              Pre-Computed
            </Badge>
          </CardTitle>
          <p className="text-sm text-zinc-400 mt-1">
            Pre-computed PMCC opportunities with LEAPS + short call combinations. Updated daily at market close.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Capital Efficient Income - Conservative */}
            <button
              onClick={() => loadPrecomputedScan('conservative')}
              disabled={scanLoading}
              className={`p-4 rounded-xl border transition-all text-left group hover:scale-[1.02] ${
                activeScan === 'conservative'
                  ? 'bg-emerald-500/20 border-emerald-500/50'
                  : 'bg-zinc-800/50 border-zinc-700/50 hover:border-emerald-500/30 hover:bg-zinc-800'
              }`}
              data-testid="pmcc-scan-conservative"
            >
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 rounded-lg bg-emerald-500/20">
                  <Shield className="w-5 h-5 text-emerald-400" />
                </div>
                <div>
                  <h3 className="font-semibold text-white">Capital Efficient</h3>
                  <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">
                    Low Risk
                  </Badge>
                </div>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed">
                High delta LEAPS (0.70-0.80), 180+ DTE, conservative short calls
              </p>
              {availableScans?.pmcc?.[0]?.available && (
                <p className="text-xs text-zinc-500 mt-2">
                  {availableScans.pmcc[0].count} opportunities
                </p>
              )}
            </button>

            {/* Leveraged Income - Balanced */}
            <button
              onClick={() => loadPrecomputedScan('balanced')}
              disabled={scanLoading}
              className={`p-4 rounded-xl border transition-all text-left group hover:scale-[1.02] ${
                activeScan === 'balanced'
                  ? 'bg-blue-500/20 border-blue-500/50'
                  : 'bg-zinc-800/50 border-zinc-700/50 hover:border-blue-500/30 hover:bg-zinc-800'
              }`}
              data-testid="pmcc-scan-balanced"
            >
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 rounded-lg bg-blue-500/20">
                  <BarChart3 className="w-5 h-5 text-blue-400" />
                </div>
                <div>
                  <h3 className="font-semibold text-white">Leveraged Income</h3>
                  <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/30 text-xs">
                    Balanced
                  </Badge>
                </div>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Moderate delta LEAPS (0.65-0.75), 120-240 DTE, balanced risk/reward
              </p>
              {availableScans?.pmcc?.[1]?.available && (
                <p className="text-xs text-zinc-500 mt-2">
                  {availableScans.pmcc[1].count} opportunities
                </p>
              )}
            </button>

            {/* Max Yield Diagonal - Aggressive */}
            <button
              onClick={() => loadPrecomputedScan('aggressive')}
              disabled={scanLoading}
              className={`p-4 rounded-xl border transition-all text-left group hover:scale-[1.02] ${
                activeScan === 'aggressive'
                  ? 'bg-orange-500/20 border-orange-500/50'
                  : 'bg-zinc-800/50 border-zinc-700/50 hover:border-orange-500/30 hover:bg-zinc-800'
              }`}
              data-testid="pmcc-scan-aggressive"
            >
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 rounded-lg bg-orange-500/20">
                  <Flame className="w-5 h-5 text-orange-400" />
                </div>
                <div>
                  <h3 className="font-semibold text-white">Max Yield Diagonal</h3>
                  <Badge className="bg-orange-500/20 text-orange-400 border-orange-500/30 text-xs">
                    Aggressive
                  </Badge>
                </div>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Lower delta LEAPS (0.55-0.65), 12-24 month, aggressive short calls
              </p>
              {availableScans?.pmcc?.[2]?.available && (
                <p className="text-xs text-zinc-500 mt-2">
                  {availableScans.pmcc[2].count} opportunities
                </p>
              )}
            </button>
          </div>

          {/* Active scan indicator */}
          {activeScan && (
            <div className="mt-4 flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg border border-zinc-700">
              <div className="flex items-center gap-2">
                <Badge className={`${
                  activeScan === 'conservative' ? 'bg-emerald-500/20 text-emerald-400' :
                  activeScan === 'balanced' ? 'bg-blue-500/20 text-blue-400' :
                  'bg-orange-500/20 text-orange-400'
                }`}>
                  {apiInfo?.label || activeScan.charAt(0).toUpperCase() + activeScan.slice(1)}
                </Badge>
                <span className="text-sm text-zinc-400">
                  Pre-computed PMCC scan active • {opportunities.length} results
                </span>
                {apiInfo?.computed_at && (
                  <span className="text-xs text-zinc-500">
                    • Updated {new Date(apiInfo.computed_at).toLocaleDateString()}
                  </span>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearActiveScan}
                className="text-zinc-400 hover:text-white"
              >
                <X className="w-4 h-4 mr-1" />
                Clear
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid lg:grid-cols-4 gap-6">
        {/* Filters Panel */}
        {filtersOpen && (
          <Card className="glass-card lg:col-span-1 h-fit" data-testid="pmcc-filters-panel">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Filter className="w-5 h-5 text-violet-400" />
                  PMCC Filters
                </CardTitle>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={resetFilters}
                    className="btn-outline h-8 px-3"
                  >
                    Reset
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => fetchOpportunities(false)}
                    className="bg-violet-600 hover:bg-violet-700 text-white h-8 px-3"
                    data-testid="scan-pmcc-btn"
                  >
                    <Search className="w-3 h-3 mr-1" />
                    Scan
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <Accordion type="multiple" defaultValue={["stock", "leaps", "short", "roi"]} className="w-full">
                
                {/* Stock Price Filter */}
                <AccordionItem value="stock" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <DollarSign className="w-4 h-4 text-violet-400" />
                      Stock Price
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Price Range ($)</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          value={filters.minPrice}
                          onChange={(e) => setFilters(f => ({ ...f, minPrice: parseFloat(e.target.value) || 0 }))}
                          className="input-dark w-24 text-center"
                          placeholder="Min"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          value={filters.maxPrice}
                          onChange={(e) => setFilters(f => ({ ...f, maxPrice: parseFloat(e.target.value) || 1000 }))}
                          className="input-dark w-24 text-center"
                          placeholder="Max"
                        />
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* LEAPS (Long Leg) Filters */}
                <AccordionItem value="leaps" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-emerald-400" />
                      LEAPS (Long Leg)
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Delta Range</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          step="0.05"
                          value={filters.minLeapsDelta}
                          onChange={(e) => setFilters(f => ({ ...f, minLeapsDelta: parseFloat(e.target.value) || 0.7 }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          step="0.05"
                          value={filters.maxLeapsDelta}
                          onChange={(e) => setFilters(f => ({ ...f, maxLeapsDelta: parseFloat(e.target.value) || 1 }))}
                          className="input-dark w-20 text-center"
                        />
                      </div>
                      <p className="text-xs text-zinc-500 mt-1">Higher delta = deeper ITM</p>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Days to Expiration</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          value={filters.minLeapsDte}
                          onChange={(e) => setFilters(f => ({ ...f, minLeapsDte: parseInt(e.target.value) || 300 }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          value={filters.maxLeapsDte}
                          onChange={(e) => setFilters(f => ({ ...f, maxLeapsDte: parseInt(e.target.value) || 730 }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500 text-xs">days</span>
                      </div>
                      <p className="text-xs text-zinc-500 mt-1">365 = 12mo, 730 = 24mo</p>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Short Leg Filters */}
                <AccordionItem value="short" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <TrendingDown className="w-4 h-4 text-cyan-400" />
                      Short Call (Short Leg)
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Delta Range</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          step="0.05"
                          value={filters.minShortDelta}
                          onChange={(e) => setFilters(f => ({ ...f, minShortDelta: parseFloat(e.target.value) || 0.15 }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          step="0.05"
                          value={filters.maxShortDelta}
                          onChange={(e) => setFilters(f => ({ ...f, maxShortDelta: parseFloat(e.target.value) || 0.40 }))}
                          className="input-dark w-20 text-center"
                        />
                      </div>
                      <p className="text-xs text-zinc-500 mt-1">Lower delta = more OTM</p>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Days to Expiration</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          value={filters.minShortDte}
                          onChange={(e) => setFilters(f => ({ ...f, minShortDte: parseInt(e.target.value) || 7 }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          value={filters.maxShortDte}
                          onChange={(e) => setFilters(f => ({ ...f, maxShortDte: parseInt(e.target.value) || 45 }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500 text-xs">days</span>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* ROI Filters */}
                <AccordionItem value="roi" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Target className="w-4 h-4 text-yellow-400" />
                      ROI Targets
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Min ROI per Cycle (%)</Label>
                      <Input
                        type="number"
                        step="0.5"
                        value={filters.minRoiPerCycle}
                        onChange={(e) => setFilters(f => ({ ...f, minRoiPerCycle: e.target.value === '' ? '' : parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="Min"
                      />
                      <p className="text-xs text-zinc-500 mt-1">Premium / LEAPS cost</p>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Min Annualized ROI (%)</Label>
                      <Input
                        type="number"
                        value={filters.minAnnualizedRoi}
                        onChange={(e) => setFilters(f => ({ ...f, minAnnualizedRoi: e.target.value === '' ? '' : parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="Min"
                      />
                    </div>
                  </AccordionContent>
                </AccordionItem>

              </Accordion>
            </CardContent>
          </Card>
        )}

        {/* Results Section */}
        <div className={`space-y-4 ${filtersOpen ? 'lg:col-span-3' : 'lg:col-span-4'}`}>
          {/* LEAPS Data Info */}
          <div className="glass-card p-4 border-l-4 border-emerald-500">
            <div className="flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-sm font-medium text-emerald-400">True LEAPS Options Data</div>
                <div className="text-xs text-zinc-400 mt-1">
                  Fetching <strong className="text-white">real LEAPS options (12-24 months out)</strong> from the Massive.com API.
                  Click any row to view chart and detailed analysis.
                </div>
              </div>
            </div>
          </div>

          {/* Live Data Badge */}
          {apiInfo?.is_live && (
            <div className="flex items-center gap-2">
              <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
                <CheckCircle className="w-3 h-3 mr-1" />
                Live Options Data
              </Badge>
              <Badge className="bg-violet-500/20 text-violet-400 border-violet-500/30">
                {opportunities.length} Results
              </Badge>
              {apiInfo?.note && (
                <span className="text-xs text-zinc-500">{apiInfo.note}</span>
              )}
            </div>
          )}

          {/* Opportunities Table */}
          <Card className="glass-card">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-lg flex items-center gap-2">
                <LineChart className="w-5 h-5 text-violet-400" />
                PMCC Opportunities
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
                  {Array(8).fill(0).map((_, i) => (
                    <Skeleton key={i} className="h-14 rounded-lg" />
                  ))}
                </div>
              ) : opportunities.length === 0 ? (
                <div className="text-center py-12 text-zinc-500">
                  <LineChart className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>No PMCC opportunities match your criteria</p>
                  <p className="text-sm mt-2">Try adjusting your filters</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <SortHeader field="symbol" label="Symbol" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <SortHeader field="stock_price" label="Price" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <th>LEAPS (Buy)</th>
                        <SortHeader field="leaps_cost" label="Cost" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <th>Short (Sell)</th>
                        <SortHeader field="short_premium" label="Premium" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <SortHeader field="net_debit" label="Net Debit" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <th>Width</th>
                        <th>ROI/Cycle</th>
                        <th>Ann. ROI</th>
                        <SortHeader field="score" label="AI Score" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <th>Analyst</th>
                        <th className="text-center">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedOpportunities.map((opp, index) => {
                        // Normalize data from both custom API and pre-computed API
                        const norm = normalizeOpp(opp);
                        
                        return (
                          <tr 
                            key={index} 
                            className="cursor-pointer hover:bg-zinc-800/50 transition-colors" 
                            data-testid={`pmcc-row-${opp.symbol}`}
                            onClick={() => {
                              setSelectedStock(opp.symbol);
                              setSelectedScanData(activeScan ? opp : null);
                              setIsModalOpen(true);
                            }}
                            title={`Click to view ${opp.symbol} details with Technical, Fundamentals & News`}
                          >
                            <td className="font-semibold text-white">{opp.symbol}</td>
                            <td className="font-mono">${opp.stock_price?.toFixed(2)}</td>
                            <td>
                              <div className="flex flex-col">
                                <span className="text-emerald-400 font-mono text-sm">{formatOptionContract(norm.leaps_dte, norm.leaps_strike)}</span>
                                <span className="text-xs text-zinc-500">δ{norm.leaps_delta?.toFixed(2)}</span>
                              </div>
                            </td>
                            <td className="text-red-400 font-mono">${norm.leaps_cost?.toLocaleString()}</td>
                            <td>
                              <div className="flex flex-col">
                                <span className="text-cyan-400 font-mono text-sm">{formatOptionContract(opp.short_dte, opp.short_strike)}</span>
                                <span className="text-xs text-zinc-500">δ{opp.short_delta?.toFixed(2)}</span>
                              </div>
                            </td>
                            <td className="text-emerald-400 font-mono">${norm.short_premium_total?.toFixed(0)}</td>
                            <td className="text-white font-mono">${norm.net_debit?.toLocaleString()}</td>
                            <td className="font-mono">${norm.strike_width?.toFixed(0)}</td>
                            <td className="text-yellow-400 font-semibold">{norm.roi_per_cycle?.toFixed(1)}%</td>
                            <td className="text-emerald-400 font-semibold">{norm.annualized_roi?.toFixed(0)}%</td>
                            <td>
                              <Badge className={`${opp.score >= 70 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : opp.score >= 50 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' : 'bg-violet-500/20 text-violet-400 border-violet-500/30'}`}>
                                {opp.score?.toFixed(0)}
                              </Badge>
                            </td>
                            <td>
                              {opp.analyst_rating ? (
                                <Badge className={`text-xs ${
                                  opp.analyst_rating === 'Strong Buy' 
                                    ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                                    : opp.analyst_rating === 'Buy'
                                      ? 'bg-green-500/20 text-green-400 border-green-500/30'
                                      : opp.analyst_rating === 'Hold'
                                        ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                                        : 'bg-red-500/20 text-red-400 border-red-500/30'
                                }`}>
                                  {opp.analyst_rating}
                                </Badge>
                              ) : (
                                <span className="text-zinc-600 text-xs">-</span>
                              )}
                            </td>
                            <td className="text-center">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSimulateOpp(opp);
                                  setSimulateModalOpen(true);
                                }}
                                className="bg-violet-500/10 border-violet-500/30 text-violet-400 hover:bg-violet-500/20 hover:text-violet-300"
                                data-testid={`simulate-btn-${opp.symbol}`}
                              >
                                <Play className="w-3 h-3 mr-1" />
                                Simulate
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Simulate Trade Modal */}
      <Dialog open={simulateModalOpen} onOpenChange={setSimulateModalOpen}>
        <DialogContent className="bg-zinc-900 border-zinc-800 max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Play className="w-5 h-5 text-violet-400" />
              Add PMCC to Simulator
            </DialogTitle>
          </DialogHeader>
          {simulateOpp && (() => {
            const norm = normalizeOpp(simulateOpp);
            return (
            <div className="space-y-4 pt-4">
              <div className="p-4 bg-zinc-800/50 rounded-lg space-y-2">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Symbol</span>
                  <span className="font-semibold text-white">{simulateOpp.symbol}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Strategy</span>
                  <Badge className="bg-violet-500/20 text-violet-400">PMCC</Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Stock Price</span>
                  <span className="text-white">${simulateOpp.stock_price?.toFixed(2)}</span>
                </div>
                <div className="border-t border-zinc-700 pt-2 mt-2">
                  <div className="text-xs text-emerald-400 mb-1">LEAPS (Buy)</div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Strike</span>
                    <span className="text-white">${norm.leaps_strike?.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Cost</span>
                    <span className="text-red-400">${norm.leaps_cost?.toLocaleString()}</span>
                  </div>
                </div>
                <div className="border-t border-zinc-700 pt-2">
                  <div className="text-xs text-cyan-400 mb-1">Short Call (Sell)</div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Strike</span>
                    <span className="text-white">${simulateOpp.short_strike?.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Premium</span>
                    <span className="text-emerald-400">${norm.short_premium_total?.toFixed(0)}</span>
                  </div>
                </div>
                <div className="border-t border-zinc-700 pt-2">
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Net Debit</span>
                    <span className="text-white">${norm.net_debit?.toLocaleString()}</span>
                  </div>
                </div>
              </div>
              
              <div>
                <Label>Number of Contracts</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={simulateContracts}
                  onChange={(e) => setSimulateContracts(parseInt(e.target.value) || 1)}
                  className="input-dark mt-2"
                />
                <p className="text-xs text-zinc-500 mt-1">
                  Capital required: ${((norm.leaps_cost || 0) * simulateContracts).toLocaleString()}
                </p>
              </div>
              
              <div className="flex gap-2 pt-2">
                <Button
                  variant="outline"
                  onClick={() => setSimulateModalOpen(false)}
                  className="flex-1 btn-outline"
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleSimulate}
                  disabled={simulateLoading}
                  className="flex-1 bg-violet-600 hover:bg-violet-700 text-white"
                >
                  {simulateLoading ? 'Adding...' : 'Add to Simulator'}
                </Button>
              </div>
            </div>
          );})()}
        </DialogContent>
      </Dialog>

      {/* Stock Detail Modal */}
      <StockDetailModal 
        symbol={selectedStock}
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setSelectedStock(null);
          setSelectedScanData(null);
        }}
        scanData={selectedScanData}
      />
    </div>
  );
};

export default PMCC;
