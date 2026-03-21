import { useState, useEffect } from 'react';
import { getPipelineLabel } from './utils';

export default function AnalyticsTab() {
  const [latency, setLatency] = useState<any>(null);
  const [toolSuccess, setToolSuccess] = useState<any[]>([]);
  const [throughput, setThroughput] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch('/api/analytics/latency', { credentials: 'include' }).then(r => r.ok ? r.json() : null),
      fetch('/api/analytics/tool-success', { credentials: 'include' }).then(r => r.ok ? r.json() : null),
      fetch('/api/analytics/throughput', { credentials: 'include' }).then(r => r.ok ? r.json() : null),
    ]).then(([lat, tools, tp]) => {
      setLatency(lat);
      setToolSuccess(tools?.tools || []);
      setThroughput(tp?.daily || []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="data-panel-empty">加载中...</div>;

  return (
    <div className="data-panel-list" style={{ fontSize: 12 }}>
      {/* Latency */}
      <div className="data-panel-card" style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>管线延迟 (ms)</div>
        {latency ? (
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {['p50', 'p75', 'p90', 'p99'].map(k => (
              <div key={k} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#0d9488' }}>{latency[k] || 0}</div>
                <div style={{ color: '#888' }}>{k.toUpperCase()}</div>
              </div>
            ))}
          </div>
        ) : <div style={{ color: '#888' }}>无数据</div>}
      </div>

      {/* Tool Success Rate Top 5 */}
      <div className="data-panel-card" style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>工具成功率 Top 5</div>
        {toolSuccess.slice(0, 5).map((t: any, i: number) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ width: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.tool_name}</span>
            <div style={{ flex: 1, height: 14, background: '#333', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ width: `${(t.success_rate || 0) * 100}%`, height: '100%', background: '#22c55e', borderRadius: 4 }}></div>
            </div>
            <span style={{ width: 40, textAlign: 'right' }}>{((t.success_rate || 0) * 100).toFixed(0)}%</span>
          </div>
        ))}
        {toolSuccess.length === 0 && <div style={{ color: '#888' }}>无数据</div>}
      </div>

      {/* Throughput */}
      <div className="data-panel-card">
        <div style={{ fontWeight: 600, marginBottom: 6 }}>每日吞吐量</div>
        {throughput.slice(-7).map((d: any, i: number) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
            <span>{d.date}</span>
            <span style={{ color: '#0d9488' }}>{d.count} 次</span>
          </div>
        ))}
        {throughput.length === 0 && <div style={{ color: '#888' }}>无数据</div>}
      </div>
    </div>
  );
}
