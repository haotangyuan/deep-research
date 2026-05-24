import axios, { AxiosHeaders, AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { getToken, onTokenChange } from './auth';

const getDefaultOrigin = () => {
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }
  return 'http://localhost:8080';
};

const API_ROOT = import.meta.env.API_BASE_URL || getDefaultOrigin();
const RESEARCH_BASE_URL = `${API_ROOT}/api/v1/research`;
const MODEL_BASE_URL = `${API_ROOT}/api/v1/models`;

// Backend Result wrapper
interface Result<T> {
  code: number;
  message: string;
  data: T;
}

export interface CreateResearchResponse {
  researchIds: string[];
}

export interface SendMessageRequest {
  content: string;
  modelId?: string;
  budget?: 'MEDIUM' | 'HIGH' | 'ULTRA';
}

export interface SendMessageResponse {
  id: string;
  content: string;
}

export interface ResearchStatusResponse {
  id: string;
  status: string;
  title?: string;
  modelId?: string;
  budget?: string;
  startTime?: string;
  completeTime?: string;
  totalInputTokens?: number;
  totalOutputTokens?: number;
}

export interface ChatMessage {
  id: number;
  researchId: string;
  role: 'user' | 'assistant';
  content: string;
  sequenceNo?: number;
  createTime: string;
}

export interface WorkflowEvent {
  id: number;
  researchId: string;
  type: string; // e.g., 'SCOPE', 'SUPERVISOR', 'RESEARCHER'
  title: string;
  content: string;
  parentEventId?: number;
  sequenceNo?: number;
  createTime: string;
}

export interface ResearchMessageResponse {
  id: string;
  status: string;
  messages: ChatMessage[];
  events: WorkflowEvent[];
  startTime?: string;
  updateTime?: string;
  completeTime?: string;
  totalInputTokens?: number;
  totalOutputTokens?: number;
}

export interface ModelInfo {
  id: string;
  type: string;
  name: string;
  model: string;
  baseUrl?: string;
}

export interface AddModelRequest {
  name?: string;
  model: string;
  baseUrl: string;
  apiKey: string;
}

const researchClient = axios.create({
  baseURL: RESEARCH_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

const modelApiInstance = axios.create({
  baseURL: MODEL_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
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

const syncInstanceDefaults = (instance: AxiosInstance, token: string | null) => {
  const headers = (instance.defaults.headers.common = AxiosHeaders.from(instance.defaults.headers.common as any));
  applyAuthorizationHeader(headers, token);
};

const bootstrapToken = getToken();
syncInstanceDefaults(researchClient, bootstrapToken);
syncInstanceDefaults(modelApiInstance, bootstrapToken);

onTokenChange((token) => {
  syncInstanceDefaults(researchClient, token);
  syncInstanceDefaults(modelApiInstance, token);
});

// Add auth token to all requests
const addAuthInterceptor = (apiInstance: AxiosInstance) => {
  apiInstance.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const token = getToken();
    if (token) {
      const headers = (config.headers = AxiosHeaders.from(config.headers as any));
      applyAuthorizationHeader(headers, token);
    }
    return config;
  });
};

addAuthInterceptor(researchClient);
addAuthInterceptor(modelApiInstance);

export const modelApi = {
  getAvailableModels: async (): Promise<ModelInfo[]> => {
    const response = await modelApiInstance.get<Result<ModelInfo[]>>(``);
    if (response.data.code !== 0) return [];
    return response.data.data;
  },

  addCustomModel: async (req: AddModelRequest): Promise<string> => {
    const response = await modelApiInstance.post<Result<string>>(``, req);
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Failed to add model');
    }
    return response.data.data;
  },

  deleteCustomModel: async (modelId: string): Promise<void> => {
    const response = await modelApiInstance.delete<Result<string>>(`/${modelId}`);
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Failed to delete model');
    }
  },
};

export const researchApi = {
  create: async (num: number = 1): Promise<CreateResearchResponse> => {
    const response = await researchClient.get<Result<CreateResearchResponse>>(`/create?num=${num}`);
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Failed to create research');
    }
    return response.data.data;
  },

  sendMessage: async (researchId: string, content: string, modelConfig?: Partial<SendMessageRequest>): Promise<SendMessageResponse> => {
    const payload: SendMessageRequest = { content, ...modelConfig };
    const response = await researchClient.post<Result<SendMessageResponse>>(`/${researchId}/messages`, payload);
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Failed to send message');
    }
    return response.data.data;
  },

  getStatus: async (researchId: string): Promise<ResearchStatusResponse> => {
    const response = await researchClient.get<Result<ResearchStatusResponse>>(`/${researchId}`);
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Failed to get status');
    }
    return response.data.data;
  },

  getMessages: async (researchId: string): Promise<ResearchMessageResponse> => {
    const response = await researchClient.get<Result<ResearchMessageResponse>>(`/${researchId}/messages`);
    if (response.data.code !== 0) {
      throw new Error(response.data.message || 'Failed to get messages');
    }
    return response.data.data;
  },

  getHistory: async (): Promise<ResearchStatusResponse[]> => {
    const response = await researchClient.get<Result<ResearchStatusResponse[]>>(`/list`);
    if (response.data.code !== 0) {
       // If API doesn't exist yet, return empty list to avoid breaking UI
       // throw new Error(response.data.message || 'Failed to get history');
       return [];
    }
    return response.data.data;
  },
  
  getSseUrl: () => `${RESEARCH_BASE_URL}/sse`
};
