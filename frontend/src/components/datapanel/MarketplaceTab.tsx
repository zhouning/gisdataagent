import { useState, useEffect } from 'react';

interface MarketItem {
  id: number;
  name: string;
  type: 'skill' | 'tool' | 'template' | 'bundle';
  description: string;
  owner: string;
  rating: number;
  rating_count: number;
  clone_count: number;
  template_type?: string;
  category?: string;
}

export default function MarketplaceTab() {
  const [items, setItems] = useState<MarketItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState<'rating' | 'usage' | 'recent'>('rating');
  const [filter, setFilter] = useState<string>('all');
  const [search, setSearch] = useState('');

  const fetchItems = async (sortBy: string) => {
    setLoading(true);
    try {
      const r = await fetch(`/api/marketplace?sort=${sortBy}`, { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setItems(d.items || []); }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchItems(sort); }, [sort]);

  const handleClone = async (item: MarketItem) => {
    const url = item.type === 'skill'
      ? `/api/skills/${item.id}/clone`
      : item.type === 'tool'
        ? `/api/user-tools/${item.id}/clone`
        : null;
    if (!url) return;
    const r = await fetch(url, { method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (r.ok) { fetchItems(sort); }
  };

  const handleRate = async (item: MarketItem, score: number) => {
    const url = item.type === 'skill'
      ? `/api/skills/${item.id}/rate`
      : item.type === 'tool'
        ? `/api/user-tools/${item.id}/rate`
        : item.type === 'template'
          ? `/api/templates/${item.id}/rate`
          : null;
    if (!url) return;
    await fetch(url, { method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ score }) });
    fetchItems(sort);
  };

  const typeLabel: Record<string, string> = { skill: '技能', tool: '工具', template: '模板', bundle: '套件' };
  const typeColor: Record<string, string> = { skill: '#7c3aed', tool: '#0d9488', template: '#d97706', bundle: '#2563eb' };

  const filtered = items.filter(i => {
    if (filter !== 'all' && i.type !== filter) return false;
    if (search && !i.name.toLowerCase().includes(search.toLowerCase())
        && !i.description.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  if (loading) return <div style={{ padding: 16, color: '#888' }}>加载中...</div>;

  return (
    <div style={{ padding: '8px 12px', fontSize: 13 }}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <input placeholder="搜索..." value={search} onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 100, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 8px', color: '#e0e0e0', fontSize: 12 }} />
        <select value={filter} onChange={e => setFilter(e.target.value)}
          style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 6px', color: '#e0e0e0', fontSize: 12 }}>
          <option value="all">全部</option>
          <option value="skill">技能</option>
          <option value="tool">工具</option>
          <option value="template">模板</option>
          <option value="bundle">套件</option>
        </select>
        <select value={sort} onChange={e => setSort(e.target.value as any)}
          style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 6px', color: '#e0e0e0', fontSize: 12 }}>
          <option value="rating">评分</option>
          <option value="usage">使用量</option>
          <option value="recent">最新</option>
        </select>
      </div>

      <div style={{ color: '#888', fontSize: 11, marginBottom: 6 }}>{filtered.length} 个共享资源</div>

      {filtered.length === 0 && (
        <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>暂无共享资源</div>
      )}

      {filtered.map(item => (
        <div key={`${item.type}-${item.id}`} style={{
          background: '#111827', border: '1px solid #1f2937', borderRadius: 6,
          padding: '8px 12px', marginBottom: 6,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#e0e0e0' }}>{item.name}</span>
              <span style={{
                marginLeft: 8, fontSize: 10, padding: '1px 6px', borderRadius: 3,
                background: typeColor[item.type] + '22', color: typeColor[item.type],
              }}>{typeLabel[item.type]}</span>
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              {[1,2,3,4,5].map(s => (
                <span key={s} onClick={() => handleRate(item, s)}
                  style={{ cursor: 'pointer', color: s <= Math.round(item.rating) ? '#f59e0b' : '#444', fontSize: 14 }}>
                  ★
                </span>
              ))}
              <span style={{ fontSize: 11, color: '#888' }}>({item.rating_count})</span>
              {(item.type === 'skill' || item.type === 'tool') && (
                <button onClick={() => handleClone(item)}
                  style={{ fontSize: 11, color: '#7dd3fc', background: 'none', border: '1px solid #334155', borderRadius: 4, padding: '1px 8px', cursor: 'pointer' }}>
                  克隆
                </button>
              )}
            </div>
          </div>
          <div style={{ fontSize: 11, color: '#aaa', marginTop: 4 }}>
            {item.description || '无描述'}
          </div>
          <div style={{ fontSize: 10, color: '#666', marginTop: 4, display: 'flex', gap: 12 }}>
            <span>by {item.owner}</span>
            <span>克隆 {item.clone_count}</span>
            {item.category && <span>{item.category}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
