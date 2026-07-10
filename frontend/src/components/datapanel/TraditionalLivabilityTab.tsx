import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Database,
  Gauge,
  ListOrdered,
  Map,
  RefreshCw,
  Shield,
} from 'lucide-react';

declare global {
  interface Window {
    __handleMapUpdate?: (payload: any) => void;
    __uwmTraditionalLastMapUpdate?: any;
  }
}

type AnyRecord = Record<string, any>;

function isRecord(value: unknown): value is AnyRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asArray<T = AnyRecord>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function fmtScore(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(3) : '-';
}

function fmtPercent(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? `${Math.round(num * 100)}%` : '-';
}

function gradeClass(grade: unknown): string {
  const text = String(grade || '').toLowerCase();
  return ['a', 'b', 'c', 'd', 'e'].includes(text) ? text : 'unknown';
}

function coverageText(source: AnyRecord): string {
  if ('matched_admin_units' in source && 'requested_admin_units' in source) {
    return `${source.matched_admin_units}/${source.requested_admin_units}`;
  }
  if ('node_count' in source || 'edge_count' in source) {
    return `${source.node_count || 0} 节点 / ${source.edge_count || 0} 边`;
  }
  return source.unit_projection || '-';
}

const complianceLabels: Record<string, string> = {
  not_assessed: '未评估',
  meets_standard: '达到已提供标准',
  below_standard: '低于已提供标准',
};

