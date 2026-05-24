import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import { authService, setToken } from '../services/auth';

export function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get('code');
    
    if (!code) {
      setStatus('error');
      setError('No authorization code received');
      return;
    }

    const handleCallback = async () => {
      try {
        const response = await authService.googleCallback(code);
        setToken(response.token);
        setStatus('success');
        
        // Redirect to home after a short delay
        setTimeout(() => {
          navigate('/', { replace: true });
          window.location.reload(); // Refresh to update auth state
        }, 1000);
      } catch (err: any) {
        setStatus('error');
        setError(err.message || 'Failed to complete authentication');
      }
    };

    handleCallback();
  }, [searchParams, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-2xl shadow-lg p-8 max-w-sm w-full mx-4 text-center">
        {status === 'loading' && (
          <>
            <Loader2 className="w-12 h-12 text-gray-400 animate-spin mx-auto mb-4" />
            <h2 className="text-lg font-semibold text-gray-900 mb-1">Signing you in...</h2>
            <p className="text-sm text-gray-500">Please wait while we complete authentication</p>
          </>
        )}

        {status === 'success' && (
          <>
            <div className="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <CheckCircle2 className="w-6 h-6 text-green-600" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900 mb-1">Success!</h2>
            <p className="text-sm text-gray-500">Redirecting you to the app...</p>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <AlertCircle className="w-6 h-6 text-red-600" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900 mb-1">Authentication Failed</h2>
            <p className="text-sm text-red-600 mb-4">{error}</p>
            <button
              onClick={() => navigate('/', { replace: true })}
              className="px-4 py-2 bg-black text-white text-sm font-medium rounded-lg hover:bg-gray-800 transition-colors"
            >
              Back to Home
            </button>
          </>
        )}
      </div>
    </div>
  );
}
