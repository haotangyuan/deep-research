import type { GraphData } from '@antv/g6';
import type { ChatMessage, WorkflowEvent } from '../../services/api';

export type AgentFlowNodeKind =
  | 'session'
  | 'agent'
  | 'subagent'
  | 'tool'
  | 'webpage'
  | 'artifact'
  | 'decision'
  | 'message'
  | 'error';

export interface AgentFlowNodeMeta {
  id: string;
  kind: AgentFlowNodeKind;
  title: string;
  subtitle?: string;
  status?: string;
  eventType?: string;
  content?: string;
  timestamp?: string;
  url?: string;
  domain?: string;
  parentId?: string;
  childIds?: string[];
  collapsible?: boolean;
  collapsed?: boolean;
  aggregateCount?: number;
  agentKey?: string;
  eventIds?: number[];
  sourceEventId?: number;
  rawEvent?: WorkflowEvent;
  rawEvents?: WorkflowEvent[];
  rawMessage?: ChatMessage;
  rawMessages?: ChatMessage[];
}

export interface AgentFlowEdgeMeta {
  id: string;
  source: string;
  target: string;
  label?: string;
}

export interface AgentFlowStats {
  agents: number;
  tools: number;
  webpages: number;
  decisions: number;
  errors: number;
}

export interface AgentFlowModel {
  graphData: GraphData;
  nodes: AgentFlowNodeMeta[];
  edges: AgentFlowEdgeMeta[];
  expandableNodeIds: string[];
  visibleNodeCount: number;
  totalNodeCount: number;
  stats: AgentFlowStats;
}
