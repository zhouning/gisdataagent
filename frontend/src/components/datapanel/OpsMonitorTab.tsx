/**
 * OpsMonitorTab — 运维监控（系统管理组）
 *
 * 对接后端：
 * - GET /api/user/token-usage — 当前用户 token 消耗
 * - GET /api/admin/metrics/summary — 聚合指标
 * - GET /api/analytics/latency — 延迟分布
 * - GET /api/analytics/tool-success — 工具成功率
 * - GET /api/analytics/token-efficiency — token 效率
 * - GET /api/analytics/throughput — 吞吐量
 * - GET /api/analytics/agent-breakdown — Agent 分解
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Activity, Loader2, AlertCircle, Zap, Clock,
  CheckCircle, BarChart3, Cpu, RefreshCw,
} from 'lucide-react';

interface TokenUsage {
  daily: Record<string, number>;
  monthly: Record<string, number>;
  limits: Record<string, any>;
  pipeline_breakdown: Record<string, number>;
}

interface MetricsSummary {
  audit_stats: Record<string, any>;
  user_count: number;
}

interface AnalyticsData {
  latency: any;
  toolSuccess: any;
  tokenEfficiency: any;
  throughput: any;
  agentBreakdown: any;
}

export default function OpsMonitorTab() {
  const [tokenUsage, setTokenUsage] = useState<TokenUsage | null>(null);
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [analytics, setAnalytics] = useState<Partial<AnalyticsData>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const results = await Promise.allSettled([
        fetch('/api/user/token-usage', { credentials: 'include' }),
        fetch('/api/admin/metrics/summary', { credentials: 'include' }),
        fetch('/api/analytics/latency', { credentials: 'include' }),
        fetch('/api/analytics/tool-success', { credentials: 'include' }),
        fetch('/api/analytics/token-efficiency', { credentials: 'include' }),
        fetch('/api/analytics/throughput', { credentials: 'include' }),
        fetch('/api/analytics/agent-breakdown', { credentials: 'include' }),
      ]);

      const json = async (r: PromiseSettledResult<Response>) =>
        r.status === 'fulfilled' && r.value.ok ? r.value.json() : null;

      const [tu, ms, lat, ts, te, tp, ab] = await Promise.all(results.map(json));
      if (tu) setTokenUsage(tu);
      if (ms) setMetrics(ms);
      setAnalytics({
        latency: lat,
        toolSuccess: ts,
        tokenEfficiency: te,
        throughput: tp,
        agentBreakdown: ab,
      });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  if (loading) {
    return <div className="tab-loading"><Loader2 size={20} className="spin" /> 加载中...</div>;
  }

  const dailyTotal = tokenUsage?.daily
    ? Object.values(tokenUsage.daily).reduce((a, b) => a + b, 0)
    : 0;
  const monthlyTotal = tokenUsage?.monthly
    ? Object.values(tokenUsage.monthly).reduce((a, b) => a + b, 0)
    : 0;
  const pipelineEntries = tokenUsage?.pipeline_breakdown
    ? Object.entries(tokenUsage.pipeline_breakdown).sort((a, b) => b[1] - a[1])
    : [];

  return (
    <div className="ops-monitor-tab">
      {error && <div className="tab-error"><AlertCircle size={14} /> {error}</div>}

      <div className="ops-monitor-tab__toolbar">
        <h4><Activity size={14} /> 运维监控</h4>
        <button className="btn-sm" onClick={loadAll}>
          <RefreshCw size={12} /> 刷新
        </button>
      </div>

      {/* Token usage cards */}
      <div className="ops-cards">
        <div className="stat-card">
          <Zap size={18} />
          <div className="stat-card__value">{dailyTotal.toLocaleString()}</div>
          <div className="stat-card__label">今日 Token</div>
        </div>
        <div className="stat-card">
          <Zap size={18} />
          <div className="stat-card__value">{monthlyTotal.toLocaleString()}</div>
          <div className="stat-card__label">本月 Token</div>
        </div>
        {metrics && (
          <div className="stat-card">
            <Cpu size={18} />
            <div className="stat-card__value">{metrics.user_count}</div>
            <div className="stat-card__label">注册用户</div>
          </div>
        )}
        {analytics.throughput?.requests_per_minute != null && (
          <div className="stat-card">
            <BarChart3 size={18} />
            <div className="stat-card__value">{analytics.throughput.requests_per_minute}</div>
            <div className="stat-card__label">请求/分钟</div>
          </div>
        )}
      </div>

      {/* Pipeline breakdown */}
      {pipelineEntries.length > 0 && (
        <div className="ops-section">
          <h5>Pipeline Token 分布</h5>
          <div className="pipeline-breakdown">
            {pipelineEntries.map(([name, count]) => (
              <div key={name} className="pipeline-row">
                <span className="pipeline-row__name">{name}</span>
                <div className="pipeline-row__bar">
                  <div
                    className="pipeline-row__fill"
                    style={{ width: `${Math.min(100, (count / pipelineEntries[0][1]) * 100)}%` }}
                  />
                </div>
                <span className="pipeline-row__count">{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Analytics summary */}
      <div className="ops-section">
        <h5>分析指标</h5>
        <div className="analytics-grid">
          {analytics.latency && (
            <div className="analytics-card">
              <Clock size={14} />
              <span>P50 延迟</span>
              <strong>{analytics.latency.p50_ms ?? analytics.latency.p50 ?? '-'} ms</strong>
            </div>
          )}
          {analytics.latency && (
            <div className="analytics-card">
              <Clock size={14} />
              <span>P95 延迟</span>
              <strong>{analytics.latency.p95_ms ?? analytics.latency.p95 ?? '-'} ms</strong>
            </div>
          )}
          {analytics.toolSuccess && (
            <div className="analytics-card">
              <CheckCircle size={14} />
              <span>工具成功率</span>
              <strong>
                {analytics.toolSuccess.success_rate != null
                  ? `${(analytics.toolSuccess.success_rate * 100).toFixed(1)}%`
                  : '-'}
              </strong>
            </div>
          )}
          {analytics.tokenEfficiency && (
            <div className="analytics-card">
              <Zap size={14} />
              <span>Token 效率</span>
              <strong>
                {analytics.tokenEfficiency.tokens_per_task ?? analytics.tokenEfficiency.efficiency ?? '-'}
              </strong>
            </div>
          )}
        </div>
      </div>

      {/* Agent breakdown */}
      {analytics.agentBreakdown?.agents && (
        <div className="ops-section">
          <h5>Agent 调用分布</h5>
          <div className="agent-breakdown">
            {(analytics.agentBreakdown.agents as any[]).map((a: any, i: number) => (
              <div key={i} className="agent-row">
                <span>{a.agent ?? a.name ?? `Agent ${i}`}</span>
                <span>{a.calls ?? a.count ?? 0} 次</span>
                <span>{a.avg_latency_ms ?? '-'} ms</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Audit stats */}
      {metrics?.audit_stats && Object.keys(metrics.audit_stats).length > 0 && (
        <div className="ops-section">
          <h5>审计统计 (30天)</h5>
          <div className="audit-stats">
            {Object.entries(metrics.audit_stats).map(([k, v]) => (
              <div key={k} className="audit-stat-row">
                <span>{k}</span>
                <strong>{typeof v === 'number' ? v.toLocaleString() : JSON.stringify(v)}</strong>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
