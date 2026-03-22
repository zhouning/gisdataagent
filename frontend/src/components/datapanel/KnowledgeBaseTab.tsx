import { useState, useEffect } from 'react';

/* ============================================================
   Knowledge Base Tab
   ============================================================ */

interface KBItem {
  id: number; name: string; description: string;
  owner_username: string; is_shared: boolean;
  doc_count: number; chunk_count: number;
  created_at: string;
}

interface KBDoc {
  id: number; filename: string; content_type: string;
  chunk_count: number; created_at: string;
}

export default function KnowledgeBaseTab() {
  const [kbs, setKbs] = useState<KBItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKb, setSelectedKb] = useState<(KBItem & { documents?: KBDoc[] }) | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createDesc, setCreateDesc] = useState('');
  const [createShared, setCreateShared] = useState(false);
  const [createError, setCreateError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [docText, setDocText] = useState('');
  const [docName, setDocName] = useState('');

  const fetchKbs = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/kb', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setKbs(data.knowledge_bases || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchKbs(); }, []);

  const handleCreate = async () => {
    setCreateError('');
    if (!createName.trim()) { setCreateError('名称必填'); return; }
    try {
      const resp = await fetch('/api/kb', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: createName.trim(), description: createDesc.trim(), is_shared: createShared }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowCreateForm(false);
        setCreateName(''); setCreateDesc(''); setCreateShared(false);
        fetchKbs();
      } else { setCreateError(data.error || '创建失败'); }
    } catch { setCreateError('网络错误'); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此知识库及所有文档？')) return;
    try {
      const resp = await fetch(`/api/kb/${id}`, { method: 'DELETE', credentials: 'include' });
      if (resp.ok) { setSelectedKb(null); fetchKbs(); }
    } catch { /* ignore */ }
  };

  const handleSelectKb = async (kb: KBItem) => {
    try {
      const resp = await fetch(`/api/kb/${kb.id}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setSelectedKb(data);
      }
    } catch { /* ignore */ }
  };

  const handleAddDoc = async () => {
    if (!selectedKb || !docText.trim()) return;
    try {
      const resp = await fetch(`/api/kb/${selectedKb.id}/documents`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: docText.trim(), filename: docName.trim() || 'document.txt' }),
      });
      if (resp.ok) {
        setDocText(''); setDocName('');
        handleSelectKb(selectedKb);
      }
    } catch { /* ignore */ }
  };

  const handleDeleteDoc = async (docId: number) => {
    if (!selectedKb) return;
    try {
      const resp = await fetch(`/api/kb/${selectedKb.id}/documents/${docId}`, { method: 'DELETE', credentials: 'include' });
      if (resp.ok) handleSelectKb(selectedKb);
    } catch { /* ignore */ }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const resp = await fetch('/api/kb/search', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery.trim(), top_k: 5 }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSearchResults(data.results || []);
      }
    } catch { /* ignore */ }
    finally { setSearching(false); }
  };

  // Detail view for a selected KB
  if (selectedKb) {
    return (
      <div className="kb-view">
        <div className="kb-detail-header">
          <button className="btn-secondary btn-sm" onClick={() => setSelectedKb(null)}>← 返回</button>
          <span className="kb-detail-name">{selectedKb.name}</span>
          <button className="cap-delete-btn" onClick={() => handleDelete(selectedKb.id)}>删除</button>
        </div>
        {selectedKb.description && <div className="kb-detail-desc">{selectedKb.description}</div>}

        <div className="skill-section-label">文档 ({(selectedKb.documents || []).length})</div>
        <div className="kb-doc-list">
          {(selectedKb.documents || []).map(doc => (
            <div key={doc.id} className="kb-doc-item">
              <span className="kb-doc-name">{doc.filename}</span>
              <span className="kb-doc-meta">{doc.chunk_count} 块</span>
              <button className="param-remove-btn" onClick={() => handleDeleteDoc(doc.id)}>×</button>
            </div>
          ))}
        </div>

        <div className="skill-section-label">添加文档</div>
        <input placeholder="文件名 (如: 政策文件.txt)" value={docName}
          onChange={e => setDocName(e.target.value)} className="capabilities-search" style={{ margin: '0 0 4px' }} />
        <textarea placeholder="粘贴文档内容..." rows={3} value={docText}
          onChange={e => setDocText(e.target.value)}
          className="tool-config-editor" style={{ margin: '0 0 6px', fontSize: '12px' }} />
        <button className="btn-primary btn-sm" onClick={handleAddDoc} disabled={!docText.trim()}>添加文档</button>

        {/* ── Knowledge Graph Section (GraphRAG v10.0.5) ── */}
        <GraphRAGSection kbId={selectedKb.id} />
      </div>
    );
  }

  return (
    <div className="kb-view">
      <div className="capabilities-summary">
        <span>{kbs.length} 个知识库</span>
        <button className="btn-add-server" onClick={() => setShowCreateForm(!showCreateForm)} title="新建知识库">+</button>
      </div>

      {showCreateForm && (
        <div className="skill-add-form">
          <div className="skill-add-form-title">新建知识库</div>
          <input placeholder="知识库名称 (必填)" value={createName}
            onChange={e => setCreateName(e.target.value)} />
          <input placeholder="描述 (可选)" value={createDesc}
            onChange={e => setCreateDesc(e.target.value)} />
          <label className="skill-checkbox">
            <input type="checkbox" checked={createShared}
              onChange={e => setCreateShared(e.target.checked)} />
            共享给其他用户
          </label>
          {createError && <div className="skill-add-error">{createError}</div>}
          <div className="skill-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => setShowCreateForm(false)}>取消</button>
            <button className="btn-primary btn-sm" onClick={handleCreate}>创建</button>
          </div>
        </div>
      )}

      <div className="kb-search-bar">
        <input className="capabilities-search" placeholder="语义搜索所有知识库..." value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()} />
        <button className="btn-primary btn-sm" onClick={handleSearch} disabled={searching}>
          {searching ? '搜索中...' : '搜索'}
        </button>
      </div>

      {searchResults.length > 0 && (
        <div className="kb-search-results">
          <div className="skill-section-label">搜索结果 ({searchResults.length})</div>
          {searchResults.map((r: any, i: number) => (
            <div key={i} className="kb-search-result-item">
              <div className="kb-result-score">相似度 {(r.score * 100).toFixed(0)}%</div>
              <div className="kb-result-text">{(r.text || r.chunk_text || '').slice(0, 200)}</div>
              <div className="kb-result-meta">{r.kb_name} / {r.filename}</div>
            </div>
          ))}
        </div>
      )}

      {loading && kbs.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : kbs.length === 0 ? (
        <div className="empty-state">暂无知识库，点击 + 创建</div>
      ) : (
        <div className="capabilities-list">
          {kbs.map(kb => (
            <div key={kb.id} className="capability-card" onClick={() => handleSelectKb(kb)} style={{ cursor: 'pointer' }}>
              <div className="cap-card-header">
                <span className="cap-card-name">{kb.name}</span>
                <span className="cap-badge cap-type-builtin">{kb.doc_count || 0} 文档</span>
                <span className="cap-badge cap-domain">{kb.chunk_count || 0} 块</span>
              </div>
              {kb.description && <div className="cap-card-desc">{kb.description}</div>}
              <div className="cap-card-footer">
                <span className="cap-owner">by {kb.owner_username}</span>
                {kb.is_shared && <span className="cap-badge cap-shared">共享</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function GraphRAGSection({ kbId }: { kbId: number }) {
  const [building, setBuilding] = useState(false);
  const [graph, setGraph] = useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [entities, setEntities] = useState<any[]>([]);
  const [graphSearch, setGraphSearch] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [tab, setTab] = useState<'entities' | 'graph'>('entities');

  const fetchGraph = async () => {
    try {
      const [gResp, eResp] = await Promise.all([
        fetch(`/api/kb/${kbId}/graph`, { credentials: 'include' }),
        fetch(`/api/kb/${kbId}/entities`, { credentials: 'include' }),
      ]);
      if (gResp.ok) {
        const g = await gResp.json();
        setGraph(g);
      }
      if (eResp.ok) {
        const e = await eResp.json();
        setEntities(e.entities || []);
      }
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchGraph(); }, [kbId]);

  const handleBuild = async () => {
    setBuilding(true);
    try {
      await fetch(`/api/kb/${kbId}/build-graph`, { method: 'POST', credentials: 'include' });
      await fetchGraph();
    } catch { /* ignore */ }
    finally { setBuilding(false); }
  };

  const handleGraphSearch = async () => {
    if (!graphSearch.trim()) return;
    setSearching(true);
    try {
      const resp = await fetch(`/api/kb/${kbId}/graph-search`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: graphSearch.trim() }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSearchResults(data.results || []);
      }
    } catch { /* ignore */ }
    finally { setSearching(false); }
  };

  const nodeCount = graph?.nodes?.length || 0;
  const edgeCount = graph?.edges?.length || 0;

  return (
    <div style={{ marginTop: 12 }}>
      <div className="skill-section-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>知识图谱 ({nodeCount} 实体, {edgeCount} 关系)</span>
        <button className="btn-primary btn-sm" onClick={handleBuild} disabled={building}>
          {building ? '构建中...' : nodeCount > 0 ? '重新构建' : '构建图谱'}
        </button>
      </div>

      {nodeCount > 0 && (
        <>
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            <button className={`cap-filter-btn ${tab === 'entities' ? 'active' : ''}`} onClick={() => setTab('entities')}>实体列表</button>
            <button className={`cap-filter-btn ${tab === 'graph' ? 'active' : ''}`} onClick={() => setTab('graph')}>图谱搜索</button>
          </div>

          {tab === 'entities' && (
            <div style={{ maxHeight: 200, overflow: 'auto' }}>
              {entities.map((ent, i) => (
                <div key={i} style={{ padding: '4px 8px', borderBottom: '1px solid #f0f0f0', fontSize: 12 }}>
                  <span style={{ fontWeight: 500 }}>{ent.name || ent.entity}</span>
                  {ent.type && <span style={{ marginLeft: 6, color: '#6b7280', fontSize: 11 }}>[{ent.type}]</span>}
                  {ent.description && <div style={{ color: '#9ca3af', fontSize: 11 }}>{ent.description}</div>}
                </div>
              ))}
              {entities.length === 0 && <div style={{ color: '#9ca3af', fontSize: 12, padding: 8 }}>暂无实体</div>}
            </div>
          )}

          {tab === 'graph' && (
            <div>
              <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
                <input className="capabilities-search" placeholder="搜索图谱实体或关系..."
                  value={graphSearch} onChange={e => setGraphSearch(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleGraphSearch()}
                  style={{ margin: 0, flex: 1 }} />
                <button className="btn-primary btn-sm" onClick={handleGraphSearch} disabled={searching}>
                  {searching ? '...' : '搜索'}
                </button>
              </div>
              {searchResults.length > 0 && (
                <div style={{ maxHeight: 200, overflow: 'auto' }}>
                  {searchResults.map((r, i) => (
                    <div key={i} style={{ padding: '4px 8px', borderBottom: '1px solid #f0f0f0', fontSize: 12 }}>
                      <div style={{ fontWeight: 500 }}>{r.source} → <span style={{ color: '#6b7280' }}>{r.relation}</span> → {r.target}</div>
                      {r.context && <div style={{ color: '#9ca3af', fontSize: 11 }}>{r.context}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {nodeCount === 0 && !building && (
        <div style={{ textAlign: 'center', color: '#9ca3af', padding: 12, fontSize: 12 }}>
          点击"构建图谱"从文档中提取实体和关系
        </div>
      )}
    </div>
  );
}
