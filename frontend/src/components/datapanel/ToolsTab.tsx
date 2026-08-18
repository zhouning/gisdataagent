import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

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
  pipelines?: string[];
  url?: string;
  command?: string;
  timeout?: number;
  bearer_token_env_var?: string;
  bearer_token_available?: boolean;
  ca_cert?: string;
  ca_cert_configured?: boolean;
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

interface McpServerForm {
  description: string;
  transport: string;
  url: string;
  command: string;
  category: string;
  pipelines: string;
  bearer_token_env_var: string;
  ca_cert: string;
  timeout: string;
  enabled: boolean;
}

interface ConnectionTestResult {
  success: boolean;
  message: string;
}

const emptyServerForm = (): McpServerForm => ({
  description: '',
  transport: 'streamable_http',
  url: '',
  command: '',
  category: '',
  pipelines: 'general,planner',
  bearer_token_env_var: '',
  ca_cert: '',
  timeout: '15',
  enabled: false,
});

const serverToForm = (server: McpServer): McpServerForm => ({
  description: server.description || '',
  transport: server.transport || 'streamable_http',
  url: server.url || '',
  command: server.command || '',
  category: server.category || '',
  pipelines: (server.pipelines || ['general', 'planner']).join(','),
  bearer_token_env_var: server.bearer_token_env_var || '',
  ca_cert: server.ca_cert || '',
  timeout: String(server.timeout || 5),
  enabled: server.enabled,
});

const formPayload = (form: McpServerForm) => ({
  ...form,
  timeout: Number(form.timeout),
  pipelines: form.pipelines.split(',').map((value) => value.trim()).filter(Boolean),
});

function ServerConfigFields({
  form,
  onChange,
}: {
  form: McpServerForm;
  onChange: (updates: Partial<McpServerForm>) => void;
}) {
  const { t } = useTranslation('common');
  const isRemote = form.transport !== 'stdio';
  return (
    <>
      <input placeholder={t('assetWorkbench.tools.description')} value={form.description}
        onChange={(event) => onChange({ description: event.target.value })} />
      <select value={form.transport}
        onChange={(event) => onChange({ transport: event.target.value })}>
        <option value="streamable_http">Streamable HTTP</option>
        <option value="sse">SSE</option>
        <option value="stdio">Stdio</option>
      </select>
      {isRemote ? (
        <input placeholder={t('assetWorkbench.tools.urlPlaceholder')} value={form.url}
          onChange={(event) => onChange({ url: event.target.value })} />
      ) : (
        <input placeholder={t('assetWorkbench.tools.commandPlaceholder')} value={form.command}
          onChange={(event) => onChange({ command: event.target.value })} />
      )}
      {isRemote && (
        <>
          <input placeholder={t('assetWorkbench.tools.tokenEnvPlaceholder')} value={form.bearer_token_env_var}
            onChange={(event) => onChange({ bearer_token_env_var: event.target.value })} />
          <input placeholder={t('assetWorkbench.tools.caCertPlaceholder')} value={form.ca_cert}
            onChange={(event) => onChange({ ca_cert: event.target.value })} />
        </>
      )}
      <div className="mcp-form-row">
        <input placeholder={t('assetWorkbench.tools.category')} value={form.category}
          onChange={(event) => onChange({ category: event.target.value })} />
        <input type="number" min="0.1" max="300" step="0.5" placeholder={t('assetWorkbench.tools.timeoutSeconds')}
          value={form.timeout} onChange={(event) => onChange({ timeout: event.target.value })} />
      </div>
      <input placeholder={t('assetWorkbench.tools.pipelinesPlaceholder')} value={form.pipelines}
        onChange={(event) => onChange({ pipelines: event.target.value })} />
    </>
  );
}

