import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import i18n, { getLocale, getLocaleHeaders } from '../../i18n';
import ReactECharts from 'echarts-for-react';
import {
  AlertTriangle,
  BarChart3,
  Building2,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Database,
  FileWarning,
  Gauge,
  Home,
  Map as MapIcon,
  Play,
  RefreshCw,
  RotateCcw,
  Route,
  Scale,
  ShieldCheck,
  SlidersHorizontal,
  Users,
} from 'lucide-react';

import './PopulationHousingOptimizationTab.css';

type RecordValue = Record<string, any>;
type ViewKey = 'overview' | 'allocations' | 'audit' | 'evidence';
type PresetKey = 'balanced' | 'fiscal' | 'commute' | 'resident';
type MapMode = 'current' | 'frozen';

interface ObjectiveWeights {
  public_cost: number;
  resident_housing_cost: number;
  commute_cost: number;
  relocation_cost: number;
  unmet_penalty: number;
}

interface ResourceControls {
  budget: number;
  supply: number;
  service: number;
  relocation: number;
}

const PRESETS: Record<PresetKey, { label: string; weights: ObjectiveWeights }> = {
  balanced: {
    label: 'balanced',
    weights: {
      public_cost: 1,
      resident_housing_cost: 0.15,
      commute_cost: 0.5,
      relocation_cost: 1,
      unmet_penalty: 1,
    },
  },
  fiscal: {
    label: 'fiscal',
    weights: {
      public_cost: 1,
      resident_housing_cost: 0.05,
      commute_cost: 0.1,
      relocation_cost: 0.25,
      unmet_penalty: 1,
    },
  },
  commute: {
    label: 'commute',
    weights: {
      public_cost: 0.35,
      resident_housing_cost: 0.1,
      commute_cost: 3,
      relocation_cost: 1.5,
      unmet_penalty: 1,
    },
  },
  resident: {
    label: 'resident',
    weights: {
      public_cost: 0.2,
      resident_housing_cost: 1,
      commute_cost: 0.2,
      relocation_cost: 0.5,
      unmet_penalty: 1,
    },
  },
};

const DEFAULT_RESOURCES: ResourceControls = {
  budget: 100,
  supply: 100,
  service: 100,
  relocation: 20,
};

const COLORS = {
  primary: '#2563eb',
  green: '#16a34a',
  amber: '#d97706',
  red: '#dc2626',
};
const SOURCE_ZONE_ID_KEY = '\u7a7a\u95f4\u5355\u5143\u6807\u8bc6';
const mapProperty = (key: string) => i18n.t(`population.map.properties.${key}`);

const EVIDENCE_LABELS: Record<string, string> = {
  population_total: 'population_total',
  population_groups: 'population_groups',
  housing_capacity: 'housing_capacity',
  transport_impedance: 'transport_impedance',
  service_capacity: 'service_capacity',
  costs: 'costs',
};

const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  fitted_proxy: 'fitted_proxy',
  scenario_assumption: 'scenario_assumption',
};

const HOUSING_TYPE_LABELS: Record<string, string> = {
  standard: 'standard',
  rental: 'rental',
  accessible: 'accessible',
};

const AUDIT_CATEGORY_LABELS: Record<string, string> = {
  population_conservation: 'population_conservation',
  housing_capacity: 'housing_capacity',
  housing_activation: 'housing_activation',
  public_service_capacity: 'public_service_capacity',
  fiscal: 'fiscal',
  relocation: 'relocation',
};

const AUDIT_ID_LABELS: Record<string, string> = {
  group_balance: 'group_balance',
  housing_capacity: 'housing_capacity',
  housing_activation: 'housing_activation',
  housing_activation_lower: 'housing_activation_lower',
  service_capacity: 'service_capacity',
  public_budget: 'public_budget',
  global_relocation_cap: 'global_relocation_cap',
  group_relocation_cap: 'group_relocation_cap',
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function formatNumber(value: unknown, maximumFractionDigits = 0): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  return new Intl.NumberFormat(getLocale(), { maximumFractionDigits }).format(number);
}

function formatCost(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  if (Math.abs(number) >= 100_000_000) return `${formatNumber(number / 100_000_000, 2)} ${i18n.t('population.units.hundredMillion')}`;
  if (Math.abs(number) >= 10_000) return `${formatNumber(number / 10_000, 2)} ${i18n.t('population.units.tenThousand')}`;
  return `${formatNumber(number, 2)} ${i18n.t('population.units.unit')}`;
}

function formatCompact(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  if (Math.abs(number) >= 100_000_000) return `${formatNumber(number / 100_000_000, 1)} ${i18n.t('population.units.hundredMillionShort')}`;
  if (Math.abs(number) >= 10_000) return `${formatNumber(number / 10_000, 1)} ${i18n.t('population.units.tenThousandShort')}`;
  return formatNumber(number);
}

