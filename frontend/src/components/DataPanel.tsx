import { useState, useEffect } from 'react';
import Papa from 'papaparse';

interface DataPanelProps {
  dataFile: string | null;
}

type TabKey = 'files' | 'table' | 'catalog' | 'history';

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

export default function DataPanel({ dataFile }: DataPanelProps) {
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
      </div>

      <div className="data-panel-content">
        {activeTab === 'files' && <FileList files={files} onFileClick={handleFileClick} />}
        {activeTab === 'table' && <DataTable columns={tableColumns} data={tableData} loading={loading} />}
        {activeTab === 'catalog' && <CatalogView />}
        {activeTab === 'history' && <HistoryView />}
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
