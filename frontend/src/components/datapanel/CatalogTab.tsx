import { useState, useEffect, useRef } from 'react';
import L from 'leaflet';
import { getAssetCategory, getAssetIcon, formatSize } from './utils';

interface CatalogAsset {
  id: number;
  asset_name: string;
  asset_type: string;
  file_format: string;
  storage_backend: string;
  crs: string;
  feature_count: number;
  file_size_bytes: number;
  tags: string;
  description: string;
  owner_user: string;
  is_shared: boolean;
  created_at: string;
  sensitivity_level?: string;
  version?: number;
  asset_code?: string;
  relevance?: number;
}

const SENS_LABEL: Record<string, string> = {
  public: '公开', internal: '内部', confidential: '机密',
  restricted: '限制', secret: '绝密',
};
const SENS_COLOR: Record<string, string> = {
  public: '#22c55e', internal: '#3b82f6', confidential: '#f59e0b',
  restricted: '#ef4444', secret: '#991b1b',
};
const PAGE_SIZE = 50;

export default function CatalogTab() {
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
      let resp: Response;
      if (searchMode === 'semantic' && keyword.trim()) {
        const params = new URLSearchParams();
        params.set('q', keyword);
        resp = await fetch(`/api/catalog/search?${params}`, { credentials: 'include' });
      } else {
        const params = new URLSearchParams();
        if (keyword) params.set('keyword', keyword);
        if (assetType) params.set('asset_type', assetType);
        params.set('offset', String(page * PAGE_SIZE));
        params.set('limit', String(PAGE_SIZE));
        resp = await fetch(`/api/catalog?${params}`, { credentials: 'include' });
      }
      if (resp.ok) {
        const data = await resp.json();
        setAssets(data.assets || []);
        setTotal(data.total ?? data.count ?? 0);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchAssets();
    const interval = setInterval(fetchAssets, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const timer = setTimeout(fetchAssets, 300);
    return () => clearTimeout(timer);
  }, [keyword, assetType, page, searchMode]);

  useEffect(() => { setPage(0); }, [keyword, assetType, searchMode]);

  if (selectedAsset) {
    return <AssetDetail asset={selectedAsset} onBack={() => setSelectedAsset(null)} />;
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="catalog-view">
      <div className="catalog-filter-bar">
        <input
          type="text"
          placeholder={searchMode === 'keyword' ? '搜索资产...' : '语义搜索（如：热岛效应分析）...'}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="catalog-search"
        />
        <select
          value={assetType}
          onChange={(e) => setAssetType(e.target.value)}
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
          onClick={() => setSearchMode(s => s === 'keyword' ? 'semantic' : 'keyword')}
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
            {assets.map((asset) => (
              <li key={asset.id} className="file-item" onClick={() => setSelectedAsset(asset)}>
                <div className={`file-icon-circle ${getAssetCategory(asset.asset_type)}`}>
                  {getAssetIcon(asset.asset_type)}
                </div>
                <div className="file-info">
                  <div className="file-name" title={asset.asset_name}>{asset.asset_name}</div>
                  {asset.asset_code && <div style={{fontSize: 11, color: '#6b7280', fontFamily: 'monospace'}}>{asset.asset_code}</div>}
                  <div className="file-meta">
                    <span className={`type-badge ${asset.asset_type}`}>{asset.asset_type}</span>
                    {asset.sensitivity_level && asset.sensitivity_level !== 'public' && (
                      <span className="sensitivity-badge" style={{
                        background: (SENS_COLOR[asset.sensitivity_level] || '#888') + '20',
                        color: SENS_COLOR[asset.sensitivity_level] || '#888',
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
              <button disabled={page === 0} onClick={() => setPage(p => p - 1)}>
                &laquo; 上一页
              </button>
              <span className="catalog-page-info">
                第 {page + 1} 页 / 共 {totalPages} 页（{total} 条）
              </span>
              <button disabled={page + 1 >= totalPages} onClick={() => setPage(p => p + 1)}>
                下一页 &raquo;
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function AssetDetail({ asset, onBack }: { asset: CatalogAsset; onBack: () => void }) {
  const [lineage, setLineage] = useState<any>(null);
  const [reviews, setReviews] = useState<{ avg_rating: number; count: number } | null>(null);
  const [detail, setDetail] = useState<Record<string, any> | null>(null);
  const bboxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`/api/catalog/${asset.id}/lineage`, { credentials: 'include' })
      .then((r) => r.json())
      .then(setLineage)
      .catch(() => {});

    fetch(`/api/catalog/${asset.id}/reviews`, { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => setReviews({ avg_rating: data.avg_rating || 0, count: data.count || 0 }))
      .catch(() => {});

    fetch(`/api/catalog/${asset.id}`, { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => { if (data.status === 'success') setDetail(data.asset); })
      .catch(() => {});
  }, [asset.id]);

  // Bbox mini-map
  useEffect(() => {
    const ext = detail?.spatial_extent;
    if (!ext || !bboxRef.current) return;
    if (ext.minx == null || ext.miny == null || ext.maxx == null || ext.maxy == null) return;

    const bounds: L.LatLngBoundsLiteral = [
      [ext.miny, ext.minx],
      [ext.maxy, ext.maxx],
    ];

    const map = L.map(bboxRef.current, {
      zoomControl: false,
      attributionControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      touchZoom: false,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
    }).addTo(map);

    L.rectangle(bounds, {
      color: '#0d9488',
      weight: 2,
      fillColor: '#0d9488',
      fillOpacity: 0.15,
    }).addTo(map);

    map.fitBounds(bounds, { padding: [10, 10] });

    return () => { map.remove(); };
  }, [detail]);

  const handleRate = async (score: number) => {
    try {
      await fetch(`/api/catalog/${asset.id}/review`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: score, comment: '' }),
      });
      const r = await fetch(`/api/catalog/${asset.id}/reviews`, { credentials: 'include' });
      if (r.ok) {
        const data = await r.json();
        setReviews({ avg_rating: data.avg_rating || 0, count: data.count || 0 });
      }
    } catch { /* ignore */ }
  };

  const sensLevel = detail?.sensitivity_level || asset.sensitivity_level || 'public';
  const version = detail?.version ?? asset.version;

  return (
    <div className="asset-detail">
      <button className="asset-back-btn" onClick={onBack}>&larr; 返回列表</button>
      <h3 className="asset-detail-title">{asset.asset_name}</h3>

      {/* Rating section */}
      {reviews && (
        <div className="asset-rating-section">
          <div className="asset-rating-row">
            {[1, 2, 3, 4, 5].map(s => (
              <span key={s} className="rating-star"
                onClick={() => handleRate(s)}
                style={{ cursor: 'pointer', color: s <= Math.round(reviews.avg_rating) ? '#f59e0b' : '#d4d4d4', fontSize: 18 }}>
                ★
              </span>
            ))}
            <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>
              {reviews.avg_rating.toFixed(1)} ({reviews.count} 评价)
            </span>
          </div>
        </div>
      )}

      <div className="asset-detail-grid">
        {asset.asset_code && <div className="asset-detail-item"><span>资产编码</span><span style={{fontFamily: 'monospace', fontWeight: 600}}>{asset.asset_code}</span></div>}
        <div className="asset-detail-item"><span>类型</span><span className={`type-badge ${asset.asset_type}`}>{asset.asset_type}</span></div>
        <div className="asset-detail-item"><span>格式</span><span>{asset.file_format || '-'}</span></div>
        <div className="asset-detail-item"><span>存储</span><span>{asset.storage_backend || '-'}</span></div>
        <div className="asset-detail-item"><span>CRS</span><span>{asset.crs || '-'}</span></div>
        <div className="asset-detail-item"><span>要素数</span><span>{asset.feature_count || 0}</span></div>
        <div className="asset-detail-item"><span>大小</span><span>{formatSize(asset.file_size_bytes || 0)}</span></div>
        <div className="asset-detail-item">
          <span>敏感级别</span>
          <span className="sensitivity-badge" style={{
            background: (SENS_COLOR[sensLevel] || '#888') + '20',
            color: SENS_COLOR[sensLevel] || '#888',
          }}>
            {SENS_LABEL[sensLevel] || '公开'}
          </span>
        </div>
        {version && (
          <div className="asset-detail-item"><span>版本</span><span>v{version}</span></div>
        )}
        {asset.description && <div className="asset-detail-item full"><span>描述</span><span>{asset.description}</span></div>}
        {asset.tags && <div className="asset-detail-item full"><span>标签</span><span>{asset.tags}</span></div>}
      </div>

      {/* Spatial extent bbox preview */}
      {detail?.spatial_extent && (
        <div className="bbox-preview-section">
          <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>空间范围</h4>
          <div className="bbox-preview" ref={bboxRef} />
          <div className="bbox-coords">
            [{detail.spatial_extent.minx?.toFixed(4)}, {detail.spatial_extent.miny?.toFixed(4)},
             {detail.spatial_extent.maxx?.toFixed(4)}, {detail.spatial_extent.maxy?.toFixed(4)}]
          </div>
        </div>
      )}

      {/* Column schema */}
      {detail?.column_schema && Array.isArray(detail.column_schema) && detail.column_schema.length > 0 && (
        <div className="column-schema-section">
          <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>字段结构</h4>
          <div className="column-schema-table">
            <div className="column-schema-header">
              <span>字段名</span><span>类型</span>
            </div>
            {detail.column_schema.map((col: { name: string; type: string }, i: number) => (
              <div key={i} className="column-schema-row">
                <span>{col.name}</span><span>{col.type}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {lineage && (
        <div className="lineage-section">
          <h4>数据血缘</h4>
          {(lineage.ancestors?.length > 0 || lineage.descendants?.length > 0) ? (
            <div className="lineage-dag">
              {/* Ancestors column */}
              {lineage.ancestors?.length > 0 && (
                <div className="lineage-col">
                  {lineage.ancestors.map((a: any, i: number) => (
                    <div key={i} className="lineage-node ancestor">
                      <div className="lineage-node-name">{a.name || `#${a.id}`}</div>
                      {a.type && <span className={`type-badge ${a.type}`}>{a.type}</span>}
                      {a.creation_tool && <div className="lineage-node-tool">{a.creation_tool}</div>}
                    </div>
                  ))}
                </div>
              )}
              {/* Arrow */}
              {lineage.ancestors?.length > 0 && (
                <div className="lineage-arrow">
                  <svg width="32" height="24"><path d="M4 12 L24 12" stroke="var(--primary)" strokeWidth="2" fill="none"/><path d="M20 7 L28 12 L20 17" stroke="var(--primary)" strokeWidth="2" fill="none"/></svg>
                </div>
              )}
              {/* Current asset (center) */}
              <div className="lineage-col">
                <div className="lineage-node current">
                  <div className="lineage-node-name">{lineage.asset?.name || asset.asset_name}</div>
                  {lineage.asset?.type && <span className={`type-badge ${lineage.asset.type}`}>{lineage.asset.type}</span>}
                </div>
              </div>
              {/* Arrow */}
              {lineage.descendants?.length > 0 && (
                <div className="lineage-arrow">
                  <svg width="32" height="24"><path d="M4 12 L24 12" stroke="var(--primary)" strokeWidth="2" fill="none"/><path d="M20 7 L28 12 L20 17" stroke="var(--primary)" strokeWidth="2" fill="none"/></svg>
                </div>
              )}
              {/* Descendants column */}
              {lineage.descendants?.length > 0 && (
                <div className="lineage-col">
                  {lineage.descendants.map((d: any, i: number) => (
                    <div key={i} className="lineage-node descendant">
                      <div className="lineage-node-name">{d.name || `#${d.id}`}</div>
                      {d.type && <span className={`type-badge ${d.type}`}>{d.type}</span>}
                      {d.creation_tool && <div className="lineage-node-tool">{d.creation_tool}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="empty-state" style={{ height: 60 }}>无血缘关系</div>
          )}
        </div>
      )}
    </div>
  );
}
