import { useState, useEffect } from 'react';

interface TraceEvent {
  timestamp: number;
  agent: string;
  type: string;
  decision: string;
  reasoning: string;
  alternatives: string[];
  context: Record<string, any>;
}

interface PipelineTrace {
  pipeline_type: string;
  trace_id: string;
  event_count: number;
  events: TraceEvent[];
  mermaid?: string;
}

export default function ObservabilityTab() {
  const [traceId, setTraceId] = useState('');
  const [trace, setTrace] = useState<PipelineTrace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadTrace = async (id: string) => {
    if (!id) return;
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/pipeline/trace/${id}`, { credentials: 'include' });
      if (r.ok) {
        const d = await r.json();
        setTrace(d);
      } else {
        setError('未找到追踪数据');
        setTrace(null);
      }
    } catch { setError('加载失败'); }
    finally { setLoading(false); }
  };

  const eventColor = (type: string) => {
    const m: Record<string, string> = {
      tool_selection: '#10b981',
      tool_rejection: '#ef4444',
      transfer: '#3b82f6',
      quality_gate: '#f59e0b',
    };
    return m[type] || '#888';
  };

  const eventIcon = (type: string) => {
    const m: Record<string, string> = {
      tool_selection: '🔧',
      tool_rejection: '❌',
      transfer: '➡️',
      quality_gate: '🔶',
    };
    return m[type] || '•';
  };

  return (
    <div style={{ padding: '8px 12px', fontSize: 13 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>Pipeline 决策追踪</div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <input
          placeholder="输入 Trace ID..."
          value={traceId}
          onChange={e => setTraceId(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && loadTrace(traceId)}
          style={{
            flex: 1, background: '#0d1117', border: '1px solid #444',
            borderRadius: 4, padding: '6px 10px', color: '#e0e0e0',
          }}
        />
        <button
          onClick={() => loadTrace(traceId)}
          disabled={loading || !traceId}
          style={{
            background: '#1e3a5f', color: '#7dd3fc', border: 'none',
            borderRadius: 4, padding: '6px 12px', cursor: 'pointer', fontSize: 12,
          }}
        >{loading ? '加载中...' : '查看'}</button>
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: 12, marginBottom: 8 }}>{error}</div>}

      {trace && (
        <div>
          {/* Summary */}
          <div style={{
            background: '#111827', border: '1px solid #1f2937', borderRadius: 6,
            padding: 10, marginBottom: 10,
          }}>
            <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
              <span><strong style={{ color: '#7dd3fc' }}>管线:</strong> {trace.pipeline_type}</span>
              <span><strong style={{ color: '#7dd3fc' }}>Trace:</strong> {trace.trace_id}</span>
              <span><strong style={{ color: '#7dd3fc' }}>事件:</strong> {trace.event_count}</span>
            </div>
          </div>

          {/* Timeline */}
          <div style={{ maxHeight: 400, overflow: 'auto' }}>
            {trace.events.map((e, i) => (
              <div key={i} style={{
                display: 'flex', gap: 8, marginBottom: 4, padding: '6px 8px',
                background: '#111827', border: '1px solid #1f2937', borderRadius: 4,
                borderLeft: `3px solid ${eventColor(e.type)}`,
              }}>
                <span style={{ fontSize: 16, lineHeight: '20px' }}>{eventIcon(e.type)}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontWeight: 600, color: '#e0e0e0', fontSize: 12 }}>{e.decision}</span>
                    <span style={{ fontSize: 10, color: '#666' }}>{e.agent}</span>
                  </div>
                  {e.reasoning && (
                    <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{e.reasoning}</div>
                  )}
                  {e.alternatives && e.alternatives.length > 0 && (
                    <div style={{ fontSize: 10, color: '#555', marginTop: 2 }}>
                      备选: {e.alternatives.join(', ')}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {trace.events.length === 0 && (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>暂无决策事件</div>
          )}
        </div>
      )}

      {!trace && !loading && !error && (
        <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>
          输入 Pipeline 执行的 Trace ID 查看决策追踪
        </div>
      )}
    </div>
  );
}
