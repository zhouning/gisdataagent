import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Activity, CheckCircle2, ChevronLeft, ChevronRight, Database, Download, Eye, FileSearch, ListFilter, Pencil, Play, Plus, RefreshCw, Save, Search, ShieldCheck, Trash2, Upload, XCircle } from 'lucide-react';

type Scope = 'liveability' | 'makani' | 'federated';

interface ProductEvidence {
  product: Record<string, any>;
  sources: Array<Record<string, any>>;
  federated: Record<string, any>;
  benchmark_v2?: Record<string, any>;
  benchmark_v3?: Record<string, any>;
  benchmark_evaluation?: Record<string, any>;
}

interface QueryResult {
  scope: Scope;
  status: string;
  reason?: string;
  error?: string;
  planner?: Record<string, any>;
  source?: Record<string, any>;
  query?: Record<string, any>;
  result?: Record<string, any>;
  timing?: { total_ms?: number; database_ms?: number };
  semantic_plan?: Record<string, any> | null;
  source_rows_persisted?: boolean;
  admission?: {
    decision?: string;
    runtime_admitted?: boolean;
    status?: string;
    required_capabilities?: string[];
    reviewed_candidate_capabilities?: string[];
  };
}

interface CandidateResolution {
  scope: Exclude<Scope, 'federated'>;
  source: Record<string, any>;
  catalog: Record<string, any>;
  resolution: Record<string, any>;
}

interface SemanticConfigurationResponse {
  schema: string;
  scope: string;
  source: Record<string, any>;
  section: string;
  offset: number;
  limit: number;
  search: string;
  total: number;
  has_more: boolean;
  items?: Array<Record<string, any>>;
  configuration?: Record<string, any>;
  collection_counts?: Record<string, number>;
  available_sections?: string[];
  downloadable?: boolean;
  execution_authority: boolean;
  gold_artifacts_runtime_accessible: boolean;
  source_rows_persisted: boolean;
}

const SOURCE_LABELS: Record<Scope, string> = {
  liveability: 'Liveability',
  makani: 'Makani',
  federated: 'Federated',
};

const SEMANTIC_CONFIGURATION_LABELS: Record<string, string> = {
  summary: '总览与版本',
  source_binding: '数据源绑定',
  activation_gate: '激活门禁',
  query_policy: '查询策略',
  response_language_policy: '响应语言策略',
  ontology_overlay: '本体映射',
  technical_catalog: '元数据发现目录',
  dictionary_semantic_publication: '字典语义发布',
  semantic_candidate_catalog: '语义候选目录',
  relationship_candidate_catalog: '关系候选目录',
  business_semantic_rules: '业务语义规则',
  semantic_caveats: '语义注意事项',
  table_bindings: '表与字段绑定',
  semantic_assets: '业务资产',
  relationships: '审核关系',
  metric_contracts: '指标合同',
};

const EXAMPLES: Record<Scope, string> = {
  liveability: '按生命周期阶段和设施类型统计宜居设施数量。',
  makani: '按建成状态统计建筑数量。',
  federated: '请分别汇总宜居设施在各建设阶段和设施类别的数量，同时汇总配电变电站在各运行状态和设备类别的数量。',
};

function fmt(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value);
}

function pct(value: unknown): string {
  return typeof value === 'number' ? `${Math.round(value * 1000) / 10}%` : '-';
}

function milliseconds(value: unknown): string {
  return typeof value === 'number' ? `${Math.round(value * 1000) / 1000} ms` : '-';
}

function signed(value: unknown): string {
  if (typeof value !== 'number') return '-';
  return value > 0 ? `+${value}` : String(value);
}

function Metric({ label, value, tone = '' }: { label: string; value: unknown; tone?: string }) {
  return <div className="abu-metric"><span>{label}</span><strong className={tone}>{fmt(value)}</strong></div>;
}

function Status({ ok, children }: { ok: boolean; children: ReactNode }) {
  return <span className={`abu-status ${ok ? 'ok' : 'warn'}`}>{ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}{children}</span>;
}

function JsonDetails({ title, value }: { title: string; value: unknown }) {
  return <details className="abu-details"><summary><Eye size={13} />{title}</summary><pre>{JSON.stringify(value ?? {}, null, 2)}</pre></details>;
}

function configurationItemLabel(item: Record<string, any>, index: number): string {
  return String(
    item.physical_table
      || item.asset_id
      || item.contract_id
      || item.relation_id
      || item.left
      || item.rule_id
      || `配置项 ${index + 1}`,
  );
}

function SemanticConfigurationInspector({ source }: { source: Record<string, any> }) {
  const [section, setSection] = useState('summary');
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [configuration, setConfiguration] = useState<SemanticConfigurationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = async (nextSection = section, nextOffset = offset, nextSearch = search) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        scope: String(source.key),
        section: nextSection,
        offset: String(nextOffset),
        limit: '25',
        include_candidates: 'true',
      });
      if (nextSearch.trim()) params.set('search', nextSearch.trim());
      const response = await fetch(`/api/abu-dhabi/nl2semantic2sql/semantic-configuration?${params.toString()}`, { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '语义配置加载失败');
      setConfiguration(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : '语义配置加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setSection('summary');
    setOffset(0);
    setSearch('');
    void load('summary', 0, '');
    // The source key is the read-model scope; load is intentionally local to this inspector.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.key]);

  const changeSection = (nextSection: string) => {
    setSection(nextSection);
    setOffset(0);
    void load(nextSection, 0, search);
  };

  const changePage = (nextOffset: number) => {
    setOffset(nextOffset);
    void load(section, nextOffset, search);
  };

  const download = async () => {
    setError('');
    try {
      const params = new URLSearchParams({ scope: String(source.key), section: 'all', offset: '0', limit: '1', include_candidates: 'true' });
      const response = await fetch(`/api/abu-dhabi/nl2semantic2sql/semantic-configuration?${params.toString()}`, { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '完整语义配置下载失败');
      const blob = new Blob([JSON.stringify(payload.configuration ?? {}, null, 2)], { type: 'application/json;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `semantic_configuration_${String(source.key)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : '完整语义配置下载失败');
    }
  };

  const items = configuration?.items || [];
  const summary = configuration?.configuration || {};
  const counts = configuration?.collection_counts || {};
  return <div className="abu-semantic-config-inspector">
    <div className="abu-config-heading"><div><span className="abu-kicker">FULL CONFIGURATION READ MODEL</span><h4>完整语义配置检查器</h4></div><button className="btn-secondary btn-sm" onClick={() => void download()} disabled={loading}><Download size={13} />下载完整 JSON</button></div>
    <p className="abu-card-note"><ShieldCheck size={14} />可查看所有已发布表绑定、字段、资产、关系、指标合同和门禁配置；这是只读审查视图，不授予 SQL 执行权限，也不包含 Benchmark Gold 或业务源数据行。</p>
    <div className="abu-config-toolbar">
      <select value={section} onChange={event => changeSection(event.target.value)} aria-label="语义配置分段">
        {Object.entries(SEMANTIC_CONFIGURATION_LABELS).map(([key, label]) => <option key={key} value={key}>{label}{counts[key] !== undefined ? ` (${counts[key]})` : ''}</option>)}
      </select>
      <div className="abu-config-search"><Search size={13} /><input value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { setOffset(0); void load(section, 0, search); } }} placeholder="筛选当前配置分段" /><button className="btn-secondary btn-sm" onClick={() => { setOffset(0); void load(section, 0, search); }} disabled={loading}><RefreshCw size={13} />刷新</button></div>
    </div>
    {error && <div className="abu-inline-error">{error}</div>}
    {loading && <div className="abu-loading"><Activity size={14} />正在加载配置...</div>}
    {!loading && section === 'summary' && <JsonDetails title="版本、绑定、门禁、策略和规则" value={summary} />}
    {!loading && section !== 'summary' && configuration?.configuration && <JsonDetails title="配置详情" value={configuration.configuration} />}
    {!loading && section !== 'summary' && !configuration?.configuration && <div className="abu-config-items">{items.map((item, index) => <details className="abu-details" key={`${section}-${configuration?.offset || 0}-${index}`}><summary><Eye size={13} />{configurationItemLabel(item, (configuration?.offset || 0) + index)}</summary><pre>{JSON.stringify(item, null, 2)}</pre></details>)}</div>}
    {!loading && section !== 'summary' && configuration && !configuration.items?.length && <div className="abu-empty">当前分段没有匹配的配置项。</div>}
    {configuration && section !== 'summary' && !configuration.configuration && <div className="abu-config-pagination"><span>{configuration.total ? `${configuration.offset + 1}-${Math.min(configuration.offset + (configuration.items?.length ?? 0), configuration.total)} / ${configuration.total}` : '0 项'}</span><button className="btn-secondary btn-sm" onClick={() => changePage(Math.max(0, configuration.offset - configuration.limit))} disabled={configuration.offset === 0 || loading}><ChevronLeft size={13} />上一页</button><button className="btn-secondary btn-sm" onClick={() => changePage(configuration.offset + configuration.limit)} disabled={!configuration.has_more || loading}>下一页<ChevronRight size={13} /></button></div>}
  </div>;
}

function resourceStatusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    technical_metadata_only: '仅有元数据，待业务语义审核',
    active_governed_table_local_v3: '已发布表内查询语义',
    reviewed_dictionary_supported_v1: '已发布字典支持语义',
    excluded_sensitive_or_operational: '已排除：敏感或运维资源',
    excluded_non_authoritative_operational: '已排除：非权威运维资源',
    excluded_system_metadata: '已排除：系统元数据',
  };
  return labels[String(value || '')] || fmt(value);
}

