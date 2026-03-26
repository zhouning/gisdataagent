import { useState, useEffect } from 'react';

interface QcTemplate {
  id: string;
  name: string;
  description: string;
  step_count: number;
  sla_total_seconds: number;
}

interface DefectCategory {
  id: string;
  name: string;
  description: string;
}

interface SeverityLevel {
  code: string;
  name: string;
  weight: number;
}

interface ReviewItem {
  id: number;
  file_path: string;
  defect_code: string;
  defect_description: string;
  severity: string;
  status: string;
  assigned_to: string;
  created_at: string;
}

export default function QcMonitorTab() {
  const [templates, setTemplates] = useState<QcTemplate[]>([]);
  const [categories, setCategories] = useState<DefectCategory[]>([]);
  const [severities, setSeverities] = useState<SeverityLevel[]>([]);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeSection, setActiveSection] = useState<'templates' | 'taxonomy' | 'reviews'>('templates');

  const fetchTemplates = async () => {
    try {
      const r = await fetch('/api/workflows/qc-templates', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setTemplates(d.templates || []); }
    } catch { /* ignore */ }
  };

  const fetchTaxonomy = async () => {
    try {
      const r = await fetch('/api/defect-taxonomy', { credentials: 'include' });
      if (r.ok) {
        const d = await r.json();
        setCategories(d.categories || []);
        setSeverities(d.severity_levels || []);
      }
    } catch { /* ignore */ }
  };

  const fetchReviews = async () => {
    try {
      const r = await fetch('/api/qc/reviews', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setReviews(d.reviews || []); }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    Promise.all([fetchTemplates(), fetchTaxonomy(), fetchReviews()]).finally(() => setLoading(false));
  }, []);

  const createFromTemplate = async (templateId: string) => {
    try {
      const r = await fetch('/api/workflows/from-template', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_id: templateId }),
      });
      if (r.ok) { alert('工作流创建成功'); }
      else { const d = await r.json(); alert(d.error || '创建失败'); }
    } catch { alert('网络错误'); }
  };

  const updateReview = async (id: number, status: string) => {
    try {
      await fetch(`/api/qc/reviews/${id}`, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      fetchReviews();
    } catch { /* ignore */ }
  };

  const sevColor = (s: string) =>
    s === 'A' ? '#e53935' : s === 'B' ? '#fb8c00' : '#43a047';

  const statusColor = (s: string) =>
    s === 'pending' ? '#fb8c00' : s === 'approved' ? '#43a047' : s === 'rejected' ? '#e53935' : '#1a73e8';

  if (loading) return <div style={{ padding: 12 }}>加载中...</div>;

  return (
    <div style={{ padding: 12 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {(['templates', 'taxonomy', 'reviews'] as const).map(s => (
          <button key={s} onClick={() => setActiveSection(s)} style={{
            padding: '4px 12px', borderRadius: 4, cursor: 'pointer',
            background: activeSection === s ? '#1a73e8' : 'white',
            color: activeSection === s ? 'white' : '#333',
            border: activeSection === s ? 'none' : '1px solid #ddd',
          }}>
            {s === 'templates' ? '质检模板' : s === 'taxonomy' ? '缺陷分类' : '复核管理'}
          </button>
        ))}
      </div>

      {activeSection === 'templates' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>质检工作流模板</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
            {templates.map(t => (
              <div key={t.id} style={{ border: '1px solid #e0e0e0', borderRadius: 6, padding: 12 }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{t.name}</div>
                <div style={{ fontSize: 11, color: '#666', marginBottom: 6 }}>{t.description}</div>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
                  {t.step_count} 步骤 · SLA {Math.round(t.sla_total_seconds / 60)} 分钟
                </div>
                <button onClick={() => createFromTemplate(t.id)} style={{
                  padding: '4px 12px', borderRadius: 4, border: 'none',
                  background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12,
                }}>创建工作流</button>
              </div>
            ))}
            {templates.length === 0 && <div style={{ color: '#999', fontSize: 12 }}>暂无模板</div>}
          </div>
        </div>
      )}

      {activeSection === 'taxonomy' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>缺陷分类体系 (GB/T 24356)</div>
          <div style={{ display: 'flex', gap: 16 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>缺陷类别</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead><tr style={{ background: '#f5f5f5' }}>
                  <th style={{ padding: '6px 8px', textAlign: 'left' }}>ID</th>
                  <th style={{ padding: '6px 8px', textAlign: 'left' }}>名称</th>
                  <th style={{ padding: '6px 8px', textAlign: 'left' }}>说明</th>
                </tr></thead>
                <tbody>{categories.map(c => (
                  <tr key={c.id}><td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{c.id}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{c.name}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee', color: '#666' }}>{c.description}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <div style={{ width: 200 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>严重程度</div>
              {severities.map(s => (
                <div key={s.code} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(s.code), color: 'white' }}>{s.code}</span>
                  <span style={{ fontSize: 12 }}>{s.name}</span>
                  <span style={{ fontSize: 11, color: '#999' }}>权重 {s.weight}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeSection === 'reviews' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>人工复核管理</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: '#f5f5f5' }}>
              <th style={{ padding: '6px 8px', textAlign: 'left' }}>ID</th>
              <th style={{ padding: '6px 8px', textAlign: 'left' }}>文件</th>
              <th style={{ padding: '6px 8px', textAlign: 'left' }}>缺陷</th>
              <th style={{ padding: '6px 8px', textAlign: 'left' }}>严重度</th>
              <th style={{ padding: '6px 8px', textAlign: 'left' }}>状态</th>
              <th style={{ padding: '6px 8px', textAlign: 'left' }}>操作</th>
            </tr></thead>
            <tbody>{reviews.map(r => (
              <tr key={r.id}>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{r.id}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee', maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.file_path}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{r.defect_code} {r.defect_description}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>
                  <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(r.severity), color: 'white' }}>{r.severity}</span>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>
                  <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: 11, background: statusColor(r.status), color: 'white' }}>{r.status}</span>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>
                  {r.status === 'pending' && <>
                    <button onClick={() => updateReview(r.id, 'approved')} style={{ padding: '2px 8px', borderRadius: 3, border: 'none', background: '#43a047', color: 'white', cursor: 'pointer', fontSize: 11, marginRight: 4 }}>通过</button>
                    <button onClick={() => updateReview(r.id, 'rejected')} style={{ padding: '2px 8px', borderRadius: 3, border: 'none', background: '#e53935', color: 'white', cursor: 'pointer', fontSize: 11 }}>驳回</button>
                  </>}
                </td>
              </tr>
            ))}</tbody>
          </table>
          {reviews.length === 0 && <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>暂无复核项</div>}
        </div>
      )}
    </div>
  );
}
