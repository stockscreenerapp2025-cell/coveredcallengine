import { useState, useEffect } from 'react';
import { screenerApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
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
  ChevronUp
} from 'lucide-react';
import { toast } from 'sonner';
import StockDetailModal from '../components/StockDetailModal';

const PMCC = () => {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [apiInfo, setApiInfo] = useState(null);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [selectedStock, setSelectedStock] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [sortField, setSortField] = useState('score');
  const [sortDirection, setSortDirection] = useState('desc');

  // PMCC Filters
  const [filters, setFilters] = useState({
    // Stock filters
    minPrice: 30,
    maxPrice: 500,
    // LEAPS filters
    minLeapsDelta: 0.70,
    maxLeapsDelta: 1.0,
    minLeapsDte: 300,
    maxLeapsDte: 730,
    // Short leg filters
    minShortDelta: 0.15,
    maxShortDelta: 0.40,
    minShortDte: 7,
    maxShortDte: 45,
    // ROI filters
    minRoiPerCycle: 1.0,
    minAnnualizedRoi: 20,
  });

  useEffect(() => {
    fetchOpportunities();
  }, []);

  const fetchOpportunities = async () => {
    setLoading(true);
    try {
      const response = await screenerApi.getPMCC({
        min_price: filters.minPrice,
        max_price: filters.maxPrice,
        min_leaps_delta: filters.minLeapsDelta,
        max_leaps_delta: filters.maxLeapsDelta,
        min_leaps_dte: filters.minLeapsDte,
        max_leaps_dte: filters.maxLeapsDte,
        min_short_delta: filters.minShortDelta,
        max_short_delta: filters.maxShortDelta,
        min_short_dte: filters.minShortDte,
        max_short_dte: filters.maxShortDte,
        min_roi: filters.minRoiPerCycle,
        min_annualized_roi: filters.minAnnualizedRoi,
      });
      setOpportunities(response.data.opportunities || []);
      setApiInfo(response.data);
    } catch (error) {
      console.error('PMCC fetch error:', error);
      toast.error('Failed to load PMCC opportunities');
    } finally {
      setLoading(false);
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
  const formatOptionContract = (expiry, strike, type = 'C') => {
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
      return `${dateStr} ${strike?.toFixed(0) || ''} ${type}`;
    } catch {
      return `${strike?.toFixed(0) || ''} ${type}`;
    }
  };

  const sortedOpportunities = [...opportunities].sort((a, b) => {
    const aVal = a[sortField] || 0;
    const bVal = b[sortField] || 0;
    return sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
  });

  const resetFilters = () => {
    setFilters({
      minPrice: 30,
      maxPrice: 500,
      minLeapsDelta: 0.70,
      maxLeapsDelta: 1.0,
      minLeapsDte: 300,
      maxLeapsDte: 730,
      minShortDelta: 0.15,
      maxShortDelta: 0.40,
      minShortDte: 7,
      maxShortDte: 45,
      minRoiPerCycle: 1.0,
      minAnnualizedRoi: 20,
    });
    toast.success('Filters reset to defaults');
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
    <div className="space-y-6" data-testid="pmcc-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <LineChart className="w-8 h-8 text-violet-500" />
            Poor Man's Covered Call (PMCC)
          </h1>
          <p className="text-zinc-400 mt-1">LEAPS-based covered call strategy with lower capital requirement</p>
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
            Reset
          </Button>
          <Button
            onClick={fetchOpportunities}
            className="bg-violet-600 hover:bg-violet-700 text-white"
            data-testid="scan-pmcc-btn"
          >
            <Search className="w-4 h-4 mr-2" />
            Scan
          </Button>
        </div>
      </div>

      {/* Strategy Explanation */}
      <Card className="glass-card border-violet-500/30">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2 text-violet-400">
            <Info className="w-5 h-5" />
            PMCC Strategy Structure
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="p-4 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="w-5 h-5 text-emerald-400" />
                <span className="font-medium text-emerald-400">1. Buy LEAPS Call (Long Leg)</span>
              </div>
              <ul className="space-y-2 text-sm text-zinc-300">
                <li>• <span className="text-white">Long expiration:</span> 12–24 months</li>
                <li>• <span className="text-white">Deep ITM:</span> High delta (~0.80–0.90)</li>
                <li>• Acts as a stock substitute at lower cost</li>
              </ul>
            </div>
            <div className="p-4 rounded-lg bg-cyan-500/5 border border-cyan-500/20">
              <div className="flex items-center gap-2 mb-3">
                <TrendingDown className="w-5 h-5 text-cyan-400" />
                <span className="font-medium text-cyan-400">2. Sell Short-Term Calls (Short Leg)</span>
              </div>
              <ul className="space-y-2 text-sm text-zinc-300">
                <li>• <span className="text-white">Expiration:</span> 7–45 days</li>
                <li>• <span className="text-white">Out-of-the-money:</span> Delta 0.15–0.40</li>
                <li>• Repeat regularly to collect income</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid lg:grid-cols-4 gap-6">
        {/* Filters Panel */}
        {filtersOpen && (
          <Card className="glass-card lg:col-span-1 h-fit" data-testid="pmcc-filters-panel">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg flex items-center gap-2">
                <Filter className="w-5 h-5 text-violet-400" />
                PMCC Filters
              </CardTitle>
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
                        onChange={(e) => setFilters(f => ({ ...f, minRoiPerCycle: parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="1.0"
                      />
                      <p className="text-xs text-zinc-500 mt-1">Premium / LEAPS cost</p>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-400">Min Annualized ROI (%)</Label>
                      <Input
                        type="number"
                        value={filters.minAnnualizedRoi}
                        onChange={(e) => setFilters(f => ({ ...f, minAnnualizedRoi: parseFloat(e.target.value) || 0 }))}
                        className="input-dark mt-2"
                        placeholder="20"
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
                        <SortHeader field="symbol" label="Symbol" />
                        <SortHeader field="stock_price" label="Price" />
                        <th>LEAPS (Buy)</th>
                        <SortHeader field="leaps_cost" label="Cost" />
                        <th>Short (Sell)</th>
                        <SortHeader field="short_premium" label="Premium" />
                        <SortHeader field="net_debit" label="Net Debit" />
                        <SortHeader field="strike_width" label="Width" />
                        <SortHeader field="roi_per_cycle" label="ROI/Cycle" />
                        <SortHeader field="annualized_roi" label="Ann. ROI" />
                        <SortHeader field="score" label="Score" />
                      </tr>
                    </thead>
                    <tbody>
                      {sortedOpportunities.map((opp, index) => (
                        <tr 
                          key={index} 
                          className="cursor-pointer hover:bg-zinc-800/50 transition-colors" 
                          data-testid={`pmcc-row-${opp.symbol}`}
                          onClick={() => {
                            setSelectedStock(opp.symbol);
                            setIsModalOpen(true);
                          }}
                          title={`Click to view ${opp.symbol} details`}
                        >
                          <td className="font-semibold text-white">{opp.symbol}</td>
                          <td className="font-mono">${opp.stock_price?.toFixed(2)}</td>
                          <td>
                            <div className="flex flex-col">
                              <span className="text-emerald-400 font-mono text-sm">{formatOptionContract(opp.leaps_dte, opp.leaps_strike)}</span>
                              <span className="text-xs text-zinc-500">δ{opp.leaps_delta?.toFixed(2)}</span>
                            </div>
                          </td>
                          <td className="text-red-400 font-mono">${opp.leaps_cost?.toLocaleString()}</td>
                          <td>
                            <div className="flex flex-col">
                              <span className="text-cyan-400 font-mono text-sm">{formatOptionContract(opp.short_dte, opp.short_strike)}</span>
                              <span className="text-xs text-zinc-500">δ{opp.short_delta?.toFixed(2)}</span>
                            </div>
                          </td>
                          <td className="text-emerald-400 font-mono">${opp.short_premium?.toFixed(0)}</td>
                          <td className="text-white font-mono">${opp.net_debit?.toLocaleString()}</td>
                          <td className="font-mono">${opp.strike_width?.toFixed(0)}</td>
                          <td className="text-yellow-400 font-semibold">{opp.roi_per_cycle?.toFixed(1)}%</td>
                          <td className="text-emerald-400 font-semibold">{opp.annualized_roi?.toFixed(0)}%</td>
                          <td>
                            <Badge className={`${opp.score >= 70 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : opp.score >= 50 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' : 'bg-violet-500/20 text-violet-400 border-violet-500/30'}`}>
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

          {/* Strategy Tips */}
          <div className="grid md:grid-cols-2 gap-6">
            <Card className="glass-card">
              <CardHeader>
                <CardTitle className="text-sm text-emerald-400">PMCC Advantages</CardTitle>
              </CardHeader>
              <CardContent className="text-xs text-zinc-400 space-y-2">
                <p>• <span className="text-white">Lower capital requirement</span> - LEAPS cost less than 100 shares</p>
                <p>• <span className="text-white">Built-in leverage</span> - Control 100 shares with less money</p>
                <p>• <span className="text-white">Income generation</span> - Sell short calls repeatedly for premium</p>
                <p>• <span className="text-white">Defined risk</span> - Maximum loss is the net debit paid</p>
              </CardContent>
            </Card>

            <Card className="glass-card">
              <CardHeader>
                <CardTitle className="text-sm text-cyan-400">Key Management Rules</CardTitle>
              </CardHeader>
              <CardContent className="text-xs text-zinc-400 space-y-2">
                <p>• <span className="text-white">LEAPS delta:</span> Keep at 0.80-0.90 (deep ITM) to minimize extrinsic value</p>
                <p>• <span className="text-white">Short call delta:</span> Stay at 0.20-0.30 (OTM) to reduce assignment risk</p>
                <p>• <span className="text-white">Roll short calls:</span> At 50% profit or 21 DTE remaining</p>
                <p>• <span className="text-white">Roll LEAPS:</span> When 6 months remaining to avoid theta acceleration</p>
              </CardContent>
            </Card>
          </div>
        </div>
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

export default PMCC;
