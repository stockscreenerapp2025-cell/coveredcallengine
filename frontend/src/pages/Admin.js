import { useState, useEffect } from 'react';
import { adminApi } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Switch } from '../components/ui/switch';
import { Badge } from '../components/ui/badge';
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
  AlertTriangle
} from 'lucide-react';
import { toast } from 'sonner';

const Admin = () => {
  const [settings, setSettings] = useState({
    polygon_api_key: '',
    openai_api_key: '',
    data_refresh_interval: 60,
    enable_live_data: false
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showPolygonKey, setShowPolygonKey] = useState(false);
  const [showOpenAIKey, setShowOpenAIKey] = useState(false);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const response = await adminApi.getSettings();
      setSettings(prev => ({
        ...prev,
        ...response.data
      }));
    } catch (error) {
      console.error('Settings fetch error:', error);
      toast.error('Failed to load settings');
    } finally {
      setLoading(false);
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

  return (
    <div className="space-y-6" data-testid="admin-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Settings className="w-8 h-8 text-violet-500" />
            Admin Settings
          </h1>
          <p className="text-zinc-400 mt-1">Configure API credentials and system settings</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge className="badge-ai">
            <Shield className="w-3 h-3 mr-1" />
            Admin Access
          </Badge>
        </div>
      </div>

      {/* Warning Banner */}
      <div className="glass-card p-4 border-l-4 border-yellow-500">
        <div className="flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-yellow-400" />
          <div>
            <div className="text-sm font-medium text-yellow-400">Security Notice</div>
            <div className="text-xs text-zinc-500">
              API keys are encrypted at rest. Never share your API keys with anyone.
            </div>
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* API Configuration */}
        <Card className="glass-card" data-testid="api-config-card">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Key className="w-5 h-5 text-violet-400" />
              API Configuration
            </CardTitle>
            <CardDescription>
              Configure your market data and AI service credentials
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Polygon API Key */}
            <div className="space-y-2">
              <Label className="flex items-center gap-2">
                Polygon.io API Key
                <a 
                  href="https://polygon.io/dashboard/api-keys" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="text-xs text-violet-400 hover:text-violet-300"
                >
                  (Get key)
                </a>
              </Label>
              <div className="relative">
                <Input
                  type={showPolygonKey ? 'text' : 'password'}
                  value={settings.polygon_api_key}
                  onChange={(e) => setSettings(s => ({ ...s, polygon_api_key: e.target.value }))}
                  placeholder="Enter your Polygon.io API key"
                  className="input-dark pr-10"
                  data-testid="polygon-api-key-input"
                />
                <button
                  type="button"
                  onClick={() => setShowPolygonKey(!showPolygonKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                >
                  {showPolygonKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <p className="text-xs text-zinc-500">
                Required for real-time stock quotes, options chains, and market news
              </p>
            </div>

            {/* OpenAI API Key */}
            <div className="space-y-2">
              <Label className="flex items-center gap-2">
                OpenAI API Key
                <a 
                  href="https://platform.openai.com/api-keys" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="text-xs text-violet-400 hover:text-violet-300"
                >
                  (Get key)
                </a>
              </Label>
              <div className="relative">
                <Input
                  type={showOpenAIKey ? 'text' : 'password'}
                  value={settings.openai_api_key}
                  onChange={(e) => setSettings(s => ({ ...s, openai_api_key: e.target.value }))}
                  placeholder="Enter your OpenAI API key"
                  className="input-dark pr-10"
                  data-testid="openai-api-key-input"
                />
                <button
                  type="button"
                  onClick={() => setShowOpenAIKey(!showOpenAIKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                >
                  {showOpenAIKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <p className="text-xs text-zinc-500">
                Required for AI-powered trade analysis and recommendations (GPT-5.2)
              </p>
              <p className="text-xs text-emerald-400">
                Note: Emergent Universal Key is pre-configured as fallback
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Data Settings */}
        <Card className="glass-card" data-testid="data-settings-card">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Database className="w-5 h-5 text-violet-400" />
              Data Settings
            </CardTitle>
            <CardDescription>
              Configure data refresh and live data options
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Data Refresh Interval */}
            <div className="space-y-2">
              <Label>Data Refresh Interval (seconds)</Label>
              <Input
                type="number"
                min="10"
                max="300"
                value={settings.data_refresh_interval}
                onChange={(e) => setSettings(s => ({ ...s, data_refresh_interval: parseInt(e.target.value) || 60 }))}
                className="input-dark"
                data-testid="refresh-interval-input"
              />
              <p className="text-xs text-zinc-500">
                How often to refresh market data (10-300 seconds)
              </p>
            </div>

            {/* Enable Live Data */}
            <div className="flex items-center justify-between p-4 rounded-lg bg-zinc-800/30">
              <div>
                <Label className="text-white">Enable Live Data</Label>
                <p className="text-xs text-zinc-500 mt-1">
                  Use real-time data instead of mock data
                </p>
              </div>
              <Switch
                checked={settings.enable_live_data}
                onCheckedChange={(checked) => setSettings(s => ({ ...s, enable_live_data: checked }))}
                data-testid="enable-live-data-switch"
              />
            </div>

            {/* Status Indicators */}
            <div className="space-y-3 pt-4 border-t border-white/5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Polygon.io Status</span>
                <Badge className={settings.polygon_api_key ? 'badge-success' : 'badge-warning'}>
                  {settings.polygon_api_key ? 'Configured' : 'Not Configured'}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">OpenAI Status</span>
                <Badge className={settings.openai_api_key ? 'badge-success' : 'badge-info'}>
                  {settings.openai_api_key ? 'Configured' : 'Using Fallback'}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Data Mode</span>
                <Badge className={settings.enable_live_data ? 'badge-success' : 'badge-warning'}>
                  {settings.enable_live_data ? 'Live' : 'Mock Data'}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Save Button */}
      <div className="flex justify-end">
        <Button
          onClick={saveSettings}
          className="btn-primary"
          disabled={saving}
          data-testid="save-settings-btn"
        >
          {saving ? (
            <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <Save className="w-4 h-4 mr-2" />
          )}
          Save Settings
        </Button>
      </div>

      {/* Help Section */}
      <Card className="glass-card" data-testid="help-section">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Activity className="w-5 h-5 text-violet-400" />
            Getting Started
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-zinc-400 space-y-4">
          <div>
            <h4 className="font-medium text-white mb-2">1. Set up Polygon.io</h4>
            <p>Create a free account at polygon.io and get your API key from the dashboard. Free tier includes 5 API calls/minute with delayed data.</p>
          </div>
          <div>
            <h4 className="font-medium text-white mb-2">2. Configure OpenAI (Optional)</h4>
            <p>For enhanced AI insights, add your OpenAI API key. The platform uses a fallback key if not configured.</p>
          </div>
          <div>
            <h4 className="font-medium text-white mb-2">3. Enable Live Data</h4>
            <p>Once your Polygon API key is configured, enable live data to switch from mock data to real market data.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Admin;
