import { useState, useEffect, useCallback } from 'react';
import { ReactFlow, Background, Controls, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { umlNodeTypes, INHERITS_EDGE_STYLE, ASSOCIATES_EDGE_STYLE } from './umlNodes';

interface Props {
  moduleId: string | null;
  onClassClick: (classId: string) => void;
}

interface GraphData {
  nodes: Node[];
  edges: Edge[];
}

export default function ClassGraph({ moduleId, onClassClick }: Props) {
  const [graph, setGraph] = useState<GraphData>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!moduleId) {
      setGraph({ nodes: [], edges: [] });
      return;
    }
    setLoading(true);
    setError(null);
    fetch(`/api/xmi/graph?module_id=${encodeURIComponent(moduleId)}`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then((data: GraphData) => {
        // Apply edge styles based on type
        const styledEdges = (data.edges || []).map(e => ({
          ...e,
          style: e.type === 'inherits' ? INHERITS_EDGE_STYLE : ASSOCIATES_EDGE_STYLE,
          animated: e.type === 'inherits',
        }));
        setGraph({ nodes: data.nodes || [], edges: styledEdges });
      })
      .catch(err => setError(String(err)))
      .finally(() => setLoading(false));
  }, [moduleId]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    onClassClick(node.id);
  }, [onClassClick]);

  if (!moduleId) {
    return (
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#9ca3af', fontSize: 13,
      }}>
        请选择一个模块查看类关系图
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#6b7280', fontSize: 13,
      }}>
        加载中...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#ef4444', fontSize: 13,
      }}>
        加载失败: {error}
      </div>
    );
  }

  return (
    <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
      <ReactFlow
        nodes={graph.nodes}
        edges={graph.edges}
        nodeTypes={umlNodeTypes}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
      >
        <Background color="#e5e7eb" gap={20} />
        <Controls />
      </ReactFlow>
      {/* Legend */}
      <div style={{
        position: 'absolute', bottom: 40, right: 10,
        background: 'rgba(255,255,255,0.92)', border: '1px solid #e5e7eb',
        borderRadius: 6, padding: '6px 10px', fontSize: 11, zIndex: 5,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <div style={{ width: 24, height: 2, background: '#3b82f6' }} />
          <span style={{ color: '#374151' }}>继承</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 24, height: 2, background: '#f59e0b', borderTop: '2px dashed #f59e0b' }} />
          <span style={{ color: '#374151' }}>关联</span>
        </div>
      </div>
    </div>
  );
}
