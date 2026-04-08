/**
 * ProjectOverviewTab — 项目总览（系统管理组）
 *
 * 聚合 /api/quality-trends + /api/resource-overview 展示治理进度汇总
 */

import { useState, useEffect } from 'react';
import {
  BarChart3, TrendingUp, Server, AlertCircle, Loader2,
  CheckCircle, Clock, AlertTriangle,
} from 'lucide-react';

interface QualityTrend {
  date: string;
  pass_rate?: number;
  total_checks?: number;
  defect_count?: number;
}

interface ResourceOverview {
  total_datasets?: number;
  total_rules?: number;
  active_workflows?: number;
  storage_mb?: number;
}

export default function ProjectOverviewTab() {
  const [trends, setTrends] = useState<QualityTrend[]>([]);
  const [resources, setResources] = useState<ResourceOverview>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [tRes, rRes] = await Promise.allSettled([
          fetch('/api/quality-trends', { credentials: 'include' }),
          fetch('/api/resource-overview', { credentials: 'include' }),
        ]);
        if (tRes.status === 'fulfilled' && tRes.value.ok) {
          const data = await tRes.value.json();
          setTrends(data.trends ?? []);
        }
        if (rRes.status === 'fulfilled' && rRes.value.ok) {
          const data = await rRes.value.json();
          setResources(data);
        }
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return <div className="tab-loading"><Loader2 size={20} className="spin" /> 加载中...</div>;
  }

  return (
    <div className="overview-tab">
      {error && <div className="tab-error"><AlertCircle size={14} /> {error}</div>}

      <div className="overview-tab__cards">
        <div className="stat-card">
          <Server size={20} />
          <div className="stat-card__value">{resources.total_datasets ?? 0}</div>
          <div className="stat-card__label">数据集</div>
        </div>
        <div className="stat-card">
          <CheckCircle size={20} />
          <div className="stat-card__value">{resources.total_rules ?? 0}</div>
          <div className="stat-card__label">质量规则</div>
        </div>
        <div className="stat-card">
          <Clock size={20} />
          <div className="stat-card__value">{resources.active_workflows ?? 0}</div>
          <div className="stat-card__label">活跃工作流</div>
        </div>
        <div className="stat-card">
          <BarChart3 size={20} />
          <div className="stat-card__value">
            {resources.storage_mb != null ? `${resources.storage_mb} MB` : '-'}
          </div>
          <div className="stat-card__label">存储用量</div>
        </div>
      </div>

      <div className="overview-tab__trends">
        <h4><TrendingUp size={14} /> 质量趋势</h4>
        {trends.length === 0 ? (
          <div className="tab-empty">暂无趋势数据，执行质量检查后自动生成</div>
        ) : (
          <div className="trend-table">
            <div className="trend-table__header">
              <span>日期</span>
              <span>通过率</span>
              <span>检查数</span>
              <span>缺陷数</span>
            </div>
            {trends.slice(0, 20).map((t, i) => (
              <div key={i} className="trend-table__row">
                <span>{t.date}</span>
                <span className={
                  (t.pass_rate ?? 0) >= 90 ? 'good' :
                  (t.pass_rate ?? 0) >= 70 ? 'warn' : 'bad'
                }>
                  {t.pass_rate != null ? `${t.pass_rate.toFixed(1)}%` : '-'}
                </span>
                <span>{t.total_checks ?? '-'}</span>
                <span>
                  {(t.defect_count ?? 0) > 0 && <AlertTriangle size={12} />}
                  {t.defect_count ?? 0}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
