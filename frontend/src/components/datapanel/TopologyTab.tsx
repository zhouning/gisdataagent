import { useState, useEffect, useCallback, useMemo } from 'react';
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
const getTypeLabel = (type: string) => {
  const map: Record<string, string> = {
    SequentialAgent: '顺序',
    ParallelAgent: '并行',
    LoopAgent: '循环',
    LlmAgent: 'LLM',
  };
  return map[type] || type;
};

/* ------------------------------------------------------------------
   Custom Nodes
   ------------------------------------------------------------------ */

function AgentNode({ data }: NodeProps) {
  const d = data as any;
  const color = getTypeColor(d.agentType);
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
          {getTypeLabel(d.agentType)}
        </span>
        <span style={{ fontWeight: 600, fontSize: 11 }}>{d.label}</span>
        {d.mentionable && (
          <span style={{ color: '#10b981', fontSize: 10, fontWeight: 700 }}>@</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

function ToolsetNode({ data }: NodeProps) {
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
      <div style={{ fontSize: 9, color: '#b45309', marginTop: 2 }}>{d.tool_count} 个工具</div>
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
      const resp = await fetch('/api/agent-topology', { credentials: 'include' });
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
  }, [setNodes, setEdges]);

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
    { type: 'SequentialAgent', label: '顺序执行', color: TYPE_COLORS.SequentialAgent },
    { type: 'ParallelAgent', label: '并行执行', color: TYPE_COLORS.ParallelAgent },
    { type: 'LoopAgent', label: '循环执行', color: TYPE_COLORS.LoopAgent },
    { type: 'LlmAgent', label: 'LLM 智能体', color: TYPE_COLORS.LlmAgent },
  ], []);

  // Escape key listener for fullscreen
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && fullscreen) setFullscreen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [fullscreen]);

  if (loading) return <div className="empty-state">加载拓扑结构...</div>;
  if (error) return <div className="empty-state">加载失败: {error}</div>;
  if (!data) return <div className="empty-state">无数据</div>;

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      ...(fullscreen ? {
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        zIndex: 9999, background: '#fff',
      } : {}),
    }}>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, padding: '8px 12px', borderBottom: '1px solid #e5e7eb', flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>智能体拓扑</span>
        {legend.map(l => (
          <span key={l.type} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: l.color, display: 'inline-block' }} />
            {l.label}
          </span>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 10, color: '#9ca3af' }}>
          {data.agents.length} 个智能体 · {data.toolsets.length} 个工具集
        </span>
        <button
          onClick={loadTopology}
          disabled={loading}
          style={{
            background: '#f3f4f6', color: '#374151', border: '1px solid #e5e7eb',
            borderRadius: 4, padding: '2px 8px', fontSize: 11, cursor: 'pointer',
            marginRight: 4,
          }}
          title="刷新拓扑"
        >
          {loading ? '刷新中...' : '刷新'}
        </button>
        <button
          onClick={() => setFullscreen(!fullscreen)}
          style={{
            background: fullscreen ? '#ef4444' : '#3b82f6', color: '#fff', border: 'none',
            borderRadius: 4, padding: '2px 8px', fontSize: 11, cursor: 'pointer',
          }}
          title={fullscreen ? '退出全屏 (Esc)' : '全屏查看'}
        >
          {fullscreen ? '退出全屏' : '全屏'}
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
                {getTypeLabel(selectedAgent.type)}
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
                  可 @ 调用
                </span>
              )}
            </div>
            <button onClick={() => setSelectedAgent(null)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', fontSize: 14 }}>
              ✕
            </button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr', gap: '4px 8px' }}>
            <span style={{ color: '#6b7280' }}>类型</span>
            <span>{selectedAgent.type}</span>
            {selectedAgent.model && <>
              <span style={{ color: '#6b7280' }}>模型</span>
              <span>{selectedAgent.model}</span>
            </>}
            <span style={{ color: '#6b7280' }}>工具集</span>
            <span>
              {selectedAgent.tools.length > 0
                ? selectedAgent.tools.map(t => t.replace('Toolset', '')).join(', ')
                : '无'}
            </span>
            <span style={{ color: '#6b7280' }}>子节点</span>
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
                        borderRadius: 3, padding: '1px 5px', margin: '0 3px 2px 0',
                        fontSize: 10, cursor: 'pointer',
                      }}>
                      {cid}
                    </button>
                  ))
                : '无'}
            </span>
          </div>
          {selectedAgent.instruction_snippet && (
            <div style={{ marginTop: 6 }}>
              <button onClick={() => setInstrExpanded(v => !v)}
                style={{
                  background: 'none', border: 'none', color: '#3b82f6',
                  cursor: 'pointer', fontSize: 10, padding: 0,
                }}>
                {instrExpanded ? '▼ 收起指令' : '▶ 展开指令摘要'}
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
