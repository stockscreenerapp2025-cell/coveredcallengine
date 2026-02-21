import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import api from '../lib/api';
import AIChatbot from '../components/AIChatbot';
import { 
  TrendingUp, 
  Shield, 
  Zap, 
  BarChart3, 
  Target, 
  Brain,
  ChevronRight,
  LineChart,
  Wallet,
  Settings,
  Activity,
  Crown,
  Clock,
  Check,
  Star,
  Sparkles,
  ArrowRight,
  Mail,
  Send,
  MessageSquare,
  Menu,
  X
} from 'lucide-react';
import { Input } from '../components/ui/input';
import { toast } from 'sonner';

const APP_NAME = "Covered Call Engine";

const Landing = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [subscriptionLinks, setSubscriptionLinks] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [contactForm, setContactForm] = useState({ name: '', email: '', subject: '', message: '' });
  const [sendingContact, setSendingContact] = useState(false);

  useEffect(() => {
    fetchSubscriptionLinks();
  }, []);

  const fetchSubscriptionLinks = async () => {
    try {
      const response = await api.get('/subscription/links');
      setSubscriptionLinks(response.data);
    } catch (error) {
      console.error('Failed to fetch subscription links:', error);
    }
  };

  const scrollToPricing = () => {
    const pricingSection = document.getElementById('pricing');
    if (pricingSection) {
      pricingSection.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const scrollToContact = () => {
    const contactSection = document.getElementById('contact');
    if (contactSection) {
      contactSection.scrollIntoView({ behavior: 'smooth' });
    }
    setMobileMenuOpen(false);
  };

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    setMobileMenuOpen(false);
  };

  const handleContactSubmit = async (e) => {
    e.preventDefault();
    if (!contactForm.name || !contactForm.email || !contactForm.message) {
      toast.error('Please fill in all required fields');
      return;
    }
    
    setSendingContact(true);
    try {
      await api.post('/contact', contactForm);
      toast.success('Message sent successfully! We\'ll get back to you soon.');
      setContactForm({ name: '', email: '', subject: '', message: '' });
    } catch (error) {
      toast.error('Failed to send message. Please try again.');
    } finally {
      setSendingContact(false);
    }
  };

  const handleSubscribe = (link) => {
    if (!link) return;
    window.open(link, '_blank');
  };

  const features = [
    {
      icon: <Target className="w-6 h-6" />,
      title: "Covered Call Screener",
      description: "Find optimal covered call opportunities with advanced filtering for ROI, delta, IV rank, and more."
    },
    {
      icon: <LineChart className="w-6 h-6" />,
      title: "PMCC Strategy Builder",
      description: "Identify Poor Man's Covered Call setups with LEAPS and short call recommendations."
    },
    {
      icon: <Brain className="w-6 h-6" />,
      title: "AI-Powered Insights",
      description: "Get trade recommendations, risk analysis, and roll suggestions powered by GPT-5.2."
    },
    {
      icon: <Wallet className="w-6 h-6" />,
      title: "Portfolio Tracking",
      description: "Track positions, calculate P/L, and manage assignment risk with CSV import support."
    },
    {
      icon: <BarChart3 className="w-6 h-6" />,
      title: "Real-Time Data",
      description: "Access live market data, options chains, and news via Polygon.io integration."
    },
    {
      icon: <Settings className="w-6 h-6" />,
      title: "Custom Filters",
      description: "Build and save custom screening filters tailored to your trading strategy."
    }
  ];

  const stats = [
    { value: "50+", label: "Screening Criteria" },
    { value: "Real-time", label: "Market Data" },
    { value: "AI", label: "Trade Analysis" },
    { value: "24/7", label: "Monitoring" }
  ];

  const plans = [
    {
      id: 'basic',
      name: 'Basic',
      price: '$29',
      period: '/month',
      description: 'Essential tools for new traders',
      linkKey: 'basic_monthly_link',
      popular: false,
      aiTokens: '2,000',
      features: [
        'Covered Call Dashboard',
        'Covered Call Scans',
        'Real Market Data',
        'TradingView Integration Charts',
        '2,000 AI tokens/month'
      ],
      icon: Clock,
      color: 'emerald',
      buttonText: 'GET STARTED'
    },
    {
      id: 'standard',
      name: 'Standard',
      price: '$59',
      period: '/month',
      description: 'Perfect for active traders',
      linkKey: 'standard_monthly_link',
      popular: true,
      aiTokens: '6,000',
      features: [
        'Everything in Basic',
        'PMCC Strategy Scanner',
        'Powerful Watch List with AI Features',
        'Portfolio Tracker',
        '6,000 AI tokens/month'
      ],
      icon: Zap,
      color: 'violet',
      buttonText: 'GET STARTED'
    },
    {
      id: 'premium',
      name: 'Premium',
      price: '$89',
      period: '/month',
      description: 'Full suite for serious traders',
      linkKey: 'premium_monthly_link',
      popular: false,
      aiTokens: '15,000',
      features: [
        'Everything in Standard',
        'Powerful Simulator and Analyser',
        'AI Management of Trades',
        '15,000 AI tokens/month'
      ],
      icon: Crown,
      color: 'amber',
      buttonText: 'GET STARTED'
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
        glow: 'shadow-emerald-500/20'
      },
      violet: {
        bg: 'bg-violet-500/10',
        border: 'border-violet-500/50',
        text: 'text-violet-400',
        button: 'bg-violet-600 hover:bg-violet-700',
        badge: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
        gradient: 'from-violet-500/20 to-transparent',
        glow: 'shadow-violet-500/30'
      },
      amber: {
        bg: 'bg-amber-500/10',
        border: 'border-amber-500/30',
        text: 'text-amber-400',
        button: 'bg-amber-600 hover:bg-amber-700',
        badge: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
        gradient: 'from-amber-500/20 to-transparent',
        glow: 'shadow-amber-500/20'
      }
    };
    return colors[color] || colors.emerald;
  };

  return (
    <div className="min-h-screen bg-[#09090b]">
      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 glass border-b border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-2 cursor-pointer" onClick={scrollToTop}>
              <Activity className="w-8 h-8 text-emerald-500" />
              <span className="text-xl font-bold text-white">{APP_NAME}</span>
            </div>
            
            {/* Desktop Navigation */}
            <div className="hidden md:flex items-center gap-6">
              <button onClick={scrollToTop} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium">
                Home
              </button>
              <button onClick={scrollToPricing} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium">
                Pricing
              </button>
              <button onClick={() => navigate('/terms')} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium">
                Terms
              </button>
              <button onClick={() => navigate('/privacy')} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium">
                Privacy
              </button>
              <button onClick={scrollToContact} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium">
                Contact
              </button>
            </div>
            
            <div className="flex items-center gap-4">
              {isAuthenticated ? (
                <Button 
                  onClick={() => navigate('/dashboard')}
                  className="btn-primary"
                  data-testid="go-to-dashboard-btn"
                >
                  Go to Dashboard
                </Button>
              ) : (
                <>
                  <Button 
                    variant="ghost" 
                    onClick={() => navigate('/login')}
                    className="text-zinc-400 hover:text-white hidden sm:inline-flex"
                    data-testid="login-btn"
                  >
                    Sign In
                  </Button>
                  <Button 
                    onClick={scrollToPricing}
                    className="btn-primary hidden sm:inline-flex"
                    data-testid="get-started-btn"
                  >
                    Get Started
                  </Button>
                </>
              )}
              
              {/* Mobile menu button */}
              <button 
                className="md:hidden text-zinc-400 hover:text-white p-2"
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              >
                {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
              </button>
            </div>
          </div>
          
          {/* Mobile Navigation */}
          {mobileMenuOpen && (
            <div className="md:hidden py-4 border-t border-white/5">
              <div className="flex flex-col gap-3">
                <button onClick={scrollToTop} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium text-left py-2">
                  Home
                </button>
                <button onClick={() => { scrollToPricing(); setMobileMenuOpen(false); }} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium text-left py-2">
                  Pricing
                </button>
                <button onClick={() => { navigate('/terms'); setMobileMenuOpen(false); }} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium text-left py-2">
                  Terms
                </button>
                <button onClick={() => { navigate('/privacy'); setMobileMenuOpen(false); }} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium text-left py-2">
                  Privacy
                </button>
                <button onClick={scrollToContact} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium text-left py-2">
                  Contact
                </button>
                {!isAuthenticated && (
                  <>
                    <button onClick={() => { navigate('/login'); setMobileMenuOpen(false); }} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium text-left py-2">
                      Sign In
                    </button>
                    <Button onClick={() => { scrollToPricing(); setMobileMenuOpen(false); }} className="btn-primary mt-2">
                      Get Started
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative pt-32 pb-20 overflow-hidden hero-gradient">
        <div className="absolute inset-0 grid-bg opacity-50" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-violet-500/10 border border-violet-500/30 mb-6 animate-fade-in">
              <Zap className="w-4 h-4 text-violet-400" />
              <span className="text-sm text-violet-300">AI-Powered Options Analysis</span>
            </div>
            
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-white mb-6 animate-fade-in stagger-1">
              Find the Best
              <span className="block text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-400">
                Covered Call Opportunities
              </span>
            </h1>
            
            <p className="text-lg sm:text-xl text-zinc-400 max-w-3xl mx-auto mb-10 animate-fade-in stagger-2">
              Professional-grade options screening engine with advanced filters for technicals, fundamentals, 
              and Greeks. Find optimal covered call and PMCC setups with AI-powered insights.
            </p>
            
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 animate-fade-in stagger-3">
              <Button 
                size="lg"
                onClick={scrollToPricing}
                className="bg-emerald-600 hover:bg-emerald-700 text-white text-lg px-8 py-6 shadow-[0_0_20px_rgba(16,185,129,0.3)] hover:shadow-[0_0_30px_rgba(16,185,129,0.5)]"
                data-testid="hero-get-started-btn"
              >
                Start Free Trial
                <ChevronRight className="w-5 h-5 ml-2" />
              </Button>
              <Button 
                size="lg"
                variant="outline"
                onClick={() => navigate('/login')}
                className="btn-outline text-lg px-8 py-6"
                data-testid="hero-sign-in-btn"
              >
                Sign In
              </Button>
            </div>
          </div>

          {/* Stats */}
          <div className="mt-20 grid grid-cols-2 md:grid-cols-4 gap-6 animate-fade-in stagger-4">
            {stats.map((stat, index) => (
              <div key={index} className="text-center p-6 glass-card">
                <div className="text-3xl font-bold text-white mb-1">{stat.value}</div>
                <div className="text-sm text-zinc-500">{stat.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 relative">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold text-white mb-4">
              Everything You Need to Hunt Premium
            </h2>
            <p className="text-zinc-400 max-w-2xl mx-auto">
              Comprehensive tools for options traders looking to generate consistent income through covered calls and PMCC strategies.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((feature, index) => (
              <div 
                key={index} 
                className="glass-card p-6 card-hover animate-fade-in"
                style={{ animationDelay: `${index * 0.1}s` }}
              >
                <div className="w-12 h-12 rounded-lg bg-violet-500/10 border border-violet-500/30 flex items-center justify-center text-violet-400 mb-4">
                  {feature.icon}
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">{feature.title}</h3>
                <p className="text-zinc-400 text-sm">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="py-20 relative">
        <div className="absolute inset-0 bg-gradient-to-b from-violet-500/5 to-transparent" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          {/* Pricing Header */}
          <div className="text-center max-w-3xl mx-auto mb-16">
            <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 mb-4">
              <Sparkles className="w-3 h-3 mr-1" />
              Premium Access
            </Badge>
            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
              Choose Your Plan
            </h2>
            <p className="text-zinc-400 text-lg">
              Get access to professional-grade options screening tools, real-time data, and AI-powered insights.
            </p>
          </div>

          {/* Pricing Cards */}
          <div className="grid md:grid-cols-3 gap-6 lg:gap-8 max-w-5xl mx-auto">
            {plans.map((plan) => {
              const colors = getColorClasses(plan.color);
              const Icon = plan.icon;
              const link = subscriptionLinks?.[plan.linkKey];
              
              return (
                <Card 
                  key={plan.id}
                  className={`glass-card relative overflow-hidden transition-all duration-300 hover:scale-[1.02] h-full flex flex-col ${
                    plan.popular ? `border-2 ${colors.border} shadow-lg ${colors.glow}` : 'border-zinc-800'
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
                  
                  <CardContent className="p-6 relative h-full flex flex-col">
                    {/* Icon & Title */}
                    <div className="text-center mb-6">
                      <div className={`w-14 h-14 mx-auto mb-4 rounded-xl ${colors.bg} border ${colors.border} flex items-center justify-center`}>
                        <Icon className={`w-7 h-7 ${colors.text}`} />
                      </div>
                      <h3 className="text-xl font-bold text-white mb-1">{plan.name}</h3>
                      <p className="text-sm text-zinc-500">{plan.description}</p>
                    </div>
                    
                    {/* Price */}
                    <div className="text-center mb-6">
                      <span className="text-4xl font-bold text-white">{plan.price}</span>
                      <span className="text-zinc-500 ml-1">{plan.period}</span>
                    </div>
                    
                    {/* Features */}
                    <ul className="space-y-3 mb-8 flex-grow">
                      {plan.features.map((feature, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-sm">
                          <Check className={`w-4 h-4 ${colors.text} flex-shrink-0 mt-0.5`} />
                          <span className="text-zinc-300">{feature}</span>
                        </li>
                      ))}
                    </ul>
                    
                    {/* CTA Button */}
                    <Button
                      onClick={() => handleSubscribe(link)}
                      className={`w-full ${colors.button} text-white font-bold py-6 text-base tracking-wide mt-auto`}
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

          {/* AI Credits Info */}
          <div className="max-w-3xl mx-auto mt-8">
            <Card className="glass-card border-amber-500/20">
              <CardContent className="p-6 text-center">
                <div className="flex items-center justify-center gap-2 mb-3">
                  <Sparkles className="w-5 h-5 text-amber-400" />
                  <h3 className="text-lg font-semibold text-white">AI Credits Included</h3>
                </div>
                <p className="text-zinc-400 mb-4 text-sm">
                  All plans include free monthly AI credits. Use AI only if you want. Buy more credits anytime — no surprises.
                </p>
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div className="bg-zinc-800/50 rounded-lg p-2">
                    <p className="text-zinc-400 text-xs">Basic</p>
                    <p className="text-white font-bold text-sm">2,000/mo</p>
                  </div>
                  <div className="bg-zinc-800/50 rounded-lg p-2 border border-violet-500/20">
                    <p className="text-zinc-400 text-xs">Standard</p>
                    <p className="text-white font-bold text-sm">6,000/mo</p>
                  </div>
                  <div className="bg-zinc-800/50 rounded-lg p-2">
                    <p className="text-zinc-400 text-xs">Premium</p>
                    <p className="text-white font-bold text-sm">15,000/mo</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Trust Badges */}
          <div className="text-center mt-12 text-zinc-500 text-sm">
            <p className="flex items-center justify-center gap-6 flex-wrap">
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
      </section>

      {/* CTA Section */}
      <section className="py-20 relative">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <div className="glass-card p-12 neon-glow">
            <Shield className="w-12 h-12 text-emerald-400 mx-auto mb-6" />
            <h2 className="text-3xl font-bold text-white mb-4">
              Ready to Find Your Next Trade?
            </h2>
            <p className="text-zinc-400 mb-8 max-w-xl mx-auto">
              Join thousands of traders using {APP_NAME} to find the best covered call and PMCC opportunities.
            </p>
            <Button 
              size="lg"
              onClick={scrollToPricing}
              className="btn-primary text-lg px-8"
              data-testid="cta-get-started-btn"
            >
              Get Started Now
              <ChevronRight className="w-5 h-5 ml-2" />
            </Button>
          </div>
        </div>
      </section>

      {/* Contact Section */}
      <section id="contact" className="py-20 relative">
        <div className="absolute inset-0 bg-gradient-to-b from-emerald-500/5 to-transparent" />
        <div className="relative max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 mb-4">
              <MessageSquare className="w-3 h-3 mr-1" />
              Get in Touch
            </Badge>
            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
              Contact Us
            </h2>
            <p className="text-zinc-400 text-lg max-w-2xl mx-auto">
              Have questions about our platform? Need help with your subscription? Our support team is here to help.
            </p>
          </div>

          <div className="glass-card p-8">
            <form onSubmit={handleContactSubmit} className="space-y-6">
              <div className="grid md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium text-zinc-400 mb-2">
                    Your Name <span className="text-red-400">*</span>
                  </label>
                  <Input
                    type="text"
                    value={contactForm.name}
                    onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })}
                    placeholder="John Doe"
                    className="input-dark"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-zinc-400 mb-2">
                    Email Address <span className="text-red-400">*</span>
                  </label>
                  <Input
                    type="email"
                    value={contactForm.email}
                    onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
                    placeholder="john@example.com"
                    className="input-dark"
                    required
                  />
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-zinc-400 mb-2">
                  Subject
                </label>
                <Input
                  type="text"
                  value={contactForm.subject}
                  onChange={(e) => setContactForm({ ...contactForm, subject: e.target.value })}
                  placeholder="How can we help you?"
                  className="input-dark"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-zinc-400 mb-2">
                  Message <span className="text-red-400">*</span>
                </label>
                <textarea
                  value={contactForm.message}
                  onChange={(e) => setContactForm({ ...contactForm, message: e.target.value })}
                  placeholder="Tell us more about your inquiry..."
                  rows={5}
                  className="w-full px-4 py-3 rounded-lg bg-zinc-800/50 border border-zinc-700 text-white placeholder-zinc-500 focus:outline-none focus:border-emerald-500 resize-none"
                  required
                />
              </div>
              
              <Button
                type="submit"
                disabled={sendingContact}
                className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-6 text-lg font-semibold"
              >
                {sendingContact ? (
                  <>
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
                    Sending...
                  </>
                ) : (
                  <>
                    <Send className="w-5 h-5 mr-2" />
                    Send Message
                  </>
                )}
              </Button>
            </form>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid md:grid-cols-4 gap-8 mb-8">
            {/* Brand */}
            <div className="md:col-span-2">
              <div className="flex items-center gap-2 mb-4">
                <Activity className="w-6 h-6 text-emerald-500" />
                <span className="text-lg font-bold text-white">{APP_NAME}</span>
              </div>
              <p className="text-zinc-500 text-sm max-w-md">
                Professional-grade options screening engine with advanced filters for technicals, fundamentals, and Greeks. Find optimal covered call and PMCC setups.
              </p>
            </div>
            
            {/* Quick Links */}
            <div>
              <h4 className="text-white font-semibold mb-4">Quick Links</h4>
              <ul className="space-y-2">
                <li>
                  <button onClick={scrollToTop} className="text-zinc-500 hover:text-emerald-400 text-sm transition-colors">
                    Home
                  </button>
                </li>
                <li>
                  <button onClick={scrollToPricing} className="text-zinc-500 hover:text-emerald-400 text-sm transition-colors">
                    Pricing
                  </button>
                </li>
                <li>
                  <button onClick={scrollToContact} className="text-zinc-500 hover:text-emerald-400 text-sm transition-colors">
                    Contact
                  </button>
                </li>
              </ul>
            </div>
            
            {/* Legal */}
            <div>
              <h4 className="text-white font-semibold mb-4">Legal</h4>
              <ul className="space-y-2">
                <li>
                  <button onClick={() => navigate('/terms')} className="text-zinc-500 hover:text-emerald-400 text-sm transition-colors">
                    Terms & Conditions
                  </button>
                </li>
                <li>
                  <button onClick={() => navigate('/privacy')} className="text-zinc-500 hover:text-emerald-400 text-sm transition-colors">
                    Privacy Policy
                  </button>
                </li>
              </ul>
            </div>
          </div>
          
          {/* Bottom */}
          <div className="pt-8 border-t border-white/5">
            <div className="flex flex-col md:flex-row items-center justify-between gap-4">
              <span className="text-sm text-zinc-500">© 2025 {APP_NAME}. All rights reserved.</span>
              <div className="flex items-center gap-6 text-sm text-zinc-500">
                <span className="flex items-center gap-1">
                  <Shield className="w-4 h-4 text-emerald-400" />
                  Secure Payment via Stripe
                </span>
              </div>
            </div>
          </div>
        </div>
      </footer>
      
      {/* AI Chatbot */}
      <AIChatbot />
    </div>
  );
};

export default Landing;
