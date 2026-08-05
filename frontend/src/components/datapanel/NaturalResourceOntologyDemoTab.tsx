import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, ArrowRight, BookOpenCheck, Boxes, Check, CheckCircle2,
  ChevronRight, CircleDot, Database, Download, ExternalLink, FileWarning,
  GitCompareArrows, LoaderCircle, MapPin, Network, Play, RefreshCw,
  Route, SearchCheck, ShieldAlert, ShieldCheck, Sparkles, TableProperties,
} from 'lucide-react';
import './NaturalResourceOntologyDemoTab.css';

type Row = Record<string, any>;
type ViewKey = 'results' | 'evidence' | 'governance' | 'coverage';

interface OverviewPayload {
  bundle: Row;
  ontology: Row;
  overview: Row;
  agent_plan: Row[];
  decision_scope: string;
  okf: Row;
}

interface Scenario extends Row {
  id: 'heping_review' | 'banzhu_adjustment';
  label: string;
  question: string;
  parcel_count: number;
  changed_count: number;
  changed_area_ha: number;
}

interface MapPayload {
  scenario_id: string;
  center: [number, number];
  zoom: number;
  bounds: [[number, number], [number, number]];
  layers: Row[];
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'include', ...init });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
  return payload as T;
}

const formatNumber = (value: number, digits = 0) => new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits,
}).format(value || 0);

const STATUS_ICONS: Record<string, typeof AlertTriangle> = {
  critical: ShieldAlert,
  warning: AlertTriangle,
  info: CircleDot,
};

function featureCenter(feature: Row): [number, number] | null {
  const points: [number, number][] = [];
  const visit = (value: any) => {
    if (Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') {
      points.push([value[1], value[0]]);
      return;
    }
    if (Array.isArray(value)) value.forEach(visit);
  };
  visit(feature?.geometry?.coordinates);
  if (!points.length) return null;
  const lat = points.reduce((sum, point) => sum + point[0], 0) / points.length;
  const lng = points.reduce((sum, point) => sum + point[1], 0) / points.length;
  return [lat, lng];
}

