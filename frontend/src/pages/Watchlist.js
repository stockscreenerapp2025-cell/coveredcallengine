import { useState, useEffect } from 'react';
import { watchlistApi } from '../lib/api';
import { Card, CardContent } from '../components/ui/card';
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
  DialogTrigger,
} from '../components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '../components/ui/alert-dialog';
import {
  BookmarkPlus,
  Plus,
  RefreshCw,
  Trash2,
  TrendingUp,
  TrendingDown,
  Star,
  Minus,
  AlertCircle
} from 'lucide-react';
import { toast } from 'sonner';

const Watchlist = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [newItem, setNewItem] = useState({
    symbol: '',
    notes: ''
  });

  useEffect(() => {
    fetchWatchlist();
  }, []);

  const fetchWatchlist = async () => {
    setLoading(true);
    try {
      const response = await watchlistApi.getAll();
      setItems(response.data);
    } catch (error) {
      console.error('Watchlist fetch error:', error);
      toast.error('Failed to load watchlist');
    } finally {
      setLoading(false);
    }
  };

  const addToWatchlist = async () => {
    if (!newItem.symbol) {
      toast.error('Please enter a symbol');
      return;
    }

    try {
      const response = await watchlistApi.add({
        symbol: newItem.symbol.toUpperCase(),
        notes: newItem.notes || null
      });
      toast.success(`${newItem.symbol.toUpperCase()} added at $${response.data.price_when_added?.toFixed(2) || 'N/A'}`);
      setAddDialogOpen(false);
      setNewItem({ symbol: '', notes: '' });
      fetchWatchlist();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to add to watchlist');
    }
  };

  const removeFromWatchlist = async (itemId, symbol) => {
    try {
      await watchlistApi.remove(itemId);
      toast.success(`${symbol} removed from watchlist`);
      fetchWatchlist();
    } catch (error) {
      toast.error('Failed to remove from watchlist');
    }
  };

  const clearAllWatchlist = async () => {
    try {
      await watchlistApi.clearAll();
      toast.success('Watchlist cleared');
      setItems([]);
    } catch (error) {
      toast.error('Failed to clear watchlist');
    }
  };

  const formatCurrency = (value) => {
    if (value === null || value === undefined || value === 0) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(value);
  };

  const formatPercent = (value) => {
    if (value === null || value === undefined) return '-';
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const formatDate = (isoDate) => {
    if (!isoDate) return '-';
    return new Date(isoDate).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  };

  const formatExpiry = (expiry) => {
    if (!expiry) return '-';
    // Convert 2025-01-17 to 17JAN25
    const date = new Date(expiry + 'T00:00:00');
    const day = date.getDate().toString().padStart(2, '0');
    const month = date.toLocaleString('en-US', { month: 'short' }).toUpperCase();
    const year = date.getFullYear().toString().slice(-2);
    return `${day}${month}${year}`;
  };

  const getAnalystColor = (rating) => {
    if (!rating) return 'text-zinc-500';
    const r = rating.toLowerCase();
    if (r.includes('strong buy')) return 'text-emerald-400';
    if (r.includes('buy')) return 'text-green-400';
    if (r.includes('hold')) return 'text-yellow-400';
    if (r.includes('sell')) return 'text-red-400';
    return 'text-zinc-400';
  };

  const getMovementIcon = (value) => {
    if (value > 0) return <TrendingUp className="w-4 h-4 text-emerald-400" />;
    if (value < 0) return <TrendingDown className="w-4 h-4 text-red-400" />;
    return <Minus className="w-4 h-4 text-zinc-500" />;
  };

  const getScoreColor = (score) => {
    if (!score) return 'bg-zinc-700 text-zinc-300';
    if (score >= 80) return 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
    if (score >= 60) return 'bg-green-500/20 text-green-400 border border-green-500/30';
    if (score >= 40) return 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30';
    return 'bg-zinc-700 text-zinc-300';
  };

  return (
    <div className="space-y-6" data-testid="watchlist-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <BookmarkPlus className="w-8 h-8 text-violet-500" />
            Watchlist
          </h1>
          <p className="text-zinc-400 mt-1">Track stocks and find covered call opportunities</p>
        </div>
        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={fetchWatchlist}
            className="btn-outline"
            data-testid="refresh-watchlist-btn"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          
          {items.length > 0 && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" className="btn-outline text-red-400 hover:text-red-300" data-testid="clear-all-btn">
                  <Trash2 className="w-4 h-4 mr-2" />
                  Clear All
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent className="bg-zinc-900 border-zinc-800">
                <AlertDialogHeader>
                  <AlertDialogTitle>Clear Watchlist?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will remove all {items.length} items from your watchlist. This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel className="bg-zinc-800 hover:bg-zinc-700 border-zinc-700">Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={clearAllWatchlist} className="bg-red-600 hover:bg-red-700">
                    Clear All
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
          
          <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
            <DialogTrigger asChild>
              <Button className="btn-primary" data-testid="add-watchlist-btn">
                <Plus className="w-4 h-4 mr-2" />
                Add Stock
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-zinc-900 border-zinc-800 max-w-md">
              <DialogHeader>
                <DialogTitle>Add to Watchlist</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 pt-4">
                <div>
                  <Label>Symbol</Label>
                  <Input
                    value={newItem.symbol}
                    onChange={(e) => setNewItem(p => ({ ...p, symbol: e.target.value.toUpperCase() }))}
                    placeholder="AAPL"
                    className="input-dark mt-2"
                    data-testid="watchlist-symbol-input"
                    onKeyDown={(e) => e.key === 'Enter' && addToWatchlist()}
                  />
                </div>
                <div>
                  <Label>Notes (optional)</Label>
                  <Input
                    value={newItem.notes}
                    onChange={(e) => setNewItem(p => ({ ...p, notes: e.target.value }))}
                    placeholder="Why I'm watching this..."
                    className="input-dark mt-2"
                  />
                </div>
                <Button onClick={addToWatchlist} className="w-full btn-primary" data-testid="save-watchlist-btn">
                  Add to Watchlist
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Watchlist Table */}
      <Card className="glass-card">
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 space-y-4">
              {Array(5).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-16 rounded-lg" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="py-16 text-center text-zinc-500">
              <Star className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p className="text-lg font-medium">Your watchlist is empty</p>
              <p className="text-sm mt-2">Add stocks to monitor for covered call opportunities</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-white/5 hover:bg-transparent">
                    <TableHead className="text-zinc-400 font-medium">Symbol</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-right">Price</TableHead>
                    <TableHead className="text-zinc-400 font-medium">Strike</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-center">Type</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-center">DTE</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-right">Premium</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-right">ROI</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-center">Delta</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-center">IV</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-center">AI Score</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-center">Analyst</TableHead>
                    <TableHead className="text-zinc-400 font-medium text-center">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => {
                    const opp = item.opportunity;
                    
                    return (
                      <TableRow 
                        key={item.id} 
                        className="border-white/5 hover:bg-white/5"
                        data-testid={`watchlist-row-${item.symbol}`}
                      >
                        {/* Symbol */}
                        <TableCell className="font-bold text-white">
                          <div className="flex flex-col">
                            <span className="text-lg">{item.symbol}</span>
                            <div className="flex items-center gap-2 text-xs">
                              <span className="text-zinc-500">
                                Added {formatDate(item.added_at)}
                              </span>
                              {item.price_when_added > 0 && item.movement_pct !== 0 && (
                                <span className={`flex items-center gap-1 ${
                                  item.movement_pct > 0 ? 'text-emerald-400' : 'text-red-400'
                                }`}>
                                  {getMovementIcon(item.movement_pct)}
                                  {formatPercent(item.movement_pct)}
                                </span>
                              )}
                            </div>
                          </div>
                        </TableCell>
                        
                        {/* Current Price */}
                        <TableCell className="text-right font-mono text-white font-medium">
                          {formatCurrency(item.current_price)}
                        </TableCell>
                        
                        {/* Strike */}
                        <TableCell>
                          {opp ? (
                            <span className="text-emerald-400 font-medium">
                              {formatExpiry(opp.expiry)} ${opp.strike}C
                            </span>
                          ) : (
                            <div className="flex items-center gap-1 text-zinc-500 text-sm">
                              <AlertCircle className="w-3 h-3" />
                              <span>No opportunities</span>
                            </div>
                          )}
                        </TableCell>
                        
                        {/* Type */}
                        <TableCell className="text-center">
                          {opp?.type ? (
                            <Badge 
                              variant="outline" 
                              className={`${opp.type === 'Weekly' ? 'border-cyan-500/50 text-cyan-400 bg-cyan-500/10' : 'border-violet-500/50 text-violet-400 bg-violet-500/10'}`}
                            >
                              {opp.type}
                            </Badge>
                          ) : (
                            <span className="text-zinc-600">-</span>
                          )}
                        </TableCell>
                        
                        {/* DTE */}
                        <TableCell className="text-center font-mono text-white">
                          {opp?.dte ? `${opp.dte}d` : '-'}
                        </TableCell>
                        
                        {/* Premium */}
                        <TableCell className="text-right font-mono text-emerald-400">
                          {opp?.premium ? `$${opp.premium.toFixed(2)}` : '-'}
                        </TableCell>
                        
                        {/* ROI */}
                        <TableCell className="text-right">
                          {opp?.roi_pct ? (
                            <span className="text-emerald-400 font-mono font-medium">
                              {opp.roi_pct.toFixed(2)}%
                            </span>
                          ) : (
                            <span className="text-zinc-600">-</span>
                          )}
                        </TableCell>
                        
                        {/* Delta */}
                        <TableCell className="text-center font-mono text-white">
                          {opp?.delta ? opp.delta.toFixed(2) : '-'}
                        </TableCell>
                        
                        {/* IV */}
                        <TableCell className="text-center font-mono text-white">
                          {opp?.iv ? `${opp.iv.toFixed(0)}%` : '-'}
                        </TableCell>
                        
                        {/* AI Score */}
                        <TableCell className="text-center">
                          {opp?.ai_score ? (
                            <Badge className={`font-mono ${getScoreColor(opp.ai_score)}`}>
                              {Math.round(opp.ai_score)}
                            </Badge>
                          ) : (
                            <span className="text-zinc-600">-</span>
                          )}
                        </TableCell>
                        
                        {/* Analyst Rating */}
                        <TableCell className="text-center">
                          {item.analyst_rating ? (
                            <Badge variant="outline" className={`${getAnalystColor(item.analyst_rating)} border-current`}>
                              {item.analyst_rating}
                            </Badge>
                          ) : (
                            <span className="text-zinc-600">-</span>
                          )}
                        </TableCell>
                        
                        {/* Delete Action */}
                        <TableCell className="text-center">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => removeFromWatchlist(item.id, item.symbol)}
                            className="text-zinc-500 hover:text-red-400 hover:bg-red-400/10"
                            data-testid={`delete-watchlist-${item.symbol}`}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Summary Stats */}
      {items.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card className="glass-card">
            <CardContent className="p-4">
              <p className="text-zinc-400 text-sm">Total Symbols</p>
              <p className="text-2xl font-bold text-white">{items.length}</p>
            </CardContent>
          </Card>
          <Card className="glass-card">
            <CardContent className="p-4">
              <p className="text-zinc-400 text-sm">With Opportunities</p>
              <p className="text-2xl font-bold text-emerald-400">
                {items.filter(i => i.opportunity).length}
              </p>
            </CardContent>
          </Card>
          <Card className="glass-card">
            <CardContent className="p-4">
              <p className="text-zinc-400 text-sm">Gainers</p>
              <p className="text-2xl font-bold text-emerald-400">
                {items.filter(i => i.movement_pct > 0).length}
              </p>
            </CardContent>
          </Card>
          <Card className="glass-card">
            <CardContent className="p-4">
              <p className="text-zinc-400 text-sm">Losers</p>
              <p className="text-2xl font-bold text-red-400">
                {items.filter(i => i.movement_pct < 0).length}
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
};

export default Watchlist;
