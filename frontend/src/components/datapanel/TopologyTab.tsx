import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { formatNumber, getLocaleHeaders } from '../../i18n';

/* ------------------------------------------------------------------
   Types
   ------------------------------------------------------------------ */

interface AgentInfo {
  id: string;
  name: string;
  type: string;
  parent_id: string | null;
  tools: string[];
  children: string[];
  model?: string;
  instruction_snippet?: string;
  mentionable?: boolean;
  pipeline_label?: string;
}

interface ToolsetInfo {
  name: string;
  description: string;
  tool_count: number;
}

interface PipelineInfo {
  id: string;
  label: string;
  color: string;
}

interface TopologyData {
  agents: AgentInfo[];
  toolsets: ToolsetInfo[];
  pipelines: PipelineInfo[];
}

/* ------------------------------------------------------------------
   Color helpers
   ------------------------------------------------------------------ */

const TYPE_COLORS: Record<string, string> = {
  SequentialAgent: '#3b82f6',
  ParallelAgent: '#8b5cf6',
  LoopAgent: '#f59e0b',
  LlmAgent: '#10b981',
};

const getTypeColor = (type: string) => TYPE_COLORS[type] || '#6b7280';
const TYPE_LABEL_KEYS: Record<string, string> = {
  SequentialAgent: 'sequential',
  ParallelAgent: 'parallel',
  LoopAgent: 'loop',
  LlmAgent: 'llm',
};

/* ------------------------------------------------------------------
   Custom Nodes
   ------------------------------------------------------------------ */

