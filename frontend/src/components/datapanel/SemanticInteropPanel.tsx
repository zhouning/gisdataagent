import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Download, FileUp, RefreshCw, ShieldAlert } from 'lucide-react';

type InteropKind = 'ontology' | 'semantic-layer';
type InteropFormat = 'turtle' | 'json-ld' | 'ossie-yaml' | 'yaml' | 'json';

interface StageRecord {
  stage_id?: string;
  kind?: string;
  source?: string | null;
  format?: string;
  mode?: string;
  status?: string;
  execution_authority?: boolean;
  received_sha256?: string;
  summary?: Record<string, number>;
  created_at?: string;
}

interface Props {
  userRole?: string;
  defaultKind?: InteropKind;
  defaultSource?: string;
  compact?: boolean;
}

interface InteropSource {
  key: string;
  label: string;
  source_id?: number | string;
  database_name?: string;
  bundle_id?: string;
}

const formatLabels: Record<InteropFormat, string> = {
  turtle: 'RDF Turtle',
  'json-ld': 'JSON-LD',
  'ossie-yaml': 'Apache Ossie YAML',
  yaml: 'GDA YAML',
  json: 'GDA JSON',
};

const formatsFor = (kind: InteropKind): InteropFormat[] => kind === 'ontology'
  ? ['turtle', 'json-ld', 'json']
  : ['ossie-yaml', 'turtle', 'json-ld', 'yaml', 'json'];

function formatSummary(summary?: Record<string, number>) {
  if (!summary) return '';
  return Object.entries(summary).map(([key, value]) => `${key.replace(/_count$/, '')} ${value}`).join(' · ');
}

