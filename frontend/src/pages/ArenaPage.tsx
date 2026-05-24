import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AlertCircle, Bot, CheckCircle2, Clock, Coins, Copy, Loader2, RefreshCw, Shield, User, Zap } from 'lucide-react';
import { researchApi, modelApi, ModelInfo, ChatMessage, WorkflowEvent } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { ModelManagerModal } from '../components/ModelManagerModal';
import { BUDGET_OPTIONS, BudgetValue } from '../constants/budget';
import { formatAppDateTime } from '../constants/time';

const MAX_MODELS = 3;
const ACTIVE_STATUSES = new Set(['PENDING', 'NEW', 'QUEUE', 'START', 'RUNNING', 'IN_SCOPE', 'IN_RESEARCH', 'IN_REPORT']);
const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);

function sortEventsChronologically(events: WorkflowEvent[] = []) {
  return [...events].sort((a, b) => {
    const seqDiff = (a.sequenceNo ?? 0) - (b.sequenceNo ?? 0);
    if (seqDiff !== 0) return seqDiff;
    const aTime = a.createTime ? new Date(a.createTime).getTime() : 0;
    const bTime = b.createTime ? new Date(b.createTime).getTime() : 0;
    return aTime - bTime;
  });
}

interface ArenaRun {
  researchId: string;
  modelId: string;
  modelName: string;
  modelIdentifier?: string;
  status: string;
  messages: ChatMessage[];
  events: WorkflowEvent[];
  startTime?: string;
  completeTime?: string;
  totalInputTokens?: number;
  totalOutputTokens?: number;
  error?: string | null;
  isSending?: boolean;
}

interface ArenaPageProps {
  sidebarOpen?: boolean;
}

type StatusMeta = { label: string; color: string; bg: string };

const STATUS_META: Record<string, StatusMeta> = {
  COMPLETED: { label: '已完成', color: 'text-green-600', bg: 'bg-green-50' },
  FAILED: { label: '失败', color: 'text-red-600', bg: 'bg-red-50' },
  RUNNING: { label: '运行中', color: 'text-blue-600', bg: 'bg-blue-50' },
  IN_SCOPE: { label: '规划中', color: 'text-purple-600', bg: 'bg-purple-50' },
  IN_RESEARCH: { label: '调研中', color: 'text-amber-600', bg: 'bg-amber-50' },
  IN_REPORT: { label: '写报告', color: 'text-indigo-600', bg: 'bg-indigo-50' },
  START: { label: '运行中', color: 'text-blue-600', bg: 'bg-blue-50' },
  QUEUE: { label: '排队中', color: 'text-gray-600', bg: 'bg-gray-100' },
  PENDING: { label: '准备中', color: 'text-gray-600', bg: 'bg-gray-100' },
  NEW: { label: '准备中', color: 'text-gray-600', bg: 'bg-gray-100' },
  CANCELLED: { label: '已取消', color: 'text-gray-500', bg: 'bg-gray-100' },
};

function getStatusMeta(status?: string): StatusMeta {
  if (!status) return { label: '未知', color: 'text-gray-600', bg: 'bg-gray-100' };
  const key = status.toUpperCase();
  return STATUS_META[key] || { label: status, color: 'text-gray-600', bg: 'bg-gray-100' };
}

/**
 * 解析后端返回的时间字符串
 * 后端已配置输出带时区偏移的ISO格式，直接解析即可
 */
function parseServerTime(timeStr?: string): number {
  if (!timeStr) return 0;
  const ts = new Date(timeStr).getTime();
  return Number.isNaN(ts) ? 0 : ts;
}

function formatDuration(start?: string, end?: string, status?: string) {
  if (!start) return '--';
  const startMs = parseServerTime(start);
  const endMs = end ? parseServerTime(end) : Date.now();
  const diff = Math.max(endMs - startMs, 0);
  if (!Number.isFinite(diff) || diff <= 0) return '--';
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const remain = seconds % 60;
  if (minutes > 0) {
    return `${minutes}分${remain.toString().padStart(2, '0')}秒${!end && status && !TERMINAL_STATUSES.has(status.toUpperCase()) ? '（进行中）' : ''}`;
  }
  return `${seconds}秒${!end && status && !TERMINAL_STATUSES.has(status.toUpperCase()) ? '（进行中）' : ''}`;
}

