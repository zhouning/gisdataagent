import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Eye, EyeOff, RotateCcw, Save, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../i18n';

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

const compareNavigationItems = (left: NavigationItem, right: NavigationItem, locale = 'zh-CN') => (
  (left.group_sort_order ?? 0) - (right.group_sort_order ?? 0)
  || (left.section_sort_order ?? 0) - (right.section_sort_order ?? 0)
  || left.sort_order - right.sort_order
  || left.label.localeCompare(right.label, locale)
);

const normalizeItems = (payload: NavigationResponse, locale: string) => (
  (payload.items || [])
    .map(item => ({ ...item, visible: item.visible !== false }))
    .sort((left, right) => compareNavigationItems(left, right, locale))
);

export default function NavigationSettingsSection() {
  const { t, i18n } = useTranslation('common');
  const locale = i18n.resolvedLanguage || i18n.language || 'zh-CN';
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
      const response = await fetch('/api/admin/navigation', { credentials: 'include', headers: getLocaleHeaders() });
      if (!response.ok) throw new Error(t('adminNavigation.loadFailed'));
      const payload: NavigationResponse = await response.json();
      const next = normalizeItems(payload, locale);
      setItems(next);
      setInitialItems(next);
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : t('adminNavigation.loadFailed') });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [locale]);

  const changed = JSON.stringify(items) !== JSON.stringify(initialItems);
  const visibleCount = items.filter(item => item.visible).length;
  const navigationLabel = (kind: 'groups' | 'sections' | 'tabs', key: string, fallback: string) => (
    t(`dataPanel.${kind}.${key}`, { defaultValue: fallback })
  );
  const groupOptions = useMemo(() => [
    ...new Map(items.map(item => [
      item.group_key,
      navigationLabel('groups', item.group_key, item.group_label),
    ])).entries(),
  ], [items, t]);
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return items.filter(item => (
      (!groupFilter || item.group_key === groupFilter)
      && (!normalized || `${navigationLabel('tabs', item.tab_key, item.label)} ${item.tab_key} ${navigationLabel('sections', item.section_key, item.section_label)}`.toLowerCase().includes(normalized))
    )).sort((left, right) => compareNavigationItems(left, right, locale));
  }, [groupFilter, items, locale, query, t]);

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
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
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
      if (!response.ok) throw new Error(payload.error || t('adminNavigation.saveFailed'));
      const next = normalizeItems(payload.items ? payload : { items }, locale);
      setItems(next);
      setInitialItems(next);
      setMessage({ type: 'success', text: t('adminNavigation.saveSuccess') });
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : t('adminNavigation.saveFailed') });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="admin-loading">{t('adminNavigation.loading')}</div>;

  return (
    <section className="navigation-settings-section">
      <div className="admin-section-heading">
        <span><Eye size={18} /></span>
        <div>
          <h3>{t('adminNavigation.title')}</h3>
          <p>{t('adminNavigation.description')}</p>
        </div>
      </div>

      <div className="navigation-settings-toolbar">
        <div className="navigation-settings-summary" title={t('adminNavigation.visibleCountTooltip')}>
          <strong>{visibleCount}</strong><span>{t('adminNavigation.visibleSummary', { total: items.length })}</span>
        </div>
        <label className="navigation-search">
          <Search size={15} />
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder={t('adminNavigation.searchPlaceholder')} />
        </label>
        <select aria-label={t('adminNavigation.groupFilterAria')} value={groupFilter} onChange={event => setGroupFilter(event.target.value)}>
          <option value="">{t('adminNavigation.allGroups')}</option>
          {groupOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <button className="btn-secondary" onClick={() => setItems(initialItems)} disabled={!changed || saving}>
          <RotateCcw size={14} />{t('adminNavigation.undo')}
        </button>
        <button className="btn-primary" onClick={save} disabled={!changed || saving}>
          <Save size={14} />{saving ? t('adminNavigation.saving') : t('adminNavigation.saveConfig')}
        </button>
      </div>

      <div className="navigation-settings-list">
        {visibleItems.length === 0 ? <div className="empty-state">{t('adminNavigation.empty')}</div> : visibleItems.map(item => (
          <div key={item.tab_key} className={`navigation-settings-row${item.visible ? '' : ' hidden'}`}>
            <button
              className="navigation-visibility-button"
              onClick={() => updateItem(item.tab_key, { visible: !item.visible })}
              title={item.visible ? t('adminNavigation.hideTab') : t('adminNavigation.showTab')}
              aria-label={item.visible
                ? t('adminNavigation.hideItem', { label: navigationLabel('tabs', item.tab_key, item.label) })
                : t('adminNavigation.showItem', { label: navigationLabel('tabs', item.tab_key, item.label) })}
            >
              {item.visible ? <Eye size={16} /> : <EyeOff size={16} />}
            </button>
            <div className="navigation-settings-label">
              <strong>{navigationLabel('tabs', item.tab_key, item.label)}</strong>
              <code>{item.tab_key}</code>
            </div>
            <div className="navigation-settings-location">
              {navigationLabel('groups', item.group_key, item.group_label)} / {navigationLabel('sections', item.section_key, item.section_label)}
            </div>
            <div className="navigation-order-actions">
              <button onClick={() => move(item.tab_key, -1)} title={t('adminNavigation.moveUp')} aria-label={t('adminNavigation.moveItemUp', { label: navigationLabel('tabs', item.tab_key, item.label) })}><ChevronUp size={15} /></button>
              <button onClick={() => move(item.tab_key, 1)} title={t('adminNavigation.moveDown')} aria-label={t('adminNavigation.moveItemDown', { label: navigationLabel('tabs', item.tab_key, item.label) })}><ChevronDown size={15} /></button>
            </div>
          </div>
        ))}
      </div>

      {message && <p className={`platform-settings-message ${message.type}`}>{message.text}</p>}
    </section>
  );
}