export default function SemanticInteropPanel({ userRole = '', defaultKind = 'semantic-layer', defaultSource = '', compact = false }: Props) {
  const [sources, setSources] = useState<InteropSource[]>([]);
  const [source, setSource] = useState(defaultSource === 'liveability' || defaultSource === 'makani' ? defaultSource : '');
  const [kind, setKind] = useState<InteropKind>(defaultKind);
  const canImport = kind === 'ontology'
    ? ['admin', 'standard_editor'].includes(userRole)
    : ['admin', 'analyst'].includes(userRole);
  const [exportFormat, setExportFormat] = useState<InteropFormat>(formatsFor(defaultKind)[0]);
  const [importFormat, setImportFormat] = useState<InteropFormat>(formatsFor(defaultKind)[0]);
  const [mode, setMode] = useState<'projection-only' | 'strict' | 'lossless-extension'>('projection-only');
  const [stages, setStages] = useState<StageRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const availableFormats = useMemo(() => formatsFor(kind), [kind]);

  useEffect(() => {
    const formats = formatsFor(kind);
    if (!formats.includes(exportFormat)) setExportFormat(formats[0]);
    if (!formats.includes(importFormat)) setImportFormat(formats[0]);
  }, [kind, exportFormat, importFormat]);

  useEffect(() => {
    if (!defaultSource) return;
    const match = sources.find(item => (
      item.key === defaultSource
      || item.database_name === defaultSource
      || (item.source_id !== undefined && `source:${item.source_id}` === defaultSource)
    ));
    if (match) setSource(match.key);
  }, [defaultSource, sources]);

  async function refreshStages() {
    try {
      const response = await fetch('/api/semantic/interop/imports', { credentials: 'include' });
      if (!response.ok) return;
      const payload = await response.json();
      setStages(payload.items || []);
    } catch {
      // The panel remains usable when the optional staging history is offline.
    }
  }

  async function refreshSources() {
    try {
      const response = await fetch('/api/semantic/interop/sources', { credentials: 'include' });
      if (!response.ok) return;
      const payload = await response.json();
      const items = Array.isArray(payload.items) ? payload.items : [];
      setSources(items);
      const defaultMatch = items.find((item: InteropSource) => (
        item.key === defaultSource
        || item.database_name === defaultSource
        || (item.source_id !== undefined && `source:${item.source_id}` === defaultSource)
      ));
      if (defaultMatch) {
        setSource(defaultMatch.key);
      } else if (items.length > 0 && !items.some((item: InteropSource) => item.key === source)) {
        setSource(items[0].key);
      }
    } catch {
      // The source catalog is optional during isolated frontend development.
    }
  }

  useEffect(() => { void refreshSources(); void refreshStages(); }, []);

  async function downloadExport() {
    if (!source) { setError('当前没有可用的已发布数据源'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const path = `/api/semantic/interop/export/${kind}/${source}/${exportFormat}`;
      const response = await fetch(path, { credentials: 'include' });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || `导出失败（${response.status}）`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${source}-${kind}.${exportFormat === 'ossie-yaml' ? 'ossie.yaml' : exportFormat === 'json-ld' ? 'jsonld' : exportFormat}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setMessage(`已导出 ${sources.find(item => item.key === source)?.label || source} · ${formatLabels[exportFormat]}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '导出失败');
    } finally {
      setBusy(false);
    }
  }

  async function importFile(file: File) {
    if (!source) { setError('当前没有可用的已发布数据源'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('source', source);
      form.append('kind', kind);
      form.append('format', importFormat);
      form.append('mode', mode);
      const response = await fetch('/api/semantic/interop/import', { method: 'POST', credentials: 'include', body: form });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `导入失败（${response.status}）`);
      const stage = payload.stage || {};
      setMessage(`已登记不可执行导入草稿 ${stage.stage_id || ''} · ${formatSummary(stage.summary)}`);
      await refreshStages();
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入失败');
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  return <section className={`semantic-interop-panel${compact ? ' compact' : ''}`}>
    <div className="semantic-interop-heading">
      <div><span className="semantic-workspace-kicker">STANDARDS INTERCHANGE</span><h4>标准互操作</h4><span>本体和语义层按标准格式交换；外部导入进入待审核草稿。</span></div>
      <span className="semantic-interop-authority"><ShieldAlert size={13} />执行权威仍为 GDA</span>
    </div>
    <div className="semantic-interop-controls">
      <label>数据源<select value={source} onChange={event => setSource(event.target.value)} disabled={!sources.length}><option value="">暂无可用数据源</option>{sources.map(item => <option key={item.key} value={item.key}>{item.label} · {item.database_name || item.key}</option>)}</select></label>
      <label>对象<select value={kind} onChange={event => setKind(event.target.value as InteropKind)}><option value="semantic-layer">语义层</option><option value="ontology">本体模型</option></select></label>
      <label>导出格式<select value={exportFormat} onChange={event => setExportFormat(event.target.value as InteropFormat)}>{availableFormats.map(item => <option key={item} value={item}>{formatLabels[item]}</option>)}</select></label>
      <button type="button" className="btn-secondary" disabled={busy} onClick={() => void downloadExport()}><Download size={14} />导出</button>
      {canImport && <>
        <label>导入格式<select value={importFormat} onChange={event => setImportFormat(event.target.value as InteropFormat)}>{availableFormats.map(item => <option key={item} value={item}>{formatLabels[item]}</option>)}</select></label>
        <label>导入模式<select value={mode} onChange={event => setMode(event.target.value as typeof mode)}><option value="projection-only">投影草稿（不可执行）</option><option value="strict">严格回读</option><option value="lossless-extension">带扩展回读</option></select></label>
        <button type="button" className="btn-secondary" disabled={busy} onClick={() => fileRef.current?.click()}><FileUp size={14} />导入文件</button>
        <input ref={fileRef} type="file" hidden accept={importFormat === 'ossie-yaml' || importFormat === 'yaml' ? '.yaml,.yml' : importFormat === 'turtle' ? '.ttl,.turtle' : importFormat === 'json-ld' ? '.jsonld,.json' : '.json'} onChange={event => { const file = event.target.files?.[0]; if (file) void importFile(file); }} />
      </>}
      <button type="button" className="btn-mini" title="刷新导入草稿" disabled={busy} onClick={() => void refreshStages()}><RefreshCw size={13} /></button>
    </div>
    {error && <div className="semantic-alert error">{error}</div>}
    {message && <div className="semantic-alert info"><CheckCircle2 size={13} />{message}</div>}
    {stages.length > 0 && <div className="semantic-interop-stages"><strong>最近导入草稿</strong>{stages.slice(0, 4).map(stage => <div key={stage.stage_id}><span>{stage.stage_id}</span><span>{stage.source || '未指定数据源'} · {stage.kind === 'ontology' ? '本体' : '语义层'} · {formatLabels[stage.format as InteropFormat] || stage.format}</span><em>{stage.status === 'staged_non_executable' ? '不可执行待审核' : stage.status}</em></div>)}</div>}
  </section>;
}
