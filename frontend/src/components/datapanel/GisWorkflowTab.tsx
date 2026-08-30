import { useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Database, GitBranch, LoaderCircle,
  Download, Map, Play, Search, ShieldCheck, Sparkles,
} from 'lucide-react';

type Row = Record<string, any>;

const DEFAULT_QUESTION = '找出生态红线内、距离道路500米以内、面积大于10亩的地块，并按行政区统计面积';
const ROLE_LABELS: Record<string, string> = {
  parcels: '地块',
  eco_redline: '生态红线',
  roads: '道路',
  admin_units: '行政区',
  planning_zones: '规划区',
};
const TEMPLATE_LABELS: Record<string, string> = {
  'parcel-redline-road-admin-summary.v1': '生态红线道路邻近地块分析',
  'planning-zone-land-use-summary.v1': '规划区现状用地叠加统计',
};
const PLANNER_LABELS: Record<string, string> = {
  llm: 'LLM 语义规划',
  deterministic_fallback: '确定性降级解析',
};
const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  supported: '语义已明确',
  needs_clarification: '需要人工确认',
  unsupported: '当前不支持',
};
const UNIT_LABELS: Record<string, string> = {
  meter: '米',
  kilometer: '公里',
  mu: '亩',
  square_meter: '平方米',
  hectare: '公顷',
};

async function callApi(path: string, body: Row): Promise<Row> {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    const message = payload?.error?.message || payload?.error || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload.data || payload;
}

const number = (value: unknown, digits = 2) => new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: digits,
}).format(Number(value || 0));

