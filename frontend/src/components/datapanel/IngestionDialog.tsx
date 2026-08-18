import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle2, CircleStop, Clock3, Database, HardDrive,
  LoaderCircle, Play, RefreshCw, TriangleAlert, X,
} from 'lucide-react';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';

interface IngestionSource {
  id: number;
  source_name: string;
  refresh_policy: string;
}

interface IngestionDefinition {
  id: number;
  target_name: string;
  target_mode: 'lakehouse' | 'postgis' | 'lakehouse_postgis';
  target_table: string | null;
  schedule_policy: string;
  max_records: number;
  page_size: number;
  enabled: boolean;
}

interface IngestionRun {
  run_id: string;
  definition_id: number;
  status: 'queued' | 'running' | 'committing' | 'cancelling' | 'cancelled' | 'succeeded' | 'failed';
  trigger_type: string;
  records_total: number;
  records_read: number;
  records_written: number;
  batches_total: number;
  batches_completed: number;
  target_uri?: string | null;
  postgis_table?: string | null;
  asset_id?: number | null;
  error_message?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
}

interface Props {
  source: IngestionSource;
  onClose: () => void;
}

const inputStyle = {
  width: '100%', background: '#0d1117', color: '#e5e7eb',
  border: '1px solid #374151', borderRadius: 4, padding: '6px 8px',
  fontSize: 12, boxSizing: 'border-box' as const,
};

function safeTableName(value: string): string {
  let normalized = value.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
  if (!normalized || !/^[a-z]/.test(normalized)) normalized = `d_${normalized || 'arcgis_dataset'}`;
  return normalized.slice(0, 63);
}

function statusColor(status: IngestionRun['status']): string {
  if (status === 'succeeded') return '#34d399';
  if (status === 'failed' || status === 'cancelled') return '#f87171';
  if (status === 'running' || status === 'committing' || status === 'cancelling') return '#60a5fa';
  return '#fbbf24';
}

