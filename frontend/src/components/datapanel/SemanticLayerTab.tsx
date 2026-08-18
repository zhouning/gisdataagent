import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

interface SourceMeta {
  table_name: string;
  display_name: string;
  description: string;
  geometry_type?: string | null;
  srid?: number | null;
  synonyms: string[];
  suggested_analyses: string[];
  annotation_count?: number;
}

interface ColumnAnnotation {
  column_name: string;
  data_type?: string;
  semantic_domain?: string | null;
  aliases?: string[];
  unit?: string;
  description?: string;
  is_geometry?: boolean;
}

interface TableDetail {
  status?: string;
  table_name?: string;
  source?: SourceMeta | null;
  columns?: ColumnAnnotation[];
}

interface ResolveResult {
  sources?: any[];
  matched_columns?: Record<string, any[]>;
  sql_filters?: string[];
  region_sql?: string[];
  hierarchy_matches?: any[];
  equivalences?: any[];
  metric_hints?: any[];
  spatial_ops?: any[];
  error?: string;
  [key: string]: any;
}

const EMPTY_SRC_FORM = {
  display_name: '', description: '',
  synonyms: '', suggested_analyses: '',
};

const EMPTY_COL_FORM = {
  semantic_domain: '', aliases: '', unit: '', description: '',
};

