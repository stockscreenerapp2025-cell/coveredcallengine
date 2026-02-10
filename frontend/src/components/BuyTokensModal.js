import { useState, useEffect } from 'react';
import api from '../lib/api';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from './ui/dialog';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Card, CardContent } from './ui/card';
import {
  Coins,
  ShoppingCart,
  Check,
  ExternalLink,
  Sparkles,
  Loader2
} from 'lucide-react';
import { toast } from 'sonner';

const BuyTokensModal = ({ open, onClose, onPurchaseComplete }) => {
  const [packs, setPacks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState(null);

  useEffect(() => {
    if (open) {
      fetchPacks();
    }
  }, [open]);

  const fetchPacks = async () => {
    try {
      const response = await api.get('/ai-wallet/packs');
      setPacks(response.data.packs || []);
    } catch (error) {
      console.error('Failed to fetch packs:', error);
      toast.error('Failed to load token packs');
    } finally {
      setLoading(false);
    }
  };

  const handlePurchase = async (packId) => {
    setPurchasing(packId);
    
    try {
      const response = await api.post('/ai-wallet/purchase/create', {
        pack_id: packId
      });
      
      const { approval_url, purchase_id } = response.data;
      
      if (approval_url) {
        toast.success('Redirecting to PayPal...');
        // Store purchase ID for tracking
        localStorage.setItem('pending_purchase', purchase_id);
        // Redirect to PayPal
        window.location.href = approval_url;
      } else {
        toast.error('Failed to create purchase');
      }
    } catch (error) {
      console.error('Purchase failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to create purchase');
    } finally {
      setPurchasing(null);
    }
  };

  const getPackColor = (packId) => {
    const colors = {
      starter: {
        bg: 'bg-emerald-500/10',
        border: 'border-emerald-500/30',
        text: 'text-emerald-400',
        badge: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
      },
      power: {
        bg: 'bg-violet-500/10',
        border: 'border-violet-500/30',
        text: 'text-violet-400',
        badge: 'bg-violet-500/20 text-violet-400 border-violet-500/30'
      },
      pro: {
        bg: 'bg-amber-500/10',
        border: 'border-amber-500/30',
        text: 'text-amber-400',
        badge: 'bg-amber-500/20 text-amber-400 border-amber-500/30'
      }
    };
    return colors[packId] || colors.starter;
  };

  const getValueBadge = (packId) => {
    if (packId === 'pro') return 'Best Value';
    if (packId === 'power') return 'Popular';
    return null;
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-2xl bg-zinc-900 border-zinc-800" data-testid="buy-tokens-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl">
            <ShoppingCart className="w-5 h-5 text-amber-400" />
            Buy AI Tokens
          </DialogTitle>
          <DialogDescription>
            Purchase token packs to use AI features. Paid tokens never expire.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-zinc-500" />
          </div>
        ) : (
          <div className="grid md:grid-cols-3 gap-4 py-4">
            {packs.map((pack) => {
              const colors = getPackColor(pack.id);
              const valueBadge = getValueBadge(pack.id);
              const pricePerToken = ((pack.price_usd / pack.tokens) * 1000).toFixed(2);
              
              return (
                <Card
                  key={pack.id}
                  className={`relative overflow-hidden transition-all duration-200 hover:scale-[1.02] ${colors.border} border`}
                  data-testid={`pack-card-${pack.id}`}
                >
                  {valueBadge && (
                    <div className={`absolute top-0 right-0 px-2 py-0.5 text-xs font-medium ${colors.badge} rounded-bl`}>
                      {valueBadge}
                    </div>
                  )}
                  
                  <CardContent className="p-4 space-y-4">
                    {/* Pack Header */}
                    <div className="text-center">
                      <div className={`w-12 h-12 mx-auto rounded-xl ${colors.bg} flex items-center justify-center mb-3`}>
                        <Coins className={`w-6 h-6 ${colors.text}`} />
                      </div>
                      <h3 className="text-lg font-bold text-white">{pack.name}</h3>
                      <p className="text-zinc-400 text-sm">{pack.description}</p>
                    </div>

                    {/* Token Amount */}
                    <div className="text-center py-2">
                      <div className="flex items-baseline justify-center gap-1">
                        <span className={`text-3xl font-bold ${colors.text}`}>
                          {pack.tokens.toLocaleString()}
                        </span>
                      </div>
                      <p className="text-zinc-500 text-xs mt-1">
                        ${pricePerToken} per 1,000 tokens
                      </p>
                    </div>

                    {/* Price */}
                    <div className="text-center py-2 border-t border-zinc-800">
                      <div className="flex items-baseline justify-center">
                        <span className="text-lg text-zinc-500">$</span>
                        <span className="text-3xl font-bold text-white">
                          {pack.price_usd}
                        </span>
                      </div>
                      <p className="text-zinc-500 text-xs">USD • One-time</p>
                    </div>

                    {/* Features */}
                    <ul className="space-y-2 text-sm">
                      <li className="flex items-center gap-2 text-zinc-300">
                        <Check className={`w-4 h-4 ${colors.text}`} />
                        Never expires
                      </li>
                      <li className="flex items-center gap-2 text-zinc-300">
                        <Check className={`w-4 h-4 ${colors.text}`} />
                        Instant delivery
                      </li>
                      <li className="flex items-center gap-2 text-zinc-300">
                        <Check className={`w-4 h-4 ${colors.text}`} />
                        All AI features
                      </li>
                    </ul>

                    {/* Buy Button */}
                    <Button
                      onClick={() => handlePurchase(pack.id)}
                      disabled={purchasing === pack.id}
                      className={`w-full ${
                        pack.id === 'pro' ? 'bg-amber-600 hover:bg-amber-700' :
                        pack.id === 'power' ? 'bg-violet-600 hover:bg-violet-700' :
                        'bg-emerald-600 hover:bg-emerald-700'
                      }`}
                      data-testid={`buy-btn-${pack.id}`}
                    >
                      {purchasing === pack.id ? (
                        <>
                          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                          Processing...
                        </>
                      ) : (
                        <>
                          Buy Now
                          <ExternalLink className="w-4 h-4 ml-2" />
                        </>
                      )}
                    </Button>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}

        {/* Info */}
        <div className="pt-4 border-t border-zinc-800">
          <p className="text-zinc-500 text-xs text-center flex items-center justify-center gap-1">
            <Sparkles className="w-3 h-3" />
            Secure payment via PayPal. Tokens credited instantly after payment.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default BuyTokensModal;
