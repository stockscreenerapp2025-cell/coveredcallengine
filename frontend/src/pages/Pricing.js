import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import api from "../lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Checkbox } from "../components/ui/checkbox";
import { Switch } from "../components/ui/switch";
import { Check, Sparkles, ExternalLink, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

/**
 * Pricing page
 * - DB-driven plans via GET /api/subscription/plans
 * - PayPal Express Checkout via POST /api/paypal/create-checkout
 * - Optional Stripe hosted links via GET /api/subscription/links (if still enabled)
 * - Handles PayPal return (token + PayerID) by calling /api/paypal/checkout-return (best-effort)
 */

const FALLBACK_PLANS = [
  {
    id: "basic",
    name: "Basic",
    description: "Essential tools for covered call trading",
    monthlyPrice: 39,
    yearlyPrice: 390,
    trialDays: 7,
    popular: false,
    color: "emerald",
  },
  {
    id: "standard",
    name: "Standard",
    description: "Advanced features for serious traders",
    monthlyPrice: 69,
    yearlyPrice: 690,
    trialDays: 7,
    popular: true,
    color: "violet",
  },
  {
    id: "premium",
    name: "Premium",
    description: "Full suite for professional traders",
    monthlyPrice: 99,
    yearlyPrice: 990,
    trialDays: 7,
    popular: false,
    color: "amber",
  },
];

const PLAN_FEATURES = {
  basic: [
    "Access to Covered Call Dashboard",
    "Covered Call Scans",
    "Real Market Data",
    "TradingView Integration Charts",
    "Key Technical Indicators",
    "Portfolio Tracker",
    "Cancel any time",
    "Dedicated Support",
    "7 Days FREE Trial",
    "2,000 AI Tokens/month",
  ],
  standard: [
    "Everything in Basic",
    "PMCC Strategy Scanner",
    "Powerful Watch List with AI Features",
    "Dedicated Support",
    "7 Days FREE Trial",
    "6,000 AI Tokens/month",
  ],
  premium: [
    "Everything in Standard",
    "Powerful Simulator and Analyser",
    "AI Management of Trades Selected",
    "Dedicated Support",
    "7 Days FREE Trial",
    "15,000 AI Tokens/month",
  ],
};

const getColorClasses = (color) => {
  const colors = {
    emerald: {
      border: "border-emerald-500/30",
      text: "text-emerald-400",
      button: "bg-emerald-600 hover:bg-emerald-700",
      badge: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
      gradient: "from-emerald-500/20 to-transparent",
      checkbox: "data-[state=checked]:bg-emerald-600 data-[state=checked]:border-emerald-600",
    },
    violet: {
      border: "border-violet-500/50",
      text: "text-violet-400",
      button: "bg-violet-600 hover:bg-violet-700",
      badge: "bg-violet-500/20 text-violet-400 border-violet-500/30",
      gradient: "from-violet-500/20 to-transparent",
      checkbox: "data-[state=checked]:bg-violet-600 data-[state=checked]:border-violet-600",
    },
    amber: {
      border: "border-amber-500/30",
      text: "text-amber-400",
      button: "bg-amber-600 hover:bg-amber-700",
      badge: "bg-amber-500/20 text-amber-400 border-amber-500/30",
      gradient: "from-amber-500/20 to-transparent",
      checkbox: "data-[state=checked]:bg-amber-600 data-[state=checked]:border-amber-600",
    },
  };
  return colors[color] || colors.emerald;
};

function normalizePlansPayload(payload) {
  // Support multiple shapes:
  // A) { plans: { basic: {...}, standard: {...} }, trial_days, currency }
  // B) { plans: [ ... ] }
  // C) { data: ... } already handled by caller
  if (!payload) return [];

  if (Array.isArray(payload.plans)) {
    return payload.plans;
  }

  if (payload.plans && typeof payload.plans === "object") {
    const obj = payload.plans;
    return Object.entries(obj).map(([id, p]) => ({
      id,
      name: p?.name || id,
      monthlyPrice: Number(p?.monthly_price ?? p?.monthlyPrice ?? 0),
      yearlyPrice: Number(p?.yearly_price ?? p?.yearlyPrice ?? 0),
      trialDays: Number(p?.trial_days ?? payload.trial_days ?? 0),
      description: p?.description || "",
    }));
  }

  return [];
}

const Pricing = () => {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const [plans, setPlans] = useState(FALLBACK_PLANS);
  const [isYearly, setIsYearly] = useState(false);

  const [acceptedTerms, setAcceptedTerms] = useState({
    basic: false,
    standard: false,
    premium: false,
  });

  const [paypalConfig, setPaypalConfig] = useState({ enabled: false, mode: "sandbox" });
  const [stripeLinks, setStripeLinks] = useState(null);

  const [loadingPlans, setLoadingPlans] = useState(true);
  const [loadingPayPal, setLoadingPayPal] = useState(false);
  const [finalizing, setFinalizing] = useState(false);

  // -------- Load plans (DB-driven) --------
  useEffect(() => {
    let cancelled = false;

    const loadPlans = async () => {
      setLoadingPlans(true);
      try {
        const res = await api.get("/subscription/plans");
        const payload = res?.data || {};
        const normalized = normalizePlansPayload(payload);

        if (!cancelled && normalized.length) {
          // Merge into our UI model
          const merged = normalized.map((p) => {
            const fallback = FALLBACK_PLANS.find((x) => x.id === p.id);
            return {
              id: p.id,
              name: p.name || fallback?.name || p.id,
              description: p.description || fallback?.description || "",
              monthlyPrice: p.monthlyPrice || fallback?.monthlyPrice || 0,
              yearlyPrice: p.yearlyPrice || fallback?.yearlyPrice || 0,
              trialDays: p.trialDays ?? fallback?.trialDays ?? 0,
              popular: fallback?.popular ?? false,
              color: fallback?.color ?? "emerald",
            };
          });

          // Keep known plan ordering if possible
          const order = ["basic", "standard", "premium"];
          merged.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));

          setPlans(merged);

          // Expand acceptedTerms keys dynamically
          const nextAccepted = {};
          for (const pl of merged) nextAccepted[pl.id] = Boolean(acceptedTerms[pl.id]);
          setAcceptedTerms((prev) => ({ ...nextAccepted, ...prev }));
        }
      } catch (e) {
        // fallback stays
        console.error("Failed to fetch plans:", e);
      } finally {
        if (!cancelled) setLoadingPlans(false);
      }
    };

    loadPlans();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -------- Load PayPal config (enabled/mode) --------
  useEffect(() => {
    let cancelled = false;

    const loadPaypalConfig = async () => {
      try {
        const res = await api.get("/paypal/config");
        if (!cancelled && res?.data) {
          setPaypalConfig({
            enabled: Boolean(res.data.enabled),
            mode: res.data.mode || "sandbox",
          });
        }
      } catch (e) {
        // If config endpoint missing or unavailable, keep disabled
        console.error("Failed to fetch PayPal config:", e);
      }
    };

    loadPaypalConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  // -------- OPTIONAL: Load Stripe hosted links (if your backend still supports it) --------
  useEffect(() => {
    let cancelled = false;

    const loadStripeLinks = async () => {
      try {
        const res = await api.get("/subscription/links");
        if (!cancelled) setStripeLinks(res?.data || null);
      } catch (e) {
        // Ignore if endpoint removed / not configured
        setStripeLinks(null);
      }
    };

    loadStripeLinks();
    return () => {
      cancelled = true;
    };
  }, []);

  // -------- Handle PayPal return (token + PayerID) --------
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const token = params.get("token");
    const payerId = params.get("PayerID") || params.get("payer_id") || params.get("payerID");
    const paypalStatus = params.get("paypal"); // success/cancelled from our return_url

    // If user cancelled on PayPal side and we were redirected back
    if (paypalStatus === "cancelled") {
      toast.info("PayPal checkout cancelled.");
      // Clean URL
      params.delete("paypal");
      navigate({ pathname: location.pathname, search: params.toString() ? `?${params.toString()}` : "" }, { replace: true });
      return;
    }

    // Only finalize if PayPal sent token + payer
    if (!token || !payerId) return;
    if (finalizing) return;

    const finalize = async () => {
      setFinalizing(true);
      try {
        // Best-effort: try POST first
        try {
          const res = await api.post("/paypal/checkout-return", {
            token,
            payer_id: payerId,
          });
          if (res?.data?.success === false) {
            throw new Error(res?.data?.message || "Checkout return failed");
          }
        } catch (postErr) {
          // Fallback: some backends use GET with query params
          const qs = new URLSearchParams({ token, PayerID: payerId }).toString();
          await api.get(`/paypal/checkout-return?${qs}`);
        }

        toast.success("Subscription activated successfully.");
      } catch (e) {
        const msg =
          e?.response?.data?.detail ||
          e?.response?.data?.message ||
          e?.message ||
          "Could not finalize PayPal checkout. Please contact support.";
        toast.error(msg);
        console.error("PayPal checkout-return finalize error:", e);
      } finally {
        // Clean URL so refresh doesn't re-trigger finalize
        const clean = new URLSearchParams(location.search);
        clean.delete("token");
        clean.delete("PayerID");
        clean.delete("payer_id");
        clean.delete("payerID");
        clean.delete("paypal");
        navigate({ pathname: location.pathname, search: clean.toString() ? `?${clean.toString()}` : "" }, { replace: true });
        setFinalizing(false);
      }
    };

    finalize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);

  const displayPlans = useMemo(() => {
    // Attach features and link keys
    return plans.map((p) => ({
      ...p,
      features: PLAN_FEATURES[p.id] || [],
      monthlyLinkKey: `${p.id}_monthly_link`,
      yearlyLinkKey: `${p.id}_yearly_link`,
    }));
  }, [plans]);

  const handlePayPalSubscribe = async (planId) => {
    if (!acceptedTerms[planId]) {
      toast.error("Please accept the Terms & Conditions to subscribe");
      return;
    }
    if (!paypalConfig?.enabled) {
      toast.error("PayPal is not enabled. Please configure PayPal in Admin → Integrations.");
      return;
    }

    setLoadingPayPal(true);
    try {
      const billing_cycle = isYearly ? "yearly" : "monthly";

      const payload = {
        plan_id: planId,
        billing_cycle,
        start_with_trial: true,
        return_url: `${window.location.origin}/pricing?paypal=success`,
        cancel_url: `${window.location.origin}/pricing?paypal=cancelled`,
      };

      const res = await api.post("/paypal/create-checkout", payload);
      const redirectUrl = res?.data?.redirect_url;

      if (!res?.data?.success || !redirectUrl) {
        toast.error("PayPal checkout could not be created. Check PayPal settings in Admin.");
        return;
      }

      window.location.href = redirectUrl;
    } catch (e) {
      const msg =
        e?.response?.data?.detail ||
        e?.response?.data?.message ||
        e?.message ||
        "Failed to start PayPal checkout";
      toast.error(msg);
      console.error("PayPal create-checkout error:", e);
    } finally {
      setLoadingPayPal(false);
    }
  };

  const handleStripeSubscribe = (planId) => {
    if (!acceptedTerms[planId]) {
      toast.error("Please accept the Terms & Conditions to subscribe");
      return;
    }

    if (!stripeLinks) {
      toast.error("Stripe payment link not configured.");
      return;
    }

    const linkKey = isYearly ? `${planId}_yearly_link` : `${planId}_monthly_link`;
    const link = stripeLinks?.[linkKey];

    if (!link) {
      toast.error("Stripe payment link not configured. Please contact support.");
      return;
    }

    let paymentUrl = link;
    if (user?.email) {
      const separator = link.includes("?") ? "&" : "?";
      paymentUrl = `${link}${separator}prefilled_email=${encodeURIComponent(user.email)}`;
    }

    window.open(paymentUrl, "_blank");
  };

  return (
    <div className="space-y-8" data-testid="pricing-page">
      {/* Header */}
      <div className="text-center max-w-3xl mx-auto">
        <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 mb-4">
          <Sparkles className="w-3 h-3 mr-1" />
          Premium Features
        </Badge>
        <h1 className="text-3xl md:text-4xl font-bold text-white mb-4">
          Choose Your
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-400"> Trading Plan</span>
        </h1>
        <p className="text-zinc-400 text-lg">All plans include a FREE trial. Cancel anytime.</p>

        {!paypalConfig?.enabled && (
          <div className="mt-4 inline-flex items-center gap-2 text-sm text-amber-300 bg-amber-500/10 border border-amber-500/20 px-3 py-2 rounded-md">
            <AlertTriangle className="w-4 h-4" />
            PayPal is not enabled yet. Configure it in <span className="font-medium">Admin → Integrations</span>.
          </div>
        )}
      </div>

      {/* Monthly/Yearly Toggle */}
      <div className="flex items-center justify-center gap-4">
        <span className={`text-sm font-medium ${!isYearly ? "text-white" : "text-zinc-500"}`}>Monthly</span>
        <Switch
          checked={isYearly}
          onCheckedChange={setIsYearly}
          className="data-[state=checked]:bg-emerald-600"
          data-testid="billing-toggle"
        />
        <span className={`text-sm font-medium ${isYearly ? "text-white" : "text-zinc-500"}`}>Yearly</span>
        {isYearly && (
          <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 ml-2">Save 2 months</Badge>
        )}
      </div>

      {/* Pricing Cards */}
      <div className="grid md:grid-cols-3 gap-6 max-w-6xl mx-auto items-stretch">
        {displayPlans.map((plan) => {
          const colors = getColorClasses(plan.color);
          const price = isYearly ? plan.yearlyPrice : plan.monthlyPrice;
          const period = isYearly ? "/year" : "/month";

          return (
            <Card
              key={plan.id}
              className={`glass-card relative overflow-hidden transition-all duration-300 hover:scale-[1.02] flex flex-col ${
                plan.popular ? `border-2 ${colors.border} shadow-lg shadow-violet-500/10` : ""
              }`}
              data-testid={`pricing-card-${plan.id}`}
            >
              {plan.popular && (
                <div className="absolute top-0 left-0 right-0 bg-violet-600 text-white text-xs font-medium py-1.5 text-center">
                  Most Popular
                </div>
              )}

              <div className={`absolute inset-0 bg-gradient-to-b ${colors.gradient} pointer-events-none`} />

              <CardHeader className={`text-center pb-2 relative ${plan.popular ? "pt-10" : ""}`}>
                <CardTitle className="text-2xl text-white font-bold">{plan.name}</CardTitle>
                <CardDescription className="text-zinc-400">{plan.description}</CardDescription>
              </CardHeader>

              <CardContent className="space-y-5 relative flex-grow flex flex-col">
                {/* Price */}
                <div className="text-center py-4">
                  <div className="flex items-baseline justify-center">
                    <span className="text-lg text-zinc-500">$</span>
                    <span className="text-5xl font-bold text-white">{price}</span>
                    <span className="text-zinc-500 ml-1">{period}</span>
                  </div>
                  <div className="text-sm text-zinc-500 mt-1">(USD)</div>
                </div>

                {/* Features */}
                <ul className="space-y-3 flex-grow">
                  {(plan.features || []).map((feature, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-sm">
                      <Check className={`w-4 h-4 ${colors.text} flex-shrink-0 mt-0.5`} />
                      <span className="text-zinc-300">{feature}</span>
                    </li>
                  ))}
                </ul>

                {/* Terms */}
                <div className="flex items-start gap-2 pt-4 border-t border-zinc-800">
                  <Checkbox
                    id={`terms-${plan.id}`}
                    checked={Boolean(acceptedTerms[plan.id])}
                    onCheckedChange={(checked) =>
                      setAcceptedTerms((prev) => ({
                        ...prev,
                        [plan.id]: Boolean(checked),
                      }))
                    }
                    className={colors.checkbox}
                    data-testid={`terms-checkbox-${plan.id}`}
                  />
                  <label htmlFor={`terms-${plan.id}`} className="text-xs text-zinc-400 leading-tight cursor-pointer">
                    Read and Accept{" "}
                    <Link to="/terms" className="text-emerald-400 hover:text-emerald-300 underline" target="_blank">
                      Terms & Conditions
                    </Link>
                  </label>
                </div>

                {/* CTA Buttons */}
                <div className="pt-2 space-y-2">
                  <Button
                    onClick={() => handlePayPalSubscribe(plan.id)}
                    disabled={loadingPlans || loadingPayPal || finalizing || !acceptedTerms[plan.id] || !paypalConfig?.enabled}
                    className={`w-full ${
                      acceptedTerms[plan.id] && paypalConfig?.enabled ? colors.button : "bg-zinc-700 cursor-not-allowed"
                    } text-white font-medium py-6`}
                    data-testid={`paypal-subscribe-btn-${plan.id}`}
                  >
                    {loadingPayPal ? "Starting PayPal..." : "SUBSCRIBE WITH PAYPAL"}
                    {acceptedTerms[plan.id] && paypalConfig?.enabled && <ExternalLink className="w-4 h-4 ml-2" />}
                  </Button>

                  {/* Optional Stripe link button (only show if links exist) */}
                  {stripeLinks && (
                    <Button
                      variant="outline"
                      onClick={() => handleStripeSubscribe(plan.id)}
                      disabled={loadingPlans || loadingPayPal || finalizing || !acceptedTerms[plan.id]}
                      className="w-full py-6 border-zinc-700 text-zinc-200 hover:bg-zinc-800"
                      data-testid={`stripe-subscribe-btn-${plan.id}`}
                    >
                      SUBSCRIBE WITH STRIPE
                      {acceptedTerms[plan.id] && <ExternalLink className="w-4 h-4 ml-2" />}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Loading hint */}
      {loadingPlans && (
        <div className="text-center text-sm text-zinc-500">Loading pricing…</div>
      )}
    </div>
  );
};

export default Pricing;
