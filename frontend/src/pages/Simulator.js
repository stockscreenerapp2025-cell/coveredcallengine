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
  'active': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
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
      const needsUpdate = trades.some(t => t.status === 'active' && (!t.current_delta || t.current_delta === 0));
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
                <SelectItem value="active">Active</SelectItem>
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
                          {trade.status === 'active' ? `${trade.dte_remaining}d` : '-'}
                        </td>
                        <td className="text-cyan-400 font-mono">
                          {trade.current_delta?.toFixed(2) || trade.short_call_delta?.toFixed(2) || '-'}
                        </td>
                        <td className="text-red-400 font-mono">
                          {trade.current_theta ? `$${Math.abs(trade.current_theta).toFixed(2)}` : '-'}
                        </td>
                        <td className={`font-mono ${(trade.premium_capture_pct || 0) >= 50 ? 'text-emerald-400' : 'text-zinc-400'}`}>
                          {trade.premium_capture_pct?.toFixed(0) || 0}%
                        </td>
                        <td className={`font-mono ${
                          trade.status === 'active' 
                            ? (trade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                            : (trade.final_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                        }`}>
                          {trade.status === 'active' 
                            ? formatCurrency(trade.unrealized_pnl)
                            : formatCurrency(trade.final_pnl)
                          }
                        </td>
                        <td className={`font-mono ${
                          trade.status === 'active'
                            ? ((trade.unrealized_pnl / trade.capital_deployed * 100) >= 0 ? 'text-emerald-400' : 'text-red-400')
                            : (trade.roi_percent >= 0 ? 'text-emerald-400' : 'text-red-400')
                        }`}>
                          {trade.status === 'active'
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

  const renderRulesTab = () => (
    <div className="space-y-6">
      {/* Rules Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <Settings className="w-5 h-5 text-violet-400" />
            Trade Management Rules
          </h2>
          <p className="text-zinc-400 text-sm mt-1">
            Automate trade decisions based on conditions like premium capture, delta, or loss thresholds
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

      {/* Templates Section */}
      <Card className="glass-card">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Copy className="w-4 h-4 text-cyan-400" />
            Quick Start Templates
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
            {templates.map(template => (
              <div 
                key={template.id}
                className="p-3 bg-zinc-800/50 rounded-lg border border-zinc-700/50 hover:border-violet-500/50 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h4 className="font-medium text-white text-sm">{template.name}</h4>
                    <p className="text-xs text-zinc-400 mt-1">{template.description}</p>
                    <div className="flex items-center gap-2 mt-2">
                      <Badge className={template.action.action_type === 'roll' ? 'bg-violet-500/20 text-violet-400' : template.action.action_type === 'close' ? 'bg-amber-500/20 text-amber-400' : 'bg-blue-500/20 text-blue-400'}>
                        {template.action.action_type}
                      </Badge>
                      {template.strategy_type && (
                        <Badge className={STRATEGY_COLORS[template.strategy_type]}>
                          {template.strategy_type === 'covered_call' ? 'CC' : 'PMCC'}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleCreateFromTemplate(template.id)}
                    className="text-cyan-400 hover:text-cyan-300"
                  >
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Active Rules */}
      <Card className="glass-card" data-testid="rules-list-card">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            Your Rules ({rules.length})
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
              <p className="text-zinc-500 text-xs mt-1">Use templates above to get started</p>
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

  const renderAnalyticsTab = () => (
    <div className="space-y-6">
      {/* Header with filters */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <LineChart className="w-5 h-5 text-cyan-400" />
            Performance Analytics
          </h2>
          <p className="text-zinc-400 text-sm mt-1">
            Analyze your trading patterns to optimize scanner parameters
          </p>
        </div>
        <div className="flex gap-2">
          <Select value={analyticsTimeframe} onValueChange={(v) => { setAnalyticsTimeframe(v); }}>
            <SelectTrigger className="w-28 h-8 bg-zinc-800/50 border-zinc-700">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-700">
              <SelectItem value="all">All Time</SelectItem>
              <SelectItem value="7d">7 Days</SelectItem>
              <SelectItem value="30d">30 Days</SelectItem>
              <SelectItem value="90d">90 Days</SelectItem>
              <SelectItem value="ytd">YTD</SelectItem>
            </SelectContent>
          </Select>
          <Select value={analyticsStrategy || "all"} onValueChange={(v) => { setAnalyticsStrategy(v === "all" ? "" : v); }}>
            <SelectTrigger className="w-36 h-8 bg-zinc-800/50 border-zinc-700">
              <SelectValue placeholder="All Strategies" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-700">
              <SelectItem value="all">All Strategies</SelectItem>
              <SelectItem value="covered_call">Covered Call</SelectItem>
              <SelectItem value="pmcc">PMCC</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={fetchAnalytics}
            className="btn-outline"
          >
            <RefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </Button>
        </div>
      </div>

      {analyticsLoading ? (
        <div className="space-y-4">
          {Array(4).fill(0).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : !analytics?.analytics ? (
        <Card className="glass-card">
          <CardContent className="py-12 text-center">
            <BarChart3 className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-white mb-2">Not Enough Data</h3>
            <p className="text-zinc-400 text-sm">
              {analytics?.message || "Close some simulated trades to see performance analytics"}
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Overall Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Total Trades</div>
                <div className="text-xl font-bold text-white">{analytics.analytics.overall.total_trades}</div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Win Rate</div>
                <div className={`text-xl font-bold ${analytics.analytics.overall.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {analytics.analytics.overall.win_rate}%
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Total P/L</div>
                <div className={`text-xl font-bold ${analytics.analytics.overall.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatCurrency(analytics.analytics.overall.total_pnl)}
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">ROI</div>
                <div className={`text-xl font-bold ${analytics.analytics.overall.roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {analytics.analytics.overall.roi}%
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Avg Win</div>
                <div className="text-xl font-bold text-emerald-400">
                  {formatCurrency(analytics.analytics.overall.avg_win)}
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="text-xs text-zinc-500 mb-1">Avg Loss</div>
                <div className="text-xl font-bold text-red-400">
                  {formatCurrency(analytics.analytics.overall.avg_loss)}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Recommendations */}
          {analytics.recommendations?.length > 0 && (
            <Card className="glass-card border-cyan-500/30">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Lightbulb className="w-4 h-4 text-cyan-400" />
                  AI Recommendations
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {analytics.recommendations.map((rec, idx) => (
                    <div key={idx} className={`p-3 rounded-lg border ${
                      rec.priority === 'high' ? 'bg-amber-500/10 border-amber-500/30' :
                      rec.priority === 'medium' ? 'bg-blue-500/10 border-blue-500/30' :
                      'bg-zinc-800/50 border-zinc-700/50'
                    }`}>
                      <div className="flex items-start gap-2">
                        <Badge className={
                          rec.priority === 'high' ? 'bg-amber-500/20 text-amber-400' :
                          rec.priority === 'medium' ? 'bg-blue-500/20 text-blue-400' :
                          'bg-zinc-500/20 text-zinc-400'
                        }>
                          {rec.priority}
                        </Badge>
                        <div>
                          <p className="text-white text-sm font-medium">{rec.message}</p>
                          <p className="text-zinc-400 text-xs mt-1">{rec.suggestion}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Performance Charts */}
          <div className="grid md:grid-cols-2 gap-6">
            {/* By Delta */}
            {analytics.analytics.by_delta?.length > 0 && (
              <Card className="glass-card">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Target className="w-4 h-4 text-violet-400" />
                    Performance by Delta Range
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={analytics.analytics.by_delta}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                        <XAxis dataKey="range" stroke="#666" fontSize={10} />
                        <YAxis stroke="#666" fontSize={10} />
                        <Tooltip 
                          contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                          formatter={(value, name) => [name === 'win_rate' ? `${value}%` : formatCurrency(value), name === 'win_rate' ? 'Win Rate' : 'Avg P/L']}
                        />
                        <Bar dataKey="win_rate" name="Win Rate" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="mt-3 space-y-1">
                    {analytics.analytics.by_delta.map((d, idx) => (
                      <div key={idx} className="flex justify-between text-xs">
                        <span className="text-zinc-400">Delta {d.range}</span>
                        <span className={d.win_rate >= 50 ? 'text-emerald-400' : 'text-zinc-300'}>
                          {d.trade_count} trades, {d.win_rate}% win, {formatCurrency(d.avg_pnl)} avg
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* By DTE */}
            {analytics.analytics.by_dte?.length > 0 && (
              <Card className="glass-card">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Clock className="w-4 h-4 text-cyan-400" />
                    Performance by DTE Range
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={analytics.analytics.by_dte}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                        <XAxis dataKey="range" stroke="#666" fontSize={10} />
                        <YAxis stroke="#666" fontSize={10} />
                        <Tooltip 
                          contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                          formatter={(value) => [`${value}%`, 'Win Rate']}
                        />
                        <Bar dataKey="win_rate" name="Win Rate" fill="#06b6d4" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="mt-3 space-y-1">
                    {analytics.analytics.by_dte.map((d, idx) => (
                      <div key={idx} className="flex justify-between text-xs">
                        <span className="text-zinc-400">{d.range}</span>
                        <span className={d.win_rate >= 50 ? 'text-emerald-400' : 'text-zinc-300'}>
                          {d.trade_count} trades, {d.win_rate}% win
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Symbol Performance */}
          {analytics.analytics.by_symbol?.length > 0 && (
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Award className="w-4 h-4 text-amber-400" />
                  Top Performing Symbols
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-zinc-500 border-b border-zinc-800">
                        <th className="pb-2 font-medium">Symbol</th>
                        <th className="pb-2 font-medium">Trades</th>
                        <th className="pb-2 font-medium">Win Rate</th>
                        <th className="pb-2 font-medium">Total P/L</th>
                        <th className="pb-2 font-medium">Avg P/L</th>
                        <th className="pb-2 font-medium">ROI</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analytics.analytics.by_symbol.slice(0, 10).map((s, idx) => (
                        <tr key={idx} className="border-b border-zinc-800/50">
                          <td className="py-2 font-semibold text-white">{s.symbol}</td>
                          <td className="py-2 text-zinc-300">{s.trade_count}</td>
                          <td className={`py-2 ${s.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400'}`}>
                            {s.win_rate}%
                          </td>
                          <td className={`py-2 ${s.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatCurrency(s.total_pnl)}
                          </td>
                          <td className={`py-2 ${s.avg_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatCurrency(s.avg_pnl)}
                          </td>
                          <td className={`py-2 ${s.roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {s.roi}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Optimal Settings */}
          {optimalSettings?.optimal_settings && (
            <Card className="glass-card border-emerald-500/30">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Zap className="w-4 h-4 text-emerald-400" />
                  Optimal Scanner Settings
                  <Badge className={
                    optimalSettings.confidence === 'high' ? 'bg-emerald-500/20 text-emerald-400' :
                    optimalSettings.confidence === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                    'bg-zinc-500/20 text-zinc-400'
                  }>
                    {optimalSettings.confidence} confidence
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid md:grid-cols-2 gap-6">
                  <div>
                    <h4 className="text-sm font-medium text-zinc-400 mb-3">Recommended Parameters</h4>
                    <div className="space-y-2">
                      <div className="flex justify-between p-2 bg-zinc-800/50 rounded">
                        <span className="text-zinc-400">Min Delta</span>
                        <span className="text-white font-mono">{optimalSettings.optimal_settings.min_delta}</span>
                      </div>
                      <div className="flex justify-between p-2 bg-zinc-800/50 rounded">
                        <span className="text-zinc-400">Max Delta</span>
                        <span className="text-white font-mono">{optimalSettings.optimal_settings.max_delta}</span>
                      </div>
                      <div className="flex justify-between p-2 bg-zinc-800/50 rounded">
                        <span className="text-zinc-400">Max DTE</span>
                        <span className="text-white font-mono">{optimalSettings.optimal_settings.max_dte} days</span>
                      </div>
                      <div className="flex justify-between p-2 bg-emerald-500/10 rounded border border-emerald-500/30">
                        <span className="text-zinc-400">Expected Win Rate</span>
                        <span className="text-emerald-400 font-mono">{optimalSettings.optimal_settings.expected_win_rate}%</span>
                      </div>
                    </div>
                    <Button
                      className="w-full mt-4 bg-emerald-600 hover:bg-emerald-700 text-white"
                      onClick={() => window.open(optimalSettings.apply_url, '_blank')}
                    >
                      <ExternalLink className="w-4 h-4 mr-2" />
                      Apply to Screener
                    </Button>
                  </div>
                  <div>
                    <h4 className="text-sm font-medium text-zinc-400 mb-3">Symbol Recommendations</h4>
                    {optimalSettings.symbol_recommendations?.top_performers?.length > 0 && (
                      <div className="mb-3">
                        <p className="text-xs text-zinc-500 mb-1">Top Performers</p>
                        <div className="flex flex-wrap gap-1">
                          {optimalSettings.symbol_recommendations.top_performers.map((s, idx) => (
                            <Badge key={idx} className="bg-emerald-500/20 text-emerald-400">
                              {s.symbol} ({s.win_rate}%)
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                    {optimalSettings.symbol_recommendations?.avoid?.length > 0 && (
                      <div>
                        <p className="text-xs text-zinc-500 mb-1">Consider Avoiding</p>
                        <div className="flex flex-wrap gap-1">
                          {optimalSettings.symbol_recommendations.avoid.map((sym, idx) => (
                            <Badge key={idx} className="bg-red-500/20 text-red-400">
                              {sym}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                    
                    {/* Save as Profile */}
                    <div className="mt-4 p-3 bg-zinc-800/50 rounded-lg">
                      <p className="text-xs text-zinc-500 mb-2">Save these settings as a profile</p>
                      <div className="flex gap-2">
                        <Input
                          value={newProfileName}
                          onChange={(e) => setNewProfileName(e.target.value)}
                          placeholder="Profile name..."
                          className="flex-1 h-8 bg-zinc-900 border-zinc-700"
                        />
                        <Button
                          onClick={handleSaveProfile}
                          disabled={savingProfile || !newProfileName.trim()}
                          className="bg-violet-600 hover:bg-violet-700 text-white h-8"
                        >
                          <Save className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Saved Profiles */}
          {profiles.length > 0 && (
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <FileText className="w-4 h-4 text-violet-400" />
                  Saved Profiles ({profiles.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {profiles.map(profile => (
                    <div key={profile.id} className="p-3 bg-zinc-800/50 rounded-lg border border-zinc-700/50">
                      <div className="flex items-start justify-between">
                        <div>
                          <h4 className="font-medium text-white">{profile.name}</h4>
                          <p className="text-xs text-zinc-500 mt-1">
                            Created {formatDate(profile.created_at)}
                          </p>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteProfile(profile.id)}
                          className="text-red-400 hover:text-red-300"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                      <div className="mt-2 text-xs space-y-1">
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Delta</span>
                          <span className="text-zinc-300">{profile.settings.min_delta} - {profile.settings.max_delta}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Max DTE</span>
                          <span className="text-zinc-300">{profile.settings.max_dte}d</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-zinc-500">Expected Win Rate</span>
                          <span className="text-emerald-400">{profile.settings.expected_win_rate}%</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Outcome Analysis */}
          {analytics.analytics.by_outcome?.length > 0 && (
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Activity className="w-4 h-4 text-blue-400" />
                  Performance by Outcome
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {analytics.analytics.by_outcome.map((outcome, idx) => (
                    <div key={idx} className="p-3 bg-zinc-800/50 rounded-lg text-center">
                      <div className="text-xs text-zinc-500 mb-1 capitalize">
                        {outcome.outcome.replace(/_/g, ' ')}
                      </div>
                      <div className="text-lg font-bold text-white">{outcome.count}</div>
                      <div className={`text-sm ${outcome.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {formatCurrency(outcome.total_pnl)}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );

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
            <LineChart className="w-4 h-4 mr-2" />
            Analytics
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
                  <div className="text-xs text-zinc-500 mb-1">{selectedTrade.status === 'active' ? 'Unrealized P/L' : 'Final P/L'}</div>
                  <div className={`text-lg font-semibold ${
                    selectedTrade.status === 'active'
                      ? (selectedTrade.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                      : (selectedTrade.final_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')
                  }`}>
                    {selectedTrade.status === 'active' 
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
                    {selectedTrade.status === 'active' ? `${selectedTrade.dte_remaining}d` : '-'}
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
              {selectedTrade.status === 'active' && (
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
                        {selectedTrade.current_gamma?.toFixed(4) || '-'}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-zinc-500 mb-1">Vega</div>
                      <div className="text-amber-400 font-mono font-semibold">
                        {selectedTrade.current_vega?.toFixed(2) || '-'}
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
