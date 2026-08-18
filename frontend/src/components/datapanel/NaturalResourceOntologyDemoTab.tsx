import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import i18n, { formatNumber as localeFormatNumber, getLocaleHeaders } from '../../i18n';
import { useTranslation } from 'react-i18next';
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

const DEMO_MAP_TEXT_KEYS: Record<string, string> = {
  '和平村 · 规划变化地块': 'ontologyDemo.map.layers.hepingChangedParcels',
  '和平村 · 空间约束': 'ontologyDemo.map.layers.hepingConstraints',
  '和平村 · 建设用地管制区': 'ontologyDemo.map.layers.hepingConstructionZones',
  '斑竹村 · 规划变化地块': 'ontologyDemo.map.layers.banzhuChangedParcels',
  '辅助预审结果': 'ontologyDemo.map.legends.preReview',
  '已注册空间约束': 'ontologyDemo.map.legends.registeredConstraints',
  '建设用地管制区': 'ontologyDemo.map.legends.constructionZones',
  '本体识别的转换过程': 'ontologyDemo.map.legends.ontologyTransitions',
  '空间冲突': 'ontologyDemo.statuses.spatialConflict.label',
  '材料待补': 'ontologyDemo.statuses.materialMissing.label',
  '条件复核': 'ontologyDemo.statuses.conditionReview.label',
  '初筛通过': 'ontologyDemo.statuses.screenedPass.label',
  '禁止/保护性约束': 'ontologyDemo.map.categories.protectiveConstraint',
  '条件性约束': 'ontologyDemo.map.categories.conditionalConstraint',
  '允许建设区': 'ontologyDemo.map.categories.allowedConstruction',
  '有条件建设区': 'ontologyDemo.map.categories.conditionalConstruction',
  '限制建设区': 'ontologyDemo.map.categories.restrictedConstruction',
  '禁止建设区': 'ontologyDemo.map.categories.prohibitedConstruction',
  '地块': 'ontologyDemo.labels.parcel',
  '规划前': 'ontologyDemo.map.fields.beforePlanning',
  '规划后': 'ontologyDemo.map.fields.afterPlanning',
  '本体过程': 'ontologyDemo.labels.process',
  '面积(公顷)': 'ontologyDemo.map.fields.areaHectare',
  '预审状态': 'ontologyDemo.labels.review',
  '判断依据': 'ontologyDemo.map.fields.reviewBasis',
  '约束类型': 'ontologyDemo.map.fields.constraintType',
  '名称': 'ontologyDemo.map.fields.name',
  '规则': 'ontologyDemo.map.fields.rule',
  '级别': 'ontologyDemo.map.fields.severity',
  '管制类型': 'ontologyDemo.map.fields.controlType',
  '代码': 'ontologyDemo.map.fields.code',
  '面积': 'ontologyDemo.map.fields.area',
  '源状态': 'ontologyDemo.labels.sourceState',
  '目标状态': 'ontologyDemo.labels.targetState',
  '转换过程': 'ontologyDemo.labels.transition',
  '农业结构调整': 'ontologyDemo.processes.agriculturalAdjustment.label',
  '建设占用': 'ontologyDemo.processes.constructionOccupation.label',
  '土地复垦': 'ontologyDemo.processes.landReclamation.label',
  '土地整治': 'ontologyDemo.processes.landRemediation.label',
  '土地利用转换': 'ontologyDemo.processes.landConversion.label',
};

function localizeDemoMapPayload(payload: MapPayload): MapPayload {
  const text = (value: unknown) => {
    const raw = String(value ?? '');
    const key = DEMO_MAP_TEXT_KEYS[raw];
    return key ? i18n.t(key, { defaultValue: raw }) : raw;
  };
  return {
    ...payload,
    layers: payload.layers.map((layer) => ({
      ...layer,
      name: text(layer.name),
      legend_title: layer.legend_title ? text(layer.legend_title) : layer.legend_title,
      category_labels: Object.fromEntries(
        Object.entries(layer.category_labels || layer.category_colors || layer.style_map || {})
          .map(([key, value]) => [key, text(layer.category_labels?.[key] || key)]),
      ),
      tooltip_labels: layer.tooltip_labels
        ? Object.fromEntries(Object.entries(layer.tooltip_labels).map(([key, value]) => [key, text(value)]))
        : layer.tooltip_labels,
    })),
  };
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: { ...getLocaleHeaders(), ...(init?.headers || {}) },
  });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
  return payload as T;
}

