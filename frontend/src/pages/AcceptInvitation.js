/**
 * AcceptInvitation - Page for users to accept invitations and create accounts
 */
import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { CheckCircle, XCircle, Loader2, Shield, Eye, EyeOff } from 'lucide-react';
import { toast } from 'sonner';

export default function AcceptInvitation() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token');
  
  const [loading, setLoading] = useState(true);
  const [invitation, setInvitation] = useState(null);
  const [error, setError] = useState(null);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (!token) {
      setError('Invalid invitation link. No token provided.');
      setLoading(false);
      return;
    }
    
    verifyToken();
  }, [token]);

  const verifyToken = async () => {
    try {
      const response = await api.get(`/invitations/verify/${token}`);
      setInvitation(response.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid or expired invitation link.');
    } finally {
      setLoading(false);
    }
  };

  const handleAccept = async (e) => {
    e.preventDefault();
    
    if (password.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }
    
    if (password !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }
    
    setAccepting(true);
    try {
      await api.post(`/invitations/accept/${token}?password=${encodeURIComponent(password)}`);
      setSuccess(true);
      toast.success('Account created successfully!');
      
      // Redirect to login after 3 seconds
      setTimeout(() => {
        navigate('/login');
      }, 3000);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create account');
    } finally {
      setAccepting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
        <Card className="glass-card w-full max-w-md">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
            <p className="mt-4 text-zinc-400">Verifying invitation...</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
        <Card className="glass-card w-full max-w-md">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <div className="p-4 rounded-full bg-red-500/20 mb-4">
              <XCircle className="w-8 h-8 text-red-400" />
            </div>
            <h2 className="text-xl font-semibold text-white mb-2">Invalid Invitation</h2>
            <p className="text-zinc-400 text-center mb-6">{error}</p>
            <Button onClick={() => navigate('/')} variant="outline">
              Go to Homepage
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (success) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
        <Card className="glass-card w-full max-w-md">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <div className="p-4 rounded-full bg-emerald-500/20 mb-4">
              <CheckCircle className="w-8 h-8 text-emerald-400" />
            </div>
            <h2 className="text-xl font-semibold text-white mb-2">Account Created!</h2>
            <p className="text-zinc-400 text-center mb-2">
              Your account has been created successfully.
            </p>
            <p className="text-zinc-500 text-sm">
              Redirecting to login...
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <Card className="glass-card w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto p-3 rounded-full bg-emerald-500/20 mb-4 w-fit">
            <Shield className="w-8 h-8 text-emerald-400" />
          </div>
          <CardTitle className="text-2xl text-white">Accept Invitation</CardTitle>
          <CardDescription>
            Create your account to join Covered Call Engine
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Invitation Details */}
          <div className="p-4 rounded-lg bg-zinc-800/50 border border-zinc-700 mb-6">
            <div className="flex items-center justify-between mb-3">
              <span className="text-zinc-400 text-sm">Invited as</span>
              <Badge className="bg-emerald-500/20 text-emerald-400">
                {invitation?.role_label}
              </Badge>
            </div>
            <div className="space-y-2">
              <div>
                <span className="text-zinc-500 text-xs">Name</span>
                <p className="text-white">{invitation?.name}</p>
              </div>
              <div>
                <span className="text-zinc-500 text-xs">Email</span>
                <p className="text-white">{invitation?.email}</p>
              </div>
            </div>
          </div>

          {/* Password Form */}
          <form onSubmit={handleAccept} className="space-y-4">
            <div>
              <Label className="text-zinc-400">Create Password</Label>
              <div className="relative mt-2">
                <Input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input-dark pr-10"
                  placeholder="Minimum 8 characters"
                  required
                  minLength={8}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-white"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            
            <div>
              <Label className="text-zinc-400">Confirm Password</Label>
              <Input
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="input-dark mt-2"
                placeholder="Re-enter password"
                required
              />
            </div>

            <Button
              type="submit"
              disabled={accepting || password.length < 8}
              className="w-full bg-emerald-600 hover:bg-emerald-700 mt-6"
            >
              {accepting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Creating Account...
                </>
              ) : (
                'Create Account & Join'
              )}
            </Button>
          </form>

          <p className="text-xs text-zinc-500 text-center mt-4">
            By creating an account, you agree to our{' '}
            <a href="/terms" className="text-emerald-400 hover:underline">Terms of Service</a>
            {' '}and{' '}
            <a href="/privacy" className="text-emerald-400 hover:underline">Privacy Policy</a>.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
