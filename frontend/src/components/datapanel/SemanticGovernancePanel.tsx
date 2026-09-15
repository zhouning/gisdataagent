import { useEffect, useState } from 'react';
import { Activity, Pencil, Plus, RefreshCw, Save, Search, ShieldCheck, Trash2, Upload } from 'lucide-react';

type AdminEntryType = 'assets' | 'fields' | 'relationships' | 'metric_contracts';

interface AdminEntryResponse {
  id: string;
  entry_type: AdminEntryType;
  payload: Record<string, any>;
  state: string;
  source: string;
  version_id?: number;
}

interface ScopeOption {
  key: string;
  label: string;
}

interface MetricGovernanceOverview {
  artifact_status?: string;
  versions?: { semantic?: string; ontology?: string; metric_contract?: string };
  contracts?: {
    total?: number;
    status_counts?: Record<string, number>;
    direct_execution_count?: number;
    result_shape_counts?: Record<string, number>;
    composition_count?: number;
    composition_kind_counts?: Record<string, number>;
  };
  ontology?: { concept_count?: number; relation_count?: number };
  semantic?: { relationship_count?: number; asset_count?: number; catalog_resource_count?: number };
  observation?: { status?: string; observation_count?: number | null; latest_observed_at?: string | null; scope_binding?: string };
  latency?: { status?: string; mean_generation_latency_ms?: number | null; p95_generation_latency_ms?: number | null };
  claim_boundary?: { source_rows_persisted?: boolean; observation_scope_mapping?: string };
}

const ADMIN_ENTRY_LABELS: Record<AdminEntryType, string> = {
  assets: '业务资产',
  fields: '语义字段',
  relationships: '审核关系',
  metric_contracts: '指标合同',
};

const COMPOSITION_KIND_LABELS: Record<string, string> = {
  wide_stage_unpivot: '宽表阶段列转行',
  detail_with_partition_total: '明细及分区总数',
  universal_coverage: '全量覆盖判断',
};

const COMPOSITION_FIELD_LABELS: Record<string, string> = {
  kind: '组成类型',
  business_grain: '业务粒度',
  axis: '分析轴',
  aggregation: '聚合方式',
  stage_semantics: '阶段口径',
  source_field_pattern: '字段模式',
  detail_metric: '明细度量',
  partition_dimension: '分区维度',
  companion_metric: '伴随度量',
  row_scope: '行范围',
  version_scope: '版本范围',
  compiler_shape: '编译形状',
  coverage_count_basis: '覆盖计数口径',
  universe: '总体范围',
  subject: '统计对象',
  predicate: '覆盖条件',
  quantifier: '量词',
  assets: '资产',
  stages: '阶段',
};

function formatCompositionValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(item => formatCompositionValue(item)).filter(Boolean).join(' · ');
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

function sourceReference(value: Record<string, any>, aggregate = false): string {
  const reference = [value.table, value.field].filter(Boolean).join('.');
  const aliased = value.alias ? `${reference} -> ${value.alias}` : reference;
  return aggregate && value.aggregate ? `${value.aggregate}(${aliased})` : aliased;
}

