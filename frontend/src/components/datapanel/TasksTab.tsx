import { useState, useEffect } from 'react';
import { formatTime } from './utils';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../../i18n';

export default function TasksTab() {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTasks();
    const hasRunning = jobs.some(j => j.status === 'running');
    const interval = setInterval(fetchTasks, hasRunning ? 3000 : 10000);
    return () => clearInterval(interval);
  }, [jobs.length]);

  const fetchTasks = async () => {
    try {
      const resp = await fetch('/api/tasks', { credentials: 'include', headers: getLocaleHeaders() });
      if (resp.ok) {
        const data = await resp.json();
        setJobs(data.jobs || []);
        setStats(data.stats || {});
      }
    } catch { /* ignore */ }
    setLoading(false);
  };

  const cancelTask = async (jobId: string) => {
    try {
      await fetch(`/api/tasks/${jobId}`, { method: 'DELETE', credentials: 'include', headers: getLocaleHeaders() });
      fetchTasks();
    } catch { /* ignore */ }
  };

  const statusColor: Record<string, string> = {
    queued: '#6b7280', running: '#0d9488', completed: '#22c55e', failed: '#ef4444', cancelled: '#eab308',
  };

  if (loading) return <div className="data-panel-empty">{t('tasks.loading')}</div>;

  return (
    <div className="data-panel-list">
      {stats.by_status && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          {Object.entries(stats.by_status).map(([status, count]: any) => (
            <span key={status} className="data-panel-badge" style={{ background: statusColor[status] || '#666' }}>
              {t(`tasks.status.${status}`, { defaultValue: status })}: {count}
            </span>
          ))}
          <span style={{ fontSize: 11, color: '#888' }}>{t('tasks.concurrentLimit')}: {stats.max_concurrent}</span>
        </div>
      )}
      {jobs.length === 0 && <div className="data-panel-empty">{t('tasks.empty')}</div>}
      {jobs.map((job: any) => (
        <div key={job.job_id} className="data-panel-card" style={{ marginBottom: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontFamily: 'monospace' }}>{job.job_id}</span>
            <span className="data-panel-badge" style={{ background: statusColor[job.status] || '#666' }}>
              {t(`tasks.status.${job.status}`, { defaultValue: job.status })}{job.status === 'running' ? ' ⏳' : ''}
            </span>
          </div>
          <div style={{ fontSize: 12, color: '#ccc', margin: '4px 0' }}>{job.prompt}</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#888' }}>
            <span>{job.pipeline_type}</span>
            <span>{job.duration > 0 ? `${job.duration}s` : ''}</span>
          </div>
          {(job.status === 'queued' || job.status === 'running') && (
            <button className="data-panel-btn-sm secondary" style={{ marginTop: 4 }} onClick={() => cancelTask(job.job_id)}>{t('tasks.cancel')}</button>
          )}
          {job.error_message && <div style={{ fontSize: 11, color: '#ef4444', marginTop: 4 }}>{job.error_message}</div>}
        </div>
      ))}
    </div>
  );
}
