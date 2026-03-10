import { useEffect, useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { CheckCircle, Mail } from 'lucide-react';
import { Button } from '../components/ui/button';

const PayPalSuccess = () => {
  const [searchParams] = useSearchParams();
  const [countdown, setCountdown] = useState(5);
  const plan = searchParams.get('plan') || 'standard';
  const cycle = searchParams.get('cycle') || 'monthly';
  const status = searchParams.get('status') || 'active';
  const token = searchParams.get('token');

  useEffect(() => {
    if (token) {
      localStorage.setItem('token', token);
      // Countdown only when we have a token (auto-login to dashboard)
      const interval = setInterval(() => {
        setCountdown(c => {
          if (c <= 1) {
            clearInterval(interval);
            window.location.href = '/dashboard';
            return 0;
          }
          return c - 1;
        });
      }, 1000);
      return () => clearInterval(interval);
    }
    // No token — stay on this page, don't redirect anywhere
  }, [token]);

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

        {token ? (
          <>
            <p className="text-zinc-500 text-sm mb-8">
              Redirecting to dashboard in {countdown} seconds...
            </p>
            <Button
              onClick={() => { window.location.href = '/dashboard'; }}
              className="bg-emerald-600 hover:bg-emerald-700 text-white px-8"
            >
              Go to Dashboard
            </Button>
          </>
        ) : (
          <div className="space-y-4 mt-6">
            <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-4 text-left">
              <div className="flex items-center gap-2 mb-2">
                <Mail className="w-5 h-5 text-emerald-400 flex-shrink-0" />
                <p className="text-white font-semibold text-sm">Your account has been created</p>
              </div>
              <p className="text-zinc-400 text-sm leading-relaxed">
                We've created an account using your PayPal email address.
                Use <span className="text-emerald-400 font-medium">"Forgot Password"</span> on
                the login page to set your password and access the dashboard.
              </p>
            </div>
            <Link to="/login">
              <Button className="bg-emerald-600 hover:bg-emerald-700 text-white px-8 w-full">
                Go to Login &amp; Set Password
              </Button>
            </Link>
          </div>
        )}
      </div>
    </div>
  );
};

export default PayPalSuccess;
