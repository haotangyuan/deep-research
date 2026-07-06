import type { EdgeData, GraphData, NodeData } from '@antv/g6';
import type { ChatMessage, WorkflowEvent } from '../../services/api';
import type { AgentFlowEdgeMeta, AgentFlowModel, AgentFlowNodeKind, AgentFlowNodeMeta } from './types';

const URL_PATTERN = /https?:\/\/[^\s"'<>),\]]+/g;

const AGENT_DEFINITIONS: Record<string, { title: string; subtitle: string; kind: AgentFlowNodeKind }> = {
  'agent-scope': { title: 'ScopeAgent', subtitle: '需求理解与范围澄清', kind: 'agent' },
  'agent-supervisor': { title: 'SupervisorAgent', subtitle: '任务拆解与调研编排', kind: 'agent' },
  'agent-researcher': { title: 'ResearcherAgent', subtitle: '子任务研究与材料压缩', kind: 'subagent' },
  'agent-search': { title: 'SearchAgent', subtitle: '网页搜索与来源整理', kind: 'subagent' },
  'agent-report': { title: 'ReportAgent', subtitle: '最终报告生成', kind: 'agent' },
};

const AGENT_FALLBACK_EDGES: Array<[string, string]> = [
  ['session', 'agent-scope'],
  ['agent-scope', 'agent-supervisor'],
  ['agent-supervisor', 'agent-researcher'],
  ['agent-researcher', 'agent-search'],
  ['agent-supervisor', 'agent-report'],
];

type MutableNode = AgentFlowNodeMeta & {
  childIds: string[];
  eventIds: number[];
  rawEvents: WorkflowEvent[];
  rawMessages: ChatMessage[];
};

function sortBySequenceAndTime<T extends { sequenceNo?: number; createTime: string }>(items: T[]) {
  return [...items].sort((a, b) => {
    const seqA = typeof a.sequenceNo === 'number' ? a.sequenceNo : Number.POSITIVE_INFINITY;
    const seqB = typeof b.sequenceNo === 'number' ? b.sequenceNo : Number.POSITIVE_INFINITY;
    if (seqA !== seqB) return seqA - seqB;
    return new Date(a.createTime).getTime() - new Date(b.createTime).getTime();
  });
}

function truncate(value: string | undefined, max = 64) {
  if (!value) return '';
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

function getDomain(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function parseJsonCandidates(content: string) {
  const candidates: unknown[] = [];
  if (!content?.trim()) return candidates;

  try {
    candidates.push(JSON.parse(content));
  } catch {
    // Plain-text event contents are expected.
  }

  const fencedJson = content.match(/```json\s*([\s\S]*?)```/i)?.[1];
  if (fencedJson) {
    try {
      candidates.push(JSON.parse(fencedJson));
    } catch {
      // Ignore malformed fenced snippets.
    }
  }

  return candidates;
}

function collectUrlsFromValue(value: unknown, acc: string[] = []) {
  if (!value) return acc;
  if (typeof value === 'string') {
    const matches = value.match(URL_PATTERN);
    if (matches) acc.push(...matches);
    return acc;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectUrlsFromValue(item, acc));
    return acc;
  }
  if (typeof value === 'object') {
    Object.values(value as Record<string, unknown>).forEach((item) => collectUrlsFromValue(item, acc));
  }
  return acc;
}

function extractUrls(content = '') {
  const urls = new Set<string>();
  content.match(URL_PATTERN)?.forEach((url) => urls.add(url.replace(/[.,;:]+$/, '')));
  parseJsonCandidates(content).forEach((candidate) => {
    collectUrlsFromValue(candidate).forEach((url) => urls.add(url.replace(/[.,;:]+$/, '')));
  });
  return [...urls].slice(0, 20);
}

function eventKind(event: WorkflowEvent): AgentFlowNodeKind {
  const type = event.type?.toUpperCase();
  if (type === 'AGENT_RUNTIME') {
    const kind = event.runtimeMetadata?.kind || '';
    if (['team_task', 'team_lifecycle'].includes(kind)) return 'subagent';
    if (['adversarial_reviewer', 'claim_verification', 'report_judge', 'intent_recognition', 'workflow_template'].includes(kind)) return 'decision';
    if (['report_draft', 'report_synthesize'].includes(kind)) return 'artifact';
    return 'tool';
  }
  if (type === 'ERROR') return 'error';
  if (type === 'INTERVENTION') return 'decision';
  if (type === 'CLARIFY_FORM' || type === 'DIRECTION_CONFIRM') return 'decision';
  if (type === 'SUPERVISOR' && (/^动态决策：/.test(event.title || '') || /^报告前验证/.test(event.title || ''))) return 'decision';
  if (type === 'REPORT') return 'artifact';
  if (type === 'SEARCH') return 'tool';
  if (type === 'RESEARCH' && /^分析中/.test(event.title || '')) return 'tool';
  if (type === 'RESEARCH' && /^已完成/.test(event.title || '')) return 'artifact';
  if (type === 'SUPERVISOR' && /^研究资料收集完成/.test(event.title || '')) return 'artifact';
  if (type === 'RESEARCH') return 'subagent';
  return 'agent';
}

function eventTitle(event: WorkflowEvent) {
  const type = event.type?.toUpperCase();
  if (type === 'AGENT_RUNTIME') {
    if (event.runtimeMetadata?.kind === 'team_lifecycle') return event.title || 'AgentScope Research Team';
    return event.runtimeMetadata?.taskTitle || event.runtimeMetadata?.stage || event.title || 'AgentScope runtime';
  }
  if (type === 'SEARCH' && /^正在搜索/.test(event.title || '')) return event.title;
  if (type === 'SEARCH') return event.title || 'Web search';
  if (type === 'RESEARCH' && /^分析中/.test(event.title || '')) return 'Think Tool';
  return event.title || event.type || 'Agent event';
}

function ownerAgentIdForEvent(event: WorkflowEvent, eventOwnerMap: Map<number, string>) {
  if (event.type?.toUpperCase() === 'AGENT_RUNTIME') {
    const stage = event.runtimeMetadata?.stage || '';
    if (stage === 'ScopeAgent') return 'agent-scope';
    if (stage === 'ResearcherAgent' || stage === 'ResearchCompressorAgent') return 'agent-researcher';
    if (stage === 'SearchAgent') return 'agent-search';
    if (stage === 'ReportAgent' || stage.startsWith('ReportAgent:') || stage === 'ReportJudge' || stage === 'ReportSynthesizer' || stage === 'ClaimVerifier') return 'agent-report';
    return 'agent-supervisor';
  }
  switch (event.type?.toUpperCase()) {
    case 'SCOPE':
    case 'CLARIFY_FORM':
    case 'DIRECTION_CONFIRM':
      return 'agent-scope';
    case 'INTERVENTION':
      return 'agent-supervisor';
    case 'SUPERVISOR':
      return 'agent-supervisor';
    case 'RESEARCH':
      return 'agent-researcher';
    case 'SEARCH':
      return 'agent-search';
    case 'REPORT':
      return 'agent-report';
    case 'ERROR':
      return event.parentEventId ? eventOwnerMap.get(event.parentEventId) || 'session' : 'session';
    default:
      return event.parentEventId ? eventOwnerMap.get(event.parentEventId) || 'agent-supervisor' : 'agent-supervisor';
  }
}

function groupForEvent(event: WorkflowEvent, ownerId: string) {
  const type = event.type?.toUpperCase();
  const title = event.title || '';

  if (type === 'AGENT_RUNTIME') {
    const kind = event.runtimeMetadata?.kind || '';
    if (kind === 'adversarial_reviewer') {
      return {
        id: 'agent-supervisor:adversarial-review',
        title: '对抗性审查',
        subtitle: '多 reviewer 投票',
        kind: 'decision' as AgentFlowNodeKind,
      };
    }
    if (kind === 'claim_verification') {
      return {
        id: 'agent-report:claim-verification',
        title: '声明交叉验证',
        subtitle: 'claim cross-check',
        kind: 'decision' as AgentFlowNodeKind,
      };
    }
    if (kind === 'report_draft') {
      return {
        id: 'agent-report:drafts',
        title: '多角度起草',
        subtitle: '3 角度并行',
        kind: 'artifact' as AgentFlowNodeKind,
      };
    }
    if (kind === 'report_judge') {
      return {
        id: 'agent-report:judges',
        title: '报告评委',
        subtitle: '5 维打分',
        kind: 'decision' as AgentFlowNodeKind,
      };
    }
    if (kind === 'report_synthesize') {
      return {
        id: 'agent-report:synthesis',
        title: '报告融合',
        subtitle: '冠军 + 嫁接落选亮点',
        kind: 'artifact' as AgentFlowNodeKind,
      };
    }
    if (kind === 'intent_recognition') {
      return {
        id: 'agent-scope:intent',
        title: '意图识别',
        subtitle: '研究类型判定',
        kind: 'decision' as AgentFlowNodeKind,
      };
    }
    if (kind === 'workflow_template') {
      return {
        id: 'agent-supervisor:template',
        title: '编排模板',
        subtitle: '按类型选模板',
        kind: 'decision' as AgentFlowNodeKind,
      };
    }
    const isTask = ['team_task', 'team_lifecycle'].includes(kind);
    return {
      id: isTask ? 'agent-supervisor:agentscope-team' : `${ownerId}:agentscope-runtime`,
      title: isTask ? 'AgentScope Research Team' : 'AgentScope Runtime',
      subtitle: isTask ? 'native tasks and workers' : 'agent / model / tool lifecycle',
      kind: (isTask ? 'subagent' : 'tool') as AgentFlowNodeKind,
    };
  }

  if (type === 'ERROR') {
    return {
      id: `${ownerId}:errors`,
      title: '错误事件',
      subtitle: '运行异常',
      kind: 'error' as AgentFlowNodeKind,
    };
  }

  if (ownerId === 'agent-scope') {
    if (type === 'CLARIFY_FORM' || type === 'DIRECTION_CONFIRM' || /需要您提供更多信息|澄清|确认/.test(title)) {
      return {
        id: 'agent-scope:clarifications',
        title: '需求澄清与方向确认',
        subtitle: '多次澄清折叠在同一分支',
        kind: 'decision' as AgentFlowNodeKind,
      };
    }
    if (/研究计划|需求已明确/.test(title)) {
      return {
        id: 'agent-scope:brief',
        title: '研究方向与计划',
        subtitle: 'scope output',
        kind: 'artifact' as AgentFlowNodeKind,
      };
    }
    return {
      id: 'agent-scope:events',
      title: '需求分析过程',
      subtitle: 'scope events',
      kind: 'tool' as AgentFlowNodeKind,
    };
  }

  if (ownerId === 'agent-supervisor') {
    if (type === 'INTERVENTION') {
      return {
        id: 'agent-supervisor:interventions',
        title: '下一轮用户干预',
        subtitle: 'pending / applied / expired',
        kind: 'decision' as AgentFlowNodeKind,
      };
    }
    if (/^动态决策：/.test(title) || /^报告前验证/.test(title)) {
      return {
        id: 'agent-supervisor:decisions',
        title: '动态决策与报告闸门',
        subtitle: 'continue / report / gate',
        kind: 'decision' as AgentFlowNodeKind,
      };
    }
    if (/拆解|规划/.test(title)) {
      return {
        id: 'agent-supervisor:plan',
        title: '任务拆解',
        subtitle: 'planner output',
        kind: 'artifact' as AgentFlowNodeKind,
      };
    }
    if (/正在研究/.test(title)) {
      return {
        id: 'agent-supervisor:delegations',
        title: '子 Agent 调度',
        subtitle: 'delegated research tasks',
        kind: 'tool' as AgentFlowNodeKind,
      };
    }
    return {
      id: 'agent-supervisor:events',
      title: '监督与汇总',
      subtitle: 'supervisor events',
      kind: 'artifact' as AgentFlowNodeKind,
    };
  }

  if (ownerId === 'agent-researcher') {
    if (/分析中/.test(title)) {
      return {
        id: 'agent-researcher:thinking',
        title: 'Think Tool',
        subtitle: '研究过程反思',
        kind: 'tool' as AgentFlowNodeKind,
      };
    }
    if (/已完成/.test(title)) {
      return {
        id: 'agent-researcher:outputs',
        title: '研究产物',
        subtitle: 'compressed findings',
        kind: 'artifact' as AgentFlowNodeKind,
      };
    }
    return {
      id: 'agent-researcher:tasks',
      title: '研究任务',
      subtitle: 'research branches',
      kind: 'subagent' as AgentFlowNodeKind,
    };
  }

  if (ownerId === 'agent-search') {
    return {
      id: 'agent-search:web',
      title: '网页搜索',
      subtitle: 'queries and sources',
      kind: 'tool' as AgentFlowNodeKind,
    };
  }

  if (ownerId === 'agent-report') {
    return {
      id: 'agent-report:output',
      title: '报告生成',
      subtitle: 'report writer events',
      kind: 'artifact' as AgentFlowNodeKind,
    };
  }

  return {
    id: `${ownerId}:events`,
    title: '运行事件',
    subtitle: 'workflow events',
    kind: eventKind(event),
  };
}

function formatEventSummary(event: WorkflowEvent) {
  const parts = [`[${event.type}] ${event.title}`];
  if (event.content) parts.push(truncate(event.content.replace(/\s+/g, ' '), 180));
  return parts.join('\n');
}

function createNode(input: AgentFlowNodeMeta): MutableNode {
  return {
    ...input,
    childIds: input.childIds ? [...input.childIds] : [],
    eventIds: input.eventIds ? [...input.eventIds] : [],
    rawEvents: input.rawEvents ? [...input.rawEvents] : [],
    rawMessages: input.rawMessages ? [...input.rawMessages] : [],
  };
}

function buildGraphNode(node: MutableNode, expandedNodeIds: Set<string>): NodeData {
  const collapsible = node.childIds.length > 0;
  const collapsed = collapsible && !expandedNodeIds.has(node.id);
  const meta: AgentFlowNodeMeta = {
    ...node,
    childIds: [...node.childIds],
    eventIds: [...node.eventIds],
    rawEvents: [...node.rawEvents],
    rawMessages: [...node.rawMessages],
    collapsible,
    collapsed,
  };

  return {
    id: node.id,
    data: meta as unknown as Record<string, unknown>,
    style: {
      labelText: truncate(node.title, node.kind === 'webpage' ? 26 : 30),
      collapsed,
    },
  };
}

export function buildAgentFlowModel(
  events: WorkflowEvent[] = [],
  messages: ChatMessage[] = [],
  researchTitle = 'Research session',
  expandedNodeIds: Set<string> = new Set(),
): AgentFlowModel {
  const nodesById = new Map<string, MutableNode>();
  const edgesById = new Map<string, AgentFlowEdgeMeta>();
  const eventOwnerMap = new Map<number, string>();
  const sortedEvents = sortBySequenceAndTime(events);

  const addNode = (node: AgentFlowNodeMeta, parentId?: string) => {
    const existing = nodesById.get(node.id);
    if (existing) {
      if (parentId && !existing.parentId) existing.parentId = parentId;
      return existing;
    }
    const created = createNode({ ...node, parentId: parentId || node.parentId });
    nodesById.set(created.id, created);
    if (parentId) {
      const parent = nodesById.get(parentId);
      if (parent && !parent.childIds.includes(created.id)) parent.childIds.push(created.id);
      addEdge(parentId, created.id, 'detail');
    }
    return created;
  };

  function addEdge(source: string, target: string, label?: string) {
    if (!nodesById.has(source) || !nodesById.has(target) || source === target) return;
    const id = `edge-${source}-${target}`;
    if (!edgesById.has(id)) edgesById.set(id, { id, source, target, label });
  }

  const attachEvent = (nodeId: string, event: WorkflowEvent) => {
    const node = nodesById.get(nodeId);
    if (!node) return;
    if (!node.eventIds.includes(event.id)) node.eventIds.push(event.id);
    if (!node.rawEvents.some((item) => item.id === event.id)) node.rawEvents.push(event);
    node.aggregateCount = node.rawEvents.length;
    node.timestamp = event.createTime;
  };

  const ensureAgent = (agentId: string) => {
    const definition = AGENT_DEFINITIONS[agentId];
    if (!definition) return nodesById.get('session');
    return addNode({
      id: agentId,
      kind: definition.kind,
      title: definition.title,
      subtitle: definition.subtitle,
      agentKey: definition.title,
    });
  };

  addNode({
    id: 'session',
    kind: 'session',
    title: researchTitle || 'Research session',
    subtitle: `${events.length} events / ${messages.length} messages`,
  });

  const firstUserMessage = sortBySequenceAndTime(messages).find((message) => message.role === 'user');
  if (firstUserMessage) {
    const requestNode = addNode(
      {
        id: 'session:user-request',
        kind: 'message',
        title: 'User request',
        subtitle: truncate(firstUserMessage.content, 80),
        content: firstUserMessage.content,
        timestamp: firstUserMessage.createTime,
        rawMessage: firstUserMessage,
        rawMessages: [firstUserMessage],
      },
      'session',
    );
    requestNode.rawMessages = [firstUserMessage];
  }

  sortedEvents.forEach((event) => {
    const ownerId = ownerAgentIdForEvent(event, eventOwnerMap);
    eventOwnerMap.set(event.id, ownerId);
    ensureAgent(ownerId);
    attachEvent(ownerId, event);
  });

  sortedEvents.forEach((event) => {
    const ownerId = eventOwnerMap.get(event.id) || ownerAgentIdForEvent(event, eventOwnerMap);
    ensureAgent(ownerId);

    const group = groupForEvent(event, ownerId);
    const groupNode = addNode(
      {
        id: group.id,
        kind: group.kind,
        title: group.title,
        subtitle: group.subtitle,
        agentKey: AGENT_DEFINITIONS[ownerId]?.title,
      },
      ownerId,
    );
    attachEvent(groupNode.id, event);

    const runtimeTaskId = event.runtimeMetadata?.kind === 'team_task' && event.runtimeMetadata.taskId;
    const runtimeCallId = event.runtimeMetadata?.kind === 'agent_call'
      ? [event.runtimeMetadata.stage || 'agent', event.runtimeMetadata.taskId || event.runtimeMetadata.workerId || 'main'].join('-')
      : null;
    const runtimeTeamId = event.runtimeMetadata?.kind === 'team_lifecycle'
      ? `runtime-team-${event.runtimeMetadata.status || event.id}`
      : null;
    const eventNodeId = runtimeTaskId
      ? `runtime-task-${runtimeTaskId}`
      : runtimeCallId
        ? `runtime-call-${runtimeCallId}`
        : runtimeTeamId || `event-${event.id}`;
    const eventNode = addNode(
      {
        id: eventNodeId,
        kind: eventKind(event),
        title: eventTitle(event),
        subtitle: event.type,
        eventType: event.type,
        content: event.content,
        timestamp: event.createTime,
        sourceEventId: event.id,
        agentKey: AGENT_DEFINITIONS[ownerId]?.title,
        rawEvent: event,
        rawEvents: [event],
        eventIds: [event.id],
        status: event.runtimeMetadata?.status,
      },
      groupNode.id,
    );
    if (runtimeTaskId) {
      eventNode.title = event.runtimeMetadata?.taskTitle || eventNode.title;
      eventNode.subtitle = `${event.runtimeMetadata?.workerId || 'worker'} · ${event.runtimeMetadata?.status || 'pending'}`;
      eventNode.status = event.runtimeMetadata?.status;
      eventNode.content = event.content;
      eventNode.timestamp = event.createTime;
      eventNode.rawEvent = event;
    }
    if (runtimeCallId) {
      eventNode.title = event.runtimeMetadata?.stage || eventNode.title;
      eventNode.subtitle = [
        event.runtimeMetadata?.modelCalls ? `${event.runtimeMetadata.modelCalls} model` : null,
        event.runtimeMetadata?.toolCalls ? `${event.runtimeMetadata.toolCalls} tool` : null,
        event.runtimeMetadata?.workerId,
      ].filter(Boolean).join(' · ') || 'AgentScope runtime';
      eventNode.status = event.runtimeMetadata?.status;
      eventNode.timestamp = event.createTime;
      eventNode.rawEvent = event;
    }
    attachEvent(eventNodeId, event);

    extractUrls(event.content).forEach((url, index) => {
      addNode(
        {
          id: `url-${event.id}-${index}`,
          kind: 'webpage',
          title: getDomain(url),
          subtitle: truncate(url, 90),
          url,
          domain: getDomain(url),
          timestamp: event.createTime,
          sourceEventId: event.id,
          agentKey: AGENT_DEFINITIONS[ownerId]?.title,
          rawEvent: event,
          rawEvents: [event],
        },
        eventNodeId,
      );
    });
  });

  sortedEvents.forEach((event) => {
    const ownerId = eventOwnerMap.get(event.id);
    if (!ownerId || ownerId === 'session') return;
    const parentOwnerId = event.parentEventId ? eventOwnerMap.get(event.parentEventId) : undefined;
    if (parentOwnerId && parentOwnerId !== ownerId) addEdge(parentOwnerId, ownerId, 'parentEventId');
  });

  AGENT_FALLBACK_EDGES.forEach(([source, target]) => {
    if (nodesById.has(source) && nodesById.has(target)) addEdge(source, target, 'flow');
  });

  const hasIncomingEdge = (target: string) => [...edgesById.values()].some((edge) => edge.target === target);
  const ensureIncomingEdge = (target: string, preferredSources: string[]) => {
    if (!nodesById.has(target) || hasIncomingEdge(target)) return;
    const source = preferredSources.find((sourceId) => nodesById.has(sourceId));
    if (source) addEdge(source, target, 'flow');
  };

  ensureIncomingEdge('agent-supervisor', ['agent-scope', 'session']);
  ensureIncomingEdge('agent-researcher', ['agent-supervisor', 'agent-scope', 'session']);
  ensureIncomingEdge('agent-search', ['agent-researcher', 'agent-supervisor', 'session']);
  ensureIncomingEdge('agent-report', ['agent-supervisor', 'agent-researcher', 'session']);

  nodesById.forEach((node) => {
    node.collapsible = node.childIds.length > 0;
    node.collapsed = node.collapsible && !expandedNodeIds.has(node.id);
    if (node.rawEvents.length > 0) {
      node.aggregateCount = node.rawEvents.length;
      node.content ||= node.rawEvents.map(formatEventSummary).join('\n\n');
      if (!node.subtitle?.includes('events')) {
        node.subtitle = node.subtitle ? `${node.subtitle} · ${node.rawEvents.length} events` : `${node.rawEvents.length} events`;
      }
    }
  });

  const isAlwaysVisible = (node: MutableNode) => node.id === 'session' || Object.prototype.hasOwnProperty.call(AGENT_DEFINITIONS, node.id);

  const isVisible = (node: MutableNode): boolean => {
    if (isAlwaysVisible(node)) return true;
    let parentId = node.parentId;
    while (parentId) {
      if (!expandedNodeIds.has(parentId)) return false;
      const parent = nodesById.get(parentId);
      if (!parent) return false;
      parentId = parent.parentId;
    }
    return true;
  };

  const visibleNodes = [...nodesById.values()].filter(isVisible);
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = [...edgesById.values()].filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target));

  const graphNodes: NodeData[] = visibleNodes.map((node) => buildGraphNode(node, expandedNodeIds));
  const graphEdges: EdgeData[] = visibleEdges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    data: edge as unknown as Record<string, unknown>,
  }));

  const allNodes = [...nodesById.values()].map((node) => ({
    ...node,
    childIds: [...node.childIds],
    eventIds: [...node.eventIds],
    rawEvents: [...node.rawEvents],
    rawMessages: [...node.rawMessages],
  }));

  const stats = allNodes.reduce(
    (acc, node) => {
      if ((node.kind === 'agent' || node.kind === 'subagent') && node.id !== 'session') acc.agents += 1;
      if (node.kind === 'tool') acc.tools += 1;
      if (node.kind === 'webpage') acc.webpages += 1;
      if (node.kind === 'decision') acc.decisions += 1;
      if (node.kind === 'error') acc.errors += 1;
      return acc;
    },
    { agents: 0, tools: 0, webpages: 0, decisions: 0, errors: 0 },
  );

  const graphData: GraphData = {
    nodes: graphNodes,
    edges: graphEdges,
  };

  return {
    graphData,
    nodes: allNodes,
    edges: [...edgesById.values()],
    expandableNodeIds: allNodes.filter((node) => node.collapsible).map((node) => node.id),
    visibleNodeCount: visibleNodes.length,
    totalNodeCount: allNodes.length,
    stats,
  };
}
