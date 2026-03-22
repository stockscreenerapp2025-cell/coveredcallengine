import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import api from '../lib/api';
import { toast } from 'sonner';
import { User, CreditCard, ShieldCheck, AlertTriangle, CheckCircle, Eye, EyeOff, Pencil, ArrowUpCircle, X } from 'lucide-react';

const PLAN_LABELS = {
  basic: 'Basic',
  standard: 'Standard',
  premium: 'Premium',
};

const PLAN_ORDER = ['basic', 'standard', 'premium'];

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
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const sub = user?.subscription || {};

  // Subscription cancel state
  const [showConfirm, setShowConfirm] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [accessUntil, setAccessUntil] = useState(null);

  // Upgrade state
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [plans, setPlans] = useState({});
  const [selectedPlan, setSelectedPlan] = useState('');
  const [selectedCycle, setSelectedCycle] = useState('monthly');
  const [upgrading, setUpgrading] = useState(false);

  // Change name state
  const [editingName, setEditingName] = useState(false);
  const [nameVal, setNameVal] = useState('');
  const [nameLoading, setNameLoading] = useState(false);

  // Change password state
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' });
  const [showPw, setShowPw] = useState({ current: false, next: false, confirm: false });
  const [pwLoading, setPwLoading] = useState(false);

  const status = sub.status || 'none';
  const currentPlan = (sub.plan_name || sub.plan || '').toLowerCase();
  const planLabel = PLAN_LABELS[currentPlan] || sub.plan_name || sub.plan || 'Free';
  const billingCycle = sub.billing_cycle === 'yearly' ? 'Yearly' : sub.billing_cycle === 'monthly' ? 'Monthly' : '—';
  const nextBilling = sub.current_period_end || sub.next_billing_date || sub.trial_end;
  const canCancel = ['active', 'trialing'].includes(status) && !cancelled;
  const canUpgrade = ['active', 'trialing', 'none', 'cancelled', 'expired'].includes(status);

  useEffect(() => {
    const upgradeStatus = searchParams.get('upgrade');
    if (upgradeStatus === 'success') {
      window.history.replaceState({}, '', '/account');
      toast.success('Subscription upgraded successfully!');
    } else if (upgradeStatus === 'cancelled') {
      window.history.replaceState({}, '', '/account');
      toast.info('Upgrade cancelled.');
    }
  }, []);

  useEffect(() => {
    if (showUpgrade && Object.keys(plans).length === 0) {
      api.get('/subscription/plans').then(res => {
        setPlans(res.data.plans || {});
        // Pre-select next plan above current
        const idx = PLAN_ORDER.indexOf(currentPlan);
        setSelectedPlan(PLAN_ORDER[idx + 1] || PLAN_ORDER[PLAN_ORDER.length - 1]);
      }).catch(() => {});
    }
  }, [showUpgrade]);

  const handleChangeName = async (e) => {
    e.preventDefault();
    if (!nameVal.trim()) return;
    setNameLoading(true);
    try {
      await api.post('/auth/me/update-name', { name: nameVal.trim() });
      toast.success('Name updated.');
      setEditingName(false);
      if (refreshUser) refreshUser();
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to update name.');
    } finally {
      setNameLoading(false);
    }
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    if (pwForm.next !== pwForm.confirm) {
      toast.error('New passwords do not match.');
      return;
    }
    if (pwForm.next.length < 8) {
      toast.error('New password must be at least 8 characters.');
      return;
    }
    setPwLoading(true);
    try {
      await api.post('/auth/me/change-password', {
        current_password: pwForm.current,
        new_password: pwForm.next,
      });
      toast.success('Password updated successfully.');
      setPwForm({ current: '', next: '', confirm: '' });
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to update password.');
    } finally {
      setPwLoading(false);
    }
  };

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
      toast.error(err?.response?.data?.detail || 'Failed to cancel. Please contact support.');
    } finally {
      setCancelling(false);
    }
  };

  const handleUpgrade = async () => {
    if (!selectedPlan) return;
    setUpgrading(true);
    try {
      // Step 1: Cancel current subscription if active
      if (['active', 'trialing'].includes(status)) {
        await api.post('/auth/me/cancel-subscription');
      }
      // Step 2: Create new PayPal checkout for selected plan
      const res = await api.post('/paypal/create-checkout', {
        plan_id: selectedPlan,
        billing_cycle: selectedCycle,
        start_with_trial: false,
        return_url: `${window.location.origin}/api/paypal/checkout-return`,
        cancel_url: `${window.location.origin}/account?upgrade=cancelled`,
      });
      // Step 3: Redirect to PayPal
      if (res.data.redirect_url) {
        window.location.href = res.data.redirect_url;
      } else {
        toast.error('Could not create checkout. Please try again.');
        setUpgrading(false);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Upgrade failed. Please try again.');
      setUpgrading(false);
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
            {editingName ? (
              <form onSubmit={handleChangeName} className="flex items-center gap-2 mt-1">
                <input
                  autoFocus
                  value={nameVal}
                  onChange={e => setNameVal(e.target.value)}
                  className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1 text-white text-sm focus:outline-none focus:border-violet-500 w-36"
                />
                <button type="submit" disabled={nameLoading} className="text-violet-400 hover:text-violet-300 text-xs font-medium">
                  {nameLoading ? 'Saving...' : 'Save'}
                </button>
                <button type="button" onClick={() => setEditingName(false)} className="text-zinc-500 hover:text-zinc-300 text-xs">
                  Cancel
                </button>
              </form>
            ) : (
              <div className="flex items-center gap-2 mt-0.5">
                <p className="text-white font-medium">{user?.name || '—'}</p>
                <button onClick={() => { setNameVal(user?.name || ''); setEditingName(true); }} className="text-zinc-500 hover:text-violet-400 transition-colors">
                  <Pencil className="w-3 h-3" />
                </button>
              </div>
            )}
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

        {/* Action buttons */}
        <div className="flex gap-3 flex-wrap">
          {/* Upgrade button */}
          {canUpgrade && !showUpgrade && (
            <button
              onClick={() => setShowUpgrade(true)}
              className="text-sm text-violet-400 hover:text-violet-300 border border-violet-500/30 hover:border-violet-500/60 rounded-lg px-4 py-2 transition-colors flex items-center gap-2"
            >
              <ArrowUpCircle className="w-4 h-4" /> Upgrade Subscription
            </button>
          )}

          {/* Cancel button */}
          {canCancel && !showConfirm && !showUpgrade && (
            <button
              onClick={() => setShowConfirm(true)}
              className="text-sm text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-500/60 rounded-lg px-4 py-2 transition-colors"
            >
              Cancel Subscription
            </button>
          )}
        </div>

        {/* Upgrade Plan Modal */}
        {showUpgrade && (
          <div className="bg-zinc-800/60 border border-violet-500/20 rounded-xl p-4 space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-white font-semibold text-sm flex items-center gap-2">
                <ArrowUpCircle className="w-4 h-4 text-violet-400" /> Select New Plan
              </p>
              <button onClick={() => setShowUpgrade(false)} className="text-zinc-500 hover:text-zinc-300">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Billing cycle toggle */}
            <div className="flex gap-2">
              {['monthly', 'yearly'].map(c => (
                <button
                  key={c}
                  onClick={() => setSelectedCycle(c)}
                  className={`flex-1 text-xs font-medium py-1.5 rounded-lg border transition-colors ${
                    selectedCycle === c
                      ? 'bg-violet-600 border-violet-500 text-white'
                      : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-white'
                  }`}
                >
                  {c.charAt(0).toUpperCase() + c.slice(1)}
                  {c === 'yearly' && <span className="ml-1 text-emerald-400">(Save 2 months)</span>}
                </button>
              ))}
            </div>

            {/* Plan options */}
            <div className="space-y-2">
              {PLAN_ORDER.map(planKey => {
                const plan = plans[planKey];
                if (!plan) return null;
                const price = selectedCycle === 'yearly' ? plan.yearly_price : plan.monthly_price;
                const isCurrent = planKey === currentPlan;
                const isSelected = planKey === selectedPlan;
                return (
                  <button
                    key={planKey}
                    onClick={() => !isCurrent && setSelectedPlan(planKey)}
                    disabled={isCurrent}
                    className={`w-full text-left p-3 rounded-lg border transition-colors ${
                      isCurrent
                        ? 'bg-zinc-800/40 border-zinc-700 opacity-50 cursor-not-allowed'
                        : isSelected
                        ? 'bg-violet-600/20 border-violet-500 text-white'
                        : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-zinc-500'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-sm">{plan.name}</span>
                      <span className="text-sm font-bold">
                        ${price}<span className="text-xs font-normal text-zinc-400">/{selectedCycle === 'yearly' ? 'yr' : 'mo'}</span>
                      </span>
                    </div>
                    {isCurrent && <p className="text-xs text-zinc-500 mt-0.5">Current plan</p>}
                  </button>
                );
              })}
            </div>

            {/* Info note */}
            <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 space-y-1">
              <p className="text-amber-400 text-xs font-semibold">⚠️ Important — Please read before upgrading</p>
              <p className="text-zinc-400 text-xs">
                By upgrading, your current subscription will be <strong className="text-white">cancelled immediately with no refund</strong> for unused days. Your new plan starts right away and you will be charged the full amount for the new plan.
              </p>
              <p className="text-zinc-400 text-xs">
                <strong className="text-white">No credit or adjustment</strong> will be applied for the remaining period of your current plan.
              </p>
              <p className="text-zinc-500 text-xs italic">
                Example: On Standard Monthly ($59/mo) and upgrading to Premium after 10 days — your current plan is cancelled immediately with no refund for the remaining 20 days. You will be charged the full $89/mo for the new plan starting today.
              </p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={handleUpgrade}
                disabled={upgrading || !selectedPlan || selectedPlan === currentPlan}
                className="flex-1 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold py-2 rounded-lg transition-colors disabled:opacity-60"
              >
                {upgrading ? 'Redirecting to PayPal...' : `Upgrade to ${PLAN_LABELS[selectedPlan] || selectedPlan}`}
              </button>
              <button
                onClick={() => setShowUpgrade(false)}
                className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm font-semibold py-2 rounded-lg transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Cancel confirmation dialog */}
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

      {/* Security — Change Password */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
        <h2 className="text-white font-semibold flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-zinc-400" /> Security
        </h2>
        <form onSubmit={handleChangePassword} className="space-y-3">
          {[
            { key: 'current', label: 'Current Password' },
            { key: 'next',    label: 'New Password' },
            { key: 'confirm', label: 'Confirm New Password' },
          ].map(({ key, label }) => (
            <div key={key}>
              <label className="block text-zinc-500 text-xs mb-1">{label}</label>
              <div className="relative">
                <input
                  type={showPw[key] ? 'text' : 'password'}
                  value={pwForm[key]}
                  onChange={e => setPwForm(f => ({ ...f, [key]: e.target.value }))}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white text-sm pr-10 focus:outline-none focus:border-violet-500"
                  placeholder="••••••••"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPw(s => ({ ...s, [key]: !s[key] }))}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                >
                  {showPw[key] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
          ))}
          <button
            type="submit"
            disabled={pwLoading}
            className="w-full bg-violet-600 hover:bg-violet-700 text-white rounded-lg py-2 text-sm font-medium transition-colors disabled:opacity-60"
          >
            {pwLoading ? 'Updating...' : 'Update Password'}
          </button>
        </form>
      </div>
    </div>
  );
}