export default function NaturalResourceOntologyDemoTab() {
  const [overview, setOverview] = useState<OverviewPayload | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState<Scenario['id']>('heping_review');
  const [mapPayload, setMapPayload] = useState<MapPayload | null>(null);
  const [governance, setGovernance] = useState<Row | null>(null);
  const [run, setRun] = useState<Row | null>(null);
  const [activeStep, setActiveStep] = useState(-1);
  const [view, setView] = useState<ViewKey>('results');
  const [selectedParcel, setSelectedParcel] = useState<Row | null>(null);
  const [evidence, setEvidence] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState('');
  const timerRef = useRef<number | undefined>();

  const selectedScenario = useMemo(
    () => scenarios.find(item => item.id === scenarioId) || null,
    [scenarioId, scenarios],
  );

  const pushMap = useCallback((payload: MapPayload, center = payload.center, zoom = payload.zoom) => {
    (window as any).__handleMapUpdate?.({ layers: payload.layers, center, zoom });
  }, []);

  const loadScenarioMap = useCallback(async (nextScenario: Scenario['id']) => {
    const payload = await api<MapPayload>(`/api/ontology/demo/map?scenario_id=${nextScenario}`);
    setMapPayload(payload);
    pushMap(payload);
    return payload;
  }, [pushMap]);

  const loadBootstrap = useCallback(async () => {
    setLoading(true);
    setMessage('');
    try {
      const [overviewData, scenarioData, governanceData] = await Promise.all([
        api<OverviewPayload>('/api/ontology/demo/overview'),
        api<{ items: Scenario[] }>('/api/ontology/demo/scenarios'),
        api<Row>('/api/ontology/demo/governance'),
      ]);
      setOverview(overviewData);
      setScenarios(scenarioData.items || []);
      setGovernance(governanceData);
      await loadScenarioMap('heping_review');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '演示场景加载失败');
    } finally {
      setLoading(false);
    }
  }, [loadScenarioMap]);

  useEffect(() => {
    loadBootstrap();
    return () => window.clearInterval(timerRef.current);
  }, [loadBootstrap]);

  useEffect(() => {
    const handleWorkspaceUpdate = async (rawEvent: Event) => {
      const detail = (rawEvent as CustomEvent).detail || {};
      if (detail.tab !== 'ontology_demo') return;
      if ((window as any).__pendingGdaWorkspaceUpdate === detail) {
        delete (window as any).__pendingGdaWorkspaceUpdate;
      }
      const nextScenario = String(detail.scenario_id || 'heping_review') as Scenario['id'];
      if (!['heping_review', 'banzhu_adjustment'].includes(nextScenario)) return;
      window.clearInterval(timerRef.current);
      setScenarioId(nextScenario);
      setView((detail.view || 'results') as ViewKey);
      setSelectedParcel(null);
      setEvidence(null);
      setMessage('');
      try {
        const payload = await loadScenarioMap(nextScenario);
        if (detail.auto_run) {
          setRunning(true);
          setActiveStep(0);
          const result = await api<Row>('/api/ontology/demo/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scenario_id: nextScenario }),
          });
          setRun(result);
          setActiveStep(result.steps?.length || 6);
          setRunning(false);
          pushMap(payload);
        } else {
          setRun(null);
          setActiveStep(-1);
        }
      } catch (error) {
        setRunning(false);
        setMessage(error instanceof Error ? error.message : '本体应用场景加载失败');
      }
    };
    window.addEventListener('gda-workspace-update', handleWorkspaceUpdate);
    const pending = (window as any).__pendingGdaWorkspaceUpdate;
    if (pending?.tab === 'ontology_demo') {
      void handleWorkspaceUpdate(new CustomEvent('gda-workspace-update', { detail: pending }));
    }
    return () => window.removeEventListener('gda-workspace-update', handleWorkspaceUpdate);
  }, [loadScenarioMap, pushMap]);

  const selectScenario = async (nextScenario: Scenario['id']) => {
    if (nextScenario === scenarioId) return;
    window.clearInterval(timerRef.current);
    setScenarioId(nextScenario);
    setRun(null);
    setActiveStep(-1);
    setView('results');
    setSelectedParcel(null);
    setEvidence(null);
    setMessage('');
    try {
      await loadScenarioMap(nextScenario);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '地图加载失败');
    }
  };

  const execute = async () => {
    setRunning(true);
    setRun(null);
    setActiveStep(0);
    setView('results');
    setMessage('');
    window.clearInterval(timerRef.current);
    try {
      const result = await api<Row>('/api/ontology/demo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: scenarioId }),
      });
      let step = 0;
      timerRef.current = window.setInterval(() => {
        step += 1;
        setActiveStep(step);
        if (step >= (result.steps?.length || 6) - 1) {
          window.clearInterval(timerRef.current);
          window.setTimeout(() => {
            setRun(result);
            setRunning(false);
          }, 220);
        }
      }, 320);
      if (mapPayload) pushMap(mapPayload);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '语义分析执行失败');
      setRunning(false);
    }
  };

  const changedFeatures = useMemo(
    () => mapPayload?.layers?.[0]?.geojsonData?.features || [],
    [mapPayload],
  );

  const representativeParcels = useMemo(() => {
    if (scenarioId !== 'heping_review') return [];
    const priority: Record<string, number> = { 空间冲突: 0, 材料待补: 1, 条件复核: 2, 初筛通过: 3 };
    return [...changedFeatures]
      .sort((left, right) => {
        const lp = left.properties || {};
        const rp = right.properties || {};
        return (priority[lp.review_status] ?? 9) - (priority[rp.review_status] ?? 9)
          || Number(rp.area_ha || 0) - Number(lp.area_ha || 0);
      })
      .slice(0, 12);
  }, [changedFeatures, scenarioId]);

  const inspectParcel = async (feature: Row) => {
    setSelectedParcel(feature);
    setView('evidence');
    setEvidence(null);
    const center = featureCenter(feature);
    if (mapPayload && center) pushMap(mapPayload, center, 17);
    try {
      const parcelId = encodeURIComponent(feature.properties.parcel_id);
      setEvidence(await api<Row>(`/api/ontology/demo/evidence?parcel_id=${parcelId}`));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '证据加载失败');
    }
  };

  if (loading && !overview) {
    return <div className="nr-demo-state"><LoaderCircle className="spin" size={20} />正在核验演示包与本体版本</div>;
  }

  if (!overview) {
    return <div className="nr-demo-state error"><AlertTriangle size={20} />{message || '演示场景不可用'}<button onClick={loadBootstrap}>重试</button></div>;
  }

  const stats = overview.ontology.stats || {};
  const scenarioStats = scenarioId === 'heping_review'
    ? [
        ['规划地块', selectedScenario?.parcel_count, '个'],
        ['变化地块', selectedScenario?.changed_count, '个'],
        ['变化面积', selectedScenario?.changed_area_ha, '公顷'],
        ['约束要素', overview.overview.registered_constraints, '个'],
      ]
    : [
        ['规划地块', selectedScenario?.parcel_count, '个'],
        ['变化地块', selectedScenario?.changed_count, '个'],
        ['变化面积', selectedScenario?.changed_area_ha, '公顷'],
        ['农用地净增', 9.06, '公顷'],
      ];

  return <div className="nr-demo-shell">
    <header className="nr-demo-header">
      <div className="nr-demo-heading">
        <span className="nr-demo-mark"><Sparkles size={17} /></span>
        <div><strong>自然资源本体应用</strong><span>福禄镇村规划语义审查</span></div>
      </div>
      <div className="nr-demo-header-meta">
        <span className="nr-demo-version"><Network size={13} />Ontology {overview.ontology.version}</span>
        <a className="nr-demo-version nr-demo-okf-link" href={overview.okf.bundle_index} target="_blank" rel="noreferrer"><BookOpenCheck size={13} />OKF {overview.okf.okf_version}</a>
        <span className="nr-demo-scope"><ShieldCheck size={13} />辅助预审</span>
        <a className="nr-demo-icon-button" href="/api/ontology/demo/evidence?download=1" title="导出证据包"><Download size={15} /></a>
        <button className="nr-demo-icon-button" onClick={loadBootstrap} title="刷新"><RefreshCw size={15} /></button>
      </div>
    </header>

    <div className="nr-demo-scenario-switch" role="tablist" aria-label="演示场景">
      {scenarios.map(item => <button
        key={item.id}
        className={scenarioId === item.id ? 'active' : ''}
        onClick={() => selectScenario(item.id)}
        role="tab"
        aria-selected={scenarioId === item.id}
      >
        {item.id === 'heping_review' ? <ShieldAlert size={15} /> : <GitCompareArrows size={15} />}
        {item.label.replace(/^.*?·\s*/, '')}
      </button>)}
    </div>

    {message && <div className="nr-demo-message"><AlertTriangle size={15} />{message}</div>}

    <section className="nr-demo-question">
      <div><span>业务问题</span><strong>{selectedScenario?.question}</strong></div>
      <button onClick={execute} disabled={running}>
        {running ? <LoaderCircle className="spin" size={16} /> : <Play size={16} fill="currentColor" />}
        {running ? '正在分析' : run ? '重新执行' : '执行语义分析'}
      </button>
    </section>

    <div className="nr-demo-view-tabs" role="tablist">
      {([
        ['results', '业务结论', SearchCheck],
        ['evidence', '证据链', Network],
        ['governance', '数据治理', TableProperties],
        ['coverage', '总体架构', Boxes],
      ] as [ViewKey, string, typeof SearchCheck][]).map(([key, label, Icon]) => <button key={key} className={view === key ? 'active' : ''} onClick={() => setView(key)}><Icon size={14} />{label}</button>)}
    </div>

    <main className="nr-demo-content">
      {view === 'results' && <ResultsView
        scenario={selectedScenario}
        scenarioId={scenarioId}
        run={run}
        running={running}
        representativeParcels={representativeParcels}
        scenarioStats={scenarioStats}
        onInspect={inspectParcel}
        onMap={() => mapPayload && pushMap(mapPayload)}
      />}
      {view === 'evidence' && <EvidenceView evidence={evidence} selectedParcel={selectedParcel} overview={overview} run={run} />}
      {view === 'governance' && <GovernanceView governance={governance} scenarioId={scenarioId} />}
      {view === 'coverage' && <CoverageView governance={governance} stats={stats} />}
    </main>

    <details className="nr-demo-runtime-details" open={running}>
      <summary><Route size={15} /><strong>执行与依据</strong><span>查看智能体、MMFE、GIS 引擎和本体如何协同</span><ChevronRight size={14} /></summary>
      <div className="nr-demo-kpis">
        {scenarioStats.map(([label, value, unit]) => <div key={String(label)}>
          <span>{label}</span><strong>{formatNumber(Number(value), unit === '公顷' ? 2 : 0)}</strong><small>{unit}</small>
        </div>)}
      </div>
      <section className={`nr-demo-runtime ${running ? 'running' : ''}`}>
        <div className="nr-demo-section-title"><Route size={15} /><strong>语义分析执行链</strong><span>过程可追溯</span></div>
        <div className="nr-demo-steps">
          {overview.agent_plan.map((step, index) => <div key={step.id} className={index < activeStep || run ? 'done' : index === activeStep ? 'active' : ''}>
            <span className="nr-demo-step-index">{index < activeStep || run ? <Check size={12} /> : index + 1}</span>
            <div><strong>{step.label}</strong><small>{step.owner}</small></div>
            {index < overview.agent_plan.length - 1 && <ChevronRight className="nr-demo-step-arrow" size={13} />}
          </div>)}
        </div>
      </section>
    </details>
  </div>;
}

