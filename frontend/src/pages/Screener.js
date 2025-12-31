import { useState, useEffect } from 'react';
import { screenerApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Slider } from '../components/ui/slider';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
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
  Search,
  Filter,
  Save,
  RefreshCw,
  Download,
  ChevronDown,
  ChevronUp,
  X
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

  // Filter states
  const [filters, setFilters] = useState({
    minRoi: 1.0,
    maxDte: 45,
    minDelta: 0.2,
    maxDelta: 0.4,
    minIvRank: 0,
    minVolume: 0,
    minOpenInterest: 0,
  });

  useEffect(() => {
    fetchOpportunities();
    fetchSavedFilters();
  }, []);

  const fetchOpportunities = async () => {
    setLoading(true);
    try {
      const response = await screenerApi.getCoveredCalls({
        min_roi: filters.minRoi,
        max_dte: filters.maxDte,
        min_delta: filters.minDelta,
        max_delta: filters.maxDelta,
        min_iv_rank: filters.minIvRank,
      });
      setOpportunities(response.data.opportunities || []);
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
        filters: filters
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
    setFilters(savedFilter.filters);
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

  const exportToCSV = () => {
    const headers = ['Symbol', 'Stock Price', 'Strike', 'Expiry', 'DTE', 'Premium', 'ROI %', 'Delta', 'IV', 'IV Rank', 'Score'];
    const rows = sortedOpportunities.map(o => [
      o.symbol, o.stock_price, o.strike, o.expiry, o.dte, o.premium, o.roi_pct, o.delta, o.iv, o.iv_rank, o.score
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
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white">Covered Call Screener</h1>
          <p className="text-zinc-400 mt-1">Find optimal premium selling opportunities</p>
        </div>
        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={() => setFiltersOpen(!filtersOpen)}
            className="btn-outline"
          >
            <Filter className="w-4 h-4 mr-2" />
            Filters
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
                <DialogTitle>Save Filter</DialogTitle>
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
                <Button onClick={saveFilter} className="w-full btn-primary" data-testid="save-filter-btn">
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
            className="btn-primary"
            data-testid="apply-filters-btn"
          >
            <Search className="w-4 h-4 mr-2" />
            Search
          </Button>
        </div>
      </div>

      <div className="grid lg:grid-cols-4 gap-6">
        {/* Filters Panel */}
        {filtersOpen && (
          <Card className="glass-card lg:col-span-1" data-testid="filters-panel">
            <CardHeader>
              <CardTitle className="text-lg">Filters</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Min ROI */}
              <div className="filter-group">
                <Label className="filter-label">Min ROI (%): {filters.minRoi}%</Label>
                <Slider
                  value={[filters.minRoi]}
                  onValueChange={([val]) => setFilters(f => ({ ...f, minRoi: val }))}
                  min={0}
                  max={10}
                  step={0.5}
                  className="mt-2"
                  data-testid="min-roi-slider"
                />
              </div>

              {/* Max DTE */}
              <div className="filter-group">
                <Label className="filter-label">Max DTE: {filters.maxDte} days</Label>
                <Slider
                  value={[filters.maxDte]}
                  onValueChange={([val]) => setFilters(f => ({ ...f, maxDte: val }))}
                  min={1}
                  max={90}
                  step={1}
                  className="mt-2"
                  data-testid="max-dte-slider"
                />
              </div>

              {/* Delta Range */}
              <div className="filter-group">
                <Label className="filter-label">Delta Range: {filters.minDelta} - {filters.maxDelta}</Label>
                <div className="flex gap-4 mt-2">
                  <div className="flex-1">
                    <span className="text-xs text-zinc-500">Min</span>
                    <Slider
                      value={[filters.minDelta]}
                      onValueChange={([val]) => setFilters(f => ({ ...f, minDelta: val }))}
                      min={0}
                      max={0.5}
                      step={0.05}
                      data-testid="min-delta-slider"
                    />
                  </div>
                  <div className="flex-1">
                    <span className="text-xs text-zinc-500">Max</span>
                    <Slider
                      value={[filters.maxDelta]}
                      onValueChange={([val]) => setFilters(f => ({ ...f, maxDelta: val }))}
                      min={0}
                      max={0.5}
                      step={0.05}
                      data-testid="max-delta-slider"
                    />
                  </div>
                </div>
              </div>

              {/* Min IV Rank */}
              <div className="filter-group">
                <Label className="filter-label">Min IV Rank: {filters.minIvRank}%</Label>
                <Slider
                  value={[filters.minIvRank]}
                  onValueChange={([val]) => setFilters(f => ({ ...f, minIvRank: val }))}
                  min={0}
                  max={100}
                  step={5}
                  className="mt-2"
                  data-testid="min-iv-rank-slider"
                />
              </div>

              {/* Saved Filters */}
              {savedFilters.length > 0 && (
                <div className="filter-group pt-4 border-t border-white/10">
                  <Label className="filter-label">Saved Filters</Label>
                  <div className="space-y-2 mt-2">
                    {savedFilters.map((filter) => (
                      <div
                        key={filter.id}
                        className="flex items-center justify-between p-2 rounded-lg bg-zinc-800/30 hover:bg-zinc-800/50"
                      >
                        <button
                          onClick={() => loadFilter(filter)}
                          className="text-sm text-zinc-300 hover:text-white"
                        >
                          {filter.name}
                        </button>
                        <button
                          onClick={() => deleteFilter(filter.id)}
                          className="text-zinc-500 hover:text-red-400"
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
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-lg">
              Results
              <Badge className="ml-2 badge-info">{opportunities.length}</Badge>
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
                      <SortHeader field="iv" label="IV" />
                      <SortHeader field="iv_rank" label="IV Rank" />
                      <SortHeader field="downside_protection" label="Protection" />
                      <SortHeader field="score" label="Score" />
                    </tr>
                  </thead>
                  <tbody>
                    {sortedOpportunities.map((opp, index) => (
                      <tr key={index} data-testid={`screener-row-${opp.symbol}`}>
                        <td className="font-semibold text-white">{opp.symbol}</td>
                        <td>${opp.stock_price?.toFixed(2)}</td>
                        <td>${opp.strike?.toFixed(2)}</td>
                        <td>{opp.expiry}</td>
                        <td>{opp.dte}d</td>
                        <td className="text-emerald-400">${opp.premium?.toFixed(2)}</td>
                        <td className="text-cyan-400">{opp.roi_pct?.toFixed(2)}%</td>
                        <td>{opp.delta?.toFixed(2)}</td>
                        <td>{(opp.iv * 100)?.toFixed(1)}%</td>
                        <td>{opp.iv_rank?.toFixed(0)}%</td>
                        <td>{opp.downside_protection?.toFixed(1)}%</td>
                        <td>
                          <Badge className={`${
                            opp.score >= 80 ? 'badge-success' :
                            opp.score >= 60 ? 'badge-warning' : 'badge-info'
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
