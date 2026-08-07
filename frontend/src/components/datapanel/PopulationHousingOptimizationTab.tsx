import { useEffect, useMemo, useState } from 'react';
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
    label: '均衡',
    weights: {
      public_cost: 1,
      resident_housing_cost: 0.15,
      commute_cost: 0.5,
      relocation_cost: 1,
      unmet_penalty: 1,
    },
  },
  fiscal: {
    label: '财政',
    weights: {
      public_cost: 1,
      resident_housing_cost: 0.05,
      commute_cost: 0.1,
      relocation_cost: 0.25,
      unmet_penalty: 1,
    },
  },
  commute: {
    label: '通勤',
    weights: {
      public_cost: 0.35,
      resident_housing_cost: 0.1,
      commute_cost: 3,
      relocation_cost: 1.5,
      unmet_penalty: 1,
    },
  },
  resident: {
    label: '居住成本',
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

const EVIDENCE_LABELS: Record<string, string> = {
  population_total: '人口总量',
  population_groups: '人群分组',
  housing_capacity: '住房容量',
  transport_impedance: '交通阻抗',
  service_capacity: '公共服务容量',
  costs: '成本参数',
};

const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  fitted_proxy: '拟合代理值',
  scenario_assumption: '情景假设',
};

const HOUSING_TYPE_LABELS: Record<string, string> = {
  standard: '普通住房',
  rental: '租赁住房',
  accessible: '适老住房',
};

const AUDIT_CATEGORY_LABELS: Record<string, string> = {
  population_conservation: '人口守恒',
  housing_capacity: '住房容量',
  housing_activation: '住房启用联动',
  public_service_capacity: '公共服务容量',
  fiscal: '公共预算',
  relocation: '跨区配置上限',
};

const AUDIT_ID_LABELS: Record<string, string> = {
  group_balance: '家庭组守恒',
  housing_capacity: '住房容量',
  housing_activation: '住房启用上限',
  housing_activation_lower: '住房启用下限',
  service_capacity: '公共服务容量',
  public_budget: '公共预算',
  global_relocation_cap: '全局跨区上限',
  group_relocation_cap: '家庭组跨区上限',
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function formatNumber(value: unknown, maximumFractionDigits = 0): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits }).format(number);
}

function formatCost(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  if (Math.abs(number) >= 100_000_000) return `${formatNumber(number / 100_000_000, 2)} 亿单位`;
  if (Math.abs(number) >= 10_000) return `${formatNumber(number / 10_000, 2)} 万单位`;
  return `${formatNumber(number, 2)} 单位`;
}

function formatCompact(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  if (Math.abs(number) >= 100_000_000) return `${formatNumber(number / 100_000_000, 1)} 亿`;
  if (Math.abs(number) >= 10_000) return `${formatNumber(number / 10_000, 1)} 万`;
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
    optimal: '最优解',
    feasible_limit_reached: '时限内可行解',
    infeasible: '不可行',
    limit_reached_without_solution: '时限内未找到解',
  };
  return status ? labels[status] || '未知状态' : '未运行';
}

function categoryText(category: unknown): string {
  return AUDIT_CATEGORY_LABELS[String(category || '')] || '其他约束';
}

function constraintText(row: RecordValue, input: RecordValue): string {
  const [prefix, identity = ''] = String(row.constraint_id || '').split('::');
  const label = AUDIT_ID_LABELS[prefix] || '约束项';
  if (!identity) return label;
  const group = (input.population_groups || []).find((item: RecordValue) => item.group_id === identity);
  if (group) return `${label}：${group.group_name}`;
  const housing = (input.housing_options || []).find((item: RecordValue) => item.housing_option_id === identity);
  if (housing) {
    const zone = (input.zones || []).find((item: RecordValue) => item.zone_id === housing.zone_id);
    return `${label}：${zone?.zone_name || housing.zone_id} ${HOUSING_TYPE_LABELS[housing.housing_type] || '住房'}`;
  }
  const zone = (input.zones || []).find((item: RecordValue) => item.zone_id === identity);
  return `${label}：${zone?.zone_name || '场景对象'}`;
}

