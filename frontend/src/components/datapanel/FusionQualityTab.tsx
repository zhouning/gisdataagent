import { useState, useEffect, useCallback } from 'react';

/* ------------------------------------------------------------------
   Types
   ------------------------------------------------------------------ */

interface FusionOperation {
  id: number;
  username: string;
  strategy: string;
  quality_score: number | null;
  duration_s: number | null;
  created_at: string;
  v2_features: {
    temporal: boolean;
    conflict: boolean;
    explainability: boolean;
  };
}

interface QualityDetail {
  operation_id: number;
  quality_score: number | null;
  quality_report: Record<string, unknown>;
  explainability: Record<string, unknown>;
}

/* ------------------------------------------------------------------
   Helpers
   ------------------------------------------------------------------ */

function confidenceBadge(score: number | null): { label: string; color: string } {
  if (score === null) return { label: '—', color: '#888' };
  if (score >= 0.7) return { label: '高', color: '#10b981' };
  if (score >= 0.3) return { label: '中', color: '#f59e0b' };
  return { label: '低', color: '#ef4444' };
}

/* ------------------------------------------------------------------
   Component
   ------------------------------------------------------------------ */

export default function FusionQualityTab() {
  const [operations, setOperations] = useState<FusionOperation[]>([]);
  const [selected, setSelected] = useState<QualityDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* Fetch operations list */
  const fetchOperations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch('/api/fusion/operations?limit=50');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setOperations(data.items ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchOperations(); }, [fetchOperations]);

  /* Fetch quality detail for a specific operation */
  const fetchDetail = useCallback(async (opId: number) => {
    try {
      const resp = await fetch(`/api/fusion/quality/${opId}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: QualityDetail = await resp.json();
      setSelected(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  /* ----------------------------------------------------------------
     Render
     ---------------------------------------------------------------- */

  return (
    <div style={{ padding: 12, height: '100%', overflow: 'auto', fontSize: 13 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>融合质量监控</h3>
        <button
          onClick={fetchOperations}
          style={{ padding: '4px 12px', cursor: 'pointer', borderRadius: 4, border: '1px solid #ccc' }}
        >
          刷新
        </button>
      </div>

      {loading && <p>加载中...</p>}
      {error && <p style={{ color: '#ef4444' }}>错误: {error}</p>}

      {/* Operations Table */}
      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #e5e7eb', textAlign: 'left' }}>
            <th style={{ padding: '6px 8px' }}>ID</th>
            <th style={{ padding: '6px 8px' }}>策略</th>
            <th style={{ padding: '6px 8px' }}>质量</th>
            <th style={{ padding: '6px 8px' }}>耗时</th>
            <th style={{ padding: '6px 8px' }}>v2 特性</th>
            <th style={{ padding: '6px 8px' }}>时间</th>
          </tr>
        </thead>
        <tbody>
          {operations.map((op) => {
            const badge = confidenceBadge(op.quality_score);
            return (
              <tr
                key={op.id}
                onClick={() => fetchDetail(op.id)}
                style={{
                  borderBottom: '1px solid #f3f4f6',
                  cursor: 'pointer',
                  background: selected?.operation_id === op.id ? '#eff6ff' : 'transparent',
                }}
              >
                <td style={{ padding: '6px 8px' }}>#{op.id}</td>
                <td style={{ padding: '6px 8px' }}>{op.strategy}</td>
                <td style={{ padding: '6px 8px' }}>
                  <span style={{
                    display: 'inline-block', padding: '2px 8px', borderRadius: 10,
                    background: badge.color + '20', color: badge.color, fontWeight: 600,
                  }}>
                    {op.quality_score !== null ? op.quality_score.toFixed(2) : '—'} {badge.label}
                  </span>
                </td>
                <td style={{ padding: '6px 8px' }}>{op.duration_s?.toFixed(1)}s</td>
                <td style={{ padding: '6px 8px' }}>
                  {op.v2_features.temporal && <span title="时序对齐">⏱</span>}
                  {op.v2_features.conflict && <span title="冲突解决">⚡</span>}
                  {op.v2_features.explainability && <span title="可解释性">🔍</span>}
                  {!op.v2_features.temporal && !op.v2_features.conflict && !op.v2_features.explainability && '—'}
                </td>
                <td style={{ padding: '6px 8px', fontSize: 11, color: '#6b7280' }}>
                  {op.created_at?.slice(0, 16)}
                </td>
              </tr>
            );
          })}
          {operations.length === 0 && !loading && (
            <tr><td colSpan={6} style={{ padding: 16, textAlign: 'center', color: '#9ca3af' }}>
              暂无融合操作记录
            </td></tr>
          )}
        </tbody>
      </table>

      {/* Detail Panel */}
      {selected && (
        <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: 12 }}>
          <h4 style={{ margin: '0 0 8px' }}>操作 #{selected.operation_id} 详情</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <strong>质量分数:</strong>{' '}
              {selected.quality_score !== null ? selected.quality_score.toFixed(4) : '—'}
            </div>
            <div>
              <strong>质量报告:</strong>{' '}
              {JSON.stringify(selected.quality_report?.warnings ?? [], null, 0).slice(0, 100)}
            </div>
          </div>
          {selected.explainability && Object.keys(selected.explainability).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <strong>可解释性元数据:</strong>
              <pre style={{ background: '#f9fafb', padding: 8, borderRadius: 4, fontSize: 11, overflow: 'auto', maxHeight: 200 }}>
                {JSON.stringify(selected.explainability, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
