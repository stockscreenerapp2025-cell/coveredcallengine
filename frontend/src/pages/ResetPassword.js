import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Activity, Eye, EyeOff, AlertCircle, CheckCircle } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';

const APP_NAME = "Covered Call Engine";
const API_URL = process.env.REACT_APP_API_URL || '';

const ResetPassword = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [mode, setMode] = useState(token ? 'reset' : 'forgot'); // 'forgot' | 'reset' | 'done'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Handle login page messages
  useEffect(() => {
    const activated = searchParams.get('activated');
    const err = searchParams.get('error');
    if (activated === 'true') {
      toast.success('Account activated! You can now log in.');
    }
    if (err === 'invalid_token') {
      setError('Invalid or expired activation link. Please request a new one.');
    }
    if (err === 'token_expired') {
      setError('Activation link expired. Please request a new one.');
    }
  }, []);

  const handleForgotPassword = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await axios.post(`${API_URL}/api/auth/forgot-password`, { email });
      setSuccess('Reset link sent! Please check your email inbox.');
      setMode('done');
      toast.success('Reset link sent!');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Something went wrong. Please try again.';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API_URL}/api/auth/reset-password`, { token, new_password: password });
      setSuccess('Password reset successfully!');
      setMode('done');
      toast.success('Password reset! Redirecting to login...');
      setTimeout(() => navigate('/login'), 2500);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Invalid or expired reset link.';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#09090b] flex items-center justify-center p-4 grid-bg">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <Link to="/" className="inline-flex items-center gap-2">
            <Activity className="w-10 h-10 text-emerald-500" />
            <span className="text-2xl font-bold text-white">{APP_NAME}</span>
          </Link>
        </div>

        <div className="glass-card p-8">
          {/* Done state */}
          {mode === 'done' && (
            <div className="text-center">
              <CheckCircle className="w-16 h-16 text-emerald-500 mx-auto mb-4" />
              <h1 className="text-2xl font-bold text-white mb-2">
                {token ? 'Password Reset!' : 'Check Your Email'}
              </h1>
              <p className="text-zinc-400 mb-6">{success}</p>
              <Link to="/login">
                <Button className="w-full btn-primary">Back to Login</Button>
              </Link>
            </div>
          )}

          {/* Forgot password form */}
          {mode === 'forgot' && (
            <>
              <h1 className="text-2xl font-bold text-white text-center mb-2">Forgot Password</h1>
              <p className="text-zinc-400 text-center mb-8">Enter your email and we'll send a reset link</p>
              {error && (
                <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-3">
                  <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
                  <span className="text-sm text-red-400">{error}</span>
                </div>
              )}
              <form onSubmit={handleForgotPassword} className="space-y-6">
                <div className="form-group">
                  <Label htmlFor="email" className="form-label">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    required
                    className="form-input"
                  />
                </div>
                <Button type="submit" className="w-full btn-primary" disabled={loading}>
                  {loading ? 'Sending...' : 'Send Reset Link'}
                </Button>
              </form>
              <p className="text-center text-zinc-400 text-sm mt-6">
                Remember your password?{' '}
                <Link to="/login" className="text-emerald-400 hover:text-emerald-300 font-medium">Sign in</Link>
              </p>
            </>
          )}

          {/* Reset password form */}
          {mode === 'reset' && (
            <>
              <h1 className="text-2xl font-bold text-white text-center mb-2">Set New Password</h1>
              <p className="text-zinc-400 text-center mb-8">Enter your new password below</p>
              {error && (
                <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-3">
                  <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
                  <span className="text-sm text-red-400">{error}</span>
                </div>
              )}
              <form onSubmit={handleResetPassword} className="space-y-6">
                <div className="form-group">
                  <Label htmlFor="password" className="form-label">New Password</Label>
                  <div className="relative">
                    <Input
                      id="password"
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Min. 8 characters"
                      required
                      className="form-input pr-10"
                    />
                    <button type="button" onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white">
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div className="form-group">
                  <Label htmlFor="confirmPassword" className="form-label">Confirm Password</Label>
                  <Input
                    id="confirmPassword"
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Repeat new password"
                    required
                    className="form-input"
                  />
                </div>
                <Button type="submit" className="w-full btn-primary" disabled={loading}>
                  {loading ? 'Resetting...' : 'Reset Password'}
                </Button>
              </form>
              <p className="text-center text-zinc-400 text-sm mt-6">
                <Link to="/login" className="text-emerald-400 hover:text-emerald-300 font-medium">Back to Login</Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default ResetPassword;
