import { useState, useEffect } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { simulatorApi } from '../lib/api';
import { Button } from './ui/button';
import {
  Activity,
  LayoutDashboard,
  Search,
  LineChart,
  Wallet,
  BookmarkPlus,
  Settings,
  LogOut,
  Menu,
  X,
  ChevronDown,
  Play,
  Headphones,
  Coins,
  Lock,
  BookOpen
} from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';

const APP_NAME = "Covered Call Engine";

const Layout = ({ children }) => {
  const { user, logout, isAdmin, isSupportStaff, isTester, hasSupportAccess, hasPageAccess, requiredPlanFor, userPlan } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [alertPopup, setAlertPopup] = useState(false);
  const [unreadAlerts, setUnreadAlerts] = useState([]);
  const [upgradeModal, setUpgradeModal] = useState(null); // { page, requiredPlan }

  useEffect(() => {
    if (!user) return;
    simulatorApi.getUnreadAlerts().then(res => {
      if (res.data?.count > 0) {
        setUnreadAlerts(res.data.alerts);
        setAlertPopup(true);
      }
    }).catch(() => {});
  }, [user]);

  // Build navigation based on user role
  const navItems = [];
  
  // Support staff ONLY sees the Support panel
  if (isSupportStaff && !isAdmin) {
    navItems.push({ path: '/support', icon: <Headphones className="w-5 h-5" />, label: 'Support' });
  } else {
    // Regular users and admins see the full navigation
    navItems.push(
      { path: '/dashboard',  pageKey: 'dashboard',  icon: <LayoutDashboard className="w-5 h-5" />, label: 'Dashboard' },
      { path: '/screener',   pageKey: 'screener',   icon: <Search className="w-5 h-5" />,          label: 'Screener' },
      { path: '/pmcc',       pageKey: 'pmcc',       icon: <LineChart className="w-5 h-5" />,        label: 'PMCC' },
      { path: '/portfolio',  pageKey: 'portfolio',  icon: <Wallet className="w-5 h-5" />,           label: 'Portfolio' },
      { path: '/simulator',  pageKey: 'simulator',  icon: <Play className="w-5 h-5" />,             label: 'Simulator' },
      { path: '/watchlist',  pageKey: 'watchlist',  icon: <BookmarkPlus className="w-5 h-5" />,     label: 'Watchlist' },
      { path: '/ai-wallet',  pageKey: 'ai-wallet',  icon: <Coins className="w-5 h-5" />,            label: 'AI Wallet' },
      { path: '/help',       pageKey: 'help',       icon: <BookOpen className="w-5 h-5" />,          label: 'Help' },
    );
    
    // Only full admins see the Admin panel
    if (isAdmin) {
      navItems.push({ path: '/admin', icon: <Settings className="w-5 h-5" />, label: 'Admin' });
    }
  }

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  const dismissAlerts = () => {
    setAlertPopup(false);
    simulatorApi.markAlertsRead().catch(() => {});
  };

  // Redirect users with no subscription to pricing page (except on /pricing itself)
  if (!isAdmin && !isTester && !isSupportStaff && user && !userPlan && location.pathname !== '/pricing') {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center p-4">
        <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-8 max-w-md w-full text-center">
          <div className="w-14 h-14 rounded-full bg-violet-500/20 flex items-center justify-center mx-auto mb-4">
            <Lock className="w-7 h-7 text-violet-400" />
          </div>
          <h2 className="text-white font-bold text-xl mb-2">No Active Subscription</h2>
          <p className="text-zinc-400 text-sm mb-6">
            Choose a plan to get started. All plans include a 7-day free trial.
          </p>
          <button
            onClick={() => navigate('/pricing')}
            className="w-full bg-violet-600 hover:bg-violet-700 text-white rounded-lg py-3 font-medium transition-colors"
          >
            View Pricing Plans
          </button>
          <button
            onClick={handleLogout}
            className="w-full mt-3 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 rounded-lg py-2 text-sm transition-colors"
          >
            Sign Out
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#09090b]">

      {/* Trade Alert Popup — shown once per login if unread alerts exist */}
      {alertPopup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-amber-500/30 rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-2xl">⚠️</span>
              <div>
                <h2 className="text-white font-semibold text-lg">Trade Alerts</h2>
                <p className="text-zinc-400 text-xs">{unreadAlerts.length} new alert{unreadAlerts.length > 1 ? 's' : ''} since your last visit</p>
              </div>
            </div>
            <div className="space-y-2 max-h-64 overflow-y-auto mb-5">
              {unreadAlerts.map((alert, i) => (
                <div key={i} className="flex items-start justify-between bg-amber-500/5 border border-amber-500/20 rounded-lg px-3 py-2">
                  <div>
                    <span className="text-amber-400 font-semibold text-sm">{alert.symbol}</span>
                    <span className="text-zinc-400 text-xs ml-2">{alert.rule_name}</span>
                    <p className="text-zinc-300 text-xs mt-0.5">{alert.message}</p>
                  </div>
                  <span className="text-zinc-500 text-xs whitespace-nowrap ml-3">
                    {new Date(alert.timestamp).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => { dismissAlerts(); navigate('/simulator'); }}
                className="flex-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 border border-amber-500/30 rounded-lg py-2 text-sm font-medium transition-colors"
              >
                View in Simulator
              </button>
              <button
                onClick={dismissAlerts}
                className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg py-2 text-sm font-medium transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar */}
      <aside className={`sidebar transition-transform duration-300 ${sidebarOpen ? 'open' : ''}`}>
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center justify-between p-4 border-b border-white/5">
            <div className="flex items-center gap-2">
              <Activity className="w-8 h-8 text-emerald-500" />
              <span className="text-lg font-bold text-white">{APP_NAME}</span>
            </div>
            <button
              className="md:hidden text-zinc-400 hover:text-white"
              onClick={() => setSidebarOpen(false)}
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 py-4 overflow-y-auto">
            {navItems.map((item) => {
              const locked = !hasPageAccess(item.pageKey);
              if (locked) {
                return (
                  <button
                    key={item.path}
                    onClick={() => setUpgradeModal({ page: item.label, requiredPlan: requiredPlanFor(item.pageKey) })}
                    className="sidebar-nav-item w-full text-left opacity-40 cursor-pointer"
                    data-testid={`nav-${item.label.toLowerCase()}`}
                  >
                    {item.icon}
                    <span className="flex-1">{item.label}</span>
                    <Lock className="w-3.5 h-3.5 text-zinc-500" />
                  </button>
                );
              }
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `sidebar-nav-item ${isActive ? 'active' : ''}`
                  }
                  onClick={() => setSidebarOpen(false)}
                  data-testid={`nav-${item.label.toLowerCase()}`}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </nav>

          {/* User section */}
          <div className="p-4 border-t border-white/5">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="flex items-center gap-3 w-full p-3 rounded-lg hover:bg-zinc-800/50 transition-colors">
                  <div className="w-8 h-8 rounded-full bg-violet-500/20 flex items-center justify-center text-violet-400 text-sm font-medium">
                    {user?.name?.charAt(0).toUpperCase() || 'U'}
                  </div>
                  <div className="flex-1 text-left">
                    <div className="text-sm font-medium text-white truncate">{user?.name}</div>
                    <div className="text-xs text-zinc-500 truncate">{user?.email}</div>
                  </div>
                  <ChevronDown className="w-4 h-4 text-zinc-500" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56 bg-zinc-900 border-zinc-800">
                <DropdownMenuItem className="text-zinc-400">
                  Signed in as {user?.email}
                </DropdownMenuItem>
                <DropdownMenuSeparator className="bg-zinc-800" />
                <DropdownMenuItem 
                  onClick={handleLogout}
                  className="text-red-400 cursor-pointer"
                  data-testid="logout-btn"
                >
                  <LogOut className="w-4 h-4 mr-2" />
                  Sign Out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </aside>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Upgrade Plan Modal */}
      {upgradeModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onClick={() => setUpgradeModal(null)}>
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-6 max-w-sm w-full" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-violet-500/20 flex items-center justify-center">
                <Lock className="w-5 h-5 text-violet-400" />
              </div>
              <div>
                <h3 className="text-white font-bold text-lg">{upgradeModal.page} Locked</h3>
                <p className="text-zinc-400 text-sm">Requires {upgradeModal.requiredPlan?.charAt(0).toUpperCase() + upgradeModal.requiredPlan?.slice(1)} plan or higher</p>
              </div>
            </div>
            <p className="text-zinc-400 text-sm mb-5">
              Your current plan <span className="text-white font-medium capitalize">({userPlan || 'none'})</span> does not include access to <span className="text-white font-medium">{upgradeModal.page}</span>. Upgrade your plan to unlock this feature.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => { setUpgradeModal(null); navigate('/pricing'); setSidebarOpen(false); }}
                className="flex-1 bg-violet-600 hover:bg-violet-700 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
              >
                Upgrade Plan
              </button>
              <button
                onClick={() => setUpgradeModal(null)}
                className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg py-2.5 text-sm font-medium transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main content */}
      <main className="main-content min-h-screen">
        {/* Top bar (mobile) */}
        <div className="sticky top-0 z-30 md:hidden glass border-b border-white/5">
          <div className="flex items-center justify-between p-4">
            <button
              onClick={() => setSidebarOpen(true)}
              className="text-zinc-400 hover:text-white"
              data-testid="mobile-menu-btn"
            >
              <Menu className="w-6 h-6" />
            </button>
            <div className="flex items-center gap-2">
              <Activity className="w-6 h-6 text-emerald-500" />
              <span className="font-bold text-white">{APP_NAME}</span>
            </div>
            <div className="w-6" /> {/* Spacer */}
          </div>
        </div>

        {/* Page content */}
        <div className="p-4 md:p-6 lg:p-8">
          {children}
        </div>
      </main>
    </div>
  );
};

export default Layout;
