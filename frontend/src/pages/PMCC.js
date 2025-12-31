import { useState, useEffect } from 'react';
import { screenerApi, aiApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Slider } from '../components/ui/slider';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { Textarea } from '../components/ui/textarea';
import {
  LineChart,
  Brain,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Sparkles
} from 'lucide-react';
import { toast } from 'sonner';

const PMCC = () => {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [selectedOpp, setSelectedOpp] = useState(null);

  // Filter states
  const [minLeapsDelta, setMinLeapsDelta] = useState(0.8);
  const [maxShortDelta, setMaxShortDelta] = useState(0.3);

  useEffect(() => {
    fetchOpportunities();
  }, []);

  const fetchOpportunities = async () => {
    setLoading(true);
    try {
      const response = await screenerApi.getPMCC({
        min_leaps_delta: minLeapsDelta,
        max_short_delta: maxShortDelta
      });
      setOpportunities(response.data.opportunities || []);
    } catch (error) {
      console.error('PMCC fetch error:', error);
      toast.error('Failed to load PMCC opportunities');
    } finally {
      setLoading(false);
    }
  };

  const getAIAnalysis = async (opp) => {
    setSelectedOpp(opp);
    setAiLoading(true);
    try {
      const response = await aiApi.analyze({
        symbol: opp.symbol,
        analysis_type: 'opportunity',
        context: `PMCC setup with LEAPS strike ${opp.leaps.strike}, short call strike ${opp.short_call.strike}`
      });
      setAiAnalysis(response.data);
    } catch (error) {
      toast.error('Failed to get AI analysis');
    } finally {
      setAiLoading(false);
    }
  };

  const formatCurrency = (value) => `$${value?.toFixed(2) || '0.00'}`;

  return (
    <div className="space-y-6" data-testid="pmcc-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <LineChart className="w-8 h-8 text-violet-500" />
            Poor Man's Covered Call
          </h1>
          <p className="text-zinc-400 mt-1">LEAPS-based covered call alternatives with lower capital requirement</p>
        </div>
        <Button
          onClick={fetchOpportunities}
          className="btn-primary"
          data-testid="refresh-pmcc-btn"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Filters */}
      <Card className="glass-card" data-testid="pmcc-filters">
        <CardContent className="py-4">
          <div className="grid md:grid-cols-3 gap-6 items-end">
            <div>
              <Label className="filter-label">Min LEAPS Delta: {minLeapsDelta.toFixed(2)}</Label>
              <Slider
                value={[minLeapsDelta]}
                onValueChange={([val]) => setMinLeapsDelta(val)}
                min={0.7}
                max={0.95}
                step={0.05}
                className="mt-2"
                data-testid="leaps-delta-slider"
              />
              <span className="text-xs text-zinc-500">Deep ITM (0.80-0.90 recommended)</span>
            </div>
            <div>
              <Label className="filter-label">Max Short Call Delta: {maxShortDelta.toFixed(2)}</Label>
              <Slider
                value={[maxShortDelta]}
                onValueChange={([val]) => setMaxShortDelta(val)}
                min={0.1}
                max={0.4}
                step={0.05}
                className="mt-2"
                data-testid="short-delta-slider"
              />
              <span className="text-xs text-zinc-500">OTM (0.20-0.30 recommended)</span>
            </div>
            <Button onClick={fetchOpportunities} className="btn-secondary" data-testid="apply-pmcc-filters-btn">
              Apply Filters
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Opportunities List */}
        <div className="lg:col-span-2 space-y-4">
          {loading ? (
            Array(5).fill(0).map((_, i) => (
              <Skeleton key={i} className="h-48 rounded-xl" />
            ))
          ) : opportunities.length === 0 ? (
            <Card className="glass-card">
              <CardContent className="py-12 text-center text-zinc-500">
                <LineChart className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>No PMCC opportunities found</p>
                <p className="text-sm mt-2">Try adjusting delta parameters</p>
              </CardContent>
            </Card>
          ) : (
            opportunities.map((opp, index) => (
              <Card 
                key={index} 
                className={`glass-card card-hover cursor-pointer ${selectedOpp?.symbol === opp.symbol ? 'border-violet-500/50 neon-glow' : ''}`}
                onClick={() => setSelectedOpp(opp)}
                data-testid={`pmcc-card-${opp.symbol}`}
              >
                <CardContent className="p-6">
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <h3 className="text-xl font-bold text-white">{opp.symbol}</h3>
                      <span className="text-zinc-500 font-mono">${opp.stock_price?.toFixed(2)}</span>
                    </div>
                    <Badge className="badge-ai">
                      <Sparkles className="w-3 h-3 mr-1" />
                      PMCC
                    </Badge>
                  </div>

                  <div className="grid md:grid-cols-2 gap-6">
                    {/* LEAPS (Long Leg) */}
                    <div className="p-4 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                      <div className="flex items-center gap-2 mb-3">
                        <TrendingUp className="w-4 h-4 text-emerald-400" />
                        <span className="text-sm font-medium text-emerald-400">Long LEAPS (Buy)</span>
                      </div>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Strike</span>
                          <span className="font-mono text-white">{formatCurrency(opp.leaps.strike)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Expiry</span>
                          <span className="font-mono text-white">{opp.leaps.expiry}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Delta</span>
                          <span className="font-mono text-white">{opp.leaps.delta?.toFixed(2)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Cost</span>
                          <span className="font-mono text-red-400">-{formatCurrency(opp.leaps.cost)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">DTE</span>
                          <span className="font-mono text-white">{opp.leaps.dte}d</span>
                        </div>
                      </div>
                    </div>

                    {/* Short Call */}
                    <div className="p-4 rounded-lg bg-red-500/5 border border-red-500/20">
                      <div className="flex items-center gap-2 mb-3">
                        <TrendingDown className="w-4 h-4 text-cyan-400" />
                        <span className="text-sm font-medium text-cyan-400">Short Call (Sell)</span>
                      </div>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Strike</span>
                          <span className="font-mono text-white">{formatCurrency(opp.short_call.strike)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Expiry</span>
                          <span className="font-mono text-white">{opp.short_call.expiry}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Delta</span>
                          <span className="font-mono text-white">{opp.short_call.delta?.toFixed(2)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Premium</span>
                          <span className="font-mono text-emerald-400">+{formatCurrency(opp.short_call.premium)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">DTE</span>
                          <span className="font-mono text-white">{opp.short_call.dte}d</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Summary Stats */}
                  <div className="grid grid-cols-4 gap-4 mt-4 pt-4 border-t border-white/5">
                    <div className="text-center">
                      <div className="text-xs text-zinc-500">Max Profit</div>
                      <div className="font-mono text-emerald-400 font-semibold">{formatCurrency(opp.max_profit)}</div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500">Max Loss</div>
                      <div className="font-mono text-red-400 font-semibold">{formatCurrency(opp.max_loss)}</div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500">Breakeven</div>
                      <div className="font-mono text-white font-semibold">{formatCurrency(opp.breakeven)}</div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500">ROI on Capital</div>
                      <div className="font-mono text-cyan-400 font-semibold">{opp.roi_on_capital?.toFixed(1)}%</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>

        {/* AI Analysis Panel */}
        <div className="space-y-4">
          <Card className="glass-card sticky top-4" data-testid="ai-analysis-panel">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Brain className="w-5 h-5 text-fuchsia-400" />
                AI Analysis
              </CardTitle>
            </CardHeader>
            <CardContent>
              {selectedOpp ? (
                <>
                  <div className="mb-4 p-3 rounded-lg bg-zinc-800/50">
                    <div className="text-sm text-zinc-400">Analyzing</div>
                    <div className="text-lg font-bold text-white">{selectedOpp.symbol}</div>
                  </div>

                  <Button
                    onClick={() => getAIAnalysis(selectedOpp)}
                    className="w-full btn-primary mb-4"
                    disabled={aiLoading}
                    data-testid="get-ai-analysis-btn"
                  >
                    {aiLoading ? (
                      <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Sparkles className="w-4 h-4 mr-2" />
                    )}
                    Get AI Insights
                  </Button>

                  {aiAnalysis && (
                    <div className="space-y-4 animate-fade-in">
                      {aiAnalysis.is_mock && (
                        <div className="p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30 flex items-center gap-2">
                          <AlertTriangle className="w-4 h-4 text-yellow-400" />
                          <span className="text-xs text-yellow-400">Mock analysis - configure OpenAI API key for real insights</span>
                        </div>
                      )}

                      <div className="p-4 rounded-lg bg-fuchsia-500/5 border border-fuchsia-500/20">
                        <h4 className="text-sm font-medium text-fuchsia-400 mb-2">Analysis</h4>
                        <p className="text-sm text-zinc-300 whitespace-pre-wrap">{aiAnalysis.analysis}</p>
                      </div>

                      {aiAnalysis.recommendations && (
                        <div className="p-4 rounded-lg bg-zinc-800/30">
                          <h4 className="text-sm font-medium text-violet-400 mb-2">Recommendations</h4>
                          <ul className="space-y-2">
                            {aiAnalysis.recommendations.map((rec, i) => (
                              <li key={i} className="text-sm text-zinc-300 flex items-start gap-2">
                                <span className="text-violet-400">•</span>
                                {rec}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {aiAnalysis.confidence && (
                        <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/30">
                          <span className="text-sm text-zinc-400">Confidence</span>
                          <Badge className={`${aiAnalysis.confidence >= 0.7 ? 'badge-success' : 'badge-warning'}`}>
                            {(aiAnalysis.confidence * 100).toFixed(0)}%
                          </Badge>
                        </div>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <div className="text-center py-8 text-zinc-500">
                  <Brain className="w-12 h-12 mx-auto mb-4 opacity-30" />
                  <p className="text-sm">Select a PMCC opportunity to analyze</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Strategy Tips */}
          <Card className="glass-card" data-testid="strategy-tips">
            <CardHeader>
              <CardTitle className="text-sm">PMCC Strategy Tips</CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-zinc-400 space-y-2">
              <p>• LEAPS should be deep ITM (delta 0.80-0.90) to minimize extrinsic value loss</p>
              <p>• Short calls should be OTM (delta 0.20-0.30) to reduce assignment risk</p>
              <p>• Roll short calls when they reach 50% profit or 21 DTE</p>
              <p>• Monitor LEAPS theta decay - consider rolling at 6 months remaining</p>
              <p>• Ideal for stocks with moderate upside potential</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default PMCC;
