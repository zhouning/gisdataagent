import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  ClipboardCheck,
  Download,
  GitBranch,
  Layers,
  Package,
  ScanSearch,
  Workflow,
  RefreshCw,
  Send,
  ShieldCheck,
  ShieldOff,
  Star,
  Users,
  X,
} from 'lucide-react';
import L from 'leaflet';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';
import { getAssetCategory, getAssetIcon } from './utils';

interface CatalogAsset {
  id: number;
  asset_name: string;
  asset_type: string;
  file_format: string;
  storage_backend: string;
  crs: string;
  feature_count: number;
  file_size_bytes: number;
  tags: string[];
  description: string;
  owner_user: string;
  is_shared: boolean;
  created_at: string;
  sensitivity_level?: string;
  version?: number | string;
  asset_code?: string;
  relevance?: number;
}

interface LifecycleStage {
  id: string;
  label: string;
  status: 'complete' | 'current' | 'attention' | 'pending';
  achieved: boolean;
}

interface ReadinessCheck {
  id: string;
  label: string;
  status: 'passed' | 'missing' | 'warning' | 'not_applicable';
  message: string;
}

interface LifecycleAsset {
  id: number;
  asset_code?: string;
  asset_name: string;
  display_name: string;
  asset_type: string;
  description: string;
  tags: string[];
  owner: string;
  is_shared: boolean;
  access_level: string;
  sensitivity_level?: string;
  license?: string;
  file_format?: string;
  storage_backend?: string;
  crs?: string;
  spatial_extent?: {
    minx?: number;
    miny?: number;
    maxx?: number;
    maxy?: number;
  };
  feature_count: number;
  file_size_bytes: number;
  column_schema: Array<{ name: string; type: string }>;
  version?: number | string;
}

interface LineageNode {
  id?: number;
  name?: string;
  type?: string;
  creation_tool?: string;
}

interface AssetLifecycle {
  asset: LifecycleAsset;
  current_stage: string;
  current_stage_label: string;
  stages: LifecycleStage[];
  readiness: {
    score: number;
    ready: boolean;
    checks: ReadinessCheck[];
    blockers: string[];
    warnings: string[];
  };
  publication: {
    evidence_detected: boolean;
    evidence: string[];
    status: string;
    data_product_urn?: string;
  };
  quality: {
    has_evidence: boolean;
    score: number | null;
    issues_count: number;
    assessed_at?: string;
  };
  usage: {
    total_accesses: number;
    unique_users: number;
    last_accessed_at?: string;
  };
  reviews: { avg_rating: number; count: number };
  versions: { current?: number | string; history_count: number };
  lineage: {
    asset?: LineageNode;
    ancestors: LineageNode[];
    descendants: LineageNode[];
    has_evidence: boolean;
    source_count: number;
    derived_count: number;
  };
  distribution_requests: Record<string, number>;
  request_access: {
    is_owner: boolean;
    can_request: boolean;
    can_package: boolean;
    my_request: DistributionRequestItem | null;
    active_grant: DistributionRequestItem | null;
    pending_items?: DistributionRequestItem[];
    active_items?: DistributionRequestItem[];
  };
}

interface ProductVersionBinding {
  tenant_id: string;
  product_urn: string;
  data_product_version_id: string;
  version_key: string;
}

interface DistributionRequestItem {
  id: number;
  status: 'pending' | 'approved' | 'rejected';
  requester: string;
  reason: string;
  approver?: string;
  reject_reason?: string;
  requested_operations: string[];
  requested_duration_days: number;
  requested_package_quota: number;
  granted_operations: string[];
  granted_package_quota: number;
  packages_created: number;
  packages_remaining: number;
  quota_exhausted: boolean;
  grant_status: 'none' | 'active' | 'expired' | 'revoked';
  grant_contract: 'asset_compatibility' | 'data_product_version';
  product_version?: ProductVersionBinding | null;
  expires_at?: string;
  revoked_at?: string;
  revoked_by?: string;
  revocation_reason?: string;
  created_at?: string;
  approved_at?: string;
}

interface CatalogTabProps {
  userRole?: string;
  username?: string;
  onAddMapLayer?: (layer: MapPublicationLayer) => void;
}

export interface MapPublicationLayer {
  layer_id: string;
  publication_id: string;
  name: string;
  type: 'mvt';
  tile_url: string;
  metadata_url: string;
  feature_url_template: string;
  source_layer: string;
  style: Record<string, unknown>;
  tooltip_fields: string[];
  visible: boolean;
  min_zoom: number;
  max_zoom: number;
  bounds: [number, number, number, number] | null;
  center: [number, number] | null;
  zoom: number;
}

interface MapPublication {
  publication_id: string;
  status: string;
  feature_count: number;
  min_zoom: number;
  max_zoom: number;
  published_at?: string;
  property_allowlist: string[];
  layer: MapPublicationLayer;
}

