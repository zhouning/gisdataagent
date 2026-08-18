import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import i18n, { getLocale, getLocaleHeaders } from '../../i18n';
import {
  ReactFlow, Background, Controls, MarkerType,
  type Edge, type Node, type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  AlertTriangle, ArrowLeft, ArrowRight, Braces, CheckCircle2, ChevronLeft, ChevronRight,
  Database, Download, FileJson, Filter, GitCompareArrows,
  Home, Layers3, LocateFixed, Maximize2, Minimize2, Network, Pencil, RefreshCw, Search,
  ShieldCheck, X,
} from 'lucide-react';
import OntologyConceptNode from './ontology/OntologyConceptNode';
import OntologyModelingPanel from './ontology/OntologyModelingPanel';
import './ontology/ontology.css';
import './ontology/value-domains.css';

type Row = Record<string, any>;

interface OntologyStatus {
  available: boolean;
  ontology_key: string;
  title: string;
  short_title: string;
  description: string;
  industry: string;
  namespace_uri: string;
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

interface OntologyProfileSummary {
  ontology_key: string;
  title: string;
  short_title: string;
  description: string;
  industry: string;
  namespace_uri: string;
  domain_count: number;
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

type ViewMode = 'graph' | 'mappings' | 'validation' | 'modeling';
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
  { key: 'direct', label: 'direct' },
  { key: 'inherited', label: 'inherited' },
  { key: 'mapped', label: 'mapped' },
];
const KIND_LABELS: Record<string, string> = {
  DomainClass: 'DomainClass', ProcessClass: 'ProcessClass', StateClass: 'StateClass',
  RoleClass: 'RoleClass', InformationClass: 'InformationClass', ObservationClass: 'ObservationClass',
  ReferenceScheme: 'ReferenceScheme', ReferenceConcept: 'ReferenceConcept', SchemaArtifact: 'SchemaArtifact',
  Domain: 'Domain', StandardDocument: 'StandardDocument', Package: 'Package', FeatureType: 'FeatureType',
  DatasetSchema: 'DatasetSchema', ObjectType: 'ObjectType', ActionType: 'ActionType',
  FunctionType: 'FunctionType', InterfaceType: 'InterfaceType', CRS: 'CRS', MetaClass: 'MetaClass',
  ValueDomain: 'ValueDomain', ValueDomainMember: 'ValueDomainMember',
};
const RELATION_LABELS: Record<string, string> = {
  subClassOf: 'subClassOf', contains: 'contains', partOf: 'partOf', locatedIn: 'locatedIn',
  hasState: 'hasState', observedBy: 'observedBy', governedBy: 'governedBy',
  exactMatch: 'exactMatch', closeMatch: 'closeMatch', broadMatch: 'broadMatch',
};

function kindLabel(kind?: string): string {
  const key = KIND_LABELS[kind || ''];
  return key ? i18n.t(`ontology.kinds.${key}`) : kind || '';
}

interface OntologyMiniMapProps {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId?: string;
  onNodeClick?: (node: Node) => void;
}

/**
 * A small, deterministic overview of the current graph. React Flow's
 * built-in minimap relies on measured custom-node dimensions; those can be
 * unavailable while a graph is being loaded or when it is embedded in the
 * standalone CIM page. Rendering from the graph positions keeps the overview
 * useful in both cases.
 */
function OntologyMiniMap({ nodes, edges, selectedNodeId, onNodeClick }: OntologyMiniMapProps) {
  const width = 184;
  const height = 116;
  const padding = 10;
  const layout = useMemo(() => {
    const visibleNodes = nodes.filter(node => !node.hidden && Number.isFinite(node.position?.x) && Number.isFinite(node.position?.y));
    if (!visibleNodes.length) return { nodes: [], edges: [], bounds: null as null | { minX: number; minY: number; maxX: number; maxY: number } };

    const nodeWidth = (node: Node) => node.measured?.width || node.width || 184;
    const nodeHeight = (node: Node) => node.measured?.height || node.height || 82;
    const minX = Math.min(...visibleNodes.map(node => node.position.x));
    const minY = Math.min(...visibleNodes.map(node => node.position.y));
    const maxX = Math.max(...visibleNodes.map(node => node.position.x + nodeWidth(node)));
    const maxY = Math.max(...visibleNodes.map(node => node.position.y + nodeHeight(node)));
    const rangeX = Math.max(1, maxX - minX);
    const rangeY = Math.max(1, maxY - minY);
    const scale = Math.min((width - padding * 2) / rangeX, (height - padding * 2) / rangeY);
    const point = (node: Node) => ({
      x: padding + (node.position.x - minX) * scale,
      y: padding + (node.position.y - minY) * scale,
      width: Math.max(5, Math.min(25, nodeWidth(node) * scale)),
      height: Math.max(4, Math.min(15, nodeHeight(node) * scale)),
    });
    const points = new Map(visibleNodes.map(node => [node.id, point(node)]));
    const miniEdges = edges.map(edge => {
      const source = points.get(edge.source);
      const target = points.get(edge.target);
      if (!source || !target) return null;
      return {
        id: edge.id,
        x1: source.x + source.width / 2,
        y1: source.y + source.height / 2,
        x2: target.x + target.width / 2,
        y2: target.y + target.height / 2,
      };
    }).filter(Boolean);
    return {
      bounds: { minX, minY, maxX, maxY },
      nodes: visibleNodes.map(node => ({ node, ...point(node) })),
      edges: miniEdges as Array<{ id: string; x1: number; y1: number; x2: number; y2: number }>,
    };
  }, [edges, nodes]);

  const colorFor = (node: Node) => {
    if ((node.data as Row)?.isFocus) return '#dc2626';
    switch ((node.data as Row)?.kind) {
      case 'DomainClass': case 'FeatureType': return '#0f766e';
      case 'ProcessClass': return '#b45309';
      case 'StateClass': case 'DatasetSchema': return '#2563eb';
      case 'InformationClass': case 'Domain': return '#7c3aed';
      case 'RoleClass': return '#be185d';
      default: return '#64748b';
    }
  };

  return (
    <div className="ontology-custom-minimap" role="img" aria-label={i18n.t('ontology.minimapAria')}>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <rect className="ontology-minimap-surface" x="0" y="0" width={width} height={height} rx="4" />
        {layout.edges.map(edge => <line key={edge.id} className="ontology-minimap-edge" x1={edge.x1} y1={edge.y1} x2={edge.x2} y2={edge.y2} />)}
        {layout.nodes.map(item => (
          <rect
            key={item.node.id}
            className={`ontology-minimap-node${item.node.id === selectedNodeId ? ' selected' : ''}`}
            x={item.x}
            y={item.y}
            width={item.width}
            height={item.height}
            rx="1.5"
            fill={colorFor(item.node)}
            onClick={() => onNodeClick?.(item.node)}
          />
        ))}
      </svg>
    </div>
  );
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'include', headers: { ...getLocaleHeaders(), ...(init?.headers || {}) } });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
  return payload as T;
}

