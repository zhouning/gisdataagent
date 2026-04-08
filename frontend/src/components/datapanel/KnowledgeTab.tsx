/**
 * KnowledgeTab — 知识库浏览（治理操作组）
 *
 * 功能：列出用户知识库、语义搜索、查看文档列表
 */

import { useState, useEffect, useCallback } from 'react';
import {
  BookOpen, Search, FileText, Loader2, AlertCircle,
  ChevronRight, Database, Hash,
} from 'lucide-react';

interface KnowledgeBase {
  id: number;
  name: string;
  description?: string;
  document_count?: number;
  is_shared?: boolean;
}

interface KBDocument {
  id: number;
  filename: string;
  doc_type?: string;
  created_at?: string;
}

interface SearchResult {
  kb_id: number;
  kb_name: string;
  document: string;
  chunk: string;
  score: number;
}

export default function KnowledgeTab() {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedKb, setSelectedKb] = useState<number | null>(null);
  const [docs, setDocs] = useState<KBDocument[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  // Load knowledge bases on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/kb', { credentials: 'include' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setKbs(data.knowledge_bases ?? []);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSelectKb = useCallback(async (id: number) => {
    if (selectedKb === id) { setSelectedKb(null); return; }
    setSelectedKb(id);
    try {
      const res = await fetch(`/api/kb/${id}`, { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setDocs(data.documents ?? []);
    } catch (e: any) {
      setError(e.message);
    }
  }, [selectedKb]);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const res = await fetch('/api/kb/search', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery, top_k: 5 }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSearchResults(data.results ?? []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSearching(false);
    }
  }, [searchQuery]);

  return (
    <div className="knowledge-tab">
      {error && (
        <div className="tab-error">
          <AlertCircle size={14} /> {error}
        </div>
      )}
      <div className="knowledge-tab__search">
        <Search size={14} />
        <input
          type="text"
          placeholder="语义搜索知识库..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
        />
        <button onClick={handleSearch} disabled={searching || !searchQuery.trim()}>
          {searching ? <Loader2 size={14} className="spin" /> : '搜索'}
        </button>
      </div>

      {searchResults.length > 0 && (
        <div className="knowledge-tab__results">
          <h4>搜索结果</h4>
          {searchResults.map((r, i) => (
            <div key={i} className="search-result-card">
              <div className="search-result-card__header">
                <span className="kb-name">{r.kb_name}</span>
                <span className="doc-name">{r.document}</span>
                <span className="score">{(r.score * 100).toFixed(0)}%</span>
              </div>
              <p className="search-result-card__chunk">{r.chunk}</p>
            </div>
          ))}
        </div>
      )}

      <div className="knowledge-tab__list">
        <h4><Database size={14} /> 知识库 ({kbs.length})</h4>
        {loading ? (
          <div className="tab-loading"><Loader2 size={20} className="spin" /> 加载中...</div>
        ) : kbs.length === 0 ? (
          <div className="tab-empty">暂无知识库，请在"知识管理"中创建</div>
        ) : (
          kbs.map(kb => (
            <div key={kb.id} className="kb-card">
              <div
                className={`kb-card__header ${selectedKb === kb.id ? 'active' : ''}`}
                onClick={() => handleSelectKb(kb.id)}
              >
                <ChevronRight size={14} className={selectedKb === kb.id ? 'rotated' : ''} />
                <BookOpen size={14} />
                <span className="kb-card__name">{kb.name}</span>
                {kb.is_shared && <span className="badge shared">共享</span>}
                <span className="kb-card__count">
                  <Hash size={12} />{kb.document_count ?? 0} 文档
                </span>
              </div>
              {kb.description && <p className="kb-card__desc">{kb.description}</p>}
              {selectedKb === kb.id && (
                <div className="kb-card__docs">
                  {docs.length === 0 ? (
                    <div className="tab-empty">暂无文档</div>
                  ) : docs.map(doc => (
                    <div key={doc.id} className="doc-item">
                      <FileText size={12} />
                      <span>{doc.filename}</span>
                      <span className="doc-type">{doc.doc_type ?? ''}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}