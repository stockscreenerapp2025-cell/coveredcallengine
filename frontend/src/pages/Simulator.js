import { useState, useEffect } from 'react';
import { simulatorApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Switch } from '../components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Play,
  RefreshCw,
  Trash2,
  TrendingUp,
  DollarSign,
  BarChart3,
  Target,
  Clock,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Activity,
  Percent,
  Layers,
  Settings,
  Plus,
  Zap,
  FileText,
  Edit,
  Copy,
  PlayCircle,
  History,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  LineChart,
  Lightbulb,
  Save,
  ExternalLink,
  Award,
  TrendingDown
} from 'lucide-react';
import { toast } from 'sonner';
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from 'recharts';

const STATUS_COLORS = {
  'open': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'active': 'bg-blue-500/20 text-blue-400 border-blue-500/30',  // Legacy support
  'rolled': 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  'closed': 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
  'expired': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'assigned': 'bg-amber-500/20 text-amber-400 border-amber-500/30'
};

const STRATEGY_COLORS = {
  'covered_call': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  'pmcc': 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  'wheel': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  'defensive': 'bg-sky-500/20 text-sky-400 border-sky-500/30'
};

const CHART_COLORS = {
  covered_call: '#10b981',
  pmcc: '#8b5cf6',
  profit: '#10b981',
  loss: '#ef4444'
};

const ACTION_COLORS = {
  'opened':       'bg-blue-500/20 text-blue-400',
  'closed':       'bg-zinc-500/20 text-zinc-400',
  'close':        'bg-zinc-500/20 text-zinc-400',
  'rolled':       'bg-violet-500/20 text-violet-400',
  'rolled_open':  'bg-cyan-500/20 text-cyan-400',
  'roll_out':     'bg-cyan-500/20 text-cyan-400',
  'roll_up':      'bg-purple-500/20 text-purple-400',
  'rule_closed':  'bg-amber-500/20 text-amber-400',
  'rule_alert':   'bg-yellow-500/20 text-yellow-400',
  'alert':        'bg-orange-500/20 text-orange-400',
  'expired':      'bg-emerald-500/20 text-emerald-400',
  'assigned':     'bg-red-500/20 text-red-400',
};

const ACTION_LABELS = {
  'opened':       'Trade Added',
  'closed':       'Trade Closed',
  'close':        'Closed by Rule',
  'rolled':       'Trade Rolled',
  'rolled_open':  'Rolled (Open)',
  'roll_out':     'Roll Out',
  'roll_up':      'Roll Up',
  'rule_closed':  'Rule Closed',
  'rule_alert':   'Rule Alert',
  'alert':        'Alert',
  'expired':      'Expired',
  'assigned':     'Assigned',
};

const CONDITION_FIELDS = [
  { value: 'premium_capture_pct', label: 'Premium Captured %' },
  { value: 'current_delta', label: 'Delta' },
  { value: 'loss_pct', label: 'Loss %' },
  { value: 'profit_pct', label: 'Profit %' },
  { value: 'dte_remaining', label: 'DTE Remaining' },
  { value: 'days_held', label: 'Days Held' },
  { value: 'current_theta', label: 'Theta (abs)' },
  { value: 'cumulative_income_ratio', label: 'Cumulative Income Ratio (PMCC)' }
];

const OPERATORS = [
  { value: 'gte', label: '>=' },
  { value: 'lte', label: '<=' },
  { value: 'gt', label: '>' },
  { value: 'lt', label: '<' },
  { value: 'eq', label: '=' }
];

const ManageGoalsForm = ({ onRun, loading, walletBalance }) => {
  const canRun = walletBalance === null || walletBalance >= 5;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div style={{ background: '#0f172a', borderRadius: '8px', padding: '14px', fontSize: '13px', color: '#94a3b8', lineHeight: 1.6 }}>
        AI will analyze this trade against your <strong style={{ color: '#a855f7' }}>configured rules</strong> and recommend
        the best action: hold, roll, close, or let expire — with full reasoning.
        <div style={{ marginTop: '8px', color: '#64748b', fontSize: '12px' }}>
          Cost: <span style={{ color: '#a855f7', fontWeight: 600 }}>5 credits</span>
        </div>
      </div>
      {!canRun && (
        <div style={{ background: '#7f1d1d', border: '1px solid #dc2626', borderRadius: '8px', padding: '10px', fontSize: '13px', color: '#fca5a5' }}>
          Insufficient credits. You need at least 5 credits to run AI analysis.
        </div>
      )}
      <button
        onClick={() => onRun({})}
        disabled={loading || !canRun}
        style={{
          background: canRun ? 'linear-gradient(135deg, #7c3aed, #a855f7)' : '#374151',
          color: 'white', border: 'none', borderRadius: '8px', padding: '14px',
          fontSize: '14px', fontWeight: '600',
          cursor: canRun ? 'pointer' : 'not-allowed', opacity: loading ? 0.7 : 1
        }}
      >
        {loading ? '⚙️ Analyzing trade...' : 'Analyze with AI (5 credits)'}
      </button>
    </div>
  );
};

