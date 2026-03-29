import { useState, useEffect, useRef, useCallback } from 'react';
import { getIconCategory, getFileIcon, formatSize } from './utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface FileEntry {
  name: string;
  path: string;
  type: string; // 'folder' | file extension
  size: number;
  modified: number;
}

interface PreviewInfo {
  name: string;
  path: string;
  size: number;
  type: string;
  crs?: string;
  bounds?: number[];
  feature_count?: number | string;
  geometry_type?: string;
  fields?: { name: string; type: string }[];
  columns?: { name: string; type: string }[];
  sample?: Record<string, any>[];
  bands?: number;
  shape?: number[];
  resolution?: number[];
  dtype?: string;
  nodata?: number | null;
  preview_error?: string;
}

// ---------------------------------------------------------------------------
// FileManager — full file browser with upload, folders, preview, delete
// ---------------------------------------------------------------------------
export function FileManager({ onFileClick }: { onFileClick: (name: string) => void }) {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [currentPath, setCurrentPath] = useState('');
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState('');
  const [preview, setPreview] = useState<PreviewInfo | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [showUrlDialog, setShowUrlDialog] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState('');
  const [downloading, setDownloading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchEntries = useCallback(async (path?: string, showLoading = false) => {
    const targetPath = path !== undefined ? path : currentPath;
    if (showLoading) setLoading(true);
    try {
      const resp = await fetch(`/api/user/files/browse?path=${encodeURIComponent(targetPath)}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setEntries(data.entries || []);
        setCurrentPath(data.path || '');
        setParentPath(data.parent);
      }
    } catch { /* ignore */ }
    finally { if (showLoading) setLoading(false); }
  }, [currentPath]);

  useEffect(() => { fetchEntries('', true); }, []);

  // Auto-refresh every 10s (silent, no loading flicker)
  useEffect(() => {
    const iv = setInterval(() => fetchEntries(), 10000);
    return () => clearInterval(iv);
  }, [fetchEntries]);

  // --- Upload ---
  const handleUpload = async (fileList: FileList | File[]) => {
    if (!fileList || fileList.length === 0) return;
    setUploading(true);
    setUploadProgress(`上传 ${fileList.length} 个文件...`);
    const formData = new FormData();
    if (currentPath) formData.append('subfolder', currentPath);
    for (let i = 0; i < fileList.length; i++) {
      formData.append(`file_${i}`, fileList[i], fileList[i].name);
    }
    try {
      const resp = await fetch('/api/user/files/upload', {
        method: 'POST', credentials: 'include', body: formData,
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setUploadProgress(`已上传 ${data.count} 个文件`);
        fetchEntries();
        setTimeout(() => setUploadProgress(''), 2000);
      } else {
        setUploadProgress(`上传失败: ${data.error || '未知错误'}`);
      }
    } catch (e) {
      setUploadProgress('上传出错');
    }
    finally { setUploading(false); }
  };

  // --- Drag & Drop ---
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setDragOver(true); };
  const handleDragLeave = () => setDragOver(false);
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) handleUpload(e.dataTransfer.files);
  };

  // --- Navigate folder ---
  const handleEntryClick = (entry: FileEntry) => {
    if (entry.type === 'folder') {
      fetchEntries(entry.path, true);
      setPreview(null);
    } else if (entry.type === 'csv') {
      onFileClick(entry.path);
    } else {
      loadPreview(entry.path);
    }
  };

  const navigateUp = () => {
    if (parentPath !== null) {
      fetchEntries(parentPath, true);
      setPreview(null);
    }
  };

  // --- Preview ---
  const loadPreview = async (path: string) => {
    setPreviewLoading(true);
    setPreview(null);
    try {
      const resp = await fetch(`/api/user/files/preview/${encodeURIComponent(path)}`, { credentials: 'include' });
      if (resp.ok) setPreview(await resp.json());
    } catch { /* ignore */ }
    finally { setPreviewLoading(false); }
  };

  // --- Delete ---
  const handleDelete = async (entry: FileEntry) => {
    const label = entry.type === 'folder' ? `文件夹 "${entry.name}" 及其所有内容` : `文件 "${entry.name}"`;
    if (!confirm(`确定删除${label}？`)) return;
    try {
      await fetch('/api/user/files/delete', {
        method: 'DELETE', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: entry.path }),
      });
      fetchEntries();
      if (preview?.path === entry.path) setPreview(null);
    } catch { /* ignore */ }
  };

  // --- Create folder ---
  const handleCreateFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    const path = currentPath ? `${currentPath}/${name}` : name;
    try {
      await fetch('/api/user/files/mkdir', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      setShowNewFolder(false);
      setNewFolderName('');
      fetchEntries();
    } catch { /* ignore */ }
  };

  // --- URL Download ---
  const handleDownloadUrl = async () => {
    if (!downloadUrl.trim()) return;
    setDownloading(true);
    try {
      const resp = await fetch('/api/user/files/download-url', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: downloadUrl, subfolder: currentPath }),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setShowUrlDialog(false);
        setDownloadUrl('');
        fetchEntries();
      } else {
        alert(data.error || '下载失败');
      }
    } catch { alert('下载出错'); }
    finally { setDownloading(false); }
  };

  // --- Breadcrumb ---
  const breadcrumbs = currentPath ? currentPath.split('/') : [];

  return (
    <div
      className={`file-manager ${dragOver ? 'drag-over' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Toolbar */}
      <div className="fm-toolbar">
        <button className="fm-btn fm-btn-primary" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          上传文件
        </button>
        <button className="fm-btn" onClick={() => setShowNewFolder(true)}>新建文件夹</button>
        <button className="fm-btn" onClick={() => setShowUrlDialog(true)}>URL下载</button>
        <input
          ref={fileInputRef} type="file" multiple style={{ display: 'none' }}
          onChange={e => { if (e.target.files) handleUpload(e.target.files); e.target.value = ''; }}
        />
        {uploadProgress && <span className="fm-status">{uploadProgress}</span>}
      </div>

      {/* New folder dialog */}
      {showNewFolder && (
        <div className="fm-inline-dialog">
          <input
            className="fm-input" placeholder="文件夹名称" autoFocus
            value={newFolderName} onChange={e => setNewFolderName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreateFolder()}
          />
          <button className="fm-btn fm-btn-sm" onClick={handleCreateFolder}>创建</button>
          <button className="fm-btn fm-btn-sm" onClick={() => { setShowNewFolder(false); setNewFolderName(''); }}>取消</button>
        </div>
      )}

      {/* URL download dialog */}
      {showUrlDialog && (
        <div className="fm-inline-dialog">
          <input
            className="fm-input fm-input-wide" placeholder="https://example.com/data.geojson" autoFocus
            value={downloadUrl} onChange={e => setDownloadUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleDownloadUrl()}
          />
          <button className="fm-btn fm-btn-sm" onClick={handleDownloadUrl} disabled={downloading}>
            {downloading ? '下载中...' : '下载'}
          </button>
          <button className="fm-btn fm-btn-sm" onClick={() => { setShowUrlDialog(false); setDownloadUrl(''); }}>取消</button>
        </div>
      )}

      {/* Breadcrumb */}
      <div className="fm-breadcrumb">
        <span className="fm-crumb" onClick={() => fetchEntries('', true)}>我的文件</span>
        {breadcrumbs.map((seg, i) => {
          const path = breadcrumbs.slice(0, i + 1).join('/');
          return (
            <span key={path}>
              <span className="fm-crumb-sep">/</span>
              <span className="fm-crumb" onClick={() => fetchEntries(path, true)}>{seg}</span>
            </span>
          );
        })}
      </div>

      {/* Drop zone overlay */}
      {dragOver && (
        <div className="fm-drop-overlay">
          <div className="fm-drop-text">拖放文件到此处上传</div>
        </div>
      )}

      {/* File list */}
      <div className="fm-content">
        <div className="fm-list">
          {loading ? (
            <div className="empty-state">加载中...</div>
          ) : entries.length === 0 && !currentPath ? (
            <div className="empty-state">暂无文件<br />点击"上传文件"或拖放文件到此处</div>
          ) : (
            <>
              {parentPath !== null && (
                <div className="fm-entry fm-entry-up" onClick={navigateUp}>
                  <span className="fm-entry-icon">⬆️</span>
                  <span className="fm-entry-name">..</span>
                </div>
              )}
              {entries.map(entry => (
                <div
                  key={entry.path}
                  className={`fm-entry ${entry.type === 'folder' ? 'fm-entry-folder' : ''} ${preview?.path === entry.path ? 'fm-entry-active' : ''}`}
                  onClick={() => handleEntryClick(entry)}
                >
                  <span className="fm-entry-icon">
                    {entry.type === 'folder' ? '📁' : (
                      <span className={`file-icon-sm ${getIconCategory(entry.type)}`}>
                        {getFileIcon(entry.type)}
                      </span>
                    )}
                  </span>
                  <span className="fm-entry-name" title={entry.name}>{entry.name}</span>
                  <span className="fm-entry-size">{entry.type !== 'folder' ? formatSize(entry.size) : ''}</span>
                  <button
                    className="fm-entry-delete" title="删除"
                    onClick={e => { e.stopPropagation(); handleDelete(entry); }}
                  >&times;</button>
                </div>
              ))}
            </>
          )}
        </div>

        {/* Preview panel */}
        {(preview || previewLoading) && (
          <div className="fm-preview">
            {previewLoading ? <div className="empty-state">加载预览...</div> : preview && (
              <>
                <div className="fm-preview-header">
                  <strong>{preview.name}</strong>
                  <span className="fm-preview-size">{formatSize(preview.size)}</span>
                  <button className="fm-preview-close" onClick={() => setPreview(null)}>&times;</button>
                </div>
                {preview.preview_error && <div className="fm-preview-error">{preview.preview_error}</div>}

                {/* Spatial info */}
                {preview.crs && <div className="fm-preview-row"><span>CRS</span><span>{preview.crs}</span></div>}
                {preview.feature_count !== undefined && <div className="fm-preview-row"><span>要素数</span><span>{preview.feature_count}</span></div>}
                {preview.geometry_type && <div className="fm-preview-row"><span>几何类型</span><span>{preview.geometry_type}</span></div>}
                {preview.bands !== undefined && <div className="fm-preview-row"><span>波段数</span><span>{preview.bands}</span></div>}
                {preview.shape && <div className="fm-preview-row"><span>尺寸</span><span>{preview.shape[1]}×{preview.shape[0]}</span></div>}
                {preview.resolution && <div className="fm-preview-row"><span>分辨率</span><span>{preview.resolution[0].toFixed(4)}°</span></div>}
                {preview.bounds && (
                  <div className="fm-preview-row">
                    <span>范围</span>
                    <span className="fm-preview-bounds">
                      [{preview.bounds.map(b => typeof b === 'number' ? b.toFixed(4) : b).join(', ')}]
                    </span>
                  </div>
                )}

                {/* Fields */}
                {(preview.fields || preview.columns) && (
                  <div className="fm-preview-fields">
                    <div className="fm-preview-subtitle">字段 ({(preview.fields || preview.columns)!.length})</div>
                    <table className="fm-preview-table">
                      <thead><tr><th>名称</th><th>类型</th></tr></thead>
                      <tbody>
                        {(preview.fields || preview.columns)!.map(f => (
                          <tr key={f.name}><td>{f.name}</td><td>{f.type}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Sample rows */}
                {preview.sample && preview.sample.length > 0 && (
                  <div className="fm-preview-fields">
                    <div className="fm-preview-subtitle">示例数据 ({preview.sample.length}行)</div>
                    <div className="fm-preview-sample-scroll">
                      <table className="fm-preview-table">
                        <thead><tr>{Object.keys(preview.sample[0]).map(k => <th key={k}>{k}</th>)}</tr></thead>
                        <tbody>
                          {preview.sample.map((row, i) => (
                            <tr key={i}>{Object.values(row).map((v, j) => <td key={j}>{String(v ?? '')}</td>)}</tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Download button */}
                <div className="fm-preview-actions">
                  <a
                    className="fm-btn fm-btn-primary fm-btn-sm"
                    href={`/api/user/files/${encodeURIComponent(preview.path)}`}
                    target="_blank" rel="noopener noreferrer"
                  >下载</a>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DataTable — keep existing export for backward compat
// ---------------------------------------------------------------------------
export function DataTable({ columns, data, loading }: { columns: string[]; data: any[]; loading: boolean }) {
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

// Keep legacy export name
export { FileManager as FileList };
