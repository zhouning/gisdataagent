import { useState } from 'react';

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

/* ---------- Domains & Methods ---------- */
const DOMAINS = [
  { value: 'urban_geography', label: '城市地理' },
  { value: 'ecological', label: '生态' },
  { value: 'agricultural', label: '农业' },
  { value: 'climate', label: '气候' },
  { value: 'general', label: '通用' },
];

const METHODS = ['PSM', 'DiD', 'ERF', 'Granger', 'GCCM', 'Causal Forest'];

type Section = 'dag' | 'counterfactual' | 'explain' | 'scenario';

/* ---------- Styles ---------- */
const S: Record<string, React.CSSProperties> = {
  section: { marginBottom: 16, borderBottom: '1px solid #eee', paddingBottom: 12 },
  sectionTitle: { fontWeight: 700, marginBottom: 8, fontSize: 14 },
  resultBox: { background: '#f5f5f5', padding: 12, borderRadius: 6, marginTop: 8, fontSize: 13, lineHeight: 1.6 },
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

/* ========== Component ========== */
export default function CausalReasoningTab() {
  const [section, setSection] = useState<Section>('dag');
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

  const run = async (fn: () => Promise<void>) => {
    setLoading(true); setError('');
    try { await fn(); } catch (e: any) { setError(e.message || '请求失败'); } finally { setLoading(false); }
  };

  /* ---------- Render ---------- */
  const tabs: { key: Section; label: string }[] = [
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
