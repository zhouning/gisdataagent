import { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2, CircleStop, Clock3, Database, HardDrive,
  LoaderCircle, Play, RefreshCw, TriangleAlert, X,
} from 'lucide-react';

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

function statusLabel(status: IngestionRun['status']): string {
  return ({
    queued: '排队', running: '运行中', committing: '提交中', cancelling: '取消中', cancelled: '已取消',
    succeeded: '成功', failed: '失败',
  } as Record<string, string>)[status] || status;
}

export default function IngestionDialog({ source, onClose }: Props) {
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
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '无法读取 ingest 状态');
      setDefinitions(payload.definitions || []);
      setRuns(payload.runs || []);
      setError('');
    } catch (cause: any) {
      setError(cause.message || '无法读取 ingest 状态');
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  useEffect(() => { fetchState(); }, [source.id]);
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
        headers: { 'Content-Type': 'application/json' },
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
      if (!response.ok) throw new Error(payload.error || '创建 ingest 失败');
      await fetchState(true);
    } catch (cause: any) {
      setError(cause.message || '创建 ingest 失败');
    } finally {
      setSaving(false);
    }
  };

  const triggerRun = async (definitionId: number) => {
    setError('');
    try {
      const response = await fetch(`/api/ingestions/${definitionId}/runs`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '启动 ingest 失败');
      await fetchState(true);
    } catch (cause: any) {
      setError(cause.message || '启动 ingest 失败');
    }
  };

  const cancelRun = async (runId: string) => {
    try {
      const response = await fetch(`/api/ingestions/runs/${runId}/cancel`, {
        method: 'POST', credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '取消失败');
      await fetchState(true);
    } catch (cause: any) {
      setError(cause.message || '取消失败');
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
              Data ingest · {source.source_name}
            </strong>
          </div>
          <button onClick={onClose} title="关闭" aria-label="关闭" style={{
            width: 30, height: 30, display: 'grid', placeItems: 'center', color: '#9ca3af',
            background: 'transparent', border: 0, cursor: 'pointer',
          }}><X size={17} /></button>
        </div>

        <div style={{ padding: 14, display: 'grid', gap: 14 }}>
          <section style={{ display: 'grid', gap: 9 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#cbd5e1' }}>物化目标</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6 }}>
              {([
                ['lakehouse', '数据湖', HardDrive],
                ['postgis', 'PostGIS', Database],
                ['lakehouse_postgis', '湖层 + PostGIS', Database],
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
                数据资产名称
                <input value={targetName} onChange={event => {
                  setTargetName(event.target.value);
                  if (targetMode !== 'lakehouse') setTargetTable(safeTableName(event.target.value));
                }} style={inputStyle} />
              </label>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                PostGIS 表
                <input value={targetTable} disabled={targetMode === 'lakehouse'}
                  onChange={event => setTargetTable(event.target.value)} style={{
                    ...inputStyle, opacity: targetMode === 'lakehouse' ? .45 : 1,
                  }} />
              </label>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                周期策略
                <select value={schedulePolicy} onChange={event => setSchedulePolicy(event.target.value)} style={inputStyle}>
                  <option value="on_demand">按需</option>
                  <option value="interval:5m">每 5 分钟</option>
                  <option value="interval:30m">每 30 分钟</option>
                  <option value="interval:1h">每小时</option>
                </select>
              </label>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                最大记录数
                <input type="number" min="1" max="1000000" value={maxRecords}
                  onChange={event => setMaxRecords(event.target.value)} style={inputStyle} />
              </label>
              <label style={{ display: 'grid', gap: 4, fontSize: 11, color: '#9ca3af' }}>
                批大小
                <input type="number" min="1" max="5000" value={pageSize}
                  onChange={event => setPageSize(event.target.value)} style={inputStyle} />
              </label>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#cbd5e1' }}>
                <input type="checkbox" checked={runNow} onChange={event => setRunNow(event.target.checked)} />
                立即运行
              </label>
              <button onClick={saveAndRun} disabled={saving || !targetName.trim()} className="btn-primary btn-sm"
                style={{ display: 'flex', alignItems: 'center', gap: 6, minHeight: 32 }}>
                {saving ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}
                {runNow ? '保存并运行' : '保存定义'}
              </button>
            </div>
          </section>

          {error && <div style={{
            display: 'flex', gap: 7, alignItems: 'flex-start', color: '#fca5a5',
            background: '#2a1218', border: '1px solid #7f1d1d', padding: 8, borderRadius: 4, fontSize: 12,
          }}><TriangleAlert size={15} style={{ flex: '0 0 auto' }} />{error}</div>}

          <section style={{ display: 'grid', gap: 7 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#cbd5e1' }}>Ingest 定义</span>
              <button onClick={() => fetchState()} title="刷新" aria-label="刷新" style={{
                width: 28, height: 28, display: 'grid', placeItems: 'center', color: '#9ca3af',
                background: 'transparent', border: 0, cursor: 'pointer',
              }}><RefreshCw size={14} /></button>
            </div>
            {loading ? <div style={{ color: '#64748b', fontSize: 12 }}>加载中...</div> : definitions.length === 0 ? (
              <div style={{ color: '#64748b', fontSize: 12, padding: '8px 0' }}>暂无定义</div>
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
                    {definition.target_mode} · {definition.schedule_policy} · {definition.page_size.toLocaleString()}/批
                  </div>
                </div>
                <button onClick={() => triggerRun(definition.id)} title="运行" aria-label="运行"
                  disabled={hasActiveRun} style={{
                    width: 30, height: 30, display: 'grid', placeItems: 'center', borderRadius: 4,
                    color: '#93c5fd', background: '#172554', border: '1px solid #1e3a8a', cursor: 'pointer',
                    opacity: hasActiveRun ? .45 : 1,
                  }}><Play size={14} /></button>
              </div>
            ))}
          </section>

          <section style={{ display: 'grid', gap: 7 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#cbd5e1' }}>运行记录</div>
            {runs.length === 0 ? <div style={{ color: '#64748b', fontSize: 12 }}>暂无运行</div> : runs.map(run => {
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
                      <span style={{ color: statusColor(run.status), fontSize: 11 }}>{statusLabel(run.status)}</span>
                      <code style={{ color: '#64748b', fontSize: 10 }}>{run.run_id.slice(0, 8)}</code>
                    </div>
                    {cancellable && <button onClick={() => cancelRun(run.run_id)} title="取消" aria-label="取消" style={{
                      width: 28, height: 28, display: 'grid', placeItems: 'center', color: '#fca5a5',
                      background: 'transparent', border: 0, cursor: 'pointer',
                    }}><CircleStop size={14} /></button>}
                  </div>
                  {active && <div style={{ height: 4, background: '#1f2937', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${progress}%`, height: '100%', background: '#3b82f6', transition: 'width .2s' }} />
                  </div>}
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 10, color: '#64748b' }}>
                    <span>{run.records_read.toLocaleString()} / {run.records_total.toLocaleString()} 条</span>
                    <span>{run.batches_completed} / {run.batches_total} 批</span>
                    {run.asset_id && <span>资产 #{run.asset_id}</span>}
                    {run.postgis_table && <span>PostGIS: {run.postgis_table}</span>}
                    {run.created_at && <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                      <Clock3 size={10} />{new Date(run.created_at).toLocaleString()}
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
