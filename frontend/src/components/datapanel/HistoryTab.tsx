import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';

interface PipelineRun {
  timestamp: string;
  pipeline_type: string;
  intent: string;
  input_tokens: number;
  output_tokens: number;
  files_generated: number;
}

export default function HistoryTab() {
  const { t, i18n } = useTranslation('common');
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/pipeline/history?days=${days}&limit=50`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (resp.ok) {
        const data = await resp.json();
        setRuns(data.runs || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchHistory(); }, [days, i18n.resolvedLanguage]);

  return (
    <div className="history-view">
      <div className="history-filter">
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            className={`history-range-btn ${days === d ? 'active' : ''}`}
            onClick={() => setDays(d)}
          >
            {t('assetWorkbench.history.days', { count: d })}
          </button>
        ))}
      </div>
      {loading && runs.length === 0 ? (
        <div className="empty-state">{t('assetWorkbench.common.loading')}</div>
      ) : runs.length === 0 ? (
        <div className="empty-state">{t('assetWorkbench.history.empty')}</div>
      ) : (
        <div className="history-timeline">
          {runs.map((run, i) => (
            <div key={i} className="history-item">
              <div className="history-item-header">
                <span className={`pipeline-badge ${run.pipeline_type}`}>
                  {t(`assetWorkbench.pipelineTypes.${run.pipeline_type}`, { defaultValue: run.pipeline_type })}
                </span>
                <span className="history-time">
                  {formatDate(run.timestamp, {
                    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
                  })}
                </span>
              </div>
              <div className="history-item-body">
                <span>{t('assetWorkbench.history.intent', { intent: run.intent })}</span>
                <span>{t('assetWorkbench.history.tokens', { count: formatNumber(run.input_tokens + run.output_tokens) })}</span>
                {run.files_generated > 0 && (
                  <span>{t('assetWorkbench.history.files', { count: formatNumber(run.files_generated) })}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
