import { useState, useEffect, useRef } from 'react';
import L from 'leaflet';

interface MetadataAsset {
  id: number;
  asset_name: string;
  display_name: string;
  technical_metadata: any;
  business_metadata: any;
  operational_metadata: any;
  created_at: string;
}

export default function MetadataPanel() {
  const [assets, setAssets] = useState<MetadataAsset[]>([]);
  const [query, setQuery] = useState('');
  const [regionFilter, setRegionFilter] = useState('');
  const [domainFilter, setDomainFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const fetchAssets = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (regionFilter) params.set('region', regionFilter);
      if (domainFilter) params.set('domain', domainFilter);
      if (sourceFilter) params.set('source_type', sourceFilter);
      const resp = await fetch(`/api/metadata/search?${params}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setAssets(data.assets || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchAssets();
  }, []);

  useEffect(() => {
    const timer = setTimeout(fetchAssets, 300);
    return () => clearTimeout(timer);
  }, [query, regionFilter, domainFilter, sourceFilter]);

  if (selectedId !== null) {
    return <MetadataDetail assetId={selectedId} onBack={() => setSelectedId(null)} />;
  }

  return (
    <div className="metadata-panel">
      <div className="metadata-filters">
        <input
          type="text"
          placeholder="搜索数据资产..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="catalog-search"
        />
        <div className="metadata-filter-row">
          <select value={regionFilter} onChange={(e) => setRegionFilter(e.target.value)} className="catalog-type-select">
            <option value="">全部地区</option>
            <option value="重庆市">重庆市</option>
            <option value="四川省">四川省</option>
            <option value="上海市">上海市</option>
            <option value="北京市">北京市</option>
            <option value="广东省">广东省</option>
            <option value="浙江省">浙江省</option>
            <option value="江苏省">江苏省</option>
            <option value="山东省">山东省</option>
            <option value="河南省">河南省</option>
          </select>
          <select value={domainFilter} onChange={(e) => setDomainFilter(e.target.value)} className="catalog-type-select">
            <option value="">全部领域</option>
            <option value="LAND_USE">土地利用</option>
            <option value="ELEVATION">高程</option>
            <option value="POPULATION">人口</option>
            <option value="TRANSPORTATION">交通</option>
            <option value="BUILDING">建筑</option>
          </select>
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} className="catalog-type-select">
            <option value="">全部来源</option>
            <option value="uploaded">上传</option>
            <option value="generated">生成</option>
          </select>
        </div>
      </div>

      {loading && assets.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : assets.length === 0 ? (
        <div className="empty-state">暂无数据资产</div>
      ) : (
        <ul className="file-list">
          {assets.map((a) => {
            const tech = a.technical_metadata || {};
            const biz = a.business_metadata || {};
            const regions = biz?.geography?.region_tags || [];
            const domain = biz?.classification?.domain;
            const format = tech?.storage?.format || '-';
            const crs = tech?.spatial?.crs;

            return (
              <li key={a.id} className="file-item" onClick={() => setSelectedId(a.id)}>
                <div className={`file-icon-circle ${format === 'tif' || format === 'tiff' ? 'raster' : 'vector'}`}>
                  {format === 'tif' || format === 'tiff' ? '🗺️' : '📍'}
                </div>
                <div className="file-info">
                  <div className="file-name" title={a.display_name || a.asset_name}>
                    {a.display_name || a.asset_name}
                  </div>
                  <div className="file-meta">
                    <span className="type-badge">{format}</span>
                    {domain && <span className="type-badge">{domain}</span>}
                    {regions.length > 0 && (
                      <span style={{ color: '#0d9488', fontSize: 11 }}>{regions.join(', ')}</span>
                    )}
                    {crs && <span style={{ fontSize: 11, color: '#888' }}>{crs}</span>}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function MetadataDetail({ assetId, onBack }: { assetId: number; onBack: () => void }) {
  const [meta, setMeta] = useState<any>(null);
  const [lineage, setLineage] = useState<any>(null);
  const [activeLayer, setActiveLayer] = useState<'technical' | 'business' | 'operational' | 'lineage'>('technical');
  const bboxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`/api/metadata/${assetId}`, { credentials: 'include' })
      .then(r => r.json()).then(setMeta).catch(() => {});
    fetch(`/api/metadata/${assetId}/lineage`, { credentials: 'include' })
      .then(r => r.json()).then(setLineage).catch(() => {});
  }, [assetId]);

  // Bbox mini-map
  useEffect(() => {
    const ext = meta?.technical?.spatial?.extent;
    if (!ext || !bboxRef.current) return;
    if (ext.minx == null) return;

    const bounds: L.LatLngBoundsLiteral = [
      [ext.miny, ext.minx],
      [ext.maxy, ext.maxx],
    ];
    const map = L.map(bboxRef.current, {
      zoomControl: false, attributionControl: false,
      dragging: false, scrollWheelZoom: false,
      doubleClickZoom: false, touchZoom: false,
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);
    L.rectangle(bounds, { color: '#0d9488', weight: 2, fillColor: '#0d9488', fillOpacity: 0.15 }).addTo(map);
    map.fitBounds(bounds, { padding: [10, 10] });
    return () => { map.remove(); };
  }, [meta]);

  if (!meta) return <div className="empty-state">加载中...</div>;

  const layers = [
    { key: 'technical' as const, label: '技术元数据', icon: '⚙️', color: '#3b82f6' },
    { key: 'business' as const, label: '业务元数据', icon: '💼', color: '#10b981' },
    { key: 'operational' as const, label: '操作元数据', icon: '🔄', color: '#f59e0b' },
    { key: 'lineage' as const, label: '血缘元数据', icon: '🔗', color: '#8b5cf6' },
  ];

  const currentData = activeLayer === 'lineage' ? lineage : meta[activeLayer];

  return (
    <div className="metadata-detail">
      <button className="asset-back-btn" onClick={onBack}>&larr; 返回列表</button>

      {/* Bbox preview */}
      {meta.technical?.spatial?.extent && (
        <div className="bbox-preview-section">
          <div className="bbox-preview" ref={bboxRef} style={{ height: 120 }} />
        </div>
      )}

      {/* Layer tabs */}
      <div className="metadata-layer-tabs">
        {layers.map(l => (
          <button
            key={l.key}
            className={`metadata-layer-tab ${activeLayer === l.key ? 'active' : ''}`}
            onClick={() => setActiveLayer(l.key)}
            style={{ borderBottomColor: activeLayer === l.key ? l.color : 'transparent' }}
          >
            <span>{l.icon}</span> {l.label}
          </button>
        ))}
      </div>

      {/* Layer content */}
      <div className="metadata-layer-content">
        {currentData ? (
          <JsonTree data={currentData} />
        ) : (
          <div className="empty-state" style={{ height: 60 }}>无数据</div>
        )}
      </div>
    </div>
  );
}

function JsonTree({ data, depth = 0 }: { data: any; depth?: number }) {
  if (data === null || data === undefined) return <span className="json-null">null</span>;
  if (typeof data === 'string') return <span className="json-string">"{data}"</span>;
  if (typeof data === 'number') return <span className="json-number">{data}</span>;
  if (typeof data === 'boolean') return <span className="json-bool">{data ? 'true' : 'false'}</span>;

  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="json-null">[]</span>;
    return (
      <div className="json-array" style={{ paddingLeft: depth > 0 ? 16 : 0 }}>
        {data.map((item, i) => (
          <div key={i} className="json-array-item">
            <JsonTree data={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  if (typeof data === 'object') {
    const entries = Object.entries(data);
    if (entries.length === 0) return <span className="json-null">{'{}'}</span>;
    return (
      <div className="json-object" style={{ paddingLeft: depth > 0 ? 16 : 0 }}>
        {entries.map(([key, val]) => (
          <div key={key} className="json-kv">
            <span className="json-key">{key}:</span>
            <JsonTree data={val} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  return <span>{String(data)}</span>;
}