function ResourceInventory({ source }: { source: Record<string, any> }) {
  const [filter, setFilter] = useState('');
  const resources = (source.technical_catalog?.resources || []) as Array<Record<string, any>>;
  const normalized = filter.trim().toLocaleLowerCase();
  const visible = normalized
    ? resources.filter(item => String(item.physical_table || '').toLocaleLowerCase().includes(normalized) || String(item.semantic_status || '').toLocaleLowerCase().includes(normalized))
    : resources;
  return <details className="abu-details abu-resource-details">
    <summary><ListFilter size={13} />完整资源目录（{resources.length}）</summary>
    <div className="abu-inventory-toolbar"><Search size={13} /><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="筛选表名或状态" /><span>{visible.length}/{resources.length}</span></div>
    <div className="abu-resource-table-wrap"><table className="abu-result-table"><thead><tr><th>资源</th><th>业务语义状态</th><th>字段</th><th>空间</th><th>PK/FK</th><th>字典</th></tr></thead><tbody>{visible.map(item => <tr key={String(item.physical_table)}><td>{fmt(item.physical_table)}</td><td>{resourceStatusLabel(item.semantic_status)}</td><td>{fmt(item.field_count)}</td><td>{item.spatial ? '是' : '否'}</td><td>{fmt(`${item.primary_key_count || 0}/${item.foreign_key_count || 0}`)}</td><td>{fmt(item.dictionary_status)}</td></tr>)}</tbody></table></div>
  </details>;
}

type AdminEntryType = 'assets' | 'fields' | 'relationships' | 'metric_contracts';

const ADMIN_ENTRY_LABELS: Record<AdminEntryType, string> = {
  assets: '业务资产',
  fields: '语义字段',
  relationships: '审核关系',
  metric_contracts: '指标合同',
};

interface AdminEntryResponse {
  id: string;
  entry_type: AdminEntryType;
  payload: Record<string, any>;
  state: string;
  source: string;
  version_id?: number;
  execution_eligible?: boolean;
}

