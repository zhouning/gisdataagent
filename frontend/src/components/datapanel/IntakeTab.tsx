import { useState, useEffect } from 'react';

interface IntakeJob {
  id: number;
  source_type: string;
  source_ref: string;
  status: string;
  tables_found: number;
  started_at: string;
  finished_at: string | null;
}

interface DatasetProfile {
  id: number;
  table_name: string;
  row_count: number;
  geometry_type: string | null;
  status: string;
  created_at: string;
}

interface SemanticDraft {
  id: number;
  table_name: string;
  version: number;
  display_name: string;
  description: string;
  confidence: number;
  status: string;
  columns_draft: any[];
  join_candidates: any[];
  reviewed_by: string | null;
}

export default function IntakeTab() {
  const [jobs, setJobs] = useState<IntakeJob[]>([]);
  const [profiles, setProfiles] = useState<DatasetProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<number | null>(null);
  const [draft, setDraft] = useState<SemanticDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<any>(null);
  const [activating, setActivating] = useState(false);
  const [message, setMessage] = useState('');

  const fetchProfiles = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/intake/profiles', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setProfiles(d.profiles || []); }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchProfiles(); }, []);

  const handleScan = async () => {
    setScanning(true);
    setMessage('');
    try {
      const r = await fetch('/api/intake/scan', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema: 'public' }),
      });
      const d = await r.json();
      if (d.status === 'ok') {
        setMessage(`扫描完成：发现 ${d.tables_found} 张表`);
        fetchProfiles();
      } else {
        setMessage(`扫描失败：${d.error || '未知错误'}`);
      }
    } catch (e: any) { setMessage(`扫描异常：${e.message}`); }
    finally { setScanning(false); }
  };

  const handleGenerateDraft = async (profileId: number) => {
    setMessage('');
    try {
      const r = await fetch(`/api/intake/${profileId}/draft`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ use_llm: true }),
      });
      const d = await r.json();
      if (d.status === 'ok') {
        setMessage(`草稿生成完成：${d.table_name} v${d.version} (置信度 ${d.confidence})`);
        fetchProfiles();
      } else {
        setMessage(`草稿生成失败：${d.error || '未知错误'}`);
      }
    } catch (e: any) { setMessage(`异常：${e.message}`); }
  };

  const handleValidate = async (profileId: number) => {
    setValidating(true);
    setValidationResult(null);
    setMessage('');
    try {
      const r = await fetch(`/api/intake/${profileId}/validate`, {
        method: 'POST', credentials: 'include',
      });
      const d = await r.json();
      setValidationResult(d);
      if (d.passed) {
        setMessage(`验证通过：${d.table_name} 得分 ${(d.eval_score * 100).toFixed(0)}%`);
      } else {
        setMessage(`验证未通过：得分 ${(d.eval_score * 100).toFixed(0)}% (需要 ≥80%)`);
      }
      fetchProfiles();
    } catch (e: any) { setMessage(`验证异常：${e.message}`); }
    finally { setValidating(false); }
  };

  const handleActivate = async (draftId: number, evalScore: number) => {
    setActivating(true);
    setMessage('');
    try {
      const r = await fetch(`/api/intake/${draftId}/activate`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ eval_score: evalScore }),
      });
      const d = await r.json();
      if (d.status === 'ok') {
        setMessage(`已激活：${d.table_name} v${d.version}`);
        fetchProfiles();
      } else {
        setMessage(`激活失败：${d.error || '未知错误'}`);
      }
    } catch (e: any) { setMessage(`激活异常：${e.message}`); }
    finally { setActivating(false); }
  };

  const handleRollback = async (datasetId: number) => {
    setMessage('');
    try {
      const r = await fetch(`/api/intake/${datasetId}/rollback`, {
        method: 'POST', credentials: 'include',
      });
      const d = await r.json();
      setMessage(d.status === 'ok' ? '已回滚' : `回滚失败：${d.error}`);
      fetchProfiles();
    } catch (e: any) { setMessage(`回滚异常：${e.message}`); }
  };

  const statusColor = (s: string) => {
    switch (s) {
      case 'active': return '#22c55e';
      case 'validated': return '#3b82f6';
      case 'reviewed': return '#f59e0b';
      case 'drafted': return '#a78bfa';
      default: return '#94a3b8';
    }
  };

  return (
    <div style={{ padding: '12px', fontSize: '13px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: '14px' }}>数据接入管理</h3>
        <button
          onClick={handleScan}
          disabled={scanning}
          style={{ padding: '4px 12px', fontSize: '12px', cursor: scanning ? 'wait' : 'pointer',
                   background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 4 }}
        >
          {scanning ? '扫描中...' : '扫描新表'}
        </button>
      </div>

      {message && (
        <div style={{ padding: '6px 10px', marginBottom: 10, borderRadius: 4,
                       background: message.includes('失败') || message.includes('异常') ? '#fef2f2' : '#f0fdf4',
                       color: message.includes('失败') || message.includes('异常') ? '#dc2626' : '#16a34a',
                       fontSize: '12px' }}>
          {message}
        </div>
      )}

      {loading ? <div>加载中...</div> : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #e2e8f0', textAlign: 'left' }}>
              <th style={{ padding: '6px 4px' }}>表名</th>
              <th style={{ padding: '6px 4px' }}>行数</th>
              <th style={{ padding: '6px 4px' }}>几何</th>
              <th style={{ padding: '6px 4px' }}>状态</th>
              <th style={{ padding: '6px 4px' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map(p => (
              <tr key={p.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '6px 4px', fontFamily: 'monospace' }}>{p.table_name}</td>
                <td style={{ padding: '6px 4px' }}>{p.row_count?.toLocaleString()}</td>
                <td style={{ padding: '6px 4px' }}>{p.geometry_type || '—'}</td>
                <td style={{ padding: '6px 4px' }}>
                  <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: '11px',
                                  background: statusColor(p.status) + '22', color: statusColor(p.status) }}>
                    {p.status}
                  </span>
                </td>
                <td style={{ padding: '6px 4px' }}>
                  {p.status === 'discovered' && (
                    <button onClick={() => handleGenerateDraft(p.id)}
                            style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer',
                                     background: '#a78bfa', color: '#fff', border: 'none', borderRadius: 3 }}>
                      生成草稿
                    </button>
                  )}
                  {p.status === 'drafted' && (
                    <button onClick={() => handleValidate(p.id)}
                            disabled={validating}
                            style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer',
                                     background: '#f59e0b', color: '#fff', border: 'none', borderRadius: 3 }}>
                      {validating ? '验证中...' : '验证'}
                    </button>
                  )}
                  {p.status === 'reviewed' && (
                    <button onClick={() => handleValidate(p.id)}
                            disabled={validating}
                            style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer',
                                     background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 3 }}>
                      {validating ? '验证中...' : '验证并激活'}
                    </button>
                  )}
                  {p.status === 'active' && (
                    <button onClick={() => handleRollback(p.id)}
                            style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer',
                                     background: '#ef4444', color: '#fff', border: 'none', borderRadius: 3 }}>
                      回滚
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {profiles.length === 0 && (
              <tr><td colSpan={5} style={{ padding: 16, textAlign: 'center', color: '#94a3b8' }}>
                暂无数据集。点击"扫描新表"开始接入。
              </td></tr>
            )}
          </tbody>
        </table>
      )}

      {validationResult && (
        <div style={{ marginTop: 12, padding: 10, background: '#f8fafc', borderRadius: 4, fontSize: '12px' }}>
          <strong>验证结果：{validationResult.table_name}</strong>
          <span style={{ marginLeft: 8, color: validationResult.passed ? '#16a34a' : '#dc2626' }}>
            {(validationResult.eval_score * 100).toFixed(0)}% ({validationResult.passed_count}/{validationResult.total})
          </span>
          <div style={{ marginTop: 6 }}>
            {(validationResult.details || []).map((d: any, i: number) => (
              <div key={i} style={{ padding: '2px 0', color: d.passed ? '#16a34a' : '#dc2626' }}>
                {d.passed ? '✓' : '✗'} [{d.type}] {d.question?.substring(0, 60)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
