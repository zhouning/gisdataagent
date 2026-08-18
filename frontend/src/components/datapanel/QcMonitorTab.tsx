import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';
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
  const { t } = useTranslation();
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
      const r = await fetch('/api/qc/dashboard', { credentials: 'include', headers: getLocaleHeaders() });
      if (r.ok) { const d = await r.json(); setDashboard(d); }
    } catch { /* ignore */ }
  };

  const fetchTemplates = async () => {
    try {
      const r = await fetch('/api/workflows/qc-templates', { credentials: 'include', headers: getLocaleHeaders() });
      if (r.ok) { const d = await r.json(); setTemplates(d.templates || []); }
    } catch { /* ignore */ }
  };

  const fetchTaxonomy = async () => {
    try {
      const r = await fetch('/api/defect-taxonomy', { credentials: 'include', headers: getLocaleHeaders() });
      if (r.ok) {
        const d = await r.json();
        setCategories(d.categories || []);
        setDefects(d.defects || []);
      }
    } catch { /* ignore */ }
  };

  const fetchReviews = async () => {
    try {
      const r = await fetch('/api/qc/reviews', { credentials: 'include', headers: getLocaleHeaders() });
      if (r.ok) { const d = await r.json(); setReviews(d.reviews || []); }
    } catch { /* ignore */ }
  };

  const fetchReportTemplates = async () => {
    try {
      const r = await fetch('/api/reports/templates', { credentials: 'include', headers: getLocaleHeaders() });
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
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ section_data: sectionData, metadata: reportMeta }),
      });
      if (r.ok) {
        const d = await r.json();
        setReportPath(d.path || null);
      } else {
        const d = await r.json();
        alert(d.error || t('qcMonitor.errors.generateReport'));
      }
    } catch { alert(t('qcMonitor.errors.network')); }
    finally { setGenerating(false); }
  };

  useEffect(() => {
    Promise.all([fetchDashboard(), fetchTemplates(), fetchTaxonomy(), fetchReviews(), fetchReportTemplates()]).finally(() => setLoading(false));
  }, []);

  const createFromTemplate = async (templateId: string) => {
    try {
      const r = await fetch('/api/workflows/from-template', {
        method: 'POST', credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_id: templateId }),
      });
      if (r.ok) { alert(t('qcMonitor.messages.workflowCreated')); }
      else { const d = await r.json(); alert(d.error || t('qcMonitor.errors.create')); }
    } catch { alert(t('qcMonitor.errors.network')); }
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
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_id: quickExecTemplate, parameters: { file_path: filePath } }),
      });
      if (r.ok) {
        const data = await r.json();
        alert(t('qcMonitor.messages.workflowRunning', { workflowId: data.workflow_id, runId: data.run_id || 'N/A' }));
      } else {
        const d = await r.json();
        alert(d.error || t('qcMonitor.errors.execute'));
      }
    } catch { alert(t('qcMonitor.errors.network')); }
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

  const statusLabel = (status: string) => {
    const key = ({
      pending: 'pending',
      in_review: 'inReview',
      fixed: 'fixed',
      approved: 'approved',
      rejected: 'rejected',
    } as Record<string, string>)[status];
    return key ? t(`qcMonitor.status.${key}`) : status;
  };

  const pendingCount = reviews.filter(r => r.status === 'pending').length;
  const fixedCount = reviews.filter(r => r.status === 'fixed').length;
  const approvedCount = reviews.filter(r => r.status === 'approved').length;

  if (loading) return <div style={{ padding: 12, color: '#888' }}>{t('qcMonitor.common.loading')}</div>;

  return (
    <div style={{ padding: 12 }}>
      {/* Summary bar */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#7dd3fc' }}>{formatNumber(reviews.length)}</div>
          <div style={{ color: '#888', fontSize: 11 }}>{t('qcMonitor.summary.totalReviews')}</div>
        </div>
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#fb8c00' }}>{formatNumber(pendingCount)}</div>
          <div style={{ color: '#888', fontSize: 11 }}>{t('qcMonitor.summary.pending')}</div>
        </div>
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#43a047' }}>{formatNumber(fixedCount)}</div>
          <div style={{ color: '#888', fontSize: 11 }}>{t('qcMonitor.summary.fixed')}</div>
        </div>
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#10b981' }}>{formatNumber(approvedCount)}</div>
          <div style={{ color: '#888', fontSize: 11 }}>{t('qcMonitor.summary.approved')}</div>
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
            {t(`qcMonitor.tabs.${s}`)}
          </button>
        ))}
      </div>

      {/* Dashboard */}
      {section === 'dashboard' && (
        <div>
          {/* Stat cards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8, marginBottom: 16 }}>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#7dd3fc' }}>{formatNumber(dashboard?.templates.count || 0)}</div>
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{t('qcMonitor.dashboard.templates')}</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#fb8c00' }}>{formatNumber(dashboard?.reviews.pending || 0)}</div>
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{t('qcMonitor.dashboard.pendingReviews')}</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#10b981' }}>{formatNumber(dashboard?.workflows.running || 0)}</div>
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{t('qcMonitor.dashboard.runningWorkflows')}</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#e53935' }}>{formatNumber(dashboard?.alerts.recent_alerts || 0)}</div>
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{t('qcMonitor.dashboard.recentAlerts')}</div>
            </div>
          </div>

          {/* Recent Reviews */}
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10, color: '#e0e0e0' }}>{t('qcMonitor.dashboard.recentReviews')}</div>
            {dashboard?.recent_reviews && dashboard.recent_reviews.length > 0 ? (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead><tr style={{ background: '#1f2937' }}>
                  <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.file')}</th>
                  <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.defectCode')}</th>
                  <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.severity')}</th>
                  <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.status')}</th>
                  <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.createdAt')}</th>
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
                          <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: ss.bg, color: ss.color }}>{statusLabel(r.status)}</span>
                        </td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#aaa' }}>{formatDate(r.created_at, { dateStyle: 'medium', timeStyle: 'short' })}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div style={{ color: '#888', fontSize: 12, textAlign: 'center', padding: 12 }}>{t('qcMonitor.empty.recentReviews')}</div>
            )}
          </div>

          {/* Workflow Stats */}
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10, color: '#e0e0e0' }}>{t('qcMonitor.dashboard.workflowStats')}</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11, color: '#888' }}>
                  <span>{t('qcMonitor.workflow.completed')}</span>
                  <span>{formatNumber(dashboard?.workflows.completed || 0)}</span>
                </div>
                <div style={{ height: 8, background: '#1f2937', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: '#10b981', width: `${dashboard?.workflows.total ? (dashboard.workflows.completed / dashboard.workflows.total * 100) : 0}%` }} />
                </div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11, color: '#888' }}>
                  <span>{t('qcMonitor.workflow.running')}</span>
                  <span>{formatNumber(dashboard?.workflows.running || 0)}</span>
                </div>
                <div style={{ height: 8, background: '#1f2937', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: '#3b82f6', width: `${dashboard?.workflows.total ? (dashboard.workflows.running / dashboard.workflows.total * 100) : 0}%` }} />
                </div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11, color: '#888' }}>
                  <span>{t('qcMonitor.workflow.failed')}</span>
                  <span>{formatNumber(dashboard?.workflows.failed || 0)}</span>
                </div>
                <div style={{ height: 8, background: '#1f2937', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: '#e53935', width: `${dashboard?.workflows.total ? (dashboard.workflows.failed / dashboard.workflows.total * 100) : 0}%` }} />
                </div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11, color: '#888' }}>
                  <span>{t('qcMonitor.workflow.slaViolated')}</span>
                  <span>{formatNumber(dashboard?.workflows.sla_violated || 0)}</span>
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
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>{t('qcMonitor.sections.workflowTemplates')}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
            {templates.map(template => (
              <div key={template.id} style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12 }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4, color: '#e0e0e0' }}>{template.name}</div>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>{template.description}</div>
                <div style={{ fontSize: 11, color: '#666', marginBottom: 8 }}>{t('qcMonitor.templates.steps', { count: formatNumber(template.step_count) })}</div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button onClick={() => createFromTemplate(template.id)} style={{
                    padding: '4px 12px', borderRadius: 4, border: 'none',
                    background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12,
                  }}>{t('qcMonitor.actions.createWorkflow')}</button>
                  <button onClick={() => handleQuickExecute(template.id)} style={{
                    padding: '4px 12px', borderRadius: 4, border: 'none',
                    background: '#16a34a', color: 'white', cursor: 'pointer', fontSize: 12,
                  }}>{t('qcMonitor.actions.uploadAndRun')}</button>
                </div>
              </div>
            ))}
            {templates.length === 0 && <div style={{ color: '#888', fontSize: 12 }}>{t('qcMonitor.empty.templates')}</div>}
          </div>
        </div>
      )}

      {/* Taxonomy — collapsible categories with defect codes */}
      {section === 'taxonomy' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>{t('qcMonitor.sections.taxonomy')}</div>
          {categories.length === 0 && <div style={{ color: '#888', fontSize: 12 }}>{t('qcMonitor.empty.taxonomy')}</div>}
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
                    <span style={{ marginInlineStart: 8, fontSize: 11, color: '#888' }}>{cat.description}</span>
                  </div>
                  <span style={{ color: '#888', fontSize: 12 }}>{collapsed ? '+' : '-'} ({formatNumber(catDefects.length)})</span>
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
                          }}>{t('qcMonitor.taxonomy.autoFix')}</span>
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
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>{t('qcMonitor.sections.reviewManagement')}</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: '#1f2937' }}>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>ID</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.file')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.defectCode')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.severity')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.status')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('qcMonitor.table.assignee')}</th>
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
                      <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: ss.bg, color: ss.color }}>{statusLabel(r.status)}</span>
                    </td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#aaa' }}>{r.assigned_to || '-'}</td>
                  </tr>
                  {isExpanded && (
                    <tr key={`${r.id}-detail`}>
                      <td colSpan={6} style={{ padding: '8px 12px', background: '#0d1117', borderBottom: '1px solid #1f2937', fontSize: 12 }}>
                        <div style={{ marginBottom: 4 }}>
                          <span style={{ color: '#888' }}>{t('qcMonitor.reviews.comment')}: </span>
                          <span style={{ color: '#ccc' }}>{r.review_comment || t('qcMonitor.common.none')}</span>
                        </div>
                        <div>
                          <span style={{ color: '#888' }}>{t('qcMonitor.reviews.fixDescription')}: </span>
                          <span style={{ color: '#ccc' }}>{r.fix_description || t('qcMonitor.common.none')}</span>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}</tbody>
          </table>
          {reviews.length === 0 && <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>{t('qcMonitor.empty.reviews')}</div>}
        </div>
      )}

      {/* Report generation */}
      {section === 'report' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>{t('qcMonitor.sections.reportGeneration')}</div>
          {/* Template selection */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10, marginBottom: 12 }}>
            {reportTemplates.map(template => (
              <div key={template.id} onClick={() => { setSelectedReportTpl(template.id); setReportPath(null); }}
                style={{
                  background: selectedReportTpl === template.id ? '#1e3a5f' : '#111827',
                  border: `1px solid ${selectedReportTpl === template.id ? '#2563eb' : '#1f2937'}`,
                  borderRadius: 6, padding: 12, cursor: 'pointer',
                }}>
                <div style={{ fontWeight: 600, fontSize: 13, color: selectedReportTpl === template.id ? '#7dd3fc' : '#e0e0e0', marginBottom: 4 }}>{template.name}</div>
                <div style={{ fontSize: 11, color: '#888' }}>{template.description}</div>
                <div style={{ fontSize: 10, color: '#666', marginTop: 4 }}>{t('qcMonitor.report.sectionCount', { count: formatNumber(template.sections.length) })}</div>
              </div>
            ))}
            {reportTemplates.length === 0 && <div style={{ color: '#888', fontSize: 12 }}>{t('qcMonitor.empty.reportTemplates')}</div>}
          </div>

          {/* Metadata form + generate */}
          {selectedReportTpl && (
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e0e0e0', marginBottom: 8 }}>{t('qcMonitor.report.metadata')}</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
                <div>
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>{t('qcMonitor.report.projectName')}</div>
                  <input value={reportMeta.project_name} onChange={e => setReportMeta({ ...reportMeta, project_name: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>{t('qcMonitor.report.checkDate')}</div>
                  <input value={reportMeta.check_date} onChange={e => setReportMeta({ ...reportMeta, check_date: e.target.value })}
                    placeholder={t('qcMonitor.report.datePlaceholder')}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>{t('qcMonitor.report.checker')}</div>
                  <input value={reportMeta.checker} onChange={e => setReportMeta({ ...reportMeta, checker: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>{t('qcMonitor.report.reviewer')}</div>
                  <input value={reportMeta.reviewer} onChange={e => setReportMeta({ ...reportMeta, reviewer: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
              </div>
              <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>
                {t('qcMonitor.report.sections', { sections: reportTemplates.find(template => template.id === selectedReportTpl)?.sections.join(' / ') })}
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={generateReport} disabled={generating}
                  style={{
                    padding: '6px 16px', borderRadius: 4, border: 'none', fontSize: 12, cursor: generating ? 'not-allowed' : 'pointer',
                    background: generating ? '#555' : '#1a73e8', color: 'white',
                  }}>
                  {generating ? t('qcMonitor.actions.generating') : t('qcMonitor.actions.generateReport')}
                </button>
                {reportPath && (
                  <a href={`/api/files/download?path=${encodeURIComponent(reportPath)}`} target="_blank" rel="noreferrer"
                    style={{ fontSize: 12, color: '#10b981', textDecoration: 'underline' }}>
                    {t('qcMonitor.actions.downloadReport')}
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
