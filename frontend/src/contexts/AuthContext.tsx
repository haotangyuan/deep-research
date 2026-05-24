import { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from 'react';
import { authService, getToken, setToken, removeToken, UserInfo, GOOGLE_CLIENT_ID } from '../services/auth';

type GoogleIdConfig = {
  client_id: string;
  callback: (response: { credential: string }) => void;
  auto_select?: boolean;
  cancel_on_tap_outside?: boolean;
  use_fedcm_for_prompt?: boolean;
};

interface AuthContextType {
  user: UserInfo | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  loginWithGoogle: (credential: string) => Promise<void>;
  startGoogleOAuth: () => void;
  logout: () => void;
  openAuthModal: () => void;
  closeAuthModal: () => void;
  isAuthModalOpen: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const googleReadyRef = useRef(false);
  const oneTapRetryRef = useRef(0);

  const hideGoogleOneTap = useCallback(() => {
    if (typeof google !== 'undefined' && google.accounts?.id) {
      const googleId = google.accounts.id as typeof google.accounts.id & { enableAutoSelect?: () => void };
      googleId.cancel();
      if (typeof googleId.disableAutoSelect === 'function') {
        googleId.disableAutoSelect();
      }
    }
  }, []);

  const promptGoogleOneTap = useCallback(function promptFn() {
    if (!googleReadyRef.current || typeof google === 'undefined' || !google.accounts?.id || user) {
      return;
    }
    google.accounts.id.prompt((notification: { isNotDisplayed: () => boolean; isSkippedMoment: () => boolean }) => {
      const notDisplayed = notification.isNotDisplayed?.();
      const skipped = notification.isSkippedMoment?.();
      if ((notDisplayed || skipped) && oneTapRetryRef.current < 3) {
        oneTapRetryRef.current += 1;
        setTimeout(() => {
          promptFn();
        }, 1500);
      }
      if (!notDisplayed && !skipped) {
        oneTapRetryRef.current = 0;
      }
    });
  }, [user]);

  const fetchUser = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }

    try {
      const userInfo = await authService.getMe();
      setUser(userInfo);
    } catch (error) {
      console.error('Failed to fetch user:', error);
      removeToken();
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  useEffect(() => {
    if (!user && isAuthModalOpen) {
      promptGoogleOneTap();
    }
  }, [isAuthModalOpen, user, promptGoogleOneTap]);

  const login = async (username: string, password: string) => {
    const response = await authService.login(username, password);
    setToken(response.token);
    await fetchUser();
    setIsAuthModalOpen(false);
    hideGoogleOneTap();
    // Refresh history list after login
    window.dispatchEvent(new Event('refreshHistory'));
  };

  const register = async (username: string, password: string) => {
    const response = await authService.register(username, password);
    setToken(response.token);
    await fetchUser();
    setIsAuthModalOpen(false);
    hideGoogleOneTap();
    // Refresh history list after register
    window.dispatchEvent(new Event('refreshHistory'));
  };

  const loginWithGoogle = async (credential: string) => {
    const response = await authService.googleOneTap(credential);
    setToken(response.token);
    await fetchUser();
    setIsAuthModalOpen(false);
    hideGoogleOneTap();
    // Refresh history list after Google login
    window.dispatchEvent(new Event('refreshHistory'));
  };

  // Initialize Google One Tap - only when NOT loading and NOT authenticated
  useEffect(() => {
    // Wait for auth check to complete and only show One Tap if not logged in
    if (!GOOGLE_CLIENT_ID || isLoading || user) {
      // Cancel any existing One Tap prompt if user is logged in
      if (user) {
        hideGoogleOneTap();
      }
      return;
    }

    const initializeGoogleOneTap = () => {
      if (typeof google === 'undefined' || !google.accounts) return;

      const config: GoogleIdConfig = {
        client_id: GOOGLE_CLIENT_ID,
        callback: async (response: { credential: string }) => {
          try {
            await loginWithGoogle(response.credential);
          } catch (error) {
            console.error('Google One Tap login failed:', error);
          }
        },
        auto_select: false,
        cancel_on_tap_outside: false,
        use_fedcm_for_prompt: true,
      };

      google.accounts.id.initialize(config);
      googleReadyRef.current = true;
      oneTapRetryRef.current = 0;
      promptGoogleOneTap();
    };

    // Load Google Identity Services script
    const script = document.getElementById('google-gsi-script');
    if (script) {
      initializeGoogleOneTap();
    } else {
      const newScript = document.createElement('script');
      newScript.id = 'google-gsi-script';
      newScript.src = 'https://accounts.google.com/gsi/client';
      newScript.async = true;
      newScript.defer = true;
      newScript.onload = initializeGoogleOneTap;
      document.head.appendChild(newScript);
    }
  }, [isLoading, user, hideGoogleOneTap, promptGoogleOneTap, loginWithGoogle]);

  const startGoogleOAuth = () => {
    const url = authService.getGoogleAuthUrl();
    if (!url) {
      console.error('Google OAuth URL 未配置');
      return;
    }
    window.location.href = url;
  };

  const logout = () => {
    authService.logout();
    setUser(null);
    // Allow One Tap to show again after logout
    if (typeof google !== 'undefined' && google.accounts?.id) {
      const googleId = google.accounts.id as typeof google.accounts.id & { enableAutoSelect?: () => void };
      googleId.cancel();
      if (typeof googleId.enableAutoSelect === 'function') {
        googleId.enableAutoSelect();
      }
    }
  };

  const openAuthModal = () => setIsAuthModalOpen(true);
  const closeAuthModal = () => setIsAuthModalOpen(false);

  // Auto-open auth modal when not logged in (after loading completes)
  useEffect(() => {
    if (!isLoading && !user) {
      setIsAuthModalOpen(true);
    }
  }, [isLoading, user]);

  useEffect(() => {
    if (user) {
      hideGoogleOneTap();
    }
  }, [user, hideGoogleOneTap]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        register,
        loginWithGoogle,
        startGoogleOAuth,
        logout,
        openAuthModal,
        closeAuthModal,
        isAuthModalOpen,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