const RecommendationCard = ({ result, onApply, onDismiss, applyLoading }) => {
  const rec = result?.recommendation || {};
  const m   = rec.metrics || {};
  const [selectedAction, setSelectedAction] = useState(rec.action || 'hold');

  const actionColors = {
    hold: '#16a34a', roll: '#7c3aed', close: '#dc2626',
    expire_and_write: '#0284c7', assign: '#f59e0b', dca: '#06b6d4'
  };
  const primaryColor = actionColors[rec.action] || '#6b7280';
  const actionLabels = {
    hold: 'HOLD', roll: 'ROLL', close: 'CLOSE', assign: 'ASSIGN',
    expire_and_write: 'WRITE NEXT', dca: 'DCA'
  };

  const confColor = rec.confidence >= 80 ? '#16a34a' : rec.confidence >= 60 ? '#f59e0b' : '#ef4444';
  const reasoning = Array.isArray(rec.reasoning) ? rec.reasoning
    : rec.reason ? [rec.reason] : ['No reasoning provided.'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

      {/* Section 1 — Metrics snapshot */}
      {m.stock_price && (
        <div style={{ background: '#0f172a', borderRadius: '8px', padding: '14px' }}>
          <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '10px', fontWeight: '600', letterSpacing: '0.05em' }}>
            TRADE HEALTH SNAPSHOT
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px' }}>
            {[
              ['Stock Price', `$${m.stock_price}`],
              ['Strike', `$${m.strike}`],
              ['Distance', `${m.in_the_money ? '⚠ ' : ''}${Math.abs(m.distance_to_strike_pct)}% ${m.in_the_money ? 'ITM' : 'OTM'}`],
              ['Breakeven', `$${m.breakeven}`],
              ['DTE', `${m.dte}d`],
              ['Capture', `${m.premium_capture_pct}%`],
            ].map(([label, val]) => (
              <div key={label} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '10px', color: '#64748b', marginBottom: '2px' }}>{label}</div>
                <div style={{ fontSize: '13px', fontWeight: '600', color: m.in_the_money && label === 'Distance' ? '#ef4444' : '#e2e8f0' }}>{val}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Section 2 — AI Decision with reasoning */}
      <div style={{ background: '#0f172a', borderRadius: '8px', padding: '16px', border: `1px solid ${primaryColor}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
          <span style={{
            background: primaryColor, color: 'white', borderRadius: '6px',
            padding: '4px 14px', fontWeight: '700', fontSize: '13px'
          }}>
            {actionLabels[rec.action] || (rec.action || 'N/A').toUpperCase()}
          </span>
          <span style={{ fontSize: '12px', color: confColor, fontWeight: '600' }}>
            Confidence: {rec.confidence ?? '—'}%
          </span>
          {rec.rule_applied && (
            <span style={{ fontSize: '11px', color: '#94a3b8', background: '#1e293b', borderRadius: '4px', padding: '2px 8px' }}>
              {rec.rule_applied}
            </span>
          )}
        </div>

        {/* Reasoning bullets */}
        <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {reasoning.map((r, i) => (
            <li key={i} style={{ fontSize: '13px', color: '#e2e8f0', lineHeight: 1.5 }}>{r}</li>
          ))}
        </ul>

        {/* Confidence basis */}
        {rec.confidence_basis?.length > 0 && (
          <div style={{ marginTop: '10px', borderTop: '1px solid #1e293b', paddingTop: '10px' }}>
            <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '6px' }}>Based on:</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {rec.confidence_basis.map((b, i) => (
                <span key={i} style={{ fontSize: '11px', color: '#94a3b8', background: '#1e293b', borderRadius: '4px', padding: '2px 8px' }}>{b}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Section 3 — Alternative actions */}
      {rec.actions?.length > 1 && (
        <div style={{ background: '#0f172a', borderRadius: '8px', padding: '14px' }}>
          <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '10px', fontWeight: '600', letterSpacing: '0.05em' }}>
            AVAILABLE ACTIONS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {rec.actions.map((act, i) => (
              <div
                key={i}
                onClick={() => setSelectedAction(act.type)}
                style={{
                  display: 'flex', alignItems: 'center', gap: '10px',
                  padding: '10px 12px', borderRadius: '8px', cursor: 'pointer',
                  border: `1px solid ${selectedAction === act.type ? (actionColors[act.type] || '#7c3aed') : '#334155'}`,
                  background: selectedAction === act.type ? 'rgba(124,58,237,0.1)' : '#0d1117',
                  transition: 'all 0.15s'
                }}
              >
                <div style={{
                  width: '14px', height: '14px', borderRadius: '50%',
                  border: `2px solid ${actionColors[act.type] || '#6b7280'}`,
                  background: selectedAction === act.type ? (actionColors[act.type] || '#7c3aed') : 'transparent',
                  flexShrink: 0
                }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '13px', fontWeight: '600', color: '#e2e8f0', display: 'flex', gap: '6px', alignItems: 'center' }}>
                    {act.label}
                    {act.primary && <span style={{ fontSize: '10px', background: primaryColor, color: 'white', borderRadius: '4px', padding: '1px 6px' }}>Recommended</span>}
                  </div>
                  <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>{act.description}</div>
                </div>
                {act.impact && (
                  <div style={{ fontSize: '11px', color: '#94a3b8', whiteSpace: 'nowrap' }}>{act.impact}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings */}
      {rec.warnings?.length > 0 && (
        <div style={{ background: '#451a03', border: '1px solid #92400e', borderRadius: '8px', padding: '10px 14px' }}>
          {rec.warnings.map((w, i) => (
            <div key={i} style={{ fontSize: '12px', color: '#fbbf24' }}>⚠ {w}</div>
          ))}
        </div>
      )}

      {/* Section 4 — Action buttons */}
      <div style={{ display: 'flex', gap: '10px' }}>
        <button
          onClick={() => onApply(selectedAction)}
          disabled={applyLoading}
          style={{
            flex: 1, background: actionColors[selectedAction] || '#7c3aed',
            color: 'white', border: 'none', borderRadius: '8px', padding: '12px',
            fontWeight: '600', cursor: 'pointer', fontSize: '14px',
            opacity: applyLoading ? 0.7 : 1
          }}
        >
          {applyLoading ? 'Executing...' : `Execute: ${(rec.actions?.find(a => a.type === selectedAction)?.label || selectedAction).toUpperCase()}`}
        </button>
        <button
          onClick={onDismiss}
          style={{
            flex: 0.4, background: '#1e293b', color: '#94a3b8',
            border: '1px solid #334155', borderRadius: '8px', padding: '12px', cursor: 'pointer'
          }}
        >
          Close Panel
        </button>
      </div>

      {/* Execution note */}
      <div style={{ fontSize: '11px', color: '#475569', textAlign: 'center' }}>
        Execute will simulate the selected action and update trade lifecycle tracking.
      </div>
    </div>
  );
};

const Simulator = () => {
  // Status helper: backend uses 'open'/'rolled'/'active' for live trades
  const isLive = (status) => ['open', 'rolled', 'active'].includes(status);

  // AI Manage modal state
  const [manageOpen, setManageOpen] = useState(false);
  const [manageTrade, setManageTrade] = useState(null);
  const [manageLoading, setManageLoading] = useState(false);
  const [manageResult, setManageResult] = useState(null);   // { recommendation, balance_after, current_price }
  const [applyLoading, setApplyLoading] = useState(false);
  const [walletBalance, setWalletBalance] = useState(null);
  const [activeTab, setActiveTab] = useState('trades');
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [selectedTrade, setSelectedTrade] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  
  // Rules state
  const [rules, setRules] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [rulesLoading, setRulesLoading] = useState(false);
  const [ruleConfig, setRuleConfig] = useState(null);
  const [ruleSaving, setRuleSaving] = useState(false);
  const [ruleDialogOpen, setRuleDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluationResults, setEvaluationResults] = useState(null);
  const [evalResultsOpen, setEvalResultsOpen] = useState(false);
  const [activeRuleStrategies, setActiveRuleStrategies] = useState(['cc', 'wheel', 'pmcc', 'defensive']);
  
  // Action Logs state
  const [actionLogs, setActionLogs] = useState([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsPagination, setLogsPagination] = useState({ page: 1, pages: 1, total: 0 });
  
  // PMCC Summary state
  const [pmccSummary, setPmccSummary] = useState(null);
  const [pmccLoading, setPmccLoading] = useState(false);
  
  // Analytics state (Phase 4)
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsTimeframe, setAnalyticsTimeframe] = useState('all');
  const [analyticsStrategy, setAnalyticsStrategy] = useState('');
  const [optimalSettings, setOptimalSettings] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [newProfileName, setNewProfileName] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  
  // Analyzer state (3-Row Structure)
  const [analyzerData, setAnalyzerData] = useState(null);
  const [analyzerLoading, setAnalyzerLoading] = useState(false);
  const [analyzerSymbol, setAnalyzerSymbol] = useState('');

  // Trade Health state
  const [healthData, setHealthData] = useState(null);
  const [healthLoading, setHealthLoading] = useState(false);
  
  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [strategyFilter, setStrategyFilter] = useState('');
  
  // Pagination
  const [pagination, setPagination] = useState({
    page: 1,
    pages: 1,
    total: 0
  });

  // Track if initial price update has been done
  const [initialUpdateDone, setInitialUpdateDone] = useState(false);

  // ── AI Manage helpers ──────────────────────────────────────────────
  const fetchWalletBalance = async () => {
    try {
      const res = await fetch('/api/simulator/wallet', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      if (res.ok) {
        const data = await res.json();
        setWalletBalance(data.balance_credits);
      }
    } catch (e) { /* silent */ }
  };

  const handleManageTrade = async (trade) => {
    setManageTrade(trade);
    setManageResult(null);
    setManageOpen(true);
    await fetchWalletBalance();
  };

  const runManageAI = async (goals = {}) => {
    if (!manageTrade) return;
    setManageLoading(true);
    setManageResult(null);
    try {
      const res = await fetch(`/api/simulator/manage/${manageTrade.id}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify({ mode: 'recommend_only', goals })
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 402) {
          alert(`Insufficient credits. You need 5 credits. Current balance: ${data.detail?.balance ?? 0}`);
        } else {
          alert(`Error: ${data.detail || 'Unknown error'}`);
        }
        return;
      }
      setManageResult(data);
      setWalletBalance(data.balance_after);
    } catch (e) {
      alert('Network error running AI manage.');
    } finally {
      setManageLoading(false);
    }
  };

  const applyRecommendation = async () => {
    if (!manageResult || !manageTrade) return;
    setApplyLoading(true);
    try {
      const res = await fetch(`/api/simulator/manage/${manageTrade.id}/apply`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify({
          recommendation: manageResult.recommendation,
          current_price: manageResult.current_price
        })
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 402) {
          alert(`Insufficient credits to apply. Need 2 credits. Balance: ${data.detail?.balance ?? 0}`);
        } else {
          const msg = typeof data.detail === 'object' ? (data.detail?.message || JSON.stringify(data.detail)) : (data.detail || 'Unknown error');
          alert(`Apply failed: ${msg}`);
        }
        return;
      }
      setWalletBalance(data.balance_after);
      setManageOpen(false);
      setManageResult(null);
      // Refresh trades list
      fetchTrades();
      alert(`✅ Applied: ${data.action_applied}. Trade updated successfully.`);
    } catch (e) {
      alert('Network error applying recommendation.');
    } finally {
      setApplyLoading(false);
    }
  };

  useEffect(() => {
    fetchTrades();
    fetchSummary();
  }, [statusFilter, strategyFilter, pagination.page]);
  
  // Disabled: auto price-update on load caused perceived "page restart" (table re-render after
  // live Yahoo fetch completes). User can manually refresh prices with the Refresh button.

  useEffect(() => {
    if (activeTab === 'rules') {
      fetchRuleConfig();
    } else if (activeTab === 'logs') {
      fetchActionLogs();
    } else if (activeTab === 'pmcc') {
      fetchPMCCSummary();
    } else if (activeTab === 'analytics') {
      fetchAnalytics();
      fetchAnalyzerData();
      fetchOptimalSettings();
      fetchProfiles();
      fetchTradesHealth();
    }
  }, [activeTab]);

  // Re-fetch analyzer when filters change
  useEffect(() => {
    if (activeTab === 'analytics') {
      fetchAnalyzerData();
      fetchAnalytics();
    }
  }, [analyticsStrategy, analyzerSymbol, analyticsTimeframe]);

  const fetchTrades = async () => {
    setLoading(true);
    try {
      const res = await simulatorApi.getTrades({
        status: statusFilter || undefined,
        strategy: strategyFilter || undefined,
        page: pagination.page,
        limit: 20
      });
      const rawTrades = res.data.trades || [];
      const computeAnnROI = (t) => {
        const live = ['open', 'rolled', 'active'].includes(t.status);
        const cap = t.capital_deployed || (t.entry_underlying_price * 100 * (t.contracts || 1));
        let pnl;
        if (live) {
          pnl = t.unrealized_pnl;
        } else if (t.final_pnl != null) {
          pnl = t.final_pnl;
        } else if (t.status === 'assigned') {
          pnl = ((t.short_call_strike - t.entry_underlying_price) * 100 * (t.contracts || 1)) + (t.premium_collected || 0);
        } else {
          pnl = 0;
        }
        const roi = t.roi_percent ?? (cap > 0 ? pnl / cap * 100 : 0);
        const dte = t.dte_remaining || t.days_held || 30;
        return roi / dte * 365;
      };
      const statusPriority = (s) => ['open', 'rolled', 'active'].includes(s) ? 0 : 1;
      rawTrades.sort((a, b) => {
        const sp = statusPriority(a.status) - statusPriority(b.status);
        if (sp !== 0) return sp;
        return computeAnnROI(b) - computeAnnROI(a);
      });
      setTrades(rawTrades);
      setPagination(prev => ({
        ...prev,
        pages: res.data.pages || 1,
        total: res.data.total || 0
      }));
    } catch (error) {
      console.error('Error fetching simulator trades:', error);
      toast.error('Failed to load simulator trades');
    } finally {
      setLoading(false);
    }
  };

  const fetchSummary = async () => {
    try {
      const res = await simulatorApi.getSummary();
      setSummary(res.data);
    } catch (error) {
      console.error('Error fetching summary:', error);
    }
  };

  const fetchRuleConfig = async () => {
    setRulesLoading(true);
    try {
      const res = await simulatorApi.getRuleConfig();
      setRuleConfig(res.data || null);
      setRules(res.data.materialized_rules || []);
    } catch (error) {
      console.error('Error fetching rule config:', error);
      toast.error('Failed to load rules');
    } finally {
      setRulesLoading(false);
    }
  };

  const fetchActionLogs = async () => {
    setLogsLoading(true);
    try {
      const res = await simulatorApi.getActionLogs({
        limit: 50,
        page: logsPagination.page
      });
      setActionLogs(res.data.logs || []);
      setLogsPagination(prev => ({
        ...prev,
        pages: res.data.pages || 1,
        total: res.data.total || 0
      }));
    } catch (error) {
      console.error('Error fetching action logs:', error);
      toast.error('Failed to load action logs');
    } finally {
      setLogsLoading(false);
    }
  };

  const fetchPMCCSummary = async () => {
    setPmccLoading(true);
    try {
      const res = await simulatorApi.getPMCCSummary();
      setPmccSummary(res.data);
    } catch (error) {
      console.error('Error fetching PMCC summary:', error);
    } finally {
      setPmccLoading(false);
    }
  };

  const fetchAnalytics = async () => {
    setAnalyticsLoading(true);
    try {
      const res = await simulatorApi.getPerformanceAnalytics({
        strategy: analyticsStrategy || undefined,
        timeframe: analyticsTimeframe
      });
      setAnalytics(res.data);
    } catch (error) {
      console.error('Error fetching analytics:', error);
    } finally {
      setAnalyticsLoading(false);
    }
  };
  
  // Fetch Analyzer data (3-Row Structure)
  const fetchAnalyzerData = async () => {
    setAnalyzerLoading(true);
    try {
      const res = await simulatorApi.getAnalyzerMetrics({
        strategy: analyticsStrategy || undefined,
        symbol: analyzerSymbol || undefined,
        time_period: analyticsTimeframe
      });
      setAnalyzerData(res.data);
    } catch (err) {
      console.error('Failed to fetch analyzer data:', err);
    } finally {
      setAnalyzerLoading(false);
    }
  };

  const fetchTradesHealth = async () => {
    setHealthLoading(true);
    try {
      const res = await simulatorApi.getTradesHealth();
      setHealthData(res.data);
    } catch (err) {
      console.error('Failed to fetch trade health:', err);
    } finally {
      setHealthLoading(false);
    }
  };

  const fetchOptimalSettings = async () => {
    try {
      const res = await simulatorApi.getOptimalSettings(analyticsStrategy || 'covered_call');
      setOptimalSettings(res.data);
    } catch (error) {
      console.error('Error fetching optimal settings:', error);
    }
  };

  const fetchProfiles = async () => {
    try {
      const res = await simulatorApi.getProfiles();
      setProfiles(res.data.profiles || []);
    } catch (error) {
      console.error('Error fetching profiles:', error);
    }
  };

  const handleSaveProfile = async () => {
    if (!newProfileName.trim()) {
      toast.error('Please enter a profile name');
      return;
    }
    setSavingProfile(true);
    try {
      await simulatorApi.saveProfile(newProfileName);
      toast.success('Profile saved');
      setNewProfileName('');
      fetchProfiles();
    } catch (error) {
      toast.error('Failed to save profile');
    } finally {
      setSavingProfile(false);
    }
  };

  const handleDeleteProfile = async (profileId) => {
    if (!window.confirm('Delete this profile?')) return;
    try {
      await simulatorApi.deleteProfile(profileId);
      toast.success('Profile deleted');
      fetchProfiles();
    } catch (error) {
      toast.error('Failed to delete profile');
    }
  };

  const handleUpdatePrices = async (silent = false) => {
    setUpdating(true);
    try {
      const res = await simulatorApi.updatePrices();
      if (!silent) toast.success(`Prices refreshed — ${res.data.updated ?? 0} trades updated`);
      fetchTrades();
      fetchSummary();
    } catch (error) {
      if (!silent) toast.error('Failed to update prices');
    } finally {
      setUpdating(false);
    }
  };

  const handleDeleteTrade = async (tradeId) => {
    if (!window.confirm('Are you sure you want to delete this simulated trade?')) return;
    
    try {
      await simulatorApi.deleteTrade(tradeId);
      toast.success('Trade deleted');
      fetchTrades();
      fetchSummary();
      setDetailOpen(false);
    } catch (error) {
      toast.error('Failed to delete trade');
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm('Are you sure you want to clear ALL simulator data? This cannot be undone.')) return;
    
    try {
      await simulatorApi.clearAll();
      toast.success('All simulator data cleared');
      fetchTrades();
      fetchSummary();
    } catch (error) {
      toast.error('Failed to clear data');
    }
  };

  const persistRuleConfig = async (nextConfig) => {
    setRuleSaving(true);
    try {
      const res = await simulatorApi.updateRuleConfig(nextConfig);
      setRuleConfig(res.data.config || nextConfig);
      setRules(res.data.config?.materialized_rules || []);
      toast.success('Rules saved');
    } catch (error) {
      console.error('Error saving rule config:', error);
      toast.error(error?.response?.data?.detail || 'Failed to save rules');
    } finally {
      setRuleSaving(false);
    }
  };

  const handleStrategyModeChange = async (strategyMode) => {
    const baseConfig = ruleConfig || { strategy_mode: strategyMode, controls: {}, alerts: { assignment_risk_alert: true, assignment_imminent_alert: true } };
    await persistRuleConfig({ ...baseConfig, strategy_mode: strategyMode });
  };

  const handleToggleAlert = async (key) => {
    if (!ruleConfig) return;
    await persistRuleConfig({ ...ruleConfig, alerts: { ...(ruleConfig.alerts || {}), [key]: !ruleConfig?.alerts?.[key] } });
  };

  const handleToggleOptionalControl = async (key) => {
    if (!ruleConfig) return;
    await persistRuleConfig({ ...ruleConfig, controls: { ...(ruleConfig.controls || {}), [key]: !ruleConfig?.controls?.[key] } });
  };

  const handleEvaluateRules = async () => {
    setEvaluating(true);
    try {
      const tradeId = selectedTrade?.id || null;
      const res = await simulatorApi.previewRuleConfig(tradeId);
      setEvaluationResults(res.data);
      setEvalResultsOpen(true);
    } catch (error) {
      toast.error('Failed to preview rules');
    } finally {
      setEvaluating(false);
    }
  };

  const formatCurrency = (value) => {
    if (value === null || value === undefined) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(value);
  };

  const formatPercent = (value) => {
    if (value === null || value === undefined) return '-';
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
    } catch {
      return dateStr;
    }
  };

  const formatDateTime = (dateStr) => {
    if (!dateStr) return '-';
    try {
      return new Date(dateStr).toLocaleString('en-US', { 
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  const formatOptionContract = (expiry, strike) => {
    if (!expiry || !strike) return '-';
    try {
      const date = new Date(expiry);
      const day = date.getDate().toString().padStart(2, '0');
      const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
      const month = months[date.getMonth()];
      const year = date.getFullYear().toString().slice(-2);
      return `${day}${month}${year} $${strike} C`;
    } catch {
      return `$${strike} C`;
    }
  };

  // Prepare chart data
  const strategyDistribution = summary?.by_strategy ? Object.entries(summary.by_strategy).map(([key, value]) => ({
    name: key === 'covered_call' ? 'Covered Call' : 'PMCC',
    value: value.total,
    color: CHART_COLORS[key]
  })).filter(d => d.value > 0) : [];

  const pnlByStrategy = summary?.by_strategy ? Object.entries(summary.by_strategy).map(([key, value]) => ({
    name: key === 'covered_call' ? 'Covered Call' : 'PMCC',
    realized: value.realized_pnl,
    unrealized: value.unrealized_pnl
  })) : [];

  // ==================== RENDER FUNCTIONS ====================

  const renderTradesTab = () => (
    <>
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        {loading && !summary ? (
          Array(6).fill(0).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))
        ) : (
          <>
            <Card className="glass-card" data-testid="total-pnl-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <DollarSign className="w-4 h-4" />
                  Total P/L
                </div>
                <div className={`text-xl font-bold font-mono ${(summary?.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatCurrency(summary?.total_pnl || 0)}
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="win-rate-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <Target className="w-4 h-4" />
                  Win Rate
                </div>
                <div className="text-xl font-bold font-mono text-white">
                  {summary?.win_rate?.toFixed(1) || 0}%
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="active-trades-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <Activity className="w-4 h-4" />
                  Active Trades
                </div>
                <div className="text-xl font-bold font-mono text-blue-400">
                  {summary?.active_trades || 0}
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="capital-deployed-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <Layers className="w-4 h-4" />
                  Capital Deployed
                </div>
                <div className="text-xl font-bold font-mono text-white">
                  {formatCurrency(summary?.total_capital_deployed || 0)}
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="avg-return-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <Percent className="w-4 h-4" />
                  Avg Return
                </div>
                <div className="text-xl font-bold font-mono text-white">
                  {(summary?.avg_return_per_trade || 0).toFixed(2)}%
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card" data-testid="assignment-rate-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
                  <AlertCircle className="w-4 h-4" />
                  Assignment Rate
                </div>
                <div className="text-xl font-bold font-mono text-amber-400">
                  {summary?.assignment_rate?.toFixed(1) || 0}%
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {/* Charts Row */}
      {summary && (summary.total_trades > 0) && (
        <div className="grid md:grid-cols-2 gap-6">
          {strategyDistribution.length > 0 && (
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-violet-400" />
                  Strategy Distribution
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={strategyDistribution}
                        cx="50%"
                        cy="60%"
                        innerRadius={40}
                        outerRadius={70}
                        paddingAngle={2}
                        dataKey="value"
                        label={({ name, value }) => `${name}: ${value}`}
                        labelLine={false}
                      >
                        {strategyDistribution.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip 
                        contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex justify-center gap-4 mt-2">
                  <div className="flex items-center gap-1.5 text-xs">
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500"></div>
                    <span className="text-zinc-400">Covered Call</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs">
                    <div className="w-2.5 h-2.5 rounded-full bg-violet-500"></div>
                    <span className="text-zinc-400">PMCC</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {pnlByStrategy.some(d => d.realized !== 0 || d.unrealized !== 0) && (
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                  P/L by Strategy
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={pnlByStrategy} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                      <XAxis type="number" tickFormatter={(v) => `$${v >= 1000 ? (v/1000).toFixed(1) + 'k' : v}`} stroke="#666" fontSize={10} />
                      <YAxis type="category" dataKey="name" stroke="#999" fontSize={10} width={80} />
                      <Tooltip 
                        contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                        formatter={(value) => formatCurrency(value)}
                      />
                      <Legend />
                      <Bar dataKey="realized" name="Realized" fill="#10b981" radius={[0, 4, 4, 0]} />
                      <Bar dataKey="unrealized" name="Unrealized" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Trades Table */}
      <Card className="glass-card" data-testid="trades-table-card">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <Activity className="w-5 h-5 text-violet-400" />
            Simulated Trades ({pagination.total})
          </CardTitle>
          <div className="flex gap-2">
            <Select value={statusFilter || "all"} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
              <SelectTrigger className="w-32 h-8 bg-zinc-800/50 border-zinc-700">
                <SelectValue placeholder="All Status" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-700">
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="open">Open</SelectItem>
                <SelectItem value="rolled">Rolled</SelectItem>
                <SelectItem value="closed">Closed</SelectItem>
                <SelectItem value="expired">Expired</SelectItem>
                <SelectItem value="assigned">Assigned</SelectItem>
              </SelectContent>
            </Select>
            <Select value={strategyFilter || "all"} onValueChange={(v) => setStrategyFilter(v === "all" ? "" : v)}>
              <SelectTrigger className="w-36 h-8 bg-zinc-800/50 border-zinc-700">
                <SelectValue placeholder="All Strategies" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-700">
                <SelectItem value="all">All Strategies</SelectItem>
                <SelectItem value="covered_call">Covered Call</SelectItem>
                <SelectItem value="pmcc">PMCC</SelectItem>
                <SelectItem value="wheel">Wheel</SelectItem>
                <SelectItem value="defensive">Defensive</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {Array(5).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : trades.length === 0 ? (
            <div className="text-center py-12">
              <Play className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-white mb-2">No Simulated Trades Yet</h3>
              <p className="text-zinc-400 text-sm mb-4">
                Add trades from the Screener or PMCC pages using the &quot;SIMULATE&quot; button
              </p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-zinc-500 border-b border-zinc-800">
                      <th className="pb-3 font-medium">Symbol</th>
                      <th className="pb-3 font-medium">Strategy</th>
                      <th className="pb-3 font-medium">Status</th>
                      <th className="pb-3 font-medium">Entry</th>
                      <th className="pb-3 font-medium">Current</th>
                      <th className="pb-3 font-medium">Contract</th>
                      <th className="pb-3 font-medium">DTE</th>
                      <th className="pb-3 font-medium">Delta</th>
                      <th className="pb-3 font-medium">IV</th>
                      <th className="pb-3 font-medium">IV Rank</th>
                      <th className="pb-3 font-medium">OI</th>
                      <th className="pb-3 font-medium">Capital Used</th>
                      <th className="pb-3 font-medium">Stock P/L</th>
                      <th className="pb-3 font-medium">Prem Earned</th>
                      <th className="pb-3 font-medium">Prem Yield</th>
                      <th className="pb-3 font-medium">P/L</th>
                      <th className="pb-3 font-medium">ROI</th>
                      <th className="pb-3 font-medium">Quality</th>
                      <th className="pb-3 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((trade) => (
                      <tr 
                        key={trade.id}
                        className="border-b border-zinc-800/50 hover:bg-zinc-800/30 cursor-pointer"
                        onClick={() => {
                          setSelectedTrade(trade);
                          setDetailOpen(true);
                        }}
                        data-testid={`simulator-row-${trade.symbol}`}
                      >
                        <td className="py-3 font-semibold text-white">
                          {trade.symbol}
                          {trade.roll_count > 0 && (
                            <Badge className="ml-1 bg-cyan-500/20 text-cyan-400 text-xs">R{trade.roll_count}</Badge>
                          )}
                        </td>
                        <td>
                          <Badge className={STRATEGY_COLORS[trade.strategy_type]}>
                            {{ covered_call: 'CC', pmcc: 'PMCC', wheel: 'CSP', defensive: 'COLLAR' }[trade.strategy_type] || (trade.strategy_type || '').toUpperCase()}
                          </Badge>
                        </td>
                        <td>
                          <Badge className={STATUS_COLORS[trade.status]}>
                            {trade.status}
                          </Badge>
                        </td>
                        <td className="text-zinc-300">${trade.entry_underlying_price?.toFixed(2)}</td>
                        <td className={`font-mono ${
                          (trade.current_underlying_price || 0) >= (trade.entry_underlying_price || 0) 
                            ? 'text-emerald-400' : 'text-red-400'
                        }`}>
                          ${trade.current_underlying_price?.toFixed(2) || '-'}
                        </td>
                        <td className="font-mono text-xs text-zinc-400">
                          {(() => { const s = formatOptionContract(trade.short_call_expiry, trade.short_call_strike); const i = s.indexOf(' '); return i > -1 ? <>{s.slice(0, i)}<br />{s.slice(i + 1)}</> : s; })()}
                        </td>
                        <td className={`${trade.dte_remaining <= 7 ? 'text-amber-400' : 'text-zinc-300'}`}>
                          {isLive(trade.status) ? `${trade.dte_remaining}d` : '-'}
                        </td>
                        <td className="text-cyan-400 font-mono">
                          {!isLive(trade.status) ? <span className="text-zinc-600">—</span>
                            : (trade.current_delta?.toFixed(2) || trade.short_call_delta?.toFixed(2) || '—')}
                        </td>
                        <td className="text-violet-400 font-mono">
                          {trade.scan_parameters?.iv_pct
                            ? `${trade.scan_parameters.iv_pct.toFixed(1)}%`
                            : trade.short_call_iv
                              ? `${(trade.short_call_iv * 100).toFixed(1)}%`
                              : trade.implied_volatility
                                ? `${trade.implied_volatility.toFixed(1)}%`
                                : '—'}
                        </td>
                        <td className="text-amber-400 font-mono">
                          {(() => {
                            const ivr = trade.iv_rank ?? trade.scan_parameters?.iv_rank;
                            // Only show if explicitly fetched (not defaulted to 100)
                            return (ivr != null && ivr > 0 && ivr < 100) ? `${ivr.toFixed(0)}%` : '—';
                          })()}
                        </td>
                        <td className="text-zinc-400 font-mono">
                          {trade.open_interest ? trade.open_interest.toLocaleString() : (trade.scan_parameters?.open_interest ? trade.scan_parameters.open_interest.toLocaleString() : '—')}
                        </td>
                        <td className="text-zinc-300 font-mono">
                          {trade.capital_deployed ? formatCurrency(trade.capital_deployed) : '—'}
                        </td>
                        <td className={`font-mono ${
                          (() => {
                            const stockPL = (trade.current_underlying_price - trade.entry_underlying_price) * 100 * (trade.contracts || 1);
                            return stockPL >= 0 ? 'text-emerald-400' : 'text-red-400';
                          })()
                        }`}>
                          {trade.entry_underlying_price && trade.current_underlying_price
                            ? formatCurrency((trade.current_underlying_price - trade.entry_underlying_price) * 100 * (trade.contracts || 1))
                            : '—'}
                        </td>
                        <td className="text-violet-400 font-mono">
                          {trade.premium_received ? formatCurrency(trade.premium_received) : '—'}
                        </td>
                        <td className={`font-mono ${(trade.premium_capture_pct || 0) >= 75 ? 'text-emerald-400' : (trade.premium_capture_pct || 0) >= 40 ? 'text-zinc-300' : 'text-zinc-500'}`}>
                          {(() => {
                            // Premium Yield = premium received / capital deployed
                            const cap = trade.capital_deployed || (trade.entry_underlying_price * 100 * (trade.contracts || 1));
                            const prem = trade.premium_received_total || (trade.short_call_premium * 100 * (trade.contracts || 1));
                            return cap > 0 ? `${((prem / cap) * 100).toFixed(1)}%` : `${trade.premium_capture_pct?.toFixed(0) || 0}%`;
                          })()}
                        </td>
                        <td className={`font-mono ${
                          isLive(trade.status)
                            ? (trade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                            : ((trade.final_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400')
                        }`}>
                          {isLive(trade.status)
                            ? formatCurrency(trade.unrealized_pnl)
                            : formatCurrency(trade.final_pnl || 0)
                          }
                        </td>
                        <td className={`font-mono ${
                          (() => {
                            const cap = trade.capital_deployed || (trade.entry_underlying_price * 100 * (trade.contracts || 1));
                            let pnl;
                            if (isLive(trade.status)) {
                              pnl = trade.unrealized_pnl;
                            } else if (trade.final_pnl != null) {
                              pnl = trade.final_pnl;
                            } else if (trade.status === 'assigned') {
                              // CC assigned: stock called away at strike + premium kept
                              pnl = ((trade.short_call_strike - trade.entry_underlying_price) * 100 * (trade.contracts || 1)) + (trade.premium_collected || 0);
                            } else {
                              pnl = 0;
                            }
                            const roi = trade.roi_percent ?? (cap > 0 ? pnl / cap * 100 : 0);
                            return roi >= 0 ? 'text-emerald-400' : 'text-red-400';
                          })()
                        }`}>
                          {(() => {
                            const cap = trade.capital_deployed || (trade.entry_underlying_price * 100 * (trade.contracts || 1));
                            let pnl;
                            if (isLive(trade.status)) {
                              pnl = trade.unrealized_pnl;
                            } else if (trade.final_pnl != null) {
                              pnl = trade.final_pnl;
                            } else if (trade.status === 'assigned') {
                              pnl = ((trade.short_call_strike - trade.entry_underlying_price) * 100 * (trade.contracts || 1)) + (trade.premium_collected || 0);
                            } else {
                              pnl = 0;
                            }
                            return formatPercent(trade.roi_percent ?? (cap > 0 ? pnl / cap * 100 : 0));
                          })()}
                        </td>
                        <td>
                          {(() => {
                            const cap = trade.capital_deployed || (trade.entry_underlying_price * 100 * (trade.contracts || 1));
                            let pnl;
                            if (isLive(trade.status)) {
                              pnl = trade.unrealized_pnl;
                            } else if (trade.final_pnl != null) {
                              pnl = trade.final_pnl;
                            } else if (trade.status === 'assigned') {
                              pnl = ((trade.short_call_strike - trade.entry_underlying_price) * 100 * (trade.contracts || 1)) + (trade.premium_collected || 0);
                            } else {
                              pnl = 0;
                            }
                            const roi = trade.roi_percent ?? (cap > 0 ? pnl / cap * 100 : 0);
                            const dte = trade.dte_remaining || trade.days_held || 30;
                            const annROI = roi / dte * 365;
                            if (pnl < 0) return <span className="text-xs text-red-400 font-medium">Losing</span>;
                            if (annROI > 20) return <span className="text-xs text-emerald-400 font-medium">High Yield</span>;
                            if (annROI > 10) return <span className="text-xs text-blue-400 font-medium">Good Income</span>;
                            return <span className="text-xs text-zinc-500 font-medium">Low Return</span>;
                          })()}
                        </td>
                        <td>
                          {isLive(trade.status) && (
                            <button
                              onClick={(e) => { e.stopPropagation(); handleManageTrade(trade); }}
                              style={{
                                background: 'linear-gradient(135deg, #7c3aed, #a855f7)',
                                color: 'white', border: 'none', borderRadius: '6px',
                                padding: '4px 10px', fontSize: '12px', cursor: 'pointer',
                                fontWeight: '600', marginRight: '6px'
                              }}
                              title="AI will analyze this trade and suggest an action (5 credits)"
                            >
                              🤖 Manage
                            </button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteTrade(trade.id);
                            }}
                            className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {pagination.pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-800">
                  <span className="text-sm text-zinc-500">
                    Page {pagination.page} of {pagination.pages}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPagination(p => ({ ...p, page: p.page - 1 }))}
                      disabled={pagination.page === 1}
                      className="btn-outline"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPagination(p => ({ ...p, page: p.page + 1 }))}
                      disabled={pagination.page === pagination.pages}
                      className="btn-outline"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </>
  );

  const renderRulesTab = () => {
    const controls = ruleConfig?.controls || {};
    const alerts = ruleConfig?.alerts || {};

    const strategyGroups = [
      {
        key: 'cc', label: 'CC', title: 'Covered Call Rules', color: 'emerald',
        desc: 'Applied to trades with strategy type CC',
        controls: [
          { key: 'profit_taking',                label: 'Take Profit Early',            desc: 'Close position when premium captured reaches the threshold (e.g. 60%). Increases cycle yield by redeploying capital sooner.', hasThreshold: true, thresholdKey: 'profit_taking_pct', thresholdMin: 40, thresholdMax: 90, thresholdDefault: 60, thresholdLabel: 'Close at % captured' },
          { key: 'roll_delta_based',             label: 'Roll Based on Delta',          desc: 'Roll when delta exceeds the configured threshold' },
          { key: 'roll_itm_near_expiry',         label: 'Roll ITM Near Expiry',         desc: 'Roll to next cycle when the call goes deep ITM close to expiry' },
          { key: 'brokerage_aware_hold',         label: 'Brokerage-Aware Hold',         desc: 'Skip action if brokerage fees would wipe out the gain' },
          { key: 'market_aware_roll_suggestion', label: 'Market-Aware Roll Suggestion', desc: 'Factor in market conditions — does not override delta or ITM rules' },
          { key: 'avoid_early_close',            label: 'Hold for Theta (Avoid Early Close)', desc: 'CC: Hold the short call for full time decay — disables profit taking rule above' },
        ],
      },
      {
        key: 'wheel', label: 'CSP', title: 'Cash Secured Put (Wheel) Rules', color: 'sky',
        desc: 'Applied to trades with strategy type Wheel / Cash Secured Put',
        controls: [
          { key: 'csp_profit_taking',            label: 'Take Profit Early',            desc: 'Close put when premium captured reaches threshold — redeploy and sell again sooner.', hasThreshold: true, thresholdKey: 'csp_profit_taking_pct', thresholdMin: 40, thresholdMax: 90, thresholdDefault: 60, thresholdLabel: 'Close at % captured' },
          { key: 'csp_roll_delta_based',         label: 'Roll Based on Delta',          desc: 'Roll put when delta exceeds threshold (e.g. 0.60) — high assignment risk signal', hasThreshold: true, thresholdKey: 'csp_delta_threshold', thresholdMin: 0.40, thresholdMax: 0.90, thresholdDefault: 0.60, thresholdStep: 0.05, thresholdLabel: 'Delta threshold' },
          { key: 'csp_roll_itm_near_expiry',     label: 'Roll ITM Near Expiry',         desc: 'Roll put to next cycle when it goes ITM close to expiry — protects against deep loss' },
          { key: 'brokerage_aware_hold',         label: 'Brokerage-Aware Hold',         desc: 'Skip action if brokerage fees would wipe out the gain' },
          { key: 'roll_before_assignment',       label: 'Roll Put Before Assignment',   desc: 'Roll the short put to avoid stock assignment (disable for true Wheel strategy)' },
          { key: 'market_aware_roll_suggestion', label: 'Market-Aware Roll Suggestion', desc: 'Factor in market conditions before suggesting a roll' },
          { key: 'avoid_early_close',            label: 'Hold for Full Cycle (Avoid Early Close)', desc: 'CSP: Hold put until near expiry — disables profit taking. Use only if targeting assignment.' },
        ],
      },
      {
        key: 'pmcc', label: 'PMCC', title: "Poor Man's Covered Call Rules", color: 'violet',
        desc: 'Applied to trades with strategy type PMCC',
        controls: [
          { key: 'manage_short_call_only',         label: 'Manage Short Call Only',         desc: 'Keep the LEAP untouched — only manage the short call leg' },
          { key: 'roll_before_assignment',         label: 'Roll Before Assignment (CRITICAL)', desc: 'Roll short call before assignment — critical for PMCC since no actual shares held' },
          { key: 'roll_delta_based',               label: 'Roll Based on Delta',            desc: 'Roll when short call delta exceeds threshold', hasThreshold: true },
          { key: 'pmcc_extrinsic_protection',      label: 'Extrinsic Value Protection',     desc: 'Do NOT roll if extrinsic value > threshold — prevents rolling too early during strong moves', hasThreshold: true, thresholdKey: 'pmcc_extrinsic_pct', thresholdMin: 10, thresholdMax: 50, thresholdDefault: 25, thresholdStep: 5, thresholdLabel: 'Min extrinsic % to block roll' },
          { key: 'roll_itm_near_expiry',           label: 'Roll ITM Near Expiry',           desc: 'Roll to next cycle when the short call goes ITM near expiry' },
          { key: 'pmcc_profit_taking',             label: 'Take Profit Early (Short Call)',  desc: 'Close short call when premium captured reaches threshold — redeploy at new strike', hasThreshold: true, thresholdKey: 'pmcc_profit_taking_pct', thresholdMin: 50, thresholdMax: 90, thresholdDefault: 75, thresholdStep: 5, thresholdLabel: 'Close at % captured' },
          { key: 'market_aware_roll_suggestion',   label: 'Market-Aware Roll Suggestion',   desc: 'Factor in market conditions — does not override assignment or delta rules' },
        ],
      },
      {
        key: 'defensive', label: 'COLLAR', title: 'Collar / Defensive Rules', color: 'amber',
        desc: 'Applied to trades with strategy type Collar or Defensive',
        controls: [
          { key: 'collar_profit_taking',         label: 'Take Profit Early (Short Call)', desc: 'Close short call when premium captured reaches threshold — redeploy at higher strike', hasThreshold: true, thresholdKey: 'collar_profit_taking_pct', thresholdMin: 40, thresholdMax: 90, thresholdDefault: 55, thresholdStep: 5, thresholdLabel: 'Close at % captured' },
          { key: 'manage_short_call_only',       label: 'Manage Short Call Only',         desc: 'Keep the protective put intact — never close the put, only manage the short call' },
          { key: 'roll_delta_based',             label: 'Roll Based on Delta',            desc: 'Roll short call when delta exceeds threshold' },
          { key: 'roll_itm_near_expiry',         label: 'Roll ITM Near Expiry',           desc: 'Roll short call to next cycle when it goes ITM near expiry' },
          { key: 'collar_put_renewal_alert',     label: 'Put Renewal Reminder',           desc: 'Alert when the protective put is within 30 days of expiry — time to roll or renew it' },
          { key: 'brokerage_aware_hold',         label: 'Brokerage-Aware Hold',           desc: 'Skip action if brokerage fees would wipe out the gain' },
          { key: 'market_aware_roll_suggestion', label: 'Market-Aware Roll Suggestion',   desc: 'Factor in market conditions before suggesting a roll' },
          { key: 'collar_maintain_structure',    label: 'Maintain Protection (Hold Unless Risk Triggers)', desc: 'Collar-specific: hold the full structure unless delta, ITM, or expiry rules are triggered. Different from PMCC theta hold.' },
        ],
      },
    ];
    const colorMap = {
      emerald: { border: 'border-emerald-500/20', bg: 'bg-emerald-500/5', row: 'border-emerald-500/20', header: 'text-emerald-400' },
      sky:     { border: 'border-sky-500/20',     bg: 'bg-sky-500/5',     row: 'border-sky-500/20',     header: 'text-sky-400'     },
      violet:  { border: 'border-violet-500/20',  bg: 'bg-violet-500/5',  row: 'border-violet-500/20',  header: 'text-violet-400'  },
      amber:   { border: 'border-amber-500/20',   bg: 'bg-amber-500/5',   row: 'border-amber-500/20',   header: 'text-amber-400'   },
    };

    return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <Settings className="w-5 h-5 text-violet-400" />
            Trade Strategy Rules
          </h2>
          <p className="text-zinc-400 text-sm mt-1">
            Rules are applied per-trade based on each trade's strategy type. Configure optional controls and alerts below.
          </p>
        </div>
        <Button
          onClick={() => handleEvaluateRules(false)}
          disabled={evaluating || !ruleConfig}
          className="bg-violet-600 hover:bg-violet-700 text-white"
          data-testid="execute-rules-btn"
        >
          <Zap className={`w-4 h-4 mr-2 ${evaluating ? 'animate-spin' : ''}`} />
          Execute Preview
        </Button>
      </div>

      {/* Strategy Filter + Reset Defaults */}
      {(() => {
        const allStrategyKeys = ['cc', 'wheel', 'pmcc', 'defensive'];
        const toggleRuleStrategy = (key) => setActiveRuleStrategies(prev =>
          prev.includes(key) ? (prev.length > 1 ? prev.filter(k => k !== key) : prev) : [...prev, key]
        );
        const rc = ruleConfig?.controls || {};
        const conflictWarnings = [];
        // Only warn about Avoid Early Close conflicts when it is explicitly ON
        if (rc.avoid_early_close === true && rc.profit_taking === true)
          conflictWarnings.push('Avoid Early Close + Take Profit Early conflict — disable one. Avoid Early Close overrides profit taking.');
        if (rc.avoid_early_close === true && rc.csp_profit_taking === true)
          conflictWarnings.push('Avoid Early Close + CSP Profit Taking conflict — disable one.');
        if (rc.avoid_early_close === true && rc.collar_profit_taking === true)
          conflictWarnings.push('Avoid Early Close + Collar Profit Taking conflict — disable one.');
        // Delta range validation
        if (rc.target_delta_min != null && rc.target_delta_max != null && rc.target_delta_min >= rc.target_delta_max)
          conflictWarnings.push('Min delta must be less than Max delta');
        const handleResetDefaults = () => persistRuleConfig({
          ...ruleConfig,
          controls: {
            // CC defaults — avoid_early_close OFF (profit taking is active)
            profit_taking: true, profit_taking_pct: 60,
            avoid_early_close: false, brokerage_aware_hold: true,
            roll_itm_near_expiry: true, roll_delta_based: true,
            market_aware_roll_suggestion: true,
            target_delta_min: 0.25, target_delta_max: 0.40,
            // CSP/Wheel defaults
            roll_before_assignment: false,
            csp_profit_taking: true, csp_profit_taking_pct: 60,
            csp_roll_itm_near_expiry: true, csp_roll_delta_based: true,
            csp_delta_threshold: 0.60,
            // PMCC defaults
            manage_short_call_only: true,
            pmcc_extrinsic_protection: true, pmcc_extrinsic_pct: 25,
            pmcc_profit_taking: true, pmcc_profit_taking_pct: 75,
            // Collar defaults — no "avoid_early_close", use collar-specific maintain structure
            collar_profit_taking: true, collar_profit_taking_pct: 55,
            collar_put_renewal_alert: true,
            collar_maintain_structure: true,
            collar_delta_min: 0.20, collar_delta_max: 0.30,
            // Shared
            close_at_capture_pct: 80, roll_dte_trigger: 21, hard_roll_dte: 7,
            no_debit_roll: true, avoid_assignment: true,
          },
          alerts: {
            assignment_risk_alert: true,
            assignment_imminent_alert: true,
          }
        });
        return (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-lg bg-zinc-800/50 border border-zinc-700/50">
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs text-zinc-400 font-medium">Show rules for:</span>
                {strategyGroups.map(group => (
                  <button key={group.key} onClick={() => toggleRuleStrategy(group.key)}
                    className={`text-xs px-3 py-1 rounded border font-semibold transition-all ${
                      activeRuleStrategies.includes(group.key)
                        ? 'bg-violet-600 text-white border-violet-500'
                        : 'bg-zinc-800 text-zinc-500 border-zinc-700'
                    }`}
                  >{group.label}</button>
                ))}
              </div>
              <button onClick={handleResetDefaults}
                className="text-xs px-3 py-1.5 rounded border border-zinc-600 text-zinc-400 hover:text-white hover:border-zinc-400 transition-all"
              >Reset to Defaults</button>
            </div>
            {conflictWarnings.length > 0 && (
              <div className="p-3 rounded-lg bg-amber-900/30 border border-amber-500/40 space-y-1">
                <div className="text-xs font-semibold text-amber-400 mb-1">⚠ Rule Conflicts Detected</div>
                {conflictWarnings.map((w, i) => (
                  <div key={i} className="text-xs text-amber-300">• {w}</div>
                ))}
              </div>
            )}

            {/* Section 3: Optional Controls — filtered by strategy */}
                  {strategyGroups.filter(g => activeRuleStrategies.includes(g.key)).map(group => {
              const cm = colorMap[group.color];
              return (
                <Card key={group.key} className={`glass-card ${cm.border}`}>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Settings className={`w-4 h-4 ${cm.header}`} />
                      <span className={cm.header}>{group.label}</span>
                      <span className="text-zinc-400 font-normal">— {group.title}</span>
                    </CardTitle>
                    <p className="text-xs text-zinc-500 mt-1">{group.desc}</p>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {group.controls.map(ctrl => (
                        <div key={ctrl.key} className={`flex items-center justify-between p-3 rounded-lg ${cm.bg} border ${cm.row}`}>
                          <div className="flex-1">
                            <p className="text-sm text-zinc-200 font-medium">{ctrl.label}</p>
                            <p className="text-xs text-zinc-500 mt-0.5">{ctrl.desc}</p>
                            {ctrl.key === 'profit_taking' && controls.profit_taking && (
                              <div className="flex items-center gap-3 mt-2">
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-zinc-400">Close at:</span>
                                  <input
                                    type="number" step="5" min="40" max="90"
                                    value={controls.profit_taking_pct ?? 60}
                                    onChange={e => persistRuleConfig({ ...ruleConfig, controls: { ...controls, profit_taking_pct: parseFloat(e.target.value) } })}
                                    disabled={ruleSaving}
                                    className="w-16 text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-white"
                                  />
                                  <span className="text-xs text-zinc-400">% premium captured</span>
                                </div>
                              </div>
                            )}
                            {ctrl.key === 'csp_profit_taking' && controls.csp_profit_taking && (
                              <div className="flex items-center gap-3 mt-2">
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-zinc-400">Close at:</span>
                                  <input
                                    type="number" step="5" min="40" max="90"
                                    value={controls.csp_profit_taking_pct ?? 60}
                                    onChange={e => persistRuleConfig({ ...ruleConfig, controls: { ...controls, csp_profit_taking_pct: parseFloat(e.target.value) } })}
                                    disabled={ruleSaving}
                                    className="w-16 text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-white"
                                  />
                                  <span className="text-xs text-zinc-400">% premium captured</span>
                                </div>
                              </div>
                            )}
                            {ctrl.key === 'csp_roll_delta_based' && controls.csp_roll_delta_based && (
                              <div className="flex items-center gap-3 mt-2">
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-zinc-400">Roll when δ &gt;:</span>
                                  <input
                                    type="number" step="0.05" min="0.40" max="0.90"
                                    value={controls.csp_delta_threshold ?? 0.60}
                                    onChange={e => persistRuleConfig({ ...ruleConfig, controls: { ...controls, csp_delta_threshold: parseFloat(e.target.value) } })}
                                    disabled={ruleSaving}
                                    className="w-16 text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-white"
                                  />
                                </div>
                              </div>
                            )}
                            {ctrl.key === 'pmcc_extrinsic_protection' && controls.pmcc_extrinsic_protection && (
                              <div className="flex items-center gap-3 mt-2">
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-zinc-400">Block roll if extrinsic &gt;:</span>
                                  <input
                                    type="number" step="5" min="10" max="50"
                                    value={controls.pmcc_extrinsic_pct ?? 25}
                                    onChange={e => persistRuleConfig({ ...ruleConfig, controls: { ...controls, pmcc_extrinsic_pct: parseFloat(e.target.value) } })}
                                    disabled={ruleSaving}
                                    className="w-16 text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-white"
                                  />
                                  <span className="text-xs text-zinc-400">% of option price</span>
                                </div>
                              </div>
                            )}
                            {ctrl.key === 'pmcc_profit_taking' && controls.pmcc_profit_taking && (
                              <div className="flex items-center gap-3 mt-2">
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-zinc-400">Close at:</span>
                                  <input
                                    type="number" step="5" min="50" max="90"
                                    value={controls.pmcc_profit_taking_pct ?? 75}
                                    onChange={e => persistRuleConfig({ ...ruleConfig, controls: { ...controls, pmcc_profit_taking_pct: parseFloat(e.target.value) } })}
                                    disabled={ruleSaving}
                                    className="w-16 text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-white"
                                  />
                                  <span className="text-xs text-zinc-400">% premium captured</span>
                                </div>
                              </div>
                            )}
                            {ctrl.key === 'collar_profit_taking' && controls.collar_profit_taking && (
                              <div className="flex items-center gap-3 mt-2">
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-zinc-400">Close at:</span>
                                  <input
                                    type="number" step="5" min="40" max="90"
                                    value={controls.collar_profit_taking_pct ?? 55}
                                    onChange={e => persistRuleConfig({ ...ruleConfig, controls: { ...controls, collar_profit_taking_pct: parseFloat(e.target.value) } })}
                                    disabled={ruleSaving}
                                    className="w-16 text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-white"
                                  />
                                  <span className="text-xs text-zinc-400">% premium captured</span>
                                </div>
                              </div>
                            )}
                            {ctrl.key === 'roll_delta_based' && controls.roll_delta_based && (
                              <div className="flex items-center gap-3 mt-2">
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-zinc-400">Min δ:</span>
                                  <input
                                    type="number" step="0.05" min="0.10" max="0.90"
                                    value={controls.target_delta_min ?? 0.25}
                                    onChange={e => persistRuleConfig({ ...ruleConfig, controls: { ...controls, target_delta_min: parseFloat(e.target.value) } })}
                                    disabled={ruleSaving}
                                    className="w-16 text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-white"
                                  />
                                </div>
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-zinc-400">Max δ:</span>
                                  <input
                                    type="number" step="0.05" min="0.10" max="0.90"
                                    value={controls.target_delta_max ?? 0.35}
                                    onChange={e => persistRuleConfig({ ...ruleConfig, controls: { ...controls, target_delta_max: parseFloat(e.target.value) } })}
                                    disabled={ruleSaving}
                                    className="w-16 text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-white"
                                  />
                                </div>
                                <span className="text-xs text-zinc-500">Roll when δ outside this range</span>
                              </div>
                            )}
                          </div>
                          <Switch
                            checked={!!controls[ctrl.key]}
                            onCheckedChange={() => handleToggleOptionalControl(ctrl.key)}
                            disabled={ruleSaving}
                          />
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        );
      })()}

      {/* Section 4: Alerts */}
      <Card className="glass-card border-amber-500/20">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            Alerts
            <span className="text-zinc-500 text-xs font-normal">(independent of strategy — no trade actions)</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-center justify-between p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
              <span className="text-sm text-zinc-300">Assignment Risk Alert</span>
              <Switch
                checked={!!alerts.assignment_risk_alert}
                onCheckedChange={() => handleToggleAlert('assignment_risk_alert')}
                disabled={ruleSaving}
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
              <span className="text-sm text-zinc-300">Assignment Imminent Alert</span>
              <Switch
                checked={!!alerts.assignment_imminent_alert}
                onCheckedChange={() => handleToggleAlert('assignment_imminent_alert')}
                disabled={ruleSaving}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Active Materialized Rules */}
      <Card className="glass-card" data-testid="rules-list-card">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            Active Rules ({rules.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {rulesLoading ? (
            <div className="space-y-2">
              {Array(3).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : rules.length === 0 ? (
            <div className="text-center py-8">
              <Settings className="w-10 h-10 text-zinc-600 mx-auto mb-3" />
              <p className="text-zinc-400 text-sm">No rules configured yet</p>
              <p className="text-zinc-500 text-xs mt-1">Enable controls above to generate per-strategy rules automatically</p>
            </div>
          ) : (
            <div className="space-y-3">
              {rules.map(rule => (
                <div
                  key={rule.id}
                  className="p-4 rounded-lg border bg-zinc-800/50 border-zinc-700/50"
                  data-testid={`rule-${rule.id}`}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="font-medium text-white">{rule.name}</h4>
                        <Badge className={
                          (rule.action?.action_type || rule.action) === 'roll'
                            ? 'bg-violet-500/20 text-violet-400'
                            : (rule.action?.action_type || rule.action) === 'alert'
                            ? 'bg-amber-500/20 text-amber-400'
                            : 'bg-blue-500/20 text-blue-400'
                        }>
                          {rule.action?.action_type || rule.action}
                        </Badge>
                        {rule.strategy_type && (
                          <Badge className={STRATEGY_COLORS[rule.strategy_type]}>
                            {{ covered_call: 'CC Only', pmcc: 'PMCC Only', wheel: 'CSP Only', defensive: 'COLLAR Only' }[rule.strategy_type] || (rule.strategy_type || '').toUpperCase()}
                          </Badge>
                        )}
                      </div>
                      {rule.description && (
                        <p className="text-xs text-zinc-400 mt-1">{rule.description}</p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
  };


  const renderLogsTab = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
          <History className="w-5 h-5 text-cyan-400" />
          Action Logs
        </h2>
        <Button
          variant="outline"
          onClick={fetchActionLogs}
          className="btn-outline"
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      <Card className="glass-card" data-testid="action-logs-card">
        <CardContent className="pt-6">
          {logsLoading ? (
            <div className="space-y-2">
              {Array(5).fill(0).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : actionLogs.length === 0 ? (
            <div className="text-center py-8">
              <FileText className="w-10 h-10 text-zinc-600 mx-auto mb-3" />
              <p className="text-zinc-400 text-sm">No action logs yet</p>
            </div>
          ) : (
            <div className="space-y-2">
              {actionLogs.map((log, idx) => {
                const actionKey = log.action || '';
                const actionLabel = ACTION_LABELS[actionKey] || (actionKey ? actionKey.replace(/_/g, ' ') : 'System Event');
                const actionColor = ACTION_COLORS[actionKey] || 'bg-zinc-700/50 text-zinc-400';
                const description = log.details || log.message || '';
                const snap = log.trade_snapshot || {};
                return (
                  <div
                    key={idx}
                    className="flex items-start gap-3 p-3 bg-zinc-800/30 rounded-lg hover:bg-zinc-800/50 transition-colors"
                  >
                    <Badge className={`${actionColor} whitespace-nowrap text-xs`}>
                      {actionLabel}
                    </Badge>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 text-sm flex-wrap">
                        <span className="font-semibold text-white">{log.symbol || snap.symbol || '—'}</span>
                        <Badge className={STRATEGY_COLORS[log.strategy_type || snap.strategy_type]} variant="outline">
                          {{ covered_call: 'CC', pmcc: 'PMCC', wheel: 'CSP', defensive: 'COLLAR' }[log.strategy_type || snap.strategy_type] || (log.strategy_type || snap.strategy_type || '').toUpperCase()}
                        </Badge>
                        {log.rule_name && (
                          <span className="text-xs text-violet-400">via &quot;{log.rule_name}&quot;</span>
                        )}
                      </div>
                      {description && (
                        <p className="text-xs text-zinc-400 mt-1">{description}</p>
                      )}
                      {/* Trade context chips */}
                      {(snap.dte_remaining != null || snap.current_delta != null || snap.premium_capture_pct != null) && (
                        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                          {snap.dte_remaining != null && (
                            <span className="text-xs bg-zinc-700/50 text-zinc-400 px-1.5 py-0.5 rounded">DTE {snap.dte_remaining}d</span>
                          )}
                          {snap.current_delta != null && (
                            <span className="text-xs bg-zinc-700/50 text-zinc-400 px-1.5 py-0.5 rounded">δ {snap.current_delta.toFixed(2)}</span>
                          )}
                          {snap.premium_capture_pct != null && (
                            <span className="text-xs bg-zinc-700/50 text-zinc-400 px-1.5 py-0.5 rounded">{snap.premium_capture_pct.toFixed(0)}% captured</span>
                          )}
                          {snap.unrealized_pnl != null && (
                            <span className={`text-xs px-1.5 py-0.5 rounded ${snap.unrealized_pnl >= 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                              P/L {snap.unrealized_pnl >= 0 ? '+' : ''}${snap.unrealized_pnl.toFixed(0)}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                    <span className="text-xs text-zinc-500 whitespace-nowrap">
                      {formatDateTime(log.timestamp)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Logs Pagination */}
          {logsPagination.pages > 1 && (
            <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-800">
              <span className="text-sm text-zinc-500">
                Page {logsPagination.page} of {logsPagination.pages}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setLogsPagination(p => ({ ...p, page: p.page - 1 }));
                    fetchActionLogs();
                  }}
                  disabled={logsPagination.page === 1}
                  className="btn-outline"
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setLogsPagination(p => ({ ...p, page: p.page + 1 }));
                    fetchActionLogs();
                  }}
                  disabled={logsPagination.page === logsPagination.pages}
                  className="btn-outline"
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );

  const renderPMCCTab = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <Layers className="w-5 h-5 text-violet-400" />
            PMCC Income Tracker
          </h2>
          <p className="text-zinc-400 text-sm mt-1">
            Track cumulative premium income vs LEAPS decay for your PMCC positions
          </p>
        </div>
        <Button
          variant="outline"
          onClick={fetchPMCCSummary}
          className="btn-outline"
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {pmccLoading ? (
        <div className="space-y-4">
          {Array(3).fill(0).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : !pmccSummary?.summary || pmccSummary.summary.length === 0 ? (
        <Card className="glass-card">
          <CardContent className="py-12 text-center">
            <Layers className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-white mb-2">No PMCC Positions</h3>
            <p className="text-zinc-400 text-sm">
              Add PMCC trades from the PMCC screener to track income vs LEAPS decay
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Overall Summary */}
          <div className="grid md:grid-cols-4 gap-4">
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Total LEAPS Investment</div>
                <div className="text-xl font-bold font-mono text-white">
                  {formatCurrency(pmccSummary.overall.total_leaps_investment)}
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Total Premium Income</div>
                <div className="text-xl font-bold font-mono text-emerald-400">
                  {formatCurrency(pmccSummary.overall.total_premium_income)}
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Income / Cost Ratio</div>
                <div className={`text-xl font-bold font-mono ${pmccSummary.overall.overall_income_ratio >= 20 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {pmccSummary.overall.overall_income_ratio.toFixed(1)}%
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Active Positions</div>
                <div className="text-xl font-bold font-mono text-blue-400">
                  {pmccSummary.overall.active_positions} / {pmccSummary.overall.total_pmcc_positions}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Individual Position Cards */}
          <div className="space-y-4">
            {pmccSummary.summary.map(position => (
              <Card key={position.original_trade_id} className="glass-card">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold text-white">{position.symbol}</span>
                        <Badge className={STATUS_COLORS[position.status]}>{position.status}</Badge>
                        {position.roll_count > 0 && (
                          <Badge className="bg-cyan-500/20 text-cyan-400">
                            {position.roll_count} rolls
                          </Badge>
                        )}
                        <Badge className={
                          position.health === 'good' ? 'bg-emerald-500/20 text-emerald-400' :
                          position.health === 'warning' ? 'bg-amber-500/20 text-amber-400' :
                          'bg-red-500/20 text-red-400'
                        }>
                          {position.health === 'good' ? <CheckCircle2 className="w-3 h-3 mr-1" /> :
                           position.health === 'warning' ? <AlertTriangle className="w-3 h-3 mr-1" /> :
                           <AlertCircle className="w-3 h-3 mr-1" />}
                          {position.health}
                        </Badge>
                      </div>
                      <div className="text-xs text-zinc-400 mt-1">
                        LEAPS: ${position.leaps_strike} exp {formatDate(position.leaps_expiry)} • {position.days_to_leaps_expiry}d remaining
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-4">
                    <div>
                      <div className="text-xs text-zinc-500">LEAPS Cost</div>
                      <div className="text-sm font-mono text-white">{formatCurrency(position.leaps_cost)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-zinc-500">Premium Income</div>
                      <div className="text-sm font-mono text-emerald-400">{formatCurrency(position.total_premium_received)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-zinc-500">Realized P/L</div>
                      <div className={`text-sm font-mono ${position.total_realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {formatCurrency(position.total_realized_pnl)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-zinc-500">Income / Cost</div>
                      <div className={`text-sm font-mono ${position.income_to_cost_ratio >= 20 ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {position.income_to_cost_ratio.toFixed(1)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-zinc-500">Est. LEAPS Decay</div>
                      <div className="text-sm font-mono text-red-400">
                        ~{position.estimated_leaps_decay_pct.toFixed(1)}%
                      </div>
                    </div>
                  </div>

                  {/* Progress bar showing income vs decay */}
                  <div className="mt-4">
                    <div className="flex justify-between text-xs text-zinc-500 mb-1">
                      <span>Income vs LEAPS Decay</span>
                      <span>{position.income_to_cost_ratio.toFixed(1)}% income / {position.estimated_leaps_decay_pct.toFixed(1)}% decay</span>
                    </div>
                    <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
                      <div 
                        className={`h-full transition-all ${
                          position.income_to_cost_ratio >= position.estimated_leaps_decay_pct 
                            ? 'bg-emerald-500' 
                            : position.income_to_cost_ratio >= position.estimated_leaps_decay_pct * 0.5
                            ? 'bg-amber-500'
                            : 'bg-red-500'
                        }`}
                        style={{ width: `${Math.min(100, (position.income_to_cost_ratio / Math.max(position.estimated_leaps_decay_pct, 1)) * 100)}%` }}
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );

  const renderAnalyticsTab = () => {
    const availableSymbols = [...new Set(trades.map(t => t.symbol))].sort();
    const a = analyzerData?.section_a_performance;
    const b = analyzerData?.section_b_risk;
    const c = analyzerData?.section_c_action_queue || [];
    const d = analyzerData?.section_d_strategy_quality || [];
    const e = analyzerData?.section_e_advanced;
    const sq = analyzerData?.sample_quality || {};

    const MetricCard = ({ label, value, sub, color = 'text-white', tooltip }) => (
      <div className="p-3 bg-zinc-800/50 rounded-lg" title={tooltip || ''}>
        <div className="text-xs text-zinc-500 mb-1 flex items-center gap-1">
          {label}
          {tooltip && <span className="text-zinc-600 cursor-help" title={tooltip}>ⓘ</span>}
        </div>
        <div className={`text-xl font-bold ${color}`}>{value ?? '—'}</div>
        {sub && <div className="text-xs text-zinc-600 mt-0.5">{sub}</div>}
      </div>
    );

    // Smart action label system
    const getActionLabel = (row) => {
      const delta = row.delta ?? 0;
      const dte = row.dte ?? 99;
      const capture = row.capture_pct ?? 0;
      if (delta >= 0.50)              return { label: '🔴 Roll or manage risk',    cls: 'bg-red-500/20 text-red-400 border-red-500/30' };
      if (capture >= 90)              return { label: '⚪ Close (cycle complete)',  cls: 'bg-zinc-700/50 text-zinc-300 border-zinc-600/30' };
      if (dte <= 7 && capture >= 70)  return { label: '🟢 Close near target',      cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' };
      if (capture < 50 && dte <= 14)  return { label: '🟡 Roll candidate',         cls: 'bg-amber-500/20 text-amber-400 border-amber-500/30' };
      return                                 { label: '⚪ Monitor',                cls: 'bg-zinc-700/50 text-zinc-400 border-zinc-600/30' };
    };

    // Derived values
    const openPremium = a ? Math.max(0, (a.net_premium_collected || 0) - (a.net_premium_kept || 0)) : 0;
    const openDrawdown = b?.open_drawdown ?? 0;
    const worstDrawdown = b?.worst_drawdown ?? 0;
    const worstDrawdownSymbol = b?.worst_drawdown_symbol ?? null;
    const assignmentRiskCount = b?.assignment_exposure ?? 0;
    const concentrationRisk = b ? (b.largest_position_weight > 40 ? 'High' : b.largest_position_weight > 25 ? 'Medium' : 'Low') : '—';
    const concentrationColor = b ? (b.largest_position_weight > 40 ? 'text-red-400' : b.largest_position_weight > 25 ? 'text-amber-400' : 'text-emerald-400') : 'text-zinc-400';

    // Smart warnings
    const warnings = [];
    if (sq.closed_trade_count != null && sq.closed_trade_count < 3) warnings.push(`Only ${sq.closed_trade_count} closed trade${sq.closed_trade_count !== 1 ? 's' : ''} — metrics may not be statistically reliable`);
    if (assignmentRiskCount > 0) warnings.push(`${assignmentRiskCount} position${assignmentRiskCount !== 1 ? 's' : ''} at high assignment risk (Δ > 0.50)`);
    const expiringCount = c.filter(r => (r.dte ?? 99) <= 7).length;
    if (expiringCount > 0) warnings.push(`${expiringCount} trade${expiringCount !== 1 ? 's' : ''} expiring within 7 days`);

    return (
    <div className="space-y-6" data-testid="analyzer-page">

      {/* ── HEADER BAR ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-cyan-400" />
            Analyzer
          </h2>
          <p className="text-zinc-500 text-xs mt-0.5">Track income, risk, and trade management — not just P/L</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={analyticsStrategy || "all"} onValueChange={(v) => setAnalyticsStrategy(v === "all" ? "" : v)}>
            <SelectTrigger className="w-36 h-8 bg-zinc-800/50 border-zinc-700" data-testid="strategy-filter">
              <SelectValue placeholder="All Strategies" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-700">
              <SelectItem value="all">All Strategies</SelectItem>
              <SelectItem value="covered_call">Covered Call</SelectItem>
              <SelectItem value="pmcc">PMCC</SelectItem>
              <SelectItem value="wheel">CSP</SelectItem>
              <SelectItem value="defensive">Collar</SelectItem>
            </SelectContent>
          </Select>
          <Select value={analyzerSymbol || "all"} onValueChange={(v) => setAnalyzerSymbol(v === "all" ? "" : v)}>
            <SelectTrigger className="w-32 h-8 bg-zinc-800/50 border-zinc-700" data-testid="symbol-filter">
              <SelectValue placeholder="All Symbols" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-700">
              <SelectItem value="all">All Symbols</SelectItem>
              {availableSymbols.map(sym => (
                <SelectItem key={sym} value={sym}>{sym}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={analyticsTimeframe} onValueChange={setAnalyticsTimeframe}>
            <SelectTrigger className="w-28 h-8 bg-zinc-800/50 border-zinc-700" data-testid="timeframe-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-700">
              <SelectItem value="all">All Time</SelectItem>
              <SelectItem value="30d">30 Days</SelectItem>
              <SelectItem value="90d">90 Days</SelectItem>
              <SelectItem value="1y">1 Year</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={fetchAnalyzerData} className="btn-outline h-8">
            <RefreshCw className={`w-4 h-4 ${analyzerLoading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {analyzerLoading ? (
        <div className="space-y-4">
          {Array(4).fill(0).map((_, i) => <Skeleton key={i} className="h-32 w-full" />)}
        </div>
      ) : !a ? (
        <Card className="glass-card">
          <CardContent className="py-12 text-center">
            <BarChart3 className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-white mb-2">No Data Available</h3>
            <p className="text-zinc-400 text-sm">
              {analyticsStrategy || analyzerSymbol
                ? `No trades found for the selected filter. Try switching to "All Strategies" or "All Symbols".`
                : 'Add trades to the simulator to see analyzer metrics.'}
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* ── 1. PERFORMANCE SNAPSHOT ── */}
          <Card className="glass-card border-blue-500/20">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <DollarSign className="w-4 h-4 text-blue-400" />
                <span className="text-blue-400">Performance Snapshot</span>
                <span className="text-zinc-500 font-normal">— How much am I making vs carrying?</span>
                <span className="ml-auto text-xs text-zinc-600">{a.total_trades} trades · {a.open_count} open · {a.closed_count} closed</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Premium income row */}
              <div>
                <div className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Premium Income Engine</div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <MetricCard
                    label="Gross Premium Sold"
                    value={formatCurrency(a.net_premium_collected)}
                    sub="Total premium collected across all trades"
                    color="text-emerald-400"
                    tooltip="Total premium collected across all trades. Includes both locked and at-risk premium."
                  />
                  <MetricCard
                    label="Realized Premium (Kept)"
                    value={formatCurrency(a.net_premium_kept)}
                    sub="Locked in — closed positions only"
                    color="text-emerald-400"
                    tooltip="Premium fully locked in from closed trades after buyback costs."
                  />
                  <MetricCard
                    label="Open Premium (At Risk)"
                    value={formatCurrency(openPremium)}
                    sub="Still at risk in open positions"
                    color="text-amber-400"
                    tooltip="Open premium can reduce if positions move against you. Not yet locked in."
                  />
                </div>
              </div>
              {/* P/L row */}
              <div>
                <div className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Realized vs Unrealized</div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <MetricCard label="Realized P/L" value={formatCurrency(a.realized_pnl)} sub="Locked — closed trades" color={a.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                  <MetricCard label="Open P/L (mark-to-market)" value={formatCurrency(a.unrealized_pnl)} sub="Temporary — open positions" color={a.unrealized_pnl >= 0 ? 'text-blue-400' : 'text-amber-400'} tooltip="Mark-to-market estimate. Changes daily with price moves. Not yet realized." />
                  <MetricCard label="Total P/L" value={formatCurrency(a.total_pnl)} sub="Realized + unrealized" color={a.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                </div>
              </div>
              {/* Efficiency row */}
              <div>
                <div className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Efficiency</div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <div className="p-3 bg-zinc-800/50 rounded-lg">
                    <div className="text-xs text-zinc-500 mb-1">ROI on Capital</div>
                    <div className={`text-xl font-bold ${a.roi_on_peak_capital >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{a.roi_on_peak_capital}%</div>
                    <div className="text-xs text-zinc-600">Realized only ÷ peak deployed</div>
                    {a.total_roi != null && (
                      <div className={`text-xs mt-1 font-medium ${a.total_roi >= 0 ? 'text-blue-400' : 'text-amber-400'}`}>
                        Total (incl. open): {a.total_roi}%
                      </div>
                    )}
                  </div>
                  {a.closed_count >= 5 ? (
                    <MetricCard label="Avg Trade Return" value={`${a.avg_closed_trade_return_pct}%`} sub="Per closed trade" color={a.avg_closed_trade_return_pct >= 0 ? 'text-emerald-400' : 'text-amber-400'} />
                  ) : (
                    <div className="p-3 bg-zinc-800/50 rounded-lg">
                      <div className="text-xs text-zinc-500 mb-1">Avg Trade Return</div>
                      <div className="text-sm text-zinc-600 mt-2">Need 5+ closed trades</div>
                      <div className="text-xs text-zinc-700">{a.closed_count} closed so far</div>
                    </div>
                  )}
                  <MetricCard label="Avg Hold Days" value={`${a.avg_hold_days}d`} sub="Closed trades" color="text-zinc-300" />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* ── 2. RISK & EXPOSURE ── */}
          <Card className="glass-card border-amber-500/20">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-amber-400" />
                <span className="text-amber-400">Risk & Exposure</span>
                <span className="text-zinc-500 font-normal">— Where can things go wrong?</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                <MetricCard label="Capital at Risk" value={formatCurrency(b.current_capital_at_risk)} sub="Current open positions" color="text-zinc-200" />
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Assignment Risk</div>
                  <div className={`text-xl font-bold ${assignmentRiskCount > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                    {assignmentRiskCount} {assignmentRiskCount === 1 ? 'position' : 'positions'}
                  </div>
                  <div className="text-xs text-zinc-600">Delta ≥ 0.50</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Open Drawdown</div>
                  <div className={`text-xl font-bold ${openDrawdown < 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                    {openDrawdown < 0 ? formatCurrency(openDrawdown) : 'None'}
                  </div>
                  <div className="text-xs text-zinc-600">
                    {openDrawdown < 0
                      ? `${b.open_drawdown_count} position${b.open_drawdown_count !== 1 ? 's' : ''} underwater`
                      : 'All positions healthy'}
                  </div>
                  {worstDrawdown < 0 && worstDrawdownSymbol && (
                    <div className="text-xs text-amber-500 mt-1">Worst: {worstDrawdownSymbol} {formatCurrency(worstDrawdown)}</div>
                  )}
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Concentration Risk</div>
                  <div className={`text-xl font-bold ${concentrationColor}`}>{concentrationRisk}</div>
                  <div className="text-xs text-zinc-600">Largest position: {b.largest_position_weight}% of capital</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Needs Management</div>
                  <div className={`text-xl font-bold ${b.trades_needing_action > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                    {b.trades_needing_action}
                  </div>
                  {b.trades_needing_action > 0 ? (
                    <div className="text-xs text-zinc-600 space-y-0.5 mt-1">
                      {b.near_expiry_count > 0 && <div>{b.near_expiry_count} near expiry</div>}
                      {b.high_delta_count > 0 && <div>{b.high_delta_count} high delta</div>}
                      {b.both_count > 0 && <div>{b.both_count} both</div>}
                    </div>
                  ) : (
                    <div className="text-xs text-zinc-600">All positions healthy</div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* ── 3. ACTION QUEUE (PRIMARY) ── */}
          <Card className="glass-card border-rose-500/20">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-rose-400" />
                <span className="text-rose-400">Action Queue</span>
                <span className="text-zinc-500 font-normal">— What do I do today?</span>
                <span className="ml-auto text-xs text-zinc-600">{c.length} open trade{c.length !== 1 ? 's' : ''}</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {c.length === 0 ? (
                <div className="text-center py-6 text-zinc-500 text-sm">No open trades — add trades to see action recommendations</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-zinc-500 border-b border-zinc-800 text-xs uppercase tracking-wider">
                        <th className="pb-2">Symbol</th>
                        <th className="pb-2">Strategy</th>
                        <th className="pb-2 text-right">Strike</th>
                        <th className="pb-2 text-right">DTE</th>
                        <th className="pb-2 text-right">Delta</th>
                        <th className="pb-2 text-right">Capture</th>
                        <th className="pb-2 text-right">Unrealized P/L</th>
                        <th className="pb-2 pl-3">Recommended Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {c.map((row, idx) => {
                        const action = getActionLabel(row);
                        return (
                          <tr key={row.trade_id || idx} className="border-b border-zinc-800/50 hover:bg-zinc-700/20">
                            <td className="py-2.5 font-semibold text-white">{row.symbol}</td>
                            <td className="py-2.5">
                              <Badge className={row.strategy === 'pmcc' ? 'bg-violet-500/20 text-violet-400 border-violet-500/30 text-xs' : 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs'}>
                                {row.strategy === 'pmcc' ? 'PMCC' : 'CC'}
                              </Badge>
                            </td>
                            <td className="py-2.5 text-right font-mono text-zinc-300">{row.strike ? `$${row.strike}` : '—'}</td>
                            <td className={`py-2.5 text-right font-mono ${(row.dte ?? 99) <= 7 ? 'text-red-400' : (row.dte ?? 99) <= 14 ? 'text-amber-400' : 'text-zinc-300'}`}>
                              {row.dte != null ? `${row.dte}d` : '—'}
                            </td>
                            <td className={`py-2.5 text-right font-mono ${(row.delta ?? 0) >= 0.60 ? 'text-red-400' : (row.delta ?? 0) >= 0.40 ? 'text-amber-400' : 'text-zinc-400'}`}>
                              {row.delta != null ? row.delta.toFixed(2) : '—'}
                            </td>
                            <td className="py-2.5 text-right font-mono text-zinc-300">
                              {row.capture_pct != null ? `${row.capture_pct.toFixed(0)}%` : '—'}
                            </td>
                            <td className={`py-2.5 text-right font-mono ${(row.unrealized_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-amber-400'}`}>
                              {row.unrealized_pnl != null ? formatCurrency(row.unrealized_pnl) : '—'}
                            </td>
                            <td className="py-2.5 pl-3">
                              <span className={`text-xs px-2 py-1 rounded-full border font-medium ${action.cls}`}>
                                {action.label}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── 4. STRATEGY SNAPSHOT ── */}
          <Card className="glass-card border-emerald-500/20">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Activity className="w-4 h-4 text-emerald-400" />
                <span className="text-emerald-400">Strategy Snapshot</span>
                <span className="text-zinc-500 font-normal">— How is each strategy performing?</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {d.length === 0 ? (
                <div className="text-center py-6 text-zinc-500 text-sm">No strategy data available</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-zinc-500 border-b border-zinc-800 text-xs uppercase tracking-wider">
                        <th className="pb-2">Strategy</th>
                        <th className="pb-2 text-right">Avg Hold</th>
                        <th className="pb-2 text-right">Assignment Risk</th>
                        <th className="pb-2 text-right">Realized P/L</th>
                        <th className="pb-2 text-right">Unrealized P/L</th>
                        <th className="pb-2 text-right">Total P/L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.map((s, idx) => {
                        const totalPL = (s.realized_pnl || 0) + (s.unrealized_pnl || 0);
                        return (
                        <tr key={idx} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                          <td className="py-3 font-semibold text-white">{s.strategy_label}</td>
                          <td className="py-3 text-right text-zinc-300">{s.avg_hold_days ?? 0}d</td>
                          <td className={`py-3 text-right font-mono ${s.assignment_rate > 30 ? 'text-amber-400' : 'text-zinc-400'}`}>
                            {s.assignment_rate != null ? `${s.assignment_rate}%` : '—'}
                          </td>
                          <td className={`py-3 text-right font-mono font-medium ${s.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatCurrency(s.realized_pnl)}
                          </td>
                          <td className={`py-3 text-right font-mono text-sm ${s.unrealized_pnl >= 0 ? 'text-blue-400' : 'text-amber-400'}`}>
                            {formatCurrency(s.unrealized_pnl)}
                          </td>
                          <td className={`py-3 text-right font-mono font-bold ${totalPL >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatCurrency(totalPL)}
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── 5. P/L VISUAL ── */}
          {d.length > 0 && (
            <Card className="glass-card border-zinc-700/50">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-zinc-400" />
                  <span className="text-zinc-300">P/L Visual</span>
                  <span className="text-zinc-500 font-normal">— Realized vs Unrealized by strategy</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-32">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={d.map(s => ({ name: s.strategy_label, Realized: s.realized_pnl, Unrealized: s.unrealized_pnl }))} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                      <XAxis type="number" stroke="#555" fontSize={10} tickFormatter={(v) => Math.abs(v) >= 1000 ? `$${(v/1000).toFixed(1)}k` : `$${v.toFixed(0)}`} />
                      <YAxis type="category" dataKey="name" stroke="#555" fontSize={10} width={95} />
                      <Tooltip contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }} formatter={(v) => formatCurrency(v)} />
                      <Bar dataKey="Realized" fill="#10b981" name="Realized (locked)" radius={[0, 4, 4, 0]} />
                      <Bar dataKey="Unrealized" fill="#6366f1" name="Open P/L (mark-to-market)" radius={[0, 4, 4, 0]} />
                      <Legend wrapperStyle={{ fontSize: '11px', color: '#71717a' }} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex items-center gap-4 mt-2 text-xs text-zinc-500">
                  <span className="flex items-center gap-1"><span className="w-3 h-2 bg-emerald-500 rounded inline-block" /> Realized — locked in</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-2 bg-indigo-500 rounded inline-block" /> Open P/L — mark-to-market</span>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ── 6. SMART WARNINGS ── */}
          {warnings.length > 0 && (
            <div className="space-y-2">
              {warnings.map((w, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                  <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                  {w}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Trade Health & AI Actions ─────────────────────────────────── */}
      <Card className="bg-zinc-800/50 border-zinc-700">
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            Trade Health &amp; AI Actions
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={handleUpdatePrices} disabled={updating} className="h-7 text-xs text-zinc-400">
              <RefreshCw className={`w-3 h-3 mr-1 ${updating ? 'animate-spin' : ''}`} />
              {updating ? 'Updating...' : 'Refresh Prices'}
            </Button>
            <Button variant="ghost" size="sm" onClick={fetchTradesHealth} className="h-7 text-xs text-zinc-400">
              <RefreshCw className={`w-3 h-3 mr-1 ${healthLoading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {healthLoading ? (
            <div className="space-y-2">{[1,2,3].map(i => <div key={i} className="h-10 bg-zinc-700/30 rounded animate-pulse" />)}</div>
          ) : !healthData || healthData.trades.length === 0 ? (
            <div className="text-center py-6 text-zinc-500 text-sm">No open trades — add trades to populate health data</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-700 text-xs text-zinc-500 uppercase tracking-wider">
                    <th className="py-2 text-left">Symbol</th>
                    <th className="py-2 text-left">Strategy</th>
                    <th className="py-2 text-right">DTE</th>
                    <th className="py-2 text-right">Delta</th>
                    <th className="py-2 text-right">Yield%</th>
                    <th className="py-2 text-right">Capture%</th>
                    <th className="py-2 text-right">P/L</th>
                    <th className="py-2 text-right">ROI%</th>
                    <th className="py-2 text-center">Pricing Source</th>
                  </tr>
                </thead>
                <tbody>
                  {healthData.trades.map((row) => {
                    const plColor = row.total_pl == null ? 'text-zinc-500' : row.total_pl >= 0 ? 'text-emerald-400' : 'text-red-400';
                    const roiColor = row.roi_pct == null ? 'text-zinc-500' : row.roi_pct >= 0 ? 'text-emerald-400' : 'text-red-400';
                    const capColor = row.capture_pct >= 75 ? 'text-emerald-400' : row.capture_pct >= 40 ? 'text-yellow-400' : 'text-red-400';
                    const dteColor = row.dte <= 7 ? 'text-orange-400' : row.dte <= 14 ? 'text-yellow-400' : 'text-zinc-300';
                    const deltaColor = row.delta >= 0.50 ? 'text-red-400' : row.delta >= 0.35 ? 'text-yellow-400' : 'text-emerald-400';
                    return (
                      <tr key={row.trade_id} className="border-b border-zinc-800/50 hover:bg-zinc-700/20">
                        <td className="py-2.5 font-semibold text-white">{row.symbol}</td>
                        <td className="py-2.5">
                          <Badge className={row.strategy === 'pmcc' ? 'bg-violet-500/20 text-violet-400 border-violet-500/30 text-xs' : 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs'}>
                            {row.strategy === 'pmcc' ? 'PMCC' : 'CC'}
                          </Badge>
                        </td>
                        <td className={`py-2.5 text-right font-mono ${dteColor}`}>{row.dte ?? '-'}d</td>
                        <td className={`py-2.5 text-right font-mono ${deltaColor}`}>{row.delta != null ? row.delta.toFixed(2) : '-'}</td>
                        <td className="py-2.5 text-right font-mono text-zinc-300">{row.yield_pct != null ? `${row.yield_pct.toFixed(2)}%` : '-'}</td>
                        <td className={`py-2.5 text-right font-mono ${capColor}`}>{row.capture_pct != null ? `${row.capture_pct.toFixed(1)}%` : '-'}</td>
                        <td className={`py-2.5 text-right font-mono font-medium ${plColor}`}>
                          {row.total_pl != null ? `$${row.total_pl.toFixed(0)}` : '—'}
                        </td>
                        <td className={`py-2.5 text-right font-mono ${roiColor}`}>
                          {row.roi_pct != null ? `${row.roi_pct.toFixed(2)}%` : '—'}
                        </td>
                        <td className="py-2.5 text-center">
                          {row.data_quality === 'missing_option_mark' ? (
                            <Badge className="bg-orange-500/20 text-orange-400 border-orange-500/30 text-xs">Model</Badge>
                          ) : row.data_quality === 'bs_estimate' ? (
                            <Badge className="bg-zinc-500/20 text-zinc-400 border-zinc-500/30 text-xs">Model</Badge>
                          ) : (
                            <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">Market</Badge>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="text-xs text-zinc-600 mt-3">
                Market = real bid/ask marks • Model = Black-Scholes estimate. Click <b>Refresh Prices</b> above to update to live market data.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
  };

  return (
    <div className="space-y-6" data-testid="simulator-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Play className="w-8 h-8 text-violet-500" />
            Trade Simulator
          </h1>
          <p className="text-zinc-400 mt-1">
            Forward-running simulation engine for strategy validation
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleClearAll}
            className="btn-outline text-red-400 hover:text-red-300"
            data-testid="clear-all-btn"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Clear All
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="bg-zinc-800/50 border border-zinc-700/50">
          <TabsTrigger value="trades" className="data-[state=active]:bg-violet-600 data-[state=active]:text-white">
            <Activity className="w-4 h-4 mr-2" />
            Trades
          </TabsTrigger>
          <TabsTrigger value="rules" className="data-[state=active]:bg-violet-600 data-[state=active]:text-white">
            <Settings className="w-4 h-4 mr-2" />
            Rules
          </TabsTrigger>
          <TabsTrigger value="logs" className="data-[state=active]:bg-violet-600 data-[state=active]:text-white">
            <History className="w-4 h-4 mr-2" />
            Logs
          </TabsTrigger>
          <TabsTrigger value="pmcc" className="data-[state=active]:bg-violet-600 data-[state=active]:text-white">
            <Layers className="w-4 h-4 mr-2" />
            PMCC Tracker
          </TabsTrigger>
          <TabsTrigger value="analytics" className="data-[state=active]:bg-violet-600 data-[state=active]:text-white">
            <BarChart3 className="w-4 h-4 mr-2" />
            Analyzer
          </TabsTrigger>
        </TabsList>

        <TabsContent value="trades" className="space-y-6">
          {renderTradesTab()}
        </TabsContent>

        <TabsContent value="rules" className="space-y-6">
          {renderRulesTab()}
        </TabsContent>

        <TabsContent value="logs" className="space-y-6">
          {renderLogsTab()}
        </TabsContent>

        <TabsContent value="pmcc" className="space-y-6">
          {renderPMCCTab()}
        </TabsContent>

        <TabsContent value="analytics" className="space-y-6">
          {renderAnalyticsTab()}
        </TabsContent>
      </Tabs>

      {/* Trade Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="bg-zinc-900 border-zinc-800 max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <span className="text-white">{selectedTrade?.symbol}</span>
              <Badge className={STRATEGY_COLORS[selectedTrade?.strategy_type]}>
                {selectedTrade?.strategy_type === 'covered_call' ? 'Covered Call' : 'PMCC'}
              </Badge>
              <Badge className={STATUS_COLORS[selectedTrade?.status]}>
                {selectedTrade?.status}
              </Badge>
              {selectedTrade?.roll_count > 0 && (
                <Badge className="bg-cyan-500/20 text-cyan-400">
                  Roll #{selectedTrade.roll_count}
                </Badge>
              )}
            </DialogTitle>
          </DialogHeader>
          
          {selectedTrade && (
            <div className="space-y-6 pt-4">
              {/* Entry Details */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Entry Price</div>
                  <div className="text-lg font-semibold text-white">${selectedTrade.entry_underlying_price?.toFixed(2)}</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Current Price</div>
                  <div className="text-lg font-semibold text-white">${selectedTrade.current_underlying_price?.toFixed(2)}</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Breakeven</div>
                  <div className="text-lg font-semibold text-white">${selectedTrade.breakeven?.toFixed(2)}</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">{isLive(selectedTrade.status) ? 'Unrealized P/L' : 'Final P/L'}</div>
                  <div className={`text-lg font-semibold ${
                    isLive(selectedTrade.status)
                      ? (selectedTrade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                      : (selectedTrade.final_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                  }`}>
                    {isLive(selectedTrade.status) 
                      ? formatCurrency(selectedTrade.unrealized_pnl)
                      : formatCurrency(selectedTrade.final_pnl)
                    }
                  </div>
                </div>
              </div>

              {/* Option Details */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-zinc-500">Short Call:</span>
                  <span className="ml-2 text-white">
                    {formatOptionContract(selectedTrade.short_call_expiry, selectedTrade.short_call_strike)}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-500">Premium:</span>
                  <span className="ml-2 text-emerald-400">${selectedTrade.short_call_premium?.toFixed(2)}</span>
                </div>
                {selectedTrade.strategy_type === 'pmcc' && (
                  <>
                    <div>
                      <span className="text-zinc-500">LEAPS:</span>
                      <span className="ml-2 text-white">
                        {formatOptionContract(selectedTrade.leaps_expiry, selectedTrade.leaps_strike)}
                      </span>
                    </div>
                    <div>
                      <span className="text-zinc-500">LEAPS Cost:</span>
                      <span className="ml-2 text-amber-400">${selectedTrade.leaps_premium?.toFixed(2)}</span>
                    </div>
                  </>
                )}
                <div>
                  <span className="text-zinc-500">Contracts:</span>
                  <span className="ml-2 text-white">{selectedTrade.contracts}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Capital Deployed:</span>
                  <span className="ml-2 text-white">{formatCurrency(selectedTrade.capital_deployed)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Max Profit:</span>
                  <span className="ml-2 text-emerald-400">{formatCurrency(selectedTrade.max_profit)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Max Loss:</span>
                  <span className="ml-2 text-red-400">{formatCurrency(selectedTrade.max_loss)}</span>
                </div>
                <div>
                  <span className="text-zinc-500">Days Held:</span>
                  <span className="ml-2 text-white">{selectedTrade.days_held}</span>
                </div>
                <div>
                  <span className="text-zinc-500">DTE Remaining:</span>
                  <span className={`ml-2 ${selectedTrade.dte_remaining <= 7 ? 'text-amber-400' : 'text-white'}`}>
                    {isLive(selectedTrade.status) ? `${selectedTrade.dte_remaining}d` : '-'}
                  </span>
                </div>
                {selectedTrade.cumulative_premium && (
                  <div className="col-span-2">
                    <span className="text-zinc-500">Cumulative Premium (incl. rolls):</span>
                    <span className="ml-2 text-emerald-400">{formatCurrency(selectedTrade.cumulative_premium)}</span>
                  </div>
                )}
              </div>

              {/* Greeks Section */}
              {isLive(selectedTrade.status) && (
                <div className="p-4 bg-zinc-800/30 rounded-lg">
                  <h4 className="text-sm font-medium text-zinc-400 mb-3 flex items-center gap-2">
                    <Activity className="w-4 h-4" />
                    Current Greeks & Volatility
                  </h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">Delta</div>
                      <div className="text-cyan-400 font-mono font-semibold">
                        {selectedTrade.current_delta?.toFixed(3) || selectedTrade.short_call_delta?.toFixed(3) || '-'}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">Theta</div>
                      <div className="text-red-400 font-mono font-semibold">
                        {selectedTrade.current_theta ? `$${selectedTrade.current_theta.toFixed(2)}/day` : '-'}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">IV</div>
                      <div className="text-violet-400 font-mono font-semibold">
                        {selectedTrade.iv ? `${(selectedTrade.iv * 100).toFixed(1)}%` : (selectedTrade.short_call_iv ? `${(selectedTrade.short_call_iv * 100).toFixed(1)}%` : '-')}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">IV Rank</div>
                      <div className="text-amber-400 font-mono font-semibold">
                        {selectedTrade.iv_rank ? `${selectedTrade.iv_rank.toFixed(0)}%` : '-'}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">Open Interest</div>
                      <div className="text-zinc-300 font-mono font-semibold">
                        {selectedTrade.open_interest ? selectedTrade.open_interest.toLocaleString() : '-'}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">Premium Captured</div>
                      <div className={`font-mono font-semibold ${(selectedTrade.premium_capture_pct || 0) >= 50 ? 'text-emerald-400' : 'text-zinc-400'}`}>
                        {selectedTrade.premium_capture_pct?.toFixed(1) || 0}%
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 pt-3 border-t border-zinc-700 flex justify-between text-xs">
                    <span className="text-zinc-500">Current Option Value:</span>
                    <span className="text-white font-mono">${selectedTrade.current_option_value?.toFixed(2) || selectedTrade.short_call_premium?.toFixed(2)}</span>
                  </div>
                </div>
              )}

              {/* Action Log */}
              {selectedTrade.action_log && selectedTrade.action_log.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-zinc-400 mb-2 flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Action Log
                  </h4>
                  <div className="bg-zinc-800/50 rounded-lg p-3 space-y-2 max-h-48 overflow-y-auto">
                    {selectedTrade.action_log.slice().reverse().map((log, idx) => (
                      <div key={idx} className="text-xs flex items-start gap-2">
                        <span className="text-zinc-500 whitespace-nowrap">{formatDateTime(log.timestamp)}</span>
                        <Badge className={ACTION_COLORS[log.action] || 'bg-zinc-500/20 text-zinc-400'}>
                          {log.action}
                        </Badge>
                        <span className="text-zinc-300">{log.details}</span>
                        {log.rule_name && (
                          <span className="text-violet-400">(Rule: {log.rule_name})</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-end gap-2 pt-4 border-t border-zinc-800">
                <Button
                  variant="outline"
                  onClick={() => handleDeleteTrade(selectedTrade.id)}
                  className="text-red-400 hover:text-red-300"
                >
                  <Trash2 className="w-4 h-4 mr-2" />
                  Delete
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setDetailOpen(false)}
                  className="btn-outline"
                >
                  Close
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Evaluation Results Dialog */}
      <Dialog open={evalResultsOpen} onOpenChange={setEvalResultsOpen}>
        <DialogContent className="bg-zinc-900 border-zinc-800 max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-violet-400" />
              Rule Evaluation Results
              {evaluationResults?.dry_run && (
                <Badge className="bg-amber-500/20 text-amber-400">Dry Run</Badge>
              )}
            </DialogTitle>
          </DialogHeader>
          
          {evaluationResults && (
            <div className="space-y-4 pt-4">
              <div className="text-sm text-zinc-400">
                Previewed {evaluationResults.results?.length ?? 0} trades
              </div>

              {!evaluationResults.results?.length ? (
                <div className="text-center py-8">
                  <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto mb-3" />
                  <p className="text-zinc-300">No active trades to preview</p>
                  <p className="text-zinc-500 text-sm">Add trades to the simulator to see decisions</p>
                </div>
              ) : (
                <div className="space-y-3 max-h-96 overflow-y-auto">
                  {evaluationResults.results.map((result, idx) => (
                    <div key={idx} className="p-3 bg-zinc-800/50 rounded-lg">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-semibold text-white">{result.symbol}</span>
                        <Badge className={STRATEGY_COLORS[result.strategy]}>
                          {{ covered_call: 'CC', pmcc: 'PMCC', wheel: 'CSP', defensive: 'COLLAR' }[result.strategy] || (result.strategy || '').toUpperCase()}
                        </Badge>
                        {result.decision && (
                          <Badge className={
                            result.decision === 'roll' ? 'bg-violet-500/20 text-violet-400' :
                            result.decision === 'close' ? 'bg-red-500/20 text-red-400' :
                            result.decision === 'hold' ? 'bg-emerald-500/20 text-emerald-400' :
                            'bg-zinc-500/20 text-zinc-400'
                          }>
                            {result.decision}
                          </Badge>
                        )}
                      </div>
                      {result.reason && (
                        <p className="text-xs text-zinc-400 mb-2">{result.reason}</p>
                      )}
                      {result.matched_rules?.length > 0 && (
                        <div className="space-y-1">
                          {result.matched_rules.map((ruleName, ruleIdx) => (
                            <div key={ruleIdx} className="text-xs text-zinc-500 flex items-center gap-1">
                              <span className="w-1 h-1 rounded-full bg-zinc-600 inline-block" />
                              {typeof ruleName === 'string' ? ruleName : (ruleName.rule_name || ruleName.name || JSON.stringify(ruleName))}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <DialogFooter>
                <Button variant="outline" onClick={() => setEvalResultsOpen(false)} className="btn-outline">
                  Close
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
      {/* ── AI Manage Modal ─────────────────────────────────────────── */}
      {manageOpen && manageTrade && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1000, padding: '20px'
        }}>
          <div style={{
            background: '#1a1a2e', border: '1px solid #7c3aed',
            borderRadius: '12px', padding: '28px', width: '100%', maxWidth: '600px',
            maxHeight: '85vh', overflowY: 'auto', color: '#e2e8f0'
          }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
              <div>
                <h2 style={{ margin: 0, fontSize: '20px', fontWeight: '700', color: '#a855f7' }}>
                  🤖 AI Trade Manager
                </h2>
                <div style={{ fontSize: '14px', color: '#94a3b8', marginTop: '4px' }}>
                  {manageTrade.symbol} · {manageTrade.strategy_type?.toUpperCase()} · {manageTrade.dte_remaining}d DTE
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                {walletBalance !== null && (
                  <div style={{
                    background: walletBalance >= 5 ? '#14532d' : '#7f1d1d',
                    border: `1px solid ${walletBalance >= 5 ? '#16a34a' : '#dc2626'}`,
                    borderRadius: '8px', padding: '6px 12px', fontSize: '13px'
                  }}>
                    💳 {walletBalance} credits
                  </div>
                )}
                <button
                  onClick={() => { setManageOpen(false); setManageResult(null); }}
                  style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', marginTop: '8px', fontSize: '18px' }}
                >✕</button>
              </div>
            </div>

            {/* Trade snapshot */}
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px',
              marginBottom: '20px', background: '#0f172a', borderRadius: '8px', padding: '14px'
            }}>
              {(() => {
                const stock = manageTrade.current_underlying_price || manageTrade.entry_underlying_price || 0;
                const strike = manageTrade.short_call_strike || 0;
                const distPct = stock > 0 ? (((strike - stock) / stock) * 100).toFixed(1) : '—';
                const itm = stock >= strike;
                const premPerShare = manageTrade.short_call_premium || 0;
                const be = stock > 0 ? (manageTrade.entry_underlying_price - premPerShare).toFixed(2) : '—';
                return [
                  ['Stock Price', `$${stock?.toFixed(2) || '—'}`],
                  ['Strike', `$${strike || '—'}`],
                  ['Distance', distPct !== '—' ? `${Math.abs(distPct)}% ${itm ? '⚠ ITM' : 'OTM'}` : '—'],
                  ['Breakeven', be !== '—' ? `$${be}` : '—'],
                  ['Capture', `${manageTrade.premium_capture_pct?.toFixed(0) ?? '0'}%`],
                  ['Delta', manageTrade.current_delta?.toFixed(2) ?? '—'],
                ].map(([label, val]) => (
                  <div key={label} style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '3px' }}>{label}</div>
                    <div style={{ fontSize: '13px', fontWeight: '600', color: label === 'Distance' && itm ? '#ef4444' : '#e2e8f0' }}>{val}</div>
                  </div>
                ));
              })()}
            </div>

            {/* Goals config */}
            {!manageResult && !manageLoading && (
              <ManageGoalsForm onRun={runManageAI} loading={manageLoading} walletBalance={walletBalance} />
            )}

            {/* Loading state */}
            {manageLoading && (
              <div style={{ textAlign: 'center', padding: '30px', color: '#a855f7' }}>
                <div style={{ fontSize: '28px', marginBottom: '10px' }}>⚙️</div>
                <div>Analyzing trade... (5 credits)</div>
              </div>
            )}

            {/* Recommendation result */}
            {manageResult && !manageLoading && (
              <RecommendationCard
                result={manageResult}
                onApply={applyRecommendation}
                onDismiss={() => { setManageResult(null); }}
                applyLoading={applyLoading}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default Simulator;
