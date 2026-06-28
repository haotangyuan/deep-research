import { useCallback, useEffect, useMemo, useRef } from 'react';
import { CanvasEvent, Graph, NodeEvent, type GraphData, type GraphOptions, type NodeData } from '@antv/g6';

import type { AgentFlowNodeKind, AgentFlowNodeMeta } from './types';

const NODE_COLORS: Record<AgentFlowNodeKind, { fill: string; stroke: string; text: string; badge: string }> = {
  session: { fill: '#111827', stroke: '#111827', text: '#ffffff', badge: '#ffffff' },
  message: { fill: '#f8fafc', stroke: '#cbd5e1', text: '#0f172a', badge: '#64748b' },
  agent: { fill: '#eff6ff', stroke: '#93c5fd', text: '#1e3a8a', badge: '#2563eb' },
  subagent: { fill: '#f5f3ff', stroke: '#c4b5fd', text: '#4c1d95', badge: '#7c3aed' },
  tool: { fill: '#ecfeff', stroke: '#67e8f9', text: '#155e75', badge: '#0891b2' },
  webpage: { fill: '#f8fafc', stroke: '#d1d5db', text: '#374151', badge: '#6b7280' },
  artifact: { fill: '#ecfdf5', stroke: '#86efac', text: '#14532d', badge: '#16a34a' },
  decision: { fill: '#fffbeb', stroke: '#fcd34d', text: '#92400e', badge: '#d97706' },
  error: { fill: '#fef2f2', stroke: '#fca5a5', text: '#991b1b', badge: '#dc2626' },
};

type GraphViewport = {
  position: [number, number] | [number, number, number];
  zoom: number;
};

type NodeRect = {
  left: number;
  right: number;
  top: number;
  bottom: number;
};

const CHILD_COLUMN_GAP = 280;
const NODE_ROW_GAP = 86;
const NODE_PADDING_X = 28;
const NODE_PADDING_Y = 18;
const TOGGLE_HIT_SIZE = 42;

function nodeMeta(data: NodeData): AgentFlowNodeMeta {
  return (data.data || {}) as unknown as AgentFlowNodeMeta;
}

function nodeSize(kind: AgentFlowNodeKind): [number, number] {
  if (kind === 'webpage') return [176, 48];
  if (kind === 'session') return [210, 58];
  return [210, 56];
}

function nodeKindLabel(kind: AgentFlowNodeKind) {
  switch (kind) {
    case 'session':
      return 'ROOT';
    case 'subagent':
      return 'SUB';
    case 'webpage':
      return 'URL';
    default:
      return kind.toUpperCase();
  }
}

type DisplayObjectLike = {
  className?: string;
  id?: string;
  parentElement?: DisplayObjectLike | null;
};

function elementNodeId(target?: unknown) {
  let current = target as DisplayObjectLike | null | undefined;
  while (current) {
    if (current.id) return current.id;
    current = current.parentElement ?? null;
  }
  return undefined;
}

function isCollapseToggleTarget(target?: unknown) {
  let current = target as DisplayObjectLike | null | undefined;
  while (current) {
    if (current.className === 'badge-1') return true;
    current = current.parentElement ?? null;
  }
  return false;
}

function normalizeGraphData(data: GraphData) {
  return {
    nodes: data.nodes || [],
    edges: data.edges || [],
  };
}

function dataId(data: { id?: unknown }) {
  return String(data.id);
}

function dataSignature(data: unknown) {
  return JSON.stringify(data);
}

function diffData<T extends { id?: unknown }>(previous: T[], next: T[]) {
  const previousById = new Map(previous.map((item) => [dataId(item), item]));
  const nextById = new Map(next.map((item) => [dataId(item), item]));

  const added = next.filter((item) => !previousById.has(dataId(item)));
  const removed = previous.filter((item) => !nextById.has(dataId(item))).map((item) => dataId(item));
  const updated = next.filter((item) => {
    const previousItem = previousById.get(dataId(item));
    return previousItem && dataSignature(previousItem) !== dataSignature(item);
  });

  return { added, removed, updated };
}

function edgeEndpoint(edge: { source?: unknown; target?: unknown }, key: 'source' | 'target') {
  return edge[key] === undefined || edge[key] === null ? undefined : String(edge[key]);
}

function edgeId(edge: { id?: unknown }) {
  return edge.id === undefined || edge.id === null ? undefined : String(edge.id);
}

function nodePosition(node?: NodeData): { x: number; y: number } | null {
  const style = node?.style as Record<string, unknown> | undefined;
  const x = style?.x;
  const y = style?.y;
  if (typeof x === 'number' && typeof y === 'number') return { x, y };
  return null;
}