function AgentNode({ data }: NodeProps) {
  const { t } = useTranslation();
  const d = data as any;
  const color = getTypeColor(d.agentType);
  const typeKey = TYPE_LABEL_KEYS[d.agentType];
  return (
    <div style={{
      background: '#fff',
      border: `2px solid ${color}`,
      borderRadius: 6,
      padding: '6px 10px',
      minWidth: 100,
      fontSize: 11,
      boxShadow: '0 1px 3px rgba(0,0,0,.1)',
    }}>
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <span style={{
          background: color, color: '#fff', borderRadius: 3,
          padding: '0 4px', fontSize: 8, fontWeight: 600,
        }}>
          {typeKey ? t(`topologyTab.types.${typeKey}.short`) : d.agentType}
        </span>
        <span style={{ fontWeight: 600, fontSize: 11, color: '#1e293b' }}>{d.label}</span>
        {d.mentionable && (
          <span style={{ color: '#10b981', fontSize: 10, fontWeight: 700 }}>@</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

function ToolsetNode({ data }: NodeProps) {
  const { t } = useTranslation();
  const d = data as any;
  return (
    <div style={{
      background: '#fffbeb',
      border: '2px solid #f59e0b',
      borderRadius: 8,
      padding: '6px 10px',
      minWidth: 120,
      fontSize: 10,
      boxShadow: '0 1px 3px rgba(0,0,0,.08)',
    }}>
      <Handle type="target" position={Position.Top} style={{ background: '#f59e0b' }} />
      <div style={{ fontWeight: 600, fontSize: 11, color: '#92400e' }}>{d.label}</div>
      <div style={{ fontSize: 9, color: '#78716c' }}>{d.description}</div>
      <div style={{ fontSize: 9, color: '#b45309', marginTop: 2 }}>
        {t('topologyTab.summary.tools', { count: formatNumber(d.tool_count) })}
      </div>
    </div>
  );
}

const nodeTypes = { agent: AgentNode, toolset: ToolsetNode };

/* ------------------------------------------------------------------
   Layout
   ------------------------------------------------------------------ */

function layoutHierarchy(agents: AgentInfo[], pipelines: PipelineInfo[]): { nodes: Node[], edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Find pipeline colors
  const pipelineColors: Record<string, string> = {};
  for (const p of pipelines) {
    pipelineColors[p.id] = p.color;
  }

  // Build parent→children map
  const childrenMap: Record<string, AgentInfo[]> = {};
  const agentMap: Record<string, AgentInfo> = {};
  for (const a of agents) {
    agentMap[a.id] = a;
    if (a.parent_id) {
      if (!childrenMap[a.parent_id]) childrenMap[a.parent_id] = [];
      childrenMap[a.parent_id].push(a);
    }
  }

  // Find root agents (no parent)
  const roots = agents.filter(a => !a.parent_id);

  // Lay out each pipeline as a column
  const COL_WIDTH = 200;
  const ROW_HEIGHT = 75;
  let globalColOffset = 0;

  function placeAgent(agent: AgentInfo, depth: number, colStart: number): number {
    const children = childrenMap[agent.id] || [];
    let totalLeafWidth = 0;

    if (children.length === 0) {
      // Leaf node: takes 1 column
      nodes.push({
        id: agent.id,
        type: 'agent',
        position: { x: colStart * COL_WIDTH, y: depth * ROW_HEIGHT },
        data: {
          label: agent.name,
          agentType: agent.type,
          tools: agent.tools,
          model: agent.model,
          instruction_snippet: agent.instruction_snippet,
          mentionable: agent.mentionable,
          pipeline_label: agent.pipeline_label,
        },
      });
      return 1;
    }

    // Place children first to determine total width
    let childCol = colStart;
    for (const child of children) {
      const w = placeAgent(child, depth + 1, childCol);
      totalLeafWidth += w;
      childCol += w;

      // Add edge
      edges.push({
        id: `e-${agent.id}-${child.id}`,
        source: agent.id,
        target: child.id,
        type: 'smoothstep',
        animated: agent.type === 'ParallelAgent',
        style: { stroke: pipelineColors[roots.find(r => isDescendant(r.id, agent.id, childrenMap))?.id || ''] || '#94a3b8' },
      });
    }

    // Place this agent centered over its children
    const centerCol = colStart + totalLeafWidth / 2 - 0.5;
    nodes.push({
      id: agent.id,
      type: 'agent',
      position: { x: centerCol * COL_WIDTH, y: depth * ROW_HEIGHT },
      data: {
        label: agent.name,
        agentType: agent.type,
        tools: agent.tools,
        model: agent.model,
        instruction_snippet: agent.instruction_snippet,
        mentionable: agent.mentionable,
        pipeline_label: agent.pipeline_label,
      },
    });

    return totalLeafWidth;
  }

  for (const root of roots) {
    const w = placeAgent(root, 0, globalColOffset);
    globalColOffset += w + 1; // Gap between pipelines
  }

  return { nodes, edges };
}

function isDescendant(rootId: string, targetId: string, childrenMap: Record<string, AgentInfo[]>): boolean {
  if (rootId === targetId) return true;
  for (const child of childrenMap[rootId] || []) {
    if (isDescendant(child.id, targetId, childrenMap)) return true;
  }
  return false;
}

/* ------------------------------------------------------------------
   Component
   ------------------------------------------------------------------ */

export default function TopologyTab() {
  const { t, i18n } = useTranslation();
  const [data, setData] = useState<TopologyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<AgentInfo | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [instrExpanded, setInstrExpanded] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const loadTopology = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch('/api/agent-topology', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json: TopologyData = await resp.json();
      setData(json);
      const layout = layoutHierarchy(json.agents, json.pipelines);
      setNodes(layout.nodes);
      setEdges(layout.edges);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [setNodes, setEdges, i18n.resolvedLanguage]);

  useEffect(() => { loadTopology(); }, [loadTopology]);

  const handleNodeClick = useCallback((_: any, node: Node) => {
    if (data) {
      const agent = data.agents.find(a => a.id === node.id);
      if (agent) {
        setSelectedAgent(agent);
        setInstrExpanded(false);
      }
    }
  }, [data]);

  const legend = useMemo(() => [
    { type: 'SequentialAgent', label: t('topologyTab.types.sequential.full'), color: TYPE_COLORS.SequentialAgent },
    { type: 'ParallelAgent', label: t('topologyTab.types.parallel.full'), color: TYPE_COLORS.ParallelAgent },
    { type: 'LoopAgent', label: t('topologyTab.types.loop.full'), color: TYPE_COLORS.LoopAgent },
    { type: 'LlmAgent', label: t('topologyTab.types.llm.full'), color: TYPE_COLORS.LlmAgent },
  ], [t, i18n.resolvedLanguage]);

  const typeLabel = (type: string) => {
    const key = TYPE_LABEL_KEYS[type];
    return key ? t(`topologyTab.types.${key}.short`) : type;
  };

  // Escape key listener for fullscreen
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && fullscreen) setFullscreen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [fullscreen]);

  if (loading) return <div className="empty-state">{t('topologyTab.common.loading')}</div>;
  if (error) return <div className="empty-state">{t('topologyTab.errors.load', { error })}</div>;
  if (!data) return <div className="empty-state">{t('topologyTab.empty.data')}</div>;

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      ...(fullscreen ? {
        position: 'fixed', inset: 0,
        zIndex: 9999, background: '#fff',
      } : {}),
    }}>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, padding: '8px 12px', borderBottom: '1px solid #e5e7eb', flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>{t('topologyTab.title')}</span>
        {legend.map(l => (
          <span key={l.type} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: l.color, display: 'inline-block' }} />
            {l.label}
          </span>
        ))}
        <span style={{ marginInlineStart: 'auto', fontSize: 10, color: '#9ca3af' }}>
          {t('topologyTab.summary.overview', {
            agents: formatNumber(data.agents.length),
            toolsets: formatNumber(data.toolsets.length),
          })}
        </span>
        <button
          onClick={loadTopology}
          disabled={loading}
          style={{
            background: '#f3f4f6', color: '#374151', border: '1px solid #e5e7eb',
            borderRadius: 4, padding: '2px 8px', fontSize: 11, cursor: 'pointer',
            marginInlineEnd: 4,
          }}
          title={t('topologyTab.actions.refreshTitle')}
        >
          {loading ? t('topologyTab.actions.refreshing') : t('topologyTab.actions.refresh')}
        </button>
        <button
          onClick={() => setFullscreen(!fullscreen)}
          style={{
            background: fullscreen ? '#ef4444' : '#3b82f6', color: '#fff', border: 'none',
            borderRadius: 4, padding: '2px 8px', fontSize: 11, cursor: 'pointer',
          }}
          title={fullscreen ? t('topologyTab.actions.exitFullscreenTitle') : t('topologyTab.actions.fullscreenTitle')}
        >
          {fullscreen ? t('topologyTab.actions.exitFullscreen') : t('topologyTab.actions.fullscreen')}
        </button>
      </div>

      {/* Flow */}
      <div style={{ flex: 1, minHeight: 300 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.3}
          maxZoom={2}
        >
          <Background gap={20} size={1} />
          <Controls />
          <MiniMap
            nodeStrokeWidth={2}
            nodeColor={(n) => {
              const t = (n.data as any)?.agentType;
              return getTypeColor(t) || '#e5e7eb';
            }}
            style={{ height: 80, width: 120 }}
          />
        </ReactFlow>
      </div>

      {/* Detail panel */}
      {selectedAgent && (
        <div style={{
          borderTop: '1px solid #e5e7eb', padding: '10px 14px', background: '#f9fafb',
          fontSize: 11, maxHeight: 200, overflowY: 'auto',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontWeight: 700, fontSize: 13 }}>{selectedAgent.name}</span>
              <span style={{
                background: getTypeColor(selectedAgent.type), color: '#fff', fontSize: 9,
                fontWeight: 600, padding: '1px 6px', borderRadius: 3,
              }}>
                {typeLabel(selectedAgent.type)}
              </span>
              {selectedAgent.pipeline_label && (
                <span style={{
                  background: '#eef2ff', color: '#4338ca', fontSize: 9,
                  padding: '1px 6px', borderRadius: 3, border: '1px solid #c7d2fe',
                }}>
                  {selectedAgent.pipeline_label}
                </span>
              )}
              {selectedAgent.mentionable && (
                <span style={{
                  background: '#d1fae5', color: '#065f46', fontSize: 9,
                  padding: '1px 6px', borderRadius: 3, border: '1px solid #a7f3d0',
                }}>
                  {t('topologyTab.details.mentionable')}
                </span>
              )}
            </div>
            <button onClick={() => setSelectedAgent(null)}
              title={t('topologyTab.actions.close')}
              aria-label={t('topologyTab.actions.close')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', fontSize: 14 }}>
              ✕
            </button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr', gap: '4px 8px' }}>
            <span style={{ color: '#6b7280' }}>{t('topologyTab.details.type')}</span>
            <span>{typeLabel(selectedAgent.type)}</span>
            {selectedAgent.model && <>
              <span style={{ color: '#6b7280' }}>{t('topologyTab.details.model')}</span>
              <span>{selectedAgent.model}</span>
            </>}
            <span style={{ color: '#6b7280' }}>{t('topologyTab.details.toolsets')}</span>
            <span>
              {selectedAgent.tools.length > 0
                ? selectedAgent.tools.map(t => t.replace('Toolset', '')).join(', ')
                : t('topologyTab.common.none')}
            </span>
            <span style={{ color: '#6b7280' }}>{t('topologyTab.details.children')}</span>
            <span>
              {selectedAgent.children.length > 0
                ? selectedAgent.children.map(cid => (
                    <button key={cid}
                      onClick={() => {
                        const child = data?.agents.find(a => a.id === cid);
                        if (child) { setSelectedAgent(child); setInstrExpanded(false); }
                      }}
                      style={{
                        background: '#f3f4f6', border: '1px solid #e5e7eb',
                        borderRadius: 3, padding: '1px 5px', marginBlockEnd: 2, marginInlineEnd: 3,
                        fontSize: 10, cursor: 'pointer',
                      }}>
                      {cid}
                    </button>
                  ))
                : t('topologyTab.common.none')}
            </span>
          </div>
          {selectedAgent.instruction_snippet && (
            <div style={{ marginTop: 6 }}>
              <button onClick={() => setInstrExpanded(v => !v)}
                style={{
                  background: 'none', border: 'none', color: '#3b82f6',
                  cursor: 'pointer', fontSize: 10, padding: 0,
                }}>
                {instrExpanded ? '▼ ' : '▶ '}
                {instrExpanded ? t('topologyTab.actions.collapseInstruction') : t('topologyTab.actions.expandInstruction')}
              </button>
              {instrExpanded && (
                <div style={{ marginTop: 4, padding: '6px 8px', background: '#fff',
                              borderRadius: 4, fontSize: 10, color: '#4b5563',
                              border: '1px solid #e5e7eb', whiteSpace: 'pre-wrap' }}>
                  {selectedAgent.instruction_snippet}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
