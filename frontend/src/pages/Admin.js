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
  AlertTriangle,
  Newspaper,
  BarChart3,
  Brain
} from 'lucide-react';
import { toast } from 'sonner';

const Admin = () => {
  const [settings, setSettings] = useState({
    // Massive.com credentials
    massive_api_key: '',
    massive_access_id: '',
    massive_secret_key: '',
    // MarketAux credentials
    marketaux_api_token: '',
    // OpenAI credentials
    openai_api_key: '',
    // General settings
    data_refresh_interval: 60,
    enable_live_data: false
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  
  // Visibility toggles
  const [showMassiveApiKey, setShowMassiveApiKey] = useState(false);
  const [showMassiveAccessId, setShowMassiveAccessId] = useState(false);
  const [showMassiveSecretKey, setShowMassiveSecretKey] = useState(false);
  const [showMarketauxToken, setShowMarketauxToken] = useState(false);
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

  const PasswordInput = ({ label, value, onChange, show, onToggle, placeholder, helpText, linkUrl, linkText }) => (
    <div className="space-y-2">
      <Label className="flex items-center gap-2">
        {label}
        {linkUrl && (
          <a 
            href={linkUrl} 
            target="_blank" 
            rel="noopener noreferrer"
            className="text-xs text-emerald-400 hover:text-emerald-300"
          >
            ({linkText})
          </a>
        )}
      </Label>
      <div className="relative">
        <Input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          className="input-dark pr-10"
        />
        <button
          type="button"
          onClick={onToggle}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
        >
          {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
      {helpText && <p className="text-xs text-zinc-500">{helpText}</p>}
    </div>
  );

  return (
    <div className="space-y-6" data-testid="admin-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
            <Settings className="w-8 h-8 text-emerald-500" />
            Admin Settings
          </h1>
          <p className="text-zinc-400 mt-1">Configure API credentials and data sources</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
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
        
        {/* Massive.com - Stock & Options Data */}
        <Card className="glass-card" data-testid="massive-config-card">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-emerald-400" />
              Massive.com - Market Data
            </CardTitle>
            <CardDescription>
              Stock quotes, options chains, and real-time market data
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <PasswordInput
              label="API Key"
              value={settings.massive_api_key}
              onChange={(e) => setSettings(s => ({ ...s, massive_api_key: e.target.value }))}
              show={showMassiveApiKey}
              onToggle={() => setShowMassiveApiKey(!showMassiveApiKey)}
              placeholder="Enter your Massive.com API Key"
              linkUrl="https://www.massive.com"
              linkText="Get API Key"
              helpText="Primary authentication key for Massive.com API"
            />
            
            <PasswordInput
              label="Access ID Key"
              value={settings.massive_access_id}
              onChange={(e) => setSettings(s => ({ ...s, massive_access_id: e.target.value }))}
              show={showMassiveAccessId}
              onToggle={() => setShowMassiveAccessId(!showMassiveAccessId)}
              placeholder="Enter your Access ID Key"
              helpText="Access identifier for API requests"
            />
            
            <PasswordInput
              label="Secret Key"
              value={settings.massive_secret_key}
              onChange={(e) => setSettings(s => ({ ...s, massive_secret_key: e.target.value }))}
              show={showMassiveSecretKey}
              onToggle={() => setShowMassiveSecretKey(!showMassiveSecretKey)}
              placeholder="Enter your Secret Key"
              helpText="Secret key for secure API authentication"
            />

            {/* Status */}
            <div className="pt-4 border-t border-zinc-800">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Connection Status</span>
                <Badge className={settings.massive_api_key && settings.massive_access_id && settings.massive_secret_key ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'}>
                  {settings.massive_api_key && settings.massive_access_id && settings.massive_secret_key ? 'Configured' : 'Not Configured'}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* MarketAux - News & Sentiment */}
        <Card className="glass-card" data-testid="marketaux-config-card">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Newspaper className="w-5 h-5 text-emerald-400" />
              MarketAux - News & Sentiment
            </CardTitle>
            <CardDescription>
              Market news, sentiment analysis for enhanced trading strategies
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <PasswordInput
              label="API Token"
              value={settings.marketaux_api_token}
              onChange={(e) => setSettings(s => ({ ...s, marketaux_api_token: e.target.value }))}
              show={showMarketauxToken}
              onToggle={() => setShowMarketauxToken(!showMarketauxToken)}
              placeholder="Enter your MarketAux API Token"
              linkUrl="https://www.marketaux.com"
              linkText="Get API Token"
              helpText="Used for market news and sentiment analysis to enhance covered call and PMCC strategies"
            />

            {/* Features */}
            <div className="pt-4 border-t border-zinc-800 space-y-2">
              <Label className="text-xs text-zinc-400">Features Enabled</Label>
              <ul className="text-xs text-zinc-500 space-y-1">
                <li className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${settings.marketaux_api_token ? 'bg-emerald-400' : 'bg-zinc-600'}`} />
                  Real-time market news feed
                </li>
                <li className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${settings.marketaux_api_token ? 'bg-emerald-400' : 'bg-zinc-600'}`} />
                  Sentiment analysis per stock
                </li>
                <li className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${settings.marketaux_api_token ? 'bg-emerald-400' : 'bg-zinc-600'}`} />
                  Strategy enhancement signals
                </li>
              </ul>
            </div>

            {/* Status */}
            <div className="pt-4 border-t border-zinc-800">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Connection Status</span>
                <Badge className={settings.marketaux_api_token ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'}>
                  {settings.marketaux_api_token ? 'Configured' : 'Not Configured'}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* OpenAI - AI Analysis */}
        <Card className="glass-card" data-testid="openai-config-card">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Brain className="w-5 h-5 text-emerald-400" />
              OpenAI - AI Analysis
            </CardTitle>
            <CardDescription>
              AI-powered trade analysis, scoring, and recommendations
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <PasswordInput
              label="OpenAI API Key"
              value={settings.openai_api_key}
              onChange={(e) => setSettings(s => ({ ...s, openai_api_key: e.target.value }))}
              show={showOpenAIKey}
              onToggle={() => setShowOpenAIKey(!showOpenAIKey)}
              placeholder="Enter your OpenAI API Key"
              linkUrl="https://platform.openai.com/api-keys"
              linkText="Get API Key"
              helpText="Powers AI trade analysis and recommendations (GPT-5.2)"
            />

            <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
              <p className="text-xs text-emerald-400">
                ✓ Emergent Universal Key is pre-configured as fallback
              </p>
            </div>

            {/* Status */}
            <div className="pt-4 border-t border-zinc-800">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Connection Status</span>
                <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
                  {settings.openai_api_key ? 'Custom Key' : 'Using Fallback'}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* General Settings */}
        <Card className="glass-card" data-testid="general-settings-card">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Database className="w-5 h-5 text-emerald-400" />
              General Settings
            </CardTitle>
            <CardDescription>
              Data refresh and live data configuration
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
                  Use real-time data from Massive.com instead of mock data
                </p>
              </div>
              <Switch
                checked={settings.enable_live_data}
                onCheckedChange={(checked) => setSettings(s => ({ ...s, enable_live_data: checked }))}
                data-testid="enable-live-data-switch"
              />
            </div>

            {/* Overall Status */}
            <div className="pt-4 border-t border-zinc-800 space-y-3">
              <Label className="text-xs text-zinc-400">System Status</Label>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Market Data (Massive.com)</span>
                  <Badge className={settings.massive_api_key ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'}>
                    {settings.massive_api_key ? 'Ready' : 'Mock Data'}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">News & Sentiment (MarketAux)</span>
                  <Badge className={settings.marketaux_api_token ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'}>
                    {settings.marketaux_api_token ? 'Ready' : 'Mock Data'}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">AI Analysis (OpenAI)</span>
                  <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
                    {settings.openai_api_key ? 'Custom Key' : 'Fallback Active'}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Data Mode</span>
                  <Badge className={settings.enable_live_data ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'}>
                    {settings.enable_live_data ? 'Live' : 'Mock Data'}
                  </Badge>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Save Button */}
      <div className="flex justify-end">
        <Button
          onClick={saveSettings}
          className="bg-emerald-600 hover:bg-emerald-700 text-white"
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
            <Activity className="w-5 h-5 text-emerald-400" />
            Getting Started
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-zinc-400 space-y-4">
          <div>
            <h4 className="font-medium text-white mb-2">1. Set up Massive.com</h4>
            <p>Create an account at <a href="https://www.massive.com" target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:underline">massive.com</a> and obtain your API Key, Access ID, and Secret Key. This provides real-time stock quotes and options chain data.</p>
          </div>
          <div>
            <h4 className="font-medium text-white mb-2">2. Set up MarketAux</h4>
            <p>Get your API token from <a href="https://www.marketaux.com" target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:underline">marketaux.com</a> for market news and sentiment analysis. This helps identify market conditions for better covered call timing.</p>
          </div>
          <div>
            <h4 className="font-medium text-white mb-2">3. Configure OpenAI (Optional)</h4>
            <p>For enhanced AI insights, add your OpenAI API key. The platform uses a fallback key if not configured.</p>
          </div>
          <div>
            <h4 className="font-medium text-white mb-2">4. Enable Live Data</h4>
            <p>Once your Massive.com credentials are configured, enable live data to switch from mock data to real market data.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Admin;