export default function SemanticLayerTab({ userRole }: { userRole?: string }) {
  const { t } = useTranslation();
  const canEdit = userRole === 'admin' || userRole === 'analyst';

  const [sources, setSources] = useState<SourceMeta[]>([]);
  const [unregistered, setUnregistered] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TableDetail | null>(null);
  const [domains, setDomains] = useState<{ name: string; description: string }[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>('');
  const [info, setInfo] = useState<string>('');
  const [showUnreg, setShowUnreg] = useState(false);

  // Table-level edit
  const [editingSrc, setEditingSrc] = useState(false);
  const [srcForm, setSrcForm] = useState(EMPTY_SRC_FORM);

  // Column-level edit (keyed by column name when editing)
  const [editingCol, setEditingCol] = useState<string | null>(null);
  const [colForm, setColForm] = useState(EMPTY_COL_FORM);

  // Preview panel
  const [showPreview, setShowPreview] = useState(false);
  const [previewQ, setPreviewQ] = useState('');
  const [previewRes, setPreviewRes] = useState<ResolveResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { refreshAll(); loadDomains(); }, []);

  async function api<T = any>(path: string, opts: RequestInit = {}): Promise<{ ok: boolean; data: T; status: number }> {
    try {
      const headers = opts.body
        ? { ...getLocaleHeaders(), 'Content-Type': 'application/json', ...(opts.headers || {}) }
        : { ...getLocaleHeaders(), ...(opts.headers || {}) };
      const resp = await fetch(path, {
        ...opts,
        credentials: 'include',
        headers,
      });
      const data = await resp.json().catch(() => ({}));
      return { ok: resp.ok, data: data as T, status: resp.status };
    } catch (e) {
      return { ok: false, data: { error: String(e) } as any, status: 0 };
    }
  }

  async function refreshAll() {
    setLoading(true);
    setError(''); setInfo('');
    const [a, b] = await Promise.all([
      api<{ sources: SourceMeta[] }>('/api/semantic/sources'),
      api<{ unregistered: string[] }>('/api/semantic/unregistered'),
    ]);
    if (a.ok) setSources(a.data.sources || []);
    if (b.ok) setUnregistered(b.data.unregistered || []);
    setLoading(false);
  }

  async function loadDomains() {
    const r = await api<{ domains: { name: string; description: string }[] }>('/api/semantic/domains');
    if (r.ok) setDomains(r.data.domains || []);
  }

  async function selectTable(name: string) {
    setSelected(name);
    setEditingSrc(false); setEditingCol(null);
    const r = await api<TableDetail>(`/api/semantic/sources/${encodeURIComponent(name)}`);
    setDetail(r.ok ? r.data : null);
    if (r.ok && r.data?.source) {
      setSrcForm({
        display_name: r.data.source.display_name || '',
        description: r.data.source.description || '',
        synonyms: (r.data.source.synonyms || []).join(', '),
        suggested_analyses: (r.data.source.suggested_analyses || []).join(', '),
      });
    }
  }

  async function saveSource() {
    if (!selected) return;
    setSaving(true); setError('');
    const body = {
      display_name: srcForm.display_name.trim(),
      description: srcForm.description.trim(),
      synonyms: srcForm.synonyms.split(',').map(s => s.trim()).filter(Boolean),
      suggested_analyses: srcForm.suggested_analyses.split(',').map(s => s.trim()).filter(Boolean),
    };
    const r = await api(`/api/semantic/sources/${encodeURIComponent(selected)}`, {
      method: 'PUT', body: JSON.stringify(body),
    });
    setSaving(false);
    if (r.ok) { setEditingSrc(false); await selectTable(selected); await refreshAll(); }
    else setError(r.data?.error || t('semanticLayer.errors.save'));
  }

  async function deleteSource(name: string) {
    if (!confirm(t('semanticLayer.confirm.deleteSource', { name }))) return;
    const r = await api(`/api/semantic/sources/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (r.ok) {
      setSelected(null); setDetail(null);
      setInfo(t('semanticLayer.messages.sourceDeleted', { name }));
      await refreshAll();
    } else setError(r.data?.error || t('semanticLayer.errors.delete'));
  }

  function beginEditCol(col: ColumnAnnotation) {
    setEditingCol(col.column_name);
    setColForm({
      semantic_domain: col.semantic_domain || '',
      aliases: (col.aliases || []).join(', '),
      unit: col.unit || '',
      description: col.description || '',
    });
  }

  async function saveCol() {
    if (!selected || !editingCol) return;
    setSaving(true); setError('');
    const body = {
      semantic_domain: colForm.semantic_domain.trim() || null,
      aliases: colForm.aliases.split(',').map(s => s.trim()).filter(Boolean),
      unit: colForm.unit.trim(),
      description: colForm.description.trim(),
    };
    const r = await api(
      `/api/semantic/annotations/${encodeURIComponent(selected)}/${encodeURIComponent(editingCol)}`,
      { method: 'PUT', body: JSON.stringify(body) },
    );
    setSaving(false);
    if (r.ok) { setEditingCol(null); await selectTable(selected); }
    else setError(r.data?.error || t('semanticLayer.errors.save'));
  }

  async function deleteCol(colName: string) {
    if (!selected) return;
    if (!confirm(t('semanticLayer.confirm.deleteColumn', { table: selected, column: colName }))) return;
    const r = await api(
      `/api/semantic/annotations/${encodeURIComponent(selected)}/${encodeURIComponent(colName)}`,
      { method: 'DELETE' },
    );
    if (r.ok) await selectTable(selected);
    else setError(r.data?.error || t('semanticLayer.errors.delete'));
  }

  async function autoRegisterOne(table: string) {
    setInfo(t('semanticLayer.messages.registering', { table }));
    const r = await api('/api/semantic/auto-register', {
      method: 'POST', body: JSON.stringify({ tables: [table] }),
    });
    if (r.ok) {
      setInfo(`${table}: ${JSON.stringify(r.data.summary)}`);
      await refreshAll();
    } else setError(r.data?.error || t('semanticLayer.errors.register'));
  }

  async function autoRegisterAll() {
    if (!unregistered.length) { setInfo(t('semanticLayer.messages.allRegistered')); return; }
    if (!confirm(t('semanticLayer.confirm.registerAll', { count: formatNumber(unregistered.length) }))) return;
    setSaving(true); setInfo(t('semanticLayer.messages.registeringAll'));
    const r = await api('/api/semantic/auto-register', { method: 'POST', body: '{}' });
    setSaving(false);
    if (r.ok) {
      const s = r.data.summary || {};
      setInfo(t('semanticLayer.messages.registrationComplete', {
        ok: formatNumber(s.ok || 0),
        skipped: formatNumber(s.skipped || 0),
        failed: formatNumber(s.failed || 0),
      }));
      await refreshAll();
    } else setError(r.data?.error || t('semanticLayer.errors.register'));
  }

  async function runPreview() {
    if (!previewQ.trim()) return;
    setPreviewLoading(true); setError('');
    const r = await api<ResolveResult>('/api/semantic/resolve-preview', {
      method: 'POST', body: JSON.stringify({ question: previewQ.trim() }),
    });
    setPreviewLoading(false);
    if (r.ok) setPreviewRes(r.data);
    else { setError(r.data?.error || t('semanticLayer.errors.preview')); setPreviewRes(null); }
  }

  async function exportJSON() {
    const r = await api('/api/semantic/export');
    if (!r.ok) { setError(r.data?.error || t('semanticLayer.errors.export')); return; }
    const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `semantic_layer_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function importJSON(file: File) {
    try {
      const text = await file.text();
      const body = JSON.parse(text);
      const nSrc = (body.sources || []).length;
      const nAnn = (body.annotations || []).length;
      if (!confirm(t('semanticLayer.confirm.import', { sources: formatNumber(nSrc), annotations: formatNumber(nAnn) }))) return;
      setSaving(true);
      const r = await api('/api/semantic/import', { method: 'POST', body: JSON.stringify(body) });
      setSaving(false);
      if (r.ok) {
        setInfo(t('semanticLayer.messages.importComplete', {
          sourcesOk: formatNumber(r.data.sources_ok || 0),
          sourcesFailed: formatNumber(r.data.sources_failed || 0),
          annotationsOk: formatNumber(r.data.annotations_ok || 0),
          annotationsFailed: formatNumber(r.data.annotations_failed || 0),
        }));
        await refreshAll();
      } else setError(r.data?.error || t('semanticLayer.errors.import'));
    } catch (e) {
      setError(t('semanticLayer.errors.jsonParse', { error: String(e) }));
    }
  }

  const filteredSources = sources.filter(s =>
    !search ||
    s.table_name.toLowerCase().includes(search.toLowerCase()) ||
    (s.display_name || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="semantic-layer-tab">
      {/* Toolbar */}
      <div className="semantic-toolbar">
        <div className="semantic-toolbar-info">
          {t('semanticLayer.toolbar.summary', {
            registered: formatNumber(sources.length),
            unregistered: formatNumber(unregistered.length),
          })}
        </div>
        <input
          type="text" placeholder={t('semanticLayer.toolbar.searchPlaceholder')}
          value={search} onChange={e => setSearch(e.target.value)}
          className="semantic-search"
        />
        {canEdit && (
          <>
            <button className="btn-primary" disabled={saving || !unregistered.length} onClick={autoRegisterAll}>
              {t('semanticLayer.actions.registerAll', { count: formatNumber(unregistered.length) })}
            </button>
            <button className="btn-secondary" onClick={() => fileInputRef.current?.click()}>↑ {t('semanticLayer.actions.import')}</button>
            <input
              ref={fileInputRef} type="file" accept=".json"
              style={{ display: 'none' }}
              onChange={e => e.target.files?.[0] && importJSON(e.target.files[0])}
            />
          </>
        )}
        <button className="btn-secondary" onClick={exportJSON}>↓ {t('semanticLayer.actions.export')}</button>
        <button className="btn-secondary" onClick={refreshAll}>{t('semanticLayer.actions.refresh')}</button>
      </div>

      {error && <div className="semantic-alert error">⚠ {error}</div>}
      {info && <div className="semantic-alert info">{info}</div>}

      <div className="semantic-body">
        {/* Left: table list */}
        <div className="semantic-sources-list">
          <div className="semantic-list-section-title">{t('semanticLayer.list.registered', { count: formatNumber(filteredSources.length) })}</div>
          {loading && <div className="semantic-loading">{t('semanticLayer.common.loading')}</div>}
          {filteredSources.map(s => (
            <div
              key={s.table_name}
              className={`semantic-source-item ${selected === s.table_name ? 'active' : ''}`}
              onClick={() => selectTable(s.table_name)}
            >
              <div className="semantic-source-name">{s.display_name || s.table_name}</div>
              <div className="semantic-source-sub">
                {t('semanticLayer.list.annotationCount', {
                  table: s.table_name,
                  count: formatNumber(s.annotation_count || 0),
                })}
                {s.geometry_type ? ` · ${s.geometry_type}` : ''}
              </div>
            </div>
          ))}

          <div className="semantic-list-section-title" style={{ marginTop: 16 }}>
            <span onClick={() => setShowUnreg(!showUnreg)} style={{ cursor: 'pointer' }}>
              {showUnreg ? '▼' : '▶'} {t('semanticLayer.list.unregistered', { count: formatNumber(unregistered.length) })}
            </span>
          </div>
          {showUnreg && unregistered.map(table => (
            <div key={table} className="semantic-unreg-item">
              <span>{table}</span>
              {canEdit && (
                <button className="btn-mini" onClick={() => autoRegisterOne(table)}>+ {t('semanticLayer.actions.register')}</button>
              )}
            </div>
          ))}
        </div>

        {/* Right: detail panel */}
        <div className="semantic-detail">
          {!selected && (
            <div className="semantic-empty">
              {t('semanticLayer.empty.selectTable')}
              <div className="semantic-hint">
                {t('semanticLayer.empty.hint')}
              </div>
            </div>
          )}

          {selected && detail && (
            <>
              {/* Table-level */}
              <div className="semantic-section">
                <div className="semantic-section-header">
                  <h4>{t('semanticLayer.sections.tableMetadata', { table: selected })}</h4>
                  {canEdit && !editingSrc && (
                    <div>
                      <button className="btn-secondary" onClick={() => setEditingSrc(true)}>{t('semanticLayer.actions.edit')}</button>
                      <button className="btn-danger" onClick={() => deleteSource(selected)}>{t('semanticLayer.actions.delete')}</button>
                    </div>
                  )}
                </div>
                {!editingSrc && detail.source && (
                  <div className="semantic-meta">
                    <div><b>{t('semanticLayer.fields.displayName')}:</b> {detail.source.display_name || <i>{t('semanticLayer.common.notSet')}</i>}</div>
                    <div><b>{t('semanticLayer.fields.description')}:</b> {detail.source.description || <i>{t('semanticLayer.common.notSet')}</i>}</div>
                    <div><b>{t('semanticLayer.fields.synonyms')}:</b> {(detail.source.synonyms || []).join(', ') || <i>{t('semanticLayer.common.none')}</i>}</div>
                    <div><b>{t('semanticLayer.fields.suggestedAnalyses')}:</b> {(detail.source.suggested_analyses || []).join(', ') || <i>{t('semanticLayer.common.none')}</i>}</div>
                    {detail.source.geometry_type && (
                      <div><b>{t('semanticLayer.fields.geometry')}:</b> {detail.source.geometry_type} (SRID={detail.source.srid})</div>
                    )}
                  </div>
                )}
                {editingSrc && (
                  <div className="semantic-form">
                    <label>{t('semanticLayer.fields.displayName')}
                      <input type="text" value={srcForm.display_name}
                        onChange={e => setSrcForm(f => ({ ...f, display_name: e.target.value }))} />
                    </label>
                    <label>{t('semanticLayer.fields.description')}
                      <textarea rows={2} value={srcForm.description}
                        onChange={e => setSrcForm(f => ({ ...f, description: e.target.value }))} />
                    </label>
                    <label>{t('semanticLayer.fields.synonymsComma')}
                      <input type="text" value={srcForm.synonyms}
                        onChange={e => setSrcForm(f => ({ ...f, synonyms: e.target.value }))} />
                    </label>
                    <label>{t('semanticLayer.fields.suggestedAnalysesComma')}
                      <input type="text" value={srcForm.suggested_analyses}
                        onChange={e => setSrcForm(f => ({ ...f, suggested_analyses: e.target.value }))} />
                    </label>
                    <div>
                      <button className="btn-primary" disabled={saving} onClick={saveSource}>
                        {saving ? t('semanticLayer.actions.saving') : t('semanticLayer.actions.save')}
                      </button>
                      <button className="btn-secondary" onClick={() => setEditingSrc(false)}>{t('semanticLayer.actions.cancel')}</button>
                    </div>
                  </div>
                )}
              </div>

              {/* Column-level */}
              <div className="semantic-section">
                <div className="semantic-section-header">
                  <h4>{t('semanticLayer.sections.columnAnnotations', { count: formatNumber((detail.columns || []).length) })}</h4>
                </div>
                <table className="semantic-cols">
                  <thead>
                    <tr>
                      <th>{t('semanticLayer.table.column')}</th><th>{t('semanticLayer.table.dataType')}</th><th>{t('semanticLayer.fields.domain')}</th>
                      <th>{t('semanticLayer.table.aliases')}</th><th>{t('semanticLayer.table.unit')}</th><th>{t('semanticLayer.table.description')}</th>
                      {canEdit && <th>{t('semanticLayer.table.actions')}</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {(detail.columns || []).map(c => {
                      const isEditing = editingCol === c.column_name;
                      return isEditing ? (
                        <tr key={c.column_name} className="semantic-col-editing">
                          <td><b>{c.column_name}</b></td>
                          <td colSpan={canEdit ? 6 : 5}>
                            <div className="semantic-inline-form">
                              <div>
                                <label>{t('semanticLayer.fields.domain')}
                                  <select value={colForm.semantic_domain}
                                    onChange={e => setColForm(f => ({ ...f, semantic_domain: e.target.value }))}>
                                    <option value="">({t('semanticLayer.common.none')})</option>
                                    {domains.map(d => (
                                      <option key={d.name} value={d.name}>{d.name} - {d.description}</option>
                                    ))}
                                  </select>
                                </label>
                                <label>{t('semanticLayer.fields.unit')}
                                  <input type="text" value={colForm.unit}
                                    onChange={e => setColForm(f => ({ ...f, unit: e.target.value }))} />
                                </label>
                              </div>
                              <label>{t('semanticLayer.fields.aliasesComma')}
                                <input type="text" value={colForm.aliases}
                                  onChange={e => setColForm(f => ({ ...f, aliases: e.target.value }))} />
                              </label>
                              <label>{t('semanticLayer.fields.descriptionRules')}
                                <textarea rows={2} value={colForm.description}
                                  onChange={e => setColForm(f => ({ ...f, description: e.target.value }))} />
                              </label>
                              <div>
                                <button className="btn-primary" disabled={saving} onClick={saveCol}>{t('semanticLayer.actions.save')}</button>
                                <button className="btn-secondary" onClick={() => setEditingCol(null)}>{t('semanticLayer.actions.cancel')}</button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        <tr key={c.column_name}>
                          <td><b>{c.column_name}</b>{c.is_geometry && <span className="semantic-geom-badge"> GEOM</span>}</td>
                          <td>{c.data_type || ''}</td>
                          <td>{c.semantic_domain || <i>—</i>}</td>
                          <td>{(c.aliases || []).join(', ') || <i>—</i>}</td>
                          <td>{c.unit || <i>—</i>}</td>
                          <td className="semantic-col-desc">{c.description || <i>—</i>}</td>
                          {canEdit && (
                            <td>
                              <button className="btn-mini" onClick={() => beginEditCol(c)}>{t('semanticLayer.actions.edit')}</button>
                              {c.semantic_domain && (
                                <button className="btn-mini btn-danger" onClick={() => deleteCol(c.column_name)}>{t('semanticLayer.actions.clear')}</button>
                              )}
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Preview panel (always visible, collapsed by default) */}
          <div className="semantic-section">
            <div className="semantic-section-header" onClick={() => setShowPreview(!showPreview)} style={{ cursor: 'pointer' }}>
              <h4>{showPreview ? '▼' : '▶'} {t('semanticLayer.sections.preview')}</h4>
            </div>
            {showPreview && (
              <div className="semantic-preview">
                <div>
                  <input
                    type="text"
                    placeholder={t('semanticLayer.preview.placeholder')}
                    value={previewQ}
                    onChange={e => setPreviewQ(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && runPreview()}
                  />
                  <button className="btn-primary" disabled={previewLoading} onClick={runPreview}>
                    {previewLoading ? t('semanticLayer.actions.resolving') : t('semanticLayer.actions.resolve')}
                  </button>
                </div>
                {previewRes && (
                  <div className="semantic-preview-result">
                    {(previewRes.sources && previewRes.sources.length > 0) && (
                      <div>
                        <b>{t('semanticLayer.preview.matchedTables')}:</b> {previewRes.sources.map((s: any) => s.table_name || s).join(', ')}
                      </div>
                    )}
                    {previewRes.sql_filters && previewRes.sql_filters.length > 0 && (
                      <div>
                        <b>{t('semanticLayer.preview.sqlFilters')}:</b>
                        <pre className="semantic-sql-filters">{previewRes.sql_filters.join('\n')}</pre>
                      </div>
                    )}
                    {previewRes.region_sql && previewRes.region_sql.length > 0 && (
                      <div>
                        <b>{t('semanticLayer.preview.regionFilters')}:</b>
                        <pre>{previewRes.region_sql.join('\n')}</pre>
                      </div>
                    )}
                    {previewRes.hierarchy_matches && previewRes.hierarchy_matches.length > 0 && (
                      <div>
                        <b>{t('semanticLayer.preview.hierarchyMatches')}:</b>
                        <pre>{JSON.stringify(previewRes.hierarchy_matches, null, 2)}</pre>
                      </div>
                    )}
                    <details>
                      <summary>{t('semanticLayer.preview.fullJson')}</summary>
                      <pre>{JSON.stringify(previewRes, null, 2)}</pre>
                    </details>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
