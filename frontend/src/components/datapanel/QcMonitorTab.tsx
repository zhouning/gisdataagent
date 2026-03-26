import { useState, useEffect } from 'react';

interface QcTemplate {
  id: string;
  name: string;
  description: string;
  step_count: number;
}

interface DefectCode {
  code: string;
  name: string;
  category: string;
  severity: string;
  auto_fixable: boolean;
}

interface DefectCategory {
  id: string;
  name: string;
  description: string;
}

interface QcReview {
  id: number;
  file_path: string;
  defect_code: string;
  severity: string;
  status: string;
  assigned_to: string;
  review_comment: string;
  fix_description: string;
  created_at: string;
}

export default function QcMonitorTab() {
  const [templates, setTemplates] = useState<QcTemplate[]>([]);
  const [categories, setCategories] = useState<DefectCategory[]>([]);
  const [defects, setDefects] = useState<DefectCode[]>([]);
  const [reviews, setReviews] = useState<QcReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [section, setSection] = useState<'templates' | 'taxonomy' | 'reviews'>('templates');
  const [collapsedCats, setCollapsedCats] = useState<Set<string>>(new Set());
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

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
        setDefects(d.defects || []);
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

  const toggleCat = (id: string) => {
    setCollapsedCats(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const sevColor = (s: string) =>
    s === 'A' ? '#e53935' : s === 'B' ? '#fb8c00' : '#43a047';

  const statusStyle = (s: string): { bg: string; color: string } => {
    switch (s) {
      case 'pending': return { bg: '#e0e0e0', color: '#555' };
      case 'in_review': return { bg: '#bbdefb', color: '#1565c0' };
      case 'fixed': return { bg: '#c8e6c9', color: '#2e7d32' };
      case 'approved': return { bg: '#a5d6a7', color: '#1b5e20' };
      case 'rejected': return { bg: '#ffcdd2', color: '#c62828' };
      default: return { bg: '#eee', color: '#666' };
    }
  };

  const pendingCount = reviews.filter(r => r.status === 'pending').length;
  const fixedCount = reviews.filter(r => r.status === 'fixed').length;
  const approvedCount = reviews.filter(r => r.status === 'approved').length;

  if (loading) return <div style={{ padding: 12, color: '#888' }}>加载中...</div>;

  return (
    <div style={{ padding: 12 }}>
      {/* Summary bar */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#7dd3fc' }}>{reviews.length}</div>
          <div style={{ color: '#888', fontSize: 11 }}>总复核数</div>
        </div>
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#fb8c00' }}>{pendingCount}</div>
          <div style={{ color: '#888', fontSize: 11 }}>待处理</div>
        </div>
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#43a047' }}>{fixedCount}</div>
          <div style={{ color: '#888', fontSize: 11 }}>已修复</div>
        </div>
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#10b981' }}>{approvedCount}</div>
          <div style={{ color: '#888', fontSize: 11 }}>已通过</div>
        </div>
      </div>

      {/* Section switcher */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {(['templates', 'taxonomy', 'reviews'] as const).map(s => (
          <button key={s} onClick={() => setSection(s)}
            style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: section === s ? '#1e3a5f' : '#111827',
              color: section === s ? '#7dd3fc' : '#888',
              border: `1px solid ${section === s ? '#2563eb' : '#333'}`,
            }}>
            {s === 'templates' ? '质检模板' : s === 'taxonomy' ? '缺陷分类' : '复核管理'}
          </button>
        ))}
      </div>

      {/* Templates */}
      {section === 'templates' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>质检工作流模板</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
            {templates.map(t => (
              <div key={t.id} style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12 }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4, color: '#e0e0e0' }}>{t.name}</div>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>{t.description}</div>
                <div style={{ fontSize: 11, color: '#666', marginBottom: 8 }}>{t.step_count} 步骤</div>
                <button onClick={() => createFromTemplate(t.id)} style={{
                  padding: '4px 12px', borderRadius: 4, border: 'none',
                  background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12,
                }}>创建工作流</button>
              </div>
            ))}
            {templates.length === 0 && <div style={{ color: '#888', fontSize: 12 }}>暂无模板</div>}
          </div>
        </div>
      )}

      {/* Taxonomy — collapsible categories with defect codes */}
      {section === 'taxonomy' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>缺陷分类体系</div>
          {categories.length === 0 && <div style={{ color: '#888', fontSize: 12 }}>暂无缺陷分类数据</div>}
          {categories.map(cat => {
            const catDefects = defects.filter(d => d.category === cat.id);
            const collapsed = collapsedCats.has(cat.id);
            return (
              <div key={cat.id} style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, marginBottom: 6 }}>
                <div onClick={() => toggleCat(cat.id)} style={{
                  padding: '8px 12px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                }}>
                  <div>
                    <span style={{ fontWeight: 600, color: '#e0e0e0', fontSize: 13 }}>{cat.name}</span>
                    <span style={{ marginLeft: 8, fontSize: 11, color: '#888' }}>{cat.description}</span>
                  </div>
                  <span style={{ color: '#888', fontSize: 12 }}>{collapsed ? '+' : '-'} ({catDefects.length})</span>
                </div>
                {!collapsed && catDefects.length > 0 && (
                  <div style={{ padding: '0 12px 8px' }}>
                    {catDefects.map(d => (
                      <div key={d.code} style={{
                        display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0',
                        borderBottom: '1px solid #1f2937', fontSize: 12,
                      }}>
                        <span style={{ fontFamily: 'monospace', color: '#7dd3fc', minWidth: 60 }}>{d.code}</span>
                        <span style={{ color: '#ccc', flex: 1 }}>{d.name}</span>
                        <span style={{
                          display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11,
                          background: sevColor(d.severity), color: 'white',
                        }}>{d.severity}</span>
                        {d.auto_fixable && (
                          <span style={{
                            display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11,
                            background: '#1e3a5f', color: '#7dd3fc',
                          }}>自动修复</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Reviews table with expandable rows */}
      {section === 'reviews' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>复核管理</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: '#1f2937' }}>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>ID</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>文件</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>缺陷码</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>严重度</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>状态</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>负责人</th>
            </tr></thead>
            <tbody>{reviews.map(r => {
              const ss = statusStyle(r.status);
              const isExpanded = expandedRow === r.id;
              return (
                <>{/* Fragment for row + detail */}
                  <tr key={r.id} onClick={() => setExpandedRow(isExpanded ? null : r.id)}
                    style={{ cursor: 'pointer', background: isExpanded ? '#1a1a2e' : 'transparent' }}>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{r.id}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc', maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.file_path}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', fontFamily: 'monospace', color: '#7dd3fc' }}>{r.defect_code}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                      <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(r.severity), color: 'white' }}>{r.severity}</span>
                    </td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                      <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: ss.bg, color: ss.color }}>{r.status}</span>
                    </td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#aaa' }}>{r.assigned_to || '-'}</td>
                  </tr>
                  {isExpanded && (
                    <tr key={`${r.id}-detail`}>
                      <td colSpan={6} style={{ padding: '8px 12px', background: '#0d1117', borderBottom: '1px solid #1f2937', fontSize: 12 }}>
                        <div style={{ marginBottom: 4 }}>
                          <span style={{ color: '#888' }}>复核意见: </span>
                          <span style={{ color: '#ccc' }}>{r.review_comment || '暂无'}</span>
                        </div>
                        <div>
                          <span style={{ color: '#888' }}>修复说明: </span>
                          <span style={{ color: '#ccc' }}>{r.fix_description || '暂无'}</span>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}</tbody>
          </table>
          {reviews.length === 0 && <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>暂无复核项</div>}
        </div>
      )}
    </div>
  );
}
