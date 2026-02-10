import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Screener from "./pages/Screener";
import PMCC from "./pages/PMCC";
import Portfolio from "./pages/Portfolio";
import Simulator from "./pages/Simulator";
import Watchlist from "./pages/Watchlist";
import Admin from "./pages/Admin";
import SupportPanel from "./pages/SupportPanel";
import Pricing from "./pages/Pricing";
import Terms from "./pages/Terms";
import Privacy from "./pages/Privacy";
import AcceptInvitation from "./pages/AcceptInvitation";
import AIWallet from "./pages/AIWallet";
import Layout from "./components/Layout";
import "@/App.css";

// Protected Route wrapper - for authenticated users
const ProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  
  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center">
        <div className="loading-spinner" />
      </div>
    );
  }
  
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  
  return children;
};

// Admin Route wrapper - ONLY for full admins
const AdminRoute = ({ children }) => {
  const { user, loading, isAdmin } = useAuth();
  
  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center">
        <div className="loading-spinner" />
      </div>
    );
  }
  
  if (!user || !isAdmin) {
    return <Navigate to="/dashboard" replace />;
  }
  
  return children;
};

// Support Route wrapper - for support staff (limited admin access)
const SupportRoute = ({ children }) => {
  const { user, loading, hasSupportAccess } = useAuth();
  
  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center">
        <div className="loading-spinner" />
      </div>
    );
  }
  
  if (!user || !hasSupportAccess) {
    return <Navigate to="/dashboard" replace />;
  }
  
  return children;
};

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public routes */}
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          
          {/* Protected routes */}
          <Route path="/dashboard" element={
            <ProtectedRoute>
              <Layout>
                <Dashboard />
              </Layout>
            </ProtectedRoute>
          } />
          <Route path="/screener" element={
            <ProtectedRoute>
              <Layout>
                <Screener />
              </Layout>
            </ProtectedRoute>
          } />
          <Route path="/pmcc" element={
            <ProtectedRoute>
              <Layout>
                <PMCC />
              </Layout>
            </ProtectedRoute>
          } />
          <Route path="/portfolio" element={
            <ProtectedRoute>
              <Layout>
                <Portfolio />
              </Layout>
            </ProtectedRoute>
          } />
          <Route path="/simulator" element={
            <ProtectedRoute>
              <Layout>
                <Simulator />
              </Layout>
            </ProtectedRoute>
          } />
          <Route path="/watchlist" element={
            <ProtectedRoute>
              <Layout>
                <Watchlist />
              </Layout>
            </ProtectedRoute>
          } />
          
          {/* Admin only route - full admin panel */}
          <Route path="/admin" element={
            <AdminRoute>
              <Layout>
                <Admin />
              </Layout>
            </AdminRoute>
          } />
          
          {/* Support staff route - limited support panel */}
          <Route path="/support" element={
            <SupportRoute>
              <Layout>
                <SupportPanel />
              </Layout>
            </SupportRoute>
          } />
          
          <Route path="/pricing" element={
            <ProtectedRoute>
              <Layout>
                <Pricing />
              </Layout>
            </ProtectedRoute>
          } />
          
          {/* Public pages */}
          <Route path="/terms" element={<Terms />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/accept-invitation" element={<AcceptInvitation />} />
          
          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster 
          position="top-right" 
          toastOptions={{
            style: {
              background: '#18181b',
              border: '1px solid rgba(255,255,255,0.1)',
              color: '#fff'
            }
          }}
        />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
