import { useState, useEffect } from 'react';
import Papa from 'papaparse';
import WorkflowEditor from './WorkflowEditor';

interface DataPanelProps {
  dataFile: string | null;
  userRole?: string;
}

type TabKey = 'files' | 'table' | 'catalog' | 'history' | 'usage' | 'tools' | 'workflows';

interface FileInfo {
  name: string;
  size: number;
  modified: string;
  type: string;
}

interface CatalogAsset {
  id: number;
  asset_name: string;
  asset_type: string;
  file_format: string;
  storage_backend: string;
  crs: string;
  feature_count: number;
  file_size_bytes: number;
  tags: string;
  description: string;
  owner_user: string;
  is_shared: boolean;
  created_at: string;
}

interface PipelineRun {
  timestamp: string;
  pipeline_type: string;
  intent: string;
  input_tokens: number;
  output_tokens: number;
  files_generated: number;
}

export default function DataPanel({ dataFile, userRole }: DataPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('files');
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [tableData, setTableData] = useState<any[]>([]);
  const [tableColumns, setTableColumns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchFiles();
    const interval = setInterval(fetchFiles, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!dataFile) return;
    loadCsvData(dataFile);
    setActiveTab('table');
  }, [dataFile]);

  const fetchFiles = async () => {
    try {
      const resp = await fetch('/api/user/files', { credentials: 'include' });
      if (resp.ok) setFiles(await resp.json());
    } catch { /* ignore */ }
  };

  const loadCsvData = async (filename: string) => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/user/files/${filename}`, { credentials: 'include' });
      if (!resp.ok) return;
      const text = await resp.text();
      const result = Papa.parse(text, { header: true, skipEmptyLines: true });
      if (result.data.length > 0) {
        setTableColumns(result.meta.fields || []);
        setTableData(result.data.slice(0, 500));
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  const handleFileClick = (file: FileInfo) => {
    if (file.type === 'csv') { loadCsvData(file.name); setActiveTab('table'); }
    else {
      // Open/download non-CSV files via the file serve API
      window.open(`/api/user/files/${encodeURIComponent(file.name)}`, '_blank');
    }
  };

  return (
    <div className="data-panel">
      <div className="data-panel-header">
        <svg className="data-panel-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
        </svg>
        <span>数据</span>
      </div>

      <div className="data-panel-tabs">
        <button className={`data-panel-tab ${activeTab === 'files' ? 'active' : ''}`}
          onClick={() => setActiveTab('files')}>文件</button>
        <button className={`data-panel-tab ${activeTab === 'table' ? 'active' : ''}`}
          onClick={() => setActiveTab('table')}>表格</button>
        <button className={`data-panel-tab ${activeTab === 'catalog' ? 'active' : ''}`}
          onClick={() => setActiveTab('catalog')}>资产</button>
        <button className={`data-panel-tab ${activeTab === 'history' ? 'active' : ''}`}
          onClick={() => setActiveTab('history')}>历史</button>
        <button className={`data-panel-tab ${activeTab === 'usage' ? 'active' : ''}`}
          onClick={() => setActiveTab('usage')}>用量</button>
        <button className={`data-panel-tab ${activeTab === 'tools' ? 'active' : ''}`}
          onClick={() => setActiveTab('tools')}>工具</button>
        <button className={`data-panel-tab ${activeTab === 'workflows' ? 'active' : ''}`}
          onClick={() => setActiveTab('workflows')}>工作流</button>
      </div>

      <div className="data-panel-content">
        {activeTab === 'files' && <FileList files={files} onFileClick={handleFileClick} />}
        {activeTab === 'table' && <DataTable columns={tableColumns} data={tableData} loading={loading} />}
        {activeTab === 'catalog' && <CatalogView />}
        {activeTab === 'history' && <HistoryView />}
        {activeTab === 'usage' && <UsageView />}
        {activeTab === 'tools' && <ToolsView userRole={userRole} />}
        {activeTab === 'workflows' && <WorkflowsView />}
      </div>
    </div>
  );
}

/* ============================================================
   Catalog View
   ============================================================ */

function CatalogView() {
  const [assets, setAssets] = useState<CatalogAsset[]>([]);
  const [keyword, setKeyword] = useState('');
  const [assetType, setAssetType] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<CatalogAsset | null>(null);

  const fetchAssets = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (keyword) params.set('keyword', keyword);
      if (assetType) params.set('asset_type', assetType);
      const resp = await fetch(`/api/catalog?${params}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setAssets(data.assets || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchAssets();
    const interval = setInterval(fetchAssets, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const timer = setTimeout(fetchAssets, 300);
    return () => clearTimeout(timer);
  }, [keyword, assetType]);

  if (selectedAsset) {
    return <AssetDetail asset={selectedAsset} onBack={() => setSelectedAsset(null)} />;
  }

  return (
    <div className="catalog-view">
      <div className="catalog-filter-bar">
        <input
          type="text"
          placeholder="搜索资产..."
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="catalog-search"
        />
        <select
          value={assetType}
          onChange={(e) => setAssetType(e.target.value)}
          className="catalog-type-select"
        >
          <option value="">全部类型</option>
          <option value="vector">矢量</option>
          <option value="raster">栅格</option>
          <option value="tabular">表格</option>
          <option value="map">地图</option>
          <option value="report">报告</option>
        </select>
      </div>
      {loading && assets.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : assets.length === 0 ? (
        <div className="empty-state">暂无数据资产</div>
      ) : (
        <ul className="file-list">
          {assets.map((asset) => (
            <li key={asset.id} className="file-item" onClick={() => setSelectedAsset(asset)}>
              <div className={`file-icon-circle ${getAssetCategory(asset.asset_type)}`}>
                {getAssetIcon(asset.asset_type)}
              </div>
              <div className="file-info">
                <div className="file-name" title={asset.asset_name}>{asset.asset_name}</div>
                <div className="file-meta">
                  <span className={`type-badge ${asset.asset_type}`}>{asset.asset_type}</span>
                  {asset.feature_count > 0 && <span>{asset.feature_count} 要素</span>}
                  {asset.crs && <span>{asset.crs}</span>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssetDetail({ asset, onBack }: { asset: CatalogAsset; onBack: () => void }) {
  const [lineage, setLineage] = useState<any>(null);

  useEffect(() => {
    fetch(`/api/catalog/${asset.id}/lineage`, { credentials: 'include' })
      .then((r) => r.json())
      .then(setLineage)
      .catch(() => {});
  }, [asset.id]);

  return (
    <div className="asset-detail">
      <button className="asset-back-btn" onClick={onBack}>&larr; 返回列表</button>
      <h3 className="asset-detail-title">{asset.asset_name}</h3>
      <div className="asset-detail-grid">
        <div className="asset-detail-item"><span>类型</span><span className={`type-badge ${asset.asset_type}`}>{asset.asset_type}</span></div>
        <div className="asset-detail-item"><span>格式</span><span>{asset.file_format || '-'}</span></div>
        <div className="asset-detail-item"><span>存储</span><span>{asset.storage_backend || '-'}</span></div>
        <div className="asset-detail-item"><span>CRS</span><span>{asset.crs || '-'}</span></div>
        <div className="asset-detail-item"><span>要素数</span><span>{asset.feature_count || 0}</span></div>
        <div className="asset-detail-item"><span>大小</span><span>{formatSize(asset.file_size_bytes || 0)}</span></div>
        {asset.description && <div className="asset-detail-item full"><span>描述</span><span>{asset.description}</span></div>}
        {asset.tags && <div className="asset-detail-item full"><span>标签</span><span>{asset.tags}</span></div>}
      </div>
      {lineage && (
        <div className="lineage-section">
          <h4>数据血缘</h4>
          {lineage.ancestors && lineage.ancestors.length > 0 && (
            <div className="lineage-group">
              <span className="lineage-label">来源</span>
              {lineage.ancestors.map((a: any, i: number) => (
                <div key={i} className="lineage-item">{a.asset_name || a.name || `Asset #${a.id}`}</div>
              ))}
            </div>
          )}
          {lineage.descendants && lineage.descendants.length > 0 && (
            <div className="lineage-group">
              <span className="lineage-label">派生</span>
              {lineage.descendants.map((d: any, i: number) => (
                <div key={i} className="lineage-item">{d.asset_name || d.name || `Asset #${d.id}`}</div>
              ))}
            </div>
          )}
          {(!lineage.ancestors || lineage.ancestors.length === 0) &&
           (!lineage.descendants || lineage.descendants.length === 0) && (
            <div className="empty-state" style={{ height: 60 }}>无血缘关系</div>
          )}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   History View
   ============================================================ */

function HistoryView() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/pipeline/history?days=${days}&limit=50`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setRuns(data.runs || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchHistory(); }, [days]);

  return (
    <div className="history-view">
      <div className="history-filter">
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            className={`history-range-btn ${days === d ? 'active' : ''}`}
            onClick={() => setDays(d)}
          >
            {d}天
          </button>
        ))}
      </div>
      {loading && runs.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : runs.length === 0 ? (
        <div className="empty-state">暂无分析记录</div>
      ) : (
        <div className="history-timeline">
          {runs.map((run, i) => (
            <div key={i} className="history-item">
              <div className="history-item-header">
                <span className={`pipeline-badge ${run.pipeline_type}`}>
                  {getPipelineLabel(run.pipeline_type)}
                </span>
                <span className="history-time">{formatTime(run.timestamp)}</span>
              </div>
              <div className="history-item-body">
                <span>意图: {run.intent}</span>
                <span>Token: {(run.input_tokens + run.output_tokens).toLocaleString()}</span>
                {run.files_generated > 0 && <span>{run.files_generated} 文件</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   Usage View
   ============================================================ */

interface UsageData {
  daily: { count: number; tokens: number };
  monthly: { count: number; total_tokens: number; input_tokens: number; output_tokens: number };
  limits: { allowed: boolean; reason: string; daily_count: number; daily_limit: number };
  pipeline_breakdown: { pipeline_type: string; count: number; tokens: number }[];
}

function UsageView() {
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchUsage = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/user/token-usage', { credentials: 'include' });
      if (resp.ok) setUsage(await resp.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchUsage();
    const interval = setInterval(fetchUsage, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading && !usage) return <div className="empty-state">加载中...</div>;
  if (!usage) return <div className="empty-state">无法获取用量数据</div>;

  const dailyPct = usage.limits.daily_limit > 0
    ? Math.min(100, Math.round((usage.limits.daily_count / usage.limits.daily_limit) * 100))
    : 0;

  const maxTokens = usage.pipeline_breakdown.length > 0
    ? Math.max(...usage.pipeline_breakdown.map((b) => b.tokens))
    : 1;

  return (
    <div className="usage-view">
      <div className="usage-card">
        <div className="usage-card-title">今日用量</div>
        <div className="usage-card-value">{usage.limits.daily_count} / {usage.limits.daily_limit}</div>
        <div className="usage-progress">
          <div
            className={`usage-progress-fill ${dailyPct >= 90 ? 'warning' : ''}`}
            style={{ width: `${dailyPct}%` }}
          />
        </div>
        <div className="usage-card-sub">{usage.daily.tokens.toLocaleString()} tokens</div>
      </div>

      <div className="usage-card">
        <div className="usage-card-title">本月汇总</div>
        <div className="usage-card-value">{usage.monthly.total_tokens.toLocaleString()}</div>
        <div className="usage-card-sub">tokens</div>
        <div className="usage-detail-row">
          <span>输入</span><span>{usage.monthly.input_tokens.toLocaleString()}</span>
        </div>
        <div className="usage-detail-row">
          <span>输出</span><span>{usage.monthly.output_tokens.toLocaleString()}</span>
        </div>
        <div className="usage-detail-row">
          <span>分析次数</span><span>{usage.monthly.count}</span>
        </div>
      </div>

      {usage.pipeline_breakdown.length > 0 && (
        <div className="usage-card">
          <div className="usage-card-title">本月管线分布</div>
          {usage.pipeline_breakdown.map((b) => (
            <div key={b.pipeline_type} className="usage-breakdown-row">
              <div className="usage-breakdown-label">
                <span className={`pipeline-badge ${b.pipeline_type}`}>
                  {getPipelineLabel(b.pipeline_type)}
                </span>
                <span className="usage-breakdown-count">{b.count}次</span>
              </div>
              <div className="usage-progress">
                <div
                  className="usage-progress-fill"
                  style={{ width: `${Math.round((b.tokens / maxTokens) * 100)}%` }}
                />
              </div>
              <div className="usage-breakdown-tokens">{b.tokens.toLocaleString()}</div>
            </div>
          ))}
        </div>
      )}

      {!usage.limits.allowed && (
        <div className="usage-limit-warning">{usage.limits.reason}</div>
      )}
    </div>
  );
}

/* ============================================================
   Tools View (MCP Tool Market)
   ============================================================ */

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

function ToolsView({ userRole }: { userRole?: string }) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [selectedServer, setSelectedServer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
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
          <div className="mcp-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => setShowAddForm(false)}>取消</button>
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

/* ============================================================
   Workflows View (v5.4)
   ============================================================ */

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

function WorkflowsView() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editWorkflow, setEditWorkflow] = useState<any>(null);
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [viewRunsFor, setViewRunsFor] = useState<number | null>(null);
  const [executing, setExecuting] = useState<number | null>(null);

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
    try {
      await fetch(`/api/workflows/${id}/execute`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameters: {} }),
      });
    } catch { /* ignore */ }
    finally { setExecuting(null); }
    fetchWorkflows();
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

/* ============================================================
   Shared components
   ============================================================ */

function FileList({ files, onFileClick }: { files: FileInfo[]; onFileClick: (f: FileInfo) => void }) {
  if (files.length === 0) {
    return <div className="empty-state">暂无文件<br />上传数据后将在此显示</div>;
  }
  return (
    <ul className="file-list">
      {files.map((file) => (
        <li key={file.name} className="file-item" onClick={() => onFileClick(file)}>
          <div className={`file-icon-circle ${getIconCategory(file.type)}`}>
            {getFileIcon(file.type)}
          </div>
          <div className="file-info">
            <div className="file-name" title={file.name}>{file.name}</div>
            <div className="file-meta">{formatSize(file.size)}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function DataTable({ columns, data, loading }: { columns: string[]; data: any[]; loading: boolean }) {
  if (loading) return <div className="empty-state">加载数据中...</div>;
  if (columns.length === 0) return <div className="empty-state">暂无数据<br />分析完成后数据将在此显示</div>;
  return (
    <div className="data-table-container">
      <table className="data-table">
        <thead>
          <tr>{columns.map((col) => <th key={col}>{col}</th>)}</tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i}>
              {columns.map((col) => (
                <td key={col} title={String(row[col] ?? '')}>{String(row[col] ?? '')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ============================================================
   Helpers
   ============================================================ */

function getIconCategory(type: string): string {
  switch (type) {
    case 'shp': case 'geojson': case 'gpkg': case 'kml': case 'prj': case 'dbf': case 'shx': case 'cpg': return 'spatial';
    case 'csv': case 'xlsx': case 'xls': return 'data';
    case 'docx': case 'pdf': return 'doc';
    case 'html': return 'web';
    default: return 'default';
  }
}

function getFileIcon(type: string): string {
  switch (type) {
    case 'shp': case 'geojson': case 'gpkg': case 'kml': case 'prj': case 'dbf': case 'shx': case 'cpg': return '\uD83D\uDDFA\uFE0F';
    case 'csv': case 'xlsx': case 'xls': return '\uD83D\uDCCA';
    case 'html': return '\uD83C\uDF10';
    case 'png': case 'jpg': case 'tif': return '\uD83D\uDDBC\uFE0F';
    case 'docx': case 'pdf': return '\uD83D\uDCC4';
    default: return '\uD83D\uDCC1';
  }
}

function getAssetCategory(type: string): string {
  switch (type) {
    case 'vector': return 'spatial';
    case 'raster': return 'spatial';
    case 'tabular': return 'data';
    case 'map': return 'web';
    case 'report': return 'doc';
    default: return 'default';
  }
}

function getAssetIcon(type: string): string {
  switch (type) {
    case 'vector': return '\uD83D\uDDFA\uFE0F';
    case 'raster': return '\uD83C\uDF0D';
    case 'tabular': return '\uD83D\uDCCA';
    case 'map': return '\uD83C\uDF10';
    case 'report': return '\uD83D\uDCC4';
    default: return '\uD83D\uDCC1';
  }
}

function getPipelineLabel(type: string): string {
  switch (type) {
    case 'optimization': return '空间优化';
    case 'governance': return '数据治理';
    case 'general': return '通用分析';
    case 'planner': return '动态规划';
    default: return type;
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(ts: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}