function ResultsView({ scenario, scenarioId, run, running, representativeParcels, scenarioStats, onInspect, onMap }: {
  scenario: Scenario | null;
  scenarioId: Scenario['id'];
  run: Row | null;
  running: boolean;
  representativeParcels: Row[];
  scenarioStats: (string | number | undefined)[][];
  onInspect: (feature: Row) => void;
  onMap: () => void;
}) {
  const sample = representativeParcels[0]?.properties;
  if (!run && !running) return <div className="nr-demo-results">
    {scenarioId === 'heping_review'
      ? <OntologyValueJourney parcel={sample} pending onInspect={() => representativeParcels[0] && onInspect(representativeParcels[0])} />
      : <StructureValueJourney scenario={scenario} />}
    <div className="nr-demo-ready-row"><div><strong>场景数据已就绪</strong><span>{scenario?.changed_count || 0} 个变化地块已加载，执行后生成业务结论和版本化证据。</span></div><button onClick={onMap}><MapPin size={14} />定位场景</button></div>
  </div>;
  if (running || !run) return <div className="nr-demo-running-state"><LoaderCircle className="spin" size={22} /><strong>正在执行语义与空间分析</strong><span>结果将绑定到本体版本和源数据证据</span></div>;

  if (run.status !== 'completed' || run.attestation?.passed !== true) {
    return <div className="nr-demo-attestation-failed">
      <ShieldAlert size={22} />
      <div><strong>执行证明未通过</strong><span>业务结论和地图结果已阻止展示。</span></div>
    </div>;
  }

  const receiptId = String(run.execution_receipt?.receipt_id || '').replace(/^sha256:/, '').slice(0, 12);

  return <div className="nr-demo-results">
    {scenarioId === 'heping_review'
      ? <OntologyValueJourney parcel={sample} onInspect={() => representativeParcels[0] && onInspect(representativeParcels[0])} />
      : <StructureValueJourney scenario={scenario} />}
    <div className="nr-demo-headline"><CheckCircle2 size={19} /><div><span>分析完成</span><strong>{run.headline}</strong></div><button onClick={onMap}><MapPin size={14} />地图</button></div>
    <div className="nr-demo-attestation-pass">
      <ShieldCheck size={17} />
      <div><strong>OKF 0.2 计算证明通过</strong><span>固定计算、输入摘要与展示结果一致 · receipt {receiptId || '-'}</span></div>
      <a href={run.okf_reference?.resource} target="_blank" rel="noreferrer">计算契约<ExternalLink size={12} /></a>
    </div>
    <div className="nr-demo-inline-kpis">
      {scenarioStats.map(([label, value, unit]) => <div key={String(label)}><span>{label}</span><strong>{formatNumber(Number(value), unit === '公顷' ? 2 : 0)}<small>{unit}</small></strong></div>)}
    </div>
    <div className="nr-demo-findings">
      {run.findings.map((finding: Row, index: number) => {
        const Icon = STATUS_ICONS[finding.severity] || CircleDot;
        return <div key={`${finding.title}-${index}`} className={`nr-demo-finding ${finding.severity}`}>
          <Icon size={16} /><div><strong>{finding.title}</strong><span>{finding.action}</span></div>
        </div>;
      })}
    </div>
    {scenarioId === 'heping_review' ? <section className="nr-demo-parcel-list">
      <div className="nr-demo-list-title"><strong>代表性地块</strong><span>按风险与面积排序</span></div>
      <div className="nr-demo-table-wrap"><table><thead><tr><th>地块</th><th>状态变化</th><th>过程</th><th>预审</th><th></th></tr></thead><tbody>
        {representativeParcels.map(feature => {
          const item = feature.properties;
          return <tr key={item.parcel_id}>
            <td><strong>{item.parcel_id.replace('和平村-', '')}</strong><small>{formatNumber(item.area_ha, 3)} ha</small></td>
            <td><span>{item.JQDLMC}</span><ArrowRight size={12} /><span>{item.GHDLMC}</span></td>
            <td>{item.process}</td>
            <td><span className={`nr-demo-status status-${item.review_status}`}>{item.review_status}</span></td>
            <td><button title="查看证据" onClick={() => onInspect(feature)}><ExternalLink size={14} /></button></td>
          </tr>;
        })}
      </tbody></table></div>
    </section> : <StructureView rows={scenario?.structure_rows || []} />}
    <div className="nr-demo-disclaimer"><ShieldCheck size={14} />{run.decision_scope}</div>
  </div>;
}

