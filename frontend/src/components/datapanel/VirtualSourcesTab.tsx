import { useState, useEffect } from 'react';
import { Database } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import FieldMappingEditor from './FieldMappingEditor';
import IngestionDialog from './IngestionDialog';
import { getLocaleHeaders } from '../../i18n';

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
  query_config?: Record<string, any>;
}

const EMPTY_VS_FORM = {
  source_name: '', source_type: 'wfs', endpoint_url: '',
  auth_config: {} as Record<string, string>,
  query_config: '{}', default_crs: 'EPSG:4326',
  refresh_policy: 'on_demand', is_shared: false,
};

export default function VirtualSourcesTab() {
  const { t } = useTranslation('common');
  const [sources, setSources] = useState<VSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [wizardStep, setWizardStep] = useState(1);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState({ ...EMPTY_VS_FORM });
  const [mappingSource, setMappingSource] = useState<VSource | null>(null);
  const [ingestionSource, setIngestionSource] = useState<VSource | null>(null);
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
  const [arcMaxRecords, setArcMaxRecords] = useState('5000');
  const [arcPageSize, setArcPageSize] = useState('2000');

  const fetchSources = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/virtual-sources', { credentials: 'include', headers: getLocaleHeaders() });
      if (r.ok) { const d = await r.json(); setSources(d.sources || []); }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchSources(); }, []);

  const handleNew = () => {
    setForm({ ...EMPTY_VS_FORM });
    setEditId(null);
    setFormError('');
    setWizardStep(1);
    setDiscoveredLayers([]);
    setArcLayerId('0');
    setArcWhere('1=1');
    setArcOutFields('*');
    setArcMaxRecords('5000');
    setArcPageSize('2000');
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
    const arcConfig = s.query_config || {};
    setArcLayerId(String(arcConfig.layer_id ?? 0));
    setArcWhere(String(arcConfig.where ?? '1=1'));
    setArcOutFields(String(arcConfig.out_fields ?? '*'));
    setArcMaxRecords(String(arcConfig.max_records ?? 5000));
    setArcPageSize(String(arcConfig.page_size ?? 2000));
    setShowForm(true);
  };

  const handleDiscover = async () => {
    if (!form.endpoint_url || !form.source_type) return;
    setDiscovering(true);
    setDiscoveredLayers([]);
    try {
      const r = await fetch('/api/virtual-sources/discover', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ source_type: form.source_type, endpoint_url: form.endpoint_url, auth_config: form.auth_config }),
      });
      if (r.ok) {
        const d = await r.json();
        setDiscoveredLayers(d.layers || []);
        if (d.partial && Array.isArray(d.warnings) && d.warnings.length > 0) {
          setFormError(t('virtualSources.partialDiscoveryFailed', { error: d.warnings[0] }));
        }
      } else {
        const d = await r.json();
        setFormError(d.error || t('virtualSources.discoveryFailed'));
      }
    } catch { setFormError(t('virtualSources.discoveryFailed')); }
    finally { setDiscovering(false); }
  };

  const buildQueryConfig = (): object => {
    if (form.source_type === 'wms') {
      return { layers: wmsLayers, styles: wmsStyles, format: wmsFormat, transparent: wmsTransparent, version: wmsVersion };
    }
    if (form.source_type === 'arcgis_rest') {
      return {
        layer_id: parseInt(arcLayerId) || 0,
        where: arcWhere,
        out_fields: arcOutFields,
        max_records: Math.max(1, Math.min(parseInt(arcMaxRecords) || 5000, 1000000)),
        page_size: Math.max(1, Math.min(parseInt(arcPageSize) || 2000, 5000)),
      };
    }
    try { return JSON.parse(form.query_config); } catch { return {}; }
  };

  const handleSave = async () => {
    if (!form.source_name || !form.endpoint_url) {
      setFormError(t('virtualSources.requiredFields'));
      return;
    }
    let qcfg = {};
    if (['wms', 'arcgis_rest'].includes(form.source_type)) {
      qcfg = buildQueryConfig();
    } else {
      try { qcfg = JSON.parse(form.query_config); } catch { setFormError(t('virtualSources.invalidQueryConfig')); return; }
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
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(body),
      });
      if (r.ok) { setShowForm(false); fetchSources(); }
      else { const d = await r.json(); setFormError(d.error || t('virtualSources.saveFailed')); }
    } catch (e: any) { setFormError(e.message); }
    finally { setSaving(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm(t('virtualSources.deleteConfirm'))) return;
    await fetch(`/api/virtual-sources/${id}`, { method: 'DELETE', credentials: 'include', headers: getLocaleHeaders() });
    fetchSources();
  };

  const handleTest = async (id: number) => {
    setTesting(id);
    try {
      const r = await fetch(`/api/virtual-sources/${id}/test`, { method: 'POST', credentials: 'include', headers: getLocaleHeaders() });
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
      wms: 'WMS', arcgis_rest: 'ArcGIS', database: 'DB', object_storage: 'OBS',
    };
    return map[t] || t;
  };

  if (loading) return <div style={{ padding: 16, color: '#888' }}>{t('virtualSources.loading')}</div>;

  return (
    <div style={{ padding: '8px 12px', fontSize: 13 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 600 }}>{t('virtualSources.title', { count: sources.length })}</span>
        <button className="btn-primary btn-sm" onClick={handleNew}
          style={{ fontSize: 12, padding: '2px 10px' }}>+ {t('virtualSources.add')}</button>
      </div>

      {showForm && (
        <div style={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 6, padding: 12, marginBottom: 10 }}>
          {/* Wizard step indicator */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 10, justifyContent: 'center' }}>
            {[1, 2, 3, 4].map(s => (
              <div key={s} style={{
                width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 600, cursor: 'pointer',
                background: wizardStep === s ? '#2563eb' : wizardStep > s ? '#10b981' : '#333',
                color: wizardStep >= s ? '#fff' : '#666',
              }} onClick={() => { if (s <= wizardStep) setWizardStep(s); }}>
                {wizardStep > s ? '✓' : s}
              </div>
            ))}
          </div>
          <div style={{ display: 'grid', gap: 8 }}>
            {/* Step 1: Basic Info */}
            {wizardStep === 1 && (<>
            <input placeholder={t('virtualSources.sourceName')} value={form.source_name}
              onChange={e => setForm({ ...form, source_name: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            <div style={{ display: 'flex', gap: 8 }}>
              <select value={form.source_type}
                onChange={e => setForm({ ...form, source_type: e.target.value })}
                style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                <option value="wfs">WFS</option>
                <option value="stac">STAC</option>
                <option value="ogc_api">OGC API</option>
                <option value="custom_api">{t('virtualSources.sourceTypes.customApi')}</option>
                <option value="wms">WMS/WMTS</option>
                <option value="arcgis_rest">ArcGIS REST</option>
                <option value="database">{t('virtualSources.sourceTypes.externalDatabase')}</option>
                <option value="object_storage">{t('virtualSources.sourceTypes.objectStorage')}</option>
              </select>
              <select value={form.refresh_policy}
                onChange={e => setForm({ ...form, refresh_policy: e.target.value })}
                style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                <option value="on_demand">{t('virtualSources.refresh.onDemand')}</option>
                <option value="interval:5m">{t('virtualSources.refresh.every5Minutes')}</option>
                <option value="interval:30m">{t('virtualSources.refresh.every30Minutes')}</option>
              </select>
            </div>
            <input placeholder={t('virtualSources.endpointUrl')} value={form.endpoint_url}
              onChange={e => setForm({ ...form, endpoint_url: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            </>)}

            {/* Step 2: CRS + Refresh + Shared */}
            {wizardStep === 2 && (<>
            <input placeholder={t('virtualSources.defaultCrs')} value={form.default_crs}
              onChange={e => setForm({ ...form, default_crs: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#aaa' }}>
              <input type="checkbox" checked={form.is_shared}
                onChange={e => setForm({ ...form, is_shared: e.target.checked })} />
              {t('virtualSources.shareWithOthers')}
            </label>
            </>)}

            {/* Step 3: Type-specific query config */}
            {wizardStep === 3 && (<>
            {/* Type-specific query config */}
            {form.source_type === 'wms' ? (
              <div style={{ display: 'grid', gap: 6 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input placeholder={t('virtualSources.layersPlaceholder')} value={wmsLayers}
                    onChange={e => setWmsLayers(e.target.value)}
                    style={{ flex: 2, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                  <input placeholder={t('virtualSources.stylesPlaceholder')} value={wmsStyles}
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
                    {t('virtualSources.transparent')}
                  </label>
                </div>
                {form.endpoint_url && (
                  <button onClick={handleDiscover} disabled={discovering}
                    style={{ fontSize: 11, color: '#7dd3fc', background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 10px', cursor: 'pointer' }}>
                    {discovering ? t('virtualSources.discovering') : t('virtualSources.discoverLayers')}
                  </button>
                )}
                {discoveredLayers.length > 0 && (
                  <div style={{ fontSize: 11, color: '#aaa', maxHeight: 80, overflow: 'auto', background: '#0d1117', borderRadius: 4, padding: 6 }}>
                    {discoveredLayers.map((l: any, i: number) => (
                      <div key={i} style={{ cursor: 'pointer', padding: '2px 0' }}
                        onClick={() => setWmsLayers(l.name)}>
                        <span style={{ color: '#7dd3fc' }}>{l.name}</span>
                        {l.title && <span style={{ marginInlineStart: 6, color: '#666' }}>{l.title}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : form.source_type === 'arcgis_rest' ? (
              <div style={{ display: 'grid', gap: 6 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input placeholder={t('virtualSources.layerIdPlaceholder')} value={arcLayerId}
                    onChange={e => setArcLayerId(e.target.value)} type="number"
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                  <input placeholder={t('virtualSources.outFieldsPlaceholder')} value={arcOutFields}
                    onChange={e => setArcOutFields(e.target.value)}
                    style={{ flex: 2, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                </div>
                <input placeholder={t('virtualSources.wherePlaceholder')} value={arcWhere}
                  onChange={e => setArcWhere(e.target.value)}
                  style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontFamily: 'monospace', fontSize: 12 }} />
                <div style={{ display: 'flex', gap: 8 }}>
                  <input placeholder={t('virtualSources.maxRecords')} value={arcMaxRecords}
                    onChange={e => setArcMaxRecords(e.target.value)} type="number" min="1" max="1000000"
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                  <input placeholder={t('virtualSources.pageSize')} value={arcPageSize}
                    onChange={e => setArcPageSize(e.target.value)} type="number" min="1" max="5000"
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                </div>
                {form.endpoint_url && (
                  <button onClick={handleDiscover} disabled={discovering}
                    style={{ fontSize: 11, color: '#7dd3fc', background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 10px', cursor: 'pointer' }}>
                    {discovering ? t('virtualSources.discovering') : t('virtualSources.discoverLayers')}
                  </button>
                )}
                {discoveredLayers.length > 0 && (
                  <div style={{ fontSize: 11, color: '#aaa', maxHeight: 80, overflow: 'auto', background: '#0d1117', borderRadius: 4, padding: 6 }}>
                    {discoveredLayers.map((l: any, i: number) => (
                      <div key={i} style={{ cursor: 'pointer', padding: '2px 0' }}
                        onClick={() => {
                          setArcLayerId(String(l.id ?? 0));
                          if (l.endpoint_url) {
                            setForm(previous => ({ ...previous, endpoint_url: l.endpoint_url }));
                          }
                        }}>
                        <span style={{ color: '#7dd3fc' }}>
                          {l.service_name ? `${l.service_name} / ` : ''}{l.id}: {l.name}
                        </span>
                        {l.geometryType && <span style={{ marginInlineStart: 6, color: '#666' }}>{l.geometryType}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <textarea placeholder={t('virtualSources.queryConfigPlaceholder')} value={form.query_config}
                onChange={e => setForm({ ...form, query_config: e.target.value })} rows={2}
                style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontFamily: 'monospace', fontSize: 12 }} />
            )}
            </>)}

            {/* Step 4: Confirm & Create */}
            {wizardStep === 4 && (<>
            <div style={{ background: '#0d1117', borderRadius: 4, padding: 8, fontSize: 12, color: '#aaa' }}>
              <div><strong style={{ color: '#e0e0e0' }}>{t('virtualSources.name')}:</strong> {form.source_name}</div>
              <div><strong style={{ color: '#e0e0e0' }}>{t('virtualSources.type')}:</strong> {form.source_type}</div>
              <div><strong style={{ color: '#e0e0e0' }}>{t('virtualSources.endpoint')}:</strong> {form.endpoint_url}</div>
              <div><strong style={{ color: '#e0e0e0' }}>CRS:</strong> {form.default_crs}</div>
              <div><strong style={{ color: '#e0e0e0' }}>{t('virtualSources.refreshLabel')}:</strong> {form.refresh_policy}</div>
              <div><strong style={{ color: '#e0e0e0' }}>{t('virtualSources.shared')}:</strong> {form.is_shared ? t('virtualSources.yes') : t('virtualSources.no')}</div>
            </div>
            </>)}
          </div>
          {formError && <div style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{formError}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', gap: 8 }}>
              {wizardStep > 1 && (
                <button className="btn-secondary btn-sm" onClick={() => setWizardStep(wizardStep - 1)}
                  style={{ fontSize: 12 }}>{t('virtualSources.previous')}</button>
              )}
              <button className="btn-secondary btn-sm" onClick={() => setShowForm(false)}
                style={{ fontSize: 12 }}>{t('virtualSources.cancel')}</button>
            </div>
            <div>
              {wizardStep < 4 ? (
                <button className="btn-primary btn-sm" onClick={() => {
                  if (wizardStep === 1 && (!form.source_name || !form.endpoint_url)) {
                    setFormError(t('virtualSources.requiredFields')); return;
                  }
                  setFormError('');
                  setWizardStep(wizardStep + 1);
                }} style={{ fontSize: 12 }}>{t('virtualSources.next')}</button>
              ) : (
                <button className="btn-primary btn-sm" onClick={handleSave} disabled={saving}
                  style={{ fontSize: 12 }}>{saving ? t('virtualSources.saving') : (editId ? t('virtualSources.update') : t('virtualSources.create'))}</button>
              )}
            </div>
          </div>
        </div>
      )}

      {sources.length === 0 && !showForm && (
        <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>
          {t('virtualSources.empty')}
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
                marginInlineStart: 8, fontSize: 11, padding: '1px 6px', borderRadius: 3,
                background: '#1e3a5f', color: '#7dd3fc',
              }}>{typeLabel(s.source_type)}</span>
              {s.is_shared && <span style={{ marginInlineStart: 6, fontSize: 11, color: '#888' }}>{t('virtualSources.shared')}</span>}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                background: healthColor(s.health_status),
              }} title={s.health_status} />
              <button onClick={(e) => { e.stopPropagation(); handleTest(s.id); }}
                style={{ fontSize: 11, color: '#7dd3fc', background: 'none', border: 'none', cursor: 'pointer' }}
                disabled={testing === s.id}>{testing === s.id ? t('virtualSources.testing') : t('virtualSources.test')}</button>
              <button onClick={(e) => { e.stopPropagation(); handleEdit(s); }}
                style={{ fontSize: 11, color: '#aaa', background: 'none', border: 'none', cursor: 'pointer' }}>{t('virtualSources.edit')}</button>
              {s.source_type === 'arcgis_rest' && (
                <button onClick={(e) => { e.stopPropagation(); setIngestionSource(s); }}
                  title={t('virtualSources.ingest')} style={{
                    display: 'flex', alignItems: 'center', gap: 3, fontSize: 11,
                    color: '#34d399', background: 'none', border: 'none', cursor: 'pointer',
                  }}><Database size={12} />{t('virtualSources.ingest')}</button>
              )}
              <button onClick={(e) => { e.stopPropagation(); setMappingSource(s); }}
                style={{ fontSize: 11, color: '#a78bfa', background: 'none', border: 'none', cursor: 'pointer' }}>{t('virtualSources.mapping')}</button>
              <button onClick={(e) => { e.stopPropagation(); handleDelete(s.id); }}
                style={{ fontSize: 11, color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer' }}>{t('virtualSources.delete')}</button>
            </div>
          </div>
          <div style={{ fontSize: 11, color: '#888', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {s.endpoint_url}
          </div>
        </div>
      ))}

    {/* Field Mapping Modal */}
    {mappingSource && (
      <FieldMappingEditor
        sourceId={mappingSource.id}
        sourceName={mappingSource.source_name}
        existingMapping={{}}
        onClose={() => setMappingSource(null)}
        onSave={() => { fetchSources(); }}
      />
    )}
    {ingestionSource && (
      <IngestionDialog
        source={ingestionSource}
        onClose={() => setIngestionSource(null)}
      />
    )}
    </div>
  );
}
