import { useState, useEffect } from 'react';
import ChartView from '../ChartView';

interface ChartItem {
  chart_id: string;
  chart_type: string;
  option: any;
  timestamp?: number;
}

export default function ChartsTab() {
  const [charts, setCharts] = useState<ChartItem[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    const poll = async () => {
      try {
        const resp = await fetch('/api/chart/pending', { credentials: 'include' });
        if (resp.ok) {
          const data = await resp.json();
          if (data.chart_updates && data.chart_updates.length > 0) {
            setCharts(prev => [
              ...data.chart_updates.map((c: any) => ({
                chart_id: c.chart_id || `chart_${Date.now()}`,
                chart_type: c.chart_type || 'unknown',
                option: c.option || c.chart_config,
                timestamp: Date.now(),
              })),
              ...prev,
            ].slice(0, 50));
          }
        }
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleClear = () => setCharts([]);

  const handleDelete = (id: string) => {
    setCharts(prev => prev.filter(c => c.chart_id !== id));
  };

  if (charts.length === 0) {
    return (
      <div className="empty-state">
        暂无图表<br />
        在对话中请求数据分析后，图表将在此显示
      </div>
    );
  }

  return (
    <div className="charts-tab">
      <div className="charts-tab-header">
        <span>{charts.length} 个图表</span>
        <button className="btn-secondary btn-sm" onClick={handleClear}>清空</button>
      </div>

      {expandedId && (
        <div className="chart-expanded-overlay" onClick={() => setExpandedId(null)}>
          <div className="chart-expanded-content" onClick={e => e.stopPropagation()}>
            <button className="chart-expanded-close" onClick={() => setExpandedId(null)}>✕</button>
            {charts.filter(c => c.chart_id === expandedId).map(c => (
              <ChartView key={c.chart_id} option={c.option} chartId={c.chart_id} height="500px" />
            ))}
          </div>
        </div>
      )}

      <div className="charts-tab-grid">
        {charts.map(c => (
          <div key={c.chart_id} className="chart-card">
            <div className="chart-card-header">
              <span className="chart-type-badge">{c.chart_type}</span>
              <div className="chart-card-actions">
                <button className="chart-action-btn" onClick={() => setExpandedId(c.chart_id)} title="展开">⤢</button>
                <button className="chart-action-btn" onClick={() => handleDelete(c.chart_id)} title="删除">✕</button>
              </div>
            </div>
            <ChartView option={c.option} chartId={c.chart_id} compact />
          </div>
        ))}
      </div>
    </div>
  );
}
