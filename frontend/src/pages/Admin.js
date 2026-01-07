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
  Calendar
} from 'lucide-react';
import { toast } from 'sonner';

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
  
  // Visibility toggles
  const [showMassiveApiKey, setShowMassiveApiKey] = useState(false);
  const [showMassiveAccessId, setShowMassiveAccessId] = useState(false);
  const [showMassiveSecretKey, setShowMassiveSecretKey] = useState(false);
  const [showMarketauxToken, setShowMarketauxToken] = useState(false);
  const [showOpenAIKey, setShowOpenAIKey] = useState(false);
  const [showStripeWebhook, setShowStripeWebhook] = useState(false);
  const [showStripeSecret, setShowStripeSecret] = useState(false);
  const [showResendKey, setShowResendKey] = useState(false);

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
        <TabsList className="grid w-full grid-cols-5 bg-zinc-800/50 p-1">
          <TabsTrigger value="dashboard" className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            Dashboard
          </TabsTrigger>
          <TabsTrigger value="users" className="flex items-center gap-2" onClick={() => fetchUsers(1)}>
            <Users className="w-4 h-4" />
            Users
          </TabsTrigger>
          <TabsTrigger value="subscriptions" className="flex items-center gap-2">
            <CreditCard className="w-4 h-4" />
            Subscriptions
          </TabsTrigger>
          <TabsTrigger value="integrations" className="flex items-center gap-2">
            <Key className="w-4 h-4" />
            Integrations
          </TabsTrigger>
          <TabsTrigger value="api-keys" className="flex items-center gap-2">
            <Database className="w-4 h-4" />
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
                      <span className="text-zinc-400">Yearly Plans</span>
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
                      <Label className="text-zinc-400">Yearly Subscription Link ($499)</Label>
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
                      <Label className="text-zinc-400">Yearly Subscription Link ($499)</Label>
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