function MetricCompositionDetails({ payload }: { payload: Record<string, any> }) {
  const composition = payload.metric_composition && typeof payload.metric_composition === 'object'
    ? payload.metric_composition as Record<string, any>
    : null;
  const dimensions = Array.isArray(payload.dimensions) ? payload.dimensions.filter((item: unknown) => item && typeof item === 'object') as Record<string, any>[] : [];
  const metrics = Array.isArray(payload.metrics) ? payload.metrics.filter((item: unknown) => item && typeof item === 'object') as Record<string, any>[] : [];
  const tables = Array.isArray(payload.tables) ? payload.tables.map((item: unknown) => String(item)).filter(Boolean) : [];
  const directExecution = payload.direct_execution && typeof payload.direct_execution === 'object'
    ? payload.direct_execution as Record<string, any>
    : null;
  const fieldMap = composition?.source_field_map && typeof composition.source_field_map === 'object'
    ? Object.entries(composition.source_field_map as Record<string, unknown>)
    : [];
  const compositionFields = composition
    ? Object.entries(composition).filter(([key]) => key !== 'source_field_map')
    : [];
  const kind = String(composition?.kind || '').trim();
  const summary = kind
    ? `${COMPOSITION_KIND_LABELS[kind] || kind}${composition?.business_grain ? ` · ${composition.business_grain}` : ''}`
    : '标准聚合合同';

  return <details className="abu-metric-composition" open={Boolean(composition)}>
    <summary><span>指标组成</span><b>{summary}</b></summary>
    <div className="abu-metric-composition-grid">
      {compositionFields.length > 0 && <section><h5>组成规则</h5><dl>{compositionFields.map(([key, value]) => <div key={key}><dt>{COMPOSITION_FIELD_LABELS[key] || key.replace(/_/g, ' ')}</dt><dd>{key === 'kind' ? COMPOSITION_KIND_LABELS[String(value)] || formatCompositionValue(value) : formatCompositionValue(value)}</dd></div>)}</dl></section>}
      {fieldMap.length > 0 && <section><h5>阶段/字段映射</h5><dl>{fieldMap.map(([key, value]) => <div key={key}><dt>{key}</dt><dd><code>{formatCompositionValue(value)}</code></dd></div>)}</dl></section>}
      {dimensions.length > 0 && <section><h5>维度</h5><ul>{dimensions.map((item, index) => <li key={`${sourceReference(item)}:${index}`}><code>{sourceReference(item)}</code></li>)}</ul></section>}
      {metrics.length > 0 && <section><h5>度量</h5><ul>{metrics.map((item, index) => <li key={`${sourceReference(item, true)}:${index}`}><code>{sourceReference(item, true)}</code></li>)}</ul></section>}
      {tables.length > 0 && <section><h5>数据范围</h5><div className="abu-metric-chip-list">{tables.map(table => <code key={table}>{table}</code>)}</div>{directExecution && <small>执行：{directExecution.enabled ? '可直接执行' : '需解析编译'} · {formatCompositionValue(directExecution.mode)}</small>}</section>}
    </div>
  </details>;
}

function AdminField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="abu-admin-field"><span>{label}</span><input value={value} onChange={event => onChange(event.target.value)} /></label>;
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

