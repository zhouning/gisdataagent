import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Eye, EyeOff, RotateCcw, Save, Search } from 'lucide-react';

interface NavigationItem {
  tab_key: string;
  label: string;
  group_key: string;
  group_label: string;
  section_key: string;
  section_label: string;
  visible: boolean;
  sort_order: number;
  group_sort_order?: number;
  section_sort_order?: number;
  lifecycle_status?: string;
}

interface NavigationResponse {
  items?: NavigationItem[];
}

const compareNavigationItems = (left: NavigationItem, right: NavigationItem) => (
  (left.group_sort_order ?? 0) - (right.group_sort_order ?? 0)
  || (left.section_sort_order ?? 0) - (right.section_sort_order ?? 0)
  || left.sort_order - right.sort_order
  || left.label.localeCompare(right.label, 'zh-CN')
);

const normalizeItems = (payload: NavigationResponse) => (
  (payload.items || [])
    .map(item => ({ ...item, visible: item.visible !== false }))
    .sort(compareNavigationItems)
);

export default function NavigationSettingsSection() {
  const [items, setItems] = useState<NavigationItem[]>([]);
  const [initialItems, setInitialItems] = useState<NavigationItem[]>([]);
  const [query, setQuery] = useState('');
  const [groupFilter, setGroupFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const load = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const response = await fetch('/api/admin/navigation', { credentials: 'include' });
      if (!response.ok) throw new Error('导航配置加载失败');
      const payload: NavigationResponse = await response.json();
      const next = normalizeItems(payload);
      setItems(next);
      setInitialItems(next);
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : '导航配置加载失败' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const changed = JSON.stringify(items) !== JSON.stringify(initialItems);
  const visibleCount = items.filter(item => item.visible).length;
  const groupOptions = useMemo(
    () => [...new Map(items.map(item => [item.group_key, item.group_label])).entries()],
    [items],
  );
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return items.filter(item => (
      (!groupFilter || item.group_key === groupFilter)
      && (!normalized || `${item.label} ${item.tab_key} ${item.section_label}`.toLowerCase().includes(normalized))
    )).sort(compareNavigationItems);
  }, [groupFilter, items, query]);

  const updateItem = (tabKey: string, update: Partial<NavigationItem>) => {
    setItems(current => current.map(item => item.tab_key === tabKey ? { ...item, ...update } : item));
  };

  const move = (tabKey: string, direction: -1 | 1) => {
    setItems(current => {
      const next = [...current];
      const target = next.find(item => item.tab_key === tabKey);
      if (!target) return current;
      const siblings = next
        .filter(item => item.group_key === target.group_key && item.section_key === target.section_key)
        .sort((a, b) => a.sort_order - b.sort_order);
      const index = siblings.findIndex(item => item.tab_key === tabKey);
      const swap = siblings[index + direction];
      if (!swap) return current;
      const targetOrder = target.sort_order;
      const swapOrder = swap.sort_order;
      return next.map(item => item.tab_key === target.tab_key
        ? { ...item, sort_order: swapOrder }
        : item.tab_key === swap.tab_key ? { ...item, sort_order: targetOrder } : item);
    });
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch('/api/admin/navigation', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: items.map(item => ({
            tab_key: item.tab_key,
            visible: item.visible,
            group_key: item.group_key,
            section_key: item.section_key,
            sort_order: item.sort_order,
          })),
      }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || '导航配置保存失败');
      const next = normalizeItems(payload.items ? payload : { items });
      setItems(next);
      setInitialItems(next);
      setMessage({ type: 'success', text: '工作台导航已保存，刷新后对用户生效。' });
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : '导航配置保存失败' });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="admin-loading">加载导航配置...</div>;

  return (
    <section className="navigation-settings-section">
      <div className="admin-section-heading">
        <span><Eye size={18} /></span>
        <div>
          <h3>工作台导航</h3>
          <p>控制右侧数据面板的 Tab 显示、分组内顺序和客户可见范围。隐藏导航不等于替代后端权限校验。</p>
        </div>
      </div>

      <div className="navigation-settings-toolbar">
        <div className="navigation-settings-summary" title="当前可见 Tab 数">
          <strong>{visibleCount}</strong><span>/ {items.length} 可见</span>
        </div>
        <label className="navigation-search">
          <Search size={15} />
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索 Tab、标识或集合" />
        </label>
        <select aria-label="按一级组筛选" value={groupFilter} onChange={event => setGroupFilter(event.target.value)}>
          <option value="">全部一级组</option>
          {groupOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <button className="btn-secondary" onClick={() => setItems(initialItems)} disabled={!changed || saving}>
          <RotateCcw size={14} />撤销
        </button>
        <button className="btn-primary" onClick={save} disabled={!changed || saving}>
          <Save size={14} />{saving ? '保存中' : '保存配置'}
        </button>
      </div>

      <div className="navigation-settings-list">
        {visibleItems.length === 0 ? <div className="empty-state">没有匹配的导航项</div> : visibleItems.map(item => (
          <div key={item.tab_key} className={`navigation-settings-row${item.visible ? '' : ' hidden'}`}>
            <button
              className="navigation-visibility-button"
              onClick={() => updateItem(item.tab_key, { visible: !item.visible })}
              title={item.visible ? '隐藏 Tab' : '显示 Tab'}
              aria-label={item.visible ? `隐藏${item.label}` : `显示${item.label}`}
            >
              {item.visible ? <Eye size={16} /> : <EyeOff size={16} />}
            </button>
            <div className="navigation-settings-label">
              <strong>{item.label}</strong>
              <code>{item.tab_key}</code>
            </div>
            <div className="navigation-settings-location">{item.group_label} / {item.section_label}</div>
            <div className="navigation-order-actions">
              <button onClick={() => move(item.tab_key, -1)} title="上移" aria-label={`上移${item.label}`}><ChevronUp size={15} /></button>
              <button onClick={() => move(item.tab_key, 1)} title="下移" aria-label={`下移${item.label}`}><ChevronDown size={15} /></button>
            </div>
          </div>
        ))}
      </div>

      {message && <p className={`platform-settings-message ${message.type}`}>{message.text}</p>}
    </section>
  );
}
