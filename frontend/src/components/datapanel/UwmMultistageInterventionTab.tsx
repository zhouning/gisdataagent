import { useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Database,
  Eye,
  GitCompare,
  Layers3,
  ListChecks,
  Map,
  Play,
  RefreshCw,
  Route,
  ShieldCheck,
  Sigma,
  Sparkles,
  Split,
} from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type R = Record<string, any>;

declare global {
  interface Window {
    __handleMapUpdate?: (payload: any) => void;
  }
}

const rec = (value: unknown): R =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as R : {};
const arr = <T = R,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const metric = (value: unknown, digits = 9) => {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? formatNumber(parsed, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : '-';
};
const unit = (value: unknown) => {
  const text = String(value || '-');
  const parts = text.split('|');
  return parts.length >= 2 ? `${parts[0]} · ${parts[1]}` : text;
};
const ACTION_TYPES = [
  'increase_green_infrastructure',
  'traffic_emission_control',
  'add_community_service',
] as const;
const FEATURE_GROUP_KEYS = [
  'baseline',
  'actionEncoding',
  'actionIntensity',
  'targetState',
  'spatialContext',
  'candidateBasis',
  'temporalContext',
];
const UNIT_LOCATION_KEYS: Record<string, string> = {
  '975': 'tuwan',
  '793': 'shijingpo',
  '791': 'yubeilu',
};
const actionFromId = (value: unknown, labeler: (value: unknown) => string) => {
  const actionId = String(value || '');
  const actionType = ACTION_TYPES.find(type => actionId.startsWith(`${type}-`)) || '';
  return {
    label: labeler(actionType),
    target: actionId.slice(actionType.length + 1),
  };
};

export default function UwmMultistageInterventionTab() {
  const { t, i18n } = useTranslation('common');
  const actionLabel = (value: unknown) => {
    const key = String(value || '');
    return key ? t(`uwmMultistage.actions.${key}`, { defaultValue: key }) : '-';
  };
  const unitLabel = (value: unknown) => {
    const parts = String(value || '').split('|');
    const locationKey = UNIT_LOCATION_KEYS[parts[2] || ''];
    return locationKey ? t(`uwmMultistage.locations.${locationKey}`) : unit(value);
  };
  const [overview, setOverview] = useState<R>({});
  const [run, setRun] = useState<R>({});
  const [loading, setLoading] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState('');
  const [focusUnit, setFocusUnit] = useState('');
  const [horizon, setHorizon] = useState(2);
  const [beamWidth, setBeamWidth] = useState(8);
  const [gamma, setGamma] = useState(0.9);
  const [uncertaintyPenalty, setUncertaintyPenalty] = useState(0.5);
  const [actionTypes, setActionTypes] = useState<string[]>([...ACTION_TYPES]);
  const [activeScene, setActiveScene] = useState('branch');

  const loadOverview = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/multistage-intervention/overview', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(t('uwmMultistage.errors.load'));
      setOverview(payload);
      const defaults = rec(payload.default_request);
      setFocusUnit(String(defaults.focus_unit || ''));
      setHorizon(Number(defaults.horizon || 2));
      setBeamWidth(Number(defaults.beam_width || 8));
      setGamma(Number(defaults.gamma || 0.9));
      setUncertaintyPenalty(Number(defaults.uncertainty_penalty || 0.5));
      setActionTypes(arr<string>(defaults.action_types));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('uwmMultistage.errors.load'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadOverview(); }, [i18n.resolvedLanguage]);

  const localizeScene = (sceneKey: string, sceneValue: unknown) => {
    const scene = rec(sceneValue);
    if (!scene.schema) return scene;
    const localizedLayers = arr<R>(scene.layers).map((layer, index) => {
      const rawName = String(layer.name || '');
      const step = rawName.match(/a(\d+)/)?.[1];
      let name = t('uwmMultistage.map.layer', { index: formatNumber(index + 1) });
      if (sceneKey === 't0') name = t(`uwmMultistage.map.t0Layer${index + 1}`, { defaultValue: name });
      else if (sceneKey === 'branch') name = t(`uwmMultistage.map.branchLayer${index + 1}`, { defaultValue: name });
      else if (step && index % 2 === 1) name = t('uwmMultistage.map.actionPropagation', { step });
      else if (step) name = t('uwmMultistage.map.actionTarget', { step });
      return { ...layer, name };
    });
    return {
      ...scene,
      summary: { ...rec(scene.summary), title: t(`uwmMultistage.map.scenes.${sceneKey}.title`) },
      layers: localizedLayers,
      metadata: {
        ...rec(scene.metadata),
        narrative: t(`uwmMultistage.map.scenes.${sceneKey}.narrative`),
      },
    };
  };

  const showScene = (sceneKey: string, payload = run) => {
    const scene = rec(rec(payload.map_scenes)[sceneKey]);
    if (!scene.schema) return;
    setActiveScene(sceneKey);
    window.__handleMapUpdate?.(localizeScene(sceneKey, scene));
  };

  useEffect(() => {
    if (run.run_id) showScene(activeScene);
  }, [i18n.resolvedLanguage]);

  const executePlan = async () => {
    setPlanning(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/multistage-intervention/plan', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          focus_unit: focusUnit,
          neighborhood_hops: focusUnit ? 1 : 0,
          horizon,
          beam_width: beamWidth,
          gamma,
          uncertainty_penalty: uncertaintyPenalty,
          action_types: actionTypes,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(t('uwmMultistage.errors.plan'));
      setRun(payload);
      setActiveScene('branch');
      window.__handleMapUpdate?.(localizeScene('branch', rec(payload.map_scenes).branch || payload.map_update));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('uwmMultistage.errors.plan'));
    } finally {
      setPlanning(false);
    }
  };

  const toggleActionType = (value: string) => {
    setActionTypes(current => current.includes(value)
      ? current.filter(item => item !== value)
      : [...current, value]);
  };

  const foundation = rec(overview.data_foundation);
  const actionCatalog = rec(overview.action_catalog);
  const dataLayers = [
    {
      key: 'adminGeometry',
      coverage: t('uwmMultistage.data.layers.adminGeometry.coverage', {
        count: formatNumber(Number(foundation.geometry_feature_count || 0)),
      }),
      status: t(`uwmMultistage.data.status.${Number(foundation.geometry_feature_count) === 1017 ? 'complete' : 'review'}`),
    },
    {
      key: 'livabilityPanel',
      coverage: t('uwmMultistage.data.layers.livabilityPanel.coverage', {
        count: formatNumber(Number(foundation.joined_admin_count || 0)),
        total: formatNumber(1017),
      }),
      status: t(`uwmMultistage.data.status.${Number(foundation.service_matched_admin_count) === 1017 ? 'complete' : 'missing'}`),
    },
    {
      key: 'spatialRelations',
      coverage: t('uwmMultistage.data.layers.spatialRelations.coverage', {
        boundary: formatNumber(Number(foundation.boundary_edge_count || 0)),
        similarity: formatNumber(Number(foundation.similarity_edge_count || 0)),
      }),
      status: t('uwmMultistage.data.status.available'),
    },
    {
      key: 'actionCatalog',
      coverage: t('uwmMultistage.data.layers.actionCatalog.coverage', {
        templates: formatNumber(Number(actionCatalog.template_count || 3)),
        actions: formatNumber(Number(foundation.available_action_count || 0)),
      }),
      status: t('uwmMultistage.data.status.scenario'),
    },
    {
      key: 'trainingSamples',
      coverage: t('uwmMultistage.data.layers.trainingSamples.coverage', {
        count: formatNumber(Number(foundation.transition_count || 0)),
      }),
      status: t('uwmMultistage.data.status.replay'),
    },
  ];
  const actionCatalogRows = arr<R>(actionCatalog.rows);
  const simulatorSpec = rec(overview.simulator_specification);
  const inputGroups = arr<R>(simulatorSpec.input_groups);
  const inputFeatures = arr<R>(simulatorSpec.input_features);
  const outputTargets = arr<R>(simulatorSpec.output_targets);
  const architecture = rec(run.world_model_architecture);
  const scope = rec(run.planning_scope);
  const candidateSummary = rec(run.candidate_action_summary);
  const selected = rec(run.selected_sequence);
  const steps = arr<R>(selected.imagined_steps);
  const dependency = rec(run.state_dependency_diagnostic);
  const searchSummary = rec(run.planner_search_summary);
  const baselines = rec(run.baselines);
  const advantages = rec(baselines.advantages);
  const ablationRows = arr<R>(rec(baselines.validated_action_ablation_benchmark).baseline_rows);
  const training = rec(run.training_summary);
  const trainingTransparency = rec(run.training_transparency);
  const runtimeProfile = rec(run.runtime_profile);
  const rankingBefore = arr<R>(dependency.ranking_before_state_update);
  const rankingAfter = arr<R>(dependency.ranking_after_state_update);
  const rankingChanges = arr<R>(dependency.ranking_changes);
  const oldSecond = actionFromId(dependency.top_second_action_without_state_update, actionLabel);
  const selectedActions = arr<R>(selected.action_sequence);
  const newSecond = selectedActions[1] || {};
  const firstAction = selectedActions[0] || {};
  const firstPropagation = rec(steps[0]?.propagation);
  const proofPoints = run.run_id ? [
    t('uwmMultistage.decision.proofAffected', { count: formatNumber(Number(firstPropagation.affected_unit_count || 0)) }),
    t('uwmMultistage.decision.proofRanks', { count: formatNumber(Number(dependency.changed_action_rank_count || 0)) }),
    t('uwmMultistage.decision.proofSecond', {
      before: formatNumber(Number(dependency.selected_second_rank_without_state_update || 0)),
      after: formatNumber(Number(dependency.selected_second_rank_after_state_update || 0)),
    }),
    t('uwmMultistage.decision.proofEvaluated', { count: formatNumber(Number(searchSummary.evaluated_imagined_action_count || 0)) }),
  ] : [];
  const canRun = actionTypes.length > 0 && !planning;

  return (
    <div className="uwm-livability-tab uwm-multistage-tab">
      <div className="datapanel-section-header">
        <div>
          <h3><BrainCircuit size={18} />{t('uwmMultistage.header.title')}</h3>
          <p>{t('uwmMultistage.header.subtitle')}</p>
        </div>
        <button className="secondary-button" onClick={loadOverview} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} />{t('uwmMultistage.header.refresh')}
        </button>
      </div>

      {error && <div className="uwm-livability-message error">{error}</div>}

      <section className="uwm-data-readiness">
        <div className="uwm-section-lead">
          <div>
            <span><Database size={14} />{t('uwmMultistage.data.eyebrow')}</span>
            <h3>{t('uwmMultistage.data.title')}</h3>
            <p>{t('uwmMultistage.data.subtitle')}</p>
          </div>
          <div className="uwm-readiness-badge"><CheckCircle2 size={16} />{t('uwmMultistage.data.connected', {
            count: formatNumber(Number(foundation.joined_admin_count || 0)),
            total: formatNumber(1017),
          })}</div>
        </div>
        <div className="uwm-data-layer-grid">
          {dataLayers.map(row => <div className="uwm-data-layer-card" key={row.key}>
            <div><strong>{t(`uwmMultistage.data.layers.${row.key}.title`)}</strong><span>{t(`statusLabels.${row.status}`, { defaultValue: row.status })}</span></div>
            <b>{row.coverage}</b>
            <small>{t(`uwmMultistage.data.layers.${row.key}.content`)}</small>
          </div>)}
        </div>
        <p className="uwm-evidence-note"><AlertTriangle size={14} />{t('uwmMultistage.data.evidenceNote')}</p>
      </section>

      <section className="uwm-action-catalog">
        <div className="uwm-section-lead">
          <div>
            <span><ListChecks size={14} />{t('uwmMultistage.catalog.eyebrow')}</span>
            <h3>{t('uwmMultistage.catalog.title', {
              instances: formatNumber(Number(actionCatalog.instance_count || 0)),
              templates: formatNumber(Number(actionCatalog.template_count || 0)),
            })}</h3>
            <p>{t('uwmMultistage.catalog.instanceDefinition', {
              instances: formatNumber(Number(actionCatalog.instance_count || 0)),
            })}</p>
          </div>
          <div className="uwm-catalog-equation"><strong>{formatNumber(Number(actionCatalog.template_count || 3))}</strong><span>{t('uwmMultistage.catalog.templates')}</span><b>×</b><strong>{t('uwmMultistage.catalog.eligibleUnits')}</strong><b>=</b><strong>{formatNumber(Number(actionCatalog.instance_count || 0))}</strong><span>{t('uwmMultistage.catalog.instances')}</span></div>
        </div>
        <div className="uwm-action-type-grid">
          {actionCatalogRows.map(row => <article key={row.action_type}>
            <header><span>{actionLabel(row.action_type)}</span><strong>{t('uwmMultistage.catalog.instanceCount', { count: formatNumber(Number(row.instance_count || 0)) })}</strong></header>
            <p><b>{t('uwmMultistage.catalog.triggerLabel')}</b>{t(`uwmMultistage.catalog.triggers.${row.action_type}`, {
              value: String(row.trigger || '').match(/[≥≤]\s*([\d.]+)/)?.[1] || '-',
            })}</p>
            <div className="uwm-action-examples">
              <span>{t('uwmMultistage.catalog.examples')}</span>
              {arr<R>(row.examples).map(example => <small key={example.target}>{unitLabel(example.target)}</small>)}
            </div>
          </article>)}
        </div>
        <p className="uwm-field-help">{t('uwmMultistage.catalog.intensityDefinition')}</p>
      </section>

      <section className="uwm-model-blueprint">
        <div className="uwm-section-lead">
          <div>
            <span><Sigma size={14} />{t('uwmMultistage.model.eyebrow')}</span>
            <h3>{t('uwmMultistage.model.title', {
              inputs: formatNumber(Number(simulatorSpec.input_dimension || 23)),
              outputs: formatNumber(Number(simulatorSpec.output_dimension || 6)),
            })}</h3>
            <p>{t('uwmMultistage.model.scopeNote')}</p>
          </div>
          <div className="uwm-model-formula">{simulatorSpec.formula || 'ŷ = x · W'}</div>
        </div>
        <div className="uwm-io-flow">
          <div className="uwm-io-column">
            <header><span>{t('uwmMultistage.model.inputVector')}</span><strong>{t('uwmMultistage.model.dimensions', { count: formatNumber(Number(simulatorSpec.input_dimension || 23)) })}</strong></header>
            <div className="uwm-feature-groups">
              {inputGroups.map((group, index) => <div key={group.group}>
                <strong>{t(`uwmMultistage.model.groups.${FEATURE_GROUP_KEYS[index] || 'unknown'}.title`, { defaultValue: String(group.group) })}</strong><b>{t('uwmMultistage.model.dimensions', { count: formatNumber(Number(group.dimension || 0)) })}</b>
                <small>{t(`uwmMultistage.model.groups.${FEATURE_GROUP_KEYS[index] || 'unknown'}.description`, { defaultValue: '' })}</small>
              </div>)}
            </div>
            <details className="uwm-vector-details">
              <summary>{t('uwmMultistage.model.showInputs', { count: formatNumber(inputFeatures.length) })}</summary>
              <div>{inputFeatures.map(feature => <span key={feature.name}><b>{t(`uwmMultistage.model.features.${feature.name}.label`, { defaultValue: String(feature.name) })}</b><small>{t(`uwmMultistage.model.features.${feature.name}.meaning`, { defaultValue: String(feature.meaning || '') })}</small></span>)}</div>
            </details>
          </div>
          <ArrowRight size={22} className="uwm-io-arrow" />
          <div className="uwm-matrix-card">
            <span>{t('uwmMultistage.model.matrix')}</span>
            <strong>{arr<number>(simulatorSpec.coefficient_matrix_shape).join(' × ')}</strong>
            <b>{t('uwmMultistage.model.coefficients', { count: formatNumber(Number(simulatorSpec.coefficient_count || 0)) })}</b>
            <small>{t('uwmMultistage.model.ridge')}</small>
          </div>
          <ArrowRight size={22} className="uwm-io-arrow" />
          <div className="uwm-io-column">
            <header><span>{t('uwmMultistage.model.outputVector')}</span><strong>{t('uwmMultistage.model.dimensions', { count: formatNumber(Number(simulatorSpec.output_dimension || 6)) })}</strong></header>
            <div className="uwm-output-list">{outputTargets.map(target => <div key={target.name}><strong>{t(`uwmMultistage.model.targets.${target.name}.label`, { defaultValue: String(target.name) })}</strong><small>{t(`uwmMultistage.model.targets.${target.name}.meaning`, { defaultValue: String(target.meaning || '') })}</small></div>)}</div>
          </div>
        </div>
        <div className="uwm-parameter-clarification"><ShieldCheck size={15} /><p><strong>{t('uwmMultistage.model.parameterCheck')}</strong>{t('uwmMultistage.model.parameterExplanation')}</p></div>
        <p className="uwm-field-help">{t('uwmMultistage.model.trainingMethod')}</p>
      </section>

      <div className="uwm-world-loop">
        <div><span>1</span><strong>{t('uwmMultistage.loop.perceive')}</strong><small>{t('uwmMultistage.loop.perceiveDetail')}</small></div>
        <ArrowRight size={18} />
        <div><span>2</span><strong>{t('uwmMultistage.loop.imagine')}</strong><small>{t('uwmMultistage.loop.imagineDetail')}</small></div>
        <ArrowRight size={18} />
        <div><span>3</span><strong>{t('uwmMultistage.loop.replan')}</strong><small>{t('uwmMultistage.loop.replanDetail')}</small></div>
      </div>

      <div className="uwm-livability-kpi-grid">
        <div className="uwm-livability-kpi"><span>{t('uwmMultistage.kpis.states')}</span><strong>{formatNumber(Number(foundation.graph_node_count || 0))}</strong><small>{t('uwmMultistage.kpis.adminUnits')}</small></div>
        <div className="uwm-livability-kpi"><span>{t('uwmMultistage.kpis.relations')}</span><strong>{formatNumber(Number(foundation.graph_edge_count || 0))}</strong><small>{t('uwmMultistage.kpis.graphEdges')}</small></div>
        <div className="uwm-livability-kpi"><span>{t('uwmMultistage.kpis.candidates')}</span><strong>{formatNumber(Number(foundation.available_action_count || 0))}</strong><small>{t('uwmMultistage.kpis.candidateDetail', { count: formatNumber(Number(actionCatalog.template_count || 3)) })}</small></div>
        <div className="uwm-livability-kpi"><span>{t('uwmMultistage.kpis.experience')}</span><strong>{formatNumber(Number(foundation.transition_count || 0))}</strong><small>{t('uwmMultistage.kpis.transitions')}</small></div>
      </div>

      <div className="uwm-multistage-controls">
        <div className="uwm-livability-panel">
          <div className="uwm-livability-panel-title"><Layers3 size={15} /><strong>{t('uwmMultistage.controls.sceneTitle')}</strong></div>
          <label>{t('uwmMultistage.controls.scope')}
            <select
              value={focusUnit ? 'reference_scene' : 'full_admin'}
              onChange={event => setFocusUnit(
                event.target.value === 'reference_scene'
                  ? String(rec(overview.default_request).focus_unit || '')
                  : '',
              )}
            >
              <option value="reference_scene">{t('uwmMultistage.controls.referenceScene')}</option>
              <option value="full_admin">{t('uwmMultistage.controls.fullAdmin')}</option>
            </select>
          </label>
          <p className="uwm-field-help">{t('uwmMultistage.controls.scopeHelp')}</p>
          <div className="uwm-action-checkboxes">
            {ACTION_TYPES.map(value => (
              <label key={value}>
                <input type="checkbox" checked={actionTypes.includes(value)} onChange={() => toggleActionType(value)} />{actionLabel(value)}
              </label>
            ))}
          </div>
        </div>

        <div className="uwm-livability-panel">
          <div className="uwm-livability-panel-title"><ShieldCheck size={15} /><strong>{t('uwmMultistage.controls.parametersTitle')}</strong></div>
          <label>{t('uwmMultistage.controls.horizon')}
            <select value={horizon} onChange={event => setHorizon(Number(event.target.value))}>
              <option value={2}>{t('uwmMultistage.controls.twoSteps')}</option>
              <option value={3}>{t('uwmMultistage.controls.threeSteps')}</option>
            </select>
          </label>
          <label>{t('uwmMultistage.controls.beamWidth')}
            <input type="number" min={2} max={30} value={beamWidth} onChange={event => setBeamWidth(Number(event.target.value))} />
          </label>
          <div className="uwm-compact-params">
            <label>{t('uwmMultistage.controls.gamma')}<input type="number" min={0.1} max={1} step={0.05} value={gamma} onChange={event => setGamma(Number(event.target.value))} /></label>
            <label>{t('uwmMultistage.controls.riskPenalty')}<input type="number" min={0} max={5} step={0.1} value={uncertaintyPenalty} onChange={event => setUncertaintyPenalty(Number(event.target.value))} /></label>
          </div>
          <button className="primary-button uwm-plan-button" onClick={executePlan} disabled={!canRun}>
            <Play size={15} />{planning ? t('uwmMultistage.controls.planning') : t('uwmMultistage.controls.plan')}
          </button>
        </div>
      </div>

      {!run.run_id && <div className="uwm-livability-panel necessity-panel">
        <div className="uwm-livability-panel-title"><Route size={15} /><strong>{t('uwmMultistage.necessity.title')}</strong></div>
        <p>{t('uwmMultistage.necessity.reason')}</p>
        <small>{t('uwmMultistage.necessity.detail')}</small>
      </div>}

      {run.run_id && <>
        <section className="uwm-decision-hero">
          <div className="uwm-hero-eyebrow"><Sparkles size={15} />{t('uwmMultistage.decision.eyebrow')}</div>
          <h2>{t('uwmMultistage.decision.headline')}</h2>
          <p><Trans
            i18nKey="uwmMultistage.decision.summary"
            values={{
              location: unitLabel(arr<string>(firstAction.target_units)[0]),
              action: actionLabel(firstAction.action_type),
            }}
            components={{ location: <strong />, action: <strong /> }}
          /></p>
          <div className="uwm-proof-points">
            {proofPoints.map(point => <span key={point}><CheckCircle2 size={14} />{point}</span>)}
          </div>
        </section>

        <section className="uwm-training-proof">
          <div className="uwm-training-proof-header">
            <div>
              <span>{t('uwmMultistage.training.question')}</span>
              <h3>{t('uwmMultistage.training.title')}</h3>
            </div>
            <strong>{t('uwmMultistage.training.milliseconds', { value: metric(runtimeProfile.total_ms, 1) })}</strong>
          </div>
          <div className="uwm-training-pipeline">
            <div><span>{t('uwmMultistageLabels.renderer')}</span><strong>{t('uwmMultistage.training.renderer')}</strong><small>{t('uwmMultistage.training.notTrained')}</small></div>
            <ArrowRight size={17} />
            <div className="trained-stage"><span>{t('uwmMultistageLabels.simulator')}</span><strong>{t('uwmMultistage.training.simulator')}</strong><small>{t('uwmMultistage.training.trainingRows', { count: formatNumber(Number(trainingTransparency.training_row_count || 0)) })}</small></div>
            <ArrowRight size={17} />
            <div><span>{t('uwmMultistageLabels.kernel')}</span><strong>{t('uwmMultistage.training.kernel')}</strong><small>{t('uwmMultistage.training.graphComputation')}</small></div>
            <ArrowRight size={17} />
            <div><span>{t('uwmMultistageLabels.planner')}</span><strong>{t('uwmMultistage.training.planner')}</strong><small>{t('uwmMultistage.training.imaginedActions', { count: formatNumber(Number(searchSummary.evaluated_imagined_action_count || 0)) })}</small></div>
          </div>
          <div className="uwm-training-facts">
            <div><span>{t('uwmMultistage.training.trainHoldout')}</span><strong>{formatNumber(Number(trainingTransparency.training_row_count || 0))}/{formatNumber(Number(trainingTransparency.holdout_row_count || 0))}</strong></div>
            <div><span>{t('uwmMultistage.training.inputOutput')}</span><strong>{t('uwmMultistage.training.dimensionFlow', {
              inputs: formatNumber(Number(trainingTransparency.feature_count || 0)),
              outputs: formatNumber(Number(trainingTransparency.target_count || 0)),
            })}</strong></div>
            <div><span>{t('uwmMultistage.training.modelCoefficients')}</span><strong>{formatNumber(Number(trainingTransparency.coefficient_count || 0))}</strong></div>
            <div><span>{t('uwmMultistage.training.duration')}</span><strong>{t('uwmMultistage.training.milliseconds', { value: metric(runtimeProfile.dynamics_training_ms, 1) })}</strong></div>
          </div>
          <p>{t('uwmMultistage.training.whySeconds')}</p>
          <p className="uwm-model-level"><strong>{t('uwmMultistage.training.modelLevelLabel')}</strong>{t('uwmMultistage.training.modelLevel')}</p>
          <p><strong>{t('uwmMultistage.training.productionLabel')}</strong>{t('uwmMultistage.training.productionRecommendation')}</p>
        </section>

        <div className="uwm-map-story-controls">
          <strong><Map size={15} />{t('uwmMultistage.map.controlsTitle')}</strong>
          <div>
            {[
              ['t0', 'current'],
              ['t1', 'firstPropagation'],
              ['branch', 'secondBranch'],
              ['t2', 'finalTrajectory'],
            ].map(([key, labelKey], index) => <button
              key={key}
              className={activeScene === key ? 'primary-button' : 'secondary-button'}
              onClick={() => showScene(key)}
            ><Eye size={13} />{formatNumber(index + 1)} {t(`uwmMultistage.map.buttons.${labelKey}`)}</button>)}
          </div>
          <small>{t(`uwmMultistage.map.scenes.${activeScene}.narrative`)}</small>
        </div>

        <div className="uwm-future-branch">
          <div className="uwm-future-card baseline-future">
            <div className="uwm-future-tag"><Split size={15} />{t('uwmMultistage.future.withoutUpdate')}</div>
            <div className="uwm-future-step"><span>a1</span><strong>{actionLabel(firstAction.action_type)}</strong><small>{unitLabel(arr<string>(firstAction.target_units)[0])}</small></div>
            <ArrowRight size={22} />
            <div className="uwm-future-step"><span>a2</span><strong>{oldSecond.label}</strong><small>{unitLabel(oldSecond.target)}</small></div>
            <p>{t('uwmMultistage.future.withoutUpdateDetail')}</p>
          </div>
          <div className="uwm-branch-divider"><span>{t('uwmMultistageLabels.vs')}</span></div>
          <div className="uwm-future-card uwm-future">
            <div className="uwm-future-tag"><BrainCircuit size={15} />{t('uwmMultistage.future.withUpdate')}</div>
            <div className="uwm-future-step"><span>a1</span><strong>{actionLabel(firstAction.action_type)}</strong><small>{unitLabel(arr<string>(firstAction.target_units)[0])}</small></div>
            <ArrowRight size={22} />
            <div className="uwm-future-step"><span>a2</span><strong>{actionLabel(newSecond.action_type)}</strong><small>{unitLabel(arr<string>(newSecond.target_units)[0])}</small></div>
            <p>{t('uwmMultistage.future.withUpdateDetail', {
              before: formatNumber(Number(dependency.selected_second_rank_without_state_update || 0)),
              after: formatNumber(Number(dependency.selected_second_rank_after_state_update || 0)),
            })}</p>
          </div>
        </div>

        <div className="uwm-livability-panel uwm-ranking-panel">
          <div className="uwm-livability-panel-title"><GitCompare size={15} /><strong>{t('uwmMultistage.ranking.title')}</strong></div>
          <div className="uwm-ranking-comparison">
            <div>
              <h4>{t('uwmMultistage.ranking.before')}</h4>
              {rankingBefore.map(row => <div className={`uwm-ranking-row ${row.rank === 1 ? 'rank-first' : ''}`} key={row.action_id}>
                <b>#{formatNumber(Number(row.rank || 0))}</b><span>{actionLabel(row.action_type)}<small>{unitLabel(row.target_unit_id)}</small></span>
              </div>)}
            </div>
            <ArrowRight className="ranking-arrow" size={24} />
            <div>
              <h4>{t('uwmMultistage.ranking.after')}</h4>
              {rankingAfter.map(row => <div className={`uwm-ranking-row ${row.rank === 1 ? 'rank-first' : ''}`} key={row.action_id}>
                <b>#{formatNumber(Number(row.rank || 0))}</b><span>{actionLabel(row.action_type)}<small>{unitLabel(row.target_unit_id)}</small></span>
              </div>)}
            </div>
          </div>
          <div className="uwm-rank-moves">
            {rankingChanges.map(row => <span key={row.action_id} className={row.rank_delta > 0 ? 'rank-up' : 'rank-down'}>
              {t('uwmMultistage.ranking.change', {
                action: actionLabel(row.action_type),
                before: formatNumber(Number(row.rank_before || 0)),
                after: formatNumber(Number(row.rank_after || 0)),
              })}
            </span>)}
          </div>
        </div>

        <div className="uwm-livability-panel uwm-search-evidence">
          <div><span>{t('uwmMultistage.search.candidates')}</span><strong>{formatNumber(Number(candidateSummary.candidate_action_count || 0))}</strong></div>
          <div><span>{t('uwmMultistage.search.evaluated')}</span><strong>{formatNumber(Number(searchSummary.evaluated_imagined_action_count || 0))}</strong></div>
          <div><span>{t('uwmMultistage.search.completed')}</span><strong>{formatNumber(Number(searchSummary.completed_sequence_count || 0))}</strong></div>
          <div><span>{t('uwmMultistage.search.retained')}</span><strong>{formatNumber(Number(searchSummary.retained_sequence_count || 0))}</strong></div>
          <p>{t('uwmMultistage.search.detail')}</p>
        </div>

        <div className="uwm-timeline">
          <div className="uwm-state-card"><span>t0</span><strong>{t('uwmMultistage.timeline.currentWorld')}</strong><small>{t('uwmMultistage.timeline.currentDetail', {
            units: formatNumber(Number(scope.allowed_unit_count || 0)),
            actions: formatNumber(Number(candidateSummary.candidate_action_count || 0)),
          })}</small></div>
          {steps.map((step, index) => {
            const action = rec(step.action);
            const propagation = rec(step.propagation);
            return <div className="uwm-step-group" key={`${action.action_id}-${index}`}>
              <div className="uwm-action-card"><span>a{formatNumber(index + 1)}</span><strong>{actionLabel(action.action_type)}</strong><small>{unitLabel(arr<string>(action.target_units)[0])}</small></div>
              <div className="uwm-state-card"><span>t{formatNumber(index + 1)}</span><strong>{t('uwmMultistage.timeline.updatedWorld')}</strong><small>{t('uwmMultistage.timeline.updatedDetail', {
                count: formatNumber(Number(propagation.neighbor_affected_unit_count || 0)),
              })}</small></div>
            </div>;
          })}
        </div>

        <details className="uwm-technical-details">
          <summary>{t('uwmMultistage.audit.expand')}</summary>
          <div className="uwm-livability-two-col">
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title"><GitCompare size={15} /><strong>{t('uwmMultistage.audit.baselines')}</strong></div>
              <div className="uwm-compare-grid">
                <div><span>{t('uwmMultistage.audit.staticAdvantage')}</span><strong>{metric(advantages.over_traditional_static)}</strong></div>
                <div><span>{t('uwmMultistage.audit.oneStepAdvantage')}</span><strong>{metric(advantages.over_one_step_greedy)}</strong></div>
                <div><span>{t('uwmMultistage.audit.noUpdateAdvantage')}</span><strong>{metric(advantages.over_multi_step_without_state_update)}</strong></div>
              </div>
            </div>
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title"><ShieldCheck size={15} /><strong>{t('uwmMultistage.audit.runAudit')}</strong></div>
              <div className="uwm-compare-grid">
                <div><span>{t('uwmMultistage.audit.runId')}</span><strong>{run.run_id}</strong></div>
                <div><span>{t('uwmMultistage.audit.retrained')}</span><strong>{t(`uwmMultistage.boolean.${Boolean(training.retrained_for_run) ? 'yes' : 'no'}`)}</strong></div>
                <div><span>{t('uwmMultistage.audit.trainHoldout')}</span><strong>{formatNumber(Number(training.train_count || 0))}/{formatNumber(Number(training.holdout_count || 0))}</strong></div>
                <div><span>{t('uwmMultistage.audit.scope')}</span><strong>{t(`uwmMultistage.scope.${String(scope.scope_mode || 'unknown')}`, { defaultValue: String(scope.scope_mode || '-') })}</strong></div>
              </div>
            </div>
          </div>
          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title"><GitCompare size={15} /><strong>{t('uwmMultistage.audit.ablation')}</strong></div>
            <div className="uwm-ablation-grid">{ablationRows.map(row => <div key={row.policy_baseline}><span>{String(row.policy_baseline)}</span><strong>{t('uwmMultistage.audit.uwmAdvantage', { value: metric(row.world_model_policy_improvement_advantage) })}</strong></div>)}</div>
          </div>
          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title"><BrainCircuit size={15} /><strong>{t('uwmMultistageLabels.architecture')}</strong></div>
            <div className="uwm-architecture-grid">{Object.keys(architecture).map(key => <div key={key}><span>{key}</span><strong>{t(`uwmMultistage.audit.architecture.${key}`, { defaultValue: key })}</strong></div>)}</div>
          </div>
          <div className="uwm-livability-panel claim-boundary-panel">
            <div className="uwm-livability-panel-title"><AlertTriangle size={15} /><strong>{t('uwmMultistage.claims.title')}</strong></div>
            <p><strong>{t('uwmMultistage.claims.allowedLabel')}</strong>{t('uwmMultistage.claims.allowed')}</p>
            <p><strong>{t('uwmMultistage.claims.evidenceLabel')}</strong>{t('uwmMultistage.claims.evidence')}</p>
            <div className="s2-chip-list">{['causal', 'permission', 'generalization', 'percentage'].map(value => <span key={value}>{t(`uwmMultistage.claims.prohibited.${value}`)}</span>)}</div>
          </div>
        </details>
      </>}
    </div>
  );
}
