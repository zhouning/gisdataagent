import { useState, useEffect } from 'react';

interface McpServer {
  name: string;
  description: string;
  transport: string;
  status: string;
  tool_count: number;
  category: string;
  enabled: boolean;
  error_message: string;
  connected_at: number | null;
}

interface McpTool {
  name: string;
  description: string;
  server: string;
}

export default function ToolsTab({ userRole }: { userRole?: string }) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [selectedServer, setSelectedServer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [addForm, setAddForm] = useState({
    name: '', description: '', transport: 'sse' as string,
    url: '', command: '', enabled: false, category: '', pipelines: 'general,planner',
  });
  const [addError, setAddError] = useState('');

  const fetchServers = async () => {
    try {
      const resp = await fetch('/api/mcp/servers', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setServers(data.servers || []);
      }
    } catch { /* ignore */ }
  };

  const fetchTools = async (serverName?: string) => {
    setLoading(true);
    const params = serverName ? `?server=${serverName}` : '';
    try {
      const resp = await fetch(`/api/mcp/tools${params}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setTools(data.tools || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  const handleToggle = async (serverName: string, currentEnabled: boolean) => {
    setToggling(serverName);
    try {
      const resp = await fetch(`/api/mcp/servers/${serverName}/toggle`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !currentEnabled }),
      });
      if (resp.ok) await fetchServers();
    } catch { /* ignore */ }
    finally { setToggling(null); }
  };

  const handleReconnect = async (serverName: string) => {
    setReconnecting(serverName);
    try {
      const resp = await fetch(`/api/mcp/servers/${serverName}/reconnect`, {
        method: 'POST',
        credentials: 'include',
      });
      if (resp.ok) await fetchServers();
    } catch { /* ignore */ }
    finally { setReconnecting(null); }
  };

  const handleAddServer = async () => {
    setAddError('');
    if (!addForm.name.trim()) { setAddError('名称必填'); return; }
    const pipelinesArr = addForm.pipelines.split(',').map(s => s.trim()).filter(Boolean);
    try {
      const resp = await fetch('/api/mcp/servers', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...addForm,
          pipelines: pipelinesArr,
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowAddForm(false);
        setAddForm({ name: '', description: '', transport: 'sse', url: '', command: '', enabled: false, category: '', pipelines: 'general,planner' });
        await fetchServers();
      } else {
        setAddError(data.error || data.message || '添加失败');
      }
    } catch { setAddError('网络错误'); }
  };

  const handleDeleteServer = async (serverName: string) => {
    if (!confirm(`确定删除 MCP 服务器「${serverName}」？`)) return;
    setDeleting(serverName);
    try {
      await fetch(`/api/mcp/servers/${serverName}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      await fetchServers();
    } catch { /* ignore */ }
    finally { setDeleting(null); }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const pipelinesArr = addForm.pipelines.split(',').map(s => s.trim()).filter(Boolean);
      const resp = await fetch('/api/mcp/servers/test', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...addForm, pipelines: pipelinesArr }),
      });
      const data = await resp.json();
      setTestResult(data.message || (resp.ok ? 'OK' : data.error || '连接失败'));
    } catch { setTestResult('网络错误'); }
    finally { setTesting(false); }
  };

  const isAdmin = userRole === 'admin';

  useEffect(() => {
    fetchServers();
    const interval = setInterval(fetchServers, 15000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (servers.some((s) => s.status === 'connected')) {
      fetchTools(selectedServer || undefined);
    } else {
      setTools([]);
    }
  }, [selectedServer, servers.length]);

  const connectedCount = servers.filter((s) => s.status === 'connected').length;

  return (
    <div className="tools-view">
      <div className="tools-summary">
        <span>{servers.length} 服务器</span>
        <span className="tools-summary-sep">/</span>
        <span className={connectedCount > 0 ? 'tools-connected' : ''}>{connectedCount} 已连接</span>
        {isAdmin && (
          <button className="btn-add-server" onClick={() => setShowAddForm(!showAddForm)} title="添加 MCP 服务器">+</button>
        )}
      </div>

      {showAddForm && isAdmin && (
        <div className="mcp-add-form">
          <div className="mcp-add-form-title">添加 MCP 服务器</div>
          <input placeholder="名称 (唯一标识)" value={addForm.name}
            onChange={e => setAddForm({...addForm, name: e.target.value})} />
          <input placeholder="描述" value={addForm.description}
            onChange={e => setAddForm({...addForm, description: e.target.value})} />
          <select value={addForm.transport}
            onChange={e => setAddForm({...addForm, transport: e.target.value})}>
            <option value="sse">SSE</option>
            <option value="streamable_http">Streamable HTTP</option>
            <option value="stdio">Stdio</option>
          </select>
          {addForm.transport === 'stdio' ? (
            <input placeholder="命令 (如 python -m server)" value={addForm.command}
              onChange={e => setAddForm({...addForm, command: e.target.value})} />
          ) : (
            <input placeholder="URL (如 http://localhost:8080/mcp)" value={addForm.url}
              onChange={e => setAddForm({...addForm, url: e.target.value})} />
          )}
          <input placeholder="分类 (如 gis, data)" value={addForm.category}
            onChange={e => setAddForm({...addForm, category: e.target.value})} />
          <input placeholder="管线 (逗号分隔: general,planner)" value={addForm.pipelines}
            onChange={e => setAddForm({...addForm, pipelines: e.target.value})} />
          <label className="mcp-add-checkbox">
            <input type="checkbox" checked={addForm.enabled}
              onChange={e => setAddForm({...addForm, enabled: e.target.checked})} />
            立即连接
          </label>
          {addError && <div className="mcp-add-error">{addError}</div>}
          {testResult && <div className={`mcp-test-result ${testResult.includes('成功') ? 'success' : 'error'}`}>{testResult}</div>}
          <div className="mcp-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => setShowAddForm(false)}>取消</button>
            <button className="btn-secondary btn-sm" onClick={handleTestConnection} disabled={testing}>{testing ? '测试中...' : '测试连接'}</button>
            <button className="btn-primary btn-sm" onClick={handleAddServer}>添加</button>
          </div>
        </div>
      )}

      <div className="tools-server-list">
        {servers.map((s) => (
          <div
            key={s.name}
            className={`tools-server-card ${selectedServer === s.name ? 'selected' : ''}`}
            onClick={() => setSelectedServer(selectedServer === s.name ? null : s.name)}
          >
            <div className="tools-server-header">
              <span className={`status-dot ${s.status}`} />
              <span className="tools-server-name">{s.name}</span>
              {s.tool_count > 0 && (
                <span className="tools-server-count">{s.tool_count}</span>
              )}
            </div>
            {s.description && (
              <div className="tools-server-desc">{s.description}</div>
            )}
            {s.error_message && (
              <div className="tools-server-error">{s.error_message}</div>
            )}
            {isAdmin && (
              <div className="tools-server-actions">
                <label className="toggle-switch" title={s.enabled ? '禁用' : '启用'}>
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    disabled={toggling === s.name}
                    onChange={(e) => { e.stopPropagation(); handleToggle(s.name, s.enabled); }}
                  />
                  <span className="toggle-slider" />
                </label>
                {s.enabled && (
                  <button
                    className="btn-reconnect"
                    disabled={reconnecting === s.name}
                    onClick={(e) => { e.stopPropagation(); handleReconnect(s.name); }}
                    title="重新连接"
                  >
                    {reconnecting === s.name ? '...' : '\u21BB'}
                  </button>
                )}
                <button
                  className="btn-delete-server"
                  disabled={deleting === s.name}
                  onClick={(e) => { e.stopPropagation(); handleDeleteServer(s.name); }}
                  title="删除"
                >
                  {deleting === s.name ? '...' : '\u00D7'}
                </button>
              </div>
            )}
          </div>
        ))}
        {servers.length === 0 && (
          <div className="empty-state">
            暂无 MCP 服务器<br />
            {isAdmin ? '点击上方 + 按钮添加' : '请联系管理员配置'}
          </div>
        )}
      </div>

      {tools.length > 0 && (
        <div className="tools-list">
          <div className="tools-list-header">
            <span>{selectedServer ? `${selectedServer}` : '全部工具'}</span>
            <span className="tools-count">{tools.length}</span>
          </div>
          {tools.map((tool) => (
            <div key={`${tool.server}-${tool.name}`} className="tool-item">
              <div className="tool-name">{tool.name}</div>
              {tool.description && (
                <div className="tool-desc">{tool.description}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {loading && tools.length === 0 && connectedCount > 0 && (
        <div className="empty-state">加载工具中...</div>
      )}
    </div>
  );
}
