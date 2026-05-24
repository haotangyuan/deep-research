import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Routes, Route, Navigate, useNavigate, useParams, Link, useLocation } from 'react-router-dom';
import { Plus, Loader2, Send, AlertCircle, Sparkles, Search, Brain, Globe, FileSearch, Zap, User, Bot, CheckCircle2, ChevronDown, PanelLeftClose, PanelLeftOpen, MessageSquare, Clock, Coins, ChevronsUpDown, RefreshCw, Shield, Copy } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { researchApi, modelApi, ResearchStatusResponse, ChatMessage, WorkflowEvent, ModelInfo, SendMessageRequest } from './services/api';
import { getToken } from './services/auth';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { AuthModal } from './components/AuthModal';
import { UserMenu } from './components/UserMenu';
import { OAuthCallback } from './pages/OAuthCallback';
import { ModelManagerModal } from './components/ModelManagerModal';
import { BUDGET_OPTIONS, BudgetValue } from './constants/budget';
import ArenaPage from './pages/ArenaPage';

// --- Types & Helpers ---

type ViewState = 'home' | 'loading' | 'chat' | 'failed';

interface ResearchState {
  id: string;
  title: string;
  modelId?: string;
  budget?: string;
  status: string;
  messages: ChatMessage[];
  events: WorkflowEvent[];
  startTime?: string;
  completeTime?: string;
  totalInputTokens?: number;
  totalOutputTokens?: number;
}

type TimelineItem = 
  | { type: 'message'; data: ChatMessage }
  | { type: 'event_group'; events: EventNode[] };

interface EventNode extends WorkflowEvent {
  children: EventNode[];
  depth: number;
}

