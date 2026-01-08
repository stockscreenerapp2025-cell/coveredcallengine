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
  ArrowRight
} from 'lucide-react';

const Pricing = () => {
  const { user } = useAuth();
  const [subscriptionLinks, setSubscriptionLinks] = useState(null);
  const [loading, setLoading] = useState(true);

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

  const handleSubscribe = (link) => {
    if (!link) return;
    // Add user email to the payment link if user is logged in
    let paymentUrl = link;
    if (user?.email) {
      const separator = link.includes('?') ? '&' : '?';
      paymentUrl = `${link}${separator}prefilled_email=${encodeURIComponent(user.email)}`;
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
          const link = subscriptionLinks?.[plan.linkKey];
          
          return (
            <Card 
              key={plan.id}
              className={`glass-card relative overflow-hidden transition-all duration-300 hover:scale-[1.02] ${
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
              
              <CardContent className="space-y-6 relative">
                {/* Price */}
                <div className="text-center">
                  <span className="text-4xl font-bold text-white">{plan.price}</span>
                  <span className="text-zinc-500 ml-1">{plan.period}</span>
                </div>
                
                {/* Features */}
                <ul className="space-y-3">
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
                
                {/* CTA Button */}
                <Button
                  onClick={() => handleSubscribe(link)}
                  disabled={loading || !link}
                  className={`w-full ${colors.button} text-white font-medium py-6`}
                  data-testid={`subscribe-btn-${plan.id}`}
                >
                  {plan.buttonText}
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
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
