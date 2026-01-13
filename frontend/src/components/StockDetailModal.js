import { useState, useEffect, useRef, memo } from 'react';
import { stocksApi, newsApi } from '../lib/api';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Button } from '../components/ui/button';
import {
  TrendingUp,
  TrendingDown,
  Newspaper,
  BarChart3,
  Activity,
  ExternalLink,
  Building2,
  Users,
  Globe,
  Calendar,
  AlertTriangle,
  Shield,
  DollarSign,
  Target,
  Sparkles,
  Loader2
} from 'lucide-react';

// Custom TradingView Chart component with SMA 50 and 200
const TradingViewChart = memo(({ symbol }) => {
  const containerRef = useRef(null);
  
  useEffect(() => {
    if (!containerRef.current || !symbol) return;
    
    // Clear previous widget
    containerRef.current.innerHTML = '';
    
    // Create widget container
    const widgetContainer = document.createElement('div');
    widgetContainer.className = 'tradingview-widget-container';
    widgetContainer.style.height = '100%';
    widgetContainer.style.width = '100%';
    
    const innerContainer = document.createElement('div');
    innerContainer.className = 'tradingview-widget-container__widget';
    innerContainer.style.height = '100%';
    innerContainer.style.width = '100%';
    widgetContainer.appendChild(innerContainer);
    
    // Create and configure script
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: symbol,
      interval: "D",
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "en",
      enable_publishing: false,
      backgroundColor: "rgba(24, 24, 27, 1)",
      gridColor: "rgba(42, 46, 57, 0.3)",
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      calendar: false,
      hide_volume: false,
      support_host: "https://www.tradingview.com",
      range: "12M",
      studies: [
        {
          id: "MASimple@tv-basicstudies",
          inputs: { length: 50 },
          styles: { 
            "plot.color": "#FACC15",
            "plot.linewidth": 2
          }
        },
        {
          id: "MASimple@tv-basicstudies", 
          inputs: { length: 200 },
          styles: {
            "plot.color": "#3B82F6",
            "plot.linewidth": 2
          }
        }
      ]
    });
    
    widgetContainer.appendChild(script);
    containerRef.current.appendChild(widgetContainer);
    
    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [symbol]);
  
  return <div ref={containerRef} style={{ height: '100%', width: '100%' }} />;
});

