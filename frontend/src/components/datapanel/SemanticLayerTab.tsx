import { useState, useEffect, useMemo } from 'react';
import { SemanticGovernancePanel } from './SemanticGovernancePanel';
import { SemanticReviewQueuePanel } from './SemanticReviewQueuePanel';
import { BenchmarkReviewQueuePanel } from './BenchmarkReviewQueuePanel';
import SemanticInteropPanel from './SemanticInteropPanel';
interface SourceMeta {
  table_name: string;
  display_name: string;
  description: string;
  geometry_type?: string | null;
  srid?: number | null;
  synonyms: string[];
  suggested_analyses: string[];
  annotation_count?: number;
  nl2sql_enabled?: boolean;
  nl2sql_priority?: number;
}

interface GovernedSemanticSource {
  key?: string;
  label?: string;
  semantic_admin_scope?: string;
  source?: { source_id?: number | string; database_name?: string };
  semantic_layer?: { version?: string; status?: string; semantic_assets?: any[]; assets?: any[]; relationships?: any[]; metric_contracts?: any[] };
  technical_catalog?: { resource_count?: number; field_count?: number };
  technical_freeze_coverage?: { metrics?: { candidate_count?: number; frozen_count?: number; pending_count?: number; failed_count?: number; freeze_rate?: number } };
  business_semantic_review_queue?: { coverage?: { table_task_count?: number; field_task_count?: number; relationship_task_count?: number; reviewed_table_count?: number; reviewed_field_count?: number; reviewed_relationship_count?: number; review_required_table_count?: number; review_required_field_count?: number; review_required_relationship_count?: number; business_semantic_coverage_complete?: boolean } };
  business_benchmark_review_queue?: { coverage?: { question_slot_count?: number; language_variant_count?: number; reviewed_business_field_count?: number } };
  dictionary_evidence?: { coverage?: { table_count?: number; field_count?: number; dictionary_exact_supported_field_count?: number; dictionary_partial_supported_field_count?: number; dictionary_unmatched_field_count?: number; no_dictionary_evidence_field_count?: number }; compatibility?: { mode?: string } };
  technical_freeze_resume?: { total_candidates?: number; completed_candidate_count?: number; batch_count?: number; updated_at?: string };
}

interface ColumnAnnotation {
  column_name: string;
  data_type?: string;
  nullable?: boolean;
  semantic_domain?: string | null;
  aliases?: string[];
  unit?: string;
  description?: string;
  is_geometry?: boolean;
  semantic_field?: string | null;
  semantic_labels?: Record<string, string>;
  business_role?: string | null;
  semantic_status?: string | null;
  semantic_execution_eligible?: boolean;
  semantic_inference?: Record<string, any> | null;
  dictionary_evidence?: Record<string, any>;
  value_domain?: Array<string | number>;
  value_semantics?: Record<string, any>;
  definition_status?: string | null;
  business_table_card_evidence?: Record<string, any>;
}

function ValueDomainEvidence({ column }: { column: ColumnAnnotation }) {
  const nestedDomain = Array.isArray(column.value_semantics?.value_domain)
    ? column.value_semantics?.value_domain
    : [];
  const values = (column.value_domain?.length ? column.value_domain : nestedDomain)
    .map(value => String(value).trim())
    .filter(Boolean);
  const evidence = column.business_table_card_evidence
    || column.value_semantics?.source_evidence;
  const artifact = String(column.value_semantics?.source_artifact || '');
  return <div className="semantic-value-evidence" title={artifact || undefined}>
    {values.length > 0
      ? <span>{values.slice(0, 4).join(' · ')}{values.length > 4 ? ` · +${values.length - 4}` : ''}</span>
      : <i>—</i>}
    <small>{evidence ? '95 表卡' : column.dictionary_evidence?.supported ? '字典' : column.semantic_inference ? '推断候选' : '—'}</small>
  </div>;
}

interface SemanticCatalogTable {
  table_name: string;
  display_name: string;
  description?: string;
  source_key: string;
  source_id?: number | string | null;
  source_name?: string | null;
  source_type?: string | null;
  ingestion_mode?: string | null;
  resource_type?: string;
  estimated_record_count?: number | string | null;
  primary_key?: string[];
  foreign_keys?: any[];
  indexes?: any[];
  columns: ColumnAnnotation[];
  annotation_count: number;
  geometry_type?: string | null;
  srid?: number | null;
  synonyms?: string[];
  suggested_analyses?: string[];
  dictionary_evidence?: { support_status?: string; alignment_status?: string; matched_field_count?: number; field_count?: number; matched_field_coverage?: number | null };
  semantic_status?: string | null;
  semantic_asset_id?: string | null;
  semantic_review_status?: string | null;
  semantic_execution_eligible?: boolean;
  semantic_retrieval_eligible?: boolean;
  semantic_evidence?: Record<string, any>;
}

interface TableDetail {
  status?: string;
  table_name?: string;
  source?: SourceMeta | null;
  columns?: ColumnAnnotation[];
}