function AdminField({ label, value, onChange, disabled = false }: { label: string; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  return <label className="abu-admin-field"><span>{label}</span><input value={value} disabled={disabled} onChange={event => onChange(event.target.value)} /></label>;
}

function AdminPayloadForm({ type, payload, onChange }: { type: AdminEntryType; payload: Record<string, any>; onChange: (next: Record<string, any>) => void }) {
  const set = (key: string, value: any) => onChange({ ...payload, [key]: value });
  const label = (key: string) => String((payload.labels || {})[key] || '');
  const setLabel = (key: string, value: string) => onChange({ ...payload, labels: { ...(payload.labels || {}), [key]: value } });
  if (type === 'assets') return <div className="abu-admin-form-grid">
    <AdminField label="资产 ID" value={String(payload.asset_id || '')} onChange={value => set('asset_id', value)} />
    <AdminField label="物理表（逗号分隔）" value={(payload.physical_tables || []).join(', ')} onChange={value => set('physical_tables', value.split(',').map(item => item.trim()).filter(Boolean))} />
    <AdminField label="中文名称" value={label('zh')} onChange={value => setLabel('zh', value)} />
    <AdminField label="英文名称" value={label('en')} onChange={value => setLabel('en', value)} />
    <AdminField label="粒度" value={String(payload.grain || '')} onChange={value => set('grain', value)} />
    <AdminField label="审核状态" value={String(payload.review_status || '')} onChange={value => set('review_status', value)} />
    <label className="abu-admin-field abu-admin-wide"><span>描述</span><textarea value={String(payload.description || '')} onChange={event => set('description', event.target.value)} rows={2} /></label>
  </div>;
  if (type === 'fields') return <div className="abu-admin-form-grid">
    <AdminField label="所属资产 ID" value={String(payload.asset_id || '')} onChange={value => set('asset_id', value)} />
    <AdminField label="语义字段" value={String(payload.semantic_field || '')} onChange={value => set('semantic_field', value)} />
    <AdminField label="物理字段" value={String(payload.physical_field || '')} onChange={value => set('physical_field', value)} />
    <AdminField label="业务角色" value={String(payload.business_role || '')} onChange={value => set('business_role', value)} />
    <AdminField label="中文名称" value={label('zh')} onChange={value => setLabel('zh', value)} />
    <AdminField label="英文名称" value={label('en')} onChange={value => setLabel('en', value)} />
    <AdminField label="单位" value={String(payload.unit || '')} onChange={value => set('unit', value)} />
    <label className="abu-admin-field abu-admin-wide"><span>描述</span><textarea value={String(payload.description || '')} onChange={event => set('description', event.target.value)} rows={2} /></label>
  </div>;
  if (type === 'relationships') return <div className="abu-admin-form-grid">
    <AdminField label="左端（schema.table.field）" value={String(payload.left || '')} onChange={value => set('left', value)} />
    <AdminField label="右端（schema.table.field）" value={String(payload.right || '')} onChange={value => set('right', value)} />
    <AdminField label="关系类型" value={String(payload.kind || 'equality')} onChange={value => set('kind', value)} />
    <AdminField label="基数" value={String(payload.cardinality || '')} onChange={value => set('cardinality', value)} />
    <AdminField label="审核状态" value={String(payload.review_status || '')} onChange={value => set('review_status', value)} />
    <AdminField label="空间谓词（可选）" value={String(payload.spatial_predicate || '')} onChange={value => set('spatial_predicate', value)} />
  </div>;
  return <div className="abu-admin-form-grid">
    <AdminField label="合同 ID" value={String(payload.contract_id || '')} onChange={value => set('contract_id', value)} />
    <AdminField label="操作" value={String(payload.operation || '')} onChange={value => set('operation', value)} />
    <AdminField label="涉及表（逗号分隔）" value={(payload.tables || []).join(', ')} onChange={value => set('tables', value.split(',').map(item => item.trim()).filter(Boolean))} />
    <AdminField label="审核状态" value={String(payload.review_status || '')} onChange={value => set('review_status', value)} />
    <label className="abu-admin-field abu-admin-wide"><span>规范 SQL 模板（审核辅助）</span><textarea value={String(payload.canonical_sql_template || '')} onChange={event => set('canonical_sql_template', event.target.value)} rows={3} /></label>
  </div>;
}

export function SemanticAdminPanel({ defaultScope }: { defaultScope: Exclude<Scope, 'federated'> }) {
  const [scope, setScope] = useState<Exclude<Scope, 'federated'>>(defaultScope);
  const [type, setType] = useState<AdminEntryType>('assets');
  const [items, setItems] = useState<AdminEntryResponse[]>([]);
  const [versions, setVersions] = useState<Array<Record<string, any>>>([]);
  const [editing, setEditing] = useState<AdminEntryResponse | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const load = async () => {
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ scope, offset: '0', limit: '50' });
      if (search.trim()) params.set('search', search.trim());
      const response = await fetch(`/api/abu-dhabi/nl2semantic2sql/semantic-admin/${type}?${params.toString()}`, { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '语义配置加载失败');
      setItems(payload.items || []); setVersions(payload.versions || []);
    } catch (err) { setError(err instanceof Error ? err.message : '语义配置加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [scope, type]);
  const save = async () => {
    if (!editing) return;
    setLoading(true); setError('');
    try {
      const isNew = editing.id === 'new';
      const url = isNew ? `/api/abu-dhabi/nl2semantic2sql/semantic-admin/${type}?scope=${scope}` : `/api/abu-dhabi/nl2semantic2sql/semantic-admin/${type}/${encodeURIComponent(editing.id)}?scope=${scope}`;
      const response = await fetch(url, { method: isNew ? 'POST' : 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ payload: editing.payload }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '语义配置保存失败');
      setEditing(null); await load();
    } catch (err) { setError(err instanceof Error ? err.message : '语义配置保存失败'); }
    finally { setLoading(false); }
  };
  const remove = async (item: AdminEntryResponse) => {
    if (!window.confirm('删除会写入当前草稿墓碑，不会修改历史发布版本。继续？')) return;
    setLoading(true); setError('');
    try {
      const response = await fetch(`/api/abu-dhabi/nl2semantic2sql/semantic-admin/${type}/${encodeURIComponent(item.id)}?scope=${scope}`, { method: 'DELETE', credentials: 'include' });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.error || '删除失败'); await load();
    } catch (err) { setError(err instanceof Error ? err.message : '删除失败'); }
    finally { setLoading(false); }
  };
  const action = async (versionId: number, operation: 'validate' | 'publish') => {
    setLoading(true); setError('');
    try {
      const response = await fetch(`/api/abu-dhabi/nl2semantic2sql/semantic-admin/versions/${versionId}/${operation}`, { method: 'POST', credentials: 'include' });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.error || '版本操作失败'); await load();
    } catch (err) { setError(err instanceof Error ? err.message : '版本操作失败'); }
    finally { setLoading(false); }
  };
  return <div className="abu-admin-panel">
    <div className="abu-admin-toolbar"><div className="abu-scope-selector">{(['liveability', 'makani'] as const).map(item => <button key={item} className={scope === item ? 'active' : ''} onClick={() => { setScope(item); setEditing(null); }}>{SOURCE_LABELS[item]}</button>)}</div><select value={type} onChange={event => { setType(event.target.value as AdminEntryType); setEditing(null); }}>{Object.entries(ADMIN_ENTRY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><div className="abu-config-search"><Search size={13} /><input value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void load(); }} placeholder="搜索语义配置" /><button className="btn-secondary btn-sm" onClick={() => void load()}><RefreshCw size={13} /></button></div><button className="btn-primary btn-sm" onClick={() => setEditing({ id: 'new', entry_type: type, state: 'draft', source: 'registry', payload: {} })}><Plus size={13} />新建</button></div>
    <div className="abu-card-note"><ShieldCheck size={14} />页面修改只进入版本草稿；校验通过后由审核角色发布。未发布配置不会进入当前问数运行时。</div>
    {error && <div className="abu-inline-error">{error}</div>}
    {editing && <div className="abu-admin-editor"><div className="abu-config-heading"><div><span className="abu-kicker">DRAFT EDITOR</span><h4>{editing.id === 'new' ? '新建' : '编辑'}{ADMIN_ENTRY_LABELS[type]}</h4></div><div className="abu-admin-actions"><button className="btn-secondary btn-sm" onClick={() => setEditing(null)}>取消</button><button className="btn-primary btn-sm" onClick={() => void save()} disabled={loading}><Save size={13} />保存草稿</button></div></div><AdminPayloadForm type={type} payload={editing.payload} onChange={payload => setEditing({ ...editing, payload })} /></div>}
    <div className="abu-admin-list">{loading && !editing ? <div className="abu-loading"><Activity size={14} />正在加载...</div> : items.map(item => <div className="abu-admin-row" key={item.id}><div className="abu-admin-row-main"><strong>{String(item.payload.asset_id || item.payload.contract_id || item.payload.left || item.payload.semantic_field || item.id)}</strong><span>{item.state === 'published_baseline' ? '基线已发布' : item.state === 'published' ? '已发布' : item.state === 'deleted' ? '草稿删除' : '草稿'}</span><small>{String(item.payload.description || item.payload.physical_field || item.payload.right || '')}</small></div><div className="abu-admin-actions"><button className="btn-secondary btn-sm" onClick={() => setEditing(item)} title="编辑"><Pencil size={13} /></button><button className="btn-secondary btn-sm" onClick={() => void remove(item)} title="删除"><Trash2 size={13} /></button></div></div>)}</div>
    {versions.length > 0 && <div className="abu-admin-versions"><h4>版本审核</h4>{versions.map(version => <div className="abu-admin-version" key={String(version.id)}><span><b>{version.version_label}</b><em>{version.status}</em></span><span className="abu-admin-actions">{version.status === 'draft' && <button className="btn-secondary btn-sm" onClick={() => void action(Number(version.id), 'validate')} disabled={loading}>校验</button>}{version.status === 'reviewed' && <button className="btn-primary btn-sm" onClick={() => void action(Number(version.id), 'publish')} disabled={loading}><Upload size={13} />发布</button>}</span></div>)}</div>}
  </div>;
}

