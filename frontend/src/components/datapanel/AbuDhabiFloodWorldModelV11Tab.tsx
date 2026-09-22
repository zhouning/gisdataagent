import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Database,
  FileCode2,
  Gauge,
  GitBranch,
  Layers3,
  LockKeyhole,
  Network,
  PackageCheck,
  Search,
  ServerCog,
  ShieldCheck,
  SlidersHorizontal,
  Waves,
} from 'lucide-react';

type Provenance = 'CUSTOMER' | 'DERIVED' | 'PUBLIC_PROXY' | 'ASSUMED' | 'DEFAULT' | 'CALIBRATED' | 'MISSING';
type Impact = 'high' | 'medium' | 'low';
type StageStatus = 'ready' | 'partial' | 'blocked';

interface ParameterDefinition {
  key: string;
  technical: string;
  provenance: Provenance;
  impact: Impact;
}

interface StageDefinition {
  key: 'inventory' | 'assembly' | 'swmm' | 'anuga' | 'coupling' | 'qa';
  number: string;
  status: StageStatus;
  icon: typeof Database;
  parameters: ParameterDefinition[];
}

const provenanceKeys: Provenance[] = ['CUSTOMER', 'DERIVED', 'PUBLIC_PROXY', 'ASSUMED', 'DEFAULT', 'CALIBRATED', 'MISSING'];

const provenanceClass: Record<Provenance, string> = {
  CUSTOMER: 'customer',
  DERIVED: 'derived',
  PUBLIC_PROXY: 'proxy',
  ASSUMED: 'assumed',
  DEFAULT: 'default',
  CALIBRATED: 'calibrated',
  MISSING: 'missing',
};

const statusClass: Record<StageStatus, string> = {
  ready: 'ready',
  partial: 'partial',
  blocked: 'blocked',
};

const parameter = (key: string, technical: string, provenance: Provenance, impact: Impact): ParameterDefinition => ({
  key,
  technical,
  provenance,
  impact,
});

