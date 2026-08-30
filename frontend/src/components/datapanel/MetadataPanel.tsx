import { useState, useEffect, useRef } from 'react';
import L from 'leaflet';

interface MetadataAsset {
  asset_id: string;
  asset_name: string;
  display_name: string;
  asset_kind?: string;
  ingestion_mode?: string;
  source_type?: string;
  source_id?: number | string | null;
  source_name?: string | null;
  source_rows_persisted?: boolean | string;
  technical_metadata: any;
  business_metadata: any;
  operational_metadata: any;
  lineage_metadata?: any;
  resource_count?: number;
  resources?: any[];
  created_at: string;
}

const INGESTION_LABELS: Record<string, string> = {
  virtual_source: '虚拟入湖',
  physical_lake: '物理入湖',
  file: '文件',
  postgis: 'PostGIS',
  database: '数据库',
  registered_asset: '已登记资产',
};

export default function MetadataPanel() {
  const [assets, setAssets] = useState<MetadataAsset[]>([]);
  const [query, setQuery] = useState('');
  const [regionFilter, setRegionFilter] = useState('');
  const [domainFilter, setDomainFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const fetchAssets = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (regionFilter) params.set('region', regionFilter);
      if (domainFilter) params.set('domain', domainFilter);
      if (sourceFilter) params.set('ingestion_mode', sourceFilter);
      params.set('limit', '200');
      const resp = await fetch(`/api/metadata/unified?${params}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setAssets(data.items || []);
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

  if (selectedKey !== null) {
    return <UnifiedMetadataDetail assetKey={selectedKey} onBack={() => setSelectedKey(null)} />;
  }

  return (
    <div className="metadata-panel">
      <div className="metadata-catalog-heading">
        <div><span className="metadata-catalog-kicker">UNIFIED METADATA CATALOG</span><h3>统一元数据目录</h3></div>
        <span>文件、PostGIS、物理入湖和虚拟入湖统一登记；接入模式不会改变元数据治理边界。</span>
      </div>
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
            <option value="virtual_source">虚拟入湖</option>
            <option value="physical_lake">物理入湖</option>
            <option value="file">文件</option>
            <option value="postgis">PostGIS</option>
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
              <li key={a.asset_id} className="file-item" onClick={() => setSelectedKey(a.asset_id)}>
                <div className={`file-icon-circle ${format === 'tif' || format === 'tiff' ? 'raster' : 'vector'}`}>
                  {format === 'tif' || format === 'tiff' ? '🗺️' : '📍'}
                </div>
                <div className="file-info">
                  <div className="file-name" title={a.display_name || a.asset_name}>
                    {a.display_name || a.asset_name}
                  </div>
                  <div className="file-meta">
                    <span className={`type-badge metadata-mode-${a.ingestion_mode || 'registered_asset'}`}>{INGESTION_LABELS[a.ingestion_mode || 'registered_asset'] || a.ingestion_mode}</span>
                    {a.source_name && <span className="type-badge">{a.source_name}</span>}
                    <span className="type-badge">{format}</span>
                    {domain && <span className="type-badge">{domain}</span>}
                    {regions.length > 0 && (
                      <span style={{ color: '#0d9488', fontSize: 11 }}>{regions.join(', ')}</span>
                    )}
                    {crs && <span style={{ fontSize: 11, color: '#888' }}>{crs}</span>}
                    <span className="metadata-persistence">源行：{a.source_rows_persisted === false ? '未复制' : '已持久化'}</span>
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

function UnifiedMetadataDetail({ assetKey, onBack }: { assetKey: string; onBack: () => void }) {
  const [item, setItem] = useState<MetadataAsset | null>(null);
  const [activeLayer, setActiveLayer] = useState<'technical_metadata' | 'business_metadata' | 'operational_metadata' | 'lineage_metadata' | 'resources'>('resources');
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    setError('');
    try {
      const response = await fetch(`/api/metadata/unified/${encodeURIComponent(assetKey)}`, { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '元数据加载失败');
      const nextItem = payload.item || null;
      setItem(nextItem);
      setActiveLayer(nextItem?.resources?.length ? 'resources' : 'technical_metadata');
    } catch (err) { setError(err instanceof Error ? err.message : '元数据加载失败'); }
  };
  useEffect(() => { void load(); }, [assetKey]);

  const refresh = async () => {
    setRefreshing(true); setError('');
    try {
      const response = await fetch(`/api/metadata/unified/${encodeURIComponent(assetKey)}/refresh`, { method: 'POST', credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '元数据刷新失败');
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : '元数据刷新失败'); }
    finally { setRefreshing(false); }
  };

  if (!item) return <div className="empty-state">{error || '加载中...'}</div>;
  const layers = [
    ...(item.resources ? [{ key: 'resources' as const, label: `资源目录 · 点击表查看字段 (${item.resources.length})` }] : []),
    { key: 'technical_metadata' as const, label: '技术元数据' },
    { key: 'business_metadata' as const, label: '业务元数据' },
    { key: 'operational_metadata' as const, label: '操作元数据' },
    { key: 'lineage_metadata' as const, label: '血缘元数据' },
  ];
  const currentData = activeLayer === 'resources' ? item.resources : item[activeLayer];
  return <div className="metadata-detail">
    <div className="metadata-detail-heading"><button className="asset-back-btn" onClick={onBack}>&larr; 返回统一目录</button><div className="metadata-detail-actions"><span className={`type-badge metadata-mode-${item.ingestion_mode || 'registered_asset'}`}>{INGESTION_LABELS[item.ingestion_mode || 'registered_asset'] || item.ingestion_mode}</span><button className="btn-secondary btn-sm" onClick={() => void refresh()} disabled={refreshing}><span aria-hidden="true">↻</span>{refreshing ? '刷新中' : '刷新发现'}</button></div></div>
    <div className="metadata-detail-summary"><h3>{item.display_name || item.asset_name}</h3><span>{item.asset_id} · {item.source_name || item.source_type || '统一资产目录'}</span><strong>源行：{item.source_rows_persisted === false ? '未复制（元数据快照）' : '已持久化'}</strong></div>
    {error && <div className="inline-error">{error}</div>}
    <div className="metadata-layer-tabs">{layers.map(layer => <button key={layer.key} className={`metadata-layer-tab ${activeLayer === layer.key ? 'active' : ''}`} onClick={() => setActiveLayer(layer.key)}>{layer.label}</button>)}</div>
    <div className="metadata-layer-content">{activeLayer === 'resources' ? <ResourceDirectory resources={item.resources || []} sourceId={item.source_id} /> : currentData ? <JsonTree data={currentData} /> : <div className="empty-state" style={{ height: 60 }}>无数据</div>}</div>
  </div>;
}

const SEMANTIC_STATUS_LABELS: Record<string, string> = {
  reviewed_business_semantics: '已审核',
  technical_semantics_complete_business_review_pending: '待业务审核',
  inferred_candidate: '推断候选',
  dictionary_supported_review_required: '字典支持·待审核',
  dictionary_table_only_review_required: '表级支持·待审核',
  documentation_gap_review_required: '待补证据',
  excluded: '已排除',
};

function ResourceDirectory({ resources, sourceId }: { resources: any[]; sourceId?: number | string | null }) {
  const [filter, setFilter] = useState('');
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const needle = filter.trim().toLocaleLowerCase();
  const visible = resources.filter(resource => !needle || JSON.stringify({
    schema: resource.schema,
    name: resource.name,
    qualified_name: resource.qualified_name,
    resource_type: resource.resource_type,
    columns: resource.columns,
  }).toLocaleLowerCase().includes(needle));
  const selected = visible.find(resource => String(resource.qualified_name || resource.name) === selectedName) || null;
  return <div className="metadata-resource-directory">
    <div className="metadata-resource-toolbar"><div className="metadata-resource-search"><span aria-hidden="true">⌕</span><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="筛选 schema、表名、字段或类型" /></div><span>{visible.length}/{resources.length} 张表</span></div>
    <div className="metadata-resource-table-wrap"><table className="metadata-resource-table"><thead><tr><th>Schema / 表</th><th>语义状态</th><th>类型</th><th>字段</th><th>空间</th><th>PK / FK</th><th>估算行数</th></tr></thead><tbody>{visible.slice(0, 500).map(resource => {
      const columns = resource.columns || [];
      const geometries = columns.filter((column: any) => String(column.type || '').toLocaleLowerCase().includes('geometry'));
      const name = String(resource.qualified_name || `${resource.schema || 'public'}.${resource.name || ''}`);
      const toggle = () => setSelectedName(selectedName === name ? null : name);
      const status = String(resource.semantic_status || 'unknown');
      return <tr key={name} className={selectedName === name ? 'selected' : ''} onClick={toggle} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } }} tabIndex={0} aria-expanded={selectedName === name} title="点击查看字段详情"><td><strong>{name}</strong><span className="metadata-table-open-hint">查看字段</span></td><td><span className={`metadata-semantic-status metadata-semantic-${status}`}>{SEMANTIC_STATUS_LABELS[status] || status}</span>{resource.semantic_execution_eligible && <span className="metadata-semantic-authority">可执行</span>}</td><td>{resource.resource_type || 'table'}</td><td>{columns.length}</td><td>{geometries.length ? geometries.map((column: any) => `${column.name} (${column.type})`).join(', ') : '-'}</td><td>{`${(resource.primary_key || []).length} / ${(resource.foreign_keys || []).length}`}</td><td>{resource.estimated_record_count ?? '-'}</td></tr>;
    })}</tbody></table></div>
    {visible.length > 500 && <div className="metadata-resource-foot">仅显示前 500 张表，请继续筛选。</div>}
    {selected && <div className="metadata-resource-detail"><div className="metadata-resource-detail-heading"><div><strong>{selected.qualified_name || selected.name}</strong><span>{selected.comment || '暂无表说明'}</span></div><button type="button" className="btn-secondary btn-sm" onClick={() => { window.dispatchEvent(new CustomEvent('gda-workspace-update', { detail: { tab: 'semantic', sourceKey: sourceId != null ? `source:${sourceId}` : undefined, tableName: selected.qualified_name || selected.name } })); }}>在语义层打开</button></div><div className="metadata-semantic-summary"><span>语义状态：<b>{SEMANTIC_STATUS_LABELS[String(selected.semantic_status || '')] || selected.semantic_status || '未登记'}</b></span><span>业务资产：<b>{selected.semantic_asset_id || '暂无已发布资产'}</b></span><span>审核状态：<b>{selected.semantic_review_status || '未审核'}</b></span><span>执行资格：<b>{selected.semantic_execution_eligible ? '已授权' : '未授权'}</b></span>{selected.semantic_evidence?.dictionary_alignment_status && <span>字典证据：<b>{selected.semantic_evidence.dictionary_alignment_status}</b></span>}</div><div className="metadata-field-table-wrap"><table className="metadata-field-table"><thead><tr><th>字段</th><th>类型</th><th>可空</th><th>业务语义</th><th>角色</th><th>语义状态</th><th>证据</th></tr></thead><tbody>{(selected.columns || []).map((column: any) => { const fieldStatus = String(column.semantic_status || ''); const labels = column.semantic_labels || {}; return <tr key={String(column.name)}><td><code>{column.name}</code></td><td>{column.type || 'unknown'}</td><td>{column.nullable === false ? '否' : '是'}</td><td>{labels.zh || labels.en || labels.ar || column.semantic_field || <i>—</i>}</td><td>{column.business_role || <i>—</i>}</td><td><span className={`metadata-semantic-status metadata-semantic-${fieldStatus}`}>{SEMANTIC_STATUS_LABELS[fieldStatus] || fieldStatus || '未标注'}</span></td><td>{column.dictionary_evidence?.supported ? '字典' : column.semantic_inference ? `推断·${column.semantic_inference.confidence || '待审'}` : '—'}</td></tr>; })}</tbody></table></div><div className="metadata-resource-constraints"><span>主键：{(selected.primary_key || []).join(', ') || '无'}</span><span>外键：{(selected.foreign_keys || []).map((key: any) => `${(key.columns || []).join(', ')} → ${key.referred_schema || 'public'}.${key.referred_table || ''}`).join('; ') || '无'}</span><span>索引：{(selected.indexes || []).map((index: any) => index.name || (index.columns || []).join(', ')).join(', ') || '无'}</span></div></div>}
  </div>;
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
