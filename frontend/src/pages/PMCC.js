import { useState, useEffect, useRef } from 'react';
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../components/ui/tooltip';
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
  const [filtersOpen, setFiltersOpen] = useState(typeof window !== 'undefined' ? window.innerWidth >= 1024 : true);
  const [selectedStock, setSelectedStock] = useState(null);
  const [selectedScanData, setSelectedScanData] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [sortField, setSortField] = useState('score');
  const [sortDirection, setSortDirection] = useState('desc');

  // Pre-computed scans state
  const [availableScans, setAvailableScans] = useState(null);
  const [activeScan, setActiveScan] = useState(null);
  const activeScanRef = useRef(null);
  const [scanLoading, setScanLoading] = useState(false);

  // Simulator state
  const [simulateModalOpen, setSimulateModalOpen] = useState(false);
  const [simulateOpp, setSimulateOpp] = useState(null);
  const [simulateContracts, setSimulateContracts] = useState(1);
  const [simulateLoading, setSimulateLoading] = useState(false);

  // Expanded row details state
  const [expandedRow, setExpandedRow] = useState(null);

  // Helper to normalize PMCC data from both custom API (leap_*) and pre-computed API (long_*)
  // Note: Backend now uses nested objects (short_call, long_call) + legacy flat fields
  const normalizeOpp = (opp) => {
    if (!opp) return null;

    // Handle nested object structure (new) vs flat fields (legacy)
    const shortCall = opp.short_call || {};
    const longCall = opp.long_call || {};

    // Handle both leap_ and leaps_ naming (backend uses singular)
    const leapsDte = longCall.dte || opp.leap_dte || opp.leaps_dte || opp.long_dte;
    const leapsStrike = longCall.strike || opp.leap_strike || opp.leaps_strike || opp.long_strike;
    const leapsAsk = longCall.premium || longCall.ask || opp.leap_ask || opp.leaps_ask || opp.long_premium;
    const leapsDelta = longCall.delta || opp.leap_delta || opp.leaps_delta || opp.long_delta;
    const leapsExpiry = longCall.expiry || opp.leap_expiry || opp.leaps_expiry || opp.long_expiry;
    const leapsOi = longCall.open_interest || opp.leap_open_interest || opp.leaps_open_interest || 0;
    const leapsIv = longCall.implied_volatility || opp.leap_iv || opp.leaps_iv || 0;

    // Premium normalization:
    // Pre-computed scans store long_premium as PER-SHARE (e.g., $86)
    // Live scans may store leap_cost as TOTAL (e.g., $8600)
    // We need both: leaps_premium (per-share for display) and leaps_cost (total for calculations)
    const rawLeapCost = opp.leap_cost || opp.leaps_cost;
    let leapsCost, leapsPremium;

    if (rawLeapCost && rawLeapCost >= 100) {
      // If leap_cost exists and is >= 100, assume it's total cost
      leapsCost = rawLeapCost;
      leapsPremium = rawLeapCost / 100;
    } else if (leapsAsk) {
      // leapsAsk is always per-share from the backend
      leapsPremium = leapsAsk;
      leapsCost = leapsAsk * 100;
    } else {
      leapsPremium = 0;
      leapsCost = 0;
    }

    // Short call data - use nested object first, then flat fields
    const shortDelta = shortCall.delta || opp.short_delta || 0;
    const shortDte = shortCall.dte || opp.short_dte;
    const shortPremium = shortCall.premium || shortCall.bid || opp.short_premium || 0;
    const shortPremiumTotal = shortPremium < 10 ? shortPremium * 100 : shortPremium; // Normalize to total
    const shortIv = shortCall.implied_volatility || opp.short_iv || 0;
    const shortStrike = shortCall.strike || opp.short_strike;
    const shortExpiry = shortCall.expiry || opp.short_expiry;
    const shortAsk = shortCall.ask || opp.short_ask;

    // Use backend width if available, otherwise calculate
    const economics = opp.economics || {};
    const strikeWidth = economics.width || opp.width || opp.strike_width || (shortStrike && leapsStrike ? shortStrike - leapsStrike : 0);

    // Net debit: prefer net_debit_total (already per-contract), fall back to per-share × 100
    const rawNetDebit = economics.net_debit_total || opp.net_debit_total ||
      (economics.net_debit ? economics.net_debit * 100 : null) ||
      (opp.net_debit ? opp.net_debit * 100 : null) ||
      (leapsCost - shortPremiumTotal);
    const netDebit = rawNetDebit || 0;

    const roiPerCycle = economics.roi_pct || opp.roi_per_cycle || opp.roi_pct || (netDebit > 0 ? (shortPremiumTotal / netDebit) * 100 : 0);
    const annualizedRoi = economics.annualized_roi_pct || opp.annualized_roi || (shortDte > 0 ? roiPerCycle * (365 / shortDte) : 0);
    const breakeven = economics.breakeven || opp.breakeven || 0;
    const maxProfit = economics.max_profit || opp.max_profit || 0;

    const stockPrice = opp.stock_price || opp.price || 0;
    const stockEquivCost = stockPrice * 100;

    // Capital efficiency — compute from stock_price / net_debit if not stored in DB yet
    const rawCapEff = opp.capital_efficiency_ratio || economics.capital_efficiency_ratio || 0;
    const capEffRatio = rawCapEff > 0 ? rawCapEff : (netDebit > 0 ? stockEquivCost / netDebit : 0);

    const capitalSavedDollar = opp.capital_saved_dollar || economics.capital_saved_dollar || (stockEquivCost - netDebit);
    const capitalSavedPct = opp.capital_saved_percent || economics.capital_saved_percent ||
      (stockEquivCost > 0 ? ((stockEquivCost - netDebit) / stockEquivCost * 100) : 0);

    const leapsExtrinsicPct = opp.leaps_extrinsic_percent || economics.leaps_extrinsic_percent || 0;

    // Payback — use roi_per_cycle to avoid shortPremiumTotal normalization issues
    // payback_months = (100 / roi_per_cycle) * (short_dte / 30)
    const rawPayback = opp.payback_months || economics.payback_months || 0;
    const paybackMonths = rawPayback > 0 ? rawPayback :
      (roiPerCycle > 0 && shortDte > 0 ? (100 / roiPerCycle) * (shortDte / 30) : 0);

    const initialCappedPl = opp.initial_capped_pl || economics.initial_capped_pl ||
      ((strikeWidth * 100) - netDebit);
    const assignmentRisk = opp.assignment_risk || (shortDelta <= 0.20 ? "Low" : shortDelta <= 0.30 ? "Medium" : "High");
    const warningBadges = opp.warning_badges || [];
    const pmccScore = opp.pmcc_score || opp.score || 0;
    const syntheticStockCost = opp.synthetic_stock_cost || economics.synthetic_stock_cost ||
      (leapsStrike + leapsPremium);

    // Synthetic Premium % — how much more than stock price the synthetic costs
    const syntheticPremiumPct = stockPrice > 0
      ? ((syntheticStockCost - stockPrice) / stockPrice) * 100
      : 0;

    // Max Return if Assigned
    const shortPremiumPerShare = shortPremium < 10 ? shortPremium : shortPremium / 100;
    const upsideToStrike = shortStrike && stockPrice ? Math.max(0, shortStrike - stockPrice) : 0;
    const maxReturnPct = stockPrice > 0
      ? ((shortPremiumPerShare + upsideToStrike) / stockPrice) * 100
      : 0;

    // Return on Capital (If Assigned)
    const maxProfitDollar = strikeWidth > 0 ? (strikeWidth * 100) - netDebit : 0;
    const returnOnCapital = netDebit > 0 ? (maxProfitDollar / netDebit) * 100 : 0;

    // Adjusted Yield — penalise for high synthetic premium and low cap efficiency
    const capEffRatioFinal = opp.capital_efficiency_ratio || economics.capital_efficiency_ratio ||
      (netDebit > 0 ? stockEquivCost / netDebit : 0);
    const capEffScore = capEffRatioFinal > 1.8 ? 1.0 : capEffRatioFinal >= 1.3 ? 0.5 : 0;
    const synPenalty = syntheticPremiumPct < 2 ? 1.0 : syntheticPremiumPct <= 5 ? 0.7 : 0.4;
    const annYield = opp.annualized_income_yield || annualizedRoi || 0;
    const adjustedYield = annYield * capEffScore * synPenalty;

    // Weighted PMCC Score (client-side, fixes zero-score bug)
    const _capEffScore   = capEffRatioFinal > 1.8 ? 1.0 : capEffRatioFinal >= 1.3 ? 0.5 : 0;
    const _synScore      = syntheticPremiumPct < 2 ? 1.0 : syntheticPremiumPct <= 5 ? 0.6 : 0;
    const _incomeScore   = roiPerCycle > 5 ? 1.0 : roiPerCycle >= 3 ? 0.6 : 0.3;
    const leapsDeltaVal  = leapsDelta || 0;
    const _greeksScore   = leapsDeltaVal >= 0.8 && leapsDeltaVal <= 0.95 ? 1.0 : leapsDeltaVal >= 0.7 ? 0.6 : 0.3;
    // Liquidity: use short OI / spread as proxy
    const shortOI        = shortCall.open_interest || opp.short_oi || 0;
    const _liqScore      = shortOI >= 500 ? 1.0 : shortOI >= 100 ? 0.6 : 0.3;
    const computedScore  = Math.round(
      (_capEffScore * 25) + (_synScore * 25) + (_incomeScore * 20) + (_greeksScore * 15) + (_liqScore * 15)
    );
    // Use backend score if valid (>0), otherwise use computed
    const finalScore = (opp.pmcc_score || opp.score || 0) > 0
      ? (opp.pmcc_score || opp.score)
      : computedScore;

    // Trade Verdict
    const verdict = finalScore >= 75 ? '🟢 Strong' : finalScore >= 50 ? '🟡 Acceptable' : '🔴 Avoid';

    // Why This Trade — top 3 drivers
    const whyDrivers = [];
    if (capEffRatioFinal > 1.8) whyDrivers.push({ icon: '✅', text: `Strong capital efficiency (${capEffRatioFinal.toFixed(2)}x)` });
    else if (capEffRatioFinal >= 1.3) whyDrivers.push({ icon: '⚠️', text: `Moderate capital efficiency (${capEffRatioFinal.toFixed(2)}x)` });
    else whyDrivers.push({ icon: '❌', text: `Poor capital efficiency (${capEffRatioFinal.toFixed(2)}x)` });

    if (syntheticPremiumPct < 2) whyDrivers.push({ icon: '✅', text: `Low synthetic premium (${syntheticPremiumPct.toFixed(1)}%)` });
    else if (syntheticPremiumPct <= 5) whyDrivers.push({ icon: '⚠️', text: `Moderate synthetic premium (${syntheticPremiumPct.toFixed(1)}%)` });
    else whyDrivers.push({ icon: '❌', text: `High synthetic premium (${syntheticPremiumPct.toFixed(1)}%)` });

    if (roiPerCycle > 5) whyDrivers.push({ icon: '✅', text: `Strong income (${roiPerCycle.toFixed(1)}% per cycle)` });
    else if (roiPerCycle >= 3) whyDrivers.push({ icon: '⚠️', text: `Moderate income (${roiPerCycle.toFixed(1)}% per cycle)` });
    else whyDrivers.push({ icon: '❌', text: `Low income (${roiPerCycle.toFixed(1)}% per cycle)` });

    return {
      ...opp,
      // Short call normalized fields
      short_call: shortCall,  // Preserve nested object
      short_delta: shortDelta,
      short_dte: shortDte,
      short_premium: shortPremium,
      short_premium_total: shortPremiumTotal,
      short_iv: shortIv,
      short_strike: shortStrike,
      short_expiry: shortExpiry,
      short_ask: shortAsk,
      // Long call (LEAPS) normalized fields
      long_call: longCall,  // Preserve nested object
      leaps_dte: leapsDte,
      leaps_strike: leapsStrike,
      leaps_premium: leapsPremium,  // Per-share price for display
      leaps_ask: leapsPremium,      // Same as leaps_premium (per-share)
      leaps_cost: leapsCost,        // Total cost (per-share × 100)
      leaps_delta: leapsDelta,
      leaps_expiry: leapsExpiry,
      leaps_oi: leapsOi,
      leaps_iv: leapsIv,
      // Economics normalized fields
      net_debit: netDebit,
      strike_width: strikeWidth,
      roi_per_cycle: roiPerCycle,
      annualized_roi: annualizedRoi,
      breakeven: breakeven,
      max_profit: maxProfit,
      // Extended pmcc_scoring fields
      capital_efficiency_ratio: capEffRatio,
      capital_saved_dollar: capitalSavedDollar,
      capital_saved_percent: capitalSavedPct,
      leaps_extrinsic_percent: leapsExtrinsicPct,
      payback_months: paybackMonths,
      initial_capped_pl: initialCappedPl,
      assignment_risk: assignmentRisk,
      warning_badges: warningBadges,
      pmcc_score: pmccScore,
      synthetic_stock_cost: syntheticStockCost,
      synthetic_premium_pct: syntheticPremiumPct,
      max_return_pct: maxReturnPct,
      return_on_capital: returnOnCapital,
      max_profit_dollar: maxProfitDollar,
      adjusted_yield: adjustedYield,
      pmcc_score: finalScore,
      verdict,
      why_drivers: whyDrivers,
    };
  };

  // Handle adding to simulator
  const handleSimulate = async () => {
    if (!simulateOpp) return;

    setSimulateLoading(true);
    try {
      // Normalize the data first
      const norm = normalizeOpp(simulateOpp);

      const shortIvPct = norm.short_iv || 0;
      const shortIvDecimal = shortIvPct > 1 ? shortIvPct / 100 : shortIvPct;

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
        short_call_iv: shortIvDecimal,
        leaps_strike: norm.leaps_strike,
        leaps_expiry: norm.leaps_expiry,
        leaps_premium: leapsPremiumPerShare,
        leaps_delta: norm.leaps_delta,
        contracts: simulateContracts,
        scan_parameters: {
            short_iv_pct: shortIvPct,
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

  // PMCC Filters
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
    // On initial load, load Custom Scan by default (user preference per Phase 5)
    // Pre-computed scans available via Quick Scans buttons
    const initializeData = async () => {
      try {
        const res = await scansApi.getAvailable();
        setAvailableScans(res.data.scans);

        // Default to Custom Scan - user can click Quick Scans for pre-computed
        fetchOpportunities();
      } catch (error) {
        console.log('Could not fetch available scans, loading custom scan:', error);
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
    activeScanRef.current = riskProfile;
    try {
      const res = await scansApi.getPMCCScan(riskProfile);
      const loaded = res.data.opportunities || [];
      setOpportunities(loaded);
      setApiInfo({
        from_cache: false,
        is_precomputed: true,
        computed_at: res.data.computed_at,
        risk_profile: riskProfile,
        label: res.data.label
      });
      // Update card count to reflect actual loaded results
      setAvailableScans(prev => {
        if (!prev?.pmcc) return prev;
        const profileOrder = ['conservative', 'balanced', 'aggressive'];
        const idx = profileOrder.indexOf(riskProfile);
        if (idx === -1) return prev;
        const updated = [...prev.pmcc];
        updated[idx] = { ...updated[idx], count: res.data.total ?? loaded.length };
        return { ...prev, pmcc: updated };
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
    activeScanRef.current = null;
    fetchOpportunities();
  };

  const fetchOpportunities = async (bypassCache = false) => {
    setLoading(true);
    try {
      // Only pass non-empty filter values
      const clampDelta = (v) => v !== '' && v !== undefined ? Math.min(Math.max(parseFloat(v), 0), 1) : v;
      const params = {};
      if (filters.minPrice) params.min_price = filters.minPrice;
      if (filters.maxPrice) params.max_price = filters.maxPrice;
      if (filters.minLeapsDelta !== '') params.min_leaps_delta = clampDelta(filters.minLeapsDelta);
      if (filters.maxLeapsDelta !== '') params.max_leaps_delta = clampDelta(filters.maxLeapsDelta);
      if (filters.minLeapsDte) params.min_leap_dte = filters.minLeapsDte;
      if (filters.maxLeapsDte) params.max_leap_dte = filters.maxLeapsDte;
      if (filters.minShortDelta !== '') params.min_short_delta = clampDelta(filters.minShortDelta);
      if (filters.maxShortDelta !== '') params.max_short_delta = clampDelta(filters.maxShortDelta);
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

      if (!activeScanRef.current) {
        setOpportunities(opportunities);
        setApiInfo(response.data);
      }
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
            onClick={() => { setActiveScan(null); fetchOpportunities(true); }}
            className="bg-violet-600 hover:bg-violet-700 text-white"
            data-testid="custom-pmcc-scan-btn"
          >
            <Search className="w-4 h-4 mr-2" />
            Custom Scan
          </Button>
        </div>
      </div>

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

      <div className="grid lg:grid-cols-10 gap-4">
        {/* Filters Panel */}
        {filtersOpen && (
          <Card className="glass-card lg:col-span-2 h-fit max-h-[60vh] lg:max-h-none overflow-y-auto" data-testid="pmcc-filters-panel">
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
                    onClick={() => { setActiveScan(null); activeScanRef.current = null; fetchOpportunities(true); }}
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
                          value={filters.minPrice ?? ''}
                          onChange={(e) => setFilters(f => ({ ...f, minPrice: e.target.value }))}
                          className="input-dark w-24 text-center"
                          placeholder="Min"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          value={filters.maxPrice ?? ''}
                          onChange={(e) => setFilters(f => ({ ...f, maxPrice: e.target.value }))}
                          className="input-dark w-24 text-center"
                          placeholder="Max"
                        />
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                {/* LEAPS (Long) Filters */}
                <AccordionItem value="leaps" className="border-zinc-800">
                  <AccordionTrigger className="text-sm font-medium hover:no-underline">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-emerald-400" />
                      LEAPS (Long)
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Delta Range</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          step="0.05"
                          min="0"
                          max="1"
                          value={filters.minLeapsDelta}
                          onChange={(e) => setFilters(f => ({ ...f, minLeapsDelta: e.target.value }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          step="0.05"
                          min="0"
                          max="1"
                          value={filters.maxLeapsDelta}
                          onChange={(e) => setFilters(f => ({ ...f, maxLeapsDelta: e.target.value }))}
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
                          onChange={(e) => setFilters(f => ({ ...f, minLeapsDte: e.target.value }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          value={filters.maxLeapsDte}
                          onChange={(e) => setFilters(f => ({ ...f, maxLeapsDte: e.target.value }))}
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
                      Short Call
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div>
                      <Label className="text-xs text-zinc-400">Delta Range</Label>
                      <div className="flex items-center gap-2 mt-2">
                        <Input
                          type="number"
                          step="0.05"
                          min="0"
                          max="1"
                          value={filters.minShortDelta}
                          onChange={(e) => setFilters(f => ({ ...f, minShortDelta: e.target.value }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          step="0.05"
                          min="0"
                          max="1"
                          value={filters.maxShortDelta}
                          onChange={(e) => setFilters(f => ({ ...f, maxShortDelta: e.target.value }))}
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
                          onChange={(e) => setFilters(f => ({ ...f, minShortDte: e.target.value }))}
                          className="input-dark w-20 text-center"
                        />
                        <span className="text-zinc-500">to</span>
                        <Input
                          type="number"
                          value={filters.maxShortDte}
                          onChange={(e) => setFilters(f => ({ ...f, maxShortDte: e.target.value }))}
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
                        onChange={(e) => setFilters(f => ({ ...f, minRoiPerCycle: e.target.value }))}
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
                        onChange={(e) => setFilters(f => ({ ...f, minAnnualizedRoi: e.target.value }))}
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
        <div className={`space-y-4 ${filtersOpen ? 'lg:col-span-8' : 'lg:col-span-10'}`}>
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
                <div className="overflow-x-auto w-full">
                  <table className="data-table text-xs" style={{minWidth: '1100px'}}>
                    <thead>
                      <tr>
                        <SortHeader field="symbol" label="Symbol" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <SortHeader field="stock_price" label="Price" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <th>LEAPS</th>
                        <th>Short Call</th>
                        <SortHeader field="net_debit" label="Net Debit" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <SortHeader field="capital_efficiency_ratio" label="Cap Eff" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <SortHeader field="roi_per_cycle" label="Income/Cycle" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <SortHeader field="max_return_pct" label="Max Return" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <SortHeader field="payback_months" label="Payback" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <SortHeader field="score" label="Score" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        <th>Signal</th>
                        <th className="text-center w-px whitespace-nowrap">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedOpportunities.map((opp, index) => {
                        const norm = normalizeOpp(opp);
                        const isExpanded = expandedRow === opp.symbol;

                        const cer = norm.capital_efficiency_ratio || 0;
                        const cerColor = cer > 1.8 ? 'text-emerald-400' : cer >= 1.3 ? 'text-yellow-400' : 'text-red-400';
                        const cerIcon = cer > 1.8 ? '🟢' : cer >= 1.3 ? '🟡' : '🔴';
                        const synthPct = norm.synthetic_premium_pct || 0;
                        const synthColor = synthPct < 2 ? 'text-emerald-400' : synthPct <= 5 ? 'text-yellow-400' : 'text-red-400';

                        const extPct = norm.leaps_extrinsic_percent || 0;
                        const extColor = extPct < 15 ? 'text-emerald-400' : extPct <= 25 ? 'text-yellow-400' : 'text-red-400';

                        const pbMonths = norm.payback_months || 0;
                        const pbColor = pbMonths < 12 ? 'text-emerald-400' : pbMonths <= 18 ? 'text-yellow-400' : 'text-red-400';

                        return (
                          <>
                            <tr
                              key={`row-${index}`}
                              className="cursor-pointer hover:bg-zinc-800/50 transition-colors"
                              data-testid={`pmcc-row-${opp.symbol}`}
                              onClick={() => {
                                setSelectedStock(opp.symbol);
                                setSelectedScanData(activeScan ? opp : null);
                                setIsModalOpen(true);
                              }}
                              title={`Click to view ${opp.symbol} details`}
                            >
                              <td className="font-semibold text-white">
                                <div className="flex flex-col gap-0.5">
                                  <span>{opp.symbol}</span>
                                  {norm.warning_badges && norm.warning_badges.length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-0.5">
                                      {norm.warning_badges.map((badge, bi) => (
                                        <span key={bi} className="text-[10px] bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded px-1 py-0 leading-4">{badge}</span>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              </td>
                              <td className="font-mono">${opp.stock_price?.toFixed(2)}</td>
                              <td>
                                <div className="flex flex-col">
                                  <span className="text-emerald-400 font-mono text-sm">
                                    {(() => { const s = formatOptionContract(norm.leaps_expiry || norm.leaps_dte, norm.leaps_strike); const i = s.indexOf(' '); return i > -1 ? <>{s.slice(0, i)}<br />{s.slice(i + 1)}</> : s; })()}
                                  </span>
                                  <span className="text-zinc-400">δ{norm.leaps_delta?.toFixed(2) || '-'} | {norm.leaps_dte}d</span>
                                </div>
                              </td>
                              <td>
                                <div className="flex flex-col">
                                  <span className="text-cyan-400 font-mono text-sm">
                                    {(() => { const s = formatOptionContract(opp.short_expiry || opp.short_dte, opp.short_strike); const i = s.indexOf(' '); return i > -1 ? <>{s.slice(0, i)}<br />{s.slice(i + 1)}</> : s; })()}
                                  </span>
                                  <span className="text-zinc-400">δ{(opp.short_delta || norm.short_delta)?.toFixed(2) || '-'} | {opp.short_dte}d</span>
                                </div>
                              </td>
                              <td className="text-white font-mono">${norm.net_debit?.toLocaleString()}</td>
                              <td className={`font-semibold ${cerColor}`}>
                                {cerIcon} {cer?.toFixed(2)}x
                              </td>
                              <td className="text-yellow-400 font-semibold">{norm.roi_per_cycle?.toFixed(1)}%</td>
                              <td className="text-emerald-400 font-semibold">
                                {norm.max_return_pct > 0 ? `${norm.max_return_pct.toFixed(1)}%` : '-'}
                              </td>
                              <td className={`font-semibold ${pbColor}`}>{pbMonths > 0 ? `${pbMonths?.toFixed(1)}mo` : '-'}</td>
                              <td>
                                <Badge className={`${norm.pmcc_score >= 70 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : norm.pmcc_score >= 50 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' : 'bg-violet-500/20 text-violet-400 border-violet-500/30'}`}>
                                  {norm.pmcc_score?.toFixed(0)}
                                </Badge>
                              </td>
                              <td>
                                {(opp.analyst_rating_label || opp.analyst_rating) ? (
                                  <Badge className={`text-xs ${
                                    (opp.analyst_rating_label || opp.analyst_rating) === 'Strong Buy'
                                      ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                                      : (opp.analyst_rating_label || opp.analyst_rating) === 'Buy'
                                        ? 'bg-green-500/20 text-green-400 border-green-500/30'
                                        : (opp.analyst_rating_label || opp.analyst_rating) === 'Hold'
                                          ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                                          : 'bg-red-500/20 text-red-400 border-red-500/30'
                                  }`}>
                                    {opp.analyst_rating_label || opp.analyst_rating}
                                  </Badge>
                                ) : (
                                  <span className="text-zinc-600 text-xs">N/A</span>
                                )}
                              </td>
                              <td className="text-center">
                                <div className="flex gap-1 justify-center">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setExpandedRow(isExpanded ? null : opp.symbol);
                                    }}
                                    className="bg-zinc-700/40 border-zinc-600 text-zinc-300 hover:bg-zinc-600/60 hover:text-white"
                                    title="Toggle details panel"
                                  >
                                    {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                                    Details
                                  </Button>
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
                                </div>
                              </td>
                            </tr>
                            {isExpanded && (
                              <tr key={`details-${index}`} className="bg-zinc-900/60">
                                <td colSpan={11} className="px-4 py-4">
                                  {/* Verdict + Why This Trade banner */}
                                  <div className="flex flex-wrap items-start gap-4 mb-4">
                                    <div className={`px-4 py-2 rounded-lg border text-sm font-semibold ${norm.verdict?.startsWith('🟢') ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : norm.verdict?.startsWith('🟡') ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400' : 'bg-red-500/10 border-red-500/30 text-red-400'}`}>
                                      Trade Verdict: {norm.verdict} &nbsp;|&nbsp; Score: {norm.pmcc_score}
                                    </div>
                                    <div className="flex gap-2 flex-wrap">
                                      {(norm.why_drivers || []).map((d, di) => (
                                        <span key={di} className="text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-zinc-300">{d.icon} {d.text}</span>
                                      ))}
                                    </div>
                                  </div>

                                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 text-xs">
                                    {/* Trade Structure */}
                                    <div className="bg-zinc-800/60 rounded-lg p-3 space-y-1">
                                      <p className="text-zinc-400 font-semibold uppercase tracking-wide text-[10px] mb-2">Trade Structure</p>
                                      <div className="flex justify-between"><span className="text-zinc-500">Stock Price</span><span className="font-mono text-white">${opp.stock_price?.toFixed(2)}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">LEAPS Strike</span><span className="font-mono text-emerald-400">${norm.leaps_strike?.toFixed(0)}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Short Strike</span><span className="font-mono text-cyan-400">${norm.short_strike?.toFixed(0)}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Net Debit / Share</span><span className="font-mono text-white">${norm.net_debit ? (norm.net_debit / 100).toFixed(2) : '-'}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Net Debit / Contract</span><span className="font-mono text-white">${norm.net_debit ? norm.net_debit.toLocaleString() : '-'}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Width</span><span className="font-mono">${norm.strike_width?.toFixed(0)}</span></div>
                                    </div>
                                    {/* Capital Analysis */}
                                    <div className="bg-zinc-800/60 rounded-lg p-3 space-y-1">
                                      <p className="text-zinc-400 font-semibold uppercase tracking-wide text-[10px] mb-2">Capital Analysis</p>
                                      <div className="flex justify-between"><span className="text-zinc-500">Stock Cost (100sh)</span><span className="font-mono">${opp.stock_equivalent_cost?.toLocaleString() || (opp.stock_price * 100)?.toLocaleString()}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">PMCC Cost (1 contract)</span><span className="font-mono text-red-400">${norm.net_debit ? norm.net_debit.toLocaleString() : '-'}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Capital Saved</span><span className="font-mono text-emerald-400">${norm.capital_saved_dollar?.toLocaleString() || '-'}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Cap Efficiency</span><span className={`font-mono font-semibold ${cerColor}`}>{cerIcon} {cer?.toFixed(2)}x</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Capital Saved %</span><span className="font-mono text-emerald-400">{norm.capital_saved_percent?.toFixed(1)}%</span></div>
                                    </div>
                                    {/* LEAPS Quality */}
                                    <div className="bg-zinc-800/60 rounded-lg p-3 space-y-1">
                                      <p className="text-zinc-400 font-semibold uppercase tracking-wide text-[10px] mb-2">LEAPS Quality</p>
                                      <div className="flex justify-between"><span className="text-zinc-500">Delta</span><span className="font-mono">{norm.leaps_delta?.toFixed(2)}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Extrinsic %</span><span className={`font-mono font-semibold ${extColor}`}>{extPct?.toFixed(1)}%</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">DTE</span><span className="font-mono">{norm.leaps_dte}d</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Ask (per share)</span><span className="font-mono">${norm.leaps_premium?.toFixed(2)}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Synthetic Cost</span><span className="font-mono">${norm.synthetic_stock_cost?.toFixed(2) || '-'}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Synthetic Premium %</span><span className={`font-mono font-semibold ${synthColor}`}>{synthPct?.toFixed(1)}%</span></div>
                                    </div>
                                    {/* Income Analysis */}
                                    <div className="bg-zinc-800/60 rounded-lg p-3 space-y-1">
                                      <p className="text-zinc-400 font-semibold uppercase tracking-wide text-[10px] mb-2">Income Analysis</p>
                                      <div className="flex justify-between"><span className="text-zinc-500">Short Bid (per share)</span><span className="font-mono text-emerald-400">${norm.short_premium?.toFixed(2)}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Short Premium (total)</span><span className="font-mono text-emerald-400">${norm.short_premium ? (norm.short_premium * 100).toFixed(0) : '-'}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">ROI / Cycle</span><span className="font-mono font-semibold text-yellow-400">{norm.roi_per_cycle?.toFixed(2)}%</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Cycle Length</span><span className="font-mono">{norm.short_dte}d</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Ann. Yield</span><span className="font-mono text-emerald-400">{(opp.annualized_income_yield || norm.annualized_roi)?.toFixed(1)}%</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Adjusted Yield</span><span className={`font-mono font-semibold ${(norm.adjusted_yield || 0) > 30 ? 'text-emerald-400' : (norm.adjusted_yield || 0) > 15 ? 'text-yellow-400' : 'text-red-400'}`}>{norm.adjusted_yield?.toFixed(1)}%</span></div>
                                    </div>
                                    {/* Payback & Risk */}
                                    <div className="bg-zinc-800/60 rounded-lg p-3 space-y-1">
                                      <p className="text-zinc-400 font-semibold uppercase tracking-wide text-[10px] mb-2">Payback & Risk</p>
                                      <div className="flex justify-between"><span className="text-zinc-500">Payback Months</span><span className={`font-mono font-semibold ${pbColor}`}>{pbMonths?.toFixed(1)}mo</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Assignment Risk</span><span className={`font-semibold ${norm.assignment_risk === 'Low' ? 'text-emerald-400' : norm.assignment_risk === 'Medium' ? 'text-yellow-400' : 'text-red-400'}`}>{norm.assignment_risk}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Short Delta</span><span className="font-mono">{norm.short_delta?.toFixed(2)}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Breakeven</span><span className="font-mono">${norm.breakeven?.toFixed(2)}</span></div>
                                    </div>
                                    {/* If Assigned */}
                                    <div className="bg-zinc-800/60 rounded-lg p-3 space-y-1">
                                      <p className="text-zinc-400 font-semibold uppercase tracking-wide text-[10px] mb-2">If Assigned</p>
                                      <div className="flex justify-between"><span className="text-zinc-500">Max Spread Value</span><span className="font-mono">${norm.strike_width ? (norm.strike_width * 100)?.toLocaleString() : '-'}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Max Profit ($)</span><span className={`font-mono font-semibold ${(norm.max_profit_dollar || 0) > 0 ? 'text-emerald-400' : 'text-red-400'}`}>${norm.max_profit_dollar?.toLocaleString() || '-'}</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">Return on Capital</span><span className={`font-mono font-semibold ${(norm.return_on_capital || 0) > 0 ? 'text-emerald-400' : 'text-red-400'}`}>{norm.return_on_capital?.toFixed(1)}%</span></div>
                                      <div className="flex justify-between"><span className="text-zinc-500">PMCC Cost (1 contract)</span><span className="font-mono text-red-400">${norm.net_debit ? norm.net_debit.toLocaleString() : '-'}</span></div>
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </>
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