async function fetchJson(url: string, init?: RequestInit): Promise<RecordValue> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: 'include', ...init });
  } catch {
    throw new Error('无法连接人口住房分析服务，请确认后端已启动且当前会话有效');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
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
    .filter((feature: RecordValue) => !focusIds || focusIds.has(String(feature.properties?.['空间单元标识'])))
    .map((feature: RecordValue) => {
      const copied = clone(feature);
      const zoneId = String(copied.properties?.['空间单元标识']);
      const households = assigned.get(zoneId) || 0;
      const band = households <= lower ? '较低' : households <= upper ? '中等' : '较高';
      copied.properties = {
        ...copied.properties,
        方案: profileLabel,
        配置家庭数: Math.round(households),
        新增住房代理套数: Math.round(newUnits.get(zoneId) || 0),
        公共服务扩容代理: Number((service.get(zoneId) || 0).toFixed(2)),
        配置强度: band,
        证据边界: '聚合代理情景，不是政策建议或个人分配',
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
        方案: profileLabel,
        起点: origin.zone_name || originId,
        目标区: destination.zone_name || destinationId,
        跨区配置家庭数: Math.round(households),
        箭头说明: '箭头由起点指向目标区',
        流向含义: '模型聚合配置关系，不是实际搬迁路线或道路路径',
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
      title: context.display?.scenario_name || '人口与住房空间配置优化',
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
        name: `${profileLabel}行政区配置`,
        type: 'categorized',
        category_column: '配置强度',
        category_labels: { 较低: '配置家庭较低', 中等: '配置家庭中等', 较高: '配置家庭较高' },
        style_map: {
          较低: { fillColor: '#dbeafe', color: '#1d4ed8' },
          中等: { fillColor: '#86efac', color: '#15803d' },
          较高: { fillColor: '#fbbf24', color: '#a16207' },
        },
        style: { weight: 1.5, fillOpacity: 0.58, opacity: 0.9 },
        geojsonData: { type: 'FeatureCollection', features: boundaryFeatures },
      },
      {
        name: `${profileLabel}跨区配置流`,
        type: 'line',
        legend_title: '聚合配置流向',
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
  if (delta === null) return <small>均衡基准不可比</small>;
  const className = Math.abs(delta) < 0.0005 ? 'neutral' : delta > 0 ? 'up' : 'down';
  return <small className={className}>{delta > 0 ? '+' : ''}{delta.toFixed(2)}%（相对均衡基准）</small>;
}

export default function PopulationHousingOptimizationTab() {
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
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : '人口住房产品不可用');
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
    const label = mode === 'frozen' ? '均衡基准方案' : '当前方案';
    (window as any).__handleMapUpdate?.(buildMapUpdate(mapContext, target, label, focus));
    setMapNotice(focus ? '已在主地图聚焦该配置关系' : `已发送${label}到主地图`);
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
        throw new Error((validationPayload.errors || []).join('；') || '输入校验失败');
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
      setError(solveError instanceof Error ? solveError.message : '求解请求失败');
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
        data: types.map((type) => HOUSING_TYPE_LABELS[type] || '其他住房'),
        axisTick: { show: false },
      },
      series: [
        { name: '配置户数', type: 'bar', data: types.map((type) => byType.get(type)?.occupied), barMaxWidth: 22 },
        { name: '新增住房', type: 'bar', data: types.map((type) => byType.get(type)?.newUnits), barMaxWidth: 22 },
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
          { name: '配置成本', value: Number(costs.public_assignment_cost) },
          { name: '住房行动', value: Number(costs.housing_action_public_cost) },
          { name: '服务扩容', value: Number(costs.service_action_public_cost) },
          { name: '跨区配置', value: Number(costs.relocation_cost) },
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
    return <div className="pho-loading"><RefreshCw size={20} className="spin" /><span>载入已验证的基准方案</span></div>;
  }

  if (!baseInput || !catalog || !mapContext) {
    return (
      <div className="pho-fatal">
        <FileWarning size={24} />
        <strong>人口住房优化产品不可用</strong>
        <span>{error || '缺少已验证的默认输入或行政区边界'}</span>
      </div>
    );
  }

  const isFeasible = ['optimal', 'feasible_limit_reached'].includes(result?.status);
  const metrics = result?.metrics || {};
  const costs = metrics.costs || {};
  const display = baseInput.display || catalog.product?.display || {};
  const zoneCount = Number(catalog.scope?.zones || mapContext.boundary_source?.matched_feature_count || 0);
  const title = display.city_name
    ? `${display.city_name}人口与住房空间配置优化`
    : '人口与住房空间配置优化';
  const boundaryKindLabel = display.boundary_kind_label || '行政区边界';
  const scopeDescription = display.scope_description
    || `${zoneCount} 个${boundaryKindLabel}的聚合代理情景配置与硬约束审计`;

  return (
    <div className="traditional-livability-tab pho-workbench" data-testid="population-housing-workbench">
      <div className="datapanel-section-header pho-header">
        <div>
          <h3>{title}</h3>
          <p>{scopeDescription}</p>
        </div>
        <div className="traditional-header-actions">
          <button className="btn-secondary" onClick={reset} title="恢复均衡基准方案" disabled={solving}>
            <RotateCcw size={14} />恢复
          </button>
          <button className="btn-primary" onClick={() => sendMap()} disabled={!isFeasible}>
            <MapIcon size={14} />发送到地图
          </button>
        </div>
      </div>

      <div className="pho-status-row">
        <span><ShieldCheck size={14} />冻结哈希已验证</span>
        <span><Scale size={14} />代理情景，非政策建议</span>
        <span><MapIcon size={14} />{mapContext.boundary_source?.matched_feature_count} 个{boundaryKindLabel}</span>
      </div>

      <section className="traditional-panel pho-controls">
        <div className="traditional-panel-title">
          <SlidersHorizontal size={15} />
          <strong>情景参数</strong>
        </div>
        <div className="pho-control-grid">
          <fieldset className="pho-fieldset">
            <legend>目标预设</legend>
            <div className="pho-segments">
              {(Object.keys(PRESETS) as PresetKey[]).map((key) => (
                <button key={key} className={preset === key ? 'active' : ''} onClick={() => applyPreset(key)} disabled={solving}>
                  {PRESETS[key].label}
                </button>
              ))}
            </div>
            <div className="pho-range-grid">
              <RangeControl label="公共成本" value={weights.public_cost} min={0} max={2} step={0.05} onChange={(value) => updateWeight('public_cost', value)} />
              <RangeControl label="居民住房成本" value={weights.resident_housing_cost} min={0} max={1.5} step={0.05} onChange={(value) => updateWeight('resident_housing_cost', value)} />
              <RangeControl label="通勤成本" value={weights.commute_cost} min={0} max={4} step={0.1} onChange={(value) => updateWeight('commute_cost', value)} />
              <RangeControl label="跨区配置成本" value={weights.relocation_cost} min={0} max={3} step={0.1} onChange={(value) => updateWeight('relocation_cost', value)} />
            </div>
          </fieldset>

          <fieldset className="pho-fieldset">
            <legend>资源与约束</legend>
            <div className="pho-range-grid">
              <RangeControl label="公共预算" value={resources.budget} min={35} max={125} step={5} suffix="%" onChange={(value) => updateResource('budget', value)} />
              <RangeControl label="最大新增住房" value={resources.supply} min={0} max={125} step={5} suffix="%" onChange={(value) => updateResource('supply', value)} />
              <RangeControl label="服务扩容能力" value={resources.service} min={0} max={125} step={5} suffix="%" onChange={(value) => updateResource('service', value)} />
              <RangeControl label="全局跨区上限" value={resources.relocation} min={0} max={20} step={0.5} suffix="%" onChange={(value) => updateResource('relocation', value)} />
            </div>
          </fieldset>
        </div>

        <div className="pho-control-actions">
          <button className="btn-primary pho-run-button" onClick={runScenario} disabled={solving}>
            {solving ? <RefreshCw size={15} className="spin" /> : <Play size={15} />}
            {solving ? '校验并求解' : '运行配置方案'}
          </button>
          <label className="pho-toggle">
            <input type="checkbox" checked={autoMap} onChange={(event) => setAutoMap(event.target.checked)} />
            求解后自动更新地图
          </label>
          <div className="pho-map-mode" aria-label="地图方案">
            <button className={mapMode === 'current' ? 'active' : ''} onClick={() => { setMapMode('current'); sendMap('current'); }}>当前结果</button>
            <button className={mapMode === 'frozen' ? 'active' : ''} onClick={() => { setMapMode('frozen'); sendMap('frozen'); }}>均衡基准</button>
          </div>
        </div>

        <div className="pho-run-meta">
          <span><Database size={13} />{catalog.scope?.zones} 个空间单元，{formatNumber(catalog.scope?.modeled_households)} 户</span>
          {elapsedMs !== null && <span><Clock3 size={13} />端到端 {formatNumber(elapsedMs, 0)} 毫秒</span>}
          {validation?.valid && <span><CheckCircle2 size={13} />输入契约通过</span>}
          {mapNotice && <span><MapIcon size={13} />{mapNotice}</span>}
        </div>
      </section>

      {error && <div className="traditional-message error"><AlertTriangle size={16} /><span>{error}</span></div>}

      <section className={`traditional-panel pho-solve-status ${isFeasible ? 'feasible' : 'infeasible'}`}>
        <div className="traditional-panel-title">
          {isFeasible ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
          <strong>求解状态：{statusText(result?.status)}</strong>
        </div>
        <div className="pho-solver-facts">
          <span>{result?.solver?.variable_count || 258} 个变量</span>
          <span>{result?.solver?.constraint_count || 98} 条约束</span>
          <span>整数规划相对间隙 {result?.solver?.mip_gap ?? '-'}</span>
        </div>
      </section>

      {!isFeasible ? (
        <section className="traditional-panel pho-infeasible-state">
          <Gauge size={30} />
          <h4>当前资源组合不可行</h4>
          <div className="pho-resource-snapshot">
            <span>预算 {resources.budget}%</span>
            <span>新增住房 {resources.supply}%</span>
            <span>服务扩容 {resources.service}%</span>
            <span>跨区上限 {resources.relocation}%</span>
          </div>
        </section>
      ) : (
        <>
          <div className="traditional-kpi-grid pho-kpi-grid">
            <div className="traditional-kpi"><span>配置家庭</span><strong>{formatNumber(metrics.assigned_households)}</strong><small>{formatNumber(metrics.modeled_people)} 人</small></div>
            <div className="traditional-kpi"><span>跨区配置</span><strong>{formatNumber(metrics.relocated_households)}</strong><MetricDelta current={metrics.relocated_households} reference={reference?.relocated_households} /></div>
            <div className="traditional-kpi"><span>新增住房</span><strong>{formatNumber(metrics.new_units)}</strong><MetricDelta current={metrics.new_units} reference={reference?.new_units} /></div>
            <div className="traditional-kpi"><span>服务扩容</span><strong>{formatNumber(metrics.service_expansion, 1)}</strong><MetricDelta current={metrics.service_expansion} reference={reference?.service_expansion} /></div>
            <div className="traditional-kpi"><span>约束审计</span><strong>{result?.constraint_summary?.passed}/{result?.constraint_summary?.constraint_count}</strong><small className="down">全部通过</small></div>
          </div>

          <nav className="pho-result-tabs" aria-label="结果视图">
            {([
              ['overview', '概览', BarChart3],
              ['allocations', '配置明细', Home],
              ['audit', '约束审计', ShieldCheck],
              ['evidence', '证据边界', FileWarning],
            ] as const).map(([key, label, Icon]) => (
              <button key={key} className={activeView === key ? 'active' : ''} onClick={() => setActiveView(key)}>
                <Icon size={14} />{label}
              </button>
            ))}
          </nav>

          {activeView === 'overview' && (
            <div className="pho-overview">
              <div className="pho-cost-strip">
                <div><CircleDollarSign size={15} /><span>公共成本代理</span><strong>{formatCost(costs.public_cost)}</strong><MetricDelta current={costs.public_cost} reference={reference?.public_cost} /></div>
                <div><Home size={15} /><span>居民住房成本代理</span><strong>{formatCost(costs.resident_housing_cost)}</strong><MetricDelta current={costs.resident_housing_cost} reference={reference?.resident_housing_cost} /></div>
                <div><Route size={15} /><span>通勤成本代理</span><strong>{formatCost(costs.commute_generalized_cost)}</strong><MetricDelta current={costs.commute_generalized_cost} reference={reference?.commute_generalized_cost} /></div>
              </div>
              <div className="traditional-message success pho-map-message">
                <MapIcon size={16} />
                <span>主地图展示 {zoneCount} 个{boundaryKindLabel}和跨区配置流；箭头指向配置目标区，流线不是实际搬迁路线。</span>
                <button className="btn-secondary" onClick={() => sendMap()}><MapIcon size={14} />刷新地图</button>
              </div>
              <div className="pho-viz-grid">
                <section className="traditional-panel pho-viz">
                  <div className="traditional-panel-title"><Building2 size={15} /><strong>住房类型配置</strong><small>单位：户</small></div>
                  <ReactECharts option={housingOption} style={{ height: 250 }} notMerge />
                </section>
                <section className="traditional-panel pho-viz">
                  <div className="traditional-panel-title"><CircleDollarSign size={15} /><strong>公共成本代理构成</strong><small>规划成本单位</small></div>
                  <ReactECharts option={costOption} style={{ height: 250 }} notMerge />
                </section>
              </div>
            </div>
          )}

          {activeView === 'allocations' && (
            <section className="traditional-panel pho-table-section">
              <div className="traditional-panel-title"><Home size={15} /><strong>家庭组到住房选项</strong><small>{result.assignments?.length || 0} 条非零配置</small></div>
              <div className="pho-table-wrap traditional-table-wrap">
                <table className="traditional-table">
                  <thead><tr><th>家庭组</th><th>起点</th><th>目标区</th><th>住房类型</th><th>家庭数</th><th>通勤</th><th>跨区</th></tr></thead>
                  <tbody>
                    {(result.assignments || []).map((row: RecordValue, index: number) => (
                      <tr
                        key={`${row.group_id}-${row.housing_option_id}-${index}`}
                        className="pho-map-row"
                        tabIndex={0}
                        title="在主地图聚焦该配置关系"
                        onClick={() => sendMap('current', row)}
                        onKeyDown={(event) => { if (event.key === 'Enter') sendMap('current', row); }}
                      >
                        <td>{row.group_name || '未命名家庭组'}</td>
                        <td>{String(row.origin_zone_id).split('|')[1] || '未标注起点'}</td>
                        <td>{row.destination_zone_name || '未标注目标区'}</td>
                        <td>{HOUSING_TYPE_LABELS[row.housing_type] || '其他住房'}</td>
                        <td>{formatNumber(row.households)}</td>
                        <td>{formatNumber(row.commute_minutes, 1)} 分钟</td>
                        <td>{row.relocated ? <span className="pho-relocated">是</span> : '否'}</td>
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
                    <small>{row.binding} 项触界</small>
                  </div>
                ))}
              </div>
              <div className="pho-table-wrap traditional-table-wrap audit">
                <table className="traditional-table">
                  <thead><tr><th>约束项</th><th>类别</th><th>左侧计算值</th><th>下界</th><th>上界</th><th>结果</th></tr></thead>
                  <tbody>
                    {(result.constraint_audit || []).map((row: RecordValue) => (
                      <tr key={row.constraint_id}>
                        <td>{constraintText(row, baseInput)}</td><td>{categoryText(row.category)}</td>
                        <td>{formatNumber(row.lhs, 3)}</td><td>{formatNumber(row.lower, 3)}</td><td>{formatNumber(row.upper, 3)}</td>
                        <td><span className={row.pass ? 'pho-pass' : 'pho-fail'}>{row.pass ? '通过' : '失败'}</span></td>
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
                <div><strong>最高可支持结论</strong><span>聚合代理情景优化概念验证</span></div>
              </div>
              <div className="pho-evidence-grid">
                {(baseInput.synthetic_flags || []).map((row: RecordValue) => (
                  <div className="traditional-kpi" key={row.field_group}>
                    <span>{EVIDENCE_LABELS[row.field_group] || '其他数据通道'}</span>
                    <strong>{EVIDENCE_STATUS_LABELS[row.status] || '未标注'}</strong>
                  </div>
                ))}
              </div>
              <div className="pho-limitations">
                <h4>阻断结论</h4>
                <ul>
                  <li>真实政策最优与财政节省</li>
                  <li>城市总体代表性与因果效果</li>
                  <li>个人或具名家庭住房分配</li>
                  <li>观测现状基线与福利改善</li>
                </ul>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
