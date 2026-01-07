import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
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
  Crown
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
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const navItems = [
    { path: '/dashboard', icon: <LayoutDashboard className="w-5 h-5" />, label: 'Dashboard' },
    { path: '/screener', icon: <Search className="w-5 h-5" />, label: 'Screener' },
    { path: '/pmcc', icon: <LineChart className="w-5 h-5" />, label: 'PMCC' },
    { path: '/portfolio', icon: <Wallet className="w-5 h-5" />, label: 'Portfolio' },
    { path: '/watchlist', icon: <BookmarkPlus className="w-5 h-5" />, label: 'Watchlist' },
    { path: '/pricing', icon: <Crown className="w-5 h-5" />, label: 'Subscribe', highlight: true },
  ];

  if (isAdmin) {
    navItems.push({ path: '/admin', icon: <Settings className="w-5 h-5" />, label: 'Admin' });
  }

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  return (
    <div className="min-h-screen bg-[#09090b]">
      {/* Sidebar */}
      <aside className={`sidebar transition-transform duration-300 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}>
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
            {navItems.map((item) => (
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
            ))}
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
