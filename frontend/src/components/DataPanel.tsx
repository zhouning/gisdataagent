import { useState, useEffect } from 'react';
import Papa from 'papaparse';

interface DataPanelProps {
  dataFile: string | null;
}

type TabKey = 'files' | 'table';

interface FileInfo {
  name: string;
  size: number;
  modified: string;
  type: string;
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
      </div>

      <div className="data-panel-content">
        {activeTab === 'files' && <FileList files={files} onFileClick={handleFileClick} />}
        {activeTab === 'table' && <DataTable columns={tableColumns} data={tableData} loading={loading} />}
      </div>
    </div>
  );
}

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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
