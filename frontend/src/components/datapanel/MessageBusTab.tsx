import { useState, useEffect } from 'react';

interface MessageStats {
  total: number;
  delivered: number;
  undelivered: number;
  unique_senders: number;
  unique_receivers: number;
  by_type: Record<string, number>;
}

interface Message {
  id: number;
  message_id: string;
  from_agent: string;
  to_agent: string;
  message_type: string;
  payload: any;
  correlation_id: string | null;
  delivered: boolean;
  created_at: string;
}

export default function MessageBusTab() {
  const [stats, setStats] = useState<MessageStats | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedMsg, setSelectedMsg] = useState<Message | null>(null);
  const [filters, setFilters] = useState({ from_agent: '', to_agent: '', message_type: '', delivered: '' });

  useEffect(() => {
    loadStats();
    loadMessages();
  }, []);

  const loadStats = async () => {
    try {
      const r = await fetch('/api/messaging/stats', { credentials: 'include' });
      if (r.ok) setStats(await r.json());
    } catch { /* ignore */ }
  };

  const loadMessages = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.from_agent) params.set('from_agent', filters.from_agent);
      if (filters.to_agent) params.set('to_agent', filters.to_agent);
      if (filters.message_type) params.set('message_type', filters.message_type);
      if (filters.delivered) params.set('delivered', filters.delivered);

      const r = await fetch(`/api/messaging/messages?${params}`, { credentials: 'include' });
      if (r.ok) {
        const data = await r.json();
        setMessages(data.messages || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  const handleReplay = async (id: number) => {
    if (!confirm('确认重新发送此消息？')) return;
    try {
      const r = await fetch(`/api/messaging/${id}/replay`, { method: 'POST', credentials: 'include' });
      if (r.ok) {
        alert('消息已重新发送');
        loadMessages();
        loadStats();
      }
    } catch { /* ignore */ }
  };

  const handleCleanup = async () => {
    if (!confirm('确认清理 30 天前的旧消息？')) return;
    try {
      const r = await fetch('/api/messaging/cleanup?days=30', { method: 'DELETE', credentials: 'include' });
      if (r.ok) {
        const data = await r.json();
        alert(`已清理 ${data.deleted} 条消息`);
        loadMessages();
        loadStats();
      }
    } catch { /* ignore */ }
  };

  return (
    <div style={{ padding: '16px', height: '100%', overflow: 'auto' }}>
      <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', fontWeight: 600 }}>消息总线监控</h3>

      {/* Stats cards */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px', marginBottom: '16px' }}>
          <div style={{ background: 'var(--surface)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>总消息数</div>
            <div style={{ fontSize: '20px', fontWeight: 600 }}>{stats.total}</div>
          </div>
          <div style={{ background: 'var(--surface)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>已送达</div>
            <div style={{ fontSize: '20px', fontWeight: 600, color: '#10b981' }}>{stats.delivered}</div>
          </div>
          <div style={{ background: 'var(--surface)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>未送达</div>
            <div style={{ fontSize: '20px', fontWeight: 600, color: '#ef4444' }}>{stats.undelivered}</div>
          </div>
          <div style={{ background: 'var(--surface)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>发送者</div>
            <div style={{ fontSize: '20px', fontWeight: 600 }}>{stats.unique_senders}</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', flexWrap: 'wrap' }}>
        <input
          placeholder="发送者"
          value={filters.from_agent}
          onChange={e => setFilters({ ...filters, from_agent: e.target.value })}
          style={{ padding: '6px 8px', fontSize: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface-elevated)' }}
        />
        <input
          placeholder="接收者"
          value={filters.to_agent}
          onChange={e => setFilters({ ...filters, to_agent: e.target.value })}
          style={{ padding: '6px 8px', fontSize: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface-elevated)' }}
        />
        <select
          value={filters.delivered}
          onChange={e => setFilters({ ...filters, delivered: e.target.value })}
          style={{ padding: '6px 8px', fontSize: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface-elevated)' }}
        >
          <option value="">全部状态</option>
          <option value="true">已送达</option>
          <option value="false">未送达</option>
        </select>
        <button onClick={loadMessages} disabled={loading} style={{ padding: '6px 12px', fontSize: '12px', borderRadius: 'var(--radius-sm)', border: 'none', background: 'var(--primary)', color: '#fff', cursor: 'pointer' }}>
          {loading ? '加载中...' : '刷新'}
        </button>
        <button onClick={handleCleanup} style={{ padding: '6px 12px', fontSize: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface-elevated)', cursor: 'pointer' }}>
          清理旧消息
        </button>
      </div>

      {/* Messages table */}
      <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
        <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--surface-elevated)', borderBottom: '1px solid var(--border)' }}>
              <th style={{ padding: '8px', textAlign: 'left', fontWeight: 600 }}>发送者</th>
              <th style={{ padding: '8px', textAlign: 'left', fontWeight: 600 }}>接收者</th>
              <th style={{ padding: '8px', textAlign: 'left', fontWeight: 600 }}>类型</th>
              <th style={{ padding: '8px', textAlign: 'left', fontWeight: 600 }}>状态</th>
              <th style={{ padding: '8px', textAlign: 'left', fontWeight: 600 }}>时间</th>
              <th style={{ padding: '8px', textAlign: 'left', fontWeight: 600 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {messages.map(msg => (
              <tr key={msg.id} style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => setSelectedMsg(msg)}>
                <td style={{ padding: '8px' }}>{msg.from_agent}</td>
                <td style={{ padding: '8px' }}>{msg.to_agent}</td>
                <td style={{ padding: '8px' }}>{msg.message_type}</td>
                <td style={{ padding: '8px' }}>
                  <span style={{ padding: '2px 6px', borderRadius: '4px', fontSize: '11px', background: msg.delivered ? '#d1fae5' : '#fee2e2', color: msg.delivered ? '#065f46' : '#991b1b' }}>
                    {msg.delivered ? '已送达' : '未送达'}
                  </span>
                </td>
                <td style={{ padding: '8px', fontSize: '11px', color: 'var(--text-secondary)' }}>{new Date(msg.created_at).toLocaleString()}</td>
                <td style={{ padding: '8px' }}>
                  {!msg.delivered && (
                    <button onClick={(e) => { e.stopPropagation(); handleReplay(msg.id); }} style={{ padding: '4px 8px', fontSize: '11px', borderRadius: 'var(--radius-sm)', border: 'none', background: 'var(--primary)', color: '#fff', cursor: 'pointer' }}>
                      重发
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {messages.length === 0 && (
          <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '12px' }}>
            暂无消息
          </div>
        )}
      </div>

      {/* Message detail modal */}
      {selectedMsg && (
        <div onClick={() => setSelectedMsg(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div onClick={e => e.stopPropagation()} style={{ background: 'var(--surface)', padding: '20px', borderRadius: 'var(--radius-lg)', maxWidth: '600px', width: '90%', maxHeight: '80vh', overflow: 'auto' }}>
            <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 600 }}>消息详情</h4>
            <div style={{ fontSize: '12px', lineHeight: 1.6 }}>
              <div style={{ marginBottom: '8px' }}><strong>ID:</strong> {selectedMsg.message_id}</div>
              <div style={{ marginBottom: '8px' }}><strong>发送者:</strong> {selectedMsg.from_agent}</div>
              <div style={{ marginBottom: '8px' }}><strong>接收者:</strong> {selectedMsg.to_agent}</div>
              <div style={{ marginBottom: '8px' }}><strong>类型:</strong> {selectedMsg.message_type}</div>
              <div style={{ marginBottom: '8px' }}><strong>关联ID:</strong> {selectedMsg.correlation_id || 'N/A'}</div>
              <div style={{ marginBottom: '8px' }}><strong>状态:</strong> {selectedMsg.delivered ? '已送达' : '未送达'}</div>
              <div style={{ marginBottom: '8px' }}><strong>时间:</strong> {new Date(selectedMsg.created_at).toLocaleString()}</div>
              <div style={{ marginBottom: '8px' }}><strong>Payload:</strong></div>
              <pre style={{ background: 'var(--surface-elevated)', padding: '8px', borderRadius: 'var(--radius-sm)', fontSize: '11px', overflow: 'auto', maxHeight: '300px' }}>
                {JSON.stringify(selectedMsg.payload, null, 2)}
              </pre>
            </div>
            <button onClick={() => setSelectedMsg(null)} style={{ marginTop: '12px', padding: '6px 12px', fontSize: '12px', borderRadius: 'var(--radius-sm)', border: 'none', background: 'var(--primary)', color: '#fff', cursor: 'pointer' }}>
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