const SENS_COLOR: Record<string, string> = {
  public: '#15803d', internal: '#2563eb', confidential: '#b45309',
  restricted: '#dc2626', secret: '#7f1d1d',
};
const PAGE_SIZE = 50;
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${formatNumber(bytes)} B`;
  if (bytes < 1024 * 1024) {
    return `${formatNumber(bytes / 1024, { maximumFractionDigits: 1 })} KB`;
  }
  return `${formatNumber(bytes / (1024 * 1024), { maximumFractionDigits: 1 })} MB`;
}

function normalizeTags(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value !== 'string' || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed)) return parsed.map(String);
  } catch { /* comma-delimited legacy tags */ }
  return value.split(',').map(tag => tag.trim()).filter(Boolean);
}

function normalizeCatalogAsset(raw: Record<string, unknown>): CatalogAsset {
  return {
    id: Number(raw.id),
    asset_name: String(raw.asset_name ?? raw.name ?? ''),
    asset_type: String(raw.asset_type ?? raw.type ?? 'other'),
    file_format: String(raw.file_format ?? raw.format ?? ''),
    storage_backend: String(raw.storage_backend ?? raw.backend ?? ''),
    crs: String(raw.crs ?? ''),
    feature_count: Number(raw.feature_count ?? raw.features ?? 0),
    file_size_bytes: Number(raw.file_size_bytes ?? raw.size_bytes ?? 0),
    tags: normalizeTags(raw.tags),
    description: String(raw.description ?? ''),
    owner_user: String(raw.owner_user ?? raw.owner_username ?? raw.owner ?? ''),
    is_shared: Boolean(raw.is_shared ?? raw.shared ?? false),
    created_at: String(raw.created_at ?? raw.created ?? ''),
    sensitivity_level: raw.sensitivity_level ? String(raw.sensitivity_level) : undefined,
    version: raw.version as number | string | undefined,
    asset_code: raw.asset_code ? String(raw.asset_code) : undefined,
    relevance: raw.relevance == null ? undefined : Number(raw.relevance),
  };
}

export default function CatalogTab({
  userRole = 'analyst',
  username = '',
  onAddMapLayer,
}: CatalogTabProps) {
  const { t, i18n } = useTranslation('common');
  const [assets, setAssets] = useState<CatalogAsset[]>([]);
  const [keyword, setKeyword] = useState('');
  const [assetType, setAssetType] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<CatalogAsset | null>(null);
  const [searchMode, setSearchMode] = useState<'keyword' | 'semantic'>('keyword');
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);

  const fetchAssets = async () => {
    setLoading(true);
    try {
      let response: Response;
      if (searchMode === 'semantic' && keyword.trim()) {
        const params = new URLSearchParams({ q: keyword });
        response = await fetch(`/api/catalog/search?${params}`, {
          credentials: 'include',
          headers: getLocaleHeaders(),
        });
      } else {
        const params = new URLSearchParams();
        if (keyword) params.set('keyword', keyword);
        if (assetType) params.set('asset_type', assetType);
        params.set('offset', String(page * PAGE_SIZE));
        params.set('limit', String(PAGE_SIZE));
        response = await fetch(`/api/catalog?${params}`, {
          credentials: 'include',
          headers: getLocaleHeaders(),
        });
      }
      if (response.ok) {
        const data = await response.json();
        const rows = Array.isArray(data.assets) ? data.assets : [];
        setAssets(rows.map((row: Record<string, unknown>) => normalizeCatalogAsset(row)));
        setTotal(data.total ?? data.count ?? 0);
      }
    } catch { /* retain the last usable catalog response */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    const interval = setInterval(fetchAssets, 30000);
    return () => clearInterval(interval);
  }, [keyword, assetType, page, searchMode, i18n.resolvedLanguage]);

  useEffect(() => {
    const timer = setTimeout(fetchAssets, 300);
    return () => clearTimeout(timer);
  }, [keyword, assetType, page, searchMode, i18n.resolvedLanguage]);

  useEffect(() => { setPage(0); }, [keyword, assetType, searchMode]);

  if (selectedAsset) {
    return (
      <AssetDetail
        asset={selectedAsset}
        onBack={() => setSelectedAsset(null)}
        userRole={userRole}
        username={username}
        onAddMapLayer={onAddMapLayer}
      />
    );
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="catalog-view">
      <div className="catalog-filter-bar">
        <input
          type="text"
          placeholder={searchMode === 'keyword'
            ? t('assetWorkbench.catalog.searchPlaceholder')
            : t('assetWorkbench.catalog.semanticSearchPlaceholder')}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          className="catalog-search"
        />
        <select
          value={assetType}
          onChange={(event) => setAssetType(event.target.value)}
          className="catalog-type-select"
        >
          <option value="">{t('assetWorkbench.catalog.allTypes')}</option>
          {['vector', 'raster', 'tabular', 'map', 'report'].map(type => (
            <option key={type} value={type}>{t(`assetWorkbench.catalog.assetTypes.${type}`)}</option>
          ))}
        </select>
        <button
          className={`catalog-search-mode ${searchMode === 'semantic' ? 'active' : ''}`}
          onClick={() => setSearchMode(mode => mode === 'keyword' ? 'semantic' : 'keyword')}
          title={searchMode === 'keyword'
            ? t('assetWorkbench.catalog.switchToSemantic')
            : t('assetWorkbench.catalog.switchToKeyword')}
        >
          {searchMode === 'keyword'
            ? t('assetWorkbench.catalog.keyword')
            : t('assetWorkbench.catalog.semantic')}
        </button>
      </div>
      {loading && assets.length === 0 ? (
        <div className="empty-state">{t('assetWorkbench.common.loading')}</div>
      ) : assets.length === 0 ? (
        <div className="empty-state">{t('assetWorkbench.common.noAssets')}</div>
      ) : (
        <>
          <ul className="file-list">
            {assets.map(asset => (
              <li key={asset.id} className="file-item" onClick={() => setSelectedAsset(asset)}>
                <div className={`file-icon-circle ${getAssetCategory(asset.asset_type)}`}>
                  {getAssetIcon(asset.asset_type)}
                </div>
                <div className="file-info">
                  <div className="file-name" title={asset.asset_name}>{asset.asset_name}</div>
                  {asset.asset_code && <div className="catalog-asset-code">{asset.asset_code}</div>}
                  <div className="file-meta">
                    <span className={`type-badge ${asset.asset_type}`}>
                      {t(`assetWorkbench.catalog.assetTypes.${asset.asset_type}`, {
                        defaultValue: asset.asset_type,
                      })}
                    </span>
                    {asset.sensitivity_level && asset.sensitivity_level !== 'public' && (
                      <span className="sensitivity-badge" style={{
                        background: `${SENS_COLOR[asset.sensitivity_level] || '#6b7280'}20`,
                        color: SENS_COLOR[asset.sensitivity_level] || '#6b7280',
                      }}>
                        {t(`assetWorkbench.catalog.sensitivity.${asset.sensitivity_level}`, {
                          defaultValue: asset.sensitivity_level,
                        })}
                      </span>
                    )}
                    {asset.feature_count > 0 && (
                      <span>{t('assetWorkbench.catalog.featureCountShort', { count: formatNumber(asset.feature_count) })}</span>
                    )}
                    {asset.crs && <span>{asset.crs}</span>}
                    {asset.relevance !== undefined && (
                      <span className="relevance-score">{Math.round(asset.relevance * 100)}%</span>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {searchMode === 'keyword' && totalPages > 1 && (
            <div className="catalog-pagination">
              <button disabled={page === 0} onClick={() => setPage(value => value - 1)}>
                &laquo; {t('assetWorkbench.common.previous')}
              </button>
              <span className="catalog-page-info">
                {t('assetWorkbench.catalog.pagination', {
                  current: formatNumber(page + 1),
                  pages: formatNumber(totalPages),
                  total: formatNumber(total),
                })}
              </span>
              <button disabled={page + 1 >= totalPages} onClick={() => setPage(value => value + 1)}>
                {t('assetWorkbench.common.next')} &raquo;
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StageIcon({ status }: { status: LifecycleStage['status'] }) {
  if (status === 'complete') return <CheckCircle2 aria-hidden="true" />;
  if (status === 'current') return <Clock3 aria-hidden="true" />;
  if (status === 'attention') return <AlertTriangle aria-hidden="true" />;
  return <Circle aria-hidden="true" />;
}

function AssetDetail({
  asset,
  onBack,
  userRole,
  username,
  onAddMapLayer,
}: {
  asset: CatalogAsset;
  onBack: () => void;
  userRole: string;
  username: string;
  onAddMapLayer?: (layer: MapPublicationLayer) => void;
}) {
  const { t } = useTranslation('common');
  const [lifecycle, setLifecycle] = useState<AssetLifecycle | null>(null);
  const [lifecycleLoading, setLifecycleLoading] = useState(true);
  const [lifecycleError, setLifecycleError] = useState('');
  const [requestFormOpen, setRequestFormOpen] = useState(false);
  const [requestReason, setRequestReason] = useState('');
  const [requestDurationDays, setRequestDurationDays] = useState(30);
  const [requestPackageQuota, setRequestPackageQuota] = useState(5);
  const [distributionBusy, setDistributionBusy] = useState('');
  const [distributionError, setDistributionError] = useState('');
  const [packageResult, setPackageResult] = useState<{
    name: string;
    url: string;
  } | null>(null);
  const [rejectingRequestId, setRejectingRequestId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [revokingRequestId, setRevokingRequestId] = useState<number | null>(null);
  const [revocationReason, setRevocationReason] = useState('');
  const [mapPublication, setMapPublication] = useState<MapPublication | null>(null);
  const [mapPublicationLoading, setMapPublicationLoading] = useState(true);
  const [mapPublicationBusy, setMapPublicationBusy] = useState(false);
  const [mapPublicationError, setMapPublicationError] = useState('');
  const bboxRef = useRef<HTMLDivElement>(null);

  const loadLifecycle = useCallback(async () => {
    setLifecycleLoading(true);
    setLifecycleError('');
    try {
      const response = await fetch(`/api/catalog/${asset.id}/lifecycle`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (!response.ok) {
        throw new Error(response.status === 404
          ? t('assetWorkbench.catalog.errors.assetUnavailable')
          : t('assetWorkbench.catalog.errors.lifecycleUnavailable'));
      }
      setLifecycle(await response.json());
    } catch (error) {
      setLifecycleError(error instanceof Error
        ? error.message
        : t('assetWorkbench.catalog.errors.lifecycleUnavailable'));
    } finally {
      setLifecycleLoading(false);
    }
  }, [asset.id, t]);

  useEffect(() => { void loadLifecycle(); }, [loadLifecycle]);

  const loadMapPublication = useCallback(async () => {
    setMapPublicationLoading(true);
    setMapPublicationError('');
    try {
      const response = await fetch(`/api/catalog/${asset.id}/map-publications/current`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (response.status === 404) {
        setMapPublication(null);
        return;
      }
      if (!response.ok) throw new Error(t('assetWorkbench.catalog.errors.mapStatusUnavailable'));
      const body = await response.json();
      setMapPublication(body.publication as MapPublication);
    } catch (error) {
      setMapPublicationError(error instanceof Error
        ? error.message
        : t('assetWorkbench.catalog.errors.mapStatusUnavailable'));
    } finally {
      setMapPublicationLoading(false);
    }
  }, [asset.id, t]);

  useEffect(() => { void loadMapPublication(); }, [loadMapPublication]);

  const detail: LifecycleAsset = lifecycle?.asset ?? {
    id: asset.id,
    asset_code: asset.asset_code,
    asset_name: asset.asset_name,
    display_name: asset.asset_name,
    asset_type: asset.asset_type,
    description: asset.description,
    tags: asset.tags,
    owner: asset.owner_user,
    is_shared: asset.is_shared,
    access_level: asset.is_shared ? 'shared' : 'private',
    sensitivity_level: asset.sensitivity_level,
    file_format: asset.file_format,
    storage_backend: asset.storage_backend,
    crs: asset.crs,
    feature_count: asset.feature_count,
    file_size_bytes: asset.file_size_bytes,
    column_schema: [],
    version: asset.version,
  };
  const lineage = lifecycle?.lineage;
  const reviews = lifecycle?.reviews;

  useEffect(() => {
    const extent = detail.spatial_extent;
    if (!extent || !bboxRef.current) return;
    if (extent.minx == null || extent.miny == null || extent.maxx == null || extent.maxy == null) return;

    const bounds: L.LatLngBoundsLiteral = [
      [extent.miny, extent.minx],
      [extent.maxy, extent.maxx],
    ];
    const map = L.map(bboxRef.current, {
      zoomControl: false,
      attributionControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      touchZoom: false,
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);
    L.rectangle(bounds, {
      color: '#0f766e', weight: 2, fillColor: '#0f766e', fillOpacity: 0.15,
    }).addTo(map);
    map.fitBounds(bounds, { padding: [10, 10] });
    return () => { map.remove(); };
  }, [detail.spatial_extent]);

  const handleRate = async (score: number) => {
    try {
      const response = await fetch(`/api/catalog/${asset.id}/review`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ rating: score, comment: '' }),
      });
      if (response.ok) await loadLifecycle();
    } catch { /* keep the existing rating */ }
  };

  const responseError = async (_response: Response, fallback: string) => fallback;

  const handleRequestAccess = async () => {
    const reason = requestReason.trim();
    if (!reason) {
      setDistributionError(t('assetWorkbench.catalog.errors.reasonRequired'));
      return;
    }
    setDistributionBusy('create');
    setDistributionError('');
    try {
      const response = await fetch('/api/data-requests', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          asset_id: asset.id,
          reason,
          duration_days: requestDurationDays,
          package_quota: requestPackageQuota,
        }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response, t('assetWorkbench.catalog.errors.requestFailed')));
      }
      setRequestReason('');
      setRequestFormOpen(false);
      await loadLifecycle();
    } catch (error) {
      setDistributionError(error instanceof Error
        ? error.message
        : t('assetWorkbench.catalog.errors.requestFailed'));
    } finally {
      setDistributionBusy('');
    }
  };

  const handleCreatePackage = async () => {
    setDistributionBusy('package');
    setDistributionError('');
    setPackageResult(null);
    try {
      const response = await fetch('/api/assets/package', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ asset_ids: [asset.id] }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response, t('assetWorkbench.catalog.errors.packageFailed')));
      }
      const body = await response.json();
      setPackageResult({
        name: String(body.zip_name || 'data-package.zip'),
        url: String(body.download_url || ''),
      });
      await loadLifecycle();
    } catch (error) {
      setDistributionError(error instanceof Error
        ? error.message
        : t('assetWorkbench.catalog.errors.packageFailed'));
    } finally {
      setDistributionBusy('');
    }
  };

  const handleReviewRequest = async (
    requestId: number,
    action: 'approve' | 'reject',
  ) => {
    const reason = rejectReason.trim();
    if (action === 'reject' && !reason) {
      setDistributionError(t('assetWorkbench.catalog.errors.rejectReasonRequired'));
      return;
    }
    setDistributionBusy(`${action}-${requestId}`);
    setDistributionError('');
    try {
      const response = await fetch(`/api/data-requests/${requestId}/${action}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(action === 'reject' ? { reason } : {}),
      });
      if (!response.ok) {
        throw new Error(await responseError(response, t('assetWorkbench.catalog.errors.reviewFailed')));
      }
      setRejectingRequestId(null);
      setRejectReason('');
      await loadLifecycle();
    } catch (error) {
      setDistributionError(error instanceof Error
        ? error.message
        : t('assetWorkbench.catalog.errors.reviewFailed'));
    } finally {
      setDistributionBusy('');
    }
  };

  const handleRevokeRequest = async (requestId: number) => {
    const reason = revocationReason.trim();
    if (!reason) {
      setDistributionError(t('assetWorkbench.catalog.errors.revokeReasonRequired'));
      return;
    }
    setDistributionBusy(`revoke-${requestId}`);
    setDistributionError('');
    try {
      const response = await fetch(`/api/data-requests/${requestId}/revoke`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ reason }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response, t('assetWorkbench.catalog.errors.revokeFailed')));
      }
      setRevokingRequestId(null);
      setRevocationReason('');
      await loadLifecycle();
    } catch (error) {
      setDistributionError(error instanceof Error
        ? error.message
        : t('assetWorkbench.catalog.errors.revokeFailed'));
    } finally {
      setDistributionBusy('');
    }
  };

  const sensitivity = detail.sensitivity_level || '';
  const pendingRequests = lifecycle?.distribution_requests?.pending || 0;
  const requestAccess = lifecycle?.request_access;
  const myRequest = requestAccess?.my_request;
  const activeGrant = requestAccess?.active_grant;
  const adminPendingItems = requestAccess?.pending_items || [];
  const adminActiveItems = requestAccess?.active_items || [];
  const isAdmin = userRole === 'admin';
  const isOwner = requestAccess?.is_owner ?? Boolean(username && detail.owner === username);
  const canPublishMap = isAdmin || isOwner;
  const readinessBlockers = lifecycle?.readiness.checks.filter(check => check.status === 'missing') || [];
  const readinessWarnings = lifecycle?.readiness.checks.filter(check => check.status === 'warning') || [];
  const formatGrantExpiry = (value?: string) => value
    ? formatDate(value, { year: 'numeric', month: '2-digit', day: '2-digit' })
    : t('assetWorkbench.common.notSet');

  const openMcpChat = (server: 'arcpy' | 'dts') => {
    const text = server === 'arcpy'
      ? t('assetWorkbench.catalog.prompts.arcpy', { id: asset.id })
      : t('assetWorkbench.catalog.prompts.dts', { id: asset.id });
    window.dispatchEvent(new CustomEvent('gda-chat-prefill', { detail: { text } }));
  };

  const handlePublishMap = async () => {
    setMapPublicationBusy(true);
    setMapPublicationError('');
    try {
      const response = await fetch(`/api/catalog/${asset.id}/map-publications`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(await responseError(response, t('assetWorkbench.catalog.errors.mapPublishFailed')));
      }
      const body = await response.json();
      const publication = body.publication as MapPublication;
      const layer = (body.layer || publication.layer) as MapPublicationLayer;
      setMapPublication(publication);
      onAddMapLayer?.(layer);
    } catch (error) {
      setMapPublicationError(error instanceof Error
        ? error.message
        : t('assetWorkbench.catalog.errors.mapPublishFailed'));
    } finally {
      setMapPublicationBusy(false);
    }
  };

  return (
    <div className="asset-detail">
      <button className="asset-back-btn" onClick={onBack} title={t('assetWorkbench.catalog.backTitle')}>
        <ArrowLeft className="rtl-flip" aria-hidden="true" />
        <span>{t('assetWorkbench.common.backToList')}</span>
      </button>
      <div className="asset-detail-heading">
        <div>
          <h3 className="asset-detail-title">{detail.display_name || detail.asset_name}</h3>
          {detail.asset_code && <code>{detail.asset_code}</code>}
        </div>
        <div className="asset-heading-actions">
          <button type="button" onClick={() => openMcpChat('arcpy')} title={t('assetWorkbench.catalog.arcpyTitle')}>
            <Workflow aria-hidden="true" />
            <span>{t('assetWorkbench.catalog.arcpyAction')}</span>
          </button>
          <button type="button" onClick={() => openMcpChat('dts')} title={t('assetWorkbench.catalog.dtsTitle')}>
            <ScanSearch aria-hidden="true" />
            <span>{t('assetWorkbench.catalog.dtsAction')}</span>
          </button>
          {lifecycle && (
            <span className={`asset-stage-badge ${lifecycle.current_stage}`}>
              {t(`assetWorkbench.catalog.lifecycleStages.${lifecycle.current_stage}`, {
                defaultValue: lifecycle.current_stage_label,
              })}
            </span>
          )}
        </div>
      </div>

      {lifecycleLoading && (
        <div className="asset-lifecycle-loading">{t('assetWorkbench.catalog.loadingEvidence')}</div>
      )}
      {lifecycleError && (
        <div className="asset-lifecycle-error" role="alert">
          <AlertTriangle aria-hidden="true" />
          <span>{lifecycleError}</span>
        </div>
      )}

      {lifecycle && (
        <section className="asset-lifecycle-section" aria-label={t('assetWorkbench.catalog.lifecycleAria')}>
          <div className="asset-section-heading">
            <div>
              <ShieldCheck aria-hidden="true" />
              <h4>{t('assetWorkbench.catalog.lifecycleReadiness')}</h4>
            </div>
            <strong className={lifecycle.readiness.ready ? 'ready' : ''}>
              {lifecycle.readiness.score}<span>/100</span>
            </strong>
          </div>

          <div className="asset-lifecycle-steps">
            {lifecycle.stages.map((stage, index) => (
              <div key={stage.id} className={`asset-lifecycle-step ${stage.status}`}>
                <div className="asset-lifecycle-step-marker">
                  <StageIcon status={stage.status} />
                  {index < lifecycle.stages.length - 1 && <span aria-hidden="true" />}
                </div>
                <span>{t(`assetWorkbench.catalog.lifecycleStages.${stage.id}`, { defaultValue: stage.label })}</span>
              </div>
            ))}
          </div>

          <div className="asset-operation-metrics">
            <div>
              <ShieldCheck aria-hidden="true" />
              <span>{t('assetWorkbench.catalog.metrics.quality')}</span>
              <strong>{lifecycle.quality.has_evidence && lifecycle.quality.score != null
                ? formatNumber(lifecycle.quality.score)
                : '-'}</strong>
            </div>
            <div>
              <Activity aria-hidden="true" />
              <span>{t('assetWorkbench.catalog.metrics.accesses')}</span>
              <strong>{formatNumber(lifecycle.usage.total_accesses)}</strong>
            </div>
            <div>
              <Users aria-hidden="true" />
              <span>{t('assetWorkbench.catalog.metrics.users')}</span>
              <strong>{formatNumber(lifecycle.usage.unique_users)}</strong>
            </div>
            <div>
              <Clock3 aria-hidden="true" />
              <span>{t('assetWorkbench.catalog.metrics.version')}</span>
              <strong>v{lifecycle.versions.current || detail.version || 1}</strong>
            </div>
          </div>

          <div className={`asset-readiness-result ${lifecycle.readiness.ready ? 'ready' : 'blocked'}`}>
            <div className="asset-readiness-status">
              {lifecycle.readiness.ready
                ? <CheckCircle2 aria-hidden="true" />
                : <AlertTriangle aria-hidden="true" />}
              <div>
                <strong>{lifecycle.readiness.ready
                  ? t('assetWorkbench.catalog.gatePassed')
                  : t('assetWorkbench.catalog.gateBlocked', { count: formatNumber(readinessBlockers.length) })}</strong>
                <span>{pendingRequests > 0
                  ? t('assetWorkbench.catalog.pendingApprovals', { count: formatNumber(pendingRequests) })
                  : t('assetWorkbench.catalog.noPendingApprovals')}</span>
              </div>
            </div>
            {readinessBlockers.length > 0 && (
              <ul className="asset-readiness-list blockers">
                {readinessBlockers.map(check => (
                  <li key={check.id}>
                    {t(`assetWorkbench.catalog.readinessChecks.${check.id}`, { defaultValue: check.message })}
                  </li>
                ))}
              </ul>
            )}
            {readinessWarnings.length > 0 && (
              <ul className="asset-readiness-list warnings">
                {readinessWarnings.map(check => (
                  <li key={check.id}>
                    {t(`assetWorkbench.catalog.readinessChecks.${check.id}`, { defaultValue: check.message })}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {lifecycle.publication.evidence_detected && !lifecycle.readiness.ready && (
            <div className="asset-publication-drift">
              <AlertTriangle aria-hidden="true" />
              <span>{t('assetWorkbench.catalog.publicationDrift')}</span>
            </div>
          )}
        </section>
      )}

      <section className="asset-map-publication-section" aria-label={t('assetWorkbench.catalog.mapService')}>
        <div className="asset-section-heading compact">
          <div>
            <Layers aria-hidden="true" />
            <h4>{t('assetWorkbench.catalog.mapService')}</h4>
          </div>
          {mapPublication?.status === 'ready' && (
            <span className="asset-map-publication-ready">{t('assetWorkbench.catalog.available')}</span>
          )}
        </div>

        {mapPublicationLoading ? (
          <div className="asset-map-publication-empty">{t('assetWorkbench.catalog.loadingPublication')}</div>
        ) : mapPublication?.status === 'ready' ? (
          <>
            <div className="asset-map-publication-summary">
              <span>MVT</span>
              <span>{t('assetWorkbench.catalog.zoomRange', {
                min: formatNumber(mapPublication.min_zoom), max: formatNumber(mapPublication.max_zoom),
              })}</span>
              <span>{t('assetWorkbench.catalog.publicProperties', {
                count: formatNumber(mapPublication.property_allowlist.length),
              })}</span>
            </div>
            <div className="asset-map-publication-actions">
              <button
                type="button"
                onClick={() => onAddMapLayer?.(mapPublication.layer)}
                disabled={!onAddMapLayer || mapPublicationBusy}
              >
                <Layers aria-hidden="true" />
                <span>{t('assetWorkbench.catalog.addToMap')}</span>
              </button>
              {canPublishMap && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => void handlePublishMap()}
                  disabled={mapPublicationBusy}
                  title={t('assetWorkbench.catalog.republishTitle')}
                >
                  <RefreshCw aria-hidden="true" />
                  <span>{mapPublicationBusy
                    ? t('assetWorkbench.catalog.publishing')
                    : t('assetWorkbench.catalog.republish')}</span>
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="asset-map-publication-empty">{t('assetWorkbench.catalog.notPublishedAsLayer')}</div>
            {canPublishMap && (
              <button
                type="button"
                className="asset-map-publication-create"
                onClick={() => void handlePublishMap()}
                disabled={mapPublicationBusy}
              >
                <Layers aria-hidden="true" />
                <span>{mapPublicationBusy
                  ? t('assetWorkbench.catalog.publishing')
                  : t('assetWorkbench.catalog.publishAsLayer')}</span>
              </button>
            )}
          </>
        )}

        {mapPublicationError && (
          <div className="asset-map-publication-error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <span>{mapPublicationError}</span>
          </div>
        )}
      </section>

      {lifecycle && requestAccess && (
        <section className="asset-distribution-section" aria-label={t('assetWorkbench.catalog.distribution.title')}>
          <div className="asset-section-heading compact">
            <div>
              <ClipboardCheck aria-hidden="true" />
              <h4>{t('assetWorkbench.catalog.distribution.title')}</h4>
            </div>
            {isAdmin && (
              <span>{t('assetWorkbench.catalog.distribution.pendingItems', {
                count: formatNumber(adminPendingItems.length),
              })}</span>
            )}
          </div>

          {isAdmin ? (
            <>
              {adminPendingItems.length > 0 ? (
                <div className="asset-distribution-queue">
                  {adminPendingItems.map(item => (
                    <div className="asset-distribution-request" key={item.id}>
                      <div className="asset-distribution-request-main">
                        <strong>{item.requester}</strong>
                        <span>{item.reason || t('assetWorkbench.catalog.distribution.noPurpose')}</span>
                        <small>
                          {t('assetWorkbench.catalog.distribution.requestSummary', {
                            duration: formatNumber(item.requested_duration_days || 30),
                            quota: formatNumber(item.requested_package_quota || 5),
                          })}
                        </small>
                      </div>
                      <div className="asset-distribution-actions">
                        <button
                          type="button"
                          className="asset-distribution-action approve"
                          onClick={() => void handleReviewRequest(item.id, 'approve')}
                          disabled={Boolean(distributionBusy)}
                          title={t('assetWorkbench.catalog.distribution.approve')}
                          aria-label={t('assetWorkbench.catalog.distribution.approveAria', { requester: item.requester })}
                        >
                          <Check aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="asset-distribution-action reject"
                          onClick={() => {
                            setRejectingRequestId(item.id);
                            setRejectReason('');
                            setDistributionError('');
                          }}
                          disabled={Boolean(distributionBusy)}
                          title={t('assetWorkbench.catalog.distribution.reject')}
                          aria-label={t('assetWorkbench.catalog.distribution.rejectAria', { requester: item.requester })}
                        >
                          <X aria-hidden="true" />
                        </button>
                      </div>
                      {rejectingRequestId === item.id && (
                        <div className="asset-distribution-reject-form">
                          <textarea
                            value={rejectReason}
                            onChange={event => setRejectReason(event.target.value)}
                            placeholder={t('assetWorkbench.catalog.distribution.rejectReason')}
                            aria-label={t('assetWorkbench.catalog.distribution.rejectReason')}
                            rows={2}
                          />
                          <div>
                            <button
                              type="button"
                              onClick={() => void handleReviewRequest(item.id, 'reject')}
                              disabled={distributionBusy === `reject-${item.id}`}
                            >
                              {t('assetWorkbench.catalog.distribution.confirmReject')}
                            </button>
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => setRejectingRequestId(null)}
                              disabled={Boolean(distributionBusy)}
                            >
                              {t('assetWorkbench.common.cancel')}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="asset-distribution-empty">{t('assetWorkbench.catalog.noPendingApprovals')}</div>
              )}

              {adminActiveItems.length > 0 && (
                <div className="asset-active-grants">
                  <div className="asset-active-grants-heading">
                    <ShieldCheck aria-hidden="true" />
                    <strong>{t('assetWorkbench.catalog.distribution.activeGrants', {
                      count: formatNumber(adminActiveItems.length),
                    })}</strong>
                  </div>
                  {adminActiveItems.map(item => (
                    <div className="asset-distribution-request active" key={item.id}>
                      <div className="asset-distribution-request-main">
                        <strong>{item.requester}</strong>
                        <span>{t('assetWorkbench.catalog.distribution.validUntil', {
                          date: formatGrantExpiry(item.expires_at),
                        })}</span>
                        <small>
                          {item.product_version
                            ? t('assetWorkbench.catalog.distribution.lockedVersion', {
                              version: item.product_version.version_key,
                            })
                            : t('assetWorkbench.catalog.distribution.assetGrant')}
                        </small>
                        <small>
                          {t('assetWorkbench.catalog.distribution.quotaUsed', {
                            used: formatNumber(item.packages_created || 0),
                            total: formatNumber(item.granted_package_quota || 0),
                          })}
                        </small>
                      </div>
                      <button
                        type="button"
                        className="asset-distribution-action revoke"
                        onClick={() => {
                          setRevokingRequestId(item.id);
                          setRevocationReason('');
                          setDistributionError('');
                        }}
                        disabled={Boolean(distributionBusy)}
                        title={t('assetWorkbench.catalog.distribution.revoke')}
                        aria-label={t('assetWorkbench.catalog.distribution.revokeAria', { requester: item.requester })}
                      >
                        <ShieldOff aria-hidden="true" />
                      </button>
                      {revokingRequestId === item.id && (
                        <div className="asset-distribution-reject-form revoke">
                          <textarea
                            value={revocationReason}
                            onChange={event => setRevocationReason(event.target.value)}
                            placeholder={t('assetWorkbench.catalog.distribution.revokeReason')}
                            aria-label={t('assetWorkbench.catalog.distribution.revokeReason')}
                            rows={2}
                          />
                          <div>
                            <button
                              type="button"
                              onClick={() => void handleRevokeRequest(item.id)}
                              disabled={distributionBusy === `revoke-${item.id}`}
                            >
                              {t('assetWorkbench.catalog.distribution.confirmRevoke')}
                            </button>
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => setRevokingRequestId(null)}
                              disabled={Boolean(distributionBusy)}
                            >
                              {t('assetWorkbench.common.cancel')}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              {activeGrant && (
                <div className="asset-grant-summary">
                  <ShieldCheck aria-hidden="true" />
                  <div>
                    <strong>{activeGrant.quota_exhausted
                      ? t('assetWorkbench.catalog.distribution.quotaExhausted')
                      : t('assetWorkbench.catalog.distribution.grantActive')}</strong>
                    <span>{t('assetWorkbench.catalog.distribution.packageValidUntil', {
                      date: formatGrantExpiry(activeGrant.expires_at),
                    })}</span>
                    <span>
                      {t('assetWorkbench.catalog.distribution.quotaRemaining', {
                        used: formatNumber(activeGrant.packages_created || 0),
                        total: formatNumber(activeGrant.granted_package_quota || 0),
                        remaining: formatNumber(activeGrant.packages_remaining || 0),
                      })}
                    </span>
                    <small>
                      {activeGrant.product_version
                        ? t('assetWorkbench.catalog.distribution.lockedVersion', {
                          version: activeGrant.product_version.version_key,
                        })
                        : t('assetWorkbench.catalog.distribution.assetGrant')}
                    </small>
                  </div>
                </div>
              )}
              {myRequest && (!activeGrant || myRequest.id !== activeGrant.id) && (
                <div className={`asset-my-request ${['expired', 'revoked'].includes(myRequest.grant_status) ? myRequest.grant_status : myRequest.status}`}>
                  {myRequest.grant_status === 'revoked'
                    ? <ShieldOff aria-hidden="true" />
                    : myRequest.grant_status === 'expired'
                    ? <X aria-hidden="true" />
                    : myRequest.status === 'approved'
                    ? <CheckCircle2 aria-hidden="true" />
                    : myRequest.status === 'rejected'
                      ? <X aria-hidden="true" />
                      : <Clock3 aria-hidden="true" />}
                  <div>
                    <strong>
                      {myRequest.grant_status === 'revoked'
                        ? t('assetWorkbench.catalog.distribution.revoked')
                        : myRequest.grant_status === 'expired'
                          ? t('assetWorkbench.catalog.distribution.expired')
                          : t(`assetWorkbench.catalog.distribution.requestStatus.${myRequest.status}`)}
                    </strong>
                    <span>{myRequest.reason || t('assetWorkbench.catalog.distribution.noPurpose')}</span>
                    <span>
                      {t('assetWorkbench.catalog.distribution.requestSummary', {
                        duration: formatNumber(myRequest.requested_duration_days || 30),
                        quota: formatNumber(myRequest.requested_package_quota || 5),
                      })}
                    </span>
                    {myRequest.product_version && (
                      <span>{t('assetWorkbench.catalog.distribution.productVersion', {
                        version: myRequest.product_version.version_key,
                      })}</span>
                    )}
                    {myRequest.reject_reason && <em>{myRequest.reject_reason}</em>}
                    {myRequest.revocation_reason && <em>{myRequest.revocation_reason}</em>}
                  </div>
                </div>
              )}
              {isOwner && !myRequest && (
                <div className="asset-distribution-empty">{t('assetWorkbench.catalog.distribution.youAreOwner')}</div>
              )}
              {requestAccess.can_request && !requestFormOpen && (
                <button
                  type="button"
                  className="asset-request-open"
                  onClick={() => {
                    setRequestFormOpen(true);
                    setDistributionError('');
                  }}
                >
                  <Send aria-hidden="true" />
                  <span>
                    {activeGrant?.quota_exhausted
                      ? t('assetWorkbench.catalog.distribution.requestMoreQuota')
                      : myRequest
                        ? t('assetWorkbench.catalog.distribution.reapply')
                        : t('assetWorkbench.catalog.distribution.requestUse')}
                  </span>
                </button>
              )}
              {requestAccess.can_request && requestFormOpen && (
                <div className="asset-request-form">
                  <div className="asset-request-contract">
                    <span>{t('assetWorkbench.catalog.distribution.authorizationMethod')}</span>
                    <strong>{t('assetWorkbench.catalog.distribution.offlinePackage')}</strong>
                    <div className="asset-request-contract-controls">
                      <label>
                        <span>{t('assetWorkbench.catalog.distribution.validDays')}</span>
                        <input
                          type="number"
                          min={1}
                          max={365}
                          value={requestDurationDays}
                          onChange={event => setRequestDurationDays(Number(event.target.value))}
                          aria-label={t('assetWorkbench.catalog.distribution.validDaysAria')}
                        />
                      </label>
                      <label>
                        <span>{t('assetWorkbench.catalog.distribution.packageCount')}</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={requestPackageQuota}
                          onChange={event => setRequestPackageQuota(Number(event.target.value))}
                          aria-label={t('assetWorkbench.catalog.distribution.packageQuotaAria')}
                        />
                      </label>
                    </div>
                  </div>
                  <textarea
                    value={requestReason}
                    onChange={event => setRequestReason(event.target.value)}
                    placeholder={t('assetWorkbench.catalog.distribution.purposePlaceholder')}
                    aria-label={t('assetWorkbench.catalog.distribution.purpose')}
                    rows={3}
                  />
                  <div className="asset-request-actions">
                    <button
                      type="button"
                      onClick={() => void handleRequestAccess()}
                      disabled={distributionBusy === 'create'}
                    >
                      <Send aria-hidden="true" />
                      <span>{distributionBusy === 'create'
                        ? t('assetWorkbench.catalog.distribution.submitting')
                        : t('assetWorkbench.catalog.distribution.submit')}</span>
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setRequestFormOpen(false)}
                      disabled={Boolean(distributionBusy)}
                    >
                      {t('assetWorkbench.common.cancel')}
                    </button>
                  </div>
                </div>
              )}
              {requestAccess.can_package && (
                <div className="asset-package-control">
                  <button
                    type="button"
                    onClick={() => void handleCreatePackage()}
                    disabled={distributionBusy === 'package'}
                  >
                    <Package aria-hidden="true" />
                    <span>{distributionBusy === 'package'
                      ? t('assetWorkbench.catalog.distribution.generating')
                      : t('assetWorkbench.catalog.distribution.generatePackage')}</span>
                  </button>
                  {packageResult?.url && (
                    <a href={packageResult.url} download={packageResult.name}>
                      <Download aria-hidden="true" />
                      <span>{t('assetWorkbench.catalog.distribution.downloadPackage', { name: packageResult.name })}</span>
                    </a>
                  )}
                </div>
              )}
            </>
          )}

          {distributionError && (
            <div className="asset-distribution-error" role="alert">
              <AlertTriangle aria-hidden="true" />
              <span>{distributionError}</span>
            </div>
          )}
        </section>
      )}

      {reviews && (
        <div className="asset-rating-section">
          <div className="asset-rating-row">
            {[1, 2, 3, 4, 5].map(score => {
              const active = score <= Math.round(reviews.avg_rating);
              return (
                <button
                  key={score}
                  className={`asset-rating-button ${active ? 'active' : ''}`}
                  onClick={() => handleRate(score)}
                  title={t('assetWorkbench.catalog.ratingAria', { score: formatNumber(score) })}
                  aria-label={t('assetWorkbench.catalog.ratingAria', { score: formatNumber(score) })}
                >
                  <Star aria-hidden="true" fill={active ? 'currentColor' : 'none'} />
                </button>
              );
            })}
            <span>{t('assetWorkbench.catalog.ratingSummary', {
              rating: formatNumber(reviews.avg_rating, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
              count: formatNumber(reviews.count),
            })}</span>
          </div>
        </div>
      )}

      <div className="asset-detail-grid">
        <div className="asset-detail-item"><span>{t('assetWorkbench.catalog.fields.type')}</span><span className={`type-badge ${detail.asset_type}`}>{t(`assetWorkbench.catalog.assetTypes.${detail.asset_type}`, { defaultValue: detail.asset_type })}</span></div>
        <div className="asset-detail-item"><span>{t('assetWorkbench.catalog.fields.owner')}</span><span>{detail.owner || t('assetWorkbench.common.notSet')}</span></div>
        <div className="asset-detail-item"><span>{t('assetWorkbench.catalog.fields.format')}</span><span>{detail.file_format || '-'}</span></div>
        <div className="asset-detail-item"><span>{t('assetWorkbench.catalog.fields.storage')}</span><span>{detail.storage_backend || '-'}</span></div>
        <div className="asset-detail-item"><span>CRS</span><span>{detail.crs || '-'}</span></div>
        <div className="asset-detail-item"><span>{t('assetWorkbench.catalog.fields.featureCount')}</span><span>{formatNumber(detail.feature_count || 0)}</span></div>
        <div className="asset-detail-item"><span>{t('assetWorkbench.catalog.fields.size')}</span><span>{formatFileSize(detail.file_size_bytes || 0)}</span></div>
        <div className="asset-detail-item">
          <span>{t('assetWorkbench.catalog.fields.sensitivity')}</span>
          <span className={`sensitivity-badge ${sensitivity ? '' : 'unset'}`} style={sensitivity ? {
            background: `${SENS_COLOR[sensitivity] || '#6b7280'}20`,
            color: SENS_COLOR[sensitivity] || '#6b7280',
          } : undefined}>
            {sensitivity
              ? t(`assetWorkbench.catalog.sensitivity.${sensitivity}`, { defaultValue: sensitivity })
              : t('assetWorkbench.common.notSet')}
          </span>
        </div>
        <div className="asset-detail-item"><span>{t('assetWorkbench.catalog.fields.accessLevel')}</span><span>{t(`assetWorkbench.catalog.accessLevels.${detail.access_level || 'private'}`, { defaultValue: detail.access_level || 'private' })}</span></div>
        <div className="asset-detail-item"><span>{t('assetWorkbench.catalog.fields.license')}</span><span>{detail.license || t('assetWorkbench.common.notSet')}</span></div>
        {detail.description && <div className="asset-detail-item full"><span>{t('assetWorkbench.catalog.fields.description')}</span><span>{detail.description}</span></div>}
        {detail.tags.length > 0 && <div className="asset-detail-item full"><span>{t('assetWorkbench.catalog.fields.tags')}</span><span>{detail.tags.join(t('assetWorkbench.catalog.tagSeparator'))}</span></div>}
      </div>

      {detail.spatial_extent && (
        <div className="bbox-preview-section">
          <h4>{t('assetWorkbench.catalog.spatialExtent')}</h4>
          <div className="bbox-preview" ref={bboxRef} />
          <div className="bbox-coords">
            [{detail.spatial_extent.minx?.toFixed(4)}, {detail.spatial_extent.miny?.toFixed(4)}, {' '}
            {detail.spatial_extent.maxx?.toFixed(4)}, {detail.spatial_extent.maxy?.toFixed(4)}]
          </div>
        </div>
      )}

      {detail.column_schema.length > 0 && (
        <div className="column-schema-section">
          <h4>{t('assetWorkbench.catalog.columnSchema')}</h4>
          <div className="column-schema-table">
            <div className="column-schema-header"><span>{t('assetWorkbench.catalog.fieldName')}</span><span>{t('assetWorkbench.catalog.fields.type')}</span></div>
            {detail.column_schema.map((column, index) => (
              <div key={`${column.name}-${index}`} className="column-schema-row">
                <span>{column.name}</span><span>{column.type}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {lineage && (
        <div className="lineage-section">
          <div className="asset-section-heading compact">
            <div><GitBranch aria-hidden="true" /><h4>{t('assetWorkbench.catalog.lineage')}</h4></div>
            <span>{t('assetWorkbench.catalog.lineageSummary', {
              sources: formatNumber(lineage.source_count),
              derived: formatNumber(lineage.derived_count),
            })}</span>
          </div>
          {(lineage.ancestors.length > 0 || lineage.descendants.length > 0) ? (
            <div className="lineage-dag">
              {lineage.ancestors.length > 0 && (
                <div className="lineage-col">
                  {lineage.ancestors.map((node, index) => (
                    <div key={node.id || `${node.name}-${index}`} className="lineage-node ancestor">
                      <div className="lineage-node-name">{node.name || `#${node.id}`}</div>
                      {node.type && <span className={`type-badge ${node.type}`}>{node.type}</span>}
                      {node.creation_tool && <div className="lineage-node-tool">{node.creation_tool}</div>}
                    </div>
                  ))}
                </div>
              )}
              {lineage.ancestors.length > 0 && <ArrowRight className="lineage-arrow-icon rtl-flip" aria-hidden="true" />}
              <div className="lineage-col">
                <div className="lineage-node current">
                  <div className="lineage-node-name">{lineage.asset?.name || detail.asset_name}</div>
                  {(lineage.asset?.type || detail.asset_type) && (
                    <span className={`type-badge ${lineage.asset?.type || detail.asset_type}`}>
                      {lineage.asset?.type || detail.asset_type}
                    </span>
                  )}
                </div>
              </div>
              {lineage.descendants.length > 0 && <ArrowRight className="lineage-arrow-icon rtl-flip" aria-hidden="true" />}
              {lineage.descendants.length > 0 && (
                <div className="lineage-col">
                  {lineage.descendants.map((node, index) => (
                    <div key={node.id || `${node.name}-${index}`} className="lineage-node descendant">
                      <div className="lineage-node-name">{node.name || `#${node.id}`}</div>
                      {node.type && <span className={`type-badge ${node.type}`}>{node.type}</span>}
                      {node.creation_tool && <div className="lineage-node-tool">{node.creation_tool}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="asset-lineage-empty">{t('assetWorkbench.catalog.noLineage')}</div>
          )}
        </div>
      )}
    </div>
  );
}
