import { useState, useEffect } from 'react';
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
}

export default function CatalogTab() {
  const [assets, setAssets] = useState<CatalogAsset[]>([]);
  const [keyword, setKeyword] = useState('');
  const [assetType, setAssetType] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<CatalogAsset | null>(null);

  const fetchAssets = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (keyword) params.set('keyword', keyword);
      if (assetType) params.set('asset_type', assetType);
      const resp = await fetch(`/api/catalog?${params}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setAssets(data.assets || []);
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
  }, [keyword, assetType]);

  if (selectedAsset) {
    return <AssetDetail asset={selectedAsset} onBack={() => setSelectedAsset(null)} />;
  }

  return (
    <div className="catalog-view">
      <div className="catalog-filter-bar">
        <input
          type="text"
          placeholder="搜索资产..."
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
      </div>
      {loading && assets.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : assets.length === 0 ? (
        <div className="empty-state">暂无数据资产</div>
      ) : (
        <ul className="file-list">
          {assets.map((asset) => (
            <li key={asset.id} className="file-item" onClick={() => setSelectedAsset(asset)}>
              <div className={`file-icon-circle ${getAssetCategory(asset.asset_type)}`}>
                {getAssetIcon(asset.asset_type)}
              </div>
              <div className="file-info">
                <div className="file-name" title={asset.asset_name}>{asset.asset_name}</div>
                <div className="file-meta">
                  <span className={`type-badge ${asset.asset_type}`}>{asset.asset_type}</span>
                  {asset.feature_count > 0 && <span>{asset.feature_count} 要素</span>}
                  {asset.crs && <span>{asset.crs}</span>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssetDetail({ asset, onBack }: { asset: CatalogAsset; onBack: () => void }) {
  const [lineage, setLineage] = useState<any>(null);

  useEffect(() => {
    fetch(`/api/catalog/${asset.id}/lineage`, { credentials: 'include' })
      .then((r) => r.json())
      .then(setLineage)
      .catch(() => {});
  }, [asset.id]);

  return (
    <div className="asset-detail">
      <button className="asset-back-btn" onClick={onBack}>&larr; 返回列表</button>
      <h3 className="asset-detail-title">{asset.asset_name}</h3>
      <div className="asset-detail-grid">
        <div className="asset-detail-item"><span>类型</span><span className={`type-badge ${asset.asset_type}`}>{asset.asset_type}</span></div>
        <div className="asset-detail-item"><span>格式</span><span>{asset.file_format || '-'}</span></div>
        <div className="asset-detail-item"><span>存储</span><span>{asset.storage_backend || '-'}</span></div>
        <div className="asset-detail-item"><span>CRS</span><span>{asset.crs || '-'}</span></div>
        <div className="asset-detail-item"><span>要素数</span><span>{asset.feature_count || 0}</span></div>
        <div className="asset-detail-item"><span>大小</span><span>{formatSize(asset.file_size_bytes || 0)}</span></div>
        {asset.description && <div className="asset-detail-item full"><span>描述</span><span>{asset.description}</span></div>}
        {asset.tags && <div className="asset-detail-item full"><span>标签</span><span>{asset.tags}</span></div>}
      </div>
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