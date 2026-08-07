import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow, Background, Controls, MiniMap, MarkerType,
  type Edge, type Node, type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  AlertTriangle, ArrowLeft, ArrowRight, Braces, CheckCircle2, ChevronLeft, ChevronRight,
  Database, Download, FileJson, Filter, GitCompareArrows,
  Home, Layers3, LocateFixed, Maximize2, Minimize2, Network, RefreshCw, Search,
  ShieldCheck, X,
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
type DetailMode = 'overview' | 'fields' | 'relations' | 'provenance';
type GraphDepth = 1 | 2 | 3;
type NavigationEntry = { concept_id: string; pref_label: string; code?: string };
type NavigationState = { entries: NavigationEntry[]; index: number };
type PropertyOrigin = 'direct' | 'inherited' | 'mapped';
type PropertyGroupCounts = Record<PropertyOrigin, number>;
const nodeTypes = { ontologyConcept: OntologyConceptNode };
const DOMAIN_MODEL_KINDS = 'DomainClass,ProcessClass,StateClass,RoleClass,InformationClass,ObservationClass';
const GRAPH_LIMITS: Record<GraphDepth, number> = { 1: 24, 2: 48, 3: 80 };
const PROPERTY_GROUPS: Array<{ key: PropertyOrigin; label: string }> = [
  { key: 'direct', label: '直接属性' },
  { key: 'inherited', label: '继承属性' },
  { key: 'mapped', label: '标准 / EA 映射字段' },
];
const KIND_LABELS: Record<string, string> = {
  DomainClass: '领域实体类', ProcessClass: '过程类', StateClass: '状态类',
  RoleClass: '角色类', InformationClass: '信息类', ObservationClass: '观测类',
  ReferenceScheme: '参考分类', ReferenceConcept: '分类代码', SchemaArtifact: '数据结构制品',
  Domain: '领域', StandardDocument: '标准', Package: 'EA 包', FeatureType: '标准要素',
  DatasetSchema: 'EA 数据结构', ObjectType: '对象类型', ActionType: '行动类型',
  FunctionType: '函数类型', InterfaceType: '接口类型', CRS: '坐标系', MetaClass: '元类',
  ValueDomain: '标准值域', ValueDomainMember: '代码项',
};
const RELATION_LABELS: Record<string, string> = {
  subClassOf: '继承', contains: '包含', partOf: '组成于', locatedIn: '位于',
  hasState: '具有状态', observedBy: '由其观测', governedBy: '受其约束',
  exactMatch: '精确映射', closeMatch: '近似映射', broadMatch: '宽泛映射',
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'include', ...init });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
  return payload as T;
}

const count = (value?: number) => new Intl.NumberFormat('zh-CN').format(value || 0);
function relationLabel(relationType?: string, prefLabel?: string) {
  if (prefLabel && prefLabel !== relationType) return prefLabel;
  return RELATION_LABELS[relationType || ''] || relationType || '关联';
}

function valueDomainLabel(value: unknown): string {
  if (value == null || value === '') return '';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.slice(0, 4).map(valueDomainLabel).filter(Boolean).join('、');
  if (typeof value === 'object') {
    const row = value as Row;
    const direct = row.label || row.pref_label || row.name || row.code || row.id || row.reference;
    if (direct) return String(direct);
    const values = row.values || row.members || row.enum;
    if (Array.isArray(values)) return values.slice(0, 4).map(valueDomainLabel).filter(Boolean).join('、');
  }
  return '';
}

function buildDomainOverview(domains: DomainSummary[]) {
  const columns = 2;
  const nodes: Node[] = domains.map((domain, index) => ({
    id: `domain-entry:${domain.domain_id}`,
    type: 'ontologyConcept',
    position: { x: (index % columns) * 285, y: Math.floor(index / columns) * 124 },
    data: {
      label: domain.label,
      code: domain.domain_id,
      kind: 'Domain',
      sourceSystem: 'curated_domain',
      domainId: domain.domain_id,
      classCount: domain.domain_class_count,
      propertyCount: domain.property_count,
    },
  }));
  return { nodes, edges: [] as Edge[] };
}

