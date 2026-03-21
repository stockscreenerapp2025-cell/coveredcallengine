import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../lib/api';
import { toast } from 'sonner';
import { User, CreditCard, ShieldCheck, AlertTriangle, CheckCircle } from 'lucide-react';

const PLAN_LABELS = {
  basic: 'Basic',
  standard: 'Standard',
  premium: 'Premium',
};

const STATUS_COLORS = {
  active:    'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  trialing:  'bg-blue-500/20 text-blue-400 border-blue-500/30',
  cancelled: 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
  past_due:  'bg-red-500/20 text-red-400 border-red-500/30',
  expired:   'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
};

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  } catch {
    return iso;
  }
}

export default function AccountSettings() {
  const { user, refreshUser } = useAuth();
  const sub = user?.subscription || {};
  const [showConfirm, setShowConfirm] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [accessUntil, setAccessUntil] = useState(null);

  const status = sub.status || 'none';
  const planLabel = PLAN_LABELS[sub.plan_name] || PLAN_LABELS[sub.plan] || sub.plan_name || sub.plan || 'Free';
  const billingCycle = sub.billing_cycle === 'yearly' ? 'Yearly' : sub.billing_cycle === 'monthly' ? 'Monthly' : '—';
  const nextBilling = sub.current_period_end || sub.next_billing_date || sub.trial_end;
  const canCancel = ['active', 'trialing'].includes(status) && !cancelled;

  const handleCancel = async () => {
    setCancelling(true);
    try {
      const res = await api.post('/auth/me/cancel-subscription');
      setCancelled(true);
      setAccessUntil(res.data.access_until);
      setShowConfirm(false);
      toast.success('Subscription cancelled. You keep access until your billing period ends.');
      if (refreshUser) refreshUser();
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Failed to cancel. Please contact support.';
      toast.error(msg);
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <User className="w-6 h-6 text-violet-400" />
          Account Settings
        </h1>
        <p className="text-zinc-400 mt-1 text-sm">Manage your profile and subscription</p>
      </div>

      {/* Profile Card */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
        <h2 className="text-white font-semibold flex items-center gap-2">
          <User className="w-4 h-4 text-zinc-400" /> Profile
        </h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-zinc-500">Name</p>
            <p className="text-white font-medium">{user?.name || '—'}</p>
          </div>
          <div>
            <p className="text-zinc-500">Email</p>
            <p className="text-white font-medium">{user?.email || '—'}</p>
          </div>
          <div>
            <p className="text-zinc-500">Member since</p>
            <p className="text-white font-medium">{formatDate(user?.created_at)}</p>
          </div>
        </div>
      </div>

      {/* Subscription Card */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
        <h2 className="text-white font-semibold flex items-center gap-2">
          <CreditCard className="w-4 h-4 text-zinc-400" /> Subscription
        </h2>

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-zinc-500">Plan</p>
            <p className="text-white font-medium">{planLabel}</p>
          </div>
          <div>
            <p className="text-zinc-500">Billing</p>
            <p className="text-white font-medium">{billingCycle}</p>
          </div>
          <div>
            <p className="text-zinc-500">Status</p>
            <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium ${STATUS_COLORS[status] || STATUS_COLORS.expired}`}>
              {status.charAt(0).toUpperCase() + status.slice(1)}
            </span>
          </div>
          <div>
            <p className="text-zinc-500">{status === 'cancelled' ? 'Access until' : 'Next billing'}</p>
            <p className="text-white font-medium">{formatDate(nextBilling)}</p>
          </div>
        </div>

        {/* Cancelled success message */}
        {cancelled && (
          <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-3 flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-emerald-400 font-semibold text-sm">Subscription Cancelled</p>
              <p className="text-zinc-300 text-xs mt-0.5">
                Your subscription has been cancelled. You keep full access{accessUntil ? ` until ${formatDate(accessUntil)}` : ' until the end of your billing period'}.
              </p>
            </div>
          </div>
        )}

        {/* Already cancelled */}
        {status === 'cancelled' && !cancelled && (
          <div className="bg-zinc-800/60 border border-zinc-700 rounded-lg p-3 text-sm text-zinc-400">
            Your subscription is cancelled. You keep access until {formatDate(nextBilling)}.
          </div>
        )}

        {/* Cancel button */}
        {canCancel && !showConfirm && (
          <button
            onClick={() => setShowConfirm(true)}
            className="mt-2 text-sm text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-500/60 rounded-lg px-4 py-2 transition-colors"
          >
            Cancel Subscription
          </button>
        )}

        {/* Confirmation dialog */}
        {showConfirm && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 space-y-3">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-white font-semibold text-sm">Cancel your subscription?</p>
                <p className="text-zinc-400 text-xs mt-1">
                  Future renewals will stop immediately. You keep full access{nextBilling ? ` until ${formatDate(nextBilling)}` : ' until your current billing period ends'}.
                  This cannot be undone.
                </p>
              </div>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleCancel}
                disabled={cancelling}
                className="flex-1 bg-red-600 hover:bg-red-700 text-white text-sm font-semibold py-2 rounded-lg transition-colors disabled:opacity-60"
              >
                {cancelling ? 'Cancelling...' : 'Yes, Cancel Subscription'}
              </button>
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm font-semibold py-2 rounded-lg transition-colors"
              >
                Keep Subscription
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Security */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
        <h2 className="text-white font-semibold flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-zinc-400" /> Security
        </h2>
        <p className="text-zinc-400 text-sm">To change your password, please contact support at <span className="text-violet-400">support@coveredcallengine.com</span></p>
      </div>
    </div>
  );
}
