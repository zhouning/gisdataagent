import { useState, useEffect } from 'react';
import { getPipelineLabel, formatTime } from './utils';

interface PipelineRun {
  timestamp: string;
  pipeline_type: string;
  intent: string;
  input_tokens: number;
  output_tokens: number;
  files_generated: number;
}

export default function HistoryTab() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/pipeline/history?days=${days}&limit=50`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setRuns(data.runs || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchHistory(); }, [days]);

  return (
    <div className="history-view">
      <div className="history-filter">
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            className={`history-range-btn ${days === d ? 'active' : ''}`}
            onClick={() => setDays(d)}
          >
            {d}天
          </button>
        ))}
      </div>
      {loading && runs.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : runs.length === 0 ? (
        <div className="empty-state">暂无分析记录</div>
      ) : (
        <div className="history-timeline">
          {runs.map((run, i) => (
            <div key={i} className="history-item">
              <div className="history-item-header">
                <span className={`pipeline-badge ${run.pipeline_type}`}>
                  {getPipelineLabel(run.pipeline_type)}
                </span>
                <span className="history-time">{formatTime(run.timestamp)}</span>
              </div>
              <div className="history-item-body">
                <span>意图: {run.intent}</span>
                <span>Token: {(run.input_tokens + run.output_tokens).toLocaleString()}</span>
                {run.files_generated > 0 && <span>{run.files_generated} 文件</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