function nodeRectAt(node: NodeData, position: { x: number; y: number }): NodeRect {
  const meta = nodeMeta(node);
  const [width, height] = nodeSize(meta.kind || 'agent');
  return {
    left: position.x - width / 2 - NODE_PADDING_X,
    right: position.x + width / 2 + NODE_PADDING_X,
    top: position.y - height / 2 - NODE_PADDING_Y,
    bottom: position.y + height / 2 + NODE_PADDING_Y,
  };
}

function overlaps(a: NodeRect, b: NodeRect) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function nextVerticalOffset(step: number) {
  if (step === 0) return 0;
  const magnitude = Math.ceil(step / 2) * NODE_ROW_GAP;
  return step % 2 === 1 ? magnitude : -magnitude;
}

function findFreeNodePosition(node: NodeData, preferred: { x: number; y: number }, occupied: NodeRect[]) {
  for (let column = 0; column < 5; column += 1) {
    const x = preferred.x + column * CHILD_COLUMN_GAP;
    for (let step = 0; step < 120; step += 1) {
      const position = { x, y: preferred.y + nextVerticalOffset(step) };
      const rect = nodeRectAt(node, position);
      if (!occupied.some((item) => overlaps(rect, item))) return { position, rect };
    }
  }

  const position = {
    x: preferred.x + CHILD_COLUMN_GAP,
    y: preferred.y + occupied.length * NODE_ROW_GAP,
  };
  return { position, rect: nodeRectAt(node, position) };
}

function captureViewport(graph: Graph): GraphViewport {
  const [x = 0, y = 0, z] = graph.getPosition();
  return {
    position: z === undefined ? [x, y] : [x, y, z],
    zoom: graph.getZoom(),
  };
}

async function restoreViewport(graph: Graph, viewport: GraphViewport) {
  if (graph.destroyed) return;
  await graph.zoomTo(viewport.zoom, false);
  if (graph.destroyed) return;
  await graph.translateTo(viewport.position, false);
}

async function drawWithoutViewportShift(graph: Graph) {
  const viewport = captureViewport(graph);
  await graph.draw();
  await restoreViewport(graph, viewport);
}

async function waitForStableContainer(container: HTMLDivElement, graph: Graph) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const rect = container.getBoundingClientRect();
    if (graph.destroyed) return false;
    if (rect.width > 0 && rect.height > 0) {
      graph.setSize(rect.width, rect.height);
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      return true;
    }
  }
  return false;
}

function withStableIncrementalPositions(graph: Graph, addedNodes: NodeData[], addedEdges: Array<{ source?: unknown; target?: unknown }>) {
  const currentNodes = graph.getNodeData();
  const currentById = new Map(currentNodes.map((node) => [dataId(node), node]));
  const positionedById = new Map(currentById);
  const occupied = currentNodes.flatMap((node) => {
    const position = nodePosition(node);
    return position ? [nodeRectAt(node, position)] : [];
  });
  const parentIdByNodeId = new Map<string, string | undefined>();
  addedNodes.forEach((node) => {
    const nodeId = dataId(node);
    const incomingEdge = addedEdges.find((edge) => edgeEndpoint(edge, 'target') === nodeId);
    parentIdByNodeId.set(nodeId, incomingEdge ? edgeEndpoint(incomingEdge, 'source') : nodeMeta(node).parentId);
  });
  const addedCountByParent = new Map<string, number>();
  parentIdByNodeId.forEach((parentId) => {
    const key = parentId || 'root';
    addedCountByParent.set(key, (addedCountByParent.get(key) || 0) + 1);
  });
  const siblingIndexByParent = new Map<string, number>();

  return addedNodes.map((node) => {
    const nodeId = dataId(node);
    const existingPosition = nodePosition(node);
    if (existingPosition) {
      occupied.push(nodeRectAt(node, existingPosition));
      positionedById.set(nodeId, node);
      return node;
    }

    const parentId = parentIdByNodeId.get(nodeId);
    const parentPosition = parentId ? nodePosition(positionedById.get(parentId)) : null;
    const parentKey = parentId || 'root';
    const siblingIndex = siblingIndexByParent.get(parentKey) || 0;
    const siblingCount = addedCountByParent.get(parentKey) || 1;
    siblingIndexByParent.set(parentKey, siblingIndex + 1);

    const preferred = {
      x: (parentPosition?.x ?? 0) + CHILD_COLUMN_GAP,
      y: (parentPosition?.y ?? 0) + (siblingIndex - (siblingCount - 1) / 2) * NODE_ROW_GAP,
    };
    const { position, rect } = findFreeNodePosition(node, preferred, occupied);
    const positionedNode = {
      ...node,
      style: {
        ...(node.style || {}),
        x: position.x,
        y: position.y,
      },
    };
    occupied.push(rect);
    positionedById.set(nodeId, positionedNode);
    return positionedNode;
  });
}