function deltaPercent(current: unknown, reference: unknown): number | null {
  const currentValue = Number(current);
  const referenceValue = Number(reference);
  if (!Number.isFinite(currentValue) || !Number.isFinite(referenceValue) || referenceValue === 0) {
    return null;
  }
  return ((currentValue / referenceValue) - 1) * 100;
}

function statusText(status?: string): string {
  const labels: Record<string, string> = {
    optimal: i18n.t('population.status.optimal'),
    feasible_limit_reached: i18n.t('population.status.feasible'),
    infeasible: i18n.t('population.status.infeasible'),
    limit_reached_without_solution: i18n.t('population.status.noSolution'),
  };
  return status ? labels[status] || i18n.t('population.status.unknown') : i18n.t('population.status.notRun');
}

function categoryText(category: unknown): string {
  return i18n.t(`population.auditCategories.${AUDIT_CATEGORY_LABELS[String(category || '')] || 'other'}`);
}

function constraintText(row: RecordValue, input: RecordValue): string {
  const [prefix, identity = ''] = String(row.constraint_id || '').split('::');
  const label = i18n.t(`population.auditIds.${AUDIT_ID_LABELS[prefix] || 'other'}`);
  if (!identity) return label;
  const group = (input.population_groups || []).find((item: RecordValue) => item.group_id === identity);
  if (group) return `${label}：${group.group_name}`;
  const housing = (input.housing_options || []).find((item: RecordValue) => item.housing_option_id === identity);
  if (housing) {
    const zone = (input.zones || []).find((item: RecordValue) => item.zone_id === housing.zone_id);
    return `${label}: ${zone?.zone_name || housing.zone_id} ${i18n.t(`population.housingTypes.${HOUSING_TYPE_LABELS[housing.housing_type] || 'other'}`)}`;
  }
  const zone = (input.zones || []).find((item: RecordValue) => item.zone_id === identity);
  return `${label}: ${zone?.zone_name || i18n.t('population.sceneObject')}`;
}

async function fetchJson(url: string, init?: RequestInit): Promise<RecordValue> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, credentials: 'include', headers: { ...getLocaleHeaders(), ...(init?.headers || {}) } });
  } catch {
    throw new Error(i18n.t('population.errors.connection'));
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || i18n.t('population.errors.request', { status: response.status }));
  return data;
}

