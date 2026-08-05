import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow, Background, Controls, MiniMap, MarkerType,
  type Edge, type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  AlertTriangle, Braces, CheckCircle2, ChevronLeft, ChevronRight,
  Database, Download, FileJson, Filter, GitCompareArrows,
  Layers3, Network, RefreshCw, Search, ShieldCheck, X,
} from 'lucide-react';
import OntologyConceptNode from './ontology/OntologyConceptNode';
import './ontology/ontology.css';
import './ontology/value-domains.css';

type Row = Record<string, any>;

interface OntologyStatus {
  available: boolean;
  backend: string;
  package_id: string;
  semantic_version: string;
  content_sha256: string;
  generated_at: string;
  model_profile: string;
  stats: Record<string, number>;
  validation: { conforms: boolean; issue_count: number; severity_counts?: Record<string, number> };
  projection: { rdf: boolean; shacl: boolean; sparql_endpoint: boolean };
}

interface DomainSummary {
  domain_id: string;
  label: string;
  concept_count: number;
  domain_class_count: number;
  standard_feature_count: number;
  ea_schema_count: number;
  property_count: number;
  mapping_count: number;
  confirmed_mapping_count: number;
  strict_coverage: number;
}

type ViewMode = 'graph' | 'mappings' | 'validation';
type DetailMode = 'fields' | 'relations' | 'provenance';
const nodeTypes = { ontologyConcept: OntologyConceptNode };
const DOMAIN_MODEL_KINDS = 'DomainClass,ProcessClass,StateClass,RoleClass,InformationClass,ObservationClass';
const KIND_LABELS: Record<string, string> = {
  DomainClass: '领域实体类', ProcessClass: '过程类', StateClass: '状态类',
  RoleClass: '角色类', InformationClass: '信息类', ObservationClass: '观测类',
  ReferenceScheme: '参考分类', ReferenceConcept: '分类代码', SchemaArtifact: '数据结构制品',
  Domain: '领域', StandardDocument: '标准', Package: 'EA 包', FeatureType: '标准要素',
  DatasetSchema: 'EA 数据结构', ObjectType: '对象类型', ActionType: '行动类型',
  FunctionType: '函数类型', InterfaceType: '接口类型', CRS: '坐标系', MetaClass: '元类',
  ValueDomain: '标准值域', ValueDomainMember: '代码项',
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'include', ...init });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
  return payload as T;
}

const count = (value?: number) => new Intl.NumberFormat('zh-CN').format(value || 0);
function sourceLabel(source?: string) {
  if (source === 'standard') return '自然资源标准';
  if (source === 'enterprise_architect') return 'Enterprise Architect';
  if (source === 'gda_core') return 'Cognitive Runtime';
  if (source === 'curated_domain') return '策划领域模型';
  return source || '-';
}

