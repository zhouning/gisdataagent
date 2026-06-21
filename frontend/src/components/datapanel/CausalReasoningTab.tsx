import { useEffect, useState } from 'react';

/* ---------- Response Interfaces ---------- */
interface DagNode { id: string; label: string; type?: string }
interface DagEdge { source: string; target: string; label?: string }
interface DagResult {
  explanation: string;
  mermaid_code?: string;
  dag_plot_path?: string;
  nodes: DagNode[];
  edges: DagEdge[];
}

interface CounterfactualResult {
  chain: string[];
  confidence: number;
  key_assumptions: string[];
}

interface ExplainResult {
  mechanism_explanation: string;
  causal_pathway: string;
  alternative_explanations: string[];
  robustness_checks: string[];
}

interface ScenarioItem {
  name: string;
  description: string;
  expected_direction: string;
  world_model_scenario?: string;
}
interface ScenarioResult {
  scenarios: ScenarioItem[];
}

interface SCCACase {
  case_id: string;
  label: string;
  description: string;
  default_row_limit?: number | null;
  exposure: string;
  outcome: string;
  confounder_count: number;
  context_columns: string[];
}
interface SCCACasesResult {
  cases: SCCACase[];
}
interface SCCAResult {
  case_id: string;
  case_label: string;
  description: string;
  row_limit?: number | null;
  row_count?: number;
  column_count?: number;
  output_dir: string;
  exposure: string;
  outcome: string;
  confounders: string[];
  context_columns: string[];
  credibility_decision?: string;
  robustness_interpretation?: string;
  evidence_grade?: string;
  evidence_grade_reasons?: string[];
  result_summary?: Record<string, any>;
  effect_estimates: Record<string, any>[];
  balance_summary: Record<string, any>[];
  robustness?: Record<string, any>;
  spatial_diagnostics?: Record<string, any>;
  data_profile?: Record<string, any>;
  files: Record<string, string>;
  map_update?: any;
  map_update_queued?: boolean;
  spatial_outputs?: Record<string, any>;
  spatial_map_error?: string;
  user_summary?: {
    headline?: string;
    plain_effect?: string;
    map_plain?: string;
    map_field?: string;
    map_field_label?: string;
    coverage?: {
      raw_input_units?: number;
      analysis_units?: number;
      mapped_features?: number;
      ratio?: number | null;
      unit_label?: string;
      is_full?: boolean;
    };
    effect?: {
      coef?: number | null;
      p_value?: number | null;
      estimator?: string;
      direction?: string;
    };
    credibility?: {
      grade?: string;
      decision?: string;
      robustness?: string;
      reasons?: string[];
    };
    caveats?: string[];
    next_action?: string;
  };
}

/* ---------- Domains & Methods ---------- */
const DOMAINS = [
  { value: 'urban_geography', label: '城市地理' },
  { value: 'ecological', label: '生态' },
  { value: 'agricultural', label: '农业' },
  { value: 'climate', label: '气候' },
  { value: 'general', label: '通用' },
];

const METHODS = ['PSM', 'DiD', 'ERF', 'Granger', 'GCCM', 'Causal Forest'];

type Section = 'scca' | 'dag' | 'counterfactual' | 'explain' | 'scenario';

