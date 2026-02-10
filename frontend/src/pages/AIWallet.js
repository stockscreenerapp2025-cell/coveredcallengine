import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Progress } from '../components/ui/progress';
import {
  Coins,
  Sparkles,
  Clock,
  TrendingUp,
  ShoppingCart,
  History,
  RefreshCw,
  Zap,
  AlertCircle,
  CheckCircle2,
  ChevronRight
} from 'lucide-react';
import { toast } from 'sonner';
import BuyTokensModal from '../components/BuyTokensModal';
import AIUsageHistoryModal from '../components/AIUsageHistoryModal';

const AIWallet = () => {
  const [searchParams] = useSearchParams();
  const [wallet, setWallet] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showBuyModal, setShowBuyModal] = useState(false);
  const [showHistoryModal, setShowHistoryModal] = useState(false);

  const fetchWallet = useCallback(async () => {
    try {
      const response = await api.get('/ai-wallet');
      setWallet(response.data);
    } catch (error) {
      console.error('Failed to fetch wallet:', error);
      toast.error('Failed to load wallet');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWallet();
    
    // Check for purchase result from URL params
    const purchaseStatus = searchParams.get('purchase');
    if (purchaseStatus === 'success') {
      toast.success('Purchase successful! Tokens will be credited shortly.');
      // Clear the URL params
      window.history.replaceState({}, '', '/ai-wallet');
    } else if (purchaseStatus === 'cancelled') {
      toast.info('Purchase cancelled');
      window.history.replaceState({}, '', '/ai-wallet');
    }
  }, [fetchWallet, searchParams]);

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  };

  const getUsagePercentage = () => {
    if (!wallet) return 0;
    const totalGrant = wallet.plan_grant || 1;
    return Math.min(100, (wallet.monthly_used / totalGrant) * 100);
  };

  const getTokenPercentage = () => {
    if (!wallet) return 100;
    const totalGrant = wallet.plan_grant || 1;
    return Math.min(100, (wallet.free_tokens_remaining / totalGrant) * 100);
  };

  const isLowBalance = () => {
    if (!wallet) return false;
    return wallet.total_tokens < wallet.plan_grant * 0.2;
  };

  if (loading) {
    return (
      <div className="space-y-6" data-testid="ai-wallet-page">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-zinc-800 rounded w-48"></div>
          <div className="h-48 bg-zinc-800 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="ai-wallet-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Coins className="w-6 h-6 text-amber-400" />
            AI Wallet
          </h1>
          <p className="text-zinc-400 text-sm mt-1">
            Manage your AI tokens and usage
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchWallet}
            className="border-zinc-700 hover:bg-zinc-800"
            data-testid="refresh-wallet-btn"
          >
            <RefreshCw className="w-4 h-4 mr-1" />
            Refresh
          </Button>
          <Button
            onClick={() => setShowBuyModal(true)}
            className="bg-amber-600 hover:bg-amber-700"
            data-testid="buy-tokens-btn"
          >
            <ShoppingCart className="w-4 h-4 mr-1" />
            Buy Tokens
          </Button>
        </div>
      </div>

      {/* Low Balance Alert */}
      {isLowBalance() && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0" />
          <div className="flex-1">
            <p className="text-amber-400 font-medium">Low Token Balance</p>
            <p className="text-zinc-400 text-sm">
              You have less than 20% of your monthly tokens remaining. Consider purchasing more to continue using AI features.
            </p>
          </div>
          <Button
            size="sm"
            onClick={() => setShowBuyModal(true)}
            className="bg-amber-600 hover:bg-amber-700"
          >
            Buy Now
          </Button>
        </div>
      )}

      {/* Main Balance Card */}
      <div className="grid md:grid-cols-3 gap-6">
        {/* Total Balance */}
        <Card className="glass-card col-span-2" data-testid="balance-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-lg flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-amber-400" />
              Token Balance
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Big Number */}
            <div className="text-center py-4">
              <div className="text-5xl font-bold text-white">
                {wallet?.total_tokens?.toLocaleString() || 0}
              </div>
              <p className="text-zinc-400 mt-1">Total Available Tokens</p>
            </div>

            {/* Balance Breakdown */}
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-emerald-500/10 rounded-lg p-4 border border-emerald-500/20">
                <div className="flex items-center gap-2 text-emerald-400 text-sm mb-2">
                  <Clock className="w-4 h-4" />
                  Free Tokens
                </div>
                <div className="text-2xl font-bold text-white">
                  {wallet?.free_tokens_remaining?.toLocaleString() || 0}
                </div>
                <p className="text-xs text-zinc-500 mt-1">Expires on reset</p>
              </div>

              <div className="bg-amber-500/10 rounded-lg p-4 border border-amber-500/20">
                <div className="flex items-center gap-2 text-amber-400 text-sm mb-2">
                  <Coins className="w-4 h-4" />
                  Paid Tokens
                </div>
                <div className="text-2xl font-bold text-white">
                  {wallet?.paid_tokens_remaining?.toLocaleString() || 0}
                </div>
                <p className="text-xs text-zinc-500 mt-1">Never expires</p>
              </div>
            </div>

            {/* Usage Progress */}
            <div>
              <div className="flex justify-between text-sm mb-2">
                <span className="text-zinc-400">Monthly Usage</span>
                <span className="text-white">
                  {wallet?.monthly_used?.toLocaleString() || 0} / {wallet?.plan_grant?.toLocaleString() || 0}
                </span>
              </div>
              <Progress 
                value={getUsagePercentage()} 
                className="h-2 bg-zinc-800"
              />
            </div>
          </CardContent>
        </Card>

        {/* Plan Info */}
        <Card className="glass-card" data-testid="plan-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-lg flex items-center gap-2">
              <Zap className="w-5 h-5 text-violet-400" />
              Your Plan
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-center py-4">
              <Badge className={`text-lg px-4 py-1 ${
                wallet?.plan === 'premium' ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
                wallet?.plan === 'standard' ? 'bg-violet-500/20 text-violet-400 border-violet-500/30' :
                'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
              }`}>
                {wallet?.plan?.charAt(0).toUpperCase() + wallet?.plan?.slice(1) || 'Basic'}
              </Badge>
            </div>

            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-zinc-400">Monthly Grant</span>
                <span className="text-white font-medium">
                  {wallet?.plan_grant?.toLocaleString()} tokens
                </span>
              </div>

              <div className="flex justify-between text-sm">
                <span className="text-zinc-400">Next Reset</span>
                <span className="text-white font-medium">
                  {formatDate(wallet?.next_reset)}
                </span>
              </div>

              <div className="flex justify-between text-sm">
                <span className="text-zinc-400">AI Features</span>
                <span className={wallet?.ai_enabled ? 'text-emerald-400' : 'text-red-400'}>
                  {wallet?.ai_enabled ? (
                    <span className="flex items-center gap-1">
                      <CheckCircle2 className="w-4 h-4" /> Enabled
                    </span>
                  ) : (
                    <span className="flex items-center gap-1">
                      <AlertCircle className="w-4 h-4" /> Disabled
                    </span>
                  )}
                </span>
              </div>
            </div>

            {/* Free Token Progress */}
            <div className="pt-4 border-t border-zinc-800">
              <div className="flex justify-between text-sm mb-2">
                <span className="text-zinc-400">Free Tokens Remaining</span>
                <span className="text-emerald-400">{getTokenPercentage().toFixed(0)}%</span>
              </div>
              <Progress 
                value={getTokenPercentage()} 
                className="h-2 bg-zinc-800"
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <div className="grid md:grid-cols-2 gap-4">
        <Card 
          className="glass-card hover:bg-zinc-800/50 cursor-pointer transition-colors"
          onClick={() => setShowBuyModal(true)}
          data-testid="quick-buy-card"
        >
          <CardContent className="p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-amber-500/20 flex items-center justify-center">
                <ShoppingCart className="w-5 h-5 text-amber-400" />
              </div>
              <div>
                <p className="text-white font-medium">Buy More Tokens</p>
                <p className="text-zinc-400 text-sm">Packs starting at $10</p>
              </div>
            </div>
            <ChevronRight className="w-5 h-5 text-zinc-500" />
          </CardContent>
        </Card>

        <Card 
          className="glass-card hover:bg-zinc-800/50 cursor-pointer transition-colors"
          onClick={() => setShowHistoryModal(true)}
          data-testid="quick-history-card"
        >
          <CardContent className="p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-violet-500/20 flex items-center justify-center">
                <History className="w-5 h-5 text-violet-400" />
              </div>
              <div>
                <p className="text-white font-medium">Usage History</p>
                <p className="text-zinc-400 text-sm">View all transactions</p>
              </div>
            </div>
            <ChevronRight className="w-5 h-5 text-zinc-500" />
          </CardContent>
        </Card>
      </div>

      {/* Info Section */}
      <Card className="glass-card">
        <CardContent className="p-4">
          <p className="text-zinc-400 text-sm text-center">
            <Sparkles className="w-4 h-4 inline mr-1 text-amber-400" />
            All plans include free monthly AI credits. Use AI only if you want. Buy more credits anytime — no surprises.
          </p>
        </CardContent>
      </Card>

      {/* Modals */}
      <BuyTokensModal 
        open={showBuyModal} 
        onClose={() => setShowBuyModal(false)}
        onPurchaseComplete={fetchWallet}
      />
      
      <AIUsageHistoryModal
        open={showHistoryModal}
        onClose={() => setShowHistoryModal(false)}
      />
    </div>
  );
};

export default AIWallet;
