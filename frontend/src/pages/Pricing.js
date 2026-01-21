import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Checkbox } from '../components/ui/checkbox';
import {
  Crown,
  Check,
  Zap,
  Shield,
  TrendingUp,
  BarChart3,
  Clock,
  Star,
  Sparkles,
  ArrowRight,
  CreditCard,
  Loader2,
  FileText
} from 'lucide-react';
import { toast } from 'sonner';

const Pricing = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [subscriptionLinks, setSubscriptionLinks] = useState(null);
  const [paypalLinks, setPaypalLinks] = useState(null);
  const [loading, setLoading] = useState(true);
  const [termsAccepted, setTermsAccepted] = useState(false);

  useEffect(() => {
    fetchPaymentConfigs();
  }, []);

  // Handle payment return (success/cancel)
  useEffect(() => {
    const paymentStatus = searchParams.get('payment');
    const provider = searchParams.get('provider');
    const plan = searchParams.get('plan');
    
    if (paymentStatus === 'success') {
      // Redirect to set-password page if coming from a payment
      if (provider && plan) {
        navigate(`/set-password?provider=${provider}&plan=${plan}`);
      } else {
        toast.success('Payment successful! Please check your email for next steps.');
      }
      // Clean up URL
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (paymentStatus === 'cancelled') {
      toast.info('Payment cancelled');
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, [searchParams, navigate]);

  const fetchPaymentConfigs = async () => {
    try {
      const [stripeRes, paypalRes] = await Promise.all([
        api.get('/subscription/links'),
        api.get('/paypal/links')
      ]);
      setSubscriptionLinks(stripeRes.data);
      setPaypalLinks(paypalRes.data);
    } catch (error) {
      console.error('Failed to fetch payment config:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubscribe = (link, provider, planId) => {
    if (!link) return;
    if (!termsAccepted) {
      toast.error('Please accept the Terms of Service and Privacy Policy to continue');
      return;
    }
    
    // Add user email and return URL to the payment link
    let paymentUrl = link;
    const returnUrl = `${window.location.origin}/pricing?payment=success&provider=${provider}&plan=${planId}`;
    const cancelUrl = `${window.location.origin}/pricing?payment=cancelled`;
    
    // For Stripe links
    if (provider === 'stripe') {
      const separator = link.includes('?') ? '&' : '?';
      paymentUrl = `${link}${separator}success_url=${encodeURIComponent(returnUrl)}&cancel_url=${encodeURIComponent(cancelUrl)}`;
      if (user?.email) {
        paymentUrl += `&prefilled_email=${encodeURIComponent(user.email)}`;
      }
    }
    
    // For PayPal links - they handle return URLs differently
    if (provider === 'paypal') {
      // PayPal subscription links usually have their own return handling
      // But we can try to append if the link supports it
      if (user?.email) {
        const separator = link.includes('?') ? '&' : '?';
        paymentUrl = `${link}${separator}email=${encodeURIComponent(user.email)}`;
      }
    }
    
    window.open(paymentUrl, '_blank');
  };

  const plans = [
    {
      id: 'trial',
      name: '7-Day FREE Trial',
      price: '$0',
      period: '7 days',
      description: 'Try premium features risk-free',
      stripeLinkKey: 'trial_link',
      paypalLinkKey: 'trial_link',
      popular: false,
      highlight: 'Start Free',
      features: [
        'Access to Covered Call Dashboard',
        'Limited Covered Call Scans',
        'Near real-time options data',
        'TradingView chart integration',
        'Key Technical indicators'
      ],
      icon: Clock,
      color: 'emerald',
      buttonText: 'Start Free Trial',
      note: '*Credit card required for verification only'
    },
    {
      id: 'monthly',
      name: 'Monthly Plan',
      price: '$49',
      period: '/month',
      description: 'Perfect for active traders',
      stripeLinkKey: 'monthly_link',
      paypalLinkKey: 'monthly_link',
      popular: true,
      highlight: 'Most Popular',
      features: [
        'Everything in Free Trial',
        'Unlimited Covered Call Scans',
        'PMCC Strategy Scanner',
        'Advanced filtering options',
        'Portfolio Tracker',
        'Cancel anytime'
      ],
      icon: Zap,
      color: 'violet',
      buttonText: 'Subscribe Monthly'
    },
    {
      id: 'yearly',
      name: 'Annual Plan',
      price: '$499',
      period: '/year',
      description: 'Best value for serious traders',
      stripeLinkKey: 'yearly_link',
      paypalLinkKey: 'yearly_link',
      popular: false,
      highlight: 'Save 15%+',
      savings: 'Save 15%+',
      features: [
        'Everything in Monthly Plan',
        'Special Discount',
        'Early access to new features',
        'Dedicated support channel',
        'Locked-in pricing'
      ],
      icon: Crown,
      color: 'amber',
      buttonText: 'Subscribe Annual'
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
        gradient: 'from-emerald-500/20 to-transparent'
      },
      violet: {
        bg: 'bg-violet-500/10',
        border: 'border-violet-500/50',
        text: 'text-violet-400',
        button: 'bg-violet-600 hover:bg-violet-700',
        badge: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
        gradient: 'from-violet-500/20 to-transparent'
      },
      amber: {
        bg: 'bg-amber-500/10',
        border: 'border-amber-500/30',
        text: 'text-amber-400',
        button: 'bg-amber-600 hover:bg-amber-700',
        badge: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
        gradient: 'from-amber-500/20 to-transparent'
      }
    };
    return colors[color] || colors.emerald;
  };

  const paypalEnabled = paypalLinks?.enabled;

  return (
    <div className="space-y-8" data-testid="pricing-page">
      {/* Header */}
      <div className="text-center max-w-3xl mx-auto">
        <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 mb-4">
          <Sparkles className="w-3 h-3 mr-1" />
          Premium Features
        </Badge>
        <h1 className="text-3xl md:text-4xl font-bold text-white mb-4">
          Unlock the Full Power of
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-400"> Covered Call Engine</span>
        </h1>
        <p className="text-zinc-400 text-lg">
          Get access to professional-grade options screening tools, real-time data, and AI-powered insights.
        </p>
      </div>

      {/* Terms & Privacy Checkbox */}
      <div className="max-w-2xl mx-auto">
        <Card className={`glass-card border ${termsAccepted ? 'border-emerald-500/50' : 'border-yellow-500/50'}`}>
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <Checkbox
                id="terms-checkbox"
                checked={termsAccepted}
                onCheckedChange={setTermsAccepted}
                className="mt-1 border-zinc-600 data-[state=checked]:bg-emerald-600 data-[state=checked]:border-emerald-600"
                data-testid="terms-checkbox"
              />
              <label htmlFor="terms-checkbox" className="text-sm text-zinc-300 cursor-pointer leading-relaxed">
                <FileText className="w-4 h-4 inline mr-1 text-zinc-400" />
                I have read and agree to the{' '}
                <Link to="/terms" className="text-emerald-400 hover:text-emerald-300 underline" target="_blank">
                  Terms of Service
                </Link>{' '}
                and{' '}
                <Link to="/privacy" className="text-emerald-400 hover:text-emerald-300 underline" target="_blank">
                  Privacy Policy
                </Link>
                . I understand that my subscription will automatically renew until cancelled.
              </label>
            </div>
            {!termsAccepted && (
              <p className="text-xs text-yellow-400 mt-2 ml-7">
                ⚠️ Please accept the terms to enable payment buttons
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Pricing Cards */}
      <div className="grid md:grid-cols-3 gap-6 max-w-6xl mx-auto">
        {plans.map((plan) => {
          const colors = getColorClasses(plan.color);
          const Icon = plan.icon;
          const stripeLink = subscriptionLinks?.[plan.stripeLinkKey];
          const paypalLink = paypalLinks?.[plan.paypalLinkKey];
          
          return (
            <Card 
              key={plan.id}
              className={`glass-card relative overflow-hidden transition-all duration-300 hover:scale-[1.02] h-full flex flex-col ${
                plan.popular ? `border-2 ${colors.border} shadow-lg shadow-violet-500/10` : ''
              }`}
              data-testid={`pricing-card-${plan.id}`}
            >
              {/* Popular Badge - Left Side */}
              {plan.popular && (
                <div className="absolute top-0 left-0 px-3 py-1 bg-violet-600 text-white text-xs font-medium rounded-br-lg">
                  <Star className="w-3 h-3 inline mr-1" />
                  Most Popular
                </div>
              )}
              
              {/* Savings Badge - Right Side */}
              {plan.savings && (
                <div className="absolute top-0 right-0 px-3 py-1 bg-amber-600 text-white text-xs font-medium rounded-bl-lg">
                  {plan.savings}
                </div>
              )}

              {/* Gradient Background */}
              <div className={`absolute inset-0 bg-gradient-to-b ${colors.gradient} pointer-events-none`} />
              
              <CardHeader className="text-center pb-2 relative">
                <div className={`w-12 h-12 mx-auto mb-4 rounded-xl ${colors.bg} flex items-center justify-center`}>
                  <Icon className={`w-6 h-6 ${colors.text}`} />
                </div>
                <Badge className={`${colors.badge} mb-2`}>
                  {plan.highlight}
                </Badge>
                <CardTitle className="text-xl text-white">{plan.name}</CardTitle>
                <CardDescription>{plan.description}</CardDescription>
              </CardHeader>
              
              <CardContent className="space-y-6 relative flex-grow flex flex-col">
                {/* Price */}
                <div className="text-center">
                  <span className="text-4xl font-bold text-white">{plan.price}</span>
                  <span className="text-zinc-500 ml-1">{plan.period}</span>
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
                
                {/* Note */}
                {plan.note && (
                  <p className="text-xs text-zinc-500 text-center italic">{plan.note}</p>
                )}
                
                {/* Payment Buttons */}
                <div className="space-y-2 mt-auto">
                  {/* Stripe Button */}
                  <Button
                    onClick={() => handleSubscribe(stripeLink, 'stripe', plan.id)}
                    disabled={loading || !stripeLink || !termsAccepted}
                    className={`w-full ${termsAccepted ? colors.button : 'bg-zinc-700 cursor-not-allowed'} text-white font-medium py-5`}
                    data-testid={`subscribe-stripe-${plan.id}`}
                  >
                    <CreditCard className="w-4 h-4 mr-2" />
                    {plan.buttonText}
                  </Button>
                  
                  {/* PayPal Button - only show if PayPal is enabled and has a link */}
                  {paypalEnabled && paypalLink && (
                    <Button
                      onClick={() => handleSubscribe(paypalLink, 'paypal', plan.id)}
                      disabled={loading || !termsAccepted}
                      variant="outline"
                      className={`w-full py-5 ${termsAccepted ? 'border-blue-500/50 text-blue-400 hover:bg-blue-500/10' : 'border-zinc-700 text-zinc-500 cursor-not-allowed'}`}
                      data-testid={`subscribe-paypal-${plan.id}`}
                    >
                      <svg className="w-4 h-4 mr-2" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M7.076 21.337H2.47a.641.641 0 0 1-.633-.74L4.944.901C5.026.382 5.474 0 5.998 0h7.46c2.57 0 4.578.543 5.69 1.81 1.01 1.15 1.304 2.42 1.012 4.287-.023.143-.047.288-.077.437-.983 5.05-4.349 6.797-8.647 6.797H9.21c-.426 0-.794.31-.858.73L7.076 21.337z"/>
                      </svg>
                      Pay with PayPal
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Features Grid */}
      <div className="max-w-4xl mx-auto pt-8">
        <h2 className="text-2xl font-bold text-white text-center mb-8">
          What You Get With Premium
        </h2>
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { icon: BarChart3, title: 'Real-Time Data', desc: 'Live options chain & stock quotes' },
            { icon: TrendingUp, title: 'Smart Screening', desc: 'AI-powered opportunity scoring' },
            { icon: Shield, title: 'Risk Analysis', desc: 'Greeks, IV rank & probability' },
            { icon: Sparkles, title: 'PMCC Scanner', desc: 'Find LEAPS diagonal spreads' }
          ].map((feature, idx) => (
            <Card key={idx} className="glass-card p-4 text-center">
              <feature.icon className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
              <h3 className="font-medium text-white text-sm">{feature.title}</h3>
              <p className="text-xs text-zinc-500">{feature.desc}</p>
            </Card>
          ))}
        </div>
      </div>

      {/* Trust Badges */}
      <div className="text-center text-zinc-500 text-sm">
        <p className="flex items-center justify-center gap-4 flex-wrap">
          <span className="flex items-center gap-1">
            <Shield className="w-4 h-4 text-emerald-400" />
            Secure Payment via Stripe
          </span>
          {paypalEnabled && (
            <span className="flex items-center gap-1">
              <Shield className="w-4 h-4 text-blue-400" />
              PayPal Accepted
            </span>
          )}
          <span className="flex items-center gap-1">
            <Check className="w-4 h-4 text-emerald-400" />
            Cancel Anytime
          </span>
          <span className="flex items-center gap-1">
            <Zap className="w-4 h-4 text-emerald-400" />
            Instant Access
          </span>
        </p>
      </div>
    </div>
  );
};

export default Pricing;
