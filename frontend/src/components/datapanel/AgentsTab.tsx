import { useState, useEffect, useMemo, useCallback } from 'react';
import { Search, Pin, EyeOff, Eye } from 'lucide-react';

interface MentionTarget {
  handle: string;
  label: string;
  display_name: string;
  aliases: string[];
  pinned: boolean;
  hidden: boolean;
  type: 'pipeline' | 'sub_agent' | 'adk_skill' | 'custom_skill';
  description: string;
  allowed: boolean;
  pipeline?: string;
}

type FilterKey = 'all' | 'pipeline' | 'sub_agent' | 'adk_skill' | 'custom_skill';

const TYPE_LABELS: Record<string, string> = {
  pipeline: '流水线',
  sub_agent: '子智能体',
  adk_skill: '内置技能',
  custom_skill: '自定义技能',
};

const TYPE_COLORS: Record<string, string> = {
  pipeline: '#3b82f6',
  sub_agent: '#10b981',
  adk_skill: '#f59e0b',
  custom_skill: '#a855f7',
};

export default function AgentsTab() {
  const [targets, setTargets] = useState<MentionTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchTargets = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/agents/mention-targets?include_hidden=1', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setTargets(data.targets || []);
      }
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchTargets(); }, [fetchTargets]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return targets.filter(t => {
      if (filter !== 'all' && t.type !== filter) return false;
      if (!q) return true;
      if (t.handle.toLowerCase().includes(q)) return true;
      if (t.display_name.toLowerCase().includes(q)) return true;
      if (t.aliases.some(a => a.toLowerCase().includes(q))) return true;
      return false;
    });
  }, [targets, filter, search]);

  if (loading) return <div className="empty-state">加载中...</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 12 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={14} style={{ position: 'absolute', left: 8, top: 8, color: '#9ca3af' }} />
          <input
            type="text" placeholder="搜索 handle / 显示名 / 别名"
            value={search} onChange={e => setSearch(e.target.value)}
            style={{
              width: '100%', padding: '6px 8px 6px 28px', fontSize: 12,
              border: '1px solid #e5e7eb', borderRadius: 4,
            }}
          />
        </div>
        <span style={{ fontSize: 11, color: '#9ca3af' }}>
          {filtered.length} / {targets.length}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {(['all', 'pipeline', 'sub_agent', 'adk_skill', 'custom_skill'] as FilterKey[]).map(k => (
          <button key={k} onClick={() => setFilter(k)}
            style={{
              padding: '3px 10px', fontSize: 11, border: '1px solid #e5e7eb',
              borderRadius: 12, cursor: 'pointer',
              background: filter === k ? '#3b82f6' : '#fff',
              color: filter === k ? '#fff' : '#374151',
            }}>
            {k === 'all' ? '全部' : TYPE_LABELS[k]}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.map(t => (
          <AgentCard
            key={t.handle} target={t}
            expanded={expanded === t.handle}
            onToggle={() => setExpanded(expanded === t.handle ? null : t.handle)}
            onChanged={fetchTargets}
          />
        ))}
        {filtered.length === 0 && (
          <div className="empty-state" style={{ padding: 24 }}>无匹配项</div>
        )}
      </div>
    </div>
  );
}

interface AgentCardProps {
  target: MentionTarget;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}

function AgentCard({ target, expanded, onToggle, onChanged }: AgentCardProps) {
  const [aliasInput, setAliasInput] = useState(target.aliases.join(', '));
  const [displayName, setDisplayName] = useState(target.display_name);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const aliases = aliasInput.split(',').map(a => a.trim()).filter(Boolean);
      await fetch(`/api/agents/${encodeURIComponent(target.handle)}/alias`, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ aliases, display_name: displayName }),
      });
      onChanged();
    } finally { setSaving(false); }
  };

  const togglePin = async () => {
    await fetch(`/api/agents/${encodeURIComponent(target.handle)}/pin`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pinned: !target.pinned }),
    });
    onChanged();
  };

  const toggleHide = async () => {
    await fetch(`/api/agents/${encodeURIComponent(target.handle)}/hide`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hidden: !target.hidden }),
    });
    onChanged();
  };

  const color = TYPE_COLORS[target.type] || '#6b7280';

  return (
    <div style={{
      border: '1px solid #e5e7eb', borderRadius: 6, marginBottom: 8,
      background: target.hidden ? '#f9fafb' : '#fff',
      opacity: target.hidden ? 0.6 : 1,
    }}>
      <div onClick={onToggle} style={{
        padding: '8px 12px', cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        {target.pinned && <Pin size={12} color="#f59e0b" />}
        <span style={{
          background: color, color: '#fff', fontSize: 9, fontWeight: 600,
          padding: '1px 6px', borderRadius: 3,
        }}>{TYPE_LABELS[target.type]}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>
            {target.display_name || target.handle}
          </div>
          <div style={{ fontSize: 10, color: '#9ca3af' }}>
            @{target.handle}
            {target.aliases.length > 0 && ` · 别名: ${target.aliases.join(', ')}`}
          </div>
        </div>
        <button onClick={e => { e.stopPropagation(); togglePin(); }}
          title={target.pinned ? '取消置顶' : '置顶'}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          <Pin size={14} color={target.pinned ? '#f59e0b' : '#9ca3af'} />
        </button>
        <button onClick={e => { e.stopPropagation(); toggleHide(); }}
          title={target.hidden ? '显示' : '隐藏'}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          {target.hidden ? <EyeOff size={14} color="#9ca3af" /> : <Eye size={14} color="#9ca3af" />}
        </button>
      </div>

      {expanded && (
        <div style={{ borderTop: '1px solid #f3f4f6', padding: '8px 12px', background: '#fafafa' }}>
          <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 6 }}>
            {target.description || '（无描述）'}
          </div>
          <label style={{ fontSize: 10, color: '#374151', display: 'block', marginTop: 6 }}>
            显示名（中文）
          </label>
          <input value={displayName} onChange={e => setDisplayName(e.target.value)}
            placeholder="例：数据探查"
            style={{ width: '100%', padding: '4px 6px', fontSize: 11,
                     border: '1px solid #e5e7eb', borderRadius: 3 }} />
          <label style={{ fontSize: 10, color: '#374151', display: 'block', marginTop: 6 }}>
            别名（逗号分隔）
          </label>
          <input value={aliasInput} onChange={e => setAliasInput(e.target.value)}
            placeholder="例：探查, 数据探查"
            style={{ width: '100%', padding: '4px 6px', fontSize: 11,
                     border: '1px solid #e5e7eb', borderRadius: 3 }} />
          <button onClick={handleSave} disabled={saving}
            style={{ marginTop: 8, padding: '4px 12px', fontSize: 11,
                     background: '#3b82f6', color: '#fff', border: 'none',
                     borderRadius: 3, cursor: 'pointer' }}>
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      )}
    </div>
  );
}
