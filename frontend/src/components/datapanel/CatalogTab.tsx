import { useCallback, useEffect, useRef, useState } from 'react';
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
import { formatSize, getAssetCategory, getAssetIcon } from './utils';

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

const SENS_LABEL: Record<string, string> = {
  public: '公开', internal: '内部', confidential: '机密',
  restricted: '限制', secret: '绝密',
};
const SENS_COLOR: Record<string, string> = {
  public: '#15803d', internal: '#2563eb', confidential: '#b45309',
  restricted: '#dc2626', secret: '#7f1d1d',
};
const PAGE_SIZE = 50;
const REQUEST_STATUS_LABEL: Record<DistributionRequestItem['status'], string> = {
  pending: '待审批',
  approved: '已批准',
  rejected: '已驳回',
};

function formatGrantExpiry(value?: string): string {
  if (!value) return '未设置';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
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
        response = await fetch(`/api/catalog/search?${params}`, { credentials: 'include' });
      } else {
        const params = new URLSearchParams();
        if (keyword) params.set('keyword', keyword);
        if (assetType) params.set('asset_type', assetType);
        params.set('offset', String(page * PAGE_SIZE));
        params.set('limit', String(PAGE_SIZE));
        response = await fetch(`/api/catalog?${params}`, { credentials: 'include' });
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
  }, [keyword, assetType, page, searchMode]);

  useEffect(() => {
    const timer = setTimeout(fetchAssets, 300);
    return () => clearTimeout(timer);
  }, [keyword, assetType, page, searchMode]);

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
          placeholder={searchMode === 'keyword' ? '搜索资产...' : '语义搜索（如：热岛效应分析）...'}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          className="catalog-search"
        />
        <select
          value={assetType}
          onChange={(event) => setAssetType(event.target.value)}
          className="catalog-type-select"
        >
          <option value="">全部类型</option>
          <option value="vector">矢量</option>
          <option value="raster">栅格</option>
          <option value="tabular">表格</option>
          <option value="map">地图</option>
          <option value="report">报告</option>
        </select>
        <button
          className={`catalog-search-mode ${searchMode === 'semantic' ? 'active' : ''}`}
          onClick={() => setSearchMode(mode => mode === 'keyword' ? 'semantic' : 'keyword')}
          title={searchMode === 'keyword' ? '切换到语义搜索' : '切换到关键词搜索'}
        >
          {searchMode === 'keyword' ? '关键词' : '语义'}
        </button>
      </div>
      {loading && assets.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : assets.length === 0 ? (
        <div className="empty-state">暂无数据资产</div>
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
                    <span className={`type-badge ${asset.asset_type}`}>{asset.asset_type}</span>
                    {asset.sensitivity_level && asset.sensitivity_level !== 'public' && (
                      <span className="sensitivity-badge" style={{
                        background: `${SENS_COLOR[asset.sensitivity_level] || '#6b7280'}20`,
                        color: SENS_COLOR[asset.sensitivity_level] || '#6b7280',
                      }}>
                        {SENS_LABEL[asset.sensitivity_level] || asset.sensitivity_level}
                      </span>
                    )}
                    {asset.feature_count > 0 && <span>{asset.feature_count} 要素</span>}
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
                &laquo; 上一页
              </button>
              <span className="catalog-page-info">
                第 {page + 1} 页 / 共 {totalPages} 页（{total} 条）
              </span>
              <button disabled={page + 1 >= totalPages} onClick={() => setPage(value => value + 1)}>
                下一页 &raquo;
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
      });
      if (!response.ok) throw new Error(response.status === 404 ? '资产不存在或无权访问' : '生命周期信息暂不可用');
      setLifecycle(await response.json());
    } catch (error) {
      setLifecycleError(error instanceof Error ? error.message : '生命周期信息暂不可用');
    } finally {
      setLifecycleLoading(false);
    }
  }, [asset.id]);

  useEffect(() => { void loadLifecycle(); }, [loadLifecycle]);

  const loadMapPublication = useCallback(async () => {
    setMapPublicationLoading(true);
    setMapPublicationError('');
    try {
      const response = await fetch(`/api/catalog/${asset.id}/map-publications/current`, {
        credentials: 'include',
      });
      if (response.status === 404) {
        setMapPublication(null);
        return;
      }
      if (!response.ok) throw new Error('地图服务状态暂不可用');
      const body = await response.json();
      setMapPublication(body.publication as MapPublication);
    } catch (error) {
      setMapPublicationError(error instanceof Error ? error.message : '地图服务状态暂不可用');
    } finally {
      setMapPublicationLoading(false);
    }
  }, [asset.id]);

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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: score, comment: '' }),
      });
      if (response.ok) await loadLifecycle();
    } catch { /* keep the existing rating */ }
  };

  const responseError = async (response: Response, fallback: string) => {
    try {
      const body = await response.json();
      return typeof body.error === 'string' ? body.error : fallback;
    } catch {
      return fallback;
    }
  };

  const handleRequestAccess = async () => {
    const reason = requestReason.trim();
    if (!reason) {
      setDistributionError('请填写申请用途');
      return;
    }
    setDistributionBusy('create');
    setDistributionError('');
    try {
      const response = await fetch('/api/data-requests', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          asset_id: asset.id,
          reason,
          duration_days: requestDurationDays,
          package_quota: requestPackageQuota,
        }),
      });
      if (!response.ok) throw new Error(await responseError(response, '提交申请失败'));
      setRequestReason('');
      setRequestFormOpen(false);
      await loadLifecycle();
    } catch (error) {
      setDistributionError(error instanceof Error ? error.message : '提交申请失败');
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset_ids: [asset.id] }),
      });
      if (!response.ok) throw new Error(await responseError(response, '生成分发包失败'));
      const body = await response.json();
      setPackageResult({
        name: String(body.zip_name || 'data-package.zip'),
        url: String(body.download_url || ''),
      });
      await loadLifecycle();
    } catch (error) {
      setDistributionError(error instanceof Error ? error.message : '生成分发包失败');
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
      setDistributionError('请填写驳回原因');
      return;
    }
    setDistributionBusy(`${action}-${requestId}`);
    setDistributionError('');
    try {
      const response = await fetch(`/api/data-requests/${requestId}/${action}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(action === 'reject' ? { reason } : {}),
      });
      if (!response.ok) throw new Error(await responseError(response, '处理申请失败'));
      setRejectingRequestId(null);
      setRejectReason('');
      await loadLifecycle();
    } catch (error) {
      setDistributionError(error instanceof Error ? error.message : '处理申请失败');
    } finally {
      setDistributionBusy('');
    }
  };

  const handleRevokeRequest = async (requestId: number) => {
    const reason = revocationReason.trim();
    if (!reason) {
      setDistributionError('请填写撤销原因');
      return;
    }
    setDistributionBusy(`revoke-${requestId}`);
    setDistributionError('');
    try {
      const response = await fetch(`/api/data-requests/${requestId}/revoke`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      if (!response.ok) throw new Error(await responseError(response, '撤销授权失败'));
      setRevokingRequestId(null);
      setRevocationReason('');
      await loadLifecycle();
    } catch (error) {
      setDistributionError(error instanceof Error ? error.message : '撤销授权失败');
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

  const openMcpChat = (server: 'arcpy' | 'dts') => {
    const text = server === 'arcpy'
      ? `请通过受控资产工作流处理数据湖资产 ID ${asset.id}：先检查 ArcPy MCP 兼容性，再使用 project_features 投影到 EPSG:32640。首次联调限制为 5000 个要素；成功后把结果作为新资产写回数据湖，登记版本和血缘，并返回新资产 ID 与 SHA-256。`
      : `请检查资产 ID ${asset.id} 是否能进入 DTS MCP 的 road 管道，并列出还需要选择的 DOM/DEM 数据湖资产；不要把建筑物图层强行当作道路输入。`;
    window.dispatchEvent(new CustomEvent('gda-chat-prefill', { detail: { text } }));
  };

  const handlePublishMap = async () => {
    setMapPublicationBusy(true);
    setMapPublicationError('');
    try {
      const response = await fetch(`/api/catalog/${asset.id}/map-publications`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(await responseError(response, '发布地图服务失败'));
      }
      const body = await response.json();
      const publication = body.publication as MapPublication;
      const layer = (body.layer || publication.layer) as MapPublicationLayer;
      setMapPublication(publication);
      onAddMapLayer?.(layer);
    } catch (error) {
      setMapPublicationError(error instanceof Error ? error.message : '发布地图服务失败');
    } finally {
      setMapPublicationBusy(false);
    }
  };

  return (
    <div className="asset-detail">
      <button className="asset-back-btn" onClick={onBack} title="返回资产列表">
        <ArrowLeft aria-hidden="true" />
        <span>返回列表</span>
      </button>
      <div className="asset-detail-heading">
        <div>
          <h3 className="asset-detail-title">{detail.display_name || detail.asset_name}</h3>
          {detail.asset_code && <code>{detail.asset_code}</code>}
        </div>
        <div className="asset-heading-actions">
          <button type="button" onClick={() => openMcpChat('arcpy')} title="在对话中使用 ArcPy MCP 处理此资产">
            <Workflow aria-hidden="true" />
            <span>ArcPy 处理</span>
          </button>
          <button type="button" onClick={() => openMcpChat('dts')} title="在对话中检查 DTS road 输入条件">
            <ScanSearch aria-hidden="true" />
            <span>DTS 检查</span>
          </button>
          {lifecycle && (
            <span className={`asset-stage-badge ${lifecycle.current_stage}`}>
              {lifecycle.current_stage_label}
            </span>
          )}
        </div>
      </div>

      {lifecycleLoading && <div className="asset-lifecycle-loading">正在汇总资产证据...</div>}
      {lifecycleError && (
        <div className="asset-lifecycle-error" role="alert">
          <AlertTriangle aria-hidden="true" />
          <span>{lifecycleError}</span>
        </div>
      )}

      {lifecycle && (
        <section className="asset-lifecycle-section" aria-label="资产生命周期">
          <div className="asset-section-heading">
            <div>
              <ShieldCheck aria-hidden="true" />
              <h4>生命周期与发布准备度</h4>
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
                <span>{stage.label}</span>
              </div>
            ))}
          </div>

          <div className="asset-operation-metrics">
            <div>
              <ShieldCheck aria-hidden="true" />
              <span>质量</span>
              <strong>{lifecycle.quality.has_evidence ? lifecycle.quality.score : '-'}</strong>
            </div>
            <div>
              <Activity aria-hidden="true" />
              <span>访问</span>
              <strong>{lifecycle.usage.total_accesses}</strong>
            </div>
            <div>
              <Users aria-hidden="true" />
              <span>用户</span>
              <strong>{lifecycle.usage.unique_users}</strong>
            </div>
            <div>
              <Clock3 aria-hidden="true" />
              <span>版本</span>
              <strong>v{lifecycle.versions.current || detail.version || 1}</strong>
            </div>
          </div>

          <div className={`asset-readiness-result ${lifecycle.readiness.ready ? 'ready' : 'blocked'}`}>
            <div className="asset-readiness-status">
              {lifecycle.readiness.ready
                ? <CheckCircle2 aria-hidden="true" />
                : <AlertTriangle aria-hidden="true" />}
              <div>
                <strong>{lifecycle.readiness.ready ? '发布门禁通过' : `${lifecycle.readiness.blockers.length} 项阻塞发布`}</strong>
                <span>{pendingRequests > 0 ? `${pendingRequests} 个申请待审批` : '当前无待审批申请'}</span>
              </div>
            </div>
            {lifecycle.readiness.blockers.length > 0 && (
              <ul className="asset-readiness-list blockers">
                {lifecycle.readiness.blockers.map(blocker => <li key={blocker}>{blocker}</li>)}
              </ul>
            )}
            {lifecycle.readiness.warnings.length > 0 && (
              <ul className="asset-readiness-list warnings">
                {lifecycle.readiness.warnings.map(warning => <li key={warning}>{warning}</li>)}
              </ul>
            )}
          </div>

          {lifecycle.publication.evidence_detected && !lifecycle.readiness.ready && (
            <div className="asset-publication-drift">
              <AlertTriangle aria-hidden="true" />
              <span>已检测到共享或发布事实，但治理门禁仍有缺口。</span>
            </div>
          )}
        </section>
      )}

      <section className="asset-map-publication-section" aria-label="地图服务">
        <div className="asset-section-heading compact">
          <div>
            <Layers aria-hidden="true" />
            <h4>地图服务</h4>
          </div>
          {mapPublication?.status === 'ready' && (
            <span className="asset-map-publication-ready">可用</span>
          )}
        </div>

        {mapPublicationLoading ? (
          <div className="asset-map-publication-empty">正在读取发布状态...</div>
        ) : mapPublication?.status === 'ready' ? (
          <>
            <div className="asset-map-publication-summary">
              <span>MVT</span>
              <span>缩放 {mapPublication.min_zoom}-{mapPublication.max_zoom}</span>
              <span>{mapPublication.property_allowlist.length} 个公开属性</span>
            </div>
            <div className="asset-map-publication-actions">
              <button
                type="button"
                onClick={() => onAddMapLayer?.(mapPublication.layer)}
                disabled={!onAddMapLayer || mapPublicationBusy}
              >
                <Layers aria-hidden="true" />
                <span>添加到地图</span>
              </button>
              {canPublishMap && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => void handlePublishMap()}
                  disabled={mapPublicationBusy}
                  title="按当前资产版本重新发布"
                >
                  <RefreshCw aria-hidden="true" />
                  <span>{mapPublicationBusy ? '发布中...' : '重新发布'}</span>
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="asset-map-publication-empty">该资产尚未发布为地图图层</div>
            {canPublishMap && (
              <button
                type="button"
                className="asset-map-publication-create"
                onClick={() => void handlePublishMap()}
                disabled={mapPublicationBusy}
              >
                <Layers aria-hidden="true" />
                <span>{mapPublicationBusy ? '发布中...' : '发布为地图图层'}</span>
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
        <section className="asset-distribution-section" aria-label="分发申请">
          <div className="asset-section-heading compact">
            <div>
              <ClipboardCheck aria-hidden="true" />
              <h4>分发申请</h4>
            </div>
            {isAdmin && <span>{adminPendingItems.length} 项待处理</span>}
          </div>

          {isAdmin ? (
            <>
              {adminPendingItems.length > 0 ? (
                <div className="asset-distribution-queue">
                  {adminPendingItems.map(item => (
                    <div className="asset-distribution-request" key={item.id}>
                      <div className="asset-distribution-request-main">
                        <strong>{item.requester}</strong>
                        <span>{item.reason || '未填写用途'}</span>
                        <small>
                          离线分发包 · {item.requested_duration_days || 30} 天 ·
                          {' '}{item.requested_package_quota || 5} 次额度
                        </small>
                      </div>
                      <div className="asset-distribution-actions">
                        <button
                          type="button"
                          className="asset-distribution-action approve"
                          onClick={() => void handleReviewRequest(item.id, 'approve')}
                          disabled={Boolean(distributionBusy)}
                          title="批准申请"
                          aria-label={`批准 ${item.requester} 的申请`}
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
                          title="驳回申请"
                          aria-label={`驳回 ${item.requester} 的申请`}
                        >
                          <X aria-hidden="true" />
                        </button>
                      </div>
                      {rejectingRequestId === item.id && (
                        <div className="asset-distribution-reject-form">
                          <textarea
                            value={rejectReason}
                            onChange={event => setRejectReason(event.target.value)}
                            placeholder="驳回原因"
                            aria-label="驳回原因"
                            rows={2}
                          />
                          <div>
                            <button
                              type="button"
                              onClick={() => void handleReviewRequest(item.id, 'reject')}
                              disabled={distributionBusy === `reject-${item.id}`}
                            >
                              确认驳回
                            </button>
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => setRejectingRequestId(null)}
                              disabled={Boolean(distributionBusy)}
                            >
                              取消
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="asset-distribution-empty">当前没有待审批申请</div>
              )}

              {adminActiveItems.length > 0 && (
                <div className="asset-active-grants">
                  <div className="asset-active-grants-heading">
                    <ShieldCheck aria-hidden="true" />
                    <strong>有效授权 {adminActiveItems.length}</strong>
                  </div>
                  {adminActiveItems.map(item => (
                    <div className="asset-distribution-request active" key={item.id}>
                      <div className="asset-distribution-request-main">
                        <strong>{item.requester}</strong>
                        <span>有效至 {formatGrantExpiry(item.expires_at)}</span>
                        <small>
                          {item.product_version
                            ? `已锁定产品版本 ${item.product_version.version_key}`
                            : '资产级过渡授权'}
                        </small>
                        <small>
                          分发包额度 已用 {item.packages_created || 0} / {item.granted_package_quota || 0}
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
                        title="撤销授权"
                        aria-label={`撤销 ${item.requester} 的授权`}
                      >
                        <ShieldOff aria-hidden="true" />
                      </button>
                      {revokingRequestId === item.id && (
                        <div className="asset-distribution-reject-form revoke">
                          <textarea
                            value={revocationReason}
                            onChange={event => setRevocationReason(event.target.value)}
                            placeholder="撤销原因"
                            aria-label="撤销原因"
                            rows={2}
                          />
                          <div>
                            <button
                              type="button"
                              onClick={() => void handleRevokeRequest(item.id)}
                              disabled={distributionBusy === `revoke-${item.id}`}
                            >
                              确认撤销
                            </button>
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => setRevokingRequestId(null)}
                              disabled={Boolean(distributionBusy)}
                            >
                              取消
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
                    <strong>{activeGrant.quota_exhausted ? '分发额度已用完' : '分发授权有效'}</strong>
                    <span>离线分发包 · 有效至 {formatGrantExpiry(activeGrant.expires_at)}</span>
                    <span>
                      额度 已用 {activeGrant.packages_created || 0} / {activeGrant.granted_package_quota || 0}
                      {' '}· 剩余 {activeGrant.packages_remaining || 0}
                    </span>
                    <small>
                      {activeGrant.product_version
                        ? `已锁定产品版本 ${activeGrant.product_version.version_key}`
                        : '资产级过渡授权'}
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
                        ? '授权已撤销'
                        : myRequest.grant_status === 'expired'
                          ? '授权已过期'
                          : REQUEST_STATUS_LABEL[myRequest.status]}
                    </strong>
                    <span>{myRequest.reason || '未填写用途'}</span>
                    <span>
                      离线分发包 · {myRequest.requested_duration_days || 30} 天 ·
                      {' '}{myRequest.requested_package_quota || 5} 次额度
                    </span>
                    {myRequest.product_version && (
                      <span>产品版本 {myRequest.product_version.version_key}</span>
                    )}
                    {myRequest.reject_reason && <em>{myRequest.reject_reason}</em>}
                    {myRequest.revocation_reason && <em>{myRequest.revocation_reason}</em>}
                  </div>
                </div>
              )}
              {isOwner && !myRequest && (
                <div className="asset-distribution-empty">你是该资产的责任人</div>
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
                      ? '申请追加额度'
                      : myRequest ? '重新申请' : '申请使用'}
                  </span>
                </button>
              )}
              {requestAccess.can_request && requestFormOpen && (
                <div className="asset-request-form">
                  <div className="asset-request-contract">
                    <span>授权方式</span>
                    <strong>离线分发包</strong>
                    <div className="asset-request-contract-controls">
                      <label>
                        <span>有效天数</span>
                        <input
                          type="number"
                          min={1}
                          max={365}
                          value={requestDurationDays}
                          onChange={event => setRequestDurationDays(Number(event.target.value))}
                          aria-label="授权有效天数"
                        />
                      </label>
                      <label>
                        <span>打包次数</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={requestPackageQuota}
                          onChange={event => setRequestPackageQuota(Number(event.target.value))}
                          aria-label="分发包申请额度"
                        />
                      </label>
                    </div>
                  </div>
                  <textarea
                    value={requestReason}
                    onChange={event => setRequestReason(event.target.value)}
                    placeholder="填写申请用途"
                    aria-label="申请用途"
                    rows={3}
                  />
                  <div className="asset-request-actions">
                    <button
                      type="button"
                      onClick={() => void handleRequestAccess()}
                      disabled={distributionBusy === 'create'}
                    >
                      <Send aria-hidden="true" />
                      <span>{distributionBusy === 'create' ? '提交中...' : '提交申请'}</span>
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setRequestFormOpen(false)}
                      disabled={Boolean(distributionBusy)}
                    >
                      取消
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
                    <span>{distributionBusy === 'package' ? '生成中...' : '生成分发包'}</span>
                  </button>
                  {packageResult?.url && (
                    <a href={packageResult.url} download={packageResult.name}>
                      <Download aria-hidden="true" />
                      <span>下载 {packageResult.name}</span>
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
                  title={`评分 ${score} 分`}
                  aria-label={`评分 ${score} 分`}
                >
                  <Star aria-hidden="true" fill={active ? 'currentColor' : 'none'} />
                </button>
              );
            })}
            <span>{reviews.avg_rating.toFixed(1)}（{reviews.count} 条评价）</span>
          </div>
        </div>
      )}

      <div className="asset-detail-grid">
        <div className="asset-detail-item"><span>类型</span><span className={`type-badge ${detail.asset_type}`}>{detail.asset_type}</span></div>
        <div className="asset-detail-item"><span>责任人</span><span>{detail.owner || '未设置'}</span></div>
        <div className="asset-detail-item"><span>格式</span><span>{detail.file_format || '-'}</span></div>
        <div className="asset-detail-item"><span>存储</span><span>{detail.storage_backend || '-'}</span></div>
        <div className="asset-detail-item"><span>CRS</span><span>{detail.crs || '-'}</span></div>
        <div className="asset-detail-item"><span>要素数</span><span>{detail.feature_count || 0}</span></div>
        <div className="asset-detail-item"><span>大小</span><span>{formatSize(detail.file_size_bytes || 0)}</span></div>
        <div className="asset-detail-item">
          <span>敏感级别</span>
          <span className={`sensitivity-badge ${sensitivity ? '' : 'unset'}`} style={sensitivity ? {
            background: `${SENS_COLOR[sensitivity] || '#6b7280'}20`,
            color: SENS_COLOR[sensitivity] || '#6b7280',
          } : undefined}>
            {sensitivity ? (SENS_LABEL[sensitivity] || sensitivity) : '未设置'}
          </span>
        </div>
        <div className="asset-detail-item"><span>访问级别</span><span>{detail.access_level || 'private'}</span></div>
        <div className="asset-detail-item"><span>许可</span><span>{detail.license || '未设置'}</span></div>
        {detail.description && <div className="asset-detail-item full"><span>描述</span><span>{detail.description}</span></div>}
        {detail.tags.length > 0 && <div className="asset-detail-item full"><span>标签</span><span>{detail.tags.join('、')}</span></div>}
      </div>

      {detail.spatial_extent && (
        <div className="bbox-preview-section">
          <h4>空间范围</h4>
          <div className="bbox-preview" ref={bboxRef} />
          <div className="bbox-coords">
            [{detail.spatial_extent.minx?.toFixed(4)}, {detail.spatial_extent.miny?.toFixed(4)}, {' '}
            {detail.spatial_extent.maxx?.toFixed(4)}, {detail.spatial_extent.maxy?.toFixed(4)}]
          </div>
        </div>
      )}

      {detail.column_schema.length > 0 && (
        <div className="column-schema-section">
          <h4>字段结构</h4>
          <div className="column-schema-table">
            <div className="column-schema-header"><span>字段名</span><span>类型</span></div>
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
            <div><GitBranch aria-hidden="true" /><h4>数据血缘</h4></div>
            <span>{lineage.source_count} 上游 / {lineage.derived_count} 下游</span>
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
              {lineage.ancestors.length > 0 && <ArrowRight className="lineage-arrow-icon" aria-hidden="true" />}
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
              {lineage.descendants.length > 0 && <ArrowRight className="lineage-arrow-icon" aria-hidden="true" />}
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
            <div className="asset-lineage-empty">尚无血缘证据</div>
          )}
        </div>
      )}
    </div>
  );
}
