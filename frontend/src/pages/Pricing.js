import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
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
  Loader2
} from 'lucide-react';
import { toast } from 'sonner';

const Pricing = () => {
  const { user } = useAuth();
  const [subscriptionLinks, setSubscriptionLinks] = useState(null);
  const [paypalConfig, setPaypalConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [processingPaypal, setProcessingPaypal] = useState(null);

  useEffect(() => {
    fetchPaymentConfigs();
  }, []);

  const fetchPaymentConfigs = async () => {
    try {
      const [stripeRes, paypalRes] = await Promise.all([
        api.get('/subscription/links'),
        api.get('/paypal/config')
      ]);
      setSubscriptionLinks(stripeRes.data);
      setPaypalConfig(paypalRes.data);
    } catch (error) {
      console.error('Failed to fetch payment config:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleStripeSubscribe = (link) => {
    if (!link) return;
    // Add user email to the payment link if user is logged in
    let paymentUrl = link;
    if (user?.email) {
      const separator = link.includes('?') ? '&' : '?';
      paymentUrl = `${link}${separator}prefilled_email=${encodeURIComponent(user.email)}`;
    }
    window.open(paymentUrl, '_blank');
  };

  const handlePaypalSubscribe = async (planType) => {
    if (!user) {
      toast.error('Please log in to subscribe with PayPal');
      return;
    }

    setProcessingPaypal(planType);
    
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL;
      const returnUrl = `${window.location.origin}/pricing?paypal=success`;
      const cancelUrl = `${window.location.origin}/pricing?paypal=cancelled`;
      
      const response = await api.post('/paypal/create-checkout', {
        plan_type: planType,
        return_url: returnUrl,
        cancel_url: cancelUrl
      });
      
      if (response.data.success && response.data.redirect_url) {
        window.location.href = response.data.redirect_url;
      } else {
        toast.error(response.data.error || 'Failed to create PayPal checkout');
      }
    } catch (error) {
      console.error('PayPal checkout error:', error);
      toast.error(error.response?.data?.detail || 'Failed to initiate PayPal checkout');
    } finally {
      setProcessingPaypal(null);
    }
  };

  // Handle PayPal return
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const paypalStatus = urlParams.get('paypal');
    
    if (paypalStatus === 'success') {
      toast.success('Payment successful! Your subscription is now active.');
      // Clean up URL
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (paypalStatus === 'cancelled') {
      toast.info('Payment cancelled');
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  const plans = [
    {
      id: 'trial',
      name: '7-Day FREE Trial',
      price: '$0',
      period: '7 days',
      description: 'Try premium features risk-free',
      linkKey: 'trial_link',
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
      linkKey: 'monthly_link',
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
      linkKey: 'yearly_link',
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

      {/* Pricing Cards */}
      <div className="grid md:grid-cols-3 gap-6 max-w-6xl mx-auto">
        {plans.map((plan) => {
          const colors = getColorClasses(plan.color);
          const Icon = plan.icon;
          const stripeLink = subscriptionLinks?.[plan.linkKey];
          const paypalEnabled = paypalConfig?.enabled;
          
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
                    onClick={() => handleStripeSubscribe(stripeLink)}
                    disabled={loading || !stripeLink}
                    className={`w-full ${colors.button} text-white font-medium py-5`}
                    data-testid={`subscribe-stripe-${plan.id}`}
                  >
                    <CreditCard className="w-4 h-4 mr-2" />
                    {plan.buttonText}
                  </Button>
                  
                  {/* PayPal Button - only show if PayPal is enabled */}
                  {paypalEnabled && (
                    <Button
                      onClick={() => handlePaypalSubscribe(plan.id)}
                      disabled={loading || processingPaypal === plan.id || !user}
                      variant="outline"
                      className="w-full border-blue-500/50 text-blue-400 hover:bg-blue-500/10 py-5"
                      data-testid={`subscribe-paypal-${plan.id}`}
                    >
                      {processingPaypal === plan.id ? (
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      ) : (
                        <svg className="w-4 h-4 mr-2" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M7.076 21.337H2.47a.641.641 0 0 1-.633-.74L4.944.901C5.026.382 5.474 0 5.998 0h7.46c2.57 0 4.578.543 5.69 1.81 1.01 1.15 1.304 2.42 1.012 4.287-.023.143-.047.288-.077.437-.983 5.05-4.349 6.797-8.647 6.797H9.21c-.426 0-.794.31-.858.73L7.076 21.337z"/>
                        </svg>
                      )}
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
          {paypalConfig?.enabled && (
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
