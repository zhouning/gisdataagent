import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

const CATEGORY_OPTIONS = [
  { value: '', labelKey: 'all' },
  { value: 'general', labelKey: 'general' },
  { value: 'governance', labelKey: 'governance' },
  { value: 'optimization', labelKey: 'optimization' },
  { value: 'analysis', labelKey: 'analysis' },
  { value: '\u57ce\u5e02\u89c4\u5212', labelKey: 'urbanPlanning' },
  { value: '\u73af\u5883\u76d1\u6d4b', labelKey: 'environmentalMonitoring' },
  { value: '\u56fd\u571f\u8d44\u6e90', labelKey: 'landResources' },
] as const;

export default function TemplatesTab() {
  const { t, i18n } = useTranslation();
  const [templates, setTemplates] = useState<any[]>([]);
  const [category, setCategory] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTemplates();
  }, [category, i18n.resolvedLanguage]);

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (category) params.set('category', category);
      const query = params.toString();
      const resp = await fetch(`/api/templates${query ? `?${query}` : ''}`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (resp.ok) {
        const data = await resp.json();
        setTemplates(data.templates || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  };

  const cloneTemplate = async (id: number, name: string) => {
    try {
      const resp = await fetch(`/api/templates/${id}/clone`, {
        method: 'POST', credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (resp.ok) alert(t('templatesTab.messages.cloned', { name }));
    } catch { alert(t('templatesTab.errors.clone')); }
  };

  const categoryLabel = (value: string) => {
    const option = CATEGORY_OPTIONS.find(item => item.value === value);
    return option ? t(`templatesTab.categories.${option.labelKey}`) : value;
  };

  if (loading) return <div className="data-panel-empty">{t('templatesTab.common.loading')}</div>;

  return (
    <div className="data-panel-list">
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        {CATEGORY_OPTIONS.map(option => (
          <button key={option.value} className={`data-panel-btn-sm ${category === option.value ? '' : 'secondary'}`}
            onClick={() => setCategory(option.value)}>{t(`templatesTab.categories.${option.labelKey}`)}</button>
        ))}
      </div>
      {templates.length === 0 && <div className="data-panel-empty">{t('templatesTab.empty.templates')}</div>}
      {templates.map((template: any) => (
        <div key={template.id} className="data-panel-card" style={{ marginBottom: 6 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{template.template_name}</div>
          <div style={{ fontSize: 12, color: '#aaa', margin: '2px 0' }}>{template.description}</div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
            <span className="data-panel-badge">{categoryLabel(template.category)}</span>
            <span style={{ fontSize: 11, color: '#888' }}>{t('templatesTab.details.cloneCount', { count: formatNumber(template.clone_count || 0) })}</span>
            <span style={{ fontSize: 11, color: '#f59e0b' }}>{'★'.repeat(Math.round(template.rating_avg || 0))}</span>
          </div>
          <button className="data-panel-btn-sm" style={{ marginTop: 6 }} onClick={() => cloneTemplate(template.id, template.template_name)}>{t('templatesTab.actions.clone')}</button>
        </div>
      ))}
    </div>
  );
}