export default function ToolsTab({ userRole }: { userRole?: string }) {
  const { t, i18n } = useTranslation('common');
  const [servers, setServers] = useState<McpServer[]>([]);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [selectedServer, setSelectedServer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingServer, setEditingServer] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<McpServerForm>(emptyServerForm);
  const [savingEdit, setSavingEdit] = useState(false);
  const [testingEdit, setTestingEdit] = useState(false);
  const [editError, setEditError] = useState('');
  const [editTestResult, setEditTestResult] = useState<ConnectionTestResult | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [addName, setAddName] = useState('');
  const [addForm, setAddForm] = useState<McpServerForm>(emptyServerForm);
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
      const resp = await fetch('/api/mcp/servers', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
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
      const resp = await fetch(`/api/mcp/tools${params}`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
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
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
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
        headers: getLocaleHeaders(),
      });
      if (resp.ok) await fetchServers();
    } catch { /* ignore */ }
    finally { setReconnecting(null); }
  };

  const handleAddServer = async () => {
    setAddError('');
    if (!addName.trim()) { setAddError(t('assetWorkbench.tools.errors.nameRequired')); return; }
    try {
      const resp = await fetch('/api/mcp/servers', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ name: addName.trim(), ...formPayload(addForm) }),
      });
      if (resp.ok) {
        setShowAddForm(false);
        setAddName('');
        setAddForm(emptyServerForm());
        setTestResult(null);
        await fetchServers();
      } else {
        setAddError(t('assetWorkbench.tools.errors.addFailed'));
      }
    } catch { setAddError(t('assetWorkbench.common.networkError')); }
  };

  const startEditing = (server: McpServer) => {
    setShowAddForm(false);
    setEditingServer(server.name);
    setEditForm(serverToForm(server));
    setEditError('');
    setEditTestResult(null);
  };

  const handleEditTestConnection = async () => {
    setTestingEdit(true);
    setEditError('');
    setEditTestResult(null);
    try {
      const resp = await fetch('/api/mcp/servers/test', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(formPayload(editForm)),
      });
      setEditTestResult({
        success: resp.ok,
        message: resp.ok
          ? t('assetWorkbench.tools.connectionSuccess')
          : t('assetWorkbench.tools.connectionFailed'),
      });
    } catch {
      setEditTestResult({ success: false, message: t('assetWorkbench.common.networkError') });
    } finally {
      setTestingEdit(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!editingServer) return;
    setSavingEdit(true);
    setEditError('');
    try {
      const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(editingServer)}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(formPayload(editForm)),
      });
      if (!resp.ok) {
        setEditError(t('assetWorkbench.tools.errors.saveFailed'));
        return;
      }
      setEditingServer(null);
      setEditTestResult(null);
      await fetchServers();
      if (selectedServer === editingServer) await fetchTools(editingServer);
    } catch {
      setEditError(t('assetWorkbench.common.networkError'));
    } finally {
      setSavingEdit(false);
    }
  };

  const handleDeleteServer = async (serverName: string) => {
    if (!confirm(t('assetWorkbench.tools.deleteConfirm', { name: serverName }))) return;
    setDeleting(serverName);
    try {
      await fetch(`/api/mcp/servers/${serverName}`, {
        method: 'DELETE',
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      await fetchServers();
    } catch { /* ignore */ }
    finally { setDeleting(null); }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const resp = await fetch('/api/mcp/servers/test', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(formPayload(addForm)),
      });
      setTestResult({
        success: resp.ok,
        message: resp.ok
          ? t('assetWorkbench.tools.connectionSuccess')
          : t('assetWorkbench.tools.connectionFailed'),
      });
    } catch {
      setTestResult({ success: false, message: t('assetWorkbench.common.networkError') });
    }
    finally { setTesting(false); }
  };

  const fetchRules = async () => {
    try {
      const r = await fetch('/api/mcp/rules', { credentials: 'include', headers: getLocaleHeaders() });
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
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
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
      await fetch(`/api/mcp/rules/${id}`, {
        method: 'DELETE', credentials: 'include', headers: getLocaleHeaders(),
      });
      await fetchRules();
    } catch { /* ignore */ }
  };

  const handleMatchTest = async () => {
    if (!matchTest.trim()) return;
    try {
      const r = await fetch(`/api/mcp/rules/match?task_type=${encodeURIComponent(matchTest)}`, {
        credentials: 'include', headers: getLocaleHeaders(),
      });
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
  }, [i18n.resolvedLanguage]);

  useEffect(() => {
    if (servers.some((s) => s.status === 'connected')) {
      fetchTools(selectedServer || undefined);
    } else {
      setTools([]);
    }
  }, [selectedServer, servers.length, i18n.resolvedLanguage]);

  const connectedCount = servers.filter((s) => s.status === 'connected').length;

  return (
    <div className="tools-view">
      <div className="tools-summary">
        <div style={{ display: 'flex', gap: 4, marginInlineEnd: 8 }}>
          {(['servers', 'rules'] as const).map(m => (
            <button key={m} onClick={() => setViewMode(m)}
              style={{
                padding: '2px 10px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                background: viewMode === m ? '#1e3a5f' : 'transparent',
                color: viewMode === m ? '#7dd3fc' : '#888',
                border: `1px solid ${viewMode === m ? '#2563eb' : '#333'}`,
              }}>
              {m === 'servers'
                ? t('assetWorkbench.tools.servers')
                : t('assetWorkbench.tools.rules')}
            </button>
          ))}
        </div>
        {viewMode === 'servers' && (
          <>
            <span>{t('assetWorkbench.tools.serverCount', { count: formatNumber(servers.length) })}</span>
            <span className="tools-summary-sep">/</span>
            <span className={connectedCount > 0 ? 'tools-connected' : ''}>
              {t('assetWorkbench.tools.connectedCount', { count: formatNumber(connectedCount) })}
            </span>
            {isAdmin && (
              <button className="btn-add-server" onClick={() => {
                setShowAddForm(!showAddForm);
                setEditingServer(null);
              }} title={t('assetWorkbench.tools.addServer')} aria-label={t('assetWorkbench.tools.addServer')}>
                <Plus size={14} />
              </button>
            )}
          </>
        )}
        {viewMode === 'rules' && (
          <>
            <span>{t('assetWorkbench.tools.ruleCount', { count: formatNumber(rules.length) })}</span>
            <button className="btn-add-server" onClick={() => setShowRuleForm(!showRuleForm)} title={t('assetWorkbench.tools.addRule')} aria-label={t('assetWorkbench.tools.addRule')}>
              <Plus size={14} />
            </button>
          </>
        )}
      </div>

      {viewMode === 'servers' && showAddForm && isAdmin && (
        <div className="mcp-add-form">
          <div className="mcp-add-form-title">{t('assetWorkbench.tools.addServer')}</div>
          <input placeholder={t('assetWorkbench.tools.namePlaceholder')} value={addName}
            onChange={(event) => setAddName(event.target.value)} />
          <ServerConfigFields form={addForm}
            onChange={(updates) => setAddForm((current) => ({ ...current, ...updates }))} />
          <label className="mcp-add-checkbox">
            <input type="checkbox" checked={addForm.enabled}
              onChange={e => setAddForm({...addForm, enabled: e.target.checked})} />
            {t('assetWorkbench.tools.connectImmediately')}
          </label>
          {addError && <div className="mcp-add-error">{addError}</div>}
          {testResult && (
            <div className={`mcp-test-result ${testResult.success ? 'success' : 'error'}`}>
              {testResult.message}
            </div>
          )}
          <div className="mcp-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => setShowAddForm(false)}>{t('assetWorkbench.common.cancel')}</button>
            <button className="btn-secondary btn-sm" onClick={handleTestConnection} disabled={testing}>
              {testing ? t('assetWorkbench.tools.testing') : t('assetWorkbench.tools.testConnection')}
            </button>
            <button className="btn-primary btn-sm" onClick={handleAddServer}>{t('assetWorkbench.common.add')}</button>
          </div>
        </div>
      )}

      {viewMode === 'servers' && editingServer && isAdmin && (
        <div className="mcp-add-form mcp-edit-form">
          <div className="mcp-add-form-title">{t('assetWorkbench.tools.editServer', { name: editingServer })}</div>
          <ServerConfigFields form={editForm}
            onChange={(updates) => setEditForm((current) => ({ ...current, ...updates }))} />
          {editError && <div className="mcp-add-error">{editError}</div>}
          {editTestResult && (
            <div className={`mcp-test-result ${editTestResult.success ? 'success' : 'error'}`}>
              {editTestResult.message}
            </div>
          )}
          <div className="mcp-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => setEditingServer(null)}>{t('assetWorkbench.common.cancel')}</button>
            <button className="btn-secondary btn-sm" onClick={handleEditTestConnection} disabled={testingEdit || savingEdit}>
              {testingEdit ? t('assetWorkbench.tools.testing') : t('assetWorkbench.tools.testConnection')}
            </button>
            <button className="btn-primary btn-sm" onClick={handleSaveEdit} disabled={savingEdit || testingEdit}>
              {savingEdit ? t('assetWorkbench.common.saving') : t('assetWorkbench.tools.saveAndReconnect')}
            </button>
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
                <label className="toggle-switch" title={s.enabled
                  ? t('assetWorkbench.tools.disable')
                  : t('assetWorkbench.tools.enable')}>
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    disabled={toggling === s.name}
                    onChange={(e) => { e.stopPropagation(); handleToggle(s.name, s.enabled); }}
                  />
                  <span className="toggle-slider" />
                </label>
                <button
                  className="btn-edit-server"
                  onClick={(event) => { event.stopPropagation(); startEditing(s); }}
                  title={t('assetWorkbench.tools.editConfig')}
                  aria-label={t('assetWorkbench.tools.editAria', { name: s.name })}
                >
                  <Pencil size={13} />
                </button>
                {s.enabled && (
                  <button
                    className="btn-reconnect"
                    disabled={reconnecting === s.name}
                    onClick={(e) => { e.stopPropagation(); handleReconnect(s.name); }}
                    title={t('assetWorkbench.tools.reconnect')}
                    aria-label={t('assetWorkbench.tools.reconnectAria', { name: s.name })}
                  >
                    <RefreshCw size={13} className={reconnecting === s.name ? 'is-spinning' : ''} />
                  </button>
                )}
                <button
                  className="btn-delete-server"
                  disabled={deleting === s.name}
                  onClick={(e) => { e.stopPropagation(); handleDeleteServer(s.name); }}
                  title={t('assetWorkbench.common.delete')}
                  aria-label={t('assetWorkbench.tools.deleteAria', { name: s.name })}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            )}
          </div>
        ))}
        {servers.length === 0 && (
          <div className="empty-state">
            {t('assetWorkbench.tools.noServers')}<br />
            {isAdmin
              ? t('assetWorkbench.tools.addServerHint')
              : t('assetWorkbench.tools.contactAdmin')}
          </div>
        )}
      </div>

      {tools.length > 0 && (
        <div className="tools-list">
          <div className="tools-list-header">
            <span>{selectedServer ? `${selectedServer}` : t('assetWorkbench.tools.allTools')}</span>
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
        <div className="empty-state">{t('assetWorkbench.tools.loadingTools')}</div>
      )}
      </>)}

      {/* Tool Rules View */}
      {viewMode === 'rules' && (
        <div style={{ padding: '8px 0' }}>
          {/* Add Rule Form */}
          {showRuleForm && (
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, marginBottom: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e0e0e0', marginBottom: 8 }}>
                {t('assetWorkbench.tools.addToolRule')}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>{t('assetWorkbench.tools.taskType')} *</div>
                  <input value={ruleForm.task_type} onChange={e => setRuleForm({ ...ruleForm, task_type: e.target.value })}
                    placeholder={t('assetWorkbench.tools.taskTypePlaceholder')}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>{t('assetWorkbench.tools.toolName')} *</div>
                  <input value={ruleForm.tool_name} onChange={e => setRuleForm({ ...ruleForm, tool_name: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>{t('assetWorkbench.tools.serverName')} *</div>
                  <input value={ruleForm.server_name} onChange={e => setRuleForm({ ...ruleForm, server_name: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>{t('assetWorkbench.tools.priority')}</div>
                  <input type="number" value={ruleForm.priority} onChange={e => setRuleForm({ ...ruleForm, priority: parseInt(e.target.value) || 0 })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>{t('assetWorkbench.tools.fallbackTool')}</div>
                  <input value={ruleForm.fallback_tool} onChange={e => setRuleForm({ ...ruleForm, fallback_tool: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>{t('assetWorkbench.tools.fallbackServer')}</div>
                  <input value={ruleForm.fallback_server} onChange={e => setRuleForm({ ...ruleForm, fallback_server: e.target.value })}
                    style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={handleAddRule} style={{ padding: '4px 12px', borderRadius: 4, border: 'none', background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12 }}>{t('assetWorkbench.common.save')}</button>
                <button onClick={() => setShowRuleForm(false)} style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid #333', background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 12 }}>{t('assetWorkbench.common.cancel')}</button>
              </div>
            </div>
          )}

          {/* Rules Table */}
          {rules.length > 0 ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead><tr style={{ background: '#1f2937' }}>
                <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('assetWorkbench.tools.taskType')}</th>
                <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('assetWorkbench.tools.tool')}</th>
                <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('assetWorkbench.tools.server')}</th>
                <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('assetWorkbench.tools.priority')}</th>
                <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('assetWorkbench.tools.fallback')}</th>
                <th style={{ padding: '6px 8px', textAlign: 'end', color: '#aaa' }}>{t('assetWorkbench.tools.actions')}</th>
              </tr></thead>
              <tbody>
                {rules.map(r => (
                  <tr key={r.id}>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#7dd3fc', fontFamily: 'monospace' }}>{r.task_type}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{r.tool_name}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#aaa' }}>{r.server_name}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#888' }}>{formatNumber(r.priority)}</td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#666', fontSize: 11 }}>
                      {r.fallback_tool ? `${r.fallback_tool} @ ${r.fallback_server || '-'}` : '-'}
                    </td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', textAlign: 'end' }}>
                      <button onClick={() => handleDeleteRule(r.id)}
                        style={{ padding: '2px 8px', borderRadius: 3, border: '1px solid #333', background: 'transparent', color: '#e53935', cursor: 'pointer', fontSize: 11 }}>
                        {t('assetWorkbench.common.delete')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ color: '#888', textAlign: 'center', padding: 24, fontSize: 12 }}>
              {t('assetWorkbench.tools.noRules')}
            </div>
          )}

          {/* Test Match */}
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, marginTop: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#e0e0e0', marginBottom: 6 }}>
              {t('assetWorkbench.tools.matchTest')}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input value={matchTest} onChange={e => { setMatchTest(e.target.value); setMatchResult(null); }}
                placeholder={t('assetWorkbench.tools.matchPlaceholder')}
                style={{ flex: 1, padding: '4px 8px', background: '#0d1117', border: '1px solid #333', borderRadius: 4, color: '#ccc', fontSize: 12 }} />
              <button onClick={handleMatchTest}
                style={{ padding: '4px 12px', borderRadius: 4, border: 'none', background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12 }}>
                {t('assetWorkbench.tools.match')}
              </button>
            </div>
            {matchResult && matchResult !== 'not_found' && (
              <div style={{ marginTop: 6, fontSize: 11, color: '#10b981' }}>
                {t('assetWorkbench.tools.matchSuccess', {
                  tool: (matchResult as ToolRule).tool_name,
                  server: (matchResult as ToolRule).server_name,
                })}
                {(matchResult as ToolRule).fallback_tool && (
                  <span style={{ color: '#888' }}> {t('assetWorkbench.tools.matchFallback', {
                    tool: (matchResult as ToolRule).fallback_tool,
                  })}</span>
                )}
              </div>
            )}
            {matchResult === 'not_found' && (
              <div style={{ marginTop: 6, fontSize: 11, color: '#fb8c00' }}>
                {t('assetWorkbench.tools.noMatch')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
