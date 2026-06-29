import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Routes, Route, Navigate, useNavigate, useParams, useLocation } from 'react-router-dom';
import { Plus, Loader2, Send, AlertCircle, Sparkles, Search, Brain, Globe, FileSearch, Zap, User, Bot, CheckCircle2, PanelLeftClose, PanelLeftOpen, MessageSquare, Clock, Coins, ChevronsUpDown, Copy, Archive, Trash2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { researchApi, modelApi, ResearchStatusResponse, ChatMessage, WorkflowEvent, ModelInfo, SendMessageRequest, DirectionAction, ResearchMessageResponse } from './services/api';
import { getToken } from './services/auth';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { AuthModal } from './components/AuthModal';
import { UserMenu } from './components/UserMenu';
import { ModelManagerModal } from './components/ModelManagerModal';
import { AgentFlowPanel } from './components/agent-flow/AgentFlowPanel';
import { AI_Prompt, type AnimatedAIInputOption } from './components/ui/animated-ai-input';
import { useAnimatedText } from './components/ui/animated-text';
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
    case 'CLARIFY_FORM': return { icon: MessageSquare, color: 'text-amber-600', bg: 'bg-amber-50' };
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
    case 'AWAITING_DIRECTION_CONFIRM': return <AlertCircle className="w-4 h-4 text-orange-500" />;
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

function getStatusLabel(status?: string) {
  switch (status?.toUpperCase()) {
    case 'COMPLETED': return '已完成';
    case 'FAILED': return '失败';
    case 'NEW': return '准备中';
    case 'NEED_CLARIFICATION': return '待澄清';
    case 'QUEUE': return '排队中';
    case 'START':
    case 'RUNNING': return '运行中';
    case 'IN_SCOPE': return '规划中';
    case 'IN_RESEARCH': return '调研中';
    case 'IN_REPORT': return '写报告';
    case 'AWAITING_DIRECTION_CONFIRM': return '待确认方向';
    default: return status || '未知';
  }
}

type HistoryUpdateDetail = {
  id: string;
  status?: string;
  title?: string;
};

function messageKey(message: ChatMessage) {
  return `msg-${message.id}`;
}

function eventKey(event: WorkflowEvent) {
  if (event.id !== undefined && event.id !== null) return `evt-${event.id}`;
  if (event.sequenceNo !== undefined && event.sequenceNo !== null && event.sequenceNo >= 0) return `evt-seq-${event.sequenceNo}`;
  return `evt-${event.type}-${event.createTime}-${event.title}`;
}

function latestTimelineSequence(messages: ChatMessage[] = [], events: WorkflowEvent[] = []) {
  const sequences = [
    ...messages.map((message) => message.sequenceNo),
    ...events.map((event) => event.sequenceNo),
  ].filter((value): value is number => typeof value === 'number' && value >= 0);
  return sequences.length ? Math.max(...sequences) : undefined;
}

function sortTimelineRecords<T extends { sequenceNo?: number; createTime: string }>(items: T[]) {
  return [...items].sort((a, b) => {
    const seqA = typeof a.sequenceNo === 'number' && a.sequenceNo >= 0 ? a.sequenceNo : Number.POSITIVE_INFINITY;
    const seqB = typeof b.sequenceNo === 'number' && b.sequenceNo >= 0 ? b.sequenceNo : Number.POSITIVE_INFINITY;
    if (seqA !== seqB) return seqA - seqB;
    return new Date(a.createTime).getTime() - new Date(b.createTime).getTime();
  });
}

function mergeTimelineRecords<T extends { sequenceNo?: number; createTime: string }>(
  existing: T[],
  incoming: T[],
  keyOf: (item: T) => string,
) {
  const merged = new Map<string, T>();
  existing.forEach((item) => merged.set(keyOf(item), item));
  incoming.forEach((item) => merged.set(keyOf(item), item));
  return sortTimelineRecords([...merged.values()]);
}

const REFRESH_HISTORY_EVENT = 'refreshHistory';
const HISTORY_UPDATE_EVENT = 'historyStatusUpdate';

const ACTIVE_HISTORY_STATUSES = new Set([
  'QUEUE',
  'START',
  'RUNNING',
  'IN_SCOPE',
  'AWAITING_DIRECTION_CONFIRM',
  'IN_RESEARCH',
  'IN_REPORT',
]);

const LIVE_SSE_STATUSES = new Set([
  'QUEUE',
  'START',
  'RUNNING',
  'IN_SCOPE',
  'IN_RESEARCH',
  'IN_REPORT',
]);

const MANAGE_BLOCKED_STATUSES = new Set([
  'QUEUE',
  'START',
  'RUNNING',
  'IN_SCOPE',
  'AWAITING_DIRECTION_CONFIRM',
  'IN_RESEARCH',
  'IN_REPORT',
]);

function shouldConnectLiveSse(status?: string) {
  return LIVE_SSE_STATUSES.has((status || '').toUpperCase());
}

function getStatusTone(status?: string) {
  switch (status?.toUpperCase()) {
    case 'COMPLETED':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    case 'FAILED':
    case 'CANCELLED':
      return 'border-red-200 bg-red-50 text-red-700';
    case 'NEED_CLARIFICATION':
    case 'AWAITING_DIRECTION_CONFIRM':
      return 'border-amber-200 bg-amber-50 text-amber-700';
    case 'QUEUE':
    case 'START':
    case 'RUNNING':
    case 'IN_SCOPE':
    case 'IN_RESEARCH':
    case 'IN_REPORT':
      return 'border-blue-200 bg-blue-50 text-blue-700';
    default:
      return 'border-gray-200 bg-gray-50 text-gray-600';
  }
}

function getStatusDot(status?: string) {
  switch (status?.toUpperCase()) {
    case 'COMPLETED':
      return 'bg-emerald-500';
    case 'FAILED':
    case 'CANCELLED':
      return 'bg-red-500';
    case 'NEED_CLARIFICATION':
    case 'AWAITING_DIRECTION_CONFIRM':
      return 'bg-amber-500';
    case 'QUEUE':
    case 'START':
    case 'RUNNING':
    case 'IN_SCOPE':
    case 'IN_RESEARCH':
    case 'IN_REPORT':
      return 'bg-blue-500';
    default:
      return 'bg-gray-300';
  }
}

function formatDuration(startTime?: string, completeTime?: string) {
  if (!startTime || !completeTime) return null;
  const start = new Date(startTime);
  const end = new Date(completeTime);
  const diffMs = end.getTime() - start.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffSecs = Math.floor((diffMs % 60000) / 1000);
  return diffMins > 0 ? `${diffMins}分${diffSecs}秒` : `${diffSecs}秒`;
}

function MessageMarkdown({ content, animateText = false }: { content: string; animateText?: boolean }) {
  const animatedContent = useAnimatedText(animateText ? content : '', ' ');
  const displayContent = animateText ? animatedContent : content;

  return (
    <div className="prose prose-zinc prose-sm max-w-none text-[14px] leading-7 prose-headings:font-semibold prose-headings:text-gray-950 prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-pre:my-3 prose-pre:rounded-xl prose-pre:border prose-pre:border-gray-200 prose-pre:bg-gray-950 prose-code:rounded-md prose-code:bg-gray-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:text-[0.85em] prose-code:font-medium prose-pre:prose-code:bg-transparent prose-pre:prose-code:p-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayContent}</ReactMarkdown>
    </div>
  );
}

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
  const [managingResearchId, setManagingResearchId] = useState<string | null>(null);

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

  const handleArchiveResearch = useCallback(async (researchId: string) => {
    setManagingResearchId(researchId);
    try {
      await researchApi.archiveResearch(researchId);
      setHistory(prev => prev.filter(item => item.id !== researchId));
      if (currentId === researchId) navigate('/new');
      window.dispatchEvent(new Event(REFRESH_HISTORY_EVENT));
    } catch (e: any) {
      console.error('Failed to archive research', e);
      window.alert(e?.message || '归档失败');
    } finally {
      setManagingResearchId(null);
    }
  }, [currentId, navigate]);

  const handleDeleteResearch = useCallback(async (researchId: string) => {
    if (!window.confirm('确定要删除这条研究会话吗？删除后无法恢复。')) return;
    setManagingResearchId(researchId);
    try {
      await researchApi.deleteResearch(researchId);
      setHistory(prev => prev.filter(item => item.id !== researchId));
      if (currentId === researchId) navigate('/new');
      window.dispatchEvent(new Event(REFRESH_HISTORY_EVENT));
    } catch (e: any) {
      console.error('Failed to delete research', e);
      window.alert(e?.message || '删除失败');
    } finally {
      setManagingResearchId(null);
    }
  }, [currentId, navigate]);

  const isArenaActive = location.pathname.startsWith('/arena');

  return (
    <aside className={`flex shrink-0 flex-col border-r border-gray-200/80 bg-[#f7f8f5] transition-all duration-300 ease-in-out ${isOpen ? 'w-72 translate-x-0' : 'w-0 -translate-x-full overflow-hidden border-r-0 opacity-0'}`}>
      <div className="border-b border-gray-200/80 px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gray-950 text-white shadow-sm">
              <Bot className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-[15px] font-semibold tracking-tight text-gray-950">Deep Research</h1>
              <p className="truncate text-[11px] font-medium text-gray-500">research workspace</p>
            </div>
          </div>
          <button
            onClick={toggle}
            className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-white hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/10"
            aria-label="收起侧边栏"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
      </div>

      <nav className="space-y-2 px-3 py-3">
        <button
          onClick={() => navigate('/new')}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-gray-950 px-4 text-sm font-semibold text-white shadow-sm shadow-gray-900/10 transition-all hover:-translate-y-0.5 hover:bg-gray-800 active:translate-y-0"
        >
          <Plus className="h-4 w-4" />
          New Research
        </button>
        <button
          onClick={() => navigate('/arena')}
          className={`flex h-10 w-full items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold transition-all ${
            isArenaActive
              ? 'border-gray-300 bg-white text-gray-950 shadow-sm'
              : 'border-transparent text-gray-600 hover:border-gray-200 hover:bg-white hover:text-gray-950'
          }`}
        >
          <Zap className="h-4 w-4" />
          LLM Arena
        </button>
      </nav>

      <div className="flex-1 overflow-y-auto px-3 pb-3">
        <div className="flex items-center justify-between px-1 py-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">History</span>
          <span className="rounded-md bg-white px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-gray-500 shadow-sm">
            {history.length}
          </span>
        </div>
        {loading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((item) => (
              <div key={item} className="rounded-xl bg-white/70 p-3 shadow-sm">
                <div className="h-3 w-4/5 animate-pulse rounded bg-gray-200" />
                <div className="mt-2 h-2.5 w-1/2 animate-pulse rounded bg-gray-100" />
              </div>
            ))}
          </div>
        ) : history.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-gray-300 bg-white/60 p-4 text-sm text-gray-500">
            暂无研究记录
          </div>
        ) : (
          <div className="space-y-1.5">
            {history.map((item) => {
              const modelInfo = item.modelId ? modelDictionary[item.modelId] : null;
              const modelDisplayName = modelInfo?.name || modelInfo?.model || null;
              const active = currentId === item.id;
              const manageDisabled = MANAGE_BLOCKED_STATUSES.has(item.status?.toUpperCase() || '') || managingResearchId === item.id;
              return (
                <div
                  key={item.id}
                  className={`group relative rounded-xl transition-all ${
                    active
                      ? 'bg-white text-gray-950 shadow-sm ring-1 ring-gray-200'
                      : 'text-gray-600 hover:bg-white/80 hover:text-gray-950'
                  }`}
                >
                  {active && <span className="absolute left-0 top-3 h-8 w-1 rounded-r-full bg-gray-950" />}
                  <div className="absolute right-2 top-2 flex items-center gap-1 opacity-60 transition-opacity group-hover:opacity-100">
                    <button
                      type="button"
                      disabled={manageDisabled}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (manageDisabled) return;
                        handleArchiveResearch(item.id);
                      }}
                      className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-gray-400"
                      aria-label="归档会话"
                      title={manageDisabled ? '进行中的会话请先取消' : '归档'}
                    >
                      <Archive className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      disabled={manageDisabled}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (manageDisabled) return;
                        handleDeleteResearch(item.id);
                      }}
                      className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/20 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-gray-400"
                      aria-label="删除会话"
                      title={manageDisabled ? '进行中的会话请先取消' : '删除'}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate(`/research/${item.id}`)}
                    className="block w-full rounded-xl px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/10"
                  >
                  <div className="flex items-start gap-3">
                    <div className={`mt-1 h-2 w-2 shrink-0 rounded-full ${getStatusDot(item.status)}`} />
                    <div className="min-w-0 flex-1 space-y-1.5 pr-12">
                      <div className="truncate text-[13px] font-semibold leading-5">{item.title || 'Untitled'}</div>
                      <div className="flex min-w-0 items-center gap-2">
                        <span className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${getStatusTone(item.status)}`}>
                          {getStatusIcon(item.status)}
                          {getStatusLabel(item.status)}
                        </span>
                        {modelDisplayName && (
                          <span className="truncate text-[11px] text-gray-500">{modelDisplayName}</span>
                        )}
                      </div>
                    </div>
                  </div>
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="border-t border-gray-200/80 p-3">
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
  const [isModelManagerOpen, setIsModelManagerOpen] = useState(false);
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
  const modelDictionary = useMemo(() => {
    const map: Record<string, ModelInfo> = {};
    modelList.forEach((model) => {
      map[model.id] = model;
    });
    return map;
  }, [modelList]);
  const inputModelOptions = useMemo<AnimatedAIInputOption[]>(() => (
    modelList.map((model) => ({
      value: model.id,
      label: model.name || model.model,
      caption: model.model,
      type: model.type,
    }))
  ), [modelList]);
  
  // Budget state
  const [selectedBudget, setSelectedBudget] = useState<BudgetValue>('HIGH');
  const [copiedMessageId, setCopiedMessageId] = useState<ChatMessage['id'] | null>(null);

  // Events expand/collapse state
  const [allEventsExpanded, setAllEventsExpanded] = useState(false);

  // HITL 方向确认状态
  const [hitlReviseFeedback, setHitlReviseFeedback] = useState('');
  const [isHitlConfirming, setIsHitlConfirming] = useState(false);
  const hitlResearchBrief = useMemo(() => {
    if (currentResearch?.status !== 'AWAITING_DIRECTION_CONFIRM') return null;
    const dirEvent = [...(currentResearch?.events || [])].reverse().find(e => e.type === 'DIRECTION_CONFIRM');
    return dirEvent?.content || null;
  }, [currentResearch?.status, currentResearch?.events]);

  // 澄清表单状态
  const clarifyFormFromEvents = useMemo(() => {
    if (currentResearch?.status !== 'NEED_CLARIFICATION') return null;
    const formEvent = [...(currentResearch?.events || [])]
      .reverse()
      .find(e => e.type === 'CLARIFY_FORM' && e.formData);
    return formEvent?.formData || null;
  }, [currentResearch?.status, currentResearch?.events]);
  const [clarifyFormAnswers, setClarifyFormAnswers] = useState<Record<string, string[] | string>>({});
  const [clarifyOtherInputs, setClarifyOtherInputs] = useState<Record<string, string>>({});
  const [isClarifySubmitting, setIsClarifySubmitting] = useState(false);
  const [clarifyTextInput, setClarifyTextInput] = useState("");
  const [isClarifyTextSubmitting, setIsClarifyTextSubmitting] = useState(false);


  const abortControllerRef = useRef<AbortController | null>(null);
  const cancelledRef = useRef(false);  // 取消标记，阻止残余 SSE 事件
  const processedIdsRef = useRef<Set<string>>(new Set());
  const chatEndRef = useRef<HTMLDivElement>(null);
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
      // 监听从终端状态研究跳转过来的消息
      const handleResend = (e: Event) => {
        const detail = (e as CustomEvent<string>).detail;
        if (detail) setInputValue(detail);
      };
      window.addEventListener('resend-message', handleResend);
      return () => window.removeEventListener('resend-message', handleResend);
    }
  }, [id, prepareDraftResearch]);

  const applyResearchSnapshot = useCallback((researchId: string, data: ResearchMessageResponse) => {
    const messages = data.messages || [];
    const events = data.events || [];
    messages.forEach((message) => processedIdsRef.current.add(messageKey(message)));
    events.forEach((event) => processedIdsRef.current.add(eventKey(event)));

    const latestSequence = latestTimelineSequence(messages, events);
    if (latestSequence !== undefined) {
      lastEventIdMapRef.current[researchId] = String(latestSequence);
    }

    setCurrentResearch(prev => {
      if (!prev || prev.id !== researchId) return prev;
      return {
        ...prev,
        messages: mergeTimelineRecords(prev.messages, messages, messageKey),
        events: mergeTimelineRecords(prev.events, events, eventKey),
        status: data.status || prev.status,
        title: data.title || prev.title,
        modelId: data.modelId || prev.modelId,
        budget: data.budget ?? prev.budget,
        totalInputTokens: data.totalInputTokens ?? prev.totalInputTokens,
        totalOutputTokens: data.totalOutputTokens ?? prev.totalOutputTokens,
        startTime: data.startTime ?? prev.startTime,
        completeTime: data.completeTime ?? prev.completeTime,
      };
    });

    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent<HistoryUpdateDetail>(HISTORY_UPDATE_EVENT, {
        detail: {
          id: researchId,
          status: data.status,
          title: data.title || undefined,
        }
      }));
      window.dispatchEvent(new Event(REFRESH_HISTORY_EVENT));
    }
  }, []);

  const syncResearchSnapshot = useCallback(async (researchId: string) => {
    try {
      const data = await researchApi.getMessages(researchId);
      applyResearchSnapshot(researchId, data);
      return data;
    } catch (error) {
      console.error('同步研究快照失败', error);
      return null;
    }
  }, [applyResearchSnapshot]);

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
        newState.status = msgData.status || newState.status;
        newState.startTime = msgData.startTime;
        newState.completeTime = msgData.completeTime;
        newState.totalInputTokens = msgData.totalInputTokens;
        newState.totalOutputTokens = msgData.totalOutputTokens;
        
        msgData.messages.forEach(m => processedIdsRef.current.add(messageKey(m)));
        msgData.events.forEach(e => processedIdsRef.current.add(eventKey(e)));
        const latestSequence = latestTimelineSequence(msgData.messages, msgData.events);
        if (latestSequence !== undefined) {
          lastEventIdMapRef.current[researchId] = String(latestSequence);
        }
        
        if (!isLatestResearchLoad(researchId, loadToken)) {
          return;
        }
        setCurrentResearch(newState);
        setViewState(status.status === 'FAILED' ? 'failed' : 'chat');
        
        if (shouldConnectLiveSse(newState.status)) {
          if (!isLatestResearchLoad(researchId, loadToken)) {
            return;
          }
          connectSSE(researchId);
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
    cancelledRef.current = false; // 新建连接时重置取消标记

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
        // 取消后忽略残余 SSE 事件
        if (cancelledRef.current) return;
        if (msg.id) {
          lastEventIdMapRef.current[researchId] = msg.id;
        }
        if (msg.data?.startsWith('[DONE]')) {
          shouldAutoReconnectRef.current = false;
          setIsConnected(false);
          syncResearchSnapshot(researchId);
          return;
       }
        try {
          const data = JSON.parse(msg.data);
          
          if (data.kind === 'event' && data.event) {
            const evt = data.event as WorkflowEvent;
            const key = eventKey(evt);
            if (!processedIdsRef.current.has(key)) {
              processedIdsRef.current.add(key);
              setCurrentResearch(prev => prev ? { ...prev, events: mergeTimelineRecords(prev.events, [evt], eventKey) } : prev);
              syncResearchSnapshot(researchId);
            }
          } else if (data.kind === 'message' && data.message) {
            const chatMsg = data.message as ChatMessage;
            const key = messageKey(chatMsg);
            if (!processedIdsRef.current.has(key)) {
              processedIdsRef.current.add(key);
              setCurrentResearch(prev => prev ? { ...prev, messages: mergeTimelineRecords(prev.messages, [chatMsg], messageKey) } : prev);
              syncResearchSnapshot(researchId);
            }
          }
        } catch (e) {
          console.error('SSE message parse failed', e, msg.data);
        }
      },
      onclose: scheduleReconnect,
      onerror: () => {
        scheduleReconnect();
      }
    });
  }, [clientId, syncResearchSnapshot]);

  // HITL 方向确认处理（在 connectSSE 之后定义，避免循环引用）
  const handleHitlConfirm = useCallback(async (action: DirectionAction, feedback?: string) => {
    if (!currentResearch) return;
    setIsHitlConfirming(true);
    try {
      await researchApi.confirmDirection(currentResearch.id, { action, feedback });
      // 成功后立即更新状态，隐藏 HITL 卡片，恢复 RUNNING 状态
      setIsHitlConfirming(false);
      setHitlReviseFeedback('');
      setCurrentResearch(prev => prev ? { ...prev, status: 'RUNNING' } : prev);
      const snapshot = await syncResearchSnapshot(currentResearch.id);
      if (shouldConnectLiveSse(snapshot?.status)) {
        connectSSE(currentResearch.id);
      }
    } catch (e: any) {
      console.error('方向确认失败', e);
      setIsHitlConfirming(false);
    }
  }, [currentResearch, connectSSE, syncResearchSnapshot]);

  // 澄清表单处理
  const handleClarifyCheckboxChange = (questionId: string, option: string, checked: boolean) => {
    setClarifyFormAnswers(prev => {
      const current = (prev[questionId] as string[]) || [];
      if (checked) return { ...prev, [questionId]: [...current, option] };
      return { ...prev, [questionId]: current.filter(o => o !== option) };
    });
  };

  const handleClarifyOtherChange = (questionId: string, value: string) => {
    setClarifyOtherInputs(prev => ({ ...prev, [questionId]: value }));
  };

  const handleClarifyOpenEndedChange = (questionId: string, value: string) => {
    setClarifyFormAnswers(prev => ({ ...prev, [questionId]: value }));
  };

  const handleClarifySubmit = useCallback(async () => {
    if (!currentResearch || !clarifyFormFromEvents) return;
    setIsClarifySubmitting(true);
    
    const lines: string[] = [];
    for (const q of clarifyFormFromEvents.questions) {
      const answer = clarifyFormAnswers[q.id];
      if (q.type === 'multi_choice') {
        const selected = (answer as string[]) || [];
        const otherText = clarifyOtherInputs[q.id];
        const parts = selected.filter(o => o !== '其他');
        if (otherText?.trim()) parts.push(`其他：${otherText.trim()}`);
        if (parts.length > 0) lines.push(`Q: ${q.text} 答：${parts.join('，')}`);
      } else {
        const value = (answer as string) || '';
        if (value.trim()) lines.push(`Q: ${q.text} 答：${value.trim()}`);
      }
    }
    
    const compiledText = lines.join('\n') || '用户已提交澄清表单';
    
    try {
      await researchApi.sendMessage(currentResearch.id, compiledText);
      setIsClarifySubmitting(false);
      setClarifyFormAnswers({});
      setClarifyOtherInputs({});
      setCurrentResearch(prev => prev ? { ...prev, status: 'RUNNING' } : prev);
      const snapshot = await syncResearchSnapshot(currentResearch.id);
      if (shouldConnectLiveSse(snapshot?.status)) {
        connectSSE(currentResearch.id);
      }
    } catch (e: any) {
      setIsClarifySubmitting(false);
      setError(e.message || '提交失败');
    }
  }, [currentResearch, clarifyFormFromEvents, clarifyFormAnswers, clarifyOtherInputs, connectSSE, syncResearchSnapshot]);
  const handleClarifyTextSubmit = useCallback(async () => {
    if (!currentResearch || !clarifyTextInput.trim()) return;
    setIsClarifyTextSubmitting(true);
    try {
      await researchApi.sendMessage(currentResearch.id, clarifyTextInput.trim());
      setClarifyTextInput("");
      setCurrentResearch(prev => prev ? { ...prev, status: "RUNNING" } : prev);
      const snapshot = await syncResearchSnapshot(currentResearch.id);
      if (shouldConnectLiveSse(snapshot?.status)) {
        connectSSE(currentResearch.id);
      }
    } catch (e: any) {
      setError("提交回答失败");
    } finally {
      setIsClarifyTextSubmitting(false);
    }
  }, [currentResearch, clarifyTextInput, connectSSE, syncResearchSnapshot]);


  // 取消研究中研究
  const handleCancelResearch = useCallback(async () => {
    if (!currentResearch) return;
    if (!window.confirm('确定要取消当前研究吗？')) return;
    try {
      cancelledRef.current = true; // 阻止残余 SSE 事件
      await researchApi.cancelResearch(currentResearch.id);
      setCurrentResearch(prev => prev ? { ...prev, status: 'CANCELLED' } : prev);
      disconnectSSE();
      syncResearchSnapshot(currentResearch.id);
    } catch (e: any) {
      setError(e.message || '取消失败');
    }
  }, [currentResearch, disconnectSSE, syncResearchSnapshot]);

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
        const modelConfig: Partial<SendMessageRequest> = { modelId: resolvedModelId, budget: selectedBudget, hitlMode: 'DIRECTION_ONLY' as const };
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
        syncResearchSnapshot(newId);
        navigate(`/research/${newId}`);
      } catch (e: any) {
        setError(e.message || 'Failed to start research');
        setViewState('chat');
        setInputValue(content);
      }
      return;
    }

    if (!currentResearch) return;

    connectSSE(currentResearch.id);

    const userMsg: ChatMessage = {
      id: Date.now(),
      researchId: currentResearch.id,
      role: 'user',
      content,
      createTime: new Date().toISOString()
    };
    // 研究中不允许发送新消息
    const activeResearchStatuses = ['QUEUE', 'START', 'RUNNING', 'IN_SCOPE', 'IN_RESEARCH', 'IN_REPORT'];
    if (currentResearch.status && activeResearchStatuses.includes(currentResearch.status.toUpperCase())) {
      setError('研究正在进行中，请等待完成，或点击「取消」终止当前研究');
      return;
    }

    const shouldAttachModel = !currentResearch.modelId;
    const modelConfig = shouldAttachModel ? { modelId: resolvedModelId, budget: selectedBudget, hitlMode: 'DIRECTION_ONLY' as const } : undefined;

    setCurrentResearch(prev => prev ? {
      ...prev,
      status: 'RUNNING',
      modelId: shouldAttachModel ? resolvedModelId : prev.modelId,
      messages: [...prev.messages, userMsg]
    } : prev);

    try {
      await researchApi.sendMessage(currentResearch.id, content, modelConfig);
      const snapshot = await syncResearchSnapshot(currentResearch.id);
      if (shouldConnectLiveSse(snapshot?.status)) {
        connectSSE(currentResearch.id);
      }
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
    <div className="flex h-full min-h-0 flex-1 overflow-hidden">
    <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-[#fbfbf8]">
      {viewState === 'loading' && !currentResearch && (
        <div className="flex flex-1 items-center justify-center">
          <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
            <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
          </div>
        </div>
      )}
      
      {/* Header for Existing Chat */}
      {!isNewChat && currentResearch && (
        <div className={`z-10 shrink-0 border-b border-gray-200/70 bg-[#fbfbf8]/90 px-6 py-4 backdrop-blur transition-all duration-300 ${!sidebarOpen ? 'pl-16' : ''}`}>
          <div className="mx-auto flex max-w-5xl items-start justify-between gap-4">
            <div className="min-w-0">
              <h2 className="truncate text-[17px] font-semibold tracking-tight text-gray-950">{currentResearch.title}</h2>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <div className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium ${getStatusTone(currentResearch.status)}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${isConnected ? 'animate-pulse bg-emerald-500' : getStatusDot(currentResearch.status)}`} />
                  {getStatusLabel(currentResearch.status)}
                </div>
                {currentResearch.modelId && (
                  <div className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-600">
                    <Brain className="h-3 w-3" />
                    <span>
                      模型：{modelDictionary[currentResearch.modelId]?.name || modelDictionary[currentResearch.modelId]?.model || currentResearch.modelId}
                    </span>
                  </div>
                )}
                {currentResearch.budget && (
                  <div className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-600">
                    <Coins className="h-3 w-3" />
                    <span>预算：{BUDGET_OPTIONS.find(b => b.value === currentResearch.budget)?.label || currentResearch.budget}</span>
                  </div>
                )}
                {(currentResearch.totalInputTokens || currentResearch.totalOutputTokens) && (
                  <div className="inline-flex items-center gap-2 rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium tabular-nums text-gray-600">
                    <span className="flex items-center gap-1.5">
                      <Coins className="h-3 w-3" />
                      <span>输入: {(currentResearch.totalInputTokens || 0).toLocaleString()}</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span>输出: {(currentResearch.totalOutputTokens || 0).toLocaleString()}</span>
                    </span>
                  </div>
                )}
                {currentResearch.startTime && currentResearch.completeTime && (
                  <div className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-600">
                    <Clock className="h-3 w-3" />
                    <span>{formatDuration(currentResearch.startTime, currentResearch.completeTime)}</span>
                  </div>
                )}
              </div>
            </div>
            {/* Cancel / Expand buttons */}
            <div className="flex shrink-0 items-center gap-2">
              {currentResearch && !['COMPLETED', 'FAILED', 'CANCELLED', 'NEED_CLARIFICATION'].includes(currentResearch.status) && (
                <button
                  onClick={handleCancelResearch}
                  className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2 text-sm font-semibold text-red-700 transition-colors hover:bg-red-100"
                  title="取消研究"
                >
                  <AlertCircle className="h-4 w-4" />
                  <span>取消</span>
                </button>
              )}
              <button
                onClick={() => setAllEventsExpanded(!allEventsExpanded)}
                className={`flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${
                  allEventsExpanded
                    ? 'bg-gray-950 text-white hover:bg-gray-800'
                    : 'border border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                }`}
                title={allEventsExpanded ? '收起所有事件详情' : '展开所有事件详情'}
              >
                <ChevronsUpDown className="h-4 w-4" />
                <span>{allEventsExpanded ? '收起详情' : '展开详情'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        {!isNewChat && (
          <div className="flex-1 space-y-7 overflow-y-auto px-6 py-8 scroll-smooth">
            {timelineItems.map((item, idx) => {
              if (item.type === 'message') {
                const isUser = item.data.role === 'user';
                const isReport = !isUser && idx === timelineItems.length - 1 && currentResearch?.status === 'COMPLETED';
                const isLatestAssistant = !isUser && idx === timelineItems.length - 1 && currentResearch?.status !== 'COMPLETED';

                if (isReport) {
                  return (
                    <div
                      key={`msg-${item.data.id}`}
                      ref={(el) => { if (el) finalReportRef.current = el; }}
                      className="mx-auto w-full max-w-4xl"
                    >
                      <div className="rounded-[1.35rem] border border-gray-200 bg-white p-8 shadow-sm shadow-gray-200/60">
                        <div className="mb-6 flex items-center gap-2 border-b border-gray-100 pb-4">
                          <FileSearch className="h-5 w-5 text-gray-950" />
                          <span className="text-lg font-semibold tracking-tight text-gray-950">Final Report</span>
                        </div>
                        <article>
                          <MessageMarkdown content={item.data.content} />
                        </article>
                      </div>
                    </div>
                  );
                }

                const isClarifyMessage = !isUser && currentResearch?.status === 'NEED_CLARIFICATION' && idx === timelineItems.length - 1 && !!clarifyFormFromEvents;

                if (isClarifyMessage && clarifyFormFromEvents) {
                  return (
                    <div key={`msg-${item.data.id}`} className="mx-auto flex w-full max-w-4xl gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-white text-gray-600 shadow-sm">
                        <Bot className="h-4 w-4" />
                      </div>
                      <div className="w-full max-w-3xl">
                        <div className="mb-3 rounded-2xl rounded-tl-md border border-gray-200 bg-white px-5 py-4 shadow-sm shadow-gray-200/60">
                          <MessageMarkdown content={item.data.content} animateText={isLatestAssistant} />
                        </div>
                        <div className="rounded-2xl border border-gray-200 bg-white px-6 py-5 shadow-sm shadow-gray-200/60">
                          <h3 className="mb-4 text-sm font-semibold text-gray-950">
                            {clarifyFormFromEvents.title || '请完善以下信息'}
                          </h3>
                          <div className="space-y-5">
                            {clarifyFormFromEvents.questions.map((q) => {
                              if (q.type === 'multi_choice') {
                                const selectedOptions = (clarifyFormAnswers[q.id] as string[]) || [];
                                return (
                                  <div key={q.id}>
                                    <p className="mb-2 text-sm font-medium text-gray-800">{q.text}</p>
                                    <div className="space-y-2">
                                      {(q.options || []).map((opt) => {
                                        const isOtherOption = opt === '其他';
                                        return (
                                          <label
                                            key={opt}
                                            className={`flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2.5 transition-colors ${
                                              selectedOptions.includes(opt)
                                                ? 'border-gray-950 bg-gray-950/[0.04]'
                                                : 'border-gray-200 bg-gray-50/50 hover:border-gray-300 hover:bg-white'
                                            }`}
                                          >
                                            <input
                                              type="checkbox"
                                              checked={selectedOptions.includes(opt)}
                                              onChange={(e) => handleClarifyCheckboxChange(q.id, opt, e.target.checked)}
                                              className="h-4 w-4 rounded border-gray-300 text-gray-950 focus:ring-gray-950"
                                            />
                                            <span className="text-sm text-gray-700">{opt}</span>
                                            {isOtherOption && (
                                              <input
                                                type="text"
                                                value={clarifyOtherInputs[q.id] || ''}
                                                onChange={(e) => handleClarifyOtherChange(q.id, e.target.value)}
                                                placeholder="请填写..."
                                                className="ml-2 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm focus:border-gray-300 focus:outline-none focus:ring-2 focus:ring-gray-950/5"
                                              />
                                            )}
                                          </label>
                                        );
                                      })}
                                      {q.allowOther && !(q.options || []).some(opt => opt === '其他') && (
                                        <label
                                          className={`flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2.5 transition-colors ${
                                            clarifyOtherInputs[q.id]
                                              ? 'border-gray-950 bg-gray-950/[0.04]'
                                              : 'border-gray-200 bg-gray-50/50 hover:border-gray-300 hover:bg-white'
                                          }`}
                                        >
                                          <input
                                            type="checkbox"
                                            checked={!!clarifyOtherInputs[q.id]}
                                            onChange={(e) => {
                                              if (!e.target.checked) handleClarifyOtherChange(q.id, '');
                                            }}
                                            className="h-4 w-4 rounded border-gray-300 text-gray-950 focus:ring-gray-950"
                                          />
                                          <span className="text-sm text-gray-700">其他</span>
                                          <input
                                            type="text"
                                            value={clarifyOtherInputs[q.id] || ''}
                                            onChange={(e) => handleClarifyOtherChange(q.id, e.target.value)}
                                            onFocus={() => { if (!clarifyOtherInputs[q.id]) handleClarifyOtherChange(q.id, ' '); }}
                                            placeholder="请填写..."
                                            className="ml-2 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm focus:border-gray-300 focus:outline-none focus:ring-2 focus:ring-gray-950/5"
                                          />
                                        </label>
                                      )}
                                    </div>
                                  </div>
                                );
                              }

                              return (
                                <div key={q.id}>
                                  <p className="mb-2 text-sm font-medium text-gray-800">{q.text}</p>
                                  <textarea
                                    value={(clarifyFormAnswers[q.id] as string) || ''}
                                    onChange={(e) => handleClarifyOpenEndedChange(q.id, e.target.value)}
                                    placeholder="请输入您的回答..."
                                    rows={3}
                                    className="w-full resize-none rounded-xl border border-gray-200 bg-gray-50/70 px-4 py-2.5 text-sm placeholder:text-gray-400 transition-colors focus:border-gray-300 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gray-950/5"
                                  />
                                </div>
                              );
                            })}
                          </div>
                          <div className="mt-5 flex justify-end">
                            <button
                              onClick={handleClarifySubmit}
                              disabled={isClarifySubmitting}
                              className="flex items-center gap-2 rounded-xl bg-gray-950 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
                            >
                              {isClarifySubmitting ? (
                                <><Loader2 className="h-4 w-4 animate-spin" /> 提交中...</>
                              ) : (
                                <><Send className="h-4 w-4" /> 提交答案</>
                              )}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                }

                const isHitlMessage = !isUser && currentResearch?.status === 'AWAITING_DIRECTION_CONFIRM' && idx === timelineItems.length - 1;
                const isNeedClarifyMessage = !isUser && currentResearch?.status === 'NEED_CLARIFICATION' && idx === timelineItems.length - 1 && !clarifyFormFromEvents;
                return (
                  <div key={`msg-${item.data.id}`} className={`mx-auto flex w-full max-w-4xl gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
                    <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl shadow-sm ${isUser ? 'bg-gray-950 text-white' : 'border border-gray-200 bg-white text-gray-600'}`}>
                      {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                    </div>
                    <div className={`flex max-w-full items-start gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
                      <div className={`max-w-3xl rounded-2xl px-5 py-4 ${
                        isUser
                          ? 'rounded-tr-md bg-gray-950 text-white shadow-sm shadow-gray-900/10'
                          : 'rounded-tl-md border border-gray-200 bg-white text-gray-800 shadow-sm shadow-gray-200/60'
                      }`}>
                        <div className={isUser ? 'whitespace-pre-wrap text-sm leading-6 text-white' : ''}>
                          {isUser ? item.data.content : <MessageMarkdown content={item.data.content} animateText={isLatestAssistant} />}
                        </div>
                        {isHitlMessage && hitlResearchBrief && (
                          <div className="mt-4 border-t border-amber-200 pt-3">
                            {isHitlConfirming ? (
                              <div className="flex items-center gap-2 py-2 text-sm text-gray-500">
                                <Loader2 className="h-4 w-4 animate-spin" />正在处理...
                              </div>
                            ) : (
                              <div className="space-y-2">
                                <button
                                  onClick={() => handleHitlConfirm('APPROVE')}
                                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-700"
                                >
                                  <CheckCircle2 className="h-4 w-4" /> 确认方向，开始研究
                                </button>
                                <div className="flex items-start gap-2">
                                  <textarea
                                    value={hitlReviseFeedback}
                                    onChange={(e) => setHitlReviseFeedback(e.target.value)}
                                    placeholder="输入修改意见..."
                                    rows={2}
                                    className="min-w-0 flex-1 resize-none rounded-xl border border-gray-200 bg-gray-50/70 px-3 py-2 text-sm text-gray-900 outline-none transition-colors placeholder:text-gray-400 focus:border-gray-300 focus:bg-white focus:ring-2 focus:ring-gray-950/5"
                                  />
                                  <button
                                    onClick={() => handleHitlConfirm('REVISE', hitlReviseFeedback)}
                                    className="shrink-0 rounded-xl bg-amber-600 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-amber-700"
                                  >
                                    提交修改
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                      {isNeedClarifyMessage && (
                        <div className="mt-4 border-t border-gray-200 pt-3">
                          {isClarifyTextSubmitting ? (
                            <div className="flex items-center gap-2 py-2 text-sm text-gray-500">
                              <Loader2 className="h-4 w-4 animate-spin" />正在处理...
                            </div>
                          ) : (
                            <div className="flex items-start gap-2">
                              <textarea
                                value={clarifyTextInput}
                                onChange={(e) => setClarifyTextInput(e.target.value)}
                                placeholder="输入您的回答..."
                                rows={2}
                                className="min-w-0 flex-1 resize-none rounded-xl border border-gray-200 bg-gray-50/70 px-3 py-2 text-sm outline-none transition-colors placeholder:text-gray-400 focus:border-gray-300 focus:bg-white focus:ring-2 focus:ring-gray-950/5"
                              />
                              <button
                                onClick={handleClarifyTextSubmit}
                                disabled={!clarifyTextInput.trim() || isClarifyTextSubmitting}
                                className="shrink-0 rounded-xl bg-gray-950 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
                              >
                                {isClarifyTextSubmitting ? (
                                  <><Loader2 className="h-4 w-4 animate-spin" /> 提交中...</>
                                ) : (
                                  <><Send className="h-4 w-4" /> 提交回答</>
                                )}
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                      {renderCopyButton(item.data, isUser)}
                    </div>
                  </div>
                );
              }

              const flattenEvents = flattenTree(item.events);
              if (flattenEvents.length === 0) return null;
              return (
                <div key={`group-${idx}`} className="mx-auto flex w-full max-w-4xl gap-0">
                  <div className="flex w-9 shrink-0 justify-center">
                    <div className="h-full w-px rounded-full bg-gray-200" />
                  </div>
                  <div className="-ml-4 flex-1 space-y-2 py-2">
                    {flattenEvents.map((evt) => {
                      const style = getEventStyle(evt.type);
                      const Icon = style.icon;
                      return (
                        <div key={evt.id} className="relative pl-4" style={{ marginLeft: evt.depth * 20 }}>
                          <div className={`absolute -left-[5px] top-1 h-2.5 w-2.5 rounded-full border-2 border-[#fbfbf8] ${style.bg.replace('bg-', 'bg-').replace('50', '400')}`} />
                          {evt.content && evt.content !== evt.title ? (
                            <details className="group rounded-xl" open={allEventsExpanded}>
                              <summary className="flex cursor-pointer list-none items-start gap-2 [&::-webkit-details-marker]:hidden">
                                <div className={`shrink-0 rounded-lg p-1.5 ${style.bg} ${style.color}`}><Icon className="h-3.5 w-3.5" /></div>
                                <div className="text-sm font-medium text-gray-900 group-hover:text-gray-600">{evt.title}</div>
                              </summary>
                              <div className="ml-10 mt-1 rounded-xl border border-gray-100 bg-white/80 p-3 font-mono text-xs text-gray-500 shadow-sm whitespace-pre-wrap break-all">{evt.content}</div>
                            </details>
                          ) : (
                            <div className="flex items-start gap-2">
                              <div className={`shrink-0 rounded-lg p-1.5 ${style.bg} ${style.color}`}><Icon className="h-3.5 w-3.5" /></div>
                              <div className="text-sm font-medium text-gray-900">{evt.title}</div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            <div ref={chatEndRef} />
          </div>
        )}

        <div className={`${isNewChat ? 'flex-1 flex flex-col items-center justify-center p-8' : 'border-t border-gray-200/70 bg-[#fbfbf8]/95 p-6 shrink-0'}`}>
          <div className={`mx-auto w-full ${isNewChat ? 'max-w-2xl' : 'max-w-4xl'}`}>
            {isNewChat && (
              <div className="mb-12 text-center">
                <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gray-950 shadow-xl shadow-gray-200">
                  <Bot className="h-8 w-8 text-white" />
                </div>
                <h2 className="mb-2 text-2xl font-semibold tracking-tight text-gray-950">What would you like to research?</h2>
                <p className="text-sm text-gray-500">Ask a focused question and choose the model/budget before the first run.</p>
              </div>
            )}

            {error && (
              <div className="mb-4 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 animate-in fade-in slide-in-from-top-2">
                <AlertCircle className="h-4 w-4" />{error}
              </div>
            )}

            <AI_Prompt
              value={inputValue}
              onValueChange={setInputValue}
              onSubmit={sendMessage}
              placeholder={isNewChat ? "Start a deep research..." : "Ask a follow-up..."}
              className="relative z-20 py-0"
              models={inputModelOptions}
              selectedModel={currentResearch?.modelId || selectedModelId}
              onModelChange={setSelectedModelId}
              modelDisabled={Boolean(currentResearch?.modelId)}
              modelLoading={modelListLoading}
              onRefreshModels={() => refreshModelList()}
              onManageModels={() => setIsModelManagerOpen(true)}
              showBudget={isNewChat || !currentResearch?.modelId}
              budgetOptions={BUDGET_OPTIONS}
              selectedBudget={selectedBudget}
              onBudgetChange={(value) => setSelectedBudget(value as BudgetValue)}
            />

            {isNewChat && (
              <div className="mt-8 flex flex-wrap justify-center gap-3">
                {['Market Analysis', 'Scientific Review', 'Code Architecture'].map((topic) => (
                  <button key={topic} onClick={() => setInputValue(topic)} className="rounded-full border border-gray-200 bg-white px-4 py-2 text-sm text-gray-600 shadow-sm transition-colors hover:bg-gray-50">
                    {topic}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
    <AgentFlowPanel
      title={currentResearch?.title || 'New research'}
      status={currentResearch ? getStatusLabel(currentResearch.status) : '等待会话事件'}
      events={currentResearch?.events || []}
      messages={currentResearch?.messages || []}
    />
    </div>
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
    <div className="relative flex h-[100dvh] overflow-hidden bg-white">
      <Sidebar isOpen={sidebarOpen} toggle={() => setSidebarOpen(false)} />
      
      {!sidebarOpen && (
        <button 
            onClick={() => setSidebarOpen(true)}
            className="absolute top-3 left-3 z-50 p-2 bg-white/80 backdrop-blur border border-gray-200 rounded-lg shadow-sm hover:bg-gray-50 transition-all"
        >
            <PanelLeftOpen className="w-5 h-5 text-gray-600" />
        </button>
      )}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
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
        <Route path="/*" element={<AppContent />} />
      </Routes>
    </AuthProvider>
  );
}

export default App;