function SourceCard({ source, onOpen }: { source: Record<string, any>; onOpen: () => void }) {
  const registration = source.source?.registration || {};
  const coverage = source.ontology?.coverage || {};
  const gate = source.semantic_layer?.activation_gate || {};
  const benchmark = source.benchmark || {};
  const scorecard = source.benchmark_scorecard || {};
  const scorecardCoverage = scorecard.coverage || {};
  const technicalCoverage = source.technical_benchmark_candidates?.coverage || {};
  const candidateCoverage = source.semantic_candidates?.coverage || {};
  const relationCoverage = source.relationship_candidates?.coverage || {};
  const semanticAssets = (source.semantic_layer?.assets || []) as Array<Record<string, any>>;
  const reviewedAssetCount = semanticAssets.filter(item => String(item.review_status || '').toLocaleLowerCase().startsWith('reviewed')).length;
  const inferredAssetCount = semanticAssets.filter(item => String(item.review_status || '') === 'inferred_candidate').length;
  return (
    <article className="abu-source-card">
      <div className="abu-card-heading"><div><span className="abu-kicker">SOURCE {source.source?.source_id}</span><h3>{source.label}</h3></div><Status ok={registration.registration_status === 'registered'}>{registration.registration_status === 'registered' ? '已登记' : '需检查登记'}</Status></div>
      <p className="abu-source-db"><Database size={14} />{source.source?.database_name} / {(source.source?.authorized_schemas || []).join(', ')}</p>
      <div className="abu-chip-row"><span className="abu-chip">登记：{fmt(registration.registration_status)}</span><span className="abu-chip">健康：{fmt(registration.health_status)}</span><span className="abu-chip">发现：{fmt(registration.discovery_status)}</span></div>
      <div className="abu-metric-grid">
        <Metric label="发现资源" value={source.technical_catalog?.resource_count} />
        <Metric label="字段" value={source.technical_catalog?.field_count} />
        <Metric label="审核业务资产" value={coverage.reviewed_business_asset_count ?? reviewedAssetCount} />
        <Metric label="推断候选资产" value={inferredAssetCount} />
        <Metric label="审核关系" value={coverage.reviewed_relationship_count} />
        <Metric label="活动语义资源" value={coverage.active_semantic_resource_count} />
        <Metric label="候选已评估" value={candidateCoverage.resource_count} />
        <Metric label="可执行资产" value={candidateCoverage.published_runtime_asset_count} tone="success" />
        <Metric label="字典支持待审核" value={candidateCoverage.dictionary_supported_review_required_count} />
        <Metric label="关系候选待审核" value={relationCoverage.candidate_review_required_count} />
        <Metric label="Benchmark" value={benchmark.metrics?.case_run_pass_rate != null ? `${Math.round(benchmark.metrics.case_run_pass_rate * 100)}%` : benchmark.status} tone="success" />
        <Metric label="题集表覆盖" value={scorecardCoverage.benchmark_table_coverage != null ? pct(scorecardCoverage.benchmark_table_coverage) : '-'} />
        <Metric label="业务字段题覆盖" value={scorecardCoverage.reviewed_business_field_coverage != null ? pct(scorecardCoverage.reviewed_business_field_coverage) : '-'} />
        <Metric label="技术候选题" value={technicalCoverage.candidate_count} />
        <Metric label="技术字段候选" value={technicalCoverage.technical_query_eligible_field_count} />
      </div>
      <div className="abu-chip-row"><span className="abu-chip">{source.semantic_layer?.version}</span><span className="abu-chip">{source.semantic_layer?.metric_contract_version}</span><span className="abu-chip">{source.source?.virtual_ingestion?.mode}</span></div>
      <div className="abu-card-note"><ShieldCheck size={14} />业务本体完整性：<b>{coverage.business_semantic_coverage_complete ? '完整' : '已审核子集，未完整覆盖'}</b></div>
      <ResourceInventory source={source} />
      <div className="abu-card-actions"><button className="btn-secondary btn-sm" onClick={onOpen}><FileSearch size={14} />查看证据</button></div>
    </article>
  );
}

function CandidateResolutionPanel({ selection }: { selection: CandidateResolution }) {
  const resolution = selection.resolution || {};
  const candidates = (resolution.candidates || []) as Array<Record<string, any>>;
  const selected = resolution.decision === 'eligible_for_existing_reviewed_runtime';
  const reviewedSet = (resolution.reviewed_asset_set_candidate_ids || []) as string[];
  return <div className="abu-candidate-result">
    <div className="abu-result-heading"><div><span className="abu-kicker">BUSINESS-LANGUAGE ASSET SELECTION</span><h3>{selected ? '已选中已发布业务资产' : '尚未获得执行资格'}</h3></div><Status ok={selected}>{selected ? '可进入已审核运行时' : '需要澄清或业务审核'}</Status></div>
    <p className="abu-candidate-boundary">候选检索仅使用业务标签、别名和数据字典说明；不以用户输入物理表名，不向未审核候选授予 SQL 权限。</p>
    <div className="abu-metric-grid"><Metric label="候选范围" value={resolution.candidate_count_considered} /><Metric label="选择状态" value={resolution.status} tone={selected ? 'success' : 'danger'} /><Metric label="审核资产集" value={reviewedSet.length || '-'} tone={reviewedSet.length ? 'success' : ''} /><Metric label="物理表名参与检索" value={resolution.physical_table_name_used_for_retrieval ? '是' : '否'} tone={resolution.physical_table_name_used_for_retrieval ? 'danger' : 'success'} /></div>
    {!candidates.length ? <div className="abu-rejection">没有足够的业务字典证据。请补充业务对象、指标或空间范围，或提交语义建模审核。</div> : <div className="abu-candidate-list">{candidates.map((candidate, index) => <article key={`${candidate.candidate_id}-${index}`} className="abu-candidate-item"><div className="abu-card-heading"><div><span className="abu-kicker">候选 {index + 1}</span><h4>{fmt(candidate.business_label)}</h4></div><Status ok={Boolean(candidate.published_runtime_asset)}>{candidate.published_runtime_asset ? '已发布' : '待审核'}</Status></div><p>{fmt(candidate.business_description)}</p><div className="abu-chip-row">{reviewedSet.includes(String(candidate.candidate_id)) && <span className="abu-chip abu-match-chip">审核资产集</span>}{(candidate.business_aliases || []).slice(0, 8).map((alias: string) => <span key={alias} className="abu-chip">{alias}</span>)}{(candidate.matched_business_objects || []).map((term: string) => <span key={`object-${term}`} className="abu-chip abu-match-chip">业务对象：{term}</span>)}{(candidate.matched_business_terms || []).map((term: string) => <span key={`match-${term}`} className="abu-chip abu-match-chip">命中：{term}</span>)}</div><p className="abu-candidate-state">{fmt(candidate.state_reason)}</p><details className="abu-details"><summary><Eye size={13} />字典字段证据</summary><div className="abu-candidate-evidence">{(candidate.dictionary_evidence?.field_description_samples || []).map((text: string, itemIndex: number) => <p key={itemIndex}>{text}</p>) || <p>无字段说明。</p>}</div></details></article>)}</div>}
  </div>;
}

function ResultTable({ result }: { result: Record<string, any> }) {
  const columns = (result.columns || []) as string[];
  const rows = (result.data || []) as Array<Record<string, any>>;
  if (!columns.length) return <div className="abu-empty">没有可展示的数据行。</div>;
  return <div className="abu-result-table-wrap"><table className="abu-result-table"><thead><tr>{columns.map(col => <th key={col}>{col}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map(col => <td key={col}>{fmt(row[col])}</td>)}</tr>)}</tbody></table>{result.truncated_for_console && <div className="abu-table-foot">仅展示前 {result.displayed_row_count} 行，共 {result.row_count} 行。</div>}</div>;
}

function PlanAuthority({ plan }: { plan: Record<string, any> | null | undefined }) {
  if (!plan) return <Metric label="语义计划" value="未生成" tone="danger" />;
  if (plan.execution_authority === true) return <Metric label="IR 执行" value="认证编译" tone="success" />;
  if (plan.status === 'planned') return <Metric label="IR 执行" value="观测 Shadow" />;
  return <Metric label="IR 执行" value="计划未生成" tone="danger" />;
}

function BenchmarkCases({ source, onUseCase }: { source: Record<string, any>; onUseCase: (scope: Scope, question: string) => void }) {
  const cases = (source.benchmark?.cases || []) as Array<Record<string, any>>;
  return <div className="abu-benchmark-cases">
    {cases.map(item => <div key={item.case_id} className="abu-benchmark-case">
      <div className="abu-benchmark-case-main">
        <span className="abu-kicker">{item.case_id}</span>
        <p>{item.question}</p>
        <div className="abu-chip-row"><span className="abu-chip">{item.track}</span><span className="abu-chip">{item.split}</span><span className="abu-chip">预期：{item.expected_status}</span></div>
      </div>
      <div className="abu-benchmark-case-meta"><Status ok={item.meets_release_threshold === true}>{item.passed_run_count}/{item.run_count} 通过</Status><button className="btn-secondary btn-sm" onClick={() => onUseCase(source.key as Scope, String(item.question || ''))} disabled={!item.question}>用此题验证</button></div>
    </div>)}
  </div>;
}

