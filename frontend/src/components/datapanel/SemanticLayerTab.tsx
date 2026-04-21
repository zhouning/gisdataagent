import { useState, useEffect, useRef } from 'react';

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
      const resp = await fetch(path, {
        credentials: 'include',
        headers: opts.body ? { 'Content-Type': 'application/json', ...(opts.headers || {}) } : (opts.headers || {}),
        ...opts,
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
    else setError(r.data?.error || '保存失败');
  }

  async function deleteSource(name: string) {
    if (!confirm(`确定删除 ${name} 的所有语义标注？此操作不可逆。`)) return;
    const r = await api(`/api/semantic/sources/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (r.ok) {
      setSelected(null); setDetail(null);
      setInfo(`已删除 ${name}`);
      await refreshAll();
    } else setError(r.data?.error || '删除失败');
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
    else setError(r.data?.error || '保存失败');
  }

  async function deleteCol(colName: string) {
    if (!selected) return;
    if (!confirm(`删除 ${selected}.${colName} 的语义标注？`)) return;
    const r = await api(
      `/api/semantic/annotations/${encodeURIComponent(selected)}/${encodeURIComponent(colName)}`,
      { method: 'DELETE' },
    );
    if (r.ok) await selectTable(selected);
    else setError(r.data?.error || '删除失败');
  }

  async function autoRegisterOne(table: string) {
    setInfo(`正在注册 ${table}...`);
    const r = await api('/api/semantic/auto-register', {
      method: 'POST', body: JSON.stringify({ tables: [table] }),
    });
    if (r.ok) {
      setInfo(`${table}: ${JSON.stringify(r.data.summary)}`);
      await refreshAll();
    } else setError(r.data?.error || '注册失败');
  }

  async function autoRegisterAll() {
    if (!unregistered.length) { setInfo('所有表都已注册'); return; }
    if (!confirm(`将自动注册 ${unregistered.length} 张未注册表。继续？`)) return;
    setSaving(true); setInfo('正在批量注册...');
    const r = await api('/api/semantic/auto-register', { method: 'POST', body: '{}' });
    setSaving(false);
    if (r.ok) {
      const s = r.data.summary || {};
      setInfo(`注册完成: ${s.ok} 成功 / ${s.skipped} 跳过 / ${s.failed} 失败`);
      await refreshAll();
    } else setError(r.data?.error || '注册失败');
  }

  async function runPreview() {
    if (!previewQ.trim()) return;
    setPreviewLoading(true); setError('');
    const r = await api<ResolveResult>('/api/semantic/resolve-preview', {
      method: 'POST', body: JSON.stringify({ question: previewQ.trim() }),
    });
    setPreviewLoading(false);
    if (r.ok) setPreviewRes(r.data);
    else { setError(r.data?.error || '预览失败'); setPreviewRes(null); }
  }

  async function exportJSON() {
    const r = await api('/api/semantic/export');
    if (!r.ok) { setError(r.data?.error || '导出失败'); return; }
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
      if (!confirm(`将导入 ${nSrc} 张表的元数据 + ${nAnn} 条列标注。继续？`)) return;
      setSaving(true);
      const r = await api('/api/semantic/import', { method: 'POST', body: JSON.stringify(body) });
      setSaving(false);
      if (r.ok) {
        setInfo(`导入成功: 表 ${r.data.sources_ok}OK/${r.data.sources_failed}FAIL, 列 ${r.data.annotations_ok}OK/${r.data.annotations_failed}FAIL`);
        await refreshAll();
      } else setError(r.data?.error || '导入失败');
    } catch (e) {
      setError('JSON 解析失败: ' + String(e));
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
          已注册 <b>{sources.length}</b> 表 · 未注册 <b>{unregistered.length}</b>
        </div>
        <input
          type="text" placeholder="搜索表名 / 显示名"
          value={search} onChange={e => setSearch(e.target.value)}
          className="semantic-search"
        />
        {canEdit && (
          <>
            <button className="btn-primary" disabled={saving || !unregistered.length} onClick={autoRegisterAll}>
              一键自动注册 ({unregistered.length})
            </button>
            <button className="btn-secondary" onClick={() => fileInputRef.current?.click()}>↑ 导入</button>
            <input
              ref={fileInputRef} type="file" accept=".json"
              style={{ display: 'none' }}
              onChange={e => e.target.files?.[0] && importJSON(e.target.files[0])}
            />
          </>
        )}
        <button className="btn-secondary" onClick={exportJSON}>↓ 导出</button>
        <button className="btn-secondary" onClick={refreshAll}>刷新</button>
      </div>

      {error && <div className="semantic-alert error">⚠ {error}</div>}
      {info && <div className="semantic-alert info">{info}</div>}

      <div className="semantic-body">
        {/* Left: table list */}
        <div className="semantic-sources-list">
          <div className="semantic-list-section-title">已注册 ({filteredSources.length})</div>
          {loading && <div className="semantic-loading">加载中...</div>}
          {filteredSources.map(s => (
            <div
              key={s.table_name}
              className={`semantic-source-item ${selected === s.table_name ? 'active' : ''}`}
              onClick={() => selectTable(s.table_name)}
            >
              <div className="semantic-source-name">{s.display_name || s.table_name}</div>
              <div className="semantic-source-sub">
                {s.table_name} · {s.annotation_count || 0} 列标注
                {s.geometry_type ? ` · ${s.geometry_type}` : ''}
              </div>
            </div>
          ))}

          <div className="semantic-list-section-title" style={{ marginTop: 16 }}>
            <span onClick={() => setShowUnreg(!showUnreg)} style={{ cursor: 'pointer' }}>
              {showUnreg ? '▼' : '▶'} 未注册 ({unregistered.length})
            </span>
          </div>
          {showUnreg && unregistered.map(t => (
            <div key={t} className="semantic-unreg-item">
              <span>{t}</span>
              {canEdit && (
                <button className="btn-mini" onClick={() => autoRegisterOne(t)}>+ 注册</button>
              )}
            </div>
          ))}
        </div>

        {/* Right: detail panel */}
        <div className="semantic-detail">
          {!selected && (
            <div className="semantic-empty">
              ← 从左侧选择一张表以查看 / 编辑其语义标注
              <div className="semantic-hint">
                语义层给 NL2SQL 提供列别名、单位、分类层级等领域知识。完善标注可显著提升 Agent 的 SQL 生成准确率（实测 +20%）。
              </div>
            </div>
          )}

          {selected && detail && (
            <>
              {/* Table-level */}
              <div className="semantic-section">
                <div className="semantic-section-header">
                  <h4>表级元数据: {selected}</h4>
                  {canEdit && !editingSrc && (
                    <div>
                      <button className="btn-secondary" onClick={() => setEditingSrc(true)}>编辑</button>
                      <button className="btn-danger" onClick={() => deleteSource(selected)}>删除</button>
                    </div>
                  )}
                </div>
                {!editingSrc && detail.source && (
                  <div className="semantic-meta">
                    <div><b>显示名:</b> {detail.source.display_name || <i>未设置</i>}</div>
                    <div><b>描述:</b> {detail.source.description || <i>未设置</i>}</div>
                    <div><b>同义词:</b> {(detail.source.synonyms || []).join(', ') || <i>无</i>}</div>
                    <div><b>建议分析:</b> {(detail.source.suggested_analyses || []).join(', ') || <i>无</i>}</div>
                    {detail.source.geometry_type && (
                      <div><b>几何:</b> {detail.source.geometry_type} (SRID={detail.source.srid})</div>
                    )}
                  </div>
                )}
                {editingSrc && (
                  <div className="semantic-form">
                    <label>显示名
                      <input type="text" value={srcForm.display_name}
                        onChange={e => setSrcForm(f => ({ ...f, display_name: e.target.value }))} />
                    </label>
                    <label>描述
                      <textarea rows={2} value={srcForm.description}
                        onChange={e => setSrcForm(f => ({ ...f, description: e.target.value }))} />
                    </label>
                    <label>同义词（逗号分隔）
                      <input type="text" value={srcForm.synonyms}
                        onChange={e => setSrcForm(f => ({ ...f, synonyms: e.target.value }))} />
                    </label>
                    <label>建议分析（逗号分隔）
                      <input type="text" value={srcForm.suggested_analyses}
                        onChange={e => setSrcForm(f => ({ ...f, suggested_analyses: e.target.value }))} />
                    </label>
                    <div>
                      <button className="btn-primary" disabled={saving} onClick={saveSource}>
                        {saving ? '保存中...' : '保存'}
                      </button>
                      <button className="btn-secondary" onClick={() => setEditingSrc(false)}>取消</button>
                    </div>
                  </div>
                )}
              </div>

              {/* Column-level */}
              <div className="semantic-section">
                <div className="semantic-section-header">
                  <h4>列标注 ({(detail.columns || []).length} 列)</h4>
                </div>
                <table className="semantic-cols">
                  <thead>
                    <tr>
                      <th>列名</th><th>数据类型</th><th>Domain</th>
                      <th>别名</th><th>单位</th><th>描述</th>
                      {canEdit && <th>操作</th>}
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
                                <label>Domain
                                  <select value={colForm.semantic_domain}
                                    onChange={e => setColForm(f => ({ ...f, semantic_domain: e.target.value }))}>
                                    <option value="">(无)</option>
                                    {domains.map(d => (
                                      <option key={d.name} value={d.name}>{d.name} - {d.description}</option>
                                    ))}
                                  </select>
                                </label>
                                <label>单位
                                  <input type="text" value={colForm.unit}
                                    onChange={e => setColForm(f => ({ ...f, unit: e.target.value }))} />
                                </label>
                              </div>
                              <label>别名（逗号分隔）
                                <input type="text" value={colForm.aliases}
                                  onChange={e => setColForm(f => ({ ...f, aliases: e.target.value }))} />
                              </label>
                              <label>描述 / 使用规则
                                <textarea rows={2} value={colForm.description}
                                  onChange={e => setColForm(f => ({ ...f, description: e.target.value }))} />
                              </label>
                              <div>
                                <button className="btn-primary" disabled={saving} onClick={saveCol}>保存</button>
                                <button className="btn-secondary" onClick={() => setEditingCol(null)}>取消</button>
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
                              <button className="btn-mini" onClick={() => beginEditCol(c)}>编辑</button>
                              {c.semantic_domain && (
                                <button className="btn-mini btn-danger" onClick={() => deleteCol(c.column_name)}>清除</button>
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
              <h4>{showPreview ? '▼' : '▶'} 语义解析预览</h4>
            </div>
            {showPreview && (
              <div className="semantic-preview">
                <div>
                  <input
                    type="text"
                    placeholder="输入自然语言问题，如：统计水田的真实面积（公顷）"
                    value={previewQ}
                    onChange={e => setPreviewQ(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && runPreview()}
                  />
                  <button className="btn-primary" disabled={previewLoading} onClick={runPreview}>
                    {previewLoading ? '解析中...' : '解析'}
                  </button>
                </div>
                {previewRes && (
                  <div className="semantic-preview-result">
                    {(previewRes.sources && previewRes.sources.length > 0) && (
                      <div>
                        <b>匹配的表:</b> {previewRes.sources.map((s: any) => s.table_name || s).join(', ')}
                      </div>
                    )}
                    {previewRes.sql_filters && previewRes.sql_filters.length > 0 && (
                      <div>
                        <b>SQL 过滤提示:</b>
                        <pre className="semantic-sql-filters">{previewRes.sql_filters.join('\n')}</pre>
                      </div>
                    )}
                    {previewRes.region_sql && previewRes.region_sql.length > 0 && (
                      <div>
                        <b>区域过滤:</b>
                        <pre>{previewRes.region_sql.join('\n')}</pre>
                      </div>
                    )}
                    {previewRes.hierarchy_matches && previewRes.hierarchy_matches.length > 0 && (
                      <div>
                        <b>层级匹配:</b>
                        <pre>{JSON.stringify(previewRes.hierarchy_matches, null, 2)}</pre>
                      </div>
                    )}
                    <details>
                      <summary>完整 JSON</summary>
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
