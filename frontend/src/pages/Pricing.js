import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Checkbox } from '../components/ui/checkbox';
import { Switch } from '../components/ui/switch';
import {
  Check,
  Shield,
  Sparkles,
  Clock,
  ExternalLink
} from 'lucide-react';
import { toast } from 'sonner';

const Pricing = () => {
  const { user } = useAuth();
  const [subscriptionLinks, setSubscriptionLinks] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isYearly, setIsYearly] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState({
    basic: false,
    standard: false,
    premium: false
  });

  useEffect(() => {
    fetchSubscriptionLinks();
  }, []);

  const fetchSubscriptionLinks = async () => {
    try {
      const response = await api.get('/subscription/links');
      setSubscriptionLinks(response.data);
    } catch (error) {
      console.error('Failed to fetch subscription links:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubscribe = (planId, link) => {
    if (!acceptedTerms[planId]) {
      toast.error('Please accept the Terms & Conditions to subscribe');
      return;
    }
    if (!link) {
      toast.error('Payment link not configured. Please contact support.');
      return;
    }
    // Add user email to the payment link if user is logged in
    let paymentUrl = link;
    if (user?.email) {
      const separator = link.includes('?') ? '&' : '?';
      paymentUrl = `${link}${separator}prefilled_email=${encodeURIComponent(user.email)}`;
    }
    window.open(paymentUrl, '_blank');
  };

  // Plan definitions matching the uploaded subscription plan
  const plans = [
    {
      id: 'basic',
      name: 'Basic',
      monthlyPrice: 39,
      yearlyPrice: 390,
      yearlySavings: 'Save 2 months',
      description: 'Essential tools for covered call trading',
      popular: false,
      color: 'emerald',
      features: [
        'Access to Covered Call Dashboard',
        'Covered Call Scans',
        'Real Market Data',
        'TradingView Integration',
        'Charts',
        'Key Technical Indicators',
        'Portfolio Tracker',
        'Cancel any time',
        'Dedicated Support'
      ],
      monthlyLinkKey: 'basic_monthly_link',
      yearlyLinkKey: 'basic_yearly_link'
    },
    {
      id: 'standard',
      name: 'Standard',
      monthlyPrice: 69,
      yearlyPrice: 690,
      yearlySavings: 'Save 2 months',
      description: 'Advanced features for serious traders',
      popular: true,
      color: 'violet',
      features: [
        'Everything in Basic',
        'PMCC Strategy Scanner',
        'Powerful Watch List with AI Features',
        'Dedicated Support'
      ],
      monthlyLinkKey: 'standard_monthly_link',
      yearlyLinkKey: 'standard_yearly_link'
    },
    {
      id: 'premium',
      name: 'Premium',
      monthlyPrice: 99,
      yearlyPrice: 990,
      yearlySavings: 'Save 2 months',
      description: 'Full suite for professional traders',
      popular: false,
      color: 'amber',
      features: [
        'Everything in Standard',
        'Powerful Simulator and Analyser',
        'AI Management of Trades',
        'Selected Dedicated Support'
      ],
      monthlyLinkKey: 'premium_monthly_link',
      yearlyLinkKey: 'premium_yearly_link'
    }
  ];

  const getColorClasses = (color) => {
    const colors = {
      emerald: {
        bg: 'bg-emerald-500/10',
        border: 'border-emerald-500/30',
        text: 'text-emerald-400',
        button: 'bg-emerald-600 hover:bg-emerald-700',
        badge: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
        gradient: 'from-emerald-500/20 to-transparent',
        checkbox: 'data-[state=checked]:bg-emerald-600 data-[state=checked]:border-emerald-600'
      },
      violet: {
        bg: 'bg-violet-500/10',
        border: 'border-violet-500/50',
        text: 'text-violet-400',
        button: 'bg-violet-600 hover:bg-violet-700',
        badge: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
        gradient: 'from-violet-500/20 to-transparent',
        checkbox: 'data-[state=checked]:bg-violet-600 data-[state=checked]:border-violet-600'
      },
      amber: {
        bg: 'bg-amber-500/10',
        border: 'border-amber-500/30',
        text: 'text-amber-400',
        button: 'bg-amber-600 hover:bg-amber-700',
        badge: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
        gradient: 'from-amber-500/20 to-transparent',
        checkbox: 'data-[state=checked]:bg-amber-600 data-[state=checked]:border-amber-600'
      }
    };
    return colors[color] || colors.emerald;
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
        <p className="text-zinc-400 text-lg">
          All plans include a 7-day FREE trial. Cancel anytime.
        </p>
      </div>

      {/* Monthly/Yearly Toggle */}
      <div className="flex items-center justify-center gap-4">
        <span className={`text-sm font-medium ${!isYearly ? 'text-white' : 'text-zinc-500'}`}>
          Monthly
        </span>
        <Switch
          checked={isYearly}
          onCheckedChange={setIsYearly}
          className="data-[state=checked]:bg-emerald-600"
          data-testid="billing-toggle"
        />
        <span className={`text-sm font-medium ${isYearly ? 'text-white' : 'text-zinc-500'}`}>
          Yearly
        </span>
        {isYearly && (
          <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 ml-2">
            Save 2 months
          </Badge>
        )}
      </div>

      {/* Pricing Cards */}
      <div className="grid md:grid-cols-3 gap-6 max-w-6xl mx-auto items-stretch">
        {plans.map((plan) => {
          const colors = getColorClasses(plan.color);
          const price = isYearly ? plan.yearlyPrice : plan.monthlyPrice;
          const period = isYearly ? '/year' : '/month';
          const linkKey = isYearly ? plan.yearlyLinkKey : plan.monthlyLinkKey;
          const link = subscriptionLinks?.[linkKey];
          
          return (
            <Card 
              key={plan.id}
              className={`glass-card relative overflow-hidden transition-all duration-300 hover:scale-[1.02] flex flex-col ${
                plan.popular ? `border-2 ${colors.border} shadow-lg shadow-violet-500/10` : ''
              }`}
              data-testid={`pricing-card-${plan.id}`}
            >
              {/* Popular Badge */}
              {plan.popular && (
                <div className="absolute top-0 left-0 right-0 bg-violet-600 text-white text-xs font-medium py-1.5 text-center">
                  Most Popular
                </div>
              )}

              {/* Gradient Background */}
              <div className={`absolute inset-0 bg-gradient-to-b ${colors.gradient} pointer-events-none`} />
              
              <CardHeader className={`text-center pb-2 relative ${plan.popular ? 'pt-10' : ''}`}>
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
                  {isYearly && (
                    <div className="text-sm text-emerald-400 mt-1">
                      {plan.yearlySavings}
                    </div>
                  )}
                </div>
                
                {/* 7-Day Trial Badge */}
                <div className="flex justify-center">
                  <Badge className="bg-cyan-500/20 text-cyan-400 border-cyan-500/30">
                    <Clock className="w-3 h-3 mr-1" />
                    7 Days FREE Trial
                  </Badge>
                </div>
                
                {/* Features */}
                <ul className="space-y-3 flex-grow">
                  {plan.features.map((feature, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-sm">
                      <Check className={`w-4 h-4 ${colors.text} flex-shrink-0 mt-0.5`} />
                      <span className="text-zinc-300">{feature}</span>
                    </li>
                  ))}
                </ul>
                
                {/* Terms & Conditions Checkbox */}
                <div className="flex items-start gap-2 pt-4 border-t border-zinc-800">
                  <Checkbox
                    id={`terms-${plan.id}`}
                    checked={acceptedTerms[plan.id]}
                    onCheckedChange={(checked) => setAcceptedTerms(prev => ({ ...prev, [plan.id]: checked }))}
                    className={colors.checkbox}
                    data-testid={`terms-checkbox-${plan.id}`}
                  />
                  <label htmlFor={`terms-${plan.id}`} className="text-xs text-zinc-400 leading-tight cursor-pointer">
                    I have read and accept the{' '}
                    <Link to="/terms" className="text-emerald-400 hover:text-emerald-300 underline" target="_blank">
                      Terms & Conditions
                    </Link>
                  </label>
                </div>
                
                {/* CTA Button - Fixed at bottom */}
                <div className="pt-2">
                  <Button
                    onClick={() => handleSubscribe(plan.id, link)}
                    disabled={loading || !acceptedTerms[plan.id]}
                    className={`w-full ${acceptedTerms[plan.id] ? colors.button : 'bg-zinc-700 cursor-not-allowed'} text-white font-medium py-6`}
                    data-testid={`subscribe-btn-${plan.id}`}
                  >
                    {acceptedTerms[plan.id] ? 'Subscribe' : 'Accept Terms to Subscribe'}
                    {acceptedTerms[plan.id] && <ExternalLink className="w-4 h-4 ml-2" />}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Trust Badges */}
      <div className="text-center text-zinc-500 text-sm pt-4">
        <p className="flex items-center justify-center gap-6 flex-wrap">
          <span className="flex items-center gap-1">
            <Shield className="w-4 h-4 text-emerald-400" />
            Secure Payment via PayPal
          </span>
          <span className="flex items-center gap-1">
            <Check className="w-4 h-4 text-emerald-400" />
            7-Day FREE Trial
          </span>
          <span className="flex items-center gap-1">
            <Check className="w-4 h-4 text-emerald-400" />
            Cancel Anytime
          </span>
        </p>
      </div>
    </div>
  );
};

export default Pricing;