export function SemanticGovernancePanel({ defaultScope, defaultEntryType = 'assets', scopeOptions, refreshToken = 0 }: { defaultScope: string; defaultEntryType?: AdminEntryType; scopeOptions: ScopeOption[]; refreshToken?: number }) {
  const [scope, setScope] = useState(defaultScope);
  const [type, setType] = useState<AdminEntryType>(defaultEntryType);
  const [items, setItems] = useState<AdminEntryResponse[]>([]);
  const [versions, setVersions] = useState<Array<Record<string, any>>>([]);
  const [editing, setEditing] = useState<AdminEntryResponse | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [overview, setOverview] = useState<MetricGovernanceOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const selectedLabel = scopeOptions.find(option => option.key === scope)?.label || scope;

  const loadOverview = async () => {
    setOverviewLoading(true);
    try {
      const response = await fetch(`/api/semantic/governance/metric-contracts/overview?scope=${encodeURIComponent(scope)}`, { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '指标治理摘要加载失败');
      setOverview(payload);
    } catch (err) {
      setOverview(null);
      setError(err instanceof Error ? err.message : '指标治理摘要加载失败');
    } finally {
      setOverviewLoading(false);
    }
  };

  const load = async () => {
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ scope, offset: '0', limit: type === 'metric_contracts' ? '200' : '50' });
      if (search.trim()) params.set('search', search.trim());
      const response = await fetch(`/api/semantic/governance/${type}?${params.toString()}`, { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '语义配置加载失败');
      setItems(payload.items || []); setVersions(payload.versions || []);
    } catch (err) { setError(err instanceof Error ? err.message : '语义配置加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { if (scopeOptions.some(option => option.key === scope)) { void load(); void loadOverview(); } }, [scope, type, scopeOptions, refreshToken]);

  const save = async () => {
    if (!editing) return;
    setLoading(true); setError('');
    try {
      const isNew = editing.id === 'new';
      const url = isNew ? `/api/semantic/governance/${type}?scope=${encodeURIComponent(scope)}` : `/api/semantic/governance/${type}/${encodeURIComponent(editing.id)}?scope=${encodeURIComponent(scope)}`;
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
      const response = await fetch(`/api/semantic/governance/${type}/${encodeURIComponent(item.id)}?scope=${encodeURIComponent(scope)}`, { method: 'DELETE', credentials: 'include' });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.error || '删除失败'); await load();
    } catch (err) { setError(err instanceof Error ? err.message : '删除失败'); }
    finally { setLoading(false); }
  };
  const action = async (versionId: number, operation: 'validate' | 'publish') => {
    setLoading(true); setError('');
    try {
      const response = await fetch(`/api/semantic/governance/versions/${versionId}/${operation}`, { method: 'POST', credentials: 'include' });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.error || '版本操作失败'); await load();
    } catch (err) { setError(err instanceof Error ? err.message : '版本操作失败'); }
    finally { setLoading(false); }
  };
  if (!scopeOptions.length) return <div className="abu-empty">当前没有可编辑的版本化业务语义配置。</div>;
  const statusCounts = overview?.contracts?.status_counts || {};
  const shapeCounts = overview?.contracts?.result_shape_counts || {};
  const formatCount = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
  const formatLatency = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value).toLocaleString()} ms` : '—';
  const observationStatus = overview?.observation?.status || (overviewLoading ? 'loading' : 'not_available');
  const observationLabel = observationStatus === 'connected' ? '已连接' : observationStatus === 'not_connected' ? '未连接' : observationStatus === 'unavailable' ? '不可用' : observationStatus === 'loading' ? '加载中' : '暂无';
  const displayedItems = type === 'metric_contracts'
    ? [...items].sort((left, right) => {
      const compositionOrder = Number(Boolean(right.payload.metric_composition)) - Number(Boolean(left.payload.metric_composition));
      return compositionOrder || String(left.payload.contract_id || left.id).localeCompare(String(right.payload.contract_id || right.id));
    })
    : items;
  return <div className="abu-admin-panel">
    <div className="abu-admin-toolbar"><div className="abu-scope-selector">{scopeOptions.map(item => <button key={item.key} className={scope === item.key ? 'active' : ''} onClick={() => { setScope(item.key); setEditing(null); }}>{item.label}</button>)}</div><select value={type} onChange={event => { setType(event.target.value as AdminEntryType); setEditing(null); }}>{Object.entries(ADMIN_ENTRY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><div className="abu-config-search"><Search size={13} /><input value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void load(); }} placeholder="搜索语义配置" /><button className="btn-secondary btn-sm" onClick={() => void load()}><RefreshCw size={13} /></button></div><button className="btn-primary btn-sm" onClick={() => setEditing({ id: 'new', entry_type: type, state: 'draft', source: 'registry', payload: {} })}><Plus size={13} />新建</button></div>
    <div className="abu-card-note"><ShieldCheck size={14} />{selectedLabel} 的修改只进入版本草稿；校验通过后由审核角色发布。未发布配置不会进入当前问数运行时。</div>
    <section className="abu-governance-overview" aria-label="指标治理总览">
      <div className="abu-governance-overview-heading"><div><span className="abu-kicker">METRIC GOVERNANCE</span><h4>指标治理总览</h4></div><button className="btn-secondary btn-sm" onClick={() => void loadOverview()} disabled={overviewLoading} title="刷新指标治理摘要"><RefreshCw size={13} /></button></div>
      {!overview && !overviewLoading && <div className="abu-governance-empty">当前范围暂无可读取的发布工件摘要。</div>}
      {overview && <>
        <div className="abu-governance-version-row"><span>语义 <b>{overview.versions?.semantic || '—'}</b></span><span>本体 <b>{overview.versions?.ontology || '—'}</b></span><span>指标合同 <b>{overview.versions?.metric_contract || '—'}</b></span><span className={`abu-governance-status ${overview.artifact_status === 'available' ? 'ok' : 'warn'}`}>{overview.artifact_status === 'available' ? '发布工件可用' : '发布工件不可用'}</span></div>
        <div className="abu-governance-kpis"><div><span>合同总数</span><strong>{formatCount(overview.contracts?.total)}</strong></div><div><span>已审核</span><strong>{formatCount(statusCounts.reviewed)}</strong></div><div><span>直接执行</span><strong>{formatCount(overview.contracts?.direct_execution_count)}</strong></div><div><span>指标组合</span><strong>{formatCount(overview.contracts?.composition_count)}</strong></div><div><span>单/双极值</span><strong>{formatCount((shapeCounts.single_extreme || 0) + (shapeCounts.dual_extreme || 0))}</strong></div><div><span>本体概念</span><strong>{formatCount(overview.ontology?.concept_count)}</strong></div><div><span>语义关系</span><strong>{formatCount(overview.semantic?.relationship_count)}</strong></div></div>
        <div className="abu-governance-detail-grid"><div><span>观测状态</span><b className={observationStatus === 'connected' ? 'ok' : 'warn'}>{observationLabel}</b><small>{overview.observation?.scope_binding === 'not_mapped_to_semantic_contract_ids' ? '尚未映射到指标合同 ID' : `观测数 ${formatCount(overview.observation?.observation_count)}`}</small></div><div><span>延迟证据</span><b>{overview.latency?.status === 'observed' ? '当前工件报告' : '暂无'}</b><small>平均 {formatLatency(overview.latency?.mean_generation_latency_ms)} · P95 {formatLatency(overview.latency?.p95_generation_latency_ms)}</small></div><div><span>数据边界</span><b>{overview.claim_boundary?.source_rows_persisted === false ? '只读、无源行持久化' : '需核验'}</b><small>本摘要不代表生产路线准确率</small></div></div>
      </>}
    </section>
    {error && <div className="abu-inline-error">{error}</div>}
    {editing && <div className="abu-admin-editor"><div className="abu-config-heading"><div><span className="abu-kicker">DRAFT EDITOR</span><h4>{editing.id === 'new' ? '新建' : '编辑'}{ADMIN_ENTRY_LABELS[type]}</h4></div><div className="abu-admin-actions"><button className="btn-secondary btn-sm" onClick={() => setEditing(null)}>取消</button><button className="btn-primary btn-sm" onClick={() => void save()} disabled={loading}><Save size={13} />保存草稿</button></div></div><AdminPayloadForm type={type} payload={editing.payload} onChange={payload => setEditing({ ...editing, payload })} /></div>}
    <div className="abu-admin-list">{loading && !editing ? <div className="abu-loading"><Activity size={14} />正在加载...</div> : displayedItems.map(item => <div className="abu-admin-row" key={item.id}><div className="abu-admin-row-main"><strong>{String(item.payload.asset_id || item.payload.contract_id || item.payload.left || item.payload.semantic_field || item.id)}</strong><span>{item.state === 'published_baseline' ? '基线已发布' : item.state === 'published' ? '已发布' : item.state === 'deleted' ? '草稿删除' : '草稿'}</span><small>{String(item.payload.description || item.payload.physical_field || item.payload.right || '')}</small></div><div className="abu-admin-actions"><button className="btn-secondary btn-sm" onClick={() => setEditing(item)} title="编辑"><Pencil size={13} /></button><button className="btn-secondary btn-sm" onClick={() => void remove(item)} title="删除"><Trash2 size={13} /></button></div>{type === 'metric_contracts' && <MetricCompositionDetails payload={item.payload} />}</div>)}</div>
    {versions.length > 0 && <div className="abu-admin-versions"><h4>版本审核</h4>{versions.map(version => <div className="abu-admin-version" key={String(version.id)}><span><b>{version.version_label}</b><em>{version.status}</em></span><span className="abu-admin-actions">{version.status === 'draft' && <button className="btn-secondary btn-sm" onClick={() => void action(Number(version.id), 'validate')} disabled={loading}>校验</button>}{version.status === 'reviewed' && <button className="btn-primary btn-sm" onClick={() => void action(Number(version.id), 'publish')} disabled={loading}><Upload size={13} />发布</button>}</span></div>)}</div>}
  </div>;
}
