import { useState, useEffect } from 'react';
import WorkflowEditor from '../WorkflowEditor';
import FilePickerDialog from './FilePickerDialog';
import { getPipelineLabel, formatTime } from './utils';

interface WorkflowSummary {
  id: number;
  workflow_name: string;
  description: string;
  owner_username: string;
  is_shared: boolean;
  pipeline_type: string;
  cron_schedule: string | null;
  use_count: number;
  created_at: string;
}

interface WorkflowRunSummary {
  id: number;
  status: string;
  total_duration: number;
  total_input_tokens: number;
  total_output_tokens: number;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
  step_results: Array<{
    node_id?: string;
    step_id?: string;
    label?: string;
    status?: string;
    duration?: number;
    output?: string;
    summary?: string;
    error?: string;
    files?: string[];
    [key: string]: any;
  }>;
}

export default function WorkflowsTab() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editWorkflow, setEditWorkflow] = useState<any>(null);
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [viewRunsFor, setViewRunsFor] = useState<number | null>(null);
  const [expandedRun, setExpandedRun] = useState<number | null>(null);
  const [executing, setExecuting] = useState<number | null>(null);
  const [liveRunId, setLiveRunId] = useState<number | null>(null);
  const [liveStatus, setLiveStatus] = useState<any>(null);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [executeTarget, setExecuteTarget] = useState<number | null>(null);

  const fetchWorkflows = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/workflows', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setWorkflows(data.workflows || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchWorkflows(); }, []);

  const handleCreate = () => {
    setEditWorkflow(null);
    setEditing(true);
  };

  const handleEdit = async (id: number) => {
    try {
      const resp = await fetch(`/api/workflows/${id}`, { credentials: 'include' });
      if (resp.ok) {
        setEditWorkflow(await resp.json());
        setEditing(true);
      }
    } catch { /* ignore */ }
  };

  const handleSave = async (wf: any) => {
    try {
      if (wf.id) {
        await fetch(`/api/workflows/${wf.id}`, {
          method: 'PUT',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(wf),
        });
      } else {
        await fetch('/api/workflows', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(wf),
        });
      }
    } catch { /* ignore */ }
    setEditing(false);
    setEditWorkflow(null);
    fetchWorkflows();
  };

  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`确定删除工作流「${name}」？`)) return;
    try {
      await fetch(`/api/workflows/${id}`, { method: 'DELETE', credentials: 'include' });
    } catch { /* ignore */ }
    fetchWorkflows();
  };

  const handleExecute = async (id: number) => {
    setExecuteTarget(id);
    setShowFilePicker(true);
  };

  const handleFileSelected = async (filePath: string) => {
    setShowFilePicker(false);
    if (!executeTarget) return;

    setExecuting(executeTarget);
    setLiveStatus(null);
    try {
      const resp = await fetch(`/api/workflows/${executeTarget}/execute`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameters: { file_path: filePath } }),
      });
      if (resp.ok) {
        const data = await resp.json();
        const runId = data.run_id;
        if (runId) {
          setLiveRunId(runId);
          const pollId = setInterval(async () => {
            try {
              const statusResp = await fetch(`/api/workflows/${executeTarget}/runs/${runId}/status`, { credentials: 'include' });
              if (statusResp.ok) {
                const statusData = await statusResp.json();
                setLiveStatus(statusData);
                if (statusData.status === 'completed' || statusData.status === 'failed') {
                  clearInterval(pollId);
                  setExecuting(null);
                  setLiveRunId(null);
                  fetchWorkflows();
                  // Keep liveStatus visible for 8 seconds after completion
                  setTimeout(() => setLiveStatus(null), 8000);
                }
              }
              // On 404, run may not have started yet — keep polling
            } catch {
              clearInterval(pollId);
              setExecuting(null);
              setLiveRunId(null);
            }
          }, 2000);
          return;
        }
      }
    } catch { /* ignore */ }
    finally {
      if (!liveRunId) {
        setExecuting(null);
        fetchWorkflows();
      }
    }
  };

  const handleViewRuns = async (id: number) => {
    setViewRunsFor(id);
    try {
      const resp = await fetch(`/api/workflows/${id}/runs?limit=10`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setRuns(data.runs || []);
      }
    } catch { /* ignore */ }
  };

  if (editing) {
    return (
      <WorkflowEditor
        workflow={editWorkflow}
        onSave={handleSave}
        onCancel={() => { setEditing(false); setEditWorkflow(null); }}
      />
    );
  }

  if (viewRunsFor !== null) {
    const wf = workflows.find((w) => w.id === viewRunsFor);
    return (
      <div className="workflow-runs-view">
        <button className="asset-back-btn" onClick={() => { setViewRunsFor(null); setRuns([]); setExpandedRun(null); }}>
          &larr; 返回列表
        </button>
        <h4>{wf?.workflow_name} — 执行历史</h4>
        {runs.length === 0 ? (
          <div className="empty-state">暂无执行记录</div>
        ) : (
          <div className="workflow-runs-list">
            {runs.map((r) => (
              <div key={r.id} className={`workflow-run-item ${r.status}`}>
                <div
                  className="workflow-run-header"
                  style={{ cursor: 'pointer' }}
                  onClick={() => setExpandedRun(expandedRun === r.id ? null : r.id)}
                >
                  <span className={`workflow-run-status ${r.status}`}>{r.status}</span>
                  <span className="workflow-run-time">{formatTime(r.started_at)}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 11, color: '#9ca3af' }}>
                    {expandedRun === r.id ? '▼' : '▶'} {r.step_results?.length || 0} 步
                  </span>
                </div>
                <div className="workflow-run-detail">
                  <span>{r.total_duration?.toFixed(1)}s</span>
                  <span>{(r.total_input_tokens + r.total_output_tokens).toLocaleString()} tokens</span>
                  {r.completed_at && <span>完成: {formatTime(r.completed_at)}</span>}
                </div>
                {r.error_message && (
                  <div className="workflow-run-error">{r.error_message}</div>
                )}
                {/* Expanded step details */}
                {expandedRun === r.id && r.step_results && r.step_results.length > 0 && (
                  <div style={{ marginTop: 8, borderTop: '1px solid #e5e7eb', paddingTop: 8 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6, color: '#374151' }}>步骤详情</div>
                    {r.step_results.map((step, idx) => (
                      <div key={idx} style={{
                        display: 'flex', flexDirection: 'column', gap: 2,
                        padding: '6px 8px', marginBottom: 4,
                        background: step.status === 'completed' ? '#f0fdf4' : step.status === 'failed' ? '#fef2f2' : '#f9fafb',
                        borderRadius: 4, fontSize: 11, borderLeft: `3px solid ${step.status === 'completed' ? '#22c55e' : step.status === 'failed' ? '#ef4444' : '#d1d5db'}`,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ fontWeight: 600 }}>
                            {idx + 1}. {step.label || step.node_id || `步骤 ${idx + 1}`}
                          </span>
                          <span style={{ color: step.status === 'completed' ? '#16a34a' : step.status === 'failed' ? '#dc2626' : '#6b7280' }}>
                            {step.status || 'unknown'}
                          </span>
                          {step.duration != null && (
                            <span style={{ color: '#6b7280' }}>{step.duration.toFixed(1)}s</span>
                          )}
                        </div>
                        {(step.summary || step.output) && (
                          <div style={{
                            marginTop: 4, padding: '4px 6px', background: '#fff', borderRadius: 3,
                            maxHeight: 120, overflowY: 'auto', whiteSpace: 'pre-wrap', fontSize: 10,
                            color: '#374151', border: '1px solid #e5e7eb',
                          }}>
                            {typeof (step.summary || step.output) === 'string' ? (step.summary || step.output) : JSON.stringify((step.summary || step.output), null, 2)}
                          </div>
                        )}
                        {step.files && step.files.length > 0 && (
                          <div style={{ marginTop: 4, fontSize: 10, color: '#0d9488' }}>
                            生成文件: {step.files.join(', ')}
                          </div>
                        )}
                        {step.error && (
                          <div style={{ marginTop: 4, color: '#dc2626', fontSize: 10 }}>
                            错误: {step.error}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {expandedRun === r.id && (!r.step_results || r.step_results.length === 0) && (
                  <div style={{ marginTop: 8, fontSize: 11, color: '#9ca3af', fontStyle: 'italic' }}>
                    无步骤详情记录
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="workflows-view">
      <div className="workflows-header">
        <button className="btn-primary btn-sm" onClick={handleCreate}>+ 新建工作流</button>
      </div>
      {loading && workflows.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : workflows.length === 0 ? (
        <div className="empty-state">暂无工作流<br />点击上方按钮创建</div>
      ) : (
        <div className="workflow-list">
          {/* Live execution status panel */}
          {liveStatus && (
            <div className="workflow-live-status">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div style={{ fontSize: 12, fontWeight: 600 }}>
                  {liveStatus.status === 'completed' ? 'v 已完成' : liveStatus.status === 'failed' ? 'x 执行失败' : '>> 执行中...'} (Run #{liveRunId || ''})
                </div>
                <div style={{ fontSize: 11, color: '#6b7280' }}>
                  {liveStatus.elapsed ? `${liveStatus.elapsed.toFixed(0)}s` : ''}
                </div>
              </div>

              {/* Progress bar */}
              {liveStatus.nodes && (() => {
                const nodes = Object.values(liveStatus.nodes);
                const completed = nodes.filter((n: any) => n.status === 'completed').length;
                const total = nodes.length;
                const progress = total > 0 ? (completed / total) * 100 : 0;
                return (
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginBottom: 4 }}>
                      <span>进度: {completed}/{total} 步骤</span>
                      <span>{progress.toFixed(0)}%</span>
                    </div>
                    <div style={{ height: 4, background: '#e5e7eb', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ height: '100%', background: 'linear-gradient(90deg, #0d9488, #14b8a6)', width: `${progress}%`, transition: 'width 0.3s ease' }} />
                    </div>
                  </div>
                );
              })()}

              {/* Step list */}
              {liveStatus.nodes && Object.entries(liveStatus.nodes).map(([nodeId, node]: [string, any]) => (
                <div key={nodeId} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, padding: '3px 0' }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                    background: node.status === 'completed' ? '#22c55e' : node.status === 'running' ? '#0d9488' : node.status === 'failed' ? '#ef4444' : '#d1d5db',
                  }} />
                  <span style={{ fontWeight: 500, flex: 1 }}>{node.label || nodeId}</span>
                  {node.duration && <span style={{ color: '#6b7280' }}>{node.duration.toFixed(1)}s</span>}
                </div>
              ))}
            </div>
          )}

          {workflows.map((wf) => (
            <div key={wf.id} className="workflow-card">
              <div className="workflow-card-header">
                <span className="workflow-card-name">{wf.workflow_name}</span>
                {wf.cron_schedule && (
                  <span className="workflow-cron-badge" title={`Cron: ${wf.cron_schedule}`}>定时</span>
                )}
              </div>
              {wf.description && (
                <div className="workflow-card-desc">{wf.description}</div>
              )}
              <div className="workflow-card-meta">
                <span className={`pipeline-badge ${wf.pipeline_type}`}>
                  {getPipelineLabel(wf.pipeline_type)}
                </span>
                <span>执行 {wf.use_count} 次</span>
              </div>
              <div className="workflow-card-actions">
                <button onClick={() => handleExecute(wf.id)} disabled={executing === wf.id}>
                  {executing === wf.id ? '执行中...' : '执行'}
                </button>
                <button onClick={() => handleEdit(wf.id)}>编辑</button>
                <button onClick={() => handleViewRuns(wf.id)}>历史</button>
                <button className="btn-danger" onClick={() => handleDelete(wf.id, wf.workflow_name)}>
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <FilePickerDialog
        open={showFilePicker}
        onSelect={handleFileSelected}
        onCancel={() => { setShowFilePicker(false); setExecuteTarget(null); }}
      />
    </div>
  );
}