const stages: StageDefinition[] = [
  {
    key: 'inventory', number: '01', status: 'partial', icon: Database,
    parameters: [
      parameter('customer_network', 'network_asset_bundle', 'CUSTOMER', 'high'),
      parameter('customer_dtm', 'surface_elevation', 'CUSTOMER', 'high'),
      parameter('rainfall_event', 'rainfall_timeseries', 'PUBLIC_PROXY', 'high'),
      parameter('tide_boundary', 'outfall_stage_timeseries', 'MISSING', 'high'),
      parameter('pump_scada', 'pump_operating_state', 'MISSING', 'high'),
      parameter('water_observation', 'calibration_observations', 'MISSING', 'high'),
    ],
  },
  {
    key: 'assembly', number: '02', status: 'partial', icon: SlidersHorizontal,
    parameters: [
      parameter('catchment_count', 'subcatchment_count', 'DERIVED', 'high'),
      parameter('catchment_area', 'AREA', 'ASSUMED', 'high'),
      parameter('imperviousness', '%Imperv', 'ASSUMED', 'high'),
      parameter('catchment_width', 'Width', 'ASSUMED', 'medium'),
      parameter('catchment_slope', 'Slope', 'ASSUMED', 'high'),
      parameter('horton_rates', 'MaxRate / MinRate / Decay / DryTime', 'ASSUMED', 'high'),
      parameter('surface_roughness', 'N-Imperv / N-Perv', 'ASSUMED', 'medium'),
      parameter('pipe_roughness', 'CONDUITS.Roughness', 'ASSUMED', 'high'),
      parameter('node_max_depth', 'JUNCTIONS.MaxDepth', 'ASSUMED', 'medium'),
      parameter('outfall_type', 'OUTFALLS.Type', 'ASSUMED', 'high'),
      parameter('software_default', 'engine_defaults', 'DEFAULT', 'low'),
    ],
  },
  {
    key: 'swmm', number: '03', status: 'partial', icon: Waves,
    parameters: [
      parameter('swmm_version', 'engine_version', 'DERIVED', 'medium'),
      parameter('flow_units', 'OPTIONS.FLOW_UNITS', 'ASSUMED', 'high'),
      parameter('infiltration_method', 'OPTIONS.INFILTRATION', 'ASSUMED', 'high'),
      parameter('flow_routing', 'OPTIONS.FLOW_ROUTING', 'DEFAULT', 'medium'),
      parameter('allow_ponding', 'OPTIONS.ALLOW_PONDING', 'DEFAULT', 'high'),
      parameter('link_offsets', 'OPTIONS.LINK_OFFSETS', 'ASSUMED', 'high'),
      parameter('min_slope', 'OPTIONS.MIN_SLOPE', 'DEFAULT', 'medium'),
      parameter('routing_step', 'OPTIONS.ROUTING_STEP', 'ASSUMED', 'high'),
      parameter('report_steps', 'OPTIONS.REPORT_STEP / WET_STEP / DRY_STEP', 'ASSUMED', 'medium'),
      parameter('rain_gage', 'RAINGAGES', 'PUBLIC_PROXY', 'high'),
      parameter('subareas', 'SUBAREAS', 'ASSUMED', 'high'),
      parameter('infiltration', 'INFILTRATION', 'ASSUMED', 'high'),
      parameter('junctions', 'JUNCTIONS', 'CUSTOMER', 'high'),
      parameter('conduits', 'CONDUITS', 'DERIVED', 'high'),
      parameter('xsections', 'XSECTIONS', 'ASSUMED', 'high'),
      parameter('outfalls', 'OUTFALLS', 'ASSUMED', 'high'),
      parameter('pump_controls', 'PUMPS / CURVES / CONTROLS', 'MISSING', 'high'),
      parameter('network_size', 'JUNCTIONS / CONDUITS', 'DERIVED', 'high'),
      parameter('swmm_input', 'model_input', 'DERIVED', 'medium'),
    ],
  },
  {
    key: 'anuga', number: '04', status: 'partial', icon: Layers3,
    parameters: [
      parameter('anuga_solver', 'solver', 'DERIVED', 'medium'),
      parameter('dtm_resolution', 'elevation_source', 'CUSTOMER', 'high'),
      parameter('mesh_resolution', 'maximum_triangle_area / grid', 'ASSUMED', 'high'),
      parameter('mesh_contract', 'mesh / boundary_tags', 'DERIVED', 'high'),
      parameter('elevation_quantity', 'Quantity.elevation', 'DERIVED', 'high'),
      parameter('friction_quantity', 'Quantity.friction', 'ASSUMED', 'high'),
      parameter('initial_stage', 'Quantity.stage', 'ASSUMED', 'medium'),
      parameter('initial_momentum', 'Quantity.xmomentum / ymomentum', 'DEFAULT', 'low'),
      parameter('boundary_condition', 'set_boundary', 'ASSUMED', 'high'),
      parameter('rainfall_operator', 'Rate_operator', 'PUBLIC_PROXY', 'high'),
      parameter('anuga_time_control', 'evolve(yieldstep, finaltime)', 'ASSUMED', 'high'),
      parameter('surface_sources', 'source / sink operators', 'DERIVED', 'high'),
      parameter('anuga_output', 'domain.sww', 'DERIVED', 'medium'),
    ],
  },
  {
    key: 'coupling', number: '05', status: 'partial', icon: GitBranch,
    parameters: [
      parameter('exchange_window', 'coupling.window_seconds', 'ASSUMED', 'high'),
      parameter('exchange_format', 'coupling_receipt / exchange_stream', 'DERIVED', 'medium'),
      parameter('node_grid_mapping', 'node_to_cell_map', 'DERIVED', 'high'),
      parameter('swmm_to_anuga', 'overflow_source', 'DERIVED', 'high'),
      parameter('anuga_to_swmm', 'surface_inflow_sink', 'ASSUMED', 'high'),
      parameter('mass_balance', 'mass_balance_receipt', 'DERIVED', 'high'),
      parameter('failure_policy', 'fallback_policy', 'DEFAULT', 'medium'),
    ],
  },
  {
    key: 'qa', number: '06', status: 'blocked', icon: ShieldCheck,
    parameters: [
      parameter('calibration_gate', 'calibration_admitted', 'MISSING', 'high'),
      parameter('traditional_model_gate', 'traditional_model_admitted', 'MISSING', 'high'),
      parameter('prediction_claim', 'city_scale_prediction_claim_allowed', 'DEFAULT', 'high'),
      parameter('outputs', 'result_contract', 'DERIVED', 'medium'),
      parameter('p0_gap', 'P0_data_gaps', 'MISSING', 'high'),
      parameter('upgrade_path', 'replacement_plan', 'DERIVED', 'high'),
    ],
  },
];

