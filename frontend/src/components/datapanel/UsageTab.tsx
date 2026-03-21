import { useState, useEffect } from 'react';
import { getPipelineLabel } from './utils';

interface UsageData {
  daily: { count: number; tokens: number };
  monthly: { count: number; total_tokens: number; input_tokens: number; output_tokens: number };
  limits: { allowed: boolean; reason: string; daily_count: number; daily_limit: number };
  pipeline_breakdown: { pipeline_type: string; count: number; tokens: number }[];
}

export default function UsageTab() {
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchUsage = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/user/token-usage', { credentials: 'include' });
      if (resp.ok) setUsage(await resp.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchUsage();
    const interval = setInterval(fetchUsage, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading && !usage) return <div className="empty-state">加载中...</div>;
  if (!usage) return <div className="empty-state">无法获取用量数据</div>;

  const dailyPct = usage.limits.daily_limit > 0
    ? Math.min(100, Math.round((usage.limits.daily_count / usage.limits.daily_limit) * 100))
    : 0;

  const maxTokens = usage.pipeline_breakdown.length > 0
    ? Math.max(...usage.pipeline_breakdown.map((b) => b.tokens))
    : 1;

  return (
    <div className="usage-view">
      <div className="usage-card">
        <div className="usage-card-title">今日用量</div>
        <div className="usage-card-value">{usage.limits.daily_count} / {usage.limits.daily_limit}</div>
        <div className="usage-progress">
          <div
            className={`usage-progress-fill ${dailyPct >= 90 ? 'warning' : ''}`}
            style={{ width: `${dailyPct}%` }}
          />
        </div>
        <div className="usage-card-sub">{usage.daily.tokens.toLocaleString()} tokens</div>
      </div>

      <div className="usage-card">
        <div className="usage-card-title">本月汇总</div>
        <div className="usage-card-value">{usage.monthly.total_tokens.toLocaleString()}</div>
        <div className="usage-card-sub">tokens</div>
        <div className="usage-detail-row">
          <span>输入</span><span>{usage.monthly.input_tokens.toLocaleString()}</span>
        </div>
        <div className="usage-detail-row">
          <span>输出</span><span>{usage.monthly.output_tokens.toLocaleString()}</span>
        </div>
        <div className="usage-detail-row">
          <span>分析次数</span><span>{usage.monthly.count}</span>
        </div>
      </div>

      {usage.pipeline_breakdown.length > 0 && (
        <div className="usage-card">
          <div className="usage-card-title">本月管线分布</div>
          {usage.pipeline_breakdown.map((b) => (
            <div key={b.pipeline_type} className="usage-breakdown-row">
              <div className="usage-breakdown-label">
                <span className={`pipeline-badge ${b.pipeline_type}`}>
                  {getPipelineLabel(b.pipeline_type)}
                </span>
                <span className="usage-breakdown-count">{b.count}次</span>
              </div>
              <div className="usage-progress">
                <div
                  className="usage-progress-fill"
                  style={{ width: `${Math.round((b.tokens / maxTokens) * 100)}%` }}
                />
              </div>
              <div className="usage-breakdown-tokens">{b.tokens.toLocaleString()}</div>
            </div>
          ))}
        </div>
      )}

      {!usage.limits.allowed && (
        <div className="usage-limit-warning">{usage.limits.reason}</div>
      )}
    </div>
  );
}