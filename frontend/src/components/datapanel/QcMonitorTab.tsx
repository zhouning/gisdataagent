import { useState, useEffect } from 'react';
import FilePickerDialog from './FilePickerDialog';

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

interface DashboardData {
  templates: { count: number };
  reviews: { total: number; pending: number; approved: number; rejected: number; fixed: number };
  workflows: { total: number; running: number; completed: number; failed: number; sla_violated: number };
  alerts: { total_rules: number; enabled_rules: number; recent_alerts: number };
  recent_reviews: Array<{ id: number; file_path: string; defect_code: string; severity: string; status: string; created_at: string }>;
}

interface ReportTemplate {
  id: string;
  name: string;
  description: string;
  sections: string[];
}

export default function QcMonitorTab() {
  const [templates, setTemplates] = useState<QcTemplate[]>([]);
  const [categories, setCategories] = useState<DefectCategory[]>([]);
  const [defects, setDefects] = useState<DefectCode[]>([]);
  const [reviews, setReviews] = useState<QcReview[]>([]);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [section, setSection] = useState<'dashboard' | 'templates' | 'taxonomy' | 'reviews' | 'report'>('dashboard');
  const [collapsedCats, setCollapsedCats] = useState<Set<string>>(new Set());
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [quickExecTemplate, setQuickExecTemplate] = useState<string | null>(null);
  // Report generation state
  const [reportTemplates, setReportTemplates] = useState<ReportTemplate[]>([]);
  const [selectedReportTpl, setSelectedReportTpl] = useState<string | null>(null);
  const [reportMeta, setReportMeta] = useState({ project_name: '', check_date: '', checker: '', reviewer: '' });
  const [generating, setGenerating] = useState(false);
  const [reportPath, setReportPath] = useState<string | null>(null);

  const fetchDashboard = async () => {
    try {
      const r = await fetch('/api/qc/dashboard', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setDashboard(d); }
    } catch { /* ignore */ }
  };

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

  const fetchReportTemplates = async () => {
    try {
      const r = await fetch('/api/reports/templates', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setReportTemplates(d.templates || []); }
    } catch { /* ignore */ }
  };

  const generateReport = async () => {
    const tpl = reportTemplates.find(t => t.id === selectedReportTpl);
    if (!tpl) return;
    setGenerating(true);
    setReportPath(null);
    try {
      const sectionData: Record<string, string> = {};
      for (const s of tpl.sections) { sectionData[s] = ''; }
      const r = await fetch('/api/reports/generate', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section_data: sectionData, metadata: reportMeta }),
      });
      if (r.ok) {
        const d = await r.json();
        setReportPath(d.path || null);
      } else {
        const d = await r.json();
        alert(d.error || '报告生成失败');
      }
    } catch { alert('网络错误'); }
    finally { setGenerating(false); }
  };

  useEffect(() => {
    Promise.all([fetchDashboard(), fetchTemplates(), fetchTaxonomy(), fetchReviews(), fetchReportTemplates()]).finally(() => setLoading(false));
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

  const handleQuickExecute = (templateId: string) => {
    setQuickExecTemplate(templateId);
    setShowFilePicker(true);
  };

  const handleFileSelected = async (filePath: string) => {
    setShowFilePicker(false);
    if (!quickExecTemplate) return;

    try {
      const r = await fetch('/api/workflows/from-template-and-execute', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_id: quickExecTemplate, parameters: { file_path: filePath } }),
      });
      if (r.ok) {
        const data = await r.json();
        alert(`工作流已创建并开始执行\nID: ${data.workflow_id}\nRun: ${data.run_id || 'N/A'}\n请前往"编排→工作流"查看实时进度`);
      } else {
        const d = await r.json();
        alert(d.error || '执行失败');
      }
    } catch { alert('网络错误'); }
    finally { setQuickExecTemplate(null); }
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
        {(['dashboard', 'templates', 'taxonomy', 'reviews', 'report'] as const).map(s => (
          <button key={s} onClick={() => setSection(s)}
            style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: section === s ? '#1e3a5f' : '#111827',
              color: section === s ? '#7dd3fc' : '#888',
              border: `1px solid ${section === s ? '#2563eb' : '#333'}`,
            }}>
            {s === 'dashboard' ? '概览' : s === 'templates' ? '模板' : s === 'taxonomy' ? '缺陷分类' : s === 'reviews' ? '复核' : '报告'}
          </button>
        ))}
      </div>

      {/* Dashboard */}
      {section === 'dashboard' && (
        <div>
          {/* Stat cards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8, marginBottom: 16 }}>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#7dd3fc' }}>{dashboard?.templates.count || 0}</div>
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>质检模板</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#fb8c00' }}>{dashboard?.reviews.pending || 0}</div>
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>待复核</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#10b981' }}>{dashboard?.workflows.running || 0}</div>
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>运行中工作流</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#e53935' }}>{dashboard?.alerts.recent_alerts || 0}</div>
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>近期告警</div>
            </div>
          </div>

          {/* Recent Reviews */}
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10, color: '#e0e0e0' }}>最近复核</div>
            {dashboard?.recent_reviews && dashboard.recent_reviews.length > 0 ? (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead><tr style={{ background: '#1f2937' }}>
                  <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>文件</th>
                  <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>缺陷码</th>
                  <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>严重度</th>
                  <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>状态</th>
                  <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>创建时间</th>
                </tr></thead>
                <tbody>
                  {dashboard.recent_reviews.map(r => {
                    const ss = statusStyle(r.status);
                    return (
                      <tr key={r.id}>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.file_path}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', fontFamily: 'monospace', color: '#7dd3fc' }}>{r.defect_code}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                          <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(r.severity), color: 'white' }}>{r.severity}</span>
                        </td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                          <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: ss.bg, color: ss.color }}>{r.status}</span>
                        </td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#aaa' }}>{new Date(r.created_at).toLocaleString('zh-CN')}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div style={{ color: '#888', fontSize: 12, textAlign: 'center', padding: 12 }}>暂无复核记录</div>
            )}
          </div>

          {/* Workflow Stats */}
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10, color: '#e0e0e0' }}>工作流统计</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11, color: '#888' }}>
                  <span>已完成</span>
                  <span>{dashboard?.workflows.completed || 0}</span>
                </div>
                <div style={{ height: 8, background: '#1f2937', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: '#10b981', width: `${dashboard?.workflows.total ? (dashboard.workflows.completed / dashboard.workflows.total * 100) : 0}%` }} />
                </div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11, color: '#888' }}>
                  <span>运行中</span>
                  <span>{dashboard?.workflows.running || 0}</span>
                </div>
                <div style={{ height: 8, background: '#1f2937', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: '#3b82f6', width: `${dashboard?.workflows.total ? (dashboard.workflows.running / dashboard.workflows.total * 100) : 0}%` }} />
                </div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11, color: '#888' }}>
                  <span>失败</span>
                  <span>{dashboard?.workflows.failed || 0}</span>
                </div>
                <div style={{ height: 8, background: '#1f2937', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: '#e53935', width: `${dashboard?.workflows.total ? (dashboard.workflows.failed / dashboard.workflows.total * 100) : 0}%` }} />
                </div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11, color: '#888' }}>
                  <span>SLA违规</span>
                  <span>{dashboard?.workflows.sla_violated || 0}</span>
                </div>
                <div style={{ height: 8, background: '#1f2937', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: '#fb8c00', width: `${dashboard?.workflows.total ? (dashboard.workflows.sla_violated / dashboard.workflows.total * 100) : 0}%` }} />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

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
                <div style={{ display: 'flex', gap: 6 }}>
                  <button onClick={() => createFromTemplate(t.id)} style={{
                    padding: '4px 12px', borderRadius: 4, border: 'none',
                    background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12,
                  }}>创建工作流</button>
                  <button onClick={() => handleQuickExecute(t.id)} style={{
                    padding: '4px 12px', borderRadius: 4, border: 'none',
                    background: '#16a34a', color: 'white', cursor: 'pointer', fontSize: 12,
                  }}>上传并执行</button>
                </div>
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

      {/* Report generation */}
      {section === 'report' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>质检报告生成</div>
          {/* Template selection */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10, marginBottom: 12 }}>
            {reportTemplates.map(t => (
              <div key={t.id} onClick={() => { setSelectedReportTpl(t.id); setReportPath(null); }}
                style={{
                  background: selectedReportTpl === t.id ? '#1e3a5f' : '#111827',
                  border: `1px solid ${selectedReportTpl === t.id ? '#2563eb' : '#1f2937'}`,
                  borderRadius: 6, padding: 12, cursor: 'pointer',
                }}>
                <div style={{ fontWeight: 600, fontSize: 13, color: selectedReportTpl === t.id ? '#7dd3fc' : '#e0e0e0', marginBottom: 4 }}>{t.name}</div>
                <div style={{ fontSize: 11, color: '#888' }}>{t.description}</div>
                <div style={{ fontSize: 10, color: '#666', marginTop: 4 }}>{t.sections.length} 个章节</div>
              </div>
            ))}
            {reportTemplates.length === 0 && <div style={{ color: '#888', fontSize: 12 }}>暂无报告模板</div>}
          </div>

          {/* Metadata form + generate */}
          {selectedReportTpl && (
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e0e0e0', marginBottom: 8 }}>报告元数据</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
                <div>
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>项目名称</div>
                  <input value={reportMeta.project_name} onChange={e => setReportMeta({ ...reportMeta, project_name: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>检查日期</div>
                  <input value={reportMeta.check_date} onChange={e => setReportMeta({ ...reportMeta, check_date: e.target.value })}
                    placeholder="2026年04月02日"
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>检查员</div>
                  <input value={reportMeta.checker} onChange={e => setReportMeta({ ...reportMeta, checker: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>审核员</div>
                  <input value={reportMeta.reviewer} onChange={e => setReportMeta({ ...reportMeta, reviewer: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
              </div>
              <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>
                章节: {reportTemplates.find(t => t.id === selectedReportTpl)?.sections.join(' / ')}
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={generateReport} disabled={generating}
                  style={{
                    padding: '6px 16px', borderRadius: 4, border: 'none', fontSize: 12, cursor: generating ? 'not-allowed' : 'pointer',
                    background: generating ? '#555' : '#1a73e8', color: 'white',
                  }}>
                  {generating ? '生成中...' : '生成报告'}
                </button>
                {reportPath && (
                  <a href={`/api/files/download?path=${encodeURIComponent(reportPath)}`} target="_blank" rel="noreferrer"
                    style={{ fontSize: 12, color: '#10b981', textDecoration: 'underline' }}>
                    下载报告
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      <FilePickerDialog
        open={showFilePicker}
        onSelect={handleFileSelected}
        onCancel={() => { setShowFilePicker(false); setQuickExecTemplate(null); }}
      />
    </div>
  );
}
