import { useState, useEffect } from 'react';

export default function TemplatesTab() {
  const [templates, setTemplates] = useState<any[]>([]);
  const [category, setCategory] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTemplates();
  }, [category]);

  const fetchTemplates = async () => {
    try {
      const params = category ? `?category=${category}` : '';
      const resp = await fetch(`/api/templates${params}`, { credentials: 'include' });
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (resp.ok) alert(`模板 "${name}" 已克隆为工作流`);
    } catch { alert('克隆失败'); }
  };

  if (loading) return <div className="data-panel-empty">加载中...</div>;

  return (
    <div className="data-panel-list">
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        {['', 'general', 'governance', 'optimization', 'analysis', '城市规划', '环境监测', '国土资源'].map(cat => {
          const label: Record<string, string> = {
            '': '全部', general: '通用', governance: '治理', optimization: '优化',
            analysis: '分析', '城市规划': '城市规划', '环境监测': '环境监测', '国土资源': '国土资源',
          };
          return (
            <button key={cat} className={`data-panel-btn-sm ${category === cat ? '' : 'secondary'}`}
              onClick={() => setCategory(cat)}>{label[cat] || cat}</button>
          );
        })}
      </div>
      {templates.length === 0 && <div className="data-panel-empty">暂无模板</div>}
      {templates.map((t: any) => (
        <div key={t.id} className="data-panel-card" style={{ marginBottom: 6 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{t.template_name}</div>
          <div style={{ fontSize: 12, color: '#aaa', margin: '2px 0' }}>{t.description}</div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
            <span className="data-panel-badge">{t.category}</span>
            <span style={{ fontSize: 11, color: '#888' }}>克隆: {t.clone_count}</span>
            <span style={{ fontSize: 11, color: '#f59e0b' }}>{'★'.repeat(Math.round(t.rating_avg || 0))}</span>
          </div>
          <button className="data-panel-btn-sm" style={{ marginTop: 6 }} onClick={() => cloneTemplate(t.id, t.template_name)}>克隆为工作流</button>
        </div>
      ))}
    </div>
  );
}
