import { useState, useEffect, useRef } from 'react';
import { portfolioApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Wallet,
  Plus,
  Upload,
  RefreshCw,
  Trash2,
  Edit,
  TrendingUp,
  TrendingDown,
  DollarSign,
  BarChart3
} from 'lucide-react';
import { toast } from 'sonner';

const Portfolio = () => {
  const [positions, setPositions] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const fileInputRef = useRef(null);

  const [newPosition, setNewPosition] = useState({
    symbol: '',
    position_type: 'covered_call',
    shares: 100,
    avg_cost: 0,
    option_strike: null,
    option_expiry: '',
    option_premium: null,
    notes: ''
  });

  useEffect(() => {
    fetchPortfolioData();
  }, []);

  const fetchPortfolioData = async () => {
    setLoading(true);
    try {
      const [positionsRes, summaryRes] = await Promise.all([
        portfolioApi.getPositions(),
        portfolioApi.getSummary()
      ]);
      setPositions(positionsRes.data);
      setSummary(summaryRes.data);
    } catch (error) {
      console.error('Portfolio fetch error:', error);
      toast.error('Failed to load portfolio');
    } finally {
      setLoading(false);
    }
  };

  const addPosition = async () => {
    if (!newPosition.symbol) {
      toast.error('Please enter a symbol');
      return;
    }

    try {
      await portfolioApi.addPosition({
        ...newPosition,
        symbol: newPosition.symbol.toUpperCase()
      });
      toast.success('Position added');
      setAddDialogOpen(false);
      setNewPosition({
        symbol: '',
        position_type: 'covered_call',
        shares: 100,
        avg_cost: 0,
        option_strike: null,
        option_expiry: '',
        option_premium: null,
        notes: ''
      });
      fetchPortfolioData();
    } catch (error) {
      toast.error('Failed to add position');
    }
  };

  const deletePosition = async (positionId) => {
    if (!window.confirm('Are you sure you want to delete this position?')) return;

    try {
      await portfolioApi.deletePosition(positionId);
      toast.success('Position deleted');
      fetchPortfolioData();
    } catch (error) {
      toast.error('Failed to delete position');
    }
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      await portfolioApi.importCSV(file);
      toast.success('CSV imported successfully');
      fetchPortfolioData();
    } catch (error) {
      toast.error('Failed to import CSV');
    }
    
    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(value || 0);
  };

  const getPositionTypeLabel = (type) => {
    switch (type) {
      case 'covered_call': return 'Covered Call';
      case 'pmcc': return 'PMCC';
      case 'stock': return 'Stock';
      default: return type;
    }
  };

  return (
    <div className="space-y-6" data-testid="portfolio-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Wallet className="w-8 h-8 text-violet-500" />
            Portfolio
          </h1>
          <p className="text-zinc-400 mt-1">Track your positions and performance</p>
        </div>
        <div className="flex gap-3">
          <input
            type="file"
            ref={fileInputRef}
            accept=".csv"
            onChange={handleFileUpload}
            className="hidden"
          />
          <Button
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            className="btn-outline"
            data-testid="import-csv-btn"
          >
            <Upload className="w-4 h-4 mr-2" />
            Import CSV
          </Button>
          <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
            <DialogTrigger asChild>
              <Button className="btn-primary" data-testid="add-position-btn">
                <Plus className="w-4 h-4 mr-2" />
                Add Position
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-zinc-900 border-zinc-800 max-w-md">
              <DialogHeader>
                <DialogTitle>Add Position</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 pt-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>Symbol</Label>
                    <Input
                      value={newPosition.symbol}
                      onChange={(e) => setNewPosition(p => ({ ...p, symbol: e.target.value.toUpperCase() }))}
                      placeholder="AAPL"
                      className="input-dark mt-2"
                      data-testid="position-symbol-input"
                    />
                  </div>
                  <div>
                    <Label>Type</Label>
                    <Select
                      value={newPosition.position_type}
                      onValueChange={(value) => setNewPosition(p => ({ ...p, position_type: value }))}
                    >
                      <SelectTrigger className="input-dark mt-2" data-testid="position-type-select">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-zinc-900 border-zinc-800">
                        <SelectItem value="covered_call">Covered Call</SelectItem>
                        <SelectItem value="pmcc">PMCC</SelectItem>
                        <SelectItem value="stock">Stock Only</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>Shares</Label>
                    <Input
                      type="number"
                      value={newPosition.shares}
                      onChange={(e) => setNewPosition(p => ({ ...p, shares: parseInt(e.target.value) || 0 }))}
                      className="input-dark mt-2"
                      data-testid="position-shares-input"
                    />
                  </div>
                  <div>
                    <Label>Avg Cost</Label>
                    <Input
                      type="number"
                      step="0.01"
                      value={newPosition.avg_cost}
                      onChange={(e) => setNewPosition(p => ({ ...p, avg_cost: parseFloat(e.target.value) || 0 }))}
                      className="input-dark mt-2"
                      data-testid="position-avg-cost-input"
                    />
                  </div>
                </div>

                {newPosition.position_type !== 'stock' && (
                  <>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <Label>Option Strike</Label>
                        <Input
                          type="number"
                          step="0.5"
                          value={newPosition.option_strike || ''}
                          onChange={(e) => setNewPosition(p => ({ ...p, option_strike: parseFloat(e.target.value) || null }))}
                          className="input-dark mt-2"
                        />
                      </div>
                      <div>
                        <Label>Option Expiry</Label>
                        <Input
                          type="date"
                          value={newPosition.option_expiry}
                          onChange={(e) => setNewPosition(p => ({ ...p, option_expiry: e.target.value }))}
                          className="input-dark mt-2"
                        />
                      </div>
                    </div>
                    <div>
                      <Label>Premium Collected (per share)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        value={newPosition.option_premium || ''}
                        onChange={(e) => setNewPosition(p => ({ ...p, option_premium: parseFloat(e.target.value) || null }))}
                        className="input-dark mt-2"
                      />
                    </div>
                  </>
                )}

                <div>
                  <Label>Notes</Label>
                  <Textarea
                    value={newPosition.notes}
                    onChange={(e) => setNewPosition(p => ({ ...p, notes: e.target.value }))}
                    placeholder="Optional notes..."
                    className="input-dark mt-2"
                  />
                </div>

                <Button onClick={addPosition} className="w-full btn-primary" data-testid="save-position-btn">
                  Add Position
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {loading ? (
          Array(4).fill(0).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))
        ) : (
          <>
            <Card className="glass-card" data-testid="total-value-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-zinc-400 text-sm mb-2">
                  <DollarSign className="w-4 h-4" />
                  Total Value
                </div>
                <div className="text-2xl font-bold font-mono text-white">
                  {formatCurrency(summary?.total_value)}
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card" data-testid="total-cost-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-zinc-400 text-sm mb-2">
                  <BarChart3 className="w-4 h-4" />
                  Total Cost
                </div>
                <div className="text-2xl font-bold font-mono text-white">
                  {formatCurrency(summary?.total_cost)}
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card" data-testid="unrealized-pl-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-zinc-400 text-sm mb-2">
                  {(summary?.unrealized_pl || 0) >= 0 ? (
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  )}
                  Unrealized P/L
                </div>
                <div className={`text-2xl font-bold font-mono ${(summary?.unrealized_pl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatCurrency(summary?.unrealized_pl)}
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card" data-testid="premium-collected-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-zinc-400 text-sm mb-2">
                  <TrendingUp className="w-4 h-4 text-cyan-400" />
                  Premium Collected
                </div>
                <div className="text-2xl font-bold font-mono text-cyan-400">
                  {formatCurrency(summary?.total_premium_collected)}
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {/* Positions Table */}
      <Card className="glass-card" data-testid="positions-table">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-lg">
            Positions
            <Badge className="ml-2 badge-info">{positions.length}</Badge>
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchPortfolioData}
            className="text-zinc-400 hover:text-white"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array(5).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : positions.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">
              <Wallet className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No positions yet</p>
              <p className="text-sm mt-2">Add your first position or import from CSV</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Type</th>
                    <th>Shares</th>
                    <th>Avg Cost</th>
                    <th>Current</th>
                    <th>Strike</th>
                    <th>Expiry</th>
                    <th>Premium</th>
                    <th>P/L</th>
                    <th>P/L %</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos) => (
                    <tr key={pos.id} data-testid={`position-row-${pos.symbol}`}>
                      <td className="font-semibold text-white">{pos.symbol}</td>
                      <td>
                        <Badge className="badge-info text-xs">
                          {getPositionTypeLabel(pos.position_type)}
                        </Badge>
                      </td>
                      <td>{pos.shares}</td>
                      <td>{formatCurrency(pos.avg_cost)}</td>
                      <td>{formatCurrency(pos.current_price)}</td>
                      <td>{pos.option_strike ? formatCurrency(pos.option_strike) : '-'}</td>
                      <td>{pos.option_expiry || '-'}</td>
                      <td className="text-emerald-400">
                        {pos.option_premium ? formatCurrency(pos.option_premium) : '-'}
                      </td>
                      <td className={pos.unrealized_pl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        {formatCurrency(pos.unrealized_pl)}
                      </td>
                      <td className={pos.unrealized_pl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        {pos.unrealized_pl_pct?.toFixed(2)}%
                      </td>
                      <td>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => deletePosition(pos.id)}
                          className="text-zinc-500 hover:text-red-400"
                          data-testid={`delete-position-${pos.symbol}`}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
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
  );
};

export default Portfolio;
