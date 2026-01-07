import { useState, useEffect } from 'react';
import { screenerApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import {
  LineChart,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Info,
  CheckCircle
} from 'lucide-react';
import { toast } from 'sonner';

const PMCC = () => {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [apiInfo, setApiInfo] = useState(null);

  useEffect(() => {
    fetchOpportunities();
  }, []);

  const fetchOpportunities = async () => {
    setLoading(true);
    try {
      const response = await screenerApi.getDashboardPMCC();
      setOpportunities(response.data.opportunities || []);
      setApiInfo(response.data);
    } catch (error) {
      console.error('PMCC fetch error:', error);
      toast.error('Failed to load PMCC opportunities');
    } finally {
      setLoading(false);
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
            Poor Man's Covered Call (PMCC)
          </h1>
          <p className="text-zinc-400 mt-1">LEAPS-based covered call strategy with lower capital requirement</p>
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

      {/* Strategy Explanation */}
      <Card className="glass-card border-violet-500/30">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2 text-violet-400">
            <Info className="w-5 h-5" />
            PMCC Strategy Structure
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="p-4 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="w-5 h-5 text-emerald-400" />
                <span className="font-medium text-emerald-400">1. Buy LEAPS Call (Long Leg)</span>
              </div>
              <ul className="space-y-2 text-sm text-zinc-300">
                <li>• <span className="text-white">Long expiration:</span> 12–24 months</li>
                <li>• <span className="text-white">Deep ITM:</span> High delta (~0.80–0.90)</li>
                <li>• Acts as a stock substitute at lower cost</li>
              </ul>
            </div>
            <div className="p-4 rounded-lg bg-cyan-500/5 border border-cyan-500/20">
              <div className="flex items-center gap-2 mb-3">
                <TrendingDown className="w-5 h-5 text-cyan-400" />
                <span className="font-medium text-cyan-400">2. Sell Short-Term Calls (Short Leg)</span>
              </div>
              <ul className="space-y-2 text-sm text-zinc-300">
                <li>• <span className="text-white">Expiration:</span> 7–30 days</li>
                <li>• <span className="text-white">Out-of-the-money:</span> Delta 0.20–0.30</li>
                <li>• Repeat regularly to collect income</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* LEAPS Data Info */}
      <div className="glass-card p-4 border-l-4 border-emerald-500">
        <div className="flex items-start gap-3">
          <CheckCircle className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-medium text-emerald-400">True LEAPS Options Data</div>
            <div className="text-xs text-zinc-400 mt-1">
              This screener now fetches <strong className="text-white">real LEAPS options (12-24 months out)</strong> from the Massive.com API.
              The long leg uses deep ITM LEAPS with high delta (0.70+), while the short leg uses OTM calls expiring in 7-45 days.
            </div>
          </div>
        </div>
      </div>

      {/* Live Data Badge */}
      {apiInfo?.is_live && (
        <div className="flex items-center gap-2">
          <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
            <CheckCircle className="w-3 h-3 mr-1" />
            Live Options Data
          </Badge>
          {apiInfo?.note && (
            <span className="text-xs text-zinc-500">{apiInfo.note}</span>
          )}
        </div>
      )}

      {/* Opportunities Table */}
      <Card className="glass-card">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <LineChart className="w-5 h-5 text-violet-400" />
            PMCC-Style Diagonal Spread Opportunities
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array(5).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-16 rounded-lg" />
              ))}
            </div>
          ) : opportunities.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">
              <LineChart className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No PMCC opportunities found with current market data</p>
              <p className="text-sm mt-2">Try refreshing or check your broker for LEAPS options</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Stock Price</th>
                    <th>Long Leg (Buy)</th>
                    <th>Cost</th>
                    <th>Short Leg (Sell)</th>
                    <th>Premium</th>
                    <th>Net Debit</th>
                    <th>Strike Width</th>
                    <th>ROI/Cycle</th>
                    <th>Ann. ROI Est.</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.map((opp, index) => (
                    <tr key={index} className="hover:bg-zinc-800/50" data-testid={`pmcc-row-${opp.symbol}`}>
                      <td className="font-semibold text-white">{opp.symbol}</td>
                      <td className="font-mono">${opp.stock_price?.toFixed(2)}</td>
                      <td>
                        <div className="flex flex-col">
                          <span className="text-emerald-400 font-mono">${opp.leaps_strike?.toFixed(0)}</span>
                          <span className="text-xs text-zinc-500">{opp.leaps_dte}d • δ{opp.leaps_delta?.toFixed(2)}</span>
                        </div>
                      </td>
                      <td className="text-red-400 font-mono">${opp.leaps_cost?.toLocaleString()}</td>
                      <td>
                        <div className="flex flex-col">
                          <span className="text-cyan-400 font-mono">${opp.short_strike?.toFixed(0)}</span>
                          <span className="text-xs text-zinc-500">{opp.short_dte}d • δ{opp.short_delta?.toFixed(2)}</span>
                        </div>
                      </td>
                      <td className="text-emerald-400 font-mono">${opp.short_premium?.toFixed(0)}</td>
                      <td className="text-white font-mono">${opp.net_debit?.toLocaleString()}</td>
                      <td className="font-mono">${opp.strike_width?.toFixed(0)}</td>
                      <td className="text-yellow-400 font-semibold">{opp.roi_per_cycle?.toFixed(1)}%</td>
                      <td className="text-emerald-400 font-semibold">{opp.annualized_roi?.toFixed(0)}%</td>
                      <td>
                        <Badge className={`${opp.score >= 70 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : opp.score >= 50 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' : 'bg-violet-500/20 text-violet-400 border-violet-500/30'}`}>
                          {opp.score?.toFixed(0)}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Strategy Tips */}
      <div className="grid md:grid-cols-2 gap-6">
        <Card className="glass-card">
          <CardHeader>
            <CardTitle className="text-sm text-emerald-400">PMCC Advantages</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-zinc-400 space-y-2">
            <p>• <span className="text-white">Lower capital requirement</span> - LEAPS cost less than 100 shares</p>
            <p>• <span className="text-white">Built-in leverage</span> - Control 100 shares with less money</p>
            <p>• <span className="text-white">Income generation</span> - Sell short calls repeatedly for premium</p>
            <p>• <span className="text-white">Defined risk</span> - Maximum loss is the net debit paid</p>
          </CardContent>
        </Card>

        <Card className="glass-card">
          <CardHeader>
            <CardTitle className="text-sm text-cyan-400">Key Management Rules</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-zinc-400 space-y-2">
            <p>• <span className="text-white">LEAPS delta:</span> Keep at 0.80-0.90 (deep ITM) to minimize extrinsic value</p>
            <p>• <span className="text-white">Short call delta:</span> Stay at 0.20-0.30 (OTM) to reduce assignment risk</p>
            <p>• <span className="text-white">Roll short calls:</span> At 50% profit or 21 DTE remaining</p>
            <p>• <span className="text-white">Roll LEAPS:</span> When 6 months remaining to avoid theta acceleration</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default PMCC;