function formatTokens(run: ArenaRun) {
  const input = run.totalInputTokens;
  const output = run.totalOutputTokens;
  // 没有数据或者都是0时显示 --
  if ((input === undefined || input === null) && (output === undefined || output === null)) return '--';
  if (!input && !output) return '--';
  return `输入 ${input || 0} / 输出 ${output || 0} / 合计 ${(input || 0) + (output || 0)}`;
}

function extractFinalMessage(messages: ChatMessage[]) {
  if (!messages?.length) return null;
  const assistants = messages.filter((m) => m.role === 'assistant');
  return assistants.length ? assistants[assistants.length - 1] : null;
}

function formatTime(time?: string) {
  return formatAppDateTime(time);
}

export function ArenaPage({ sidebarOpen = true }: ArenaPageProps) {
  const { isAuthenticated } = useAuth();
  const [topicInput, setTopicInput] = useState('');
  const [arenaTopic, setArenaTopic] = useState<string>('');
  const [arenaStartedAt, setArenaStartedAt] = useState<string | null>(null);
  const [selectedBudget, setSelectedBudget] = useState<BudgetValue>('HIGH');
  const [modelList, setModelList] = useState<ModelInfo[]>([]);
  const [modelListLoading, setModelListLoading] = useState(false);
  const [selectedModelIds, setSelectedModelIds] = useState<string[]>([]);
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [isModelManagerOpen, setIsModelManagerOpen] = useState(false);
  const [arenaRuns, setArenaRuns] = useState<ArenaRun[]>([]);
  const [isLaunching, setIsLaunching] = useState(false);
  const [arenaError, setArenaError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'grid' | 'tabs'>('grid');
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [copiedRunId, setCopiedRunId] = useState<string | null>(null);

  const modelMenuRef = useRef<HTMLDivElement>(null);
  const pollingTimersRef = useRef<Record<string, number>>({});
  const copyResetTimeoutRef = useRef<number | null>(null);

  const modelDictionary = useMemo(() => {
    const map: Record<string, ModelInfo> = {};
    modelList.forEach((model) => {
      map[model.id] = model;
    });
    return map;
  }, [modelList]);

  const groupedModels = useMemo(() => ({
    platform: modelList.filter((m) => m.type === 'GLOBAL'),
    user: modelList.filter((m) => m.type === 'USER'),
  }), [modelList]);

  const selectedModelInfos = useMemo(() => selectedModelIds.map((id) => modelDictionary[id]).filter(Boolean), [selectedModelIds, modelDictionary]);

  const hasActiveRuns = arenaRuns.some((run) => ACTIVE_STATUSES.has((run.status || '').toUpperCase()));
  const totalRuns = arenaRuns.length;
  const finishedRuns = arenaRuns.filter((run) => TERMINAL_STATUSES.has((run.status || '').toUpperCase())).length;
  const completionPercent = totalRuns ? Math.round((finishedRuns / totalRuns) * 100) : 0;

  const stopPolling = useCallback((researchId: string) => {
    const timer = pollingTimersRef.current[researchId];
    if (timer) {
      window.clearTimeout(timer);
      delete pollingTimersRef.current[researchId];
    }
  }, []);

  const stopAllPolling = useCallback(() => {
    Object.keys(pollingTimersRef.current).forEach((key) => stopPolling(key));
  }, [stopPolling]);

  const pollResearch = useCallback(async (researchId: string) => {
    try {
      const resp = await researchApi.getMessages(researchId);
      const normalizedEvents = sortEventsChronologically(resp.events || []);
      setArenaRuns((prev) => prev.map((run) => run.researchId === researchId ? {
        ...run,
        status: resp.status,
        messages: resp.messages,
        events: normalizedEvents,
        startTime: resp.startTime ?? run.startTime,
        completeTime: resp.completeTime ?? run.completeTime,
        totalInputTokens: resp.totalInputTokens ?? run.totalInputTokens,
        totalOutputTokens: resp.totalOutputTokens ?? run.totalOutputTokens,
        error: null,
      } : run));
      const nextStatus = (resp.status || '').toUpperCase();
      if (!TERMINAL_STATUSES.has(nextStatus)) {
        stopPolling(researchId);
        pollingTimersRef.current[researchId] = window.setTimeout(() => pollResearch(researchId), 2500);
      } else {
        stopPolling(researchId);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '同步进度失败';
      setArenaRuns((prev) => prev.map((run) => run.researchId === researchId ? { ...run, error: message } : run));
      stopPolling(researchId);
      pollingTimersRef.current[researchId] = window.setTimeout(() => pollResearch(researchId), 4000);
    }
  }, [stopPolling]);

  useEffect(() => {
    return () => {
      stopAllPolling();
      if (copyResetTimeoutRef.current) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, [stopAllPolling]);

  const refreshModelList = useCallback(async (preferredModelId?: string) => {
    if (!isAuthenticated) {
      setModelList([]);
      setSelectedModelIds([]);
      return;
    }
    setModelListLoading(true);
    try {
      const list = await modelApi.getAvailableModels();
      setModelList(list);
      setSelectedModelIds((prev) => {
        const stillValid = prev.filter((id) => list.some((m) => m.id === id));
        if (preferredModelId && list.some((m) => m.id === preferredModelId)) {
          if (!stillValid.includes(preferredModelId) && stillValid.length < MAX_MODELS) {
            return [...stillValid, preferredModelId];
          }
          return stillValid;
        }
        if (stillValid.length > 0) return stillValid;
        return list.slice(0, Math.min(MAX_MODELS, list.length)).map((model) => model.id);
      });
    } catch (error) {
      console.error('加载模型失败', error);
    } finally {
      setModelListLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    refreshModelList();
  }, [refreshModelList]);

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
    if (arenaRuns.length === 0) {
      setActiveTabId(null);
      return;
    }
    if (!activeTabId || !arenaRuns.some((run) => run.researchId === activeTabId)) {
      setActiveTabId(arenaRuns[0].researchId);
    }
  }, [arenaRuns, activeTabId]);

  const toggleModelSelection = (modelId: string) => {
    setSelectedModelIds((prev) => {
      if (prev.includes(modelId)) {
        return prev.filter((id) => id !== modelId);
      }
      if (prev.length >= MAX_MODELS) {
        return prev;
      }
      return [...prev, modelId];
    });
  };

  const handleReset = useCallback((force = false) => {
    if (!force && hasActiveRuns) {
      const confirmReset = window.confirm('当前有模型仍在运行，确定要清空并放弃这次对比吗？');
      if (!confirmReset) return;
    }
    stopAllPolling();
    setArenaRuns([]);
    setArenaTopic('');
    setArenaStartedAt(null);
    setActiveTabId(null);
    setArenaError(null);
  }, [hasActiveRuns, stopAllPolling]);

  const startArena = async () => {
    const content = topicInput.trim();
    if (!content) {
      setArenaError('请输入研究主题');
      return;
    }
    if (selectedModelIds.length === 0) {
      setArenaError('请至少选择一个模型');
      return;
    }
    if (arenaRuns.length > 0) {
      setArenaError('请先清空当前对比结果，然后再发起新的 Arena 会话。');
      return;
    }
    setArenaError(null);
    setIsLaunching(true);
    try {
      const created = await researchApi.create(selectedModelIds.length);
      const ids = created.researchIds || [];
      if (ids.length < selectedModelIds.length) {
        throw new Error('没有分配足够的研究 ID');
      }
      const runs: ArenaRun[] = selectedModelIds.map((modelId, index) => {
        const assignedId = ids[index];
        const model = modelDictionary[modelId];
        return {
          researchId: assignedId,
          modelId,
          modelName: model?.name || model?.model || `模型 ${index + 1}`,
          modelIdentifier: model?.model,
          status: 'START',
          messages: [],
          events: [],
          isSending: true,
        };
      });
      setArenaTopic(content);
      setArenaStartedAt(new Date().toISOString());
      setArenaRuns(runs);
      setActiveTabId(runs[0]?.researchId || null);

      await Promise.allSettled(runs.map(async (run) => {
        try {
          await researchApi.sendMessage(run.researchId, content, { modelId: run.modelId, budget: selectedBudget });
          setArenaRuns((prev) => prev.map((item) => item.researchId === run.researchId ? { ...item, status: 'RUNNING', isSending: false } : item));
          pollResearch(run.researchId);
        } catch (error) {
          const message = error instanceof Error ? error.message : '触发研究失败';
          setArenaRuns((prev) => prev.map((item) => item.researchId === run.researchId ? { ...item, status: 'FAILED', error: message, isSending: false } : item));
        }
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : '启动 Arena 失败';
      setArenaError(message);
      setArenaRuns([]);
      setArenaTopic('');
      setArenaStartedAt(null);
      stopAllPolling();
    } finally {
      setIsLaunching(false);
    }
  };

  const handleCopyReport = useCallback((runId: string, text: string) => {
    if (!text?.trim()) return;
    if (!navigator?.clipboard) {
      setArenaError('当前环境不支持复制');
      return;
    }
    navigator.clipboard.writeText(text).then(() => {
      setCopiedRunId(runId);
      if (copyResetTimeoutRef.current) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
      copyResetTimeoutRef.current = window.setTimeout(() => setCopiedRunId(null), 2000);
    }).catch((err) => {
      console.error('复制失败', err);
      setArenaError('复制失败，请稍后再试');
    });
  }, []);

  const renderRunCard = (run: ArenaRun) => {
    const statusMeta = getStatusMeta(run.status);
    const report = extractFinalMessage(run.messages);
    return (
      <div key={run.researchId} className="flex flex-col border border-gray-200 rounded-2xl bg-white p-5 shadow-sm min-h-[420px]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-gray-500">模型</p>
            <p className="text-lg font-semibold text-gray-900">{run.modelName}</p>
            <p className="text-xs text-gray-500">{run.modelIdentifier || run.modelId}</p>
          </div>
          <div className={`px-3 py-1.5 rounded-full text-xs font-semibold ${statusMeta.bg} ${statusMeta.color} flex items-center gap-1`}>
            {run.status?.toUpperCase() === 'COMPLETED' && <CheckCircle2 className="w-3.5 h-3.5" />}
            {run.status && !TERMINAL_STATUSES.has(run.status.toUpperCase()) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            <span>{statusMeta.label}</span>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs text-gray-500 flex items-center gap-1"><Coins className="w-3.5 h-3.5" />Tokens</div>
            <div className="text-sm font-semibold text-gray-900 mt-0.5">{formatTokens(run)}</div>
          </div>
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs text-gray-500 flex items-center gap-1"><Clock className="w-3.5 h-3.5" />耗时</div>
            <div className="text-sm font-semibold text-gray-900 mt-0.5">{formatDuration(run.startTime, run.completeTime, run.status)}</div>
          </div>
        </div>

        <div className="mt-4 flex-1 flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-semibold text-gray-900">研究报告</p>
            {report?.content && (
              <button
                className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-lg border ${copiedRunId === run.researchId ? 'border-green-200 text-green-600 bg-green-50' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}
                onClick={() => handleCopyReport(run.researchId, report.content)}
              >
                <Copy className="w-3.5 h-3.5" /> {copiedRunId === run.researchId ? '已复制' : '复制'}
              </button>
            )}
          </div>
          <div className="flex-1 rounded-xl border border-gray-100 bg-gray-50 p-3 overflow-y-auto max-h-72">
            {run.error && (
              <div className="text-sm text-red-600 flex items-center gap-2"><AlertCircle className="w-4 h-4" />{run.error}</div>
            )}
            {!run.error && report?.content && (
              <ReactMarkdown className="prose prose-sm max-w-none" remarkPlugins={[remarkGfm]}>{report.content}</ReactMarkdown>
            )}
            {!run.error && !report?.content && (
              <div className="text-sm text-gray-500 flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />等待模型输出...
              </div>
            )}
          </div>
        </div>

        <div className="mt-4">
          <p className="text-xs font-semibold text-gray-500">关键事件</p>
          {run.events.length ? (
            <div className="mt-2 space-y-2 max-h-32 overflow-y-auto pr-1">
              {sortEventsChronologically(run.events).slice(-4).reverse().map((evt) => (
                <div key={`${evt.id ?? evt.sequenceNo}-${evt.createTime ?? ''}`} className="p-2 rounded-lg border border-gray-100 bg-gray-50">
                  <p className="text-sm font-medium text-gray-900">{evt.title}</p>
                  <p className="text-xs text-gray-500">{formatTime(evt.createTime)}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-400 mt-1">还没有事件...</p>
          )}
        </div>
      </div>
    );
  };

  const comparisonRows = useMemo(() => arenaRuns.map((run) => ({
    model: run.modelName,
    status: getStatusMeta(run.status).label,
    tokens: formatTokens(run),
    duration: formatDuration(run.startTime, run.completeTime, run.status),
  })), [arenaRuns]);

  return (
    <main className="flex-1 flex flex-col overflow-hidden bg-white">
      <div className={`border-b border-gray-100 px-6 py-4 flex flex-col gap-4 ${!sidebarOpen ? 'pl-16' : ''}`}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-sm text-gray-500 uppercase tracking-wide">LLM Arena</p>
            <h1 className="text-2xl font-semibold text-gray-900">多模型深度研究对比</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setViewMode('grid')}
              className={`px-3 py-1.5 rounded-full text-sm border ${viewMode === 'grid' ? 'bg-black text-white border-black' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}
            >
              并列
            </button>
            <button
              onClick={() => setViewMode('tabs')}
              className={`px-3 py-1.5 rounded-full text-sm border ${viewMode === 'tabs' ? 'bg-black text-white border-black' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}
            >
              卡片
            </button>
            <button
              onClick={() => refreshModelList()}
              className="p-2 rounded-full border border-gray-200 text-gray-500 hover:bg-gray-50"
              disabled={modelListLoading}
            >
              <RefreshCw className={`w-4 h-4 ${modelListLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

{/* 运行中：紧凑的一行摘要 */}
        {arenaRuns.length > 0 ? (
          <div className="bg-[#f4f4f4] rounded-2xl px-4 py-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-2">
                <Bot className="w-4 h-4 text-gray-500" />
                <span className="font-medium text-gray-900 max-w-[300px] truncate">{arenaTopic}</span>
              </div>
              <div className="h-4 w-px bg-gray-300" />
              <div className="flex items-center gap-1.5 text-gray-600">
                <Coins className="w-3.5 h-3.5" />
                <span>{BUDGET_OPTIONS.find((b) => b.value === selectedBudget)?.label || selectedBudget}</span>
              </div>
              <div className="h-4 w-px bg-gray-300" />
              <div className="flex items-center gap-1.5 text-gray-600">
                <Zap className="w-3.5 h-3.5 text-amber-500" />
                <span>{arenaRuns.map((r) => r.modelName).join('、')}</span>
              </div>
            </div>
            <button
              onClick={() => handleReset()}
              className="px-4 py-1.5 text-sm rounded-xl border border-gray-300 text-gray-600 hover:bg-gray-100"
            >
              清空并重新开始
            </button>
          </div>
        ) : (
          /* 初始状态：完整输入界面 */
          <div className="bg-[#f4f4f4] rounded-2xl p-4 border border-transparent focus-within:border-gray-200">
            {arenaError && (
              <div className="mb-3 text-sm text-red-600 flex items-center gap-2"><AlertCircle className="w-4 h-4" />{arenaError}</div>
            )}
            <textarea
              value={topicInput}
              onChange={(e) => setTopicInput(e.target.value)}
              placeholder="输入想要调研的主题..."
              className="w-full bg-white rounded-2xl border border-gray-200 p-4 text-sm text-gray-900 min-h-[88px]"
              disabled={isLaunching}
            />

            <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="flex flex-col gap-2">
                <span className="text-xs font-semibold text-gray-500 flex items-center gap-1"><Coins className="w-3.5 h-3.5" />预算策略</span>
                <div className="grid grid-cols-3 gap-2">
                  {BUDGET_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setSelectedBudget(option.value)}
                      className={`px-3 py-2 rounded-xl text-left border text-sm ${selectedBudget === option.value ? 'bg-black text-white border-black' : 'border-gray-200 text-gray-700 hover:bg-gray-100'}`}
                    >
                      <span className="font-semibold">{option.label}</span>
                      <span className="block text-[11px] opacity-70">{option.caption}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-2 col-span-1 lg:col-span-2">
                <span className="text-xs font-semibold text-gray-500 flex items-center gap-1"><Zap className="w-3.5 h-3.5 text-amber-500" />模型（最多{MAX_MODELS}个）</span>
                <div ref={modelMenuRef} className="relative">
                  <button
                    onClick={() => setShowModelMenu((prev) => !prev)}
                    className="w-full flex items-center justify-between px-4 py-3 bg-white border border-gray-200 rounded-2xl text-left"
                  >
                    <div>
                      <p className="text-sm font-semibold text-gray-900">{selectedModelInfos.length ? `${selectedModelInfos.length} 个模型已选` : '选择模型'}</p>
                      <p className="text-xs text-gray-500">
                        {selectedModelInfos.map((m) => m?.name || m?.model).filter(Boolean).join('，') || '点击展开并挑选模型'}
                      </p>
                    </div>
                    <ChevronsDownIcon />
                  </button>

                  {showModelMenu && (
                    <div className="absolute z-50 mt-2 w-full bg-white border border-gray-200 rounded-2xl shadow-xl p-4">
                      {[{ key: 'platform', label: '平台内置', icon: <Shield className="w-3.5 h-3.5" />, models: groupedModels.platform }, { key: 'user', label: '我的模型', icon: <User className="w-3.5 h-3.5" />, models: groupedModels.user }].map((section) => (
                        <div key={section.key} className="mb-4 last:mb-0">
                          <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                            {section.icon}
                            <span>{section.label}</span>
                            <span className="text-[10px] text-gray-400">({section.models.length})</span>
                          </div>
                          {section.models.length === 0 ? (
                            <p className="text-xs text-gray-400 mt-1 ml-5">暂无模型</p>
                          ) : (
                            <div className="mt-2 space-y-2">
                              {section.models.map((model) => {
                                const checked = selectedModelIds.includes(model.id);
                                const disabled = !checked && selectedModelIds.length >= MAX_MODELS;
                                return (
                                  <label key={model.id} className={`flex items-center justify-between gap-2 p-3 border rounded-xl cursor-pointer ${checked ? 'border-black bg-black/5' : 'border-gray-200 hover:border-gray-300'} ${disabled ? 'opacity-60 cursor-not-allowed' : ''}`}>
                                    <div>
                                      <p className="text-sm font-semibold text-gray-900">{model.name || model.model}</p>
                                      <p className="text-xs text-gray-500">{model.model}</p>
                                    </div>
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      disabled={disabled}
                                      onChange={() => toggleModelSelection(model.id)}
                                      className="w-4 h-4"
                                    />
                                  </label>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      ))}
                      <div className="mt-4 space-y-2">
                        {selectedModelIds.length >= MAX_MODELS && <p className="text-xs text-amber-600">已达到选择上限</p>}
                        <button
                          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl border border-gray-200 text-sm"
                          onClick={() => { setShowModelMenu(false); setIsModelManagerOpen(true); }}
                        >
                          <PlusIcon /> 管理模型
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between">
              <div className="text-xs text-gray-500">先在这里配置好主题、预算和模型，点击下方即可触发最多 3 个模型并行深入调研。</div>
              <button
                onClick={startArena}
                disabled={isLaunching || !topicInput.trim() || selectedModelIds.length === 0}
                className={`px-5 py-2.5 rounded-2xl text-sm font-semibold flex items-center gap-2 ${isLaunching ? 'bg-gray-300 text-gray-500' : 'bg-black text-white hover:bg-gray-900'}`}
              >
                {isLaunching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bot className="w-4 h-4" />}
                发起对比
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6 bg-gray-50">
        {arenaRuns.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-gray-500">
            <div className="w-16 h-16 bg-white rounded-2xl flex items-center justify-center shadow mb-4">
              <Zap className="w-8 h-8 text-amber-500" />
            </div>
            <p className="text-lg font-semibold text-gray-900 mb-2">准备开启 Arena</p>
            <p className="text-sm text-gray-500 max-w-md">选择最多 3 个模型，输入研究主题，即可在这里并排查看每个模型的调研过程、报告、耗时与 token 消耗。</p>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="bg-white border border-gray-200 rounded-2xl p-4 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-wide">本次对比</p>
                  <p className="text-lg font-semibold text-gray-900">{arenaTopic}</p>
                  <p className="text-xs text-gray-500">开始于 {formatTime(arenaStartedAt || undefined)}</p>
                </div>
                <div className="flex items-center gap-4 text-sm">
                  <div className="flex flex-col text-center">
                    <span className="text-xs text-gray-500">完成度</span>
                    <span className="text-lg font-semibold text-gray-900">{completionPercent}%</span>
                  </div>
                  <div className="flex flex-col text-center">
                    <span className="text-xs text-gray-500">模型数量</span>
                    <span className="text-lg font-semibold text-gray-900">{arenaRuns.length}</span>
                  </div>
                  <div className="flex flex-col text-center">
                    <span className="text-xs text-gray-500">状态</span>
                    <span className="text-lg font-semibold text-gray-900">{finishedRuns}/{arenaRuns.length}</span>
                  </div>
                </div>
              </div>
            </div>

            {viewMode === 'grid' ? (
              <div className={`grid gap-4 ${arenaRuns.length === 1 ? 'grid-cols-1' : arenaRuns.length === 2 ? 'grid-cols-1 md:grid-cols-2' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3'}`}>
                {arenaRuns.map((run) => renderRunCard(run))}
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {arenaRuns.map((run) => (
                    <button key={run.researchId} onClick={() => setActiveTabId(run.researchId)} className={`px-4 py-2 rounded-full text-sm border ${activeTabId === run.researchId ? 'bg-black text-white border-black' : 'border-gray-200 text-gray-700 hover:bg-gray-100'}`}>
                      {run.modelName}
                    </button>
                  ))}
                </div>
                {arenaRuns.filter((run) => run.researchId === activeTabId).map((run) => renderRunCard(run))}
              </div>
            )}

            <div className="bg-white border border-gray-200 rounded-2xl p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-gray-900">指标对比</p>
                <p className="text-xs text-gray-500">Tokens · 耗时</p>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-gray-500 uppercase tracking-wide">
                      <th className="py-2">模型</th>
                      <th className="py-2">状态</th>
                      <th className="py-2">Tokens</th>
                      <th className="py-2">耗时</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparisonRows.map((row, index) => (
                      <tr key={`${row.model}-${index}`} className="border-t border-gray-100">
                        <td className="py-2 font-medium text-gray-900">{row.model}</td>
                        <td className="py-2 text-gray-600">{row.status}</td>
                        <td className="py-2 text-gray-600">{row.tokens}</td>
                        <td className="py-2 text-gray-600">{row.duration}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>

      <ModelManagerModal
        isOpen={isModelManagerOpen}
        onClose={() => setIsModelManagerOpen(false)}
        models={modelList}
        onRefresh={() => refreshModelList()}
        onModelCreated={(modelId) => refreshModelList(modelId)}
      />
    </main>
  );
}

function ChevronsDownIcon() {
  return (
    <svg className="w-4 h-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="7 13 12 18 17 13" />
      <polyline points="7 6 12 11 17 6" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

export default ArenaPage;
