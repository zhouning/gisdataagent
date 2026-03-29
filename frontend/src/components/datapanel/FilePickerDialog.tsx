import { useState, useEffect, useRef } from 'react';

interface FileInfo {
  name: string;
  size: number;
  modified: number;
  type: string;
}

interface FilePickerDialogProps {
  open: boolean;
  onSelect: (filePath: string) => void;
  onCancel: () => void;
}

export default function FilePickerDialog({ open, onSelect, onCancel }: FilePickerDialogProps) {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchFiles = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/user/files', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setFiles(data || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    if (open) {
      fetchFiles();
      setSelected(null);
    }
  }, [open]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const resp = await fetch('/api/user/files', {
        method: 'POST',
        credentials: 'include',
        body: formData,
      });
      if (resp.ok) {
        const data = await resp.json();
        await fetchFiles();
        setSelected(data.path);
      } else {
        alert('上传失败');
      }
    } catch {
      alert('上传失败');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleConfirm = () => {
    if (selected) {
      onSelect(selected);
    }
  };

  if (!open) return null;

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 9999,
    }}>
      <div style={{
        background: '#fff', borderRadius: 8, width: 600, maxHeight: '80vh',
        display: 'flex', flexDirection: 'column', boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>选择数据文件</h3>
          <button onClick={onCancel} style={{ border: 'none', background: 'none', fontSize: 20, cursor: 'pointer', color: '#9ca3af' }}>×</button>
        </div>

        <div style={{ padding: 16, borderBottom: '1px solid #e5e7eb' }}>
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleUpload}
            style={{ display: 'none' }}
            accept=".shp,.zip,.geojson,.gpkg,.kml,.kmz,.tif,.tiff"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            style={{
              padding: '8px 16px', borderRadius: 4, border: '1px solid #d1d5db',
              background: '#fff', cursor: uploading ? 'not-allowed' : 'pointer', fontSize: 13,
            }}
          >
            {uploading ? '上传中...' : '📁 上传新文件'}
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {loading ? (
            <div style={{ textAlign: 'center', color: '#9ca3af', padding: 20 }}>加载中...</div>
          ) : files.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#9ca3af', padding: 20 }}>暂无文件，请上传</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {files.map((f, i) => (
                <div
                  key={i}
                  onClick={() => setSelected(f.name)}
                  style={{
                    padding: 12, borderRadius: 6, border: `2px solid ${selected === f.name ? '#1a73e8' : '#e5e7eb'}`,
                    cursor: 'pointer', background: selected === f.name ? '#eff6ff' : '#fff',
                    transition: 'all 0.15s',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 14, fontWeight: 500, flex: 1 }}>{f.name}</span>
                    <span style={{
                      padding: '2px 6px', borderRadius: 3, background: '#f3f4f6',
                      fontSize: 10, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase',
                    }}>{f.type}</span>
                  </div>
                  <div style={{ fontSize: 11, color: '#9ca3af' }}>
                    {(f.size / 1024 / 1024).toFixed(2)} MB · {new Date(f.modified * 1000).toLocaleString('zh-CN')}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ padding: 16, borderTop: '1px solid #e5e7eb', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{
            padding: '8px 16px', borderRadius: 4, border: '1px solid #d1d5db',
            background: '#fff', cursor: 'pointer', fontSize: 13,
          }}>取消</button>
          <button
            onClick={handleConfirm}
            disabled={!selected}
            style={{
              padding: '8px 16px', borderRadius: 4, border: 'none',
              background: selected ? '#1a73e8' : '#d1d5db', color: '#fff',
              cursor: selected ? 'pointer' : 'not-allowed', fontSize: 13, fontWeight: 500,
            }}
          >确定</button>
        </div>
      </div>
    </div>
  );
}
