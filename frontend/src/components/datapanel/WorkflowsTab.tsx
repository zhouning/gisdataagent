import { useState, useEffect } from 'react';
import WorkflowEditor from '../WorkflowEditor';
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
  error_message: string | null;
}

export default function WorkflowsTab() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editWorkflow, setEditWorkflow] = useState<any>(null);
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [viewRunsFor, setViewRunsFor] = useState<number | null>(null);
  const [executing, setExecuting] = useState<number | null>(null);
  const [liveRunId, setLiveRunId] = useState<number | null>(null);
  const [liveStatus, setLiveStatus] = useState<any>(null);

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
    setExecuting(id);
    setLiveStatus(null);
    try {
      const resp = await fetch(`/api/workflows/${id}/execute`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameters: {} }),
      });
      if (resp.ok) {
        const data = await resp.json();
        const runId = data.run_id;
        if (runId) {
          setLiveRunId(runId);
          // Poll live status every 2s
          const pollId = setInterval(async () => {
            try {
              const statusResp = await fetch(`/api/workflows/${id}/runs/${runId}/status`, { credentials: 'include' });
              if (statusResp.ok) {
                const statusData = await statusResp.json();
                setLiveStatus(statusData);
                if (statusData.status === 'completed' || statusData.status === 'failed') {
                  clearInterval(pollId);
                  setExecuting(null);
                  setLiveRunId(null);
                  fetchWorkflows();
                }
              } else {
                // Run finished (404 = already completed, removed from live cache)
                clearInterval(pollId);
                setExecuting(null);
                setLiveRunId(null);
                setLiveStatus(null);
                fetchWorkflows();
              }
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
      // Fallback: if no run_id returned, reset immediately
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
        <button className="asset-back-btn" onClick={() => { setViewRunsFor(null); setRuns([]); }}>
          &larr; 返回列表
        </button>
        <h4>{wf?.workflow_name} — 执行历史</h4>
        {runs.length === 0 ? (
          <div className="empty-state">暂无执行记录</div>
        ) : (
          <div className="workflow-runs-list">
            {runs.map((r) => (
              <div key={r.id} className={`workflow-run-item ${r.status}`}>
                <div className="workflow-run-header">
                  <span className={`workflow-run-status ${r.status}`}>{r.status}</span>
                  <span className="workflow-run-time">{formatTime(r.started_at)}</span>
                </div>
                <div className="workflow-run-detail">
                  <span>{r.total_duration?.toFixed(1)}s</span>
                  <span>{(r.total_input_tokens + r.total_output_tokens).toLocaleString()} tokens</span>
                </div>
                {r.error_message && (
                  <div className="workflow-run-error">{r.error_message}</div>
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
          {liveStatus && executing && (
            <div className="workflow-live-status">
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                ▶ 执行中... (Run #{liveRunId})
              </div>
              {liveStatus.nodes && Object.entries(liveStatus.nodes).map(([nodeId, node]: [string, any]) => (
                <div key={nodeId} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, padding: '3px 0' }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                    background: node.status === 'completed' ? '#22c55e' : node.status === 'running' ? '#0d9488' : node.status === 'failed' ? '#ef4444' : '#d1d5db',
                  }} />
                  <span style={{ fontWeight: 500 }}>{node.label || nodeId}</span>
                  <span style={{ color: '#9ca3af' }}>{node.status}</span>
                  {node.duration && <span style={{ color: '#6b7280' }}>{node.duration.toFixed(1)}s</span>}
                </div>
              ))}
              {liveStatus.overall_status && (
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                  总状态: {liveStatus.overall_status} | 耗时: {liveStatus.elapsed?.toFixed(1) || '?'}s
                </div>
              )}
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
    </div>
  );
}