function buildEventTree(events: WorkflowEvent[]): EventNode[] {
  const nodeMap = new Map<number, EventNode>();
  const roots: EventNode[] = [];

  events.forEach(evt => {
    nodeMap.set(evt.id, { ...evt, children: [], depth: 0 });
  });

  events.forEach(evt => {
    const node = nodeMap.get(evt.id)!;
    if (evt.parentEventId && nodeMap.has(evt.parentEventId)) {
      const parent = nodeMap.get(evt.parentEventId)!;
      node.depth = parent.depth + 1;
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

function flattenTree(nodes: EventNode[]): EventNode[] {
  const result: EventNode[] = [];
  const traverse = (node: EventNode) => {
    result.push(node);
    node.children.forEach(traverse);
  };
  nodes.forEach(traverse);
  return result;
}

function getEventStyle(type: string) {
  switch (type?.toUpperCase()) {
    case 'SCOPE': return { icon: Brain, color: 'text-purple-600', bg: 'bg-purple-50' };
    case 'SUPERVISOR': return { icon: Sparkles, color: 'text-pink-600', bg: 'bg-pink-50' };
    case 'RESEARCH': return { icon: Search, color: 'text-blue-600', bg: 'bg-blue-50' };
    case 'SEARCH': return { icon: Globe, color: 'text-green-600', bg: 'bg-green-50' };
    case 'REPORT': return { icon: FileSearch, color: 'text-orange-600', bg: 'bg-orange-50' };
    case 'ERROR': return { icon: AlertCircle, color: 'text-red-600', bg: 'bg-red-50' };
    default: return { icon: Zap, color: 'text-gray-600', bg: 'bg-gray-50' };
  }
}

function getStatusIcon(status: string) {
  switch (status?.toUpperCase()) {
    case 'COMPLETED': return <CheckCircle2 className="w-4 h-4 text-green-500" />;
    case 'FAILED': return <AlertCircle className="w-4 h-4 text-red-500" />;
    case 'NEW': return <div className="w-2 h-2 rounded-full bg-gray-300" />;
    case 'NEED_CLARIFICATION': return <MessageSquare className="w-4 h-4 text-amber-500" />;
    case 'QUEUE':
    case 'START':
    case 'RUNNING':
    case 'IN_SCOPE':
    case 'IN_RESEARCH':
    case 'IN_REPORT':
        return <Loader2 className="w-3 h-3 text-blue-500 animate-spin" />;
    default: return <div className="w-2 h-2 rounded-full bg-gray-300" />;
  }
}

type HistoryUpdateDetail = {
  id: string;
  status?: string;
  title?: string;
};

const REFRESH_HISTORY_EVENT = 'refreshHistory';
const HISTORY_UPDATE_EVENT = 'historyStatusUpdate';

const ACTIVE_HISTORY_STATUSES = new Set([
  'QUEUE',
  'START',
  'RUNNING',
  'IN_SCOPE',
  'IN_RESEARCH',
  'IN_REPORT',
]);

// --- Components ---

function Sidebar({ isOpen, toggle }: { isOpen: boolean; toggle: () => void }) {
  const [history, setHistory] = useState<ResearchStatusResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [modelList, setModelList] = useState<ModelInfo[]>([]);
  const navigate = useNavigate();
  const { id: currentId } = useParams();
  const location = useLocation();
  const { isAuthenticated } = useAuth();
  const historyLoadInFlightRef = useRef(false);
  const pendingHistoryRefreshRef = useRef(false);
  const initialLoadRef = useRef(true);

  // 模型字典用于显示model name
  const modelDictionary = useMemo(() => {
    const map: Record<string, ModelInfo> = {};
    modelList.forEach((model) => {
      map[model.id] = model;
    });
    return map;
  }, [modelList]);

  // 加载模型列表
  useEffect(() => {
    if (!isAuthenticated) {
      setModelList([]);
      return;
    }
    modelApi.getAvailableModels().then(setModelList).catch(console.error);
  }, [isAuthenticated]);
  
  const loadHistory = useCallback(async function loadHistoryInternal(options: { showSpinner?: boolean } = {}) {
    if (historyLoadInFlightRef.current) {
      pendingHistoryRefreshRef.current = true;
      return;
    }
    historyLoadInFlightRef.current = true;
    if (options.showSpinner) {
      setLoading(true);
    }
    try {
      const list = await researchApi.getHistory();
      const filtered = list.filter((item) => item.status?.toUpperCase() !== 'NEW');
      setHistory(filtered);
    } catch (e) {
      console.error('Failed to load history', e);
    } finally {
      historyLoadInFlightRef.current = false;
      setLoading(false);
      if (pendingHistoryRefreshRef.current) {
        pendingHistoryRefreshRef.current = false;
        loadHistoryInternal();
      }
    }
  }, []);

  useEffect(() => {
    loadHistory({ showSpinner: initialLoadRef.current });
    initialLoadRef.current = false;
    const handleRefresh = () => loadHistory();
    window.addEventListener(REFRESH_HISTORY_EVENT, handleRefresh);
    return () => window.removeEventListener(REFRESH_HISTORY_EVENT, handleRefresh);
  }, [location.pathname, loadHistory]);

  const hasActiveHistory = useMemo(() => history.some(item => ACTIVE_HISTORY_STATUSES.has(item.status?.toUpperCase() || '')), [history]);

  useEffect(() => {
    if (!hasActiveHistory) return;
    const intervalId = window.setInterval(() => loadHistory(), 5000);
    return () => window.clearInterval(intervalId);
  }, [hasActiveHistory, loadHistory]);

  useEffect(() => {
    const handleHistoryStatusUpdate = (event: Event) => {
      const detail = (event as CustomEvent<HistoryUpdateDetail>).detail;
      if (!detail) return;
      setHistory(prev => {
        if (!prev || prev.length === 0) return prev;
        let matched = false;
        const next = prev.map(item => {
          if (item.id !== detail.id) return item;
          matched = true;
          return {
            ...item,
            status: detail.status || item.status,
            title: detail.title || item.title,
          };
        });
        return matched ? next : prev;
      });
    };
    window.addEventListener(HISTORY_UPDATE_EVENT, handleHistoryStatusUpdate);
    return () => window.removeEventListener(HISTORY_UPDATE_EVENT, handleHistoryStatusUpdate);
  }, []);

  const isArenaActive = location.pathname.startsWith('/arena');

  return (
    <aside className={`bg-gray-50 border-r border-gray-200 flex flex-col shrink-0 transition-all duration-300 ease-in-out ${isOpen ? 'w-72 translate-x-0' : 'w-0 -translate-x-full opacity-0 overflow-hidden border-r-0'}`}>
      <div className="p-4 border-b border-gray-200 flex justify-between items-center">
        <h1 className="text-lg font-bold text-gray-900 flex items-center gap-2">
          <div className="w-8 h-8 bg-black rounded-lg flex items-center justify-center">
            <Bot className="w-5 h-5 text-white" />
          </div>
          Deep Research
        </h1>
        <button onClick={toggle} className="p-1 hover:bg-gray-200 rounded-md text-gray-500">
            <PanelLeftClose className="w-5 h-5" />
        </button>
      </div>
      
      <div className="p-3 space-y-2">
        <button
          onClick={() => navigate('/new')}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-black text-white text-sm font-medium rounded-lg hover:bg-gray-800 transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Research
        </button>
        <button
          onClick={() => navigate('/arena')}
          className={`w-full flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium rounded-lg border transition-colors ${isArenaActive ? 'bg-white border-black text-black' : 'border-gray-200 text-gray-700 hover:bg-gray-100'}`}
        >
          <Zap className="w-4 h-4" />
          LLM Arena
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3">
        <div className="py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">History</div>
        {loading ? (
          <div className="flex justify-center py-4"><Loader2 className="w-5 h-5 animate-spin text-gray-400" /></div>
        ) : (
          <div className="space-y-1">
            {history.map((item) => {
              const modelInfo = item.modelId ? modelDictionary[item.modelId] : null;
              const modelDisplayName = modelInfo?.name || modelInfo?.model || null;
              return (
                <Link
                  key={item.id}
                  to={`/research/${item.id}`}
                  className={`w-full text-left px-3 py-2 rounded-lg transition-colors block ${
                    currentId === item.id ? 'bg-gray-200 text-gray-900' : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium truncate">{item.title || 'Untitled'}</div>
                      {modelDisplayName && (
                        <div className="text-[11px] text-gray-400 truncate mt-0.5">{modelDisplayName}</div>
                      )}
                    </div>
                    <div className="shrink-0 mt-0.5">
                      {getStatusIcon(item.status)}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* User menu at bottom */}
      <div className="p-3 border-t border-gray-200">
        <UserMenu />
      </div>
    </aside>
  );
}

function ResearchPage({ sidebarOpen = true }: { sidebarOpen?: boolean }) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  
  const [viewState, setViewState] = useState<ViewState>('home');
  const [currentResearch, setCurrentResearch] = useState<ResearchState | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [clientId] = useState(() => {
    const createId = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `client-${Math.random().toString(36).slice(2)}`);
    if (typeof window === 'undefined' || !window.sessionStorage) {
      return createId();
    }
    const cached = window.sessionStorage.getItem('dr-client-id');
    if (cached) return cached;
    const id = createId();
    window.sessionStorage.setItem('dr-client-id', id);
    return id;
  });
  
  // Model state
  const [modelList, setModelList] = useState<ModelInfo[]>([]);
  const [modelListLoading, setModelListLoading] = useState(false);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [isModelManagerOpen, setIsModelManagerOpen] = useState(false);
  const selectedModelInfo = useMemo(() => modelList.find(m => m.id === selectedModelId), [modelList, selectedModelId]);
  const refreshModelList = useCallback(async (nextSelectedId?: string) => {
    if (!isAuthenticated) {
      setModelList([]);
      setSelectedModelId('');
      setModelListLoading(false);
      return;
    }
    setModelListLoading(true);
    try {
      const list = await modelApi.getAvailableModels();
      setModelList(list);
      setSelectedModelId((prevSelected) => {
        if (nextSelectedId && list.some((m) => m.id === nextSelectedId)) {
          return nextSelectedId;
        }
        if (prevSelected && list.some((m) => m.id === prevSelected)) {
          return prevSelected;
        }
        return list[0]?.id || '';
      });
    } catch (error) {
      console.error('Failed to load models', error);
      if (nextSelectedId) {
        setSelectedModelId('');
      }
    } finally {
      setModelListLoading(false);
    }
  }, [isAuthenticated]);
  const groupedModels = useMemo(() => ({
    platform: modelList.filter((m) => m.type === 'GLOBAL'),
    user: modelList.filter((m) => m.type === 'USER'),
  }), [modelList]);
  const modelDictionary = useMemo(() => {
    const map: Record<string, ModelInfo> = {};
    modelList.forEach((model) => {
      map[model.id] = model;
    });
    return map;
  }, [modelList]);
  
  // Budget state
  const [selectedBudget, setSelectedBudget] = useState<BudgetValue>('HIGH');
  const [copiedMessageId, setCopiedMessageId] = useState<ChatMessage['id'] | null>(null);

  // Events expand/collapse state
  const [allEventsExpanded, setAllEventsExpanded] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const processedIdsRef = useRef<Set<string>>(new Set());
  const chatEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const lastEventIdMapRef = useRef<Record<string, string | undefined>>({});
  const activeResearchRef = useRef<string | null>(null);
  const shouldAutoReconnectRef = useRef(false);
  const copyResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finalReportRef = useRef<HTMLDivElement | null>(null);
  const shouldScrollReportRef = useRef(false);
  const lastViewedResearchIdRef = useRef<string | null>(null);
  const draftResearchIdRef = useRef<string | null>(null);
  const preparingDraftRef = useRef(false);
  const activeResearchLoadRef = useRef<{ id: string; token: symbol } | null>(null);

  // --- Effects ---

  useEffect(() => {
    refreshModelList();
  }, [refreshModelList]);

  useEffect(() => {
    if (!id) {
      refreshModelList();
    }
  }, [id, refreshModelList]);

  useEffect(() => {
    if (id) {
      loadResearch(id);
    } else {
      resetToNew();
    }
    return () => disconnectSSE();
  }, [id]);

  useEffect(() => {
    if ((viewState === 'chat' || viewState === 'failed') && timelineItems.length > 0) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [currentResearch?.messages, currentResearch?.events, viewState]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const newHeight = Math.min(textareaRef.current.scrollHeight, 200); // Limit auto-grow height check
      textareaRef.current.style.height = newHeight + 'px';
    }
  }, [inputValue]);

  // Close model menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(event.target as Node)) {
        setShowModelMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current) {
        clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    finalReportRef.current = null;
  }, [currentResearch?.id]);

  useEffect(() => {
    if (id && id !== lastViewedResearchIdRef.current) {
      lastViewedResearchIdRef.current = id;
      shouldScrollReportRef.current = true;
    }
  }, [id]);



  // --- Logic ---

  const handleCopyMessage = useCallback(async (messageId: ChatMessage['id'], content: string) => {
    if (!content) return;
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      console.warn('当前环境不支持剪贴板复制');
      return;
    }
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMessageId(messageId);
      if (copyResetTimeoutRef.current) {
        clearTimeout(copyResetTimeoutRef.current);
      }
      copyResetTimeoutRef.current = setTimeout(() => setCopiedMessageId(null), 2000);
    } catch (err) {
      console.error('复制消息失败', err);
    }
  }, []);

  const renderCopyButton = useCallback((message: ChatMessage, isUser: boolean) => {
    if (!message?.content) return null;
    return (
      <button
        type="button"
        onClick={() => handleCopyMessage(message.id, message.content)}
        className={`flex items-center gap-1 px-2 py-1 text-[11px] rounded-full border transition-colors flex-none whitespace-nowrap mt-1 ${isUser ? 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50' : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'}`}
        aria-label="复制消息"
      >
        {copiedMessageId === message.id ? (
          <>
            <CheckCircle2 className="w-3 h-3" />
            <span>已复制</span>
          </>
        ) : (
          <>
            <Copy className="w-3 h-3" />
            <span>复制</span>
          </>
        )}
      </button>
    );
  }, [copiedMessageId, handleCopyMessage]);

  const prepareDraftResearch = useCallback(async () => {
    if (draftResearchIdRef.current || preparingDraftRef.current) return;
    preparingDraftRef.current = true;
    try {
      const history = await researchApi.getHistory();
      const draft = history.find(item => item.status === 'NEW');
      if (draft) {
        draftResearchIdRef.current = draft.id;
      } else {
        const created = await researchApi.create();
        const allocatedId = created.researchIds[0];
        if (allocatedId) {
          draftResearchIdRef.current = allocatedId;
          window.dispatchEvent(new Event(REFRESH_HISTORY_EVENT));
        }
      }
    } catch (error) {
      console.error('准备可用研究失败', error);
    } finally {
      preparingDraftRef.current = false;
    }
  }, []);

  const acquireDraftResearchId = useCallback(async () => {
    if (!draftResearchIdRef.current) {
      await prepareDraftResearch();
    }
    if (draftResearchIdRef.current) {
      const allocated = draftResearchIdRef.current;
      draftResearchIdRef.current = null;
      return allocated;
    }
    const created = await researchApi.create();
    const allocatedId = created.researchIds[0];
    if (allocatedId) {
      window.dispatchEvent(new Event(REFRESH_HISTORY_EVENT));
      return allocatedId;
    }
    throw new Error('无法获取可用的研究 ID');
  }, [prepareDraftResearch]);

  useEffect(() => {
    if (!id) {
      prepareDraftResearch();
    }
  }, [id, prepareDraftResearch]);

  const syncResearchStatus = useCallback(async (researchId: string) => {
    try {
      const statusResp = await researchApi.getStatus(researchId);
      let hasChanged = false;
      setCurrentResearch(prev => {
        if (!prev || prev.id !== researchId) return prev;
        const nextTitle = statusResp.title || prev.title;
        const nextModel = statusResp.modelId || prev.modelId;
        if (prev.status !== statusResp.status || prev.title !== nextTitle || prev.modelId !== nextModel) {
          hasChanged = true;
        }
        return {
          ...prev,
          status: statusResp.status,
          title: nextTitle,
          modelId: nextModel,
          budget: statusResp.budget ?? prev.budget,
          startTime: statusResp.startTime ?? prev.startTime,
          completeTime: statusResp.completeTime ?? prev.completeTime,
          totalInputTokens: statusResp.totalInputTokens ?? prev.totalInputTokens,
          totalOutputTokens: statusResp.totalOutputTokens ?? prev.totalOutputTokens,
        };
      });
      if (hasChanged && typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent<HistoryUpdateDetail>(HISTORY_UPDATE_EVENT, {
          detail: {
            id: researchId,
            status: statusResp.status,
            title: statusResp.title || undefined,
          }
        }));
        window.dispatchEvent(new Event(REFRESH_HISTORY_EVENT));
      }
    } catch (error) {
      console.error('同步研究状态失败', error);
    }
  }, []);

  const beginResearchLoad = (researchId: string) => {
    const token = Symbol('research-load');
    activeResearchLoadRef.current = { id: researchId, token };
    return token;
  };

  const isLatestResearchLoad = (researchId: string, token: symbol) => {
    const current = activeResearchLoadRef.current;
    return current?.id === researchId && current.token === token;
  };

  const clearResearchLoad = () => {
    activeResearchLoadRef.current = null;
  };

  const resetToNew = () => {
    clearResearchLoad();
    setCurrentResearch(null);
    setViewState('chat');
    setError(null);
    setInputValue('');
    lastEventIdMapRef.current = {};
    activeResearchRef.current = null;
    disconnectSSE();
  };

  const loadResearch = async (researchId: string) => {
    const loadToken = beginResearchLoad(researchId);
    setError(null);
    setViewState('loading');
    processedIdsRef.current.clear();
    disconnectSSE();

    try {
      const status = await researchApi.getStatus(researchId);
      if (!isLatestResearchLoad(researchId, loadToken)) {
        return;
      }
      
      let newState: ResearchState = {
        id: researchId,
        title: status.title || 'Untitled',
        modelId: status.modelId || undefined,
        budget: status.budget || undefined,
        status: status.status,
        messages: [],
        events: []
      };

      if (status.status === 'NEW') {
        if (isLatestResearchLoad(researchId, loadToken)) {
          setCurrentResearch(newState);
          setViewState('chat');
        }
      } else {
        if (!isLatestResearchLoad(researchId, loadToken)) {
          return;
        }
        const msgData = await researchApi.getMessages(researchId);
        if (!isLatestResearchLoad(researchId, loadToken)) {
          return;
        }
        newState.messages = msgData.messages;
        newState.events = msgData.events;
        newState.startTime = msgData.startTime;
        newState.completeTime = msgData.completeTime;
        newState.totalInputTokens = msgData.totalInputTokens;
        newState.totalOutputTokens = msgData.totalOutputTokens;
        
        msgData.messages.forEach(m => processedIdsRef.current.add(`msg-${m.id}`));
        msgData.events.forEach(e => processedIdsRef.current.add(`evt-${e.id}`));
        
        if (!isLatestResearchLoad(researchId, loadToken)) {
          return;
        }
        setCurrentResearch(newState);
        setViewState(status.status === 'FAILED' ? 'failed' : 'chat');
        
        if (status.status !== 'FAILED' && status.status !== 'COMPLETED') {
          if (!isLatestResearchLoad(researchId, loadToken)) {
            return;
          }
          delete lastEventIdMapRef.current[researchId];
          connectSSE(researchId, { resetCursor: true });
        }
      }
    } catch (e) {
      if (isLatestResearchLoad(researchId, loadToken)) {
        setError('Failed to load research');
        setViewState('failed');
      }
    }
  };

  const disconnectSSE = useCallback(() => {
    shouldAutoReconnectRef.current = false;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    activeResearchRef.current = null;
    setIsConnected(false);
  }, []);

  const connectSSE = useCallback((researchId: string, options?: { resetCursor?: boolean }) => {
    if (!researchId) return;
    shouldAutoReconnectRef.current = true;

    const shouldResetCursor = options?.resetCursor || activeResearchRef.current !== researchId;
    if (shouldResetCursor) {
      delete lastEventIdMapRef.current[researchId];
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    activeResearchRef.current = researchId;

    const token = getToken();
    const headers: Record<string, string> = {
      'X-Research-Id': researchId,
      'X-Client-Id': clientId,
    };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    const lastEventId = lastEventIdMapRef.current[researchId];
    if (lastEventId) {
      headers['Last-Event-Id'] = lastEventId;
    }

    const scheduleReconnect = () => {
      setIsConnected(false);
      if (!shouldAutoReconnectRef.current || controller.signal.aborted) {
        return;
      }
      setTimeout(() => connectSSE(researchId), 1000);
    };

    fetchEventSource(researchApi.getSseUrl(), {
      method: 'GET',
      headers,
      signal: controller.signal,
      onopen: async (response) => {
        if (response.ok) {
          setIsConnected(true);
        } else {
          scheduleReconnect();
        }
      },
      onmessage: (msg) => {
        if (msg.id) {
          lastEventIdMapRef.current[researchId] = msg.id;
        }
        if (msg.data?.startsWith('[DONE]')) {
           // 刷新最终状态
          syncResearchStatus(researchId);
          return;
       }
        try {
          const data = JSON.parse(msg.data);
          
          if (data.kind === 'event' && data.event) {
            const evt = data.event as WorkflowEvent;
            const key = `evt-${evt.id}`;
            if (!processedIdsRef.current.has(key)) {
              processedIdsRef.current.add(key);
              setCurrentResearch(prev => prev ? { ...prev, events: [...prev.events, evt] } : prev);
            }
          } else if (data.kind === 'message' && data.message) {
            const chatMsg = data.message as ChatMessage;
            const key = `msg-${chatMsg.id}`;
            if (!processedIdsRef.current.has(key)) {
              processedIdsRef.current.add(key);
              setCurrentResearch(prev => prev ? { ...prev, messages: [...prev.messages, chatMsg] } : prev);
              // 只在收到 message 时刷新状态（状态变化通常伴随消息）
              syncResearchStatus(researchId);
            }
          }
        } catch (e) {}
      },
      onclose: scheduleReconnect,
      onerror: () => {
        scheduleReconnect();
      }
    });
  }, [clientId, syncResearchStatus]);

  const sendMessage = async () => {
    if (!inputValue.trim()) return;
    const content = inputValue.trim();
    setInputValue('');
    const resolvedModelId = currentResearch?.modelId || selectedModelId;
    const needsModelSelection = !id || !currentResearch?.modelId;
    if (needsModelSelection && !resolvedModelId) {
      setError('当前没有可用模型，请先在「模型管理」中添加。');
      setInputValue(content);
      return;
    }

    if (!id) {
      setViewState('loading');
      try {
        const newId = await acquireDraftResearchId();
        if (!newId) {
          throw new Error('未找到可用的研究');
        }
        const modelConfig: Partial<SendMessageRequest> = { modelId: resolvedModelId, budget: selectedBudget };
        const tempMessage: ChatMessage = {
          id: Date.now(),
          researchId: newId,
          role: 'user',
          content,
          createTime: new Date().toISOString()
        };

        setCurrentResearch({
          id: newId,
          title: 'Untitled',
          modelId: selectedModelId,
          status: 'RUNNING',
          messages: [tempMessage],
          events: []
        });
        processedIdsRef.current.clear();
        setViewState('chat');

        connectSSE(newId, { resetCursor: true });
        await researchApi.sendMessage(newId, content, modelConfig);
        navigate(`/research/${newId}`);
      } catch (e: any) {
        setError(e.message || 'Failed to start research');
        setViewState('chat');
        setInputValue(content);
      }
      return;
    }

    if (!currentResearch) return;

    const needsConnection = activeResearchRef.current !== currentResearch.id || !isConnected;
    if (needsConnection) {
      connectSSE(currentResearch.id);
    }

    const userMsg: ChatMessage = {
      id: Date.now(),
      researchId: currentResearch.id,
      role: 'user',
      content,
      createTime: new Date().toISOString()
    };
    const shouldAttachModel = !currentResearch.modelId;
    const modelConfig = shouldAttachModel ? { modelId: resolvedModelId, budget: selectedBudget } : undefined;

    setCurrentResearch(prev => prev ? {
      ...prev,
      status: 'RUNNING',
      modelId: shouldAttachModel ? resolvedModelId : prev.modelId,
      messages: [...prev.messages, userMsg]
    } : prev);

    try {
      await researchApi.sendMessage(currentResearch.id, content, modelConfig);
    } catch (e: any) {
      setError(e.message || 'Failed to send message');
    }
  };

  const timelineItems = useMemo(() => {
    if (!currentResearch) return [];
    const items: TimelineItem[] = [];
    const messages = [...currentResearch.messages].sort((a, b) => new Date(a.createTime).getTime() - new Date(b.createTime).getTime());
    const events = [...currentResearch.events].sort((a, b) => new Date(a.createTime).getTime() - new Date(b.createTime).getTime());
    let eventIdx = 0;
    const flushEvents = (untilTime: number | null) => {
      const group: WorkflowEvent[] = [];
      while (eventIdx < events.length) {
        const evt = events[eventIdx];
        const evtTime = new Date(evt.createTime).getTime();
        if (untilTime !== null && evtTime > untilTime) break;
        group.push(evt);
        eventIdx++;
      }
      if (group.length > 0) items.push({ type: 'event_group', events: buildEventTree(group) });
    };
    messages.forEach(msg => {
      flushEvents(new Date(msg.createTime).getTime());
      items.push({ type: 'message', data: msg });
    });
    flushEvents(null);
    return items;
  }, [currentResearch?.messages, currentResearch?.events]);

  useEffect(() => {
    if (shouldScrollReportRef.current && currentResearch?.status === 'COMPLETED' && finalReportRef.current) {
      finalReportRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      shouldScrollReportRef.current = false;
    }
  }, [currentResearch?.status, timelineItems]);

  const effectiveResearchId = id || currentResearch?.id;
  const isNewChat = !effectiveResearchId || (currentResearch ? currentResearch.messages.length === 0 : false);

  return (
    <>
    <main className="flex-1 flex flex-col overflow-hidden bg-white relative">
      {viewState === 'loading' && !currentResearch && (
        <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      )}
      
      {/* Header for Existing Chat */}
      {!isNewChat && currentResearch && (
        <div className={`px-6 py-3 border-b border-gray-100 bg-white z-10 shrink-0 transition-all duration-300 ${!sidebarOpen ? 'pl-16' : ''}`}>
          <div className="flex justify-between items-start">
            <div>
              <h2 className="text-lg font-bold text-gray-900">{currentResearch.title}</h2>
              <div className="flex items-center gap-3 mt-1 flex-wrap">
                <div className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-gray-300'}`} />
                  <span className="text-xs text-gray-500">{currentResearch.status}</span>
                </div>
                {currentResearch.modelId && (
                  <div className="flex items-center gap-1.5 text-xs text-gray-500">
                    <Brain className="w-3 h-3" />
                    <span>
                      模型：{modelDictionary[currentResearch.modelId]?.name || modelDictionary[currentResearch.modelId]?.model || currentResearch.modelId}
                    </span>
                  </div>
                )}
                {currentResearch.budget && (
                  <div className="flex items-center gap-1.5 text-xs text-gray-500">
                    <Coins className="w-3 h-3" />
                    <span>预算：{BUDGET_OPTIONS.find(b => b.value === currentResearch.budget)?.label || currentResearch.budget}</span>
                  </div>
                )}
                {/* Token stats */}
                {(currentResearch.totalInputTokens || currentResearch.totalOutputTokens) && (
                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    <span className="flex items-center gap-1">
                      <Coins className="w-3 h-3" />
                      <span>输入: {(currentResearch.totalInputTokens || 0).toLocaleString()}</span>
                    </span>
                    <span className="flex items-center gap-1">
                      <span>输出: {(currentResearch.totalOutputTokens || 0).toLocaleString()}</span>
                    </span>
                  </div>
                )}
                {/* Duration */}
                {currentResearch.startTime && currentResearch.completeTime && (
                  <div className="flex items-center gap-1 text-xs text-gray-500">
                    <Clock className="w-3 h-3" />
                    <span>
                      {(() => {
                        const start = new Date(currentResearch.startTime!);
                        const end = new Date(currentResearch.completeTime!);
                        const diffMs = end.getTime() - start.getTime();
                        const diffMins = Math.floor(diffMs / 60000);
                        const diffSecs = Math.floor((diffMs % 60000) / 1000);
                        return diffMins > 0 ? `${diffMins}分${diffSecs}秒` : `${diffSecs}秒`;
                      })()}
                    </span>
                  </div>
                )}
              </div>
            </div>
            {/* Expand/Collapse all events button */}
            <button
              onClick={() => setAllEventsExpanded(!allEventsExpanded)}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                allEventsExpanded 
                  ? 'bg-gray-900 text-white hover:bg-gray-800' 
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
              title={allEventsExpanded ? '收起所有事件详情' : '展开所有事件详情'}
            >
              <ChevronsUpDown className="w-4 h-4" />
              <span>{allEventsExpanded ? '收起详情' : '展开详情'}</span>
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 flex flex-col overflow-hidden relative">
        {!isNewChat && (
          <div className="flex-1 overflow-y-auto p-6 space-y-8 scroll-smooth">
            {timelineItems.map((item, idx) => {
              if (item.type === 'message') {
                const isUser = item.data.role === 'user';
                const isReport = !isUser && idx === timelineItems.length - 1 && currentResearch?.status === 'COMPLETED';
                
                if (isReport) {
                  return (
                    <div
                      key={`msg-${item.data.id}`}
                      ref={(el) => { if (el) finalReportRef.current = el; }}
                      className="max-w-4xl mx-auto w-full"
                    >
                      <div className="bg-white border border-gray-200 rounded-2xl p-8 shadow-sm">
                        <div className="flex items-center gap-2 mb-6 pb-4 border-b border-gray-100">
                          <FileSearch className="w-5 h-5 text-black" />
                          <span className="font-bold text-lg">Final Report</span>
                        </div>
                        <article className="prose prose-gray max-w-none">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.data.content}</ReactMarkdown>
                        </article>
                      </div>
                    </div>
                  );
                }
                return (
                  <div key={`msg-${item.data.id}`} className={`flex gap-4 ${isUser ? 'flex-row-reverse' : ''}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${isUser ? 'bg-black text-white' : 'bg-gray-200 text-gray-600'}`}>
                      {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                    </div>
                    <div className={`flex items-start gap-2 max-w-full ${isUser ? 'flex-row-reverse' : ''}`}>
                      <div className={`max-w-2xl px-5 py-3 rounded-2xl ${isUser ? 'bg-gray-100 text-gray-900 rounded-tr-none' : 'bg-white border border-gray-200 text-gray-800 rounded-tl-none shadow-sm'}`}>
                        <div className="whitespace-pre-wrap text-sm">
                          {isUser ? item.data.content : <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.data.content}</ReactMarkdown>}
                        </div>
                      </div>
                      {renderCopyButton(item.data, isUser)}
                    </div>
                  </div>
                );
              } else {
                const flattenEvents = flattenTree(item.events);
                if (flattenEvents.length === 0) return null;
                return (
                  <div key={`group-${idx}`} className="flex gap-0 w-full">
                    <div className="w-8 shrink-0 flex justify-center">
                        <div className="w-0.5 bg-gray-200 h-full rounded-full" />
                    </div>
                    <div className="flex-1 -ml-4 space-y-2 py-2">
                      {flattenEvents.map((evt) => {
                        const style = getEventStyle(evt.type);
                        const Icon = style.icon;
                        return (
                          <div key={evt.id} className="relative pl-4" style={{ marginLeft: evt.depth * 20 }}>
                            <div className={`absolute -left-[5px] top-1 w-2.5 h-2.5 rounded-full border-2 border-white ${style.bg.replace('bg-', 'bg-').replace('50', '400')}`} />
                            {evt.content && evt.content !== evt.title ? (
                              <details className="group" open={allEventsExpanded}>
                                <summary className="flex items-start gap-2 cursor-pointer list-none [&::-webkit-details-marker]:hidden">
                                  <div className={`p-1.5 rounded-lg ${style.bg} ${style.color} shrink-0`}><Icon className="w-3.5 h-3.5" /></div>
                                  <div className="text-sm font-medium text-gray-900 group-hover:text-gray-600">{evt.title}</div>
                                </summary>
                                <div className="ml-10 mt-1 text-xs text-gray-500 font-mono bg-gray-50 p-2 rounded border border-gray-100 whitespace-pre-wrap break-all">{evt.content}</div>
                              </details>
                            ) : (
                              <div className="flex items-start gap-2">
                                <div className={`p-1.5 rounded-lg ${style.bg} ${style.color} shrink-0`}><Icon className="w-3.5 h-3.5" /></div>
                                <div className="text-sm font-medium text-gray-900">{evt.title}</div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              }
            })}
            <div ref={chatEndRef} />
          </div>
        )}

        <div className={`${isNewChat ? 'flex-1 flex flex-col items-center justify-center p-8' : 'p-6 bg-white border-t border-gray-100 shrink-0'}`}>
          <div className={`w-full ${isNewChat ? 'max-w-2xl' : 'max-w-4xl'} mx-auto`}>
            
            {isNewChat && (
              <div className="text-center mb-12">
                <div className="w-16 h-16 bg-black rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-xl shadow-gray-200">
                  <Bot className="w-8 h-8 text-white" />
                </div>
                <h2 className="text-2xl font-bold text-gray-900 mb-2">What would you like to research?</h2>
              </div>
            )}

            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600 flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
                <AlertCircle className="w-4 h-4" />{error}
              </div>
            )}

            {/* Unified Input Card - 只在可输入状态显示 */}
            {(!currentResearch || ['NEW', 'NEED_CLARIFICATION', 'COMPLETED', 'FAILED'].includes(currentResearch.status)) && (
            <div className={`bg-[#f4f4f4] border border-transparent rounded-[26px] focus-within:border-gray-200 focus-within:bg-white focus-within:shadow-lg transition-all relative z-20 flex flex-col`}>
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder={isNewChat ? "Start a deep research..." : "Ask a follow-up..."}
                className={`w-full px-4 pt-4 pb-2 bg-transparent border-none resize-none focus:ring-0 max-h-[200px] overflow-y-auto text-gray-900 placeholder:text-gray-500 ${isNewChat ? 'min-h-[52px] text-base' : 'min-h-[40px]'}`}
                rows={1}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
              />
              
              <div className="w-full flex items-center gap-3 px-2 pb-2 mt-2">
                {isNewChat ? (
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-none w-[220px]">
                      <div className="flex items-center gap-1 text-[11px] font-medium text-gray-600 whitespace-nowrap">
                        <Coins className="w-3.5 h-3.5 text-gray-500" />
                        <span>研究预算</span>
                      </div>
                      <div className="grid grid-cols-3 gap-1 bg-white border border-gray-200 rounded-2xl shadow-sm h-11 p-1 w-full">
                        {BUDGET_OPTIONS.map((option) => {
                          const active = selectedBudget === option.value;
                          return (
                            <button
                              key={option.value}
                              onClick={() => setSelectedBudget(option.value)}
                              title={option.caption}
                              className={`h-full px-2 rounded-xl text-left flex flex-col justify-center leading-tight transition-all ${
                                active ? 'bg-black text-white shadow-sm' : 'text-gray-600 hover:text-gray-900'
                              }`}
                            >
                              <span className="text-xs font-semibold">{option.label}</span>
                              <span className={`text-[10px] ${active ? 'text-white/80' : 'text-gray-400'} hidden 2xl:block`}>{option.caption}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-[320px]">
                      <div className="flex items-center gap-1 text-[11px] font-medium text-gray-600 whitespace-nowrap">
                        <Zap className="w-3.5 h-3.5 text-amber-500" />
                        <span>模型选择</span>
                      </div>
                      <div ref={modelMenuRef} className="relative flex-1 min-w-[200px]">
                        <button
                          onClick={() => setShowModelMenu(!showModelMenu)}
                          className="flex items-center gap-3 px-3 h-11 w-full text-left bg-white border border-gray-200 rounded-2xl shadow-sm hover:border-gray-300"
                        >
                          <div className="flex flex-col text-sm min-w-0">
                            <span className="font-medium text-gray-900 truncate">{selectedModelInfo?.name || '选择模型'}</span>
                            <span className="text-[11px] text-gray-500 truncate hidden xl:block">{selectedModelInfo?.model || '点击挑选或新增模型'}</span>
                          </div>
                          <ChevronDown className={`w-4 h-4 text-gray-400 ml-auto transition-transform ${showModelMenu ? 'rotate-180' : ''}`} />
                        </button>

                        {showModelMenu && (
                          <div className="absolute bottom-full left-0 mb-2 w-full sm:w-[320px] bg-white border border-gray-200 rounded-2xl shadow-xl p-4 animate-in fade-in zoom-in-95 origin-bottom-left z-50">
                            <div className="flex items-center justify-between mb-3">
                              <div>
                                <p className="text-sm font-semibold text-gray-900">选择模型</p>
                                <p className="text-[11px] text-gray-500">首条消息会锁定模型与凭证</p>
                              </div>
                              <button
                                onClick={() => refreshModelList()}
                                className="p-2 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50"
                                disabled={modelListLoading}
                              >
                                <RefreshCw className={`w-4 h-4 ${modelListLoading ? 'animate-spin' : ''}`} />
                              </button>
                            </div>

                            <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
                              {[{ key: 'platform', label: '平台内置', icon: <Shield className="w-3.5 h-3.5 text-gray-500" />, models: groupedModels.platform, empty: '暂无内置模型，请联系管理员' },
                                { key: 'user', label: '我的模型', icon: <User className="w-3.5 h-3.5 text-gray-500" />, models: groupedModels.user, empty: '暂无自定义模型，先在下方创建' }].map(section => (
                                  <div key={section.key}>
                                    <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                                      {section.icon}
                                      <span>{section.label}</span>
                                      <span className="text-[10px] text-gray-400">({section.models.length})</span>
                                    </div>
                                    {section.models.length === 0 ? (
                                      <p className="text-[11px] text-gray-400 ml-6 mt-1">{section.empty}</p>
                                    ) : (
                                      <div className="mt-2 space-y-1">
                                        {section.models.map(model => {
                                          const active = selectedModelId === model.id;
                                          return (
                                            <button
                                              key={model.id}
                                              onClick={() => { setSelectedModelId(model.id); setShowModelMenu(false); }}
                                              className={`w-full text-left px-3 py-2 rounded-xl border text-sm transition-colors ${active ? 'border-black bg-black/5 text-gray-900' : 'border-gray-100 hover:border-gray-200 text-gray-700'}`}
                                            >
                                              <div className="flex items-center justify-between gap-2">
                                                <span className="font-medium truncate">{model.name || model.model}</span>
                                                <span className={`text-[10px] px-2 py-0.5 rounded-full ${model.type === 'GLOBAL' ? 'bg-gray-100 text-gray-600' : 'bg-amber-100 text-amber-600'}`}>
                                                  {model.type === 'GLOBAL' ? '内置' : '自定义'}
                                                </span>
                                              </div>
                                              <div className="text-[11px] text-gray-500 mt-1 truncate">ID：{model.model}</div>
                                            </button>
                                          );
                                        })}
                                      </div>
                                    )}
                                  </div>
                              ))}
                            </div>

                            <div className="mt-4 space-y-2">
                              {modelList.length === 0 && <p className="text-xs text-red-500">暂无可用模型，请先创建一个。</p>}
                              <button
                                onClick={() => { setShowModelMenu(false); setIsModelManagerOpen(true); }}
                                className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-xl border border-gray-200 text-gray-700 hover:bg-gray-50"
                              >
                                <Plus className="w-4 h-4" />
                                管理模型
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex-1" />
                )}

                <button 
                    onClick={sendMessage} 
                    disabled={!inputValue.trim()} 
                    className={`flex-none p-2 rounded-full transition-all shadow-sm ${inputValue.trim() ? 'bg-black text-white hover:bg-gray-800' : 'bg-gray-200 text-gray-400'}`}
                >
                    <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
            )}

            {isNewChat && (
              <div className="mt-8 flex flex-wrap justify-center gap-3">
                {['Market Analysis', 'Scientific Review', 'Code Architecture'].map((topic) => (
                  <button key={topic} onClick={() => setInputValue(topic)} className="px-4 py-2 bg-white hover:bg-gray-50 border border-gray-200 rounded-full text-sm text-gray-600 transition-colors shadow-sm">
                    {topic}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
    <ModelManagerModal
      isOpen={isModelManagerOpen}
      onClose={() => setIsModelManagerOpen(false)}
      models={modelList}
      onRefresh={() => refreshModelList()}
      onModelCreated={(modelId) => refreshModelList(modelId)}
    />
    </>
  );
}

function AppContent() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="h-screen flex bg-white relative overflow-hidden">
      <Sidebar isOpen={sidebarOpen} toggle={() => setSidebarOpen(false)} />
      
      {!sidebarOpen && (
        <button 
            onClick={() => setSidebarOpen(true)}
            className="absolute top-3 left-3 z-50 p-2 bg-white/80 backdrop-blur border border-gray-200 rounded-lg shadow-sm hover:bg-gray-50 transition-all"
        >
            <PanelLeftOpen className="w-5 h-5 text-gray-600" />
        </button>
      )}

      <div className="flex-1 flex flex-col min-w-0 w-full overflow-hidden">
        <Routes>
            <Route path="/research/:id" element={<ResearchPage sidebarOpen={sidebarOpen} />} />
            <Route path="/new" element={<ResearchPage sidebarOpen={sidebarOpen} />} />
            <Route path="/arena" element={<ArenaPage sidebarOpen={sidebarOpen} />} />
            <Route path="/" element={<Navigate to="/new" replace />} />
        </Routes>
      </div>
      
      {/* Auth Modal */}
      <AuthModal />
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/oauth2callback" element={<OAuthCallback />} />
        <Route path="/*" element={<AppContent />} />
      </Routes>
    </AuthProvider>
  );
}

export default App;