function BenchmarkReleaseScorecards({ sources }: { sources: Array<Record<string, any>> }) {
  return <section className="abu-section"><div className="abu-section-title"><div><span className="abu-kicker">RELEASE SCORECARD</span><h3>全库覆盖与模型质量</h3></div><span className="abu-muted">覆盖完整性和准确率分开统计</span></div><div className="abu-source-grid">{sources.map(source => { const scorecard = source.benchmark_scorecard || {}; const coverage = scorecard.coverage || {}; const quality = scorecard.quality || {}; const technical = source.technical_benchmark_candidates || {}; const technicalCoverage = technical.coverage || {}; return <article key={`scorecard-${source.key}`} className="abu-detail-card"><h3>{source.label}</h3><div className="abu-metric-grid"><Metric label="完整题数" value={scorecard.benchmark?.case_count} /><Metric label="发现表覆盖" value={coverage.benchmark_table_coverage != null ? pct(coverage.benchmark_table_coverage) : '-'} /><Metric label="技术层可问表" value={coverage.technical_query_table_coverage != null ? `${pct(coverage.technical_query_table_coverage)} (${coverage.benchmark_referenced_technical_query_table_count}/${coverage.technical_query_eligible_table_count})` : '-'} /><Metric label="业务字段题覆盖" value={coverage.reviewed_business_field_coverage != null ? pct(coverage.reviewed_business_field_coverage) : '-'} /><Metric label="业务问数准确率" value={quality.business_query_accuracy != null ? pct(quality.business_query_accuracy) : '-'} tone="success" /><Metric label="报告题数/全量" value={quality.report_case_count != null ? `${quality.report_case_count}/${quality.benchmark_case_count}` : '-'} /><Metric label="待补字段题位" value={source.benchmark_coverage_plan?.summary?.candidate_case_slots_to_fill} /><Metric label="技术候选题" value={technicalCoverage.candidate_count} /><Metric label="待真实源冻结" value={technicalCoverage.language_variant_count} /></div><p className="abu-card-note"><ShieldCheck size={14} />技术层可问表只表示可以做受限只读的表级、字段级查询；技术候选题仍需真实源执行并冻结结果，不能当作业务准确率。业务字段题覆盖表示已审核业务字段中已有 benchmark 题目的比例。任何覆盖门禁未通过，都不会删除题目来提高准确率。</p><Status ok={scorecard.status === 'ready'}>{scorecard.status === 'ready' ? '可发布' : '覆盖待完善'}</Status><JsonDetails title="发布门禁与覆盖指标" value={{ gates: scorecard.release_gates, coverage, quality, terminology: scorecard.terminology, technical_candidates: technical }} /></article>; })}</div></section>;
}

function BenchmarkRouteCard({ title, route }: { title: string; route: Record<string, any> }) {
  const metrics = route.metrics || {};
  const routes = Object.entries(metrics.planner_route_counts || {}) as Array<[string, unknown]>;
  const semantic = route.semantic_configuration || {};
  return <article className="abu-detail-card abu-route-card">
    <div className="abu-card-heading"><div><span className="abu-kicker">{fmt(route.execution_profile)}</span><h3>{title}</h3></div><Status ok={route.status === 'passed'}>{route.status === 'passed' ? '36 题通过' : fmt(route.status)}</Status></div>
    <div className="abu-metric-grid">
      <Metric label="总通过" value={`${fmt(metrics.passed_case_count)}/${fmt(metrics.case_count)}`} tone={metrics.case_pass_rate === 1 ? 'success' : 'danger'} />
      <Metric label="执行正确" value={`${fmt(metrics.execute_passed_case_count)}/${fmt(metrics.execute_case_count)}`} tone={metrics.execute_pass_rate === 1 ? 'success' : 'danger'} />
      <Metric label="Clarify" value={`${fmt(metrics.clarify_passed_case_count)}/${fmt(metrics.clarify_case_count)}`} />
      <Metric label="Refuse" value={`${fmt(metrics.refuse_passed_case_count)}/${fmt(metrics.refuse_case_count)}`} />
      <Metric label="结果合同" value={`${fmt(metrics.result_contract_passed_case_count)}/${fmt(metrics.result_contract_case_count)}`} tone="success" />
      <Metric label="自由生成均值" value={milliseconds(metrics.mean_generation_latency_ms)} />
    </div>
    <div className="abu-chip-row">{routes.map(([name, count]) => <span className="abu-chip" key={name}>{name}: {fmt(count)}</span>)}</div>
    <div className="abu-semantic-binding">
      {(['liveability', 'makani'] as const).map(source => <div key={source}><span>{SOURCE_LABELS[source]}</span><strong>{fmt(semantic[source]?.semantic_version)}</strong><code title={semantic[source]?.sha256}>{String(semantic[source]?.sha256 || '-').slice(0, 12)}</code></div>)}
    </div>
    <div className="abu-card-note"><ShieldCheck size={14} />题集、语义层和运行隔离均由评测器绑定；失败分类：{Object.keys(metrics.failure_class_counts || {}).length ? Object.keys(metrics.failure_class_counts).join(', ') : '无'}。</div>
  </article>;
}

function StabilitySummary({ stability }: { stability?: Record<string, any> }) {
  if (!stability) return <div className="abu-rejection">尚未发布重复稳定性评测。</div>;
  const audit = stability.configuration_audit || {};
  const metrics = stability.metrics || {};
  const latency = metrics.latency || {};
  const usage = metrics.usage_candidate_minus_baseline_total || {};
  const promotion = stability.promotion_assessment || {};
  const unstable = (stability.unstable_route_cases || []) as Array<Record<string, any>>;
  return <article className="abu-detail-card abu-stability-card">
    <div className="abu-card-heading"><div><span className="abu-kicker">REPEATED STABILITY / PRIMARY CONCLUSION</span><h3>3 组重复评测：两路线均为 17/18，未形成替换依据</h3></div><Status ok={audit.each_run_pair_controlled === true}>每组受控</Status></div>
    <div className="abu-metric-grid">
      <Metric label="重复组" value={audit.run_count} />
      <Metric label="路线观测" value={metrics.route_observation_count} />
      <Metric label="Baseline" value={`${fmt(metrics.baseline_route_passed_count)}/${fmt(metrics.route_observation_count)} (${pct(metrics.baseline_route_pass_rate)})`} />
      <Metric label="SemanticQueryIR" value={`${fmt(metrics.candidate_route_passed_count)}/${fmt(metrics.route_observation_count)} (${pct(metrics.candidate_route_pass_rate)})`} />
      <Metric label="准确率差" value={pct(metrics.candidate_minus_baseline_pass_rate)} />
      <Metric label="IR 平均延迟差" value={milliseconds(latency.mean_candidate_minus_baseline_ms)} tone={latency.mean_candidate_minus_baseline_ms > 0 ? 'danger' : 'success'} />
      <Metric label="IR 更快组数" value={`${fmt(latency.candidate_faster_run_count)}/${fmt(audit.run_count)}`} />
      <Metric label="Baseline 更快组数" value={`${fmt(latency.baseline_faster_run_count)}/${fmt(audit.run_count)}`} />
      <Metric label="候选路线晋级" value={promotion.promotion_supported ? '支持' : '不支持'} tone={promotion.promotion_supported ? 'success' : 'danger'} />
    </div>
    <div className="abu-comparison-slices"><span>三组延迟差 IR-Baseline：<b>{(latency.run_deltas_ms || []).map((value: number) => milliseconds(value)).join(' / ')}</b></span><span>累计 token 差：输入 <b>{signed(usage.input_tokens)}</b>，输出 <b>{signed(usage.output_tokens)}</b></span></div>
    <div className="abu-chip-row">{unstable.map(item => <span className="abu-chip" key={item.case_id}>{item.case_id} · {item.family} · B {item.baseline_passed_run_count}/{item.run_count} · IR {item.candidate_passed_run_count}/{item.run_count}</span>)}</div>
    <div className="abu-card-note"><ShieldCheck size={14} />结论：总体准确率持平，但两路线各有一个不同的随机结果错误；IR 的延迟方向跨组不一致且 token 成本持续更高。当前应保持 baseline 生产默认，并继续扩充真正区分路线的困难题。</div>
    <JsonDetails title="重复稳定性指标与输入报告校验和" value={stability} />
  </article>;
}

