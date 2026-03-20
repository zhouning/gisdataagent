import { useState, useEffect } from 'react';
import Papa from 'papaparse';
import WorkflowEditor from './WorkflowEditor';

interface DataPanelProps {
  dataFile: string | null;
  userRole?: string;
}

type TabKey = 'files' | 'table' | 'catalog' | 'history' | 'usage' | 'tools' | 'workflows' | 'suggestions' | 'tasks' | 'templates' | 'analytics' | 'capabilities' | 'kb' | 'vsources' | 'market';

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
        <button className={`data-panel-tab ${activeTab === 'suggestions' ? 'active' : ''}`}
          onClick={() => setActiveTab('suggestions')}>建议</button>
        <button className={`data-panel-tab ${activeTab === 'tasks' ? 'active' : ''}`}
          onClick={() => setActiveTab('tasks')}>任务</button>
        <button className={`data-panel-tab ${activeTab === 'templates' ? 'active' : ''}`}
          onClick={() => setActiveTab('templates')}>模板</button>
        <button className={`data-panel-tab ${activeTab === 'analytics' ? 'active' : ''}`}
          onClick={() => setActiveTab('analytics')}>分析</button>
        <button className={`data-panel-tab ${activeTab === 'capabilities' ? 'active' : ''}`}
          onClick={() => setActiveTab('capabilities')}>能力</button>
        <button className={`data-panel-tab ${activeTab === 'kb' ? 'active' : ''}`}
          onClick={() => setActiveTab('kb')}>知识库</button>
        <button className={`data-panel-tab ${activeTab === 'vsources' ? 'active' : ''}`}
          onClick={() => setActiveTab('vsources')}>数据源</button>
        <button className={`data-panel-tab ${activeTab === 'market' ? 'active' : ''}`}
          onClick={() => setActiveTab('market')}>市场</button>
      </div>

      <div className="data-panel-content">
        {activeTab === 'files' && <FileList files={files} onFileClick={handleFileClick} />}
        {activeTab === 'table' && <DataTable columns={tableColumns} data={tableData} loading={loading} />}
        {activeTab === 'catalog' && <CatalogView />}
        {activeTab === 'history' && <HistoryView />}
        {activeTab === 'usage' && <UsageView />}
        {activeTab === 'tools' && <ToolsView userRole={userRole} />}
        {activeTab === 'workflows' && <WorkflowsView />}
        {activeTab === 'suggestions' && <SuggestionsView />}
        {activeTab === 'tasks' && <TasksView />}
        {activeTab === 'templates' && <TemplatesView />}
        {activeTab === 'analytics' && <AnalyticsView />}
        {activeTab === 'capabilities' && <CapabilitiesView userRole={userRole} />}
        {activeTab === 'kb' && <KnowledgeBaseView />}
        {activeTab === 'vsources' && <VirtualSourcesView />}
        {activeTab === 'market' && <MarketplaceView />}
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
          {(lineage.ancestors?.length > 0 || lineage.descendants?.length > 0) ? (
            <div className="lineage-dag">
              {/* Ancestors column */}
              {lineage.ancestors?.length > 0 && (
                <div className="lineage-col">
                  {lineage.ancestors.map((a: any, i: number) => (
                    <div key={i} className="lineage-node ancestor">
                      <div className="lineage-node-name">{a.name || `#${a.id}`}</div>
                      {a.type && <span className={`type-badge ${a.type}`}>{a.type}</span>}
                      {a.creation_tool && <div className="lineage-node-tool">{a.creation_tool}</div>}
                    </div>
                  ))}
                </div>
              )}
              {/* Arrow */}
              {lineage.ancestors?.length > 0 && (
                <div className="lineage-arrow">
                  <svg width="32" height="24"><path d="M4 12 L24 12" stroke="var(--primary)" strokeWidth="2" fill="none"/><path d="M20 7 L28 12 L20 17" stroke="var(--primary)" strokeWidth="2" fill="none"/></svg>
                </div>
              )}
              {/* Current asset (center) */}
              <div className="lineage-col">
                <div className="lineage-node current">
                  <div className="lineage-node-name">{lineage.asset?.name || asset.asset_name}</div>
                  {lineage.asset?.type && <span className={`type-badge ${lineage.asset.type}`}>{lineage.asset.type}</span>}
                </div>
              </div>
              {/* Arrow */}
              {lineage.descendants?.length > 0 && (
                <div className="lineage-arrow">
                  <svg width="32" height="24"><path d="M4 12 L24 12" stroke="var(--primary)" strokeWidth="2" fill="none"/><path d="M20 7 L28 12 L20 17" stroke="var(--primary)" strokeWidth="2" fill="none"/></svg>
                </div>
              )}
              {/* Descendants column */}
              {lineage.descendants?.length > 0 && (
                <div className="lineage-col">
                  {lineage.descendants.map((d: any, i: number) => (
                    <div key={i} className="lineage-node descendant">
                      <div className="lineage-node-name">{d.name || `#${d.id}`}</div>
                      {d.type && <span className={`type-badge ${d.type}`}>{d.type}</span>}
                      {d.creation_tool && <div className="lineage-node-tool">{d.creation_tool}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
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

/* ============================================================
   Capabilities View — Skills & Toolsets Browser
   ============================================================ */

interface CapabilityItem {
  name: string;
  description: string;
  domain?: string;
  version?: string;
  intent_triggers?: string;
  type: string;
  id?: number;
  owner_username?: string;
  skill_name?: string;
  toolset_names?: string[];
  trigger_keywords?: string[];
  model_tier?: string;
  is_shared?: boolean;
}

type CapFilter = 'all' | 'builtin_skill' | 'custom_skill' | 'toolset' | 'user_tool' | 'bundle' | 'template';

const TOOLSETS = [
  { name: 'ExplorationToolset', label: '数据探查与质量审计' },
  { name: 'GeoProcessingToolset', label: '缓冲区、叠加、裁剪' },
  { name: 'LocationToolset', label: '地理编码、POI搜索' },
  { name: 'AnalysisToolset', label: '空间统计与属性分析' },
  { name: 'VisualizationToolset', label: '地图渲染、3D可视化' },
  { name: 'DatabaseToolset', label: 'PostGIS查询与管理' },
  { name: 'FileToolset', label: '文件读写与格式转换' },
  { name: 'MemoryToolset', label: '空间记忆存储与检索' },
  { name: 'AdminToolset', label: '用户管理与系统配置' },
  { name: 'RemoteSensingToolset', label: '遥感影像与DEM下载' },
  { name: 'SpatialStatisticsToolset', label: '空间自相关与热点' },
  { name: 'SemanticLayerToolset', label: '语义目录浏览' },
  { name: 'StreamingToolset', label: '流式输出与进度推送' },
  { name: 'TeamToolset', label: '团队协作与资产共享' },
  { name: 'DataLakeToolset', label: '数据湖资产注册' },
  { name: 'McpHubToolset', label: 'MCP外部工具集成' },
  { name: 'FusionToolset', label: '多源数据融合' },
  { name: 'KnowledgeGraphToolset', label: '知识图谱构建' },
  { name: 'KnowledgeBaseToolset', label: '知识库与RAG检索' },
  { name: 'AdvancedAnalysisToolset', label: '时序、网络、假设分析' },
  { name: 'SpatialAnalysisTier2Toolset', label: '高级空间分析' },
  { name: 'WatershedToolset', label: '流域提取与水文分析' },
  { name: 'UserToolset', label: '用户自定义工具' },
];

const EMPTY_SKILL_FORM = {
  skill_name: '', instruction: '', description: '',
  toolset_names: [] as string[], trigger_keywords: '',
  model_tier: 'standard', is_shared: false,
};

function CapabilitiesView({ userRole }: { userRole?: string }) {
  const [items, setItems] = useState<CapabilityItem[]>([]);
  const [filter, setFilter] = useState<CapFilter>('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [counts, setCounts] = useState({ builtin: 0, custom: 0, toolset: 0 });

  // Skill form state
  const [showSkillForm, setShowSkillForm] = useState(false);
  const [editingSkill, setEditingSkill] = useState<CapabilityItem | null>(null);
  const [skillForm, setSkillForm] = useState({ ...EMPTY_SKILL_FORM });
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  // User tool form state
  const [showToolForm, setShowToolForm] = useState(false);
  const [editingTool, setEditingTool] = useState<any>(null);
  const [toolForm, setToolForm] = useState({
    tool_name: '', description: '', template_type: 'http_call',
    template_config: '{}', parameters: [] as {name: string; type: string; description: string; required: boolean; default?: string}[],
    is_shared: false,
  });
  const [toolError, setToolError] = useState('');
  const [savingTool, setSavingTool] = useState(false);

  // Bundle state
  const [bundles, setBundles] = useState<any[]>([]);
  const [showBundleForm, setShowBundleForm] = useState(false);
  const [editingBundle, setEditingBundle] = useState<any>(null);
  const [bundleForm, setBundleForm] = useState({ bundle_name: '', description: '', toolset_names: [] as string[], skill_names: [] as string[], intent_triggers: '', is_shared: false });
  const [bundleError, setBundleError] = useState('');
  const [savingBundle, setSavingBundle] = useState(false);
  const [availableTools, setAvailableTools] = useState<{ toolsets: string[]; skills: string[] }>({ toolsets: [], skills: [] });
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  const fetchCapabilities = async () => {
    setLoading(true);
    try {
      const [capResp, utResp, bundleResp, availResp, tmplResp] = await Promise.all([
        fetch('/api/capabilities', { credentials: 'include' }),
        fetch('/api/user-tools', { credentials: 'include' }),
        fetch('/api/bundles', { credentials: 'include' }),
        fetch('/api/bundles/available-tools', { credentials: 'include' }),
        fetch('/api/templates', { credentials: 'include' }),
      ]);
      let builtin: CapabilityItem[] = [], custom: CapabilityItem[] = [], toolsets: CapabilityItem[] = [], userTools: CapabilityItem[] = [];
      if (capResp.ok) {
        const data = await capResp.json();
        builtin = data.builtin_skills || [];
        custom = (data.custom_skills || []).map((s: any) => ({
          ...s, name: s.skill_name, type: 'custom_skill',
          intent_triggers: (s.trigger_keywords || []).join(', '),
        }));
        toolsets = data.toolsets || [];
      }
      if (utResp.ok) {
        const utData = await utResp.json();
        userTools = (utData.tools || []).map((t: any) => ({
          ...t, name: t.tool_name, type: 'user_tool',
        }));
      }
      if (bundleResp.ok) {
        const bData = await bundleResp.json();
        setBundles(bData.bundles || []);
      }
      if (availResp.ok) {
        setAvailableTools(await availResp.json());
      }
      let templateItems: CapabilityItem[] = [];
      if (tmplResp.ok) {
        const tData = await tmplResp.json();
        templateItems = (tData.templates || []).map((t: any) => ({
          ...t, name: t.template_name, type: 'template' as const,
          description: `[${t.category || '通用'}] ${t.description || ''}`,
          domain: t.category,
        }));
      }
      setItems([...builtin, ...custom, ...toolsets, ...userTools, ...templateItems]);
      setCounts({ builtin: builtin.length, custom: custom.length, toolset: toolsets.length, userTool: userTools.length, template: templateItems.length } as any);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchCapabilities(); }, []);

  const handleDeleteSkill = async (id: number) => {
    if (!confirm('确定删除此自定义技能？')) return;
    try {
      const resp = await fetch(`/api/skills/${id}`, { method: 'DELETE', credentials: 'include' });
      if (resp.ok) fetchCapabilities();
    } catch { /* ignore */ }
  };

  const handleEditSkill = (item: CapabilityItem) => {
    setEditingSkill(item);
    setSkillForm({
      skill_name: item.skill_name || item.name || '',
      instruction: (item as any).instruction || '',
      description: item.description || '',
      toolset_names: item.toolset_names || [],
      trigger_keywords: (item.trigger_keywords || []).join(', '),
      model_tier: item.model_tier || 'standard',
      is_shared: item.is_shared || false,
    });
    setFormError('');
    setShowSkillForm(true);
  };

  const handleNewSkill = () => {
    setEditingSkill(null);
    setSkillForm({ ...EMPTY_SKILL_FORM });
    setFormError('');
    setShowSkillForm(true);
  };

  const handleSaveSkill = async () => {
    setFormError('');
    if (!skillForm.skill_name.trim()) { setFormError('技能名称必填'); return; }
    if (!skillForm.instruction.trim()) { setFormError('指令必填'); return; }
    setSaving(true);
    try {
      const body = {
        skill_name: skillForm.skill_name.trim(),
        instruction: skillForm.instruction.trim(),
        description: skillForm.description.trim(),
        toolset_names: skillForm.toolset_names,
        trigger_keywords: skillForm.trigger_keywords.split(',').map(s => s.trim()).filter(Boolean),
        model_tier: skillForm.model_tier,
        is_shared: skillForm.is_shared,
      };
      const url = editingSkill ? `/api/skills/${editingSkill.id}` : '/api/skills';
      const method = editingSkill ? 'PUT' : 'POST';
      const resp = await fetch(url, {
        method, credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowSkillForm(false);
        setEditingSkill(null);
        setSkillForm({ ...EMPTY_SKILL_FORM });
        fetchCapabilities();
      } else {
        setFormError(data.error || '保存失败');
      }
    } catch { setFormError('网络错误'); }
    finally { setSaving(false); }
  };

  const toggleToolset = (name: string) => {
    setSkillForm(f => ({
      ...f,
      toolset_names: f.toolset_names.includes(name)
        ? f.toolset_names.filter(n => n !== name)
        : [...f.toolset_names, name],
    }));
  };

  // --- User Tool handlers ---
  const handleNewTool = () => {
    setEditingTool(null);
    setToolForm({ tool_name: '', description: '', template_type: 'http_call', template_config: '{}', parameters: [], is_shared: false });
    setToolError(''); setTestResult(null);
    setShowToolForm(true); setShowSkillForm(false);
  };

  const handleEditTool = (item: any) => {
    setEditingTool(item);
    setToolForm({
      tool_name: item.tool_name || item.name || '',
      description: item.description || '',
      template_type: item.template_type || 'http_call',
      template_config: JSON.stringify(item.template_config || {}, null, 2),
      parameters: item.parameters || [],
      is_shared: item.is_shared || false,
    });
    setToolError(''); setTestResult(null);
    setShowToolForm(true); setShowSkillForm(false);
  };

  const handleDeleteTool = async (id: number) => {
    if (!confirm('确定删除此自定义工具？')) return;
    try {
      const resp = await fetch(`/api/user-tools/${id}`, { method: 'DELETE', credentials: 'include' });
      if (resp.ok) fetchCapabilities();
    } catch { /* ignore */ }
  };

  const handleSaveTool = async () => {
    setToolError('');
    if (!toolForm.tool_name.trim()) { setToolError('工具名称必填'); return; }
    let configObj: any;
    try { configObj = JSON.parse(toolForm.template_config); }
    catch { setToolError('模板配置必须是有效 JSON'); return; }
    setSavingTool(true);
    try {
      const body = {
        tool_name: toolForm.tool_name.trim(),
        description: toolForm.description.trim(),
        template_type: toolForm.template_type,
        template_config: configObj,
        parameters: toolForm.parameters,
        is_shared: toolForm.is_shared,
      };
      const url = editingTool ? `/api/user-tools/${editingTool.id}` : '/api/user-tools';
      const method = editingTool ? 'PUT' : 'POST';
      const resp = await fetch(url, {
        method, credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowToolForm(false); setEditingTool(null);
        fetchCapabilities();
      } else { setToolError(data.error || '保存失败'); }
    } catch { setToolError('网络错误'); }
    finally { setSavingTool(false); }
  };

  const handleTestTool = async () => {
    if (!editingTool?.id) return;
    setTesting(true); setTestResult(null);
    const testParams: Record<string, string> = {};
    toolForm.parameters.forEach(p => { testParams[p.name] = p.default || ''; });
    try {
      const resp = await fetch(`/api/user-tools/${editingTool.id}/test`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params: testParams }),
      });
      const data = await resp.json();
      setTestResult(data.result || data.message || JSON.stringify(data));
    } catch (e) { setTestResult('测试失败: ' + e); }
    finally { setTesting(false); }
  };

  const addParam = () => {
    setToolForm(f => ({
      ...f, parameters: [...f.parameters, { name: '', type: 'string', description: '', required: true }],
    }));
  };

  const updateParam = (idx: number, field: string, value: any) => {
    setToolForm(f => {
      const params = [...f.parameters];
      (params[idx] as any)[field] = value;
      return { ...f, parameters: params };
    });
  };

  const removeParam = (idx: number) => {
    setToolForm(f => ({ ...f, parameters: f.parameters.filter((_, i) => i !== idx) }));
  };

  const TEMPLATE_TYPES = [
    { value: 'http_call', label: 'HTTP 调用' },
    { value: 'sql_query', label: 'SQL 查询' },
    { value: 'file_transform', label: '文件转换' },
    { value: 'chain', label: '链式组合' },
    { value: 'python_sandbox', label: 'Python 沙箱' },
  ];

  const TEMPLATE_HINTS: Record<string, string> = {
    http_call: '{"method":"GET","url":"https://api.example.com/data","headers":{},"extract_path":"data.result"}',
    sql_query: '{"query":"SELECT * FROM parcels WHERE area > :min_area","readonly":true}',
    file_transform: '{"operations":[{"op":"filter","column":"area","condition":">","value":100}],"output_format":"geojson"}',
    chain: '{"steps":[{"tool_name":"my_query","param_map":{"x":"$input.x"}}]}',
    python_sandbox: '{"python_code":"def tool_function(params):\\n    # 在此编写处理逻辑\\n    return {\\\"result\\\": params.get(\\\"input\\\", \\\"hello\\\")}","timeout":30}',
  };

  const filtered = items.filter(item => {
    if (filter !== 'all' && item.type !== filter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (item.name || '').toLowerCase().includes(q)
      || (item.description || '').toLowerCase().includes(q)
      || (item.domain || '').toLowerCase().includes(q)
      || (item.intent_triggers || '').toLowerCase().includes(q);
  });

  const domainMap: Record<string, string> = {
    gis: 'GIS', governance: '治理', visualization: '可视化',
    analysis: '分析', database: '数据库', fusion: '融合',
    collaboration: '协作', general: '通用',
  };

  const typeLabel = (t: string) =>
    t === 'builtin_skill' ? '内置技能' : t === 'custom_skill' ? '自定义技能' : t === 'user_tool' ? '自定义工具' : t === 'template' ? '行业模板' : '工具集';

  const typeClass = (t: string) =>
    t === 'builtin_skill' ? 'cap-type-builtin' : t === 'custom_skill' ? 'cap-type-custom' : t === 'user_tool' ? 'cap-type-usertool' : t === 'template' ? 'cap-type-template' : 'cap-type-toolset';

  return (
    <div className="capabilities-view">
      <div className="capabilities-summary">
        <span>{(counts as any).builtin} 内置技能</span>
        <span className="cap-sep">/</span>
        <span>{(counts as any).custom} 自定义</span>
        <span className="cap-sep">/</span>
        <span>{(counts as any).toolset} 工具集</span>
        <span className="cap-sep">/</span>
        <span>{(counts as any).userTool || 0} 自建工具</span>
        <button className="btn-add-server" onClick={() => showSkillForm ? setShowSkillForm(false) : handleNewSkill()} title="新建自定义技能">+技能</button>
        <button className="btn-add-server" onClick={() => showToolForm ? setShowToolForm(false) : handleNewTool()} title="新建自定义工具">+工具</button>
      </div>

      {showSkillForm && (
        <div className="skill-add-form">
          <div className="skill-add-form-title">{editingSkill ? `编辑: ${editingSkill.name}` : '新建自定义技能'}</div>
          <input placeholder="技能名称 (必填，如: 土壤分析专家)" maxLength={100}
            value={skillForm.skill_name} onChange={e => setSkillForm({ ...skillForm, skill_name: e.target.value })} />
          <textarea placeholder="指令 (必填，描述技能的行为和专业知识，最多10000字)" rows={4} maxLength={10000}
            value={skillForm.instruction} onChange={e => setSkillForm({ ...skillForm, instruction: e.target.value })} />
          <input placeholder="描述 (可选)" value={skillForm.description}
            onChange={e => setSkillForm({ ...skillForm, description: e.target.value })} />
          <div className="skill-section-label">选择工具集</div>
          <div className="skill-toolset-grid">
            {TOOLSETS.map(t => (
              <label key={t.name} className="skill-toolset-item">
                <input type="checkbox" checked={skillForm.toolset_names.includes(t.name)}
                  onChange={() => toggleToolset(t.name)} />
                <span>{t.label}</span>
              </label>
            ))}
          </div>
          <input placeholder="触发关键词 (逗号分隔，如: 土壤, 地质)" value={skillForm.trigger_keywords}
            onChange={e => setSkillForm({ ...skillForm, trigger_keywords: e.target.value })} />
          <div className="skill-row">
            <select value={skillForm.model_tier} onChange={e => setSkillForm({ ...skillForm, model_tier: e.target.value })}>
              <option value="fast">快速 (fast)</option>
              <option value="standard">标准 (standard)</option>
              <option value="premium">高级 (premium)</option>
            </select>
            <label className="skill-checkbox">
              <input type="checkbox" checked={skillForm.is_shared}
                onChange={e => setSkillForm({ ...skillForm, is_shared: e.target.checked })} />
              共享给其他用户
            </label>
          </div>
          {formError && <div className="skill-add-error">{formError}</div>}
          <div className="skill-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => { setShowSkillForm(false); setEditingSkill(null); }}>取消</button>
            <button className="btn-primary btn-sm" disabled={saving} onClick={handleSaveSkill}>
              {saving ? '保存中...' : editingSkill ? '保存' : '创建'}
            </button>
          </div>
        </div>
      )}

      {showToolForm && (
        <div className="skill-add-form">
          <div className="skill-add-form-title">{editingTool ? `编辑工具: ${editingTool.name}` : '新建自定义工具'}</div>
          <input placeholder="工具名称 (必填，如: query_weather)" maxLength={100}
            value={toolForm.tool_name} onChange={e => setToolForm({ ...toolForm, tool_name: e.target.value })} />
          <input placeholder="描述 (给 LLM 看的工具说明)" value={toolForm.description}
            onChange={e => setToolForm({ ...toolForm, description: e.target.value })} />
          <div className="skill-row">
            <select value={toolForm.template_type} onChange={e => {
              const tt = e.target.value;
              setToolForm({ ...toolForm, template_type: tt, template_config: TEMPLATE_HINTS[tt] || '{}' });
            }}>
              {TEMPLATE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            <label className="skill-checkbox">
              <input type="checkbox" checked={toolForm.is_shared}
                onChange={e => setToolForm({ ...toolForm, is_shared: e.target.checked })} />
              共享
            </label>
          </div>

          <div className="skill-section-label">参数定义 <button className="param-add-btn" onClick={addParam}>+ 添加参数</button></div>
          {toolForm.parameters.map((p, idx) => (
            <div key={idx} className="param-row">
              <input placeholder="参数名" value={p.name} className="param-name"
                onChange={e => updateParam(idx, 'name', e.target.value)} />
              <select value={p.type} onChange={e => updateParam(idx, 'type', e.target.value)}>
                <option value="string">string</option>
                <option value="number">number</option>
                <option value="integer">integer</option>
                <option value="boolean">boolean</option>
              </select>
              <input placeholder="说明" value={p.description} className="param-desc"
                onChange={e => updateParam(idx, 'description', e.target.value)} />
              <button className="param-remove-btn" onClick={() => removeParam(idx)}>×</button>
            </div>
          ))}

          <div className="skill-section-label">模板配置 (JSON)</div>
          <textarea className="tool-config-editor" rows={5} value={toolForm.template_config}
            onChange={e => setToolForm({ ...toolForm, template_config: e.target.value })}
            placeholder={TEMPLATE_HINTS[toolForm.template_type] || '{}'} />

          {toolError && <div className="skill-add-error">{toolError}</div>}
          {testResult && <div className="tool-test-result">{testResult}</div>}
          <div className="skill-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => { setShowToolForm(false); setEditingTool(null); }}>取消</button>
            {editingTool?.id && <button className="btn-secondary btn-sm" disabled={testing} onClick={handleTestTool}>{testing ? '测试中...' : '测试'}</button>}
            <button className="btn-primary btn-sm" disabled={savingTool} onClick={handleSaveTool}>
              {savingTool ? '保存中...' : editingTool ? '保存' : '创建'}
            </button>
          </div>
        </div>
      )}

      <input className="capabilities-search" placeholder="搜索技能或工具集..."
        value={search} onChange={e => setSearch(e.target.value)} />

      <div className="capabilities-filters">
        {(['all', 'builtin_skill', 'custom_skill', 'toolset', 'user_tool', 'bundle', 'template'] as CapFilter[]).map(f => (
          <button key={f} className={`cap-filter-btn ${filter === f ? 'active' : ''}`}
            onClick={() => setFilter(f)}>
            {f === 'all' ? '全部' : f === 'builtin_skill' ? '内置技能' : f === 'custom_skill' ? '自定义' : f === 'user_tool' ? '自建工具' : f === 'bundle' ? `技能包(${bundles.length})` : f === 'template' ? '行业模板' : '工具集'}
          </button>
        ))}
      </div>

      {loading && items.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">暂无匹配项</div>
      ) : (
        <div className="capabilities-list">
          {filtered.map((item, i) => (
            <div key={`${item.type}-${item.id || item.name}-${i}`} className="capability-card">
              <div className="cap-card-header">
                <span className="cap-card-name">{item.name}</span>
                <span className={`cap-badge ${typeClass(item.type)}`}>{typeLabel(item.type)}</span>
                {item.domain && <span className="cap-badge cap-domain">{domainMap[item.domain] || item.domain}</span>}
              </div>
              {item.description && <div className="cap-card-desc">{item.description}</div>}
              {item.intent_triggers && (
                <div className="cap-card-triggers">
                  {item.intent_triggers.split(',').map((t, j) => (
                    <span key={j} className="cap-trigger-tag">{t.trim()}</span>
                  ))}
                </div>
              )}
              {item.type === 'custom_skill' && (
                <div className="cap-card-footer">
                  {item.owner_username && <span className="cap-owner">by {item.owner_username}</span>}
                  {item.is_shared && <span className="cap-badge cap-shared">共享</span>}
                  {item.id && (
                    <>
                      <button className="cap-edit-btn" onClick={() => handleEditSkill(item)}>编辑</button>
                      <button className="cap-delete-btn" onClick={() => handleDeleteSkill(item.id!)}>删除</button>
                    </>
                  )}
                </div>
              )}
              {item.type === 'user_tool' && (
                <div className="cap-card-footer">
                  <span className="cap-badge cap-template-type">{(item as any).template_type}</span>
                  {item.owner_username && <span className="cap-owner">by {item.owner_username}</span>}
                  {item.is_shared && <span className="cap-badge cap-shared">共享</span>}
                  {item.id && (
                    <>
                      <button className="cap-edit-btn" onClick={() => handleEditTool(item)}>编辑</button>
                      <button className="cap-delete-btn" onClick={() => handleDeleteTool(item.id!)}>删除</button>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Skill Bundles Section ── */}
      {filter === 'bundle' && (
        <div className="capabilities-list">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: '#6b7280' }}>组合多个工具集+技能为可复用的技能包</span>
            <button className="cap-add-btn" onClick={() => { setEditingBundle(null); setBundleForm({ bundle_name: '', description: '', toolset_names: [], skill_names: [], intent_triggers: '', is_shared: false }); setShowBundleForm(true); }}>+ 技能包</button>
          </div>

          {showBundleForm && (
            <div className="cap-skill-form" style={{ marginBottom: 12 }}>
              <h4>{editingBundle ? '编辑技能包' : '创建技能包'}</h4>
              {bundleError && <div className="cap-form-error">{bundleError}</div>}
              <input placeholder="技能包名称" value={bundleForm.bundle_name} onChange={e => setBundleForm(f => ({ ...f, bundle_name: e.target.value }))} />
              <input placeholder="描述（可选）" value={bundleForm.description} onChange={e => setBundleForm(f => ({ ...f, description: e.target.value }))} />
              <input placeholder="触发关键词（逗号分隔）" value={bundleForm.intent_triggers} onChange={e => setBundleForm(f => ({ ...f, intent_triggers: e.target.value }))} />

              <div style={{ fontSize: 11, fontWeight: 600, marginTop: 8 }}>工具集</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                {(availableTools.toolsets || []).map(ts => (
                  <label key={ts} style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 2 }}>
                    <input type="checkbox" checked={bundleForm.toolset_names.includes(ts)}
                      onChange={e => {
                        const names = e.target.checked ? [...bundleForm.toolset_names, ts] : bundleForm.toolset_names.filter(n => n !== ts);
                        setBundleForm(f => ({ ...f, toolset_names: names }));
                      }} />
                    {ts}
                  </label>
                ))}
              </div>

              <div style={{ fontSize: 11, fontWeight: 600 }}>技能</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                {(availableTools.skills || []).map(sk => (
                  <label key={sk} style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 2 }}>
                    <input type="checkbox" checked={bundleForm.skill_names.includes(sk)}
                      onChange={e => {
                        const names = e.target.checked ? [...bundleForm.skill_names, sk] : bundleForm.skill_names.filter(n => n !== sk);
                        setBundleForm(f => ({ ...f, skill_names: names }));
                      }} />
                    {sk}
                  </label>
                ))}
              </div>

              <label style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                <input type="checkbox" checked={bundleForm.is_shared} onChange={e => setBundleForm(f => ({ ...f, is_shared: e.target.checked }))} />
                共享给其他用户
              </label>

              <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                <button className="cap-save-btn" disabled={savingBundle} onClick={async () => {
                  if (!bundleForm.bundle_name.trim()) { setBundleError('名称不能为空'); return; }
                  if (bundleForm.toolset_names.length === 0 && bundleForm.skill_names.length === 0) { setBundleError('至少选择一个工具集或技能'); return; }
                  setSavingBundle(true); setBundleError('');
                  try {
                    const url = editingBundle ? `/api/bundles/${editingBundle.id}` : '/api/bundles';
                    const method = editingBundle ? 'PUT' : 'POST';
                    const resp = await fetch(url, { method, credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundleForm) });
                    if (!resp.ok) { const d = await resp.json(); setBundleError(d.error || '保存失败'); return; }
                    setShowBundleForm(false); fetchCapabilities();
                  } catch { setBundleError('网络错误'); }
                  finally { setSavingBundle(false); }
                }}>{savingBundle ? '保存中...' : '保存'}</button>
                <button className="cap-cancel-btn" onClick={() => setShowBundleForm(false)}>取消</button>
              </div>
            </div>
          )}

          {bundles.map(b => (
            <div key={b.id} className="capability-card">
              <div className="cap-card-header">
                <span className="cap-type-badge cap-type-custom">技能包</span>
                <span className="cap-name">{b.bundle_name}</span>
              </div>
              {b.description && <div className="cap-description">{b.description}</div>}
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                工具集: {(b.toolset_names || []).join(', ') || '无'} | 技能: {(b.skill_names || []).join(', ') || '无'}
              </div>
              {b.intent_triggers && <div style={{ fontSize: 11, color: '#9ca3af' }}>触发: {b.intent_triggers}</div>}
              <div className="cap-card-actions">
                {b.owner_username && <span className="cap-owner">by {b.owner_username}</span>}
                {b.is_shared && <span className="cap-badge cap-shared">共享</span>}
                <button className="cap-edit-btn" onClick={() => { setEditingBundle(b); setBundleForm({ bundle_name: b.bundle_name, description: b.description || '', toolset_names: b.toolset_names || [], skill_names: b.skill_names || [], intent_triggers: b.intent_triggers || '', is_shared: b.is_shared || false }); setShowBundleForm(true); }}>编辑</button>
                <button className="cap-delete-btn" onClick={async () => {
                  if (!confirm(`确定删除技能包 "${b.bundle_name}"？`)) return;
                  await fetch(`/api/bundles/${b.id}`, { method: 'DELETE', credentials: 'include' });
                  fetchCapabilities();
                }}>删除</button>
              </div>
            </div>
          ))}
          {bundles.length === 0 && !showBundleForm && (
            <div style={{ textAlign: 'center', color: '#9ca3af', padding: 20, fontSize: 12 }}>
              暂无技能包，点击 "+ 技能包" 创建
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   Knowledge Base View
   ============================================================ */

interface KBItem {
  id: number; name: string; description: string;
  owner_username: string; is_shared: boolean;
  doc_count: number; chunk_count: number;
  created_at: string;
}

interface KBDoc {
  id: number; filename: string; content_type: string;
  chunk_count: number; created_at: string;
}

function KnowledgeBaseView() {
  const [kbs, setKbs] = useState<KBItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKb, setSelectedKb] = useState<(KBItem & { documents?: KBDoc[] }) | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createDesc, setCreateDesc] = useState('');
  const [createShared, setCreateShared] = useState(false);
  const [createError, setCreateError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [docText, setDocText] = useState('');
  const [docName, setDocName] = useState('');

  const fetchKbs = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/kb', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setKbs(data.knowledge_bases || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchKbs(); }, []);

  const handleCreate = async () => {
    setCreateError('');
    if (!createName.trim()) { setCreateError('名称必填'); return; }
    try {
      const resp = await fetch('/api/kb', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: createName.trim(), description: createDesc.trim(), is_shared: createShared }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowCreateForm(false);
        setCreateName(''); setCreateDesc(''); setCreateShared(false);
        fetchKbs();
      } else { setCreateError(data.error || '创建失败'); }
    } catch { setCreateError('网络错误'); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此知识库及所有文档？')) return;
    try {
      const resp = await fetch(`/api/kb/${id}`, { method: 'DELETE', credentials: 'include' });
      if (resp.ok) { setSelectedKb(null); fetchKbs(); }
    } catch { /* ignore */ }
  };

  const handleSelectKb = async (kb: KBItem) => {
    try {
      const resp = await fetch(`/api/kb/${kb.id}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setSelectedKb(data);
      }
    } catch { /* ignore */ }
  };

  const handleAddDoc = async () => {
    if (!selectedKb || !docText.trim()) return;
    try {
      const resp = await fetch(`/api/kb/${selectedKb.id}/documents`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: docText.trim(), filename: docName.trim() || 'document.txt' }),
      });
      if (resp.ok) {
        setDocText(''); setDocName('');
        handleSelectKb(selectedKb);
      }
    } catch { /* ignore */ }
  };

  const handleDeleteDoc = async (docId: number) => {
    if (!selectedKb) return;
    try {
      const resp = await fetch(`/api/kb/${selectedKb.id}/documents/${docId}`, { method: 'DELETE', credentials: 'include' });
      if (resp.ok) handleSelectKb(selectedKb);
    } catch { /* ignore */ }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const resp = await fetch('/api/kb/search', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery.trim(), top_k: 5 }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSearchResults(data.results || []);
      }
    } catch { /* ignore */ }
    finally { setSearching(false); }
  };

  // Detail view for a selected KB
  if (selectedKb) {
    return (
      <div className="kb-view">
        <div className="kb-detail-header">
          <button className="btn-secondary btn-sm" onClick={() => setSelectedKb(null)}>← 返回</button>
          <span className="kb-detail-name">{selectedKb.name}</span>
          <button className="cap-delete-btn" onClick={() => handleDelete(selectedKb.id)}>删除</button>
        </div>
        {selectedKb.description && <div className="kb-detail-desc">{selectedKb.description}</div>}

        <div className="skill-section-label">文档 ({(selectedKb.documents || []).length})</div>
        <div className="kb-doc-list">
          {(selectedKb.documents || []).map(doc => (
            <div key={doc.id} className="kb-doc-item">
              <span className="kb-doc-name">{doc.filename}</span>
              <span className="kb-doc-meta">{doc.chunk_count} 块</span>
              <button className="param-remove-btn" onClick={() => handleDeleteDoc(doc.id)}>×</button>
            </div>
          ))}
        </div>

        <div className="skill-section-label">添加文档</div>
        <input placeholder="文件名 (如: 政策文件.txt)" value={docName}
          onChange={e => setDocName(e.target.value)} className="capabilities-search" style={{ margin: '0 0 4px' }} />
        <textarea placeholder="粘贴文档内容..." rows={3} value={docText}
          onChange={e => setDocText(e.target.value)}
          className="tool-config-editor" style={{ margin: '0 0 6px', fontSize: '12px' }} />
        <button className="btn-primary btn-sm" onClick={handleAddDoc} disabled={!docText.trim()}>添加文档</button>

        {/* ── Knowledge Graph Section (GraphRAG v10.0.5) ── */}
        <GraphRAGSection kbId={selectedKb.id} />
      </div>
    );
  }

  return (
    <div className="kb-view">
      <div className="capabilities-summary">
        <span>{kbs.length} 个知识库</span>
        <button className="btn-add-server" onClick={() => setShowCreateForm(!showCreateForm)} title="新建知识库">+</button>
      </div>

      {showCreateForm && (
        <div className="skill-add-form">
          <div className="skill-add-form-title">新建知识库</div>
          <input placeholder="知识库名称 (必填)" value={createName}
            onChange={e => setCreateName(e.target.value)} />
          <input placeholder="描述 (可选)" value={createDesc}
            onChange={e => setCreateDesc(e.target.value)} />
          <label className="skill-checkbox">
            <input type="checkbox" checked={createShared}
              onChange={e => setCreateShared(e.target.checked)} />
            共享给其他用户
          </label>
          {createError && <div className="skill-add-error">{createError}</div>}
          <div className="skill-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => setShowCreateForm(false)}>取消</button>
            <button className="btn-primary btn-sm" onClick={handleCreate}>创建</button>
          </div>
        </div>
      )}

      <div className="kb-search-bar">
        <input className="capabilities-search" placeholder="语义搜索所有知识库..." value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()} />
        <button className="btn-primary btn-sm" onClick={handleSearch} disabled={searching}>
          {searching ? '搜索中...' : '搜索'}
        </button>
      </div>

      {searchResults.length > 0 && (
        <div className="kb-search-results">
          <div className="skill-section-label">搜索结果 ({searchResults.length})</div>
          {searchResults.map((r: any, i: number) => (
            <div key={i} className="kb-search-result-item">
              <div className="kb-result-score">相似度 {(r.score * 100).toFixed(0)}%</div>
              <div className="kb-result-text">{(r.text || r.chunk_text || '').slice(0, 200)}</div>
              <div className="kb-result-meta">{r.kb_name} / {r.filename}</div>
            </div>
          ))}
        </div>
      )}

      {loading && kbs.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : kbs.length === 0 ? (
        <div className="empty-state">暂无知识库，点击 + 创建</div>
      ) : (
        <div className="capabilities-list">
          {kbs.map(kb => (
            <div key={kb.id} className="capability-card" onClick={() => handleSelectKb(kb)} style={{ cursor: 'pointer' }}>
              <div className="cap-card-header">
                <span className="cap-card-name">{kb.name}</span>
                <span className="cap-badge cap-type-builtin">{kb.doc_count || 0} 文档</span>
                <span className="cap-badge cap-domain">{kb.chunk_count || 0} 块</span>
              </div>
              {kb.description && <div className="cap-card-desc">{kb.description}</div>}
              <div className="cap-card-footer">
                <span className="cap-owner">by {kb.owner_username}</span>
                {kb.is_shared && <span className="cap-badge cap-shared">共享</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   GraphRAG Section (Knowledge Graph visualization)
   ============================================================ */

function GraphRAGSection({ kbId }: { kbId: number }) {
  const [building, setBuilding] = useState(false);
  const [graph, setGraph] = useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [entities, setEntities] = useState<any[]>([]);
  const [graphSearch, setGraphSearch] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [tab, setTab] = useState<'entities' | 'graph'>('entities');

  const fetchGraph = async () => {
    try {
      const [gResp, eResp] = await Promise.all([
        fetch(`/api/kb/${kbId}/graph`, { credentials: 'include' }),
        fetch(`/api/kb/${kbId}/entities`, { credentials: 'include' }),
      ]);
      if (gResp.ok) {
        const g = await gResp.json();
        setGraph(g);
      }
      if (eResp.ok) {
        const e = await eResp.json();
        setEntities(e.entities || []);
      }
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchGraph(); }, [kbId]);

  const handleBuild = async () => {
    setBuilding(true);
    try {
      await fetch(`/api/kb/${kbId}/build-graph`, { method: 'POST', credentials: 'include' });
      await fetchGraph();
    } catch { /* ignore */ }
    finally { setBuilding(false); }
  };

  const handleGraphSearch = async () => {
    if (!graphSearch.trim()) return;
    setSearching(true);
    try {
      const resp = await fetch(`/api/kb/${kbId}/graph-search`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: graphSearch.trim() }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSearchResults(data.results || []);
      }
    } catch { /* ignore */ }
    finally { setSearching(false); }
  };

  const nodeCount = graph?.nodes?.length || 0;
  const edgeCount = graph?.edges?.length || 0;

  return (
    <div style={{ marginTop: 12 }}>
      <div className="skill-section-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>知识图谱 ({nodeCount} 实体, {edgeCount} 关系)</span>
        <button className="btn-primary btn-sm" onClick={handleBuild} disabled={building}>
          {building ? '构建中...' : nodeCount > 0 ? '重新构建' : '构建图谱'}
        </button>
      </div>

      {nodeCount > 0 && (
        <>
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            <button className={`cap-filter-btn ${tab === 'entities' ? 'active' : ''}`} onClick={() => setTab('entities')}>实体列表</button>
            <button className={`cap-filter-btn ${tab === 'graph' ? 'active' : ''}`} onClick={() => setTab('graph')}>图谱搜索</button>
          </div>

          {tab === 'entities' && (
            <div style={{ maxHeight: 200, overflow: 'auto' }}>
              {entities.map((ent, i) => (
                <div key={i} style={{ padding: '4px 8px', borderBottom: '1px solid #f0f0f0', fontSize: 12 }}>
                  <span style={{ fontWeight: 500 }}>{ent.name || ent.entity}</span>
                  {ent.type && <span style={{ marginLeft: 6, color: '#6b7280', fontSize: 11 }}>[{ent.type}]</span>}
                  {ent.description && <div style={{ color: '#9ca3af', fontSize: 11 }}>{ent.description}</div>}
                </div>
              ))}
              {entities.length === 0 && <div style={{ color: '#9ca3af', fontSize: 12, padding: 8 }}>暂无实体</div>}
            </div>
          )}

          {tab === 'graph' && (
            <div>
              <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
                <input className="capabilities-search" placeholder="搜索图谱实体或关系..."
                  value={graphSearch} onChange={e => setGraphSearch(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleGraphSearch()}
                  style={{ margin: 0, flex: 1 }} />
                <button className="btn-primary btn-sm" onClick={handleGraphSearch} disabled={searching}>
                  {searching ? '...' : '搜索'}
                </button>
              </div>
              {searchResults.length > 0 && (
                <div style={{ maxHeight: 200, overflow: 'auto' }}>
                  {searchResults.map((r, i) => (
                    <div key={i} style={{ padding: '4px 8px', borderBottom: '1px solid #f0f0f0', fontSize: 12 }}>
                      <div style={{ fontWeight: 500 }}>{r.source} → <span style={{ color: '#6b7280' }}>{r.relation}</span> → {r.target}</div>
                      {r.context && <div style={{ color: '#9ca3af', fontSize: 11 }}>{r.context}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {nodeCount === 0 && !building && (
        <div style={{ textAlign: 'center', color: '#9ca3af', padding: 12, fontSize: 12 }}>
          点击"构建图谱"从文档中提取实体和关系
        </div>
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

/* ============================================================
   Suggestions View (v12.0.3)
   ============================================================ */

function SuggestionsView() {
  const [observations, setObservations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSuggestions();
    const interval = setInterval(fetchSuggestions, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchSuggestions = async () => {
    try {
      const resp = await fetch('/api/suggestions', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setObservations(data.suggestions || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  };

  const executeSuggestion = async (obsId: string, prompt: string, pipelineType: string) => {
    try {
      await fetch(`/api/suggestions/${obsId}/execute`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, pipeline_type: pipelineType }),
      });
      alert('任务已提交到队列');
    } catch { alert('执行失败'); }
  };

  const dismissSuggestion = async (obsId: string) => {
    try {
      await fetch(`/api/suggestions/${obsId}/dismiss`, {
        method: 'POST', credentials: 'include',
      });
      setObservations(prev => prev.filter(o => o.observation_id !== obsId));
    } catch { /* ignore */ }
  };

  if (loading) return <div className="data-panel-empty">加载中...</div>;
  if (observations.length === 0) return <div className="data-panel-empty">暂无分析建议</div>;

  return (
    <div className="data-panel-list">
      {observations.map((obs: any) => (
        <div key={obs.observation_id} className="data-panel-card" style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{obs.file_path?.split(/[/\\]/).pop()}</div>
          {(obs.suggestions || []).map((s: any, i: number) => (
            <div key={i} style={{ padding: '6px 0', borderTop: i > 0 ? '1px solid #333' : 'none' }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{s.title}</div>
              <div style={{ fontSize: 12, color: '#aaa', margin: '2px 0' }}>{s.description}</div>
              <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                <span className="data-panel-badge" style={{ background: '#0d9488' }}>{s.category}</span>
                <span style={{ fontSize: 11, color: '#888' }}>相关度: {'★'.repeat(Math.round((s.relevance_score || 0) * 5))}</span>
              </div>
              <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <button className="data-panel-btn-sm" onClick={() => executeSuggestion(obs.observation_id, s.prompt_template, s.pipeline_type)}>执行</button>
                <button className="data-panel-btn-sm secondary" onClick={() => dismissSuggestion(obs.observation_id)}>忽略</button>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/* ============================================================
   Tasks View (v12.0.3)
   ============================================================ */

function TasksView() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTasks();
    const hasRunning = jobs.some(j => j.status === 'running');
    const interval = setInterval(fetchTasks, hasRunning ? 3000 : 10000);
    return () => clearInterval(interval);
  }, [jobs.length]);

  const fetchTasks = async () => {
    try {
      const resp = await fetch('/api/tasks', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setJobs(data.jobs || []);
        setStats(data.stats || {});
      }
    } catch { /* ignore */ }
    setLoading(false);
  };

  const cancelTask = async (jobId: string) => {
    try {
      await fetch(`/api/tasks/${jobId}`, { method: 'DELETE', credentials: 'include' });
      fetchTasks();
    } catch { /* ignore */ }
  };

  const statusColor: Record<string, string> = {
    queued: '#6b7280', running: '#0d9488', completed: '#22c55e', failed: '#ef4444', cancelled: '#eab308',
  };

  if (loading) return <div className="data-panel-empty">加载中...</div>;

  return (
    <div className="data-panel-list">
      {stats.by_status && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          {Object.entries(stats.by_status).map(([status, count]: any) => (
            <span key={status} className="data-panel-badge" style={{ background: statusColor[status] || '#666' }}>
              {status}: {count}
            </span>
          ))}
          <span style={{ fontSize: 11, color: '#888' }}>并发上限: {stats.max_concurrent}</span>
        </div>
      )}
      {jobs.length === 0 && <div className="data-panel-empty">暂无后台任务</div>}
      {jobs.map((job: any) => (
        <div key={job.job_id} className="data-panel-card" style={{ marginBottom: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontFamily: 'monospace' }}>{job.job_id}</span>
            <span className="data-panel-badge" style={{ background: statusColor[job.status] || '#666' }}>
              {job.status}{job.status === 'running' ? ' ⏳' : ''}
            </span>
          </div>
          <div style={{ fontSize: 12, color: '#ccc', margin: '4px 0' }}>{job.prompt}</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#888' }}>
            <span>{job.pipeline_type}</span>
            <span>{job.duration > 0 ? `${job.duration}s` : ''}</span>
          </div>
          {(job.status === 'queued' || job.status === 'running') && (
            <button className="data-panel-btn-sm secondary" style={{ marginTop: 4 }} onClick={() => cancelTask(job.job_id)}>取消</button>
          )}
          {job.error_message && <div style={{ fontSize: 11, color: '#ef4444', marginTop: 4 }}>{job.error_message}</div>}
        </div>
      ))}
    </div>
  );
}

/* ============================================================
   Templates View (v12.0.4)
   ============================================================ */

function TemplatesView() {
  const [templates, setTemplates] = useState<any[]>([]);
  const [category, setCategory] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTemplates();
  }, [category]);

  const fetchTemplates = async () => {
    try {
      const params = category ? `?category=${category}` : '';
      const resp = await fetch(`/api/templates${params}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setTemplates(data.templates || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  };

  const cloneTemplate = async (id: number, name: string) => {
    try {
      const resp = await fetch(`/api/templates/${id}/clone`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (resp.ok) alert(`模板 "${name}" 已克隆为工作流`);
    } catch { alert('克隆失败'); }
  };

  if (loading) return <div className="data-panel-empty">加载中...</div>;

  return (
    <div className="data-panel-list">
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        {['', 'general', 'governance', 'optimization', 'analysis', '城市规划', '环境监测', '国土资源'].map(cat => {
          const label: Record<string, string> = {
            '': '全部', general: '通用', governance: '治理', optimization: '优化',
            analysis: '分析', '城市规划': '城市规划', '环境监测': '环境监测', '国土资源': '国土资源',
          };
          return (
            <button key={cat} className={`data-panel-btn-sm ${category === cat ? '' : 'secondary'}`}
              onClick={() => setCategory(cat)}>{label[cat] || cat}</button>
          );
        })}
      </div>
      {templates.length === 0 && <div className="data-panel-empty">暂无模板</div>}
      {templates.map((t: any) => (
        <div key={t.id} className="data-panel-card" style={{ marginBottom: 6 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{t.template_name}</div>
          <div style={{ fontSize: 12, color: '#aaa', margin: '2px 0' }}>{t.description}</div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
            <span className="data-panel-badge">{t.category}</span>
            <span style={{ fontSize: 11, color: '#888' }}>克隆: {t.clone_count}</span>
            <span style={{ fontSize: 11, color: '#f59e0b' }}>{'★'.repeat(Math.round(t.rating_avg || 0))}</span>
          </div>
          <button className="data-panel-btn-sm" style={{ marginTop: 6 }} onClick={() => cloneTemplate(t.id, t.template_name)}>克隆为工作流</button>
        </div>
      ))}
    </div>
  );
}

/* ============================================================
   Analytics View (v12.0.4)
   ============================================================ */

function AnalyticsView() {
  const [latency, setLatency] = useState<any>(null);
  const [toolSuccess, setToolSuccess] = useState<any[]>([]);
  const [throughput, setThroughput] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch('/api/analytics/latency', { credentials: 'include' }).then(r => r.ok ? r.json() : null),
      fetch('/api/analytics/tool-success', { credentials: 'include' }).then(r => r.ok ? r.json() : null),
      fetch('/api/analytics/throughput', { credentials: 'include' }).then(r => r.ok ? r.json() : null),
    ]).then(([lat, tools, tp]) => {
      setLatency(lat);
      setToolSuccess(tools?.tools || []);
      setThroughput(tp?.daily || []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="data-panel-empty">加载中...</div>;

  return (
    <div className="data-panel-list" style={{ fontSize: 12 }}>
      {/* Latency */}
      <div className="data-panel-card" style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>管线延迟 (ms)</div>
        {latency ? (
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {['p50', 'p75', 'p90', 'p99'].map(k => (
              <div key={k} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#0d9488' }}>{latency[k] || 0}</div>
                <div style={{ color: '#888' }}>{k.toUpperCase()}</div>
              </div>
            ))}
          </div>
        ) : <div style={{ color: '#888' }}>无数据</div>}
      </div>

      {/* Tool Success Rate Top 5 */}
      <div className="data-panel-card" style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>工具成功率 Top 5</div>
        {toolSuccess.slice(0, 5).map((t: any, i: number) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ width: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.tool_name}</span>
            <div style={{ flex: 1, height: 14, background: '#333', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ width: `${(t.success_rate || 0) * 100}%`, height: '100%', background: '#22c55e', borderRadius: 4 }}></div>
            </div>
            <span style={{ width: 40, textAlign: 'right' }}>{((t.success_rate || 0) * 100).toFixed(0)}%</span>
          </div>
        ))}
        {toolSuccess.length === 0 && <div style={{ color: '#888' }}>无数据</div>}
      </div>

      {/* Throughput */}
      <div className="data-panel-card">
        <div style={{ fontWeight: 600, marginBottom: 6 }}>每日吞吐量</div>
        {throughput.slice(-7).map((d: any, i: number) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
            <span>{d.date}</span>
            <span style={{ color: '#0d9488' }}>{d.count} 次</span>
          </div>
        ))}
        {throughput.length === 0 && <div style={{ color: '#888' }}>无数据</div>}
      </div>
    </div>
  );
}

/* ============================================================
   Virtual Sources View (v13.0)
   ============================================================ */

interface VSource {
  id: number;
  source_name: string;
  source_type: string;
  endpoint_url: string;
  owner_username: string;
  is_shared: boolean;
  enabled: boolean;
  health_status: string;
  default_crs: string;
  refresh_policy: string;
  created_at: string | null;
}

const EMPTY_VS_FORM = {
  source_name: '', source_type: 'wfs', endpoint_url: '',
  auth_config: {} as Record<string, string>,
  query_config: '{}', default_crs: 'EPSG:4326',
  refresh_policy: 'on_demand', is_shared: false,
};

function VirtualSourcesView() {
  const [sources, setSources] = useState<VSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState({ ...EMPTY_VS_FORM });
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);

  const fetchSources = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/virtual-sources', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setSources(d.sources || []); }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchSources(); }, []);

  const handleNew = () => {
    setForm({ ...EMPTY_VS_FORM });
    setEditId(null);
    setFormError('');
    setShowForm(true);
  };

  const handleEdit = (s: VSource) => {
    setForm({
      source_name: s.source_name,
      source_type: s.source_type,
      endpoint_url: s.endpoint_url,
      auth_config: {},
      query_config: '{}',
      default_crs: s.default_crs,
      refresh_policy: s.refresh_policy,
      is_shared: s.is_shared,
    });
    setEditId(s.id);
    setFormError('');
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.source_name || !form.endpoint_url) {
      setFormError('名称和端点URL不能为空');
      return;
    }
    let qcfg = {};
    try { qcfg = JSON.parse(form.query_config); } catch { setFormError('查询配置JSON格式错误'); return; }
    setSaving(true);
    setFormError('');
    try {
      const body = {
        source_name: form.source_name,
        source_type: form.source_type,
        endpoint_url: form.endpoint_url,
        auth_config: form.auth_config.type ? form.auth_config : undefined,
        query_config: qcfg,
        default_crs: form.default_crs,
        refresh_policy: form.refresh_policy,
        is_shared: form.is_shared,
      };
      const url = editId ? `/api/virtual-sources/${editId}` : '/api/virtual-sources';
      const method = editId ? 'PUT' : 'POST';
      const r = await fetch(url, {
        method, credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (r.ok) { setShowForm(false); fetchSources(); }
      else { const d = await r.json(); setFormError(d.error || '保存失败'); }
    } catch (e: any) { setFormError(e.message); }
    finally { setSaving(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此数据源？')) return;
    await fetch(`/api/virtual-sources/${id}`, { method: 'DELETE', credentials: 'include' });
    fetchSources();
  };

  const handleTest = async (id: number) => {
    setTesting(id);
    try {
      const r = await fetch(`/api/virtual-sources/${id}/test`, { method: 'POST', credentials: 'include' });
      if (r.ok) { fetchSources(); }
    } catch { /* ignore */ }
    finally { setTesting(null); }
  };

  const healthColor = (h: string) => {
    if (h === 'healthy') return '#10b981';
    if (h === 'error') return '#ef4444';
    if (h === 'timeout') return '#f59e0b';
    return '#888';
  };

  const typeLabel = (t: string) => {
    const map: Record<string, string> = { wfs: 'WFS', stac: 'STAC', ogc_api: 'OGC API', custom_api: 'API' };
    return map[t] || t;
  };

  if (loading) return <div style={{ padding: 16, color: '#888' }}>加载中...</div>;

  return (
    <div style={{ padding: '8px 12px', fontSize: 13 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 600 }}>虚拟数据源 ({sources.length})</span>
        <button className="btn-primary btn-sm" onClick={handleNew}
          style={{ fontSize: 12, padding: '2px 10px' }}>+ 新增</button>
      </div>

      {showForm && (
        <div style={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 6, padding: 12, marginBottom: 10 }}>
          <div style={{ display: 'grid', gap: 8 }}>
            <input placeholder="数据源名称" value={form.source_name}
              onChange={e => setForm({ ...form, source_name: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            <div style={{ display: 'flex', gap: 8 }}>
              <select value={form.source_type}
                onChange={e => setForm({ ...form, source_type: e.target.value })}
                style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                <option value="wfs">WFS</option>
                <option value="stac">STAC</option>
                <option value="ogc_api">OGC API</option>
                <option value="custom_api">自定义 API</option>
              </select>
              <select value={form.refresh_policy}
                onChange={e => setForm({ ...form, refresh_policy: e.target.value })}
                style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                <option value="on_demand">按需</option>
                <option value="interval:5m">5分钟</option>
                <option value="interval:30m">30分钟</option>
              </select>
            </div>
            <input placeholder="端点 URL" value={form.endpoint_url}
              onChange={e => setForm({ ...form, endpoint_url: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            <input placeholder="默认CRS (EPSG:4326)" value={form.default_crs}
              onChange={e => setForm({ ...form, default_crs: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
            <textarea placeholder='查询配置 JSON (如 {"feature_type":"topp:states"})' value={form.query_config}
              onChange={e => setForm({ ...form, query_config: e.target.value })} rows={2}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontFamily: 'monospace', fontSize: 12 }} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#aaa' }}>
              <input type="checkbox" checked={form.is_shared}
                onChange={e => setForm({ ...form, is_shared: e.target.checked })} />
              共享给其他用户
            </label>
          </div>
          {formError && <div style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{formError}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn-primary btn-sm" onClick={handleSave} disabled={saving}
              style={{ fontSize: 12 }}>{saving ? '保存中...' : (editId ? '更新' : '创建')}</button>
            <button className="btn-secondary btn-sm" onClick={() => setShowForm(false)}
              style={{ fontSize: 12 }}>取消</button>
          </div>
        </div>
      )}

      {sources.length === 0 && !showForm && (
        <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>
          暂无虚拟数据源，点击"+ 新增"注册远程 WFS/STAC/API 服务
        </div>
      )}

      {sources.map(s => (
        <div key={s.id} style={{
          background: '#111827', border: '1px solid #1f2937', borderRadius: 6,
          padding: '8px 12px', marginBottom: 6, cursor: 'pointer',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#e0e0e0' }}>{s.source_name}</span>
              <span style={{
                marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 3,
                background: '#1e3a5f', color: '#7dd3fc',
              }}>{typeLabel(s.source_type)}</span>
              {s.is_shared && <span style={{ marginLeft: 6, fontSize: 11, color: '#888' }}>共享</span>}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                background: healthColor(s.health_status),
              }} title={s.health_status} />
              <button onClick={(e) => { e.stopPropagation(); handleTest(s.id); }}
                style={{ fontSize: 11, color: '#7dd3fc', background: 'none', border: 'none', cursor: 'pointer' }}
                disabled={testing === s.id}>{testing === s.id ? '测试中...' : '测试'}</button>
              <button onClick={(e) => { e.stopPropagation(); handleEdit(s); }}
                style={{ fontSize: 11, color: '#aaa', background: 'none', border: 'none', cursor: 'pointer' }}>编辑</button>
              <button onClick={(e) => { e.stopPropagation(); handleDelete(s.id); }}
                style={{ fontSize: 11, color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer' }}>删除</button>
            </div>
          </div>
          <div style={{ fontSize: 11, color: '#888', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {s.endpoint_url}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ============================================================
   Marketplace View (v14.0)
   ============================================================ */

interface MarketItem {
  id: number;
  name: string;
  type: 'skill' | 'tool' | 'template' | 'bundle';
  description: string;
  owner: string;
  rating: number;
  rating_count: number;
  clone_count: number;
  template_type?: string;
  category?: string;
}

function MarketplaceView() {
  const [items, setItems] = useState<MarketItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState<'rating' | 'usage' | 'recent'>('rating');
  const [filter, setFilter] = useState<string>('all');
  const [search, setSearch] = useState('');

  const fetchItems = async (sortBy: string) => {
    setLoading(true);
    try {
      const r = await fetch(`/api/marketplace?sort=${sortBy}`, { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setItems(d.items || []); }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchItems(sort); }, [sort]);

  const handleClone = async (item: MarketItem) => {
    const url = item.type === 'skill'
      ? `/api/skills/${item.id}/clone`
      : item.type === 'tool'
        ? `/api/user-tools/${item.id}/clone`
        : null;
    if (!url) return;
    const r = await fetch(url, { method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (r.ok) { fetchItems(sort); }
  };

  const handleRate = async (item: MarketItem, score: number) => {
    const url = item.type === 'skill'
      ? `/api/skills/${item.id}/rate`
      : item.type === 'tool'
        ? `/api/user-tools/${item.id}/rate`
        : item.type === 'template'
          ? `/api/templates/${item.id}/rate`
          : null;
    if (!url) return;
    await fetch(url, { method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ score }) });
    fetchItems(sort);
  };

  const typeLabel: Record<string, string> = { skill: '技能', tool: '工具', template: '模板', bundle: '套件' };
  const typeColor: Record<string, string> = { skill: '#7c3aed', tool: '#0d9488', template: '#d97706', bundle: '#2563eb' };

  const filtered = items.filter(i => {
    if (filter !== 'all' && i.type !== filter) return false;
    if (search && !i.name.toLowerCase().includes(search.toLowerCase())
        && !i.description.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  if (loading) return <div style={{ padding: 16, color: '#888' }}>加载中...</div>;

  return (
    <div style={{ padding: '8px 12px', fontSize: 13 }}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <input placeholder="搜索..." value={search} onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 100, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 8px', color: '#e0e0e0', fontSize: 12 }} />
        <select value={filter} onChange={e => setFilter(e.target.value)}
          style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 6px', color: '#e0e0e0', fontSize: 12 }}>
          <option value="all">全部</option>
          <option value="skill">技能</option>
          <option value="tool">工具</option>
          <option value="template">模板</option>
          <option value="bundle">套件</option>
        </select>
        <select value={sort} onChange={e => setSort(e.target.value as any)}
          style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '3px 6px', color: '#e0e0e0', fontSize: 12 }}>
          <option value="rating">评分</option>
          <option value="usage">使用量</option>
          <option value="recent">最新</option>
        </select>
      </div>

      <div style={{ color: '#888', fontSize: 11, marginBottom: 6 }}>{filtered.length} 个共享资源</div>

      {filtered.length === 0 && (
        <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>暂无共享资源</div>
      )}

      {filtered.map(item => (
        <div key={`${item.type}-${item.id}`} style={{
          background: '#111827', border: '1px solid #1f2937', borderRadius: 6,
          padding: '8px 12px', marginBottom: 6,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#e0e0e0' }}>{item.name}</span>
              <span style={{
                marginLeft: 8, fontSize: 10, padding: '1px 6px', borderRadius: 3,
                background: typeColor[item.type] + '22', color: typeColor[item.type],
              }}>{typeLabel[item.type]}</span>
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              {[1,2,3,4,5].map(s => (
                <span key={s} onClick={() => handleRate(item, s)}
                  style={{ cursor: 'pointer', color: s <= Math.round(item.rating) ? '#f59e0b' : '#444', fontSize: 14 }}>
                  ★
                </span>
              ))}
              <span style={{ fontSize: 11, color: '#888' }}>({item.rating_count})</span>
              {(item.type === 'skill' || item.type === 'tool') && (
                <button onClick={() => handleClone(item)}
                  style={{ fontSize: 11, color: '#7dd3fc', background: 'none', border: '1px solid #334155', borderRadius: 4, padding: '1px 8px', cursor: 'pointer' }}>
                  克隆
                </button>
              )}
            </div>
          </div>
          <div style={{ fontSize: 11, color: '#aaa', marginTop: 4 }}>
            {item.description || '无描述'}
          </div>
          <div style={{ fontSize: 10, color: '#666', marginTop: 4, display: 'flex', gap: 12 }}>
            <span>by {item.owner}</span>
            <span>克隆 {item.clone_count}</span>
            {item.category && <span>{item.category}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