export default function OntologyTab() {
  const [status, setStatus] = useState<OntologyStatus | null>(null);
  const [domains, setDomains] = useState<DomainSummary[]>([]);
  const [selectedDomain, setSelectedDomain] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('graph');
  const [graph, setGraph] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] });
  const [graphMeta, setGraphMeta] = useState<Row>({});
  const [selectedConceptId, setSelectedConceptId] = useState('');
  const [concept, setConcept] = useState<Row | null>(null);
  const [properties, setProperties] = useState<Row[]>([]);
  const [propertyTotal, setPropertyTotal] = useState(0);
  const [relations, setRelations] = useState<Row[]>([]);
  const [detailMode, setDetailMode] = useState<DetailMode>('fields');
  const [query, setQuery] = useState('');
  const [kindFilter, setKindFilter] = useState(DOMAIN_MODEL_KINDS);
  const [sourceFilter, setSourceFilter] = useState('');
  const [searchResults, setSearchResults] = useState<Row[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchOpen, setSearchOpen] = useState(false);
  const [mappings, setMappings] = useState<Row[]>([]);
  const [mappingTotal, setMappingTotal] = useState(0);
  const [mappingStatus, setMappingStatus] = useState('');
  const [mappingOffset, setMappingOffset] = useState(0);
  const [validation, setValidation] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const searchTimer = useRef<number | undefined>();

  const loadBootstrap = useCallback(async () => {
    setLoading(true); setMessage('');
    try {
      const [statusData, domainData] = await Promise.all([
        api<OntologyStatus>('/api/ontology/status'),
        api<{ items: DomainSummary[] }>('/api/ontology/domains'),
      ]);
      setStatus(statusData); setDomains(domainData.items || []);
    } catch (error) { setMessage(error instanceof Error ? error.message : '本体服务不可用'); }
    finally { setLoading(false); }
  }, []);

  const loadGraph = useCallback(async (rootId = '') => {
    setLoading(true); setMessage('');
    try {
      const params = new URLSearchParams({ depth: rootId ? '2' : '1', limit: rootId ? '180' : '250' });
      if (rootId) params.set('root_id', rootId); else if (selectedDomain) params.set('domain_id', selectedDomain);
      const data = await api<Row>(`/api/ontology/graph?${params}`);
      const edges = (data.edges || []).map((edge: Edge & { data?: Row }) => ({
        ...edge, type: 'default', markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13 },
        style: {
          stroke: edge.data?.mappingStatus === 'conflict' ? '#dc2626'
            : edge.data?.mappingStatus === 'confirmed' ? '#0f766e'
              : edge.data?.relationType === 'contains' ? '#64748b' : '#2563eb',
          strokeWidth: edge.data?.mappingStatus ? 2 : 1.2,
          strokeDasharray: edge.data?.mappingStatus === 'conflict' ? '5 4' : undefined,
        }, labelStyle: { fontSize: 10, fill: '#475569' },
      }));
      setGraph({ nodes: data.nodes || [], edges }); setGraphMeta(data);
    } catch (error) { setMessage(error instanceof Error ? error.message : '图谱加载失败'); }
    finally { setLoading(false); }
  }, [selectedDomain]);

  const loadConcept = useCallback(async (conceptId: string) => {
    if (!conceptId) return;
    setSelectedConceptId(conceptId); setMessage('');
    try {
      const encoded = encodeURIComponent(conceptId);
      const [detail, fields, relationData] = await Promise.all([
        api<Row>(`/api/ontology/concept?concept_id=${encoded}`),
        api<Row>(`/api/ontology/properties?concept_id=${encoded}&limit=200`),
        api<Row>(`/api/ontology/relations?concept_id=${encoded}&limit=200`),
      ]);
      setConcept(detail); setProperties(fields.items || []); setPropertyTotal(fields.total || 0);
      setRelations(relationData.items || []);
    } catch (error) { setMessage(error instanceof Error ? error.message : '概念加载失败'); }
  }, []);

  useEffect(() => {
    const handleWorkspaceUpdate = (rawEvent: Event) => {
      const detail = (rawEvent as CustomEvent).detail || {};
      if (detail.tab !== 'ontology') return;
      if ((window as any).__pendingGdaWorkspaceUpdate === detail) {
        delete (window as any).__pendingGdaWorkspaceUpdate;
      }
      if (detail.view === 'mappings') {
        setViewMode('mappings');
        return;
      }
      const conceptId = String(detail.concept_id || '').trim();
      if (!conceptId) return;
      setViewMode('graph');
      loadConcept(conceptId);
      loadGraph(conceptId);
    };
    window.addEventListener('gda-workspace-update', handleWorkspaceUpdate);
    const pending = (window as any).__pendingGdaWorkspaceUpdate;
    if (pending?.tab === 'ontology') {
      handleWorkspaceUpdate(new CustomEvent('gda-workspace-update', { detail: pending }));
    }
    return () => window.removeEventListener('gda-workspace-update', handleWorkspaceUpdate);
  }, [loadConcept, loadGraph]);

  const loadMappings = useCallback(async () => {
    setLoading(true); setMessage('');
    try {
      const params = new URLSearchParams({ offset: String(mappingOffset), limit: '80' });
      if (selectedDomain) params.set('domain_id', selectedDomain); if (mappingStatus) params.set('status', mappingStatus);
      const data = await api<Row>(`/api/ontology/mappings?${params}`);
      setMappings(data.items || []); setMappingTotal(data.total || 0);
    } catch (error) { setMessage(error instanceof Error ? error.message : '映射加载失败'); }
    finally { setLoading(false); }
  }, [mappingOffset, mappingStatus, selectedDomain]);

  const loadValidation = useCallback(async () => {
    setLoading(true); setMessage('');
    try { setValidation(await api<Row>('/api/ontology/validation')); }
    catch (error) { setMessage(error instanceof Error ? error.message : '校验报告加载失败'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadBootstrap(); }, [loadBootstrap]);
  useEffect(() => {
    if (!status) return;
    if (viewMode === 'graph') loadGraph(); else if (viewMode === 'mappings') loadMappings(); else loadValidation();
  }, [status, selectedDomain, viewMode, loadGraph, loadMappings, loadValidation]);

  useEffect(() => {
    window.clearTimeout(searchTimer.current);
    if (!query.trim()) { setSearchResults([]); setSearchOpen(false); return; }
    searchTimer.current = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: query.trim(), limit: '40' });
        if (selectedDomain) params.set('domain_id', selectedDomain); if (kindFilter) params.set('kinds', kindFilter);
        if (sourceFilter) params.set('source_system', sourceFilter);
        const data = await api<Row>(`/api/ontology/concepts?${params}`);
        setSearchResults(data.items || []); setSearchTotal(data.total || 0); setSearchOpen(true);
      } catch (error) { setMessage(error instanceof Error ? error.message : '检索失败'); }
    }, 240);
    return () => window.clearTimeout(searchTimer.current);
  }, [query, selectedDomain, kindFilter, sourceFilter]);

  const selectedDomainData = domains.find(domain => domain.domain_id === selectedDomain);
  const visibleIssues = (validation?.issues || []).slice(0, 500);
  const graphTitle = selectedConceptId && concept ? concept.pref_label
    : selectedDomainData ? `${selectedDomainData.domain_id} ${selectedDomainData.label}` : '全域核心模型';
  const minimapColor = useCallback((node: Node) => {
    const kind = (node.data as Row)?.kind;
    return kind === 'DomainClass' ? '#0f766e' : kind === 'ProcessClass' ? '#b45309'
      : kind === 'StateClass' ? '#2563eb' : kind === 'InformationClass' ? '#7c3aed'
        : kind === 'RoleClass' ? '#be185d' : '#64748b';
  }, []);
  const graphStats = useMemo(() => `${count(graphMeta.node_count)} 节点 · ${count(graphMeta.edge_count)} 关系`, [graphMeta]);

  if (loading && !status) return <div className="ontology-state"><RefreshCw className="spin" size={18} />正在加载本体</div>;

  return <div className="ontology-workbench">
    <header className="ontology-header">
      <div className="ontology-title"><Network size={18} /><div><strong>自然资源“一张图”本体</strong><span>v{status?.semantic_version || '-'}</span></div></div>
      <div className="ontology-kpis"><span><b>{count(status?.stats?.domain_class_count)}</b>领域类</span><span><b>{count(status?.stats?.relation_count)}</b>语义关系</span><span><b>{count(status?.stats?.schema_artifact_count)}</b>数据制品</span><span><b>{count(status?.stats?.confirmed_mapping_count)}</b>确认映射</span></div>
      <div className="ontology-header-actions">
        <span className={`ontology-conformance ${status?.validation?.conforms ? 'ok' : 'error'}`}>{status?.validation?.conforms ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}{status?.validation?.conforms ? '发布门通过' : '发布门失败'}</span>
        <button title="刷新" onClick={loadBootstrap}><RefreshCw size={15} /></button>
        <div className="ontology-export-menu"><button title="导出本体"><Download size={15} /></button><div>
          <a href="/api/ontology/export/turtle"><Network size={13} />Turtle</a><a href="/api/ontology/export/shacl"><ShieldCheck size={13} />SHACL</a>
          <a href="/api/ontology/export/jsonld-context"><FileJson size={13} />JSON-LD</a><a href="/api/ontology/export/manifest"><Braces size={13} />Manifest</a>
        </div></div>
      </div>
    </header>

    <div className="ontology-toolbar">
      <div className="ontology-segments"><button className={viewMode === 'graph' ? 'active' : ''} onClick={() => setViewMode('graph')}><Network size={14} />图谱</button><button className={viewMode === 'mappings' ? 'active' : ''} onClick={() => setViewMode('mappings')}><GitCompareArrows size={14} />映射</button><button className={viewMode === 'validation' ? 'active' : ''} onClick={() => setViewMode('validation')}><ShieldCheck size={14} />校验</button></div>
      <div className="ontology-search-wrap"><Search size={15} /><input value={query} onChange={event => setQuery(event.target.value)} onFocus={() => query && setSearchOpen(true)} placeholder="代码、名称、EA GUID" />{query && <button title="清除" onClick={() => setQuery('')}><X size={14} /></button>}
        {searchOpen && <div className="ontology-search-results"><div className="ontology-search-count">{count(searchTotal)} 个结果</div>{searchResults.map(item => <button key={item.concept_id} onClick={() => { setSearchOpen(false); setViewMode('graph'); loadConcept(item.concept_id); loadGraph(item.concept_id); }}><span className={`ontology-kind-dot kind-${item.kind}`} /><span><strong>{item.pref_label}</strong><small>{item.code || item.concept_id}</small></span><em>{KIND_LABELS[item.kind] || item.kind}</em></button>)}</div>}
      </div>
      <label className="ontology-select"><Filter size={13} /><select value={kindFilter} onChange={event => setKindFilter(event.target.value)}><option value={DOMAIN_MODEL_KINDS}>领域模型</option><option value="DomainClass">实体类</option><option value="ProcessClass">过程类</option><option value="StateClass">状态类</option><option value="InformationClass">信息类</option><option value="RoleClass">角色类</option><option value="ObservationClass">观测类</option><option value="ReferenceScheme,ReferenceConcept">参考分类</option><option value="SchemaArtifact">数据结构制品</option><option value="">全部记录</option></select></label>
      <label className="ontology-select"><Database size={13} /><select value={sourceFilter} onChange={event => setSourceFilter(event.target.value)}><option value="">全部来源</option><option value="curated_domain">策划领域模型</option><option value="standard">自然资源标准</option><option value="enterprise_architect">Enterprise Architect</option></select></label>
    </div>
    {message && <div className="ontology-message"><AlertTriangle size={14} />{message}<button onClick={() => setMessage('')}><X size={13} /></button></div>}

    <div className="ontology-body">
      <aside className="ontology-domain-pane"><div className="ontology-pane-title"><Layers3 size={14} /><strong>领域</strong><span>{domains.length}</span></div>
        <button className={`ontology-domain-row ${!selectedDomain ? 'active' : ''}`} onClick={() => { setSelectedDomain(''); setSelectedConceptId(''); setConcept(null); }}><div><b>ALL</b><span>全域核心模型</span></div><small>{count(status?.stats?.domain_class_count)}</small></button>
        <div className="ontology-domain-scroll">{domains.map(domain => <button key={domain.domain_id} className={`ontology-domain-row ${selectedDomain === domain.domain_id ? 'active' : ''}`} onClick={() => { setSelectedDomain(domain.domain_id); setSelectedConceptId(''); setConcept(null); setMappingOffset(0); }}><div><b>{domain.domain_id}</b><span>{domain.label}</span></div><small>{count(domain.domain_class_count)}</small><div className="ontology-coverage" title={`严格映射覆盖 ${(domain.strict_coverage * 100).toFixed(1)}%`}><i style={{ width: `${Math.min(domain.strict_coverage * 100, 100)}%` }} /></div></button>)}</div>
        {selectedDomainData && <div className="ontology-domain-summary"><div><span>标准要素</span><b>{count(selectedDomainData.standard_feature_count)}</b></div><div><span>EA 结构</span><b>{count(selectedDomainData.ea_schema_count)}</b></div><div><span>字段</span><b>{count(selectedDomainData.property_count)}</b></div><div><span>严格覆盖</span><b>{(selectedDomainData.strict_coverage * 100).toFixed(1)}%</b></div></div>}
      </aside>

      <main className="ontology-main-pane">
        {viewMode === 'graph' && <><div className="ontology-view-title"><div><strong>{graphTitle}</strong><span>{graphStats}{graphMeta.truncated ? ' · 已按预算截断' : ''}</span></div>{selectedConceptId && <button onClick={() => { setSelectedConceptId(''); setConcept(null); loadGraph(''); }}><Layers3 size={13} />返回领域</button>}</div><div className="ontology-graph"><ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} onNodeClick={(_, node) => loadConcept(node.id)} fitView fitViewOptions={{ padding: 0.22 }} minZoom={0.08} maxZoom={2.2}><Background color="#263244" gap={22} size={1} /><Controls showInteractive={false} /><MiniMap nodeColor={minimapColor} bgColor="#111827" maskColor="rgba(11, 15, 25, .68)" pannable zoomable /></ReactFlow>{loading && <div className="ontology-loading"><RefreshCw className="spin" size={17} /></div>}</div></>}

        {viewMode === 'mappings' && <div className="ontology-table-view"><div className="ontology-view-title"><div><strong>语义与数据映射</strong><span>{count(mappingTotal)} 条可追溯映射</span></div><label className="ontology-select"><select value={mappingStatus} onChange={event => { setMappingStatus(event.target.value); setMappingOffset(0); }}><option value="">全部状态</option><option value="confirmed">已确认</option><option value="candidate">候选</option><option value="conflict">冲突</option><option value="rejected">已拒绝</option></select></label></div>
          <div className="ontology-table-scroll"><table><thead><tr><th>来源对象</th><th>映射语义</th><th>目标对象</th><th>证据</th></tr></thead><tbody>{mappings.map(row => <tr key={row.mapping_id} onClick={() => { setViewMode('graph'); loadConcept(row.source_concept_id); loadGraph(row.source_concept_id); }}><td><strong>{row.source_concept?.pref_label}</strong><small>{row.source_concept?.code}</small></td><td><span className={`ontology-status status-${row.mapping_status}`}>{row.mapping_status}</span><small>{row.mapping_type}</small></td><td><strong>{row.target_concept?.pref_label}</strong><small>{row.target_concept?.code}</small></td><td><span>{row.confidence == null ? '-' : `${(row.confidence * 100).toFixed(0)}%`}</span><small>{(row.evidence?.match_basis || []).join(' + ')}</small></td></tr>)}</tbody></table></div>
          <div className="ontology-pagination"><button disabled={mappingOffset === 0} onClick={() => setMappingOffset(Math.max(0, mappingOffset - 80))}><ChevronLeft size={14} /></button><span>{mappingTotal ? mappingOffset + 1 : 0}-{Math.min(mappingOffset + 80, mappingTotal)} / {mappingTotal}</span><button disabled={mappingOffset + 80 >= mappingTotal} onClick={() => setMappingOffset(mappingOffset + 80)}><ChevronRight size={14} /></button></div></div>}

        {viewMode === 'validation' && <div className="ontology-validation-view"><div className="ontology-view-title"><div><strong>发布校验</strong><span>{validation?.validators?.join(' · ')}</span></div><span className={`ontology-conformance ${validation?.conforms ? 'ok' : 'error'}`}>{validation?.conforms ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}{validation?.conforms ? 'Conforms' : 'Failed'}</span></div>
          <div className="ontology-validation-summary"><div><span>SHACL</span><b>{validation?.shacl_conforms ? '通过' : '失败'}</b></div><div><span>错误</span><b>{count(validation?.severity_counts?.error)}</b></div><div><span>警告</span><b>{count(validation?.severity_counts?.warning)}</b></div><div><span>观察项</span><b>{count(validation?.issue_count)}</b></div></div>
          <div className="ontology-issue-list">{visibleIssues.map((issue: Row, index: number) => <div key={`${issue.code}-${index}`}><span className={`ontology-issue-severity ${issue.severity}`}>{issue.severity}</span><strong>{issue.code}</strong><code>{issue.table || issue.source || issue.relation_id || issue.ea_object_id || ''}</code><span>{issue.field || issue.heading || issue.raw_datatype || (issue.count ? `${issue.count} 条` : '')}</span></div>)}</div></div>}
      </main>

      {concept && <aside className="ontology-detail-pane"><div className="ontology-detail-head"><div><span>{KIND_LABELS[concept.kind] || concept.kind}</span><strong>{concept.pref_label}</strong><code>{concept.code || 'no-code'}</code></div><button title="关闭" onClick={() => { setConcept(null); setSelectedConceptId(''); }}><X size={15} /></button></div>
        <div className="ontology-detail-tabs"><button className={detailMode === 'fields' ? 'active' : ''} onClick={() => setDetailMode('fields')}>字段 <span>{propertyTotal}</span></button><button className={detailMode === 'relations' ? 'active' : ''} onClick={() => setDetailMode('relations')}>关系 <span>{relations.length}</span></button><button className={detailMode === 'provenance' ? 'active' : ''} onClick={() => setDetailMode('provenance')}>溯源</button></div>
        <div className="ontology-detail-scroll">{detailMode === 'fields' && <div className="ontology-fields">{properties.map(field => <div key={field.property_id}><div><strong>{field.pref_label}</strong><code>{field.code}</code></div><span>{field.datatype || '未定义'}{field.length ? `(${field.length}${field.scale_value ? `,${field.scale_value}` : ''})` : ''}</span><em>{field.min_count > 0 ? '必填' : '可选'}</em></div>)}
          {properties.length < propertyTotal && <button onClick={async () => { const data = await api<Row>(`/api/ontology/properties?concept_id=${encodeURIComponent(concept.concept_id)}&offset=${properties.length}&limit=200`); setProperties(current => [...current, ...(data.items || [])]); }}>加载更多字段</button>}</div>}
          {detailMode === 'relations' && <div className="ontology-relations">{relations.map(row => <button key={`${row.relation_id}-${row.traversal_direction}`} onClick={() => { loadConcept(row.other_concept.concept_id); loadGraph(row.other_concept.concept_id); }}><span>{row.traversal_direction === 'out' ? '→' : '←'}</span><div><strong>{row.other_concept.pref_label}</strong><small>{row.other_concept.code || row.other_concept.kind}</small></div><em>{row.relation_type}</em></button>)}</div>}
          {detailMode === 'provenance' && <div className="ontology-provenance"><dl><dt>稳定 ID</dt><dd><code>{concept.concept_id}</code></dd><dt>URI</dt><dd><code>{concept.uri}</code></dd><dt>来源</dt><dd>{sourceLabel(concept.source_system)}</dd><dt>来源对象</dt><dd>{concept.source_object_id || '-'}</dd><dt>EA GUID</dt><dd><code>{concept.ea_guid || '-'}</code></dd><dt>模型包路径</dt><dd>{concept.package_path || '-'}</dd><dt>生命周期</dt><dd><span className={`ontology-status status-${concept.lifecycle_status}`}>{concept.lifecycle_status}</span></dd></dl>{concept.definition && <p>{concept.definition}</p>}<pre>{JSON.stringify(concept.provenance || {}, null, 2)}</pre></div>}
        </div></aside>}
    </div>
    <footer className="ontology-footer"><span>{status?.model_profile}</span><span title={status?.content_sha256}>Package {status?.content_sha256?.slice(0, 12)}</span><span>{status?.backend === 'immutable_package' ? '固定包运行' : status?.backend}</span><span>{status?.projection?.sparql_endpoint ? 'SPARQL ready' : 'RDF package ready'}</span></footer>
  </div>;
}