function buildMapUpdate(
  context: RecordValue,
  result: RecordValue,
  profileLabel: string,
  focus?: RecordValue,
): RecordValue {
  const zones = context.zones || [];
  const zoneById = new Map<string, RecordValue>(zones.map((zone: RecordValue) => [String(zone.zone_id), zone]));
  const assigned = new Map<string, number>();
  const newUnits = new Map<string, number>();
  const service = new Map<string, number>();
  for (const row of result.assignments || []) {
    assigned.set(row.destination_zone_id, (assigned.get(row.destination_zone_id) || 0) + Number(row.households));
  }
  for (const row of result.housing_actions || []) {
    newUnits.set(row.zone_id, (newUnits.get(row.zone_id) || 0) + Number(row.new_units));
  }
  for (const row of result.service_actions || []) {
    service.set(row.zone_id, (service.get(row.zone_id) || 0) + Number(row.service_expansion));
  }

  const values = [...assigned.values()].sort((a, b) => a - b);
  const lower = values[Math.floor(values.length / 3)] || 0;
  const upper = values[Math.floor(values.length * 2 / 3)] || 0;
  const focusIds = focus ? new Set([String(focus.origin_zone_id), String(focus.destination_zone_id)]) : null;
  const boundaryFeatures = (context.boundary_geojson?.features || [])
    .filter((feature: RecordValue) => !focusIds || focusIds.has(String(feature.properties?.[SOURCE_ZONE_ID_KEY])))
    .map((feature: RecordValue) => {
      const copied = clone(feature);
      const zoneId = String(copied.properties?.[SOURCE_ZONE_ID_KEY]);
      const households = assigned.get(zoneId) || 0;
      const band = households <= lower ? 'low' : households <= upper ? 'medium' : 'high';
      copied.properties = {
        ...copied.properties,
        [mapProperty('plan')]: profileLabel,
        [mapProperty('households')]: Math.round(households),
        [mapProperty('newHousing')]: Math.round(newUnits.get(zoneId) || 0),
        [mapProperty('serviceExpansion')]: Number((service.get(zoneId) || 0).toFixed(2)),
        [mapProperty('intensity')]: i18n.t(`population.map.intensity.${band}`),
        [mapProperty('evidenceBoundary')]: i18n.t('population.map.evidenceBoundary'),
      };
      return copied;
    });

  const flowTotals = new Map<string, number>();
  for (const row of focus ? [focus] : result.assignments || []) {
    if (!row.relocated) continue;
    const key = `${row.origin_zone_id}@@${row.destination_zone_id}`;
    flowTotals.set(key, (flowTotals.get(key) || 0) + Number(row.households));
  }
  const flowFeatures = [...flowTotals.entries()].map(([key, households]) => {
    const [originId, destinationId] = key.split('@@');
    const origin = zoneById.get(originId) || {};
    const destination = zoneById.get(destinationId) || {};
    return {
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: [
          [Number(origin.centroid?.lon), Number(origin.centroid?.lat)],
          [Number(destination.centroid?.lon), Number(destination.centroid?.lat)],
        ],
      },
      properties: {
        [mapProperty('plan')]: profileLabel,
        [mapProperty('origin')]: origin.zone_name || originId,
        [mapProperty('destination')]: destination.zone_name || destinationId,
        [mapProperty('relocatedHouseholds')]: Math.round(households),
        [mapProperty('arrowMeaning')]: i18n.t('population.map.arrowMeaning'),
        [mapProperty('flowMeaning')]: i18n.t('population.map.flowMeaning'),
      },
    };
  });

  let center = context.center || [29.55, 106.55];
  let zoom = context.zoom || 11;
  if (focus) {
    const origin = zoneById.get(String(focus.origin_zone_id)) || {};
    const destination = zoneById.get(String(focus.destination_zone_id)) || {};
    center = [
      (Number(origin.centroid?.lat) + Number(destination.centroid?.lat)) / 2,
      (Number(origin.centroid?.lon) + Number(destination.centroid?.lon)) / 2,
    ];
    zoom = 12;
  }

  return {
    schema: 'map_update.v1',
    summary: {
      title: context.display?.scenario_name || i18n.t('population.title'),
      profile: profileLabel,
      status: result.status,
      zone_count: boundaryFeatures.length,
      cross_zone_flow_count: flowFeatures.length,
      claim_boundary: 'aggregate_proxy_scenario_not_policy_advice',
    },
    center,
    zoom,
    layers: [
      {
        name: `${profileLabel}${i18n.t('population.map.zoneAllocation')}`,
        type: 'categorized',
        category_column: mapProperty('intensity'),
        category_labels: { low: i18n.t('population.map.intensity.low'), medium: i18n.t('population.map.intensity.medium'), high: i18n.t('population.map.intensity.high') },
        style_map: {
          low: { fillColor: '#dbeafe', color: '#1d4ed8' },
          medium: { fillColor: '#86efac', color: '#15803d' },
          high: { fillColor: '#fbbf24', color: '#a16207' },
        },
        style: { weight: 1.5, fillOpacity: 0.58, opacity: 0.9 },
        geojsonData: { type: 'FeatureCollection', features: boundaryFeatures },
      },
      {
        name: `${profileLabel}${i18n.t('population.map.relocationFlow')}`,
        type: 'line',
        legend_title: i18n.t('population.map.flowLegend'),
        style: {
          color: '#dc2626',
          weight: focus ? 4 : 3,
          opacity: focus ? 0.92 : 0.78,
          arrowheads: true,
          arrowColor: '#dc2626',
          arrowPlacement: 0.78,
          arrowSize: focus ? 15 : 12,
        },
        geojsonData: { type: 'FeatureCollection', features: flowFeatures },
      },
    ],
    metadata: {
      boundary_match_method: context.boundary_source?.match_method,
      boundary_crs: context.boundary_source?.crs,
      focus_mode: Boolean(focus),
      flow_direction_encoding: 'arrow_points_to_destination',
      empirical_policy_optimality_claim: false,
    },
  };
}

