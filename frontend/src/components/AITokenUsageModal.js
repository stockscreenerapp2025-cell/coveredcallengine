import { useState } from 'react';
import api from '../lib/api';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from './ui/dialog';
import { Button } from './ui/button';
import {
  Sparkles,
  Coins,
  AlertTriangle,
  Loader2
} from 'lucide-react';

/**
 * AITokenUsageModal - Confirmation dialog before AI action execution
 * 
 * Usage:
 *   const [showConfirm, setShowConfirm] = useState(false);
 *   const [estimate, setEstimate] = useState(null);
 *   
 *   // Before AI action:
 *   const est = await api.post('/ai-wallet/estimate', { action: 'ai_analysis' });
 *   setEstimate(est.data);
 *   setShowConfirm(true);
 *   
 *   // In render:
 *   <AITokenUsageModal
 *     open={showConfirm}
 *     onClose={() => setShowConfirm(false)}
 *     onConfirm={executeAIAction}
 *     estimate={estimate}
 *     actionDescription="Analyze this trade"
 *   />
 */
const AITokenUsageModal = ({ 
  open, 
  onClose, 
  onConfirm, 
  estimate,
  actionDescription = "Execute AI action",
  loading = false
}) => {
  const isInsufficientTokens = estimate && !estimate.sufficient_tokens;

  const handleConfirm = () => {
    if (isInsufficientTokens) {
      // Redirect to buy tokens
      window.location.href = '/ai-wallet';
      return;
    }
    onConfirm?.();
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md bg-zinc-900 border-zinc-800" data-testid="token-usage-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-amber-400" />
            Confirm AI Action
          </DialogTitle>
          <DialogDescription>
            This action will use AI tokens from your wallet
          </DialogDescription>
        </DialogHeader>

        <div className="py-4 space-y-4">
          {/* Action Description */}
          <div className="bg-zinc-800/50 rounded-lg p-4 border border-zinc-700">
            <p className="text-zinc-300">{actionDescription}</p>
          </div>

          {/* Token Cost */}
          {estimate && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-zinc-400">Token Cost</span>
                <span className="text-white font-medium flex items-center gap-1">
                  <Coins className="w-4 h-4 text-amber-400" />
                  {estimate.estimated_tokens?.toLocaleString()}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-zinc-400">Current Balance</span>
                <span className={`font-medium ${
                  isInsufficientTokens ? 'text-red-400' : 'text-emerald-400'
                }`}>
                  {estimate.current_balance?.toLocaleString()} tokens
                </span>
              </div>

              {isInsufficientTokens && (
                <div className="flex items-center justify-between pt-2 border-t border-zinc-700">
                  <span className="text-zinc-400">After Action</span>
                  <span className="text-red-400 font-medium">
                    Insufficient tokens
                  </span>
                </div>
              )}

              {!isInsufficientTokens && (
                <div className="flex items-center justify-between pt-2 border-t border-zinc-700">
                  <span className="text-zinc-400">After Action</span>
                  <span className="text-zinc-300">
                    {(estimate.current_balance - estimate.estimated_tokens).toLocaleString()} tokens
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Insufficient Tokens Warning */}
          {isInsufficientTokens && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 flex items-start gap-2">
              <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-red-400 font-medium">Insufficient Tokens</p>
                <p className="text-zinc-400 text-sm">
                  You need {estimate?.estimated_tokens?.toLocaleString()} tokens but only have {estimate?.current_balance?.toLocaleString()}.
                  Purchase more tokens to continue.
                </p>
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            onClick={onClose}
            className="border-zinc-700 hover:bg-zinc-800"
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={loading}
            className={isInsufficientTokens 
              ? "bg-amber-600 hover:bg-amber-700" 
              : "bg-emerald-600 hover:bg-emerald-700"
            }
            data-testid="confirm-ai-action-btn"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Processing...
              </>
            ) : isInsufficientTokens ? (
              <>
                <Coins className="w-4 h-4 mr-2" />
                Buy Tokens
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4 mr-2" />
                Confirm ({estimate?.estimated_tokens} tokens)
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default AITokenUsageModal;
