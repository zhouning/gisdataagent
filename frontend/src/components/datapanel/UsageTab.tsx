import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

interface UsageData {
  daily: { count: number; tokens: number };
  monthly: { count: number; total_tokens: number; input_tokens: number; output_tokens: number };
  limits: { allowed: boolean; reason: string; daily_count: number; daily_limit: number };
  pipeline_breakdown: { pipeline_type: string; count: number; tokens: number }[];
}

export default function UsageTab() {
  const { t, i18n } = useTranslation('common');
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchUsage = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/user/token-usage', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (resp.ok) setUsage(await resp.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchUsage();
    const interval = setInterval(fetchUsage, 30000);
    return () => clearInterval(interval);
  }, [i18n.resolvedLanguage]);

  if (loading && !usage) return <div className="empty-state">{t('assetWorkbench.common.loading')}</div>;
  if (!usage) return <div className="empty-state">{t('assetWorkbench.usage.unavailable')}</div>;

  const dailyPct = usage.limits.daily_limit > 0
    ? Math.min(100, Math.round((usage.limits.daily_count / usage.limits.daily_limit) * 100))
    : 0;

  const maxTokens = usage.pipeline_breakdown.length > 0
    ? Math.max(...usage.pipeline_breakdown.map((b) => b.tokens))
    : 1;

  return (
    <div className="usage-view">
      <div className="usage-card">
        <div className="usage-card-title">{t('assetWorkbench.usage.today')}</div>
        <div className="usage-card-value">
          {formatNumber(usage.limits.daily_count)} / {formatNumber(usage.limits.daily_limit)}
        </div>
        <div className="usage-progress">
          <div
            className={`usage-progress-fill ${dailyPct >= 90 ? 'warning' : ''}`}
            style={{ width: `${dailyPct}%` }}
          />
        </div>
        <div className="usage-card-sub">{t('assetWorkbench.usage.tokenCount', { count: formatNumber(usage.daily.tokens) })}</div>
      </div>

      <div className="usage-card">
        <div className="usage-card-title">{t('assetWorkbench.usage.monthlySummary')}</div>
        <div className="usage-card-value">{formatNumber(usage.monthly.total_tokens)}</div>
        <div className="usage-card-sub">{t('assetWorkbench.usage.tokens')}</div>
        <div className="usage-detail-row">
          <span>{t('assetWorkbench.usage.input')}</span><span>{formatNumber(usage.monthly.input_tokens)}</span>
        </div>
        <div className="usage-detail-row">
          <span>{t('assetWorkbench.usage.output')}</span><span>{formatNumber(usage.monthly.output_tokens)}</span>
        </div>
        <div className="usage-detail-row">
          <span>{t('assetWorkbench.usage.analysisCount')}</span><span>{formatNumber(usage.monthly.count)}</span>
        </div>
      </div>

      {usage.pipeline_breakdown.length > 0 && (
        <div className="usage-card">
          <div className="usage-card-title">{t('assetWorkbench.usage.pipelineBreakdown')}</div>
          {usage.pipeline_breakdown.map((b) => (
            <div key={b.pipeline_type} className="usage-breakdown-row">
              <div className="usage-breakdown-label">
                <span className={`pipeline-badge ${b.pipeline_type}`}>
                  {t(`assetWorkbench.pipelineTypes.${b.pipeline_type}`, { defaultValue: b.pipeline_type })}
                </span>
                <span className="usage-breakdown-count">
                  {t('assetWorkbench.usage.runCount', { count: formatNumber(b.count) })}
                </span>
              </div>
              <div className="usage-progress">
                <div
                  className="usage-progress-fill"
                  style={{ width: `${Math.round((b.tokens / maxTokens) * 100)}%` }}
                />
              </div>
              <div className="usage-breakdown-tokens">{formatNumber(b.tokens)}</div>
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
