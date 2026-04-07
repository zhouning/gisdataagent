/**
 * AdjustmentTab — 模型调整建议（勾选确认）
 *
 * 调用 /api/v1/datasets/{id}/advise 获取建议，分三级展示。
 */

import { useState, useCallback } from 'react';
import { Wrench, Check, Loader2, ChevronDown, ChevronRight } from 'lucide-react';

interface AdviceItem {
  field: string;
  name: string;
  action: string;
}

interface AdviceResult {
  source: string;
  target_table: string;
  match_rate: number;
  must_do: AdviceItem[];
  should_do: AdviceItem[];
  optional: AdviceItem[];
}

interface AdjustmentTabProps {
  datasetId?: string | null;
  onConfirm?: (selected: AdviceItem[]) => void;
}

export default function AdjustmentTab({ datasetId, onConfirm }: AdjustmentTabProps) {
  const [advice, setAdvice] = useState<AdviceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showOptional, setShowOptional] = useState(false);

  const fetchAdvice = useCallback(async () => {
    if (!datasetId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/datasets/${datasetId}/advise`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ standard_table: 'DLTB' }),
      });
      if (!res.ok) throw new Error(`获取建议失败: ${res.status}`);
      const data: AdviceResult = await res.json();
      setAdvice(data);
      // 默认选中 must_do 和 should_do
      const defaults = new Set([
        ...data.must_do.map(a => a.field),
        ...data.should_do.map(a => a.field),
      ]);
      setSelected(defaults);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [datasetId]);

  const toggleSelect = (field: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  };

  const handleConfirm = () => {
    if (!advice) return;
    const all = [...advice.must_do, ...advice.should_do, ...advice.optional];
    const selectedItems = all.filter(a => selected.has(a.field));
    onConfirm?.(selectedItems);
  };

  if (!datasetId) {
    return (
      <div className="tab-content-placeholder">
        <Wrench size={40} strokeWidth={1} />
        <h3>调整建议</h3>
        <p>请先上传数据并执行标准对照</p>
      </div>
    );
  }

  return (
    <div className="adjust-tab">
      <div className="match-header">
        <button className="btn-primary btn-sm" onClick={fetchAdvice} disabled={loading}>
          {loading ? <Loader2 size={13} className="spin" /> : <Wrench size={13} />}
          {loading ? '生成中...' : '生成调整建议'}
        </button>
      </div>

      {error && <div className="upload-error"><span>{error}</span></div>}

      {advice && (
        <>
          {/* Must do */}
          {advice.must_do.length > 0 && (
            <div className="advice-group">
              <div className="advice-group-title" style={{ color: '#ef4444' }}>
                必须执行 ({advice.must_do.length})
              </div>
              {advice.must_do.map(a => (
                <label key={a.field} className="advice-item">
                  <input type="checkbox" checked={selected.has(a.field)} onChange={() => toggleSelect(a.field)} />
                  <code>{a.field}</code>
                  <span className="advice-name">{a.name}</span>
                  <span className="advice-action">{a.action}</span>
                </label>
              ))}
            </div>
          )}

          {/* Should do */}
          {advice.should_do.length > 0 && (
            <div className="advice-group">
              <div className="advice-group-title" style={{ color: '#eab308' }}>
                建议执行 ({advice.should_do.length})
              </div>
              {advice.should_do.map(a => (
                <label key={a.field} className="advice-item">
                  <input type="checkbox" checked={selected.has(a.field)} onChange={() => toggleSelect(a.field)} />
                  <code>{a.field}</code>
                  <span className="advice-name">{a.name}</span>
                  <span className="advice-action">{a.action}</span>
                </label>
              ))}
            </div>
          )}

          {/* Optional (collapsible) */}
          {advice.optional.length > 0 && (
            <div className="advice-group">
              <div
                className="advice-group-title advice-group-toggle"
                style={{ color: '#6b7280' }}
                onClick={() => setShowOptional(!showOptional)}
              >
                {showOptional ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                可选/评估 ({advice.optional.length})
              </div>
              {showOptional && advice.optional.map(a => (
                <label key={a.field} className="advice-item">
                  <input type="checkbox" checked={selected.has(a.field)} onChange={() => toggleSelect(a.field)} />
                  <code>{a.field}</code>
                  <span className="advice-name">{a.name}</span>
                </label>
              ))}
            </div>
          )}

          {/* Confirm */}
          <div className="advice-footer">
            <span className="advice-count">已选 {selected.size} 项</span>
            <button className="btn-primary btn-sm" onClick={handleConfirm}>
              <Check size={13} /> 确认并执行
            </button>
          </div>
        </>
      )}
    </div>
  );
}