function OntologyValueJourney({ parcel, pending = false, onInspect }: { parcel?: Row; pending?: boolean; onInspect: () => void }) {
  const source = parcel?.JQDLMC || '旱地';
  const target = parcel?.GHDLMC || '村居住用地';
  const process = parcel?.process || '建设占用';
  const reviewStatus = pending ? '待分析' : (parcel?.review_status || '材料待补');
  const statusExplanation: Record<string, string> = {
    空间冲突: '命中保护性空间约束，转人工复核',
    材料待补: '建设占用缺少 authorizedBy 审批证据',
    条件复核: '命中地灾或林地条件约束，需部门协同',
    初筛通过: '未发现已注册约束和证据缺口',
    待分析: '执行后给出处置建议及完整依据',
  };
  return <section className="nr-demo-value-journey">
    <div className="nr-demo-value-heading"><div><span>本体带来的变化</span><strong>同一条地块记录，从“字段不同”到“可解释的业务判断”</strong></div><small>示例地块 {parcel?.parcel_id || '和平村规划图斑'}</small></div>
    <div className="nr-demo-journey-grid">
      <article className="traditional">
        <header><span>1</span><div><small>原始数据</small><strong>传统方式看到什么</strong></div></header>
        <dl><div><dt>BSM</dt><dd>{parcel?.parcel_id?.replace('和平村-', '') || '图斑标识'}</dd></div><div><dt>JQDLMC</dt><dd>{source}</dd></div><div><dt>GHDLMC</dt><dd>{target}</dd></div></dl>
        <p>只能发现两个字段值不同，业务含义仍依赖人工解释。</p>
      </article>
      <ArrowRight className="nr-demo-journey-arrow" size={18} />
      <article className="semantic">
        <header><span>2</span><div><small>本体解释</small><strong>这是什么、发生了什么</strong></div></header>
        <div className="nr-demo-mini-chain"><span>地块实体</span><ChevronRight size={12} /><span>{parcel?.source_state || '耕地利用状态'}</span><ChevronRight size={12} /><b>{process}</b><ChevronRight size={12} /><span>{parcel?.target_state || '建设用地利用状态'}</span></div>
        <p><code>LandParcel</code> 通过状态和过程关系连接空间约束与审批证据。</p>
      </article>
      <ArrowRight className="nr-demo-journey-arrow" size={18} />
      <article className="decision">
        <header><span>3</span><div><small>业务结果</small><strong>下一步应该做什么</strong></div></header>
        <div className={`nr-demo-status status-${reviewStatus}`}>{reviewStatus}</div>
        <p>{statusExplanation[reviewStatus]}</p>
        {!pending && <button onClick={onInspect}><Network size={13} />查看为什么</button>}
      </article>
    </div>
    <div className="nr-demo-value-contrast">
      <div><span>没有本体</span><strong>字段值不同</strong><small>结论依赖人员经验和系统定制</small></div>
      <ArrowRight size={15} />
      <div><span>使用本体</span><strong>{process} → {reviewStatus}</strong><small>对象、规则、证据和来源均可追溯</small></div>
    </div>
  </section>;
}