function BenchmarkComparison({ evaluation }: { evaluation?: Record<string, any> }) {
  if (!evaluation) return <div className="abu-rejection">尚未发布双路线端到端评测。</div>;
  const baseline = evaluation.routes?.baseline_sql || {};
  const candidate = evaluation.routes?.semantic_ir_experimental || {};
  const pairwise = evaluation.pairwise || {};
  const interpretation = pairwise.interpretation || {};
  const route = pairwise.metrics?.route_comparison || {};
  const generation = route.paired_generation || {};
  const usage = generation.usage || {};
  const freeForm = pairwise.metrics?.by_category?.single_source_free_form_route?.paired_generation || {};
  const mismatch = pairwise.metrics?.by_category?.route_or_contract_mismatch?.paired_generation || {};
  return <div className="abu-evaluation-band">
    <div className="abu-section-title"><div><span className="abu-kicker">PUBLISHED END-TO-END EVIDENCE</span><h3>双路线真实源执行结果</h3></div><span className="abu-muted">{fmt(evaluation.release_id)}</span></div>
    <StabilitySummary stability={evaluation.stability} />
    <div className="abu-section-title abu-snapshot-title"><div><span className="abu-kicker">PUBLISHED SNAPSHOT</span><h3>发布基准单次快照</h3></div></div>
    <div className="abu-source-grid"><BenchmarkRouteCard title="Baseline SQL" route={baseline} /><BenchmarkRouteCard title="SemanticQueryIR 候选路线" route={candidate} /></div>
    <article className="abu-detail-card abu-comparison-card">
      <div className="abu-card-heading"><div><span className="abu-kicker">CONTROLLED PAIRWISE SNAPSHOT</span><h3>发布快照的 6 个路线题：6/6 对 6/6</h3></div><Status ok={pairwise.paired_configuration_verified === true}>配置一致</Status></div>
      <div className="abu-metric-grid">
        <Metric label="路线对比题" value={interpretation.route_comparison_case_count} />
        <Metric label="共同控制题" value={interpretation.shared_control_case_count} />
        <Metric label="Baseline" value={`${fmt(route.baseline_passed_case_count)}/${fmt(route.case_count)}`} tone="success" />
        <Metric label="SemanticQueryIR" value={`${fmt(route.candidate_passed_case_count)}/${fmt(route.case_count)}`} tone="success" />
        <Metric label="准确率差" value={pct(route.candidate_minus_baseline_pass_rate)} />
        <Metric label="平均延迟差 IR-Baseline" value={milliseconds(generation.candidate_minus_baseline_mean_latency_ms)} />
        <Metric label="输入 token 差" value={signed(usage.input_tokens?.candidate_minus_baseline_total)} />
        <Metric label="输出 token 差" value={signed(usage.output_tokens?.candidate_minus_baseline_total)} />
        <Metric label="候选路线晋级" value={interpretation.promotion_supported ? '支持' : '不支持'} tone={interpretation.promotion_supported ? 'success' : 'danger'} />
      </div>
      <div className="abu-comparison-slices"><span>5 个纯自由规划题：IR 平均延迟差 <b>{milliseconds(freeForm.candidate_minus_baseline_mean_latency_ms)}</b></span><span>1 个路线/合同差异题：IR 平均延迟差 <b>{milliseconds(mismatch.candidate_minus_baseline_mean_latency_ms)}</b></span></div>
      <div className="abu-card-note"><ShieldCheck size={14} />该区只保留发布时的单次快照用于追溯；路线决策以上方三组重复稳定性结果为准。30 个审核合同、准入策略和联邦题是共同控制，不算作 IR 优势证据。</div>
      <JsonDetails title="配对指标与结论边界" value={pairwise} />
    </article>
  </div>;
}