function sourceLabel(namespace: string, value: unknown, fallback = String(value ?? '')): string {
  if (!value) return fallback;
  const entries = i18n.getResource('zh-CN', 'common', `ontologyDemo.${namespace}`) as Record<string, { sourceName?: string; label?: string }> | undefined;
  const entry = Object.entries(entries || {}).find(([, item]) => item?.sourceName === value);
  return entry ? i18n.t(`ontologyDemo.${namespace}.${entry[0]}.label`, { defaultValue: fallback }) : fallback;
}

function sourceKey(namespace: string, value: unknown, fallback = ''): string {
  const entries = i18n.getResource('zh-CN', 'common', `ontologyDemo.${namespace}`) as Record<string, { sourceName?: string }> | undefined;
  return Object.entries(entries || {}).find(([, item]) => item?.sourceName === value)?.[0] || fallback;
}

const formatNumber = (value: number, digits = 0) => localeFormatNumber(value || 0, {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits,
});

function statusLabel(value: unknown, fallback = String(value ?? '')) { return sourceLabel('statuses', value, fallback); }
function processLabel(value: unknown, fallback = String(value ?? '')) { return sourceLabel('processes', value, fallback); }
function landUseLabel(value: unknown, fallback = String(value ?? '')) { return sourceLabel('landUse', value, fallback); }
function directionLabel(value: unknown, fallback = String(value ?? '')) { return sourceLabel('directions', value, fallback); }