const StockDetailModal = ({ symbol, isOpen, onClose, scanData = null }) => {
  const [stockData, setStockData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sentimentData, setSentimentData] = useState(null);
  const [analyzingSentiment, setAnalyzingSentiment] = useState(false);

  useEffect(() => {
    if (isOpen && symbol) {
      fetchStockData();
      setSentimentData(null); // Reset sentiment when modal opens
    }
  }, [isOpen, symbol]);

  const fetchStockData = async () => {
    setLoading(true);
    try {
      const response = await stocksApi.getDetails(symbol);
      setStockData(response.data);
    } catch (error) {
      console.error('Failed to fetch stock details:', error);
    } finally {
      setLoading(false);
    }
  };

  const analyzeSentiment = async () => {
    if (!stockData?.news?.length) return;
    
    setAnalyzingSentiment(true);
    try {
      const response = await newsApi.analyzeSentiment(stockData.news);
      setSentimentData(response.data);
    } catch (error) {
      console.error('Failed to analyze sentiment:', error);
    } finally {
      setAnalyzingSentiment(false);
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const formatNumber = (num) => {
    if (!num) return 'N/A';
    if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
    if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
    if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
    return num.toLocaleString();
  };

  // Merge API data with pre-computed scan data
  const getTechnicals = () => {
    const apiTechnicals = stockData?.technicals || {};
    if (scanData) {
      return {
        ...apiTechnicals,
        sma_50: scanData.sma50 || apiTechnicals.sma_50,
        sma_200: scanData.sma200 || apiTechnicals.sma_200,
        rsi: scanData.rsi14 || apiTechnicals.rsi,
        atr_pct: scanData.atr_pct,
        delta: scanData.delta,
        above_sma_50: scanData.sma50 ? stockData?.price > scanData.sma50 : apiTechnicals.above_sma_50,
        above_sma_200: scanData.sma200 ? stockData?.price > scanData.sma200 : apiTechnicals.above_sma_200,
        sma_50_above_200: scanData.sma50 && scanData.sma200 ? scanData.sma50 > scanData.sma200 : apiTechnicals.sma_50_above_200,
        trend: scanData.sma50 && scanData.sma200 
          ? (scanData.sma50 > scanData.sma200 ? 'bullish' : 'bearish') 
          : apiTechnicals.trend
      };
    }
    return apiTechnicals;
  };

  const getFundamentals = () => {
    const apiFundamentals = stockData?.fundamentals || {};
    if (scanData) {
      return {
        ...apiFundamentals,
        market_cap: scanData.market_cap || apiFundamentals.market_cap,
        eps_ttm: scanData.eps_ttm,
        roe: scanData.roe,
        debt_to_equity: scanData.debt_to_equity,
        days_to_earnings: scanData.days_to_earnings,
        sector: scanData.sector || apiFundamentals.sector
      };
    }
    return apiFundamentals;
  };

  const technicals = getTechnicals();
  const fundamentals = getFundamentals();

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-7xl max-h-[90vh] overflow-hidden bg-zinc-900 border-zinc-700">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3 text-xl">
            <span className="text-white font-bold">{symbol}</span>
            {stockData && (
              <>
                <span className="text-zinc-400 font-normal text-lg">
                  {stockData.fundamentals?.name || symbol}
                </span>
                <span className="text-2xl font-mono text-white">
                  ${stockData.price?.toFixed(2)}
                </span>
                <Badge className={stockData.change >= 0 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}>
                  {stockData.change >= 0 ? <TrendingUp className="w-3 h-3 mr-1" /> : <TrendingDown className="w-3 h-3 mr-1" />}
                  {stockData.change >= 0 ? '+' : ''}{stockData.change_pct?.toFixed(2)}%
                </Badge>
              </>
            )}
          </DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 h-[calc(90vh-120px)] overflow-hidden">
          {/* TradingView Chart - 2/3 width */}
          <div className="lg:col-span-2 h-[500px] lg:h-full rounded-lg overflow-hidden border border-zinc-700 bg-zinc-900">
            {isOpen && symbol && (
              <TradingViewChart symbol={symbol} />
            )}
          </div>

          {/* Right Panel - 1/3 width */}
          <div className="lg:col-span-1 overflow-y-auto space-y-4 pr-2">
            {loading ? (
              <div className="space-y-4">
                <Skeleton className="h-32" />
                <Skeleton className="h-48" />
                <Skeleton className="h-64" />
              </div>
            ) : stockData && (
              <Tabs defaultValue="technicals" className="w-full">
                <TabsList className="grid w-full grid-cols-3 bg-zinc-800">
                  <TabsTrigger value="technicals" className="text-xs">Technicals</TabsTrigger>
                  <TabsTrigger value="fundamentals" className="text-xs">Fundamentals</TabsTrigger>
                  <TabsTrigger value="news" className="text-xs">News</TabsTrigger>
                </TabsList>

                {/* Technical Indicators Tab */}
                <TabsContent value="technicals" className="space-y-4 mt-4">
                  <Card className="bg-zinc-800/50 border-zinc-700">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <Activity className="w-4 h-4 text-cyan-400" />
                        Technical Indicators
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {/* SMA Indicators */}
                      <div className="grid grid-cols-2 gap-3">
                        <div className="p-3 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500 mb-1">SMA 50</div>
                          <div className="text-lg font-mono text-yellow-400">
                            ${technicals?.sma_50?.toFixed(2) || 'N/A'}
                          </div>
                          {(technicals?.above_sma_50 !== undefined || (stockData?.price && technicals?.sma_50)) && (
                            <div className={`text-xs ${
                              technicals?.above_sma_50 || (stockData?.price > technicals?.sma_50) 
                                ? 'text-emerald-400' : 'text-red-400'
                            }`}>
                              Price {technicals?.above_sma_50 || (stockData?.price > technicals?.sma_50) ? 'Above ↑' : 'Below ↓'}
                            </div>
                          )}
                        </div>
                        <div className="p-3 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500 mb-1">SMA 200</div>
                          <div className="text-lg font-mono text-blue-400">
                            ${technicals?.sma_200?.toFixed(2) || 'N/A'}
                          </div>
                          {(technicals?.above_sma_200 !== undefined || (stockData?.price && technicals?.sma_200)) && (
                            <div className={`text-xs ${
                              technicals?.above_sma_200 || (stockData?.price > technicals?.sma_200) 
                                ? 'text-emerald-400' : 'text-red-400'
                            }`}>
                              Price {technicals?.above_sma_200 || (stockData?.price > technicals?.sma_200) ? 'Above ↑' : 'Below ↓'}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* RSI */}
                      <div className="p-3 rounded bg-zinc-900/50">
                        <div className="flex justify-between items-center mb-2">
                          <span className="text-xs text-zinc-500">RSI (14)</span>
                          <span className={`text-lg font-mono ${
                            technicals?.rsi > 70 ? 'text-red-400' : 
                            technicals?.rsi < 30 ? 'text-emerald-400' : 'text-white'
                          }`}>
                            {technicals?.rsi?.toFixed(1) || 'N/A'}
                          </span>
                        </div>
                        <div className="h-2 bg-zinc-700 rounded-full overflow-hidden">
                          <div 
                            className={`h-full ${
                              technicals?.rsi > 70 ? 'bg-red-500' : 
                              technicals?.rsi < 30 ? 'bg-emerald-500' : 'bg-violet-500'
                            }`}
                            style={{ width: `${Math.min(technicals?.rsi || 0, 100)}%` }}
                          />
                        </div>
                        <div className="flex justify-between text-xs text-zinc-500 mt-1">
                          <span>Oversold</span>
                          <span>Overbought</span>
                        </div>
                      </div>

                      {/* ATR% and Delta - from scan data */}
                      {(technicals?.atr_pct !== undefined || technicals?.delta !== undefined) && (
                        <div className="grid grid-cols-2 gap-3">
                          {technicals?.atr_pct !== undefined && (
                            <div className="p-3 rounded bg-zinc-900/50">
                              <div className="text-xs text-zinc-500 mb-1">ATR %</div>
                              <div className={`text-lg font-mono ${
                                technicals.atr_pct > 4 ? 'text-orange-400' : 
                                technicals.atr_pct > 2.5 ? 'text-yellow-400' : 'text-emerald-400'
                              }`}>
                                {technicals.atr_pct?.toFixed(2)}%
                              </div>
                              <div className="text-xs text-zinc-500">
                                {technicals.atr_pct > 4 ? 'High Volatility' : 
                                 technicals.atr_pct > 2.5 ? 'Moderate' : 'Low Volatility'}
                              </div>
                            </div>
                          )}
                          {technicals?.delta !== undefined && (
                            <div className="p-3 rounded bg-zinc-900/50">
                              <div className="text-xs text-zinc-500 mb-1">Delta</div>
                              <div className="text-lg font-mono text-cyan-400">
                                {technicals.delta?.toFixed(2)}
                              </div>
                              <div className="text-xs text-zinc-500">
                                Prob OTM: {Math.round((1 - technicals.delta) * 100)}%
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Trend */}
                      <div className="p-3 rounded bg-zinc-900/50">
                        <div className="text-xs text-zinc-500 mb-2">Overall Trend</div>
                        <Badge className={`text-sm ${
                          technicals?.trend === 'bullish' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                          technicals?.trend === 'bearish' ? 'bg-red-500/20 text-red-400 border-red-500/30' :
                          'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                        }`}>
                          {technicals?.trend === 'bullish' && <TrendingUp className="w-3 h-3 mr-1" />}
                          {technicals?.trend === 'bearish' && <TrendingDown className="w-3 h-3 mr-1" />}
                          {technicals?.trend?.toUpperCase() || 'NEUTRAL'}
                        </Badge>
                        {technicals?.sma_50_above_200 !== undefined && (
                          <div className={`text-xs mt-2 ${technicals.sma_50_above_200 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {technicals.sma_50_above_200 ? '✓ Golden Cross (SMA50 > SMA200)' : '✗ Death Cross (SMA50 < SMA200)'}
                          </div>
                        )}
                      </div>

                      {/* Chart Legend */}
                      <div className="p-3 rounded bg-zinc-900/50">
                        <div className="text-xs text-zinc-500 mb-2">Chart Indicators Legend</div>
                        <div className="space-y-1 text-xs">
                          <div className="flex items-center gap-2">
                            <div className="w-4 h-0.5 bg-yellow-400"></div>
                            <span className="text-zinc-400">SMA 50</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="w-4 h-0.5 bg-blue-500"></div>
                            <span className="text-zinc-400">SMA 200</span>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* Fundamentals Tab */}
                <TabsContent value="fundamentals" className="space-y-4 mt-4">
                  <Card className="bg-zinc-800/50 border-zinc-700">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <Building2 className="w-4 h-4 text-emerald-400" />
                        Company Info
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {(stockData?.fundamentals?.name || fundamentals?.name) && (
                        <div>
                          <div className="text-xs text-zinc-500">Company Name</div>
                          <div className="text-white">{stockData?.fundamentals?.name || fundamentals?.name}</div>
                        </div>
                      )}
                      
                      {(stockData?.fundamentals?.sic_description || fundamentals?.sector) && (
                        <div>
                          <div className="text-xs text-zinc-500">Sector / Industry</div>
                          <div className="text-zinc-300 text-sm">
                            {fundamentals?.sector || stockData?.fundamentals?.sic_description}
                          </div>
                        </div>
                      )}

                      <div className="grid grid-cols-2 gap-3">
                        <div className="p-3 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500">Market Cap</div>
                          <div className="text-lg font-mono text-emerald-400">
                            {formatNumber(fundamentals?.market_cap || stockData?.fundamentals?.market_cap)}
                          </div>
                        </div>
                        <div className="p-3 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500">Employees</div>
                          <div className="text-lg font-mono text-white flex items-center gap-1">
                            <Users className="w-4 h-4 text-zinc-500" />
                            {stockData?.fundamentals?.employees?.toLocaleString() || 'N/A'}
                          </div>
                        </div>
                      </div>

                      {stockData?.fundamentals?.list_date && (
                        <div className="flex items-center gap-2 text-sm text-zinc-400">
                          <Calendar className="w-4 h-4" />
                          Listed: {formatDate(stockData.fundamentals.list_date)}
                        </div>
                      )}

                      {stockData?.fundamentals?.primary_exchange && (
                        <div className="flex items-center gap-2 text-sm text-zinc-400">
                          <BarChart3 className="w-4 h-4" />
                          Exchange: {stockData.fundamentals.primary_exchange}
                        </div>
                      )}

                      {stockData?.fundamentals?.homepage && (
                        <a 
                          href={stockData.fundamentals.homepage} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 text-sm text-cyan-400 hover:underline"
                        >
                          <Globe className="w-4 h-4" />
                          Company Website
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}

                      {stockData?.fundamentals?.description && (
                        <div>
                          <div className="text-xs text-zinc-500 mb-1">About</div>
                          <div className="text-xs text-zinc-400 line-clamp-4">
                            {stockData.fundamentals.description}
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  {/* Key Financial Metrics - Enhanced with scan data */}
                  <Card className="bg-zinc-800/50 border-zinc-700">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <DollarSign className="w-4 h-4 text-yellow-400" />
                        Key Financial Metrics
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-2 gap-3">
                        {fundamentals?.eps_ttm !== undefined && (
                          <div className="p-3 rounded bg-zinc-900/50">
                            <div className="text-xs text-zinc-500">EPS (TTM)</div>
                            <div className={`text-lg font-mono ${fundamentals.eps_ttm > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              ${fundamentals.eps_ttm?.toFixed(2)}
                            </div>
                            <div className="text-xs text-zinc-500">
                              {fundamentals.eps_ttm > 0 ? 'Profitable' : 'Loss Making'}
                            </div>
                          </div>
                        )}
                        {fundamentals?.roe !== undefined && fundamentals?.roe !== null && (
                          <div className="p-3 rounded bg-zinc-900/50">
                            <div className="text-xs text-zinc-500">ROE</div>
                            <div className={`text-lg font-mono ${fundamentals.roe > 15 ? 'text-emerald-400' : 'text-yellow-400'}`}>
                              {fundamentals.roe?.toFixed(1)}%
                            </div>
                            <div className="text-xs text-zinc-500">
                              {fundamentals.roe > 15 ? 'Strong' : fundamentals.roe > 10 ? 'Good' : 'Below Avg'}
                            </div>
                          </div>
                        )}
                        {fundamentals?.debt_to_equity !== undefined && fundamentals?.debt_to_equity !== null && (
                          <div className="p-3 rounded bg-zinc-900/50">
                            <div className="text-xs text-zinc-500">Debt/Equity</div>
                            <div className={`text-lg font-mono ${
                              fundamentals.debt_to_equity > 1.5 ? 'text-orange-400' : 
                              fundamentals.debt_to_equity > 1 ? 'text-yellow-400' : 'text-emerald-400'
                            }`}>
                              {fundamentals.debt_to_equity?.toFixed(2)}
                            </div>
                            <div className="text-xs text-zinc-500">
                              {fundamentals.debt_to_equity > 1.5 ? 'High Debt' : fundamentals.debt_to_equity > 1 ? 'Moderate' : 'Low Debt'}
                            </div>
                          </div>
                        )}
                        {fundamentals?.days_to_earnings !== undefined && fundamentals?.days_to_earnings !== null && (
                          <div className="p-3 rounded bg-zinc-900/50">
                            <div className="text-xs text-zinc-500">Next Earnings</div>
                            <div className={`text-lg font-mono ${
                              fundamentals.days_to_earnings < 14 ? 'text-orange-400' : 'text-zinc-300'
                            }`}>
                              {fundamentals.days_to_earnings >= 0 ? `${fundamentals.days_to_earnings}d` : 'Passed'}
                            </div>
                            <div className={`text-xs ${fundamentals.days_to_earnings < 14 ? 'text-orange-400' : 'text-zinc-500'}`}>
                              {fundamentals.days_to_earnings < 14 ? '⚠ Approaching' : 'No Binary Event'}
                            </div>
                          </div>
                        )}
                      </div>
                      
                      {/* Quality Assessment */}
                      {(fundamentals?.eps_ttm !== undefined || fundamentals?.roe !== undefined) && (
                        <div className="mt-3 p-3 rounded bg-zinc-900/50">
                          <div className="flex justify-between items-center">
                            <span className="text-xs text-zinc-500">Quality Assessment</span>
                            <Badge className={`text-xs ${
                              (fundamentals?.eps_ttm > 0 && fundamentals?.roe > 10) 
                                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                                : fundamentals?.eps_ttm > 0
                                  ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                                  : 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'
                            }`}>
                              {(fundamentals?.eps_ttm > 0 && fundamentals?.roe > 10) ? '★★★ Strong' : 
                               fundamentals?.eps_ttm > 0 ? '★★ Moderate' : '★ Speculative'}
                            </Badge>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  {/* Analyst Ratings Card */}
                  <Card className="bg-zinc-800/50 border-zinc-700">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <Target className="w-4 h-4 text-violet-400" />
                        Analyst Ratings
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {stockData?.analyst_ratings?.rating ? (
                        <>
                          <div className="flex items-center justify-between mb-3">
                            <Badge className={`text-sm px-3 py-1 ${
                              stockData.analyst_ratings.rating === 'Strong Buy' 
                                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                                : stockData.analyst_ratings.rating === 'Buy'
                                  ? 'bg-green-500/20 text-green-400 border-green-500/30'
                                  : stockData.analyst_ratings.rating === 'Hold'
                                    ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                                    : 'bg-red-500/20 text-red-400 border-red-500/30'
                            }`}>
                              {stockData.analyst_ratings.rating}
                            </Badge>
                            {stockData.analyst_ratings.has_sufficient_coverage ? (
                              <span className="text-xs text-zinc-400">
                                {stockData.analyst_ratings.num_analysts} analysts
                              </span>
                            ) : (
                              <span className="text-xs text-orange-400">
                                ⚠ {stockData.analyst_ratings.num_analysts || 0} analysts (min 5 recommended)
                              </span>
                            )}
                          </div>
                          
                          {stockData.analyst_ratings.target_price && (
                            <div className="grid grid-cols-2 gap-3">
                              <div className="p-3 rounded bg-zinc-900/50">
                                <div className="text-xs text-zinc-500">Target Price</div>
                                <div className="text-lg font-mono text-white">
                                  ${stockData.analyst_ratings.target_price?.toFixed(2)}
                                </div>
                                {stockData.analyst_ratings.upside_pct !== null && (
                                  <div className={`text-xs ${stockData.analyst_ratings.upside_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {stockData.analyst_ratings.upside_pct >= 0 ? '▲' : '▼'} {Math.abs(stockData.analyst_ratings.upside_pct)}% upside
                                  </div>
                                )}
                              </div>
                              <div className="p-3 rounded bg-zinc-900/50">
                                <div className="text-xs text-zinc-500">Price Range</div>
                                <div className="text-sm font-mono">
                                  <span className="text-red-400">${stockData.analyst_ratings.target_low?.toFixed(0)}</span>
                                  <span className="text-zinc-500"> - </span>
                                  <span className="text-emerald-400">${stockData.analyst_ratings.target_high?.toFixed(0)}</span>
                                </div>
                              </div>
                            </div>
                          )}
                        </>
                      ) : (
                        <div className="text-sm text-zinc-500 text-center py-4">
                          No analyst coverage available
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  {/* Price Stats */}
                  <Card className="bg-zinc-800/50 border-zinc-700">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <BarChart3 className="w-4 h-4 text-cyan-400" />
                        Today's Stats
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="p-2 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500">Open</div>
                          <div className="font-mono text-white">${stockData?.open?.toFixed(2) || 'N/A'}</div>
                        </div>
                        <div className="p-2 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500">Volume</div>
                          <div className="font-mono text-white">{stockData?.volume ? (stockData.volume / 1e6)?.toFixed(2) + 'M' : 'N/A'}</div>
                        </div>
                        <div className="p-2 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500">High</div>
                          <div className="font-mono text-emerald-400">${stockData?.high?.toFixed(2) || 'N/A'}</div>
                        </div>
                        <div className="p-2 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500">Low</div>
                          <div className="font-mono text-red-400">${stockData?.low?.toFixed(2) || 'N/A'}</div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* News Tab */}
                <TabsContent value="news" className="space-y-3 mt-4">
                  {/* Risk Assessment from scan data */}
                  {scanData && (
                    <Card className="bg-zinc-800/50 border-zinc-700 mb-4">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <Shield className="w-4 h-4 text-violet-400" />
                          Risk Assessment
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        <div className="grid grid-cols-2 gap-3">
                          <div className="p-3 rounded bg-zinc-900/50">
                            <div className="text-xs text-zinc-500 mb-1">Risk Profile</div>
                            <Badge className={`text-sm ${
                              scanData.risk_profile === 'conservative' 
                                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                                : scanData.risk_profile === 'balanced'
                                  ? 'bg-blue-500/20 text-blue-400 border-blue-500/30'
                                  : 'bg-orange-500/20 text-orange-400 border-orange-500/30'
                            }`}>
                              {scanData.risk_profile?.charAt(0).toUpperCase() + scanData.risk_profile?.slice(1)}
                            </Badge>
                          </div>
                          <div className="p-3 rounded bg-zinc-900/50">
                            <div className="text-xs text-zinc-500 mb-1">Timeframe</div>
                            <Badge className={`text-sm ${
                              scanData.timeframe === 'weekly' 
                                ? 'bg-blue-500/20 text-blue-400 border-blue-500/30' 
                                : 'bg-purple-500/20 text-purple-400 border-purple-500/30'
                            }`}>
                              {scanData.timeframe === 'weekly' ? 'Weekly' : 'Monthly'}
                            </Badge>
                          </div>
                        </div>
                        
                        <div className="p-3 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500 mb-2">Binary Event Check</div>
                          {fundamentals?.days_to_earnings !== undefined && fundamentals?.days_to_earnings !== null ? (
                            <div className={`flex items-center gap-2 ${
                              fundamentals.days_to_earnings < (scanData?.dte || 30) 
                                ? 'text-orange-400' : 'text-emerald-400'
                            }`}>
                              {fundamentals.days_to_earnings < (scanData?.dte || 30) ? (
                                <>
                                  <AlertTriangle className="w-4 h-4" />
                                  <span className="text-sm">⚠ Earnings in {fundamentals.days_to_earnings}d (before expiry)</span>
                                </>
                              ) : (
                                <>
                                  <Shield className="w-4 h-4" />
                                  <span className="text-sm">✓ No binary events before expiry</span>
                                </>
                              )}
                            </div>
                          ) : (
                            <span className="text-sm text-zinc-400">Earnings date unknown</span>
                          )}
                        </div>

                        <div className="p-3 rounded bg-zinc-900/50">
                          <div className="text-xs text-zinc-500 mb-2">Volatility Assessment</div>
                          <Badge className={`${
                            technicals?.atr_pct > 4 
                              ? 'bg-orange-500/20 text-orange-400 border-orange-500/30'
                              : technicals?.atr_pct > 2.5
                                ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                                : 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                          }`}>
                            {technicals?.atr_pct > 4 ? '● High Volatility' : 
                             technicals?.atr_pct > 2.5 ? '● Moderate Volatility' : '● Low Volatility'}
                          </Badge>
                        </div>

                        <div className="p-3 rounded bg-zinc-900/50">
                          <div className="flex justify-between items-center">
                            <span className="text-xs text-zinc-500">Overall Risk Level</span>
                            <Badge className={`${
                              scanData.risk_profile === 'conservative' && (!fundamentals?.days_to_earnings || fundamentals.days_to_earnings > (scanData?.dte || 30))
                                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                                : scanData.risk_profile === 'aggressive' || (fundamentals?.days_to_earnings && fundamentals.days_to_earnings < (scanData?.dte || 30))
                                  ? 'bg-orange-500/20 text-orange-400 border-orange-500/30'
                                  : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                            }`}>
                              {scanData.risk_profile === 'conservative' && (!fundamentals?.days_to_earnings || fundamentals.days_to_earnings > (scanData?.dte || 30))
                                ? '● Low Risk'
                                : scanData.risk_profile === 'aggressive' || (fundamentals?.days_to_earnings && fundamentals.days_to_earnings < (scanData?.dte || 30))
                                  ? '● High Risk'
                                  : '● Medium Risk'}
                            </Badge>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  <div className="flex items-center gap-2 mb-2">
                    <Newspaper className="w-4 h-4 text-violet-400" />
                    <span className="text-sm font-medium text-white">Latest News</span>
                  </div>
                  
                  {stockData?.news?.length > 0 ? (
                    <div className="space-y-3">
                      {stockData.news.map((article, index) => (
                        <a
                          key={index}
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block p-3 rounded-lg bg-zinc-800/50 border border-zinc-700 hover:border-zinc-600 transition-colors"
                        >
                          <div className="text-sm font-medium text-white line-clamp-2 mb-1">
                            {article.title}
                          </div>
                          {article.description && (
                            <div className="text-xs text-zinc-400 line-clamp-2 mb-2">
                              {article.description}
                            </div>
                          )}
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-zinc-500">{article.source}</span>
                            <span className="text-zinc-600">{formatDate(article.published)}</span>
                          </div>
                          {article.sentiment !== undefined && (
                            <Badge className={`mt-2 text-xs ${
                              article.sentiment > 0 ? 'bg-emerald-500/20 text-emerald-400' :
                              article.sentiment < 0 ? 'bg-red-500/20 text-red-400' :
                              'bg-zinc-500/20 text-zinc-400'
                            }`}>
                              {article.sentiment > 0 ? 'Positive' : article.sentiment < 0 ? 'Negative' : 'Neutral'}
                            </Badge>
                          )}
                        </a>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-8 text-zinc-500">
                      <Newspaper className="w-8 h-8 mx-auto mb-2 opacity-50" />
                      <p className="text-sm">No recent news available</p>
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default StockDetailModal;
