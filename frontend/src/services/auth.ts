import axios, { AxiosHeaders } from 'axios';

const getDefaultOrigin = () => {
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }
  return 'http://localhost:8080';
};

const API_ROOT = import.meta.env.API_BASE_URL || getDefaultOrigin();
const API_BASE_URL = `${API_ROOT}/api/v1/user`;

interface Result<T> {
  code: number;
  message: string;
  data: T;
}

export interface AuthResponse {
  token: string;
}

export interface UserInfo {
  avatarUrl: string;
}

type TokenListener = (token: string | null) => void;

let inMemoryToken: string | null = null;
const tokenListeners = new Set<TokenListener>();

const readStoredToken = (): string | null => {
  if (typeof window === 'undefined' || !window.localStorage) {
    return null;
  }
  try {
    return window.localStorage.getItem('token');
  } catch {
    return null;
  }
};

const writeStoredToken = (token: string | null) => {
  if (typeof window === 'undefined' || !window.localStorage) {
    return;
  }
  try {
    if (token) {
      window.localStorage.setItem('token', token);
    } else {
      window.localStorage.removeItem('token');
    }
  } catch {
    // 忽略存储异常，后续请求仍可从内存中读取 token
  }
};

const notifyTokenListeners = (token: string | null) => {
  tokenListeners.forEach((listener) => listener(token));
};

export const onTokenChange = (listener: TokenListener) => {
  tokenListeners.add(listener);
  return () => tokenListeners.delete(listener);
};

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === 'token') {
      inMemoryToken = event.newValue;
      notifyTokenListeners(event.newValue);
    }
  });
}

export const getToken = (): string | null => {
  if (inMemoryToken !== null) {
    return inMemoryToken;
  }
  inMemoryToken = readStoredToken();
  return inMemoryToken;
};

export const setToken = (token: string) => {
  inMemoryToken = token;
  writeStoredToken(token);
  notifyTokenListeners(token);
};

export const removeToken = () => {
  inMemoryToken = null;
  writeStoredToken(null);
  notifyTokenListeners(null);
};

export const isAuthenticated = () => !!getToken();

// Create axios instance with auth header
const authApi = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

const applyAuthorizationHeader = (headers: any, token: string | null) => {
  if (!headers) return;
  if (token) {
    if (typeof headers.set === 'function') {
      headers.set('Authorization', `Bearer ${token}`);
    } else {
      headers.Authorization = `Bearer ${token}`;
    }
  } else if (typeof headers.delete === 'function') {
    headers.delete('Authorization');
  } else if (headers.Authorization) {
    delete headers.Authorization;
  }
};

// Add auth token to requests
authApi.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    const headers = (config.headers = AxiosHeaders.from(config.headers as any));
    applyAuthorizationHeader(headers, token);
  }
  return config;
});

const syncAuthApiDefaults = (token: string | null) => {
  const headers = (authApi.defaults.headers.common = AxiosHeaders.from(authApi.defaults.headers.common as any));
  applyAuthorizationHeader(headers, token);
};

syncAuthApiDefaults(getToken());
onTokenChange(syncAuthApiDefaults);

export const authService = {
  register: async (username: string, password: string): Promise<AuthResponse> => {
    const response = await authApi.post<Result<AuthResponse>>('/register', { username, password });
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Registration failed');
    }
    return response.data.data;
  },

  login: async (username: string, password: string): Promise<AuthResponse> => {
    const response = await authApi.post<Result<AuthResponse>>('/login', { username, password });
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Login failed');
    }
    return response.data.data;
  },

  getMe: async (): Promise<UserInfo> => {
    const response = await authApi.get<Result<UserInfo>>('/me');
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Failed to get user info');
    }
    return response.data.data;
  },

  logout: () => {
    removeToken();
  },
};