/* ---------- Styles ---------- */
const S: Record<string, React.CSSProperties> = {
  section: { marginBottom: 16, borderBottom: '1px solid #eee', paddingBottom: 12 },
  sectionTitle: { fontWeight: 700, marginBottom: 8, fontSize: 14 },
  resultBox: { background: '#f5f5f5', padding: 12, borderRadius: 6, marginTop: 8, fontSize: 13, lineHeight: 1.6 },
  insightBox: { background: '#fff', border: '1px solid #d6d3d1', borderLeft: '4px solid var(--primary, #0d9488)', padding: 12, borderRadius: 6, marginTop: 10 },
  insightTitle: { fontSize: 15, fontWeight: 700, color: '#1c1917', marginBottom: 6 },
  detailBlock: { background: '#fff', border: '1px solid #e7e5e4', borderRadius: 6, padding: 10, marginTop: 8 },
  detailTitle: { fontSize: 13, fontWeight: 700, color: '#292524', marginBottom: 4 },
  mutedText: { color: '#57534e', fontSize: 12, lineHeight: 1.5 },
  chainStep: { display: 'flex', alignItems: 'center', marginBottom: 4, gap: 6 },
  switcher: { display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' as const },
  switchBtn: { padding: '5px 12px', borderRadius: 6, border: '1px solid #d6d3d1', background: '#fff', cursor: 'pointer', fontSize: 13 },
  switchBtnActive: { padding: '5px 12px', borderRadius: 6, border: '1px solid var(--primary, #0d9488)', background: 'var(--primary-light, #f0fdfa)', cursor: 'pointer', fontSize: 13, fontWeight: 600, color: 'var(--primary, #0d9488)' },
  input: { width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid #d6d3d1', fontSize: 13, marginBottom: 8 },
  select: { width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid #d6d3d1', fontSize: 13, marginBottom: 8 },
  textarea: { width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid #d6d3d1', fontSize: 13, marginBottom: 8, minHeight: 60, resize: 'vertical' as const, fontFamily: 'inherit' },
  btn: { padding: '7px 18px', borderRadius: 8, border: 'none', background: 'var(--primary, #0d9488)', color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  btnDisabled: { opacity: 0.6, cursor: 'not-allowed' },
  label: { display: 'block', fontSize: 12, color: '#57534e', marginBottom: 2, fontWeight: 500 },
  error: { color: '#dc2626', fontSize: 13, marginTop: 6 },
  row: { marginBottom: 8 },
  pre: { background: '#1e1e1e', color: '#d4d4d4', padding: 10, borderRadius: 6, fontSize: 12, overflowX: 'auto' as const, whiteSpace: 'pre-wrap' as const },
  table: { width: '100%', borderCollapse: 'collapse' as const, fontSize: 13 },
  th: { textAlign: 'left' as const, padding: '6px 8px', borderBottom: '2px solid #d6d3d1', background: '#fafaf9', fontWeight: 600 },
  td: { padding: '6px 8px', borderBottom: '1px solid #eee' },
  badge: { display: 'inline-block', fontSize: 12, padding: '1px 8px', borderRadius: 10, background: '#e0f2fe', color: '#0369a1' },
  empty: { textAlign: 'center' as const, color: '#a8a29e', padding: 32, fontSize: 13 },
  grid2: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8 },
  kv: { background: '#fff', border: '1px solid #e7e5e4', borderRadius: 6, padding: 8 },
  kvLabel: { fontSize: 11, color: '#78716c', marginBottom: 2 },
  kvValue: { fontSize: 13, fontWeight: 600, color: '#292524', wordBreak: 'break-word' as const },
};

/* ---------- Helpers ---------- */
async function post<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const r = await fetch(url, {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok || data.error) throw new Error(data.error || data.detail || '请求失败');
  return data as T;
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { method: 'GET', credentials: 'include' });
  const data = await r.json();
  if (!r.ok || data.error) throw new Error(data.error || data.detail || '请求失败');
  return data as T;
}

function fmt(value: unknown, digits = 3): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—';
    if (value !== 0 && Math.abs(value) < 0.001) return value.toExponential(2);
    return value.toFixed(digits);
  }
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value);
}

function estimatorLabel(value: unknown): string {
  const key = String(value || '');
  const labels: Record<string, string> = {
    baseline_adjusted_ols: '基准调整回归',
    spatial_lag_adjusted_ols: '空间滞后校准回归',
    spatial_slx_ols: '空间邻域暴露回归',
    erf_delta_anchor: '目标情景响应曲线',
  };
  return labels[key] || key || '估计器';
}

function estimatorHint(value: unknown): string {
  const key = String(value || '');
  const hints: Record<string, string> = {
    baseline_adjusted_ols: '核心参考模型：在控制混淆变量后，估计处理变量对结果变量的平均方向和幅度。',
    spatial_lag_adjusted_ols: '检查邻近区域的暴露或结果是否改变主效应，用来识别空间依赖。',
    spatial_slx_ols: '把邻域暴露纳入模型，用来判断是否存在空间溢出影响。',
    erf_delta_anchor: '把模型换算为目标情景，例如达到 35°C 或 70 岁需要处理变量变化多少。',
  };
  return hints[key] || '用于补充判断主效应是否稳定。';
}

function effectInterpretation(row: Record<string, any>, exposure: string, outcome: string): string {
  const coef = Number(row.coef);
  const p = Number(row.p_value);
  const ciLower = row.ci_lower;
  const ciUpper = row.ci_upper;
  const direction = Number.isFinite(coef)
    ? coef > 0 ? '正向' : coef < 0 ? '负向' : '接近 0'
    : '方向不明确';
  const sig = Number.isFinite(p)
    ? p < 0.05 ? '达到常用显著性阈值' : '未达到常用显著性阈值'
    : '显著性未计算';
  const ci = ciLower !== undefined && ciUpper !== undefined
    ? `，95% 置信区间约为 ${fmt(ciLower)} 到 ${fmt(ciUpper)}`
    : '';
  return `${exposure} 对 ${outcome} 的估计方向为${direction}，P 值 ${fmt(p)}，${sig}${ci}。`;
}

