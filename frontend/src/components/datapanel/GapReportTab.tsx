/**
 * GapReportTab — 差距分析详情
 *
 * 展示 match 结果中的差距项，按严重程度分组（高/中/低/信息）。
 * 点击差距项可在地图上定位相关图斑。
 */

import { AlertTriangle, AlertCircle, Info, CircleDot } from 'lucide-react';
import type { ReactNode } from 'react';

interface GapItem {
  差距类型: string;
  字段代码: string;
  字段名称: string;
  严重程度: string;
  描述: string;
  建议: string;
}

interface GapReportTabProps {
  gaps?: GapItem[];
  matchRate?: number;
  onLocateFeature?: (fieldCode: string) => void;
}

const SEVERITY_CONFIG: Record<string, { icon: ReactNode; color: string; bg: string; label: string }> = {
  high: { icon: <AlertCircle size={14} />, color: '#ef4444', bg: 'rgba(239,68,68,.08)', label: '高优先级 — 必须处理' },
  medium: { icon: <AlertTriangle size={14} />, color: '#eab308', bg: 'rgba(234,179,8,.08)', label: '中优先级 — 建议处理' },
  low: { icon: <Info size={14} />, color: '#3b82f6', bg: 'rgba(59,130,246,.08)', label: '低优先级 — 可选处理' },
  info: { icon: <CircleDot size={14} />, color: '#6b7280', bg: 'rgba(107,114,128,.06)', label: '信息 — 多余字段' },
};

export default function GapReportTab({ gaps, matchRate, onLocateFeature }: GapReportTabProps) {
  if (!gaps || gaps.length === 0) {
    return (
      <div className="tab-content-placeholder">
        <AlertTriangle size={40} strokeWidth={1} />
        <h3>差距分析</h3>
        <p>请先在"匹配"Tab 执行标准对照分析</p>
      </div>
    );
  }

  // 过滤注释行（field_code 过长的）
  const realGaps = gaps.filter(g => g.字段代码.length < 20);

  // 按严重程度分组
  const grouped: Record<string, GapItem[]> = { high: [], medium: [], low: [], info: [] };
  for (const g of realGaps) {
    const key = g.严重程度 in grouped ? g.严重程度 : 'info';
    grouped[key].push(g);
  }

  return (
    <div className="gap-tab">
      {/* Summary */}
      {matchRate != null && (
        <div className="gap-summary">
          <span>匹配率 <strong>{Math.round(matchRate * 100)}%</strong></span>
          <span className="gap-summary-sep">|</span>
          <span style={{ color: '#ef4444' }}>高 {grouped.high.length}</span>
          <span style={{ color: '#eab308' }}>中 {grouped.medium.length}</span>
          <span style={{ color: '#3b82f6' }}>低 {grouped.low.length}</span>
          <span style={{ color: '#6b7280' }}>多余 {grouped.info.length}</span>
        </div>
      )}

      {/* Gap groups */}
      {(['high', 'medium', 'low', 'info'] as const).map(severity => {
        const items = grouped[severity];
        if (items.length === 0) return null;
        const config = SEVERITY_CONFIG[severity];

        return (
          <div key={severity} className="gap-group" style={{ borderLeftColor: config.color }}>
            <div className="gap-group-header" style={{ color: config.color }}>
              {config.icon}
              <span>{config.label} ({items.length})</span>
            </div>
            {items.map((g, i) => (
              <div
                key={i}
                className="gap-item"
                style={{ background: config.bg }}
                onClick={() => onLocateFeature?.(g.字段代码)}
              >
                <div className="gap-item-header">
                  <code className="gap-field-code">{g.字段代码}</code>
                  <span className="gap-field-name">{g.字段名称}</span>
                </div>
                <div className="gap-item-desc">{g.描述}</div>
                <div className="gap-item-suggest">建议：{g.建议}</div>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
