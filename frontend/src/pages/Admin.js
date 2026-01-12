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
  Trash2
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
    sender_email: ''
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

  useEffect(() => {
    fetchSettings();
    fetchDashboardStats();
    fetchSubscriptionSettings();
    fetchIntegrationSettings();
  }, []);

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
        <TabsList className="grid w-full grid-cols-7 bg-zinc-800/50 p-1">
          <TabsTrigger value="dashboard" className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            Dashboard
          </TabsTrigger>
          <TabsTrigger value="users" className="flex items-center gap-2" onClick={() => { fetchUsers(1); fetchInvitations(); }}>
            <Users className="w-4 h-4" />
            Users
          </TabsTrigger>
          <TabsTrigger value="support" className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4" />
            Support
          </TabsTrigger>
          <TabsTrigger value="email-automation" className="flex items-center gap-2" onClick={() => { fetchEmailTemplates(); fetchAutomationRules(); fetchEmailLogs(); fetchEmailStats(); }}>
            <Mail className="w-4 h-4" />
            Email
          </TabsTrigger>
          <TabsTrigger value="subscriptions" className="flex items-center gap-2">
            <CreditCard className="w-4 h-4" />
            Billing
          </TabsTrigger>
          <TabsTrigger value="integrations" className="flex items-center gap-2">
            <Zap className="w-4 h-4" />
            Integrations
          </TabsTrigger>
          <TabsTrigger value="imap" className="flex items-center gap-2" onClick={() => fetchImapStatus()}>
            <Mail className="w-4 h-4" />
            Email Sync
          </TabsTrigger>
          <TabsTrigger value="api-keys" className="flex items-center gap-2">
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

        {/* Users Tab */}
        <TabsContent value="users" className="space-y-6 mt-6">
          <Card className="glass-card">
            <CardHeader>
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Users className="w-5 h-5 text-violet-400" />
                  User Management
                </CardTitle>
                <div className="flex flex-wrap gap-2">
                  <div className="relative">
                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                    <Input
                      placeholder="Search email..."
                      value={userFilters.search}
                      onChange={(e) => setUserFilters(f => ({ ...f, search: e.target.value }))}
                      className="input-dark pl-9 w-48"
                    />
                  </div>
                  <Select value={userFilters.status} onValueChange={(v) => setUserFilters(f => ({ ...f, status: v }))}>
                    <SelectTrigger className="w-32 bg-zinc-800 border-zinc-700">
                      <SelectValue placeholder="Status" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Status</SelectItem>
                      <SelectItem value="active">Active</SelectItem>
                      <SelectItem value="trialing">Trial</SelectItem>
                      <SelectItem value="cancelled">Cancelled</SelectItem>
                      <SelectItem value="past_due">Past Due</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button onClick={() => fetchUsers(1)} className="bg-violet-600 hover:bg-violet-700">
                    <Search className="w-4 h-4 mr-2" />
                    Search
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {usersLoading ? (
                <div className="space-y-2">
                  {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
                </div>
              ) : users.length === 0 ? (
                <div className="text-center py-8 text-zinc-500">
                  <Users className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>No users found</p>
                </div>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Email</th>
                          <th>Name</th>
                          <th>Plan</th>
                          <th>Status</th>
                          <th>Created</th>
                          <th>Last Login</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {users.map((user) => (
                          <tr key={user.id}>
                            <td className="font-medium text-white">{user.email}</td>
                            <td>{user.name || '-'}</td>
                            <td>
                              <Badge className={
                                user.subscription?.plan === 'yearly' ? 'bg-amber-500/20 text-amber-400' :
                                user.subscription?.plan === 'monthly' ? 'bg-violet-500/20 text-violet-400' :
                                user.subscription?.plan === 'trial' ? 'bg-blue-500/20 text-blue-400' :
                                'bg-zinc-700/50 text-zinc-500'
                              }>
                                {user.subscription?.plan || 'none'}
                              </Badge>
                            </td>
                            <td>{getStatusBadge(user.subscription?.status)}</td>
                            <td className="text-xs text-zinc-500">
                              {user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}
                            </td>
                            <td className="text-xs text-zinc-500">
                              {user.last_login ? new Date(user.last_login).toLocaleDateString() : 'Never'}
                            </td>
                            <td>
                              <div className="flex gap-1 flex-wrap">
                                {!user.subscription?.status && (
                                  <>
                                    <Button size="sm" variant="outline" className="text-xs px-2 py-1 h-7" onClick={() => setUserSubscription(user.id, 'trialing', 'trial')}>
                                      Start Trial
                                    </Button>
                                    <Button size="sm" variant="outline" className="text-xs px-2 py-1 h-7 text-emerald-400" onClick={() => setUserSubscription(user.id, 'active', 'monthly')}>
                                      Activate
                                    </Button>
                                  </>
                                )}
                                {user.subscription?.status === 'trialing' && (
                                  <Button size="sm" variant="outline" className="text-xs px-2 py-1 h-7" onClick={() => extendUserTrial(user.id, 7)}>
                                    +7 days
                                  </Button>
                                )}
                                {user.subscription?.status === 'active' && (
                                  <Button size="sm" variant="outline" className="text-xs px-2 py-1 h-7 text-red-400" onClick={() => setUserSubscription(user.id, 'cancelled', user.subscription?.plan)}>
                                    Cancel
                                  </Button>
                                )}
                                {user.subscription?.status === 'cancelled' && (
                                  <Button size="sm" variant="outline" className="text-xs px-2 py-1 h-7 text-emerald-400" onClick={() => setUserSubscription(user.id, 'active', user.subscription?.plan || 'monthly')}>
                                    Reactivate
                                  </Button>
                                )}
                                {!user.is_admin && (
                                  <Button 
                                    size="sm" 
                                    variant="ghost" 
                                    className="text-xs px-2 py-1 h-7 text-red-400 hover:text-red-300 hover:bg-red-500/10" 
                                    onClick={() => deleteUser(user.id, user.email)}
                                    title="Delete user"
                                  >
                                    <Trash2 className="w-3 h-3" />
                                  </Button>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  
                  {/* Pagination */}
                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-800">
                    <span className="text-sm text-zinc-500">
                      Showing {users.length} of {usersPagination.total} users
                    </span>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fetchUsers(usersPagination.page - 1)}
                        disabled={usersPagination.page <= 1}
                      >
                        <ChevronLeft className="w-4 h-4" />
                      </Button>
                      <span className="px-3 py-1 text-sm text-zinc-400">
                        Page {usersPagination.page} of {usersPagination.pages}
                      </span>
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
                </>
              )}
            </CardContent>
          </Card>

          {/* Invitations Section */}
          <Card className="glass-card">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Mail className="w-5 h-5 text-emerald-400" />
                    Invitations
                  </CardTitle>
                  <CardDescription>Invite support staff and testers</CardDescription>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={fetchInvitations}>
                    <RefreshCw className="w-4 h-4" />
                  </Button>
                  <Button onClick={() => setShowInviteModal(true)} className="bg-emerald-600 hover:bg-emerald-700">
                    <Mail className="w-4 h-4 mr-2" />
                    Send Invite
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {invitationsLoading ? (
                <div className="space-y-2">
                  {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
                </div>
              ) : invitations.length === 0 ? (
                <div className="text-center py-8 text-zinc-500">
                  <Mail className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>No invitations sent yet</p>
                  <Button onClick={() => setShowInviteModal(true)} className="mt-4" variant="outline">
                    Send First Invite
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  {invitations.map(inv => (
                    <div key={inv.id} className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50 border border-zinc-700">
                      <div className="flex items-center gap-4">
                        <div>
                          <p className="text-white font-medium">{inv.name}</p>
                          <p className="text-sm text-zinc-400">{inv.email}</p>
                        </div>
                        <Badge className={inv.role === 'support_staff' ? 'bg-violet-500/20 text-violet-400' : 'bg-cyan-500/20 text-cyan-400'}>
                          {inv.role === 'support_staff' ? 'Support Staff' : 'Tester'}
                        </Badge>
                        <Badge className={inv.environment === 'test' ? 'bg-amber-500/20 text-amber-400' : 'bg-emerald-500/20 text-emerald-400'}>
                          {inv.environment === 'test' ? '🧪 Test' : '🚀 Prod'}
                        </Badge>
                        <Badge className={
                          inv.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
                          inv.status === 'accepted' ? 'bg-emerald-500/20 text-emerald-400' :
                          'bg-red-500/20 text-red-400'
                        }>
                          {inv.status}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-zinc-500">
                          {new Date(inv.created_at).toLocaleDateString()}
                        </span>
                        {inv.status === 'pending' && (
                          <>
                            <Button size="sm" variant="ghost" onClick={() => resendInvitation(inv.id)} className="text-zinc-400 hover:text-white">
                              Resend
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => revokeInvitation(inv.id)} className="text-red-400 hover:text-red-300">
                              Revoke
                            </Button>
                          </>
                        )}
                        <Button 
                          size="sm" 
                          variant="ghost" 
                          onClick={() => revokeInvitation(inv.id)} 
                          className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
                          title="Delete invitation"
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Invite Modal */}
          {showInviteModal && (
            <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
              <div className="bg-zinc-900 rounded-xl max-w-md w-full">
                <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
                  <h3 className="font-semibold text-white">Send Invitation</h3>
                  <Button variant="ghost" size="sm" onClick={() => setShowInviteModal(false)}>
                    <XCircle className="w-5 h-5" />
                  </Button>
                </div>
                <div className="p-4 space-y-4">
                  <div>
                    <Label className="text-zinc-400">Email</Label>
                    <Input
                      type="email"
                      value={inviteForm.email}
                      onChange={(e) => setInviteForm(f => ({ ...f, email: e.target.value }))}
                      className="input-dark mt-2"
                      placeholder="user@example.com"
                    />
                  </div>
                  <div>
                    <Label className="text-zinc-400">Name</Label>
                    <Input
                      value={inviteForm.name}
                      onChange={(e) => setInviteForm(f => ({ ...f, name: e.target.value }))}
                      className="input-dark mt-2"
                      placeholder="Full name"
                    />
                  </div>
                  <div>
                    <Label className="text-zinc-400">Role</Label>
                    <Select value={inviteForm.role} onValueChange={(v) => setInviteForm(f => ({ ...f, role: v }))}>
                      <SelectTrigger className="input-dark mt-2">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="support_staff">Support Staff - Access to Support System only</SelectItem>
                        <SelectItem value="tester">Beta Tester - Access to test platform features</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-zinc-400">Environment</Label>
                    <Select value={inviteForm.environment} onValueChange={(v) => setInviteForm(f => ({ ...f, environment: v }))}>
                      <SelectTrigger className="input-dark mt-2">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="test">🧪 Test Environment - For testing and preview</SelectItem>
                        <SelectItem value="production">🚀 Production - Live platform</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-zinc-500 mt-1">
                      {inviteForm.environment === 'test' 
                        ? 'User will be invited to the test/preview environment' 
                        : 'User will be invited to the live production site'}
                    </p>
                  </div>
                  <div>
                    <Label className="text-zinc-400">Personal Message (optional)</Label>
                    <textarea
                      value={inviteForm.message}
                      onChange={(e) => setInviteForm(f => ({ ...f, message: e.target.value }))}
                      className="w-full h-24 mt-2 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700 text-white text-sm resize-none focus:outline-none focus:border-emerald-500"
                      placeholder="Add a personal welcome message..."
                    />
                  </div>
                </div>
                <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setShowInviteModal(false)}>Cancel</Button>
                  <Button onClick={sendInvitation} disabled={sendingInvite} className="bg-emerald-600 hover:bg-emerald-700">
                    {sendingInvite ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Mail className="w-4 h-4 mr-2" />}
                    Send Invitation
                  </Button>
                </div>
              </div>
            </div>
          )}
        </TabsContent>

        {/* Support Tab */}
        <TabsContent value="support" className="space-y-6 mt-6">
          <AdminSupport />
        </TabsContent>

        {/* Email Automation Tab */}
        <TabsContent value="email-automation" className="space-y-6 mt-6">
          {/* Email Stats Overview */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-emerald-500/20">
                    <CheckCircle className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{emailStats?.total_sent || 0}</div>
                    <div className="text-xs text-zinc-500">Emails Sent</div>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-red-500/20">
                    <XCircle className="w-5 h-5 text-red-400" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{emailStats?.total_failed || 0}</div>
                    <div className="text-xs text-zinc-500">Failed</div>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-blue-500/20">
                    <Mail className="w-5 h-5 text-blue-400" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{emailStats?.recent_sent_7d || 0}</div>
                    <div className="text-xs text-zinc-500">Sent (7 days)</div>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-violet-500/20">
                    <Activity className="w-5 h-5 text-violet-400" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{emailTemplates.length}</div>
                    <div className="text-xs text-zinc-500">Templates</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
          
          {/* Sub-tabs for Email Automation */}
          <Tabs value={emailSubTab} onValueChange={setEmailSubTab} className="w-full">
            <TabsList className="bg-zinc-800/50 p-1">
              <TabsTrigger value="templates" className="flex items-center gap-2">
                <Mail className="w-4 h-4" />
                Templates
              </TabsTrigger>
              <TabsTrigger value="rules" className="flex items-center gap-2">
                <Settings className="w-4 h-4" />
                Automation Rules
              </TabsTrigger>
              <TabsTrigger value="broadcast" className="flex items-center gap-2">
                <Newspaper className="w-4 h-4" />
                Broadcast
              </TabsTrigger>
              <TabsTrigger value="logs" className="flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Logs & Analytics
              </TabsTrigger>
            </TabsList>
            
            {/* Email Templates */}
            <TabsContent value="templates" className="mt-4">
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Mail className="w-5 h-5 text-emerald-400" />
                    Email Templates
                  </CardTitle>
                  <CardDescription>Manage automated email templates for user lifecycle</CardDescription>
                </CardHeader>
                <CardContent>
                  {emailLoading ? (
                    <div className="space-y-3">
                      {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {emailTemplates.map((template) => (
                        <div key={template.id || template.key} className="p-4 rounded-lg bg-zinc-800/50 border border-zinc-700 hover:border-zinc-600 transition-colors">
                          <div className="flex items-center justify-between">
                            <div className="flex-1">
                              <div className="flex items-center gap-3">
                                <h4 className="font-medium text-white">{template.name}</h4>
                                <Badge className={template.enabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-500/20 text-zinc-400'}>
                                  {template.enabled ? 'Active' : 'Disabled'}
                                </Badge>
                                <Badge className="bg-violet-500/20 text-violet-400">{template.purpose}</Badge>
                                <Badge className="bg-cyan-500/20 text-cyan-400">{template.trigger}</Badge>
                              </div>
                              <p className="text-sm text-zinc-500 mt-1">Subject: {template.subject}</p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Switch
                                checked={template.enabled}
                                onCheckedChange={(enabled) => handleUpdateTemplate(template.key || template.id, { enabled })}
                              />
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setSelectedTemplate(template)}
                                className="text-zinc-400 hover:text-white"
                              >
                                <Eye className="w-4 h-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setEditingTemplate(template)}
                                className="text-zinc-400 hover:text-white"
                              >
                                <Settings className="w-4 h-4" />
                              </Button>
                            </div>
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
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Settings className="w-5 h-5 text-violet-400" />
                    Automation Rules
                  </CardTitle>
                  <CardDescription>Configure when and how emails are sent automatically</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {automationRules.map((rule) => (
                      <div key={rule.id} className="p-4 rounded-lg bg-zinc-800/50 border border-zinc-700">
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="flex items-center gap-3">
                              <h4 className="font-medium text-white">{rule.name}</h4>
                              <Badge className={rule.enabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-500/20 text-zinc-400'}>
                                {rule.enabled ? 'Active' : 'Disabled'}
                              </Badge>
                            </div>
                            <div className="flex items-center gap-4 mt-2 text-sm text-zinc-400">
                              <span className="flex items-center gap-1">
                                <Zap className="w-3 h-3" />
                                {triggerTypes.find(t => t.value === rule.trigger_type)?.label || rule.trigger_type}
                              </span>
                              <span className="flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                {rule.delay_minutes === 0 ? 'Immediate' : `${Math.floor(rule.delay_minutes / 60)}h ${rule.delay_minutes % 60}m delay`}
                              </span>
                              <span className="flex items-center gap-1">
                                <Mail className="w-3 h-3" />
                                {rule.template_key}
                              </span>
                            </div>
                          </div>
                          <Switch
                            checked={rule.enabled}
                            onCheckedChange={(enabled) => handleToggleRule(rule.id, enabled)}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
            
            {/* Broadcast / Announcements */}
            <TabsContent value="broadcast" className="mt-4">
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Newspaper className="w-5 h-5 text-cyan-400" />
                    Send Broadcast
                  </CardTitle>
                  <CardDescription>Send announcements or updates to all users</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <Label className="text-zinc-400">Template</Label>
                    <Select
                      value={broadcastData.template_key}
                      onValueChange={(value) => setBroadcastData({ ...broadcastData, template_key: value })}
                    >
                      <SelectTrigger className="input-dark mt-2">
                        <SelectValue placeholder="Select template" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="announcement">Announcement</SelectItem>
                        <SelectItem value="system_update">System Update</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-zinc-400">Title</Label>
                    <Input
                      value={broadcastData.announcement_title}
                      onChange={(e) => setBroadcastData({ ...broadcastData, announcement_title: e.target.value })}
                      className="input-dark mt-2"
                      placeholder="Enter announcement title..."
                    />
                  </div>
                  <div>
                    <Label className="text-zinc-400">Content</Label>
                    <textarea
                      value={broadcastData.announcement_content}
                      onChange={(e) => setBroadcastData({ ...broadcastData, announcement_content: e.target.value })}
                      className="w-full h-40 mt-2 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700 text-white resize-none focus:outline-none focus:border-emerald-500"
                      placeholder="Enter announcement content..."
                    />
                  </div>
                  <Button
                    onClick={handleSendBroadcast}
                    disabled={sendingBroadcast}
                    className="w-full bg-emerald-600 hover:bg-emerald-700"
                  >
                    {sendingBroadcast ? (
                      <>
                        <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                        Sending...
                      </>
                    ) : (
                      <>
                        <Mail className="w-4 h-4 mr-2" />
                        Send Broadcast to All Users
                      </>
                    )}
                  </Button>
                </CardContent>
              </Card>
            </TabsContent>
            
            {/* Logs & Analytics */}
            <TabsContent value="logs" className="mt-4">
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Activity className="w-5 h-5 text-blue-400" />
                    Email Logs
                  </CardTitle>
                  <CardDescription>View sent emails and their status</CardDescription>
                </CardHeader>
                <CardContent>
                  {emailLogs.length === 0 ? (
                    <div className="text-center py-8 text-zinc-500">
                      <Mail className="w-12 h-12 mx-auto mb-4 opacity-50" />
                      <p>No emails sent yet</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {emailLogs.slice(0, 20).map((log) => (
                        <div key={log.id} className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/30 text-sm">
                          <div className="flex items-center gap-3">
                            {log.status === 'sent' ? (
                              <CheckCircle className="w-4 h-4 text-emerald-400" />
                            ) : (
                              <XCircle className="w-4 h-4 text-red-400" />
                            )}
                            <div>
                              <span className="text-white">{log.recipient}</span>
                              <span className="text-zinc-500 ml-2">• {log.template_key}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-3 text-zinc-500">
                            <span>{log.subject?.substring(0, 30)}...</span>
                            <span>{new Date(log.created_at).toLocaleString()}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
          
          {/* Template Preview Modal */}
          {selectedTemplate && (
            <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
              <div className="bg-zinc-900 rounded-xl max-w-2xl w-full max-h-[80vh] overflow-hidden">
                <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
                  <h3 className="font-semibold text-white">Preview: {selectedTemplate.name}</h3>
                  <Button variant="ghost" size="sm" onClick={() => setSelectedTemplate(null)}>
                    <XCircle className="w-5 h-5" />
                  </Button>
                </div>
                <div className="p-4 overflow-auto max-h-[60vh]">
                  <div className="mb-4 p-3 bg-zinc-800 rounded-lg">
                    <div className="text-xs text-zinc-500">Subject:</div>
                    <div className="text-white">{selectedTemplate.subject}</div>
                  </div>
                  <div dangerouslySetInnerHTML={{ __html: selectedTemplate.html }} />
                </div>
                <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
                  <Input
                    placeholder="test@email.com"
                    className="input-dark w-48"
                    id="test-email-input"
                  />
                  <Button
                    onClick={() => {
                      const email = document.getElementById('test-email-input').value;
                      if (email) handleTestEmail(selectedTemplate.key, email);
                    }}
                    className="bg-emerald-600 hover:bg-emerald-700"
                  >
                    Send Test
                  </Button>
                </div>
              </div>
            </div>
          )}
          
          {/* Template Edit Modal */}
          {editingTemplate && (
            <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
              <div className="bg-zinc-900 rounded-xl max-w-2xl w-full max-h-[80vh] overflow-hidden">
                <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
                  <h3 className="font-semibold text-white">Edit: {editingTemplate.name}</h3>
                  <Button variant="ghost" size="sm" onClick={() => setEditingTemplate(null)}>
                    <XCircle className="w-5 h-5" />
                  </Button>
                </div>
                <div className="p-4 space-y-4 overflow-auto max-h-[60vh]">
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
    </div>
  );
};

export default Admin;