export default function GisWorkflowTab() {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [redlineRelation, setRedlineRelation] = useState('');
  const [areaBasis, setAreaBasis] = useState('');
  const [roadDistanceBasis, setRoadDistanceBasis] = useState('');
  const [sourceNames, setSourceNames] = useState<Record<string, string>>({});
  const [fieldOverrides, setFieldOverrides] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Row | null>(null);
  const [proposalEnvelope, setProposalEnvelope] = useState<Row | null>(null);
  const [result, setResult] = useState<Row | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [needsReplan, setNeedsReplan] = useState(false);
  const [loading, setLoading] = useState<'proposal' | 'preview' | 'execute' | ''>('');
  const [error, setError] = useState('');
  const templateId = proposalEnvelope?.proposal?.template_id || '';
  const isParcelTemplate = templateId === 'parcel-redline-road-admin-summary.v1';
  const isPlanningZoneTemplate = templateId === 'planning-zone-land-use-summary.v1';

  const requestBody = () => ({
    question: question.trim(),
    proposal: proposalEnvelope?.proposal,
    question_sha256: proposalEnvelope?.question_sha256,
    proposal_fingerprint: proposalEnvelope?.proposal_fingerprint,
    proposal_attestation: proposalEnvelope?.proposal_attestation,
    planner_evidence: proposalEnvelope?.evidence,
    redline_relation: isParcelTemplate ? redlineRelation : null,
    area_basis: isParcelTemplate ? areaBasis : null,
    road_distance_basis: isParcelTemplate ? roadDistanceBasis : null,
    output_crs: 'EPSG:4326',
    source_names: sourceNames,
    fields: Object.fromEntries(
      Object.entries(fieldOverrides).filter(([, value]) => Boolean(value)),
    ),
  });

  const applyProposalSemantics = (proposal: Row) => {
    setRedlineRelation(
      proposal.redline_relation && proposal.redline_relation !== 'unspecified'
        ? proposal.redline_relation : '',
    );
    setAreaBasis(
      proposal.area_basis && proposal.area_basis !== 'unspecified'
        ? proposal.area_basis : '',
    );
    setRoadDistanceBasis(
      proposal.road_distance_basis && proposal.road_distance_basis !== 'unspecified'
        ? proposal.road_distance_basis : '',
    );
  };

  const proposeWorkflow = async () => {
    setLoading('proposal');
    setError('');
    setProposalEnvelope(null);
    setPreview(null);
    setResult(null);
    setConfirmed(false);
    setSourceNames({});
    setFieldOverrides({});
    try {
      const data = await callApi('/api/platform/v1/gis-workflows/proposals', {
        question: question.trim(),
      });
      setProposalEnvelope(data);
      applyProposalSemantics(data.proposal || {});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法生成 GIS 语义提案');
    } finally {
      setLoading('');
    }
  };

  const previewPlan = async () => {
    if (!proposalEnvelope) return;
    setLoading('preview');
    setError('');
    setResult(null);
    setConfirmed(false);
    try {
      const data = await callApi('/api/platform/v1/gis-workflows/preview', requestBody());
      setPreview(data);
      setNeedsReplan(false);
    } catch (reason) {
      setPreview(null);
      setError(reason instanceof Error ? reason.message : '无法生成空间分析计划');
    } finally {
      setLoading('');
    }
  };

  const executePlan = async () => {
    if (!preview?.executable || !preview?.plan_fingerprint || !confirmed) return;
    setLoading('execute');
    setError('');
    try {
      const data = await callApi('/api/platform/v1/gis-workflows/execute', {
        ...requestBody(),
        confirmed_plan_fingerprint: preview.plan_fingerprint,
        confirm_assumptions: true,
      });
      setResult(data);
      (window as any).__handleMapUpdate?.(data.map_update);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '空间工作流执行失败');
    } finally {
      setLoading('');
    }
  };

  const downloadEvidence = () => {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `gis-workflow-${result.evidence?.plan_fingerprint?.slice(0, 12) || 'result'}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const selectedSources = (preview?.source_candidates || []).filter((item: Row) => item.selected);
  const candidatesByRole = (preview?.source_candidates || []).reduce((groups: Row, item: Row) => {
    groups[item.role] = [...(groups[item.role] || []), item];
    return groups;
  }, {} as Row);
  const selectedByRole = Object.fromEntries(selectedSources.map((item: Row) => [item.role, item]));
  const fieldOptions: Record<string, string[]> = {
    parcel_id: selectedByRole.parcels?.available_columns || [],
    admin_code: selectedByRole.admin_units?.available_columns || [],
    admin_name: selectedByRole.admin_units?.available_columns || [],
    land_use_code: selectedByRole.parcels?.available_columns || [],
    land_use_name: selectedByRole.parcels?.available_columns || [],
    zone_code: selectedByRole.planning_zones?.available_columns || [],
    zone_name: selectedByRole.planning_zones?.available_columns || [],
  };
  const requiredFields = isPlanningZoneTemplate
    ? [
        ['parcel_id', '地块标识字段'],
        ['land_use_code', '现状用地代码字段'],
        ['land_use_name', '现状用地名称字段'],
        ['zone_code', '规划区代码字段'],
        ['zone_name', '规划区名称字段'],
      ] as const
    : [
        ['parcel_id', '地块标识字段'],
        ['admin_code', '行政区代码字段'],
        ['admin_name', '行政区名称字段'],
      ] as const;
  const statistics = result?.statistics || [];
  const resultIsPlanningZone = result?.plan?.intent?.template_id === 'planning-zone-land-use-summary.v1';

  return (
    <div className="gis-workflow-workspace">
      <div className="traditional-panel gis-workflow-query">
        <div className="traditional-panel-title">
          <Search size={15} />
          <strong>空间分析需求</strong>
        </div>
        <textarea
          aria-label="空间分析需求"
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
            setProposalEnvelope(null);
            setPreview(null);
            setResult(null);
            setConfirmed(false);
            setSourceNames({});
            setFieldOverrides({});
            setRedlineRelation('');
            setAreaBasis('');
            setRoadDistanceBasis('');
          }}
        />
        <button className="primary-button" onClick={proposeWorkflow} disabled={loading !== '' || question.trim().length < 8}>
          {loading === 'proposal' ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}
          生成语义提案
        </button>
      </div>

      {error && <div className="traditional-message error"><AlertTriangle size={15} />{error}</div>}

      {proposalEnvelope && (
        <div className="traditional-panel gis-workflow-proposal">
          <div className="traditional-panel-title">
            <Sparkles size={15} />
            <strong>语义提案</strong>
            <span className={`gis-workflow-planner-mode ${proposalEnvelope.evidence?.mode || ''}`}>
              {PLANNER_LABELS[proposalEnvelope.evidence?.mode] || proposalEnvelope.evidence?.mode}
            </span>
          </div>
          <div className="gis-workflow-proposal-summary">
            <span>状态</span><strong>{PROPOSAL_STATUS_LABELS[proposalEnvelope.proposal?.status] || proposalEnvelope.proposal?.status}</strong>
            <span>模板</span><strong>{TEMPLATE_LABELS[templateId] || templateId}</strong>
            {isParcelTemplate && (
              <>
                <span>距离</span><strong>{proposalEnvelope.proposal?.distance ? `${proposalEnvelope.proposal.distance.value} ${UNIT_LABELS[proposalEnvelope.proposal.distance.unit] || proposalEnvelope.proposal.distance.unit}` : '未识别'}</strong>
                <span>面积</span><strong>{proposalEnvelope.proposal?.minimum_area ? `${proposalEnvelope.proposal.minimum_area.value} ${UNIT_LABELS[proposalEnvelope.proposal.minimum_area.unit] || proposalEnvelope.proposal.minimum_area.unit}` : '未识别'}</strong>
              </>
            )}
          </div>
          {proposalEnvelope.proposal?.unsupported_reason && (
            <div className="traditional-message error"><AlertTriangle size={15} />{proposalEnvelope.proposal.unsupported_reason}</div>
          )}
          {(proposalEnvelope.proposal?.clarifications || []).length > 0 && (
            <div className="gis-workflow-clarifications">
              {(proposalEnvelope.proposal.clarifications || []).map((item: Row) => (
                <div key={item.clarification_id}><AlertTriangle size={14} /><span>{item.question}</span></div>
              ))}
            </div>
          )}
          {proposalEnvelope.proposal?.status !== 'unsupported' && isParcelTemplate && (
            <div className="gis-workflow-options">
              <label>
                生态红线内
                <select value={redlineRelation} onChange={(event) => {
                  setRedlineRelation(event.target.value);
                  setPreview(null);
                  setConfirmed(false);
                }}>
                  <option value="" disabled>请选择空间关系</option>
                  <option value="intersects">相交即纳入</option>
                  <option value="covered_by">整宗地块完全位于红线内</option>
                </select>
              </label>
              <label>
                面积计算对象
                <select value={areaBasis} onChange={(event) => {
                  setAreaBasis(event.target.value);
                  setPreview(null);
                  setConfirmed(false);
                }}>
                  <option value="" disabled>请选择面积对象</option>
                  <option value="clipped_result">条件处理后的几何</option>
                  <option value="original_parcel">原始完整地块</option>
                </select>
              </label>
              <label>
                道路距离判定
                <select value={roadDistanceBasis} onChange={(event) => {
                  setRoadDistanceBasis(event.target.value);
                  setPreview(null);
                  setConfirmed(false);
                }}>
                  <option value="" disabled>请选择距离对象</option>
                  <option value="geometry_boundary">按地块几何边界</option>
                  <option value="centroid">按地块中心点</option>
                </select>
              </label>
            </div>
          )}
          <div className="gis-workflow-planner-evidence">
            <span>{proposalEnvelope.evidence?.provider || '本地规则'} / {proposalEnvelope.evidence?.model || '固定解析器'}</span>
            <span>提示词 {proposalEnvelope.evidence?.prompt_version}</span>
            {proposalEnvelope.evidence?.response_sha256 && (
              <code title={proposalEnvelope.evidence.response_sha256}>
                响应指纹 {proposalEnvelope.evidence.response_sha256.slice(0, 16)}...
              </code>
            )}
            {proposalEnvelope.evidence?.fallback_reason && <span>原因：{proposalEnvelope.evidence.fallback_reason}</span>}
          </div>
          <button
            className="primary-button"
            onClick={previewPlan}
            disabled={
              loading !== ''
              || proposalEnvelope.proposal?.status === 'unsupported'
              || (isParcelTemplate && (!redlineRelation || !areaBasis || !roadDistanceBasis))
            }
          >
            {loading === 'preview' ? <LoaderCircle className="spin" size={15} /> : <GitBranch size={15} />}
            校验数据并生成 DAG
          </button>
        </div>
      )}

      {preview && (
        <>
          <div className={`traditional-message ${preview.executable ? 'success' : 'error'}`}>
            {preview.executable && !needsReplan ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
            {needsReplan
              ? '数据源或字段选择已变化，请重新生成计划。'
              : preview.executable
                ? '计划已就绪，可以确认执行。'
                : '计划暂不可执行，请先解决数据或字段阻塞项。'}
          </div>

          {(preview.blockers || []).length > 0 && (
            <div className="traditional-panel">
              <div className="traditional-panel-title"><AlertTriangle size={15} /><strong>阻塞项</strong></div>
              <div className="gis-workflow-blockers">
                {preview.blockers.map((item: Row, index: number) => (
                  <div key={`${item.code}-${index}`}>
                    <strong>{ROLE_LABELS[item.role] || item.role || '需求'}</strong>
                    <span>{item.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="traditional-panel">
            <div className="traditional-panel-title"><Database size={15} /><strong>数据依据</strong></div>
            <div className="gis-workflow-source-grid">
              {Object.entries(candidatesByRole).map(([role, candidates]) => {
                const items = candidates as Row[];
                const selected = items.find((item) => item.selected);
                return (
                  <div key={role}>
                    <label htmlFor={`gis-workflow-source-${role}`}>{ROLE_LABELS[role] || role}</label>
                    <select
                      id={`gis-workflow-source-${role}`}
                      value={sourceNames[role] || selected?.semantic_source_name || ''}
                      onChange={(event) => {
                        setSourceNames((current) => ({ ...current, [role]: event.target.value }));
                        setConfirmed(false);
                        setNeedsReplan(true);
                        setResult(null);
                      }}
                    >
                      <option value="">请选择</option>
                      {items.map((item) => (
                        <option key={item.resource_version_id} value={item.semantic_source_name}>
                          {item.semantic_source_name} · {item.version_key}
                        </option>
                      ))}
                    </select>
                    {selected && <small>版本 {selected.version_key} · {selected.source_crs || 'CRS 未知'}</small>}
                  </div>
                );
              })}
              {Object.keys(candidatesByRole).length === 0 && <p>尚未发现活动的版本化空间数据源。</p>}
            </div>
            <div className="gis-workflow-field-grid">
              {requiredFields.map(([field, label]) => (
                <div key={field}>
                  <label htmlFor={`gis-workflow-field-${field}`}>{label}</label>
                  <select
                    id={`gis-workflow-field-${field}`}
                    value={fieldOverrides[field] || ''}
                    onChange={(event) => {
                      setFieldOverrides((current) => ({ ...current, [field]: event.target.value }));
                      setConfirmed(false);
                      setNeedsReplan(true);
                      setResult(null);
                    }}
                    disabled={fieldOptions[field].length === 0}
                  >
                    <option value="">自动识别</option>
                    {fieldOptions[field].map((column) => <option key={column} value={column}>{column}</option>)}
                  </select>
                </div>
              ))}
            </div>
            {needsReplan && (
              <button className="secondary-button gis-workflow-replan" onClick={previewPlan} disabled={loading !== ''}>
                <GitBranch size={15} />按当前选择重新生成计划
              </button>
            )}
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title"><GitBranch size={15} /><strong>确定性执行步骤</strong></div>
            <ol className="gis-workflow-steps">
              {(preview.steps || []).map((step: Row) => (
                <li key={step.node_id}>
                  <strong>{step.title}</strong>
                  <span>{step.algorithm.algorithm_id} · {step.algorithm.algorithm_version}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title"><ShieldCheck size={15} /><strong>执行前确认</strong></div>
            <div className="gis-workflow-assumptions">
              {(preview.assumptions || []).map((item: Row) => (
                <div key={item.assumption_id}>
                  <strong>{item.label}</strong>
                  <span>{item.consequence}</span>
                </div>
              ))}
            </div>
            <label className="gis-workflow-confirm">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                disabled={!preview.executable || needsReplan}
              />
              我确认上述数据版本、步骤和空间语义
            </label>
            <button className="primary-button" onClick={executePlan} disabled={!preview.executable || needsReplan || !confirmed || loading !== ''}>
              {loading === 'execute' ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />}
              执行空间分析
            </button>
          </div>
        </>
      )}

      {result && (
        <div className="traditional-panel gis-workflow-results">
          <div className="traditional-panel-title"><CheckCircle2 size={15} /><strong>分析结果</strong></div>
          <div className="traditional-kpi-grid">
            <div className="traditional-kpi"><span>{resultIsPlanningZone ? '叠加地块' : '符合条件地块'}</span><strong>{number(resultIsPlanningZone ? result.summary?.parcel_count : result.summary?.eligible_parcel_count, 0)}</strong></div>
            <div className="traditional-kpi"><span>{resultIsPlanningZone ? '规划区' : '行政区'}</span><strong>{number(resultIsPlanningZone ? result.summary?.planning_zone_count : result.summary?.admin_unit_count, 0)}</strong></div>
            <div className="traditional-kpi"><span>总面积（亩）</span><strong>{number(resultIsPlanningZone ? result.summary?.total_intersection_area_mu : result.summary?.total_allocated_area_mu)}</strong></div>
            <div className="traditional-kpi"><span>执行耗时</span><strong>{number(result.evidence?.duration_ms, 0)} ms</strong></div>
          </div>
          <p>{result.summary?.conclusion}</p>
          <div className="traditional-table-wrap">
            <table className="traditional-table">
              <thead><tr>{resultIsPlanningZone ? <><th>规划区</th><th>现状用地</th></> : <th>行政区</th>}<th>地块数</th><th>面积（亩）</th></tr></thead>
              <tbody>{statistics.map((item: Row) => (
                <tr key={resultIsPlanningZone ? `${item.zone_code}-${item.land_use_code}` : item.admin_code}>
                  <td>{resultIsPlanningZone ? item.zone_name : item.admin_name}</td>
                  {resultIsPlanningZone && <td>{item.land_use_name}</td>}
                  <td>{number(item.parcel_count, 0)}</td>
                  <td>{number(item.area_mu)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="gis-workflow-result-actions">
            <button className="secondary-button" onClick={() => (window as any).__handleMapUpdate?.(result.map_update)}>
              <Map size={15} />发送结果到地图
            </button>
            <button className="secondary-button" onClick={downloadEvidence}>
              <Download size={15} />下载执行证据
            </button>
          </div>
            <div className="gis-workflow-evidence">
            <span>规划模式</span><code>{PLANNER_LABELS[result.plan?.planner_evidence?.mode] || result.plan?.planner_evidence?.mode}</code>
            <span>Proposal 指纹</span><code>{result.plan?.proposal_fingerprint}</code>
            <span>计划指纹</span><code>{result.evidence?.plan_fingerprint}</code>
            <span>结果指纹</span><code>{result.evidence?.result_sha256}</code>
          </div>
        </div>
      )}
    </div>
  );
}