function layoutFocusedNodes(nodes: Node[], edges: Edge[], rootId: string): Node[] {
  if (!rootId || !nodes.some(node => node.id === rootId)) return nodes;

  type Placement = { distance: number; side: -1 | 0 | 1 };
  const adjacency = new Map<string, Array<{ id: string; side: -1 | 1 }>>();
  const connect = (from: string, to: string, side: -1 | 1) => {
    const rows = adjacency.get(from) || [];
    rows.push({ id: to, side });
    adjacency.set(from, rows);
  };
  edges.forEach(edge => {
    connect(edge.source, edge.target, 1);
    connect(edge.target, edge.source, -1);
  });

  const placement = new Map<string, Placement>([[rootId, { distance: 0, side: 0 }]]);
  const queue = [rootId];
  while (queue.length) {
    const current = queue.shift()!;
    const currentPlacement = placement.get(current)!;
    (adjacency.get(current) || []).forEach(next => {
      if (placement.has(next.id)) return;
      placement.set(next.id, {
        distance: currentPlacement.distance + 1,
        side: currentPlacement.side || next.side,
      });
      queue.push(next.id);
    });
  }

  const groups = new Map<string, Node[]>();
  nodes.forEach(node => {
    if (node.id === rootId) return;
    const value = placement.get(node.id) || { distance: 1, side: 1 as const };
    const key = `${value.side}:${value.distance}`;
    const group = groups.get(key) || [];
    group.push(node);
    groups.set(key, group);
  });
  groups.forEach(group => group.sort((a, b) => String(a.data?.label || '').localeCompare(String(b.data?.label || ''), 'zh-CN')));

  return nodes.map(node => {
    const value = placement.get(node.id) || { distance: 1, side: 1 as const };
    if (node.id === rootId) {
      return { ...node, position: { x: 0, y: 0 }, data: { ...node.data, isFocus: true, graphDistance: 0 } };
    }
    const group = groups.get(`${value.side}:${value.distance}`) || [node];
    const index = group.findIndex(item => item.id === node.id);
    const maxRows = 12;
    const column = Math.floor(index / maxRows);
    const row = index % maxRows;
    const rowsInColumn = Math.min(maxRows, group.length - column * maxRows);
    return {
      ...node,
      position: {
        x: value.side * (value.distance * 320 + column * 220),
        y: (row - (rowsInColumn - 1) / 2) * 116,
      },
      data: { ...node.data, isFocus: false, graphDistance: value.distance },
    };
  });
}

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
  const [focusedConceptId, setFocusedConceptId] = useState('');
  const [selectedConceptId, setSelectedConceptId] = useState('');
  const [concept, setConcept] = useState<Row | null>(null);
  const [properties, setProperties] = useState<Row[]>([]);
  const [propertyTotal, setPropertyTotal] = useState(0);
  const [propertyGroupCounts, setPropertyGroupCounts] = useState<PropertyGroupCounts>({
    direct: 0, inherited: 0, mapped: 0,
  });
  const [relations, setRelations] = useState<Row[]>([]);
  const [relationTotal, setRelationTotal] = useState(0);
  const [detailMode, setDetailMode] = useState<DetailMode>('fields');
  const [query, setQuery] = useState('');
  const [kindFilter, setKindFilter] = useState('');
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
  const [fullscreen, setFullscreen] = useState(false);
  const [graphDepth, setGraphDepth] = useState<GraphDepth>(1);
  const [navigation, setNavigation] = useState<NavigationState>({ entries: [], index: -1 });
  const searchTimer = useRef<number | undefined>();
  const flowInstance = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const conceptRequest = useRef(0);
  const graphRequest = useRef(0);

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

  const loadGraph = useCallback(async (rootId = '', depth: GraphDepth = 1) => {
    const requestId = ++graphRequest.current;
    setLoading(true); setMessage('');
    try {
      const params = new URLSearchParams({
        depth: String(rootId ? depth : 1),
        limit: String(rootId ? GRAPH_LIMITS[depth] : 250),
      });
      if (rootId) params.set('root_id', rootId); else if (selectedDomain) params.set('domain_id', selectedDomain);
      const data = await api<Row>(`/api/ontology/graph?${params}`);
      if (requestId !== graphRequest.current) return;
      const edges = (data.edges || []).map((edge: Edge & { data?: Row }) => ({
        ...edge,
        type: 'default',
        label: relationLabel(edge.data?.relationType, typeof edge.label === 'string' ? edge.label : undefined),
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 15,
          height: 15,
          color: edge.data?.mappingStatus ? '#0f766e'
            : edge.data?.relationType === 'subClassOf' ? '#4f46e5'
              : edge.data?.relationType === 'contains' ? '#64748b' : '#b45309',
        },
        style: {
          stroke: edge.data?.mappingStatus === 'conflict' ? '#dc2626'
            : edge.data?.mappingStatus === 'confirmed' ? '#0f766e'
              : edge.data?.relationType === 'subClassOf' ? '#4f46e5'
                : edge.data?.relationType === 'contains' ? '#64748b' : '#b45309',
          strokeWidth: edge.data?.mappingStatus ? 2 : 1.2,
          strokeDasharray: edge.data?.mappingStatus ? '5 4' : undefined,
        },
        labelStyle: { fontSize: 10, fill: '#475569', fontWeight: 600 },
        labelShowBg: true,
        labelBgPadding: [5, 3] as [number, number],
        labelBgBorderRadius: 3,
        labelBgStyle: { fill: '#ffffff', fillOpacity: 0.9 },
      }));
      setGraph({ nodes: layoutFocusedNodes(data.nodes || [], edges, rootId), edges });
      setGraphMeta(data);
    } catch (error) { setMessage(error instanceof Error ? error.message : '图谱加载失败'); }
    finally { if (requestId === graphRequest.current) setLoading(false); }
  }, [selectedDomain]);

  const loadConcept = useCallback(async (conceptId: string) => {
    if (!conceptId) return null;
    const requestId = ++conceptRequest.current;
    setMessage('');
    try {
      const encoded = encodeURIComponent(conceptId);
      const [detail, fields, relationData] = await Promise.all([
        api<Row>(`/api/ontology/concept?concept_id=${encoded}`),
        api<Row>(`/api/ontology/properties?concept_id=${encoded}&include_effective=true&limit=500`),
        api<Row>(`/api/ontology/relations?concept_id=${encoded}&limit=200`),
      ]);
      if (requestId !== conceptRequest.current) return null;
      setConcept(detail); setProperties(fields.items || []); setPropertyTotal(fields.total || 0);
      setPropertyGroupCounts({
        direct: fields.group_counts?.direct || 0,
        inherited: fields.group_counts?.inherited || 0,
        mapped: fields.group_counts?.mapped || 0,
      });
      setRelations(relationData.items || []); setRelationTotal(relationData.total || 0);
      return detail;
    } catch (error) { setMessage(error instanceof Error ? error.message : '概念加载失败'); }
    return null;
  }, []);

  const selectConcept = useCallback((
    conceptId: string,
    detail: DetailMode = 'fields',
  ) => {
    if (!conceptId) return Promise.resolve(null);
    setSelectedConceptId(conceptId);
    setDetailMode(detail);
    return loadConcept(conceptId);
  }, [loadConcept]);

  const focusConcept = useCallback((conceptId: string, hint?: Partial<NavigationEntry>, pushHistory = true) => {
    if (!conceptId) return;
    setViewMode('graph');
    setSearchOpen(false);
    setQuery('');
    setFocusedConceptId(conceptId);
    if (pushHistory) {
      setNavigation(current => {
        const currentEntry = current.entries[current.index];
        const entry: NavigationEntry = {
          concept_id: conceptId,
          pref_label: hint?.pref_label || hint?.code || conceptId,
          code: hint?.code,
        };
        if (currentEntry?.concept_id === conceptId) {
          const entries = current.entries.map((item, index) => index === current.index ? { ...item, ...entry } : item);
          return { entries, index: current.index };
        }
        const entries = [...current.entries.slice(0, current.index + 1), entry].slice(-20);
        return { entries, index: entries.length - 1 };
      });
    }
    void selectConcept(conceptId).then(detail => {
      if (!detail) return;
      if (detail.domain_id) setSelectedDomain(detail.domain_id);
      setNavigation(current => ({
        ...current,
        entries: current.entries.map(item => item.concept_id === conceptId ? {
          ...item,
          pref_label: detail.pref_label || item.pref_label,
          code: detail.code || item.code,
        } : item),
      }));
    });
  }, [selectConcept]);

  const showDomainOverview = useCallback((domainId = selectedDomain) => {
    conceptRequest.current += 1;
    setViewMode('graph');
    setSelectedDomain(domainId);
    setFocusedConceptId('');
    setSelectedConceptId('');
    setConcept(null);
    setProperties([]);
    setPropertyTotal(0);
    setPropertyGroupCounts({ direct: 0, inherited: 0, mapped: 0 });
    setRelations([]);
    setRelationTotal(0);
    setNavigation({ entries: [], index: -1 });
  }, [selectedDomain]);

  const openHistoryEntry = useCallback((index: number) => {
    const entry = navigation.entries[index];
    if (!entry || index === navigation.index) return;
    setNavigation(current => ({ ...current, index }));
    focusConcept(entry.concept_id, entry, false);
  }, [focusConcept, navigation]);

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
      focusConcept(conceptId, {
        pref_label: String(detail.pref_label || detail.label || conceptId),
        code: detail.code ? String(detail.code) : undefined,
      });
    };
    window.addEventListener('gda-workspace-update', handleWorkspaceUpdate);
    const pending = (window as any).__pendingGdaWorkspaceUpdate;
    if (pending?.tab === 'ontology') {
      handleWorkspaceUpdate(new CustomEvent('gda-workspace-update', { detail: pending }));
    }
    return () => window.removeEventListener('gda-workspace-update', handleWorkspaceUpdate);
  }, [focusConcept]);

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
    if (viewMode === 'graph') {
      if (focusedConceptId) {
        void loadGraph(focusedConceptId, graphDepth);
      } else if (selectedDomain) {
        void loadGraph('', 1);
      } else {
        graphRequest.current += 1;
        const overview = buildDomainOverview(domains);
        setGraph(overview);
        setGraphMeta({
          node_count: overview.nodes.length,
          edge_count: 0,
          depth: 0,
          truncated: false,
          overview: 'domains',
        });
        setLoading(false);
      }
    } else if (viewMode === 'mappings') {
      void loadMappings();
    } else {
      void loadValidation();
    }
  }, [status, domains, selectedDomain, focusedConceptId, graphDepth, viewMode, loadGraph, loadMappings, loadValidation]);

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

  useEffect(() => {
    if (!fullscreen) return;
    const previousBodyOverflow = document.body.style.overflow;
    const previousRootOverflow = document.documentElement.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFullscreen(false);
    };
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overflow = previousRootOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [fullscreen]);

  useEffect(() => {
    if (viewMode !== 'graph' || graph.nodes.length === 0) return;
    let secondFrame = 0;
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        void flowInstance.current?.fitView({ padding: fullscreen ? 0.12 : 0.22, duration: 240 });
      });
    });
    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (secondFrame) window.cancelAnimationFrame(secondFrame);
    };
  }, [fullscreen, graph.nodes.length, focusedConceptId, graphDepth, viewMode]);

  const selectedDomainData = domains.find(domain => domain.domain_id === selectedDomain);
  const visibleIssues = (validation?.issues || []).slice(0, 500);
  const currentNavigationEntry = navigation.entries[navigation.index];
  const graphTitle = focusedConceptId ? currentNavigationEntry?.pref_label || focusedConceptId
    : selectedDomainData ? `${selectedDomainData.domain_id} ${selectedDomainData.label}` : '自然资源领域概览';
  const minimapColor = useCallback((node: Node) => {
    if ((node.data as Row)?.isFocus) return '#dc2626';
    const kind = (node.data as Row)?.kind;
    return kind === 'DomainClass' ? '#0f766e' : kind === 'ProcessClass' ? '#b45309'
      : kind === 'StateClass' ? '#2563eb' : kind === 'InformationClass' ? '#7c3aed'
        : kind === 'RoleClass' ? '#be185d' : '#64748b';
  }, []);
  const graphStats = useMemo(() => graphMeta.overview === 'domains'
    ? `${count(graphMeta.node_count)} 个领域入口`
    : `${count(graphMeta.node_count)} 节点 · ${count(graphMeta.edge_count)} 关系`, [graphMeta]);
  const outgoingRelations = useMemo(() => relations.filter(row => row.traversal_direction === 'out'), [relations]);
  const incomingRelations = useMemo(() => relations.filter(row => row.traversal_direction === 'in'), [relations]);
  const groupedProperties = useMemo(() => {
    const groups: Record<PropertyOrigin, Row[]> = { direct: [], inherited: [], mapped: [] };
    properties.forEach(field => {
      const origin = (field.origin_type || 'direct') as PropertyOrigin;
      (groups[origin] || groups.direct).push(field);
    });
    return groups;
  }, [properties]);
  const visibleGraphNodes = useMemo<Node[]>(() => graph.nodes.map(node => ({
    ...node,
    selected: node.id === selectedConceptId,
  })), [graph.nodes, selectedConceptId]);
  const historyStart = Math.max(0, navigation.index - 3);
  const visibleHistory = navigation.entries.slice(historyStart, navigation.index + 1);

  if (loading && !status) return <div className="ontology-state"><RefreshCw className="spin" size={18} />正在加载本体</div>;

  return <div className={`ontology-workbench${fullscreen ? ' is-fullscreen' : ''}`}>
    <header className="ontology-header">
      <div className="ontology-title"><Network size={18} /><div><strong>自然资源“一张图”本体</strong><span>v{status?.semantic_version || '-'}</span></div></div>
      <div className="ontology-kpis"><span><b>{count(status?.stats?.domain_class_count)}</b>领域类</span><span><b>{count(status?.stats?.relation_count)}</b>语义关系</span><span><b>{count(status?.stats?.schema_artifact_count)}</b>数据制品</span><span><b>{count(status?.stats?.confirmed_mapping_count)}</b>确认映射</span></div>
      <div className="ontology-header-actions">
        <span className={`ontology-conformance ${status?.validation?.conforms ? 'ok' : 'error'}`}>{status?.validation?.conforms ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}{status?.validation?.conforms ? '发布门通过' : '发布门失败'}</span>
        <button
          className="ontology-fullscreen-toggle"
          title={fullscreen ? '退出最大化（Esc）' : '最大化本体模型'}
          aria-label={fullscreen ? '退出最大化本体模型' : '最大化本体模型'}
          aria-pressed={fullscreen}
          onClick={() => setFullscreen(value => !value)}
        >
          {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
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
        {searchOpen && <div className="ontology-search-results"><div className="ontology-search-count">{count(searchTotal)} 个结果</div>{searchResults.map(item => <button key={item.concept_id} onClick={() => focusConcept(item.concept_id, item)}><span className={`ontology-kind-dot kind-${item.kind}`} /><span><strong>{item.pref_label}</strong><small>{item.code || item.concept_id}</small></span><em>{KIND_LABELS[item.kind] || item.kind}</em></button>)}</div>}
      </div>
      <label className="ontology-select"><Filter size={13} /><select value={kindFilter} onChange={event => setKindFilter(event.target.value)}><option value="">全部本体对象</option><option value={DOMAIN_MODEL_KINDS}>领域模型</option><option value="DomainClass">实体类</option><option value="ProcessClass">过程类</option><option value="StateClass">状态类</option><option value="InformationClass">信息类</option><option value="RoleClass">角色类</option><option value="ObservationClass">观测类</option><option value="ReferenceScheme,ReferenceConcept">参考分类</option><option value="SchemaArtifact">数据结构制品</option></select></label>
      <label className="ontology-select"><Database size={13} /><select value={sourceFilter} onChange={event => setSourceFilter(event.target.value)}><option value="">全部来源</option><option value="curated_domain">策划领域模型</option><option value="standard">自然资源标准</option><option value="enterprise_architect">Enterprise Architect</option></select></label>
    </div>
    {message && <div className="ontology-message"><AlertTriangle size={14} />{message}<button onClick={() => setMessage('')}><X size={13} /></button></div>}

    <div className="ontology-body">
      <aside className="ontology-domain-pane"><div className="ontology-pane-title"><Layers3 size={14} /><strong>领域</strong><span>{domains.length}</span></div>
        <button className={`ontology-domain-row ${!selectedDomain ? 'active' : ''}`} onClick={() => { showDomainOverview(''); setMappingOffset(0); }}><div><b>ALL</b><span>领域概览</span></div><small>{count(status?.stats?.domain_class_count)}</small></button>
        <div className="ontology-domain-scroll">{domains.map(domain => <button key={domain.domain_id} className={`ontology-domain-row ${selectedDomain === domain.domain_id ? 'active' : ''}`} onClick={() => { showDomainOverview(domain.domain_id); setMappingOffset(0); }}><div><b>{domain.domain_id}</b><span>{domain.label}</span></div><small>{count(domain.domain_class_count)}</small><div className="ontology-coverage" title={`严格映射覆盖 ${(domain.strict_coverage * 100).toFixed(1)}%`}><i style={{ width: `${Math.min(domain.strict_coverage * 100, 100)}%` }} /></div></button>)}</div>
        {selectedDomainData && <div className="ontology-domain-summary"><div><span>标准要素</span><b>{count(selectedDomainData.standard_feature_count)}</b></div><div><span>EA 结构</span><b>{count(selectedDomainData.ea_schema_count)}</b></div><div><span>字段</span><b>{count(selectedDomainData.property_count)}</b></div><div><span>严格覆盖</span><b>{(selectedDomainData.strict_coverage * 100).toFixed(1)}%</b></div></div>}
      </aside>

      <main className="ontology-main-pane">
        {viewMode === 'graph' && <>
          <div className="ontology-view-title ontology-graph-title">
            <div className="ontology-graph-heading">
              <strong>{graphTitle}</strong>
              <span>{graphStats}{graphMeta.truncated ? ' · 已按预算截断' : ''}</span>
              {focusedConceptId && <nav className="ontology-breadcrumb" aria-label="对象浏览路径">
                <button title="返回当前领域概览" onClick={() => showDomainOverview()}>{selectedDomainData?.label || '领域概览'}</button>
                {historyStart > 0 && <><ChevronRight size={10} /><span>...</span></>}
                {visibleHistory.map((entry, offset) => {
                  const index = historyStart + offset;
                  return <span key={`${entry.concept_id}-${index}`}>
                    <ChevronRight size={10} />
                    <button
                      className={index === navigation.index ? 'active' : ''}
                      title={entry.code || entry.pref_label}
                      onClick={() => openHistoryEntry(index)}
                    >{entry.pref_label}</button>
                  </span>;
                })}
              </nav>}
            </div>
            {focusedConceptId && <div className="ontology-graph-tools">
              <div className="ontology-history-controls">
                <button title="上一个对象" aria-label="上一个对象" disabled={navigation.index <= 0} onClick={() => openHistoryEntry(navigation.index - 1)}><ArrowLeft size={13} /></button>
                <button title="下一个对象" aria-label="下一个对象" disabled={navigation.index < 0 || navigation.index >= navigation.entries.length - 1} onClick={() => openHistoryEntry(navigation.index + 1)}><ArrowRight size={13} /></button>
                <button title="返回领域概览" aria-label="返回领域概览" onClick={() => showDomainOverview()}><Home size={13} /></button>
              </div>
              <div className="ontology-depth-segments" aria-label="关联层级">
                {([1, 2, 3] as GraphDepth[]).map(depth => <button
                  key={depth}
                  className={graphDepth === depth ? 'active' : ''}
                  aria-pressed={graphDepth === depth}
                  onClick={() => setGraphDepth(depth)}
                >{depth}级</button>)}
              </div>
            </div>}
          </div>
          <div className="ontology-graph">
            <ReactFlow
              nodes={visibleGraphNodes}
              edges={graph.edges}
              nodeTypes={nodeTypes}
              onInit={instance => { flowInstance.current = instance; }}
              onNodeClick={(_, node) => {
                const data = node.data as Row;
                if (data.domainId) showDomainOverview(String(data.domainId));
                else void selectConcept(node.id);
              }}
              onNodeDoubleClick={(_, node) => {
                const data = node.data as Row;
                if (data.domainId) showDomainOverview(String(data.domainId));
                else focusConcept(node.id, {
                  pref_label: String(data.label || node.id),
                  code: data.code ? String(data.code) : undefined,
                });
              }}
              fitView
              fitViewOptions={{ padding: focusedConceptId ? 0.16 : 0.22 }}
              minZoom={0.08}
              maxZoom={2.2}
            >
              <Background color="#263244" gap={22} size={1} />
              <Controls showInteractive={false} />
              <MiniMap nodeColor={minimapColor} bgColor="#111827" maskColor="rgba(11, 15, 25, .68)" pannable zoomable />
            </ReactFlow>
            {graph.edges.length > 0 && <div className="ontology-graph-legend" aria-label="关系图例">
              <span><i className="inheritance" />继承</span>
              <span><i className="composition" />组成</span>
              <span><i className="object-relation" />对象关系</span>
              <span><i className="mapping" />数据映射</span>
            </div>}
            {loading && <div className="ontology-loading"><RefreshCw className="spin" size={17} /></div>}
          </div>
        </>}

        {viewMode === 'mappings' && <div className="ontology-table-view"><div className="ontology-view-title"><div><strong>语义与数据映射</strong><span>{count(mappingTotal)} 条可追溯映射</span></div><label className="ontology-select"><select value={mappingStatus} onChange={event => { setMappingStatus(event.target.value); setMappingOffset(0); }}><option value="">全部状态</option><option value="confirmed">已确认</option><option value="candidate">候选</option><option value="conflict">冲突</option><option value="rejected">已拒绝</option></select></label></div>
          <div className="ontology-table-scroll"><table><thead><tr><th>来源对象</th><th>映射语义</th><th>目标对象</th><th>证据</th></tr></thead><tbody>{mappings.map(row => <tr key={row.mapping_id} onClick={() => focusConcept(row.source_concept_id, row.source_concept)}><td><strong>{row.source_concept?.pref_label}</strong><small>{row.source_concept?.code}</small></td><td><span className={`ontology-status status-${row.mapping_status}`}>{row.mapping_status}</span><small>{row.mapping_type}</small></td><td><strong>{row.target_concept?.pref_label}</strong><small>{row.target_concept?.code}</small></td><td><span>{row.confidence == null ? '-' : `${(row.confidence * 100).toFixed(0)}%`}</span><small>{(row.evidence?.match_basis || []).join(' + ')}</small></td></tr>)}</tbody></table></div>
          <div className="ontology-pagination"><button disabled={mappingOffset === 0} onClick={() => setMappingOffset(Math.max(0, mappingOffset - 80))}><ChevronLeft size={14} /></button><span>{mappingTotal ? mappingOffset + 1 : 0}-{Math.min(mappingOffset + 80, mappingTotal)} / {mappingTotal}</span><button disabled={mappingOffset + 80 >= mappingTotal} onClick={() => setMappingOffset(mappingOffset + 80)}><ChevronRight size={14} /></button></div></div>}

        {viewMode === 'validation' && <div className="ontology-validation-view"><div className="ontology-view-title"><div><strong>发布校验</strong><span>{validation?.validators?.join(' · ')}</span></div><span className={`ontology-conformance ${validation?.conforms ? 'ok' : 'error'}`}>{validation?.conforms ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}{validation?.conforms ? 'Conforms' : 'Failed'}</span></div>
          <div className="ontology-validation-summary"><div><span>SHACL</span><b>{validation?.shacl_conforms ? '通过' : '失败'}</b></div><div><span>错误</span><b>{count(validation?.severity_counts?.error)}</b></div><div><span>警告</span><b>{count(validation?.severity_counts?.warning)}</b></div><div><span>观察项</span><b>{count(validation?.issue_count)}</b></div></div>
          <div className="ontology-issue-list">{visibleIssues.map((issue: Row, index: number) => <div key={`${issue.code}-${index}`}><span className={`ontology-issue-severity ${issue.severity}`}>{issue.severity}</span><strong>{issue.code}</strong><code>{issue.table || issue.source || issue.relation_id || issue.ea_object_id || ''}</code><span>{issue.field || issue.heading || issue.raw_datatype || (issue.count ? `${issue.count} 条` : '')}</span></div>)}</div></div>}
      </main>

      <aside className={`ontology-detail-pane${concept ? ' has-selection' : ''}`}>
        {concept ? <>
          <div className="ontology-detail-head">
            <div className="ontology-detail-identity"><span>{KIND_LABELS[concept.kind] || concept.kind}</span><strong>{concept.pref_label}</strong><code>{concept.code || 'no-code'}</code></div>
            <div className="ontology-detail-actions">
              <button
                title={focusedConceptId === selectedConceptId ? '当前已是中心对象' : '以此对象为中心'}
                aria-label="以此对象为中心"
                disabled={focusedConceptId === selectedConceptId}
                onClick={() => focusConcept(concept.concept_id, concept)}
              ><LocateFixed size={15} /></button>
              <button title="清除对象选择" aria-label="清除对象选择" onClick={() => {
                conceptRequest.current += 1;
                setSelectedConceptId('');
                setConcept(null);
                setProperties([]);
                setRelations([]);
              }}><X size={15} /></button>
            </div>
            <div className="ontology-detail-metrics"><span><b>{count(propertyGroupCounts.direct)}</b>直接</span><span><b>{count(propertyTotal)}</b>有效字段</span><span><b>{count(relationTotal)}</b>关系</span></div>
            {concept.definition && <p title={concept.definition}>{concept.definition}</p>}
          </div>
          <div className="ontology-detail-tabs">
            <button className={detailMode === 'overview' ? 'active' : ''} onClick={() => setDetailMode('overview')}>概览</button>
            <button className={detailMode === 'fields' ? 'active' : ''} onClick={() => setDetailMode('fields')}>属性 <span>{propertyTotal}</span></button>
            <button className={detailMode === 'relations' ? 'active' : ''} onClick={() => setDetailMode('relations')}>关系 <span>{relationTotal}</span></button>
            <button className={detailMode === 'provenance' ? 'active' : ''} onClick={() => setDetailMode('provenance')}>约束/溯源</button>
          </div>
          <div className="ontology-detail-scroll">
            {detailMode === 'overview' && <div className="ontology-object-overview">
              <section><h4>对象定义</h4><p>{concept.definition || '未提供定义'}</p></section>
              <dl>
                <dt>对象类型</dt><dd>{KIND_LABELS[concept.kind] || concept.kind}</dd>
                <dt>所属领域</dt><dd>{domains.find(item => item.domain_id === concept.domain_id)?.label || concept.domain_id || '-'}</dd>
                <dt>数据来源</dt><dd>{sourceLabel(concept.source_system)}</dd>
                <dt>空间类型</dt><dd>{concept.geometry_type || '非空间对象'}</dd>
                <dt>确认映射</dt><dd>{count(concept.mapping_count)}</dd>
                <dt>生命周期</dt><dd><span className={`ontology-status status-${concept.lifecycle_status}`}>{concept.lifecycle_status}</span></dd>
              </dl>
            </div>}
            {detailMode === 'fields' && <div className="ontology-fields">{PROPERTY_GROUPS.map(group => {
              const groupFields = groupedProperties[group.key];
              const groupTotal = propertyGroupCounts[group.key];
              if (!groupFields.length && !groupTotal) return null;
              return <section className={`ontology-field-group origin-${group.key}`} key={group.key}>
                <h4><span>{group.label}</span><b>{count(groupTotal)}</b></h4>
                {groupFields.map(field => {
                  const domain = valueDomainLabel(field.value_domain);
                  const cardinality = `${field.min_count ?? 0}..${field.max_count == null ? '*' : field.max_count}`;
                  const origin = field.origin_concept || {};
                  const originName = origin.pref_label || origin.code || field.source_object_id || field.source_id;
                  const originSystem = sourceLabel(origin.source_system);
                  return <div className="ontology-field-row" key={field.property_id}>
                    <div className="ontology-field-name"><strong>{field.pref_label}</strong><code>{field.code}</code></div>
                    <span className="ontology-field-type">{field.datatype || '未定义'}{field.length ? `(${field.length}${field.scale_value ? `,${field.scale_value}` : ''})` : ''}</span>
                    <div className="ontology-field-constraints">
                      <em className={field.min_count > 0 ? 'required' : ''}>{field.min_count > 0 ? '必填' : '可选'}</em>
                      <span>基数 {cardinality}</span>
                      {domain && <span className="ontology-field-domain" title={domain}>值域 {domain}</span>}
                      {field.default_value != null && <span title={String(field.default_value)}>默认 {String(field.default_value)}</span>}
                    </div>
                    <div className="ontology-field-origin" title={`${originSystem} · ${originName || '-'}`}>
                      <span>{group.key === 'direct' ? '定义于' : group.key === 'inherited' ? `继承自 L${field.origin_depth}` : '映射自'}</span>
                      <strong>{originName || '-'}</strong>
                      <em>{originSystem}</em>
                    </div>
                  </div>;
                })}
              </section>;
            })}
              {properties.length === 0 && <div className="ontology-detail-empty">无有效属性定义</div>}
              {properties.length < propertyTotal && <button onClick={async () => {
                const data = await api<Row>(`/api/ontology/properties?concept_id=${encodeURIComponent(concept.concept_id)}&include_effective=true&offset=${properties.length}&limit=500`);
                setProperties(current => [...current, ...(data.items || [])]);
              }}>加载更多属性</button>}
            </div>}
            {detailMode === 'relations' && <div className="ontology-relations">{[
              { key: 'out', label: '出向关系', rows: outgoingRelations },
              { key: 'in', label: '入向关系', rows: incomingRelations },
            ].map(group => group.rows.length > 0 && <section key={group.key}>
              <h4>{group.label}<span>{group.rows.length}</span></h4>
              {group.rows.map(row => <div className="ontology-relation-row" key={`${row.relation_id}-${row.traversal_direction}`}>
                <button className="ontology-relation-select" onClick={() => void selectConcept(row.other_concept.concept_id, 'relations')} onDoubleClick={() => focusConcept(row.other_concept.concept_id, row.other_concept)}>
                  <span className={`ontology-relation-direction ${row.traversal_direction}`}>{row.traversal_direction === 'out' ? <ArrowRight size={13} /> : <ArrowLeft size={13} />}</span>
                  <div><strong>{row.other_concept.pref_label}</strong><small>{KIND_LABELS[row.other_concept.kind] || row.other_concept.kind}{row.other_concept.code ? ` · ${row.other_concept.code}` : ''}</small></div>
                  <em title={row.relation_type}>{relationLabel(row.relation_type, row.pref_label)}</em>
                </button>
                <button className="ontology-relation-focus" title="以此对象为中心" aria-label={`以${row.other_concept.pref_label}为中心`} onClick={() => focusConcept(row.other_concept.concept_id, row.other_concept)}><LocateFixed size={13} /></button>
              </div>)}
            </section>)}
              {relations.length === 0 && <div className="ontology-detail-empty">无直接关系</div>}
            </div>}
            {detailMode === 'provenance' && <div className="ontology-provenance"><dl><dt>稳定 ID</dt><dd><code>{concept.concept_id}</code></dd><dt>URI</dt><dd><code>{concept.uri}</code></dd><dt>来源</dt><dd>{sourceLabel(concept.source_system)}</dd><dt>来源对象</dt><dd>{concept.source_object_id || '-'}</dd><dt>EA GUID</dt><dd><code>{concept.ea_guid || '-'}</code></dd><dt>模型包路径</dt><dd>{concept.package_path || '-'}</dd><dt>生命周期</dt><dd><span className={`ontology-status status-${concept.lifecycle_status}`}>{concept.lifecycle_status}</span></dd></dl>{concept.definition && <p>{concept.definition}</p>}<pre>{JSON.stringify(concept.provenance || {}, null, 2)}</pre></div>}
          </div>
        </> : <>
          <div className="ontology-detail-head ontology-detail-placeholder-head">
            <div className="ontology-detail-identity"><span>Ontology Inspector</span><strong>本体对象检查器</strong><code>v{status?.semantic_version || '-'}</code></div>
          </div>
          <div className="ontology-detail-scroll">
            <div className="ontology-model-overview">
              <h4>{selectedDomainData?.label || '自然资源全域模型'}</h4>
              <div><span>领域类</span><b>{count(selectedDomainData?.domain_class_count || status?.stats?.domain_class_count)}</b></div>
              <div><span>语义关系</span><b>{count(status?.stats?.relation_count)}</b></div>
              <div><span>数据结构制品</span><b>{count(selectedDomainData?.standard_feature_count || status?.stats?.schema_artifact_count)}</b></div>
              <div><span>字段定义</span><b>{count(selectedDomainData?.property_count || status?.stats?.property_count)}</b></div>
              <section><span>语义层</span><strong>策划领域模型</strong></section>
              <section><span>标准层</span><strong>自然资源数据标准</strong></section>
              <section><span>实现层</span><strong>Enterprise Architect</strong></section>
            </div>
          </div>
        </>}
      </aside>
    </div>
    <footer className="ontology-footer"><span>{status?.model_profile}</span><span title={status?.content_sha256}>Package {status?.content_sha256?.slice(0, 12)}</span><span>{status?.backend === 'immutable_package' ? '固定包运行' : status?.backend}</span><span>{status?.projection?.sparql_endpoint ? 'SPARQL ready' : 'RDF package ready'}</span></footer>
  </div>;
}
