import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Pin, EyeOff, Eye } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

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

const TYPE_LABEL_KEYS: Record<MentionTarget['type'], string> = {
  pipeline: 'pipeline',
  sub_agent: 'subAgent',
  adk_skill: 'builtInSkill',
  custom_skill: 'customSkill',
};

const TYPE_COLORS: Record<string, string> = {
  pipeline: '#3b82f6',
  sub_agent: '#10b981',
  adk_skill: '#f59e0b',
  custom_skill: '#a855f7',
};

export default function AgentsTab() {
  const { t, i18n } = useTranslation();
  const [targets, setTargets] = useState<MentionTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchTargets = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/agents/mention-targets?include_hidden=1', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (resp.ok) {
        const data = await resp.json();
        setTargets(data.targets || []);
      }
    } finally { setLoading(false); }
  }, [i18n.resolvedLanguage]);

  useEffect(() => { fetchTargets(); }, [fetchTargets]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const typeOrder: Record<FilterKey, number> = {
      all: 99,
      pipeline: 0,
      sub_agent: 1,
      adk_skill: 2,
      custom_skill: 3,
    };
    return targets
      .filter(t => {
        if (filter !== 'all' && t.type !== filter) return false;
        if (!q) return true;
        if (t.handle.toLowerCase().includes(q)) return true;
        if (t.display_name.toLowerCase().includes(q)) return true;
        if (t.aliases.some(a => a.toLowerCase().includes(q))) return true;
        return false;
      })
      .sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        const at = typeOrder[a.type] ?? 99;
        const bt = typeOrder[b.type] ?? 99;
        if (at !== bt) return at - bt;
        return (a.display_name || a.handle).localeCompare(
          b.display_name || b.handle,
          i18n.resolvedLanguage || i18n.language,
        );
      });
  }, [targets, filter, search, i18n.resolvedLanguage, i18n.language]);

  if (loading) return <div className="empty-state">{t('agentsTab.common.loading')}</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 12 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={14} style={{ position: 'absolute', insetInlineStart: 8, top: 8, color: '#9ca3af' }} />
          <input
            type="text" placeholder={t('agentsTab.search.placeholder')}
            value={search} onChange={e => setSearch(e.target.value)}
            style={{
              width: '100%', paddingBlock: 6, paddingInlineEnd: 8, paddingInlineStart: 28, fontSize: 12,
              border: '1px solid #e5e7eb', borderRadius: 4,
            }}
          />
        </div>
        <span style={{ fontSize: 11, color: '#9ca3af' }}>
          {t('agentsTab.search.resultCount', {
            filtered: formatNumber(filtered.length),
            total: formatNumber(targets.length),
          })}
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
            {k === 'all' ? t('agentsTab.filters.all') : t(`agentsTab.types.${TYPE_LABEL_KEYS[k]}`)}
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
          <div className="empty-state" style={{ padding: 24 }}>{t('agentsTab.empty.noMatches')}</div>
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
  const { t } = useTranslation();
  const [aliasInput, setAliasInput] = useState(target.aliases.join(', '));
  const [displayName, setDisplayName] = useState(target.display_name);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const aliases = aliasInput.split(',').map(a => a.trim()).filter(Boolean);
      await fetch(`/api/agents/${encodeURIComponent(target.handle)}/alias`, {
        method: 'PUT', credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ aliases, display_name: displayName }),
      });
      onChanged();
    } finally { setSaving(false); }
  };

  const togglePin = async () => {
    await fetch(`/api/agents/${encodeURIComponent(target.handle)}/pin`, {
      method: 'PUT', credentials: 'include',
      headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ pinned: !target.pinned }),
    });
    onChanged();
  };

  const toggleHide = async () => {
    await fetch(`/api/agents/${encodeURIComponent(target.handle)}/hide`, {
      method: 'PUT', credentials: 'include',
      headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
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
        }}>{t(`agentsTab.types.${TYPE_LABEL_KEYS[target.type]}`)}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>
            {target.display_name || target.handle}
          </div>
          <div style={{ fontSize: 10, color: '#9ca3af' }}>
            @{target.handle}
            {target.aliases.length > 0 && ` · ${t('agentsTab.card.aliases', { aliases: target.aliases.join(', ') })}`}
          </div>
        </div>
        <button onClick={e => { e.stopPropagation(); togglePin(); }}
          title={target.pinned ? t('agentsTab.actions.unpin') : t('agentsTab.actions.pin')}
          aria-label={target.pinned ? t('agentsTab.actions.unpin') : t('agentsTab.actions.pin')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          <Pin size={14} color={target.pinned ? '#f59e0b' : '#9ca3af'} />
        </button>
        <button onClick={e => { e.stopPropagation(); toggleHide(); }}
          title={target.hidden ? t('agentsTab.actions.show') : t('agentsTab.actions.hide')}
          aria-label={target.hidden ? t('agentsTab.actions.show') : t('agentsTab.actions.hide')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          {target.hidden ? <EyeOff size={14} color="#9ca3af" /> : <Eye size={14} color="#9ca3af" />}
        </button>
      </div>

      {expanded && (
        <div style={{ borderTop: '1px solid #f3f4f6', padding: '8px 12px', background: '#fafafa' }}>
          <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 6 }}>
            {target.description || t('agentsTab.empty.noDescription')}
          </div>
          <label style={{ fontSize: 10, color: '#374151', display: 'block', marginTop: 6 }}>
            {t('agentsTab.form.displayName')}
          </label>
          <input value={displayName} onChange={e => setDisplayName(e.target.value)}
            placeholder={t('agentsTab.form.displayNamePlaceholder')}
            style={{ width: '100%', padding: '4px 6px', fontSize: 11,
                     border: '1px solid #e5e7eb', borderRadius: 3 }} />
          <label style={{ fontSize: 10, color: '#374151', display: 'block', marginTop: 6 }}>
            {t('agentsTab.form.aliases')}
          </label>
          <input value={aliasInput} onChange={e => setAliasInput(e.target.value)}
            placeholder={t('agentsTab.form.aliasesPlaceholder')}
            style={{ width: '100%', padding: '4px 6px', fontSize: 11,
                     border: '1px solid #e5e7eb', borderRadius: 3 }} />
          <button onClick={handleSave} disabled={saving}
            style={{ marginTop: 8, padding: '4px 12px', fontSize: 11,
                     background: '#3b82f6', color: '#fff', border: 'none',
                     borderRadius: 3, cursor: 'pointer' }}>
            {saving ? t('agentsTab.actions.saving') : t('agentsTab.actions.save')}
          </button>
        </div>
      )}
    </div>
  );
}
