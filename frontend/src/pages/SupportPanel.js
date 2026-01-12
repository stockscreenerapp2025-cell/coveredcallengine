/**
 * SupportPanel - Dedicated support panel for support staff users
 * Only shows the Support ticket management functionality
 */
import { useAuth } from '../contexts/AuthContext';
import AdminSupport from '../components/AdminSupport';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Headphones, Shield } from 'lucide-react';

const SupportPanel = () => {
  const { user, isAdmin, isSupportStaff } = useAuth();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Headphones className="w-7 h-7 text-emerald-400" />
            Support Dashboard
          </h1>
          <p className="text-zinc-400 mt-1">
            Manage customer support tickets
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
            <Shield className="w-3 h-3 mr-1" />
            {isAdmin ? 'Admin' : 'Support Staff'}
          </Badge>
          <span className="text-sm text-zinc-500">{user?.email}</span>
        </div>
      </div>

      {/* Support Component */}
      <AdminSupport />
    </div>
  );
};

export default SupportPanel;
