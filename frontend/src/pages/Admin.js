import { useState, useEffect } from 'react';
import { adminApi } from '../lib/api';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Switch } from '../components/ui/switch';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Skeleton } from '../components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Settings,
  Key,
  Database,
  Activity,
  Save,
  RefreshCw,
  Shield,
  Eye,
  EyeOff,
  AlertTriangle,
  Newspaper,
  BarChart3,
  Brain,
  CreditCard,
  DollarSign,
  TestTube,
  Zap,
  Users,
  TrendingUp,
  TrendingDown,
  Mail,
  Search,
  ChevronLeft,
  ChevronRight,
  Clock,
  AlertCircle,
  CheckCircle,
  XCircle,
  Calendar,
  MessageSquare,
  Trash2,
  Download,
  ExternalLink,
  X
} from 'lucide-react';
import { toast } from 'sonner';
import AdminSupport from '../components/AdminSupport';

const Admin = () => {
  const [activeTab, setActiveTab] = useState('dashboard');

  // API Settings
  const [settings, setSettings] = useState({
    massive_api_key: '',
    massive_access_id: '',
    massive_secret_key: '',
    marketaux_api_token: '',
    openai_api_key: '',
    data_refresh_interval: 60,
    enable_live_data: false
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Dashboard Stats
  const [dashboardStats, setDashboardStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(true);

  // User Management
  const [users, setUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersPagination, setUsersPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [userFilters, setUserFilters] = useState({ status: '', plan: '', search: '' });
  const [selectedUser, setSelectedUser] = useState(null);

  // Screener Status (Phase 8)
  const [screenerStatus, setScreenerStatus] = useState(null);
  const [screenerStatusLoading, setScreenerStatusLoading] = useState(false);

  // Invitations
  const [invitations, setInvitations] = useState([]);
  const [invitationsLoading, setInvitationsLoading] = useState(false);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteForm, setInviteForm] = useState({ email: '', name: '', role: 'tester', environment: 'test', message: '' });
  const [sendingInvite, setSendingInvite] = useState(false);

  // Subscription settings
  const [subscriptionSettings, setSubscriptionSettings] = useState({
    active_mode: 'test',
    test_links: { trial: '', monthly: '', yearly: '' },
    live_links: { trial: '', monthly: '', yearly: '' }
  });
  const [savingSubscription, setSavingSubscription] = useState(false);

  // Integration settings
  const [integrationSettings, setIntegrationSettings] = useState({
    stripe_webhook_secret: '',
    stripe_secret_key: '',
    resend_api_key: '',
    sender_email: '',
    paypal_enabled: true,
    paypal_mode: 'sandbox',
    paypal_api_username: '',
    paypal_api_password: '',
    paypal_api_signature: ''
  });
  const [integrationStatus, setIntegrationStatus] = useState(null);
  const [savingIntegration, setSavingIntegration] = useState(false);
  const [testEmailAddress, setTestEmailAddress] = useState('');
  const [sendingTestEmail, setSendingTestEmail] = useState(false);

  // Visibility toggles
  const [showMassiveApiKey, setShowMassiveApiKey] = useState(false);
  const [showMassiveAccessId, setShowMassiveAccessId] = useState(false);
  const [showMassiveSecretKey, setShowMassiveSecretKey] = useState(false);
  const [showMarketauxToken, setShowMarketauxToken] = useState(false);
  const [showOpenAIKey, setShowOpenAIKey] = useState(false);
  const [showStripeWebhook, setShowStripeWebhook] = useState(false);
  const [showStripeSecret, setShowStripeSecret] = useState(false);
  const [showResendKey, setShowResendKey] = useState(false);
  const [showPayPalPassword, setShowPayPalPassword] = useState(false);
  const [showPayPalSignature, setShowPayPalSignature] = useState(false);

  // Email Automation
  const [emailTemplates, setEmailTemplates] = useState([]);
  const [automationRules, setAutomationRules] = useState([]);
  const [emailLogs, setEmailLogs] = useState([]);
  const [emailStats, setEmailStats] = useState(null);
  const [emailLoading, setEmailLoading] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [editingTemplate, setEditingTemplate] = useState(null);
  const [emailSubTab, setEmailSubTab] = useState('templates');
  const [triggerTypes, setTriggerTypes] = useState([]);
  const [actionTypes, setActionTypes] = useState([]);
  const [broadcastData, setBroadcastData] = useState({
    template_key: 'announcement',
    announcement_title: '',
    announcement_content: ''
  });
  const [sendingBroadcast, setSendingBroadcast] = useState(false);

  // IMAP Email Sync
  const [imapSettings, setImapSettings] = useState({
    imap_server: 'imap.hostinger.com',
    imap_port: 993,
    username: '',
    password: ''
  });
  const [imapStatus, setImapStatus] = useState(null);
  const [imapHistory, setImapHistory] = useState([]);
  const [imapLoading, setImapLoading] = useState(false);
  const [imapSaving, setImapSaving] = useState(false);
  const [imapSyncing, setImapSyncing] = useState(false);
  const [showImapPassword, setShowImapPassword] = useState(false);

  // Pre-computed Scans Trigger
  const [triggeringScan, setTriggeringScan] = useState(false);
  const [lastScanResult, setLastScanResult] = useState(null);

  // Universe Exclusions Drilldown (Data Quality Tab)
  const [exclusionDrilldown, setExclusionDrilldown] = useState({
    open: false,
    reason: null,
    data: [],
    loading: false,
    offset: 0,
    total: 0
  });

  useEffect(() => {
    fetchSettings();
    fetchDashboardStats();
    fetchSubscriptionSettings();
    fetchIntegrationSettings();
    fetchScreenerStatus();
  }, []);

  // Keep Data Quality tab fresh (without masking missing backend fields)
  useEffect(() => {
    if (activeTab !== 'data-quality') return;
    // Fetch immediately on tab focus
    fetchScreenerStatus();
    // Poll every 30s while this tab is active
    const interval = setInterval(() => {
      fetchScreenerStatus();
    }, 30000);
    return () => clearInterval(interval);
  }, [activeTab]);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const response = await adminApi.getSettings();
      setSettings(prev => ({ ...prev, ...response.data }));
    } catch (error) {
      console.error('Settings fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchDashboardStats = async () => {
    setStatsLoading(true);
    try {
      const response = await api.get('/admin/dashboard-stats');
      setDashboardStats(response.data);
    } catch (error) {
      console.error('Dashboard stats error:', error);
    } finally {
      setStatsLoading(false);
    }
  };

  const fetchScreenerStatus = async () => {
    setScreenerStatusLoading(true);
    try {
      const response = await api.get('/screener/admin-status');
      setScreenerStatus(response.data);
    } catch (error) {
      console.error('Screener status error:', error);
    } finally {
      setScreenerStatusLoading(false);
    }
  };

  // Fetch exclusion drilldown data for a specific reason
  const fetchExclusionDrilldown = async (reason, offset = 0) => {
    setExclusionDrilldown(prev => ({ ...prev, loading: true, reason, offset }));
    try {
      const runId = screenerStatus?.run_id;
      const params = new URLSearchParams({
        limit: '100',
        offset: String(offset)
      });
      if (runId) params.append('run_id', runId);
      if (reason) params.append('reason', reason);
      
      const response = await api.get(`/admin/universe/excluded?${params.toString()}`);
      setExclusionDrilldown(prev => ({
        ...prev,
        open: true,
        data: response.data.items || [],
        total: response.data.total || 0,
        loading: false
      }));
    } catch (error) {
      console.error('Exclusion drilldown error:', error);
      toast.error('Failed to fetch exclusion details');
      setExclusionDrilldown(prev => ({ ...prev, loading: false }));
    }
  };

  // Download CSV with authentication (fixes auth header issue)
  const downloadExclusionCsv = async (reason) => {
    try {
      const runId = screenerStatus?.run_id;
      const params = new URLSearchParams();
      if (runId) params.append('run_id', runId);
      if (reason) params.append('reason', reason);
      
      // Use authenticated API call
      const response = await api.get(`/admin/universe/excluded.csv?${params.toString()}`, {
        responseType: 'blob'
      });
      
      // Create blob and trigger download
      const blob = new Blob([response.data], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      
      // Generate filename
      const reasonPart = reason ? `_${reason.toLowerCase()}` : '_all';
      const runIdPart = runId ? `_${runId}` : '';
      link.download = `excluded${reasonPart}${runIdPart}.csv`;
      
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      
      toast.success('CSV downloaded successfully');
    } catch (error) {
      console.error('CSV download error:', error);
      toast.error('Failed to download CSV');
    }
  };



  const fetchSubscriptionSettings = async () => {
    try {
      const response = await api.get('/subscription/admin/settings');
      setSubscriptionSettings(response.data);
    } catch (error) {
      console.error('Subscription settings error:', error);
    }
  };

  const fetchIntegrationSettings = async () => {
    try {
      const response = await api.get('/admin/integration-settings');
      setIntegrationStatus(response.data);
    } catch (error) {
      console.error('Integration settings error:', error);
    }
  };

  // IMAP Functions
  const fetchImapStatus = async () => {
    setImapLoading(true);
    try {
      const [statusRes, settingsRes, historyRes] = await Promise.all([
        api.get('/admin/imap/status'),
        api.get('/admin/imap/settings'),
        api.get('/admin/imap/sync-history?limit=10')
      ]);
      setImapStatus(statusRes.data);
      if (settingsRes.data.username) {
        setImapSettings(prev => ({
          ...prev,
          imap_server: settingsRes.data.imap_server || 'imap.hostinger.com',
          imap_port: settingsRes.data.imap_port || 993,
          username: settingsRes.data.username || '',
          password: settingsRes.data.password || ''
        }));
      }
      setImapHistory(historyRes.data.history || []);
    } catch (error) {
      console.error('IMAP status error:', error);
    } finally {
      setImapLoading(false);
    }
  };

  const saveImapSettings = async () => {
    setImapSaving(true);
    try {
      const response = await api.post('/admin/imap/settings', imapSettings);
      if (response.data.connection_test?.success) {
        toast.success('IMAP settings saved and connection verified!');
        fetchImapStatus();
      } else {
        toast.error(response.data.connection_test?.message || 'Settings saved but connection test failed');
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to save IMAP settings');
    } finally {
      setImapSaving(false);
    }
  };

  const testImapConnection = async () => {
    try {
      const response = await api.post('/admin/imap/test-connection');
      if (response.data.success) {
        toast.success(response.data.message);
      } else {
        toast.error(response.data.message);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Connection test failed');
    }
  };

  const syncImapNow = async () => {
    setImapSyncing(true);
    try {
      const response = await api.post('/admin/imap/sync-now');
      if (response.data.success) {
        toast.success(`Sync complete: ${response.data.processed} emails processed, ${response.data.matched} matched to tickets`);
        fetchImapStatus();
      } else {
        toast.error(response.data.errors?.[0] || 'Sync failed');
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Sync failed');
    } finally {
      setImapSyncing(false);
    }
  };

  const fetchEmailTemplates = async () => {
    setEmailLoading(true);
    try {
      const response = await api.get('/admin/email-automation/templates');
      setEmailTemplates(response.data.templates || []);
    } catch (error) {
      console.error('Email templates error:', error);
    } finally {
      setEmailLoading(false);
    }
  };

  const fetchAutomationRules = async () => {
    try {
      const response = await api.get('/admin/email-automation/rules');
      setAutomationRules(response.data.rules || []);
      setTriggerTypes(response.data.trigger_types || []);
      setActionTypes(response.data.action_types || []);
    } catch (error) {
      console.error('Automation rules error:', error);
    }
  };

  const fetchEmailLogs = async () => {
    try {
      const response = await api.get('/admin/email-automation/logs');
      setEmailLogs(response.data.logs || []);
    } catch (error) {
      console.error('Email logs error:', error);
    }
  };

  const fetchEmailStats = async () => {
    try {
      const response = await api.get('/admin/email-automation/stats');
      setEmailStats(response.data);
    } catch (error) {
      console.error('Email stats error:', error);
    }
  };

  const handleUpdateTemplate = async (templateId, updates) => {
    try {
      await api.put(`/admin/email-automation/templates/${templateId}`, null, { params: updates });
      toast.success('Template updated successfully');
      fetchEmailTemplates();
      setEditingTemplate(null);
    } catch (error) {
      toast.error('Failed to update template');
    }
  };

  const handleToggleRule = async (ruleId, enabled) => {
    try {
      await api.put(`/admin/email-automation/rules/${ruleId}`, null, { params: { enabled } });
      toast.success(`Rule ${enabled ? 'enabled' : 'disabled'}`);
      fetchAutomationRules();
    } catch (error) {
      toast.error('Failed to update rule');
    }
  };

  const handleSendBroadcast = async () => {
    if (!broadcastData.announcement_title || !broadcastData.announcement_content) {
      toast.error('Please fill in title and content');
      return;
    }

    setSendingBroadcast(true);
    try {
      const response = await api.post('/admin/email-automation/broadcast', null, {
        params: {
          template_key: broadcastData.template_key,
          announcement_title: broadcastData.announcement_title,
          announcement_content: broadcastData.announcement_content
        }
      });
      toast.success(`Broadcast sent to ${response.data.sent} users`);
      setBroadcastData({ template_key: 'announcement', announcement_title: '', announcement_content: '' });
      fetchEmailLogs();
      fetchEmailStats();
    } catch (error) {
      toast.error('Failed to send broadcast');
    } finally {
      setSendingBroadcast(false);
    }
  };

  const handleTestEmail = async (templateKey, email) => {
    try {
      await api.post('/admin/email-automation/test-send', null, {
        params: { template_key: templateKey, recipient_email: email }
      });
      toast.success(`Test email sent to ${email}`);
    } catch (error) {
      toast.error('Failed to send test email');
    }
  };

  const fetchUsers = async (page = 1) => {
    setUsersLoading(true);
    try {
      const params = new URLSearchParams({ page: page.toString(), limit: '20' });
      if (userFilters.status && userFilters.status !== 'all') params.append('status', userFilters.status);
      if (userFilters.plan && userFilters.plan !== 'all') params.append('plan', userFilters.plan);
      if (userFilters.search) params.append('search', userFilters.search);

      const response = await api.get(`/admin/users?${params.toString()}`);
      setUsers(response.data.users);
      setUsersPagination({ page: response.data.page, pages: response.data.pages, total: response.data.total });
    } catch (error) {
      console.error('Users fetch error:', error);
      toast.error('Failed to load users');
    } finally {
      setUsersLoading(false);
    }
  };

  const fetchInvitations = async () => {
    setInvitationsLoading(true);
    try {
      const response = await api.get('/invitations/list');
      setInvitations(response.data.invitations || []);
    } catch (error) {
      console.error('Invitations fetch error:', error);
    } finally {
      setInvitationsLoading(false);
    }
  };

  const sendInvitation = async () => {
    if (!inviteForm.email || !inviteForm.name) {
      toast.error('Please fill in email and name');
      return;
    }

    setSendingInvite(true);
    try {
      await api.post('/invitations/send', inviteForm);
      toast.success(`Invitation sent to ${inviteForm.email}`);
      setShowInviteModal(false);
      setInviteForm({ email: '', name: '', role: 'tester', message: '' });
      fetchInvitations();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to send invitation');
    } finally {
      setSendingInvite(false);
    }
  };

  const revokeInvitation = async (invitationId) => {
    if (!window.confirm('Are you sure you want to revoke this invitation?')) return;

    try {
      await api.delete(`/invitations/${invitationId}`);
      toast.success('Invitation revoked');
      fetchInvitations();
    } catch (error) {
      toast.error('Failed to revoke invitation');
    }
  };

  const resendInvitation = async (invitationId) => {
    try {
      await api.post(`/invitations/${invitationId}/resend`);
      toast.success('Invitation resent');
    } catch (error) {
      toast.error('Failed to resend invitation');
    }
  };

  const saveSettings = async () => {
    setSaving(true);
    try {
      await adminApi.updateSettings(settings);
      toast.success('Settings saved successfully');
    } catch (error) {
      toast.error('Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const saveSubscriptionSettings = async () => {
    setSavingSubscription(true);
    try {
      const params = new URLSearchParams({
        active_mode: subscriptionSettings.active_mode,
        test_trial: subscriptionSettings.test_links?.trial || '',
        test_monthly: subscriptionSettings.test_links?.monthly || '',
        test_yearly: subscriptionSettings.test_links?.yearly || '',
        live_trial: subscriptionSettings.live_links?.trial || '',
        live_monthly: subscriptionSettings.live_links?.monthly || '',
        live_yearly: subscriptionSettings.live_links?.yearly || ''
      });
      await api.post(`/subscription/admin/settings?${params.toString()}`);
      toast.success('Subscription settings saved');
    } catch (error) {
      toast.error('Failed to save subscription settings');
    } finally {
      setSavingSubscription(false);
    }
  };

  const saveIntegrationSettings = async () => {
    setSavingIntegration(true);
    try {
      const params = new URLSearchParams();
      if (integrationSettings.stripe_webhook_secret) params.append('stripe_webhook_secret', integrationSettings.stripe_webhook_secret);
      if (integrationSettings.stripe_secret_key) params.append('stripe_secret_key', integrationSettings.stripe_secret_key);
      if (integrationSettings.resend_api_key) params.append('resend_api_key', integrationSettings.resend_api_key);
      if (integrationSettings.sender_email) params.append('sender_email', integrationSettings.sender_email);
      // PayPal settings
      if (integrationSettings.paypal_enabled !== undefined) params.append('paypal_enabled', String(integrationSettings.paypal_enabled));
      if (integrationSettings.paypal_mode) params.append('paypal_mode', integrationSettings.paypal_mode);
      if (integrationSettings.paypal_api_username) params.append('paypal_api_username', integrationSettings.paypal_api_username);
      if (integrationSettings.paypal_api_password) params.append('paypal_api_password', integrationSettings.paypal_api_password);
      if (integrationSettings.paypal_api_signature) params.append('paypal_api_signature', integrationSettings.paypal_api_signature);

      await api.post(`/admin/integration-settings?${params.toString()}`);
      toast.success('Integration settings saved');
      fetchIntegrationSettings();
    } catch (error) {
      toast.error('Failed to save integration settings');
    } finally {
      setSavingIntegration(false);
    }
  };

  const sendTestEmail = async () => {
    if (!testEmailAddress) {
      toast.error('Please enter an email address');
      return;
    }
    setSendingTestEmail(true);
    try {
      const response = await api.post(`/admin/test-email?recipient_email=${encodeURIComponent(testEmailAddress)}&template_name=welcome`);
      if (response.data.status === 'success') {
        toast.success(`Test email sent to ${testEmailAddress}`);
      } else {
        toast.error(response.data.message || 'Failed to send test email');
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to send test email');
    } finally {
      setSendingTestEmail(false);
    }
  };

  const switchSubscriptionMode = async (mode) => {
    try {
      await api.post(`/subscription/admin/switch-mode?mode=${mode}`);
      setSubscriptionSettings(prev => ({ ...prev, active_mode: mode }));
      toast.success(`Switched to ${mode} mode`);
    } catch (error) {
      toast.error('Failed to switch mode');
    }
  };

  const extendUserTrial = async (userId, days) => {
    try {
      await api.post(`/admin/users/${userId}/extend-trial?days=${days}`);
      toast.success(`Trial extended by ${days} days`);
      fetchUsers(usersPagination.page);
    } catch (error) {
      toast.error('Failed to extend trial');
    }
  };

  const setUserSubscription = async (userId, status, plan = 'monthly') => {
    try {
      await api.post(`/admin/users/${userId}/set-subscription?status=${status}&plan=${plan}`);
      toast.success(`Subscription set to ${status}`);
      fetchUsers(usersPagination.page);
      fetchDashboardStats();
    } catch (error) {
      toast.error('Failed to set subscription');
    }
  };

  const deleteUser = async (userId, userEmail) => {
    if (!window.confirm(`Are you sure you want to delete user "${userEmail}"?\n\nThis action cannot be undone.`)) {
      return;
    }

    try {
      await api.delete(`/admin/users/${userId}`);
      toast.success(`User ${userEmail} deleted`);
      fetchUsers(usersPagination.page);
      fetchDashboardStats();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to delete user');
    }
  };

  const PasswordInput = ({ value, onChange, show, onToggle, placeholder, label }) => (
    <div className="space-y-2">
      <Label className="text-zinc-400">{label}</Label>
      <div className="relative">
        <Input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="input-dark pr-10 font-mono text-sm"
        />
        <button
          type="button"
          onClick={onToggle}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-white"
        >
          {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );

  const StatCard = ({ title, value, icon: Icon, trend, color = "emerald" }) => (
    <Card className="glass-card">
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-zinc-500 uppercase tracking-wide">{title}</p>
            <p className={`text-2xl font-bold text-${color}-400 mt-1`}>{value}</p>
            {trend && (
              <p className={`text-xs mt-1 ${trend >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {trend >= 0 ? '↑' : '↓'} {Math.abs(trend)}%
              </p>
            )}
          </div>
          <div className={`p-3 rounded-lg bg-${color}-500/10`}>
            <Icon className={`w-6 h-6 text-${color}-400`} />
          </div>
        </div>
      </CardContent>
    </Card>
  );

  const getStatusBadge = (status) => {
    const styles = {
      active: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
      trialing: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
      cancelled: 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
      past_due: 'bg-red-500/20 text-red-400 border-red-500/30',
      expired: 'bg-orange-500/20 text-orange-400 border-orange-500/30'
    };

    if (!status) {
      return <Badge className="bg-zinc-700/50 text-zinc-500 border-zinc-600/30">No Sub</Badge>;
    }

    return <Badge className={styles[status] || styles.expired}>{status}</Badge>;
  };

  // Helpers for Data Quality tab (avoid masking missing values with hardcoded defaults)
  const isNumber = (v) => typeof v === 'number' && !Number.isNaN(v);

  const formatUtc = (isoString) => {
    if (!isoString) return 'N/A';
    try {
      const d = new Date(isoString);
      if (Number.isNaN(d.getTime())) return 'N/A';
      const date = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
      const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
      return `${date} — ${time} UTC`;
    } catch {
      return 'N/A';
    }
  };

  const healthScoreValue = isNumber(screenerStatus?.health_score) ? screenerStatus.health_score : null;

  const lastFullRunIso =
    screenerStatus?.last_full_run_at ??
    screenerStatus?.last_full_run_utc ??
    screenerStatus?.last_full_run ??
    screenerStatus?.last_run_at ??
    screenerStatus?.last_run ??
    null;

  const marketState = screenerStatus?.market_state ?? screenerStatus?.market?.state ?? null;
  const priceSource =
    screenerStatus?.underlying_price_source ??
    screenerStatus?.price_source ??
    screenerStatus?.pricing_rule ??
    null;

  const realtimeBadgeText = (() => {
    if (!marketState && !priceSource) return '⚠️ Data source unknown';
    const ms = String(marketState || '').toUpperCase();
    const ps = String(priceSource || '').toUpperCase();

    const isLive = ps.includes('REAL') || ps.includes('LIVE') || ps.includes('INTRADAY') || ps.includes('OPEN');
    const isClose = ps.includes('CLOSE') || ps.includes('PREV') || ps.includes('EOD');

    if (ms === 'OPEN') return isLive ? '✅ Real-time (OPEN)' : '🟡 Market OPEN (non-live source)';
    if (ms === 'CLOSED') return isClose ? '🕐 Market Close data' : '🟡 Market CLOSED (source unclear)';
    if (ms === 'PREMARKET' || ms === 'AFTERHOURS') return isLive ? `✅ ${ms} live` : `🟡 ${ms} (non-live)`;
    return isLive ? '✅ Live pricing' : isClose ? '🕐 Market close pricing' : '⚠️ Data source unknown';
  })();

  const sdHigh = isNumber(screenerStatus?.score_distribution?.high) ? screenerStatus.score_distribution.high : null;
  const sdMediumHigh = isNumber(screenerStatus?.score_distribution?.medium_high) ? screenerStatus.score_distribution.medium_high : null;
  const sdMedium = isNumber(screenerStatus?.score_distribution?.medium) ? screenerStatus.score_distribution.medium : null;
  const sdLow = isNumber(screenerStatus?.score_distribution?.low) ? screenerStatus.score_distribution.low : null;

  const scoreDriftValue = isNumber(screenerStatus?.score_drift) ? screenerStatus.score_drift : null;
  const outlierSwingsValue = isNumber(screenerStatus?.outlier_swings) ? screenerStatus.outlier_swings : null;

  // Universe tier counts and exclusion breakdown
  const tierCounts = screenerStatus?.tier_counts || screenerStatus?.universe?.tier_counts || null;
  const universeIncluded = screenerStatus?.included ?? screenerStatus?.universe?.included ?? null;
  const universeExcluded = screenerStatus?.excluded ?? screenerStatus?.universe?.excluded ?? null;
  const excludedCountsByReason = screenerStatus?.excluded_counts_by_reason || screenerStatus?.universe?.excluded_counts_by_reason || screenerStatus?.universe?.excluded_counts || null;
  const excludedCountsByStage = screenerStatus?.excluded_counts_by_stage || screenerStatus?.universe?.excluded_counts_by_stage || null;
  const currentRunId = screenerStatus?.run_id || null;

  return (
    <div className="space-y-6" data-testid="admin-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Settings className="w-8 h-8 text-emerald-500" />
            Admin Panel
          </h1>
          <p className="text-zinc-400 mt-1">Manage users, subscriptions, and settings</p>
        </div>
        <Button onClick={() => { fetchDashboardStats(); fetchSettings(); }} variant="outline" className="btn-outline">
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Main Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="flex w-full bg-zinc-800/50 p-1 overflow-x-auto">
          <TabsTrigger value="dashboard" className="flex items-center gap-2 px-3">
            <BarChart3 className="w-4 h-4" />
            Dashboard
          </TabsTrigger>
          <TabsTrigger value="data-quality" className="flex items-center gap-2 px-3" onClick={() => fetchScreenerStatus()}>
            <Database className="w-4 h-4" />
            Data Quality
          </TabsTrigger>
          <TabsTrigger value="users" className="flex items-center gap-2 px-3" onClick={() => { fetchUsers(1); fetchInvitations(); }}>
            <Users className="w-4 h-4" />
            Users
          </TabsTrigger>
          <TabsTrigger value="support" className="flex items-center gap-2 px-3">
            <MessageSquare className="w-4 h-4" />
            Support
          </TabsTrigger>
          <TabsTrigger value="email-automation" className="flex items-center gap-2 px-3" onClick={() => { fetchEmailTemplates(); fetchAutomationRules(); fetchEmailLogs(); fetchEmailStats(); }}>
            <Mail className="w-4 h-4" />
            Email
          </TabsTrigger>
          <TabsTrigger value="subscriptions" className="flex items-center gap-2 px-3">
            <CreditCard className="w-4 h-4" />
            Billing
          </TabsTrigger>
          <TabsTrigger value="integrations" className="flex items-center gap-2 px-3">
            <Zap className="w-4 h-4" />
            Integrations
          </TabsTrigger>
          <TabsTrigger value="imap" className="flex items-center gap-2 px-3" onClick={() => fetchImapStatus()}>
            <Mail className="w-4 h-4" />
            Email Sync
          </TabsTrigger>
          <TabsTrigger value="api-keys" className="flex items-center gap-2 px-3">
            <Key className="w-4 h-4" />
            API Keys
          </TabsTrigger>
        </TabsList>

        {/* Dashboard Tab */}
        <TabsContent value="dashboard" className="space-y-6 mt-6">
          {statsLoading ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[...Array(8)].map((_, i) => <Skeleton key={i} className="h-24 rounded-lg" />)}
            </div>
          ) : dashboardStats ? (
            <>
              {/* KPI Cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard title="Total Users" value={dashboardStats.users?.total || 0} icon={Users} color="violet" />
                <StatCard title="Active (7d)" value={dashboardStats.users?.active_7d || 0} icon={Activity} color="emerald" />
                <StatCard title="Trial Users" value={dashboardStats.users?.trial || 0} icon={Clock} color="blue" />
                <StatCard title="Paid Subs" value={dashboardStats.subscriptions?.active || 0} icon={CreditCard} color="amber" />
              </div>

              {/* Revenue & Metrics */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard
                  title="MRR"
                  value={`$${dashboardStats.revenue?.mrr?.toLocaleString() || 0}`}
                  icon={DollarSign}
                  color="emerald"
                />
                <StatCard
                  title="ARR"
                  value={`$${dashboardStats.revenue?.arr?.toLocaleString() || 0}`}
                  icon={TrendingUp}
                  color="cyan"
                />
                <StatCard
                  title="Conversion Rate"
                  value={`${dashboardStats.subscriptions?.conversion_rate || 0}%`}
                  icon={TrendingUp}
                  color="violet"
                />
                <StatCard
                  title="Churn Rate"
                  value={`${dashboardStats.subscriptions?.churn_rate || 0}%`}
                  icon={TrendingDown}
                  color="red"
                />
              </div>

              {/* Alerts */}
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5 text-yellow-400" />
                    Alerts & Notifications
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid md:grid-cols-3 gap-4">
                    <div className={`p-4 rounded-lg ${dashboardStats.alerts?.trials_ending_soon > 0 ? 'bg-yellow-500/10 border border-yellow-500/30' : 'bg-zinc-800/50'}`}>
                      <div className="flex items-center gap-3">
                        <Clock className={`w-8 h-8 ${dashboardStats.alerts?.trials_ending_soon > 0 ? 'text-yellow-400' : 'text-zinc-600'}`} />
                        <div>
                          <p className="text-2xl font-bold text-white">{dashboardStats.alerts?.trials_ending_soon || 0}</p>
                          <p className="text-xs text-zinc-400">Trials ending in 3 days</p>
                        </div>
                      </div>
                    </div>
                    <div className={`p-4 rounded-lg ${dashboardStats.alerts?.payment_failures > 0 ? 'bg-red-500/10 border border-red-500/30' : 'bg-zinc-800/50'}`}>
                      <div className="flex items-center gap-3">
                        <AlertCircle className={`w-8 h-8 ${dashboardStats.alerts?.payment_failures > 0 ? 'text-red-400' : 'text-zinc-600'}`} />
                        <div>
                          <p className="text-2xl font-bold text-white">{dashboardStats.alerts?.payment_failures || 0}</p>
                          <p className="text-xs text-zinc-400">Payment failures</p>
                        </div>
                      </div>
                    </div>
                    <div className={`p-4 rounded-lg ${dashboardStats.alerts?.open_tickets > 0 ? 'bg-blue-500/10 border border-blue-500/30' : 'bg-zinc-800/50'}`}>
                      <div className="flex items-center gap-3">
                        <Mail className={`w-8 h-8 ${dashboardStats.alerts?.open_tickets > 0 ? 'text-blue-400' : 'text-zinc-600'}`} />
                        <div>
                          <p className="text-2xl font-bold text-white">{dashboardStats.alerts?.open_tickets || 0}</p>
                          <p className="text-xs text-zinc-400">Open support tickets</p>
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Subscription Breakdown */}
              <div className="grid md:grid-cols-2 gap-6">
                <Card className="glass-card">
                  <CardHeader>
                    <CardTitle className="text-lg">Subscription Breakdown</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
                      <span className="text-zinc-400">Monthly Plans</span>
                      <span className="text-xl font-bold text-violet-400">{dashboardStats.subscriptions?.monthly || 0}</span>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
                      <span className="text-zinc-400">Annual Plans</span>
                      <span className="text-xl font-bold text-amber-400">{dashboardStats.subscriptions?.yearly || 0}</span>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
                      <span className="text-zinc-400">Cancelled</span>
                      <span className="text-xl font-bold text-zinc-400">{dashboardStats.users?.cancelled || 0}</span>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
                      <span className="text-zinc-400">Past Due</span>
                      <span className="text-xl font-bold text-red-400">{dashboardStats.users?.past_due || 0}</span>
                    </div>
                  </CardContent>
                </Card>

                <Card className="glass-card">
                  <CardHeader>
                    <CardTitle className="text-lg">Quick Actions</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Button className="w-full justify-start" variant="outline" onClick={() => { setActiveTab('users'); fetchUsers(1); }}>
                      <Users className="w-4 h-4 mr-2" />
                      View All Users
                    </Button>
                    <Button className="w-full justify-start" variant="outline" onClick={() => setActiveTab('subscriptions')}>
                      <CreditCard className="w-4 h-4 mr-2" />
                      Manage Subscriptions
                    </Button>
                    <Button className="w-full justify-start" variant="outline" onClick={() => setActiveTab('integrations')}>
                      <Key className="w-4 h-4 mr-2" />
                      Configure Integrations
                    </Button>
                    <Button className="w-full justify-start" variant="outline" onClick={() => setActiveTab('data-quality')}>
                      <Database className="w-4 h-4 mr-2" />
                      View Data Quality
                    </Button>
                  </CardContent>
                </Card>
              </div>
            </>
          ) : (
            <Card className="glass-card p-8 text-center">
              <AlertCircle className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
              <p className="text-zinc-400">Failed to load dashboard data</p>
            </Card>
          )}
        </TabsContent>

        {/* Data Quality Tab */}
        <TabsContent value="data-quality" className="space-y-6 mt-6">
          {screenerStatusLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-32 w-full" />
              <div className="grid md:grid-cols-2 gap-4">
                <Skeleton className="h-48" />
                <Skeleton className="h-48" />
              </div>
            </div>
          ) : screenerStatus ? (
            <div className="space-y-6">
              {/* 1️⃣ Overall System Health */}
              <Card className={`glass-card border-2 ${
                healthScoreValue === null
                  ? 'border-zinc-700 bg-gradient-to-r from-zinc-700/10 to-transparent'
                  : healthScoreValue >= 80
                    ? 'border-emerald-500/30 bg-gradient-to-r from-emerald-500/5 to-transparent'
                    : healthScoreValue >= 60
                      ? 'border-yellow-500/30 bg-gradient-to-r from-yellow-500/5 to-transparent'
                      : 'border-red-500/30 bg-gradient-to-r from-red-500/5 to-transparent'
              }`}>
                <CardContent className="pt-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className={`w-16 h-16 rounded-full flex items-center justify-center ${
                        healthScoreValue === null
                          ? 'bg-zinc-700/30'
                          : healthScoreValue >= 80
                            ? 'bg-emerald-500/20'
                            : healthScoreValue >= 60
                              ? 'bg-yellow-500/20'
                              : 'bg-red-500/20'
                      }`}>
                        <span className={`text-2xl ${
                          healthScoreValue === null
                            ? 'text-zinc-400'
                            : healthScoreValue >= 80
                              ? 'text-emerald-400'
                              : healthScoreValue >= 60
                                ? 'text-yellow-400'
                                : 'text-red-400'
                        }`}>
                          {healthScoreValue === null ? '⚪' : healthScoreValue >= 80 ? '🟢' : healthScoreValue >= 60 ? '🟡' : '🔴'}
                        </span>
                      </div>
                      <div>
                        <p className="text-sm text-zinc-400 uppercase tracking-wider">System Health</p>
                        <p className={`text-3xl font-bold ${
                          healthScoreValue === null
                            ? 'text-zinc-300'
                            : healthScoreValue >= 80
                              ? 'text-emerald-400'
                              : healthScoreValue >= 60
                                ? 'text-yellow-400'
                                : 'text-red-400'
                        }`}>
                          {healthScoreValue === null ? 'UNKNOWN' : healthScoreValue >= 80 ? 'HEALTHY' : healthScoreValue >= 60 ? 'DEGRADED' : 'CRITICAL'}
                          <span className="text-xl ml-2">({healthScoreValue ?? 'N/A'} / 100)</span>
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-zinc-400">Last Full Run</p>
                      <p className="text-lg font-mono text-white">{formatUtc(lastFullRunIso)}</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* 2️⃣ Core Metrics */}
              <div className="grid md:grid-cols-4 gap-4">
                <Card className="glass-card">
                  <CardContent className="pt-4">
                    <p className="text-xs text-zinc-500 uppercase">Total Opportunities</p>
                    <p className="text-2xl font-bold text-emerald-400 mt-1">
                      {isNumber(screenerStatus?.total_opportunities) ? screenerStatus.total_opportunities : 'N/A'}
                    </p>
                  </CardContent>
                </Card>
                <Card className="glass-card">
                  <CardContent className="pt-4">
                    <p className="text-xs text-zinc-500 uppercase">Symbols Scanned</p>
                    <p className="text-2xl font-bold text-violet-400 mt-1">
                      {isNumber(screenerStatus?.symbols_scanned) ? screenerStatus.symbols_scanned : 'N/A'}
                    </p>
                  </CardContent>
                </Card>
                <Card className="glass-card">
                  <CardContent className="pt-4">
                    <p className="text-xs text-zinc-500 uppercase">Avg Score</p>
                    <p className="text-2xl font-bold text-cyan-400 mt-1">
                      {isNumber(screenerStatus?.average_score) ? screenerStatus.average_score.toFixed(1) : 'N/A'}
                    </p>
                  </CardContent>
                </Card>
                <Card className="glass-card">
                  <CardContent className="pt-4">
                    <p className="text-xs text-zinc-500 uppercase">Data Freshness</p>
                    <p className="text-lg font-medium text-white mt-1">{realtimeBadgeText}</p>
                  </CardContent>
                </Card>
              </div>

              {/* 3️⃣ Score Distribution */}
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <BarChart3 className="w-5 h-5 text-violet-400" />
                    Score Distribution
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-4 gap-4">
                    <div className="text-center p-4 rounded-lg bg-emerald-500/10">
                      <p className="text-3xl font-bold text-emerald-400">{sdHigh ?? 'N/A'}</p>
                      <p className="text-xs text-zinc-400 mt-1">High (70+)</p>
                    </div>
                    <div className="text-center p-4 rounded-lg bg-cyan-500/10">
                      <p className="text-3xl font-bold text-cyan-400">{sdMediumHigh ?? 'N/A'}</p>
                      <p className="text-xs text-zinc-400 mt-1">Med-High (50-69)</p>
                    </div>
                    <div className="text-center p-4 rounded-lg bg-yellow-500/10">
                      <p className="text-3xl font-bold text-yellow-400">{sdMedium ?? 'N/A'}</p>
                      <p className="text-xs text-zinc-400 mt-1">Medium (30-49)</p>
                    </div>
                    <div className="text-center p-4 rounded-lg bg-zinc-700/50">
                      <p className="text-3xl font-bold text-zinc-400">{sdLow ?? 'N/A'}</p>
                      <p className="text-xs text-zinc-400 mt-1">Low (&lt;30)</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* 3.5️⃣ Universe Breakdown (Tier Counts) */}
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Database className="w-5 h-5 text-cyan-400" />
                    Universe Breakdown
                  </CardTitle>
                  <CardDescription>
                    Run ID: <span className="font-mono text-xs text-zinc-400">{currentRunId || 'N/A'}</span>
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {tierCounts ? (
                    <div className="space-y-4">
                      {/* Tier Counts Grid */}
                      <div className="grid grid-cols-5 gap-3">
                        <div className="text-center p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
                          <p className="text-2xl font-bold text-blue-400">{tierCounts.sp500 ?? 'N/A'}</p>
                          <p className="text-xs text-zinc-400 mt-1">S&P 500</p>
                        </div>
                        <div className="text-center p-3 rounded-lg bg-purple-500/10 border border-purple-500/20">
                          <p className="text-2xl font-bold text-purple-400">{tierCounts.nasdaq100_net ?? 'N/A'}</p>
                          <p className="text-xs text-zinc-400 mt-1">Nasdaq 100</p>
                        </div>
                        <div className="text-center p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                          <p className="text-2xl font-bold text-amber-400">{tierCounts.etf_whitelist ?? 'N/A'}</p>
                          <p className="text-xs text-zinc-400 mt-1">ETF Whitelist</p>
                        </div>
                        <div className="text-center p-3 rounded-lg bg-zinc-700/50 border border-zinc-600/20">
                          <p className="text-2xl font-bold text-zinc-400">{tierCounts.liquidity_expansion ?? 0}</p>
                          <p className="text-xs text-zinc-400 mt-1">Liquidity Exp.</p>
                        </div>
                        <div className="text-center p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
                          <p className="text-2xl font-bold text-emerald-400">{tierCounts.total ?? 'N/A'}</p>
                          <p className="text-xs text-zinc-400 mt-1">Total</p>
                        </div>
                      </div>
                      
                      {/* Included / Excluded Summary */}
                      <div className="flex gap-4 mt-4">
                        <div className="flex-1 p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                          <div className="flex items-center justify-between">
                            <span className="text-zinc-400">Included</span>
                            <span className="text-2xl font-bold text-emerald-400">{universeIncluded ?? 'N/A'}</span>
                          </div>
                        </div>
                        <div className="flex-1 p-4 rounded-lg bg-red-500/10 border border-red-500/20">
                          <div className="flex items-center justify-between">
                            <span className="text-zinc-400">Excluded</span>
                            <span className="text-2xl font-bold text-red-400">{universeExcluded ?? 'N/A'}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-zinc-500 text-center py-4">No tier count data available</p>
                  )}
                </CardContent>
              </Card>

              {/* 3.6️⃣ Exclusions Breakdown (Clickable) */}
              <Card className="glass-card">
                <CardHeader className="flex flex-row items-center justify-between">
                  <div>
                    <CardTitle className="text-lg flex items-center gap-2">
                      <XCircle className="w-5 h-5 text-red-400" />
                      Exclusions Breakdown
                    </CardTitle>
                    <CardDescription>Click a reason to view excluded symbols</CardDescription>
                  </div>
                  <button
                    onClick={() => downloadExclusionCsv(null)}
                    className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-zinc-700 hover:bg-zinc-600 rounded-lg transition-colors"
                  >
                    <Download className="w-4 h-4" />
                    Download All CSV
                  </button>
                </CardHeader>
                <CardContent>
                  {excludedCountsByReason ? (
                    <div className="space-y-4">
                      {/* By Reason Table */}
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-zinc-700">
                              <th className="text-left py-2 px-3 text-zinc-400 font-medium">Reason</th>
                              <th className="text-right py-2 px-3 text-zinc-400 font-medium">Count</th>
                              <th className="text-right py-2 px-3 text-zinc-400 font-medium">Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(excludedCountsByReason)
                              .filter(([_, count]) => count > 0)
                              .sort(([, a], [, b]) => b - a)
                              .map(([reason, count]) => (
                                <tr key={reason} className="border-b border-zinc-800 hover:bg-zinc-800/50 transition-colors">
                                  <td className="py-3 px-3">
                                    <button
                                      onClick={() => fetchExclusionDrilldown(reason, 0)}
                                      className="text-left text-cyan-400 hover:text-cyan-300 hover:underline cursor-pointer"
                                    >
                                      {reason.replace(/_/g, ' ')}
                                    </button>
                                  </td>
                                  <td className="py-3 px-3 text-right">
                                    <span className="font-mono text-red-400">{count}</span>
                                  </td>
                                  <td className="py-3 px-3 text-right">
                                    <div className="flex items-center justify-end gap-2">
                                      <button
                                        onClick={() => fetchExclusionDrilldown(reason, 0)}
                                        className="p-1.5 rounded hover:bg-zinc-700 text-zinc-400 hover:text-white"
                                        title="View Details"
                                      >
                                        <Eye className="w-4 h-4" />
                                      </button>
                                      <a
                                        href={getExclusionCsvUrl(reason)}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="p-1.5 rounded hover:bg-zinc-700 text-zinc-400 hover:text-white"
                                        title="Download CSV"
                                      >
                                        <Download className="w-4 h-4" />
                                      </a>
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            {Object.entries(excludedCountsByReason).filter(([_, count]) => count > 0).length === 0 && (
                              <tr>
                                <td colSpan={3} className="py-4 text-center text-zinc-500">
                                  No exclusions recorded
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>

                      {/* By Stage (Optional - if available) */}
                      {excludedCountsByStage && Object.values(excludedCountsByStage).some(v => v > 0) && (
                        <div className="mt-4 pt-4 border-t border-zinc-700">
                          <p className="text-xs text-zinc-500 uppercase mb-2">By Stage</p>
                          <div className="flex flex-wrap gap-2">
                            {Object.entries(excludedCountsByStage)
                              .filter(([_, count]) => count > 0)
                              .map(([stage, count]) => (
                                <Badge key={stage} variant="outline" className="text-xs">
                                  {stage}: {count}
                                </Badge>
                              ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-zinc-500 text-center py-4">No exclusion data available</p>
                  )}
                </CardContent>
              </Card>

              {/* 4️⃣ Data Quality Indicators */}
              <div className="grid md:grid-cols-2 gap-4">
                <Card className="glass-card">
                  <CardHeader>
                    <CardTitle className="text-lg">Quality Checks</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <span className="text-zinc-400">Score Drift (vs 24h ago)</span>
                      <span className={`font-bold ${
                        scoreDriftValue === null
                          ? 'text-zinc-500'
                          : Math.abs(scoreDriftValue) < 5
                            ? 'text-emerald-400'
                            : Math.abs(scoreDriftValue) < 10
                              ? 'text-yellow-400'
                              : 'text-red-400'
                      }`}>
                        {scoreDriftValue === null ? 'N/A' : `${scoreDriftValue > 0 ? '+' : ''}${scoreDriftValue.toFixed(1)}%`}
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <span className="text-zinc-400">Outlier Swings</span>
                      <span className={`font-bold ${
                        outlierSwingsValue === null
                          ? 'text-zinc-500'
                          : outlierSwingsValue === 0
                            ? 'text-emerald-400'
                            : outlierSwingsValue < 3
                              ? 'text-yellow-400'
                              : 'text-red-400'
                      }`}>
                        {outlierSwingsValue ?? 'N/A'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <span className="text-zinc-400">Market State</span>
                      <Badge className={
                        marketState === 'OPEN'
                          ? 'bg-emerald-500/20 text-emerald-400'
                          : marketState === 'CLOSED'
                            ? 'bg-zinc-500/20 text-zinc-400'
                            : 'bg-yellow-500/20 text-yellow-400'
                      }>
                        {marketState || 'N/A'}
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <span className="text-zinc-400">Price Source</span>
                      <span className="text-white font-mono text-sm">{priceSource || 'N/A'}</span>
                    </div>
                  </CardContent>
                </Card>

                <Card className="glass-card">
                  <CardHeader>
                    <CardTitle className="text-lg">System Info</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <span className="text-zinc-400">Cache Status</span>
                      <Badge className={screenerStatus?.cache_status === 'valid' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-yellow-500/20 text-yellow-400'}>
                        {screenerStatus?.cache_status || 'N/A'}
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <span className="text-zinc-400">Last Cache Update</span>
                      <span className="text-white text-sm">{formatUtc(screenerStatus?.cache_updated_at)}</span>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <span className="text-zinc-400">API Errors (24h)</span>
                      <span className={`font-bold ${
                        !isNumber(screenerStatus?.api_errors_24h)
                          ? 'text-zinc-500'
                          : screenerStatus.api_errors_24h === 0
                            ? 'text-emerald-400'
                            : screenerStatus.api_errors_24h < 5
                              ? 'text-yellow-400'
                              : 'text-red-400'
                      }`}>
                        {screenerStatus?.api_errors_24h ?? 'N/A'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <span className="text-zinc-400">Scheduler Status</span>
                      <Badge className={screenerStatus?.scheduler_running ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}>
                        {screenerStatus?.scheduler_running ? 'Running' : screenerStatus?.scheduler_running === false ? 'Stopped' : 'N/A'}
                      </Badge>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          ) : (
            <Card className="glass-card p-8 text-center">
              <Database className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
              <p className="text-zinc-400">No screener status data available</p>
              <Button onClick={fetchScreenerStatus} variant="outline" className="mt-4">
                <RefreshCw className="w-4 h-4 mr-2" />
                Retry
              </Button>
            </Card>
          )}
        </TabsContent>

        {/* Users Tab */}
        <TabsContent value="users" className="space-y-6 mt-6">
          {/* Filters */}
          <Card className="glass-card">
            <CardContent className="pt-4">
              <div className="flex flex-wrap gap-4 items-end">
                <div className="flex-1 min-w-[200px]">
                  <Label className="text-zinc-400 text-xs">Search</Label>
                  <div className="relative mt-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
                    <Input
                      placeholder="Email or name..."
                      value={userFilters.search}
                      onChange={(e) => setUserFilters(f => ({ ...f, search: e.target.value }))}
                      className="input-dark pl-10"
                    />
                  </div>
                </div>
                <div className="w-40">
                  <Label className="text-zinc-400 text-xs">Status</Label>
                  <Select value={userFilters.status} onValueChange={(v) => setUserFilters(f => ({ ...f, status: v }))}>
                    <SelectTrigger className="input-dark mt-1">
                      <SelectValue placeholder="All" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All</SelectItem>
                      <SelectItem value="trialing">Trialing</SelectItem>
                      <SelectItem value="active">Active</SelectItem>
                      <SelectItem value="cancelled">Cancelled</SelectItem>
                      <SelectItem value="past_due">Past Due</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="w-40">
                  <Label className="text-zinc-400 text-xs">Plan</Label>
                  <Select value={userFilters.plan} onValueChange={(v) => setUserFilters(f => ({ ...f, plan: v }))}>
                    <SelectTrigger className="input-dark mt-1">
                      <SelectValue placeholder="All" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All</SelectItem>
                      <SelectItem value="monthly">Monthly</SelectItem>
                      <SelectItem value="yearly">Yearly</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Button onClick={() => fetchUsers(1)} className="bg-emerald-600 hover:bg-emerald-700">
                  <Search className="w-4 h-4 mr-2" />
                  Search
                </Button>
                <Button onClick={() => setShowInviteModal(true)} variant="outline" className="border-violet-500 text-violet-400">
                  <Mail className="w-4 h-4 mr-2" />
                  Invite User
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Users Table */}
          <Card className="glass-card">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-lg">Users ({usersPagination.total})</CardTitle>
              <Button onClick={() => fetchUsers(usersPagination.page)} variant="ghost" size="sm">
                <RefreshCw className={`w-4 h-4 ${usersLoading ? 'animate-spin' : ''}`} />
              </Button>
            </CardHeader>
            <CardContent>
              {usersLoading ? (
                <div className="space-y-2">
                  {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-16" />)}
                </div>
              ) : users.length === 0 ? (
                <p className="text-zinc-500 text-center py-8">No users found</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="text-left text-xs text-zinc-500 border-b border-zinc-800">
                        <th className="pb-2 font-medium">User</th>
                        <th className="pb-2 font-medium">Status</th>
                        <th className="pb-2 font-medium">Plan</th>
                        <th className="pb-2 font-medium">Trial Ends</th>
                        <th className="pb-2 font-medium">Joined</th>
                        <th className="pb-2 font-medium text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((user) => (
                        <tr key={user.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                          <td className="py-3">
                            <div>
                              <p className="font-medium text-white">{user.name || 'N/A'}</p>
                              <p className="text-xs text-zinc-500">{user.email}</p>
                            </div>
                          </td>
                          <td className="py-3">
                            {getStatusBadge(user.subscription?.status)}
                          </td>
                          <td className="py-3">
                            <span className="text-zinc-400">{user.subscription?.plan || '-'}</span>
                          </td>
                          <td className="py-3">
                            {user.subscription?.trial_end ? (
                              <span className="text-xs text-zinc-400">
                                {new Date(user.subscription.trial_end).toLocaleDateString()}
                              </span>
                            ) : '-'}
                          </td>
                          <td className="py-3">
                            <span className="text-xs text-zinc-500">
                              {new Date(user.created_at).toLocaleDateString()}
                            </span>
                          </td>
                          <td className="py-3">
                            <div className="flex justify-end gap-1">
                              {user.subscription?.status === 'trialing' && (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => extendUserTrial(user.id, 7)}
                                  className="text-blue-400 hover:text-blue-300 text-xs"
                                >
                                  +7 days
                                </Button>
                              )}
                              <Select onValueChange={(status) => setUserSubscription(user.id, status)}>
                                <SelectTrigger className="h-8 w-24 text-xs">
                                  <SelectValue placeholder="Set..." />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="active">Activate</SelectItem>
                                  <SelectItem value="trialing">Trial</SelectItem>
                                  <SelectItem value="cancelled">Cancel</SelectItem>
                                </SelectContent>
                              </Select>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => deleteUser(user.id, user.email)}
                                className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
                              >
                                <Trash2 className="w-4 h-4" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Pagination */}
              {usersPagination.pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-800">
                  <p className="text-sm text-zinc-500">
                    Page {usersPagination.page} of {usersPagination.pages}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fetchUsers(usersPagination.page - 1)}
                      disabled={usersPagination.page <= 1}
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fetchUsers(usersPagination.page + 1)}
                      disabled={usersPagination.page >= usersPagination.pages}
                    >
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Invitations Section */}
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Mail className="w-5 h-5 text-violet-400" />
                Pending Invitations
              </CardTitle>
            </CardHeader>
            <CardContent>
              {invitationsLoading ? (
                <Skeleton className="h-20" />
              ) : invitations.length === 0 ? (
                <p className="text-zinc-500 text-center py-4">No pending invitations</p>
              ) : (
                <div className="space-y-2">
                  {invitations.map((inv) => (
                    <div key={inv.id} className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                      <div>
                        <p className="font-medium text-white">{inv.name}</p>
                        <p className="text-xs text-zinc-500">{inv.email} • {inv.role}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge className={inv.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' : inv.status === 'accepted' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-500/20 text-zinc-400'}>
                          {inv.status}
                        </Badge>
                        {inv.status === 'pending' && (
                          <>
                            <Button size="sm" variant="ghost" onClick={() => resendInvitation(inv.id)}>
                              <RefreshCw className="w-4 h-4" />
                            </Button>
                            <Button size="sm" variant="ghost" className="text-red-400" onClick={() => revokeInvitation(inv.id)}>
                              <XCircle className="w-4 h-4" />
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Invite Modal */}
          {showInviteModal && (
            <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
              <Card className="glass-card w-full max-w-md mx-4">
                <CardHeader>
                  <CardTitle>Invite New User</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <Label>Email</Label>
                    <Input
                      type="email"
                      value={inviteForm.email}
                      onChange={(e) => setInviteForm(f => ({ ...f, email: e.target.value }))}
                      className="input-dark mt-1"
                      placeholder="user@example.com"
                    />
                  </div>
                  <div>
                    <Label>Name</Label>
                    <Input
                      value={inviteForm.name}
                      onChange={(e) => setInviteForm(f => ({ ...f, name: e.target.value }))}
                      className="input-dark mt-1"
                      placeholder="John Doe"
                    />
                  </div>
                  <div>
                    <Label>Role</Label>
                    <Select value={inviteForm.role} onValueChange={(v) => setInviteForm(f => ({ ...f, role: v }))}>
                      <SelectTrigger className="input-dark mt-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="tester">Beta Tester</SelectItem>
                        <SelectItem value="subscriber">Subscriber</SelectItem>
                        <SelectItem value="admin">Admin</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>Personal Message (Optional)</Label>
                    <Input
                      value={inviteForm.message}
                      onChange={(e) => setInviteForm(f => ({ ...f, message: e.target.value }))}
                      className="input-dark mt-1"
                      placeholder="Welcome to CCE!"
                    />
                  </div>
                  <div className="flex gap-2 pt-2">
                    <Button variant="outline" className="flex-1" onClick={() => setShowInviteModal(false)}>
                      Cancel
                    </Button>
                    <Button className="flex-1 bg-violet-600 hover:bg-violet-700" onClick={sendInvitation} disabled={sendingInvite}>
                      {sendingInvite ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4 mr-2" />}
                      Send Invite
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        {/* Support Tab */}
        <TabsContent value="support" className="mt-6">
          <AdminSupport />
        </TabsContent>

        {/* Email Automation Tab */}
        <TabsContent value="email-automation" className="space-y-6 mt-6">
          {/* Email Stats */}
          {emailStats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard title="Total Sent" value={emailStats.total_sent || 0} icon={Mail} color="violet" />
              <StatCard title="Delivered" value={emailStats.delivered || 0} icon={CheckCircle} color="emerald" />
              <StatCard title="Failed" value={emailStats.failed || 0} icon={XCircle} color="red" />
              <StatCard title="Pending" value={emailStats.pending || 0} icon={Clock} color="yellow" />
            </div>
          )}

          {/* Sub-tabs */}
          <Tabs value={emailSubTab} onValueChange={setEmailSubTab}>
            <TabsList className="bg-zinc-800/50">
              <TabsTrigger value="templates">Templates</TabsTrigger>
              <TabsTrigger value="rules">Automation Rules</TabsTrigger>
              <TabsTrigger value="broadcast">Broadcast</TabsTrigger>
              <TabsTrigger value="logs">Logs</TabsTrigger>
            </TabsList>

            {/* Templates */}
            <TabsContent value="templates" className="mt-4">
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg">Email Templates</CardTitle>
                  <CardDescription>Manage automated email templates</CardDescription>
                </CardHeader>
                <CardContent>
                  {emailLoading ? (
                    <div className="space-y-2">
                      {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-16" />)}
                    </div>
                  ) : emailTemplates.length === 0 ? (
                    <p className="text-zinc-500 text-center py-4">No templates configured</p>
                  ) : (
                    <div className="space-y-3">
                      {emailTemplates.map((template) => (
                        <div key={template.key || template.id} className="p-4 rounded-lg bg-zinc-800/50 flex items-center justify-between">
                          <div>
                            <p className="font-medium text-white">{template.name}</p>
                            <p className="text-xs text-zinc-500">{template.subject}</p>
                          </div>
                          <div className="flex gap-2">
                            <Button size="sm" variant="outline" onClick={() => setEditingTemplate(template)}>
                              Edit
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => handleTestEmail(template.key || template.id, testEmailAddress || 'test@example.com')}>
                              Test
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* Automation Rules */}
            <TabsContent value="rules" className="mt-4">
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg">Automation Rules</CardTitle>
                  <CardDescription>Configure when emails are automatically sent</CardDescription>
                </CardHeader>
                <CardContent>
                  {automationRules.length === 0 ? (
                    <p className="text-zinc-500 text-center py-4">No automation rules configured</p>
                  ) : (
                    <div className="space-y-3">
                      {automationRules.map((rule) => (
                        <div key={rule.id} className="p-4 rounded-lg bg-zinc-800/50 flex items-center justify-between">
                          <div>
                            <p className="font-medium text-white">{rule.name}</p>
                            <p className="text-xs text-zinc-500">Trigger: {rule.trigger_type} → Template: {rule.template_key}</p>
                          </div>
                          <Switch
                            checked={rule.enabled}
                            onCheckedChange={(enabled) => handleToggleRule(rule.id, enabled)}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* Broadcast */}
            <TabsContent value="broadcast" className="mt-4">
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg">Send Broadcast</CardTitle>
                  <CardDescription>Send an announcement to all active users</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <Label>Announcement Title</Label>
                    <Input
                      value={broadcastData.announcement_title}
                      onChange={(e) => setBroadcastData(d => ({ ...d, announcement_title: e.target.value }))}
                      className="input-dark mt-1"
                      placeholder="New Feature Announcement"
                    />
                  </div>
                  <div>
                    <Label>Content</Label>
                    <textarea
                      value={broadcastData.announcement_content}
                      onChange={(e) => setBroadcastData(d => ({ ...d, announcement_content: e.target.value }))}
                      className="w-full h-32 mt-1 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700 text-white resize-none focus:outline-none focus:border-emerald-500"
                      placeholder="We're excited to announce..."
                    />
                  </div>
                  <Button onClick={handleSendBroadcast} disabled={sendingBroadcast} className="bg-violet-600 hover:bg-violet-700">
                    {sendingBroadcast ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Mail className="w-4 h-4 mr-2" />}
                    Send Broadcast
                  </Button>
                </CardContent>
              </Card>
            </TabsContent>

            {/* Logs */}
            <TabsContent value="logs" className="mt-4">
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg">Email Logs</CardTitle>
                  <CardDescription>Recent email activity</CardDescription>
                </CardHeader>
                <CardContent>
                  {emailLogs.length === 0 ? (
                    <p className="text-zinc-500 text-center py-4">No email logs yet</p>
                  ) : (
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {emailLogs.map((log, idx) => (
                        <div key={idx} className="p-3 rounded-lg bg-zinc-800/50 flex items-center justify-between">
                          <div>
                            <p className="text-sm text-white">{log.recipient}</p>
                            <p className="text-xs text-zinc-500">{log.template} • {new Date(log.sent_at).toLocaleString()}</p>
                          </div>
                          <Badge className={log.status === 'delivered' ? 'bg-emerald-500/20 text-emerald-400' : log.status === 'failed' ? 'bg-red-500/20 text-red-400' : 'bg-yellow-500/20 text-yellow-400'}>
                            {log.status}
                          </Badge>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          {/* Template Editor Modal */}
          {editingTemplate && (
            <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
              <div className="bg-zinc-900 rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto">
                <div className="p-4 border-b border-zinc-800">
                  <h3 className="text-lg font-medium text-white">Edit Template: {editingTemplate.name}</h3>
                </div>
                <div className="p-4 space-y-4">
                  <div>
                    <Label className="text-zinc-400">Template Name</Label>
                    <Input
                      value={editingTemplate.name}
                      onChange={(e) => setEditingTemplate({ ...editingTemplate, name: e.target.value })}
                      className="input-dark mt-2"
                    />
                  </div>
                  <div>
                    <Label className="text-zinc-400">Subject Line</Label>
                    <Input
                      value={editingTemplate.subject}
                      onChange={(e) => setEditingTemplate({ ...editingTemplate, subject: e.target.value })}
                      className="input-dark mt-2"
                    />
                  </div>
                  <div>
                    <Label className="text-zinc-400">HTML Content</Label>
                    <textarea
                      value={editingTemplate.html}
                      onChange={(e) => setEditingTemplate({ ...editingTemplate, html: e.target.value })}
                      className="w-full h-60 mt-2 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700 text-white font-mono text-sm resize-none focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                </div>
                <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setEditingTemplate(null)}>Cancel</Button>
                  <Button
                    onClick={() => handleUpdateTemplate(editingTemplate.key || editingTemplate.id, {
                      name: editingTemplate.name,
                      subject: editingTemplate.subject,
                      html: editingTemplate.html
                    })}
                    className="bg-emerald-600 hover:bg-emerald-700"
                  >
                    <Save className="w-4 h-4 mr-2" />
                    Save Changes
                  </Button>
                </div>
              </div>
            </div>
          )}
        </TabsContent>

        {/* Subscriptions Tab */}
        <TabsContent value="subscriptions" className="space-y-6 mt-6">
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-emerald-400" />
                Payment Link Management
              </CardTitle>
              <CardDescription>Manage Stripe payment links for subscription plans</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Mode Toggle */}
              <div className="flex items-center justify-between p-4 rounded-lg bg-zinc-800/50 border border-zinc-700">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${subscriptionSettings.active_mode === 'live' ? 'bg-emerald-500/20' : 'bg-yellow-500/20'}`}>
                    {subscriptionSettings.active_mode === 'live' ? (
                      <Zap className="w-5 h-5 text-emerald-400" />
                    ) : (
                      <TestTube className="w-5 h-5 text-yellow-400" />
                    )}
                  </div>
                  <div>
                    <div className="font-medium text-white">
                      Current Mode: <span className={subscriptionSettings.active_mode === 'live' ? 'text-emerald-400' : 'text-yellow-400'}>
                        {subscriptionSettings.active_mode?.toUpperCase()}
                      </span>
                    </div>
                    <p className="text-xs text-zinc-500">
                      {subscriptionSettings.active_mode === 'live'
                        ? 'Production payment links are active'
                        : 'Test payment links are active (no real charges)'}
                    </p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant={subscriptionSettings.active_mode === 'test' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => switchSubscriptionMode('test')}
                    className={subscriptionSettings.active_mode === 'test' ? 'bg-yellow-600 hover:bg-yellow-700' : ''}
                  >
                    <TestTube className="w-4 h-4 mr-1" />
                    Test
                  </Button>
                  <Button
                    variant={subscriptionSettings.active_mode === 'live' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => switchSubscriptionMode('live')}
                    className={subscriptionSettings.active_mode === 'live' ? 'bg-emerald-600 hover:bg-emerald-700' : ''}
                  >
                    <Zap className="w-4 h-4 mr-1" />
                    Live
                  </Button>
                </div>
              </div>

              {/* Payment Links */}
              <Tabs defaultValue="test" className="w-full">
                <TabsList className="grid w-full grid-cols-2 bg-zinc-800/50">
                  <TabsTrigger value="test"><TestTube className="w-4 h-4 mr-2" />Test Links</TabsTrigger>
                  <TabsTrigger value="live"><Zap className="w-4 h-4 mr-2" />Live Links</TabsTrigger>
                </TabsList>

                <TabsContent value="test" className="space-y-4 mt-4">
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label className="text-zinc-400">7-Day FREE Trial Link</Label>
                      <Input
                        value={subscriptionSettings.test_links?.trial || ''}
                        onChange={(e) => setSubscriptionSettings(prev => ({
                          ...prev,
                          test_links: { ...prev.test_links, trial: e.target.value }
                        }))}
                        placeholder="https://buy.stripe.com/test_..."
                        className="input-dark font-mono text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-zinc-400">Monthly Subscription Link ($49)</Label>
                      <Input
                        value={subscriptionSettings.test_links?.monthly || ''}
                        onChange={(e) => setSubscriptionSettings(prev => ({
                          ...prev,
                          test_links: { ...prev.test_links, monthly: e.target.value }
                        }))}
                        placeholder="https://buy.stripe.com/test_..."
                        className="input-dark font-mono text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-zinc-400">Annual Subscription Link ($499)</Label>
                      <Input
                        value={subscriptionSettings.test_links?.yearly || ''}
                        onChange={(e) => setSubscriptionSettings(prev => ({
                          ...prev,
                          test_links: { ...prev.test_links, yearly: e.target.value }
                        }))}
                        placeholder="https://buy.stripe.com/test_..."
                        className="input-dark font-mono text-sm"
                      />
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="live" className="space-y-4 mt-4">
                  <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 mb-4">
                    <p className="text-xs text-emerald-400">
                      ⚠️ Live links process real payments. Test thoroughly before switching to live mode.
                    </p>
                  </div>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label className="text-zinc-400">7-Day FREE Trial Link</Label>
                      <Input
                        value={subscriptionSettings.live_links?.trial || ''}
                        onChange={(e) => setSubscriptionSettings(prev => ({
                          ...prev,
                          live_links: { ...prev.live_links, trial: e.target.value }
                        }))}
                        placeholder="https://buy.stripe.com/live_..."
                        className="input-dark font-mono text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-zinc-400">Monthly Subscription Link ($49)</Label>
                      <Input
                        value={subscriptionSettings.live_links?.monthly || ''}
                        onChange={(e) => setSubscriptionSettings(prev => ({
                          ...prev,
                          live_links: { ...prev.live_links, monthly: e.target.value }
                        }))}
                        placeholder="https://buy.stripe.com/live_..."
                        className="input-dark font-mono text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-zinc-400">Annual Subscription Link ($499)</Label>
                      <Input
                        value={subscriptionSettings.live_links?.yearly || ''}
                        onChange={(e) => setSubscriptionSettings(prev => ({
                          ...prev,
                          live_links: { ...prev.live_links, yearly: e.target.value }
                        }))}
                        placeholder="https://buy.stripe.com/live_..."
                        className="input-dark font-mono text-sm"
                      />
                    </div>
                  </div>
                </TabsContent>
              </Tabs>

              <div className="flex justify-end pt-4 border-t border-zinc-800">
                <Button onClick={saveSubscriptionSettings} className="bg-emerald-600 hover:bg-emerald-700" disabled={savingSubscription}>
                  {savingSubscription ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                  Save Payment Links
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* PayPal Configuration Card */}
          <Card className={`glass-card border-l-4 ${integrationStatus?.paypal?.configured ? 'border-emerald-500' : 'border-yellow-500'}`}>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <DollarSign className="w-5 h-5 text-cyan-400" />
                PayPal Subscription Settings
              </CardTitle>
              <CardDescription>Configure PayPal Express Checkout + Recurring Profiles for subscription payments</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Enabled Toggle */}
              <div className="flex items-center justify-between p-4 rounded-lg bg-zinc-800/50 border border-zinc-700">
                <div>
                  <Label className="text-white">PayPal Payments Enabled</Label>
                  <p className="text-xs text-zinc-500">Allow customers to pay via PayPal</p>
                </div>
                <Switch
                  checked={integrationSettings.paypal_enabled}
                  onCheckedChange={(checked) => setIntegrationSettings(prev => ({ ...prev, paypal_enabled: checked }))}
                />
              </div>

              {/* Mode Toggle */}
              <div className="flex items-center justify-between p-4 rounded-lg bg-zinc-800/50 border border-zinc-700">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${integrationSettings.paypal_mode === 'live' ? 'bg-emerald-500/20' : 'bg-yellow-500/20'}`}>
                    {integrationSettings.paypal_mode === 'live' ? (
                      <Zap className="w-5 h-5 text-emerald-400" />
                    ) : (
                      <TestTube className="w-5 h-5 text-yellow-400" />
                    )}
                  </div>
                  <div>
                    <div className="font-medium text-white">
                      Mode: <span className={integrationSettings.paypal_mode === 'live' ? 'text-emerald-400' : 'text-yellow-400'}>
                        {integrationSettings.paypal_mode?.toUpperCase() || 'SANDBOX'}
                      </span>
                    </div>
                    <p className="text-xs text-zinc-500">
                      {integrationSettings.paypal_mode === 'live'
                        ? 'Production PayPal endpoint'
                        : 'Sandbox PayPal endpoint (no real charges)'}
                    </p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant={integrationSettings.paypal_mode === 'sandbox' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setIntegrationSettings(prev => ({ ...prev, paypal_mode: 'sandbox' }))}
                    className={integrationSettings.paypal_mode === 'sandbox' ? 'bg-yellow-600 hover:bg-yellow-700' : ''}
                  >
                    <TestTube className="w-4 h-4 mr-1" />
                    Sandbox
                  </Button>
                  <Button
                    variant={integrationSettings.paypal_mode === 'live' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setIntegrationSettings(prev => ({ ...prev, paypal_mode: 'live' }))}
                    className={integrationSettings.paypal_mode === 'live' ? 'bg-emerald-600 hover:bg-emerald-700' : ''}
                  >
                    <Zap className="w-4 h-4 mr-1" />
                    Live
                  </Button>
                </div>
              </div>

              {/* API Credentials */}
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="paypal_api_username">API Username</Label>
                  <Input
                    id="paypal_api_username"
                    type="text"
                    value={integrationSettings.paypal_api_username}
                    onChange={(e) => setIntegrationSettings(prev => ({ ...prev, paypal_api_username: e.target.value }))}
                    placeholder={integrationStatus?.paypal?.api_username_masked || "sb-xxxxx_api1.business.example.com"}
                    className="bg-zinc-800 border-zinc-700"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="paypal_api_password">API Password</Label>
                  <div className="relative">
                    <Input
                      id="paypal_api_password"
                      type={showPayPalPassword ? 'text' : 'password'}
                      value={integrationSettings.paypal_api_password}
                      onChange={(e) => setIntegrationSettings(prev => ({ ...prev, paypal_api_password: e.target.value }))}
                      placeholder={integrationStatus?.paypal?.has_api_password ? '••••••••' : 'Enter API password'}
                      className="bg-zinc-800 border-zinc-700 pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPayPalPassword(!showPayPalPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white"
                    >
                      {showPayPalPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="paypal_api_signature">API Signature</Label>
                  <div className="relative">
                    <Input
                      id="paypal_api_signature"
                      type={showPayPalSignature ? 'text' : 'password'}
                      value={integrationSettings.paypal_api_signature}
                      onChange={(e) => setIntegrationSettings(prev => ({ ...prev, paypal_api_signature: e.target.value }))}
                      placeholder={integrationStatus?.paypal?.has_api_signature ? '••••••••' : 'Enter API signature'}
                      className="bg-zinc-800 border-zinc-700 pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPayPalSignature(!showPayPalSignature)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white"
                    >
                      {showPayPalSignature ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
              </div>

              {/* IPN URL Info */}
              <div className="p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                <p className="text-xs text-cyan-400 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" />
                  Set your PayPal IPN URL to: <code className="bg-zinc-800 px-1 rounded">{window.location.origin}/api/paypal/ipn</code>
                </p>
              </div>

              <div className="flex justify-end">
                <Button onClick={saveIntegrationSettings} className="bg-cyan-600 hover:bg-cyan-700" disabled={savingIntegration}>
                  {savingIntegration ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                  Save PayPal Settings
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Integrations Tab */}
        <TabsContent value="integrations" className="space-y-6 mt-6">
          {/* Integration Status */}
          <div className="grid md:grid-cols-2 gap-4">
            <Card className={`glass-card border-l-4 ${integrationStatus?.stripe?.webhook_secret_configured ? 'border-emerald-500' : 'border-yellow-500'}`}>
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  {integrationStatus?.stripe?.webhook_secret_configured ? (
                    <CheckCircle className="w-8 h-8 text-emerald-400" />
                  ) : (
                    <XCircle className="w-8 h-8 text-yellow-400" />
                  )}
                  <div>
                    <p className="font-medium text-white">Stripe Webhooks</p>
                    <p className="text-xs text-zinc-500">
                      {integrationStatus?.stripe?.webhook_secret_configured ? 'Configured' : 'Not configured'}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className={`glass-card border-l-4 ${integrationStatus?.email?.resend_api_key_configured ? 'border-emerald-500' : 'border-yellow-500'}`}>
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  {integrationStatus?.email?.resend_api_key_configured ? (
                    <CheckCircle className="w-8 h-8 text-emerald-400" />
                  ) : (
                    <XCircle className="w-8 h-8 text-yellow-400" />
                  )}
                  <div>
                    <p className="font-medium text-white">Resend Email</p>
                    <p className="text-xs text-zinc-500">
                      {integrationStatus?.email?.resend_api_key_configured ? 'Configured' : 'Not configured'}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className={`glass-card border-l-4 ${integrationStatus?.paypal?.configured ? 'border-emerald-500' : 'border-yellow-500'}`}>
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  {integrationStatus?.paypal?.configured ? (
                    <CheckCircle className="w-8 h-8 text-emerald-400" />
                  ) : (
                    <XCircle className="w-8 h-8 text-yellow-400" />
                  )}
                  <div>
                    <p className="font-medium text-white">PayPal Subscriptions</p>
                    <p className="text-xs text-zinc-500">
                      {integrationStatus?.paypal?.configured ? 'Configured' : 'Not configured'}
                      {integrationStatus?.paypal?.mode ? ` • ${integrationStatus.paypal.mode.toUpperCase()}` : ''}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Stripe Settings */}
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-violet-400" />
                Stripe Configuration
              </CardTitle>
              <CardDescription>Configure Stripe webhook for subscription automation</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <PasswordInput
                label="Stripe Webhook Secret"
                value={integrationSettings.stripe_webhook_secret}
                onChange={(v) => setIntegrationSettings(s => ({ ...s, stripe_webhook_secret: v }))}
                show={showStripeWebhook}
                onToggle={() => setShowStripeWebhook(!showStripeWebhook)}
                placeholder="whsec_..."
              />
              <p className="text-xs text-zinc-500">
                Get this from Stripe Dashboard → Developers → Webhooks → Add endpoint → Signing secret
              </p>
              <PasswordInput
                label="Stripe Secret Key (Optional)"
                value={integrationSettings.stripe_secret_key}
                onChange={(v) => setIntegrationSettings(s => ({ ...s, stripe_secret_key: v }))}
                show={showStripeSecret}
                onToggle={() => setShowStripeSecret(!showStripeSecret)}
                placeholder="sk_live_... or sk_test_..."
              />
            </CardContent>
          </Card>

          {/* Email Settings */}
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Mail className="w-5 h-5 text-cyan-400" />
                Email Configuration (Resend)
              </CardTitle>
              <CardDescription>Configure email service for automated notifications</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <PasswordInput
                label="Resend API Key"
                value={integrationSettings.resend_api_key}
                onChange={(v) => setIntegrationSettings(s => ({ ...s, resend_api_key: v }))}
                show={showResendKey}
                onToggle={() => setShowResendKey(!showResendKey)}
                placeholder="re_..."
              />
              <div className="space-y-2">
                <Label className="text-zinc-400">Sender Email</Label>
                <Input
                  value={integrationSettings.sender_email}
                  onChange={(e) => setIntegrationSettings(s => ({ ...s, sender_email: e.target.value }))}
                  placeholder="noreply@coveredcallengine.com"
                  className="input-dark"
                />
              </div>
              <p className="text-xs text-zinc-500">
                Get your API key from <a href="https://resend.com" target="_blank" rel="noopener noreferrer" className="text-cyan-400 hover:underline">resend.com</a>
              </p>

              {/* Test Email Section */}
              <div className="mt-4 pt-4 border-t border-zinc-700">
                <Label className="text-zinc-400 mb-2 block">Send Test Email</Label>
                <div className="flex gap-2">
                  <Input
                    value={testEmailAddress}
                    onChange={(e) => setTestEmailAddress(e.target.value)}
                    placeholder="your-email@example.com"
                    className="input-dark flex-1"
                    type="email"
                  />
                  <Button
                    onClick={sendTestEmail}
                    disabled={sendingTestEmail || !testEmailAddress}
                    className="bg-cyan-600 hover:bg-cyan-700"
                  >
                    {sendingTestEmail ? (
                      <RefreshCw className="w-4 h-4 animate-spin" />
                    ) : (
                      <Mail className="w-4 h-4" />
                    )}
                    <span className="ml-2">Test</span>
                  </Button>
                </div>
                <p className="text-xs text-zinc-500 mt-2">
                  ⚠️ In Resend test mode, emails can only be sent to your verified email address
                </p>
              </div>
            </CardContent>
          </Card>

          <div className="flex justify-end">
            <Button onClick={saveIntegrationSettings} className="bg-emerald-600 hover:bg-emerald-700" disabled={savingIntegration}>
              {savingIntegration ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Save Integration Settings
            </Button>
          </div>
        </TabsContent>

        {/* IMAP Email Sync Tab */}
        <TabsContent value="imap" className="space-y-6 mt-6">
          {/* Status Cards */}
          <div className="grid md:grid-cols-3 gap-4">
            <Card className={`glass-card border-l-4 ${imapStatus?.configured ? 'border-emerald-500' : 'border-yellow-500'}`}>
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  {imapStatus?.configured ? (
                    <CheckCircle className="w-8 h-8 text-emerald-400" />
                  ) : (
                    <AlertCircle className="w-8 h-8 text-yellow-400" />
                  )}
                  <div>
                    <p className="font-medium text-white">IMAP Connection</p>
                    <p className="text-xs text-zinc-500">
                      {imapStatus?.configured ? 'Configured' : 'Not configured'}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className={`glass-card border-l-4 ${imapStatus?.last_sync_success ? 'border-emerald-500' : imapStatus?.last_sync_error ? 'border-red-500' : 'border-zinc-600'}`}>
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  {imapStatus?.last_sync_success ? (
                    <CheckCircle className="w-8 h-8 text-emerald-400" />
                  ) : imapStatus?.last_sync_error ? (
                    <XCircle className="w-8 h-8 text-red-400" />
                  ) : (
                    <Clock className="w-8 h-8 text-zinc-400" />
                  )}
                  <div>
                    <p className="font-medium text-white">Last Sync</p>
                    <p className="text-xs text-zinc-500">
                      {imapStatus?.last_sync
                        ? new Date(imapStatus.last_sync).toLocaleString()
                        : 'Never synced'}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="glass-card border-l-4 border-violet-500">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <Mail className="w-8 h-8 text-violet-400" />
                  <div>
                    <p className="font-medium text-white">Emails Processed</p>
                    <p className="text-xs text-zinc-500">
                      {imapStatus?.last_sync_processed ?? 0} in last sync
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Error Alert */}
          {imapStatus?.last_sync_error && (
            <Card className="glass-card border-red-500/50 bg-red-500/5">
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-red-400 mt-0.5" />
                  <div>
                    <p className="font-medium text-red-400">Sync Error</p>
                    <p className="text-sm text-zinc-400 mt-1">{imapStatus.last_sync_error}</p>
                    {imapStatus.last_sync_error.includes('authentication') && (
                      <p className="text-xs text-yellow-400 mt-2">
                        Please update your IMAP password below if you changed it in Hostinger.
                      </p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* IMAP Settings */}
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Settings className="w-5 h-5 text-emerald-400" />
                IMAP Email Settings
              </CardTitle>
              <CardDescription>
                Configure connection to your Hostinger mailbox for automatic email sync. Syncs run automatically every 6 hours.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid md:grid-cols-2 gap-4">
                <div className="form-group">
                  <Label className="form-label">IMAP Server</Label>
                  <Input
                    value={imapSettings.imap_server}
                    onChange={(e) => setImapSettings(prev => ({ ...prev, imap_server: e.target.value }))}
                    placeholder="imap.hostinger.com"
                    className="input-dark"
                  />
                </div>
                <div className="form-group">
                  <Label className="form-label">Port</Label>
                  <Input
                    type="number"
                    value={imapSettings.imap_port}
                    onChange={(e) => setImapSettings(prev => ({ ...prev, imap_port: parseInt(e.target.value) || 993 }))}
                    placeholder="993"
                    className="input-dark"
                  />
                </div>
              </div>
              <div className="grid md:grid-cols-2 gap-4">
                <div className="form-group">
                  <Label className="form-label">Email Address (Username)</Label>
                  <Input
                    value={imapSettings.username}
                    onChange={(e) => setImapSettings(prev => ({ ...prev, username: e.target.value }))}
                    placeholder="support@coveredcallengine.com"
                    className="input-dark"
                  />
                </div>
                <div className="form-group">
                  <Label className="form-label">Password</Label>
                  <div className="relative">
                    <Input
                      type={showImapPassword ? 'text' : 'password'}
                      value={imapSettings.password}
                      onChange={(e) => setImapSettings(prev => ({ ...prev, password: e.target.value }))}
                      placeholder="Enter new password to update"
                      className="input-dark pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowImapPassword(!showImapPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                    >
                      {showImapPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <p className="text-xs text-zinc-500 mt-1">Leave blank to keep existing password</p>
                </div>
              </div>

              <div className="flex gap-3">
                <Button onClick={testImapConnection} variant="outline" className="border-zinc-700">
                  <Activity className="w-4 h-4 mr-2" />
                  Test Connection
                </Button>
                <Button onClick={saveImapSettings} className="bg-emerald-600 hover:bg-emerald-700" disabled={imapSaving}>
                  {imapSaving ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                  Save Settings
                </Button>
                <Button onClick={syncImapNow} variant="outline" className="border-violet-500 text-violet-400 hover:bg-violet-500/10" disabled={imapSyncing}>
                  {imapSyncing ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
                  Sync Now
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Sync History */}
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Clock className="w-5 h-5 text-violet-400" />
                Sync History
              </CardTitle>
              <CardDescription>
                Recent email sync attempts and results
              </CardDescription>
            </CardHeader>
            <CardContent>
              {imapHistory.length === 0 ? (
                <p className="text-sm text-zinc-500 text-center py-4">No sync history yet</p>
              ) : (
                <div className="space-y-2">
                  {imapHistory.map((log, idx) => (
                    <div key={idx} className={`flex items-center justify-between p-3 rounded-lg ${log.success ? 'bg-emerald-500/5' : 'bg-red-500/5'}`}>
                      <div className="flex items-center gap-3">
                        {log.success ? (
                          <CheckCircle className="w-5 h-5 text-emerald-400" />
                        ) : (
                          <XCircle className="w-5 h-5 text-red-400" />
                        )}
                        <div>
                          <p className="text-sm text-white">
                            {log.emails_processed} emails processed
                            {log.matched_to_tickets > 0 && `, ${log.matched_to_tickets} matched`}
                            {log.new_tickets_created > 0 && `, ${log.new_tickets_created} new tickets`}
                          </p>
                          <p className="text-xs text-zinc-500">
                            {new Date(log.timestamp).toLocaleString()}
                          </p>
                        </div>
                      </div>
                      {log.error && (
                        <span className="text-xs text-red-400 max-w-xs truncate">{log.error}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* API Keys Tab */}
        <TabsContent value="api-keys" className="space-y-6 mt-6">
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Database className="w-5 h-5 text-emerald-400" />
                Data Provider API Keys
              </CardTitle>
              <CardDescription>Configure API credentials for market data providers</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Massive.com */}
              <div className="p-4 rounded-lg bg-zinc-800/50 space-y-4">
                <h4 className="font-medium text-white flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-violet-400" />
                  Massive.com (Market Data)
                </h4>
                <PasswordInput
                  label="API Key"
                  value={settings.massive_api_key}
                  onChange={(v) => setSettings(s => ({ ...s, massive_api_key: v }))}
                  show={showMassiveApiKey}
                  onToggle={() => setShowMassiveApiKey(!showMassiveApiKey)}
                  placeholder="Your Massive.com API Key"
                />
                <PasswordInput
                  label="Access ID"
                  value={settings.massive_access_id}
                  onChange={(v) => setSettings(s => ({ ...s, massive_access_id: v }))}
                  show={showMassiveAccessId}
                  onToggle={() => setShowMassiveAccessId(!showMassiveAccessId)}
                  placeholder="Your Access ID"
                />
                <PasswordInput
                  label="Secret Key"
                  value={settings.massive_secret_key}
                  onChange={(v) => setSettings(s => ({ ...s, massive_secret_key: v }))}
                  show={showMassiveSecretKey}
                  onToggle={() => setShowMassiveSecretKey(!showMassiveSecretKey)}
                  placeholder="Your Secret Key"
                />
              </div>

              {/* MarketAux */}
              <div className="p-4 rounded-lg bg-zinc-800/50 space-y-4">
                <h4 className="font-medium text-white flex items-center gap-2">
                  <Newspaper className="w-4 h-4 text-cyan-400" />
                  MarketAux (News)
                </h4>
                <PasswordInput
                  label="API Token"
                  value={settings.marketaux_api_token}
                  onChange={(v) => setSettings(s => ({ ...s, marketaux_api_token: v }))}
                  show={showMarketauxToken}
                  onToggle={() => setShowMarketauxToken(!showMarketauxToken)}
                  placeholder="Your MarketAux API Token"
                />
              </div>

              {/* OpenAI */}
              <div className="p-4 rounded-lg bg-zinc-800/50 space-y-4">
                <h4 className="font-medium text-white flex items-center gap-2">
                  <Brain className="w-4 h-4 text-emerald-400" />
                  OpenAI (AI Insights)
                </h4>
                <PasswordInput
                  label="API Key"
                  value={settings.openai_api_key}
                  onChange={(v) => setSettings(s => ({ ...s, openai_api_key: v }))}
                  show={showOpenAIKey}
                  onToggle={() => setShowOpenAIKey(!showOpenAIKey)}
                  placeholder="sk-..."
                />
              </div>

              <div className="flex justify-end pt-4 border-t border-zinc-800">
                <Button onClick={saveSettings} className="bg-emerald-600 hover:bg-emerald-700" disabled={saving}>
                  {saving ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                  Save API Keys
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Exclusion Drilldown Modal */}
      {exclusionDrilldown.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl w-full max-w-4xl max-h-[80vh] flex flex-col mx-4">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-4 border-b border-zinc-700">
              <div>
                <h3 className="text-lg font-semibold text-white">
                  Excluded Symbols: {exclusionDrilldown.reason?.replace(/_/g, ' ') || 'All'}
                </h3>
                <p className="text-sm text-zinc-400">
                  Showing {exclusionDrilldown.data.length} of {exclusionDrilldown.total} symbols
                  {currentRunId && <span className="ml-2 font-mono text-xs">• Run: {currentRunId}</span>}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={getExclusionCsvUrl(exclusionDrilldown.reason)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-colors"
                >
                  <Download className="w-4 h-4" />
                  CSV
                </a>
                <button
                  onClick={() => setExclusionDrilldown(prev => ({ ...prev, open: false }))}
                  className="p-2 rounded-lg hover:bg-zinc-700 text-zinc-400 hover:text-white"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-auto p-4">
              {exclusionDrilldown.loading ? (
                <div className="flex items-center justify-center py-12">
                  <RefreshCw className="w-8 h-8 text-zinc-500 animate-spin" />
                </div>
              ) : exclusionDrilldown.data.length > 0 ? (
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-zinc-900">
                    <tr className="border-b border-zinc-700">
                      <th className="text-left py-2 px-3 text-zinc-400 font-medium">Symbol</th>
                      <th className="text-right py-2 px-3 text-zinc-400 font-medium">Price</th>
                      <th className="text-right py-2 px-3 text-zinc-400 font-medium">Avg Volume</th>
                      <th className="text-right py-2 px-3 text-zinc-400 font-medium">$ Volume</th>
                      <th className="text-left py-2 px-3 text-zinc-400 font-medium">Stage</th>
                      <th className="text-left py-2 px-3 text-zinc-400 font-medium">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {exclusionDrilldown.data.map((item, idx) => (
                      <tr key={`${item.symbol}-${idx}`} className="border-b border-zinc-800 hover:bg-zinc-800/50">
                        <td className="py-2 px-3 font-mono text-cyan-400">{item.symbol || 'N/A'}</td>
                        <td className="py-2 px-3 text-right text-white">
                          {item.price_used ? `$${Number(item.price_used).toFixed(2)}` : 'N/A'}
                        </td>
                        <td className="py-2 px-3 text-right text-zinc-400">
                          {item.avg_volume ? Number(item.avg_volume).toLocaleString() : 'N/A'}
                        </td>
                        <td className="py-2 px-3 text-right text-zinc-400">
                          {item.dollar_volume ? `$${(Number(item.dollar_volume) / 1e6).toFixed(1)}M` : 'N/A'}
                        </td>
                        <td className="py-2 px-3">
                          <Badge variant="outline" className="text-xs">
                            {item.exclude_stage || 'N/A'}
                          </Badge>
                        </td>
                        <td className="py-2 px-3 text-zinc-500 text-xs max-w-[200px] truncate" title={item.exclude_detail}>
                          {item.exclude_detail || 'N/A'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
                  <CheckCircle className="w-12 h-12 mb-4 text-zinc-600" />
                  <p>No excluded symbols found</p>
                </div>
              )}
            </div>

            {/* Modal Footer - Pagination */}
            {exclusionDrilldown.total > 100 && (
              <div className="flex items-center justify-between p-4 border-t border-zinc-700">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchExclusionDrilldown(exclusionDrilldown.reason, Math.max(0, exclusionDrilldown.offset - 100))}
                  disabled={exclusionDrilldown.offset === 0 || exclusionDrilldown.loading}
                >
                  <ChevronLeft className="w-4 h-4 mr-1" />
                  Prev
                </Button>
                <span className="text-sm text-zinc-400">
                  Page {Math.floor(exclusionDrilldown.offset / 100) + 1} of {Math.ceil(exclusionDrilldown.total / 100)}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchExclusionDrilldown(exclusionDrilldown.reason, exclusionDrilldown.offset + 100)}
                  disabled={exclusionDrilldown.offset + 100 >= exclusionDrilldown.total || exclusionDrilldown.loading}
                >
                  Next
                  <ChevronRight className="w-4 h-4 ml-1" />
                </Button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default Admin;