function RangeControl({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="pho-range-control">
      <span>{label}</span>
      <output>{formatNumber(value, 2)}{suffix}</output>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function MetricDelta({ current, reference }: { current: unknown; reference: unknown }) {
  const delta = deltaPercent(current, reference);
  if (delta === null) return <small>{i18n.t('population.metricDelta.incomparable')}</small>;
  const className = Math.abs(delta) < 0.0005 ? 'neutral' : delta > 0 ? 'up' : 'down';
  return <small className={className}>{delta > 0 ? '+' : ''}{delta.toFixed(2)}% ({i18n.t('population.metricDelta.reference')})</small>;
}

export default function PopulationHousingOptimizationTab() {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<RecordValue | null>(null);
  const [baseInput, setBaseInput] = useState<RecordValue | null>(null);
  const [mapContext, setMapContext] = useState<RecordValue | null>(null);
  const [portfolio, setPortfolio] = useState<RecordValue | null>(null);
  const [referencePortfolio, setReferencePortfolio] = useState<RecordValue | null>(null);
  const [preset, setPreset] = useState<PresetKey>('balanced');
  const [weights, setWeights] = useState<ObjectiveWeights>(clone(PRESETS.balanced.weights));
  const [resources, setResources] = useState<ResourceControls>(DEFAULT_RESOURCES);
  const [activeView, setActiveView] = useState<ViewKey>('overview');
  const [mapMode, setMapMode] = useState<MapMode>('current');
  const [autoMap, setAutoMap] = useState(true);
  const [mapNotice, setMapNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [solving, setSolving] = useState(false);
  const [error, setError] = useState('');
  const [validation, setValidation] = useState<RecordValue | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const [catalogPayload, inputPayload, portfolioPayload, mapPayload] = await Promise.all([
          fetchJson('/api/uwm/population-housing/catalog'),
          fetchJson('/api/uwm/population-housing/default-input'),
          fetchJson('/api/uwm/population-housing/default-portfolio'),
          fetchJson('/api/uwm/population-housing/map-context'),
        ]);
        if (cancelled) return;
        setCatalog(catalogPayload);
        setBaseInput(inputPayload);
        setPortfolio(portfolioPayload);
        setReferencePortfolio(portfolioPayload);
        setMapContext(mapPayload);
      } catch (loadError: unknown) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : t('population.errors.unavailable'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const result = portfolio?.results?.[0] || null;
  const frozenResult = useMemo(() => {
    const rows = referencePortfolio?.results || [];
    return rows.find((row: RecordValue) => row.profile_id === 'balanced') || rows[0] || null;
  }, [referencePortfolio]);
  const reference = useMemo(() => {
    const rows = referencePortfolio?.comparison || [];
    return rows.find((row: RecordValue) => row.profile_id === 'balanced') || rows[0] || null;
  }, [referencePortfolio]);

  const applyPreset = (key: PresetKey) => {
    setPreset(key);
    setWeights(clone(PRESETS[key].weights));
  };

  const sendMap = (mode: MapMode = mapMode, focus?: RecordValue, resultOverride?: RecordValue) => {
    const target = resultOverride || (mode === 'frozen' ? frozenResult : result);
    if (!mapContext || !target || !['optimal', 'feasible_limit_reached'].includes(target.status)) return;
    const label = mode === 'frozen' ? t('population.map.frozenPlan') : t('population.map.currentPlan');
    (window as any).__handleMapUpdate?.(buildMapUpdate(mapContext, target, label, focus));
    setMapNotice(focus ? t('population.map.focused') : t('population.map.sent', { label }));
  };

  const reset = () => {
    setPreset('balanced');
    setWeights(clone(PRESETS.balanced.weights));
    setResources(DEFAULT_RESOURCES);
    setValidation(null);
    setError('');
    setElapsedMs(null);
    setPortfolio(referencePortfolio);
    setActiveView('overview');
    setMapMode('current');
    if (autoMap && frozenResult) sendMap('current', undefined, frozenResult);
  };

  const updateWeight = (field: keyof ObjectiveWeights, value: number) => {
    setPreset('balanced');
    setWeights((current) => ({ ...current, [field]: value }));
  };

  const updateResource = (field: keyof ResourceControls, value: number) => {
    setResources((current) => ({ ...current, [field]: value }));
  };

  const runScenario = async () => {
    if (!baseInput) return;
    setSolving(true);
    setError('');
    setValidation(null);
    setMapNotice('');
    const started = performance.now();
    try {
      const input = clone(baseInput);
      input.scenario_id = 'interactive-population-housing-demo';
      input.parameters.total_public_budget = Number(
        (Number(baseInput.parameters.total_public_budget) * resources.budget / 100).toFixed(6),
      );
      input.parameters.max_relocated_households_share = resources.relocation / 100;
      input.housing_options = input.housing_options.map((option: RecordValue, index: number) => ({
        ...option,
        max_new_units: Math.max(
          0,
          Math.round(Number(baseInput.housing_options[index].max_new_units) * resources.supply / 100),
        ),
      }));
      input.zones = input.zones.map((zone: RecordValue, index: number) => ({
        ...zone,
        max_service_expansion: Number(
          (Number(baseInput.zones[index].max_service_expansion) * resources.service / 100).toFixed(6),
        ),
      }));

      const validationPayload = await fetchJson('/api/uwm/population-housing/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      });
      setValidation(validationPayload);
      if (!validationPayload.valid) {
        throw new Error((validationPayload.errors || []).join('; ') || t('population.errors.validation'));
      }

      const solved = await fetchJson('/api/uwm/population-housing/solve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input, profiles: { interactive_demo: weights } }),
      });
      setPortfolio(solved);
      setElapsedMs(performance.now() - started);
      setActiveView('overview');
      setMapMode('current');
      const solvedResult = solved.results?.[0];
      if (autoMap && solvedResult && ['optimal', 'feasible_limit_reached'].includes(solvedResult.status)) {
        sendMap('current', undefined, solvedResult);
      }
    } catch (solveError: unknown) {
      setError(solveError instanceof Error ? solveError.message : t('population.errors.solve'));
    } finally {
      setSolving(false);
    }
  };

  const housingOption = useMemo(() => {
    if (!result) return {};
    const byType = new Map<string, { occupied: number; newUnits: number }>();
    for (const action of result.housing_actions || []) {
      const current = byType.get(action.housing_type) || { occupied: 0, newUnits: 0 };
      current.occupied += Number(action.occupied_units);
      current.newUnits += Number(action.new_units);
      byType.set(action.housing_type, current);
    }
    const types = [...byType.keys()];
    return {
      animationDuration: 300,
      color: [COLORS.green, COLORS.amber],
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { bottom: 0, textStyle: { fontSize: 10 } },
      grid: { left: 72, right: 14, top: 14, bottom: 36 },
      xAxis: {
        type: 'value',
        splitNumber: 3,
        axisLabel: { formatter: (value: number) => formatCompact(value), hideOverlap: true },
        splitLine: { lineStyle: { color: '#e5e7eb' } },
      },
      yAxis: {
        type: 'category',
        data: types.map((type) => i18n.t(`population.housingTypes.${HOUSING_TYPE_LABELS[type] || 'other'}`)),
        axisTick: { show: false },
      },
      series: [
        { name: i18n.t('population.charts.occupiedUnits'), type: 'bar', data: types.map((type) => byType.get(type)?.occupied), barMaxWidth: 22 },
        { name: i18n.t('population.charts.newUnits'), type: 'bar', data: types.map((type) => byType.get(type)?.newUnits), barMaxWidth: 22 },
      ],
    };
  }, [result]);

  const costOption = useMemo(() => {
    const costs = result?.metrics?.costs;
    if (!costs) return {};
    return {
      color: [COLORS.primary, COLORS.green, COLORS.amber, COLORS.red],
      tooltip: { trigger: 'item', formatter: (params: RecordValue) => `${params.name}<br/>${formatCost(params.value)}` },
      legend: { bottom: 0, textStyle: { fontSize: 10 } },
      series: [{
        type: 'pie',
        radius: ['42%', '69%'],
        center: ['50%', '43%'],
        avoidLabelOverlap: true,
        label: { show: false },
        emphasis: { label: { show: true, formatter: '{b}\n{d}%', fontSize: 10 } },
        data: [
          { name: i18n.t('population.costs.assignment'), value: Number(costs.public_assignment_cost) },
          { name: i18n.t('population.costs.housingAction'), value: Number(costs.housing_action_public_cost) },
          { name: i18n.t('population.costs.serviceAction'), value: Number(costs.service_action_public_cost) },
          { name: i18n.t('population.costs.relocation'), value: Number(costs.relocation_cost) },
        ],
      }],
    };
  }, [result]);

  const auditByCategory = useMemo(() => {
    const counts = new Map<string, { passed: number; total: number; binding: number }>();
    for (const row of result?.constraint_audit || []) {
      const current = counts.get(row.category) || { passed: 0, total: 0, binding: 0 };
      current.total += 1;
      current.passed += row.pass ? 1 : 0;
      const slacks = [row.lower_slack, row.upper_slack]
        .filter((value) => value !== null && value !== undefined)
        .map(Number);
      if (slacks.some((value) => Math.abs(value) <= 0.00001)) current.binding += 1;
      counts.set(row.category, current);
    }
    return [...counts.entries()].map(([category, values]) => ({ category, ...values }));
  }, [result]);

  if (loading) {
    return <div className="pho-loading"><RefreshCw size={20} className="spin" /><span>{t('population.loading')}</span></div>;
  }

  if (!baseInput || !catalog || !mapContext) {
    return (
      <div className="pho-fatal">
        <FileWarning size={24} />
        <strong>{t('population.unavailable')}</strong>
        <span>{error || t('population.missingInput')}</span>
      </div>
    );
  }

  const isFeasible = ['optimal', 'feasible_limit_reached'].includes(result?.status);
  const metrics = result?.metrics || {};
  const costs = metrics.costs || {};
  const display = baseInput.display || catalog.product?.display || {};
  const zoneCount = Number(catalog.scope?.zones || mapContext.boundary_source?.matched_feature_count || 0);
  const title = display.city_name
    ? `${display.city_name}${t('population.title')}`
    : t('population.title');
  const boundaryKindLabel = display.boundary_kind_label || t('population.boundary');
  const scopeDescription = display.scope_description
    || t('population.scopeDescription', { count: zoneCount, boundary: boundaryKindLabel });

  return (
    <div className="traditional-livability-tab pho-workbench" data-testid="population-housing-workbench">
      <div className="datapanel-section-header pho-header">
        <div>
          <h3>{title}</h3>
          <p>{scopeDescription}</p>
        </div>
        <div className="traditional-header-actions">
          <button className="btn-secondary" onClick={reset} title={t('population.actions.resetTitle')} disabled={solving}>
            <RotateCcw size={14} />{t('population.actions.reset')}
          </button>
          <button className="btn-primary" onClick={() => sendMap()} disabled={!isFeasible}>
            <MapIcon size={14} />{t('population.actions.sendMap')}
          </button>
        </div>
      </div>

      <div className="pho-status-row">
        <span><ShieldCheck size={14} />{t('population.status.frozenHash')}</span>
        <span><Scale size={14} />{t('population.status.proxyScenario')}</span>
        <span><MapIcon size={14} />{t('population.status.boundaryCount', { count: mapContext.boundary_source?.matched_feature_count, boundary: boundaryKindLabel })}</span>
      </div>

      <section className="traditional-panel pho-controls">
        <div className="traditional-panel-title">
          <SlidersHorizontal size={15} />
          <strong>{t('population.controls.scenarioParams')}</strong>
        </div>
        <div className="pho-control-grid">
          <fieldset className="pho-fieldset">
            <legend>{t('population.controls.objectivePreset')}</legend>
            <div className="pho-segments">
              {(Object.keys(PRESETS) as PresetKey[]).map((key) => (
                <button key={key} className={preset === key ? 'active' : ''} onClick={() => applyPreset(key)} disabled={solving}>
                  {t(`population.presets.${PRESETS[key].label}`)}
                </button>
              ))}
            </div>
            <div className="pho-range-grid">
              <RangeControl label={t('population.controls.publicCost')} value={weights.public_cost} min={0} max={2} step={0.05} onChange={(value) => updateWeight('public_cost', value)} />
              <RangeControl label={t('population.controls.residentHousingCost')} value={weights.resident_housing_cost} min={0} max={1.5} step={0.05} onChange={(value) => updateWeight('resident_housing_cost', value)} />
              <RangeControl label={t('population.controls.commuteCost')} value={weights.commute_cost} min={0} max={4} step={0.1} onChange={(value) => updateWeight('commute_cost', value)} />
              <RangeControl label={t('population.controls.relocationCost')} value={weights.relocation_cost} min={0} max={3} step={0.1} onChange={(value) => updateWeight('relocation_cost', value)} />
            </div>
          </fieldset>

          <fieldset className="pho-fieldset">
            <legend>{t('population.controls.resources')}</legend>
            <div className="pho-range-grid">
              <RangeControl label={t('population.controls.publicBudget')} value={resources.budget} min={35} max={125} step={5} suffix="%" onChange={(value) => updateResource('budget', value)} />
              <RangeControl label={t('population.controls.maxNewHousing')} value={resources.supply} min={0} max={125} step={5} suffix="%" onChange={(value) => updateResource('supply', value)} />
              <RangeControl label={t('population.controls.serviceExpansion')} value={resources.service} min={0} max={125} step={5} suffix="%" onChange={(value) => updateResource('service', value)} />
              <RangeControl label={t('population.controls.globalRelocationCap')} value={resources.relocation} min={0} max={20} step={0.5} suffix="%" onChange={(value) => updateResource('relocation', value)} />
            </div>
          </fieldset>
        </div>

        <div className="pho-control-actions">
          <button className="btn-primary pho-run-button" onClick={runScenario} disabled={solving}>
            {solving ? <RefreshCw size={15} className="spin" /> : <Play size={15} />}
            {solving ? t('population.actions.validateSolve') : t('population.actions.runPlan')}
          </button>
          <label className="pho-toggle">
            <input type="checkbox" checked={autoMap} onChange={(event) => setAutoMap(event.target.checked)} />
            {t('population.actions.autoMap')}
          </label>
          <div className="pho-map-mode" aria-label={t('population.map.planAria')}>
            <button className={mapMode === 'current' ? 'active' : ''} onClick={() => { setMapMode('current'); sendMap('current'); }}>{t('population.map.current')}</button>
            <button className={mapMode === 'frozen' ? 'active' : ''} onClick={() => { setMapMode('frozen'); sendMap('frozen'); }}>{t('population.map.frozen')}</button>
          </div>
        </div>

        <div className="pho-run-meta">
          <span><Database size={13} />{t('population.meta.scope', { zones: catalog.scope?.zones, households: formatNumber(catalog.scope?.modeled_households) })}</span>
          {elapsedMs !== null && <span><Clock3 size={13} />{t('population.meta.elapsed', { ms: formatNumber(elapsedMs, 0) })}</span>}
          {validation?.valid && <span><CheckCircle2 size={13} />{t('population.meta.contractPassed')}</span>}
          {mapNotice && <span><MapIcon size={13} />{mapNotice}</span>}
        </div>
      </section>

      {error && <div className="traditional-message error"><AlertTriangle size={16} /><span>{error}</span></div>}

      <section className={`traditional-panel pho-solve-status ${isFeasible ? 'feasible' : 'infeasible'}`}>
        <div className="traditional-panel-title">
          {isFeasible ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
          <strong>{t('population.solveStatus')}: {statusText(result?.status)}</strong>
        </div>
        <div className="pho-solver-facts">
          <span>{t('population.solverFacts.variables', { count: result?.solver?.variable_count || 258 })}</span>
          <span>{t('population.solverFacts.constraints', { count: result?.solver?.constraint_count || 98 })}</span>
          <span>{t('population.solverFacts.gap', { value: result?.solver?.mip_gap ?? '-' })}</span>
        </div>
      </section>

      {!isFeasible ? (
        <section className="traditional-panel pho-infeasible-state">
          <Gauge size={30} />
          <h4>{t('population.infeasible.title')}</h4>
          <div className="pho-resource-snapshot">
            <span>{t('population.controls.publicBudget')} {resources.budget}%</span>
            <span>{t('population.controls.maxNewHousing')} {resources.supply}%</span>
            <span>{t('population.controls.serviceExpansion')} {resources.service}%</span>
            <span>{t('population.controls.globalRelocationCap')} {resources.relocation}%</span>
          </div>
        </section>
      ) : (
        <>
          <div className="traditional-kpi-grid pho-kpi-grid">
            <div className="traditional-kpi"><span>{t('population.kpis.assigned')}</span><strong>{formatNumber(metrics.assigned_households)}</strong><small>{t('population.kpis.people', { count: formatNumber(metrics.modeled_people) })}</small></div>
            <div className="traditional-kpi"><span>{t('population.kpis.relocated')}</span><strong>{formatNumber(metrics.relocated_households)}</strong><MetricDelta current={metrics.relocated_households} reference={reference?.relocated_households} /></div>
            <div className="traditional-kpi"><span>{t('population.kpis.newHousing')}</span><strong>{formatNumber(metrics.new_units)}</strong><MetricDelta current={metrics.new_units} reference={reference?.new_units} /></div>
            <div className="traditional-kpi"><span>{t('population.kpis.serviceExpansion')}</span><strong>{formatNumber(metrics.service_expansion, 1)}</strong><MetricDelta current={metrics.service_expansion} reference={reference?.service_expansion} /></div>
            <div className="traditional-kpi"><span>{t('population.kpis.audit')}</span><strong>{result?.constraint_summary?.passed}/{result?.constraint_summary?.constraint_count}</strong><small className="down">{t('population.kpis.allPassed')}</small></div>
          </div>

          <nav className="pho-result-tabs" aria-label={t('population.resultViews')}>
            {([
              ['overview', t('population.views.overview'), BarChart3],
              ['allocations', t('population.views.allocations'), Home],
              ['audit', t('population.views.audit'), ShieldCheck],
              ['evidence', t('population.views.evidence'), FileWarning],
            ] as const).map(([key, label, Icon]) => (
              <button key={key} className={activeView === key ? 'active' : ''} onClick={() => setActiveView(key)}>
                <Icon size={14} />{label}
              </button>
            ))}
          </nav>

          {activeView === 'overview' && (
            <div className="pho-overview">
              <div className="pho-cost-strip">
                <div><CircleDollarSign size={15} /><span>{t('population.costs.public')}</span><strong>{formatCost(costs.public_cost)}</strong><MetricDelta current={costs.public_cost} reference={reference?.public_cost} /></div>
                <div><Home size={15} /><span>{t('population.costs.housing')}</span><strong>{formatCost(costs.resident_housing_cost)}</strong><MetricDelta current={costs.resident_housing_cost} reference={reference?.resident_housing_cost} /></div>
                <div><Route size={15} /><span>{t('population.costs.commute')}</span><strong>{formatCost(costs.commute_generalized_cost)}</strong><MetricDelta current={costs.commute_generalized_cost} reference={reference?.commute_generalized_cost} /></div>
              </div>
              <div className="traditional-message success pho-map-message">
                <MapIcon size={16} />
                <span>{t('population.map.message', { count: zoneCount, boundary: boundaryKindLabel })}</span>
                <button className="btn-secondary" onClick={() => sendMap()}><MapIcon size={14} />{t('population.actions.refreshMap')}</button>
              </div>
              <div className="pho-viz-grid">
                <section className="traditional-panel pho-viz">
                  <div className="traditional-panel-title"><Building2 size={15} /><strong>{t('population.charts.housingTypes')}</strong><small>{t('population.charts.householdUnit')}</small></div>
                  <ReactECharts option={housingOption} style={{ height: 250 }} notMerge />
                </section>
                <section className="traditional-panel pho-viz">
                  <div className="traditional-panel-title"><CircleDollarSign size={15} /><strong>{t('population.charts.costComposition')}</strong><small>{t('population.charts.planningCostUnit')}</small></div>
                  <ReactECharts option={costOption} style={{ height: 250 }} notMerge />
                </section>
              </div>
            </div>
          )}

          {activeView === 'allocations' && (
            <section className="traditional-panel pho-table-section">
              <div className="traditional-panel-title"><Home size={15} /><strong>{t('population.allocations.title')}</strong><small>{t('population.allocations.count', { count: result.assignments?.length || 0 })}</small></div>
              <div className="pho-table-wrap traditional-table-wrap">
                <table className="traditional-table">
                  <thead><tr><th>{t('population.allocations.group')}</th><th>{t('population.allocations.origin')}</th><th>{t('population.allocations.destination')}</th><th>{t('population.allocations.housingType')}</th><th>{t('population.allocations.households')}</th><th>{t('population.allocations.commute')}</th><th>{t('population.allocations.relocated')}</th></tr></thead>
                  <tbody>
                    {(result.assignments || []).map((row: RecordValue, index: number) => (
                      <tr
                        key={`${row.group_id}-${row.housing_option_id}-${index}`}
                        className="pho-map-row"
                        tabIndex={0}
                        title={t('population.allocations.focusMap')}
                        onClick={() => sendMap('current', row)}
                        onKeyDown={(event) => { if (event.key === 'Enter') sendMap('current', row); }}
                      >
                        <td>{row.group_name || t('population.allocations.unnamedGroup')}</td>
                        <td>{String(row.origin_zone_id).split('|')[1] || t('population.allocations.unknownOrigin')}</td>
                        <td>{row.destination_zone_name || t('population.allocations.unknownDestination')}</td>
                        <td>{i18n.t(`population.housingTypes.${HOUSING_TYPE_LABELS[row.housing_type] || 'other'}`)}</td>
                        <td>{formatNumber(row.households)}</td>
                        <td>{t('population.allocations.minutes', { value: formatNumber(row.commute_minutes, 1) })}</td>
                        <td>{row.relocated ? <span className="pho-relocated">{t('population.common.yes')}</span> : t('population.common.no')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {activeView === 'audit' && (
            <section className="pho-audit-view">
              <div className="pho-audit-summary">
                {auditByCategory.map((row) => (
                  <div className="traditional-kpi" key={row.category}>
                    <span>{categoryText(row.category)}</span>
                    <strong>{row.passed}/{row.total}</strong>
                    <small>{t('population.audit.binding', { count: row.binding })}</small>
                  </div>
                ))}
              </div>
              <div className="pho-table-wrap traditional-table-wrap audit">
                <table className="traditional-table">
                  <thead><tr><th>{t('population.audit.constraint')}</th><th>{t('population.audit.category')}</th><th>{t('population.audit.lhs')}</th><th>{t('population.audit.lower')}</th><th>{t('population.audit.upper')}</th><th>{t('population.audit.result')}</th></tr></thead>
                  <tbody>
                    {(result.constraint_audit || []).map((row: RecordValue) => (
                      <tr key={row.constraint_id}>
                        <td>{constraintText(row, baseInput)}</td><td>{categoryText(row.category)}</td>
                        <td>{formatNumber(row.lhs, 3)}</td><td>{formatNumber(row.lower, 3)}</td><td>{formatNumber(row.upper, 3)}</td>
                        <td><span className={row.pass ? 'pho-pass' : 'pho-fail'}>{row.pass ? t('population.common.passed') : t('population.common.failed')}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {activeView === 'evidence' && (
            <section className="traditional-panel pho-evidence-view">
              <div className="pho-boundary-banner">
                <Scale size={22} />
                <div><strong>{t('population.evidence.maxClaim')}</strong><span>{t('population.evidence.proxyProof')}</span></div>
              </div>
              <div className="pho-evidence-grid">
                {(baseInput.synthetic_flags || []).map((row: RecordValue) => (
                  <div className="traditional-kpi" key={row.field_group}>
                    <span>{t(`population.evidenceFields.${EVIDENCE_LABELS[row.field_group] || 'other'}`)}</span>
                    <strong>{t(`population.evidenceStatus.${EVIDENCE_STATUS_LABELS[row.status] || 'other'}`)}</strong>
                  </div>
                ))}
              </div>
              <div className="pho-limitations">
                <h4>{t('population.evidence.blockedClaims')}</h4>
                <ul>
                  <li>{t('population.evidence.limitations.policy')}</li>
                  <li>{t('population.evidence.limitations.representativeness')}</li>
                  <li>{t('population.evidence.limitations.individual')}</li>
                  <li>{t('population.evidence.limitations.welfare')}</li>
                </ul>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
