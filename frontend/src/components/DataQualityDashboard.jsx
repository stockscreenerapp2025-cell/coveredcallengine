import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { RefreshCw, CheckCircle, AlertTriangle, XCircle, Clock, Calendar, Database } from 'lucide-react';
import { toast } from 'sonner';
import api from '../lib/api';

const DataQualityDashboard = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchDataQuality();
  }, []);

  const fetchDataQuality = async () => {
    setLoading(true);
    try {
      const response = await api.get('/screener/data-quality-dashboard');
      setData(response.data);
    } catch (error) {
      console.error('Failed to fetch data quality:', error);
      toast.error('Failed to load data quality status');
    } finally {
      setLoading(false);
    }
  };

  const handleRefreshScans = async () => {
    setRefreshing(true);
    try {
      toast.info('Refreshing all scans with T-1 data... This may take a few minutes.');
      await api.post('/screener/refresh-precomputed');
      toast.success('Scans refreshed successfully!');
      await fetchDataQuality();
    } catch (error) {
      console.error('Failed to refresh scans:', error);
      const msg = error.response?.data?.detail || 'Failed to refresh scans';
      toast.error(msg);
    } finally {
      setRefreshing(false);
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'green':
        return <CheckCircle className="w-5 h-5 text-emerald-400" />;
      case 'amber':
        return <AlertTriangle className="w-5 h-5 text-yellow-400" />;
      case 'red':
        return <XCircle className="w-5 h-5 text-red-400" />;
      default:
        return <Clock className="w-5 h-5 text-zinc-400" />;
    }
  };

  const getStatusBadge = (status) => {
    const styles = {
      green: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
      amber: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
      red: 'bg-red-500/20 text-red-400 border-red-500/30',
    };
    return styles[status] || 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30';
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-32 w-full" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="data-quality-dashboard">
      {/* T-1 Data Overview */}
      <Card className="glass-card border-emerald-500/30">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Calendar className="w-5 h-5 text-emerald-400" />
              T-1 Market Data Status
            </CardTitle>
            <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
              {data?.t1_data?.data_date || 'Loading...'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-zinc-800/50 rounded-lg p-4">
              <p className="text-xs text-zinc-500 mb-1">Data Date</p>
              <p className="text-lg font-bold text-white">{data?.t1_data?.data_date}</p>
              <p className="text-xs text-zinc-400 mt-1">Previous trading day</p>
            </div>
            <div className="bg-zinc-800/50 rounded-lg p-4">
              <p className="text-xs text-zinc-500 mb-1">Data Age</p>
              <p className="text-lg font-bold text-white">{data?.t1_data?.data_age_hours?.toFixed(1)}h</p>
              <p className="text-xs text-zinc-400 mt-1">Since market close</p>
            </div>
            <div className="bg-zinc-800/50 rounded-lg p-4">
              <p className="text-xs text-zinc-500 mb-1">Next Refresh</p>
              <p className="text-sm font-medium text-white">{data?.t1_data?.next_refresh}</p>
              <p className="text-xs text-zinc-400 mt-1">4:00 PM ET daily</p>
            </div>
            <div className="bg-zinc-800/50 rounded-lg p-4">
              <p className="text-xs text-zinc-500 mb-1">Current Time (ET)</p>
              <p className="text-sm font-medium text-white">{data?.market_status?.current_time_et}</p>
              <p className="text-xs text-zinc-400 mt-1">{data?.market_status?.market_status}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Overall Status */}
      <Card className={`glass-card ${
        data?.overall_status === 'green' ? 'border-emerald-500/30' :
        data?.overall_status === 'amber' ? 'border-yellow-500/30' : 'border-red-500/30'
      }`}>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Database className="w-5 h-5" />
              Scan Status Overview
            </CardTitle>
            <div className="flex items-center gap-3">
              <Badge className={getStatusBadge(data?.overall_status)}>
                {data?.overall_status_emoji} {data?.overall_message}
              </Badge>
              <Button
                onClick={handleRefreshScans}
                disabled={refreshing}
                className="bg-violet-600 hover:bg-violet-700"
                data-testid="refresh-all-scans-btn"
              >
                <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
                {refreshing ? 'Refreshing...' : 'Refresh All'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-6 mb-4">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-4 h-4 text-emerald-400" />
              <span className="text-emerald-400 font-medium">{data?.summary?.green}</span>
              <span className="text-zinc-500 text-sm">Fresh</span>
            </div>
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-yellow-400" />
              <span className="text-yellow-400 font-medium">{data?.summary?.amber}</span>
              <span className="text-zinc-500 text-sm">Slightly Stale</span>
            </div>
            <div className="flex items-center gap-2">
              <XCircle className="w-4 h-4 text-red-400" />
              <span className="text-red-400 font-medium">{data?.summary?.red}</span>
              <span className="text-zinc-500 text-sm">Needs Refresh</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Individual Scan Status */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data?.scans?.map((scan, index) => (
          <Card 
            key={index} 
            className={`glass-card ${
              scan.status === 'green' ? 'border-emerald-500/20' :
              scan.status === 'amber' ? 'border-yellow-500/20' : 'border-red-500/20'
            }`}
            data-testid={`scan-status-${scan.scan_type}-${scan.profile}`}
          >
            <CardContent className="p-4">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-semibold text-white">{scan.scan_type}</h3>
                  <p className="text-sm text-zinc-400">{scan.profile}</p>
                </div>
                {getStatusIcon(scan.status)}
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Opportunities</span>
                  <span className="text-white font-medium">{scan.count}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Computed Date</span>
                  <span className="text-white">{scan.computed_date || 'Never'}</span>
                </div>
                {scan.days_old !== null && scan.days_old !== undefined && (
                  <div className="flex justify-between text-sm">
                    <span className="text-zinc-500">Age</span>
                    <span className={`${
                      scan.status === 'green' ? 'text-emerald-400' :
                      scan.status === 'amber' ? 'text-yellow-400' : 'text-red-400'
                    }`}>
                      {scan.days_old === 0 ? 'Fresh (T-1)' : `${scan.days_old} day(s) old`}
                    </span>
                  </div>
                )}
              </div>
              
              {scan.needs_refresh && (
                <div className="mt-3 pt-3 border-t border-zinc-700/50">
                  <p className="text-xs text-yellow-400 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" />
                    Needs refresh
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Info Note */}
      <div className="text-center text-sm text-zinc-500">
        <p>
          CCE uses <span className="text-emerald-400 font-medium">T-1 (previous trading day)</span> market close data for all scans.
          Data is automatically refreshed daily after 4:00 PM ET.
        </p>
      </div>
    </div>
  );
};

export default DataQualityDashboard;
