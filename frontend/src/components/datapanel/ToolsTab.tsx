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

interface ToolRule {
  id: number;
  task_type: string;
  tool_name: string;
  server_name: string;
  priority: number;
  fallback_tool: string | null;
  fallback_server: string | null;
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
  // Tool rules state
  const [viewMode, setViewMode] = useState<'servers' | 'rules'>('servers');
  const [rules, setRules] = useState<ToolRule[]>([]);
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [ruleForm, setRuleForm] = useState({ task_type: '', tool_name: '', server_name: '', priority: 0, fallback_tool: '', fallback_server: '' });
  const [matchTest, setMatchTest] = useState('');
  const [matchResult, setMatchResult] = useState<ToolRule | null | 'not_found'>(null);

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

  const fetchRules = async () => {
    try {
      const r = await fetch('/api/mcp/rules', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setRules(d.rules || []); }
    } catch { /* ignore */ }
  };

  const handleAddRule = async () => {
    if (!ruleForm.task_type || !ruleForm.tool_name || !ruleForm.server_name) return;
    try {
      const body: Record<string, unknown> = {
        task_type: ruleForm.task_type, tool_name: ruleForm.tool_name,
        server_name: ruleForm.server_name, priority: ruleForm.priority,
      };
      if (ruleForm.fallback_tool) body.fallback_tool = ruleForm.fallback_tool;
      if (ruleForm.fallback_server) body.fallback_server = ruleForm.fallback_server;
      const r = await fetch('/api/mcp/rules', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        setShowRuleForm(false);
        setRuleForm({ task_type: '', tool_name: '', server_name: '', priority: 0, fallback_tool: '', fallback_server: '' });
        await fetchRules();
      }
    } catch { /* ignore */ }
  };

  const handleDeleteRule = async (id: number) => {
    try {
      await fetch(`/api/mcp/rules/${id}`, { method: 'DELETE', credentials: 'include' });
      await fetchRules();
    } catch { /* ignore */ }
  };

  const handleMatchTest = async () => {
    if (!matchTest.trim()) return;
    try {
      const r = await fetch(`/api/mcp/rules/match?task_type=${encodeURIComponent(matchTest)}`, { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setMatchResult(d.match || 'not_found'); }
      else { setMatchResult('not_found'); }
    } catch { setMatchResult('not_found'); }
  };

  const isAdmin = userRole === 'admin';

  useEffect(() => {
    fetchServers();
    fetchRules();
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
        <div style={{ display: 'flex', gap: 4, marginRight: 8 }}>
          {(['servers', 'rules'] as const).map(m => (
            <button key={m} onClick={() => setViewMode(m)}
              style={{
                padding: '2px 10px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                background: viewMode === m ? '#1e3a5f' : 'transparent',
                color: viewMode === m ? '#7dd3fc' : '#888',
                border: `1px solid ${viewMode === m ? '#2563eb' : '#333'}`,
              }}>
              {m === 'servers' ? '服务器' : '工具规则'}
            </button>
          ))}
        </div>
        {viewMode === 'servers' && (
          <>
            <span>{servers.length} 服务器</span>
            <span className="tools-summary-sep">/</span>
            <span className={connectedCount > 0 ? 'tools-connected' : ''}>{connectedCount} 已连接</span>
            {isAdmin && (
              <button className="btn-add-server" onClick={() => setShowAddForm(!showAddForm)} title="添加 MCP 服务器">+</button>
            )}
          </>
        )}
        {viewMode === 'rules' && (
          <>
            <span>{rules.length} 条规则</span>
            <button className="btn-add-server" onClick={() => setShowRuleForm(!showRuleForm)} title="添加规则">+</button>
          </>
        )}
      </div>

      {viewMode === 'servers' && showAddForm && isAdmin && (
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

      {viewMode === 'servers' && (<>
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
      </>)}

      {/* Tool Rules View */}
      {viewMode === 'rules' && (
        <div style={{ padding: '8px 0' }}>
          {/* Add Rule Form */}
          {showRuleForm && (
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, marginBottom: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e0e0e0', marginBottom: 8 }}>添加工具规则</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>任务类型 *</div>
                  <input value={ruleForm.task_type} onChange={e => setRuleForm({ ...ruleForm, task_type: e.target.value })}
                    placeholder="如: spatial_analysis"
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>工具名称 *</div>
                  <input value={ruleForm.tool_name} onChange={e => setRuleForm({ ...ruleForm, tool_name: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>服务器名称 *</div>
                  <input value={ruleForm.server_name} onChange={e => setRuleForm({ ...ruleForm, server_name: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>优先级</div>
                  <input type="number" value={ruleForm.priority} onChange={e => setRuleForm({ ...ruleForm, priority: parseInt(e.target.value) || 0 })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>降级工具</div>
                  <input value={ruleForm.fallback_tool} onChange={e => setRuleForm({ ...ruleForm, fallback_tool: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>降级服务器</div>
                  <input value={ruleForm.fallback_server} onChange={e => setRuleForm({ ...ruleForm, fallback_server: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={handleAddRule} style={{ padding: '4px 12px', borderRadius: 4, border: 'none', background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12 }}>保存</button>
                <button onClick={() => setShowRuleForm(false)} style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid #333', background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 12 }}>取消</button>
              </div>
            </div>
          )}

          {/* Rules Table */}
          {rules.length > 0 ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead><tr style={{ background: '#1f2937' }}>
                <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>任务类型</th>
                <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>工具</th>
                <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>服务器</th>
                <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>优先级</th>
                <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>降级</th>
                <th style={{ padding: '6px 8px', textAlign: 'right', color: '#aaa' }}>操作</th>
              </tr></thead>
              <tbody>
                {rules.map(r => (
                  <tr key={r.id}>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#7dd3fc', fontFamily: 'monospace' }}>{r.task_type}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{r.tool_name}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#aaa' }}>{r.server_name}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#888' }}>{r.priority}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#666', fontSize: 11 }}>
                      {r.fallback_tool ? `${r.fallback_tool} @ ${r.fallback_server || '-'}` : '-'}
                    </td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', textAlign: 'right' }}>
                      <button onClick={() => handleDeleteRule(r.id)}
                        style={{ padding: '2px 8px', borderRadius: 3, border: '1px solid #333', background: 'transparent', color: '#e53935', cursor: 'pointer', fontSize: 11 }}>
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ color: '#888', textAlign: 'center', padding: 24, fontSize: 12 }}>暂无工具规则，点击 + 添加</div>
          )}

          {/* Test Match */}
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, marginTop: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#e0e0e0', marginBottom: 6 }}>规则匹配测试</div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input value={matchTest} onChange={e => { setMatchTest(e.target.value); setMatchResult(null); }}
                placeholder="输入任务类型..."
                style={{ flex: 1, padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
              <button onClick={handleMatchTest}
                style={{ padding: '4px 12px', borderRadius: 4, border: 'none', background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12 }}>
                匹配
              </button>
            </div>
            {matchResult && matchResult !== 'not_found' && (
              <div style={{ marginTop: 6, fontSize: 11, color: '#10b981' }}>
                匹配成功: {(matchResult as ToolRule).tool_name} @ {(matchResult as ToolRule).server_name}
                {(matchResult as ToolRule).fallback_tool && <span style={{ color: '#888' }}> (降级: {(matchResult as ToolRule).fallback_tool})</span>}
              </div>
            )}
            {matchResult === 'not_found' && (
              <div style={{ marginTop: 6, fontSize: 11, color: '#fb8c00' }}>未找到匹配规则</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
