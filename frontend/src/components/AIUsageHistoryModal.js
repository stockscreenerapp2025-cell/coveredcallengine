import { useState, useEffect } from 'react';
import api from '../lib/api';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from './ui/dialog';
import { Badge } from './ui/badge';
import { ScrollArea } from './ui/scroll-area';
import {
  History,
  ArrowDownLeft,
  ArrowUpRight,
  RefreshCw,
  Gift,
  ShoppingCart,
  Loader2,
  Clock
} from 'lucide-react';

const AIUsageHistoryModal = ({ open, onClose }) => {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (open) {
      fetchHistory();
    }
  }, [open]);

  const fetchHistory = async () => {
    try {
      const response = await api.get('/ai-wallet/ledger?limit=100');
      const raw = response.data.entries || [];

      // Collapse usage+reversal pairs into a single "Failed" row.
      // A reversal is a system refund — pairing it with its usage avoids
      // confusing duplicate entries in the history.
      const collapsed = [];
      const reversedIds = new Set();

      raw.forEach((entry, i) => {
        if (reversedIds.has(i)) return; // already consumed as part of a pair
        if (entry.source === 'reversal') return; // lone reversal — skip

        if (entry.source === 'usage') {
          // Look ahead for a matching reversal (same action, within next 3 entries)
          const matchIdx = raw.findIndex(
            (r, j) => j > i && j <= i + 3 &&
              r.source === 'reversal' && r.action === entry.action
          );
          if (matchIdx !== -1) {
            reversedIds.add(matchIdx);
            collapsed.push({ ...entry, _failed: true });
            return;
          }
        }
        collapsed.push(entry);
      });

      setEntries(collapsed);
    } catch (error) {
      console.error('Failed to fetch history:', error);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getSourceIcon = (source) => {
    switch (source) {
      case 'usage':
        return <ArrowUpRight className="w-4 h-4 text-red-400" />;
      case 'purchase':
        return <ShoppingCart className="w-4 h-4 text-amber-400" />;
      case 'grant':
        return <Gift className="w-4 h-4 text-emerald-400" />;
      case 'reversal':
        return <RefreshCw className="w-4 h-4 text-blue-400" />;
      case 'expiry':
        return <Clock className="w-4 h-4 text-zinc-400" />;
      default:
        return <History className="w-4 h-4 text-zinc-400" />;
    }
  };

  const getSourceLabel = (source) => {
    const labels = {
      usage: 'AI Usage',
      purchase: 'Purchase',
      grant: 'Monthly Grant',
      reversal: 'Refund',
      expiry: 'Expired'
    };
    return labels[source] || source;
  };

  const getSourceBadge = (source) => {
    const styles = {
      usage: 'bg-red-500/20 text-red-400 border-red-500/30',
      purchase: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
      grant: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
      reversal: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
      expiry: 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'
    };
    return styles[source] || styles.usage;
  };

  const formatAction = (action) => {
    // Convert action names to readable format
    return action
      .replace(/_/g, ' ')
      .toLowerCase()
      .replace(/\b\w/g, c => c.toUpperCase());
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-lg bg-zinc-900 border-zinc-800" data-testid="usage-history-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="w-5 h-5 text-violet-400" />
            Usage History
          </DialogTitle>
          <DialogDescription>
            View your AI token transactions and usage
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-zinc-500" />
          </div>
        ) : entries.length === 0 ? (
          <div className="text-center py-8">
            <History className="w-12 h-12 mx-auto text-zinc-600 mb-3" />
            <p className="text-zinc-400">No transactions yet</p>
            <p className="text-zinc-500 text-sm">Your AI usage will appear here</p>
          </div>
        ) : (
          <ScrollArea className="h-[400px] pr-4">
            <div className="space-y-2">
              {entries.map((entry, index) => (
                <div
                  key={index}
                  className={`flex items-center gap-3 p-3 rounded-lg border transition-colors ${
                    entry._failed
                      ? 'bg-zinc-800/30 border-zinc-700/50 opacity-60'
                      : 'bg-zinc-800/50 border-zinc-800 hover:border-zinc-700'
                  }`}
                  data-testid={`history-entry-${index}`}
                >
                  {/* Icon */}
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                    entry._failed ? 'bg-zinc-700' :
                    entry.source === 'usage' ? 'bg-red-500/20' :
                    entry.source === 'purchase' ? 'bg-amber-500/20' :
                    entry.source === 'grant' ? 'bg-emerald-500/20' :
                    'bg-zinc-700'
                  }`}>
                    {getSourceIcon(entry.source)}
                  </div>

                  {/* Details */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-medium truncate ${entry._failed ? 'text-zinc-400' : 'text-white'}`}>
                        {formatAction(entry.action)}
                      </span>
                      {entry._failed
                        ? <Badge className="text-xs bg-zinc-700 text-zinc-400 border-zinc-600">Failed — No Charge</Badge>
                        : <Badge className={`text-xs ${getSourceBadge(entry.source)}`}>{getSourceLabel(entry.source)}</Badge>
                      }
                    </div>
                    <p className="text-zinc-500 text-xs">
                      {formatDate(entry.timestamp)}
                    </p>
                  </div>

                  {/* Token Amount */}
                  <div className="text-right">
                    {entry._failed ? (
                      <div className="font-medium text-zinc-500">±0</div>
                    ) : (
                      <>
                        <div className={`font-medium ${
                          entry.tokens_total > 0 ? 'text-emerald-400' : 'text-red-400'
                        }`}>
                          {entry.tokens_total > 0 ? '+' : ''}{entry.tokens_total.toLocaleString()}
                        </div>
                        {(entry.free_tokens !== 0 || entry.paid_tokens !== 0) && (
                          <p className="text-zinc-500 text-xs">
                            {entry.free_tokens !== 0 && `Free: ${entry.free_tokens}`}
                            {entry.free_tokens !== 0 && entry.paid_tokens !== 0 && ' / '}
                            {entry.paid_tokens !== 0 && `Paid: ${entry.paid_tokens}`}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default AIUsageHistoryModal;
