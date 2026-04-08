import React, { useEffect, useState } from 'react';
import { ThumbsUp, ThumbsDown, BarChart3, RefreshCw, Play } from 'lucide-react';

interface FeedbackStats {
  total: number;
  upvotes: number;
  downvotes: number;
  satisfaction_rate: number;
  by_pipeline: Record<string, { up: number; down: number }>;
  trend: { date: string; up: number; down: number }[];
}

interface FeedbackItem {
  id: number;
  username: string;
  pipeline_type: string;
  query_text: string;
  vote: number;
  issue_description: string | null;
  resolved_at: string | null;
  resolution_action: string | null;
  created_at: string;
}

export default function FeedbackTab() {
  const [stats, setStats] = useState<FeedbackStats | null>(null);
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [sResp, lResp] = await Promise.all([
        fetch('/api/feedback/stats?days=30', { credentials: 'include' }),
        fetch('/api/feedback/list?limit=50', { credentials: 'include' }),
      ]);
      if (sResp.ok) setStats(await sResp.json());
      if (lResp.ok) setItems(await lResp.json());
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { fetchAll(); }, []);

  const processDownvotes = async () => {
    setProcessing(true);
    try {
      await fetch('/api/feedback/process-downvotes', {
        method: 'POST', credentials: 'include',
      });
      fetchAll();
    } catch { /* ignore */ }
    setProcessing(false);
  };

  const rate = stats ? (stats.satisfaction_rate * 100).toFixed(1) : '—';
  const maxTrend = stats?.trend
    ? Math.max(...stats.trend.map(t => t.up + t.down), 1)
    : 1;

  return (
    <div style={{ padding: '12px 16px', color: '#e0e0e0', fontSize: 13 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, color: '#a0d2db' }}>
          <BarChart3 size={16} style={{ marginRight: 6, verticalAlign: 'text-bottom' }} />
          反馈看板
        </h3>
        <button onClick={fetchAll} disabled={loading}
          style={{ background: 'none', border: '1px solid #444', borderRadius: 4, color: '#888', padding: '3px 8px', cursor: 'pointer', fontSize: 12 }}>
          <RefreshCw size={12} /> 刷新
        </button>
      </div>

      {/* Stats cards */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
          <StatCard label="总反馈" value={stats.total} />
          <StatCard label="满意率" value={`${rate}%`} color={parseFloat(rate) >= 80 ? '#4ade80' : '#f59e0b'} />
          <StatCard label="好评" value={stats.upvotes} color="#4ade80" icon={<ThumbsUp size={12} />} />
          <StatCard label="差评" value={stats.downvotes} color="#f87171" icon={<ThumbsDown size={12} />} />
        </div>
      )}

      {/* Trend sparkline */}
      {stats?.trend && stats.trend.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>30 天趋势</div>
          <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: 40 }}>
            {stats.trend.map((t, i) => {
              const total = t.up + t.down;
              const h = Math.max(2, (total / maxTrend) * 36);
              const upPct = total > 0 ? t.up / total : 0;
              return (
                <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}
                  title={`${t.date}: ${t.up}👍 ${t.down}👎`}>
                  <div style={{ height: h * upPct, background: '#4ade80', borderRadius: '2px 2px 0 0' }} />
                  <div style={{ height: h * (1 - upPct), background: '#f87171', borderRadius: '0 0 2px 2px' }} />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* By pipeline */}
      {stats?.by_pipeline && Object.keys(stats.by_pipeline).length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>按管线分布</div>
          {Object.entries(stats.by_pipeline).map(([pipe, counts]) => {
            const total = counts.up + counts.down;
            const upPct = total > 0 ? (counts.up / total) * 100 : 0;
            return (
              <div key={pipe} style={{ display: 'flex', alignItems: 'center', marginBottom: 4, fontSize: 12 }}>
                <span style={{ width: 80, color: '#aaa' }}>{pipe}</span>
                <div style={{ flex: 1, height: 8, background: '#333', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${upPct}%`, height: '100%', background: '#4ade80' }} />
                </div>
                <span style={{ marginLeft: 8, color: '#888', minWidth: 40 }}>{counts.up}/{total}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Admin action */}
      <div style={{ marginBottom: 12 }}>
        <button onClick={processDownvotes} disabled={processing}
          style={{ background: '#1a1a2e', border: '1px solid #f87171', borderRadius: 4, color: '#f87171', padding: '4px 12px', cursor: 'pointer', fontSize: 12 }}>
          <Play size={12} style={{ marginRight: 4 }} />
          {processing ? '处理中...' : '批量处理差评'}
        </button>
      </div>

      {/* Recent feedback list */}
      <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>最近反馈</div>
      <div style={{ maxHeight: 300, overflowY: 'auto' }}>
        {items.map(item => (
          <div key={item.id}
            style={{ padding: '6px 8px', borderBottom: '1px solid #2a2a3a', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <span style={{ color: item.vote === 1 ? '#4ade80' : '#f87171', flexShrink: 0 }}>
              {item.vote === 1 ? <ThumbsUp size={12} /> : <ThumbsDown size={12} />}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: '#ccc', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.query_text}
              </div>
              {item.issue_description && (
                <div style={{ color: '#f59e0b', fontSize: 11, marginTop: 2 }}>{item.issue_description}</div>
              )}
            </div>
            <span style={{ color: '#666', fontSize: 11, flexShrink: 0 }}>{item.pipeline_type || '—'}</span>
            <span style={{ color: item.resolved_at ? '#4ade80' : '#666', fontSize: 11, flexShrink: 0 }}>
              {item.resolved_at ? '✓' : '○'}
            </span>
          </div>
        ))}
        {items.length === 0 && !loading && (
          <div style={{ textAlign: 'center', color: '#555', padding: 20 }}>暂无反馈数据</div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color, icon }: { label: string; value: string | number; color?: string; icon?: React.ReactNode }) {
  return (
    <div style={{ background: '#1a1a2e', borderRadius: 6, padding: '8px 12px', textAlign: 'center' }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>{icon} {label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: color || '#e0e0e0' }}>{value}</div>
    </div>
  );
}
