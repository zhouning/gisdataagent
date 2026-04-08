/**
 * KnowledgeManageTab — 知识管理 CRUD（系统管理组）
 *
 * 三个 section：语义等价库、标准规则、数据模型
 * + 知识库 CRUD（创建/删除）
 */

import { useState, useEffect, useCallback } from 'react';
import {
  BookOpen, Layers, FileText, Database, Loader2, AlertCircle,
  Plus, Trash2, ChevronDown, ChevronRight, Search, Box,
} from 'lucide-react';

type Section = 'vocab' | 'standards' | 'kb' | 'models';

interface VocabGroup {
  group_id: string;
  fields: string[];
  field_count: number;
}

interface StandardSummary {
  name: string;
  description: string;
  table_count: number;
  field_count: number;
}

interface KnowledgeBase {
  id: number;
  name: string;
  description?: string;
  document_count?: number;
}

export default function KnowledgeManageTab() {
  const [section, setSection] = useState<Section>('vocab');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Vocab state
  const [vocabGroups, setVocabGroups] = useState<VocabGroup[]>([]);
  const [vocabFilter, setVocabFilter] = useState('');

  // Standards state
  const [standards, setStandards] = useState<StandardSummary[]>([]);
  const [selectedStd, setSelectedStd] = useState<string | null>(null);
  const [stdDetail, setStdDetail] = useState<any>(null);

  // KB state
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [newKbName, setNewKbName] = useState('');
  const [creating, setCreating] = useState(false);

  // Load data when section changes
  useEffect(() => {
    setError(null);
    if (section === 'vocab' && vocabGroups.length === 0) loadVocab();
    if (section === 'standards' && standards.length === 0) loadStandards();
    if (section === 'kb' && kbs.length === 0) loadKbs();
  }, [section]);

  const loadVocab = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/knowledge/vocab', { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setVocabGroups(data.groups ?? []);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadStandards = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/knowledge/standards', { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStandards(data.standards ?? []);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadKbs = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/kb', { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setKbs(data.knowledge_bases ?? []);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleSelectStd = useCallback(async (name: string) => {
    if (selectedStd === name) { setSelectedStd(null); return; }
    setSelectedStd(name);
    try {
      const res = await fetch(`/api/knowledge/standards/${encodeURIComponent(name)}`, { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStdDetail(await res.json());
    } catch (e: any) { setError(e.message); }
  }, [selectedStd]);

  const handleCreateKb = useCallback(async () => {
    if (!newKbName.trim()) return;
    setCreating(true);
    try {
      const res = await fetch('/api/kb', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newKbName.trim() }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setNewKbName('');
      loadKbs();
    } catch (e: any) { setError(e.message); }
    finally { setCreating(false); }
  }, [newKbName]);

  const handleDeleteKb = useCallback(async (id: number) => {
    try {
      const res = await fetch(`/api/kb/${id}`, { method: 'DELETE', credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setKbs(prev => prev.filter(k => k.id !== id));
    } catch (e: any) { setError(e.message); }
  }, []);

  const sections: { key: Section; label: string; icon: any }[] = [
    { key: 'vocab', label: '语义词表', icon: <Layers size={14} /> },
    { key: 'standards', label: '标准规则', icon: <FileText size={14} /> },
    { key: 'kb', label: '知识库', icon: <Database size={14} /> },
    { key: 'models', label: '数据模型', icon: <Box size={14} /> },
  ];

  const filteredGroups = vocabFilter
    ? vocabGroups.filter(g =>
        g.group_id.toLowerCase().includes(vocabFilter.toLowerCase()) ||
        g.fields.some(f => f.toLowerCase().includes(vocabFilter.toLowerCase()))
      )
    : vocabGroups;

  return (
    <div className="km-tab">
      <div className="km-tab__nav">
        {sections.map(s => (
          <button
            key={s.key}
            className={`km-nav-btn ${section === s.key ? 'active' : ''}`}
            onClick={() => setSection(s.key)}
          >
            {s.icon} {s.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="tab-error"><AlertCircle size={14} /> {error}</div>
      )}

      <div className="km-tab__content">
        {loading && <div className="tab-loading"><Loader2 size={20} className="spin" /> 加载中...</div>}

        {/* Vocab section */}
        {!loading && section === 'vocab' && (
          <>
            <div className="km-search">
              <Search size={14} />
              <input placeholder="过滤等价组或字段..." value={vocabFilter}
                onChange={e => setVocabFilter(e.target.value)} />
            </div>
            <div className="km-vocab-list">
              {filteredGroups.map(g => (
                <div key={g.group_id} className="vocab-group">
                  <div className="vocab-group__id">{g.group_id}</div>
                  <div className="vocab-group__fields">
                    {g.fields.map(f => <span key={f} className="field-tag">{f}</span>)}
                  </div>
                </div>
              ))}
              {filteredGroups.length === 0 && <div className="tab-empty">无匹配结果</div>}
            </div>
          </>
        )}

        {/* Standards section */}
        {!loading && section === 'standards' && (
          <div className="km-standards-list">
            {standards.length === 0 ? (
              <div className="tab-empty">暂无已加载标准</div>
            ) : standards.map(s => (
              <div key={s.name} className="std-card">
                <div className="std-card__header" onClick={() => handleSelectStd(s.name)}>
                  <ChevronRight size={14} className={selectedStd === s.name ? 'rotated' : ''} />
                  <span className="std-card__name">{s.name}</span>
                  <span className="std-card__meta">{s.table_count} 表 / {s.field_count} 字段</span>
                </div>
                {selectedStd === s.name && stdDetail && (
                  <div className="std-card__detail">
                    {(stdDetail.tables ?? []).map((t: any) => (
                      <div key={t.属性表名 ?? t.table_name} className="std-table">
                        <strong>{t.中文名 ?? t.table_label} ({t.属性表名 ?? t.table_name})</strong>
                        <span className="std-table__count">{(t.字段 ?? t.fields ?? []).length} 字段</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* KB section */}
        {!loading && section === 'kb' && (
          <>
            <div className="km-kb-create">
              <input placeholder="新知识库名称" value={newKbName}
                onChange={e => setNewKbName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleCreateKb()} />
              <button onClick={handleCreateKb} disabled={creating || !newKbName.trim()}>
                <Plus size={14} /> 创建
              </button>
            </div>
            <div className="km-kb-list">
              {kbs.map(kb => (
                <div key={kb.id} className="kb-manage-card">
                  <BookOpen size={14} />
                  <span className="kb-manage-card__name">{kb.name}</span>
                  <span className="kb-manage-card__count">{kb.document_count ?? 0} 文档</span>
                  <button className="btn-icon danger" onClick={() => handleDeleteKb(kb.id)}
                    title="删除知识库">
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
              {kbs.length === 0 && <div className="tab-empty">暂无知识库</div>}
            </div>
          </>
        )}

        {/* Models section */}
        {!loading && section === 'models' && (
          <div className="tab-empty">
            <Box size={32} strokeWidth={1} />
            <p>上传 EA XMI 文件以导入数据模型（开发中）</p>
          </div>
        )}
      </div>
    </div>
  );
}
