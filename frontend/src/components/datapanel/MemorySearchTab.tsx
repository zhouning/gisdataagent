import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';

interface Memory {
  id: number;
  type: string;
  key: string;
  value: any;
  description: string;
  updated_at: string;
}

const MEMORY_TYPES = [
  { value: '', labelKey: 'all' },
  { value: 'region', labelKey: 'region' },
  { value: 'viz_preference', labelKey: 'visualizationPreference' },
  { value: 'analysis_result', labelKey: 'analysisResult' },
  { value: 'auto_extract', labelKey: 'autoExtract' },
  { value: 'custom', labelKey: 'custom' },
];

export default function MemorySearchTab() {
  const { t, i18n } = useTranslation();
  const [keyword, setKeyword] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const doSearch = useCallback(async (kw: string, tp: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (kw) params.set('keyword', kw);
      if (tp) params.set('type', tp);
      const r = await fetch(`/api/memory/search?${params}`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (r.ok) {
        const d = await r.json();
        setMemories(d.memories || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); setSearched(true); }
  }, [i18n.resolvedLanguage]);

  // Debounced search on keyword change
  useEffect(() => {
    const timer = setTimeout(() => {
      if (keyword || typeFilter) doSearch(keyword, typeFilter);
    }, 300);
    return () => clearTimeout(timer);
  }, [keyword, typeFilter, doSearch]);

  // Initial load
  useEffect(() => {
    if (!keyword && !typeFilter) doSearch('', '');
  }, [doSearch, keyword, typeFilter]);

  const handleDelete = async (id: number) => {
    if (!confirm(t('memorySearch.confirm.delete'))) return;
    await fetch(`/api/user/memories/${id}`, {
      method: 'DELETE',
      credentials: 'include',
      headers: getLocaleHeaders(),
    });
    doSearch(keyword, typeFilter);
  };

  const typeColor = (t: string) => {
    const m: Record<string, string> = {
      region: '#3b82f6', viz_preference: '#8b5cf6', analysis_result: '#10b981',
      auto_extract: '#f59e0b', custom: '#ec4899',
    };
    return m[t] || '#888';
  };

  const typeLabel = (type: string) => {
    const option = MEMORY_TYPES.find(item => item.value === type);
    return option ? t(`memorySearch.types.${option.labelKey}`) : type;
  };

  return (
    <div style={{ padding: '8px 12px', fontSize: 13 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <input
          placeholder={t('memorySearch.search.placeholder')}
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          style={{
            flex: 1, background: '#0d1117', border: '1px solid #444',
            borderRadius: 4, padding: '6px 10px', color: '#e0e0e0', fontSize: 13,
          }}
        />
        <select
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
          style={{
            background: '#0d1117', border: '1px solid #444',
            borderRadius: 4, padding: '6px 8px', color: '#e0e0e0', fontSize: 12,
          }}
        >
          {MEMORY_TYPES.map(t => (
            <option key={t.value} value={t.value}>{typeLabel(t.value)}</option>
          ))}
        </select>
      </div>

      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary, #888)', cursor: 'pointer', margin: '4px 0' }}>
        <input type="checkbox" checked={typeFilter === 'auto_extract'} onChange={() => setTypeFilter(typeFilter === 'auto_extract' ? '' : 'auto_extract')} />
        {t('memorySearch.filters.autoExtractOnly')}
      </label>

      {loading && <div style={{ color: '#888', textAlign: 'center', padding: 16 }}>{t('memorySearch.common.searching')}</div>}

      {!loading && searched && memories.length === 0 && (
        <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>
          {keyword || typeFilter ? t('memorySearch.empty.noMatches') : t('memorySearch.empty.noData')}
        </div>
      )}

      {!loading && memories.map(m => (
        <div key={m.id} style={{
          background: '#111827', border: '1px solid #1f2937', borderRadius: 6,
          padding: '8px 12px', marginBottom: 6,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#e0e0e0' }}>{m.key}</span>
              <span style={{
                marginInlineStart: 8, fontSize: 10, padding: '1px 6px', borderRadius: 3,
                background: `${typeColor(m.type)}20`, color: typeColor(m.type),
              }}>{typeLabel(m.type)}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: '#666' }}>
                {m.updated_at ? formatDate(m.updated_at, { dateStyle: 'medium' }) : ''}
              </span>
              <button onClick={() => handleDelete(m.id)}
                style={{ fontSize: 11, color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer' }}>
                {t('memorySearch.actions.delete')}
              </button>
            </div>
          </div>
          {m.description && (
            <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>{m.description}</div>
          )}
        </div>
      ))}

      <div style={{ fontSize: 11, color: '#555', textAlign: 'center', marginTop: 8 }}>
        {t('memorySearch.summary.count', { count: formatNumber(memories.length) })}
      </div>
    </div>
  );
}
