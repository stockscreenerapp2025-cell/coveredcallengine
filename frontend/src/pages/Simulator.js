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
  'pmcc': 'bg-violet-500/20 text-violet-400 border-violet-500/30'
};

const CHART_COLORS = {
  covered_call: '#10b981',
  pmcc: '#8b5cf6',
  profit: '#10b981',
  loss: '#ef4444'
};

const ACTION_COLORS = {
  'opened': 'bg-blue-500/20 text-blue-400',
  'closed': 'bg-zinc-500/20 text-zinc-400',
  'rolled': 'bg-violet-500/20 text-violet-400',
  'rolled_open': 'bg-cyan-500/20 text-cyan-400',
  'rule_closed': 'bg-amber-500/20 text-amber-400',
  'rule_alert': 'bg-yellow-500/20 text-yellow-400',
  'expired': 'bg-emerald-500/20 text-emerald-400',
  'assigned': 'bg-red-500/20 text-red-400'
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

const Simulator = () => {
  // Status helper: backend uses 'open'/'rolled'/'active' for live trades
  const isLive = (status) => ['open', 'rolled', 'active'].includes(status);
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
  const [ruleDialogOpen, setRuleDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluationResults, setEvaluationResults] = useState(null);
  const [evalResultsOpen, setEvalResultsOpen] = useState(false);
  
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

  useEffect(() => {
    fetchTrades();
    fetchSummary();
  }, [statusFilter, strategyFilter, pagination.page]);
  
  // Auto-update prices on first load if there are active trades without current data
  useEffect(() => {
    if (!initialUpdateDone && trades.length > 0 && !loading) {
      const needsUpdate = trades.some(t => isLive(t.status) && (!t.current_delta || t.current_delta === 0));
      if (needsUpdate) {
        setInitialUpdateDone(true);
        handleUpdatePrices();
      } else {
        setInitialUpdateDone(true);
      }
    }
  }, [trades, loading, initialUpdateDone]);

  useEffect(() => {
    if (activeTab === 'rules') {
      fetchRules();
      fetchTemplates();
    } else if (activeTab === 'logs') {
      fetchActionLogs();
    } else if (activeTab === 'pmcc') {
      fetchPMCCSummary();
    } else if (activeTab === 'analytics') {
      fetchAnalytics();
      fetchAnalyzerData();
      fetchOptimalSettings();
      fetchProfiles();
    }
  }, [activeTab]);

  const fetchTrades = async () => {
    setLoading(true);
    try {
      const res = await simulatorApi.getTrades({
        status: statusFilter || undefined,
        strategy: strategyFilter || undefined,
        page: pagination.page,
        limit: 20
      });
      setTrades(res.data.trades || []);
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

  const fetchRules = async () => {
    setRulesLoading(true);
    try {
      const res = await simulatorApi.getRules();
      setRules(res.data.rules || []);
    } catch (error) {
      console.error('Error fetching rules:', error);
      toast.error('Failed to load rules');
    } finally {
      setRulesLoading(false);
    }
  };

  const fetchTemplates = async () => {
    try {
      const res = await simulatorApi.getRuleTemplates();
      setTemplates(res.data.templates || []);
    } catch (error) {
      console.error('Error fetching templates:', error);
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

  const handleUpdatePrices = async () => {
    setUpdating(true);
    try {
      const res = await simulatorApi.updatePrices();
      toast.success(`Updated ${res.data.updated} trades. Expired: ${res.data.expired}, Assigned: ${res.data.assigned}`);
      fetchTrades();
      fetchSummary();
    } catch (error) {
      toast.error('Failed to update prices');
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

  const handleCreateFromTemplate = async (templateId) => {
    try {
      await simulatorApi.createFromTemplate(templateId);
      toast.success('Rule created from template');
      fetchRules();
    } catch (error) {
      toast.error('Failed to create rule');
    }
  };

  const handleToggleRule = async (rule) => {
    try {
      await simulatorApi.updateRule(rule.id, { is_enabled: !rule.is_enabled });
      toast.success(`Rule ${!rule.is_enabled ? 'enabled' : 'disabled'}`);
      fetchRules();
    } catch (error) {
      toast.error('Failed to update rule');
    }
  };

  const handleDeleteRule = async (ruleId) => {
    if (!window.confirm('Delete this rule?')) return;
    try {
      await simulatorApi.deleteRule(ruleId);
      toast.success('Rule deleted');
      fetchRules();
    } catch (error) {
      toast.error('Failed to delete rule');
    }
  };

  const handleEvaluateRules = async (dryRun = true) => {
    setEvaluating(true);
    try {
      const res = await simulatorApi.evaluateRules(dryRun);
      setEvaluationResults(res.data);
      setEvalResultsOpen(true);
      if (!dryRun && res.data.results.length > 0) {
        toast.success(`Executed rules on ${res.data.results.length} trades`);
        fetchTrades();
        fetchSummary();
        fetchActionLogs();
      }
    } catch (error) {
      toast.error('Failed to evaluate rules');
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
                  {formatCurrency(summary?.avg_return_per_trade || 0)}
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
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={strategyDistribution}
                        cx="50%"
                        cy="50%"
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
                      <th className="pb-3 font-medium">Prem %</th>
                      <th className="pb-3 font-medium">P/L</th>
                      <th className="pb-3 font-medium">ROI</th>
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
                            {trade.strategy_type === 'covered_call' ? 'CC' : 'PMCC'}
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
                          {formatOptionContract(trade.short_call_expiry, trade.short_call_strike)}
                        </td>
                        <td className={`${trade.dte_remaining <= 7 ? 'text-amber-400' : 'text-zinc-300'}`}>
                          {isLive(trade.status) ? `${trade.dte_remaining}d` : '-'}
                        </td>
                        <td className="text-cyan-400 font-mono">
                          {trade.current_delta?.toFixed(2) || trade.short_call_delta?.toFixed(2) || '-'}
                        </td>
                        <td className="text-violet-400 font-mono">
                          {/* IV display: short_call_iv stored as decimal, scan_parameters.iv_pct as percentage */}
                          {trade.scan_parameters?.iv_pct 
                            ? `${trade.scan_parameters.iv_pct.toFixed(1)}%`
                            : trade.short_call_iv 
                              ? `${(trade.short_call_iv * 100).toFixed(1)}%`
                              : trade.implied_volatility
                                ? `${trade.implied_volatility.toFixed(1)}%`
                                : '-'}
                        </td>
                        <td className="text-amber-400 font-mono">
                          {trade.iv_rank ? `${trade.iv_rank.toFixed(0)}%` : (trade.scan_parameters?.iv_rank ? `${trade.scan_parameters.iv_rank.toFixed(0)}%` : '-')}
                        </td>
                        <td className="text-zinc-400 font-mono">
                          {trade.open_interest ? trade.open_interest.toLocaleString() : (trade.scan_parameters?.open_interest ? trade.scan_parameters.open_interest.toLocaleString() : '-')}
                        </td>
                        <td className={`font-mono ${(trade.premium_capture_pct || 0) >= 50 ? 'text-emerald-400' : 'text-zinc-400'}`}>
                          {trade.premium_capture_pct?.toFixed(0) || 0}%
                        </td>
                        <td className={`font-mono ${
                          isLive(trade.status) 
                            ? (trade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                            : (trade.final_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                        }`}>
                          {isLive(trade.status) 
                            ? formatCurrency(trade.unrealized_pnl)
                            : formatCurrency(trade.final_pnl)
                          }
                        </td>
                        <td className={`font-mono ${
                          isLive(trade.status)
                            ? ((trade.unrealized_pnl / trade.capital_deployed * 100) >= 0 ? 'text-emerald-400' : 'text-red-400')
                            : (trade.roi_percent >= 0 ? 'text-emerald-400' : 'text-red-400')
                        }`}>
                          {isLive(trade.status)
                            ? formatPercent(trade.capital_deployed > 0 ? (trade.unrealized_pnl / trade.capital_deployed * 100) : 0)
                            : formatPercent(trade.roi_percent)
                          }
                        </td>
                        <td>
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
    // Group templates by category
    const categoryOrder = [
      'premium_harvesting',
      'expiry_management', 
      'assignment_awareness',
      'rolling',
      'pmcc_specific',
      'brokerage_aware',
      'informational',
      'optional_advanced'
    ];
    
    const categoryLabels = {
      'premium_harvesting': { label: 'Premium Harvesting', icon: '💰', description: 'No Early Close', color: 'emerald' },
      'expiry_management': { label: 'Expiry Decisions', icon: '📅', description: 'Primary Controls', color: 'blue' },
      'assignment_awareness': { label: 'Assignment Awareness', icon: '⚠️', description: 'Alerts Only', color: 'amber' },
      'rolling': { label: 'Rolling Rules', icon: '🔄', description: 'Core Income Logic', color: 'violet' },
      'pmcc_specific': { label: 'PMCC-Specific', icon: '📊', description: 'Short Leg Focused', color: 'cyan' },
      'brokerage_aware': { label: 'Brokerage-Aware', icon: '💸', description: 'Cost Controls', color: 'zinc' },
      'informational': { label: 'Informational', icon: 'ℹ️', description: 'Non-Action', color: 'zinc' },
      'optional_advanced': { label: 'Optional/Advanced', icon: '⚙️', description: 'Not Recommended', color: 'red' }
    };
    
    const groupedTemplates = {};
    templates.forEach(t => {
      const cat = t.category || 'other';
      if (!groupedTemplates[cat]) groupedTemplates[cat] = [];
      groupedTemplates[cat].push(t);
    });
    
    const getActionColor = (action) => {
      const actionType = action?.action_type || action;
      switch(actionType) {
        case 'roll': return 'bg-violet-500/20 text-violet-400 border-violet-500/30';
        case 'alert': return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
        case 'hold': return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
        case 'expire': return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
        case 'assignment': return 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30';
        case 'close': return 'bg-red-500/20 text-red-400 border-red-500/30';
        case 'suggest': return 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30';
        case 'prompt': return 'bg-pink-500/20 text-pink-400 border-pink-500/30';
        default: return 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30';
      }
    };

    return (
    <div className="space-y-6">
      {/* Rules Header - Updated Philosophy */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <Settings className="w-5 h-5 text-violet-400" />
            Income Strategy Trade Management
          </h2>
          <p className="text-zinc-400 text-sm mt-1">
            Trades are managed, not closed. Rolling and assignment logic drive decisions—not stop-losses.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => handleEvaluateRules(true)}
            disabled={evaluating}
            className="btn-outline"
            data-testid="dry-run-rules-btn"
          >
            <PlayCircle className={`w-4 h-4 mr-2 ${evaluating ? 'animate-spin' : ''}`} />
            Dry Run
          </Button>
          <Button
            onClick={() => handleEvaluateRules(false)}
            disabled={evaluating}
            className="bg-violet-600 hover:bg-violet-700 text-white"
            data-testid="execute-rules-btn"
          >
            <Zap className="w-4 h-4 mr-2" />
            Execute Rules
          </Button>
        </div>
      </div>

      {/* Income Strategy Philosophy Banner */}
      <Card className="glass-card border-violet-500/30 bg-violet-950/20">
        <CardContent className="py-4">
          <div className="flex items-start gap-3">
            <div className="p-2 bg-violet-500/20 rounded-lg">
              <TrendingUp className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <h3 className="font-medium text-violet-300 mb-1">Income Strategy Philosophy</h3>
              <p className="text-sm text-zinc-400">
                For CC and PMCC, loss is managed via <span className="text-emerald-400">time</span>, <span className="text-blue-400">premium decay</span>, <span className="text-violet-400">rolling</span>, and <span className="text-cyan-400">assignment logic</span>—not stop-losses. 
                Unrealised losses do not imply trade failure.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Templates by Category */}
      <div className="space-y-4">
        {categoryOrder.map(category => {
          const categoryTemplates = groupedTemplates[category] || [];
          if (categoryTemplates.length === 0) return null;
          
          const catInfo = categoryLabels[category] || { label: category, icon: '📋', description: '', color: 'zinc' };
          const isAdvanced = category === 'optional_advanced';
          
          return (
            <Card key={category} className={`glass-card ${isAdvanced ? 'opacity-60 border-red-500/20' : ''}`}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{catInfo.icon}</span>
                    <span className="text-white">{catInfo.label}</span>
                    <span className="text-xs text-zinc-500">({catInfo.description})</span>
                  </div>
                  {isAdvanced && (
                    <Badge className="bg-red-500/20 text-red-400 text-xs">
                      Not Recommended for Income Strategy
                    </Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {categoryTemplates.map(template => (
                    <div 
                      key={template.id}
                      className={`p-3 bg-zinc-800/50 rounded-lg border transition-colors ${
                        template.is_default 
                          ? 'border-emerald-500/30 hover:border-emerald-500/50' 
                          : template.is_advanced 
                          ? 'border-red-500/20 hover:border-red-500/40'
                          : 'border-zinc-700/50 hover:border-violet-500/50'
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <h4 className="font-medium text-white text-sm">{template.name}</h4>
                            {template.is_default && (
                              <Badge className="bg-emerald-500/20 text-emerald-400 text-xs">Default</Badge>
                            )}
                          </div>
                          <p className="text-xs text-zinc-400 mt-1 line-clamp-2">{template.description}</p>
                          <div className="flex items-center gap-2 mt-2 flex-wrap">
                            <Badge className={getActionColor(template.action)}>
                              {template.action?.action_type || template.action || 'rule'}
                            </Badge>
                            {template.strategy_type && (
                              <Badge className={STRATEGY_COLORS[template.strategy_type]}>
                                {template.strategy_type === 'covered_call' ? 'CC' : 'PMCC'}
                              </Badge>
                            )}
                            {template.ui_hint && (
                              <span className="text-xs text-zinc-500">{template.ui_hint}</span>
                            )}
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleCreateFromTemplate(template.id)}
                          className="text-cyan-400 hover:text-cyan-300 ml-2"
                        >
                          <Plus className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Active Rules */}
      <Card className="glass-card" data-testid="rules-list-card">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            Your Active Rules ({rules.length})
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
              <p className="text-zinc-500 text-xs mt-1">Add income strategy rules above to automate trade management</p>
            </div>
          ) : (
            <div className="space-y-3">
              {rules.map(rule => (
                <div 
                  key={rule.id}
                  className={`p-4 rounded-lg border transition-colors ${
                    rule.is_enabled 
                      ? 'bg-zinc-800/50 border-zinc-700/50' 
                      : 'bg-zinc-900/50 border-zinc-800/50 opacity-60'
                  }`}
                  data-testid={`rule-${rule.id}`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h4 className="font-medium text-white">{rule.name}</h4>
                        <Badge className={rule.action.action_type === 'roll' ? 'bg-violet-500/20 text-violet-400' : rule.action.action_type === 'close' ? 'bg-amber-500/20 text-amber-400' : 'bg-blue-500/20 text-blue-400'}>
                          {rule.action.action_type}
                        </Badge>
                        {rule.strategy_type && (
                          <Badge className={STRATEGY_COLORS[rule.strategy_type]}>
                            {rule.strategy_type === 'covered_call' ? 'CC Only' : 'PMCC Only'}
                          </Badge>
                        )}
                        {rule.times_triggered > 0 && (
                          <span className="text-xs text-zinc-500">
                            Triggered {rule.times_triggered}x
                          </span>
                        )}
                      </div>
                      {rule.description && (
                        <p className="text-xs text-zinc-400 mt-1">{rule.description}</p>
                      )}
                      <div className="flex flex-wrap gap-2 mt-2">
                        {rule.conditions.map((cond, idx) => (
                          <span key={idx} className="text-xs bg-zinc-700/50 px-2 py-1 rounded text-zinc-300">
                            {CONDITION_FIELDS.find(f => f.value === cond.field)?.label || cond.field} {OPERATORS.find(o => o.value === cond.operator)?.label} {cond.value}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Switch
                        checked={rule.is_enabled}
                        onCheckedChange={() => handleToggleRule(rule)}
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeleteRule(rule.id)}
                        className="text-red-400 hover:text-red-300"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
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
              {actionLogs.map((log, idx) => (
                <div 
                  key={idx}
                  className="flex items-start gap-3 p-3 bg-zinc-800/30 rounded-lg"
                >
                  <Badge className={ACTION_COLORS[log.action] || 'bg-zinc-500/20 text-zinc-400'}>
                    {log.action}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="font-semibold text-white">{log.symbol}</span>
                      <Badge className={STRATEGY_COLORS[log.strategy_type]} variant="outline">
                        {log.strategy_type === 'covered_call' ? 'CC' : 'PMCC'}
                      </Badge>
                      {log.rule_name && (
                        <span className="text-xs text-violet-400">via &quot;{log.rule_name}&quot;</span>
                      )}
                    </div>
                    <p className="text-xs text-zinc-400 mt-1">{log.details}</p>
                  </div>
                  <span className="text-xs text-zinc-500 whitespace-nowrap">
                    {formatDateTime(log.timestamp)}
                  </span>
                </div>
              ))}
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
    // This is now the ANALYZER page with fixed 3-row structure
    // State is managed at component level
    
    // Available symbols from trades
    const availableSymbols = [...new Set(trades.map(t => t.symbol))].sort();
    
    // Format helpers
    const getProfitFactorColor = (pf) => {
      if (pf >= 1.5) return 'text-emerald-400';
      if (pf >= 1) return 'text-amber-400';
      return 'text-red-400';
    };
    
    const getScopeLabel = () => {
      if (analyzerSymbol) return `Symbol: ${analyzerSymbol}`;
      if (analyticsStrategy === 'covered_call') return 'Strategy: Covered Call';
      if (analyticsStrategy === 'pmcc') return 'Strategy: PMCC';
      return 'Portfolio (All)';
    };
    
    return (
    <div className="space-y-6" data-testid="analyzer-page">
      {/* Analyzer Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-cyan-400" />
            Analyzer
          </h2>
          <p className="text-zinc-400 text-sm mt-1">
            Performance, Risk & Strategy Health
          </p>
        </div>
        
        {/* Scope Filters */}
        <div className="flex flex-wrap gap-2">
          <Select value={analyticsStrategy || "all"} onValueChange={(v) => setAnalyticsStrategy(v === "all" ? "" : v)}>
            <SelectTrigger className="w-36 h-8 bg-zinc-800/50 border-zinc-700" data-testid="strategy-filter">
              <SelectValue placeholder="All Strategies" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-700">
              <SelectItem value="all">All Strategies</SelectItem>
              <SelectItem value="covered_call">Covered Call</SelectItem>
              <SelectItem value="pmcc">PMCC</SelectItem>
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
      
      {/* Scope Indicator */}
      <div className="flex items-center gap-2 text-sm">
        <Badge className="bg-cyan-500/20 text-cyan-400">{getScopeLabel()}</Badge>
        {analyzerData?.scope?.type && (
          <span className="text-zinc-500">
            Scope: {analyzerData.scope.type.charAt(0).toUpperCase() + analyzerData.scope.type.slice(1)}
          </span>
        )}
      </div>

      {analyzerLoading ? (
        <div className="space-y-4">
          {Array(3).fill(0).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : !analyzerData?.row1_outcome ? (
        <Card className="glass-card">
          <CardContent className="py-12 text-center">
            <BarChart3 className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-white mb-2">No Data Available</h3>
            <p className="text-zinc-400 text-sm">
              Add trades to the simulator to see analyzer metrics
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* ==================== ROW 1: OUTCOME ==================== */}
          <Card className="glass-card border-blue-500/20" data-testid="row1-outcome">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <DollarSign className="w-4 h-4 text-blue-400" />
                <span className="text-blue-400">Row 1: Outcome</span>
                <span className="text-zinc-500 font-normal">— What did I make?</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                {/* Existing Metrics */}
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Total P/L</div>
                  <div className={`text-xl font-bold ${analyzerData.row1_outcome.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatCurrency(analyzerData.row1_outcome.total_pnl)}
                  </div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Win Rate</div>
                  <div className={`text-xl font-bold ${analyzerData.row1_outcome.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {analyzerData.row1_outcome.win_rate}%
                  </div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">ROI</div>
                  <div className={`text-xl font-bold ${analyzerData.row1_outcome.roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {analyzerData.row1_outcome.roi}%
                  </div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Avg Win</div>
                  <div className="text-xl font-bold text-emerald-400">
                    {formatCurrency(analyzerData.row1_outcome.avg_win)}
                  </div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Avg Loss</div>
                  <div className="text-xl font-bold text-red-400">
                    {formatCurrency(analyzerData.row1_outcome.avg_loss)}
                  </div>
                </div>
                
                {/* New Derived Metrics */}
                <div className="p-3 bg-zinc-800/50 rounded-lg border border-blue-500/20">
                  <div className="text-xs text-zinc-500 mb-1 flex items-center gap-1">
                    Expectancy
                    <span className="text-zinc-600 cursor-help" title={analyzerData.row1_outcome.expectancy_tooltip}>ⓘ</span>
                  </div>
                  <div className={`text-xl font-bold ${analyzerData.row1_outcome.expectancy >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatCurrency(analyzerData.row1_outcome.expectancy)}
                  </div>
                  <div className="text-xs text-zinc-600">per trade</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg border border-blue-500/20">
                  <div className="text-xs text-zinc-500 mb-1">Max Drawdown</div>
                  <div className="text-xl font-bold text-amber-400">
                    {formatCurrency(analyzerData.row1_outcome.max_drawdown)}
                  </div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg border border-blue-500/20">
                  <div className="text-xs text-zinc-500 mb-1 flex items-center gap-1">
                    Time-Weighted Return
                    <span className="text-zinc-600 cursor-help" title={analyzerData.row1_outcome.twr_tooltip}>ⓘ</span>
                  </div>
                  <div className={`text-xl font-bold ${analyzerData.row1_outcome.time_weighted_return >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {analyzerData.row1_outcome.time_weighted_return}%
                  </div>
                  <div className="text-xs text-zinc-600">annualized</div>
                </div>
              </div>
              
              {/* Trade counts */}
              <div className="flex gap-4 mt-3 text-xs text-zinc-500">
                <span>Total: {analyzerData.row1_outcome.total_trades}</span>
                <span>Open: {analyzerData.row1_outcome.open_trades}</span>
                <span>Completed: {analyzerData.row1_outcome.completed_trades}</span>
              </div>
            </CardContent>
          </Card>

          {/* ==================== ROW 2: RISK & CAPITAL ==================== */}
          <Card className="glass-card border-amber-500/20" data-testid="row2-risk-capital">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-amber-400" />
                <span className="text-amber-400">Row 2: Risk & Capital</span>
                <span className="text-zinc-500 font-normal">— How much pain did I take?</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 gap-3">
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Peak Capital at Risk</div>
                  <div className="text-xl font-bold text-white">
                    {formatCurrency(analyzerData.row2_risk_capital.peak_capital_at_risk)}
                  </div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1">Avg Capital per Trade</div>
                  <div className="text-xl font-bold text-white">
                    {formatCurrency(analyzerData.row2_risk_capital.avg_capital_per_trade)}
                  </div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-1 flex items-center gap-1">
                    Worst Case Loss
                    <span className="text-zinc-600 cursor-help" title={analyzerData.row2_risk_capital.worst_case_loss_tooltip}>ⓘ</span>
                  </div>
                  <div className="text-xl font-bold text-red-400">
                    {formatCurrency(analyzerData.row2_risk_capital.worst_case_loss)}
                  </div>
                  <div className="text-xs text-zinc-600">theoretical</div>
                </div>
                <div className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="text-xs text-zinc-500 mb-2">Assignment Exposure</div>
                  <div className="flex items-center gap-4">
                    <div>
                      <div className="text-xs text-zinc-600">CC</div>
                      <div className={`text-lg font-bold ${analyzerData.row2_risk_capital.assignment_exposure_cc > 20 ? 'text-amber-400' : 'text-zinc-300'}`}>
                        {analyzerData.row2_risk_capital.assignment_exposure_cc}%
                      </div>
                    </div>
                    <div className="h-8 w-px bg-zinc-700" />
                    <div>
                      <div className="text-xs text-zinc-600">PMCC</div>
                      <div className={`text-lg font-bold ${analyzerData.row2_risk_capital.assignment_exposure_pmcc > 20 ? 'text-red-400' : 'text-zinc-300'}`}>
                        {analyzerData.row2_risk_capital.assignment_exposure_pmcc}%
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              
              {/* Risk context */}
              <div className="flex gap-4 mt-3 text-xs text-zinc-500">
                <span>Open Positions: {analyzerData.row2_risk_capital.total_open_positions}</span>
                <span>CC at Risk: {analyzerData.row2_risk_capital.cc_positions_at_risk}</span>
                <span>PMCC at Risk: {analyzerData.row2_risk_capital.pmcc_positions_at_risk}</span>
              </div>
            </CardContent>
          </Card>

          {/* ==================== ROW 3: STRATEGY HEALTH ==================== */}
          <Card className="glass-card border-emerald-500/20" data-testid="row3-strategy-health">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Activity className="w-4 h-4 text-emerald-400" />
                <span className="text-emerald-400">Row 3: Strategy Health</span>
                <span className="text-zinc-500 font-normal">— Is the logic working?</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {analyzerData.row3_strategy_health.strategies?.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-zinc-500 border-b border-zinc-800">
                        <th className="pb-2 font-medium">Strategy</th>
                        <th className="pb-2 font-medium">Win Rate</th>
                        <th className="pb-2 font-medium">Avg Hold (Days)</th>
                        <th className="pb-2 font-medium">Profit Factor</th>
                        <th className="pb-2 font-medium">Trades</th>
                        <th className="pb-2 font-medium">Realized P/L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analyzerData.row3_strategy_health.strategies.map((s, idx) => (
                        <tr key={idx} className="border-b border-zinc-800/50">
                          <td className="py-3 font-semibold text-white">{s.strategy_label}</td>
                          <td className={`py-3 ${s.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400'}`}>
                            {s.win_rate}%
                          </td>
                          <td className="py-3 text-zinc-300">{s.avg_hold_days}</td>
                          <td className={`py-3 font-mono ${getProfitFactorColor(s.profit_factor)}`}>
                            {s.profit_factor}
                            <span className="ml-1 text-xs">
                              {s.profit_factor_status === 'good' ? '✓' : s.profit_factor_status === 'caution' ? '⚠' : ''}
                            </span>
                          </td>
                          <td className="py-3 text-zinc-300">
                            {s.completed_trades} / {s.total_trades}
                            {s.open_trades > 0 && <span className="text-zinc-500 text-xs ml-1">({s.open_trades} open)</span>}
                          </td>
                          <td className={`py-3 ${s.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatCurrency(s.realized_pnl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-6 text-zinc-500">
                  No strategy data available for current scope
                </div>
              )}
              
              {/* Strategy Distribution Charts */}
              {analyzerData.row3_strategy_health.strategy_distribution?.length > 0 && (
                <div className="grid md:grid-cols-2 gap-4 mt-4 pt-4 border-t border-zinc-800">
                  <div>
                    <div className="text-xs text-zinc-500 mb-2">Strategy Distribution</div>
                    <div className="h-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={analyzerData.row3_strategy_health.strategy_distribution}
                            dataKey="value"
                            nameKey="name"
                            cx="50%"
                            cy="50%"
                            outerRadius={50}
                            fill="#8b5cf6"
                            label={({ name, value }) => `${name}: ${value}`}
                          >
                            {analyzerData.row3_strategy_health.strategy_distribution.map((entry, index) => (
                              <Cell key={index} fill={index === 0 ? '#06b6d4' : '#8b5cf6'} />
                            ))}
                          </Pie>
                          <Tooltip 
                            contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-500 mb-2">P/L by Strategy</div>
                    <div className="h-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={analyzerData.row3_strategy_health.pnl_by_strategy} layout="vertical">
                          <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                          <XAxis type="number" stroke="#666" fontSize={10} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
                          <YAxis type="category" dataKey="name" stroke="#666" fontSize={10} width={80} />
                          <Tooltip 
                            contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                            formatter={(value) => formatCurrency(value)}
                          />
                          <Bar dataKey="realized" name="Realized" fill="#10b981" radius={[0, 4, 4, 0]} />
                          <Bar dataKey="unrealized" name="Unrealized" fill="#6366f1" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
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
            onClick={handleUpdatePrices}
            disabled={updating}
            className="btn-outline"
            data-testid="update-prices-btn"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${updating ? 'animate-spin' : ''}`} />
            {updating ? 'Updating...' : 'Update Prices'}
          </Button>
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
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">Gamma</div>
                      <div className="text-violet-400 font-mono font-semibold">
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">Vega</div>
                      <div className="text-amber-400 font-mono font-semibold">
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
                Evaluated {evaluationResults.trades_evaluated} trades against {evaluationResults.rules_count} rules
              </div>
              
              {evaluationResults.results.length === 0 ? (
                <div className="text-center py-8">
                  <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto mb-3" />
                  <p className="text-zinc-300">No rules triggered</p>
                  <p className="text-zinc-500 text-sm">All trades are within defined thresholds</p>
                </div>
              ) : (
                <div className="space-y-3 max-h-96 overflow-y-auto">
                  {evaluationResults.results.map((result, idx) => (
                    <div key={idx} className="p-3 bg-zinc-800/50 rounded-lg">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-semibold text-white">{result.symbol}</span>
                        <Badge className={STRATEGY_COLORS[result.strategy]}>
                          {result.strategy === 'covered_call' ? 'CC' : 'PMCC'}
                        </Badge>
                      </div>
                      <div className="space-y-1">
                        {result.matched_rules.map((rule, ruleIdx) => (
                          <div key={ruleIdx} className="text-sm flex items-center gap-2">
                            <Badge className={rule.action_type === 'roll' ? 'bg-violet-500/20 text-violet-400' : rule.action_type === 'close' ? 'bg-amber-500/20 text-amber-400' : 'bg-blue-500/20 text-blue-400'}>
                              {rule.action_type}
                            </Badge>
                            <span className="text-zinc-300">{rule.rule_name}</span>
                            {rule.dry_run ? (
                              <span className="text-amber-400 text-xs">(would execute)</span>
                            ) : rule.success ? (
                              <span className="text-emerald-400 text-xs">✓ {rule.message}</span>
                            ) : (
                              <span className="text-red-400 text-xs">✗ Failed</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              
              <DialogFooter>
                {evaluationResults.dry_run && evaluationResults.results.length > 0 && (
                  <Button
                    onClick={() => {
                      setEvalResultsOpen(false);
                      handleEvaluateRules(false);
                    }}
                    className="bg-violet-600 hover:bg-violet-700 text-white"
                  >
                    <Zap className="w-4 h-4 mr-2" />
                    Execute Now
                  </Button>
                )}
                <Button variant="outline" onClick={() => setEvalResultsOpen(false)} className="btn-outline">
                  Close
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Simulator;
