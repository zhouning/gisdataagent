import { getIconCategory, getFileIcon, formatSize } from './utils';

interface FileInfo {
  name: string;
  size: number;
  modified: string;
  type: string;
}

export function FileList({ files, onFileClick }: { files: FileInfo[]; onFileClick: (f: FileInfo) => void }) {
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