function StructureValueJourney({ scenario }: { scenario: Scenario | null }) {
  return <section className="nr-demo-value-journey compact">
    <div className="nr-demo-value-heading"><div><span>本体带来的变化</span><strong>让统计表中的地类变化能够回到具体地块和业务过程</strong></div></div>
    <div className="nr-demo-value-contrast">
      <div><span>传统方式</span><strong>表中农用地净增 9.06 公顷</strong><small>只有汇总数字，难以回答由哪些图斑变化形成</small></div>
      <ArrowRight size={15} />
      <div><span>本体方式</span><strong>状态统计 ↔ {scenario?.changed_count || 559} 个变化地块</strong><small>共享土地利用状态语义，可追溯到转换过程和空间对象</small></div>
    </div>
  </section>;
}

function StructureView({ rows }: { rows: Row[] }) {
  const selected = rows.filter(row => ['农用地合计', '旱地', '园地', '林地', '牧草地', '坑塘水面', '宅基地（村居住用地）'].includes(row.name));
  const max = Math.max(...selected.map(row => Math.abs(row.delta_ha)), 1);
  return <section className="nr-demo-structure">
    <div className="nr-demo-list-title"><strong>土地利用结构调整</strong><span>规划基期 → 规划目标年</span></div>
    {selected.map(row => <div key={row.name} className="nr-demo-delta-row">
      <div><strong>{row.name}</strong><span>{formatNumber(row.baseline_ha, 2)} → {formatNumber(row.target_ha, 2)} ha</span></div>
      <div className="nr-demo-delta-track"><i className={row.delta_ha >= 0 ? 'positive' : 'negative'} style={{ width: `${Math.max(5, Math.abs(row.delta_ha) / max * 100)}%` }} /></div>
      <b className={row.delta_ha >= 0 ? 'positive' : 'negative'}>{row.delta_ha > 0 ? '+' : ''}{formatNumber(row.delta_ha, 2)}</b>
    </div>)}
  </section>;
}

