/**
 * DataUploadTab — 文件上传 + 数据集信息展示
 *
 * 上传后：
 * 1. 调用 /api/v1/upload 上传文件
 * 2. 展示数据基本信息（记录数、坐标系、字段数）
 * 3. 调用 /api/v1/datasets/{id}/geojson 获取 GeoJSON
 * 4. 通过 MapContext 触发地图渲染
 * 5. 自动在对话面板触发 AI 分析
 */

import { useState, useCallback } from 'react';
import {
  Upload, FileText, MapPin, Table2, AlertCircle, Loader2, Check,
  Download, Trash2, ChevronDown, ChevronRight,
} from 'lucide-react';

export interface DatasetInfo {
  dataset_id: string;
  filename: string;
  record_count?: number;
  crs?: string;
  geometry_type?: string[];
  column_count?: number;
  columns?: string[];
  bounds?: number[];
  error?: string;
}

interface DataUploadTabProps {
  onDatasetLoaded?: (ds: DatasetInfo, geojson: any) => void;
  onAnalyzeRequest?: (ds: DatasetInfo) => void;
}

export default function DataUploadTab({ onDatasetLoaded, onAnalyzeRequest }: DataUploadTabProps) {
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedDs, setExpandedDs] = useState<string | null>(null);

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    setError(null);

    try {
      // Upload each file
      for (const file of Array.from(files)) {
        const formData = new FormData();
        formData.append('file', file);

        const uploadRes = await fetch('/api/v1/upload', {
          method: 'POST',
          body: formData,
        });

        if (!uploadRes.ok) {
          const err = await uploadRes.json();
          throw new Error(err.error || `上传失败: ${uploadRes.status}`);
        }

        const dsInfo: DatasetInfo = await uploadRes.json();
        setDatasets(prev => [...prev, dsInfo]);
        setExpandedDs(dsInfo.dataset_id);

        // Fetch GeoJSON for map rendering
        try {
          const geojsonRes = await fetch(`/api/v1/datasets/${dsInfo.dataset_id}/geojson`);
          if (geojsonRes.ok) {
            const geojson = await geojsonRes.json();
            onDatasetLoaded?.(dsInfo, geojson);
          }
        } catch (geoErr) {
          console.warn('GeoJSON 加载失败:', geoErr);
        }
      }
    } catch (err: any) {
      setError(err.message || '上传失败');
    } finally {
      setUploading(false);
      // Reset input
      e.target.value = '';
    }
  }, [onDatasetLoaded]);

  const handleAnalyze = useCallback((ds: DatasetInfo) => {
    onAnalyzeRequest?.(ds);
  }, [onAnalyzeRequest]);

  const handleRemove = useCallback((dsId: string) => {
    setDatasets(prev => prev.filter(d => d.dataset_id !== dsId));
    if (expandedDs === dsId) setExpandedDs(null);
  }, [expandedDs]);

  return (
    <div className="upload-tab">
      {/* Upload area */}
      <div className="upload-area">
        <label className="upload-dropzone">
          <input
            type="file"
            accept=".shp,.shx,.dbf,.prj,.cpg,.geojson,.json,.gpkg,.zip"
            multiple
            onChange={handleUpload}
            disabled={uploading}
            style={{ display: 'none' }}
          />
          {uploading ? (
            <>
              <Loader2 size={32} className="spin" />
              <span>上传中...</span>
            </>
          ) : (
            <>
              <Upload size={32} strokeWidth={1.5} />
              <span className="upload-dropzone-title">点击或拖拽上传数据文件</span>
              <span className="upload-dropzone-hint">
                支持 Shapefile (.shp+附属文件) / GeoJSON / GPKG / ZIP
              </span>
            </>
          )}
        </label>
      </div>

      {/* Error message */}
      {error && (
        <div className="upload-error">
          <AlertCircle size={14} />
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Dataset list */}
      {datasets.length > 0 && (
        <div className="dataset-list">
          <div className="dataset-list-header">
            <FileText size={14} />
            <span>已上传数据集 ({datasets.length})</span>
          </div>

          {datasets.map(ds => (
            <div key={ds.dataset_id} className="dataset-card">
              {/* Card header */}
              <div
                className="dataset-card-header"
                onClick={() => setExpandedDs(expandedDs === ds.dataset_id ? null : ds.dataset_id)}
              >
                {expandedDs === ds.dataset_id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <FileText size={14} />
                <span className="dataset-filename">{ds.filename}</span>
                <div className="dataset-badges">
                  {ds.record_count != null && (
                    <span className="badge">{ds.record_count.toLocaleString()} 条</span>
                  )}
                  {ds.geometry_type && ds.geometry_type.length > 0 && (
                    <span className="badge">{ds.geometry_type.join('/')}</span>
                  )}
                </div>
              </div>

              {/* Expanded details */}
              {expandedDs === ds.dataset_id && (
                <div className="dataset-card-body">
                  <div className="dataset-info-grid">
                    <div className="info-item">
                      <MapPin size={12} />
                      <span className="info-label">坐标系</span>
                      <span className="info-value">{ds.crs || '未知'}</span>
                    </div>
                    <div className="info-item">
                      <Table2 size={12} />
                      <span className="info-label">字段数</span>
                      <span className="info-value">{ds.column_count ?? ds.columns?.length ?? '-'}</span>
                    </div>
                  </div>

                  {/* Column list (collapsed) */}
                  {ds.columns && ds.columns.length > 0 && (
                    <div className="dataset-columns">
                      <span className="columns-label">字段：</span>
                      <span className="columns-list">
                        {ds.columns.slice(0, 12).join(', ')}
                        {ds.columns.length > 12 ? ` ... +${ds.columns.length - 12}` : ''}
                      </span>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="dataset-actions">
                    <button className="btn-primary btn-sm" onClick={() => handleAnalyze(ds)}>
                      <Check size={13} />
                      开始分析
                    </button>
                    <button className="btn-ghost btn-sm" onClick={() => handleRemove(ds.dataset_id)}>
                      <Trash2 size={13} />
                      移除
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {datasets.length === 0 && !uploading && (
        <div className="upload-empty">
          <p>上传数据文件后，系统将自动：</p>
          <ul>
            <li>识别字段含义（语义等价库匹配）</li>
            <li>在地图上渲染空间范围</li>
            <li>推荐对应的数据标准</li>
            <li>生成差距分析报告</li>
          </ul>
        </div>
      )}
    </div>
  );
}
