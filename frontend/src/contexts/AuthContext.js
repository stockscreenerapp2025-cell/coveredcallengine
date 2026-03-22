import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from '../lib/api';

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState(localStorage.getItem('token'));

  const fetchUser = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }

    try {
      const response = await api.get('/auth/me');
      setUser(response.data);
    } catch (error) {
      console.error('Auth error:', error);
      localStorage.removeItem('token');
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (email, password) => {
    const response = await api.post('/auth/login', { email, password });
    const { access_token, user: userData } = response.data;
    
    localStorage.setItem('token', access_token);
    setToken(access_token);
    setUser(userData);
    
    return userData;
  };

  const register = async (email, password, name) => {
    const response = await api.post('/auth/register', { email, password, name });
    const { access_token, user: userData } = response.data;
    
    localStorage.setItem('token', access_token);
    setToken(access_token);
    setUser(userData);
    
    return userData;
  };

  const logout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setUser(null);
  };

  // Role-based access helpers
  const isAdmin = user?.is_admin || false;
  const isSupportStaff = user?.is_support_staff || user?.role === 'support_staff';
  const isTester = user?.is_tester || user?.role === 'tester';
  const hasSupportAccess = isAdmin || isSupportStaff;

  // Plan-based access
  const userPlan = user?.subscription?.plan_id?.toLowerCase() || null;

  const PLAN_ACCESS = {
    basic:    ['dashboard', 'screener', 'portfolio', 'watchlist', 'ai-wallet', 'help'],
    standard: ['dashboard', 'screener', 'pmcc', 'portfolio', 'watchlist', 'ai-wallet', 'help'],
    premium:  ['dashboard', 'screener', 'pmcc', 'portfolio', 'simulator', 'watchlist', 'ai-wallet', 'help'],
  };

  const hasPageAccess = (page) => {
    if (isAdmin || isTester) return true;
    if (!userPlan) return false;
    return (PLAN_ACCESS[userPlan] || []).includes(page);
  };

  // The minimum plan required to access a page
  const requiredPlanFor = (page) => {
    if (PLAN_ACCESS.basic?.includes(page)) return 'basic';
    if (PLAN_ACCESS.standard?.includes(page)) return 'standard';
    if (PLAN_ACCESS.premium?.includes(page)) return 'premium';
    return null;
  };

  // Check if user has a specific permission
  const hasPermission = (permission) => {
    if (isAdmin) return true;
    const permissions = user?.permissions || [];
    if (permissions.includes('*')) return true;
    return permissions.includes(permission);
  };

  const value = {
    user,
    token,
    loading,
    login,
    register,
    logout,
    isAuthenticated: !!user,
    isAdmin,
    isSupportStaff,
    isTester,
    hasSupportAccess,
    hasPermission,
    userPlan,
    hasPageAccess,
    requiredPlanFor
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};