function EvidenceView({ evidence, selectedParcel, overview, run }: { evidence: Row | null; selectedParcel: Row | null; overview: OverviewPayload; run: Row | null }) {
  if (!selectedParcel || !evidence) return <div className="nr-demo-evidence-empty">
    <Network size={24} /><strong>语义证据链</strong><span>从分析结论中的地块进入，可查看实体、状态、过程、约束和来源。</span>
    <div className="nr-demo-ontology-facts"><span><b>{overview.ontology.stats.domain_classes}</b>领域类</span><span><b>{overview.ontology.stats.mappings}</b>映射</span><span><b>{formatNumber(overview.ontology.stats.rdf_triples)}</b>三元组</span></div>
  </div>;
  const trace = evidence.semantic_trace;
  const props = selectedParcel.properties;
  const hits = props.evidence?.constraint_hits || [];
  return <div className="nr-demo-evidence">
    <div className="nr-demo-evidence-title"><div><span>地块实体</span><strong>{props.parcel_id}</strong></div><span className={`nr-demo-status status-${props.review_status}`}>{props.review_status}</span></div>
    <div className="nr-demo-semantic-chain">
      <div><small>源状态</small><strong>{trace.source_state.label}</strong><span>{trace.source_state.source_value}</span><code>{trace.source_state.class}</code></div>
      <ArrowRight size={16} />
      <div className="process"><small>转换过程</small><strong>{trace.transition.label}</strong><span>affectsParcel</span><code>{trace.transition.class}</code></div>
      <ArrowRight size={16} />
      <div><small>目标状态</small><strong>{trace.target_state.label}</strong><span>{trace.target_state.source_value}</span><code>{trace.target_state.class}</code></div>
    </div>
    <section className="nr-demo-evidence-block">
      <div className="nr-demo-list-title"><strong>规则命中</strong><span>{hits.length} 项空间约束</span></div>
      {hits.length ? hits.map((hit: Row) => <div className="nr-demo-hit" key={hit.layer}>
        {hit.severity === 'critical' ? <ShieldAlert size={15} /> : <AlertTriangle size={15} />}
        <div><strong>{hit.label}</strong><span>{hit.names?.join('、') || hit.rule}</span></div>
        <b>{formatNumber(hit.intersection_area_ha, 4)} ha</b>
      </div>) : <div className="nr-demo-none"><CheckCircle2 size={15} />未命中已注册空间约束</div>}
      {props.evidence?.approval_evidence === 'missing' && <div className="nr-demo-hit evidence-gap"><FileWarning size={15} /><div><strong>审批文件未关联</strong><span>ConstructionOccupation.authorizedBy → ApprovalDocument</span></div><b>待补</b></div>}
    </section>
    <section className="nr-demo-evidence-block">
      <div className="nr-demo-list-title"><strong>字段到本体的映射</strong><span>MMFE</span></div>
      <div className="nr-demo-mapping-list">
        {(evidence.field_mappings || []).slice(0, 5).map((mapping: Row) => <div key={mapping.source}><code>{mapping.source}</code><ArrowRight size={13} /><code>{mapping.target}</code><span>{mapping.relation}</span></div>)}
      </div>
    </section>
    <div className="nr-demo-provenance"><BookOpenCheck size={15} /><div><strong>版本化证据</strong><span>本体 {evidence.ontology.version} · 数据包 {evidence.bundle.version} · {evidence.sources.length} 个源资产均记录 SHA-256</span></div></div>
    {run?.attestation?.passed === true && <div className="nr-demo-attestation-pass">
      <ShieldCheck size={17} />
      <div><strong>运行证明已通过</strong><span>{run.attestation.checks?.length || 0} 项确定性检查 · {String(run.attestation.verdict_id || '').replace(/^sha256:/, '').slice(0, 12)}</span></div>
      <a href={run.okf_reference?.resource} target="_blank" rel="noreferrer">OKF 契约<ExternalLink size={12} /></a>
    </div>}
  </div>;
}