function topBalanceRows(rows: Record<string, any>[]): Record<string, any>[] {
  return [...(rows || [])]
    .sort((a, b) => Number(b.abs_corr_with_exposure || 0) - Number(a.abs_corr_with_exposure || 0))
    .slice(0, 5);
}

function balanceStatus(rows: Record<string, any>[]): string {
  const maxCorr = Math.max(0, ...((rows || []).map(r => Number(r.abs_corr_with_exposure || 0))));
  if (maxCorr < 0.1) return `较好，最大暴露相关约 ${fmt(maxCorr)}。`;
  if (maxCorr < 0.3) return `可接受，但仍有变量与处理变量相关，最大约 ${fmt(maxCorr)}。`;
  return `需要谨慎，存在较强相关变量，最大约 ${fmt(maxCorr)}。`;
}

function yesNo(value: unknown): string {
  if (value === true) return '通过';
  if (value === false) return '未通过';
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

/* ========== Component ========== */
export default function CausalReasoningTab() {
  const [section, setSection] = useState<Section>('scca');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  /* --- DAG state --- */
  const [dagQ, setDagQ] = useState('');
  const [dagDomain, setDagDomain] = useState('general');
  const [dagGeofm, setDagGeofm] = useState(false);
  const [dagResult, setDagResult] = useState<DagResult | null>(null);
  const [dagMermaidOpen, setDagMermaidOpen] = useState(false);

  /* --- Counterfactual state --- */
  const [cfQ, setCfQ] = useState('');
  const [cfCtx, setCfCtx] = useState('');
  const [cfTime, setCfTime] = useState('');
  const [cfResult, setCfResult] = useState<CounterfactualResult | null>(null);

  /* --- Explain state --- */
  const [exStat, setExStat] = useState('');
  const [exMethod, setExMethod] = useState('PSM');
  const [exQ, setExQ] = useState('');
  const [exResult, setExResult] = useState<ExplainResult | null>(null);

  /* --- Scenario state --- */
  const [scBase, setScBase] = useState('');
  const [scN, setScN] = useState(3);
  const [scTarget, setScTarget] = useState('');
  const [scConstraint, setScConstraint] = useState('');
  const [scResult, setScResult] = useState<ScenarioResult | null>(null);

  /* --- SCCA state --- */
  const [sccaCases, setSccaCases] = useState<SCCACase[]>([]);
  const [sccaCaseId, setSccaCaseId] = useState('chongqing_uhi');
  const [sccaRowLimit, setSccaRowLimit] = useState(600);
  const [sccaFullData, setSccaFullData] = useState(true);
  const [sccaResult, setSccaResult] = useState<SCCAResult | null>(null);
  const [showSccaDetails, setShowSccaDetails] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    setLoading(true); setError('');
    try { await fn(); } catch (e: any) { setError(e.message || '请求失败'); } finally { setLoading(false); }
  };

  useEffect(() => {
    let cancelled = false;
    getJson<SCCACasesResult>('/api/causal/scca/cases')
      .then(data => {
        if (cancelled) return;
        setSccaCases(data.cases);
        const selected = data.cases.find(c => c.case_id === sccaCaseId) || data.cases[0];
        if (selected) {
          setSccaCaseId(selected.case_id);
          if (selected.default_row_limit) setSccaRowLimit(selected.default_row_limit);
        }
      })
      .catch(() => {
        // Auth/session errors are surfaced when the user runs a workflow.
      });
    return () => { cancelled = true; };
  }, []);

  /* ---------- Render ---------- */
  const tabs: { key: Section; label: string }[] = [
    { key: 'scca', label: 'SCCA校准' },
    { key: 'dag', label: '因果图构建' },
    { key: 'counterfactual', label: '反事实推理' },
    { key: 'explain', label: '机制解释' },
    { key: 'scenario', label: '情景生成' },
  ];

  return (
    <div style={{ padding: 12, overflowY: 'auto', height: '100%' }}>
      {/* Tab switcher */}
      <div style={S.switcher}>
        {tabs.map(t => (
          <button key={t.key} style={section === t.key ? S.switchBtnActive : S.switchBtn}
            onClick={() => { setSection(t.key); setError(''); }}>{t.label}</button>
        ))}
      </div>

      {/* ===== 0. SCCA Runner ===== */}
      {section === 'scca' && (
        <div style={S.section}>
          <div style={S.sectionTitle}>SCCA 空间上下文因果校准</div>
          <div style={S.row}>
            <label style={S.label}>测试流程</label>
            <select
              style={S.select}
              value={sccaCaseId}
              onChange={e => {
                const next = e.target.value;
                setSccaCaseId(next);
                const matched = sccaCases.find(c => c.case_id === next);
                if (matched?.default_row_limit) setSccaRowLimit(matched.default_row_limit);
              }}
            >
              {(sccaCases.length ? sccaCases : [
                { case_id: 'chongqing_uhi', label: '重庆 UHI 建筑高度热环境', description: '', exposure: 'floor', outcome: 'LST', confounder_count: 7, context_columns: [] },
                { case_id: 'county_social_capital', label: '美国 CountyData 社会资本长寿', description: '', exposure: 'SocialAssoc', outcome: 'AveAgeDeath', confounder_count: 11, context_columns: [] },
              ]).map(c => <option key={c.case_id} value={c.case_id}>{c.label}</option>)}
            </select>
          </div>
          <div style={S.grid2}>
            <div style={S.row}>
              <label style={S.label}>抽样行数</label>
              <input
                type="number"
                min={50}
                max={5000}
                style={S.input}
                disabled={sccaFullData}
                value={sccaRowLimit}
                onChange={e => setSccaRowLimit(Math.max(50, Number(e.target.value) || 600))}
              />
            </div>
            <div style={{ ...S.row, display: 'flex', alignItems: 'center', gap: 6, paddingTop: 20 }}>
              <input
                type="checkbox"
                id="scca-full-data"
                checked={sccaFullData}
                onChange={e => setSccaFullData(e.target.checked)}
              />
              <label htmlFor="scca-full-data" style={{ fontSize: 13 }}>地图展示完整样例数据</label>
            </div>
          </div>
          <div style={{ ...S.mutedText, marginBottom: 8 }}>
            勾选完整样例数据时，重庆会显示所有样本建筑面，美国会显示所有样本县域；关闭后只取前 N 行用于快速测试。
          </div>
          <button style={{ ...S.btn, ...(loading ? S.btnDisabled : {}) }} disabled={loading}
            onClick={() => run(async () => {
              const body: Record<string, unknown> = { case_id: sccaCaseId };
              body.row_limit = sccaFullData ? null : sccaRowLimit;
              const result = await post<SCCAResult>('/api/causal/scca/run', body);
              setSccaResult(result);
              if (result.map_update && (window as any).__handleMapUpdate) {
                (window as any).__handleMapUpdate(result.map_update);
              }
            })}>
            {loading ? '运行中...' : '运行 SCCA 测试流程'}
          </button>

          {sccaResult && (
            <div style={S.resultBox}>
              <div style={S.insightBox}>
                <div style={S.insightTitle}>{sccaResult.user_summary?.headline || 'SCCA 分析完成'}</div>
                <div>{sccaResult.user_summary?.plain_effect || `${sccaResult.exposure} → ${sccaResult.outcome}`}</div>
                <div style={{ ...S.mutedText, marginTop: 6 }}>{sccaResult.user_summary?.map_plain}</div>
              </div>

              <div style={{ ...S.grid2, marginTop: 10 }}>
                <div style={S.kv}>
                  <div style={S.kvLabel}>分析对象</div>
                  <div style={S.kvValue}>{sccaResult.case_label}</div>
                </div>
                <div style={S.kv}>
                  <div style={S.kvLabel}>地图覆盖</div>
                  <div style={S.kvValue}>
                    {fmt(sccaResult.user_summary?.coverage?.mapped_features ?? sccaResult.map_update?.summary?.feature_count, 0)}
                    {' / '}
                    {fmt(sccaResult.user_summary?.coverage?.analysis_units ?? sccaResult.row_count, 0)}
                    {' '}
                    {sccaResult.user_summary?.coverage?.unit_label || '单元'}
                  </div>
                  {sccaResult.user_summary?.coverage?.raw_input_units &&
                    sccaResult.user_summary.coverage.raw_input_units !== sccaResult.user_summary.coverage.analysis_units && (
                      <div style={S.mutedText}>原始输入 {fmt(sccaResult.user_summary.coverage.raw_input_units, 0)} 条，已剔除缺失/异常记录</div>
                    )}
                </div>
                <div style={S.kv}>
                  <div style={S.kvLabel}>地图指标</div>
                  <div style={S.kvValue}>{sccaResult.user_summary?.map_field_label || sccaResult.map_update?.summary?.map_field || 'SCCA 指标'}</div>
                </div>
                <div style={S.kv}>
                  <div style={S.kvLabel}>可信度</div>
                  <div style={S.kvValue}>{sccaResult.user_summary?.credibility?.grade || sccaResult.evidence_grade || '—'}</div>
                </div>
              </div>

              <div style={{ marginTop: 10 }}>
                <strong>怎么读这张图:</strong>
                <ul style={{ margin: '4px 0 0 18px', padding: 0 }}>
                  {(sccaResult.user_summary?.caveats || []).slice(0, 4).map((item, i) => <li key={i}>{item}</li>)}
                  {sccaResult.user_summary?.next_action && <li>{sccaResult.user_summary.next_action}</li>}
                </ul>
              </div>

              <div style={{ marginTop: 10 }}>
                <span style={S.badge}>处理变量: {sccaResult.exposure}</span>{' '}
                <span style={S.badge}>结果变量: {sccaResult.outcome}</span>{' '}
                <span style={S.badge}>控制变量: {sccaResult.confounders.length} 个</span>
              </div>

              <button
                style={{ ...S.switchBtn, marginTop: 10 }}
                onClick={() => setShowSccaDetails(!showSccaDetails)}
              >
                {showSccaDetails ? '收起技术细节' : '查看技术细节'}
              </button>

              {showSccaDetails && (
                <div style={{ marginTop: 8 }}>
                  <div style={S.detailBlock}>
                    <div style={S.detailTitle}>1. 模型设定</div>
                    <div style={S.mutedText}>这部分说明本次 SCCA 到底在估计什么，哪些变量被当作控制项。</div>
                    <div style={{ marginTop: 6 }}>
                      <span style={S.badge}>处理变量 {sccaResult.exposure}</span>{' '}
                      <span style={S.badge}>结果变量 {sccaResult.outcome}</span>{' '}
                      <span style={S.badge}>有效样本 {fmt(sccaResult.row_count, 0)}</span>
                    </div>
                    <div style={{ marginTop: 6 }}>
                      <strong>控制变量:</strong> {sccaResult.confounders.join('、') || '—'}
                    </div>
                    <div style={{ marginTop: 4 }}>
                      <strong>空间上下文:</strong> {sccaResult.context_columns.join('、') || '—'}
                    </div>
                  </div>

                  {sccaResult.effect_estimates.length > 0 && (
                    <div style={S.detailBlock}>
                      <div style={S.detailTitle}>2. 估计结果怎么读</div>
                      <div style={S.mutedText}>系数表示处理变量增加 1 个单位时，结果变量的估计变化；P 值越小，说明这个估计越不容易由随机波动解释。</div>
                      {sccaResult.effect_estimates.slice(0, 4).map((row, i) => (
                        <div key={i} style={{ borderTop: i === 0 ? 'none' : '1px solid #eee', paddingTop: i === 0 ? 0 : 8, marginTop: i === 0 ? 6 : 8 }}>
                          <div style={{ fontWeight: 700 }}>{estimatorLabel(row.estimator)}</div>
                          <div style={S.mutedText}>{estimatorHint(row.estimator)}</div>
                          <div style={{ ...S.grid2, marginTop: 6 }}>
                            <div style={S.kv}><div style={S.kvLabel}>系数</div><div style={S.kvValue}>{fmt(row.coef)}</div></div>
                            <div style={S.kv}><div style={S.kvLabel}>P 值</div><div style={S.kvValue}>{fmt(row.p_value)}</div></div>
                            <div style={S.kv}><div style={S.kvLabel}>解释度 R²</div><div style={S.kvValue}>{fmt(row.r_squared)}</div></div>
                            <div style={S.kv}><div style={S.kvLabel}>样本数</div><div style={S.kvValue}>{fmt(row.n, 0)}</div></div>
                          </div>
                          <div style={{ marginTop: 6 }}>{effectInterpretation(row, sccaResult.exposure, sccaResult.outcome)}</div>
                          {row.warnings && row.warnings !== '[]' && <div style={{ ...S.mutedText, color: '#b45309' }}>提示: {fmt(row.warnings)}</div>}
                        </div>
                      ))}
                    </div>
                  )}

                  {sccaResult.balance_summary && sccaResult.balance_summary.length > 0 && (
                    <div style={S.detailBlock}>
                      <div style={S.detailTitle}>3. 混淆控制是否平衡</div>
                      <div style={S.mutedText}>这里看控制变量和处理变量的剩余相关性。数值越小，说明处理变量和该控制变量越不容易混在一起。</div>
                      <div style={{ marginTop: 6 }}><strong>总体判断:</strong> {balanceStatus(sccaResult.balance_summary)}</div>
                      <table style={{ ...S.table, marginTop: 6 }}>
                        <thead>
                          <tr>
                            <th style={S.th}>变量</th>
                            <th style={S.th}>与处理变量的绝对相关</th>
                            <th style={S.th}>解读</th>
                          </tr>
                        </thead>
                        <tbody>
                          {topBalanceRows(sccaResult.balance_summary).map((row, i) => (
                            <tr key={i}>
                              <td style={S.td}>{fmt(row.variable)}</td>
                              <td style={S.td}>{fmt(row.abs_corr_with_exposure)}</td>
                              <td style={S.td}>{Number(row.abs_corr_with_exposure || 0) < 0.1 ? '很好' : Number(row.abs_corr_with_exposure || 0) < 0.3 ? '可接受' : '偏高，需谨慎'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {(sccaResult.spatial_diagnostics || sccaResult.robustness) && (
                    <div style={S.detailBlock}>
                      <div style={S.detailTitle}>4. 空间诊断与稳健性</div>
                      <div style={S.mutedText}>这里回答两个问题：空间邻近关系是否会改变结论，换一种检查方法后结论是否稳定。</div>
                      <div style={{ ...S.grid2, marginTop: 6 }}>
                        <div style={S.kv}>
                          <div style={S.kvLabel}>诊断状态</div>
                          <div style={S.kvValue}>{fmt(sccaResult.spatial_diagnostics?.status)}</div>
                        </div>
                        <div style={S.kv}>
                          <div style={S.kvLabel}>空间图边数</div>
                          <div style={S.kvValue}>{fmt(sccaResult.spatial_diagnostics?.graph?.edge_count, 0)}</div>
                        </div>
                        <div style={S.kv}>
                          <div style={S.kvLabel}>方向稳定</div>
                          <div style={S.kvValue}>{yesNo(sccaResult.robustness?.ablation_direction_stable)}</div>
                        </div>
                        <div style={S.kv}>
                          <div style={S.kvLabel}>Bootstrap 符号稳定</div>
                          <div style={S.kvValue}>{fmt(sccaResult.robustness?.bootstrap_sign_stability)}</div>
                        </div>
                      </div>
                      {sccaResult.robustness?.main_limitation && (
                        <div style={{ marginTop: 6, color: '#b45309' }}>
                          主要限制: {fmt(sccaResult.robustness.main_limitation)}
                        </div>
                      )}
                    </div>
                  )}

                  {sccaResult.evidence_grade_reasons && sccaResult.evidence_grade_reasons.length > 0 && (
                    <div style={S.detailBlock}>
                      <div style={S.detailTitle}>5. 证据等级依据</div>
                      <ul style={{ margin: '4px 0 0 18px' }}>
                        {sccaResult.evidence_grade_reasons.slice(0, 4).map((reason, i) => <li key={i}>{reason}</li>)}
                      </ul>
                    </div>
                  )}

                  <div style={S.detailBlock}>
                    <div style={S.detailTitle}>6. 输出文件</div>
                    <div style={S.mutedText}>这些文件用于复核、下载或继续做报告，不需要先读它们才能理解页面结论。</div>
                    <div style={{ marginTop: 6 }}><strong>输出目录:</strong> <code>{sccaResult.output_dir}</code></div>
                    {sccaResult.files && Object.keys(sccaResult.files).length > 0 && (
                      <div style={{ marginTop: 6 }}>
                      {['manifest', 'effect_estimates', 'spatial_diagnostics', 'robustness_manifest', 'result_summary_markdown']
                        .filter(k => sccaResult.files[k])
                        .map(k => <span key={k} style={S.badge}>{k}</span>)
                        .reduce<React.ReactNode[]>((a, b) => [...a, ' ', b], [])}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {sccaResult.spatial_map_error && (
                <div style={{ marginTop: 6, color: '#b45309' }}>
                  地图输出提示: {sccaResult.spatial_map_error}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ===== 1. DAG Builder ===== */}
      {section === 'dag' && (
        <div style={S.section}>
          <div style={S.sectionTitle}>因果图构建</div>
          <div style={S.row}>
            <label style={S.label}>问题</label>
            <input style={S.input} value={dagQ} onChange={e => setDagQ(e.target.value)}
              placeholder="例如: 城市扩张如何影响耕地面积" />
          </div>
          <div style={S.row}>
            <label style={S.label}>领域</label>
            <select style={S.select} value={dagDomain} onChange={e => setDagDomain(e.target.value)}>
              {DOMAINS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
            </select>
          </div>
          <div style={{ ...S.row, display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={dagGeofm} onChange={e => setDagGeofm(e.target.checked)} id="geofm-cb" />
            <label htmlFor="geofm-cb" style={{ fontSize: 13 }}>使用 GeoFM 嵌入</label>
          </div>
          <button style={{ ...S.btn, ...(loading ? S.btnDisabled : {}) }} disabled={loading}
            onClick={() => run(async () => {
              const d = await post<DagResult>('/api/causal/dag', { question: dagQ, domain: dagDomain, use_geofm_embedding: dagGeofm });
              setDagResult(d);
            })}>
            {loading ? '构建中...' : '构建因果图'}
          </button>

          {dagResult && (
            <div style={S.resultBox}>
              <div style={{ marginBottom: 8 }}>{dagResult.explanation}</div>
              {dagResult.dag_plot_path && (
                <img src={dagResult.dag_plot_path} alt="DAG" style={{ maxWidth: '100%', borderRadius: 6, marginBottom: 8 }} />
              )}
              {dagResult.nodes.length > 0 && (
                <div style={{ marginBottom: 6 }}>
                  <strong>节点:</strong>{' '}
                  {dagResult.nodes.map(n => <span key={n.id} style={S.badge}>{n.label}</span>).reduce<React.ReactNode[]>((a, b) => [...a, ' ', b], [])}
                </div>
              )}
              {dagResult.edges.length > 0 && (
                <div style={{ marginBottom: 6 }}>
                  <strong>边:</strong>{' '}
                  {dagResult.edges.map((e, i) => <span key={i} style={{ fontSize: 12 }}>{e.source} → {e.target}{e.label ? ` (${e.label})` : ''}{i < dagResult.edges.length - 1 ? '；' : ''}</span>)}
                </div>
              )}
              {dagResult.mermaid_code && (
                <div>
                  <button style={{ ...S.switchBtn, marginTop: 6, fontSize: 12 }}
                    onClick={() => setDagMermaidOpen(!dagMermaidOpen)}>
                    {dagMermaidOpen ? '收起' : '展开'} Mermaid 代码
                  </button>
                  {dagMermaidOpen && <pre style={{ ...S.pre, marginTop: 6 }}>{dagResult.mermaid_code}</pre>}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ===== 2. Counterfactual ===== */}
      {section === 'counterfactual' && (
        <div style={S.section}>
          <div style={S.sectionTitle}>反事实推理</div>
          <div style={S.row}>
            <label style={S.label}>问题</label>
            <input style={S.input} value={cfQ} onChange={e => setCfQ(e.target.value)}
              placeholder="例如: 如果2018年没有建高铁站，该区域的商业密度会怎样" />
          </div>
          <div style={S.row}>
            <label style={S.label}>空间上下文（可选）</label>
            <input style={S.input} value={cfCtx} onChange={e => setCfCtx(e.target.value)} placeholder="例如: 长三角城市群" />
          </div>
          <div style={S.row}>
            <label style={S.label}>时间范围（可选）</label>
            <input style={S.input} value={cfTime} onChange={e => setCfTime(e.target.value)} placeholder="例如: 2015-2023" />
          </div>
          <button style={{ ...S.btn, ...(loading ? S.btnDisabled : {}) }} disabled={loading}
            onClick={() => run(async () => {
              const body: Record<string, unknown> = { question: cfQ };
              if (cfCtx) body.spatial_context = cfCtx;
              if (cfTime) body.time_range = cfTime;
              setCfResult(await post<CounterfactualResult>('/api/causal/counterfactual', body));
            })}>
            {loading ? '推理中...' : '反事实推理'}
          </button>

          {cfResult && (
            <div style={S.resultBox}>
              <div style={S.sectionTitle}>推理链</div>
              {cfResult.chain.map((step, i) => (
                <div key={i} style={S.chainStep}>
                  <span style={{ ...S.badge, background: '#dbeafe', minWidth: 22, textAlign: 'center' }}>{i + 1}</span>
                  <span>{step}</span>
                </div>
              ))}
              <div style={{ marginTop: 8 }}>
                <strong>置信度:</strong> {(cfResult.confidence * 100).toFixed(0)}%
              </div>
              {cfResult.key_assumptions.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <strong>关键假设:</strong>
                  <ul style={{ margin: '4px 0 0 18px' }}>
                    {cfResult.key_assumptions.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ===== 3. Mechanism Explanation ===== */}
      {section === 'explain' && (
        <div style={S.section}>
          <div style={S.sectionTitle}>机制解释</div>
          <div style={S.row}>
            <label style={S.label}>统计结果 (JSON)</label>
            <textarea style={S.textarea} value={exStat} onChange={e => setExStat(e.target.value)}
              placeholder='粘贴 Angle A 工具输出的 JSON，例如 {"att": 0.15, "p_value": 0.02, ...}' />
          </div>
          <div style={S.row}>
            <label style={S.label}>方法</label>
            <select style={S.select} value={exMethod} onChange={e => setExMethod(e.target.value)}>
              {METHODS.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div style={S.row}>
            <label style={S.label}>补充问题（可选）</label>
            <input style={S.input} value={exQ} onChange={e => setExQ(e.target.value)} placeholder="例如: 为什么处理效应显著" />
          </div>
          <button style={{ ...S.btn, ...(loading ? S.btnDisabled : {}) }} disabled={loading}
            onClick={() => run(async () => {
              let parsed: unknown;
              try { parsed = JSON.parse(exStat); } catch { throw new Error('统计结果 JSON 格式无效'); }
              const body: Record<string, unknown> = { statistical_result: parsed, method_name: exMethod };
              if (exQ) body.question = exQ;
              setExResult(await post<ExplainResult>('/api/causal/explain', body));
            })}>
            {loading ? '解释中...' : '解释因果机制'}
          </button>

          {exResult && (
            <div style={S.resultBox}>
              <div style={{ marginBottom: 8 }}><strong>机制解释:</strong> {exResult.mechanism_explanation}</div>
              <div style={{ marginBottom: 8 }}><strong>因果路径:</strong> {exResult.causal_pathway}</div>
              {exResult.alternative_explanations.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <strong>替代解释:</strong>
                  <ul style={{ margin: '4px 0 0 18px' }}>
                    {exResult.alternative_explanations.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </div>
              )}
              {exResult.robustness_checks.length > 0 && (
                <div>
                  <strong>稳健性检查建议:</strong>
                  <ul style={{ margin: '4px 0 0 18px' }}>
                    {exResult.robustness_checks.map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ===== 4. Scenario Generator ===== */}
      {section === 'scenario' && (
        <div style={S.section}>
          <div style={S.sectionTitle}>情景生成</div>
          <div style={S.row}>
            <label style={S.label}>基准情景描述</label>
            <textarea style={S.textarea} value={scBase} onChange={e => setScBase(e.target.value)}
              placeholder="描述基准情景，例如: 某城市中心区现有商业用地比例30%，交通便利度高" />
          </div>
          <div style={S.row}>
            <label style={S.label}>生成数量 (1-5)</label>
            <input type="number" style={S.input} min={1} max={5} value={scN} onChange={e => setScN(Math.min(5, Math.max(1, Number(e.target.value))))} />
          </div>
          <div style={S.row}>
            <label style={S.label}>目标变量（可选）</label>
            <input style={S.input} value={scTarget} onChange={e => setScTarget(e.target.value)} placeholder="例如: 商业密度" />
          </div>
          <div style={S.row}>
            <label style={S.label}>约束条件（可选）</label>
            <input style={S.input} value={scConstraint} onChange={e => setScConstraint(e.target.value)} placeholder="例如: 保持总用地面积不变" />
          </div>
          <button style={{ ...S.btn, ...(loading ? S.btnDisabled : {}) }} disabled={loading}
            onClick={() => run(async () => {
              const body: Record<string, unknown> = { base_context: scBase, n_scenarios: scN };
              if (scTarget) body.target_variable = scTarget;
              if (scConstraint) body.constraint = scConstraint;
              setScResult(await post<ScenarioResult>('/api/causal/scenarios', body));
            })}>
            {loading ? '生成中...' : '生成情景'}
          </button>

          {scResult && scResult.scenarios.length > 0 && (
            <div style={{ ...S.resultBox, padding: 0, overflow: 'hidden' }}>
              <table style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>名称</th>
                    <th style={S.th}>描述</th>
                    <th style={S.th}>预期方向</th>
                    <th style={S.th}>世界模型情景</th>
                  </tr>
                </thead>
                <tbody>
                  {scResult.scenarios.map((s, i) => (
                    <tr key={i}>
                      <td style={{ ...S.td, fontWeight: 600, whiteSpace: 'nowrap' }}>{s.name}</td>
                      <td style={S.td}>{s.description}</td>
                      <td style={{ ...S.td, whiteSpace: 'nowrap' }}>{s.expected_direction}</td>
                      <td style={S.td}>{s.world_model_scenario || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Error display */}
      {error && <div style={S.error}>{error}</div>}

      {/* Empty state per section */}
      {!loading && !error && section === 'dag' && !dagResult && (
        <div style={S.empty}>输入因果问题后点击"构建因果图"，LLM 将推理出因果 DAG</div>
      )}
      {!loading && !error && section === 'counterfactual' && !cfResult && (
        <div style={S.empty}>描述反事实问题，模型将推演可能的因果链</div>
      )}
      {!loading && !error && section === 'explain' && !exResult && (
        <div style={S.empty}>粘贴统计工具输出的 JSON，LLM 将解释背后的因果机制</div>
      )}
      {!loading && !error && section === 'scenario' && !scResult && (
        <div style={S.empty}>描述基准场景，模型将生成多组对比情景供分析</div>
      )}
    </div>
  );
}
