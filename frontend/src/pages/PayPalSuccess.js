import { useEffect } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { CheckCircle } from 'lucide-react';
import { Button } from '../components/ui/button';

const PayPalSuccess = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const plan = searchParams.get('plan') || 'standard';
  const cycle = searchParams.get('cycle') || 'monthly';
  const status = searchParams.get('status') || 'active';
  const token = searchParams.get('token');

  useEffect(() => {
    // Store token to auto-login the user
    if (token) {
      localStorage.setItem('token', token);
    }
    // Auto-redirect after 5 seconds
    const timer = setTimeout(() => {
      if (token) {
        window.location.href = '/dashboard';
      } else {
        navigate('/login');
      }
    }, 5000);
    return () => clearTimeout(timer);
  }, [token, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950">
      <div className="text-center max-w-md mx-auto p-8">
        <div className="flex justify-center mb-6">
          <CheckCircle className="w-20 h-20 text-emerald-400" />
        </div>
        <h1 className="text-3xl font-bold text-white mb-3">
          {status === 'trialing' ? 'Trial Started!' : 'Subscription Activated!'}
        </h1>
        <p className="text-zinc-400 mb-2">
          Your <span className="text-white font-semibold capitalize">{plan}</span> plan ({cycle}) is now active.
        </p>
        {status === 'trialing' && (
          <p className="text-emerald-400 text-sm mb-2">
            Your 7-day free trial has started. You won't be charged until the trial ends.
          </p>
        )}
        <p className="text-zinc-500 text-sm mb-8">
          Redirecting in 5 seconds...
        </p>
        {token ? (
          <Button
            onClick={() => { window.location.href = '/dashboard'; }}
            className="bg-emerald-600 hover:bg-emerald-700 text-white px-8"
          >
            Go to Dashboard
          </Button>
        ) : (
          <div className="space-y-3">
            <Link to="/login">
              <Button className="bg-emerald-600 hover:bg-emerald-700 text-white px-8 w-full">
                Log In to Dashboard
              </Button>
            </Link>
            <p className="text-zinc-500 text-xs">
              Use "Forgot Password" on the login page to set your password.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default PayPalSuccess;