export default function AbuDhabiNl2SqlProductTab() {
  const [evidence, setEvidence] = useState<ProductEvidence | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [scope, setScope] = useState<Scope>('liveability');
  const [question, setQuestion] = useState(EXAMPLES.liveability);
  const [running, setRunning] = useState(false);
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [candidateResolution, setCandidateResolution] = useState<CandidateResolution | null>(null);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [view, setView] = useState<'overview' | 'ontology' | 'semantic' | 'benchmark'>('overview');

  const loadEvidence = async () => {
    setLoading(true); setError('');
    try {
      const response = await fetch('/api/abu-dhabi/nl2semantic2sql/evidence', { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '证据加载失败');
      setEvidence(payload);
    } catch (err) { setError(err instanceof Error ? err.message : '证据加载失败'); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadEvidence(); }, []);

  const selected = useMemo(() => evidence?.sources.find(item => item.key === selectedSource) || null, [evidence, selectedSource]);
  const runQuery = async () => {
    if (!question.trim()) return;
    setRunning(true); setError(''); setQueryResult(null);
    try {
      if (scope !== 'federated') {
        const candidateResponse = await fetch('/api/abu-dhabi/nl2semantic2sql/semantic-candidates/resolve', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope, question: question.trim() }) });
        const candidatePayload = await candidateResponse.json();
        if (!candidateResponse.ok) throw new Error(candidatePayload.error || '业务资产选择失败');
        setCandidateResolution(candidatePayload);
        if (candidatePayload.resolution?.decision !== 'eligible_for_existing_reviewed_runtime') {
          return;
        }
      } else {
        setCandidateResolution(null);
      }
      const response = await fetch('/api/abu-dhabi/nl2semantic2sql/execute', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope, question: question.trim() }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '查询执行失败');
      setQueryResult(payload);
    } catch (err) { setError(err instanceof Error ? err.message : '查询执行失败'); }
    finally { setRunning(false); }
  };

  const chooseScope = (next: Scope) => { setScope(next); setQuestion(EXAMPLES[next]); setQueryResult(null); setCandidateResolution(null); };
  const useBenchmarkCase = (next: Scope, benchmarkQuestion: string) => {
    setScope(next);
    setQuestion(benchmarkQuestion);
    setQueryResult(null);
    setCandidateResolution(null);
    setView('overview');
  };
  if (loading) return <div className="abu-product-tab"><div className="abu-loading"><Activity size={16} />正在加载产品证据...</div></div>;
  if (!evidence) return <div className="abu-product-tab"><div className="abu-error">{error || '产品证据不可用'}<button className="btn-secondary btn-sm" onClick={loadEvidence}>重试</button></div></div>;

  return (
    <div className="abu-product-tab">
      <div className="abu-hero"><div><span className="abu-kicker">PRODUCT EVIDENCE / ABU DHABI</span><h2>NL2Semantic2SQL 验证工作台</h2><p>真实 PostgreSQL 虚拟来源的语义解析、受治理执行和 benchmark 证据。</p></div><div className="abu-hero-status"><Status ok={evidence.product.source_rows_persisted === false}>只读虚拟入湖</Status><Status ok={evidence.product.benchmark_gold_runtime_accessible === false}>Gold 与运行时隔离</Status><Status ok={evidence.product.execution_paths?.reviewed_metric_contract?.enabled === true}>认证指标编译</Status></div></div>
      <div className="abu-view-tabs">{([['overview', '总览'], ['ontology', '本体模型'], ['semantic', '语义层'], ['benchmark', 'Benchmark']] as const).map(([key, label]) => <button key={key} className={view === key ? 'active' : ''} onClick={() => setView(key)}>{label}</button>)}</div>
      {error && <div className="abu-inline-error">{error}</div>}
      {view === 'benchmark' && <BenchmarkComparison evaluation={evidence.benchmark_evaluation} />}
      {view === 'benchmark' && <BenchmarkReleaseScorecards sources={evidence.sources} />}
      {view === 'overview' && <>
        <section className="abu-section"><div className="abu-section-title"><div><span className="abu-kicker">REGISTERED SOURCES</span><h3>数据源与虚拟入湖</h3></div><span className="abu-muted">source rows persisted = false</span></div><div className="abu-source-grid">{evidence.sources.map(source => <SourceCard key={source.key} source={source} onOpen={() => { setSelectedSource(source.key); setView('semantic'); }} />)}</div></section>
        <section className="abu-section"><div className="abu-section-title"><div><span className="abu-kicker">MANUAL VALIDATION</span><h3>自然语言问数</h3></div><span className="abu-muted">问题不需要表名或字段名</span></div><div className="abu-query-toolbar"><div className="abu-scope-selector">{(['liveability', 'makani', 'federated'] as Scope[]).map(item => <button key={item} className={scope === item ? 'active' : ''} onClick={() => chooseScope(item)}>{SOURCE_LABELS[item]}</button>)}</div><button className="btn-secondary btn-sm" onClick={() => setQuestion(EXAMPLES[scope])}>填入示例</button></div><textarea className="abu-question" value={question} onChange={event => setQuestion(event.target.value)} placeholder="输入业务问题..." rows={3} /><button className="btn-primary abu-run-button" disabled={running || !question.trim()} onClick={runQuery}><Play size={15} />{running ? '执行中...' : '先选业务资产并查询'}</button>{candidateResolution && <CandidateResolutionPanel selection={candidateResolution} />}{queryResult && <div className="abu-query-result"><div className="abu-result-heading"><div><span className="abu-kicker">EXECUTION EVIDENCE</span><h3>{queryResult.status === 'ok' ? '查询完成' : queryResult.status === 'rejected' ? '已拒答' : '查询执行失败'}</h3></div><Status ok={queryResult.status === 'ok'}>{queryResult.status === 'ok' ? '通过校验' : queryResult.status === 'rejected' ? '已拒答' : '执行失败'}</Status></div>{queryResult.reason && <div className="abu-rejection">{queryResult.reason}</div>}{queryResult.error && <div className="abu-rejection">执行原因：{queryResult.error}</div>}<div className="abu-metric-grid"><Metric label="路由" value={queryResult.planner?.route} /><Metric label="准入决策" value={queryResult.admission?.decision || '运行时治理校验'} tone={queryResult.admission?.runtime_admitted === false ? 'danger' : 'success'} /><Metric label="LLM 调用" value={queryResult.planner?.llm_invoked ? '是' : '否'} /><PlanAuthority plan={queryResult.query?.semantic_plan || queryResult.semantic_plan} /><Metric label="总耗时" value={milliseconds(queryResult.timing?.total_ms)} /><Metric label="数据库耗时" value={milliseconds(queryResult.timing?.database_ms)} /><Metric label="数据库" value={queryResult.source?.database_name || (queryResult.result?.sections || []).map((s: any) => s.source).join(', ')} /><Metric label="来源行持久化" value={queryResult.source_rows_persisted ? '是' : '否'} tone={queryResult.source_rows_persisted ? 'danger' : 'success'} /></div>{queryResult.result?.sections ? queryResult.result.sections.map((section: any) => <div key={section.source} className="abu-result-section"><h4>{SOURCE_LABELS[section.source as Scope] || section.source}</h4><ResultTable result={section.result || {}} /><JsonDetails title="查询与语义计划" value={{ query: section.query, semantic_plan: section.query?.semantic_plan }} /></div>) : <><ResultTable result={queryResult.result || {}} /><JsonDetails title="查询与语义计划" value={{ query: queryResult.query, semantic_plan: queryResult.query?.semantic_plan }} /></>}</div>}</section>
      </>}
      {view === 'ontology' && <section className="abu-section"><div className="abu-section-title"><div><span className="abu-kicker">ONTOLOGY</span><h3>本体模型审核状态</h3></div><span className="abu-muted">技术实体全量登记，业务语义按审核范围启用</span></div><div className="abu-source-grid">{evidence.sources.map(source => { const concepts = (source.ontology.concepts || []) as Array<Record<string, any>>; const candidateConcepts = concepts.filter(item => String(item.runtime_status || '').includes('technical_metadata_only')).length; return <article key={source.key} className="abu-detail-card"><h3>{source.label}</h3><div className="abu-metric-grid"><Metric label="发现资源" value={source.ontology.coverage.resource_count} /><Metric label="活动概念" value={source.ontology.coverage.active_semantic_resource_count} /><Metric label="审核业务资产" value={source.ontology.coverage.reviewed_business_asset_count} /><Metric label="候选概念" value={candidateConcepts} /><Metric label="审核关系" value={source.ontology.coverage.reviewed_relationship_count} /></div><p className="abu-card-note"><ShieldCheck size={14} />本体运行时作用：业务标签/别名解析、粒度与字段角色约束、仅审核关系准入 Join。候选概念用于检索和审核，不获得业务执行授权。</p><Status ok={source.ontology.coverage.business_semantic_coverage_complete === true}>{source.ontology.coverage.business_semantic_coverage_complete ? '业务本体完整' : '业务本体尚未完整覆盖'}</Status><JsonDetails title={`概念与关系（${source.ontology.concepts.length} 个概念）`} value={{ concepts: source.ontology.concepts, relations: source.ontology.relations }} /></article> })}</div></section>}
      {view === 'semantic' && <>
        <section className="abu-section"><div className="abu-section-title"><div><span className="abu-kicker">SEMANTIC LAYER</span><h3>语义层配置</h3></div><span className="abu-muted">发布基线、完整配置审查与治理编辑</span></div><div className="abu-source-grid">{evidence.sources.map(source => { const assets = (source.semantic_layer.assets || []) as Array<Record<string, any>>; const reviewed = assets.filter(item => String(item.review_status || '').toLocaleLowerCase().startsWith('reviewed')).length; const inferred = assets.filter(item => String(item.review_status || '') === 'inferred_candidate').length; const queueCoverage = source.business_benchmark_review_queue?.coverage || {}; return <article key={source.key} className="abu-detail-card"><h3>{source.label} <span className="abu-chip">{source.semantic_layer.version}</span></h3><p>{source.semantic_layer.status}</p><div className="abu-metric-grid"><Metric label="审核业务资产" value={reviewed} /><Metric label="推断候选资产" value={inferred} /><Metric label="Metric contracts" value={source.semantic_layer.metric_contracts.length} /><Metric label="审核关系" value={source.semantic_layer.relationships.length} /><Metric label="关系候选" value={source.relationship_candidates?.coverage?.candidate_review_required_count} /><Metric label="全库题位候选" value={queueCoverage.question_slot_count} /><Metric label="直接执行合同" value={source.semantic_layer.metric_contracts.filter((item: any) => item.direct_execution_enabled).length} /></div><div className="abu-card-note"><ShieldCheck size={14} />字典关系和空间关系只作为候选证据；未经关系、基数、坐标系和敏感性审核，不会进入 Join 准入。推断候选资产可查看、筛选和提交审核，但不会进入业务 SQL 执行。</div><div className="abu-policy-list">{Object.entries(source.semantic_layer.query_policy || {}).map(([key, value]) => <span key={key}><b>{key}</b>{fmt(value)}</span>)}</div><JsonDetails title="业务资产与配置摘要" value={{ assets: source.semantic_layer.assets, relationships: source.semantic_layer.relationships, contracts: source.semantic_layer.metric_contracts, candidate_catalog: source.semantic_candidates, relationship_candidates: source.relationship_candidates, caveats: source.semantic_layer.semantic_caveats }} /><SemanticConfigurationInspector source={source} /></article> })}</div></section>
        <section className="abu-section"><div className="abu-section-title"><div><span className="abu-kicker">SEMANTIC GOVERNANCE</span><h3>语义层治理与 CRUD</h3></div><span className="abu-muted">同一语义层中的草稿、校验、审核发布</span></div><SemanticAdminPanel defaultScope={scope === 'federated' ? 'liveability' : scope} /></section>
      </>}
      {view === 'benchmark' && <section className="abu-section"><div className="abu-section-title"><div><span className="abu-kicker">BENCHMARK</span><h3>真实数据源 benchmark</h3></div><span className="abu-muted">v1 控制组 + v2 选表/语义治理评测</span></div><article className="abu-detail-card"><h3>Benchmark v2：主评测集</h3><p>{evidence.benchmark_v2?.purpose}</p><div className="abu-metric-grid"><Metric label="总用例" value={evidence.benchmark_v2?.case_count} /><Metric label="Liveability" value={evidence.benchmark_v2?.scope_case_counts?.liveability} /><Metric label="Makani" value={evidence.benchmark_v2?.scope_case_counts?.makani} /><Metric label="Federated" value={evidence.benchmark_v2?.scope_case_counts?.federated} /><Metric label="单资产 Top-1" value={evidence.benchmark_v2?.selection_report?.metrics?.execute_single_asset_top1_accuracy != null ? `${Math.round(evidence.benchmark_v2.selection_report.metrics.execute_single_asset_top1_accuracy * 100)}%` : '-'} tone="success" /><Metric label="多资产完整集" value={evidence.benchmark_v2?.selection_report?.metrics?.execute_multi_asset_reviewed_set_coverage_accuracy != null ? `${Math.round(evidence.benchmark_v2.selection_report.metrics.execute_multi_asset_reviewed_set_coverage_accuracy * 100)}%` : '-'} tone="success" /><Metric label="非执行安全门" value={evidence.benchmark_v2?.selection_report?.metrics?.non_execute_safety_gate_rate != null ? `${Math.round(evidence.benchmark_v2.selection_report.metrics.non_execute_safety_gate_rate * 100)}%` : '-'} tone="success" /><Metric label="Gold SQL" value={evidence.benchmark_v2?.anti_leakage?.gold_sql_in_public_dataset ? '存在' : '隔离'} tone="success" /><Metric label="物理表名入题" value={evidence.benchmark_v2?.anti_leakage?.questions_use_physical_table_names ? '是' : '否'} tone="success" /></div><div className="abu-card-note"><ShieldCheck size={14} />单资产和多资产分别计分：前者考察 Top-1，后者考察完整审核资产集，避免把真实关系问数误判为单表题。v2 覆盖选表、字段、粒度、关系准入、歧义澄清、拒答和跨源边界；SQL/结果正确性由独立评测器读取私有合同。</div><JsonDetails title="v2 用例与评测维度" value={evidence.benchmark_v2} /></article><div className="abu-source-grid">{evidence.sources.map(source => <article key={source.key} className="abu-detail-card"><h3>{source.label}：v1 稳定性控制组</h3><div className="abu-metric-grid"><Metric label="用例" value={source.benchmark.metrics.case_count} /><Metric label="Validation" value={source.benchmark.split_counts?.validation} /><Metric label="Holdout" value={source.benchmark.split_counts?.holdout} /><Metric label="观察" value={source.benchmark.metrics.case_run_count} /><Metric label="通过率" value={`${Math.round((source.benchmark.metrics.case_run_pass_rate || 0) * 100)}%`} tone="success" /><Metric label="安全召回" value={`${Math.round((source.benchmark.metrics.safety_pass_rate || 0) * 100)}%`} tone="success" /><Metric label="直接路由" value={`${Math.round((source.benchmark.metrics.planner?.direct_metric_query_route_rate || 0) * 100)}%`} /><Metric label="LLM 调用率" value={`${Math.round((source.benchmark.metrics.planner?.llm_invocation_case_rate || 0) * 100)}%`} /></div><BenchmarkCases source={source} onUseCase={useBenchmarkCase} /></article>)}</div><article className="abu-detail-card abu-federated-card"><h3>Federated：独立聚合并列展示</h3><div className="abu-metric-grid"><Metric label="用例" value={evidence.federated.metrics.case_count} /><Metric label="通过率" value={`${Math.round((evidence.federated.metrics.case_pass_rate || 0) * 100)}%`} tone="success" /><Metric label="Gold 等价" value={`${Math.round((evidence.federated.metrics.gold_bundle_equivalence_pass_rate || 0) * 100)}%`} tone="success" /><Metric label="跨库 SQL" value={evidence.federated.execution_policy.cross_database_sql ? '允许' : '禁止'} /><Metric label="跨源 Join" value={evidence.federated.execution_policy.cross_source_join ? '允许' : '禁止'} /></div><JsonDetails title="Federated 用例与边界" value={{ cases: evidence.federated.cases, claim_boundary: evidence.federated.claim_boundary, limitations: evidence.federated.limitations }} /></article></section>}
      {view === 'benchmark' && evidence.benchmark_v3 && <section className="abu-section"><article className="abu-detail-card"><h3>Benchmark v3：困难题集</h3><p>{evidence.benchmark_v3.purpose}</p><div className="abu-metric-grid"><Metric label="总用例" value={evidence.benchmark_v3.case_count} /><Metric label="单资产 Top-1" value={evidence.benchmark_v3.selection_report?.metrics?.single_asset_top1_accuracy != null ? `${Math.round(evidence.benchmark_v3.selection_report.metrics.single_asset_top1_accuracy * 100)}%` : '-'} tone="danger" /><Metric label="组合资产覆盖" value={evidence.benchmark_v3.selection_report?.metrics?.composite_reviewed_set_coverage_accuracy != null ? `${Math.round(evidence.benchmark_v3.selection_report.metrics.composite_reviewed_set_coverage_accuracy * 100)}%` : '-'} tone="danger" /><Metric label="非执行安全门" value={evidence.benchmark_v3.selection_report?.metrics?.non_execute_safety_gate_rate != null ? `${Math.round(evidence.benchmark_v3.selection_report.metrics.non_execute_safety_gate_rate * 100)}%` : '-'} tone="danger" /><Metric label="端到端 Gold" value="尚未发布" tone="danger" /></div><div className="abu-card-note"><ShieldCheck size={14} />v3 结果目前是困难题的语义候选选择证据，不是端到端 SQL/结果准确率。</div><JsonDetails title="v3 用例与评测维度" value={evidence.benchmark_v3} /></article></section>}
      {selected && <div className="abu-selected-source"><button className="btn-secondary btn-sm" onClick={() => setSelectedSource(null)}>关闭详情</button><strong>{selected.label} 已选中</strong></div>}
    </div>
  );
}