interface ResolveResult {
  sources?: any[];
  matched_columns?: Record<string, any[]>;
  sql_filters?: string[];
  region_sql?: string[];
  hierarchy_matches?: any[];
  equivalences?: any[];
  metric_hints?: any[];
  spatial_ops?: any[];
  error?: string;
  [key: string]: any;
}

function semanticColumnCounts(columns: ColumnAnnotation[] = []) {
  return columns.reduce((counts, column) => {
    counts.evidence += (column.semantic_field || column.semantic_labels || column.business_role || column.semantic_inference || column.semantic_status) ? 1 : 0;
    if (column.semantic_status === 'reviewed_business_semantics') counts.reviewed += 1;
    else if (column.semantic_status === 'inferred_candidate') counts.candidate += 1;
    else if (!column.semantic_status && !(column.semantic_field || column.semantic_labels || column.business_role || column.semantic_inference)) counts.blank += 1;
    return counts;
  }, { evidence: 0, reviewed: 0, candidate: 0, blank: 0 });
}

const EMPTY_SRC_FORM = {
  display_name: '', description: '',
  synonyms: '', suggested_analyses: '',
};

const EMPTY_COL_FORM = {
  semantic_domain: '', aliases: '', unit: '', description: '',
};

export default function SemanticLayerTab({ userRole, requestedTarget }: { userRole?: string; requestedTarget?: { sourceKey?: string; tableName?: string } | null }) {
  const canEdit = userRole === 'admin' || userRole === 'analyst';

  const [sources, setSources] = useState<SourceMeta[]>([]);
  const [catalogTables, setCatalogTables] = useState<SemanticCatalogTable[]>([]);
  const [catalogSources, setCatalogSources] = useState<{ source_key: string; source_name?: string; source_type?: string; ingestion_mode?: string }[]>([]);
  const [governedSources, setGovernedSources] = useState<GovernedSemanticSource[]>([]);
  const [selectedSourceKey, setSelectedSourceKey] = useState('');
  const [unregistered, setUnregistered] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TableDetail | null>(null);
  const [domains, setDomains] = useState<{ name: string; description: string }[]>([]);
  const [catalogSearch, setCatalogSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>('');
  const [info, setInfo] = useState<string>('');
  const [activeView, setActiveView] = useState<'catalog' | 'model' | 'preview'>('catalog');
  const [governanceRefreshToken, setGovernanceRefreshToken] = useState(0);
  const [pendingFocus, setPendingFocus] = useState<{ sourceKey?: string; tableName: string } | null>(null);

  // Table-level edit
  const [editingSrc, setEditingSrc] = useState(false);
  const [srcForm, setSrcForm] = useState(EMPTY_SRC_FORM);
  const [nl2sqlEnabled, setNl2sqlEnabled] = useState(true);
  const [nl2sqlPriority, setNl2sqlPriority] = useState(0);

  // Column-level edit (keyed by column name when editing)
  const [editingCol, setEditingCol] = useState<string | null>(null);
  const [colForm, setColForm] = useState(EMPTY_COL_FORM);

  // Preview panel
  const [previewQ, setPreviewQ] = useState('');
  const [previewRes, setPreviewRes] = useState<ResolveResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => { refreshAll(); loadDomains(); }, []);

  useEffect(() => {
    if (!requestedTarget?.tableName) return;
    setActiveView('catalog');
    setPendingFocus({ sourceKey: requestedTarget.sourceKey, tableName: requestedTarget.tableName });
  }, [requestedTarget]);

  // Metadata drill-down uses the same workspace event bus as the other model
  // workbenches.  This keeps one semantic-layer entry point while allowing an
  // operator to jump directly from a unified metadata table to its semantic
  // record without duplicating a second configuration page.
  useEffect(() => {
    const handleWorkspaceUpdate = (rawEvent: Event) => {
      const detail = (rawEvent as CustomEvent).detail || {};
      if (detail.tab !== 'semantic' || !detail.tableName) return;
      setActiveView('catalog');
      setPendingFocus({ sourceKey: detail.sourceKey, tableName: String(detail.tableName) });
    };
    window.addEventListener('gda-workspace-update', handleWorkspaceUpdate);
    return () => window.removeEventListener('gda-workspace-update', handleWorkspaceUpdate);
  }, []);

  useEffect(() => {
    if (!pendingFocus || !catalogTables.length) return;
    const normalized = pendingFocus.tableName.toLocaleLowerCase();
    const match = catalogTables.find(table => {
      const sameTable = String(table.table_name || '').toLocaleLowerCase() === normalized;
      const sameSource = !pendingFocus.sourceKey || table.source_key === pendingFocus.sourceKey;
      return sameTable && sameSource;
    });
    if (!match) return;
    setSelectedSourceKey(match.source_key);
    setPendingFocus(null);
    void selectCatalogTable(match);
  }, [pendingFocus, catalogTables]);

  async function api<T = any>(path: string, opts: RequestInit = {}): Promise<{ ok: boolean; data: T; status: number }> {
    try {
      const resp = await fetch(path, {
        credentials: 'include',
        headers: opts.body ? { 'Content-Type': 'application/json', ...(opts.headers || {}) } : (opts.headers || {}),
        ...opts,
      });
      const data = await resp.json().catch(() => ({}));
      return { ok: resp.ok, data: data as T, status: resp.status };
    } catch (e) {
      return { ok: false, data: { error: String(e) } as any, status: 0 };
    }
  }

  async function refreshAll() {
    setLoading(true);
    setError(''); setInfo('');
    const [a, b, d, e] = await Promise.all([
      api<{ sources: SourceMeta[] }>('/api/semantic/sources'),
      api<{ unregistered: string[] }>('/api/semantic/unregistered'),
      api<{ sources: GovernedSemanticSource[] }>('/api/abu-dhabi/nl2semantic2sql/evidence'),
      api<{ tables: SemanticCatalogTable[]; sources: typeof catalogSources }>('/api/semantic/catalog?limit=1000'),
    ]);
    if (a.ok) setSources(a.data.sources || []);
    if (b.ok) setUnregistered(b.data.unregistered || []);
    if (d.ok) setGovernedSources(d.data.sources || []);
    if (e.ok) {
      setCatalogTables(e.data.tables || []);
      setCatalogSources(e.data.sources || []);
    }
    setLoading(false);
  }

  async function loadDomains() {
    const r = await api<{ domains: { name: string; description: string }[] }>('/api/semantic/domains');
    if (r.ok) setDomains(r.data.domains || []);
  }

  async function selectTable(name: string) {
    setSelected(name);
    setEditingSrc(false); setEditingCol(null);
    const r = await api<TableDetail>(`/api/semantic/sources/${encodeURIComponent(name)}`);
    const catalogTable = catalogTables.find(table => table.table_name === name || table.table_name.split('.').pop() === name);
    const catalogColumns = new Map((catalogTable?.columns || []).map(column => [column.column_name.toLocaleLowerCase(), column]));
    setDetail(r.ok ? { ...r.data, columns: (r.data.columns || []).map(column => ({ ...catalogColumns.get(column.column_name.toLocaleLowerCase()), ...column })) } : null);
    if (r.ok && r.data?.source) {
      setSrcForm({
        display_name: r.data.source.display_name || '',
        description: r.data.source.description || '',
        synonyms: (r.data.source.synonyms || []).join(', '),
        suggested_analyses: (r.data.source.suggested_analyses || []).join(', '),
      });
      setNl2sqlEnabled(r.data.source.nl2sql_enabled !== false);
      setNl2sqlPriority(Number(r.data.source.nl2sql_priority || 0));
    }
  }

  async function selectCatalogTable(table: SemanticCatalogTable) {
    setSelected(table.table_name);
    setEditingSrc(false); setEditingCol(null);
    const r = await api<TableDetail>(`/api/semantic/sources/${encodeURIComponent(table.table_name)}`);
    if (r.ok) {
      const catalogColumns = new Map((table.columns || []).map(column => [column.column_name.toLocaleLowerCase(), column]));
      setDetail({
        ...r.data,
        columns: (r.data.columns || []).map(column => {
          const catalogColumn = catalogColumns.get(column.column_name.toLocaleLowerCase());
          const merged = { ...catalogColumn, ...column };
          // The table detail endpoint may return a legacy empty CRUD row.
          // Keep the non-empty artifact-backed card evidence visible instead
          // of replacing it with an empty string/null from that row.
          for (const key of ['semantic_domain', 'aliases', 'unit', 'description', 'value_semantics', 'value_domain', 'semantic_field', 'semantic_labels', 'business_role', 'semantic_status']) {
            const detailValue = (column as any)[key];
            const catalogValue = (catalogColumn as any)?.[key];
            if ((detailValue === undefined || detailValue === null || detailValue === '' || (Array.isArray(detailValue) && detailValue.length === 0) || (typeof detailValue === 'object' && detailValue && !Array.isArray(detailValue) && Object.keys(detailValue).length === 0)) && catalogValue !== undefined) {
              (merged as any)[key] = catalogValue;
            }
          }
          return merged;
        }),
      });
      if (r.data?.source) {
        setSrcForm({
          display_name: r.data.source.display_name || '',
          description: r.data.source.description || '',
          synonyms: (r.data.source.synonyms || []).join(', '),
          suggested_analyses: (r.data.source.suggested_analyses || []).join(', '),
        });
        setNl2sqlEnabled(r.data.source.nl2sql_enabled !== false);
        setNl2sqlPriority(Number(r.data.source.nl2sql_priority || 0));
      }
      return;
    }

    // An unregistered table is still a first-class catalog item. Keep its
    // physical schema visible and let the editor create semantic metadata on
    // demand instead of hiding it behind the registry.
    setDetail({
      status: 'success',
      table_name: table.table_name,
      source: null,
      columns: table.columns || [],
    });
    setSrcForm({
      display_name: table.display_name || table.table_name,
      description: table.description || '',
      synonyms: '',
      suggested_analyses: '',
    });
    setNl2sqlEnabled(true);
    setNl2sqlPriority(0);
  }

  async function saveSource() {
    if (!selected) return;
    setSaving(true); setError('');
    const body = {
      display_name: srcForm.display_name.trim(),
      description: srcForm.description.trim(),
      synonyms: srcForm.synonyms.split(',').map(s => s.trim()).filter(Boolean),
      suggested_analyses: srcForm.suggested_analyses.split(',').map(s => s.trim()).filter(Boolean),
      nl2sql_enabled: nl2sqlEnabled,
      nl2sql_priority: nl2sqlPriority,
    };
    const r = await api(`/api/semantic/sources/${encodeURIComponent(selected)}`, {
      method: 'PUT', body: JSON.stringify(body),
    });
    setSaving(false);
    if (r.ok) { setEditingSrc(false); await selectTable(selected); await refreshAll(); }
    else setError(r.data?.error || '保存失败');
  }

  async function deleteSource(name: string) {
    if (!confirm(`确定删除 ${name} 的所有语义标注？此操作不可逆。`)) return;
    const r = await api(`/api/semantic/sources/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (r.ok) {
      setSelected(null); setDetail(null);
      setInfo(`已删除 ${name}`);
      await refreshAll();
    } else setError(r.data?.error || '删除失败');
  }

  function beginEditCol(col: ColumnAnnotation) {
    setEditingCol(col.column_name);
    setColForm({
      semantic_domain: col.semantic_domain || '',
      aliases: (col.aliases || []).join(', '),
      unit: col.unit || '',
      description: col.description || '',
    });
  }

  async function saveCol() {
    if (!selected || !editingCol) return;
    setSaving(true); setError('');
    const body = {
      semantic_domain: colForm.semantic_domain.trim() || null,
      aliases: colForm.aliases.split(',').map(s => s.trim()).filter(Boolean),
      unit: colForm.unit.trim(),
      description: colForm.description.trim(),
    };
    const r = await api(
      `/api/semantic/annotations/${encodeURIComponent(selected)}/${encodeURIComponent(editingCol)}`,
      { method: 'PUT', body: JSON.stringify(body) },
    );
    setSaving(false);
    if (r.ok) { setEditingCol(null); await selectTable(selected); }
    else setError(r.data?.error || '保存失败');
  }

  async function deleteCol(colName: string) {
    if (!selected) return;
    if (!confirm(`删除 ${selected}.${colName} 的语义标注？`)) return;
    const r = await api(
      `/api/semantic/annotations/${encodeURIComponent(selected)}/${encodeURIComponent(colName)}`,
      { method: 'DELETE' },
    );
    if (r.ok) await selectTable(selected);
    else setError(r.data?.error || '删除失败');
  }

  async function autoRegisterOne(table: string) {
    setInfo(`正在注册 ${table}...`);
    const r = await api('/api/semantic/auto-register', {
      method: 'POST', body: JSON.stringify({ tables: [table] }),
    });
    if (r.ok) {
      setInfo(`${table}: ${JSON.stringify(r.data.summary)}`);
      await refreshAll();
    } else setError(r.data?.error || '注册失败');
  }

  async function autoRegisterAll() {
    if (!unregistered.length) { setInfo('所有表都已注册'); return; }
    if (!confirm(`将自动注册 ${unregistered.length} 张未注册表。继续？`)) return;
    setSaving(true); setInfo('正在批量注册...');
    const r = await api('/api/semantic/auto-register', { method: 'POST', body: '{}' });
    setSaving(false);
    if (r.ok) {
      const s = r.data.summary || {};
      setInfo(`注册完成: ${s.ok} 成功 / ${s.skipped} 跳过 / ${s.failed} 失败`);
      await refreshAll();
    } else setError(r.data?.error || '注册失败');
  }

  async function runPreview() {
    if (!previewQ.trim()) return;
    setPreviewLoading(true); setError('');
    const r = await api<ResolveResult>('/api/semantic/resolve-preview', {
      method: 'POST', body: JSON.stringify({ question: previewQ.trim() }),
    });
    setPreviewLoading(false);
    if (r.ok) setPreviewRes(r.data);
    else { setError(r.data?.error || '预览失败'); setPreviewRes(null); }
  }

  const sourceProfiles = useMemo(() => {
    return catalogSources.map(source => ({
      key: source.source_key,
      label: source.source_name || source.source_key,
      sourceType: source.source_type || '数据源',
      ingestionMode: source.ingestion_mode || 'registered_asset',
      assets: catalogTables.filter(table => table.source_key === source.source_key),
      semantic: governedSources.find(item => String(item.source?.source_id || '') === String(source.source_key.replace(/^source:/, ''))),
    })).sort((a, b) => a.label.localeCompare(b.label));
  }, [catalogSources, catalogTables, governedSources]);

  const governanceScopes = useMemo(() => governedSources.filter(source => source.semantic_admin_scope).map(source => ({ key: source.semantic_admin_scope as string, label: source.label || source.key || source.semantic_admin_scope as string })), [governedSources]);

  const filteredCatalogTables = useMemo(() => {
    const needle = catalogSearch.trim().toLocaleLowerCase();
    return catalogTables.filter(table => {
      if (selectedSourceKey && table.source_key !== selectedSourceKey) return false;
      if (!needle) return true;
      const tableText = [
        table.table_name, table.display_name, table.description, table.source_name,
        ...(table.columns || []).flatMap(column => [column.column_name, column.semantic_domain, column.description, ...(column.aliases || [])]),
      ].filter(Boolean).join(' ').toLocaleLowerCase();
      return tableText.includes(needle);
    });
  }, [catalogTables, catalogSearch, selectedSourceKey]);

  const catalogSemanticStats = useMemo(() => filteredCatalogTables.reduce((stats, table) => {
    const counts = semanticColumnCounts(table.columns || []);
    stats.evidence += counts.evidence;
    stats.reviewed += counts.reviewed;
    stats.candidate += counts.candidate;
    stats.blank += counts.blank;
    return stats;
  }, { evidence: 0, reviewed: 0, candidate: 0, blank: 0 }), [filteredCatalogTables]);

  return (
    <div className="semantic-layer-tab">
      <section className="semantic-workspace-intro">
        <div>
          <span className="semantic-workspace-kicker">SEMANTIC WORKSPACE</span>
          <h3>统一语义层工作区</h3>
          <p>从同一语义工作区切换目录语义、业务模型和解析验证；数据源、表和字段均来自统一目录。</p>
        </div>
        <div className="semantic-workspace-stats"><strong>{catalogSources.length || sourceProfiles.length}</strong><span>数据源</span><strong>{catalogTables.length}</strong><span>目录表</span><strong>{sources.length}</strong><span>已注册表</span></div>
      </section>

      <nav className="semantic-view-tabs" aria-label="语义工作区视图">
        <button type="button" className={activeView === 'catalog' ? 'active' : ''} onClick={() => setActiveView('catalog')}><strong>目录语义</strong><span>全库表、字段与语义标注</span></button>
        <button type="button" className={activeView === 'model' ? 'active' : ''} onClick={() => setActiveView('model')}><strong>业务模型</strong><span>资产、关系与指标合同</span></button>
        <button type="button" className={activeView === 'preview' ? 'active' : ''} onClick={() => setActiveView('preview')}><strong>解析验证</strong><span>检查语义如何参与问数</span></button>
      </nav>

      <SemanticInteropPanel userRole={userRole} defaultKind="semantic-layer" defaultSource={selectedSourceKey || undefined} />

      {activeView === 'catalog' && <section className="semantic-catalog-workspace">
        <div className="semantic-catalog-heading">
          <div><span className="semantic-workspace-kicker">TECHNICAL SEMANTICS</span><h4>全库表与字段语义</h4><p>表来自统一元数据目录，已注册和未注册表都可查看物理字段；注册后才能保存表级和字段级语义。</p></div>
          <div className="semantic-catalog-actions">
            <select value={selectedSourceKey} onChange={event => setSelectedSourceKey(event.target.value)} aria-label="按数据源筛选">
              <option value="">全部数据源</option>
              {catalogSources.map(source => <option key={source.source_key} value={source.source_key}>{source.source_name || source.source_key}</option>)}
            </select>
            {canEdit && <button className="btn-primary" disabled={saving || !unregistered.length} onClick={autoRegisterAll}>一键注册未登记表 ({unregistered.length})</button>}
            <button className="btn-secondary" onClick={refreshAll}>刷新目录</button>
          </div>
        </div>
        <div className="semantic-toolbar">
          <div className="semantic-toolbar-info">显示 <b>{filteredCatalogTables.length}</b> / {catalogTables.length} 张表 · 语义证据 <b>{catalogSemanticStats.evidence}</b> · 业务已审核 <b>{catalogSemanticStats.reviewed}</b> · 待业务审核 <b>{catalogSemanticStats.candidate}</b> · 空白 <b>{catalogSemanticStats.blank}</b></div>
          <input type="text" placeholder="搜索表、字段、别名或描述" value={catalogSearch} onChange={e => setCatalogSearch(e.target.value)} className="semantic-search" />
          <span className="semantic-toolbar-hint">标准导入/导出请使用上方“标准互操作”；所有外部文件先进入不可执行草稿。</span>
        </div>
        <div className="semantic-status-legend"><span><b>语义证据</b>：技术目录、推断或字典已形成可追溯标注</span><span><b>业务已审核</b>：可进入相应执行合同</span><span><b>待业务审核</b>：可浏览、可提交审核，但不自动进入生产 SQL</span></div>
        {error && <div className="semantic-alert error">⚠ {error}</div>}
        {info && <div className="semantic-alert info">{info}</div>}
        <div className="semantic-body">
          <div className="semantic-sources-list">
            <div className="semantic-list-section-title">全库目录 ({filteredCatalogTables.length})</div>
            {loading && <div className="semantic-loading">加载中...</div>}
            {!loading && !filteredCatalogTables.length && <div className="semantic-empty">当前筛选条件下暂无表。</div>}
            {filteredCatalogTables.map(table => (
              <button type="button" key={`${table.source_key}:${table.table_name}`} className={`semantic-source-item ${selected === table.table_name ? 'active' : ''}`} onClick={() => void selectCatalogTable(table)}>
                <span className="semantic-source-name">{table.display_name || table.table_name}</span>
                <span className="semantic-source-sub">{table.table_name} · {table.columns.length} 字段 · 语义证据 {semanticColumnCounts(table.columns || []).evidence} · 业务已审核 {semanticColumnCounts(table.columns || []).reviewed} · 待审核 {semanticColumnCounts(table.columns || []).candidate} · {table.semantic_status === 'reviewed_business_semantics' ? '语义已审核' : table.semantic_status === 'excluded' ? '已排除' : '待业务审核'}</span>
                <span className="semantic-source-sub">{table.source_name || '未命名数据源'} · {table.ingestion_mode === 'virtual_source' ? '虚拟入湖' : table.ingestion_mode || '目录资产'}{!sources.some(source => source.table_name === table.table_name) ? ' · 未注册' : ''} · 字典{table.dictionary_evidence?.support_status === 'dictionary_exact_supported' ? '完整支持' : table.dictionary_evidence?.support_status === 'dictionary_partial_supported' ? '部分支持' : table.dictionary_evidence?.support_status === 'dictionary_unmatched' ? '未对齐' : '无证据'}</span>
              </button>
            ))}
          </div>

          <div className="semantic-detail">
            {!selected && <div className="semantic-empty">从左侧选择一张表，查看全部字段及其语义标注。<div className="semantic-hint">这里是技术语义工作区：物理字段、类型、可空性和语义别名集中在同一张表中；业务语义治理在本区下方单独管理。</div></div>}
            {selected && detail && <>
              <div className="semantic-section">
                <div className="semantic-section-header"><h4>表级语义: {selected}</h4>{canEdit && !editingSrc && <div>{detail.source ? <><button className="btn-secondary" onClick={() => setEditingSrc(true)}>编辑</button><button className="btn-danger" onClick={() => deleteSource(selected)}>删除</button></> : <button className="btn-primary" onClick={() => setEditingSrc(true)}>注册语义</button>}</div>}</div>
                {!editingSrc && detail.source && <div className="semantic-meta"><div><b>显示名:</b> {detail.source.display_name || <i>未设置</i>}</div><div><b>描述:</b> {detail.source.description || <i>未设置</i>}</div><div><b>同义词:</b> {(detail.source.synonyms || []).join(', ') || <i>无</i>}</div><div><b>建议分析:</b> {(detail.source.suggested_analyses || []).join(', ') || <i>无</i>}</div>{detail.source.geometry_type && <div><b>几何:</b> {detail.source.geometry_type} (SRID={detail.source.srid})</div>}<div><b>参与智能问数:</b> {detail.source.nl2sql_enabled === false ? '否（仅保留注册与血缘）' : '是'}</div><div><b>问数优先级:</b> {detail.source.nl2sql_priority ?? 0}</div></div>}
                {!editingSrc && !detail.source && <div className="semantic-meta"><strong>此表尚未注册语义配置。</strong><span>物理字段已可浏览，点击“注册语义”后可维护表级说明、问数策略和字段标注。</span></div>}
                {editingSrc && <div className="semantic-form"><label>显示名<input type="text" value={srcForm.display_name} onChange={e => setSrcForm(f => ({ ...f, display_name: e.target.value }))} /></label><label>描述<textarea rows={2} value={srcForm.description} onChange={e => setSrcForm(f => ({ ...f, description: e.target.value }))} /></label><label>同义词（逗号分隔）<input type="text" value={srcForm.synonyms} onChange={e => setSrcForm(f => ({ ...f, synonyms: e.target.value }))} /></label><label>建议分析（逗号分隔）<input type="text" value={srcForm.suggested_analyses} onChange={e => setSrcForm(f => ({ ...f, suggested_analyses: e.target.value }))} /></label><label className="semantic-checkbox-label"><input type="checkbox" checked={nl2sqlEnabled} onChange={e => setNl2sqlEnabled(e.target.checked)} />参与智能问数</label><label>问数优先级（-1000 至 1000）<input type="number" min={-1000} max={1000} step={1} value={nl2sqlPriority} onChange={e => setNl2sqlPriority(Number(e.target.value || 0))} /></label><div><button className="btn-primary" disabled={saving} onClick={saveSource}>{saving ? '保存中...' : '保存'}</button><button className="btn-secondary" onClick={() => setEditingSrc(false)}>取消</button></div></div>}
              </div>
              <div className="semantic-section"><div className="semantic-section-header"><h4>字段语义 ({(detail.columns || []).length} 列)</h4><span className="semantic-detail-evidence">状态来自统一元数据语义证据；推断候选不会自动获得执行权限。</span></div><div className="semantic-column-scroll"><table className="semantic-cols"><thead><tr><th>列名</th><th>数据类型</th><th>可空</th><th>业务语义</th><th>角色</th><th>状态 / 证据</th><th>值域 / 来源</th><th>Domain</th><th>别名</th><th>单位</th><th>描述</th>{canEdit && <th>操作</th>}</tr></thead><tbody>{(detail.columns || []).map(c => { const isEditing = editingCol === c.column_name; const labels = c.semantic_labels || {}; const status = c.semantic_status || ''; return isEditing ? <tr key={c.column_name} className="semantic-col-editing"><td><b>{c.column_name}</b></td><td colSpan={canEdit ? 11 : 10}><div className="semantic-inline-form"><div><label>Domain<select value={colForm.semantic_domain} onChange={e => setColForm(f => ({ ...f, semantic_domain: e.target.value }))}><option value="">(无)</option>{domains.map(d => <option key={d.name} value={d.name}>{d.name} - {d.description}</option>)}</select></label><label>单位<input type="text" value={colForm.unit} onChange={e => setColForm(f => ({ ...f, unit: e.target.value }))} /></label></div><label>别名（逗号分隔）<input type="text" value={colForm.aliases} onChange={e => setColForm(f => ({ ...f, aliases: e.target.value }))} /></label><label>描述 / 使用规则<textarea rows={2} value={colForm.description} onChange={e => setColForm(f => ({ ...f, description: e.target.value }))} /></label><div><button className="btn-primary" disabled={saving} onClick={saveCol}>保存</button><button className="btn-secondary" onClick={() => setEditingCol(null)}>取消</button></div></div></td></tr> : <tr key={c.column_name}><td><b>{c.column_name}</b>{c.is_geometry && <span className="semantic-geom-badge"> GEOM</span>}</td><td>{c.data_type || ''}</td><td>{c.nullable === false ? '否' : '是'}</td><td>{labels.zh || labels.en || labels.ar || c.semantic_field || <i>—</i>}</td><td>{c.business_role || <i>—</i>}</td><td><span className={`metadata-semantic-status metadata-semantic-${status}`}>{status === 'reviewed_business_semantics' ? '已审核' : status === 'inferred_candidate' ? `推断候选${c.semantic_inference?.confidence ? `·${c.semantic_inference.confidence}` : ''}` : status || '未标注'}</span>{c.dictionary_evidence?.supported && <small className="semantic-evidence-tag">字典</small>}</td><td><ValueDomainEvidence column={c} /></td><td>{c.semantic_domain || <i>—</i>}</td><td>{(c.aliases || []).join(', ') || <i>—</i>}</td><td>{c.unit || <i>—</i>}</td><td className="semantic-col-desc">{c.description || <i>—</i>}</td>{canEdit && <td><button className="btn-mini" onClick={() => detail.source ? beginEditCol(c) : setInfo('请先注册此表的语义配置，再编辑字段标注。')}>编辑</button>{c.semantic_domain && detail.source && <button className="btn-mini btn-danger" onClick={() => deleteCol(c.column_name)}>清除</button>}</td>}</tr>; })}</tbody></table></div></div>
            </>}
          </div>
        </div>
      </section>}

      {activeView === 'model' && <section className="semantic-source-registry">
        <div className="semantic-registry-heading"><div><h4>数据源范围与语义证据</h4><span>数据源卡片只负责范围筛选和证据摘要，不替代表/字段目录。</span></div><select value={selectedSourceKey} onChange={event => setSelectedSourceKey(event.target.value)}><option value="">全部数据源</option>{sourceProfiles.map(profile => <option key={profile.key} value={profile.key}>{profile.label}</option>)}</select></div>
        <div className="semantic-source-registry-grid">{sourceProfiles.map(profile => { const semantic = profile.semantic?.semantic_layer || {}; const semanticAssets = semantic.semantic_assets || semantic.assets || []; const queue = profile.semantic?.business_semantic_review_queue?.coverage || {}; const benchmarkQueue = profile.semantic?.business_benchmark_review_queue?.coverage || {}; const freeze = profile.semantic?.technical_freeze_coverage?.metrics || {}; const dictionary = profile.semantic?.dictionary_evidence?.coverage || {}; return <button type="button" key={profile.key} className={`semantic-source-registry-card ${selectedSourceKey === profile.key ? 'active' : ''}`} onClick={() => setSelectedSourceKey(selectedSourceKey === profile.key ? '' : profile.key)}><strong>{profile.label}</strong><span>{profile.sourceType} · {profile.ingestionMode === 'virtual_source' ? '虚拟入湖' : profile.ingestionMode}</span><small>{profile.assets.length} 个目录资产 · {semanticAssets.length} 个业务资产 · 已审核关系 {queue.reviewed_relationship_count || 0}/{queue.relationship_task_count || 0}（待审核 {queue.review_required_relationship_count || 0}）</small><small>{profile.semantic?.technical_catalog?.field_count || 0} 个字段 · 业务语义已审核 {queue.reviewed_field_count || 0}/{queue.field_task_count || 0} · 技术冻结 {freeze.frozen_count || 0}/{freeze.candidate_count || 0}</small><small>字典支持字段：完整 {dictionary.dictionary_exact_supported_field_count || 0} · 部分 {dictionary.dictionary_partial_supported_field_count || 0} · 待补证据 {dictionary.no_dictionary_evidence_field_count || 0}</small><small>业务 benchmark 题位 {benchmarkQueue.question_slot_count || 0} · 三语言变体 {benchmarkQueue.language_variant_count || 0}</small></button>; })}{!sourceProfiles.length && <div className="semantic-empty">统一元数据目录暂无可关联数据源。</div>}</div>
        {selectedSourceKey && (() => { const profile = sourceProfiles.find(item => item.key === selectedSourceKey); const semantic = profile?.semantic?.semantic_layer || {}; const semanticAssets = semantic.semantic_assets || semantic.assets || []; const queue = profile?.semantic?.business_semantic_review_queue?.coverage || {}; const freeze = profile?.semantic?.technical_freeze_coverage?.metrics || {}; const dictionary = profile?.semantic?.dictionary_evidence || {}; return profile?.semantic ? <div className="semantic-source-evidence"><div><strong>{profile.semantic.label || profile.label}</strong><span>{profile.semantic.source?.database_name || '已绑定数据源'} · 版本 {semantic.version || '-'}</span><span>状态：{semantic.status || '已登记'} · {profile.semantic.technical_catalog?.resource_count || 0} 张元数据表 · {profile.semantic.technical_catalog?.field_count || 0} 个元数据字段</span></div><div className="semantic-source-evidence-progress"><span>业务语义：{queue.reviewed_table_count || 0}/{queue.table_task_count || profile.assets.length} 表，{queue.reviewed_field_count || 0}/{queue.field_task_count || 0} 字段已审核</span><span>关系审核：{queue.reviewed_relationship_count || 0}/{queue.relationship_task_count || 0} 已审核，待审核 {queue.review_required_relationship_count || 0}</span><span>技术验证：{freeze.frozen_count || 0}/{freeze.candidate_count || 0} 已冻结，待处理 {freeze.pending_count || 0}，失败 {freeze.failed_count || 0}</span><span>字典证据：{dictionary.compatibility?.mode === 'schema_equivalent_rebind' ? 'schema 等价重绑定' : dictionary.compatibility?.mode === 'exact_fingerprint' ? '精确指纹绑定' : '未登记'}；完整支持 {dictionary.coverage?.dictionary_exact_supported_field_count || 0}，部分支持 {dictionary.coverage?.dictionary_partial_supported_field_count || 0}，无证据 {dictionary.coverage?.no_dictionary_evidence_field_count || 0}</span></div><div className="semantic-source-evidence-assets">{semanticAssets.slice(0, 8).map((asset: any) => <details key={String(asset.asset_id)}><summary>{asset.labels?.zh || asset.labels?.en || asset.asset_id}<span>{(asset.fields || []).length} 个语义字段 · {asset.review_status || '待审核'}</span></summary><div>{(asset.fields || []).slice(0, 12).map((field: any) => <span key={`${asset.asset_id}:${field.semantic_field || field.physical_field}`}><code>{field.physical_field || field.semantic_field}</code> {field.labels?.zh || field.labels?.en || ''}</span>)}</div></details>)}</div></div> : <div className="semantic-source-evidence empty">该数据源已进入统一目录，尚未提供版本化业务语义证据；全库表和字段仍可在上方目录中浏览。</div>; })()}
      </section>}

      {activeView === 'model' && governanceScopes.length > 0 && <section className="semantic-governance-workspace"><div className="semantic-registry-heading"><div><span className="semantic-workspace-kicker">BUSINESS GOVERNANCE</span><h4>业务语义治理</h4><span>业务资产、语义字段、关系和指标合同使用独立版本草稿与审核发布。</span></div></div><SemanticGovernancePanel defaultScope={governanceScopes[0].key} scopeOptions={governanceScopes} refreshToken={governanceRefreshToken} /></section>}

      {activeView === 'model' && governanceScopes.length > 0 && <SemanticReviewQueuePanel scopeOptions={governanceScopes} onDraftCreated={() => setGovernanceRefreshToken(value => value + 1)} />}

      {activeView === 'model' && governanceScopes.length > 0 && <BenchmarkReviewQueuePanel scopeOptions={governanceScopes} />}

      {activeView === 'preview' && <section className="semantic-section semantic-preview-section"><div className="semantic-section-header"><div><h4>解析验证</h4><span>验证当前语义配置如何参与解析</span></div></div><div className="semantic-preview"><div><input type="text" placeholder="输入自然语言问题，如：统计水田的真实面积（公顷）" value={previewQ} onChange={e => setPreviewQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && runPreview()} /><button className="btn-primary" disabled={previewLoading} onClick={runPreview}>{previewLoading ? '解析中...' : '解析'}</button></div>{previewRes && <div className="semantic-preview-result">{previewRes.sources && previewRes.sources.length > 0 && <div><b>匹配的表:</b> {previewRes.sources.map((s: any) => s.table_name || s).join(', ')}</div>}{previewRes.sql_filters && previewRes.sql_filters.length > 0 && <div><b>SQL 过滤提示:</b><pre className="semantic-sql-filters">{previewRes.sql_filters.join('\n')}</pre></div>}{previewRes.region_sql && previewRes.region_sql.length > 0 && <div><b>区域过滤:</b><pre>{previewRes.region_sql.join('\n')}</pre></div>}{previewRes.hierarchy_matches && previewRes.hierarchy_matches.length > 0 && <div><b>层级匹配:</b><pre>{JSON.stringify(previewRes.hierarchy_matches, null, 2)}</pre></div>}<details><summary>完整 JSON</summary><pre>{JSON.stringify(previewRes, null, 2)}</pre></details></div>}</div></section>}
    </div>
  );
}