const formatValue = (value: string) => value.length > 30 ? `${value.slice(0, 30)}…` : value;

function StatusBadge({ provenance, label }: { provenance: Provenance; label: string }) {
  return <span className={`abu-v11-source-badge ${provenanceClass[provenance]}`}>{label}</span>;
}

export default function AbuDhabiFloodWorldModelV11Tab() {
  const { t, i18n } = useTranslation('common');
  const [selectedStageKey, setSelectedStageKey] = useState<StageDefinition['key']>(stages[0].key);
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'ALL' | Provenance>('ALL');
  const [onlyHighImpact, setOnlyHighImpact] = useState(false);

  const tr = (key: string) => String(t(`floodV11.${key}`));
  const list = (key: string) => t(`floodV11.${key}`, { returnObjects: true }) as unknown as string[];
  const selectedStage = stages.find(stage => stage.key === selectedStageKey) || stages[0];
  const StageIcon = selectedStage.icon;

  const allParameters = useMemo(() => stages.flatMap(stage => stage.parameters), []);
  const counts = useMemo(() => allParameters.reduce<Record<string, number>>((acc, item) => {
    acc[item.provenance] = (acc[item.provenance] || 0) + 1;
    return acc;
  }, {}), [allParameters]);

  const parameterRows = useMemo(() => selectedStage.parameters.map(definition => {
    const prefix = `parameters.${definition.key}`;
    const noteKey = `floodV11.${prefix}.note`;
    return {
      ...definition,
      label: tr(`${prefix}.label`),
      value: tr(`${prefix}.value`),
      unit: tr(`${prefix}.unit`),
      source: tr(`${prefix}.source`),
      replacement: tr(`${prefix}.replacement`),
      note: i18n.exists(noteKey) ? tr(`${prefix}.note`) : '',
    };
  }), [i18n, i18n.language, selectedStage]);

  const visibleParameters = useMemo(() => parameterRows.filter(item => {
    const query = search.trim().toLowerCase();
    const matchesQuery = !query || [item.label, item.technical, item.value, item.source, item.replacement]
      .some(value => value.toLowerCase().includes(query));
    const matchesSource = sourceFilter === 'ALL' || item.provenance === sourceFilter;
    const matchesImpact = !onlyHighImpact || item.impact === 'high';
    return matchesQuery && matchesSource && matchesImpact;
  }), [onlyHighImpact, parameterRows, search, sourceFilter]);

  const stageText = (key: string, field: 'title' | 'subtitle' | 'summary' | 'status') => tr(`stages.${key}.${field}`);

  return (
    <div className="abu-v11-tab">
      <section className="abu-v11-hero">
        <div>
          <span className="abu-v11-kicker">ABU DHABI / MODEL TRANSPARENCY WORKBENCH</span>
          <h2>{tr('title')}</h2>
          <p>{tr('subtitle')}</p>
          <div className="abu-v11-hero-meta">
            <span><PackageCheck size={13} /> {tr('meta.isolated')}</span>
            <span><FileCode2 size={13} /> {tr('meta.formats')}</span>
            <span><LockKeyhole size={13} /> {tr('meta.calibration')}</span>
          </div>
        </div>
        <div className="abu-v11-hero-badge">
          <strong>{tr('badge.count')}</strong>
          <span>{tr('badge.title')}</span>
          <small>{tr('badge.previous')}</small>
        </div>
      </section>

      <section className="abu-v11-notice">
        <AlertTriangle size={17} />
        <div>
          <strong>{tr('notice.title')}</strong>
          <p>{tr('notice.body')}</p>
        </div>
      </section>

      <section className="abu-v11-metrics" aria-label={tr('metrics.registered')}>
        <div><Database size={15} /><span>{tr('metrics.skeleton')}</span><strong>238,287 / 238,350</strong><small>{tr('metrics.pipesNodes')}</small></div>
        <div><Network size={15} /><span>{tr('metrics.network')}</span><strong>146,692 / 93,669</strong><small>{tr('metrics.nodesPipes')}</small></div>
        <div><Gauge size={15} /><span>{tr('metrics.registered')}</span><strong>{allParameters.length}</strong><small>{tr('metrics.registeredUnit')}</small></div>
        <div><AlertTriangle size={15} /><span>{tr('metrics.assumed')}</span><strong className="warning">{counts.ASSUMED || 0}</strong><small>{tr('metrics.assumedUnit')}</small></div>
        <div><LockKeyhole size={15} /><span>{tr('metrics.calibration')}</span><strong className="danger">{tr('metrics.calibrationValue')}</strong><small>{tr('metrics.calibrationUnit')}</small></div>
      </section>

      <section className="abu-v11-stage-workbench">
        <aside className="abu-v11-stage-nav" aria-label={tr('nav.label')}>
          <div className="abu-v11-stage-nav-heading"><span>{tr('nav.label')}</span><small>{tr('nav.hint')}</small></div>
          {stages.map((stage, index) => {
            const Icon = stage.icon;
            return (
              <button key={stage.key} className={`abu-v11-stage-nav-item ${stage.key === selectedStageKey ? 'active' : ''}`} type="button" onClick={() => setSelectedStageKey(stage.key)}>
                <span className="abu-v11-stage-number">{stage.number}</span>
                <span className="abu-v11-stage-icon"><Icon size={15} /></span>
                <span className="abu-v11-stage-nav-copy"><strong>{stageText(stage.key, 'title')}</strong><small>{stageText(stage.key, 'subtitle')}</small></span>
                <span className={`abu-v11-stage-dot ${statusClass[stage.status]}`} />
                {index < stages.length - 1 && <span className="abu-v11-stage-connector" />}
              </button>
            );
          })}
          <div className="abu-v11-stage-nav-foot"><CircleDashed size={14} /><span>{tr('nav.foot')}</span></div>
        </aside>

        <main className="abu-v11-stage-main">
          <div className="abu-v11-stage-heading">
            <div className="abu-v11-stage-heading-icon"><StageIcon size={20} /></div>
            <div>
              <span className="abu-v11-overline">STAGE {selectedStage.number} / {tr('stage.contract')}</span>
              <h3>{stageText(selectedStage.key, 'title')}</h3>
              <p>{stageText(selectedStage.key, 'subtitle')}</p>
            </div>
            <span className={`abu-v11-stage-status ${statusClass[selectedStage.status]}`}>{stageText(selectedStage.key, 'status')}</span>
          </div>
          <div className="abu-v11-summary">{stageText(selectedStage.key, 'summary')}</div>

          <div className="abu-v11-io-grid">
            <div><span>{tr('stage.input')}</span>{list(`stages.${selectedStage.key}.inputs`).map(item => <div key={item}><ArrowRight size={12} />{item}</div>)}</div>
            <div><span>{tr('stage.output')}</span>{list(`stages.${selectedStage.key}.outputs`).map(item => <div key={item}><CheckCircle2 size={12} />{item}</div>)}</div>
          </div>

          <div className="abu-v11-parameter-toolbar">
            <div className="abu-v11-toolbar-title"><SlidersHorizontal size={15} /><strong>{tr('table.title')}</strong><small>{visibleParameters.length} / {selectedStage.parameters.length} {tr('table.countUnit')}</small></div>
            <label className="abu-v11-search"><Search size={14} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder={tr('table.search')} /></label>
            <select value={sourceFilter} onChange={event => setSourceFilter(event.target.value as 'ALL' | Provenance)} aria-label={tr('table.source')}>
              <option value="ALL">{tr('table.allSources')}</option>
              {provenanceKeys.map(key => <option key={key} value={key}>{tr(`sourceLabels.${key}`)}</option>)}
            </select>
            <label className="abu-v11-impact-filter"><input type="checkbox" checked={onlyHighImpact} onChange={event => setOnlyHighImpact(event.target.checked)} />{tr('table.highOnly')}</label>
          </div>

          <div className="abu-v11-table-wrap">
            <table className="abu-v11-parameter-table">
              <thead><tr><th>{tr('table.parameter')}</th><th>{tr('table.technical')}</th><th>{tr('table.value')}</th><th>{tr('table.source')}</th><th>{tr('table.status')}</th><th>{tr('table.impactReplacement')}</th></tr></thead>
              <tbody>
                {visibleParameters.map(item => (
                  <tr key={item.key}>
                    <td><strong>{item.label}</strong>{item.note && <small>{item.note}</small>}</td>
                    <td><code>{item.technical}</code></td>
                    <td><strong className="abu-v11-value">{formatValue(item.value)}</strong><small>{item.unit}</small></td>
                    <td><span className="abu-v11-source-text">{item.source}</span></td>
                    <td><StatusBadge provenance={item.provenance} label={tr(`sourceLabels.${item.provenance}`)} /></td>
                    <td><span className={`abu-v11-impact ${item.impact}`}>{tr(`impact.${item.impact}`)}</span><small>{item.replacement}</small></td>
                  </tr>
                ))}
                {visibleParameters.length === 0 && <tr><td className="abu-v11-empty" colSpan={6}>{tr('table.noMatch')}</td></tr>}
              </tbody>
            </table>
          </div>

          {selectedStage.key === 'inventory' && <div className="abu-v11-callout assumed"><AlertTriangle size={15} /><div><strong>{tr('callouts.gapTitle')}</strong><p>{tr('callouts.gapBody')}</p></div></div>}
          {selectedStage.key === 'coupling' && <div className="abu-v11-flow-strip">{list('couplingFlow').map((item, index) => <span key={item}>{index > 0 && <ArrowRight size={15} />}{item}</span>)}</div>}
          {selectedStage.key === 'qa' && <div className="abu-v11-callout blocked"><LockKeyhole size={15} /><div><strong>{tr('callouts.qaTitle')}</strong><p>{tr('callouts.qaBody')}</p></div></div>}
        </main>
      </section>

      <section className="abu-v11-source-summary">
        <div className="abu-v11-section-title"><ServerCog size={16} /><div><span className="abu-v11-overline">{tr('sourceSummary.overline')}</span><h3>{tr('sourceSummary.title')}</h3></div></div>
        <div className="abu-v11-source-grid">
          {provenanceKeys.map(key => <div key={key}><StatusBadge provenance={key} label={tr(`sourceLabels.${key}`)} /><strong>{counts[key] || 0}</strong><small>{tr('sourceSummary.registered')}</small></div>)}
        </div>
        <div className="abu-v11-format-grid">
          <div><FileCode2 size={16} /><div><strong>{tr('sourceSummary.swmmTitle')}</strong><p>{tr('sourceSummary.swmmBody')}</p></div></div>
          <div><Layers3 size={16} /><div><strong>{tr('sourceSummary.anugaTitle')}</strong><p>{tr('sourceSummary.anugaBody')}</p></div></div>
          <div><GitBranch size={16} /><div><strong>{tr('sourceSummary.ruleTitle')}</strong><p>{tr('sourceSummary.ruleBody')}</p></div></div>
        </div>
      </section>

      <section className="abu-v11-footer-note"><ShieldCheck size={15} /><span>{tr('footer')}</span><ChevronRight size={15} /></section>
    </div>
  );
}
