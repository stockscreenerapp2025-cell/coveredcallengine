import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '../components/ui/button';
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
  Settings
} from 'lucide-react';

const Landing = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

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

  return (
    <div className="min-h-screen bg-[#09090b]">
      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 glass border-b border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-8 h-8 text-violet-500" />
              <span className="text-xl font-bold text-white">Premium Hunter</span>
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
                    className="text-zinc-400 hover:text-white"
                    data-testid="login-btn"
                  >
                    Sign In
                  </Button>
                  <Button 
                    onClick={() => navigate('/register')}
                    className="btn-primary"
                    data-testid="get-started-btn"
                  >
                    Get Started
                  </Button>
                </>
              )}
            </div>
          </div>
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
              Hunt Premium with
              <span className="block text-transparent bg-clip-text bg-gradient-to-r from-violet-400 to-cyan-400">
                Covered Calls & PMCC
              </span>
            </h1>
            
            <p className="text-lg sm:text-xl text-zinc-400 max-w-3xl mx-auto mb-10 animate-fade-in stagger-2">
              Professional-grade options screening platform for identifying, analyzing, 
              and managing covered call and Poor Man's Covered Call strategies with real-time data and AI insights.
            </p>
            
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 animate-fade-in stagger-3">
              <Button 
                size="lg"
                onClick={() => navigate('/register')}
                className="btn-primary text-lg px-8 py-6 animate-pulse-glow"
                data-testid="hero-get-started-btn"
              >
                Start Hunting Premium
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

      {/* CTA Section */}
      <section className="py-20 relative">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <div className="glass-card p-12 neon-glow">
            <Shield className="w-12 h-12 text-violet-400 mx-auto mb-6" />
            <h2 className="text-3xl font-bold text-white mb-4">
              Ready to Start Hunting Premium?
            </h2>
            <p className="text-zinc-400 mb-8 max-w-xl mx-auto">
              Join thousands of traders using Premium Hunter to find the best covered call and PMCC opportunities.
            </p>
            <Button 
              size="lg"
              onClick={() => navigate('/register')}
              className="btn-primary text-lg px-8"
              data-testid="cta-get-started-btn"
            >
              Get Started Free
              <ChevronRight className="w-5 h-5 ml-2" />
            </Button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-violet-500" />
              <span className="text-sm text-zinc-500">© 2025 Premium Hunter. All rights reserved.</span>
            </div>
            <div className="flex items-center gap-6 text-sm text-zinc-500">
              <span>Powered by Polygon.io & OpenAI</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