function eventCanvasPoints(graph: Graph, event: any): Array<{ x: number; y: number }> {
  const points: Array<{ x: number; y: number }> = [];
  const canvas = event?.canvas;
  if (typeof canvas?.x === 'number' && typeof canvas?.y === 'number') points.push({ x: canvas.x, y: canvas.y });
  if (Array.isArray(canvas) && typeof canvas[0] === 'number' && typeof canvas[1] === 'number') {
    points.push({ x: canvas[0], y: canvas[1] });
  }
  if (typeof event?.canvasX === 'number' && typeof event?.canvasY === 'number') {
    points.push({ x: event.canvasX, y: event.canvasY });
  }

  const viewport = event?.viewport;
  if (typeof viewport?.x === 'number' && typeof viewport?.y === 'number') {
    const [x, y] = graph.getCanvasByViewport([viewport.x, viewport.y]);
    points.push({ x, y });
  }
  if (Array.isArray(viewport) && typeof viewport[0] === 'number' && typeof viewport[1] === 'number') {
    const [x, y] = graph.getCanvasByViewport([viewport[0], viewport[1]]);
    points.push({ x, y });
  }
  return points;
}

function isCollapseToggleEvent(graph: Graph, event: any) {
  const nodeId = event?.target?.id || elementNodeId(event?.originalTarget);
  if (!nodeId) return false;
  const datum = graph.getNodeData(nodeId);
  const meta = nodeMeta(datum);
  if (!meta.collapsible) return false;
  if (isCollapseToggleTarget(event?.originalTarget)) return true;

  const position = nodePosition(datum);
  const points = eventCanvasPoints(graph, event);
  if (!position || points.length === 0) return false;

  const [width] = nodeSize(meta.kind || 'agent');
  const toggleCenter = {
    x: position.x + width / 2 + 10,
    y: position.y,
  };

  return points.some((point) => (
    Math.abs(point.x - toggleCenter.x) <= TOGGLE_HIT_SIZE / 2 &&
    Math.abs(point.y - toggleCenter.y) <= TOGGLE_HIT_SIZE / 2
  ));
}

function preserveRenderedNodePositions(graph: Graph, nodes: NodeData[]) {
  const currentById = new Map(graph.getNodeData().map((node) => [dataId(node), node]));
  return nodes.map((node) => {
    if (nodePosition(node)) return node;
    const currentPosition = nodePosition(currentById.get(dataId(node)));
    if (!currentPosition) return node;
    return {
      ...node,
      style: {
        ...(node.style || {}),
        ...currentPosition,
      },
    };
  });
}

function applyGraphDataDiff(graph: Graph, previousData: GraphData, nextData: GraphData) {
  const previous = normalizeGraphData(previousData);
  const next = normalizeGraphData(nextData);
  const nodeDiff = diffData(previous.nodes, next.nodes);
  const edgeDiff = diffData(previous.edges, next.edges);
  const addedNodes = withStableIncrementalPositions(graph, nodeDiff.added, edgeDiff.added);
  const updatedNodes = preserveRenderedNodePositions(graph, nodeDiff.updated);
  const updatedEdges = edgeDiff.updated.filter((edge) => {
    const id = edgeId(edge);
    if (!id) return true;
    const previousEdge = previous.edges.find((item) => dataId(item) === id);
    return (
      edgeEndpoint(previousEdge || {}, 'source') !== edgeEndpoint(edge, 'source') ||
      edgeEndpoint(previousEdge || {}, 'target') !== edgeEndpoint(edge, 'target') ||
      dataSignature(previousEdge?.data) !== dataSignature(edge.data)
    );
  });

  if (edgeDiff.removed.length > 0) graph.removeEdgeData(edgeDiff.removed);
  if (nodeDiff.removed.length > 0) graph.removeNodeData(nodeDiff.removed);
  if (addedNodes.length > 0) graph.addNodeData(addedNodes);
  if (updatedNodes.length > 0) graph.updateNodeData(updatedNodes);
  if (edgeDiff.added.length > 0) graph.addEdgeData(edgeDiff.added);
  if (updatedEdges.length > 0) graph.updateEdgeData(updatedEdges);

  return (
    nodeDiff.added.length +
      nodeDiff.removed.length +
      nodeDiff.updated.length +
      edgeDiff.added.length +
      edgeDiff.removed.length +
      updatedEdges.length >
    0
  );
}

