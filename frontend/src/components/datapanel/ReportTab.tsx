/**
 * ReportTab — 治理成果报告预览与下载
 *
 * 调用 /api/v1/datasets/{id}/report 生成并下载 Word 报告。
 */

import { useState, useCallback } from 'react';
import { FileText, Download, Loader2, Eye, CheckCircle } from 'lucide-react';

interface ReportTabProps {
  datasetId?: string | null;
  matchRate?: number;
  gapCount?: { high: number; medium: number; low: number };
}

export default function ReportTab({ datasetId, matchRate, gapCount }: ReportTabProps) {
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = useCallback(async () => {
    if (!datasetId) return;
    setGenerating(true);
    setError(null);

    try {
      const res = await fetch(`/api/v1/datasets/${datasetId}/report`);
      if (!res.ok) throw new Error(`报告生成失败: ${res.status}`);

      // Download the file
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const disposition = res.headers.get('Content-Disposition') || '';
      const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
      const filename = filenameMatch?.[1] || '治理分析报告.docx';

      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      setGenerated(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  }, [datasetId]);

  if (!datasetId) {
    return (
      <div className="tab-content-placeholder">
        <FileText size={40} strokeWidth={1} />
        <h3>治理报告</h3>
        <p>完成标准对照分析后可生成报告</p>
      </div>
    );
  }

  return (
    <div className="report-tab">
      {/* Report info */}
      <div className="report-info">
        <FileText size={24} strokeWidth={1.5} />
        <div className="report-info-text">
          <h3>数据治理分析报告</h3>
          <p>包含：概述 → 字段匹配 → 差距分析 → 调整建议 → 完整匹配表</p>
        </div>
      </div>

      {/* Stats preview */}
      {(matchRate != null || gapCount) && (
        <div className="report-stats">
          {matchRate != null && (
            <div className="report-stat-item">
              <span className="report-stat-value">{Math.round(matchRate * 100)}%</span>
              <span className="report-stat-label">匹配率</span>
            </div>
          )}
          {gapCount && (
            <>
              <div className="report-stat-item">
                <span className="report-stat-value" style={{ color: '#ef4444' }}>{gapCount.high}</span>
                <span className="report-stat-label">高优先级</span>
              </div>
              <div className="report-stat-item">
                <span className="report-stat-value" style={{ color: '#eab308' }}>{gapCount.medium}</span>
                <span className="report-stat-label">中优先级</span>
              </div>
            </>
          )}
        </div>
      )}

      {/* Report contents outline */}
      <div className="report-outline">
        <div className="report-outline-title">报告目录</div>
        <ol className="report-outline-list">
          <li>概述（源数据、目标标准、分析时间）</li>
          <li>字段匹配分析（精确/语义/未匹配）</li>
          <li>差距分析
            <ul>
              <li>高优先级差距（必须处理）</li>
              <li>中优先级差距（建议处理）</li>
              <li>低优先级差距（可选处理）</li>
              <li>多余字段（评估处理）</li>
            </ul>
          </li>
          <li>调整建议总结</li>
          <li>附录：完整字段匹配表</li>
        </ol>
      </div>

      {/* Actions */}
      <div className="report-actions">
        <button className="btn-primary" onClick={handleGenerate} disabled={generating}>
          {generating ? (
            <><Loader2 size={14} className="spin" /> 生成中...</>
          ) : generated ? (
            <><CheckCircle size={14} /> 重新生成并下载 Word</>
          ) : (
            <><Download size={14} /> 生成并下载 Word 报告</>
          )}
        </button>
      </div>

      {error && <div className="upload-error"><span>{error}</span></div>}

      {generated && (
        <div className="report-success">
          <CheckCircle size={14} />
          <span>报告已生成并下载。可在 Word 中打开查看完整内容。</span>
        </div>
      )}
    </div>
  );
}
