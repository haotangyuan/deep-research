import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Bot, ChevronLeft, ChevronRight, ExternalLink, GitBranch, Globe2, Info, Loader2, MousePointer2, Wrench } from 'lucide-react';

import type { ChatMessage, WorkflowEvent } from '../../services/api';
import { buildAgentFlowModel } from './transform';
import type { AgentFlowNodeMeta } from './types';

const AgentFlowGraph = lazy(() =>
  import('./AgentFlowGraph').then((module) => ({ default: module.AgentFlowGraph })),
);

interface AgentFlowPanelProps {
  title?: string;
  status?: string;
  events: WorkflowEvent[];
  messages: ChatMessage[];
}

function formatTimestamp(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function detailLabel(kind?: string) {
  switch (kind) {
    case 'subagent':
      return '子 Agent';
    case 'tool':
      return '工具调用';
    case 'webpage':
      return '网页来源';
    case 'artifact':
      return '产物';
    case 'decision':
      return '人工确认';
    case 'message':
      return '用户消息';
    case 'error':
      return '错误';
    case 'session':
      return '会话';
    default:
      return 'Agent';
  }
}

export function AgentFlowPanel({ title, status, events, messages }: AgentFlowPanelProps) {
  const [open, setOpen] = useState(true);
  const [expandedNodeIds, setExpandedNodeIds] = useState<string[]>([]);
  const expandedNodeIdSet = useMemo(() => new Set(expandedNodeIds), [expandedNodeIds]);
  const model = useMemo(() => buildAgentFlowModel(events, messages, title, expandedNodeIdSet), [events, expandedNodeIdSet, messages, title]);
  const [selectedNode, setSelectedNode] = useState<AgentFlowNodeMeta | null>(null);
  const [panelWidth, setPanelWidth] = useState(() => {
    if (typeof window === 'undefined') return 420;
    const cached = window.localStorage.getItem('agent-flow-panel-width');
    const parsed = cached ? Number(cached) : 420;
    return Number.isFinite(parsed) ? Math.max(340, parsed) : 420;
  });
  const [isResizing, setIsResizing] = useState(false);
  const resizeFrameRef = useRef<number | null>(null);
  const currentNode = useMemo(() => {
    const selectedId = selectedNode?.id;
    if (selectedId) {
      return model.nodes.find((node) => node.id === selectedId) || model.nodes[0];
    }
    return model.nodes[0];
  }, [model.nodes, selectedNode]);

  useEffect(() => {
    setExpandedNodeIds((previous) => {
      const next = previous.filter((nodeId) => model.expandableNodeIds.includes(nodeId));
      if (next.length === previous.length && next.every((nodeId, index) => nodeId === previous[index])) return previous;
      return next;
    });
  }, [model.expandableNodeIds]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('agent-flow-panel-width', String(panelWidth));
    }
  }, [panelWidth]);

  const handleNodeSelect = useCallback((node: AgentFlowNodeMeta) => {
    setSelectedNode(node);
  }, []);

  const handleToggleCollapse = useCallback((nodeId: string) => {
    setExpandedNodeIds((previous) => {
      const next = new Set(previous);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return [...next];
    });
  }, []);

  const handleResizeStart = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsResizing(true);
    const handlePointerMove = (moveEvent: PointerEvent) => {
      if (resizeFrameRef.current) cancelAnimationFrame(resizeFrameRef.current);
      resizeFrameRef.current = requestAnimationFrame(() => {
        const nextWidth = Math.max(340, window.innerWidth - moveEvent.clientX);
        setPanelWidth(nextWidth);
      });
    };
    const handlePointerUp = () => {
      setIsResizing(false);
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      if (resizeFrameRef.current) {
        cancelAnimationFrame(resizeFrameRef.current);
        resizeFrameRef.current = null;
      }
    };
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp, { once: true });
  }, []);

  return (
    <>
    {open && (
      <button
        type="button"
        className="fixed inset-0 z-30 bg-gray-950/10 backdrop-blur-[1px] lg:hidden"
        aria-label="关闭 Agent 流向图"
        onClick={() => setOpen(false)}
      />
    )}
    <aside
      className={`flex h-full min-h-0 shrink-0 border-l border-gray-200/80 bg-[#f7f8f5] shadow-2xl shadow-gray-950/10 transition-[width,transform] duration-300 ease-in-out lg:relative lg:z-20 lg:shadow-none ${
        isResizing ? 'select-none !transition-none' : ''
      }`}
      style={{ width: open ? `${panelWidth}px` : '48px' }}
    >
      {open && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="调整 Agent 流向图宽度"
          onPointerDown={handleResizeStart}
          className="absolute left-0 top-0 z-20 hidden h-full w-2 -translate-x-1 cursor-col-resize touch-none hover:bg-gray-900/5 md:block"
        />
      )}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="absolute -left-4 top-5 z-30 flex h-8 w-8 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-600 shadow-sm transition-colors hover:text-gray-950"
        aria-label={open ? '隐藏 Agent 流向图' : '显示 Agent 流向图'}
      >
        {open ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </button>

      {!open ? (
        <div className="flex h-full w-12 flex-col items-center gap-3 pt-16 text-gray-500">
          <GitBranch className="h-5 w-5" />
          <div className="origin-center rotate-90 whitespace-nowrap text-xs font-semibold tracking-[0.18em]">AGENT FLOW</div>
        </div>
      ) : (
        <div className="flex h-full min-w-0 flex-1 flex-col">
          <div className="border-b border-gray-200/80 px-4 py-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">
                  <GitBranch className="h-3.5 w-3.5" />
                  Agent Flow
                </div>
                <h2 className="mt-1 text-[15px] font-semibold tracking-tight text-gray-950">调用链路与来源</h2>
                <p className="mt-1 text-xs text-gray-500">{status || '等待会话事件'}</p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white px-2.5 py-1 text-xs font-semibold tabular-nums text-gray-700">
                {model.visibleNodeCount}/{model.totalNodeCount} nodes
              </div>
            </div>

            <div className="mt-4 grid grid-cols-4 gap-2">
              <div className="rounded-xl bg-white px-2 py-2 shadow-sm">
                <Bot className="h-3.5 w-3.5 text-blue-600" />
                <div className="mt-1 text-sm font-semibold text-gray-950">{model.stats.agents}</div>
                <div className="text-[10px] text-gray-500">agents</div>
              </div>
              <div className="rounded-xl bg-white px-2 py-2 shadow-sm">
                <Wrench className="h-3.5 w-3.5 text-cyan-600" />
                <div className="mt-1 text-sm font-semibold text-gray-950">{model.stats.tools}</div>
                <div className="text-[10px] text-gray-500">tools</div>
              </div>
              <div className="rounded-xl bg-white px-2 py-2 shadow-sm">
                <Globe2 className="h-3.5 w-3.5 text-gray-600" />
                <div className="mt-1 text-sm font-semibold text-gray-950">{model.stats.webpages}</div>
                <div className="text-[10px] text-gray-500">pages</div>
              </div>
              <div className="rounded-xl bg-white px-2 py-2 shadow-sm">
                <Info className="h-3.5 w-3.5 text-amber-600" />
                <div className="mt-1 text-sm font-semibold text-gray-950">{model.stats.decisions}</div>
                <div className="text-[10px] text-gray-500">HITL</div>
              </div>
            </div>
          </div>

          <div className="min-h-0 flex-1">
            {events.length === 0 && messages.length === 0 ? (
              <div className="flex h-full items-center justify-center px-8 text-center">
                <div>
                  <MousePointer2 className="mx-auto h-8 w-8 text-gray-300" />
                  <p className="mt-3 text-sm font-medium text-gray-700">暂无调用链路</p>
                  <p className="mt-1 text-xs leading-5 text-gray-500">发送研究请求后，这里会展示 agent、工具、网页来源和报告产物。</p>
                </div>
              </div>
            ) : (
              <Suspense
                fallback={
                  <div className="flex h-full items-center justify-center px-6">
                    <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-500 shadow-sm">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      正在加载图谱
                    </div>
                  </div>
                }
              >
                <AgentFlowGraph
                  data={model.graphData}
                  selectedNodeId={currentNode?.id}
                  onNodeSelect={handleNodeSelect}
                  onToggleCollapse={handleToggleCollapse}
                />
              </Suspense>
            )}
          </div>

          <div className="max-h-[32%] overflow-y-auto border-t border-gray-200/80 bg-white px-4 py-4">
            {currentNode ? (
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="rounded-md bg-gray-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-gray-600">
                    {detailLabel(currentNode.kind)}
                  </span>
                  {currentNode.timestamp && (
                    <span className="text-[11px] tabular-nums text-gray-400">{formatTimestamp(currentNode.timestamp)}</span>
                  )}
                </div>
                <h3 className="mt-3 text-sm font-semibold text-gray-950">{currentNode.title}</h3>
                {currentNode.subtitle && <p className="mt-1 break-words text-xs leading-5 text-gray-500">{currentNode.subtitle}</p>}
                {currentNode.url && (
                  <a
                    href={currentNode.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-3 inline-flex max-w-full items-center gap-1 rounded-lg border border-gray-200 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                  >
                    <ExternalLink className="h-3 w-3 shrink-0" />
                    <span className="truncate">{currentNode.domain || currentNode.url}</span>
                  </a>
                )}
                {currentNode.content && (
                  <pre className="mt-3 max-h-32 overflow-y-auto whitespace-pre-wrap rounded-xl bg-gray-50 p-3 text-[11px] leading-5 text-gray-600">
                    {currentNode.content}
                  </pre>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500">选择一个节点查看详情。</p>
            )}
          </div>
        </div>
      )}
    </aside>
    </>
  );
}