function statusCount(scenario: Scenario | null, key: string): number {
  const entries = i18n.getResource('zh-CN', 'common', 'ontologyDemo.statuses') as Record<string, { sourceName?: string }> | undefined;
  const sourceName = entries?.[key]?.sourceName;
  return Number((scenario?.review_status_counts || {})[sourceName || key] || 0);
}

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
  const { t, i18n: localeI18n } = useTranslation('common');
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
    const localized = localizeDemoMapPayload(payload);
    (window as any).__handleMapUpdate?.({ layers: localized.layers, center, zoom });
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
      setMessage(error instanceof Error ? error.message : t('ontologyDemo.errors.bootstrap'));
    } finally {
      setLoading(false);
    }
  }, [loadScenarioMap, t, localeI18n.resolvedLanguage]);

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
        setMessage(error instanceof Error ? error.message : t('ontologyDemo.errors.scenario'));
      }
    };
    window.addEventListener('gda-workspace-update', handleWorkspaceUpdate);
    const pending = (window as any).__pendingGdaWorkspaceUpdate;
    if (pending?.tab === 'ontology_demo') {
      void handleWorkspaceUpdate(new CustomEvent('gda-workspace-update', { detail: pending }));
    }
    return () => window.removeEventListener('gda-workspace-update', handleWorkspaceUpdate);
  }, [loadScenarioMap, pushMap, t, localeI18n.resolvedLanguage]);

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
      setMessage(error instanceof Error ? error.message : t('ontologyDemo.errors.map'));
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
      setMessage(error instanceof Error ? error.message : t('ontologyDemo.errors.run'));
      setRunning(false);
    }
  };

  const changedFeatures = useMemo(
    () => mapPayload?.layers?.[0]?.geojsonData?.features || [],
    [mapPayload],
  );

  const representativeParcels = useMemo(() => {
    if (scenarioId !== 'heping_review') return [];
    const priority: Record<string, number> = {};
    ['spatialConflict', 'materialMissing', 'conditionReview', 'screenedPass'].forEach((key, index) => {
      const sourceName = (i18n.getResource('zh-CN', 'common', `ontologyDemo.statuses.${key}.sourceName`) as string | undefined);
      if (sourceName) priority[sourceName] = index;
    });
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
      setMessage(error instanceof Error ? error.message : t('ontologyDemo.errors.evidence'));
    }
  };

  if (loading && !overview) {
    return <div className="nr-demo-state"><LoaderCircle className="spin" size={20} />{t('ontologyDemo.states.verifying')}</div>;
  }

  if (!overview) {
    return <div className="nr-demo-state error"><AlertTriangle size={20} />{message || t('ontologyDemo.states.unavailable')}<button onClick={loadBootstrap}>{t('ontologyDemo.actions.retry')}</button></div>;
  }

  const stats = overview.ontology.stats || {};
  const scenarioStats = scenarioId === 'heping_review'
    ? [
        [t('ontologyDemo.stats.planningParcels'), selectedScenario?.parcel_count, t('ontologyDemo.units.count')],
        [t('ontologyDemo.stats.changedParcels'), selectedScenario?.changed_count, t('ontologyDemo.units.count')],
        [t('ontologyDemo.stats.changedArea'), selectedScenario?.changed_area_ha, t('ontologyDemo.units.hectare')],
        [t('ontologyDemo.stats.constraints'), overview.overview.registered_constraints, t('ontologyDemo.units.count')],
      ]
    : [
        [t('ontologyDemo.stats.planningParcels'), selectedScenario?.parcel_count, t('ontologyDemo.units.count')],
        [t('ontologyDemo.stats.changedParcels'), selectedScenario?.changed_count, t('ontologyDemo.units.count')],
        [t('ontologyDemo.stats.changedArea'), selectedScenario?.changed_area_ha, t('ontologyDemo.units.hectare')],
        [t('ontologyDemo.stats.netAgriculturalGain'), 9.06, t('ontologyDemo.units.hectare')],
      ];

  return <div className="nr-demo-shell">
    <header className="nr-demo-header">
      <div className="nr-demo-heading">
        <span className="nr-demo-mark"><Sparkles size={17} /></span>
        <div><strong>{t('ontologyDemo.header.title')}</strong><span>{t('ontologyDemo.header.subtitle')}</span></div>
      </div>
      <div className="nr-demo-header-meta">
        <span className="nr-demo-version"><Network size={13} />Ontology {overview.ontology.version}</span>
        <a className="nr-demo-version nr-demo-okf-link" href={overview.okf.bundle_index} target="_blank" rel="noreferrer"><BookOpenCheck size={13} />OKF {overview.okf.okf_version}</a>
        <span className="nr-demo-scope"><ShieldCheck size={13} />{t('ontologyDemo.header.scope')}</span>
        <a className="nr-demo-icon-button" href="/api/ontology/demo/evidence?download=1" title={t('ontologyDemo.actions.export')} aria-label={t('ontologyDemo.actions.export')}><Download size={15} /></a>
        <button className="nr-demo-icon-button" onClick={loadBootstrap} title={t('ontologyDemo.actions.refresh')} aria-label={t('ontologyDemo.actions.refresh')}><RefreshCw size={15} /></button>
      </div>
    </header>

    <div className="nr-demo-scenario-switch" role="tablist" aria-label={t('ontologyDemo.scenarios.aria')}>
      {scenarios.map(item => <button
        key={item.id}
        className={scenarioId === item.id ? 'active' : ''}
        onClick={() => selectScenario(item.id)}
        role="tab"
        aria-selected={scenarioId === item.id}
      >
        {item.id === 'heping_review' ? <ShieldAlert size={15} /> : <GitCompareArrows size={15} />}
        {t(`ontologyDemo.scenarios.${item.id}.label`)}
      </button>)}
    </div>

    {message && <div className="nr-demo-message"><AlertTriangle size={15} />{message}</div>}

    <section className="nr-demo-question">
      <div><span>{t('ontologyDemo.question.label')}</span><strong>{selectedScenario ? t(`ontologyDemo.scenarios.${selectedScenario.id}.question`) : ''}</strong></div>
      <button onClick={execute} disabled={running}>
        {running ? <LoaderCircle className="spin" size={16} /> : <Play size={16} fill="currentColor" />}
        {running ? t('ontologyDemo.actions.running') : run ? t('ontologyDemo.actions.rerun') : t('ontologyDemo.actions.run')}
      </button>
    </section>

    <div className="nr-demo-view-tabs" role="tablist">
      {([
        ['results', t('ontologyDemo.views.results'), SearchCheck],
        ['evidence', t('ontologyDemo.views.evidence'), Network],
        ['governance', t('ontologyDemo.views.governance'), TableProperties],
        ['coverage', t('ontologyDemo.views.coverage'), Boxes],
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
      <summary><Route size={15} /><strong>{t('ontologyDemo.runtime.title')}</strong><span>{t('ontologyDemo.runtime.subtitle')}</span><ChevronRight size={14} /></summary>
      <div className="nr-demo-kpis">
        {scenarioStats.map(([label, value, unit]) => <div key={String(label)}>
          <span>{label}</span><strong>{formatNumber(Number(value), unit === t('ontologyDemo.units.hectare') ? 2 : 0)}</strong><small>{unit}</small>
        </div>)}
      </div>
      <section className={`nr-demo-runtime ${running ? 'running' : ''}`}>
        <div className="nr-demo-section-title"><Route size={15} /><strong>{t('ontologyDemo.runtime.chainTitle')}</strong><span>{t('ontologyDemo.runtime.traceable')}</span></div>
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
    <div className="nr-demo-ready-row"><div><strong>{i18n.t('ontologyDemo.results.ready')}</strong><span>{i18n.t('ontologyDemo.results.readyDetail', { count: formatNumber(scenario?.changed_count || 0) })}</span></div><button onClick={onMap}><MapPin size={14} />{i18n.t('ontologyDemo.actions.locate')}</button></div>
  </div>;
  if (running || !run) return <div className="nr-demo-running-state"><LoaderCircle className="spin" size={22} /><strong>{i18n.t('ontologyDemo.results.running')}</strong><span>{i18n.t('ontologyDemo.results.runningDetail')}</span></div>;

  if (run.status !== 'completed' || run.attestation?.passed !== true) {
    return <div className="nr-demo-attestation-failed">
      <ShieldAlert size={22} />
      <div><strong>{i18n.t('ontologyDemo.results.attestationFailed')}</strong><span>{i18n.t('ontologyDemo.results.attestationFailedDetail')}</span></div>
    </div>;
  }

  const receiptId = String(run.execution_receipt?.receipt_id || '').replace(/^sha256:/, '').slice(0, 12);

  return <div className="nr-demo-results">
    {scenarioId === 'heping_review'
      ? <OntologyValueJourney parcel={sample} onInspect={() => representativeParcels[0] && onInspect(representativeParcels[0])} />
      : <StructureValueJourney scenario={scenario} />}
    <div className="nr-demo-headline"><CheckCircle2 size={19} /><div><span>{i18n.t('ontologyDemo.results.completed')}</span><strong>{i18n.t(`ontologyDemo.results.headline.${scenarioId}`, { changed: formatNumber(scenario?.changed_count || 0), conflicts: formatNumber(statusCount(scenario, 'spatialConflict')), missing: formatNumber(statusCount(scenario, 'materialMissing')) })}</strong></div><button onClick={onMap}><MapPin size={14} />{i18n.t('ontologyDemo.actions.map')}</button></div>
    <div className="nr-demo-attestation-pass">
      <ShieldCheck size={17} />
      <div><strong>{i18n.t('ontologyDemo.results.okfPassed')}</strong><span>{i18n.t('ontologyDemo.results.receipt', { id: receiptId || '-' })}</span></div>
      <a href={run.okf_reference?.resource} target="_blank" rel="noreferrer">{i18n.t('ontologyDemo.results.contract')}<ExternalLink size={12} /></a>
    </div>
    <div className="nr-demo-inline-kpis">
      {scenarioStats.map(([label, value, unit]) => <div key={String(label)}><span>{label}</span><strong>{formatNumber(Number(value), unit === i18n.t('ontologyDemo.units.hectare') ? 2 : 0)}<small>{unit}</small></strong></div>)}
    </div>
    <div className="nr-demo-findings">
      {run.findings.map((_finding: Row, index: number) => {
        const finding = run.findings[index] as Row;
        const Icon = STATUS_ICONS[finding.severity] || CircleDot;
        return <div key={`${finding.severity}-${index}`} className={`nr-demo-finding ${finding.severity}`}>
          <Icon size={16} /><div><strong>{i18n.t(`ontologyDemo.results.findings.${scenarioId}.${index}.title`, { count: formatNumber(index === 0 ? statusCount(scenario, 'spatialConflict') : index === 1 ? statusCount(scenario, 'materialMissing') : statusCount(scenario, 'conditionReview')) })}</strong><span>{i18n.t(`ontologyDemo.results.findings.${scenarioId}.${index}.action`)}</span></div>
        </div>;
      })}
    </div>
    {scenarioId === 'heping_review' ? <section className="nr-demo-parcel-list">
      <div className="nr-demo-list-title"><strong>{i18n.t('ontologyDemo.results.representativeParcels')}</strong><span>{i18n.t('ontologyDemo.results.sortedByRisk')}</span></div>
      <div className="nr-demo-table-wrap"><table><thead><tr><th>{i18n.t('ontologyDemo.labels.parcel')}</th><th>{i18n.t('ontologyDemo.labels.stateChange')}</th><th>{i18n.t('ontologyDemo.labels.process')}</th><th>{i18n.t('ontologyDemo.labels.review')}</th><th></th></tr></thead><tbody>
        {representativeParcels.map(feature => {
          const item = feature.properties;
          return <tr key={item.parcel_id}>
            <td><strong>{item.parcel_id}</strong><small>{formatNumber(item.area_ha, 3)} ha</small></td>
            <td><span>{landUseLabel(item.JQDLMC)}</span><ArrowRight size={12} /><span>{landUseLabel(item.GHDLMC)}</span></td>
            <td>{processLabel(item.process)}</td>
            <td><span className={`nr-demo-status status-${sourceKey('statuses', item.review_status, 'materialMissing')}`}>{statusLabel(item.review_status)}</span></td>
            <td><button title={i18n.t('ontologyDemo.actions.viewEvidence')} aria-label={i18n.t('ontologyDemo.actions.viewEvidence')} onClick={() => onInspect(feature)}><ExternalLink size={14} /></button></td>
          </tr>;
        })}
      </tbody></table></div>
    </section> : <StructureView rows={scenario?.structure_rows || []} />}
    <div className="nr-demo-disclaimer"><ShieldCheck size={14} />{i18n.t('ontologyDemo.header.scope')}</div>
  </div>;
}

function OntologyValueJourney({ parcel, pending = false, onInspect }: { parcel?: Row; pending?: boolean; onInspect: () => void }) {
  const source = landUseLabel(parcel?.JQDLMC, i18n.t('ontologyDemo.terms.dryland.label'));
  const target = landUseLabel(parcel?.GHDLMC, i18n.t('ontologyDemo.terms.ruralResidential.label'));
  const process = processLabel(parcel?.process, i18n.t('ontologyDemo.processes.constructionOccupation.label'));
  const reviewStatus = pending ? 'pending' : sourceKey('statuses', parcel?.review_status, 'materialMissing');
  const statusExplanation: Record<string, string> = {
    spatialConflict: i18n.t('ontologyDemo.statuses.spatialConflict.explanation'),
    materialMissing: i18n.t('ontologyDemo.statuses.materialMissing.explanation'),
    conditionReview: i18n.t('ontologyDemo.statuses.conditionReview.explanation'),
    screenedPass: i18n.t('ontologyDemo.statuses.screenedPass.explanation'),
    pending: i18n.t('ontologyDemo.statuses.pending.explanation'),
  };
  return <section className="nr-demo-value-journey">
    <div className="nr-demo-value-heading"><div><span>{i18n.t('ontologyDemo.valueJourney.title')}</span><strong>{i18n.t('ontologyDemo.valueJourney.subtitle')}</strong></div><small>{i18n.t('ontologyDemo.valueJourney.exampleParcel', { id: parcel?.parcel_id || i18n.t('ontologyDemo.valueJourney.sampleParcel') })}</small></div>
    <div className="nr-demo-journey-grid">
      <article className="traditional">
        <header><span>1</span><div><small>{i18n.t('ontologyDemo.valueJourney.rawData')}</small><strong>{i18n.t('ontologyDemo.valueJourney.traditionalView')}</strong></div></header>
        <dl><div><dt>BSM</dt><dd>{parcel?.parcel_id || i18n.t('ontologyDemo.valueJourney.parcelId')}</dd></div><div><dt>JQDLMC</dt><dd>{source}</dd></div><div><dt>GHDLMC</dt><dd>{target}</dd></div></dl>
        <p>{i18n.t('ontologyDemo.valueJourney.rawDetail')}</p>
      </article>
      <ArrowRight className="nr-demo-journey-arrow" size={18} />
      <article className="semantic">
        <header><span>2</span><div><small>{i18n.t('ontologyDemo.valueJourney.ontologyExplanation')}</small><strong>{i18n.t('ontologyDemo.valueJourney.whatHappened')}</strong></div></header>
        <div className="nr-demo-mini-chain"><span>{i18n.t('ontologyDemo.terms.landParcel.label')}</span><ChevronRight size={12} /><span>{landUseLabel(parcel?.source_state, i18n.t('ontologyDemo.terms.cultivatedState.label'))}</span><ChevronRight size={12} /><b>{process}</b><ChevronRight size={12} /><span>{landUseLabel(parcel?.target_state, i18n.t('ontologyDemo.terms.constructionState.label'))}</span></div>
        <p><code>LandParcel</code> {i18n.t('ontologyDemo.valueJourney.ontologyDetail')}</p>
      </article>
      <ArrowRight className="nr-demo-journey-arrow" size={18} />
      <article className="decision">
        <header><span>3</span><div><small>{i18n.t('ontologyDemo.valueJourney.businessResult')}</small><strong>{i18n.t('ontologyDemo.valueJourney.nextAction')}</strong></div></header>
        <div className={`nr-demo-status status-${reviewStatus}`}>{i18n.t(`ontologyDemo.statuses.${reviewStatus}.label`)}</div>
        <p>{statusExplanation[reviewStatus]}</p>
        {!pending && <button onClick={onInspect}><Network size={13} />{i18n.t('ontologyDemo.actions.why')}</button>}
      </article>
    </div>
    <div className="nr-demo-value-contrast">
      <div><span>{i18n.t('ontologyDemo.valueJourney.withoutOntology')}</span><strong>{i18n.t('ontologyDemo.valueJourney.fieldDifference')}</strong><small>{i18n.t('ontologyDemo.valueJourney.withoutDetail')}</small></div>
      <ArrowRight size={15} />
      <div><span>{i18n.t('ontologyDemo.valueJourney.withOntology')}</span><strong>{process} → {i18n.t(`ontologyDemo.statuses.${reviewStatus}.label`)}</strong><small>{i18n.t('ontologyDemo.valueJourney.withDetail')}</small></div>
    </div>
  </section>;
}

function StructureValueJourney({ scenario }: { scenario: Scenario | null }) {
  return <section className="nr-demo-value-journey compact">
    <div className="nr-demo-value-heading"><div><span>{i18n.t('ontologyDemo.valueJourney.title')}</span><strong>{i18n.t('ontologyDemo.structureJourney.subtitle')}</strong></div></div>
    <div className="nr-demo-value-contrast">
      <div><span>{i18n.t('ontologyDemo.valueJourney.traditional')}</span><strong>{i18n.t('ontologyDemo.structureJourney.traditionalTitle')}</strong><small>{i18n.t('ontologyDemo.structureJourney.traditionalDetail')}</small></div>
      <ArrowRight size={15} />
      <div><span>{i18n.t('ontologyDemo.valueJourney.ontology')}</span><strong>{i18n.t('ontologyDemo.structureJourney.ontologyTitle', { count: formatNumber(scenario?.changed_count || 559) })}</strong><small>{i18n.t('ontologyDemo.structureJourney.ontologyDetail')}</small></div>
    </div>
  </section>;
}

function StructureView({ rows }: { rows: Row[] }) {
  const selectedKeys = new Set(['totalAgricultural', 'dryland', 'orchard', 'forest', 'pasture', 'pond', 'ruralResidential']);
  const selected = rows.filter(row => selectedKeys.has(sourceKey('structure', row.name)));
  const max = Math.max(...selected.map(row => Math.abs(row.delta_ha)), 1);
  return <section className="nr-demo-structure">
    <div className="nr-demo-list-title"><strong>{i18n.t('ontologyDemo.structure.title')}</strong><span>{i18n.t('ontologyDemo.structure.period')}</span></div>
    {selected.map(row => <div key={row.name} className="nr-demo-delta-row">
      <div><strong>{sourceLabel('structure', row.name)}</strong><span>{formatNumber(row.baseline_ha, 2)} → {formatNumber(row.target_ha, 2)} ha</span></div>
      <div className="nr-demo-delta-track"><i className={row.delta_ha >= 0 ? 'positive' : 'negative'} style={{ width: `${Math.max(5, Math.abs(row.delta_ha) / max * 100)}%` }} /></div>
      <b className={row.delta_ha >= 0 ? 'positive' : 'negative'}>{row.delta_ha > 0 ? '+' : ''}{formatNumber(row.delta_ha, 2)} <small>{directionLabel(row.direction)}</small></b>
    </div>)}
  </section>;
}

function EvidenceView({ evidence, selectedParcel, overview, run }: { evidence: Row | null; selectedParcel: Row | null; overview: OverviewPayload; run: Row | null }) {
  if (!selectedParcel || !evidence) return <div className="nr-demo-evidence-empty">
    <Network size={24} /><strong>{i18n.t('ontologyDemo.evidence.title')}</strong><span>{i18n.t('ontologyDemo.evidence.empty')}</span>
    <div className="nr-demo-ontology-facts"><span><b>{overview.ontology.stats.domain_classes}</b>{i18n.t('ontologyDemo.evidence.domainClasses')}</span><span><b>{overview.ontology.stats.mappings}</b>{i18n.t('ontologyDemo.evidence.mappings')}</span><span><b>{formatNumber(overview.ontology.stats.rdf_triples)}</b>{i18n.t('ontologyDemo.evidence.triples')}</span></div>
  </div>;
  const trace = evidence.semantic_trace;
  const props = selectedParcel.properties;
  const hits = props.evidence?.constraint_hits || [];
  return <div className="nr-demo-evidence">
    <div className="nr-demo-evidence-title"><div><span>{i18n.t('ontologyDemo.terms.landParcel.label')}</span><strong>{props.parcel_id}</strong></div><span className={`nr-demo-status status-${sourceKey('statuses', props.review_status, 'materialMissing')}`}>{statusLabel(props.review_status)}</span></div>
    <div className="nr-demo-semantic-chain">
      <div><small>{i18n.t('ontologyDemo.labels.sourceState')}</small><strong>{landUseLabel(trace.source_state.label)}</strong><span>{landUseLabel(trace.source_state.source_value)}</span><code>{trace.source_state.class}</code></div>
      <ArrowRight size={16} />
      <div className="process"><small>{i18n.t('ontologyDemo.labels.transition')}</small><strong>{processLabel(trace.transition.label)}</strong><span>affectsParcel</span><code>{trace.transition.class}</code></div>
      <ArrowRight size={16} />
      <div><small>{i18n.t('ontologyDemo.labels.targetState')}</small><strong>{landUseLabel(trace.target_state.label)}</strong><span>{landUseLabel(trace.target_state.source_value)}</span><code>{trace.target_state.class}</code></div>
    </div>
    <section className="nr-demo-evidence-block">
      <div className="nr-demo-list-title"><strong>{i18n.t('ontologyDemo.evidence.ruleHits')}</strong><span>{i18n.t('ontologyDemo.evidence.constraintCount', { count: hits.length })}</span></div>
      {hits.length ? hits.map((hit: Row) => <div className="nr-demo-hit" key={hit.layer}>
        {hit.severity === 'critical' ? <ShieldAlert size={15} /> : <AlertTriangle size={15} />}
        <div><strong>{sourceLabel('constraints', hit.label)}</strong><span>{hit.names?.join('、') || hit.rule}</span></div>
        <b>{formatNumber(hit.intersection_area_ha, 4)} ha</b>
      </div>) : <div className="nr-demo-none"><CheckCircle2 size={15} />{i18n.t('ontologyDemo.evidence.noConstraints')}</div>}
      {props.evidence?.approval_evidence === 'missing' && <div className="nr-demo-hit evidence-gap"><FileWarning size={15} /><div><strong>{i18n.t('ontologyDemo.evidence.approvalMissing')}</strong><span>ConstructionOccupation.authorizedBy → ApprovalDocument</span></div><b>{i18n.t('ontologyDemo.statuses.materialMissing.label')}</b></div>}
    </section>
    <section className="nr-demo-evidence-block">
      <div className="nr-demo-list-title"><strong>{i18n.t('ontologyDemo.evidence.fieldMappings')}</strong><span>MMFE</span></div>
      <div className="nr-demo-mapping-list">
        {(evidence.field_mappings || []).slice(0, 5).map((mapping: Row) => <div key={mapping.source}><code>{mapping.source}</code><ArrowRight size={13} /><code>{mapping.target}</code><span>{mapping.relation}</span></div>)}
      </div>
    </section>
    <div className="nr-demo-provenance"><BookOpenCheck size={15} /><div><strong>{i18n.t('ontologyDemo.evidence.versioned')}</strong><span>{i18n.t('ontologyDemo.evidence.provenance', { ontology: evidence.ontology.version, bundle: evidence.bundle.version, count: evidence.sources.length })}</span></div></div>
    {run?.attestation?.passed === true && <div className="nr-demo-attestation-pass">
      <ShieldCheck size={17} />
      <div><strong>{i18n.t('ontologyDemo.results.attestationPassed')}</strong><span>{i18n.t('ontologyDemo.results.checks', { count: run.attestation.checks?.length || 0, id: String(run.attestation.verdict_id || '').replace(/^sha256:/, '').slice(0, 12) })}</span></div>
      <a href={run.okf_reference?.resource} target="_blank" rel="noreferrer">{i18n.t('ontologyDemo.results.okfContract')}<ExternalLink size={12} /></a>
    </div>}
  </div>;
}

function GovernanceView({ governance, scenarioId }: { governance: Row | null; scenarioId: Scenario['id'] }) {
  if (!governance) return null;
  const projectGroups = Object.values(governance.projects || {}) as Row[][];
  const projects = projectGroups[scenarioId === 'heping_review' ? 0 : 1] || [];
  return <div className="nr-demo-governance">
    <section>
      <div className="nr-demo-list-title"><strong>{i18n.t('ontologyDemo.governance.qualityTitle')}</strong><span>{i18n.t('ontologyDemo.governance.checkCount', { count: governance.quality.checks.length })}</span></div>
      <div className="nr-demo-quality-grid">
        {governance.quality.checks.map((check: Row) => <div key={check.id} className={check.status}>
          {check.status === 'passed' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          <div><strong>{i18n.t(`ontologyDemo.governance.checks.${check.id}.label`, { defaultValue: check.label })}</strong><span>{check.value}</span>{check.reason && <small>{i18n.t(`ontologyDemo.governance.checks.${check.id}.reason`, { defaultValue: check.reason })}</small>}</div>
        </div>)}
      </div>
    </section>
    <section>
      <div className="nr-demo-list-title"><strong>{i18n.t('ontologyDemo.governance.projectsTitle')}</strong><span>{i18n.t('ontologyDemo.governance.projectsDetail', { count: projects.length })}</span></div>
      <div className="nr-demo-table-wrap"><table><thead><tr><th>{i18n.t('ontologyDemo.labels.project')}</th><th>{i18n.t('ontologyDemo.labels.type')}</th><th>{i18n.t('ontologyDemo.labels.landArea')}</th><th>{i18n.t('ontologyDemo.labels.cultivatedArea')}</th><th>{i18n.t('ontologyDemo.labels.link')}</th></tr></thead><tbody>
        {projects.slice(0, 16).map((project: Row) => <tr key={project.sequence}><td><strong>{project.name}</strong><small>{project.location}</small></td><td>{sourceLabel('projectTypes', project.project_type)}</td><td>{typeof project.land_area_ha === 'number' ? `${formatNumber(project.land_area_ha, 2)} ha` : '-'}</td><td>{typeof project.cultivated_land_ha === 'number' ? `${formatNumber(project.cultivated_land_ha, 2)} ha` : '-'}</td><td><span className="nr-demo-unresolved">{i18n.t('ontologyDemo.governance.unlinked')}</span></td></tr>)}
      </tbody></table></div>
    </section>
    <section>
      <div className="nr-demo-list-title"><strong>{i18n.t('ontologyDemo.governance.sourcesTitle')}</strong><span>{i18n.t('ontologyDemo.governance.sourceCount', { count: governance.sources.length })}</span></div>
      <div className="nr-demo-source-list">{governance.sources.map((source: Row) => <div key={source.relative_path}><Database size={14} /><div><strong>{source.role}</strong><span>{source.name} · {source.record_count ?? '-'} {i18n.t('ontologyDemo.units.records')}</span></div><code>{source.sha256.slice(0, 10)}</code></div>)}</div>
    </section>
  </div>;
}

function CoverageView({ governance, stats }: { governance: Row | null; stats: Row }) {
  if (!governance) return null;
  const architectureRows: [string, string, typeof Sparkles][] = [
    [i18n.t('ontologyDemo.coverage.layers.application'), i18n.t('ontologyDemo.coverage.layerDetails.application'), Sparkles],
    [i18n.t('ontologyDemo.coverage.layers.agent'), i18n.t('ontologyDemo.coverage.layerDetails.agent'), Route],
    [i18n.t('ontologyDemo.coverage.layers.semantic'), i18n.t('ontologyDemo.coverage.layerDetails.semantic', { classes: stats.domain_classes, mappings: stats.mappings }), Network],
    [i18n.t('ontologyDemo.coverage.layers.data'), i18n.t('ontologyDemo.coverage.layerDetails.data'), Database],
  ];
  return <div className="nr-demo-coverage">
    <div className="nr-demo-architecture">
      {architectureRows.map(([label, text, Icon], index) => <div key={label}><span><Icon size={16} /></span><div><strong>{label}</strong><p>{text}</p></div>{index < 3 && <i />}</div>)}
    </div>
    <section>
      <div className="nr-demo-list-title"><strong>{i18n.t('ontologyDemo.coverage.capabilityTitle')}</strong><span>{i18n.t('ontologyDemo.coverage.capabilityDetail')}</span></div>
      <div className="nr-demo-capability-grid">{governance.capability_coverage.map((item: Row, index: number) => <div key={item.capability}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{i18n.t(`ontologyDemo.coverage.capabilities.${index}.name`, { defaultValue: item.capability })}</strong><p>{i18n.t(`ontologyDemo.coverage.capabilities.${index}.evidence`, { defaultValue: item.evidence })}</p></div></div>)}</div>
    </section>
    <div className="nr-demo-boundary-note"><ShieldCheck size={16} /><div><strong>{i18n.t('ontologyDemo.coverage.boundaryTitle')}</strong><span>{i18n.t('ontologyDemo.coverage.boundary')}</span></div></div>
  </div>;
}
