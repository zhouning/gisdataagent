import { useState, useEffect } from 'react';

interface VSource {
  id: number;
  source_name: string;
  source_type: string;
  endpoint_url: string;
  owner_username: string;
  is_shared: boolean;
  enabled: boolean;
  health_status: string;
  default_crs: string;
  refresh_policy: string;
  created_at: string | null;
}

const EMPTY_VS_FORM = {
  source_name: '', source_type: 'wfs', endpoint_url: '',
  auth_config: {} as Record<string, string>,
  query_config: '{}', default_crs: 'EPSG:4326',
  refresh_policy: 'on_demand', is_shared: false,
};

export default function VirtualSourcesTab() {
  const [sources, setSources] = useState<VSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState({ ...EMPTY_VS_FORM });
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);
  const [discoveredLayers, setDiscoveredLayers] = useState<any[]>([]);
  const [discovering, setDiscovering] = useState(false);

  // WMS-specific form state
  const [wmsLayers, setWmsLayers] = useState('');
  const [wmsStyles, setWmsStyles] = useState('');
  const [wmsFormat, setWmsFormat] = useState('image/png');
  const [wmsTransparent, setWmsTransparent] = useState(true);
  const [wmsVersion, setWmsVersion] = useState('1.1.1');
  // ArcGIS-specific form state
  const [arcLayerId, setArcLayerId] = useState('0');
  const [arcWhere, setArcWhere] = useState('1=1');
  const [arcOutFields, setArcOutFields] = useState('*');

  const fetchSources = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/virtual-sources', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setSources(d.sources || []); }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchSources(); }, []);

  const handleNew = () => {
    setForm({ ...EMPTY_VS_FORM });
    setEditId(null);
    setFormError('');
    setShowForm(true);
  };

  const handleEdit = (s: VSource) => {
    setForm({
      source_name: s.source_name,
      source_type: s.source_type,
      endpoint_url: s.endpoint_url,
      auth_config: {},
      query_config: '{}',
      default_crs: s.default_crs,
      refresh_policy: s.refresh_policy,
      is_shared: s.is_shared,
    });
    setEditId(s.id);
    setFormError('');
    setShowForm(true);
  };

  const handleDiscover = async () => {
    if (!form.endpoint_url || !form.source_type) return;
    setDiscovering(true);
    setDiscoveredLayers([]);
    try {
      const r = await fetch('/api/virtual-sources/discover', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_type: form.source_type, endpoint_url: form.endpoint_url, auth_config: form.auth_config }),
      });
      if (r.ok) {
        const d = await r.json();
        setDiscoveredLayers(d.layers || []);
      }
    } catch { /* ignore */ }
    finally { setDiscovering(false); }
  };

  const buildQueryConfig = (): object => {
    if (form.source_type === 'wms') {
      return { layers: wmsLayers, styles: wmsStyles, format: wmsFormat, transparent: wmsTransparent, version: wmsVersion };
    }
    if (form.source_type === 'arcgis_rest') {
      return { layer_id: parseInt(arcLayerId) || 0, where: arcWhere, out_fields: arcOutFields };
    }
    try { return JSON.parse(form.query_config); } catch { return {}; }
  };

  const handleSave = async () => {
    if (!form.source_name || !form.endpoint_url) {
      setFormError('名称和端点URL不能为空');
      return;
    }
    let qcfg = {};
    if (['wms', 'arcgis_rest'].includes(form.source_type)) {
      qcfg = buildQueryConfig();
    } else {
      try { qcfg = JSON.parse(form.query_config); } catch { setFormError('查询配置JSON格式错误'); return; }
    }
    setSaving(true);
    setFormError('');
    try {
      const body = {
        source_name: form.source_name,
        source_type: form.source_type,
        endpoint_url: form.endpoint_url,
        auth_config: form.auth_config.type ? form.auth_config : undefined,
        query_config: qcfg,
        default_crs: form.default_crs,
        refresh_policy: form.refresh_policy,
        is_shared: form.is_shared,
      };
      const url = editId ? `/api/virtual-sources/${editId}` : '/api/virtual-sources';
      const method = editId ? 'PUT' : 'POST';
      const r = await fetch(url, {
        method, credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (r.ok) { setShowForm(false); fetchSources(); }
      else { const d = await r.json(); setFormError(d.error || '保存失败'); }
    } catch (e: any) { setFormError(e.message); }
    finally { setSaving(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此数据源？')) return;
    await fetch(`/api/virtual-sources/${id}`, { method: 'DELETE', credentials: 'include' });
    fetchSources();
  };

  const handleTest = async (id: number) => {
    setTesting(id);
    try {
      const r = await fetch(`/api/virtual-sources/${id}/test`, { method: 'POST', credentials: 'include' });
      if (r.ok) { fetchSources(); }
    } catch { /* ignore */ }
    finally { setTesting(null); }
  };

  const healthColor = (h: string) => {
    if (h === 'healthy') return '#10b981';
    if (h === 'error') return '#ef4444';
    if (h === 'timeout') return '#f59e0b';
    return '#888';
  };

  const typeLabel = (t: string) => {
    const map: Record<string, string> = {
      wfs: 'WFS', stac: 'STAC', ogc_api: 'OGC API', custom_api: 'API',
      wms: 'WMS', arcgis_rest: 'ArcGIS',
    };
    return map[t] || t;
  };

  if (loading) return <div style={{ padding: 16, color: '#888' }}>加载中...</div>;

  return (
    <div style={{ padding: '8px 12px', fontSize: 13 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 600 }}>虚拟数据源 ({sources.length})</span>
        <button className="btn-primary btn-sm" onClick={handleNew}
          style={{ fontSize: 12, padding: '2px 10px' }}>+ 新增</button>
      </div>

      {showForm && (
        <div style={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 6, padding: 12, marginBottom: 10 }}>
          <div style={{ display: 'grid', gap: 8 }}>
            <input placeholder="数据源名称" value={form.source_name}
              onChange={e => setForm({ ...form, source_name: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            <div style={{ display: 'flex', gap: 8 }}>
              <select value={form.source_type}
                onChange={e => setForm({ ...form, source_type: e.target.value })}
                style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                <option value="wfs">WFS</option>
                <option value="stac">STAC</option>
                <option value="ogc_api">OGC API</option>
                <option value="custom_api">自定义 API</option>
                <option value="wms">WMS/WMTS</option>
                <option value="arcgis_rest">ArcGIS REST</option>
              </select>
              <select value={form.refresh_policy}
                onChange={e => setForm({ ...form, refresh_policy: e.target.value })}
                style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                <option value="on_demand">按需</option>
                <option value="interval:5m">5分钟</option>
                <option value="interval:30m">30分钟</option>
              </select>
            </div>
            <input placeholder="端点 URL" value={form.endpoint_url}
              onChange={e => setForm({ ...form, endpoint_url: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            <input placeholder="默认CRS (EPSG:4326)" value={form.default_crs}
              onChange={e => setForm({ ...form, default_crs: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            {/* Type-specific query config */}
            {form.source_type === 'wms' ? (
              <div style={{ display: 'grid', gap: 6 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input placeholder="图层 (layers)" value={wmsLayers}
                    onChange={e => setWmsLayers(e.target.value)}
                    style={{ flex: 2, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                  <input placeholder="样式 (styles)" value={wmsStyles}
                    onChange={e => setWmsStyles(e.target.value)}
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <select value={wmsFormat} onChange={e => setWmsFormat(e.target.value)}
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                    <option value="image/png">PNG</option>
                    <option value="image/jpeg">JPEG</option>
                  </select>
                  <select value={wmsVersion} onChange={e => setWmsVersion(e.target.value)}
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                    <option value="1.1.1">WMS 1.1.1</option>
                    <option value="1.3.0">WMS 1.3.0</option>
                  </select>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#aaa', fontSize: 12 }}>
                    <input type="checkbox" checked={wmsTransparent} onChange={e => setWmsTransparent(e.target.checked)} />
                    透明
                  </label>
                </div>
                {form.endpoint_url && (
                  <button onClick={handleDiscover} disabled={discovering}
                    style={{ fontSize: 11, color: '#7dd3fc', background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 10px', cursor: 'pointer' }}>
                    {discovering ? '发现中...' : '发现图层'}
                  </button>
                )}
                {discoveredLayers.length > 0 && (
                  <div style={{ fontSize: 11, color: '#aaa', maxHeight: 80, overflow: 'auto', background: '#0d1117', borderRadius: 4, padding: 6 }}>
                    {discoveredLayers.map((l: any, i: number) => (
                      <div key={i} style={{ cursor: 'pointer', padding: '2px 0' }}
                        onClick={() => setWmsLayers(l.name)}>
                        <span style={{ color: '#7dd3fc' }}>{l.name}</span>
                        {l.title && <span style={{ marginLeft: 6, color: '#666' }}>{l.title}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : form.source_type === 'arcgis_rest' ? (
              <div style={{ display: 'grid', gap: 6 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input placeholder="图层ID (layer_id)" value={arcLayerId}
                    onChange={e => setArcLayerId(e.target.value)} type="number"
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                  <input placeholder="字段 (out_fields: *)" value={arcOutFields}
                    onChange={e => setArcOutFields(e.target.value)}
                    style={{ flex: 2, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                </div>
                <input placeholder="WHERE 条件 (默认: 1=1)" value={arcWhere}
                  onChange={e => setArcWhere(e.target.value)}
                  style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontFamily: 'monospace', fontSize: 12 }} />
                {form.endpoint_url && (
                  <button onClick={handleDiscover} disabled={discovering}
                    style={{ fontSize: 11, color: '#7dd3fc', background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 10px', cursor: 'pointer' }}>
                    {discovering ? '发现中...' : '发现图层'}
                  </button>
                )}
                {discoveredLayers.length > 0 && (
                  <div style={{ fontSize: 11, color: '#aaa', maxHeight: 80, overflow: 'auto', background: '#0d1117', borderRadius: 4, padding: 6 }}>
                    {discoveredLayers.map((l: any, i: number) => (
                      <div key={i} style={{ cursor: 'pointer', padding: '2px 0' }}
                        onClick={() => setArcLayerId(String(l.id ?? 0))}>
                        <span style={{ color: '#7dd3fc' }}>{l.id}: {l.name}</span>
                        {l.geometryType && <span style={{ marginLeft: 6, color: '#666' }}>{l.geometryType}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <textarea placeholder='查询配置 JSON (如 {"feature_type":"topp:states"})' value={form.query_config}
                onChange={e => setForm({ ...form, query_config: e.target.value })} rows={2}
                style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontFamily: 'monospace', fontSize: 12 }} />
            )}
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#aaa' }}>
              <input type="checkbox" checked={form.is_shared}
                onChange={e => setForm({ ...form, is_shared: e.target.checked })} />
              共享给其他用户
            </label>
          </div>
          {formError && <div style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{formError}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn-primary btn-sm" onClick={handleSave} disabled={saving}
              style={{ fontSize: 12 }}>{saving ? '保存中...' : (editId ? '更新' : '创建')}</button>
            <button className="btn-secondary btn-sm" onClick={() => setShowForm(false)}
              style={{ fontSize: 12 }}>取消</button>
          </div>
        </div>
      )}

      {sources.length === 0 && !showForm && (
        <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>
          暂无虚拟数据源，点击"+ 新增"注册远程 WFS/STAC/API 服务
        </div>
      )}

      {sources.map(s => (
        <div key={s.id} style={{
          background: '#111827', border: '1px solid #1f2937', borderRadius: 6,
          padding: '8px 12px', marginBottom: 6, cursor: 'pointer',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#e0e0e0' }}>{s.source_name}</span>
              <span style={{
                marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 3,
                background: '#1e3a5f', color: '#7dd3fc',
              }}>{typeLabel(s.source_type)}</span>
              {s.is_shared && <span style={{ marginLeft: 6, fontSize: 11, color: '#888' }}>共享</span>}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                background: healthColor(s.health_status),
              }} title={s.health_status} />
              <button onClick={(e) => { e.stopPropagation(); handleTest(s.id); }}
                style={{ fontSize: 11, color: '#7dd3fc', background: 'none', border: 'none', cursor: 'pointer' }}
                disabled={testing === s.id}>{testing === s.id ? '测试中...' : '测试'}</button>
              <button onClick={(e) => { e.stopPropagation(); handleEdit(s); }}
                style={{ fontSize: 11, color: '#aaa', background: 'none', border: 'none', cursor: 'pointer' }}>编辑</button>
              <button onClick={(e) => { e.stopPropagation(); handleDelete(s.id); }}
                style={{ fontSize: 11, color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer' }}>删除</button>
            </div>
          </div>
          <div style={{ fontSize: 11, color: '#888', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {s.endpoint_url}
          </div>
        </div>
      ))}
    </div>
  );
}