export default function IngestionDialog({ source, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const [definitions, setDefinitions] = useState<IngestionDefinition[]>([]);
  const [runs, setRuns] = useState<IngestionRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [targetName, setTargetName] = useState(`${source.source_name} ODS`);
  const [targetMode, setTargetMode] = useState<IngestionDefinition['target_mode']>('lakehouse_postgis');
  const [targetTable, setTargetTable] = useState(safeTableName(`${source.source_name}_ods`));
  const [schedulePolicy, setSchedulePolicy] = useState(
    ['on_demand', 'interval:5m', 'interval:30m', 'interval:1h'].includes(source.refresh_policy)
      ? source.refresh_policy : 'on_demand',
  );
  const [maxRecords, setMaxRecords] = useState('1000000');
  const [pageSize, setPageSize] = useState('2000');
  const [runNow, setRunNow] = useState(true);

  const hasActiveRun = useMemo(
    () => runs.some(run => ['queued', 'running', 'committing', 'cancelling'].includes(run.status)),
    [runs],
  );

  const fetchState = async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const response = await fetch(`/api/virtual-sources/${source.id}/ingestions`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || t('ingestionDialog.errors.load'));
      setDefinitions(payload.definitions || []);
      setRuns(payload.runs || []);
      setError('');
    } catch (cause: any) {
      setError(cause.message || t('ingestionDialog.errors.load'));
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  useEffect(() => { fetchState(); }, [source.id, i18n.resolvedLanguage]);
  useEffect(() => {
    if (!hasActiveRun) return undefined;
    const timer = window.setInterval(() => fetchState(true), 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveRun, source.id]);

  const saveAndRun = async () => {
    setSaving(true);
    setError('');
    try {
      const response = await fetch(`/api/virtual-sources/${source.id}/ingestions`, {
        method: 'POST', credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_name: targetName,
          target_mode: targetMode,
          target_table: targetMode === 'lakehouse' ? null : targetTable,
          schedule_policy: schedulePolicy,
          max_records: Number(maxRecords),
          page_size: Number(pageSize),
          run_now: runNow,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || t('ingestionDialog.errors.create'));
      await fetchState(true);
    } catch (cause: any) {
      setError(cause.message || t('ingestionDialog.errors.create'));
    } finally {
      setSaving(false);
    }
  };

  const triggerRun = async (definitionId: number) => {
    setError('');
    try {
      const response = await fetch(`/api/ingestions/${definitionId}/runs`, {
        method: 'POST', credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: '{}',
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || t('ingestionDialog.errors.start'));
      await fetchState(true);
    } catch (cause: any) {
      setError(cause.message || t('ingestionDialog.errors.start'));
    }
  };

  const cancelRun = async (runId: string) => {
    try {
      const response = await fetch(`/api/ingestions/runs/${runId}/cancel`, {
        method: 'POST', credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || t('ingestionDialog.errors.cancel'));
      await fetchState(true);
    } catch (cause: any) {
      setError(cause.message || t('ingestionDialog.errors.cancel'));
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1100, background: 'rgba(0,0,0,.68)',
      display: 'grid', placeItems: 'center', padding: 16,
    }} onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div style={{
        width: 'min(760px, 96vw)', maxHeight: '90vh', overflow: 'auto',
        background: '#111827', border: '1px solid #374151', borderRadius: 6,
        boxShadow: '0 20px 60px rgba(0,0,0,.45)', color: '#e5e7eb',
      }}>
        <div style={{
          height: 48, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 14px', borderBottom: '1px solid #273244', position: 'sticky', top: 0,
          background: '#111827', zIndex: 2,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <Database size={17} color="#60a5fa" />
            <strong style={{ fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {t('ingestionDialog.title')} · {source.source_name}
            </strong>
          </div>
          <button onClick={onClose} title={t('ingestionDialog.actions.close')} aria-label={t('ingestionDialog.actions.close')} style={{
            width: 30, height: 30, display: 'grid', placeItems: 'center', color: '#9ca3af',
            background: 'transparent', border: 0, cursor: 'pointer',
          }}><X size={17} /></button>
        </div>

        <div style={{ padding: 14, display: 'grid', gap: 14 }}>
          <section style={{ display: 'grid', gap: 9 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#cbd5e1' }}>{t('ingestionDialog.sections.target')}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6 }}>
              {([
                ['lakehouse', t('ingestionDialog.modes.lakehouse'), HardDrive],
                ['postgis', t('ingestionDialog.modes.postgis'), Database],
                ['lakehouse_postgis', t('ingestionDialog.modes.lakehousePostgis'), Database],
              ] as const).map(([mode, label, Icon]) => (
                <button key={mode} onClick={() => setTargetMode(mode)} style={{
                  minHeight: 36, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                  borderRadius: 4, border: `1px solid ${targetMode === mode ? '#3b82f6' : '#374151'}`,
                  background: targetMode === mode ? '#172554' : '#0d1117',
                  color: targetMode === mode ? '#bfdbfe' : '#9ca3af', cursor: 'pointer', fontSize: 12,
                }}><Icon size={14} />{label}</button>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 8 }}>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                {t('ingestionDialog.form.assetName')}
                <input value={targetName} onChange={event => {
                  setTargetName(event.target.value);
                  if (targetMode !== 'lakehouse') setTargetTable(safeTableName(event.target.value));
                }} style={inputStyle} />
              </label>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                {t('ingestionDialog.form.postgisTable')}
                <input value={targetTable} disabled={targetMode === 'lakehouse'}
                  onChange={event => setTargetTable(event.target.value)} style={{
                    ...inputStyle, opacity: targetMode === 'lakehouse' ? .45 : 1,
                  }} />
              </label>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                {t('ingestionDialog.form.schedule')}
                <select value={schedulePolicy} onChange={event => setSchedulePolicy(event.target.value)} style={inputStyle}>
                  <option value="on_demand">{t('ingestionDialog.schedules.onDemand')}</option>
                  <option value="interval:5m">{t('ingestionDialog.schedules.fiveMinutes')}</option>
                  <option value="interval:30m">{t('ingestionDialog.schedules.thirtyMinutes')}</option>
                  <option value="interval:1h">{t('ingestionDialog.schedules.hourly')}</option>
                </select>
              </label>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                {t('ingestionDialog.form.maxRecords')}
                <input type="number" min="1" max="1000000" value={maxRecords}
                  onChange={event => setMaxRecords(event.target.value)} style={inputStyle} />
              </label>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                {t('ingestionDialog.form.pageSize')}
                <input type="number" min="1" max="5000" value={pageSize}
                  onChange={event => setPageSize(event.target.value)} style={inputStyle} />
              </label>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#cbd5e1' }}>
                <input type="checkbox" checked={runNow} onChange={event => setRunNow(event.target.checked)} />
                {t('ingestionDialog.form.runNow')}
              </label>
              <button onClick={saveAndRun} disabled={saving || !targetName.trim()} className="btn-primary btn-sm"
                style={{ display: 'flex', alignItems: 'center', gap: 6, minHeight: 32 }}>
                {saving ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}
                {runNow ? t('ingestionDialog.actions.saveAndRun') : t('ingestionDialog.actions.save')}
              </button>
            </div>
          </section>

          {error && <div style={{
            display: 'flex', gap: 7, alignItems: 'flex-start', color: '#fca5a5',
            background: '#2a1218', border: '1px solid #7f1d1d', padding: 8, borderRadius: 4, fontSize: 12,
          }}><TriangleAlert size={15} style={{ flex: '0 0 auto' }} />{error}</div>}

          <section style={{ display: 'grid', gap: 7 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#cbd5e1' }}>{t('ingestionDialog.sections.definitions')}</span>
              <button onClick={() => fetchState()} title={t('ingestionDialog.actions.refresh')} aria-label={t('ingestionDialog.actions.refresh')} style={{
                width: 28, height: 28, display: 'grid', placeItems: 'center', color: '#9ca3af',
                background: 'transparent', border: 0, cursor: 'pointer',
              }}><RefreshCw size={14} /></button>
            </div>
            {loading ? <div style={{ color: '#64748b', fontSize: 12 }}>{t('ingestionDialog.common.loading')}</div> : definitions.length === 0 ? (
              <div style={{ color: '#64748b', fontSize: 12, padding: '8px 0' }}>{t('ingestionDialog.empty.definitions')}</div>
            ) : definitions.map(definition => (
              <div key={definition.id} style={{
                display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 8,
                alignItems: 'center', borderTop: '1px solid #273244', padding: '8px 0',
              }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: '#e5e7eb', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {definition.target_name}
                  </div>
                  <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>
                    {t(`ingestionDialog.modes.${definition.target_mode === 'lakehouse_postgis' ? 'lakehousePostgis' : definition.target_mode}`)} · {t(`ingestionDialog.scheduleValues.${definition.schedule_policy}`, { defaultValue: definition.schedule_policy })} · {t('ingestionDialog.counts.perBatch', { count: formatNumber(definition.page_size) })}
                  </div>
                </div>
                <button onClick={() => triggerRun(definition.id)} title={t('ingestionDialog.actions.run')} aria-label={t('ingestionDialog.actions.run')}
                  disabled={hasActiveRun} style={{
                    width: 30, height: 30, display: 'grid', placeItems: 'center', borderRadius: 4,
                    color: '#93c5fd', background: '#172554', border: '1px solid #1e3a8a', cursor: 'pointer',
                    opacity: hasActiveRun ? .45 : 1,
                  }}><Play size={14} /></button>
              </div>
            ))}
          </section>

          <section style={{ display: 'grid', gap: 7 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#cbd5e1' }}>{t('ingestionDialog.sections.runs')}</div>
            {runs.length === 0 ? <div style={{ color: '#64748b', fontSize: 12 }}>{t('ingestionDialog.empty.runs')}</div> : runs.map(run => {
              const progress = run.records_total > 0
                ? Math.min(100, Math.round(run.records_read * 100 / run.records_total)) : 0;
              const active = ['queued', 'running', 'committing', 'cancelling'].includes(run.status);
              const cancellable = ['queued', 'running', 'cancelling'].includes(run.status);
              return (
                <div key={run.run_id} style={{ borderTop: '1px solid #273244', padding: '9px 0', display: 'grid', gap: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: 7, alignItems: 'center', minWidth: 0 }}>
                      {run.status === 'succeeded' ? <CheckCircle2 size={14} color="#34d399" />
                        : active ? <LoaderCircle size={14} color="#60a5fa" className="spin" />
                          : <TriangleAlert size={14} color="#f87171" />}
                      <span style={{ color: statusColor(run.status), fontSize: 11 }}>{t(`ingestionDialog.status.${run.status}`, { defaultValue: run.status })}</span>
                      <code style={{ color: '#64748b', fontSize: 10 }}>{run.run_id.slice(0, 8)}</code>
                    </div>
                    {cancellable && <button onClick={() => cancelRun(run.run_id)} title={t('ingestionDialog.actions.cancel')} aria-label={t('ingestionDialog.actions.cancel')} style={{
                      width: 28, height: 28, display: 'grid', placeItems: 'center', color: '#fca5a5',
                      background: 'transparent', border: 0, cursor: 'pointer',
                    }}><CircleStop size={14} /></button>}
                  </div>
                  {active && <div style={{ height: 4, background: '#1f2937', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${progress}%`, height: '100%', background: '#3b82f6', transition: 'width .2s' }} />
                  </div>}
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 10, color: '#64748b' }}>
                    <span>{t('ingestionDialog.counts.records', { read: formatNumber(run.records_read), total: formatNumber(run.records_total) })}</span>
                    <span>{t('ingestionDialog.counts.batches', { completed: formatNumber(run.batches_completed), total: formatNumber(run.batches_total) })}</span>
                    {run.asset_id && <span>{t('ingestionDialog.counts.asset', { id: formatNumber(run.asset_id) })}</span>}
                    {run.postgis_table && <span>PostGIS: {run.postgis_table}</span>}
                    {run.created_at && <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                      <Clock3 size={10} />{formatDate(run.created_at, { dateStyle: 'medium', timeStyle: 'short', hour12: false })}
                    </span>}
                  </div>
                  {run.target_uri && <div title={run.target_uri} style={{
                    color: '#94a3b8', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{run.target_uri}</div>}
                  {run.error_message && <div style={{ color: '#fca5a5', fontSize: 10 }}>{run.error_message}</div>}
                </div>
              );
            })}
          </section>
        </div>
      </div>
    </div>
  );
}