const count = (value?: number) => new Intl.NumberFormat(getLocale()).format(value || 0);
function relationLabel(relationType?: string, prefLabel?: string) {
  if (prefLabel && prefLabel !== relationType) return prefLabel;
  const key = RELATION_LABELS[relationType || ''];
  return key ? i18n.t(`ontology.relations.${key}`) : relationType || i18n.t('ontology.relations.related');
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

function buildDomainOverview(domains: DomainSummary[], compact = false) {
  const columns = compact ? 1 : 2;
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
  if (source === 'standard') return i18n.t('ontology.sources.standard');
  if (source === 'enterprise_architect') return i18n.t('ontology.sources.enterpriseArchitect');
  if (source === 'dmt_source_catalog') return i18n.t('ontology.sources.dmtCatalog');
  if (source === 'gda_core') return i18n.t('ontology.sources.cognitiveRuntime');
  if (source === 'curated_domain') return i18n.t('ontology.sources.curatedDomain');
  return source || '-';
}

function lifecycleLabel(status?: string) {
  return status ? i18n.t(`platform.enums.lifecycle.${status}`, { defaultValue: status }) : '-';
}

export interface OntologyTabProps {
  /** API root used by the viewer. Public CIM pages use the bounded read-only root. */
  apiBase?: string;
  /** Export is intentionally disabled for the public, unauthenticated viewer. */
  allowExport?: boolean;
  /** Optional deep link used by the CIM host to open a specific object. */
  initialConceptId?: string;
  /** Operational package details are useful internally but not on customer-facing pages. */
  showTechnicalStatus?: boolean;
  className?: string;
  /** Internal role used to expose governed draft editing. Public viewers omit it. */
  userRole?: string;
}

export default function OntologyTab({
  apiBase = '/api/ontology',
  allowExport = true,
  initialConceptId = '',
  showTechnicalStatus = true,
  className = '',
  userRole = '',
}: OntologyTabProps) {
  const { t } = useTranslation();
  const legacyApi = apiBase.replace(/\/$/, '');
  const supportsOntologyRegistry = legacyApi === '/api/ontology';
  const [ontologyKey, setOntologyKey] = useState('natural-resource-one-map');
  const [ontologyProfiles, setOntologyProfiles] = useState<OntologyProfileSummary[]>([]);
  const ontologyApi = supportsOntologyRegistry ? `/api/ontologies/${ontologyKey}` : legacyApi;
  const canModel = ['admin', 'standard_editor'].includes(userRole);
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
  const [compactLayout, setCompactLayout] = useState(() => window.matchMedia('(max-width: 680px)').matches);
  const [navigation, setNavigation] = useState<NavigationState>({ entries: [], index: -1 });
  const searchTimer = useRef<number | undefined>();
  const flowInstance = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const conceptRequest = useRef(0);
  const graphRequest = useRef(0);
  const initialConceptOpened = useRef('');

  useEffect(() => {
    if (!supportsOntologyRegistry) return;
    void api<{ items: OntologyProfileSummary[] }>('/api/ontologies')
      .then(data => setOntologyProfiles(data.items || []))
      .catch(() => setOntologyProfiles([]));
  }, [supportsOntologyRegistry]);

  useEffect(() => {
    setStatus(null);
    setDomains([]);
    setSelectedDomain('');
    setFocusedConceptId('');
    setSelectedConceptId('');
    setConcept(null);
    setProperties([]);
    setRelations([]);
    setNavigation({ entries: [], index: -1 });
    setQuery('');
    setSearchResults([]);
    setMappings([]);
    setMappingStatus('');
    setMappingOffset(0);
    setValidation(null);
    setKindFilter('');
    setSourceFilter('');
    setViewMode('graph');
    setLoading(true);
    initialConceptOpened.current = '';
  }, [ontologyKey]);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 680px)');
    const handleChange = (event: MediaQueryListEvent) => setCompactLayout(event.matches);
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

  const loadBootstrap = useCallback(async () => {
    setLoading(true); setMessage('');
    try {
      const [statusData, domainData] = await Promise.all([
        api<OntologyStatus>(`${ontologyApi}/status`),
        api<{ items: DomainSummary[] }>(`${ontologyApi}/domains`),
      ]);
      setStatus(statusData); setDomains(domainData.items || []);
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontology.errors.serviceUnavailable')); }
    finally { setLoading(false); }
  }, [ontologyApi]);

  const loadGraph = useCallback(async (rootId = '', depth: GraphDepth = 1) => {
    const requestId = ++graphRequest.current;
    setLoading(true); setMessage('');
    try {
      const params = new URLSearchParams({
        depth: String(rootId ? depth : 1),
        limit: String(rootId ? GRAPH_LIMITS[depth] : 250),
      });
      if (rootId) params.set('root_id', rootId); else if (selectedDomain) params.set('domain_id', selectedDomain);
      const data = await api<Row>(`${ontologyApi}/graph?${params}`);
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
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontology.errors.graphLoad')); }
    finally { if (requestId === graphRequest.current) setLoading(false); }
  }, [ontologyApi, selectedDomain]);

  const loadConcept = useCallback(async (conceptId: string) => {
    if (!conceptId) return null;
    const requestId = ++conceptRequest.current;
    setMessage('');
    try {
      const encoded = encodeURIComponent(conceptId);
      const [detail, fields, relationData] = await Promise.all([
        api<Row>(`${ontologyApi}/concept?concept_id=${encoded}`),
        api<Row>(`${ontologyApi}/properties?concept_id=${encoded}&include_effective=true&limit=500`),
        api<Row>(`${ontologyApi}/relations?concept_id=${encoded}&limit=200`),
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
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontology.errors.conceptLoad')); }
    return null;
  }, [ontologyApi]);

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
      const requestedOntologyKey = String(detail.ontology_key || '').trim();
      if (supportsOntologyRegistry && requestedOntologyKey) {
        setOntologyKey(requestedOntologyKey);
      }
      if ((window as any).__pendingGdaWorkspaceUpdate === detail) {
        delete (window as any).__pendingGdaWorkspaceUpdate;
      }
      if (detail.view === 'mappings') {
        setViewMode('mappings');
        return;
      }
      if (detail.view === 'validation') {
        setViewMode('validation');
        return;
      }
      if (detail.view === 'graph') {
        showDomainOverview();
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
  }, [focusConcept, showDomainOverview]);

  const loadMappings = useCallback(async () => {
    setLoading(true); setMessage('');
    try {
      const params = new URLSearchParams({ offset: String(mappingOffset), limit: '80' });
      if (selectedDomain) params.set('domain_id', selectedDomain); if (mappingStatus) params.set('status', mappingStatus);
      const data = await api<Row>(`${ontologyApi}/mappings?${params}`);
      setMappings(data.items || []); setMappingTotal(data.total || 0);
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontology.errors.mappingLoad')); }
    finally { setLoading(false); }
  }, [mappingOffset, mappingStatus, ontologyApi, selectedDomain]);

  const loadValidation = useCallback(async () => {
    setLoading(true); setMessage('');
    try { setValidation(await api<Row>(`${ontologyApi}/validation`)); }
    catch (error) { setMessage(error instanceof Error ? error.message : t('ontology.errors.validationLoad')); }
    finally { setLoading(false); }
  }, [ontologyApi]);

  useEffect(() => { loadBootstrap(); }, [loadBootstrap]);
  useEffect(() => {
    if (!status || !initialConceptId || initialConceptOpened.current === initialConceptId) return;
    initialConceptOpened.current = initialConceptId;
    focusConcept(initialConceptId, { pref_label: initialConceptId });
  }, [focusConcept, initialConceptId, status]);
  useEffect(() => {
    if (!status) return;
    if (viewMode === 'graph') {
      if (focusedConceptId) {
        void loadGraph(focusedConceptId, graphDepth);
      } else if (selectedDomain) {
        void loadGraph('', 1);
      } else {
        graphRequest.current += 1;
        const overview = buildDomainOverview(domains, compactLayout);
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
    } else if (viewMode === 'validation') {
      void loadValidation();
    }
  }, [status, domains, selectedDomain, focusedConceptId, graphDepth, viewMode, compactLayout, loadGraph, loadMappings, loadValidation]);

  useEffect(() => {
    window.clearTimeout(searchTimer.current);
    if (!query.trim()) { setSearchResults([]); setSearchOpen(false); return; }
    searchTimer.current = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: query.trim(), limit: '40' });
        if (selectedDomain) params.set('domain_id', selectedDomain); if (kindFilter) params.set('kinds', kindFilter);
        if (sourceFilter) params.set('source_system', sourceFilter);
        const data = await api<Row>(`${ontologyApi}/concepts?${params}`);
        setSearchResults(data.items || []); setSearchTotal(data.total || 0); setSearchOpen(true);
      } catch (error) { setMessage(error instanceof Error ? error.message : t('ontology.errors.search')); }
    }, 240);
    return () => window.clearTimeout(searchTimer.current);
  }, [kindFilter, ontologyApi, query, selectedDomain, sourceFilter]);

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
    let settleTimer = 0;
    const fitGraph = (duration: number) => {
      void flowInstance.current?.fitView({
        padding: fullscreen ? 0.12 : 0.22,
        duration,
      });
    };
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        fitGraph(240);
      });
    });
    // The production shell can finish sizing after fonts and the CIM sidebar
    // settle. A delayed pass keeps deep-linked relation nodes inside view.
    settleTimer = window.setTimeout(() => fitGraph(180), 320);
    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (secondFrame) window.cancelAnimationFrame(secondFrame);
      window.clearTimeout(settleTimer);
    };
  }, [fullscreen, graph.nodes.length, focusedConceptId, graphDepth, viewMode]);

  const selectedDomainData = domains.find(domain => domain.domain_id === selectedDomain);
  const visibleIssues = (validation?.issues || []).slice(0, 500);
  const currentNavigationEntry = navigation.entries[navigation.index];
  const graphTitle = focusedConceptId ? currentNavigationEntry?.pref_label || focusedConceptId
    : selectedDomainData ? `${selectedDomainData.domain_id} ${selectedDomainData.label}` : `${status?.short_title || t('ontology.industryOntology')} ${t('ontology.domainOverview')}`;
  const graphStats = useMemo(() => graphMeta.overview === 'domains'
    ? t('ontology.graphStats.domains', { count: count(graphMeta.node_count) })
    : t('ontology.graphStats.nodes', { nodes: count(graphMeta.node_count), edges: count(graphMeta.edge_count) }), [graphMeta, t]);
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

  if (loading && !status) return <div className="ontology-state"><RefreshCw className="spin" size={18} />{t('ontology.loading')}</div>;

  return <div className={`ontology-workbench${fullscreen ? ' is-fullscreen' : ''}${className ? ` ${className}` : ''}`}>
    <header className="ontology-header">
      <div className="ontology-title"><Network size={18} /><div><strong>{status?.title || t('ontology.modelTitle')}</strong><span>v{status?.semantic_version || '-'}</span></div></div>
      {supportsOntologyRegistry && ontologyProfiles.length > 0 && <label className="ontology-profile-select"><span>{t('ontology.industryOntology')}</span><select value={ontologyKey} onChange={event => setOntologyKey(event.target.value)}>{ontologyProfiles.map(profile => <option key={profile.ontology_key} value={profile.ontology_key}>{profile.short_title}</option>)}</select></label>}
      <div className="ontology-kpis"><span><b>{count(status?.stats?.domain_class_count)}</b>{t('ontology.kpis.domainClasses')}</span><span><b>{count(status?.stats?.relation_count)}</b>{t('ontology.kpis.relations')}</span><span><b>{count(status?.stats?.schema_artifact_count)}</b>{t('ontology.kpis.artifacts')}</span><span><b>{count(status?.stats?.confirmed_mapping_count)}</b>{t('ontology.kpis.confirmedMappings')}</span></div>
      <div className="ontology-header-actions">
        <span className={`ontology-conformance ${status?.validation?.conforms ? 'ok' : 'error'}`}>{status?.validation?.conforms ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}{status?.validation?.conforms ? t('ontology.validation.ok') : t('ontology.validation.problem')}</span>
        <button
          className="ontology-fullscreen-toggle"
          title={fullscreen ? t('ontology.actions.exitFullscreen') : t('ontology.actions.fullscreen')}
          aria-label={fullscreen ? t('ontology.actions.exitFullscreen') : t('ontology.actions.fullscreen')}
          aria-pressed={fullscreen}
          onClick={() => setFullscreen(value => !value)}
        >
          {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
        <button title={t('ontology.actions.refresh')} onClick={loadBootstrap}><RefreshCw size={15} /></button>
        {allowExport && <div className="ontology-export-menu"><button title={t('ontology.actions.export')}><Download size={15} /></button><div>
          <a href={`${ontologyApi}/export/turtle`}><Network size={13} />Turtle</a><a href={`${ontologyApi}/export/shacl`}><ShieldCheck size={13} />SHACL</a>
          <a href={`${ontologyApi}/export/jsonld-context`}><FileJson size={13} />JSON-LD</a><a href={`${ontologyApi}/export/manifest`}><Braces size={13} />Manifest</a>
        </div></div>}
      </div>
    </header>

    <div className="ontology-toolbar">
      <div className="ontology-segments"><button className={viewMode === 'graph' ? 'active' : ''} onClick={() => setViewMode('graph')}><Network size={14} />{t('ontology.views.graph')}</button><button className={viewMode === 'mappings' ? 'active' : ''} onClick={() => setViewMode('mappings')}><GitCompareArrows size={14} />{t('ontology.views.mappings')}</button><button className={viewMode === 'validation' ? 'active' : ''} onClick={() => setViewMode('validation')}><ShieldCheck size={14} />{t('ontology.views.validation')}</button>{canModel && <button className={viewMode === 'modeling' ? 'active' : ''} onClick={() => { setViewMode('modeling'); setFullscreen(true); }}><Pencil size={14} />{t('ontology.views.modeling')}</button>}</div>
      {viewMode !== 'modeling' && <><div className="ontology-search-wrap"><Search size={15} /><input value={query} onChange={event => setQuery(event.target.value)} onFocus={() => query && setSearchOpen(true)} placeholder={t('ontology.searchPlaceholder')} />{query && <button title={t('ontology.actions.clear')} onClick={() => setQuery('')}><X size={14} /></button>}
        {searchOpen && <div className="ontology-search-results"><div className="ontology-search-count">{t('ontology.searchCount', { count: count(searchTotal) })}</div>{searchResults.map(item => <button key={item.concept_id} onClick={() => focusConcept(item.concept_id, item)}><span className={`ontology-kind-dot kind-${item.kind}`} /><span><strong>{item.pref_label}</strong><small>{item.code || item.concept_id}</small></span><em>{kindLabel(item.kind)}</em></button>)}</div>}
      </div>
      <label className="ontology-select"><Filter size={13} /><select value={kindFilter} onChange={event => setKindFilter(event.target.value)}><option value="">{t('ontology.filters.allObjects')}</option><option value={DOMAIN_MODEL_KINDS}>{t('ontology.filters.domainModel')}</option><option value="DomainClass">{kindLabel('DomainClass')}</option><option value="ProcessClass">{kindLabel('ProcessClass')}</option><option value="StateClass">{kindLabel('StateClass')}</option><option value="InformationClass">{kindLabel('InformationClass')}</option><option value="RoleClass">{kindLabel('RoleClass')}</option><option value="ObservationClass">{kindLabel('ObservationClass')}</option><option value="ReferenceScheme,ReferenceConcept">{t('ontology.filters.reference')}</option><option value="SchemaArtifact">{kindLabel('SchemaArtifact')}</option></select></label>
      <label className="ontology-select"><Database size={13} /><select value={sourceFilter} onChange={event => setSourceFilter(event.target.value)}><option value="">{t('ontology.filters.allSources')}</option><option value="curated_domain">{sourceLabel('curated_domain')}</option>{ontologyKey === 'abu-dhabi-dmt-gis' ? <option value="dmt_source_catalog">{sourceLabel('dmt_source_catalog')}</option> : <><option value="standard">{sourceLabel('standard')}</option><option value="enterprise_architect">{sourceLabel('enterprise_architect')}</option></>}</select></label></>}
    </div>
    {message && <div className="ontology-message"><AlertTriangle size={14} />{message}<button onClick={() => setMessage('')}><X size={13} /></button></div>}

    <div className={`ontology-body${viewMode === 'modeling' ? ' is-modeling' : ''}`}>
      {viewMode !== 'modeling' && <aside className="ontology-domain-pane"><div className="ontology-pane-title"><Layers3 size={14} /><strong>{t('ontology.domain')}</strong><span>{domains.length}</span></div>
        <button className={`ontology-domain-row ${!selectedDomain ? 'active' : ''}`} onClick={() => { showDomainOverview(''); setMappingOffset(0); }}><div><b>{t('ontology.allDomains')}</b><span>{t('ontology.domainOverview')}</span></div><small>{count(status?.stats?.domain_class_count)}</small></button>
        <div className="ontology-domain-scroll">{domains.map(domain => <button key={domain.domain_id} title={`${domain.domain_id} · ${domain.label}`} className={`ontology-domain-row ${selectedDomain === domain.domain_id ? 'active' : ''}`} onClick={() => { showDomainOverview(domain.domain_id); setMappingOffset(0); }}><div><b>{domain.domain_id}</b><span>{domain.label}</span></div><small>{count(domain.domain_class_count)}</small><div className="ontology-coverage" title={t('ontology.strictCoverage', { value: (domain.strict_coverage * 100).toFixed(1) })}><i style={{ width: `${Math.min(domain.strict_coverage * 100, 100)}%` }} /></div></button>)}</div>
        {selectedDomainData && <div className="ontology-domain-summary"><div><span>{t('ontology.summary.standardFeatures')}</span><b>{count(selectedDomainData.standard_feature_count)}</b></div><div><span>{t('ontology.summary.eaSchemas')}</span><b>{count(selectedDomainData.ea_schema_count)}</b></div><div><span>{t('ontology.summary.fields')}</span><b>{count(selectedDomainData.property_count)}</b></div><div><span>{t('ontology.summary.coverage')}</span><b>{(selectedDomainData.strict_coverage * 100).toFixed(1)}%</b></div></div>}
      </aside>}

      <main className="ontology-main-pane">
        {viewMode === 'modeling' && <OntologyModelingPanel apiBase={ontologyApi} userRole={userRole} selectedConcept={concept} domainOptions={domains.map(domain => ({ domain_id: domain.domain_id, label: domain.label }))} ontologyTitle={status?.short_title} onDraftChanged={() => { void loadBootstrap(); if (selectedConceptId) void loadConcept(selectedConceptId); }} />}
        {viewMode === 'graph' && <>
          <div className="ontology-view-title ontology-graph-title">
            <div className="ontology-graph-heading">
              <strong>{graphTitle}</strong>
              <span>{graphStats}{graphMeta.truncated ? ` · ${t('ontology.truncated')}` : ''}</span>
              {focusedConceptId && <nav className="ontology-breadcrumb" aria-label={t('ontology.breadcrumb')}>
                <button title={t('ontology.actions.backToDomain')} onClick={() => showDomainOverview()}>{selectedDomainData?.label || t('ontology.domainOverview')}</button>
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
                <button title={t('ontology.actions.previous')} aria-label={t('ontology.actions.previous')} disabled={navigation.index <= 0} onClick={() => openHistoryEntry(navigation.index - 1)}><ArrowLeft size={13} /></button>
                <button title={t('ontology.actions.next')} aria-label={t('ontology.actions.next')} disabled={navigation.index < 0 || navigation.index >= navigation.entries.length - 1} onClick={() => openHistoryEntry(navigation.index + 1)}><ArrowRight size={13} /></button>
                <button title={t('ontology.actions.backToDomain')} aria-label={t('ontology.actions.backToDomain')} onClick={() => showDomainOverview()}><Home size={13} /></button>
              </div>
              <div className="ontology-depth-segments" aria-label={t('ontology.relationDepth')}>
                {([1, 2, 3] as GraphDepth[]).map(depth => <button
                  key={depth}
                  className={graphDepth === depth ? 'active' : ''}
                  aria-pressed={graphDepth === depth}
                  onClick={() => setGraphDepth(depth)}
                >{t('ontology.depth', { depth })}</button>)}
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
              <OntologyMiniMap
                nodes={visibleGraphNodes}
                edges={graph.edges}
                selectedNodeId={selectedConceptId}
                onNodeClick={node => {
                  const width = node.measured?.width || node.width || 184;
                  const height = node.measured?.height || node.height || 82;
                  void flowInstance.current?.setCenter(
                    node.position.x + width / 2,
                    node.position.y + height / 2,
                    { duration: 240, zoom: 1 },
                  );
                  void selectConcept(node.id);
                }}
              />
            </ReactFlow>
            {graph.edges.length > 0 && <div className="ontology-graph-legend" aria-label={t('ontology.graphLegend')}>
              <span><i className="inheritance" />{t('ontology.legend.inheritance')}</span>
              <span><i className="composition" />{t('ontology.legend.composition')}</span>
              <span><i className="object-relation" />{t('ontology.legend.objectRelation')}</span>
              <span><i className="mapping" />{t('ontology.legend.mapping')}</span>
            </div>}
            {loading && <div className="ontology-loading"><RefreshCw className="spin" size={17} /></div>}
          </div>
        </>}

        {viewMode === 'mappings' && <div className="ontology-table-view"><div className="ontology-view-title"><div><strong>{t('ontology.mappingTitle')}</strong><span>{t('ontology.mappingCount', { count: count(mappingTotal) })}</span></div><label className="ontology-select"><select value={mappingStatus} onChange={event => { setMappingStatus(event.target.value); setMappingOffset(0); }}><option value="">{t('ontology.filters.allStatuses')}</option><option value="confirmed">{t('ontology.status.confirmed')}</option><option value="candidate">{t('ontology.status.candidate')}</option><option value="conflict">{t('ontology.status.conflict')}</option><option value="rejected">{t('ontology.status.rejected')}</option></select></label></div>
          <div className="ontology-table-scroll"><table><thead><tr><th>{t('ontology.mapping.source')}</th><th>{t('ontology.mapping.semantic')}</th><th>{t('ontology.mapping.target')}</th><th>{t('ontology.mapping.evidence')}</th></tr></thead><tbody>{mappings.map(row => <tr key={row.mapping_id} onClick={() => focusConcept(row.source_concept_id, row.source_concept)}><td><strong>{row.source_concept?.pref_label}</strong><small>{row.source_concept?.code}</small></td><td><span className={`ontology-status status-${row.mapping_status}`}>{t(`ontology.status.${row.mapping_status}`, { defaultValue: row.mapping_status })}</span><small>{row.mapping_type}</small></td><td><strong>{row.target_concept?.pref_label}</strong><small>{row.target_concept?.code}</small></td><td><span>{row.confidence == null ? '-' : `${(row.confidence * 100).toFixed(0)}%`}</span><small>{(row.evidence?.match_basis || []).join(' + ')}</small></td></tr>)}</tbody></table></div>
          <div className="ontology-pagination"><button disabled={mappingOffset === 0} onClick={() => setMappingOffset(Math.max(0, mappingOffset - 80))}><ChevronLeft size={14} /></button><span>{mappingTotal ? mappingOffset + 1 : 0}-{Math.min(mappingOffset + 80, mappingTotal)} / {mappingTotal}</span><button disabled={mappingOffset + 80 >= mappingTotal} onClick={() => setMappingOffset(mappingOffset + 80)}><ChevronRight size={14} /></button></div></div>}

        {viewMode === 'validation' && <div className="ontology-validation-view"><div className="ontology-view-title"><div><strong>{t('ontology.validation.title')}</strong><span>{t('ontology.validation.issueCount', { count: count(validation?.issue_count) })}</span></div><span className={`ontology-conformance ${validation?.conforms ? 'ok' : 'error'}`}>{validation?.conforms ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}{validation?.conforms ? t('ontology.validation.passed') : t('ontology.validation.problem')}</span></div>
          <div className="ontology-validation-summary"><div><span>{t('ontology.validation.structure')}</span><b>{validation?.shacl_conforms ? t('ontology.common.passed') : t('ontology.common.failed')}</b></div><div><span>{t('ontology.validation.errors')}</span><b>{count(validation?.severity_counts?.error)}</b></div><div><span>{t('ontology.validation.warnings')}</span><b>{count(validation?.severity_counts?.warning)}</b></div><div><span>{t('ontology.validation.pending')}</span><b>{count(validation?.issue_count)}</b></div></div>
          <div className="ontology-issue-list">{visibleIssues.map((issue: Row, index: number) => <div key={`${issue.code}-${index}`}><span className={`ontology-issue-severity ${issue.severity}`}>{issue.severity}</span><strong>{issue.code}</strong><code>{issue.table || issue.source || issue.relation_id || issue.ea_object_id || ''}</code><span>{issue.field || issue.heading || issue.raw_datatype || (issue.count ? t('ontology.validation.issueItems', { count: issue.count }) : '')}</span></div>)}</div></div>}
      </main>

      {viewMode !== 'modeling' && <aside className={`ontology-detail-pane${concept ? ' has-selection' : ''}`}>
        {concept ? <>
          <div className="ontology-detail-head">
            <div className="ontology-detail-identity"><span>{kindLabel(concept.kind)}</span><strong>{concept.pref_label}</strong><code>{concept.code || 'no-code'}</code></div>
            <div className="ontology-detail-actions">
              <button
                title={focusedConceptId === selectedConceptId ? t('ontology.actions.alreadyCentered') : t('ontology.actions.centerObject')}
                aria-label={t('ontology.actions.centerObject')}
                disabled={focusedConceptId === selectedConceptId}
                onClick={() => focusConcept(concept.concept_id, concept)}
              ><LocateFixed size={15} /></button>
              <button title={t('ontology.actions.clearSelection')} aria-label={t('ontology.actions.clearSelection')} onClick={() => {
                conceptRequest.current += 1;
                setSelectedConceptId('');
                setConcept(null);
                setProperties([]);
                setRelations([]);
              }}><X size={15} /></button>
            </div>
            <div className="ontology-detail-metrics"><span><b>{count(propertyGroupCounts.direct)}</b>{t('ontology.detail.direct')}</span><span><b>{count(propertyTotal)}</b>{t('ontology.detail.effectiveFields')}</span><span><b>{count(relationTotal)}</b>{t('ontology.detail.relations')}</span></div>
            {concept.definition && <p title={concept.definition}>{concept.definition}</p>}
          </div>
          <div className="ontology-detail-tabs">
            <button className={detailMode === 'overview' ? 'active' : ''} onClick={() => setDetailMode('overview')}>{t('ontology.detail.overview')}</button>
            <button className={detailMode === 'fields' ? 'active' : ''} onClick={() => setDetailMode('fields')}>{t('ontology.detail.fields')} <span>{propertyTotal}</span></button>
            <button className={detailMode === 'relations' ? 'active' : ''} onClick={() => setDetailMode('relations')}>{t('ontology.detail.relationsTab')} <span>{relationTotal}</span></button>
            <button className={detailMode === 'provenance' ? 'active' : ''} onClick={() => setDetailMode('provenance')}>{t('ontology.detail.provenance')}</button>
          </div>
          <div className="ontology-detail-scroll">
            {detailMode === 'overview' && <div className="ontology-object-overview">
              <section><h4>{t('ontology.detail.objectDefinition')}</h4><p>{concept.definition || t('ontology.detail.noDefinition')}</p></section>
              <dl>
                <dt>{t('ontology.detail.objectType')}</dt><dd>{kindLabel(concept.kind)}</dd>
                <dt>{t('ontology.detail.domain')}</dt><dd>{domains.find(item => item.domain_id === concept.domain_id)?.label || concept.domain_id || '-'}</dd>
                <dt>{t('ontology.detail.source')}</dt><dd>{sourceLabel(concept.source_system)}</dd>
                <dt>{t('ontology.detail.geometry')}</dt><dd>{concept.geometry_type || t('ontology.detail.nonSpatial')}</dd>
                <dt>{t('ontology.detail.confirmedMappings')}</dt><dd>{count(concept.mapping_count)}</dd>
                <dt>{t('ontology.detail.lifecycle')}</dt><dd><span className={`ontology-status status-${concept.lifecycle_status}`}>{lifecycleLabel(concept.lifecycle_status)}</span></dd>
              </dl>
            </div>}
            {detailMode === 'fields' && <div className="ontology-fields">{PROPERTY_GROUPS.map(group => {
              const groupFields = groupedProperties[group.key];
              const groupTotal = propertyGroupCounts[group.key];
              if (!groupFields.length && !groupTotal) return null;
              return <section className={`ontology-field-group origin-${group.key}`} key={group.key}>
                <h4><span>{t(`ontology.propertyGroups.${group.label}`)}</span><b>{count(groupTotal)}</b></h4>
                {groupFields.map(field => {
                  const domain = valueDomainLabel(field.value_domain);
                  const cardinality = `${field.min_count ?? 0}..${field.max_count == null ? '*' : field.max_count}`;
                  const origin = field.origin_concept || {};
                  const originName = origin.pref_label || origin.code || field.source_object_id || field.source_id;
                  const originSystem = sourceLabel(origin.source_system);
                  return <div className="ontology-field-row" key={field.property_id}>
                    <div className="ontology-field-name"><strong>{field.pref_label}</strong><code>{field.code}</code></div>
                    <span className="ontology-field-type">{field.datatype || t('ontology.detail.undefined')}{field.length ? `(${field.length}${field.scale_value ? `,${field.scale_value}` : ''})` : ''}</span>
                    <div className="ontology-field-constraints">
                      <em className={field.min_count > 0 ? 'required' : ''}>{field.min_count > 0 ? t('ontology.detail.required') : t('ontology.detail.optional')}</em>
                      <span>{t('ontology.detail.cardinality', { value: cardinality })}</span>
                      {domain && <span className="ontology-field-domain" title={domain}>{t('ontology.detail.valueDomain', { value: domain })}</span>}
                      {field.default_value != null && <span title={String(field.default_value)}>{t('ontology.detail.defaultValue', { value: String(field.default_value) })}</span>}
                    </div>
                    <div className="ontology-field-origin" title={`${originSystem} · ${originName || '-'}`}>
                      <span>{group.key === 'direct' ? t('ontology.detail.definedIn') : group.key === 'inherited' ? t('ontology.detail.inheritedFrom', { depth: field.origin_depth }) : t('ontology.detail.mappedFrom')}</span>
                      <strong>{originName || '-'}</strong>
                      <em>{originSystem}</em>
                    </div>
                  </div>;
                })}
              </section>;
            })}
              {properties.length === 0 && <div className="ontology-detail-empty">{t('ontology.detail.noProperties')}</div>}
              {properties.length < propertyTotal && <button onClick={async () => {
                const data = await api<Row>(`${ontologyApi}/properties?concept_id=${encodeURIComponent(concept.concept_id)}&include_effective=true&offset=${properties.length}&limit=500`);
                setProperties(current => [...current, ...(data.items || [])]);
              }}>{t('ontology.detail.loadMoreProperties')}</button>}
            </div>}
            {detailMode === 'relations' && <div className="ontology-relations">{[
              { key: 'out', label: t('ontology.detail.outgoing'), rows: outgoingRelations },
              { key: 'in', label: t('ontology.detail.incoming'), rows: incomingRelations },
            ].map(group => group.rows.length > 0 && <section key={group.key}>
              <h4>{group.label}<span>{group.rows.length}</span></h4>
              {group.rows.map(row => <div className="ontology-relation-row" key={`${row.relation_id}-${row.traversal_direction}`}>
                <button className="ontology-relation-select" onClick={() => void selectConcept(row.other_concept.concept_id, 'relations')} onDoubleClick={() => focusConcept(row.other_concept.concept_id, row.other_concept)}>
                  <span className={`ontology-relation-direction ${row.traversal_direction}`}>{row.traversal_direction === 'out' ? <ArrowRight size={13} /> : <ArrowLeft size={13} />}</span>
                  <div><strong>{row.other_concept.pref_label}</strong><small>{kindLabel(row.other_concept.kind)}{row.other_concept.code ? ` · ${row.other_concept.code}` : ''}</small></div>
                  <em title={row.relation_type}>{relationLabel(row.relation_type, row.pref_label)}</em>
                </button>
                <button className="ontology-relation-focus" title={t('ontology.actions.centerObject')} aria-label={t('ontology.actions.centerNamed', { name: row.other_concept.pref_label })} onClick={() => focusConcept(row.other_concept.concept_id, row.other_concept)}><LocateFixed size={13} /></button>
              </div>)}
            </section>)}
              {relations.length === 0 && <div className="ontology-detail-empty">{t('ontology.detail.noRelations')}</div>}
            </div>}
            {detailMode === 'provenance' && <div className="ontology-provenance"><dl><dt>{t('ontology.provenance.stableId')}</dt><dd><code>{concept.concept_id}</code></dd><dt>URI</dt><dd><code>{concept.uri}</code></dd><dt>{t('ontology.detail.source')}</dt><dd>{sourceLabel(concept.source_system)}</dd><dt>{t('ontology.provenance.sourceObject')}</dt><dd>{concept.source_object_id || '-'}</dd><dt>EA GUID</dt><dd><code>{concept.ea_guid || '-'}</code></dd><dt>{t('ontology.provenance.packagePath')}</dt><dd>{concept.package_path || '-'}</dd><dt>{t('ontology.detail.lifecycle')}</dt><dd><span className={`ontology-status status-${concept.lifecycle_status}`}>{lifecycleLabel(concept.lifecycle_status)}</span></dd></dl>{concept.definition && <p>{concept.definition}</p>}<pre>{JSON.stringify(concept.provenance || {}, null, 2)}</pre></div>}
          </div>
        </> : <>
          <div className="ontology-detail-head ontology-detail-placeholder-head">
            <div className="ontology-detail-identity"><span>{t('ontology.detail.currentSelection')}</span><strong>{t('ontology.detail.objectDetails')}</strong><code>{t('ontology.detail.modelVersion', { version: status?.semantic_version || '-' })}</code></div>
          </div>
          <div className="ontology-detail-scroll">
            <div className="ontology-model-overview">
              <h4>{selectedDomainData?.label || `${status?.short_title || t('ontology.industryOntology')}${t('ontology.fullModel')}`}</h4>
              <div><span>{t('ontology.kpis.domainClasses')}</span><b>{count(selectedDomainData?.domain_class_count || status?.stats?.domain_class_count)}</b></div>
              <div><span>{t('ontology.kpis.relations')}</span><b>{count(status?.stats?.relation_count)}</b></div>
              <div><span>{t('ontology.kpis.artifacts')}</span><b>{count(selectedDomainData?.standard_feature_count || status?.stats?.schema_artifact_count)}</b></div>
              <div><span>{t('ontology.detail.fieldDefinitions')}</span><b>{count(selectedDomainData?.property_count || status?.stats?.property_count)}</b></div>
              <section><span>{t('ontology.layers.semantic')}</span><strong>{t('ontology.sources.curatedDomain')}</strong></section>
              <section><span>{t('ontology.layers.standard')}</span><strong>{ontologyKey === 'abu-dhabi-dmt-gis' ? 'DMT CDM / LDM' : t('ontology.sources.naturalResourceStandard')}</strong></section>
              <section><span>{t('ontology.layers.implementation')}</span><strong>{ontologyKey === 'abu-dhabi-dmt-gis' ? 'DMT PDM / source catalog' : 'Enterprise Architect'}</strong></section>
            </div>
          </div>
        </>}
      </aside>}
    </div>
    {showTechnicalStatus && <footer className="ontology-footer"><span>{status?.model_profile}</span><span title={status?.content_sha256}>{t('ontology.footer.package')} {status?.content_sha256?.slice(0, 12)}</span><span>{status?.backend === 'immutable_package' ? t('ontology.footer.immutable') : status?.backend}</span><span>{status?.projection?.sparql_endpoint ? 'SPARQL ready' : 'RDF package ready'}</span></footer>}
  </div>;
}