export default function TraditionalLivabilityTab() {
  const [analysis, setAnalysis] = useState<AnyRecord | null>(null);
  const [s1, setS1] = useState<AnyRecord | null>(null);
  const [s1Unavailable, setS1Unavailable] = useState<AnyRecord | null>(null);
  const [topN, setTopN] = useState(8);
  const [loading, setLoading] = useState(false);
  const [pushingMap, setPushingMap] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const loadTraditionalAnalysis = async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch(`/api/uwm/traditional-livability?top_n=${topN}`, {
        credentials: 'include',
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || '传统方法分析加载失败');
        return;
      }
      setAnalysis(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '传统方法分析加载失败');
    } finally {
      setLoading(false);
    }
  };

  const loadS1Assessment = async () => {
    try {
      const resp = await fetch('/api/uwm/traditional-livability/s1', { credentials: 'include' });
      const data = await resp.json();
      if (!resp.ok || data.ready === false) {
        setS1(null);
        setS1Unavailable(data);
        return;
      }
      setS1(data);
      setS1Unavailable(null);
    } catch (err: unknown) {
      setS1(null);
      setS1Unavailable({ blockers: [err instanceof Error ? err.message : 's1_request_failed'] });
    }
  };

  const pushTraditionalLayerToMap = async () => {
    setPushingMap(true);
    setError('');
    setMessage('');
    try {
      const resp = await fetch('/api/uwm/traditional-livability/map', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ top_n: topN }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error || data.map_update_queued === false) {
        setError(data.error || '传统方法图层发送失败');
        return;
      }
      const mapResp = await fetch('/api/map/pending', { credentials: 'include' });
      const mapData = await mapResp.json();
      const mapUpdate = mapData.map_update || data.map_update;
      window.__uwmTraditionalLastMapUpdate = mapUpdate;
      if (mapUpdate && window.__handleMapUpdate) {
        window.__handleMapUpdate(mapUpdate);
      }
      setMessage('已发送传统方法静态优先级图层到地图。');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '传统方法图层发送失败');
    } finally {
      setPushingMap(false);
    }
  };

  useEffect(() => {
    loadTraditionalAnalysis();
    loadS1Assessment();
  }, [topN]);

  const summary = isRecord(analysis?.summary) ? analysis.summary : {};
  const dataBasis = isRecord(analysis?.data_basis) ? analysis.data_basis : {};
  const indicatorSystem = isRecord(analysis?.indicator_system) ? analysis.indicator_system : {};
  const methodBoundary = isRecord(analysis?.method_boundary) ? analysis.method_boundary : {};
  const rankedUnits = asArray<AnyRecord>(analysis?.ranked_admin_units);
  const priorityDiagnosis = asArray<AnyRecord>(analysis?.priority_diagnosis);
  const dimensions = asArray<AnyRecord>(analysis?.dimension_summary);
  const sourceCoverage = isRecord(dataBasis.source_coverage) ? dataBasis.source_coverage : {};
  const sourceRows = useMemo(
    () => Object.entries(sourceCoverage).map(([name, value]) => ({
      name,
      value: isRecord(value) ? value : {},
    })),
    [sourceCoverage],
  );
  const actionPlan = isRecord(analysis?.static_action_plan) ? analysis.static_action_plan : {};
  const actions = asArray<AnyRecord>(actionPlan.actions);
  const indicatorDimensions = asArray<AnyRecord>(indicatorSystem.dimensions);
  const s1Summary = isRecord(s1?.summary) ? s1.summary : {};
  const s1DataSupport = isRecord(s1?.data_support) ? s1.data_support : {};
  const s1Metrics = asArray<AnyRecord>(s1?.supply_metrics);
  const s1Blockers = asArray<string>(s1?.production_blockers || s1Unavailable?.blockers);

  return (
    <div className="traditional-livability-tab">
      <div className="datapanel-section-header">
        <div>
          <h3>城市宜居性分析（传统方法）</h3>
          <p>同一套UWM多源场景数据上的静态指标聚合、短板诊断和优先级排序。</p>
        </div>
        <div className="traditional-header-actions">
          <label className="traditional-control">
            <span>重点单元数</span>
            <select value={topN} onChange={(event) => setTopN(Number(event.target.value))}>
              {[5, 8, 12, 16, 20].map(value => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <button className="secondary-button" onClick={loadTraditionalAnalysis} disabled={loading}>
            <RefreshCw size={14} />
            刷新
          </button>
          <button className="primary-button" onClick={pushTraditionalLayerToMap} disabled={pushingMap || !analysis}>
            <Map size={14} />
            发送到地图
          </button>
        </div>
      </div>

      {error && <div className="traditional-message error"><AlertTriangle size={15} />{error}</div>}
      {message && <div className="traditional-message success"><Shield size={15} />{message}</div>}
      {loading && !analysis && <div className="traditional-empty">正在加载传统方法分析...</div>}

      <div className="traditional-panel">
        <div className="traditional-panel-title">
          <Database size={15} />
          <strong>S1 设施供需评估</strong>
        </div>
        {s1Unavailable && (
          <div className="traditional-empty">
            S1 快照当前不可用；系统未生成替代性合规结论。阻塞项：{s1Blockers.join(' / ') || '-'}
          </div>
        )}
        {s1 && (
          <>
            <div className="traditional-kpi-grid">
              <div className="traditional-kpi"><span>执行区域</span><strong>重庆市</strong></div>
              <div className="traditional-kpi"><span>{s1DataSupport.complete_inventory ? '完整库存' : '采样库存'}</span><strong>{s1Summary.facility_count || 0}</strong></div>
              <div className="traditional-kpi"><span>已匹配人口单元</span><strong>{s1Summary.population_unit_count || 0}</strong></div>
              <div className="traditional-kpi"><span>未匹配设施</span><strong>{s1Summary.unmatched_facility_count || 0}</strong></div>
            </div>
            <div className="traditional-message error">
              <AlertTriangle size={15} />权威 FP/FPP 标准未提供；下表仅展示设施库存与每万人设施数，不代表达标或不达标。
            </div>
            <div className="traditional-table-wrap">
              <table className="traditional-table">
                <thead><tr><th>行政单元</th><th>设施类</th><th>设施数</th><th>每万人设施数</th><th>合规状态</th></tr></thead>
                <tbody>
                  {s1Metrics.slice(0, 30).map(row => (
                    <tr key={`${row.admin_code}-${row.canonical_class}`}>
                      <td>{row.admin_name || row.admin_code}</td><td>{row.canonical_class}</td><td>{row.facility_count}</td>
                      <td>{fmtScore(row.facilities_per_10000_residents)}</td><td>{complianceLabels[String(row.compliance_status)] || '未评估'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="traditional-boundary-grid">
              <div><span>生产阻塞项 production_blockers</span><strong>{s1Blockers.join(' / ') || '-'}</strong></div>
              <div><span>能力边界</span><strong>当前库存与人口归一化；不含网络服务区、容量合规和未来影响</strong></div>
            </div>
          </>
        )}
      </div>

      {analysis && (
        <>
          <div className="traditional-kpi-grid">
            <div className="traditional-kpi">
              <span>综合宜居性得分</span>
              <strong>{fmtScore(summary.city_livability_score)}</strong>
            </div>
            <div className={`traditional-kpi grade ${gradeClass(summary.grade)}`}>
              <span>评价等级</span>
              <strong>{summary.grade || '-'}</strong>
            </div>
            <div className="traditional-kpi">
              <span>行政单元</span>
              <strong>{summary.admin_unit_count || 0}</strong>
            </div>
            <div className="traditional-kpi">
              <span>数据源</span>
              <strong>{summary.data_source_count || 0}</strong>
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <BarChart3 size={15} />
              <strong>指标维度</strong>
            </div>
            <div className="traditional-bar-list">
              {dimensions.map(item => (
                <div key={item.dimension_id} className="traditional-bar-row">
                  <div>
                    <strong>{item.label}</strong>
                    <span>权重 {fmtPercent(item.weight)} · 低分单元 {item.low_score_unit_count || 0}</span>
                  </div>
                  <div className="traditional-bar-track">
                    <div style={{ width: fmtPercent(item.mean_score) }} />
                  </div>
                  <b>{fmtScore(item.mean_score)}</b>
                </div>
              ))}
            </div>
            <div className="traditional-indicator-grid">
              {indicatorDimensions.map(item => (
                <div key={item.dimension_id}>
                  <span>{item.label}</span>
                  <strong>{asArray<string>(item.indicator_fields).join(' / ')}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <ListOrdered size={15} />
              <strong>静态优先级排名</strong>
            </div>
            <div className="traditional-table-wrap">
              <table className="traditional-table">
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>行政单元</th>
                    <th>宜居得分</th>
                    <th>短板</th>
                    <th>静态建议</th>
                  </tr>
                </thead>
                <tbody>
                  {rankedUnits.slice(0, 12).map(row => (
                    <tr key={row.admin_unit_id}>
                      <td>{row.static_rank}</td>
                      <td>{row.county}{row.township}</td>
                      <td>{fmtScore(row.traditional_livability_score)}</td>
                      <td>
                        <div className="traditional-tag-list">
                          {asArray<string>(row.issue_tags).map(tag => (
                            <span key={tag} className="traditional-tag">{tag}</span>
                          ))}
                        </div>
                      </td>
                      <td>{asArray<string>(row.recommended_static_actions).slice(0, 2).join('；') || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="traditional-two-col">
            <div className="traditional-panel">
              <div className="traditional-panel-title">
                <Gauge size={15} />
                <strong>重点短板诊断</strong>
              </div>
              <div className="traditional-diagnosis-list">
                {priorityDiagnosis.map(row => (
                  <div key={row.admin_unit_id} className="traditional-diagnosis-item">
                    <div>
                      <strong>{row.static_rank}. {row.county}{row.township}</strong>
                      <span>宜居得分 {fmtScore(row.traditional_livability_score)}</span>
                    </div>
                    <div className="traditional-tag-list">
                      {asArray<string>(row.issue_tags).map(tag => (
                        <span key={tag} className="traditional-tag">{tag}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="traditional-panel">
              <div className="traditional-panel-title">
                <Shield size={15} />
                <strong>能力边界</strong>
              </div>
              <div className="traditional-boundary-grid">
                <div>
                  <span>能输出</span>
                  <strong>{asArray<string>(methodBoundary.can_output).join(' / ')}</strong>
                </div>
                <div>
                  <span>不能输出</span>
                  <strong>反事实预测 / 多步策略 / 空间外溢 / 风险校正收益 / 规划器优化方案</strong>
                </div>
              </div>
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <AlertTriangle size={15} />
              <strong>规则静态建议</strong>
            </div>
            <div className="traditional-action-list">
              {actions.map(action => (
                <div key={action.action_type}>
                  <strong>{action.action_name}</strong>
                  <span>{asArray<string>(action.target_units).length} 个目标单元 · {action.basis}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <Database size={15} />
              <strong>数据基础</strong>
            </div>
            <div className="traditional-source-grid">
              {sourceRows.map(row => (
                <div key={row.name}>
                  <span>{row.name}</span>
                  <strong>{coverageText(row.value)}</strong>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
