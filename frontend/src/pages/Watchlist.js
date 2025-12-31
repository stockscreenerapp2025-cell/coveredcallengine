import { useState, useEffect } from 'react';
import { watchlistApi, stocksApi } from '../lib/api';
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
  DialogTrigger,
} from '../components/ui/dialog';
import {
  BookmarkPlus,
  Plus,
  RefreshCw,
  Trash2,
  TrendingUp,
  TrendingDown,
  Star,
  Target
} from 'lucide-react';
import { toast } from 'sonner';

const Watchlist = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [newItem, setNewItem] = useState({
    symbol: '',
    target_price: '',
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
      await watchlistApi.add({
        symbol: newItem.symbol.toUpperCase(),
        target_price: newItem.target_price ? parseFloat(newItem.target_price) : null,
        notes: newItem.notes || null
      });
      toast.success(`${newItem.symbol.toUpperCase()} added to watchlist`);
      setAddDialogOpen(false);
      setNewItem({ symbol: '', target_price: '', notes: '' });
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

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(value || 0);
  };

  const getDistanceToTarget = (current, target) => {
    if (!target) return null;
    const distance = ((target - current) / current) * 100;
    return distance;
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
          <p className="text-zinc-400 mt-1">Monitor stocks for covered call opportunities</p>
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
                  />
                </div>
                <div>
                  <Label>Target Price (optional)</Label>
                  <Input
                    type="number"
                    step="0.01"
                    value={newItem.target_price}
                    onChange={(e) => setNewItem(p => ({ ...p, target_price: e.target.value }))}
                    placeholder="150.00"
                    className="input-dark mt-2"
                    data-testid="watchlist-target-input"
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

      {/* Watchlist Grid */}
      {loading ? (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array(6).fill(0).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card className="glass-card">
          <CardContent className="py-16 text-center text-zinc-500">
            <Star className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p className="text-lg font-medium">Your watchlist is empty</p>
            <p className="text-sm mt-2">Add stocks to monitor for covered call opportunities</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((item) => {
            const distanceToTarget = getDistanceToTarget(item.current_price, item.target_price);
            
            return (
              <Card 
                key={item.id} 
                className="glass-card card-hover"
                data-testid={`watchlist-card-${item.symbol}`}
              >
                <CardContent className="p-5">
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <h3 className="text-xl font-bold text-white">{item.symbol}</h3>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-2xl font-mono text-white">
                          {formatCurrency(item.current_price)}
                        </span>
                        {item.change >= 0 ? (
                          <TrendingUp className="w-4 h-4 text-emerald-400" />
                        ) : (
                          <TrendingDown className="w-4 h-4 text-red-400" />
                        )}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => removeFromWatchlist(item.id, item.symbol)}
                      className="text-zinc-500 hover:text-red-400"
                      data-testid={`remove-watchlist-${item.symbol}`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>

                  <div className="space-y-3">
                    {/* Daily Change */}
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-zinc-500">Today</span>
                      <span className={`font-mono ${item.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {item.change >= 0 ? '+' : ''}{item.change?.toFixed(2)} ({item.change_pct >= 0 ? '+' : ''}{item.change_pct?.toFixed(2)}%)
                      </span>
                    </div>

                    {/* Target Price */}
                    {item.target_price && (
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-zinc-500 flex items-center gap-1">
                          <Target className="w-3 h-3" />
                          Target
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-white">{formatCurrency(item.target_price)}</span>
                          <Badge className={`text-xs ${
                            distanceToTarget >= 0 ? 'badge-success' : 'badge-danger'
                          }`}>
                            {distanceToTarget >= 0 ? '+' : ''}{distanceToTarget?.toFixed(1)}%
                          </Badge>
                        </div>
                      </div>
                    )}

                    {/* Notes */}
                    {item.notes && (
                      <div className="pt-2 border-t border-white/5">
                        <p className="text-xs text-zinc-500 line-clamp-2">{item.notes}</p>
                      </div>
                    )}
                  </div>

                  {/* Added date */}
                  <div className="mt-4 pt-3 border-t border-white/5">
                    <span className="text-xs text-zinc-600">
                      Added {new Date(item.added_at).toLocaleDateString()}
                    </span>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default Watchlist;
