import { useState, useEffect, useRef } from 'react';
import { X, Lock, User, Loader2, AlertCircle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { GOOGLE_CLIENT_ID } from '../services/auth';

type AuthMode = 'login' | 'register';

export function AuthModal() {
  const { isAuthModalOpen, closeAuthModal, login, register, loginWithGoogle, startGoogleOAuth } = useAuth();
  const [mode, setMode] = useState<AuthMode>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isGoogleButtonReady, setGoogleButtonReady] = useState(false);
  const googleButtonRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isAuthModalOpen) {
      setUsername('');
      setPassword('');
      setError(null);
      setGoogleButtonReady(false);
    }
  }, [isAuthModalOpen]);

  // Render Google Sign-In button
  useEffect(() => {
    if (!isAuthModalOpen || !GOOGLE_CLIENT_ID || !googleButtonRef.current) return;

    const renderButton = () => {
      if (typeof google === 'undefined' || !google.accounts) return;

      google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (response) => {
          setIsLoading(true);
          setError(null);
          try {
            await loginWithGoogle(response.credential);
          } catch (err: any) {
            setError(err.message || 'Google login failed');
          } finally {
            setIsLoading(false);
          }
        },
      });

      if (googleButtonRef.current) {
        googleButtonRef.current.innerHTML = '';
      }

      google.accounts.id.renderButton(googleButtonRef.current!, {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        text: 'continue_with',
        shape: 'rectangular',
        width: 320,
      });

      setGoogleButtonReady(true);
    };

    // Wait for Google script to load
    const checkGoogle = setInterval(() => {
      if (typeof google !== 'undefined' && google.accounts) {
        clearInterval(checkGoogle);
        renderButton();
      }
    }, 100);

    return () => clearInterval(checkGoogle);
  }, [isAuthModalOpen, loginWithGoogle]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;

    setIsLoading(true);
    setError(null);

    try {
      if (mode === 'login') {
        await login(username, password);
      } else {
        await register(username, password);
      }
    } catch (err: any) {
      setError(err.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  if (!isAuthModalOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={closeAuthModal}
      />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Close button */}
        <button
          onClick={closeAuthModal}
          className="absolute top-4 right-4 p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors z-10"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="p-8">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="w-12 h-12 bg-black rounded-xl flex items-center justify-center mx-auto mb-4">
              <User className="w-6 h-6 text-white" />
            </div>
            <h2 className="text-2xl font-semibold text-gray-900">
              {mode === 'login' ? '欢迎回来' : '创建账户'}
            </h2>
            <p className="text-gray-500 mt-1 text-sm">
              {mode === 'login' 
                ? '登录以继续您的研究' 
                : '开始使用 Deep Research'}
            </p>
          </div>

          {/* Google Sign-In */}
          {GOOGLE_CLIENT_ID && (
            <>
              <div 
                ref={googleButtonRef} 
                className="flex justify-center mb-4"
              />

              {!isGoogleButtonReady && (
                <button
                  type="button"
                  onClick={startGoogleOAuth}
                  className="w-full mb-6 py-2.5 border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-center gap-2"
                >
                  <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google" className="w-4 h-4" />
                  使用 Google 账号登录
                </button>
              )}

              <div className="relative mb-6">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-gray-200" />
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-white px-3 text-gray-400">或</span>
                </div>
              </div>
            </>
          )}

          {/* Error */}
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-100 rounded-lg flex items-center gap-2 text-sm text-red-600">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                用户名
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入用户名"
                  className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-black/5 focus:border-gray-300 transition-colors"
                  disabled={isLoading}
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                密码
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-black/5 focus:border-gray-300 transition-colors"
                  disabled={isLoading}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading || !username.trim() || !password.trim()}
              className="w-full py-2.5 bg-black text-white text-sm font-medium rounded-lg hover:bg-gray-800 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {mode === 'login' ? '登录中...' : '创建中...'}
                </>
              ) : (
                mode === 'login' ? '登录' : '创建账户'
              )}
            </button>
          </form>

          {/* Toggle mode */}
          <div className="mt-6 pt-4 border-t border-gray-100">
            {mode === 'login' ? (
              <div className="text-center">
                <span className="text-sm text-gray-600">还没有账户？</span>
                <button
                  onClick={() => { setMode('register'); setError(null); }}
                  className="ml-2 text-sm font-semibold text-black hover:underline"
                >
                  立即注册
                </button>
              </div>
            ) : (
              <div className="text-center">
                <span className="text-sm text-gray-600">已有账户？</span>
                <button
                  onClick={() => { setMode('login'); setError(null); }}
                  className="ml-2 text-sm font-semibold text-black hover:underline"
                >
                  立即登录
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
