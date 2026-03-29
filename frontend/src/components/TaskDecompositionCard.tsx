import { useState } from 'react';

interface TaskNode {
  id: string;
  description: string;
  agent_hint: string;
  dependencies: string[];
  enabled: boolean;
}

interface TaskDecompositionCardProps {
  tasks: TaskNode[];
  onApprove: (tasks: TaskNode[]) => void;
  onCancel: () => void;
}

export default function TaskDecompositionCard({ tasks: initialTasks, onApprove, onCancel }: TaskDecompositionCardProps) {
  const [tasks, setTasks] = useState<TaskNode[]>(
    initialTasks.map(t => ({ ...t, enabled: true }))
  );

  const toggleTask = (id: string) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, enabled: !t.enabled } : t));
  };

  const updateDescription = (id: string, description: string) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, description } : t));
  };

  const handleApprove = () => {
    const enabled = tasks.filter(t => t.enabled);
    onApprove(enabled);
  };

  return (
    <div style={{ background: 'var(--surface)', padding: '16px', borderRadius: 'var(--radius-md)', marginBottom: '12px' }}>
      <h4 style={{ margin: '0 0 8px 0', fontSize: '14px', fontWeight: 600 }}>🔀 任务分解</h4>
      <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '12px' }}>
        检测到复杂查询，已分解为 {tasks.length} 个子任务。请确认后执行：
      </p>

      <div style={{ maxHeight: '400px', overflow: 'auto', marginBottom: '12px' }}>
        {tasks.map((task, idx) => (
          <div key={task.id} style={{
            background: task.enabled ? 'var(--surface-elevated)' : '#1a1a1a',
            padding: '10px',
            borderRadius: 'var(--radius-sm)',
            marginBottom: '8px',
            opacity: task.enabled ? 1 : 0.5,
            border: `1px solid ${task.enabled ? 'var(--border)' : '#333'}`
          }}>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'start', marginBottom: '6px' }}>
              <input
                type="checkbox"
                checked={task.enabled}
                onChange={() => toggleTask(task.id)}
                style={{ marginTop: '4px' }}
              />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginBottom: '4px' }}>
                  任务 {idx + 1} {task.agent_hint && `· ${task.agent_hint}`}
                </div>
                <textarea
                  value={task.description}
                  onChange={e => updateDescription(task.id, e.target.value)}
                  disabled={!task.enabled}
                  rows={2}
                  style={{
                    width: '100%',
                    padding: '4px 6px',
                    fontSize: '12px',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)',
                    resize: 'vertical',
                    color: task.enabled ? 'var(--text)' : 'var(--text-tertiary)'
                  }}
                />
                {task.dependencies.length > 0 && (
                  <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                    依赖: {task.dependencies.join(', ')}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
        <button onClick={onCancel} style={{ padding: '6px 12px', fontSize: '12px', background: 'transparent', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}>
          取消
        </button>
        <button onClick={handleApprove} style={{ padding: '6px 12px', fontSize: '12px', background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}>
          批准并执行 ({tasks.filter(t => t.enabled).length}/{tasks.length})
        </button>
      </div>
    </div>
  );
}
