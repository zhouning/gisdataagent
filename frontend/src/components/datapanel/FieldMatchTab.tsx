/**
 * FieldMatchTab — 字段匹配结果展示
 *
 * 调用 /api/v1/datasets/{id}/match 获取标准对照结果，
 * 展示字段匹配详情（精确/语义/未匹配着色）。
 */

import { useState, useCallback } from 'react';
import { Table2, Check, ArrowRight, X, Loader2, Search } from 'lucide-react';

interface FieldMatch {
  源字段: string;
  目标字段: string | null;
  目标字段名称: string | null;
  匹配类型: string;
  语义组: string | null;
}

interface MatchResult {
  源数据: string;
  目标标准表: string;
  目标标准表中文名: string;
  源字段数: number;
  标准字段数: number;
  匹配率: number;
  字段匹配详情: FieldMatch[];
}

interface FieldMatchTabProps {
  datasetId?: string | null;
  onMatchComplete?: (result: MatchResult) => void;
  onHighlightFeatures?: (fieldName: string, matchType: string) => void;
}

const MATCH_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  exact: { bg: 'rgba(34,197,94,.12)', color: '#22c55e', label: '精确' },
  semantic: { bg: 'rgba(59,130,246,.12)', color: '#3b82f6', label: '语义' },
  unmatched: { bg: 'rgba(239,68,68,.08)', color: '#ef4444', label: '未匹配' },
};

export default function FieldMatchTab({ datasetId, onMatchComplete, onHighlightFeatures }: FieldMatchTabProps) {
  const [result, setResult] = useState<MatchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>('all');

  const runMatch = useCallback(async () => {
    if (!datasetId) return;
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`/api/v1/datasets/${datasetId}/match`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ standard_table: 'DLTB' }),
      });
      if (!res.ok) throw new Error(`分析失败: ${res.status}`);
      const data: MatchResult = await res.json();
      setResult(data);
      onMatchComplete?.(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [datasetId, onMatchComplete]);

  const filteredFields = result?.字段匹配详情?.filter(f => {
    if (filter === 'all') return true;
    return f.匹配类型 === filter;
  }) ?? [];

  if (!datasetId) {
    return (
      <div className="tab-content-placeholder">
        <Table2 size={40} strokeWidth={1} />
        <h3>字段匹配</h3>
        <p>请先在"数据"Tab 上传数据集</p>
      </div>
    );
  }

  return (
    <div className="match-tab">
      {/* Header with run button */}
      <div className="match-header">
        <button className="btn-primary btn-sm" onClick={runMatch} disabled={loading}>
          {loading ? <Loader2 size={13} className="spin" /> : <Search size={13} />}
          {loading ? '分析中...' : '执行标准对照'}
        </button>
        <span className="match-hint">对照标准：三调地类图斑 (DLTB)</span>
      </div>

      {error && <div className="upload-error"><X size={14} /><span>{error}</span></div>}

      {result && (
        <>
          {/* Summary bar */}
          <div className="match-summary">
            <div className="match-stat">
              <span className="match-stat-value">{Math.round(result.匹配率 * 100)}%</span>
              <span className="match-stat-label">匹配率</span>
            </div>
            <div className="match-stat">
              <span className="match-stat-value">{result.源字段数}</span>
              <span className="match-stat-label">源字段</span>
            </div>
            <div className="match-stat">
              <span className="match-stat-value">{result.标准字段数}</span>
              <span className="match-stat-label">标准字段</span>
            </div>
          </div>

          {/* Filter */}
          <div className="match-filter">
            {['all', 'exact', 'semantic', 'unmatched'].map(f => (
              <button
                key={f}
                className={`filter-btn ${filter === f ? 'active' : ''}`}
                onClick={() => setFilter(f)}
              >
                {f === 'all' ? '全部' : MATCH_STYLES[f]?.label}
                {f !== 'all' && (
                  <span className="filter-count">
                    {result.字段匹配详情.filter(m => m.匹配类型 === f).length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Table */}
          <div className="match-table-wrap">
            <table className="match-table">
              <thead>
                <tr>
                  <th>源字段</th>
                  <th></th>
                  <th>标准字段</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {filteredFields.map((f, i) => {
                  const style = MATCH_STYLES[f.匹配类型] || MATCH_STYLES.unmatched;
                  return (
                    <tr
                      key={i}
                      className="match-row"
                      onClick={() => onHighlightFeatures?.(f.源字段, f.匹配类型)}
                    >
                      <td className="field-name">{f.源字段}</td>
                      <td className="arrow-cell">
                        {f.目标字段 ? <ArrowRight size={12} /> : <X size={12} style={{ color: '#ef4444' }} />}
                      </td>
                      <td className="field-name">
                        {f.目标字段 ? (
                          <span>{f.目标字段}<span className="field-label"> ({f.目标字段名称})</span></span>
                        ) : (
                          <span className="no-match">—</span>
                        )}
                      </td>
                      <td>
                        <span className="match-badge" style={{ background: style.bg, color: style.color }}>
                          {style.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