function GovernanceView({ governance, scenarioId }: { governance: Row | null; scenarioId: Scenario['id'] }) {
  if (!governance) return null;
  const projects = governance.projects?.[scenarioId === 'heping_review' ? '和平村' : '斑竹村'] || [];
  return <div className="nr-demo-governance">
    <section>
      <div className="nr-demo-list-title"><strong>质量与语义治理</strong><span>{governance.quality.checks.length} 项检查</span></div>
      <div className="nr-demo-quality-grid">
        {governance.quality.checks.map((check: Row) => <div key={check.id} className={check.status}>
          {check.status === 'passed' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          <div><strong>{check.label}</strong><span>{check.value}</span>{check.reason && <small>{check.reason}</small>}</div>
        </div>)}
      </div>
    </section>
    <section>
      <div className="nr-demo-list-title"><strong>重点项目台账</strong><span>{projects.length} 项 · 空间关联待治理</span></div>
      <div className="nr-demo-table-wrap"><table><thead><tr><th>项目</th><th>类型</th><th>用地</th><th>占耕</th><th>关联</th></tr></thead><tbody>
        {projects.slice(0, 16).map((project: Row) => <tr key={project.sequence}><td><strong>{project.name}</strong><small>{project.location}</small></td><td>{project.project_type}</td><td>{typeof project.land_area_ha === 'number' ? `${formatNumber(project.land_area_ha, 2)} ha` : '-'}</td><td>{typeof project.cultivated_land_ha === 'number' ? `${formatNumber(project.cultivated_land_ha, 2)} ha` : '-'}</td><td><span className="nr-demo-unresolved">待关联</span></td></tr>)}
      </tbody></table></div>
    </section>
    <section>
      <div className="nr-demo-list-title"><strong>来源资产</strong><span>{governance.sources.length} 个</span></div>
      <div className="nr-demo-source-list">{governance.sources.map((source: Row) => <div key={source.relative_path}><Database size={14} /><div><strong>{source.role}</strong><span>{source.name} · {source.record_count ?? '-'} 条</span></div><code>{source.sha256.slice(0, 10)}</code></div>)}</div>
    </section>
  </div>;
}

function CoverageView({ governance, stats }: { governance: Row | null; stats: Row }) {
  if (!governance) return null;
  const architectureRows: [string, string, typeof Sparkles][] = [
    ['应用层', '规划审查 · 结构调整 · 跨部门协同', Sparkles],
    ['智能体层', '问题理解 · 任务规划 · 工具调用 · 证据解释', Route],
    ['语义层', `本体 ${stats.domain_classes} 类 · ${stats.mappings} 映射 · MMFE`, Network],
    ['数据层', '基础地理 · 规划地类 · 管控边界 · 项目台账', Database],
  ];
  return <div className="nr-demo-coverage">
    <div className="nr-demo-architecture">
      {architectureRows.map(([label, text, Icon], index) => <div key={label}><span><Icon size={16} /></span><div><strong>{label}</strong><p>{text}</p></div>{index < 3 && <i />}</div>)}
    </div>
    <section>
      <div className="nr-demo-list-title"><strong>数据中心能力闭环</strong><span>一个场景覆盖十类能力</span></div>
      <div className="nr-demo-capability-grid">{governance.capability_coverage.map((item: Row, index: number) => <div key={item.capability}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{item.capability}</strong><p>{item.evidence}</p></div></div>)}</div>
    </section>
    <div className="nr-demo-boundary-note"><ShieldCheck size={16} /><div><strong>职责边界</strong><span>本体定义语义与规则；MMFE 执行语义融合；GIS 引擎完成空间计算；Agent 负责理解、规划、调用和解释。</span></div></div>
  </div>;
}