interface AgentFlowGraphProps {
  data: GraphData;
  selectedNodeId?: string;
  onNodeSelect: (node: AgentFlowNodeMeta) => void;
  onToggleCollapse: (nodeId: string) => void;
}

export function AgentFlowGraph({ data, selectedNodeId, onNodeSelect, onToggleCollapse }: AgentFlowGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const onNodeSelectRef = useRef(onNodeSelect);
  const onToggleCollapseRef = useRef(onToggleCollapse);
  const selectedNodeIdRef = useRef(selectedNodeId);
  const initializedRef = useRef(false);
  const initialFitDoneRef = useRef(false);
  const graphDataRef = useRef<GraphData>({ nodes: [], edges: [] });
  const pendingGraphDataRef = useRef<GraphData | null>(null);
  const updateQueueRef = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    onNodeSelectRef.current = onNodeSelect;
  }, [onNodeSelect]);

  useEffect(() => {
    onToggleCollapseRef.current = onToggleCollapse;
  }, [onToggleCollapse]);

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId]);

  const applySelectedState = useCallback(async (graph: Graph, nextSelectedNodeId?: string) => {
    if (graph.destroyed) return;
    const state = Object.fromEntries(
      graph.getNodeData().map((node) => {
        const id = String(node.id);
        return [id, nextSelectedNodeId === id ? ['selected'] : []];
      }),
    );
    await graph.setElementState(state, false);
  }, []);

  const graphOptions = useMemo<GraphOptions>(
    () => ({
      animation: false,
      node: {
        type: 'rect',
        style: (datum: NodeData) => {
          const meta = nodeMeta(datum);
          const colors = NODE_COLORS[meta.kind || 'agent'];
          const collapsible = Boolean(meta.collapsible);
          return {
            size: nodeSize(meta.kind || 'agent'),
            radius: 10,
            fill: colors.fill,
            stroke: colors.stroke,
            lineWidth: 1,
            shadowColor: 'rgba(15, 23, 42, 0.08)',
            shadowBlur: 10,
            shadowOffsetY: 4,
            cursor: 'pointer',
            labelText: meta.title,
            labelFill: colors.text,
            labelFontSize: 12,
            labelFontWeight: 600,
            labelWordWrap: true,
            labelMaxWidth: meta.kind === 'webpage' ? 138 : 168,
            labelPlacement: 'center' as const,
            badge: true,
            badges: [
              {
                text: nodeKindLabel(meta.kind || 'agent'),
                placement: 'right-top' as const,
                fill: colors.badge,
                fontSize: 8,
                opacity: meta.kind === 'session' ? 0.85 : 0.95,
              },
              ...(collapsible
                ? [
                    {
                      text: meta.collapsed ? '+' : '-',
                      placement: 'right' as const,
                      offsetX: 12,
                      fill: colors.text,
                      backgroundFill: '#ffffff',
                      backgroundStroke: colors.stroke,
                      backgroundLineWidth: 1.2,
                      backgroundRadius: 8,
                      stroke: colors.stroke,
                      fontSize: 12,
                      fontWeight: 700,
                      padding: [3, 7, 3, 7],
                    },
                  ]
                : []),
            ],
            port: false,
          };
        },
        state: {
          selected: {
            lineWidth: 2,
            stroke: '#111827',
            shadowColor: 'rgba(17, 24, 39, 0.18)',
            shadowBlur: 16,
          },
        },
      },
      edge: {
        type: 'cubic-horizontal',
        style: {
          stroke: '#cbd5e1',
          lineWidth: 1.2,
          endArrow: true,
          endArrowSize: 6,
        },
      },
      layout: {
        type: 'indented',
        direction: 'LR',
        dropCap: false,
        indent: 240,
        getHeight: () => 60,
        preLayout: false,
      },
      behaviors: ['zoom-canvas', 'drag-canvas'],
    }),
    [],
  );

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    let disposed = false;
    let initialFitTimer: number | null = null;

    const graph = new Graph({
      container,
      data,
      ...graphOptions,
    });
    graphRef.current = graph;
    if (import.meta.env.DEV) {
      (window as unknown as { __agentFlowGraph?: Graph }).__agentFlowGraph = graph;
    }
    graphDataRef.current = {
      nodes: [...(data.nodes || [])],
      edges: [...(data.edges || [])],
    };
    pendingGraphDataRef.current = null;
    initialFitDoneRef.current = false;

    const scheduleInitialFit = () => {
      if (initialFitDoneRef.current || graph.destroyed || graph.getNodeData().length === 0) return;
      if (initialFitTimer !== null) window.clearTimeout(initialFitTimer);
      initialFitTimer = window.setTimeout(async () => {
        initialFitTimer = null;
        if (disposed || graph.destroyed || initialFitDoneRef.current) return;
        const ready = await waitForStableContainer(container, graph);
        if (!ready || disposed || graph.destroyed || graph.getNodeData().length === 0) return;
        await graph.fitView({ when: 'always', direction: 'both' }, { duration: 0 });
        initialFitDoneRef.current = true;
      }, 120);
    };

    const handleNodeClick = (event: any) => {
      if (isCollapseToggleEvent(graph, event)) {
        if ((event?.detail ?? 1) > 1) return;
        const nodeId = event?.target?.id || elementNodeId(event?.originalTarget);
        if (nodeId) onToggleCollapseRef.current(nodeId);
        return;
      }

      const id = event?.target?.id;
      if (!id) return;
      const datum = graph.getNodeData(id);
      const meta = nodeMeta(datum);
      if (meta?.id) onNodeSelectRef.current(meta);
    };

    const handleResetViewport = async (event: any) => {
      if (isCollapseToggleTarget(event?.originalTarget)) return;
      if (event?.target?.id) return;
      if (graph.destroyed) return;
      await graph.fitView({ when: 'always', direction: 'both' }, { duration: 280, easing: 'easeInOutCubic' });
    };

    graph.on(NodeEvent.CLICK, handleNodeClick);
    graph.on(CanvasEvent.DBLCLICK, handleResetViewport);
    const initialRender = graph.render().then(async () => {
      if (disposed || graph.destroyed) return;
      initializedRef.current = true;
      scheduleInitialFit();

      const pendingData = pendingGraphDataRef.current;
      if (pendingData) {
        pendingGraphDataRef.current = null;
        applyGraphDataDiff(graph, graphDataRef.current, pendingData);
        graphDataRef.current = pendingData;
        await drawWithoutViewportShift(graph);
        if (disposed || graph.destroyed) return;
      }
      if (!disposed && !graph.destroyed) {
        await applySelectedState(graph, selectedNodeIdRef.current);
      }
    }).catch((error) => {
      if (!disposed) console.error('Agent flow graph initial render failed', error);
    });

    const resizeObserver = new ResizeObserver(() => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (disposed || graph.destroyed || !rect || rect.width <= 0 || rect.height <= 0) return;
      graph.setSize(rect.width, rect.height);
      if (initializedRef.current && !initialFitDoneRef.current) scheduleInitialFit();
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      disposed = true;
      initializedRef.current = false;
      initialFitDoneRef.current = false;
      pendingGraphDataRef.current = null;
      if (initialFitTimer !== null) window.clearTimeout(initialFitTimer);
      resizeObserver.disconnect();
      graph.off(NodeEvent.CLICK, handleNodeClick);
      graph.off(CanvasEvent.DBLCLICK, handleResetViewport);
      if (graphRef.current === graph) {
        graphRef.current = null;
      }
      if (import.meta.env.DEV && (window as unknown as { __agentFlowGraph?: Graph }).__agentFlowGraph === graph) {
        delete (window as unknown as { __agentFlowGraph?: Graph }).__agentFlowGraph;
      }
      void initialRender.finally(() => {
        if (!graph.destroyed) graph.destroy();
      });
    };
  }, [applySelectedState, graphOptions]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    const nextData = {
      nodes: [...(data.nodes || [])],
      edges: [...(data.edges || [])],
    };
    if (!initializedRef.current) {
      pendingGraphDataRef.current = nextData;
      return;
    }

    updateQueueRef.current = updateQueueRef.current
      .then(async () => {
        if (graphRef.current !== graph || graph.destroyed || !initializedRef.current) return;
        const changed = applyGraphDataDiff(graph, graphDataRef.current, nextData);
        graphDataRef.current = nextData;
        if (changed) {
          await drawWithoutViewportShift(graph);
        }
        if (graphRef.current === graph && !graph.destroyed) {
          await applySelectedState(graph, selectedNodeIdRef.current);
        }
      })
      .catch((error) => {
        console.error('Agent flow graph incremental update failed', error);
      });
  }, [applySelectedState, data]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !initializedRef.current) return;
    void applySelectedState(graph, selectedNodeId);
  }, [applySelectedState, selectedNodeId]);

  return <div ref={containerRef} className="h-full min-h-[360px] w-full" />;
}
