import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import L from 'leaflet';
import { ArrowLeft } from 'lucide-react';
import { getLocaleHeaders } from '../../i18n';

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
  const { t, i18n } = useTranslation('common');
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
      const resp = await fetch(`/api/metadata/search?${params}`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (resp.ok) {
        const data = await resp.json();
        setAssets(data.assets || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchAssets();
  }, [i18n.resolvedLanguage]);

  useEffect(() => {
    const timer = setTimeout(fetchAssets, 300);
    return () => clearTimeout(timer);
  }, [query, regionFilter, domainFilter, sourceFilter, i18n.resolvedLanguage]);

  if (selectedId !== null) {
    return <MetadataDetail assetId={selectedId} onBack={() => setSelectedId(null)} />;
  }

  return (
    <div className="metadata-panel">
      <div className="metadata-filters">
        <input
          type="text"
          placeholder={t('assetWorkbench.metadata.searchPlaceholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="catalog-search"
        />
        <div className="metadata-filter-row">
          <select value={regionFilter} onChange={(e) => setRegionFilter(e.target.value)} className="catalog-type-select">
            <option value="">{t('assetWorkbench.metadata.allRegions')}</option>
            {['\u91cd\u5e86\u5e02', '\u56db\u5ddd\u7701', '\u4e0a\u6d77\u5e02', '\u5317\u4eac\u5e02', '\u5e7f\u4e1c\u7701', '\u6d59\u6c5f\u7701', '\u6c5f\u82cf\u7701', '\u5c71\u4e1c\u7701', '\u6cb3\u5357\u7701'].map(region => (
              <option key={region} value={region}>
                {t(`assetWorkbench.metadata.regions.${region}`, { defaultValue: region })}
              </option>
            ))}
          </select>
          <select value={domainFilter} onChange={(e) => setDomainFilter(e.target.value)} className="catalog-type-select">
            <option value="">{t('assetWorkbench.metadata.allDomains')}</option>
            {['LAND_USE', 'ELEVATION', 'POPULATION', 'TRANSPORTATION', 'BUILDING'].map(domain => (
              <option key={domain} value={domain}>{t(`assetWorkbench.metadata.domains.${domain}`)}</option>
            ))}
          </select>
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} className="catalog-type-select">
            <option value="">{t('assetWorkbench.metadata.allSources')}</option>
            <option value="uploaded">{t('assetWorkbench.metadata.sources.uploaded')}</option>
            <option value="generated">{t('assetWorkbench.metadata.sources.generated')}</option>
          </select>
        </div>
      </div>

      {loading && assets.length === 0 ? (
        <div className="empty-state">{t('assetWorkbench.common.loading')}</div>
      ) : assets.length === 0 ? (
        <div className="empty-state">{t('assetWorkbench.common.noAssets')}</div>
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
                    {domain && (
                      <span className="type-badge">
                        {t(`assetWorkbench.metadata.domains.${domain}`, { defaultValue: domain })}
                      </span>
                    )}
                    {regions.length > 0 && (
                      <span style={{ color: '#0d9488', fontSize: 11 }}>
                        {regions.map((region: string) => t(`assetWorkbench.metadata.regions.${region}`, { defaultValue: region })).join(', ')}
                      </span>
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
  const { t, i18n } = useTranslation('common');
  const [meta, setMeta] = useState<any>(null);
  const [lineage, setLineage] = useState<any>(null);
  const [activeLayer, setActiveLayer] = useState<'technical' | 'business' | 'operational' | 'lineage'>('technical');
  const bboxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`/api/metadata/${assetId}`, { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.json()).then(setMeta).catch(() => {});
    fetch(`/api/metadata/${assetId}/lineage`, { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.json()).then(setLineage).catch(() => {});
  }, [assetId, i18n.resolvedLanguage]);

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

  if (!meta) return <div className="empty-state">{t('assetWorkbench.common.loading')}</div>;

  const layers = [
    { key: 'technical' as const, label: t('assetWorkbench.metadata.layers.technical'), icon: '⚙️', color: '#3b82f6' },
    { key: 'business' as const, label: t('assetWorkbench.metadata.layers.business'), icon: '💼', color: '#10b981' },
    { key: 'operational' as const, label: t('assetWorkbench.metadata.layers.operational'), icon: '🔄', color: '#f59e0b' },
    { key: 'lineage' as const, label: t('assetWorkbench.metadata.layers.lineage'), icon: '🔗', color: '#8b5cf6' },
  ];

  const currentData = activeLayer === 'lineage' ? lineage : meta[activeLayer];

  return (
    <div className="metadata-detail">
      <button className="asset-back-btn" onClick={onBack}>
        <ArrowLeft aria-hidden="true" />
        <span>{t('assetWorkbench.common.backToList')}</span>
      </button>

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
          <div className="empty-state" style={{ height: 60 }}>{t('assetWorkbench.common.noData')}</div>
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
      <div className="json-array" style={{ paddingInlineStart: depth > 0 ? 16 : 0 }}>
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
      <div className="json-object" style={{ paddingInlineStart: depth > 0 ? 16 : 0 }}>
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
