import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getLocale, getLocaleHeaders } from '../../i18n';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  CloudRain,
  Clock3,
  Database,
  ExternalLink,
  FileCheck2,
  Gauge,
  GitBranch,
  Globe2,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Map as MapIcon,
  Network,
  Play,
  RotateCcw,
  ShieldCheck,
  SlidersHorizontal,
  TimerReset,
  Waves,
} from 'lucide-react';

type StageStatus = 'ready' | 'partial' | 'blocked';

interface Stage {
  key: string;
  index: string;
  title: string;
  subtitle: string;
  status: StageStatus;
  statusLabel: string;
  icon: typeof Database;
  summary: string;
  inputs: string[];
  outputs: string[];
  next: string;
}

const stages: Stage[] = [
  {
    key: 'data',
    index: '01',
    title: '数据与准入',
    subtitle: '权威数据、元数据、哈希和工程语义',
    status: 'partial',
    statusLabel: '已接入 · 工程语义待确认',
    icon: Database,
    summary: '客户管网与 5 m DTM 已接入并完成空间规范化；管径、高程、设施角色、泵站运行、潮位边界和历史观测仍需客户权威确认。',
    inputs: ['客户雨水管网 GDB', '事件降雨 / 雷达 QPE', '高程与垂直基准', '泵闸、潮位和观测'],
    outputs: ['字段映射与问题清单', '客户回执自动验收', '来源、版本、时效和 SHA-256'],
    next: '客户数据到达后先运行回执验收与事件时序预检。',
  },
  {
    key: 'swmm',
    index: '02',
    title: '一维雨水管网',
    subtitle: 'EPA SWMM 5.2.4 产流与管网水力',
    status: 'partial',
    statusLabel: '诊断可运行',
    icon: Waves,
    summary: '当前一维结果来自单个全市连续网络 EPA SWMM 5.2.4 诊断作业；严格数值质量门未通过，结果未校准、未工程准入。',
    inputs: ['管段、节点和设施拓扑', '汇水区与雨水口绑定', '降雨时序', '泵闸与出水边界'],
    outputs: ['节点水深、入流和溢流', '管段流量、流速和容量率', '质量门与原生 RPT / OUT'],
    next: '替换客户权威单位、高程、边界和事件强迫后再做校准。',
  },
  {
    key: 'surface',
    index: '03',
    title: '二维地表水动力',
    subtitle: 'ANUGA 主链路 + 双向验证成果 + LISFLOOD-FP 诊断适配',
    status: 'partial',
    statusLabel: '5 m DTM 输入 · 250 m 计算网格',
    icon: Layers3,
    summary: '客户 5 m DTM 作为地形输入；已登记 2/5/10/25/50/100 年一遇 SWMM→ANUGA 单向成果，并有独立的 100 年一遇 SWMM–ANUGA 同步双向数值验证成果；两者均未工程准入。',
    inputs: ['DEM / DSM 与垂直基准', '道路路缘和建筑阻水', '地表进水与回灌关系', '二维边界与糙率'],
    outputs: ['最大积水深度和范围', '积水持续时间与退水', '与 SWMM 的体积交换对账'],
    next: '完成地表数据、源项和边界映射后进入真实事件二维验证。',
  },
  {
    key: 'gwm',
    index: '04',
    title: 'GWM 快速推演层',
    subtitle: '状态表示、情景筛选和不确定性门控',
    status: 'partial',
    statusLabel: '历史事件 GWM R1 已接入 · 研究代理',
    icon: GitBranch,
    summary: '当前可调用版本为 GWM-R1-20260914：17 场训练事件，学习 250 m SWMM–ANUGA 物理标签；它不是直接由历史积水观测训练的工程预测模型。',
    inputs: ['SWMM / ANUGA 多事件状态', '观测掩码与质量掩码', '降雨、潮位和操作动作', '图结构与空间特征'],
    outputs: ['快速情景 rollout', '分布外检测与不确定性', '候选方案筛选与回退信号'],
    next: '继续用冻结模型开展独立事件外部检验；Sentinel-2 只作为云筛选后的积水观测证据，不作为实测水深 ground truth。',
  },
  {
    key: 'validation',
    index: '05',
    title: '验证与交付',
    subtitle: '独立事件、影响叠加和工程决策',
    status: 'partial',
    statusLabel: '历史重演已接入',
    icon: ShieldCheck,
    summary: '2024 年 4 月重构事件的 SWMM→ANUGA 回放和 Sentinel-2 外部观测链已接入；SWMM 严格质量门未通过，独立二维复核和工程准入仍待完成。',
    inputs: ['独立历史暴雨', '水位、流量、积水观测', '道路与设施影响', '工程方案与运行约束'],
    outputs: ['积水风险图和影响清单', '传统模型与 GWM 对照', '可追溯交付包与准入声明'],
    next: '通过独立事件盲测后，才可形成城市级预测或方案优化声明。',
  },
];

const stageStatusClass: Record<StageStatus, string> = {
  ready: 'abu-flood-status-ready',
  partial: 'abu-flood-status-partial',
  blocked: 'abu-flood-status-blocked',
};

const modelRows = [
  { name: 'EPA SWMM 5.2.4', role: '一维产流与管网水力', owner: '物理基线', status: '全市连续网络诊断 · 严格质量门未通过', tone: 'partial' },
  { name: 'ANUGA', role: '二维地表积水扩散', owner: '主二维链路', status: '5 m DTM · 250 m 网格 · 单向成果 + 双向验证成果', tone: 'partial' },
  { name: 'LISFLOOD-FP 5.9', role: '二维独立交叉验证', owner: '复核模型', status: '合成诊断适配已存在 · 未发现全市登记成果', tone: 'blocked' },
  { name: 'GWM R1', role: '历史事件推理与快速筛选', owner: '研究代理层', status: '17 场训练事件 · 模拟物理标签 · 未工程准入', tone: 'partial' },
];

const gates = [
  ['客户权威数据完整', '工程语义、泵站、潮位和观测仍待确认', 'blocked'],
  ['SWMM 工程校准', '尚未准入', 'blocked'],
  ['二维历史事件', '回放已接入 · 独立复核未完成', 'partial'],
  ['历史事件 GWM R1', '研究推理可用 · 外部确认性验证未完成', 'partial'],
  ['城市级预测声明', '关闭', 'blocked'],
];

export type CustomerHotspotsBootstrap = {
  metadata: {
    feature_count?: number;
    source_version?: string;
    source_sha256?: string;
    priority_counts?: Record<string, number>;
    center_counts?: Record<string, number>;
    evidence_class?: string;
    event_linkage?: string;
    validation_status?: string;
    [key: string]: any;
  };
  geojson: {
    type: 'FeatureCollection';
    name?: string;
    bbox?: number[];
    features: any[];
  };
};

const customerHotspotMapLayerBase = {
  name: '客户静态积水热点（506）',
  type: 'bubble',
  layer_id: 'abu-dhabi-customer-hotspots-506',
  category_column: 'priority',
  category_colors: {
    Important: '#f59e0b',
    'Very Important': '#ef4444',
  },
  category_labels: {
    Important: '重要',
    'Very Important': '非常重要',
  },
  legend_title: '客户积水热点优先级',
  style: {
    min_radius: 7,
    max_radius: 7,
    color: '#fff7ed',
    fillOpacity: 0.92,
    opacity: 0.98,
  },
  tooltip_fields: ['hotspot_id', 'priority', 'center', 'description', 'evidence_class', 'event_linkage', 'source_version'],
  tooltip_labels: {
    hotspot_id: '热点 ID',
    priority: '优先级',
    center: '区域 / 管理中心',
    description: '地点描述',
    evidence_class: '证据类别',
    event_linkage: '事件关联',
    source_version: '来源版本',
  },
} as const;

// These are private, locally generated derivatives of the customer FileGDB.
// They are input/asset geometry only; no hydraulic variables are encoded here.
const customerMapLayers = {
  extent: {
    name: '模型输入 · 客户 GDB 雨水管线（全量 MVT，238,287 条）', type: 'mvt',
    tile_url: '/api/tiles/abu-stormwater-pipelines-v1/{z}/{x}/{y}.pbf',
    metadata_url: '/api/tiles/abu-stormwater-pipelines-v1/metadata.json',
    layer_id: 'abu-stormwater-pipelines-v1', source_layer: 'stormwater_pipelines',
    min_zoom: 8, max_zoom: 16, bounds: [54.3058647, 24.2761843, 54.7718883, 24.6097775] as [number, number, number, number],
    style: { color: '#00e5ff', weight: 3, opacity: 1 },
  },
  network: {
    name: '模型输入 · 客户 GDB 雨水管线（全量 MVT，高对比显示，238,287 条）', type: 'mvt',
    tile_url: '/api/tiles/abu-stormwater-pipelines-v1/{z}/{x}/{y}.pbf',
    metadata_url: '/api/tiles/abu-stormwater-pipelines-v1/metadata.json',
    layer_id: 'abu-stormwater-pipelines-v1', source_layer: 'stormwater_pipelines',
    min_zoom: 8, max_zoom: 16, bounds: [54.3058647, 24.2761843, 54.7718883, 24.6097775] as [number, number, number, number],
    style: { color: '#00e5ff', weight: 3, opacity: 1 },
    tooltip_fields: ['registered_pipeline_fid', 'source_node_id', 'target_node_id', 'recomputed_length_m', 'diameter_numeric', 'pipe_material', 'pipeline_status'],
    tooltip_labels: { registered_pipeline_fid: '客户管段 FID', source_node_id: '起点拓扑 ID', target_node_id: '终点拓扑 ID', recomputed_length_m: '重算长度（m）', diameter_numeric: '管径候选值', pipe_material: '管材', pipeline_status: '管线状态' },
  },
  nodes: {
    name: '模型输入 · 管线端点拓扑节点（全量 MVT，默认高亮，238,350 个）', type: 'mvt',
    tile_url: '/api/tiles/abu-stormwater-nodes-v1/{z}/{x}/{y}.pbf',
    metadata_url: '/api/tiles/abu-stormwater-nodes-v1/metadata.json',
    layer_id: 'abu-stormwater-nodes-v1', source_layer: 'stormwater_nodes',
    min_zoom: 8, max_zoom: 16, bounds: [54.3058643, 24.2761845, 54.7718879, 24.6097773] as [number, number, number, number],
    style: {
      color: '#0f172a', fillColor: '#ff2fb3', weight: 0.5,
      radius: 60, radiusUnits: 'meters', radiusMinPixels: 1.1, radiusMaxPixels: 4.8,
      opacity: 0.96, fillOpacity: 0.92,
    },
    tooltip_fields: ['node_id', 'degree', 'endpoint_count', 'component_id', 'candidate_facility_count', 'candidate_facility_roles'],
    tooltip_labels: { node_id: '拓扑节点 ID', degree: '连接度', endpoint_count: '吸附端点数', component_id: '连通分量', candidate_facility_count: '候选设施数', candidate_facility_roles: '候选设施角色' },
  },
  sourceNodes: {
    name: '原始参考 · Makani SW_NODE 设施点（8,614 个，不代表全部管线端点）', type: 'fgb', fgb: 'abu_dhabi_customer_stormwater_nodes_full.fgb',
    style: { color: '#fdf4ff', fillColor: '#d946ef', radius: 4, weight: 1, opacity: 0.95, fillOpacity: 0.86 },
    visible: false,
    tooltip_fields: ['UNITID', 'PointCode', 'Affiliation', 'GroundElev', 'WellBottomElev'],
    tooltip_labels: { UNITID: '设施 ID', PointCode: '物探点号', Affiliation: '附属物类型', GroundElev: '地面高程', WellBottomElev: '井底高程' },
  },
} as const;

const swmmResultCatalog = [
  { name: '节点最大水深', unit: 'm', geometry: '节点', field: 'max_water_depth_m' },
  { name: '节点最大溢流量', unit: 'm³/s', geometry: '节点', field: 'max_overflow_or_flooding_m3s' },
  { name: '管段最大流量', unit: 'm³/s', geometry: '管段', field: 'max_flow_m3s' },
  { name: '管段最大流速', unit: 'm/s', geometry: '管段', field: 'max_velocity_ms' },
  { name: '管段容量率', unit: '比例（0-1）', geometry: '管段', field: 'max_capacity_fraction' },
];

const swmmResultLayers = {
  citywideRuntime: {
    name: 'SWMM 全市连续网络运行状态（单个全市作业）',
    type: 'categorized',
    geojson: 'abu_dhabi_city_swmm_partition_runtime_status.geojson',
    category_column: 'runtime_status',
    category_colors: {
      completed: '#16a34a',
      completed_quality_warning: '#f59e0b',
      failed: '#dc2626',
      compiled_pending_runtime: '#f59e0b',
      blocked_no_eligible_internal_edges: '#6b7280',
    },
    legend_title: 'SWMM 全市作业运行状态',
    style: { min_radius: 8, max_radius: 15, weight: 2, color: '#111827', opacity: 0.95, fillOpacity: 0.85 },
    tooltip_fields: ['partition_label', 'runtime_status', 'hydraulic_result_status', 'node_count', 'internal_edge_count', 'routing_method', 'node_flooding_detected', 'failure_class', 'failure_explanation', 'calibration_status'],
    tooltip_labels: { partition_label: '计算分块', runtime_status: '运行状态', hydraulic_result_status: '水动力状态', node_count: '节点数', internal_edge_count: '内部管段数', routing_method: '路由方法', node_flooding_detected: '节点积水', failure_class: '失败分类', failure_explanation: '失败说明', calibration_status: '校准状态' },
  },
  citywidePartitions: {
    name: 'SWMM 全市连续网络编译覆盖',
    type: 'bubble',
    geojson: 'abu_dhabi_city_swmm_partition_status.geojson',
    value_column: 'partition_id',
    breaks: [1],
    color_scheme: 'YlGnBu',
    legend_title: 'SWMM 全市连续网络',
    style: { min_radius: 8, max_radius: 15, weight: 2, opacity: 0.95, fillOpacity: 0.85 },
    tooltip_fields: ['partition_label', 'compile_status', 'node_count', 'internal_edge_count', 'boundary_incident_edge_count', 'hydraulic_result_status', 'forcing_source', 'calibration_status'],
    tooltip_labels: { partition_label: '计算分块', compile_status: '输入状态', node_count: '节点数', internal_edge_count: '内部管段数', boundary_incident_edge_count: '跨块关联管段数', hydraulic_result_status: '水动力结果', forcing_source: '模型输入降雨来源', calibration_status: '校准状态' },
  },
  nodes: {
    name: 'SWMM 全市结果 · 客户节点最大水深（真实节点几何）',
    type: 'bubble',
    fgb: 'abu_dhabi_city_swmm_node_results.fgb',
    value_column: 'max_water_depth_m',
    breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 3],
    color_scheme: 'YlOrRd',
    legend_title: 'SWMM 节点最大水深（m）· 客户节点',
    style: { min_radius: 3, max_radius: 13, color: '#7f1d1d', fillOpacity: 0.72 },
    tooltip_fields: ['node_id', 'partition_id', 'max_water_depth_m', 'max_hydraulic_head_m', 'max_stored_volume_m3', 'max_total_inflow_m3s', 'max_overflow_or_flooding_m3s'],
    tooltip_labels: { node_id: '节点 ID', partition_id: '分区', max_water_depth_m: '最大水深（m）', max_hydraulic_head_m: '最大液压水头（m）', max_stored_volume_m3: '最大储存体积（m³）', max_total_inflow_m3s: '最大总入流（m³/s）', max_overflow_or_flooding_m3s: '最大溢流/积水（m³/s）' },
  },
  links: {
    name: 'SWMM 全市结果 · 客户管段最大容量率（真实管线几何）',
    type: 'choropleth',
    fgb: 'abu_dhabi_city_swmm_link_results.fgb',
    value_column: 'max_capacity_fraction',
    breaks: [0.1, 0.25, 0.5, 0.75, 0.9, 1],
    color_scheme: 'YlOrRd',
    legend_title: 'SWMM 管段最大容量率（比例）· 客户管线',
    style: { weight: 3, opacity: 0.9 },
    tooltip_fields: ['registered_pipeline_fid', 'swmm_link_id', 'partition_id', 'max_flow_m3s', 'max_velocity_ms', 'max_water_depth_m', 'max_capacity_fraction', 'max_flow_volume_m3'],
    tooltip_labels: { registered_pipeline_fid: '客户管段 FID', swmm_link_id: 'SWMM 管段 ID', partition_id: '分区', max_flow_m3s: '最大流量（m³/s）', max_velocity_ms: '最大流速（m/s）', max_water_depth_m: '最大管内水深（m）', max_capacity_fraction: '最大容量率', max_flow_volume_m3: '最大流量体积（m³）' },
  },
  nodeOverflow: {
    name: 'SWMM 诊断层 · 客户节点最大溢流/积水量',
    type: 'bubble',
    fgb: 'abu_dhabi_city_swmm_node_results.fgb',
    value_column: 'max_overflow_or_flooding_m3s',
    breaks: [0.0001, 0.001, 0.005, 0.01, 0.03],
    color_scheme: 'Reds',
    legend_title: '节点最大溢流/积水（m³/s）',
    style: { min_radius: 4, max_radius: 14, color: '#991b1b', fillOpacity: 0.76 },
    visible: false,
    tooltip_fields: ['node_id', 'partition_id', 'max_overflow_or_flooding_m3s', 'max_water_depth_m', 'max_total_inflow_m3s'],
    tooltip_labels: { node_id: '节点 ID', partition_id: '分区', max_overflow_or_flooding_m3s: '最大溢流/积水（m³/s）', max_water_depth_m: '最大水深（m）', max_total_inflow_m3s: '最大总入流（m³/s）' },
  },
  linkFlow: {
    name: 'SWMM 诊断层 · 客户管段最大流量/流速',
    type: 'choropleth',
    fgb: 'abu_dhabi_city_swmm_link_results.fgb',
    value_column: 'max_flow_m3s',
    breaks: [0.001, 0.005, 0.01, 0.03, 0.1],
    color_scheme: 'Blues',
    legend_title: '管段最大流量（m³/s）',
    style: { weight: 3, opacity: 0.9 },
    visible: false,
    tooltip_fields: ['registered_pipeline_fid', 'swmm_link_id', 'partition_id', 'max_flow_m3s', 'max_velocity_ms', 'max_capacity_fraction'],
    tooltip_labels: { registered_pipeline_fid: '客户管段 FID', swmm_link_id: 'SWMM 管段 ID', partition_id: '分区', max_flow_m3s: '最大流量（m³/s）', max_velocity_ms: '最大流速（m/s）', max_capacity_fraction: '最大容量率' },
  },
} as const;

const stageLayerKeys: Record<string, Array<keyof typeof customerMapLayers>> = {
  // Draw dense endpoint symbols first and the cyan pipe centerlines last.
  // Otherwise the ~238k endpoint circles completely cover short pipe
  // segments at neighborhood scale.
  data: ['nodes', 'network'],
  swmm: ['nodes', 'network'],
  surface: ['nodes', 'network'],
  gwm: [],
  validation: ['nodes', 'network'],
};

const stageResultLayerKeys: Record<string, Array<keyof typeof swmmResultLayers>> = {
  data: [],
  swmm: ['links', 'nodes', 'linkFlow', 'nodeOverflow', 'citywideRuntime', 'citywidePartitions'],
  surface: [],
  // GWM has its own result contract and must never fall back to SWMM layers.
  gwm: [],
  validation: ['links', 'nodes', 'linkFlow', 'nodeOverflow', 'citywideRuntime', 'citywidePartitions'],
};

type CustomerDtmDiagnostic = {
  maximum_depth: any;
  metadata: {
    timeline?: {
      available?: boolean;
      run_id?: string;
      endpoint?: string;
      time_values?: string[];
      elapsed_minutes?: number[];
      period_count?: number;
      step_minutes?: number;
      total_cell_count?: number;
      initial_time_index?: number;
    };
    [key: string]: any;
  };
};

type PublicCitywide2dDiagnostic = CustomerDtmDiagnostic;

function isCustomerDtmSurface(diagnostic: PublicCitywide2dDiagnostic | null | undefined): boolean {
  const metadata = diagnostic?.metadata || {};
  const sourceClass = String(metadata.surface_source_class || metadata.surface_evidence_class || '').toLowerCase();
  const source = String(metadata.surface_source || metadata.surface_product || '').toLowerCase();
  return sourceClass === 'customer_authoritative'
    || sourceClass.includes('customer')
    || source.includes('customer')
    || source.includes('dtm');
}

type HistoricalReplayValidation = {
  maximum_depth: any;
  metadata: {
    timeline?: {
      available?: boolean;
      run_id?: string;
      endpoint?: string;
      time_values?: string[];
      elapsed_minutes?: number[];
      period_count?: number;
      step_minutes?: number;
      total_cell_count?: number;
      initial_time_index?: number;
    };
    domain?: Record<string, any>;
    surface_product?: string;
    results?: Record<string, any>;
    coupling?: Record<string, any>;
    validation?: Record<string, any>;
    delivery_assets?: Array<Record<string, any>>;
    forcing?: Record<string, any>;
    [key: string]: any;
  };
};

type SentinelObservationMapPayload = {
  schema: string;
  status: string;
  event: { external_holdout: boolean; training_forbidden: boolean; satellite_observation_utc: string };
  observation: { observed_new_surface_water_area_m2: number; valid_observation_area_m2: number };
  geojson: { type: 'FeatureCollection'; features: any[] };
  feature_count: number;
  claim_boundary: string[];
};

type SentinelObservationDashboard = {
  status: string;
  event: {
    event_id: string;
    external_holdout: boolean;
    training_forbidden: boolean;
    satellite_observation_utc: string;
    observation_time_seconds_from_event_start: number;
  };
  forcing: {
    start_utc: string;
    source: string;
    support_point_count: number;
    zero_rainfall_tail_hours: number;
    nearest_300_second_model_frame_seconds: number;
  };
  observation: {
    source: string;
    before_date: string;
    after_date: string;
    valid_observation_area_m2: number;
    observed_new_surface_water_area_m2: number;
    valid_250m_cell_count: number;
    observed_flood_250m_cell_count: number;
    minimum_250m_valid_fraction: number;
    minimum_250m_observed_water_fraction: number;
    mndwi_change_threshold: number;
    valid_scl_classes: number[];
    water_condition: string;
  };
  scenes: {
    before: Array<{ item_id: string; datetime_utc: string; grid_code: string; cloud_cover_percent: number }>;
    after: Array<{ item_id: string; datetime_utc: string; grid_code: string; cloud_cover_percent: number }>;
  };
  external_comparison: {
    status: string;
    physics_replay: string;
    gwm_comparison: string;
    comparison: { iou: number; precision: number; recall: number } | null;
    gwm_metrics: { iou: number; precision: number; recall: number } | null;
  };
  assets: Array<{ kind: string; asset: string; available: boolean }>;
  receipt_sha256?: string;
};

function buildCustomerDtmMapLayers(diagnostic: CustomerDtmDiagnostic, includeTimeline: boolean) {
  const timeline = diagnostic.metadata?.timeline;
  const maximumDepth = {
    name: '二维结果 · 客户 dtm_5M 最大积水深度',
    type: 'choropleth' as const,
    geojsonData: diagnostic.maximum_depth,
    value_column: 'maximum_depth_m',
    breaks: [0.005, 0.05, 0.10, 0.20, 0.30, 0.50],
    color_scheme: 'Blues',
    legend_title: '二维最大积水深度（m）· 客户 DTM',
    style: { weight: 0.25, opacity: 0.75, fillOpacity: 0.78 },
    tooltip_fields: ['cell_id', 'maximum_depth_m', 'maximum_depth_time_seconds', 'final_depth_m'],
    tooltip_labels: {
      cell_id: '二维单元 ID',
      maximum_depth_m: '最大积水深度（m）',
      maximum_depth_time_seconds: '最大深度时刻（s）',
      final_depth_m: '末时刻积水深度（m）',
    },
  };
  if (!includeTimeline || !timeline?.available || !timeline.endpoint) return [maximumDepth];
  return [
    {
      name: '二维结果 · 客户 dtm_5M 动态地表水深',
      type: 'choropleth' as const,
      value_column: 'depth_m',
      breaks: [0.005, 0.05, 0.10, 0.20, 0.30, 0.50],
      color_scheme: 'Blues',
      legend_title: '二维动态积水深度（m）· 客户 DTM',
      style: { weight: 0.25, opacity: 0.78, fillOpacity: 0.82 },
      tooltip_fields: ['cell_id', 'time_hours', 'depth_m'],
      tooltip_labels: { cell_id: '二维单元 ID', time_hours: '模拟时间（h）', depth_m: '积水深度（m）' },
      scenarioTimeline: {
        runId: String(timeline.run_id || 'abu-dhabi-customer-dtm5m-anuga-20260905'),
        endpoint: String(timeline.endpoint),
        timeValues: Array.isArray(timeline.time_values) ? timeline.time_values : [],
        elapsedMinutes: Array.isArray(timeline.elapsed_minutes) ? timeline.elapsed_minutes : [],
        periodCount: Number(timeline.period_count || 0),
        totalNodeCount: Number(timeline.total_cell_count || 0),
        kind: 'surface-cell' as const,
      },
    },
  ];
}

function buildPublicCitywide2dMapLayers(diagnostic: PublicCitywide2dDiagnostic) {
  const timeline = diagnostic.metadata?.timeline;
  if (!timeline?.available || !timeline.endpoint) return [];
  const returnPeriod = Number(diagnostic.metadata?.return_period_years || 100);
  const customerSurface = isCustomerDtmSurface(diagnostic);
  const surfaceLabel = customerSurface ? '客户 5 m DTM' : 'Copernicus DEM GLO-30 公共 DEM';
  const resultQualifier = customerSurface ? '客户 DTM 主结果' : '公共 DEM 原型';
  return [
    {
      name: `二维结果 · ${surfaceLabel} 全市陆域最大积水深度 · ${returnPeriod} 年一遇`,
      type: 'choropleth' as const,
      geojsonData: diagnostic.maximum_depth,
      value_column: 'maximum_depth_m',
      breaks: [0.01, 0.05, 0.10, 0.20, 0.50, 1, 2, 3],
      color_scheme: 'Blues',
      legend_title: `全市陆域二维最大积水深度（m）· ${resultQualifier}`,
      style: { weight: 0.15, opacity: 0.72, fillOpacity: 0.76 },
      visible: false,
      tooltip_fields: ['cell_id', 'maximum_depth_m', 'maximum_depth_time_minutes', 'final_depth_m', 'land_fraction', 'permanent_water_fraction'],
      tooltip_labels: {
        cell_id: '二维单元 ID', maximum_depth_m: '最大积水深度（m）',
        maximum_depth_time_minutes: '最大深度时刻（分钟）', final_depth_m: '末时刻积水深度（m）',
        land_fraction: '陆地比例', permanent_water_fraction: '永久水体比例',
      },
    },
    {
      name: `二维结果 · ${surfaceLabel} 全市陆域动态积水深度 · ${returnPeriod} 年一遇`,
      type: 'choropleth' as const,
      value_column: 'depth_m',
      breaks: [0.01, 0.05, 0.10, 0.20, 0.50, 1, 2, 3],
      color_scheme: 'Blues',
      legend_title: `全市陆域二维动态积水深度（m）· ${resultQualifier}`,
      style: { weight: 0.15, opacity: 0.78, fillOpacity: 0.80 },
      tooltip_fields: ['cell_id', 'time_minutes', 'depth_m', 'land_fraction', 'permanent_water_fraction'],
      tooltip_labels: { cell_id: '二维单元 ID', time_minutes: '模拟时间（分钟）', depth_m: '积水深度（m）', land_fraction: '陆地比例', permanent_water_fraction: '永久水体比例' },
      scenarioTimeline: {
        runId: String(timeline.run_id || (customerSurface ? 'abu-dhabi-customer-dtm5m-citywide-anuga' : 'abu-dhabi-public-copernicus-citywide-anuga')),
        endpoint: String(timeline.endpoint),
        timeValues: Array.isArray(timeline.time_values) ? timeline.time_values : [],
        elapsedMinutes: Array.isArray(timeline.elapsed_minutes) ? timeline.elapsed_minutes : [],
        periodCount: Number(timeline.period_count || 0),
        totalNodeCount: Number(timeline.total_cell_count || 0),
        initialTimeIndex: Math.max(0, Math.min(
          Number.isInteger(timeline.initial_time_index) ? Number(timeline.initial_time_index) : 0,
          Math.max(0, Number(timeline.period_count || 0) - 1),
        )),
        kind: 'surface-cell' as const,
      },
    },
  ];
}

// The Abu Dhabi workbench was originally authored as a Chinese-first
// prototype. Keep its domain copy intact for Chinese users, while providing a
// deterministic English presentation for the customer demo. This dictionary
// deliberately covers both complete phrases and the common domain tokens used
// in dynamic run receipts, map labels, and validation messages.
const ABU_EN_REPLACEMENTS: Array<[string, string]> = [
  ['已接入 · 工程语义待确认', 'Integrated · engineering semantics pending confirmation'],
  ['客户管网与 5 m DTM 已接入并完成空间规范化；管径、高程、设施角色、泵站运行、潮位边界和历史观测仍需客户权威确认。', 'The customer network and 5 m DTM are integrated and spatially normalized; pipe diameter, elevation, facility roles, pump operations, tidal boundaries, and historical observations still require authoritative customer confirmation.'],
  ['当前一维结果来自单个全市连续网络 EPA SWMM 5.2.4 诊断作业；严格数值质量门未通过，结果未校准、未工程准入。', 'The current 1D result comes from one citywide continuous-network EPA SWMM 5.2.4 diagnostic run. The strict numerical quality gate did not pass; the result is neither calibrated nor engineering-admitted.'],
  ['EPA SWMM 诊断作业；严格数值质量门未通过，未校准、未工程准入，不构成城市级预测声明。', 'EPA SWMM diagnostic run; the strict numerical quality gate failed. It is not calibrated or engineering-admitted and does not constitute a citywide prediction claim.'],
  ['5 m DTM 输入 · 250 m 计算网格', '5 m DTM input · 250 m computational grid'],
  ['客户 5 m DTM 作为地形输入；已登记 2/5/10/25/50/100 年一遇 SWMM→ANUGA 单向成果，并有独立的 100 年一遇 SWMM–ANUGA 同步双向数值验证成果；两者均未工程准入。', 'The customer 5 m DTM is the terrain input. Registered assets include six 2/5/10/25/50/100-year one-way SWMM→ANUGA results and a separate 100-year synchronous two-way SWMM–ANUGA numerical-validation result; neither is engineering-admitted.'],
  ['公共 DEM 全市二维原型已接入', 'Public-DEM citywide 2D prototype connected'],
  ['客户 5 m DTM 作为地形输入，当前 ANUGA 2D 采用 250 m 计算网格并与 SWMM 单向耦合；多年一遇结果用于诊断与方案筛选，尚未完成观测校准。', 'The customer 5 m DTM is the terrain input. ANUGA 2D currently uses a 250 m computational grid with one-way coupling from SWMM; return-period results support diagnostics and option screening and have not been observation-calibrated.'],
  ['客户 5 m DTM 作为地形输入，ANUGA 2D 实际采用 250 m 计算网格并接受 SWMM 单向源项；2/5/10/25/50/100 年一遇结果可切换，但尚未完成观测校准和工程准入。', 'The customer 5 m DTM is the terrain input. ANUGA 2D actually uses a 250 m computational grid with one-way SWMM source terms. The 2/5/10/25/50/100-year results are selectable but have not completed observation calibration or engineering admission.'],
  ['历史事件 GWM R1 已接入 · 研究代理', 'Historical-event GWM R1 integrated · research emulator'],
  ['当前可调用版本为 GWM-R1-20260914：17 场训练事件，学习 250 m SWMM–ANUGA 物理标签；它不是直接由历史积水观测训练的工程预测模型。', 'The callable release is GWM-R1-20260914: 17 training events learning 250 m SWMM–ANUGA physics labels. It is not an engineering prediction model trained directly on observed historical inundation.'],
  ['继续用冻结模型开展独立事件外部检验；Sentinel-2 只作为云筛选后的积水观测证据，不作为实测水深 ground truth。', 'Continue independent-event external testing with the frozen model. Sentinel-2 is cloud-screened inundation evidence, not measured-depth ground truth.'],
  ['2024 年 4 月重构事件的 SWMM→ANUGA 回放和 Sentinel-2 外部观测链已接入；SWMM 严格质量门未通过，独立二维复核和工程准入仍待完成。', 'The reconstructed April 2024 SWMM→ANUGA replay and Sentinel-2 external-observation chain are integrated. The SWMM strict quality gate did not pass; independent 2D review and engineering admission remain incomplete.'],
  ['全市连续网络诊断 · 严格质量门未通过', 'Citywide continuous-network diagnostic · strict quality gate failed'],
  ['5 m DTM 输入 · 250 m 网格 · 单向耦合', '5 m DTM input · 250 m grid · one-way coupling'],
  ['5 m DTM · 250 m 网格 · 单向成果 + 双向验证成果', '5 m DTM · 250 m grid · one-way results + two-way validation result'],
  ['合成诊断适配已存在 · 未发现全市登记成果', 'Synthetic diagnostic adapter available · no registered citywide result found'],
  ['客户 5 m DTM 输入 · 250 m 网格 · 单向耦合 · 未校准', 'Customer 5 m DTM input · 250 m grid · one-way coupling · uncalibrated'],
  ['客户 5 m DTM · 250 m 网格 · 同步双向数值验证 · 未校准', 'Customer 5 m DTM · 250 m grid · synchronous two-way numerical validation · uncalibrated'],
  ['客户 5 m DTM · 250 m · 双向验证成果已加载', 'Customer 5 m DTM · 250 m · two-way validation result loaded'],
  ['尚未完成独立复核', 'Independent review incomplete'],
  ['研究代理层', 'Research-emulator layer'],
  ['17 场训练事件 · 模拟物理标签 · 未工程准入', '17 training events · emulates physics labels · not engineering-admitted'],
  ['工程语义、泵站、潮位和观测仍待确认', 'Engineering semantics, pumps, tides, and observations remain to be confirmed'],
  ['回放已接入 · 独立复核未完成', 'Replay integrated · independent review incomplete'],
  ['历史事件 GWM R1', 'Historical-event GWM R1'],
  ['研究推理可用 · 外部确认性验证未完成', 'Research inference available · confirmatory external validation incomplete'],
  ['客户 GDB 已接入并完成空间规范化，工程语义待确认', 'Customer GDB integrated and spatially normalized; engineering semantics remain to be confirmed'],
  ['客户 5 m DTM 输入、250 m 计算网格结果已接入', 'Customer 5 m DTM input and 250 m-grid result integrated'],
  ['ANUGA 2D · 客户 5 m DTM 输入 / 250 m 全市计算网格', 'ANUGA 2D · customer 5 m DTM input / 250 m citywide computational grid'],
  ['模型范围与适用边界', 'Model scope and fitness-for-use boundary'],
  ['工程语义', 'Engineering semantics'],
  ['待确认', 'Pending'],
  ['GWM R1（独立入口已接入）', 'GWM R1 (available in a separate workflow)'],
  ['SWMM 作业与诊断结果', 'SWMM run and diagnostic result'],
  ['技术详情与作业标识', 'Technical details and run identifier'],
  ['最近成功作业 Run ID', 'Latest successful run ID'],
  ['当前作业 Run ID', 'Current run ID'],
  ['路由连续性误差', 'Routing continuity error'],
  ['绝对值越接近 0 越好', 'Closer to zero in absolute value is better'],
  ['未通过', 'Failed'],
  ['历史事件 GWM R1 结果图层 · 当前状态', 'Historical-event GWM R1 result layers · current status'],
  ['历史事件 GWM R1 地图已刷新', 'Historical-event GWM R1 map refreshed'],
  ['SWMM 诊断地图已刷新', 'SWMM diagnostic map refreshed'],
  ['客户 5 m DTM 输入、250 m 网格结果已接入', 'Customer 5 m DTM input and 250 m-grid result integrated'],
  ['历史节点/管段诊断资产已接入', 'Historical node/link diagnostic asset integrated'],
  ['作业运行状态已接入', 'Run status integrated'],
  ['2024 历史重演 · 客户 5 m DTM 输入、250 m 网格积水结果', '2024 historical replay · customer 5 m DTM input and 250 m-grid inundation result'],
  ['阶段 5 诊断验证', 'Phase-5 diagnostic validation'],
  ['研究代理已接入', 'Research emulator integrated'],
  ['历史重演已接入', 'Historical replay connected'],
  ['EPA SWMM 诊断作业 · 节点级原生 OUT 时序', 'EPA SWMM diagnostic run · native OUT node time series'],
  ['部分几何覆盖', 'Partial geometry coverage'],
  ['完整几何覆盖', 'Complete geometry coverage'],
  ['历史事件 GWM R1 仅接受冻结模型与已登记降雨强迫；规则型情景筛选保留工程动作参数，两者结果和适用边界相互独立。', 'Historical-event GWM R1 accepts only the frozen model and registered rainfall forcing. Rule-based screening retains engineering action parameters; the two outputs and fitness-for-use boundaries are separate.'],
  ['正在推理历史事件 GWM R1…', 'Running historical-event GWM R1 inference…'],
  ['历史事件 GWM R1 时间轴已就绪', 'Historical-event GWM R1 timeline ready'],
  ['推理历史积水过程', 'Run historical inundation inference'],
  ['运行规则型情景筛选', 'Run rule-based scenario screening'],
  ['规则型情景筛选', 'Rule-based scenario screening'],
  ['规则筛选已接入', 'Rule-based screening integrated'],
  ['GWM 推演模式', 'GWM inference mode'],
  ['历史降雨场次', 'Historical rainfall event'],
  ['出水边界水位调整（m）', 'Outfall boundary level adjustment (m)'],
  ['二维历史事件', '2D historical event'],
  ['模型版本', 'Model release'],
  ['冻结研究代理', 'Frozen research emulator'],
  ['训练事件', 'Training events'],
  ['验证 / 盲测', 'Validation / blind test'],
  ['事件严格分离', 'Event-disjoint splits'],
  ['外部留出', 'External holdout'],
  ['禁止训练与调参', 'Excluded from training and tuning'],
  ['学习目标', 'Learning target'],
  ['历史事件 GWM R1 场次目录读取失败', 'Failed to read the historical-event GWM R1 event catalog'],
  ['历史事件 GWM R1 没有可推理的历史降雨场次', 'Historical-event GWM R1 has no available rainfall event for inference'],
  ['历史事件 GWM R1 推理提交失败', 'Failed to submit historical-event GWM R1 inference'],
  ['历史事件 GWM R1 返回缺少 run_id', 'Historical-event GWM R1 response is missing run_id'],
  ['历史事件 GWM R1 运行回执读取失败', 'Failed to read the historical-event GWM R1 run receipt'],
  ['历史事件 GWM R1 地图结果读取失败', 'Failed to read the historical-event GWM R1 map result'],
  ['历史事件 GWM R1 推理失败', 'Historical-event GWM R1 inference failed'],
  ['已恢复最近成功完成的 EPA SWMM 诊断作业；这不代表最近一次提交尝试成功', 'Restored the latest successfully completed EPA SWMM diagnostic run; this does not imply that the most recent submission attempt succeeded'],
  ['训练型推理使用冻结的 GWM-R1-20260914 与已登记历史降雨强迫；模型由 17 场训练事件学习 250 m SWMM–ANUGA 标签，不直接学习历史观测积水，也不接受规则型控制参数。', 'Trained inference uses frozen GWM-R1-20260914 and registered historical rainfall forcing. The model learns 250 m SWMM–ANUGA labels from 17 training events; it does not directly learn observed historical inundation or accept rule-based control parameters.'],
  ['诊断与外部验证阶段', 'Diagnostic and external-validation stage'],
  ['下一步：补齐权威工程属性与运行边界 → 修复 SWMM 数值质量 → 独立二维复核 → 冻结 GWM 确认性外部验证', 'Next: complete authoritative engineering attributes and operating boundaries → resolve SWMM numerical quality → independent 2D review → confirmatory external validation of the frozen GWM'],
  ['客户管段 FID', 'Customer pipe FID'],
  ['起点拓扑 ID', 'Source topology node ID'],
  ['终点拓扑 ID', 'Target topology node ID'],
  ['重算长度（m）', 'Recomputed length (m)'],
  ['管径候选值', 'Candidate diameter'],
  ['管材', 'Pipe material'],
  ['管线状态', 'Pipe status'],
  ['拓扑节点 ID', 'Topology node ID'],
  ['连接度', 'Node degree'],
  ['吸附端点数', 'Snapped endpoint count'],
  ['连通分量', 'Connected component'],
  ['候选设施数', 'Candidate facility count'],
  ['候选设施角色', 'Candidate facility roles'],
  ['客户 5 m DTM', 'Customer 5 m DTM'],
  ['客户 DTM 主结果', 'customer DTM primary result'],
  ['Copernicus DEM GLO-30 公共 DEM', 'Copernicus DEM GLO-30 public DEM'],
  ['Copernicus DEM GLO-30 公共代理', 'Copernicus DEM GLO-30 public proxy'],
  ['客户 5 m DTM 全市二维结果已接入', 'Customer 5 m DTM citywide 2D result connected'],
  ['客户 5 m DTM 全市多年一遇结果已接入', 'Customer 5 m DTM citywide return-period results connected'],
  ['客户提供的 5 m DTM 已驱动全市 ANUGA 2D 多年一遇结果；2/5/10/25/50/100 年一遇均可切换，结果包含最大深度和动态地表水深。', 'The customer-provided 5 m DTM drives the citywide ANUGA 2D return-period results. The 2/5/10/25/50/100-year scenarios are selectable, with maximum depth and dynamic surface-water depth outputs.'],
  ['客户 5 m DTM 全市陆域多年一遇结果', 'Customer 5 m DTM citywide land-surface return-period result'],
  ['客户 5 m DTM 多年一遇结果已接入', 'Customer 5 m DTM return-period results connected'],
  ['客户 5 m DTM 主结果', 'customer 5 m DTM primary result'],
  ['客户 5 m DTM 阶段 3 基线', 'Customer 5 m DTM phase-3 baseline'],
  ['Copernicus DEM GLO-30 阶段 3 回退基线', 'Copernicus DEM GLO-30 phase-3 fallback baseline'],
  ['客户 5 m DTM + ANUGA 2D 全市地表结果', 'Customer 5 m DTM + ANUGA 2D citywide surface result'],
  ['客户 5 m DTM 驱动的 ANUGA 2D 全市多年一遇结果', 'customer 5 m DTM-driven ANUGA 2D citywide return-period result'],
  ['当前地图主图层来自客户 5 m DTM 驱动的 ANUGA 2D 全市多年一遇结果，使用 250 m 计算网格；ESA WorldCover 2021 陆海掩膜已应用，海域不接受降雨且不输出为城市积水。时间轴可播放陆域积水演变。', 'The primary map layer is the customer 5 m DTM-driven ANUGA 2D citywide return-period result on a 250 m grid. The ESA WorldCover 2021 land/water mask is applied: sea cells receive no rainfall and are not published as urban flooding. The timeline plays land-surface flood evolution.'],
  ['二维地表结果已接入（客户 5 m DTM）', '2D surface result connected (customer 5 m DTM)'],
  ['客户 5 m DTM + ANUGA 2D 全市地表结果', 'Customer 5 m DTM + ANUGA 2D citywide surface result'],
  ['客户 5 m DTM 全市二维结果已接入：', 'Customer 5 m DTM citywide 2D result connected: '],
  ['模拟时间（h）', 'Simulation time (h)'],
  ['模拟时间（分钟）', 'Simulation time (minutes)'],
  ['积水深度（m）', 'Flood depth (m)'],
  ['最大积水深度（m）', 'Maximum flood depth (m)'],
  ['最大深度时刻（分钟）', 'Time of maximum depth (minutes)'],
  ['末时刻积水深度（m）', 'Final-time flood depth (m)'],
  ['时间（分钟）', 'Time (minutes)'],
  // Phase-3 invocation and registered-result workspace. Keep these labels in
  // the explicit dictionary: the old catch-all fallback turned the entire
  // Chinese field into "model metadata" in the English UI.
  ['二维地表水动力工作区', '2D surface-hydrodynamics workspace'],
  ['二维模型调用', '2D model invocation'],
  ['已算结果', 'Precomputed results'],
  ['提交后会在独立私有目录中真实启动 ANUGA 2D，不覆盖已登记成果。当前这个 Web 新建作业器只开放二维面雨直接驱动；已算结果中同时保留 SWMM→ANUGA 单向成果和 SWMM–ANUGA 同步双向数值验证成果。LISFLOOD-FP 已有合成诊断适配器，但尚未核实到可加载的阿布扎比全市成果。', 'Submitting creates a real ANUGA 2D run in a separate private directory without overwriting registered results. The web job creator currently supports direct 2D rainfall forcing only. Registered results retain the one-way SWMM→ANUGA products and the synchronous two-way SWMM–ANUGA numerical-validation product. LISFLOOD-FP has a synthetic diagnostic adapter, but no loadable Abu Dhabi citywide result has been verified.'],
  ['求解器与一维输入', 'Solver and 1D input'],
  ['能力状态与作业来源', 'Capability status and job source'],
  ['二维求解器', '2D solver'],
  ['ANUGA 2D（当前可新建作业）', 'ANUGA 2D (new jobs available)'],
  ['LISFLOOD-FP（合成诊断已适配，全市作业器未接入）', 'LISFLOOD-FP (synthetic diagnostic adapter; citywide job runner not connected)'],
  ['阶段 2 输入作业', 'Phase-2 input job'],
  ['本次新算：二维面雨直接驱动', 'New run: direct 2D rainfall forcing'],
  ['已登记 SWMM OUT（仅已有成果）', 'Registered SWMM OUT (precomputed results only)'],
  ['耦合方式', 'Coupling mode'],
  ['二维面雨直接驱动', 'Direct 2D rainfall forcing'],
  ['单向交换（已算成果可加载）', 'One-way exchange (precomputed result can be loaded)'],
  ['同步双向交换（已算验证成果可加载；Web 新算器未接入）', 'Synchronous two-way exchange (validated result can be loaded; web runner not connected)'],
  ['计算范围', 'Computational domain'],
  ['阿布扎比全市登记范围', 'Registered Abu Dhabi citywide domain'],
  ['降雨强迫', 'Rainfall forcing'],
  ['2022 官方 Zone B DDF + 明示雨型假设', '2022 official Zone B DDF + explicit hyetograph assumptions'],
  ['Zone B 官方 DDF 设计暴雨', 'Official Zone B DDF design storm'],
  ['峰值位置（%）', 'Peak position (%)'],
  ['当前 2 年一遇 180 分钟总雨量为', 'The current 2-year, 180-minute rainfall total is'],
  ['当前 5 年一遇 180 分钟总雨量为', 'The current 5-year, 180-minute rainfall total is'],
  ['当前 10 年一遇 180 分钟总雨量为', 'The current 10-year, 180-minute rainfall total is'],
  ['当前 25 年一遇 180 分钟总雨量为', 'The current 25-year, 180-minute rainfall total is'],
  ['当前 50 年一遇 180 分钟总雨量为', 'The current 50-year, 180-minute rainfall total is'],
  ['当前 100 年一遇 180 分钟总雨量为', 'The current 100-year, 180-minute rainfall total is'],
  ['5 分钟交替块时程和峰值位置是建模假设。', 'The 5-minute alternating-block hyetograph and peak position are modeling assumptions.'],
  ['地形、网格与糙率', 'Terrain, grid and roughness'],
  ['新算参数写入运行回执', 'New-run parameters are written to the run receipt'],
  ['地形产品', 'Terrain product'],
  ['客户 AUH_DTM 5 m（主输入）', 'Customer AUH_DTM 5 m (primary input)'],
  ['公开回退', 'Public fallback'],
  ['计算网格（m）', 'Computational grid (m)'],
  ['快速诊断', 'Rapid diagnostic'],
  ['登记基线', 'Registered baseline'],
  ['高分辨率（Web 调用暂未开放）', 'High resolution (not available from the web runner)'],
  ['陆地 Manning n', 'Land Manning n'],
  ['水体 Manning n', 'Water Manning n'],
  ['初始水深（m）', 'Initial depth (m)'],
  ['最小发布水深（m）', 'Minimum published depth (m)'],
  ['交换与重复计量控制', 'Exchange and double-counting controls'],
  ['当前新算为面雨模式，耦合参数锁定', 'The new run uses direct rainfall forcing; coupling parameters are locked'],
  ['SWMM→二维交换变量', 'SWMM-to-2D exchange variable'],
  ['节点 overflow / flooding 流量', 'Node overflow / flooding flow'],
  ['动态水头反向反馈', 'Dynamic head feedback'],
  ['本次新算关闭（双向已算成果可在右侧页面加载）', 'Disabled for this new run (the precomputed two-way result can be loaded in the results view)'],
  ['进水口有效开口面积（m²）', 'Effective inlet opening area (m²)'],
  ['单点最大交换流量（m³/s）', 'Maximum exchange flow at one point (m³/s)'],
  ['避免 SWMM 汇水区与二维面雨重复计量（耦合成果中启用）', 'Avoid double-counting SWMM subcatchments and 2D rainfall (enabled in coupled products)'],
  ['边界与运行设置', 'Boundary and run settings'],
  ['模拟总时长 = 降雨历时 + 雨后计算', 'Total simulation duration = rainfall duration + post-rainfall simulation'],
  ['边界类型', 'Boundary type'],
  ['外边界固定水位', 'Fixed stage at the outer boundary'],
  ['海边界水位（m）', 'Sea-boundary level (m)'],
  ['永久水体比例阈值', 'Permanent-water fraction threshold'],
  ['总模拟时长（分钟）', 'Total simulation duration (minutes)'],
  ['二维作业与结果回执', '2D job and result receipt'],
  ['提交二维计算', 'Submit 2D calculation'],
  ['正在运行 ANUGA 2D…', 'Running ANUGA 2D…'],
  ['当前二维 Run ID', 'Current 2D Run ID'],
  ['计算网格', 'Computational grid'],
  ['参数验收', 'Parameter acceptance'],
  ['地形与网格准备', 'Terrain and grid preparation'],
  ['ANUGA 水动力求解', 'ANUGA hydrodynamic solve'],
  ['最大深度与时间轴发布', 'Maximum-depth and timeline publication'],
  ['已完成或正在执行', 'Completed or in progress'],
  ['等待前序步骤', 'Waiting for preceding steps'],
  ['已进入', 'Entered'],
  ['待处理', 'Pending'],
  ['新算结果写入独立私有目录；诊断用途，未校准、未工程准入，不覆盖已登记成果。', 'New-run results are written to a separate private directory for diagnostics; they are not calibrated or engineering-admitted and do not overwrite registered results.'],
  ['设置二维水动力参数', 'Configure 2D hydrodynamic parameters'],
  ['提交后这里会显示 Run ID、求解状态、网格与结果摘要；完成后最大深度和动态时间轴会自动发送到地图。', 'After submission, this panel shows the Run ID, solver status, grid and result summary; maximum depth and the dynamic timeline are sent to the map when complete.'],
  ['已登记的二维成果', 'Registered 2D results'],
  ['单向多年一遇成果与 100 年一遇同步双向数值验证成果独立保留；加载只读成果和回执，不会启动新计算。', 'One-way return-period products and the 100-year synchronous two-way numerical-validation product are retained separately. Loading a read-only result and receipt does not start a new calculation.'],
  ['成果来源', 'Result source'],
  ['SWMM→ANUGA 单向多年一遇（6 套）', 'One-way SWMM→ANUGA return-period products (6)'],
  ['SWMM–ANUGA 同步双向验证（100 年一遇）', 'Synchronous two-way SWMM–ANUGA validation (100-year event)'],
  ['单向', 'One-way'],
  ['同步双向验证', 'Synchronous two-way validation'],
  ['节点溢流 → 二维源项', 'Node overflow → 2D source term'],
  ['个陆域单元', 'land-surface cells'],
  ['海边界', 'Sea boundary'],
  ['永久水体阈值', 'Permanent-water threshold'],
  ['百万 m³', 'million m³'],
  ['加载二维结果…', 'Loading 2D result…'],
  ['正在加载二维结果…', 'Loading 2D result…'],
  ['加载到地图', 'Load onto map'],
  ['正在读取最大深度、时间轴与运行回执…', 'Reading maximum depth, timeline and run receipt…'],
  ['已选择成果来源，点击“加载到地图”读取成果', 'A result source is selected. Click “Load onto map” to read the product.'],
  ['求解器', 'Solver'],
  ['地形 / 网格', 'Terrain / grid'],
  ['输出', 'Output'],
  ['模拟时长', 'Simulation duration'],
  ['最大积水深度', 'Maximum flood depth'],
  ['淹没面积 ≥ 0.01 m', 'Inundated area ≥ 0.01 m'],
  ['淹没面积 ≥ 0.05 m', 'Inundated area ≥ 0.05 m'],
  ['同步交换窗口', 'Synchronous exchange windows'],
  ['交换接口', 'Exchange interfaces'],
  ['窗口', 'window'],
  ['客户管网节点与二维单元', 'Customer network nodes and 2D cells'],
  ['登记成果运行回执', 'Registered-result run receipt'],
  ['能力边界', 'Capability boundary'],
  ['该成果的回执记录了同步窗口中的正向与反向交换，可作为 SWMM–ANUGA 双向数值验证成果使用；但回执单独不能证明每个时间窗都重新调用了原生 SWMM，且完整 SWMM 系统质量平衡未在该动态 API 回执中评估。结果未校准、未工程准入。', 'The receipt records forward and reverse exchange in the synchronous windows, so this product can be used as a SWMM–ANUGA two-way numerical-validation result. The receipt alone does not prove that native SWMM was re-invoked in every window, and the full SWMM system mass balance was not evaluated in this dynamic API receipt. The result is not calibrated or engineering-admitted.'],
  ['这六套多年一遇成果使用已完成的 SWMM 原生 OUT 作为 ANUGA 单向源项，没有动态水头反向反馈；结果未校准、未工程准入。', 'These six return-period products use completed native SWMM OUT data as one-way ANUGA source terms with no dynamic head feedback. The results are not calibrated or engineering-admitted.'],
  ['输出决策支持报告', 'Open decision-support report'],
  ['正在生成报告…', 'Generating report…'],
  ['正在生成阶段 5 决策支持报告…', 'Generating phase 5 decision-support report…'],
  ['打开阶段 5 决策支持报告', 'Open phase 5 decision-support report'],
  // Complete UI sentences must be translated before token-level fallbacks.
  // Keeping these phrases here also covers text returned by the SWMM receipt
  // and prevents the presentation layer from producing mixed-language copy.
  ['SWMM 进程已完成；结果资产仍可播放。严格门失败检查：', 'The SWMM process completed; result assets remain playable. Strict-gate failures: '],
  ['SWMM 进程已返回；结果资产仍可播放。严格门失败检查：', 'The SWMM process returned; result assets remain playable. Strict-gate failures: '],
  ['选择重现期后会自动读取对应 ANUGA 2D 最大深度和时间轴；无需额外点击加载。完成后地图会自动刷新，时间轴从首个时间片开始可播放。', 'Selecting a return period automatically reads the matching ANUGA 2D maximum-depth result and timeline; no separate load action is required. When complete, the map refreshes automatically and the timeline can play from the first time slice.'],
  ['当前结果由接口元数据确定；加载完成后显示模拟时长、时间片和时间步长。', 'The current result is defined by service metadata. After loading, the simulation duration, time slices, and time step are shown below.'],
  ['正在读取历史重演结果并准备地图和时间轴…', 'Reading the historical replay result and preparing the map and timeline…'],
  ['历史重演已加载；地图和时间轴已就绪。需要重新发送图层时，使用“在地图上展示当前阶段”。', 'Historical replay loaded; the map and timeline are ready. Use “Show current stage on map” only to resend the layers.'],
  ['历史重演尚未加载；可点击“加载 / 刷新历史重演结果”重试。', 'Historical replay is not loaded. Select “Load / refresh historical replay result” to retry.'],
  ['二维结果响应格式无效，未找到最大深度图层。', 'The 2D result response is invalid; no maximum-depth layer was returned.'],
  ['这不是页面加载错误：动态波路由在部分时间步内未达到严格收敛要求。当前结果保留用于历史过程回放和问题定位；修正管网高程、几何、时间步或边界条件后再重新计算。', 'This is not a page-loading error: dynamic-wave routing did not meet the strict convergence requirement at some time steps. The current result is retained for historical replay and diagnosis; recalculate after correcting network elevations, geometry, time steps, or boundary conditions.'],
  ['查看 SWMM 数值检查详情', 'View SWMM numerical check details'],
  ['检查项', 'Check'],
  ['观测值 / 阈值', 'Observed / threshold'],
  ['状态', 'Status'],
  ['未收敛时间步比例', 'Non-converging step percentage'],
  ['SWMM 报告不含错误', 'No SWMM report errors'],
  ['管段稳定性', 'Link stability'],
  ['产流连续性误差', 'Runoff continuity error'],
  ['汇流连续性误差', 'Routing continuity error'],
  ['数值格式：百分比检查显示“观测值 / 阈值”；管段稳定性显示布尔值。', 'Formatting: percentage checks show “observed / threshold”; link stability shows boolean values.'],
  ['客户数据到达后先运行回执验收与事件时序预检。', 'After customer data arrives, run receipt validation and the event time-series pre-check first.'],
  ['最大容量率', 'Maximum capacity fraction'],
  ['此前的 30 个数字只是内部计算组织，不是客户正式排水分区，也不再作为全市结果来源。地图主结果使用客户真实节点和管线几何；内部计算组织仅用于调试和资源调度。', 'The former 30 labels were internal compute organization, not official customer drainage districts, and are not used as the source of citywide results. Map results use customer actual node and pipe geometry; internal compute organization is used only for debugging and resource scheduling.'],
  ['按钮会真实调用 EPA SWMM 5.2.4 的全市连续网络并保存原生 RPT / OUT；设计暴雨可直接使用 2022 年官方 Zone B DDF 的 2/5/10/25/50/100 年一遇、180 分钟雨量。DDF 表未给出完整时间雨型，当前 5 分钟交替块分配和 40% 峰值位置属于明确建模假设。结果未校准、未工程准入。', 'This action invokes EPA SWMM 5.2.4 on the continuous citywide network and stores native RPT / OUT. Design storms use the 2022 official Zone B DDF depths for 2/5/10/25/50/100-year return periods at 180 minutes. The DDF table does not publish a complete hyetograph; the 5-minute alternating-block allocation and 40% peak position are explicit modeling assumptions. Results are not calibrated or engineering-admitted.'],
  ['节点级结果来自本次 EPA SWMM 原生 OUT 时序，地图每帧加载全部 ${totalNodeCount.toLocaleString()} 个节点（含零值节点），可按 ${nativeTimeline.reportStepMinutes} 分钟报告步播放；降雨输入：${rainfallSource}。', 'Node-level results come from the native EPA SWMM OUT time series. Every map frame loads all ${totalNodeCount.toLocaleString()} nodes, including zero-value nodes, and can play at the ${nativeTimeline.reportStepMinutes}-minute report step. Rainfall input: ${rainfallSource}.'],
  ['本次 SWMM 原生 RPT 的节点最大水深和节点溢流结果已回挂客户真实节点几何；降雨输入：${rainfallSource}；分区汇总仅作为辅助层。', 'Maximum node depth and overflow from the native SWMM RPT are joined to customer actual node geometry. Rainfall input: ${rainfallSource}. Partition summaries are auxiliary only.'],
  ['堵塞', 'blockage'],
  ['管线能力', 'pipe capacity'],
  ['${scenario.returnPeriodYears} 年一遇预计算结果尚未找到。', '${scenario.returnPeriodYears}-year return-period precomputed result was not found.'],
  ['加载 ${scenario.returnPeriodYears} 年一遇预计算结果', 'Load ${scenario.returnPeriodYears}-year return-period precomputed result'],
  ['${payload.features.length} 个全市作业状态标记 · ${completed} 已完成 · ${failed} 运行失败', '${payload.features.length} citywide job-status markers · ${completed} completed · ${failed} failed'],
  ['客户真实节点/管线几何', 'Customer actual node/pipe geometry'],
  ['本次真实 SWMM 情景已接入原生 OUT 时间轴，共 ${Number(scenarioMapPayload.metadata?.total_node_result_count || scenarioMapPayload.metadata?.timeline?.total_node_count || 0).toLocaleString()} 个节点；地图每个时间片均加载全部节点（含零值节点），没有按阈值或数量截断。可在 2D/3D 地图底部播放，节点溢流/积水层可在图层控制中打开。', 'The current real SWMM scenario is connected to the native OUT timeline with ${Number(scenarioMapPayload.metadata?.total_node_result_count || scenarioMapPayload.metadata?.timeline?.total_node_count || 0).toLocaleString()} nodes. Every time slice loads all nodes, including zero-value nodes, without threshold or count truncation. Play it from the bottom timeline in the 2D/3D map; the node overflow/flooding layer can be enabled in layer controls.'],
  ['${Number(scenarioMapPayload.metadata?.total_node_result_count || scenarioMapPayload.metadata?.timeline?.total_node_count || 0).toLocaleString()} 个客户节点 · 每帧包含零值节点 · 水深、水头、入流和溢流/积水速率 · 无展示截断', '${Number(scenarioMapPayload.metadata?.total_node_result_count || scenarioMapPayload.metadata?.timeline?.total_node_count || 0).toLocaleString()} customer nodes · every frame includes zero-value nodes · depth, head, inflow, and overflow/flooding rate · no display truncation'],
  ['EPA SWMM 5.2.4 产流与管网水力', 'EPA SWMM 5.2.4 runoff and network hydraulics'],
  ['当前已切换为单个全市连续网络 SWMM 诊断；保留跨内部计算组织的可用连接，结果仍需工程校准。', 'The current diagnostic uses one continuous citywide SWMM network; usable cross-partition connections are retained, and engineering calibration is still required.'],
  ['替换客户权威单位、高程、边界和事件强迫后再做校准。', 'Calibrate after replacing proxy units, elevations, boundaries, and event forcing with authoritative customer values.'],
  ['与 SWMM 的体积交换对账', 'SWMM volume-exchange reconciliation'],
  ['完成地表数据、源项和边界映射后进入真实事件二维验证。', 'Enter real-event 2D validation after surface data, source terms, and boundary mappings are complete.'],
  ['GWM 学习已验收的传统模型状态和观测，不替代物理模型作为工程权威。', 'GWM learns validated traditional-model states and observations; it does not replace the physical models as the engineering authority.'],
  ['最终输出面向防涝调度、工程改造、风险分区和应急响应，所有结论绑定证据等级。', 'Final outputs support flood-control operations, engineering upgrades, risk zoning, and emergency response; every conclusion is bound to an evidence level.'],
  ['Zone B 官方 DDF 交替块雨型（2022）', 'Zone B official DDF alternating-block hyetograph (2022)'],
  ['将总量、时长和雨型转换为 5 分钟强迫', 'Convert depth, duration, and hyetograph into 5-minute forcing'],
  ['加载全市连续网络基线并叠加受控动作', 'Load the continuous citywide network baseline and apply controlled actions'],
  ['准备节点、管段和地表结果的时间轴', 'Prepare the time axis for node, link, and surface results'],
  ['真实 SWMM 作业完成后接入动态结果图层', 'Connect dynamic result layers after the real SWMM job completes'],
  ['阿布扎比暴雨内涝世界模型 · 客户空间结果与 SWMM 诊断', 'Abu Dhabi Stormwater Flood World Model · customer spatial results and SWMM diagnostics'],
  ['客户真实节点/管线几何 + EPA SWMM 全市连续网络最大值；当前为 Open-Meteo 公开代理降雨、未校准、未工程准入。', 'Customer actual node/pipe geometry + EPA SWMM continuous-citywide-network maxima; current forcing is Open-Meteo public proxy rainfall, not calibrated or engineering-admitted.'],
  ['客户 GDB 输入资产 + 全市连续网络 SWMM 编译覆盖；动态水动力结果尚未生成。', 'Customer GDB input assets + continuous-citywide-network SWMM compile coverage; dynamic hydraulic results have not been generated.'],
  ['真实 SWMM 诊断', 'Real SWMM diagnostics'],
  ['真实 EPA SWMM 诊断运行', 'Real EPA SWMM diagnostic run'],
  ['使用', 'using '],
  ['城市级预测声明', 'citywide prediction claim'],
  ['未校准', 'not calibrated'],
  ['未工程准入', 'not engineering-admitted'],
  ['不构成', 'does not constitute'],
  ['小时公开数据', 'hourly public data'],
  ['按模型 5 分钟步长展开', 'expanded to the model 5-minute step'],
  ['仅用于原型代理', 'for prototype proxy use only'],
  ['排水情景', 'drainage scenario'],
  ['调整基线', 'adjust the baseline'],
  ['不修改', 'without modifying '],
  ['客户原始', 'customer original '],
  ['当前基线', 'current baseline'],
  ['实际未应用', 'not applied'],
  ['降雨输入', 'rainfall input'],
  ['来源读取中', 'reading source'],
  ['模型输入时间窗', 'model input window'],
  ['个失败', 'failed'],
  ['个作业失败，失败原因保留在运行回执。', 'jobs failed; failure reasons are retained in the run receipt.'],
  ['个全市作业已执行', 'citywide jobs executed'],
  ['个全市连续网络作业已完成', 'citywide continuous-network jobs completed'],
  ['个全市连续网络作业已完成', 'citywide continuous-network jobs completed'],
  ['高风险情景回到传统模型复核', 'High-risk scenarios return to traditional-model review'],
  ['影响与方案优先级', 'Impact and plan priorities'],
  ['原生 RPT', 'native RPT'],
  ['原生 OUT', 'native OUT'],
  ['时间轴', 'timeline'],
  ['每帧加载全部节点', 'every frame loads all nodes'],
  ['含零值节点', 'including zero-value nodes'],
  ['没有按阈值或数量截断', 'without threshold or count truncation'],
  ['可在 2D/3D 地图底部播放', 'play it from the bottom timeline of the 2D/3D map'],
  ['节点溢流/积水层可在图层控制中打开', 'the node overflow/flooding layer can be enabled in layer controls'],
  ['共', 'with '],
  ['地图', 'map'],
  ['每个时间片', 'every time slice'],
  ['均加载', 'loads '],
  ['全部节点', 'all nodes'],
  ['零值节点', 'zero-value nodes'],
  ['没有按阈值或数量截断', 'without threshold or count truncation'],
  ['可在', 'play it from '],
  ['地图底部', 'the map timeline'],
  ['打开', 'enabled'],
  ['诊断链路可运行', 'Diagnostic pipeline available'],
  ['真实 EPA SWMM 诊断运行；未校准、未工程准入，不构成城市级预测声明。', 'Real EPA SWMM diagnostic run; not calibrated or engineering-admitted, and it does not constitute a citywide prediction claim.'],
  ['基线管网 · 泵站参数已提交，但当前基线无泵站链接，实际未应用', 'Baseline network · pump parameters submitted, but the current baseline has no pump links; not applied'],
  ['基线管网 · 泵站停用（当前基线无泵站链接）', 'Baseline network · pumps disabled (the current baseline has no pump links)'],
  ['泵站参数已提交，但当前基线无泵站链接', 'Pump parameters submitted, but the current baseline has no pump links'],
  ['泵站停用', 'Pumps disabled'],
  ['2022 官方 Zone B DDF 雨量与假设交替块时程', '2022 official Zone B DDF depth and assumed alternating-block hyetograph'],
  ['真实 SWMM 情景运行失败；请查看运行回执。', 'The real SWMM scenario failed; review the run receipt.'],
  ['真实 EPA SWMM 诊断运行；仍需工程校准和准入。', 'Real EPA SWMM diagnostic run; engineering calibration and admission are still required.'],
  ['真实 EPA SWMM 诊断运行；严格数值质量门未通过，未校准、未工程准入。', 'Real EPA SWMM diagnostic run; the strict numerical quality gate did not pass, and the run is not calibrated or engineering-admitted.'],
  ['地图主图层是客户真实节点和管线上的全市连续网络 SWMM 诊断输出；内部计算组织只用于调度，不改变水力拓扑。', 'The primary map layer is continuous-citywide-network SWMM diagnostics on customer actual nodes and pipes; internal compute organization is used only for scheduling and does not change hydraulic topology.'],
  ['当前地图主图层来自本次真实 EPA SWMM OUT 的节点结果，并已回挂客户真实节点几何；它是全市连续网络诊断结果，仍未校准、未工程准入。', 'The primary map layer comes from node results in this real EPA SWMM OUT and is joined to customer actual node geometry; it is a continuous-citywide-network diagnostic result, not calibrated or engineering-admitted.'],
  ['全市连续网络输入已编译；正式结果将回挂客户真实节点和管线几何。', 'The continuous-citywide-network inputs are compiled; formal results will be joined to customer actual node and pipe geometry.'],
  ['已接入公开代理 SWMM 诊断结果：Open-Meteo 72 小时、EPA SWMM 5.2.4；仅用于原型闭环，未校准、未工程准入。', 'Public-proxy SWMM diagnostic results connected: Open-Meteo 72 hours and EPA SWMM 5.2.4; prototype loop only, not calibrated or engineering-admitted.'],
  ['未检测到本地私有客户图层，地图保持空白；请先生成受控 GDB 派生预览。', 'No local private customer layers were detected; the map remains blank. Generate a controlled GDB derivative preview first.'],
  ['点击阶段查看输入、输出与下一步', 'Select a stage to view inputs, outputs, and the next action'],
  ['数值质量通过不等于工程校准通过。', 'Passing numerical quality does not mean engineering calibration has passed.'],
  ['下一批数据到达后：回执验收 → 事件预检 → SWMM 边界绑定 → 工程复核', 'After the next data delivery: receipt validation → event pre-check → SWMM boundary binding → engineering review'],
  ['原始输入资产与 SWMM 结果', 'Raw input assets and SWMM results'],
  ['原始资产是 SWMM 的空间输入；节点和管段结果是模型计算输出并回挂到客户真实几何。结果字段包含水深、流量、流速和容量率，并保留事件与校准声明。', 'Raw assets are spatial inputs to SWMM; node and link results are model outputs joined to customer actual geometry. Result fields include depth, flow, velocity, and capacity fraction, with event and calibration claims retained.'],
  ['运行后这里会显示生成的雨型摘要、动作叠加和 SWMM 动态作业状态。', 'The generated hyetograph summary, applied actions, and dynamic SWMM job status will appear here after a run.'],
  ['阿布扎比暴雨内涝世界模型', 'Abu Dhabi Stormwater Flood World Model'],
  ['阿布扎比暴雨内涝世界模型 · GWM 快速推演', 'Abu Dhabi Stormwater Flood World Model · GWM rapid rollout'],
  ['GWM 基线', 'GWM baseline'],
  ['GWM 干预', 'GWM intervention'],
  ['GWM 影响差值', 'GWM intervention delta'],
  ['GWM 基线最大积水深度（m）', 'GWM baseline maximum flood depth (m)'],
  ['GWM 干预积水深度（m）', 'GWM intervention flood depth (m)'],
  ['GWM 干预相对基线变化（m）', 'GWM intervention change from baseline (m)'],
  ['二维单元 ID', '2D cell ID'],
  ['阶段 3 源深度（m）', 'Phase-3 source depth (m)'],
  ['空间响应倍率', 'Spatial response factor'],
  ['行动敏感度', 'Action sensitivity'],
  ['水域主导单元', 'Water-dominated cell'],
  ['基线深度（m）', 'Baseline depth (m)'],
  ['干预深度（m）', 'Intervention depth (m)'],
  ['变化量（m）', 'Change (m)'],
  ['基线积水深度（m）', 'Baseline flood depth (m)'],
  ['不确定性（m）', 'Uncertainty (m)'],
  ['陆地有效单元', 'active land cells'],
  ['水域单元', 'water cells'],
  ['排水改善面积', 'drainage improvement area'],
  ['峰值地表蓄水量变化', 'peak surface storage change'],
  ['排除水域网格', 'excluded water cells'],
  ['基线受影响网格', 'baseline affected cells'],
  ['干预受影响网格', 'intervention affected cells'],
  ['面积与蓄水量为基于网格的代理指标', 'area and storage are grid-based proxy metrics'],
  ['个陆域有效单元', 'active land cells'],
  ['个水域单元', 'water cells'],
  ['城市暴雨内涝世界模型', 'Urban Stormwater Flood World Model'],
  ['暴雨内涝世界模型', 'Stormwater Flood World Model'],
  ['模型分区口径更正', 'Model partition terminology correction'],
  ['情景模拟输入', 'Scenario inputs'], ['情景模拟', 'Scenario simulation'],
  ['当前项目快照', 'Current project snapshot'], ['原始输入资产与 SWMM 结果', 'Raw input assets and SWMM results'],
  ['从数据到决策', 'From data to decisions'], ['模型流程视图', 'Model workflow view'],
  ['模型分工', 'Model responsibilities'], ['协作关系', 'Collaboration'], ['交付物', 'Deliverables'],
  ['准入闸门', 'Admission gates'], ['当前项目状态', 'Current project status'],
  ['客户数据等待阶段', 'Waiting for customer data'], ['等待客户补充', 'Waiting for customer data'],
  ['诊断可运行', 'Diagnostic run available'], ['等待地表数据', 'Waiting for surface data'], ['客户 DTM 局部诊断已接入', 'Customer DTM local diagnostic connected'], ['全市公共 DEM 原型已接入', 'Full-city public DEM prototype connected'],
  ['正式训练关闭', 'Formal training closed'], ['等待独立事件', 'Waiting for an independent event'],
  ['等待事件数据', 'Waiting for event data'], ['尚未准入', 'Not admitted'], ['关闭', 'Closed'], ['已完成', 'Completed'], ['完成', 'Completed'], ['完成但有告警', 'Completed with warnings'],
  ['排队中', 'Queued'], ['运行中', 'Running'], ['失败', 'Failed'], ['尚未运行', 'Not run'],
  ['完成·质量告警', 'Completed · quality warning'], ['运行中/待接入', 'Running / pending integration'],
  ['运行失败', 'Run failed'], ['无失败分区', 'No failed partitions'], ['全市', 'Citywide'],
  ['全市连续网络', 'Citywide continuous network'], ['计算分块', 'Compute partition'], ['分区', 'Partition'],
  ['客户真实', 'Customer actual'], ['客户', 'Customer'], ['规范化', 'normalized'], ['原始输入', 'Raw input'],
  ['雨水管线', 'stormwater pipes'], ['雨水节点', 'stormwater nodes'], ['管线', 'pipes'], ['管段', 'links'], ['节点', 'nodes'],
  ['一维产流与管网水力', '1D runoff and network hydraulics'], ['二维地表积水扩散', '2D surface flood spreading'], ['二维独立交叉验证', 'Independent 2D cross-check'],
  ['ANUGA 主链路 + 双向验证成果 + LISFLOOD-FP 诊断适配', 'ANUGA primary chain + two-way validation result + LISFLOOD-FP diagnostic adapter'],
  ['ANUGA 主链路 + LISFLOOD-FP 复核', 'ANUGA primary chain + LISFLOOD-FP cross-check'],
  ['快速 rollout 与筛选', 'Rapid rollouts and screening'], ['GWM 正式训练', 'Formal GWM training'], ['传统模型与 GWM 对照', 'Traditional-model and GWM comparison'],
  ['快速推演层', 'Rapid rollout layer'], ['运行失败', 'Run failed'], ['失败原因按分区查看', 'View failure reasons by partition'],
  ['客户权威数据完整', 'Customer authoritative data complete'], ['SWMM 工程校准', 'SWMM engineering calibration'], ['二维真实事件', 'Real 2D event'], ['城市级预测声明', 'Citywide prediction claim'],
  ['最大水深（m）', 'Maximum depth (m)'], ['最大流速（m/s）', 'Maximum velocity (m/s)'], ['最大液压水头（m）', 'Maximum hydraulic head (m)'], ['最大管内水深（m）', 'Maximum pipe depth (m)'],
  ['最大储存体积（m³）', 'Maximum stored volume (m³)'], ['最大流量体积（m³）', 'Maximum flow volume (m³)'], ['最大流量（m³/s）', 'Maximum flow (m³/s)'], ['最大总入流（m³/s）', 'Maximum total inflow (m³/s)'],
  ['最大溢流/积水（m³/s）', 'Maximum overflow/flooding (m³/s)'], ['节点最大溢流/积水（m³/s）', 'Maximum node overflow/flooding (m³/s)'], ['节点最大溢流量', 'Maximum node overflow'],
  ['节点最大水深（m）', 'Maximum node depth (m)'], ['节点最大水深', 'Maximum node depth'], ['管段最大流速', 'Maximum link velocity'], ['管段最大流量', 'Maximum link flow'], ['管段容量率', 'Link capacity fraction'],
  ['外排量（百万升）', 'Outflow (million litres)'], ['洪涝损失（百万升）', 'Flooding loss (million litres)'], ['累计溢流量（百万升）', 'Cumulative overflow (million litres)'], ['积水时长（小时）', 'Flooding duration (hours)'],
  ['液压水头（m）', 'Hydraulic head (m)'], ['模拟经过（分钟）', 'Elapsed simulation (minutes)'], ['当前节点水深（m）', 'Current node depth (m)'], ['当前溢流量（m³/s）', 'Current overflow (m³/s)'],
  ['峰值位置', 'Peak position'], ['最大水深时刻', 'Time of maximum depth'], ['节点 ID', 'Node ID'], ['SWMM 管段 ID', 'SWMM link ID'], ['客户管段 FID', 'Customer link FID'],
  ['均匀雨型', 'Uniform hyetograph'], ['前峰雨型', 'Front-loaded hyetograph'], ['交替块雨型', 'Alternating-block hyetograph'], ['地图动画回挂', 'Map animation integration'], ['生成雨型预览', 'Generated hyetograph preview'], ['输出时序状态', 'Output time-series state'], ['绑定 SWMM 情景', 'Bind SWMM scenario'], ['生成降雨时序', 'Generate rainfall time series'],
  ['DEM / DSM 与垂直基准', 'DEM / DSM and vertical datum'], ['道路路缘和建筑阻水', 'Road curbs and building blockage'], ['客户数据与工程问题回执', 'Customer data and engineering issue receipt'], ['最终哈希清单与准入声明', 'Final hash manifest and admission statement'],
  ['全市连续网络诊断（拓扑保真）', 'Citywide continuous-network diagnostics (topology preserved)'], ['SWMM 输入、RPT / OUT 与动态状态', 'SWMM inputs, RPT / OUT, and dynamic state'], ['二维积水深度、范围和持续时间', '2D flood depth, extent, and duration'], ['SWMM-ANUGA 体积交换对账', 'SWMM-ANUGA volume exchange reconciliation'],
  ['最大积水深度和范围', 'Maximum flood depth and extent'], ['积水持续时间与退水', 'Flooding duration and recession'], ['道路与设施影响', 'Road and facility impacts'], ['独立历史暴雨', 'Independent historical storm'], ['水位、流量、积水观测', 'Water-level, flow, and flood observations'],
  ['严格质量门', 'Strict quality gate'], ['质量门', 'Quality gate'], ['通过', 'Passed'], ['告警', 'Warning'], ['是', 'Yes'], ['否', 'No'], ['暂无', 'Unavailable'], ['默认', 'Default'], ['比例', 'Ratio'],
  ['1 个作业', '1 run'], ['0 / 11 工程问题关闭', '0 / 11 engineering issues closed'], ['客户规范化管线', 'Normalized customer pipes'], ['客户规范化节点', 'Normalized customer nodes'], ['客户真实几何已接入', 'Customer actual geometry connected'], ['本次节点结果已接入', 'Current node results connected'],
  ['仅运行状态已接入', 'Runtime status only'], ['公开代理局部原型已接入', 'Public-proxy local prototype connected'], ['统计已接入', 'Statistics connected'], ['诊断已接入', 'Diagnostics connected'], ['待运行', 'Pending run'], ['未生成 / 未准入', 'Not generated / not admitted'],
  ['泵站', 'pumps'], ['泵闸', 'pumps and gates'], ['出水边界', 'outfall boundary'], ['边界水位', 'boundary level'],
  ['排水情景动作', 'Drainage scenario actions'], ['管线作用范围', 'Pipe action scope'], ['堵塞率', 'Blockage (%)'],
  ['管线能力倍率', 'Pipe capacity multiplier'], ['泵站启用', 'Pumps enabled'], ['泵站能力倍率', 'Pump capacity multiplier'],
  ['自由出水', 'Open outfall'], ['固定水位边界', 'Fixed-level boundary'], ['无管线调整', 'No pipe adjustment'],
  ['重点管廊', 'Priority corridor'], ['选定区域', 'Selected zone'], ['模型输入降雨数据', 'Model rainfall input'],
  ['降雨来源', 'Rainfall source'], ['在线公开来源降雨数据', 'Online public rainfall data'], ['参数化设计暴雨', 'Parametric design storm'],
  ['客户权威历史降雨时序', 'Customer authoritative historical rainfall time series'], ['公开来源纬度', 'Public source latitude'],
  ['公开来源经度', 'Public source longitude'], ['模拟范围', 'Simulation scope'], ['目标计算分块', 'Target compute partition'],
  ['降雨时长', 'Rainfall duration'], ['总降雨量', 'Total rainfall'], ['时间雨型', 'Temporal rainfall pattern'],
  ['设计重现期', 'Design return period'], ['年一遇', '-year return period'], ['峰值位置', 'Peak position'],
  ['空间分布', 'Spatial distribution'], ['全市均匀', 'Uniform citywide'], ['分区降雨系数', 'Zonal rainfall factor'],
  ['雨后计算', 'Post-rainfall simulation'], ['运行设置', 'Run settings'], ['输出间隔', 'Output interval'],
  ['运行引擎', 'Run engine'], ['默认', 'Default'], ['恢复默认', 'Restore defaults'], ['设置降雨和排水情景', 'Set rainfall and drainage scenario'],
  ['运行后这里会显示生成的雨型摘要、动作叠加和 SWMM 动态作业状态。', 'The generated hyetograph summary, actions, and dynamic SWMM run status will appear here after a run.'],
  ['一维雨水管网', '1D stormwater network'], ['二维地表水动力', '2D surface hydrodynamics'], ['GWM 快速推演层', 'GWM rapid rollout layer'],
  ['验证与交付', 'Validation and delivery'], ['传统模型', 'Traditional models'], ['快速推演层', 'Rapid rollout layer'],
  ['决策输出', 'Decision outputs'], ['物理基线', 'Physical baseline'], ['主二维链路', 'Primary 2D chain'], ['复核模型', 'Cross-check model'], ['代理层', 'Surrogate layer'],
  ['输入', 'Inputs'], ['输出', 'Outputs'], ['下一动作', 'Next action'], ['阶段可推进', 'stages available'],
  ['客户规范化管线', 'Normalized customer pipes'], ['客户规范化节点', 'Normalized customer nodes'], ['空间参考', 'Spatial reference'], ['问题', 'issues'],
  ['节点最大水深', 'Maximum node water depth'], ['节点最大溢流量', 'Maximum node overflow'], ['节点最大溢流/积水量', 'Maximum node overflow/flooding'],
  ['管段最大流量', 'Maximum link flow'], ['管段最大流速', 'Maximum link velocity'], ['管段容量率', 'Link capacity fraction'], ['比例', 'Ratio'],
  ['SWMM 全市连续网络运行状态', 'SWMM citywide network runtime status'], ['SWMM 全市连续网络编译覆盖', 'SWMM citywide network compile coverage'],
  ['SWMM 全市结果', 'SWMM citywide results'], ['SWMM 诊断层', 'SWMM diagnostic layer'], ['客户节点最大水深', 'Customer node maximum water depth'],
  ['客户管段最大容量率', 'Customer link maximum capacity fraction'], ['真实节点几何', 'actual node geometry'], ['真实管线几何', 'actual pipe geometry'],
  ['运行状态', 'Runtime status'], ['水动力状态', 'Hydraulic status'], ['节点数', 'Node count'], ['内部管段数', 'Internal link count'], ['路由方法', 'Routing method'],
  ['节点积水', 'Node flooding'], ['失败分类', 'Failure class'], ['失败说明', 'Failure explanation'], ['校准状态', 'Calibration status'],
  ['输入状态', 'Input status'], ['跨块关联管段数', 'Cross-partition link count'], ['水动力结果', 'Hydraulic result'], ['模型输入降雨来源', 'Model rainfall source'],
  ['最大水深', 'Maximum depth'], ['当前节点水深', 'Current node depth'], ['模拟时刻', 'Simulation time'], ['模拟经过', 'Elapsed simulation'], ['液压水头', 'Hydraulic head'],
  ['当前溢流量', 'Current overflow'], ['最大溢流量', 'Maximum overflow'], ['积水时长', 'Flooding duration'], ['累计溢流量', 'Cumulative overflow'], ['最大水深时刻', 'Time of maximum depth'],
  ['分区洪涝损失', 'Partition flooding loss'], ['外排量', 'External outflow'], ['洪涝损失', 'Flooding loss'], ['路由连续性误差', 'Routing continuity error'],
  ['质量门', 'Quality gate'], ['严格质量门', 'Strict quality gate'], ['通过', 'Passed'], ['告警', 'Warning'], ['是', 'Yes'], ['否', 'No'],
  ['无展示截断', 'No display truncation'], ['全量接入', 'Fully integrated'], ['诊断已接入', 'Diagnostic integrated'], ['统计已接入', 'Statistics integrated'], ['待运行', 'Pending run'], ['暂无', 'Unavailable'],
  ['地图当前显示', 'Currently shown on map'], ['SWMM 结果图层', 'SWMM result layers'], ['本次情景地图已刷新', 'Scenario map refreshed'], ['全市节点/管段结果已接入', 'Citywide node/link results integrated'],
  ['计算分块运行状态已接入', 'Compute partition runtime status integrated'], ['全市输入已编译 / 结果待运行', 'Citywide inputs compiled / results pending'], ['公开代理原型 / 未准入', 'Public proxy prototype / not admitted'], ['未生成 / 未准入', 'Not generated / not admitted'],
  ['当前阶段暂无可展示的结果空间图层', 'No result spatial layer is available for this stage'], ['暂无已接入的客户真实图层', 'No customer layers integrated'],
  ['结果阶段已隐藏原始管网，避免遮挡结果；切换到数据阶段可查看原始输入。', 'Raw network is hidden during result stages to avoid obscuring results; switch to the data stage to view raw inputs.'],
  ['在地图上展示当前阶段', 'Show current stage on map'], ['重新发送当前阶段图层到地图', 'Resend current stage layers to map'],
  ['客户输入、积水热点与模型结果', 'Customer inputs, flood hotspots, and model results'],
  ['客户静态积水热点（506）', 'Customer static flood hotspots (506)'],
  ['客户积水热点优先级', 'Customer flood-hotspot priority'],
  ['已加载客户静态积水热点', 'Loaded customer static flood hotspots: '],
  ['该图层表示客户已知易涝点，不代表当前事件积水、发生时间或实测水深。', 'This layer represents customer-known flood-prone locations, not current-event inundation, occurrence time, or measured flood depth.'],
  ['客户积水热点图层未加载', 'Customer flood-hotspot layer was not loaded'],
  ['完整性校验未通过', 'integrity validation failed'],
  ['客户积水热点是独立的静态参考图层；原始管网资产是 SWMM 的空间输入，节点和管段结果是模型计算输出并回挂到客户真实几何。', 'Customer flood hotspots are an independent static reference layer. Raw network assets are spatial inputs to SWMM, while node and link results are model outputs joined back to customer geometry.'],
  ['静态参考 · 非事件观测', 'Static reference · not an event observation'],
  ['客户积水热点图层不可用', 'Customer flood-hotspot layer unavailable'],
  ['正在校验客户积水热点图层…', 'Validating the customer flood-hotspot layer...'],
  ['热点 ID', 'Hotspot ID'], ['优先级', 'Priority'], ['区域 / 管理中心', 'Area / management center'], ['地点描述', 'Location description'],
  ['证据类别', 'Evidence class'], ['事件关联', 'Event linkage'], ['来源版本', 'Source version'], ['非常重要', 'Very Important'], ['重要', 'Important'],
  ['原始资产是 SWMM 的空间输入', 'Raw assets are spatial inputs to SWMM'], ['节点和管段结果是模型计算输出并回挂到客户真实几何', 'Node and link results are model outputs joined back to customer geometry'],
  ['本次真实 SWMM 情景', 'Current SWMM scenario'], ['本次真实 SWMM 情景 · 全量节点级时序结果', 'Current SWMM scenario · complete node-level time series'],
  ['本次真实 SWMM 情景 · 节点最大水深', 'Current SWMM scenario · maximum node depth'], ['本次真实 SWMM 情景 · 节点溢流/积水', 'Current SWMM scenario · node overflow/flooding'], ['本次真实 SWMM 情景 · 分区汇总（辅助）', 'Current SWMM scenario · partition summary (auxiliary)'],
  ['从权威数据、物理模拟到 GWM 快速推演的全流程工作台。', 'An end-to-end workspace from authoritative data and physical simulation to GWM rapid rollouts.'],
  ['工程校准未准入', 'Engineering calibration not admitted'], ['2024-04 历史重演已接入', 'Apr 2024 historical replay connected'], ['阶段可推进', 'stages available'],
  ['客户 GDB 空间已核验', 'Customer GDB geometry verified'], ['事件与校准数据仍待准入', 'Event and calibration data pending admission'],
  ['口径更正：全市结果来自单个连续网络 SWMM 作业。', 'Clarification: citywide results come from one continuous SWMM network run.'],
  ['按钮会真实调用 EPA SWMM', 'This action invokes EPA SWMM'], ['结果未校准、未工程准入。', 'Results are not calibrated or engineering-admitted.'],
  ['当前为公开代理诊断结果', 'Current results use a public proxy for diagnostics'], ['客户权威事件、边界和校准数据到达后', 'After customer authoritative event, boundary, and calibration data arrive'],
  ['下一批数据到达后', 'After the next data delivery'], ['回执验收', 'receipt validation'], ['事件预检', 'event pre-check'], ['边界绑定', 'boundary binding'], ['工程复核', 'engineering review'],
  ['全部计算分块', 'All compute partitions'], ['计算分块', 'Compute partition'], ['官方输入', 'Official input'], ['官方', 'official'], ['分钟', 'minutes'], ['小时', 'hours'], ['个', ''], ['条', ''],
  ['全市连续网络（单个 SWMM 作业）', 'Citywide continuous network (one SWMM job)'], ['内部调试分块（不作为全市结果）', 'Internal debug partitions (not citywide results)'],
  ['原始输入 · 客户雨水管线（规范化全量，238,287 条）', 'Raw input · customer stormwater pipes (normalized full set, 238,287 features)'],
  ['原始输入 · 客户雨水节点（规范化全量，238,350 个）', 'Raw input · customer stormwater nodes (normalized full set, 238,350 features)'],
  ['模型输入 · 客户 GDB 雨水管线（规范化全量，238,287 条）', 'Model input · customer GDB stormwater pipes (normalized full set, 238,287 features)'],
  ['模型输入 · 管线端点拓扑节点（0.1 m 吸附派生，238,350 个）', 'Model input · pipe-endpoint topology nodes (0.1 m snap-derived, 238,350 features)'],
  ['模型输入 · 客户 GDB 雨水管线（全量 MVT，238,287 条）', 'Model input · customer GDB stormwater pipes (full MVT, 238,287 features)'],
  ['模型输入 · 管线端点拓扑节点（全量 MVT，238,350 个）', 'Model input · pipe-endpoint topology nodes (full MVT, 238,350 features)'],
  ['模型输入 · 客户 GDB 雨水管线（全量 MVT，高对比显示，238,287 条）', 'Model input · customer GDB stormwater pipes (full high-contrast MVT, 238,287 features)'],
  ['模型输入 · 管线端点拓扑节点（全量 MVT，默认高亮，238,350 个）', 'Model input · pipe-endpoint topology nodes (full MVT, highlighted by default, 238,350 features)'],
  ['原始参考 · Makani SW_NODE 设施点（8,614 个，不代表全部管线端点）', 'Source reference · Makani SW_NODE facilities (8,614 features, not all pipe endpoints)'],
  ['拓扑节点 ID', 'Topology node ID'], ['连接度', 'Degree'], ['吸附端点数', 'Snapped endpoint count'], ['连通分量', 'Connected component'],
  ['候选设施数', 'Candidate facility count'], ['候选设施角色', 'Candidate facility roles'], ['起点拓扑 ID', 'Source topology ID'], ['终点拓扑 ID', 'Target topology ID'],
  ['重算长度（m）', 'Recomputed length (m)'], ['管径候选值', 'Candidate diameter'], ['管材', 'Pipe material'], ['管线状态', 'Pipe status'],
  ['设施 ID', 'Facility ID'], ['物探点号', 'Survey point code'], ['附属物类型', 'Affiliation'], ['地面高程', 'Ground elevation'], ['井底高程', 'Well-bottom elevation'],
  ['降雨时长（分钟）', 'Rainfall duration (minutes)'], ['降雨历时（分钟）', 'Rainfall duration (minutes)'], ['雨后计算（分钟）', 'Post-rainfall simulation (minutes)'], ['输出间隔（分钟）', 'Output interval (minutes)'], ['边界水位（m）', 'Boundary level (m)'],
  ['堵塞率（%）', 'Blockage (%)'], ['出水边界', 'Outfall boundary'], ['自由出水（诊断）', 'Open outfall (diagnostic)'], ['固定水位边界', 'Fixed-level boundary'],
  ['EPA SWMM 5.2.4（当前）', 'EPA SWMM 5.2.4 (current)'], ['SWMM + 二维（待准入）', 'SWMM + 2D (pending admission)'], ['GWM 快速推演（待训练）', 'GWM rapid rollout (training pending)'],
  ['真实 SWMM 作业与结果', 'Real SWMM job and results'], ['生成雨型预览', 'Generated hyetograph preview'], ['模型输入时间窗', 'Model input window'], ['节点积水作业', 'Node-flooding jobs'], ['真实 SWMM 报告', 'Real SWMM report'],
  ['全市作业进度', 'Citywide job progress'], ['本次降雨总量', 'Rainfall total for this run'], ['模型开始时间（UTC）', 'Model start time (UTC)'],
  ['无管线调整（基线）', 'No pipe adjustment (baseline)'], ['百万升 · 全市连续网络', 'million litres · citywide continuous network'],
  ['ANUGA 2D · 客户 dtm_5M 最大积水深度', 'ANUGA 2D · customer dtm_5M maximum flood depth'],
  ['500 m × 500 m 局部诊断 · 2,500 个二维单元 · 结果未校准、未工程准入', '500 m × 500 m local diagnostic · 2,500 surface cells · not calibrated or engineering-admitted'],
  ['全市连续网络运行状态', 'Citywide continuous-network runtime status'], ['局部诊断已接入', 'Local diagnostic connected'],
  ['全市连续网络编译覆盖', 'Citywide continuous-network compile coverage'], ['全市原型已接入', 'Full-city prototype connected'],
  ['分区降雨系数（后端接入）', 'Zonal rainfall factor (backend integration pending)'],
  ['已加载预计算的全市连续网络基线情景', 'Loaded the precomputed citywide continuous-network baseline scenario'],
  ['Copernicus DEM GLO-30 已完成全市 ANUGA 2D 原型；客户 dtm_5M.tif 仍作为局部诊断参考。全市真实事件模拟仍依赖权威 DTM、垂直基准、道路路缘、建筑阻水和观测。', 'Copernicus DEM GLO-30 supports the citywide ANUGA 2D prototype; customer dtm_5M.tif remains a local diagnostic reference. A citywide real-event simulation still requires an authoritative DTM and vertical datum, road curbs, building blockage, and observations.'],
  ['开始', 'Start'], ['结束', 'End'], ['状态', 'Status'], ['百万升', 'million litres'], ['已接入', 'Connected'], ['未知', 'Unknown'],
  ['官方 DDF 总量 + 假设时间分配', 'Official DDF depth + assumed temporal allocation'], ['参数化设计暴雨，不是实测雨量曲线', 'Parametric design storm, not an observed rainfall curve'],
  ['质量守恒、边界和物理验证', 'Mass conservation, boundaries, and physical validation'], ['学习已验收状态，筛选候选情景', 'Learn validated states and screen candidate scenarios'], ['高风险情景回到传统模型复核', 'High-risk scenarios return to traditional-model review'],
  ['GWM 不能绕过物理模型、观测验证和不确定性门控', 'GWM cannot bypass physical models, observation validation, or uncertainty gates'],
  ['原始资产是 SWMM 的空间输入；节点和管段结果是模型计算输出并回挂到客户真实几何。结果字段包含水深、流量、流速和容量率，并保留事件与校准声明。', 'Raw assets are spatial inputs to SWMM; node and link results are model outputs joined to customer actual geometry. Result fields include depth, flow, velocity, and capacity fraction, with event and calibration claims retained.'],
  ['内部计算组织仅用于调试和资源调度', 'Internal compute organization is used only for debugging and resource scheduling'], ['此前的 30 个数字只是内部计算组织', 'The former 30 labels were internal compute organization'],
  ['不是客户正式排水分区', 'not official customer drainage districts'], ['也不再作为全市结果来源', 'and are not used as the source of citywide results'],
  ['SWMM 全市连续网络运行状态（单个全市作业）', 'SWMM citywide continuous-network runtime status (one citywide job)'], ['SWMM 全市连续网络运行状态（仅辅助）', 'SWMM citywide continuous-network runtime status (auxiliary only)'],
  ['SWMM 全市作业运行状态', 'SWMM citywide job runtime status'], ['SWMM 全市连续网络编译覆盖', 'SWMM citywide continuous-network compile coverage'],
  ['SWMM 节点最大水深（m）· 客户节点', 'SWMM maximum node depth (m) · customer nodes'], ['SWMM 管段最大容量率（比例）· 客户管线', 'SWMM maximum link capacity fraction (ratio) · customer pipes'],
  ['SWMM 诊断层 · 客户节点最大溢流/积水量', 'SWMM diagnostic layer · customer maximum node overflow/flooding'], ['SWMM 诊断层 · 客户管段最大流量/流速', 'SWMM diagnostic layer · customer maximum link flow/velocity'],
  ['客户管段最大容量率', 'Customer maximum link capacity fraction'], ['当前为 Open-Meteo 公开代理降雨', 'Current forcing is Open-Meteo public proxy rainfall'], ['当前强迫为 Open-Meteo 公开代理降雨', 'Current forcing is Open-Meteo public proxy rainfall'],
  ['已接入客户真实节点/管线几何上的全市连续网络 SWMM 最大值', 'Citywide continuous-network SWMM maxima joined to customer actual node/pipe geometry'], ['已接入全市连续网络运行状态', 'Citywide continuous-network runtime status connected'],
  ['已接入公开代理 SWMM 诊断结果', 'Public-proxy SWMM diagnostic results connected'], ['全市连续网络输入已编译', 'Citywide continuous-network inputs are compiled'], ['正式结果将回挂客户真实节点和管线几何', 'Formal results will be joined to customer actual node and pipe geometry'],
  ['当前阶段暂无可展示的结果空间图层', 'No result spatial layer is available for the current stage'], ['当前地图图层和结果状态', 'Current map layers and result status'], ['结果字段包含水深、流量、流速和容量率', 'Result fields include depth, flow, velocity, and capacity fraction'],
  ['模型分区口径更正', 'Model partition terminology correction'], ['城市降雨内涝情景模拟', 'Urban rainfall-flood scenario simulation'], ['设置降雨和排水情景', 'Set rainfall and drainage scenario'],
  ['本次模型输入降雨数据', 'Rainfall input for this run'], ['来源读取中', 'Reading source'], ['本次真实 SWMM 情景', 'Current real SWMM scenario'],
  ['城市降雨内涝情景模拟', 'Urban rainfall-flood scenario simulation'],
  ['数据与准入', 'Data and admission'], ['权威数据、元数据、哈希和工程语义', 'Authoritative data, metadata, hashes, and engineering semantics'],
  ['客户管网已完成私有派生审计', 'The customer network has passed the private derivative audit'],
  ['事件降雨、潮位、观测和工程字段仍需客户回执验收', 'Event rainfall, tide levels, observations, and engineering fields still require customer receipt validation'],
  ['客户雨水管网 GDB', 'Customer stormwater network GDB'], ['事件降雨 / 雷达 QPE', 'Event rainfall / radar QPE'],
  ['高程与垂直基准', 'Elevation and vertical datum'], ['泵闸、潮位和观测', 'Pumps, gates, tide levels, and observations'],
  ['字段映射与问题清单', 'Field mapping and issue list'], ['客户回执自动验收', 'Automated customer receipt validation'],
  ['来源、版本、时效和 SHA-256', 'Source, version, freshness, and SHA-256'],
  ['管段、节点和设施拓扑', 'Link, node, and facility topology'], ['汇水区与雨水口绑定', 'Subcatchment and inlet bindings'],
  ['降雨时序', 'Rainfall time series'], ['泵闸与出水边界', 'Pump/gate and outfall boundaries'],
  ['节点水深、入流和溢流', 'Node depth, inflow, and overflow'], ['管段流量、流速和容量率', 'Link flow, velocity, and capacity fraction'],
  ['质量门与原生 RPT / OUT', 'Quality gates and native RPT / OUT'],
  ['最大积水深度和范围', 'Maximum flood depth and extent'], ['积水持续时间与退水', 'Flooding duration and recession'],
  ['二维模型负责地表积水扩散、道路汇流和建筑阻水', 'The 2D model handles surface-water spreading, road conveyance, and building blockage'],
  ['真实事件模拟依赖 DEM、道路路缘和观测', 'Real-event simulation depends on DEM, road curbs, and observations'],
  ['二维边界与糙率', '2D boundaries and roughness'], ['地表进水与回灌关系', 'Surface inflow and return-flow relationships'],
  ['积水风险图和影响清单', 'Flood-risk maps and impact lists'], ['传统模型与 GWM 对照', 'Traditional-model and GWM comparison'],
  ['可追溯交付包与准入声明', 'Traceable delivery bundle and admission statement'],
  ['状态表示、情景筛选和不确定性门控', 'State representation, scenario screening, and uncertainty gating'],
  ['SWMM / ANUGA 多事件状态', 'Multi-event SWMM / ANUGA states'], ['观测掩码与质量掩码', 'Observation and quality masks'],
  ['降雨、潮位和操作动作', 'Rainfall, tide levels, and operating actions'], ['图结构与空间特征', 'Graph structure and spatial features'],
  ['快速情景 rollout', 'Rapid scenario rollouts'], ['分布外检测与不确定性', 'Out-of-distribution detection and uncertainty'],
  ['候选方案筛选与回退信号', 'Candidate-plan screening and fallback signals'],
  ['独立事件、影响叠加和工程决策', 'Independent events, impact overlay, and engineering decisions'],
  ['独立历史暴雨', 'Independent historical storms'], ['水位、流量、积水观测', 'Water-level, flow, and flood observations'],
  ['道路与设施影响', 'Road and facility impacts'], ['工程方案与运行约束', 'Engineering options and operating constraints'],
  ['完成多事件校准、盲测和不确定性门控后才允许正式训练', 'Formal training is allowed only after multi-event calibration, blind testing, and uncertainty gating'],
  ['通过独立事件盲测后，才可形成城市级预测或方案优化声明', 'Citywide prediction or plan-optimization claims require independent-event blind testing'],
  ['SWMM 诊断层', 'SWMM diagnostic layer'], ['客户管段最大容量率', 'Customer link maximum capacity fraction'],
  ['SWMM 全市作业运行状态', 'SWMM citywide job runtime status'], ['SWMM 全市连续网络编译覆盖', 'SWMM citywide continuous-network compile coverage'],
  ['客户 GDB 的私有格式派生几何', 'Private-format derived geometry from the customer GDB'],
  ['尚未检测到客户 GDB 派生图层', 'No customer GDB derivative layers detected'],
  ['请先生成受控 GDB 派生预览', 'Generate a controlled GDB derivative preview first'],
  ['客户 GDB 输入资产', 'Customer GDB input assets'], ['全市连续网络诊断结果', 'Citywide continuous-network diagnostic results'],
  ['不是分区面或积水点', 'Not partition polygons or flood-location points'],
  ['全市连续网络 SWMM 输入已编译', 'Citywide continuous-network SWMM inputs are compiled'],
  ['保留跨内部计算组织的可用管段', 'Usable links across internal compute organization are retained'],
  ['尚未形成完整动态水动力结果', 'Complete dynamic hydraulic results are not yet available'],
  ['运行状态标记不代表积水位置', 'Runtime markers do not represent flood locations'],
  ['分区洪涝损失、外排量和连续性误差仅在分区统计表中查看，不映射为中心点结果', 'Partition flooding loss, outflow, and continuity error are shown only in the partition summary and are not mapped as centroid results'],
  ['保留跨内部计算组织的可用连接；不是正式分区面', 'Usable cross-partition connections are retained; these are not official partition polygons'],
  ['当前原型固定 5 分钟路由步长', 'The current prototype uses a fixed 5-minute routing step'],
  ['三类来源互斥，运行回执记录真实来源', 'The three sources are mutually exclusive; the run receipt records the actual source'],
  ['已准备 2/5/10/25/50/100 年一遇共 6 套全市预计算结果', 'Six citywide precomputed results are available for 2/5/10/25/50/100-year return periods'],
  ['严格质量门均未通过，仅用于原型诊断展示', 'None passed the strict quality gate; they are for prototype diagnostics only'],
  ['官方输入：Zone B、', 'Official input: Zone B, '], ['年一遇、180 分钟、', '-year return period, 180 minutes, '],
  ['5 分钟时程由 DDF 嵌套雨量插值后采用交替块法生成', 'The 5-minute hyetograph is generated by interpolating nested DDF depths and applying the alternating-block method'],
  ['峰值位置为可调整假设', 'Peak position is an adjustable assumption'],
  ['运行时从 Open-Meteo Archive API 拉取该坐标的小时降雨', 'At runtime, hourly rainfall is fetched for this coordinate from the Open-Meteo Archive API'],
  ['公开数据仅作原型代理，不等同于客户实测', 'Public data is a prototype proxy and is not equivalent to customer measurements'],
  ['公开站点约束雨型（NOAA NCEI）', 'Public station-constrained hyetograph (NOAA NCEI)'],
  ['公开站点约束雨型（NOAA NCEI · OMAD）', 'Public station-constrained hyetograph (NOAA NCEI · OMAD)'],
  ['公开站点约束雨型（NOAA NCEI · OMAA）', 'Public station-constrained hyetograph (NOAA NCEI · OMAA)'],
  ['公开站点', 'Public station'], ['事件窗口', 'Event window'],
  ['使用 NOAA NCEI 阿布扎比站点 2024-04 公开累计观测约束的本地代理时序；原始观测为 12 小时累计，不是逐小时实测，结果仅用于原型敏感性验证，不等同客户权威历史降雨。', 'Uses a local proxy series constrained by NOAA NCEI Abu Dhabi station accumulations for April 2024. Native observations are 12-hour accumulations, not hourly measurements; results are for prototype sensitivity validation and are not equivalent to customer-authoritative historical rainfall.'],
  ['12 小时累计约束', '12-hour accumulation constraint'],
  ['站点累计约束', 'Station accumulation constraint'],
  ['客户权威历史时序入口已保留', 'The customer authoritative historical-series entry point is retained'],
  ['当前私有数据尚未接入，运行会被拦截', 'Private customer data is not connected yet; execution is blocked'],
  ['后续通过客户 CSV / NetCDF 和事件元数据验收后绑定', 'It will be bound after customer CSV / NetCDF and event metadata pass validation'],
  ['调整基线的受控动作，不修改客户原始 GDB', 'Controlled actions adjust the baseline without modifying the original customer GDB'],
  ['当前基线无泵站链接', 'The current baseline has no pump links'], ['实际未应用', 'not applied in the current baseline'],
  ['当前原型固定 5 分钟路由步长', 'The current prototype uses a fixed 5-minute routing step'],
  ['已从最近一次完成的真实 EPA SWMM 情景恢复', 'Restored from the latest completed real EPA SWMM scenario'],
  ['正在读取预计算作业…', 'Reading the precomputed job…'], ['正在准备原生 OUT 时间轴…', 'Preparing the native OUT timeline…'],
  ['正在加载全量节点到地图…', 'Loading all nodes onto the map…'], ['正在执行真实 SWMM…', 'Running SWMM Simulation...'],
  ['正在读取预计算结果目录…', 'Reading the precomputed-result catalog…'], ['重试并加载', 'Retry and load'],
  ['年一遇预计算结果', '-year return-period precomputed result'],
  ['运行真实 SWMM 情景', 'Run SWMM Simulation'],
  ['真实 SWMM 情景提交失败', 'Failed to submit the real SWMM scenario'], ['真实 SWMM 情景运行失败', 'The real SWMM scenario failed'],
  ['预计算 SWMM 作业读取失败', 'Failed to read the precomputed SWMM job'], ['预计算 SWMM 时间轴读取失败', 'Failed to read the precomputed SWMM timeline'],
  ['预计算 SWMM 结果加载失败', 'Failed to load precomputed SWMM results'], ['全量 SWMM 节点结果读取失败', 'Failed to read the complete SWMM node results'],
  ['预计算结果目录加载超时，请确认后端服务已启动后重试。', 'The precomputed-result catalog timed out. Confirm that the backend service is running and try again.'],
  ['登录会话已失效，请重新登录后加载预计算结果。', 'Your login session has expired. Sign in again before loading precomputed results.'],
  ['预计算结果目录接口返回了页面内容而不是 JSON，请确认后端服务已启动并刷新页面。', 'The precomputed-result catalog returned an HTML page instead of JSON. Confirm that the backend service is running, then refresh the page.'],
  ['预计算结果目录不存在或接口不可用，请检查后端服务。', 'The precomputed-result catalog is missing or its API is unavailable. Check the backend service.'],
  ['预计算结果目录数据不完整，必须包含 2/5/10/25/50/100 年一遇六套结果。', 'The precomputed-result catalog is incomplete. It must contain all six 2/5/10/25/50/100-year results.'],
  ['预计算结果目录加载失败，请检查后端服务后重试。', 'Failed to load the precomputed-result catalog. Check the backend service and try again.'],
  ['SWMM 情景状态读取失败', 'Failed to read SWMM scenario status'], ['SWMM 情景地图结果读取失败', 'Failed to read SWMM scenario map results'],
  ['地图组件尚未就绪，请刷新页面后重试', 'The map is not ready; refresh the page and try again'],
  ['选择单分区时，需要指定一个分区。', 'Select a partition when using single-partition scope.'],
  ['降雨时长必须在 5 分钟至 72 小时之间。', 'Rainfall duration must be between 5 minutes and 72 hours.'],
  ['降雨总量必须大于 0，且不超过 1000 mm。', 'Total rainfall must be greater than 0 and no more than 1000 mm.'],
  ['已选择管线情景，请调整堵塞率或管线能力倍率，或恢复“无管线调整”。', 'A pipe scenario is selected; adjust blockage or capacity, or restore “No pipe adjustment”.'],
  ['历史事件模式需要上传客户权威降雨时序和元数据；当前先使用设计暴雨原型。', 'Historical-event mode requires the customer authoritative rainfall series and metadata; the design-storm prototype is used for now.'],
  ['本次情景降雨输入', 'Rainfall input for this scenario'], ['来源读取中', 'Reading source'],
  ['模型输入时间窗', 'Model input window'], ['真实 SWMM 报告', 'Real SWMM report'],
  ['官方 DDF 总量 + 假设时间分配', 'Official DDF depth + assumed temporal allocation'],
  ['参数化设计暴雨，不是实测雨量曲线', 'Parametric design storm, not an observed rainfall curve'],
  ['小时公开数据已按模型 5 分钟步长展开，仅用于原型代理。', 'Hourly public data was expanded to the model 5-minute step and is for prototype proxy use only.'],
  ['本次模型输入降雨数据', 'Rainfall input for this run'], ['个全市作业已执行', 'citywide jobs executed'],
  ['个全市连续网络作业已完成', 'citywide continuous-network jobs completed'], ['个作业失败，失败原因保留在运行回执。', 'jobs failed; failure reasons are retained in the run receipt.'],
  ['作业范围', 'Job scope'], ['外排量（百万升）', 'Outflow (million litres)'], ['洪涝损失（百万升）', 'Flooding loss (million litres)'],
  ['严格质量门', 'Strict quality gate'], ['不代表工程准入', 'Does not represent engineering admission'],
  ['全市连续网络 · 单个 SWMM 作业', 'Citywide continuous network · one SWMM job'],
  ['客户真实节点/管线几何', 'Customer actual node/pipe geometry'], ['当前为 Open-Meteo 公开代理降雨', 'Current forcing is Open-Meteo public proxy rainfall'],
  ['客户真实节点/管线几何 + EPA SWMM 全市连续网络最大值', 'Customer actual node/pipe geometry + EPA SWMM citywide continuous-network maxima'],
  ['客户 GDB 输入资产 + 全市连续网络 SWMM 作业状态', 'Customer GDB input assets + citywide continuous-network SWMM job status'],
  ['客户 GDB 输入资产 + 全市连续网络 SWMM 编译覆盖', 'Customer GDB input assets + citywide continuous-network SWMM compile coverage'],
  ['客户 GDB 输入资产 + Open-Meteo 公开代理强迫下的 EPA SWMM 5.2.4 诊断结果', 'Customer GDB input assets + EPA SWMM 5.2.4 diagnostic results under Open-Meteo public proxy forcing'],
  ['客户 GDB 的私有格式派生几何；结果图层尚未接入或当前阶段没有结果输出。', 'Private-format geometry derived from the customer GDB; result layers are not connected or this stage has no result output.'],
  ['尚未检测到客户 GDB 派生图层，地图保持空白以避免展示虚构空间结果。', 'No customer GDB derivative layer was detected; the map remains blank to avoid showing fabricated spatial results.'],
  ['客户图层：EPSG:32640 → WGS 84 预览；SWMM 结果尚未接入。', 'Customer layers: EPSG:32640 → WGS 84 preview; SWMM results are not connected yet.'],
  ['客户图层：全量管网已通过矢量瓦片接入地图；SWMM 结果尚未接入。', 'Customer layers: the full network is connected to the map through vector tiles; SWMM results are not connected yet.'],
  ['已接入客户真实节点/管线几何上的全市连续网络 SWMM 最大值', 'Citywide continuous-network SWMM maxima joined to customer actual node/pipe geometry'],
  ['已接入全市连续网络运行状态', 'Citywide continuous-network runtime status connected'],
  ['已接入公开代理 SWMM 诊断结果', 'Public-proxy SWMM diagnostic results connected'],
  ['结果阶段已隐藏原始管网，避免遮挡结果；切换到数据阶段可查看原始输入。', 'Raw network is hidden during result stages to avoid obscuring results; switch to the data stage to view raw inputs.'],
  ['当前阶段暂无可展示的结果空间图层', 'No result spatial layer is available for the current stage'], ['暂无已接入的客户真实图层', 'No customer actual layers are connected'],
  ['地图当前显示 · 原始输入', 'Currently shown on map · raw inputs'], ['SWMM 结果图层 · 当前状态', 'SWMM result layers · current status'], ['SWMM / ANUGA 结果图层 · 当前状态', 'SWMM / ANUGA result layers · current status'], ['ANUGA 2D 局部诊断已接入', 'ANUGA 2D local diagnostic connected'], ['ANUGA 2D 局部结果已接入', 'ANUGA 2D local result connected'],
  ['全市公共二维原型已接入', 'Full-city public 2D prototype connected'], ['全市原型已接入', 'Full-city prototype connected'], ['二维地表结果已接入（公共 DEM 原型）', '2D surface result connected (public DEM prototype)'],
  ['Copernicus DEM 全市二维原型已接入', 'Copernicus DEM full-city 2D prototype connected'],
  ['ANUGA 2D · Copernicus DEM GLO-30 全市公共原型', 'ANUGA 2D · Copernicus DEM GLO-30 full-city public prototype'],
  ['全市公共二维原型已接入：Copernicus DEM GLO-30、250 m 计算网格、11 个时间片（0–300 分钟）；最大积水深度和动态地表水深可在 2D/3D 地图底部播放。该结果仅用于原型演示，未校准、未工程准入。', 'Full-city public 2D prototype connected: Copernicus DEM GLO-30, 250 m computational grid, and 11 time slices (0–300 minutes). Maximum and dynamic surface-water depth can be played from the bottom timeline in the 2D/3D map. This result is for prototype demonstration only, not calibrated or engineering-admitted.'],
  ['当前地图主图层来自 Copernicus DEM GLO-30 驱动的 ANUGA 2D 全市公共原型，使用 250 m 计算网格；ESA WorldCover 2021 永久水体掩膜已应用，海域不接受降雨且不输出为城市积水。时间轴可播放陆域积水演变。结果仅用于原型演示，未校准、未工程准入，后续可用客户权威 DTM、海岸线和潮位边界替换并复跑。', 'The primary map layer is the ANUGA 2D citywide public prototype driven by Copernicus DEM GLO-30 on a 250 m grid. The ESA WorldCover 2021 permanent-water mask is applied: sea cells receive no rainfall and are not published as urban flooding. The timeline plays land-surface flood evolution. Results are for prototype demonstration only, not calibrated or engineering-admitted; customer authoritative DTM, shoreline, and tide boundaries can replace the public proxies for reruns.'],
  ['250 m 原型网格', '250 m prototype grid'], ['个计算单元', 'computational cells'], ['个时间片', 'time slices'], ['最大深度', 'maximum depth'],
  ['当前地图主图层来自客户 dtm_5M.tif 驱动的 ANUGA 2D 局部结果，使用真实空间坐标和二维单元面；时间轴可播放动态积水深度。结果未校准、未工程准入。', 'The primary map layer is a customer dtm_5M.tif-driven ANUGA 2D local result using real coordinates and 2D cell polygons; the timeline plays dynamic flood depth. Results are not calibrated or engineering-admitted.'],
  ['结果回挂客户真实节点和管线几何；内部计算组织不作为空间结果来源', 'Results are joined to customer actual node and pipe geometry; internal compute organization is not a spatial-result source'],
  ['仅运行状态已接入', 'Runtime status only'], ['公开代理局部原型已接入', 'Public-proxy local prototype connected'],
  ['分区统计已接入，空间结果待接入', 'Partition statistics connected; spatial results pending'], ['客户真实几何已接入', 'Customer actual geometry connected'],
  ['当前地图主图层来自本次真实 EPA SWMM OUT 的节点结果', 'The current map primary layer comes from node results in this real EPA SWMM OUT'],
  ['地图主图层是客户真实节点和管线上的全市连续网络 SWMM 诊断输出', 'The primary map layer is citywide continuous-network SWMM diagnostics on customer actual nodes and pipes'],
  ['地图中的运行状态标记表示全市作业状态，不是分区边界，也不代表发生积水的位置。', 'Runtime markers show citywide job status, not partition boundaries or flood locations.'],
  ['当前为公开代理诊断结果；客户权威事件、边界和校准数据到达后，将替换同一结果契约。', 'Current results are public-proxy diagnostics; customer authoritative events, boundaries, and calibration data will replace the same result contract.'],
  ['2024 事件证据与重构', '2024 Event Evidence & Reconstruction'],
  ['公开事实', 'Public facts'], ['重构雨型', 'Reconstructed hyetograph'], ['事件时间线', 'Event timeline'], ['验证缺口', 'Validation gaps'],
  ['仅用于原型敏感性演示', 'Prototype sensitivity only'], ['不发布地图图层', 'No map layer published'], ['来源', 'Source'], ['打开来源', 'Open source'],
  ['公开事实与重构雨型分开呈现', 'Public evidence and reconstructed rainfall are shown separately'],
  ['本页只展示可追溯公开证据和明确标注的重构雨型，不覆盖真实 SWMM / ANUGA 地图结果。', 'This tab shows traceable public evidence and an explicitly labelled reconstructed hyetograph; it does not replace real SWMM / ANUGA map results.'],
  ['公开资料未找到可准入的市内逐时/24 h 实测序列，不能用艾因站值替代。', 'No admissible hourly or 24-hour city observation was identified; the Al Ain station total cannot substitute for it.'],
  ['不是阿布扎比市雨量。', 'Not Abu Dhabi city rainfall.'],
  ['阿布扎比市本地 24 h 雨量', 'Abu Dhabi city local 24-hour rainfall'],
  ['国家级极端事件记录', 'National extreme-rainfall record'], ['公开恢复记录', 'Documented recovery'],
  ['三波次重构雨型（40 h 雨量窗口）', 'Three-burst reconstructed hyetograph (40-hour rainfall window)'],
  ['逐时雨强（mm/h）', 'Hourly intensity (mm/h)'], ['累计重构雨量', 'Reconstructed cumulative rainfall'],
  ['最大雨强', 'Peak intensity'], ['逐时', 'Hourly'], ['累计', 'Cumulative'],
  ['本页不向地图发送任何空间要素', 'This tab does not send any spatial feature to the map'],
  ['正在读取 2024 事件公开证据…', 'Loading 2024 event evidence...'], ['2024 事件证据暂不可用', '2024 event evidence is temporarily unavailable'], ['条', 'items'],
  ['真实 SWMM / ANUGA 结果仍在上方地图区域展示', 'Real SWMM / ANUGA results remain available in the map area above'],
  ['陆海掩膜已应用', 'Land/water mask applied'], ['永久水体单元已排除', 'Permanent-water cells excluded'],
  ['陆地比例', 'Land fraction'], ['永久水体比例', 'Permanent-water fraction'],
  ['ANUGA 2D · Copernicus DEM GLO-30 全市陆域原型', 'ANUGA 2D · Copernicus DEM GLO-30 citywide land-surface prototype'],
  ['点击阶段查看输入、输出与下一步', 'Select a stage to view inputs, outputs, and the next action'], ['数值质量通过不等于工程校准通过。', 'Numerical quality passing does not mean engineering calibration passing.'],
  ['客户数据等待阶段', 'Waiting for customer data'], ['下一批数据到达后：回执验收 → 事件预检 → SWMM 边界绑定 → 工程复核', 'After the next data delivery: receipt validation → event pre-check → SWMM boundary binding → engineering review'],
];

// Runtime receipts and map labels contain values that cannot be listed
// literally above (node counts, run IDs, cell counts, and measurements).
const ABU_EN_DYNAMIC_REPLACEMENTS: Array<[RegExp, string]> = [
  [/EPA SWMM 原生 OUT 共包含 ([\d,]+) 个结果节点；当前地图可定位 ([\d,]+) 个（([\d.]+)%），([\d,]+) 个因几何缺失暂不可视化。已映射节点包含零值节点，且未按数值阈值或数量截断。该作业严格数值质量门未通过，仅用于诊断。/g,
    'The native EPA SWMM OUT contains $1 result nodes. The map can locate $2 ($3%); $4 nodes cannot currently be visualized because geometry is missing. Mapped nodes include zero values and are not filtered by value threshold or count. The strict numerical quality gate failed, so this run is diagnostic only.'],
  [/客户 5 m DTM 全市二维结果已接入：250 m 计算网格、([\d]+) 个时间片；/g,
    'Customer 5 m DTM citywide 2D result connected: 250 m grid, $1 time slices;'],
  [/250 m 计算网格 · ([\d,]+) 个陆域单元 · ([\d,]+) 个永久水体单元已排除 · ([\d]+) 个时间片 · 最大深度 ([\d.]+) m/g,
    '250 m computational grid · $1 land-surface cells · $2 permanent-water cells excluded · $3 time slices · maximum depth $4 m'],
  [/GWM 基于阶段 3 二维地表结果进行 (\d+) 年一遇快速 rollout；([\d,]+) 个二维单元（([\d,]+) 个陆域有效单元，排除 ([\d,]+) 个水域单元）(?:、(\d+) 个时间片)?。/g,
    'GWM performs a rapid rollout from the phase-3 2D surface result for a $1-year event: $2 2D cells ($3 active land cells; $4 water cells excluded); $5 time slices.'],
  [/已完成 (\d+) 年一遇 GWM rollout/g, 'Completed $1-year GWM rollout'],
  [/GWM 基于阶段 3 二维地表结果生成基线、干预和差值图层，([\d,]+) 个二维单元、(\d+) 个时间片。/g,
    'GWM generated baseline, intervention, and delta layers from the phase-3 2D surface result: $1 2D cells and $2 time slices.'],
  [/时间轴 (\d+) 帧 · 不确定性 ([\d.]+)% · 高风险情景回退 SWMM \/ ANUGA 复核/g,
    'Timeline: $1 frames · uncertainty $2% · high-risk scenarios return to SWMM / ANUGA review'],
  [/正在准备阶段 3 的 (\d+) 年一遇二维结果…/g, 'Preparing the phase-3 $1-year 2D result…'],
  [/阶段 3 的 (\d+) 年一遇二维结果已准备，GWM 将基于该结果运行。/g, 'The phase-3 $1-year 2D result is ready; GWM will run from this result.'],
  [/运行前会自动加载阶段 3 的 (\d+) 年一遇二维结果。/g, 'The matching phase-3 $1-year 2D result will be loaded automatically before the run.'],
  [/阶段 3 二维结果尚未准备，无法运行 GWM/g, 'The phase-3 2D result is not ready; GWM cannot run yet'],
  [/全市公共二维原型已接入：Copernicus DEM GLO-30、250 m 计算网格、([\d]+) 个时间片；ESA WorldCover 2021 陆海掩膜已应用，([\d,]+) 个永久水体单元已排除，海域不再显示为城市积水。该结果仅用于原型演示，未校准、未工程准入。/g,
    'Citywide public 2D prototype connected: Copernicus DEM GLO-30, 250 m grid, $1 time slices. The ESA WorldCover 2021 land/water mask is applied; $2 permanent-water cells are excluded and the sea is not shown as urban flooding. Results are for prototype demonstration only, not calibrated or engineering-admitted.'],
  [/本次真实 SWMM 情景已接入原生 OUT 时间轴，共 ([\d,]+) 个节点；地图每个时间片均加载全部节点（含零值节点），没有按阈值或数量截断。可在 2D\/3D 地图底部播放，节点溢流\/积水层可在图层控制中打开。/g,
    'The current SWMM scenario is connected to the native OUT timeline with $1 nodes. Every map time slice loads all nodes, including zero-value nodes, without threshold or count truncation. Play it from the bottom timeline in the 2D/3D map; enable the node overflow/flooding layer in layer controls.'],
  [/节点级结果来自本次 EPA SWMM 原生 OUT 时序，地图每帧加载全部 ([\d,]+) 个节点（含零值节点），可按 ([\d.]+) 分钟报告步播放；降雨输入：(.+?)。/g,
    'Node-level results come from the native EPA SWMM OUT time series. Every map frame loads all $1 nodes, including zero-value nodes, and can play at the $2-minute report step. Rainfall input: $3.'],
  [/本次真实 SWMM 情景 · 节点最大水深 · (.+)/g, 'Current SWMM scenario · maximum node depth · $1'],
  [/本次真实 SWMM 情景 · 节点溢流\/积水 · (.+)/g, 'Current SWMM scenario · node overflow/flooding · $1'],
  [/本次真实 SWMM 情景 · 分区汇总（辅助） · (.+)/g, 'Current SWMM scenario · partition summary (auxiliary) · $1'],
  [/二维结果 · Copernicus DEM GLO-30 全市陆域最大积水深度/g, '2D result · Copernicus DEM GLO-30 citywide land-surface maximum flood depth'],
  [/二维结果 · Copernicus DEM GLO-30 全市陆域动态积水深度/g, '2D result · Copernicus DEM GLO-30 citywide dynamic land-surface flood depth'],
  [/全市陆域二维最大积水深度（m）· 公共 DEM 原型/g, 'Citywide land-surface 2D maximum flood depth (m) · public DEM prototype'],
  [/全市陆域二维动态积水深度（m）· 公共 DEM 原型/g, 'Citywide dynamic land-surface 2D flood depth (m) · public DEM prototype'],
  [/二维结果 · Copernicus DEM GLO-30 全市公共原型最大积水深度/g, '2D result · Copernicus DEM GLO-30 full-city public prototype maximum flood depth'],
  [/二维结果 · Copernicus DEM GLO-30 全市动态地表水深/g, '2D result · Copernicus DEM GLO-30 full-city dynamic surface-water depth'],
  [/全市二维最大积水深度（m）· 公共 DEM 原型/g, 'Citywide 2D maximum flood depth (m) · public DEM prototype'],
  [/全市二维动态积水深度（m）· 公共 DEM 原型/g, 'Citywide 2D dynamic flood depth (m) · public DEM prototype'],
  [/全市二维最大积水深度/g, 'Citywide 2D maximum flood depth'],
  [/全市二维动态积水深度/g, 'Citywide 2D dynamic flood depth'],
  [/公共 DEM 原型/g, 'public DEM prototype'],
  [/([\d,]+) 个客户节点 · 每帧包含零值节点 · 水深、水头、入流和溢流\/积水速率 · 无展示截断/g,
    '$1 customer nodes · every frame includes zero-value nodes · depth, head, inflow, and overflow/flooding rate · no display truncation'],
  [/([\d,]+) 个计算单元 · ([\d]+) 个时间片 · 最大深度 ([\d.]+) m/g,
    '$1 computational cells · $2 time slices · maximum depth $3 m'],
  [/250 m 原型网格 · ([\d,]+) 个陆域单元 · ([\d,]+) 个永久水体单元已排除 · ([\d]+) 个时间片 · 最大深度 ([\d.]+) m/g,
    '250 m prototype grid · $1 land-surface cells · $2 permanent-water cells excluded · $3 time slices · maximum depth $4 m'],
  [/陆海掩膜已应用：(.+?)；永久水体占比阈值 ([\d.]+)；降雨仅施加到陆域单元，永久水体单元不进入城市积水图层。/g,
    'Land/water mask applied: $1; permanent-water fraction threshold $2; rainfall is applied to land cells only, and permanent-water cells are excluded from the urban-flood layer.'],
  [/([\d,]+) 个全市作业状态标记 · ([\d,]+) 已完成 · ([\d,]+) 运行失败/g,
    '$1 citywide job-status markers · $2 completed · $3 failed'],
];

export function translateAbuEnglishText(value: string): string {
  let translated = value;
  for (const [source, target] of ABU_EN_DYNAMIC_REPLACEMENTS) {
    translated = translated.replace(source, target);
  }
  for (const [source, target] of ABU_EN_REPLACEMENTS.sort((a, b) => b[0].length - a[0].length)) {
    translated = translated.split(source).join(target);
  }
  // Never leave Chinese glyphs in the English customer view. Any remaining
  // fragment is an unstructured diagnostic emitted by a legacy receipt. Keep
  // the English surface honest and compact instead of leaking Han characters
  // or the old, confusing generic "model metadata" placeholder.
  return translated
    .replace(/[\u3400-\u9fff]+/g, 'untranslated field')
    .replace(/：/g, ': ')
    .replace(/，/g, ', ')
    .replace(/；/g, '; ')
    .replace(/。/g, '.')
    .replace(/（/g, ' (')
    .replace(/）/g, ')')
    .replace(/、/g, ', ');
}

function localizeAbuText(value: string): string {
  return getLocale() === 'en-US' ? translateAbuEnglishText(value) : value;
}

function localizeAbuPair(zh: string, en: string): string {
  return getLocale() === 'en-US' ? en : zh;
}

function localizeAbuLayerMetadata<T>(value: T, translateAll = false): T {
  if (getLocale() !== 'en-US') return value;
  if (typeof value === 'string') return translateAbuEnglishText(value) as T;
  if (Array.isArray(value)) return value.map(item => localizeAbuLayerMetadata(item, translateAll)) as T;
  if (value && typeof value === 'object') {
    const next: Record<string, unknown> = {};
    Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
      // Do not rewrite IDs, file names, URLs, or feature payloads. Only the
      // presentation metadata is sent through the language adapter.
      const presentationKey = ['name', 'legend_title', 'tooltip_labels', 'category_labels', 'summary', 'title', 'subtitle', 'result_boundary', 'claim_boundary'].includes(key);
      next[key] = translateAll || presentationKey
        ? localizeAbuLayerMetadata(item, translateAll || key === 'tooltip_labels')
        : item;
    });
    return next as T;
  }
  return value;
}

type RainfallMode = 'design_storm' | 'online_public' | 'public_station_event' | 'historical_event';
type RainfallPattern = 'uniform' | 'front_loaded' | 'alternating_block' | 'official_zone_b_ddf_abm';
type ReturnPeriodYears = 2 | 5 | 10 | 25 | 50 | 100;
type GwmMode = 'trained' | 'screening';
type SurfaceWorkspaceView = 'invoke' | 'results';
type SurfaceResultSource = 'return_period_one_way' | 'bidirectional_validation';

interface SurfaceRunForm {
  solver: 'anuga';
  couplingMode: 'surface_rainfall_only' | 'one_way_swmm_to_anuga' | 'two_way_swmm_anuga';
  rainfallSource: 'zone_b_design_storm';
  returnPeriodYears: ReturnPeriodYears;
  rainfallDurationMinutes: 180;
  peakPositionPercent: number;
  terrainSource: 'customer_dtm_5m' | 'copernicus_dem_glo30';
  domain: 'citywide';
  cellSizeM: 50 | 100 | 250 | 500;
  landManningN: number;
  waterManningN: number;
  initialDepthM: number;
  minimumOutputDepthM: number;
  tailMinutes: number;
  outputIntervalMinutes: 5 | 10 | 15 | 30 | 60;
  boundaryType: 'fixed_stage';
  seaBoundaryLevelM: number;
  waterCellFractionThreshold: number;
  exchangeWindowSeconds: 300 | 600 | 900;
  openingAreaM2: number;
  dischargeCoefficient: number;
  maximumExchangeRateM3s: number;
  interfaceDetailLimit: number;
}

interface SurfaceRunReceipt {
  runId: string;
  status: string;
  createdAt?: string;
  startedAt?: string;
  finishedAt?: string;
  failureReason?: string;
  failureDetail?: string;
  scenario?: Record<string, any>;
  summary?: Record<string, any>;
}

type TrainedGwmEvent = {
  event_id: string;
  split: 'train' | 'validation' | 'test' | 'external_test_2024_april';
  external_holdout: boolean;
  training_forbidden: boolean;
  start_utc: string;
  end_utc: string;
};

type TrainedGwmModelCatalog = {
  release_id?: string;
  training_event_count?: number;
  validation_event_count?: number;
  blind_test_event_count?: number;
  external_holdout_event_count?: number;
  training_period_start_utc?: string | null;
  training_period_end_utc?: string | null;
  target?: string;
  grid_cell_size_m?: number;
  claim_boundary?: string;
};

interface FloodScenarioForm {
  scope: 'citywide' | 'partition';
  partition: string;
  rainfallMode: RainfallMode;
  publicLatitude: number;
  publicLongitude: number;
  publicStation: 'OMAD' | 'OMAA';
  startTime: string;
  durationMinutes: number;
  totalDepthMm: number;
  rainfallPattern: RainfallPattern;
  returnPeriodYears: ReturnPeriodYears;
  peakPosition: number;
  spatialPattern: 'uniform' | 'zonal';
  tailMinutes: number;
  pipeScope: 'none' | 'priority_corridor' | 'selected_zone';
  blockagePercent: number;
  pipeCapacityMultiplier: number;
  pumpEnabled: boolean;
  pumpCapacityMultiplier: number;
  outfallMode: 'open' | 'fixed_level';
  outfallLevelM: number;
  outputIntervalMinutes: number;
}

interface ScenarioRun {
  runId: string;
  status: string;
  startedAt: string;
  finishedAt?: string;
  restoredFromLatestCompleted?: boolean;
  peakIntensityMmPerHour: number;
  generatedIntervals: number;
  generatedTotalDepthMm: number;
  rainfallMode?: RainfallMode;
  rainfallSource?: string;
  rainfallStats?: {
    station?: string;
    station_label?: string;
    anchor_total_depth_mm?: number;
    event_window_utc?: string[];
    evidence_class?: string;
    admission?: string;
  };
  actionSummary: string;
  claimBoundary: string;
  totalPartitions?: number;
  completedPartitions?: number;
  failedPartitions?: number;
  currentPartition?: number | 'full_city' | null;
  summary?: {
    node_flooding_partition_count?: number;
    completed_count?: number;
    failed_count?: number;
  };
  actualSummary?: {
    external_outflow_million_litres?: number | null;
    flooding_loss_million_litres?: number | null;
    runoff_continuity_error_percent?: number | null;
    routing_continuity_error_percent?: number | null;
    node_flooding_detected?: boolean;
    numerical_quality_passed?: boolean;
    strict_numerical_quality_passed?: boolean;
  };
  warnings?: string[];
  partitions?: Array<{
    partition_id: number | 'full_city';
    partition_label: string;
    status: string;
    failure_reason?: string;
    result_summary?: {
      external_outflow_million_litres?: number | null;
      flooding_loss_million_litres?: number | null;
      runoff_continuity_error_percent?: number | null;
      routing_continuity_error_percent?: number | null;
      node_flooding_detected?: boolean;
      numerical_quality_passed?: boolean;
      strict_numerical_quality_passed?: boolean;
    };
  }>;
}

const DEFAULT_FLOOD_SCENARIO: FloodScenarioForm = {
  scope: 'citywide',
  partition: 'all',
  rainfallMode: 'design_storm',
  publicLatitude: 24.4539,
  publicLongitude: 54.3773,
  publicStation: 'OMAD',
  startTime: '2024-04-16T00:00',
  durationMinutes: 180,
  totalDepthMm: 28.71,
  rainfallPattern: 'official_zone_b_ddf_abm',
  returnPeriodYears: 10,
  peakPosition: 40,
  spatialPattern: 'uniform',
  tailMinutes: 60,
  pipeScope: 'none',
  blockagePercent: 0,
  pipeCapacityMultiplier: 1,
  pumpEnabled: true,
  pumpCapacityMultiplier: 1,
  outfallMode: 'open',
  outfallLevelM: 0,
  outputIntervalMinutes: 15,
};

const DEFAULT_SURFACE_RUN: SurfaceRunForm = {
  solver: 'anuga',
  couplingMode: 'surface_rainfall_only',
  rainfallSource: 'zone_b_design_storm',
  returnPeriodYears: 10,
  rainfallDurationMinutes: 180,
  peakPositionPercent: 40,
  terrainSource: 'customer_dtm_5m',
  domain: 'citywide',
  cellSizeM: 250,
  landManningN: 0.035,
  waterManningN: 0.02,
  initialDepthM: 0,
  minimumOutputDepthM: 0.01,
  tailMinutes: 120,
  outputIntervalMinutes: 30,
  boundaryType: 'fixed_stage',
  seaBoundaryLevelM: 0,
  waterCellFractionThreshold: 0.2,
  exchangeWindowSeconds: 300,
  openingAreaM2: 0.5,
  dischargeCoefficient: 0.61,
  maximumExchangeRateM3s: 5,
  interfaceDetailLimit: 200,
};

const rainfallPatternLabels: Record<RainfallPattern, string> = {
  uniform: '均匀雨型',
  front_loaded: '前峰雨型',
  alternating_block: '交替块雨型',
  official_zone_b_ddf_abm: 'Zone B 官方 DDF 交替块雨型（2022）',
};

const zoneB180DepthByReturnPeriod: Record<ReturnPeriodYears, number> = {
  2: 11.31,
  5: 25.29,
  10: 28.71,
  25: 40.35,
  50: 51.48,
  100: 60.33,
};

const zoneBDurationsThrough180 = [5, 10, 15, 30, 60, 120, 180] as const;
const zoneBDepthsThrough180: Record<ReturnPeriodYears, readonly number[]> = {
  2: [4.02, 4.93, 5.53, 6.76, 8.25, 10.08, 11.31],
  5: [9.39, 11.44, 12.76, 15.44, 18.68, 22.60, 25.29],
  10: [10.59, 12.92, 14.43, 17.48, 21.18, 25.68, 28.71],
  25: [15.69, 18.93, 21.02, 25.21, 30.24, 36.26, 40.35],
  50: [23.03, 27.05, 29.56, 34.51, 40.28, 47.02, 51.48],
  100: [26.99, 31.70, 34.64, 40.44, 47.21, 55.12, 60.33],
};

function buildZoneBProfile(returnPeriod: ReturnPeriodYears, peakPositionPercent: number) {
  const published = zoneBDepthsThrough180[returnPeriod];
  const cumulative = Array.from({ length: 36 }, (_, index) => {
    const duration = (index + 1) * 5;
    const exactIndex = zoneBDurationsThrough180.indexOf(duration as typeof zoneBDurationsThrough180[number]);
    if (exactIndex >= 0) return published[exactIndex];
    const upperIndex = zoneBDurationsThrough180.findIndex(value => value > duration);
    const lowerDuration = zoneBDurationsThrough180[upperIndex - 1];
    const upperDuration = zoneBDurationsThrough180[upperIndex];
    const ratio = (Math.log(duration) - Math.log(lowerDuration)) / (Math.log(upperDuration) - Math.log(lowerDuration));
    return Math.exp(Math.log(published[upperIndex - 1]) + ratio * (Math.log(published[upperIndex]) - Math.log(published[upperIndex - 1])));
  });
  const increments = cumulative.map((value, index) => value - (index > 0 ? cumulative[index - 1] : 0));
  const peakIndex = Math.max(0, Math.min(35, Math.round(35 * peakPositionPercent / 100)));
  const positions = [peakIndex];
  for (let distance = 1; positions.length < 36; distance += 1) {
    if (peakIndex + distance < 36) positions.push(peakIndex + distance);
    if (peakIndex - distance >= 0 && positions.length < 36) positions.push(peakIndex - distance);
  }
  const ordered = Array(36).fill(0) as number[];
  [...increments].sort((left, right) => right - left).forEach((value, index) => { ordered[positions[index]] = value; });
  const maximum = Math.max(...ordered);
  return ordered.map(value => Number((value / maximum).toFixed(3)));
}

const scenarioRunStages = [
  ['01', '生成降雨时序', '将总量、时长和雨型转换为 5 分钟强迫'],
  ['02', '绑定 SWMM 情景', '加载全市连续网络基线并叠加受控动作'],
  ['03', '输出时序状态', '准备节点、管段和地表结果的时间轴'],
  ['04', '地图动画回挂', '真实 SWMM 作业完成后接入动态结果图层'],
] as const;

export function buildCustomerHotspotMapLayer(payload: CustomerHotspotsBootstrap) {
  return {
    ...customerHotspotMapLayerBase,
    geojsonData: payload.geojson,
  };
}

function withCustomerHotspotOverlay(mapUpdate: any, payload?: CustomerHotspotsBootstrap | null) {
  if (payload?.geojson?.type !== 'FeatureCollection' || payload.geojson.features.length !== 506) return mapUpdate;
  const layers = Array.isArray(mapUpdate?.layers) ? mapUpdate.layers : [];
  if (layers.some((layer: any) => layer?.layer_id === customerHotspotMapLayerBase.layer_id)) return mapUpdate;
  return {
    ...mapUpdate,
    layers: [
      ...layers,
      localizeAbuLayerMetadata(buildCustomerHotspotMapLayer(payload)),
    ],
  };
}

function buildCustomerMapUpdate(stageKey: string, ready: boolean, resultReady: boolean, cityCompiled: boolean, cityRuntimeReady: boolean, cityDynamicResultReady: boolean, citySpatialResultReady: boolean, dtmDiagnostic?: CustomerDtmDiagnostic | null, publicCitywide2dDiagnostic?: PublicCitywide2dDiagnostic | null, customerHotspots?: CustomerHotspotsBootstrap | null) {
  const keys = stageLayerKeys[stageKey] || stageLayerKeys.data;
    const resultKeys = stageResultLayerKeys[stageKey] || [];
  // The five-feature public proxy sample is not a citywide hydraulic result.
  const stageSupportsResults = resultKeys.length > 0;
  const showCitywideSpatialResults = stageSupportsResults && citySpatialResultReady;
  const showCitywideRuntimeResult = stageSupportsResults && cityRuntimeReady && !showCitywideSpatialResults;
  const showCitywideCompileResult = stageSupportsResults && cityCompiled && !cityRuntimeReady && !showCitywideSpatialResults;
  const showProxyResults = stageSupportsResults && resultReady && !cityCompiled && !cityRuntimeReady && !showCitywideSpatialResults;
  const showResultLayers = resultKeys.length > 0 && (
    showCitywideSpatialResults || showCitywideRuntimeResult || showCitywideCompileResult || showProxyResults
  );
  const showPublicCitywide2dResult = Boolean(publicCitywide2dDiagnostic) && ['surface', 'validation'].includes(stageKey);
  const showDtmResult = Boolean(dtmDiagnostic) && !showPublicCitywide2dResult && ['swmm', 'surface', 'validation'].includes(stageKey);
  const dtmLayers = showDtmResult && dtmDiagnostic
    // Keep the temporal surface result available from the default SWMM stage
    // as well as the dedicated surface/validation stages. This makes the
    // model effect visible immediately after opening the Abu Dhabi tab.
    ? buildCustomerDtmMapLayers(dtmDiagnostic, true)
    : [];
  const publicCitywide2dLayers = showPublicCitywide2dResult && publicCitywide2dDiagnostic
    ? buildPublicCitywide2dMapLayers(publicCitywide2dDiagnostic)
    : [];
  const publicCustomerSurface = isCustomerDtmSurface(publicCitywide2dDiagnostic);
  const publicSurfaceLabel = publicCustomerSurface ? '客户 5 m DTM' : 'Copernicus DEM GLO-30 公共代理';
  const publicReturnPeriod = Number(publicCitywide2dDiagnostic?.metadata?.return_period_years || 100);
  const layers = [
    ...publicCitywide2dLayers,
    ...dtmLayers,
    ...(showCitywideSpatialResults
      ? [
        // These layers are the actual SWMM outputs joined to customer geometry.
        swmmResultLayers.links,
        swmmResultLayers.nodes,
        swmmResultLayers.linkFlow,
        swmmResultLayers.nodeOverflow,
        { ...swmmResultLayers.citywideRuntime, name: 'SWMM 全市连续网络运行状态（仅辅助）', visible: false },
      ]
      : showCitywideRuntimeResult
      ? [
        // Keep the categorical runtime status on top of metric points so a
        // completed partition is shown only as a run-state marker. Aggregate
        // partition metrics are deliberately not rendered as spatial results.
        { ...swmmResultLayers.citywideRuntime, name: 'SWMM 全市连续网络运行状态（单个全市作业）' },
      ]
      : showCitywideCompileResult
        ? []
        : showProxyResults
          ? resultKeys.filter(key => key === 'links' || key === 'nodes').map(key => swmmResultLayers[key])
      : []),
    ...(ready && !showResultLayers && !showPublicCitywide2dResult && !showDtmResult
      ? keys.map(key => resultKeys.length > 0
        ? {
          ...customerMapLayers[key],
          style: {
            ...customerMapLayers[key].style,
            // Keep the raw customer network visible while a SWMM result is
            // unavailable. Topology nodes must remain legible at city scale;
            // the previous 0.25 fill opacity made them look absent.
            opacity: key === 'network' ? 0.42 : key === 'sourceNodes' ? 0.95 : 0.86,
            fillOpacity: key === 'nodes' ? 0.72 : key === 'sourceNodes' ? 0.86 : undefined,
          },
        }
        : customerMapLayers[key])
      : []),
  ];
  // A local 500 m DTM diagnostic must open at its actual footprint. Using the
  // citywide default view (zoom 10) makes a valid result look like a stray
  // point in 3D. Derive a stable WGS84 center from the result polygons and
  // use a neighborhood-scale zoom; citywide SWMM results keep the default.
  let mapCenter: [number, number] = [24.46, 54.45];
  let mapZoom = 10;
  // Stage 1 opens at network-detail scale so roughly 238k pipe endpoints do
  // not collapse into a solid symbol mass over the equally dense pipe layer.
  // Users can still zoom out for the full extent; point radii scale with zoom.
  if (stageKey === 'data') mapZoom = 13;
  if (showDtmResult && dtmDiagnostic?.maximum_depth?.features?.length) {
    const coordinates: number[][] = [];
    for (const feature of dtmDiagnostic.maximum_depth.features) {
      const rings = feature?.geometry?.coordinates;
      if (!Array.isArray(rings)) continue;
      for (const ring of rings) {
        if (!Array.isArray(ring)) continue;
        for (const coordinate of ring) {
          if (Array.isArray(coordinate) && coordinate.length >= 2 && Number.isFinite(Number(coordinate[0])) && Number.isFinite(Number(coordinate[1]))) {
            coordinates.push([Number(coordinate[0]), Number(coordinate[1])]);
          }
        }
      }
    }
    if (coordinates.length) {
      const minLng = Math.min(...coordinates.map(point => point[0]));
      const maxLng = Math.max(...coordinates.map(point => point[0]));
      const minLat = Math.min(...coordinates.map(point => point[1]));
      const maxLat = Math.max(...coordinates.map(point => point[1]));
      mapCenter = [(minLat + maxLat) / 2, (minLng + maxLng) / 2];
      mapZoom = 15;
    }
  }
  if (showPublicCitywide2dResult && publicCitywide2dDiagnostic?.metadata?.domain_bounds_epsg32640?.length === 4) {
    const bounds = publicCitywide2dDiagnostic.metadata.domain_bounds_epsg32640.map(Number);
    if (Array.isArray(bounds) && bounds.every(Number.isFinite)) {
      // The public result is already in WGS84 GeoJSON; use its metadata extent
      // only to keep the citywide view stable without inspecting all features.
      mapCenter = [24.46, 54.45];
      mapZoom = 10;
    }
  }
  const mapUpdate = {
    schema: 'map_update.v1',
      summary: {
      title: '阿布扎比暴雨内涝世界模型 · 客户空间结果与 SWMM 诊断',
        subtitle: showPublicCitywide2dResult
        ? `${publicSurfaceLabel} + ANUGA 2D 全市地表结果；${publicReturnPeriod} 年一遇、250 m 计算网格，结果未校准、未工程准入。`
        : ready && showCitywideSpatialResults
        ? '客户真实节点/管线几何 + EPA SWMM 全市连续网络最大值；当前为 Open-Meteo 公开代理降雨、未校准、未工程准入。'
        : ready && showCitywideRuntimeResult
        ? '客户 GDB 输入资产 + 全市连续网络 SWMM 作业状态；不是分区面或积水点。'
        : ready && showCitywideCompileResult
        ? '客户 GDB 输入资产 + 全市连续网络 SWMM 编译覆盖；动态水动力结果尚未生成。'
        : showDtmResult
        ? '客户 dtm_5M.tif + ANUGA 2D 局部地表结果；最大积水深度已回挂真实坐标，动态水深可在验证阶段播放。当前为诊断运行，未校准、未工程准入。'
        : ready && showProxyResults
        ? '客户 GDB 输入资产 + Open-Meteo 公开代理强迫下的 EPA SWMM 5.2.4 诊断结果；结果未校准、未工程准入。'
        : ready
          ? '客户 GDB 的私有格式派生几何；结果图层尚未接入或当前阶段没有结果输出。'
          : '尚未检测到客户 GDB 派生图层，地图保持空白以避免展示虚构空间结果。',
      source_status: showPublicCitywide2dResult
        ? (publicCustomerSurface ? 'customer_dtm5m_citywide_2d_result' : 'public_copernicus_citywide_2d_prototype')
        : showDtmResult
        ? 'customer_dtm_private_derived_result'
        : ready ? 'customer_gdb_private_derivative' : 'customer_geometry_not_available',
      layer_group: showPublicCitywide2dResult ? (publicCustomerSurface ? 'customer_dtm5m_citywide_2d_results' : 'public_copernicus_citywide_2d_results') : showDtmResult ? 'customer_dtm_anuga_2d_results' : showCitywideSpatialResults ? 'swmm_citywide_spatial_results' : 'raw_input_assets',
      result_status: showPublicCitywide2dResult
        ? (publicCustomerSurface ? 'customer_dtm5m_citywide_2d_not_admitted' : 'public_copernicus_citywide_2d_not_admitted')
        : showDtmResult
        ? 'customer_dtm_anuga_2d_diagnostic_not_admitted'
        : showCitywideSpatialResults ? 'swmm_citywide_spatial_results_not_admitted' : showCitywideRuntimeResult ? 'swmm_citywide_partition_runtime_status_not_admitted' : showProxyResults ? 'swmm_public_proxy_prototype_not_admitted' : 'swmm_results_not_available',
      event_id: showPublicCitywide2dResult
        ? (publicCustomerSurface ? 'abu-dhabi-customer-dtm5m-citywide-anuga' : 'abu-dhabi-public-copernicus-citywide-anuga-20260906')
        : showDtmResult
        ? 'abu-dhabi-customer-dtm5m-anuga-20260905'
        : showCitywideSpatialResults ? 'abu-dhabi-open-meteo-proxy-72h-swmm-citywide-20260824' : showProxyResults ? 'abu-dhabi-public-proxy-72h-swmm-prototype-20260822' : undefined,
      forcing_source: showPublicCitywide2dResult || showDtmResult || showCitywideSpatialResults || showProxyResults ? `Public Zone B DDF ${publicReturnPeriod}-year / 180-minute precipitation` : undefined,
      solver: showPublicCitywide2dResult || showDtmResult ? 'ANUGA 2D' : showCitywideSpatialResults || showProxyResults ? 'EPA SWMM 5.2.4' : undefined,
    },
    center: mapCenter,
    zoom: mapZoom,
    layers,
  };
  return withCustomerHotspotOverlay(localizeAbuLayerMetadata(mapUpdate), customerHotspots);
}

function buildScenarioResultMapUpdate(payload: any) {
  const runId = String(payload?.metadata?.run_id || 'unknown');
  const totalNodeCount = Number(payload?.metadata?.total_node_result_count || payload?.metadata?.timeline?.total_node_count || 0);
  const missingGeometryCount = Number(payload?.metadata?.missing_geometry_count || 0);
  const mappedNodeCount = Number(payload?.metadata?.node_feature_count || Math.max(0, totalNodeCount - missingGeometryCount));
  const geometryCoveragePercent = totalNodeCount > 0 ? (mappedNodeCount / totalNodeCount) * 100 : 0;
  const nativeTimeline = payload?.metadata?.timeline?.available
    ? {
      runId,
      endpoint: `/api/abu-dhabi/flood/scenarios/${encodeURIComponent(runId)}/map/timeseries?format=columns`,
      timeValues: Array.isArray(payload.metadata.timeline.time_values) ? payload.metadata.timeline.time_values : [],
      elapsedMinutes: Array.isArray(payload.metadata.timeline.elapsed_minutes) ? payload.metadata.timeline.elapsed_minutes : [],
      periodCount: Number(payload.metadata.timeline.period_count || 0),
      reportStepMinutes: Math.max(1, Number(payload.metadata.timeline.step_minutes || 5)),
      totalNodeCount: mappedNodeCount,
      kind: 'swmm-node' as const,
    }
    : undefined;
  const emptySlice = { type: 'FeatureCollection', features: [] };
  const rainfallSource = String(payload?.metadata?.rainfall_source || '本次情景降雨输入');
  const displayedRainfallSource = localizeAbuText(rainfallSource);
  const mapUpdate = {
    schema: 'map_update.v1',
    summary: {
      title: localizeAbuPair('阿布扎比暴雨内涝世界模型 · EPA SWMM 诊断作业', 'Abu Dhabi Stormwater Flood World Model · EPA SWMM diagnostic run'),
      subtitle: nativeTimeline
        ? localizeAbuPair(
          `原生 OUT 包含 ${totalNodeCount.toLocaleString()} 个结果节点；当前地图可定位 ${mappedNodeCount.toLocaleString()} 个（${geometryCoveragePercent.toFixed(1)}%），${missingGeometryCount.toLocaleString()} 个因几何缺失暂不可视化。已映射节点不按数值阈值或数量截断，并包含零值节点；可按 ${nativeTimeline.reportStepMinutes} 分钟报告步播放。降雨输入：${displayedRainfallSource}。`,
          `The native OUT contains ${totalNodeCount.toLocaleString()} result nodes. The map can locate ${mappedNodeCount.toLocaleString()} (${geometryCoveragePercent.toFixed(1)}%); ${missingGeometryCount.toLocaleString()} nodes cannot currently be visualized because geometry is missing. Mapped nodes are not filtered by value threshold or count and include zero values. Playback uses the ${nativeTimeline.reportStepMinutes}-minute reporting step. Rainfall input: ${displayedRainfallSource}.`,
        )
        : localizeAbuPair(
          `本次 SWMM 原生 RPT 的节点最大水深和节点溢流结果已回挂客户真实节点几何；降雨输入：${displayedRainfallSource}；作业汇总仅作为辅助层。`,
          `Maximum node depth and overflow from the native SWMM RPT are joined to customer node geometry. Rainfall input: ${displayedRainfallSource}. The run summary is auxiliary only.`,
        ),
      source_status: 'interactive_swmm_run_result',
      layer_group: 'interactive_swmm_scenario_results',
      result_status: 'diagnostic_partition_summary',
      event_id: runId,
      solver: payload?.metadata?.solver || 'EPA SWMM 5.2.4',
      result_boundary: nativeTimeline
        ? 'node_level_native_swmm_out_timeseries_joined_to_customer_node_geometry'
        : payload?.metadata?.result_boundary || 'node_level_maxima_joined_to_customer_node_geometry',
      claim_boundary: payload?.metadata?.claim_boundary || 'diagnostic only; not calibrated or engineering admitted',
      map_node_completeness: payload?.metadata?.map_node_completeness || 'geometry_coverage_not_reported',
      total_node_result_count: totalNodeCount,
      mapped_node_count: mappedNodeCount,
      missing_geometry_count: missingGeometryCount,
      geometry_coverage_fraction: payload?.metadata?.geometry_coverage_fraction,
    },
    center: [24.46, 54.45],
    zoom: 10,
    layers: [
      {
        name: localizeAbuPair(`EPA SWMM 诊断作业 · 节点最大水深 · ${runId}`, `EPA SWMM diagnostic run · maximum node depth · ${runId}`),
        type: 'bubble',
        geojsonData: nativeTimeline ? emptySlice : payload,
        scenarioTimeline: nativeTimeline,
        value_column: nativeTimeline ? 'scenario_water_depth_m' : 'scenario_max_water_depth_m',
        breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 3],
        color_scheme: 'YlOrRd',
        legend_title: '节点最大水深（m）',
        style: { min_radius: 2, max_radius: 13, color: '#7f1d1d', opacity: 0.9, fillOpacity: 0.72 },
        tooltip_fields: [
          'node_id',
          'partition_label',
          ...(nativeTimeline
            ? ['scenario_timestamp', 'scenario_elapsed_minutes', 'scenario_water_depth_m', 'scenario_hydraulic_head_m', 'scenario_overflow_or_flooding_m3s', 'scenario_total_inflow_m3s']
            : ['scenario_max_water_depth_m', 'scenario_max_hydraulic_head_m', 'scenario_max_overflow_or_flooding_m3s', 'scenario_flooded_hours', 'scenario_total_flood_volume_million_litres']),
          'scenario_node_flooding_detected',
          'scenario_max_depth_time',
        ],
        tooltip_labels: {
          node_id: '节点 ID',
          partition_label: '分区',
          scenario_max_water_depth_m: '节点最大水深（m）',
          scenario_water_depth_m: '当前节点水深（m）',
          scenario_timestamp: '模拟时刻',
          scenario_elapsed_minutes: '模拟经过（分钟）',
          scenario_hydraulic_head_m: '液压水头（m）',
          scenario_overflow_or_flooding_m3s: '当前溢流量（m³/s）',
          scenario_max_hydraulic_head_m: '最大液压水头（m）',
          scenario_max_overflow_or_flooding_m3s: '最大溢流量（m³/s）',
          scenario_flooded_hours: '积水时长（小时）',
          scenario_total_flood_volume_million_litres: '累计溢流量（百万升）',
          scenario_node_flooding_detected: '节点积水',
          scenario_max_depth_time: '最大水深时刻',
        },
      },
      {
        name: localizeAbuPair(`EPA SWMM 诊断作业 · 节点溢流/积水 · ${runId}`, `EPA SWMM diagnostic run · node overflow/flooding · ${runId}`),
        type: 'bubble',
        geojsonData: nativeTimeline
          ? emptySlice
          : { type: 'FeatureCollection', features: (Array.isArray(payload?.features) ? payload.features : []).filter((feature: any) => Number(feature?.properties?.scenario_max_overflow_or_flooding_m3s || 0) > 0) },
        scenarioTimeline: nativeTimeline,
        value_column: nativeTimeline ? 'scenario_overflow_or_flooding_m3s' : 'scenario_max_overflow_or_flooding_m3s',
        breaks: [0.0001, 0.001, 0.005, 0.01, 0.03, 0.1],
        color_scheme: 'Reds',
        legend_title: '节点最大溢流/积水（m³/s）',
        visible: false,
        style: { min_radius: 3, max_radius: 15, color: '#7f1d1d', opacity: 0.95, fillOpacity: 0.8 },
        tooltip_fields: nativeTimeline
          ? ['node_id', 'partition_label', 'scenario_timestamp', 'scenario_elapsed_minutes', 'scenario_overflow_or_flooding_m3s', 'scenario_water_depth_m']
          : ['node_id', 'partition_label', 'scenario_max_overflow_or_flooding_m3s', 'scenario_flooded_hours', 'scenario_total_flood_volume_million_litres'],
        tooltip_labels: {
          node_id: '节点 ID', partition_label: '分区', scenario_timestamp: '模拟时刻', scenario_elapsed_minutes: '模拟经过（分钟）',
          scenario_overflow_or_flooding_m3s: nativeTimeline ? '当前溢流量（m³/s）' : '最大溢流量（m³/s）',
          scenario_water_depth_m: '当前节点水深（m）', scenario_max_overflow_or_flooding_m3s: '最大溢流量（m³/s）',
          scenario_flooded_hours: '积水时长（小时）', scenario_total_flood_volume_million_litres: '累计溢流量（百万升）',
        },
      },
      {
        name: localizeAbuPair(`EPA SWMM 诊断作业 · 作业汇总（辅助） · ${runId}`, `EPA SWMM diagnostic run · run summary (auxiliary) · ${runId}`),
        type: 'bubble',
        geojsonData: { type: 'FeatureCollection', features: Array.isArray(payload?.partition_features) ? payload.partition_features : [] },
        value_column: 'scenario_flooding_loss_million_litres',
        breaks: [0.01, 0.1, 1, 10, 100],
        color_scheme: 'YlOrRd',
        legend_title: '分区洪涝损失（百万升）',
        visible: false,
        style: { min_radius: 7, max_radius: 24, color: '#7f1d1d', opacity: 0.95, fillOpacity: 0.78 },
        tooltip_fields: ['partition_label', 'runtime_status', 'scenario_external_outflow_million_litres', 'scenario_flooding_loss_million_litres', 'scenario_routing_continuity_error_percent', 'scenario_node_flooding_detected'],
        tooltip_labels: { partition_label: '分区', runtime_status: '运行状态', scenario_external_outflow_million_litres: '外排量（百万升）', scenario_flooding_loss_million_litres: '洪涝损失（百万升）', scenario_routing_continuity_error_percent: '路由连续性误差（%）', scenario_node_flooding_detected: '节点积水' },
      },
    ],
  };
  return localizeAbuLayerMetadata(mapUpdate);
}

/** Build the isolated phase-4 GWM map contract.
 *
 * GWM deliberately publishes baseline/intervention/delta surface products
 * under their own layer names.  The intervention layer owns the lazy
 * timeline endpoint; SWMM and ANUGA layers are never reused here.
 */
function buildGwmResultMapUpdate(payload: any) {
  const metadata = payload?.metadata || {};
  const runId = String(metadata.run_id || payload?.run_id || 'unknown');
  const timeline = metadata.timeline?.available ? metadata.timeline : null;
  const emptySlice = { type: 'FeatureCollection', features: [] };
  if (metadata.model_mode === 'trained_event_rollout') {
    const event = metadata.event || {};
    const periodCount = Number(timeline?.period_count || 0);
    const cellCount = Number(timeline?.total_cell_count || metadata.grid?.rows * metadata.grid?.columns || 0);
    const trainingEventCount = Number(metadata.model?.training_event_count || 0);
    const externalValidation = metadata.external_validation;
    const maximumDepth = payload?.maximum_depth || emptySlice;
    const surface = payload?.surface || payload || emptySlice;
    const timelineConfig = timeline?.endpoint
      ? {
        runId,
        endpoint: String(timeline.endpoint),
        timeValues: Array.isArray(timeline.time_values) ? timeline.time_values : [],
        elapsedMinutes: Array.isArray(timeline.elapsed_minutes) ? timeline.elapsed_minutes : [],
        periodCount,
        reportStepMinutes: Math.max(1, Number(timeline.step_minutes || 5)),
        totalNodeCount: cellCount,
        initialTimeIndex: Math.max(0, Math.min(
          Number.isInteger(timeline.initial_time_index) ? Number(timeline.initial_time_index) : 0,
          Math.max(0, periodCount - 1),
        )),
        kind: 'gwm-surface-cell' as const,
      }
      : undefined;
    const mapUpdate = {
      schema: 'map_update.v1',
      summary: {
        title: localizeAbuPair('阿布扎比暴雨内涝世界模型 · 历史事件 GWM R1', 'Abu Dhabi Stormwater Flood World Model · historical-event GWM R1'),
        subtitle: externalValidation
          ? localizeAbuPair(
            `冻结的 GWM R1 研究代理对 2024 外部留出事件进行推理；已延长零雨退水尾段至 Sentinel-2 过境时相，地图初始帧为 T+${Number(externalValidation.model_frame_seconds || 0) / 60} min 同相位切片。`,
            `The frozen GWM R1 research emulator infers the 2024 external holdout. A zero-rainfall recession tail extends to the Sentinel-2 overpass, and the initial map frame is the phase-aligned T+${Number(externalValidation.model_frame_seconds || 0) / 60} min slice.`,
          )
          : localizeAbuPair(
            `冻结的 GWM R1 研究代理对历史降雨场次 ${String(event.event_id || runId)} 进行推理；${trainingEventCount} 场训练事件、${cellCount.toLocaleString()} 个 250 m 陆域网格、${periodCount} 个 5 分钟时间片。`,
            `The frozen GWM R1 research emulator infers historical rainfall event ${String(event.event_id || runId)} using ${trainingEventCount} training events, ${cellCount.toLocaleString()} 250 m land cells, and ${periodCount} five-minute time slices.`,
          ),
        source_status: 'gwm_r1_trained_event_rollout',
        layer_group: 'gwm_r1_trained_surface_results',
        result_status: 'gwm_research_emulator_not_engineering_admitted',
        event_id: String(event.event_id || runId),
        solver: String(metadata.solver || 'five-year rainfall-conditioned GWM'),
        claim_boundary: metadata.claim_boundary || 'Frozen five-year research GWM inference. It is not an engineering replacement for the physical solver.',
        external_holdout: Boolean(event.external_holdout),
        training_forbidden: Boolean(event.training_forbidden),
      },
      center: [24.46, 54.45],
      zoom: 10,
      layers: [
        {
          name: localizeAbuPair(`历史事件 GWM R1 · 最大积水深度 · ${runId}`, `Historical-event GWM R1 · maximum flood depth · ${runId}`),
          type: 'choropleth' as const,
          geojsonData: maximumDepth,
          value_column: 'maximum_depth_m',
          breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 3],
          color_scheme: 'Blues',
          legend_title: localizeAbuPair('历史事件 GWM R1 最大积水深度（m）', 'Historical-event GWM R1 maximum flood depth (m)'),
          visible: false,
          style: { weight: 0.15, opacity: 0.72, fillOpacity: 0.76 },
          tooltip_fields: ['cell_id', 'maximum_depth_m', 'event_id', 'event_split', 'external_holdout'],
          tooltip_labels: { cell_id: '250 m 网格 ID', maximum_depth_m: '最大积水深度（m）', event_id: '历史降雨场次', event_split: '数据拆分', external_holdout: '外部留出' },
        },
        {
          name: localizeAbuPair(`历史事件 GWM R1 · 动态积水深度 · ${runId}`, `Historical-event GWM R1 · dynamic flood depth · ${runId}`),
          type: 'choropleth' as const,
          geojsonData: surface,
          scenarioTimeline: timelineConfig,
          value_column: 'depth_m',
          breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 3],
          color_scheme: 'Blues',
          legend_title: localizeAbuPair('历史事件 GWM R1 动态积水深度（m）', 'Historical-event GWM R1 dynamic flood depth (m)'),
          style: { weight: 0.15, opacity: 0.8, fillOpacity: 0.8 },
          tooltip_fields: ['cell_id', 'time_minutes', 'depth_m', 'event_id', 'event_split', 'external_holdout'],
          tooltip_labels: { cell_id: '250 m 网格 ID', time_minutes: '模拟时间（分钟）', depth_m: '积水深度（m）', event_id: '历史降雨场次', event_split: '数据拆分', external_holdout: '外部留出' },
        },
      ],
    };
    return localizeAbuLayerMetadata(mapUpdate);
  }
  const period = Number(metadata.return_period_years || 100);
  const count = Number(metadata.source_feature_count || timeline?.total_cell_count || 0);
  const activeCount = Number(metadata.active_cell_count || 0);
  const excludedWaterCount = Number(metadata.excluded_water_cell_count || 0);
  const sourceClass = String(metadata.surface_source_class || metadata.surface_evidence_class || '').toLowerCase();
  const sourceValue = String(metadata.surface_source || metadata.surface_product || '').toLowerCase();
  const customerSurface = sourceClass.includes('customer') || sourceClass.includes('dtm') || sourceValue.includes('customer') || sourceValue.includes('dtm');
  const baselineSourceLabel = customerSurface ? '客户 5 m DTM 阶段 3 基线' : 'Copernicus DEM GLO-30 阶段 3 回退基线';
  const baseline = payload?.baseline_maximum || emptySlice;
  const intervention = payload?.intervention_maximum || emptySlice;
  const delta = payload?.delta_maximum || emptySlice;
  const timelineConfig = timeline
    ? {
      runId,
      endpoint: `/api/abu-dhabi/flood/gwm/runs/${encodeURIComponent(runId)}/map/timeseries`,
      timeValues: Array.isArray(timeline.time_values) ? timeline.time_values : [],
      elapsedMinutes: Array.isArray(timeline.elapsed_minutes) ? timeline.elapsed_minutes : [],
      periodCount: Number(timeline.period_count || 0),
      reportStepMinutes: Math.max(1, Number(timeline.step_minutes || 30)),
      totalNodeCount: count,
      initialTimeIndex: Math.max(0, Math.min(
        Number.isInteger(timeline.initial_time_index) ? Number(timeline.initial_time_index) : 0,
        Math.max(0, Number(timeline.period_count || 0) - 1),
      )),
      kind: 'gwm-surface-cell' as const,
    }
    : undefined;
  const mapUpdate = {
    schema: 'map_update.v1',
    summary: {
      title: '阿布扎比暴雨内涝世界模型 · GWM 快速推演',
      subtitle: `GWM 基于${baselineSourceLabel}进行 ${period} 年一遇快速 rollout；${count.toLocaleString()} 个二维单元（${activeCount.toLocaleString()} 个陆域有效单元，排除 ${excludedWaterCount.toLocaleString()} 个水域单元）${timelineConfig ? `、${timelineConfig.periodCount} 个时间片` : ''}。`,
      source_status: 'gwm_phase4_rapid_rollout',
      layer_group: 'gwm_phase4_surface_results',
      result_status: 'gwm_screening_not_admitted',
      event_id: runId,
      solver: 'GWM rapid rollout adapter',
      claim_boundary: metadata.claim_boundary || 'GWM phase-4 rapid rollout for screening; high-risk cases return to SWMM/ANUGA.',
      return_period_years: period,
      actions: metadata.actions || {},
    },
    center: [24.46, 54.45],
    zoom: 10,
    layers: [
      {
        name: `GWM 基线 · ${period} 年一遇最大积水深度 · ${runId}`,
        type: 'choropleth' as const,
        geojsonData: baseline,
        value_column: 'baseline_depth_m',
        breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 3],
        color_scheme: 'Blues',
        legend_title: 'GWM 基线最大积水深度（m）',
        style: { weight: 0.15, opacity: 0.72, fillOpacity: 0.72 },
        tooltip_fields: ['cell_id', 'baseline_depth_m', 'source_depth_m', 'land_fraction', 'permanent_water_fraction', 'water_dominated', 'uncertainty_m'],
        tooltip_labels: { cell_id: '二维单元 ID', baseline_depth_m: '基线积水深度（m）', source_depth_m: '阶段 3 源深度（m）', land_fraction: '陆地比例', permanent_water_fraction: '永久水体比例', water_dominated: '水域主导单元', uncertainty_m: '不确定性（m）' },
      },
      {
        name: `GWM 干预 · ${period} 年一遇动态积水深度 · ${runId}`,
        type: 'choropleth' as const,
        // Bootstrap with the first renderable frame so the result is visible
        // immediately in both map modes. MapPanel replaces this payload with
        // the selected timeline frame once the timeline is active.
        geojsonData: payload?.intervention || emptySlice,
        scenarioTimeline: timelineConfig,
        value_column: 'intervention_depth_m',
        breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 3],
        color_scheme: 'YlOrRd',
        legend_title: 'GWM 干预积水深度（m）',
        style: { weight: 0.15, opacity: 0.8, fillOpacity: 0.8 },
        tooltip_fields: ['cell_id', 'time_minutes', 'baseline_depth_m', 'intervention_depth_m', 'delta_depth_m', 'source_depth_m', 'spatial_response_factor', 'action_sensitivity_score', 'water_dominated', 'uncertainty_m'],
        tooltip_labels: { cell_id: '二维单元 ID', time_minutes: '模拟时间（分钟）', baseline_depth_m: '基线深度（m）', intervention_depth_m: '干预深度（m）', delta_depth_m: '变化量（m）', source_depth_m: '阶段 3 源深度（m）', spatial_response_factor: '空间响应倍率', action_sensitivity_score: '行动敏感度', water_dominated: '水域主导单元', uncertainty_m: '不确定性（m）' },
      },
      {
        name: `GWM 影响差值 · ${period} 年一遇 · ${runId}`,
        type: 'choropleth' as const,
        geojsonData: delta,
        value_column: 'delta_depth_m',
        breaks: [-1, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5],
        color_scheme: 'RdBu',
        legend_title: 'GWM 干预相对基线变化（m）',
        visible: false,
        style: { weight: 0.15, opacity: 0.78, fillOpacity: 0.78 },
        tooltip_fields: ['cell_id', 'baseline_depth_m', 'intervention_depth_m', 'delta_depth_m', 'spatial_response_factor', 'action_sensitivity_score', 'water_dominated', 'uncertainty_m'],
        tooltip_labels: { cell_id: '二维单元 ID', baseline_depth_m: '基线深度（m）', intervention_depth_m: '干预深度（m）', delta_depth_m: '变化量（m）', spatial_response_factor: '空间响应倍率', action_sensitivity_score: '行动敏感度', water_dominated: '水域主导单元', uncertainty_m: '不确定性（m）' },
      },
    ],
  };
  return localizeAbuLayerMetadata(mapUpdate);
}

/** Build the independent phase-5 historical replay validation map contract. */
function buildHistoricalValidationMapUpdate(payload: HistoricalReplayValidation) {
  const metadata = payload?.metadata || {};
  const timeline = metadata.timeline?.available ? metadata.timeline : null;
  const runId = String(metadata.run_id || 'abu-dhabi-april-2024-historical-replay');
  const periodCount = Number(timeline?.period_count || 0);
  const cellCount = Number(timeline?.total_cell_count || metadata.domain?.active_land_cells || 0);
  const maximumDepth = payload?.maximum_depth || { type: 'FeatureCollection', features: [] };
  const timelineConfig = timeline && timeline.endpoint
    ? {
      runId,
      endpoint: String(timeline.endpoint),
      timeValues: Array.isArray(timeline.time_values) ? timeline.time_values : [],
      elapsedMinutes: Array.isArray(timeline.elapsed_minutes) ? timeline.elapsed_minutes : [],
      periodCount,
      reportStepMinutes: Math.max(1, Number(timeline.step_minutes || 120)),
      totalNodeCount: cellCount,
      initialTimeIndex: Math.max(0, Math.min(
        Number.isInteger(timeline.initial_time_index) ? Number(timeline.initial_time_index) : 0,
        Math.max(0, periodCount - 1),
      )),
      kind: 'surface-cell' as const,
    }
    : undefined;
  const mapUpdate = {
    schema: 'map_update.v1',
    summary: {
      title: '阿布扎比暴雨内涝世界模型 · 2024 历史事件重演验证',
      subtitle: `客户 DTM + 客户 2024 年 4 月历史降雨 · SWMM→ANUGA 2D 数值重演；${cellCount.toLocaleString()} 个陆域二维单元、${periodCount} 个时间片。`,
      source_status: 'customer_historical_replay_validation',
      layer_group: 'abu_dhabi_phase5_historical_replay_validation',
      result_status: String(metadata.validation?.status || 'historical_replay_numerical_validation_observation_pending'),
      event_id: runId,
      solver: metadata.solver || 'EPA SWMM 5.2.4 + ANUGA 2D',
      claim_boundary: metadata.claim_boundary || 'Historical replay numerical validation; observation comparison and engineering admission remain pending.',
    },
    center: [24.46, 54.45],
    zoom: 10,
    layers: [
      {
        name: '2024 历史重演 · 最大积水深度',
        type: 'choropleth' as const,
        geojsonData: maximumDepth,
        value_column: 'maximum_depth_m',
        breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 3],
        color_scheme: 'YlOrRd',
        legend_title: '历史重演最大积水深度（m）',
        style: { weight: 0.15, opacity: 0.76, fillOpacity: 0.78 },
        tooltip_fields: ['cell_id', 'maximum_depth_m', 'maximum_depth_time_minutes', 'final_depth_m'],
        tooltip_labels: { cell_id: '二维单元 ID', maximum_depth_m: '最大积水深度（m）', maximum_depth_time_minutes: '最大深度时刻（分钟）', final_depth_m: '末时刻积水深度（m）' },
      },
      {
        name: '2024 历史重演 · 动态积水深度',
        type: 'choropleth' as const,
        geojsonData: { type: 'FeatureCollection', features: [] },
        scenarioTimeline: timelineConfig,
        value_column: 'depth_m',
        breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 3],
        color_scheme: 'Blues',
        legend_title: '历史重演动态积水深度（m）',
        style: { weight: 0.15, opacity: 0.8, fillOpacity: 0.8 },
        tooltip_fields: ['cell_id', 'time_minutes', 'depth_m'],
        tooltip_labels: { cell_id: '二维单元 ID', time_minutes: '模拟时间（分钟）', depth_m: '积水深度（m）' },
      },
    ],
  };
  return localizeAbuLayerMetadata(mapUpdate);
}

/** Build the read-only Sentinel-2 observed-water map contract. */
function buildSentinelObservationMapUpdate(payload: SentinelObservationMapPayload) {
  const featureCount = Number(payload.feature_count || payload.geojson?.features?.length || 0);
  const mapUpdate = {
    schema: 'map_update.v1',
    summary: {
      title: '阿布扎比暴雨内涝世界模型 · 2024 Sentinel-2 观测积水',
      subtitle: `2024-04-17 雨后 Sentinel-2 新增地表水观测；${featureCount.toLocaleString()} 个 250 m 观测单元，独立外部留出集，不代表实测水深。`,
      source_status: 'sentinel2_external_holdout_observation',
      layer_group: 'abu_dhabi_april_2024_sentinel2_observation',
      result_status: 'observation_only_not_physics_depth',
      event_id: 'noaa-isd-ae-202404151200-0327',
      solver: 'Sentinel-2 L2A spectral observation',
      claim_boundary: payload.claim_boundary,
    },
    center: [24.46, 54.45],
    zoom: 10,
    layers: [
      {
        name: '2024 历史观测 · Sentinel-2 新增地表水（250 m）',
        type: 'choropleth' as const,
        geojsonData: payload.geojson,
        value_column: 'observed_water_fraction_of_valid_pixels',
        breaks: [0.02, 0.05, 0.10, 0.25, 0.50, 0.75, 1],
        color_scheme: 'ObservedBlues',
        legend_title: '观测新增水体占有效像元比例',
        style: { color: '#082f49', weight: 0.7, opacity: 0.98, fillOpacity: 0.86 },
        tooltip_fields: ['cell_id', 'observed_water_fraction_of_valid_pixels', 'valid_fraction', 'observation_time_utc', 'source_resolution_m'],
        tooltip_labels: {
          cell_id: '250 m 观测单元',
          observed_water_fraction_of_valid_pixels: '有效像元新增水体比例',
          valid_fraction: '成对有效覆盖比例',
          observation_time_utc: '卫星观测时间（UTC）',
          source_resolution_m: '地图聚合分辨率（m）',
        },
      },
    ],
  };
  return localizeAbuLayerMetadata(mapUpdate);
}

export default function AbuDhabiFloodWorldModelTab() {
  const { t, i18n: activeI18n } = useTranslation('common');
  const zhUiText: Record<string, string> = {
    title: '城市暴雨内涝世界模型',
    subtitle: '从权威数据、物理模拟到 GWM 快速推演的全流程工作台。',
    'hero.diagnosticReady': '诊断链路可运行',
    'hero.calibrationPending': '工程校准未准入',
    'hero.eventPending': '2024-04 历史重演已接入',
    'hero.stagesAvailable': '阶段能力已就绪',
    'hero.customerGdbVerified': '客户 GDB 已接入并完成空间规范化，工程语义待确认',
    'hero.eventCalibrationPending': '事件与校准数据仍待准入',
    'pipeline.statusHint': '右上角图标表示阶段能力或成果是否已就绪，不代表工程校准或准入。',
    'pipeline.complete': '阶段能力或成果已就绪；不代表工程准入',
    'pipeline.waiting': '等待阶段能力或成果就绪',
    'terminology.aria': '模型范围与适用边界',
    'terminology.title': '模型范围与适用边界',
    'terminology.body': '当前一维结果来自全市连续网络 EPA SWMM 5.2.4 诊断作业，并回挂至可解析的客户管网空间几何。模型尚未完成工程校准；降雨时空分布、管网工程属性、泵站运行、潮位边界及积水观测仍需进一步核验。当前结果用于技术验证和方案筛选，不构成工程设计或城市级预测结论。',
    'metrics.aria': '当前项目快照',
    'metrics.pipelines': '客户规范化管线',
    'metrics.nodes': '客户规范化节点',
    'metrics.network': 'SWMM 全市连续网络',
    'metrics.oneRun': '1 个作业',
    'metrics.crs': '空间参考',
    'metrics.p0': '工程语义',
    'scenario.aria': '城市降雨内涝情景模拟',
    'scenario.title': '情景模拟输入',
    'scenario.badge': '真实 SWMM 诊断',
    'scenario.run': '运行 SWMM 情景模拟',
    'scenario.running': '正在运行 SWMM 情景模拟…',
    'scenario.disclaimer': '按钮会真实调用 EPA SWMM 5.2.4 的全市连续网络并保存原生 RPT / OUT；设计暴雨可直接使用 2022 年官方 Zone B DDF 的 2/5/10/25/50/100 年一遇、180 分钟雨量。DDF 表未给出完整时间雨型，当前 5 分钟交替块分配和 40% 峰值位置属于明确建模假设。结果未校准、未工程准入。',
  };
  const en = (key: string, fallback: string, options?: Record<string, unknown>) => {
    const locale = getLocale();
    const defaultValue = locale === 'zh-CN' ? (zhUiText[key] || fallback) : fallback;
    return t(`abuDhabiFlood.${key}`, { defaultValue, ...(options || {}) });
  };
  // Start from the data/admission stage so an operator can verify the source
  // assets before opening any derived hydraulic result. Result stages remain
  // directly selectable from the stage rail.
  const [selectedKey, setSelectedKey] = useState('data');
  const [view, setView] = useState<'flow' | 'models' | 'deliverables' | 'event' | 'observation'>('flow');
  const [mapSent, setMapSent] = useState(false);
  const [customerMapReady, setCustomerMapReady] = useState(false);
  const [customerHotspots, setCustomerHotspots] = useState<CustomerHotspotsBootstrap | null>(null);
  const [customerHotspotsChecked, setCustomerHotspotsChecked] = useState(false);
  const [customerHotspotsError, setCustomerHotspotsError] = useState<string | null>(null);
  const [swmmResultReady, setSwmmResultReady] = useState(false);
  const [cityCompileReady, setCityCompileReady] = useState(false);
  const [cityRuntimeReady, setCityRuntimeReady] = useState(false);
  const [cityDynamicResultReady, setCityDynamicResultReady] = useState(false);
  const [citySpatialResultReady, setCitySpatialResultReady] = useState(false);
  const [customerDtmDiagnostic, setCustomerDtmDiagnostic] = useState<CustomerDtmDiagnostic | null>(null);
  const [publicCitywide2dDiagnostic, setPublicCitywide2dDiagnostic] = useState<PublicCitywide2dDiagnostic | null>(null);
  const [surfaceWorkspaceView, setSurfaceWorkspaceView] = useState<SurfaceWorkspaceView>('invoke');
  const [surfaceRunForm, setSurfaceRunForm] = useState<SurfaceRunForm>(DEFAULT_SURFACE_RUN);
  const [surfaceRunReceipt, setSurfaceRunReceipt] = useState<SurfaceRunReceipt | null>(null);
  const [surfaceRunBusy, setSurfaceRunBusy] = useState(false);
  const [surfaceRunError, setSurfaceRunError] = useState<string | null>(null);
  const [surfaceReturnPeriodYears, setSurfaceReturnPeriodYears] = useState<ReturnPeriodYears>(100);
  const [surfaceResultSource, setSurfaceResultSource] = useState<SurfaceResultSource>('return_period_one_way');
  const [surfaceReturnPeriodLoading, setSurfaceReturnPeriodLoading] = useState(false);
  const [surfaceReturnPeriodError, setSurfaceReturnPeriodError] = useState<string | null>(null);
  const [surfaceReloadToken, setSurfaceReloadToken] = useState(0);
  const [surfaceInvocationReceipt, setSurfaceInvocationReceipt] = useState<{
    runId: string;
    returnPeriodYears: number;
    loadedAt: string;
  } | null>(null);
  const [runtimeCountLabel, setRuntimeCountLabel] = useState('全市连续网络 · 单个 SWMM 作业');
  const [runtimeFailureLabel, setRuntimeFailureLabel] = useState('失败原因按分区查看');
  const [customerMapChecked, setCustomerMapChecked] = useState(false);
  const [scenario, setScenario] = useState<FloodScenarioForm>(DEFAULT_FLOOD_SCENARIO);
  const [scenarioRun, setScenarioRun] = useState<ScenarioRun | null>(null);
  const [scenarioMapPayload, setScenarioMapPayload] = useState<any | null>(null);
  const scenarioMapPayloadRef = useRef<any | null>(null);
  const [scenarioBusy, setScenarioBusy] = useState(false);
  // Phase-4 GWM state is intentionally independent from the SWMM scenario
  // state above.  This prevents a GWM rollout from replacing a native OUT
  // result or causing stages 1–3 to render the wrong map contract.
  const [gwmRun, setGwmRun] = useState<any | null>(null);
  const [gwmMapPayload, setGwmMapPayload] = useState<any | null>(null);
  const gwmMapPayloadRef = useRef<any | null>(null);
  const [gwmBusy, setGwmBusy] = useState(false);
  const [gwmError, setGwmError] = useState<string | null>(null);
  const [gwmMode, setGwmMode] = useState<GwmMode>('trained');
  const [trainedGwmEvents, setTrainedGwmEvents] = useState<TrainedGwmEvent[]>([]);
  const [trainedGwmModel, setTrainedGwmModel] = useState<TrainedGwmModelCatalog | null>(null);
  const [trainedGwmEventsLoading, setTrainedGwmEventsLoading] = useState(false);
  const [trainedGwmEventsError, setTrainedGwmEventsError] = useState<string | null>(null);
  const [trainedGwmEventId, setTrainedGwmEventId] = useState('');
  const [gwmReturnPeriodYears, setGwmReturnPeriodYears] = useState<ReturnPeriodYears>(10);
  const [gwmActions, setGwmActions] = useState({
    pipeCapacityMultiplier: 1,
    blockagePercent: 0,
    pumpCapacityMultiplier: 1,
    outfallLevelAdjustment: 0,
  });
  const [historicalReplayValidation, setHistoricalReplayValidation] = useState<HistoricalReplayValidation | null>(null);
  const historicalReplayValidationRef = useRef<HistoricalReplayValidation | null>(null);
  const [historicalReplayLoading, setHistoricalReplayLoading] = useState(false);
  const [historicalReplayError, setHistoricalReplayError] = useState<string | null>(null);
  const [historicalReplayReportLoading, setHistoricalReplayReportLoading] = useState(false);
  const [simulationReportLoading, setSimulationReportLoading] = useState(false);
  const [simulationReportError, setSimulationReportError] = useState<string | null>(null);
  const [precomputedLoadStage, setPrecomputedLoadStage] = useState<'job' | 'timeline' | 'map' | null>(null);
  const precomputedRunIdRef = useRef<string | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [designStormBatch, setDesignStormBatch] = useState<any | null>(null);
  const [designStormBatchLoading, setDesignStormBatchLoading] = useState(true);
  const [designStormBatchError, setDesignStormBatchError] = useState<string | null>(null);
  const [eventEvidence, setEventEvidence] = useState<any | null>(null);
  const [eventEvidenceLoading, setEventEvidenceLoading] = useState(false);
  const [sentinelObservation, setSentinelObservation] = useState<SentinelObservationDashboard | null>(null);
  const [sentinelObservationLoading, setSentinelObservationLoading] = useState(false);
  const [sentinelObservationError, setSentinelObservationError] = useState<string | null>(null);
  const [sentinelObservationMap, setSentinelObservationMap] = useState<SentinelObservationMapPayload | null>(null);
  const sentinelObservationMapRef = useRef<SentinelObservationMapPayload | null>(null);
  const [sentinelObservationMapLoading, setSentinelObservationMapLoading] = useState(false);
  const [sentinelObservationMapError, setSentinelObservationMapError] = useState<string | null>(null);
  const [sentinelObservationMapSent, setSentinelObservationMapSent] = useState(false);
  const originalTextNodesRef = useRef(new WeakMap<Text, string>());
  const originalAttributesRef = useRef(new WeakMap<HTMLElement, Record<string, string>>());
  const customerDtmSurfaceActive = isCustomerDtmSurface(publicCitywide2dDiagnostic);
  const customerDtmBidirectionalSurfaceActive = String(publicCitywide2dDiagnostic?.metadata?.result_variant || '') === 'bidirectional_validation';
  // Pipeline progress is deliberately separate from the engineering-maturity
  // status on each stage. A green check means the stage capability or result
  // is ready; it never means calibration or engineering admission has passed.
  const pipelineStageCompletion = useMemo<Record<string, boolean>>(() => ({
    data: customerMapChecked && customerMapReady && customerHotspotsChecked && Boolean(customerHotspots),
    swmm: Boolean(
      scenarioMapPayload
      && scenarioRun
      && ['completed', 'completed_with_warnings'].includes(String(scenarioRun.status)),
    ),
    surface: Boolean(
      publicCitywide2dDiagnostic?.maximum_depth?.type === 'FeatureCollection'
      && Number(publicCitywide2dDiagnostic?.metadata?.timeline?.period_count || 0) > 0,
    ),
    gwm: Boolean(
      trainedGwmModel?.release_id
      && Number(trainedGwmModel.training_event_count || 0) > 0
      && trainedGwmEvents.length > 0,
    ),
    validation: Boolean(
      historicalReplayValidation?.maximum_depth?.type === 'FeatureCollection'
      && sentinelObservation?.event?.external_holdout === true
      && sentinelObservationMap?.geojson?.type === 'FeatureCollection',
    ),
  }), [
    customerMapChecked,
    customerMapReady,
    customerHotspots,
    customerHotspotsChecked,
    historicalReplayValidation,
    publicCitywide2dDiagnostic,
    scenarioMapPayload,
    scenarioRun,
    sentinelObservation,
    sentinelObservationMap,
    trainedGwmEvents.length,
    trainedGwmModel,
  ]);
  const completedStageCount = useMemo(
    () => stages.filter(stage => pipelineStageCompletion[stage.key]).length,
    [pipelineStageCompletion],
  );
  const displayStages = useMemo(() => stages.map(stage => {
    if (stage.key !== 'surface') return stage;
    return {
      ...stage,
      statusLabel: customerDtmSurfaceActive
        ? customerDtmBidirectionalSurfaceActive
          ? '客户 5 m DTM · 250 m · 双向验证成果已加载'
          : '客户 5 m DTM 输入 · 250 m 计算网格'
        : '公共 DEM 全市二维原型已接入',
      summary: customerDtmSurfaceActive
        ? customerDtmBidirectionalSurfaceActive
          ? '当前加载为客户 5 m DTM 的 100 年一遇 SWMM–ANUGA 同步双向数值验证成果；回执记录正向与反向交换，但尚未完成观测校准、原生运行日志证明和工程准入。'
          : '客户 5 m DTM 作为地形输入，ANUGA 2D 实际采用 250 m 计算网格并接受 SWMM 单向源项；2/5/10/25/50/100 年一遇结果可切换，但尚未完成观测校准和工程准入。'
        : stage.summary,
    };
  }), [customerDtmBidirectionalSurfaceActive, customerDtmSurfaceActive]);
  const selectedStage = useMemo(
    () => displayStages.find(stage => stage.key === selectedKey) || displayStages[0],
    [displayStages, selectedKey],
  );
  const selectedTrainedGwmEvent = useMemo(
    () => trainedGwmEvents.find(event => event.event_id === trainedGwmEventId) || null,
    [trainedGwmEventId, trainedGwmEvents],
  );
  const StageIcon = selectedStage.icon;
  const controlsBusy = scenarioBusy || surfaceRunBusy || gwmBusy || precomputedLoadStage !== null;

  // Keep this legacy-rich domain tab readable in every language, including
  // text generated after a SWMM run (status receipts, validation errors, and
  // map-layer summaries). The original Chinese nodes are retained so a user
  // can switch back from English/Arabic without leaving stale translated DOM.
  useEffect(() => {
    const root = document.querySelector<HTMLElement>('.abu-flood-tab');
    if (!root) return;
    const locale = getLocale();
    const translate = () => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const textNodes: Text[] = [];
      let current: Node | null;
      while ((current = walker.nextNode())) textNodes.push(current as Text);
      textNodes.forEach(node => {
        const value = node.nodeValue || '';
        if (locale === 'en-US') {
          // React may update a text node while English mode is active. If the
          // new value contains Han characters, treat it as the latest source
          // string before translating it.
          if (/[\u3400-\u9fff]/.test(value)) originalTextNodesRef.current.set(node, value);
          const source = originalTextNodesRef.current.get(node) || value;
          const next = translateAbuEnglishText(source);
          if (next !== value) node.nodeValue = next;
        } else {
          const original = originalTextNodesRef.current.get(node);
          if (original !== undefined && value !== original) node.nodeValue = original;
        }
      });
      root.querySelectorAll<HTMLElement>('[aria-label], [title], [placeholder]').forEach(element => {
        for (const attribute of ['aria-label', 'title', 'placeholder']) {
          const value = element.getAttribute(attribute);
          if (!value) continue;
          const originals = originalAttributesRef.current.get(element) || {};
          if (locale === 'en-US') {
            if (/[\u3400-\u9fff]/.test(value)) originals[attribute] = value;
            const source = originals[attribute] || value;
            element.setAttribute(attribute, translateAbuEnglishText(source));
          } else if (originals[attribute] !== undefined) {
            element.setAttribute(attribute, originals[attribute]);
          }
          originalAttributesRef.current.set(element, originals);
        }
      });
    };
    translate();
    if (locale !== 'en-US') return;
    const observer = new MutationObserver(() => {
      observer.disconnect();
      translate();
      observer.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['aria-label', 'title', 'placeholder'] });
    });
    observer.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['aria-label', 'title', 'placeholder'] });
    return () => observer.disconnect();
  }, [activeI18n.resolvedLanguage, scenarioRun, scenarioMapPayload, customerMapReady, citySpatialResultReady, cityRuntimeReady, cityCompileReady, view, selectedKey]);

  const loadHistoricalReplayValidation = useCallback(async () => {
    setHistoricalReplayLoading(true);
    setHistoricalReplayError(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/validation/historical-replay/bootstrap', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(String(payload?.error || '历史重演验证结果暂不可用'));
      if (payload?.maximum_depth?.type !== 'FeatureCollection') throw new Error('历史重演最大积水深度结果格式无效');
      historicalReplayValidationRef.current = payload;
      setHistoricalReplayValidation(payload);
      return payload as HistoricalReplayValidation;
    } catch (error) {
      const message = error instanceof Error ? error.message : '历史重演验证结果加载失败';
      setHistoricalReplayError(message);
      return null;
    } finally {
      setHistoricalReplayLoading(false);
    }
  }, []);

  const loadSentinelObservation = useCallback(async () => {
    setSentinelObservationLoading(true);
    setSentinelObservationError(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/validation/april-2024/sentinel-observation', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(String(payload?.error || '2024 历史观测产品暂不可用'));
      if (payload?.event?.external_holdout !== true || payload?.event?.training_forbidden !== true) {
        throw new Error('2024 历史观测留出集契约无效');
      }
      setSentinelObservation(payload as SentinelObservationDashboard);
    } catch (error) {
      setSentinelObservation(null);
      setSentinelObservationError(error instanceof Error ? error.message : '2024 历史观测产品加载失败');
    } finally {
      setSentinelObservationLoading(false);
    }
  }, []);

  const loadSentinelObservationMap = useCallback(async () => {
    setSentinelObservationMapLoading(true);
    setSentinelObservationMapError(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/validation/april-2024/sentinel-observation/map', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(String(payload?.error || '2024 历史观测地图暂不可用'));
      if (payload?.geojson?.type !== 'FeatureCollection' || !Array.isArray(payload.geojson.features)) {
        throw new Error('2024 历史观测地图结果格式无效');
      }
      sentinelObservationMapRef.current = payload as SentinelObservationMapPayload;
      setSentinelObservationMap(payload as SentinelObservationMapPayload);
      return payload as SentinelObservationMapPayload;
    } catch (error) {
      sentinelObservationMapRef.current = null;
      setSentinelObservationMap(null);
      setSentinelObservationMapError(error instanceof Error ? error.message : '2024 历史观测地图加载失败');
      return null;
    } finally {
      setSentinelObservationMapLoading(false);
    }
  }, []);

  const showSentinelObservationOnMap = useCallback(async () => {
    const payload = sentinelObservationMapRef.current || await loadSentinelObservationMap();
    if (!payload) return;
    const mapHandler = (window as any).__handleMapUpdate;
    if (typeof mapHandler !== 'function') {
      setSentinelObservationMapError('地图组件尚未就绪，请刷新页面后重试');
      return;
    }
    mapHandler(withCustomerHotspotOverlay(buildSentinelObservationMapUpdate(payload), customerHotspots));
    setMapSent(true);
    setSentinelObservationMapSent(true);
  }, [customerHotspots, loadSentinelObservationMap]);

  const openHistoricalReplayReport = useCallback(async () => {
    // Open synchronously with the click so browser popup protection does not
    // suppress the customer report after the authenticated request completes.
    const reportWindow = window.open('', '_blank');
    if (!reportWindow) {
      setHistoricalReplayError('浏览器阻止了报告窗口，请允许本站点打开新窗口后重试。');
      return;
    }
    const reportLocale = getLocale();
    const reportTitle = reportLocale === 'zh-CN'
      ? '阿布扎比城市暴雨内涝世界模型 · 阶段5交付报告'
      : reportLocale === 'ar-AE'
        ? 'نموذج العالم للفيضانات المطرية في أبوظبي · تقرير المرحلة 5'
        : 'Abu Dhabi Urban Pluvial Flood World Model - Phase 5 Delivery Report';
    const reportLoading = reportLocale === 'zh-CN'
      ? '正在生成阶段5图文报告…'
      : reportLocale === 'ar-AE'
        ? 'جارٍ إنشاء تقرير المرحلة 5…'
        : 'Generating the phase 5 delivery report…';
    reportWindow.document.title = reportTitle;
    reportWindow.document.body.innerHTML = `<p style="font-family:Arial;padding:24px">${reportLoading}</p>`;
    setHistoricalReplayReportLoading(true);
    setHistoricalReplayError(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/validation/historical-replay/report', {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const html = await response.text();
      if (!response.ok) {
        let message = '阶段 5 图文报告暂不可用';
        try { message = String(JSON.parse(html)?.error || message); } catch { /* keep fallback */ }
        throw new Error(message);
      }
      reportWindow.document.open();
      reportWindow.document.write(html);
      reportWindow.document.close();
    } catch (error) {
      const message = error instanceof Error ? error.message : '阶段 5 图文报告生成失败';
      setHistoricalReplayError(message);
      reportWindow.document.body.textContent = message;
      reportWindow.document.body.style.cssText = 'font-family:Arial;padding:24px;color:#991b1b';
    } finally {
      setHistoricalReplayReportLoading(false);
    }
  }, []);

  const openSimulationReport = useCallback(async (reportType: string, options?: { runId?: string; returnPeriodYears?: number }) => {
    const reportWindow = window.open('', '_blank');
    if (!reportWindow) {
      setSimulationReportError('浏览器阻止了报告窗口，请允许本站点打开新窗口后重试。');
      return;
    }
    const locale = getLocale();
    const reportLoading = locale === 'zh-CN' ? '正在生成决策支持报告…' : locale === 'ar-AE' ? 'جارٍ إنشاء تقرير دعم القرار…' : 'Generating decision-support report…';
    reportWindow.document.title = locale === 'zh-CN' ? '阿布扎比暴雨内涝决策支持报告' : 'Abu Dhabi flood decision-support report';
    reportWindow.document.body.innerHTML = `<p style="font-family:Arial;padding:24px">${reportLoading}</p>`;
    setSimulationReportLoading(true);
    setSimulationReportError(null);
    try {
      const params = new URLSearchParams();
      if (options?.runId) params.set('run_id', options.runId);
      if (options?.returnPeriodYears) params.set('return_period_years', String(options.returnPeriodYears));
      const query = params.toString();
      const response = await fetch(`/api/abu-dhabi/flood/reports/${encodeURIComponent(reportType)}${query ? `?${query}` : ''}`, { credentials: 'include', headers: getLocaleHeaders() });
      const html = await response.text();
      if (!response.ok) {
        let message = '决策支持报告暂不可用';
        try { message = String(JSON.parse(html)?.error || message); } catch { /* keep fallback */ }
        throw new Error(message);
      }
      reportWindow.document.open();
      reportWindow.document.write(html);
      reportWindow.document.close();
    } catch (error) {
      const message = error instanceof Error ? error.message : '决策支持报告生成失败';
      setSimulationReportError(message);
      reportWindow.document.body.textContent = message;
      reportWindow.document.body.style.cssText = 'font-family:Arial;padding:24px;color:#991b1b';
    } finally {
      setSimulationReportLoading(false);
    }
  }, []);

  // Phase 5 is loaded independently so a late replay response cannot replace
  // the state or map contract owned by stages 1-4.
  useEffect(() => {
    loadHistoricalReplayValidation();
  }, [loadHistoricalReplayValidation]);

  useEffect(() => {
    const handleFrameLoaded = (event: Event) => {
      const detail = (event as CustomEvent).detail || {};
      if (!precomputedRunIdRef.current || detail.runId !== precomputedRunIdRef.current) return;
      precomputedRunIdRef.current = null;
      setPrecomputedLoadStage(null);
    };
    const handleFrameFailed = (event: Event) => {
      const detail = (event as CustomEvent).detail || {};
      if (!precomputedRunIdRef.current || detail.runId !== precomputedRunIdRef.current) return;
      precomputedRunIdRef.current = null;
      setPrecomputedLoadStage(null);
      setScenarioError(String(detail.message || '全量 SWMM 节点结果读取失败'));
    };
    window.addEventListener('swmm-scenario-frame-loaded', handleFrameLoaded);
    window.addEventListener('swmm-scenario-frame-failed', handleFrameFailed);
    return () => {
      window.removeEventListener('swmm-scenario-frame-loaded', handleFrameLoaded);
      window.removeEventListener('swmm-scenario-frame-failed', handleFrameFailed);
    };
  }, []);

  // Full-city return-period product. Customer 5 m DTM coupled results are
  // loaded first; the public Copernicus product is retained only as an
  // explicit fallback when the selected customer period is unavailable.
  useEffect(() => {
    let cancelled = false;
    setSurfaceReturnPeriodLoading(true);
    setSurfaceReturnPeriodError(null);
    const selectedPeriod = surfaceResultSource === 'bidirectional_validation' ? 100 : surfaceReturnPeriodYears;
    const resultSource = encodeURIComponent(surfaceResultSource);
    fetch(`/api/abu-dhabi/flood/public-citywide-2d/bootstrap?return_period_years=${selectedPeriod}&result_source=${resultSource}`, { credentials: 'include', headers: getLocaleHeaders() })
      .then(async response => {
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(String(payload?.detail || payload?.error || `二维结果请求失败（HTTP ${response.status}）`));
        }
        return payload;
      })
      .then(payload => {
        if (cancelled) return;
        if (payload?.maximum_depth?.type === 'FeatureCollection') {
          setPublicCitywide2dDiagnostic(payload);
          setSurfaceInvocationReceipt({
            runId: String(payload.metadata?.timeline?.run_id || 'registered-anuga-result'),
            returnPeriodYears: Number(payload.metadata?.return_period_years || selectedPeriod),
            loadedAt: new Date().toISOString(),
          });
          const available = Array.isArray(payload.metadata?.available_return_periods) ? payload.metadata.available_return_periods.map(Number) : [];
          if (!available.includes(selectedPeriod)) {
            setSurfaceReturnPeriodError(`${selectedPeriod} 年一遇二维结果当前未生成。`);
          }
        } else if (payload?.error) {
          setSurfaceReturnPeriodError(String(payload.error));
        } else {
          setSurfaceReturnPeriodError('二维结果响应格式无效，未找到最大深度图层。');
        }
      })
      .catch(error => {
        if (!cancelled) setSurfaceReturnPeriodError(error instanceof Error ? error.message : '二维重现期结果加载失败');
      })
      .finally(() => {
        if (!cancelled) setSurfaceReturnPeriodLoading(false);
      });
    return () => { cancelled = true; };
  }, [surfaceReloadToken]);

  // Restore the latest completed private run after a browser refresh. The
  // server returns only the auditable run receipt; native OUT slices are still
  // requested lazily by MapPanel through the timeline endpoint.
  useEffect(() => {
    let cancelled = false;
    const restoreLatestRun = async () => {
      try {
        const response = await fetch('/api/abu-dhabi/flood/scenarios/latest', { credentials: 'include', headers: getLocaleHeaders() });
        if (!response.ok) return;
        const latest = await response.json();
        if (!['completed', 'completed_with_warnings'].includes(String(latest?.status))) return;
        const runId = String(latest?.run_id || '');
        if (!runId || cancelled) return;
        const mapResponse = await fetch(
          `/api/abu-dhabi/flood/scenarios/${encodeURIComponent(runId)}/map/bootstrap`,
          { credentials: 'include', headers: getLocaleHeaders() },
        );
        const mapPayload = await mapResponse.json();
        if (!mapResponse.ok || cancelled) return;
        const partitionRows = Array.isArray(latest.partitions) ? latest.partitions : [];
        const latestSummary = partitionRows.find((row: any) => row?.result_summary)?.result_summary;
        scenarioMapPayloadRef.current = mapPayload;
        setScenarioMapPayload(mapPayload);
        setScenarioRun(current => current || {
          runId,
          status: String(latest.status),
          startedAt: String(latest.started_at || latest.created_at || ''),
          finishedAt: String(latest.finished_at || ''),
          restoredFromLatestCompleted: true,
          peakIntensityMmPerHour: Number(latest.scenario?.rainfall_stats?.peak_intensity_mm_per_hour || 0),
          generatedIntervals: Number(latest.scenario?.rainfall_stats?.generated_intervals || 0),
          generatedTotalDepthMm: Number(latest.scenario?.rainfall_stats?.generated_total_depth_mm || latest.scenario?.total_depth_mm || 0),
          rainfallMode: latest.scenario?.rainfall_mode,
          rainfallSource: latest.scenario?.rainfall_stats?.source_label,
          actionSummary: '已恢复最近成功完成的 EPA SWMM 诊断作业；这不代表最近一次提交尝试成功',
          claimBoundary: 'EPA SWMM 诊断作业；严格数值质量门未通过，未校准、未工程准入，不构成城市级预测声明。',
          totalPartitions: Number(latest.total_partitions || latest.summary?.partition_count || 1),
          completedPartitions: Number(latest.summary?.completed_count || 0),
          failedPartitions: Number(latest.summary?.failed_count || 0),
          warnings: latest.warnings,
          actualSummary: latestSummary,
          partitions: partitionRows,
        });
      } catch (error) {
        console.warn('[AbuDhabiFloodWorldModelTab] latest SWMM run restore failed:', error);
      }
    };
    restoreLatestRun();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    void loadSentinelObservation();
  }, [loadSentinelObservation]);

  useEffect(() => {
    void loadSentinelObservationMap();
  }, [loadSentinelObservationMap]);

  // Public event evidence is a separate, non-spatial product. It is loaded
  // only when available and never published through the shared map handler.
  useEffect(() => {
    let cancelled = false;
    setEventEvidenceLoading(true);
    fetch('/api/abu-dhabi/flood/events/april-2024/evidence', { credentials: 'include', headers: getLocaleHeaders() })
      .then(response => response.ok ? response.json() : null)
      .then(payload => {
        if (!cancelled) setEventEvidence(payload);
      })
      .catch(() => {
        if (!cancelled) setEventEvidence(null);
      })
      .finally(() => {
        if (!cancelled) setEventEvidenceLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const loadDesignStormBatchCatalog = useCallback(async (surfaceError = false): Promise<any | null> => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20_000);
    setDesignStormBatchLoading(true);
    setDesignStormBatchError(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/design-storms/latest', {
        credentials: 'include',
        headers: getLocaleHeaders(),
        signal: controller.signal,
      });
      const contentType = response.headers.get('content-type') || '';
      if (response.status === 401) throw new Error('登录会话已失效，请重新登录后加载预计算结果。');
      if (!contentType.toLowerCase().includes('application/json')) {
        throw new Error('预计算结果目录接口返回了页面内容而不是 JSON，请确认后端服务已启动并刷新页面。');
      }
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.detail || payload?.error || '预计算结果目录不存在或接口不可用，请检查后端服务。');
      }
      const requiredReturnPeriods = [2, 5, 10, 25, 50, 100];
      const runs = Array.isArray(payload?.runs) ? payload.runs : [];
      if (requiredReturnPeriods.some(returnPeriod => !runs.some((row: any) => (
        Number(row?.return_period_years) === returnPeriod && Boolean(row?.run_id)
      )))) {
        throw new Error('预计算结果目录数据不完整，必须包含 2/5/10/25/50/100 年一遇六套结果。');
      }
      setDesignStormBatch(payload);
      return payload;
    } catch (error) {
      const message = error instanceof DOMException && error.name === 'AbortError'
        ? '预计算结果目录加载超时，请确认后端服务已启动后重试。'
        : error instanceof Error
        ? error.message
        : '预计算结果目录加载失败，请检查后端服务后重试。';
      setDesignStormBatch(null);
      setDesignStormBatchError(message);
      if (surfaceError) setScenarioError(message);
      console.warn('[AbuDhabiFloodWorldModelTab] Zone B batch catalog restore failed:', error);
      return null;
    } finally {
      window.clearTimeout(timeout);
      setDesignStormBatchLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDesignStormBatchCatalog();
  }, [loadDesignStormBatchCatalog]);

  // The map panel can mount one render after this tab during a full-page
  // restore. Retry briefly so the restored timeline is not lost when the
  // global map handler is not available on the first effect pass.
  useEffect(() => {
    if (!scenarioMapPayload || selectedKey !== 'swmm') return;
    const publish = () => {
      const mapHandler = (window as any).__handleMapUpdate;
      if (typeof mapHandler !== 'function') return false;
      mapHandler(withCustomerHotspotOverlay(buildScenarioResultMapUpdate(scenarioMapPayload), customerHotspots));
      setMapSent(true);
      return true;
    };
    if (publish()) return;
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (publish() || attempts >= 20) window.clearInterval(timer);
    }, 150);
    return () => window.clearInterval(timer);
  }, [customerHotspots, scenarioMapPayload, selectedKey]);

  // The trained model accepts only the frozen historical-event catalog. Load
  // its read-only catalog during workbench bootstrap so pipeline readiness
  // reflects the already-frozen GWM release; a new rollout is an invocation,
  // not a prerequisite for declaring the stage capability available.
  useEffect(() => {
    if (gwmMode !== 'trained' || trainedGwmEvents.length) return;
    let cancelled = false;
    setTrainedGwmEventsLoading(true);
    setTrainedGwmEventsError(null);
    fetch('/api/abu-dhabi/flood/gwm/trained/events', { credentials: 'include', headers: getLocaleHeaders() })
      .then(async response => {
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error(String(payload?.error || '历史事件 GWM R1 场次目录读取失败'));
        const events = Array.isArray(payload?.events) ? payload.events.filter((event: unknown): event is TrainedGwmEvent => (
          Boolean(event)
          && typeof (event as TrainedGwmEvent).event_id === 'string'
          && typeof (event as TrainedGwmEvent).split === 'string'
        )) : [];
        if (!events.length) throw new Error('历史事件 GWM R1 没有可推理的历史降雨场次');
        if (cancelled) return;
        setTrainedGwmModel(payload?.model || null);
        setTrainedGwmEvents(events);
        setTrainedGwmEventId(current => events.some((event: TrainedGwmEvent) => event.event_id === current) ? current : events[0].event_id);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setTrainedGwmModel(null);
          setTrainedGwmEventsError(error instanceof Error ? error.message : '历史事件 GWM R1 场次目录读取失败');
        }
      })
      .finally(() => { if (!cancelled) setTrainedGwmEventsLoading(false); });
    return () => { cancelled = true; };
  }, [gwmMode, trainedGwmEvents.length]);

  // Publish only the GWM map contract when stage 4 is selected. This effect
  // is separate from SWMM so a late SWMM/ANUGA response cannot overwrite the
  // GWM baseline/intervention/delta layers.
  useEffect(() => {
    if (!gwmMapPayload || selectedKey !== 'gwm') return;
    const publish = () => {
      const mapHandler = (window as any).__handleMapUpdate;
      if (typeof mapHandler !== 'function') return false;
      mapHandler(withCustomerHotspotOverlay(buildGwmResultMapUpdate(gwmMapPayload), customerHotspots));
      setMapSent(true);
      return true;
    };
    if (publish()) return;
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (publish() || attempts >= 20) window.clearInterval(timer);
    }, 150);
    return () => window.clearInterval(timer);
  }, [customerHotspots, gwmMapPayload, selectedKey]);

  // Publish only the independent phase-5 replay contract when validation is
  // selected. The retry handles the map component mounting one render later.
  useEffect(() => {
    if (!historicalReplayValidation || selectedKey !== 'validation') return;
    const publish = () => {
      const mapHandler = (window as any).__handleMapUpdate;
      if (typeof mapHandler !== 'function') return false;
      mapHandler(withCustomerHotspotOverlay(buildHistoricalValidationMapUpdate(historicalReplayValidation), customerHotspots));
      setMapSent(true);
      return true;
    };
    if (publish()) return;
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (publish() || attempts >= 20) window.clearInterval(timer);
    }, 150);
    return () => window.clearInterval(timer);
  }, [customerHotspots, historicalReplayValidation, selectedKey]);

  // The Sentinel-2 observation is an independent read-only map contract. It
  // is published when the observation sub-view is selected and can never
  // overwrite a SWMM, GWM, or physics-replay layer in another view.
  useEffect(() => {
    if (!sentinelObservationMap || view !== 'observation') return;
    const publish = () => {
      const mapHandler = (window as any).__handleMapUpdate;
      if (typeof mapHandler !== 'function') return false;
      mapHandler(withCustomerHotspotOverlay(buildSentinelObservationMapUpdate(sentinelObservationMap), customerHotspots));
      setMapSent(true);
      setSentinelObservationMapSent(true);
      return true;
    };
    if (publish()) return;
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (publish() || attempts >= 20) window.clearInterval(timer);
    }, 150);
    return () => window.clearInterval(timer);
  }, [customerHotspots, sentinelObservationMap, view]);

  const rainfallProfile = useMemo(() => {
    if (scenario.rainfallPattern === 'official_zone_b_ddf_abm') {
      return buildZoneBProfile(scenario.returnPeriodYears, scenario.peakPosition);
    }
    const peak = Math.max(0.05, Math.min(0.95, scenario.peakPosition / 100));
    const values = Array.from({ length: 18 }, (_, index) => {
      const x = (index + 0.5) / 18;
      if (scenario.rainfallPattern === 'uniform') return 1;
      if (scenario.rainfallPattern === 'front_loaded') return 1.7 - x * 1.15;
      const distance = Math.abs(x - peak);
      return Math.max(0.16, 1.7 - distance * 3.8);
    });
    const maximum = Math.max(...values);
    return values.map(value => Number((value / maximum).toFixed(3)));
  }, [scenario.peakPosition, scenario.rainfallPattern, scenario.returnPeriodYears]);

  const isDesignStorm = scenario.rainfallMode === 'design_storm';
  const isOnlinePublicRainfall = scenario.rainfallMode === 'online_public';
  const isPublicStationEvent = scenario.rainfallMode === 'public_station_event';
  const isOfficialZoneBStorm = isDesignStorm && scenario.rainfallPattern === 'official_zone_b_ddf_abm';

  const updateScenario = <K extends keyof FloodScenarioForm>(key: K, value: FloodScenarioForm[K]) => {
    setScenario(current => ({ ...current, [key]: value }));
    setScenarioError(null);
  };

  const updateRainfallPattern = (rainfallPattern: RainfallPattern) => {
    setScenario(current => rainfallPattern === 'official_zone_b_ddf_abm'
      ? {
        ...current,
        rainfallPattern,
        durationMinutes: 180,
        tailMinutes: 60,
        outputIntervalMinutes: 30,
        totalDepthMm: zoneB180DepthByReturnPeriod[current.returnPeriodYears],
      }
      : { ...current, rainfallPattern });
    setScenarioError(null);
  };

  const updateRainfallMode = (rainfallMode: RainfallMode) => {
    setScenario(current => rainfallMode === 'public_station_event'
      ? {
        ...current,
        rainfallMode,
        startTime: '2024-04-15T00:00',
        durationMinutes: 4320,
        tailMinutes: 0,
        outputIntervalMinutes: 30,
        rainfallPattern: 'uniform',
      }
      : { ...current, rainfallMode });
    setScenarioError(null);
  };

  const updateReturnPeriod = (returnPeriodYears: ReturnPeriodYears) => {
    setScenario(current => ({
      ...current,
      returnPeriodYears,
      durationMinutes: 180,
      totalDepthMm: zoneB180DepthByReturnPeriod[returnPeriodYears],
    }));
    setScenarioError(null);
  };

  const updateSurfaceRun = <K extends keyof SurfaceRunForm>(key: K, value: SurfaceRunForm[K]) => {
    setSurfaceRunForm(current => ({ ...current, [key]: value }));
    setSurfaceRunError(null);
  };

  const resetSurfaceRun = () => {
    setSurfaceRunForm(DEFAULT_SURFACE_RUN);
    setSurfaceRunReceipt(null);
    setSurfaceRunError(null);
  };

  const runSurfaceModel = async () => {
    setSurfaceRunError(null);
    setSurfaceRunBusy(true);
    setSurfaceRunReceipt(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/surface/runs', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          solver: surfaceRunForm.solver,
          coupling_mode: surfaceRunForm.couplingMode,
          rainfall_source: surfaceRunForm.rainfallSource,
          return_period_years: surfaceRunForm.returnPeriodYears,
          rainfall_duration_minutes: surfaceRunForm.rainfallDurationMinutes,
          peak_position_percent: surfaceRunForm.peakPositionPercent,
          terrain_source: surfaceRunForm.terrainSource,
          domain: surfaceRunForm.domain,
          cell_size_m: surfaceRunForm.cellSizeM,
          land_manning_n: surfaceRunForm.landManningN,
          water_manning_n: surfaceRunForm.waterManningN,
          initial_depth_m: surfaceRunForm.initialDepthM,
          minimum_output_depth_m: surfaceRunForm.minimumOutputDepthM,
          tail_minutes: surfaceRunForm.tailMinutes,
          output_interval_minutes: surfaceRunForm.outputIntervalMinutes,
          boundary_type: surfaceRunForm.boundaryType,
          sea_boundary_level_m: surfaceRunForm.seaBoundaryLevelM,
          water_cell_fraction_threshold: surfaceRunForm.waterCellFractionThreshold,
          exchange_window_seconds: surfaceRunForm.exchangeWindowSeconds,
          opening_area_m2: surfaceRunForm.openingAreaM2,
          discharge_coefficient: surfaceRunForm.dischargeCoefficient,
          maximum_exchange_rate_m3s: surfaceRunForm.maximumExchangeRateM3s,
          interface_detail_limit: surfaceRunForm.interfaceDetailLimit,
        }),
      });
      const created = await response.json().catch(() => null);
      if (!response.ok) throw new Error(String(created?.detail || created?.error || '二维模型作业提交失败'));
      const runId = String(created?.run_id || '');
      if (!runId) throw new Error('二维模型作业返回缺少 run_id');
      setSurfaceRunReceipt({
        runId,
        status: String(created?.status || 'queued'),
        createdAt: String(created?.created_at || ''),
        scenario: created?.scenario,
      });
      let completed: any = created;
      for (let attempt = 0; attempt < 3600; attempt += 1) {
        if (attempt > 0) await new Promise(resolve => window.setTimeout(resolve, 1000));
        const statusResponse = await fetch(`/api/abu-dhabi/flood/surface/runs/${encodeURIComponent(runId)}`, { credentials: 'include', headers: getLocaleHeaders() });
        const status = await statusResponse.json().catch(() => null);
        if (!statusResponse.ok) throw new Error(String(status?.detail || status?.error || '二维模型作业状态读取失败'));
        completed = status;
        setSurfaceRunReceipt({
          runId,
          status: String(status?.status || 'running'),
          createdAt: String(status?.created_at || created?.created_at || ''),
          startedAt: String(status?.started_at || ''),
          finishedAt: String(status?.finished_at || ''),
          failureReason: status?.failure_reason ? String(status.failure_reason) : undefined,
          failureDetail: status?.failure_detail ? String(status.failure_detail) : undefined,
          scenario: status?.scenario,
          summary: status?.summary,
        });
        if (status?.status === 'failed') throw new Error(String(status?.failure_detail || status?.failure_reason || '二维模型作业失败'));
        if (status?.status === 'completed') break;
      }
      if (completed?.status !== 'completed') throw new Error('二维模型作业等待超时，作业仍可能在后台运行');
      const mapResponse = await fetch(`/api/abu-dhabi/flood/surface/runs/${encodeURIComponent(runId)}/map/bootstrap`, { credentials: 'include', headers: getLocaleHeaders() });
      const mapPayload = await mapResponse.json().catch(() => null);
      if (!mapResponse.ok || mapPayload?.maximum_depth?.type !== 'FeatureCollection') {
        throw new Error(String(mapPayload?.detail || mapPayload?.error || '二维模型地图结果读取失败'));
      }
      setSelectedKey('surface');
      setSurfaceWorkspaceView('invoke');
      setPublicCitywide2dDiagnostic(mapPayload);
    } catch (error) {
      setSurfaceRunError(error instanceof Error ? error.message : '二维模型作业失败');
    } finally {
      setSurfaceRunBusy(false);
    }
  };

  const runScenarioPreview = async () => {
    setScenarioError(null);
    if (scenario.rainfallMode === 'historical_event') {
      setScenarioError('历史事件模式需要上传客户权威降雨时序和元数据；当前先使用设计暴雨原型。');
      return;
    }
    if (!Number.isFinite(scenario.durationMinutes) || scenario.durationMinutes < 5 || scenario.durationMinutes > 72 * 60) {
      setScenarioError('降雨时长必须在 5 分钟至 72 小时之间。');
      return;
    }
    if (isDesignStorm && (!Number.isFinite(scenario.totalDepthMm) || scenario.totalDepthMm <= 0 || scenario.totalDepthMm > 1000)) {
      setScenarioError('降雨总量必须大于 0，且不超过 1000 mm。');
      return;
    }
    if (scenario.scope === 'partition' && scenario.partition === 'all') {
      setScenarioError('选择单分区时，需要指定一个分区。');
      return;
    }
    if (scenario.pipeScope !== 'none' && scenario.blockagePercent <= 0 && scenario.pipeCapacityMultiplier === 1) {
      setScenarioError('已选择管线情景，请调整堵塞率或管线能力倍率，或恢复“无管线调整”。');
      return;
    }
    setScenarioBusy(true);
    scenarioMapPayloadRef.current = null;
    setScenarioMapPayload(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/scenarios', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(scenario),
      });
      const created = await response.json();
      if (!response.ok) throw new Error(created?.error || '真实 SWMM 情景提交失败');
      const actionSummary = scenario.pipeScope === 'none'
        ? (scenario.pumpEnabled ? '基线管网 · 泵站参数已提交，但当前基线无泵站链接，实际未应用' : '基线管网 · 泵站停用（当前基线无泵站链接）')
        : `${scenario.pipeScope === 'priority_corridor' ? '重点管廊' : '选定区域'} · 堵塞 ${scenario.blockagePercent}% · 管线能力 ${scenario.pipeCapacityMultiplier.toFixed(2)}x · ${scenario.pumpEnabled ? '泵站参数已提交，但当前基线无泵站链接' : '泵站停用'}`;
      setScenarioRun({
        runId: String(created.run_id),
        status: String(created.status || 'queued'),
        startedAt: new Date().toISOString(),
        peakIntensityMmPerHour: 0,
        generatedIntervals: Math.ceil(scenario.durationMinutes / 5),
        generatedTotalDepthMm: isDesignStorm ? scenario.totalDepthMm : 0,
          rainfallMode: scenario.rainfallMode,
          rainfallSource: isOnlinePublicRainfall ? '在线公开来源降雨数据（Open-Meteo）' : isPublicStationEvent ? `公开站点约束雨型（NOAA NCEI · ${scenario.publicStation}）` : isOfficialZoneBStorm ? `Abu Dhabi 2022 官方 Zone B DDF · ${scenario.returnPeriodYears} 年一遇` : '参数化设计暴雨',
          rainfallStats: undefined,
        actionSummary,
        claimBoundary: `EPA SWMM 诊断作业；使用${isOnlinePublicRainfall ? '在线公开来源降雨数据（Open-Meteo）' : isPublicStationEvent ? `NOAA NCEI ${scenario.publicStation} 12 小时累计约束的公开代理时序` : isOfficialZoneBStorm ? '2022 官方 Zone B DDF 雨量与假设交替块时程' : '参数化设计暴雨'}，未校准、未工程准入，不构成城市级预测声明。`,
        totalPartitions: Number(created.total_partitions || 1),
        completedPartitions: 0,
        currentPartition: null,
      });
      let run = created;
      for (let attempt = 0; attempt < 3600; attempt += 1) {
        if (attempt > 0) await new Promise(resolve => window.setTimeout(resolve, 1000));
        const statusResponse = await fetch(`/api/abu-dhabi/flood/scenarios/${encodeURIComponent(String(created.run_id))}`, { credentials: 'include', headers: getLocaleHeaders() });
        const statusPayload = await statusResponse.json();
        if (!statusResponse.ok) throw new Error(statusPayload?.error || 'SWMM 情景状态读取失败');
        run = statusPayload;
        const partitionRows = Array.isArray(run.partitions) ? run.partitions : [];
        const completed = partitionRows.filter((row: any) => ['completed', 'completed_quality_warning'].includes(row.status)).length;
        const failed = partitionRows.filter((row: any) => row.status === 'failed').length;
        const current = run.current_partition == null ? null : run.current_partition;
        const firstSummary = partitionRows.find((row: any) => row.result_summary?.external_outflow_million_litres != null)?.result_summary;
        setScenarioRun(currentRun => currentRun ? {
          ...currentRun,
          status: String(run.status || 'running'),
          finishedAt: String(run.finished_at || currentRun.finishedAt || ''),
          completedPartitions: completed,
          failedPartitions: failed,
          currentPartition: current,
          peakIntensityMmPerHour: Number(run.scenario?.rainfall_stats?.peak_intensity_mm_per_hour || currentRun.peakIntensityMmPerHour || 0),
          generatedTotalDepthMm: Number(run.scenario?.rainfall_stats?.generated_total_depth_mm || currentRun.generatedTotalDepthMm || 0),
          rainfallMode: run.scenario?.rainfall_mode || currentRun.rainfallMode,
          rainfallSource: run.scenario?.rainfall_stats?.source_label || currentRun.rainfallSource,
          rainfallStats: run.scenario?.rainfall_stats || currentRun.rainfallStats,
          summary: run.summary,
          warnings: run.warnings,
          partitions: partitionRows,
          ...(firstSummary ? { actualSummary: firstSummary } : {}),
        } : currentRun);
        if (['completed', 'completed_with_warnings'].includes(String(run.status))) {
          // The run receipt is not itself a spatial layer. Fetch the completed
          // partition summary and replace the previous static map state with
          // this run's dynamic GeoJSON immediately.
          try {
            const mapResponse = await fetch(`/api/abu-dhabi/flood/scenarios/${encodeURIComponent(String(created.run_id))}/map/bootstrap`, { credentials: 'include', headers: getLocaleHeaders() });
            const mapPayload = await mapResponse.json();
            if (!mapResponse.ok) throw new Error(mapPayload?.error || 'SWMM 情景地图结果读取失败');
            setSelectedKey('swmm');
            scenarioMapPayloadRef.current = mapPayload;
            setScenarioMapPayload(mapPayload);
          } catch (mapError: unknown) {
            setScenarioError(mapError instanceof Error ? mapError.message : 'SWMM 情景地图结果读取失败');
          }
          break;
        }
        if (String(run.status) === 'failed') {
          setScenarioError(String(run.failure_reason || '真实 SWMM 情景运行失败；请查看运行回执。'));
          break;
        }
      }
    } catch (error: unknown) {
      setScenarioError(error instanceof Error ? error.message : '真实 SWMM 情景运行失败');
    } finally {
      setScenarioBusy(false);
    }
  };

  const loadPrecomputedDesignStorm = async () => {
    const availableBatch = designStormBatch || await loadDesignStormBatchCatalog(true);
    if (!availableBatch) return;
    const selected = (availableBatch?.runs || []).find(
      (row: any) => Number(row.return_period_years) === scenario.returnPeriodYears,
    );
    if (!selected?.run_id) {
      setScenarioError(`${scenario.returnPeriodYears} 年一遇预计算结果尚未找到。`);
      return;
    }
    setPrecomputedLoadStage('job');
    setScenarioError(null);
    try {
      const runId = String(selected.run_id);
      precomputedRunIdRef.current = runId;
      const runResponse = await fetch(`/api/abu-dhabi/flood/scenarios/${encodeURIComponent(runId)}`, { credentials: 'include', headers: getLocaleHeaders() });
      const run = await runResponse.json();
      if (!runResponse.ok) throw new Error(run?.error || '预计算 SWMM 作业读取失败');
      setPrecomputedLoadStage('timeline');
      const mapResponse = await fetch(
        `/api/abu-dhabi/flood/scenarios/${encodeURIComponent(runId)}/map/bootstrap`,
        { credentials: 'include', headers: getLocaleHeaders() },
      );
      const mapPayload = await mapResponse.json();
      if (!mapResponse.ok) throw new Error(mapPayload?.error || '预计算 SWMM 时间轴读取失败');
      if (typeof (window as any).__handleMapUpdate !== 'function') {
        throw new Error('地图组件尚未就绪，请刷新页面后重试');
      }
      const partitionRows = Array.isArray(run.partitions) ? run.partitions : [];
      setPrecomputedLoadStage('map');
      setSelectedKey('swmm');
      scenarioMapPayloadRef.current = mapPayload;
      setScenarioMapPayload(mapPayload);
      setScenario(current => ({
        ...current,
        rainfallMode: 'design_storm',
        rainfallPattern: 'official_zone_b_ddf_abm',
        durationMinutes: 180,
        tailMinutes: Number(run.scenario?.tail_minutes || 60),
        outputIntervalMinutes: Number(run.scenario?.output_interval_minutes || 30),
        totalDepthMm: Number(selected.published_180_minute_depth_mm),
      }));
      setScenarioRun({
        runId,
        status: String(run.status),
        startedAt: String(run.started_at || run.created_at || ''),
        finishedAt: String(run.finished_at || ''),
        peakIntensityMmPerHour: Number(selected.rainfall_stats?.peak_intensity_mm_per_hour || 0),
        generatedIntervals: Number(selected.rainfall_stats?.generated_intervals || 36),
        generatedTotalDepthMm: Number(selected.published_180_minute_depth_mm || 0),
        rainfallMode: 'design_storm',
        rainfallSource: `Abu Dhabi 2022 官方 Zone B DDF · ${scenario.returnPeriodYears} 年一遇`,
        actionSummary: '已加载预计算的全市连续网络诊断基线',
        claimBoundary: selected.strict_quality_passed
          ? 'EPA SWMM 诊断作业；仍需工程校准和准入。'
          : 'EPA SWMM 诊断作业；严格数值质量门未通过，未校准、未工程准入。',
        totalPartitions: 1,
        completedPartitions: 1,
        failedPartitions: 0,
        summary: run.summary,
        actualSummary: selected.hydraulic_summary,
        warnings: run.warnings,
        partitions: partitionRows,
      });
    } catch (error: unknown) {
      precomputedRunIdRef.current = null;
      setPrecomputedLoadStage(null);
      setScenarioError(error instanceof Error ? error.message : '预计算 SWMM 结果加载失败');
    }
  };

  const runTrainedGwmRollout = async () => {
    if (!trainedGwmEventId) {
      setGwmError('请先选择一个已准入的历史降雨场次');
      return;
    }
    setGwmError(null);
    setGwmBusy(true);
    gwmMapPayloadRef.current = null;
    setGwmMapPayload(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/gwm/trained/rollout', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ eventId: trainedGwmEventId }),
      });
      const created = await response.json();
      if (!response.ok) throw new Error(created?.detail || created?.error || '历史事件 GWM R1 推理提交失败');
      const runId = String(created.run_id || '');
      if (!runId) throw new Error('历史事件 GWM R1 返回缺少 run_id');
      const [runResponse, mapResponse] = await Promise.all([
        fetch(`/api/abu-dhabi/flood/gwm/trained/runs/${encodeURIComponent(runId)}`, { credentials: 'include', headers: getLocaleHeaders() }),
        fetch(`/api/abu-dhabi/flood/gwm/trained/runs/${encodeURIComponent(runId)}/map`, { credentials: 'include', headers: getLocaleHeaders() }),
      ]);
      const run = await runResponse.json();
      const mapPayload = await mapResponse.json();
      if (!runResponse.ok) throw new Error(run?.detail || run?.error || '历史事件 GWM R1 运行回执读取失败');
      if (!mapResponse.ok) throw new Error(mapPayload?.detail || mapPayload?.error || '历史事件 GWM R1 地图结果读取失败');
      gwmMapPayloadRef.current = mapPayload;
      setGwmRun(run);
      setGwmMapPayload(mapPayload);
      setSelectedKey('gwm');
    } catch (error: unknown) {
      setGwmError(error instanceof Error ? error.message : '历史事件 GWM R1 推理失败');
    } finally {
      setGwmBusy(false);
    }
  };

  const runGwmRollout = async () => {
    setGwmError(null);
    setGwmBusy(true);
    gwmMapPayloadRef.current = null;
    setGwmMapPayload(null);
    try {
      // Make the phase-3 prerequisite explicit for operators.  The GWM
      // service reads the same precomputed ANUGA surface product, but the
      // selected return period may differ from the last surface view (for
      // example, the page starts on the 100-year result while GWM defaults to
      // 10 years).  Load that exact phase-3 result before submitting the
      // rollout so the map and the audit trail refer to one scenario.
      const loadedSurfaceReturnPeriod = Number(publicCitywide2dDiagnostic?.metadata?.return_period_years || 0);
      if (loadedSurfaceReturnPeriod !== gwmReturnPeriodYears) {
        setSurfaceReturnPeriodLoading(true);
        const surfaceResponse = await fetch(
          `/api/abu-dhabi/flood/public-citywide-2d/bootstrap?return_period_years=${encodeURIComponent(String(gwmReturnPeriodYears))}`,
          { credentials: 'include', headers: getLocaleHeaders() },
        );
        const surfacePayload = await surfaceResponse.json().catch(() => null);
        if (!surfaceResponse.ok || surfacePayload?.maximum_depth?.type !== 'FeatureCollection') {
          throw new Error(String(surfacePayload?.detail || surfacePayload?.error || '阶段 3 二维结果尚未准备，无法运行 GWM'));
        }
        setSurfaceReturnPeriodYears(gwmReturnPeriodYears);
        setPublicCitywide2dDiagnostic(surfacePayload);
        setSurfaceReturnPeriodLoading(false);
      }
      const response = await fetch('/api/abu-dhabi/flood/gwm/rollout', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          returnPeriodYears: gwmReturnPeriodYears,
          pipeCapacityMultiplier: gwmActions.pipeCapacityMultiplier,
          blockagePercent: gwmActions.blockagePercent,
          pumpCapacityMultiplier: gwmActions.pumpCapacityMultiplier,
          outfallLevelAdjustment: gwmActions.outfallLevelAdjustment,
          scenarioLabel: `GWM ${gwmReturnPeriodYears}-year screening rollout`,
        }),
      });
      const created = await response.json();
      if (!response.ok) throw new Error(created?.detail || created?.error || 'GWM 快速推演提交失败');
      const runId = String(created.run_id || '');
      if (!runId) throw new Error('GWM 返回缺少 run_id');
      const [runResponse, mapResponse] = await Promise.all([
        fetch(`/api/abu-dhabi/flood/gwm/runs/${encodeURIComponent(runId)}`, { credentials: 'include', headers: getLocaleHeaders() }),
        fetch(`/api/abu-dhabi/flood/gwm/runs/${encodeURIComponent(runId)}/map`, { credentials: 'include', headers: getLocaleHeaders() }),
      ]);
      const run = await runResponse.json();
      const mapPayload = await mapResponse.json();
      if (!runResponse.ok) throw new Error(run?.error || 'GWM 运行回执读取失败');
      if (!mapResponse.ok) throw new Error(mapPayload?.error || 'GWM 地图结果读取失败');
      gwmMapPayloadRef.current = mapPayload;
      setGwmRun(run);
      setGwmMapPayload(mapPayload);
      setSelectedKey('gwm');
    } catch (error: unknown) {
      setGwmError(error instanceof Error ? error.message : 'GWM 快速推演失败');
      setSurfaceReturnPeriodLoading(false);
    } finally {
      setGwmBusy(false);
    }
  };

  const resetScenario = () => {
    setScenario(DEFAULT_FLOOD_SCENARIO);
    setScenarioRun(null);
    setScenarioError(null);
    setScenarioBusy(false);
    setPrecomputedLoadStage(null);
    precomputedRunIdRef.current = null;
    scenarioMapPayloadRef.current = null;
    setScenarioMapPayload(null);
  };

  const sendStageToMap = (stageKey = selectedKey, ready = customerMapReady, resultReady = swmmResultReady, cityCompiled = cityCompileReady, cityRuntime = cityRuntimeReady, cityDynamicResult = cityDynamicResultReady, citySpatialResult = citySpatialResultReady, dtmDiagnostic = customerDtmDiagnostic, publicCitywide2d = publicCitywide2dDiagnostic) => {
    const handler = (window as any).__handleMapUpdate;
    if (typeof handler !== 'function') return;
    if (stageKey === 'swmm' && scenarioMapPayloadRef.current) {
      handler(withCustomerHotspotOverlay(buildScenarioResultMapUpdate(scenarioMapPayloadRef.current), customerHotspots));
      setMapSent(true);
      return;
    }
    if (stageKey === 'gwm' && gwmMapPayloadRef.current) {
      handler(withCustomerHotspotOverlay(buildGwmResultMapUpdate(gwmMapPayloadRef.current), customerHotspots));
      setMapSent(true);
      return;
    }
    if (stageKey === 'validation' && historicalReplayValidationRef.current) {
      handler(withCustomerHotspotOverlay(buildHistoricalValidationMapUpdate(historicalReplayValidationRef.current), customerHotspots));
      setMapSent(true);
      return;
    }
    handler(buildCustomerMapUpdate(stageKey, ready, resultReady, cityCompiled, cityRuntime, cityDynamicResult, citySpatialResult, dtmDiagnostic, publicCitywide2d, customerHotspots));
    setMapSent(true);
  };

  // The customer package is admitted as a static hotspot prior only. The API
  // validates all 506 official point IDs before any feature reaches the map;
  // auxiliary Booster points, engineering polygons and lines are excluded.
  useEffect(() => {
    let cancelled = false;
    setCustomerHotspotsError(null);
    fetch('/api/abu-dhabi/flood/customer-hotspots/bootstrap', { credentials: 'include', headers: getLocaleHeaders() })
      .then(async response => {
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error(String(payload?.detail || payload?.error || '客户积水热点读取失败'));
        if (payload?.geojson?.type !== 'FeatureCollection' || payload.geojson.features?.length !== 506) {
          throw new Error('客户积水热点图层未通过 506 点完整性校验');
        }
        if (!cancelled) setCustomerHotspots(payload as CustomerHotspotsBootstrap);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setCustomerHotspots(null);
          setCustomerHotspotsError(error instanceof Error ? error.message : '客户积水热点读取失败');
        }
      })
      .finally(() => { if (!cancelled) setCustomerHotspotsChecked(true); });
    return () => { cancelled = true; };
  }, []);

  // The customer DTM result is a private derived product served by the
  // authenticated diagnostic endpoint. It is intentionally loaded separately
  // from the raw FileGDB assets so the source raster never enters the browser
  // or public repository.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/abu-dhabi/flood/dtm-diagnostic/bootstrap', { credentials: 'include', headers: getLocaleHeaders() })
      .then(response => response.ok ? response.json() : null)
      .then(payload => {
        if (!cancelled && payload?.maximum_depth?.type === 'FeatureCollection') {
          setCustomerDtmDiagnostic(payload);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Refresh the shared map as soon as either the private DTM result or the
  // full-city public 2D prototype arrives. Both resources can become
  // available at different times after a page reload.
  useEffect(() => {
    if (!customerDtmDiagnostic && !publicCitywide2dDiagnostic && !customerHotspots) return;
    const publish = () => {
      const handler = (window as any).__handleMapUpdate;
      if (typeof handler !== 'function') return false;
      if (view === 'observation' && sentinelObservationMapRef.current) {
        handler(withCustomerHotspotOverlay(buildSentinelObservationMapUpdate(sentinelObservationMapRef.current), customerHotspots));
        setMapSent(true);
        setSentinelObservationMapSent(true);
        return true;
      }
      // An explicitly loaded SWMM scenario owns the SWMM/GWM map until the
      // user selects another stage. Late DTM/public-2D bootstrap responses
      // must not replace its native OUT timeline.
      const activeScenario = scenarioMapPayloadRef.current;
      const activeGwm = gwmMapPayloadRef.current;
      if ((activeScenario && selectedKey === 'swmm') || (activeGwm && selectedKey === 'gwm')) {
        // scenarioMapPayload's dedicated effect publishes the native OUT
        // result. Skipping here avoids duplicate 20 MB first-frame requests.
        return true;
      }
      // Phase 5 owns the validation map once its independent replay payload
      // is available. Keep the public design-storm prototype from replacing
      // the historical replay layer on the same render.
      if (selectedKey === 'validation' && historicalReplayValidationRef.current) {
        handler(withCustomerHotspotOverlay(buildHistoricalValidationMapUpdate(historicalReplayValidationRef.current), customerHotspots));
        setMapSent(true);
        return true;
      }
      handler(buildCustomerMapUpdate(selectedKey, customerMapReady, swmmResultReady, cityCompileReady, cityRuntimeReady, cityDynamicResultReady, citySpatialResultReady, customerDtmDiagnostic, publicCitywide2dDiagnostic, customerHotspots));
      setMapSent(true);
      return true;
    };
    if (publish()) return;
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (publish() || attempts >= 20) window.clearInterval(timer);
    }, 150);
    return () => window.clearInterval(timer);
  }, [customerDtmDiagnostic, publicCitywide2dDiagnostic, historicalReplayValidation, customerHotspots, customerMapReady, swmmResultReady, cityCompileReady, cityRuntimeReady, cityDynamicResultReady, citySpatialResultReady, selectedKey, view]);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/user/files', { credentials: 'include', headers: getLocaleHeaders() })
      .then(response => response.ok ? response.json() : [])
      .then(files => {
        if (cancelled) return;
        const names = new Set(Array.isArray(files) ? files.map((file: any) => String(file.name || '')) : []);
        // The map consumes durable PostGIS-backed MVT layers, while these
        // private full-resolution files remain the authoritative source and
        // readiness evidence for both visualization and model compilation.
        const ready = names.has('abu_dhabi_customer_stormwater_gdb_pipeline_full.fgb')
          && names.has('abu_dhabi_customer_stormwater_topology_nodes_full.fgb');
        const resultReady = names.has('abu_dhabi_swmm_public_proxy_pilot_nodes.geojson')
          && names.has('abu_dhabi_swmm_public_proxy_pilot_links.geojson');
        const cityCompiled = names.has('abu_dhabi_city_swmm_full_compile_summary.json');
        const cityRuntime = names.has('abu_dhabi_city_swmm_full_runtime_status.geojson');
        const cityDynamicResult = names.has('abu_dhabi_city_swmm_full_summary.json');
        const citySpatialResult = names.has('abu_dhabi_city_swmm_full_node_results.fgb')
          && names.has('abu_dhabi_city_swmm_full_link_results.fgb');
        setCityCompileReady(cityCompiled);
        setCityRuntimeReady(cityRuntime);
        setCityDynamicResultReady(cityDynamicResult);
        setCitySpatialResultReady(citySpatialResult);
        setCustomerMapReady(ready);
        setSwmmResultReady(resultReady);
        setCustomerMapChecked(true);
        if (cityRuntime) {
          fetch('/api/user/files/abu_dhabi_city_swmm_partition_runtime_status.geojson', { credentials: 'include', headers: getLocaleHeaders() })
            .then(response => response.ok ? response.json() : null)
            .then(payload => {
              if (cancelled || !payload?.features) return;
              const counts = payload.features.reduce((acc: Record<string, number>, feature: any) => {
                const status = String(feature.properties?.runtime_status || 'unknown');
                acc[status] = (acc[status] || 0) + 1;
                return acc;
              }, {});
              const completed = (counts.completed || 0) + (counts.completed_quality_warning || 0);
              const failed = counts.failed || 0;
        setRuntimeCountLabel(`${payload.features.length} 个全市作业状态标记 · ${completed} 已完成 · ${failed} 运行失败`);
              const failureClasses = payload.features
                .filter((feature: any) => feature.properties?.runtime_status === 'failed')
                .reduce((acc: Record<string, number>, feature: any) => {
                  const label = String(feature.properties?.failure_class || '运行失败');
                  acc[label] = (acc[label] || 0) + 1;
                  return acc;
                }, {});
              setRuntimeFailureLabel(Object.entries(failureClasses).map(([label, count]) => `${label} ${count}`).join(' · ') || '无失败分区');
            })
            .catch(() => {});
        }
        // Map publication is handled by the effect keyed by readiness and 2D
        // diagnostics. Do not force the legacy SWMM stage here: it can finish
        // after the public citywide surface bootstrap and overwrite the
        // default full-city flood-depth layer and timeline.
      })
      .catch(() => { if (!cancelled) { setCustomerMapChecked(true); setSwmmResultReady(false); setCityRuntimeReady(false); setCityDynamicResultReady(false); setCitySpatialResultReady(false); } });
    return () => { cancelled = true; };
  }, []);

  const historicalReplayVisible = Boolean(historicalReplayValidation && selectedKey === 'validation');
  const publicCitywide2dVisible = Boolean(
    publicCitywide2dDiagnostic && (selectedKey === 'surface' || (selectedKey === 'validation' && !historicalReplayVisible)),
  );
  const gwmVisible = Boolean(gwmMapPayload && selectedKey === 'gwm');
  const gwmIsTrained = Boolean(gwmRun?.metadata?.model_mode === 'trained_event_rollout');
  const gwmExternalHoldout = Boolean(gwmRun?.metadata?.event?.external_holdout);
  const publicLandWaterMask = publicCitywide2dDiagnostic?.metadata?.land_water_mask;
  const surfaceModelConfiguration = publicCitywide2dDiagnostic?.metadata?.model_configuration || {};
  const surfaceForcing = publicCitywide2dDiagnostic?.metadata?.forcing || {};
  const surfaceCouplingSummary = publicCitywide2dDiagnostic?.metadata?.coupling_summary || {};
  const surfaceResultVariant = String(publicCitywide2dDiagnostic?.metadata?.result_variant || 'return_period_one_way');
  const surfaceIsBidirectionalValidation = surfaceResultVariant === 'bidirectional_validation';
  const scenarioNativeNodeCount = Number(scenarioMapPayload?.metadata?.total_node_result_count || scenarioMapPayload?.metadata?.timeline?.total_node_count || 0);
  const scenarioMissingGeometryCount = Number(scenarioMapPayload?.metadata?.missing_geometry_count || 0);
  const scenarioMappedNodeCount = Number(scenarioMapPayload?.metadata?.node_feature_count || Math.max(0, scenarioNativeNodeCount - scenarioMissingGeometryCount));
  const scenarioGeometryCoveragePercent = scenarioNativeNodeCount > 0 ? (scenarioMappedNodeCount / scenarioNativeNodeCount) * 100 : 0;
  const mapWarning = historicalReplayVisible
    ? localizeAbuPair(
      `2024 历史事件重演已接入：客户 5 m DTM 输入 + 客户开发包重构降雨时序，采用 250 m 计算网格，共 ${Number(historicalReplayValidation?.metadata?.timeline?.total_cell_count || 0).toLocaleString()} 个二维陆域单元、${Number(historicalReplayValidation?.metadata?.timeline?.period_count || 0)} 个时间片；SWMM 严格质量门、独立二维复核和工程准入均未完成。`,
      `The 2024 historical replay is integrated using the customer 5 m DTM input, reconstructed rainfall timing from the customer development package, and a 250 m computational grid: ${Number(historicalReplayValidation?.metadata?.timeline?.total_cell_count || 0).toLocaleString()} 2D land cells and ${Number(historicalReplayValidation?.metadata?.timeline?.period_count || 0)} time slices. The SWMM strict quality gate, independent 2D review, and engineering admission remain incomplete.`,
    )
    : gwmVisible && gwmIsTrained
    ? localizeAbuPair(
      `历史事件 GWM R1 已接入：冻结研究代理对场次 ${String(gwmRun?.metadata?.event?.event_id || '')} 推理，${Number(gwmRun?.metadata?.model?.training_event_count || 0).toLocaleString()} 场训练事件，输出 ${Number(gwmRun?.metrics?.affected_cell_count || 0).toLocaleString()} 个受影响 250 m 网格和 ${Number(gwmRun?.metadata?.timeline?.period_count || 0)} 个 5 分钟时间片。模型学习 SWMM–ANUGA 标签，不是直接观测训练。${gwmExternalHoldout ? ' 当前为 2024 外部留出事件，仅允许冻结推理和报告。' : ''}`,
      `Historical-event GWM R1 is integrated. The frozen research emulator infers event ${String(gwmRun?.metadata?.event?.event_id || '')} from ${Number(gwmRun?.metadata?.model?.training_event_count || 0).toLocaleString()} training events and outputs ${Number(gwmRun?.metrics?.affected_cell_count || 0).toLocaleString()} affected 250 m cells over ${Number(gwmRun?.metadata?.timeline?.period_count || 0)} five-minute time slices. It learns SWMM–ANUGA labels, not observations directly.${gwmExternalHoldout ? ' This is the 2024 external holdout and is limited to frozen inference and reporting.' : ''}`,
    )
    : gwmVisible
    ? localizeAbuText(`规则型 GWM ${Number(gwmRun?.metadata?.return_period_years || gwmReturnPeriodYears)} 年一遇情景筛选已接入：基于阶段 3 二维结果生成基线、干预和差值图层，${Number(gwmRun?.metrics?.source_feature_count || 0).toLocaleString()} 个二维单元、${Number(gwmRun?.metadata?.timeline?.period_count || 0)} 个时间片。`)
    : publicCitywide2dVisible
    ? localizeAbuPair(
      surfaceIsBidirectionalValidation
        ? `客户 5 m DTM 的 100 年一遇 SWMM–ANUGA 同步双向数值验证成果已接入：${Number(surfaceCouplingSummary.window_count || 0)} 个同步窗口、${Number(surfaceCouplingSummary.interface_count || 0).toLocaleString()} 个交换接口，且回执记录非零 ANUGA→SWMM 回流。这是同步交换验证成果，未校准、未工程准入；每窗口原生 SWMM 重新调用仍需运行日志证明。`
        : `${customerDtmSurfaceActive ? '客户 5 m DTM 输入' : 'Copernicus DEM GLO-30 公共 DEM'}的全市二维结果已接入：250 m 计算网格、${Number(publicCitywide2dDiagnostic?.metadata?.timeline?.period_count || 0)} 个时间片；ESA WorldCover 2021 陆海掩膜已应用，${Number(publicLandWaterMask?.excluded_permanent_water_cells || 0).toLocaleString()} 个永久水体或土地覆盖源外单元已排除。结果未校准、未工程准入。`,
      surfaceIsBidirectionalValidation
        ? `The customer-DTM 100-year SWMM–ANUGA synchronous two-way numerical-validation result is integrated with ${Number(surfaceCouplingSummary.window_count || 0)} synchronized windows and ${Number(surfaceCouplingSummary.interface_count || 0).toLocaleString()} exchange interfaces; the receipt records non-zero ANUGA-to-SWMM return flow. It is not calibrated or engineering-admitted, and native SWMM re-invocation in every window still requires runtime-log evidence.`
        : `${customerDtmSurfaceActive ? 'The citywide 2D result using the customer 5 m DTM as input' : 'The citywide public 2D result using Copernicus DEM GLO-30'} is integrated on a 250 m computational grid with ${Number(publicCitywide2dDiagnostic?.metadata?.timeline?.period_count || 0)} time slices. The ESA WorldCover 2021 mask excludes ${Number(publicLandWaterMask?.excluded_permanent_water_cells || 0).toLocaleString()} permanent-water or out-of-coverage cells. The result is uncalibrated and not engineering-admitted.`,
    )
    : scenarioMapPayload
    ? localizeAbuPair(
      `EPA SWMM 原生 OUT 共包含 ${scenarioNativeNodeCount.toLocaleString()} 个结果节点；当前地图可定位 ${scenarioMappedNodeCount.toLocaleString()} 个（${scenarioGeometryCoveragePercent.toFixed(1)}%），${scenarioMissingGeometryCount.toLocaleString()} 个因几何缺失暂不可视化。已映射节点包含零值节点，且未按数值阈值或数量截断。该作业严格数值质量门未通过，仅用于诊断。`,
      `The native EPA SWMM OUT contains ${scenarioNativeNodeCount.toLocaleString()} result nodes. The map can locate ${scenarioMappedNodeCount.toLocaleString()} (${scenarioGeometryCoveragePercent.toFixed(1)}%); ${scenarioMissingGeometryCount.toLocaleString()} nodes cannot currently be visualized because geometry is missing. Mapped nodes include zero values and are not filtered by value threshold or count. The strict numerical quality gate failed, so this run is diagnostic only.`,
    )
    : !customerMapChecked ? localizeAbuText('正在检查本地私有客户图层和 SWMM 全市结果…')
    : citySpatialResultReady ? localizeAbuText('已接入客户真实节点/管线几何上的全市连续网络 SWMM 最大值：节点最大水深、节点溢流/积水、管段流量、流速和容量率。当前强迫为 Open-Meteo 公开代理降雨，结果未校准、未工程准入。')
    : cityRuntimeReady ? `${localizeAbuText('已接入全市连续网络运行状态')}：${localizeAbuText(runtimeCountLabel)}。${localizeAbuText('失败分类')}：${localizeAbuText(runtimeFailureLabel)}。`
    : cityCompileReady ? localizeAbuText('全市连续网络 SWMM 输入已编译：保留跨内部计算组织的可用管段；尚未形成完整动态水动力结果。')
    : customerMapReady && swmmResultReady ? localizeAbuText('已接入公开代理 SWMM 诊断结果：Open-Meteo 72 小时、EPA SWMM 5.2.4；仅用于原型闭环，未校准、未工程准入。')
    : customerMapReady ? localizeAbuText('客户图层：全量管网已通过矢量瓦片接入地图；SWMM 结果尚未接入。')
    : localizeAbuText('未检测到本地私有客户图层，地图保持空白；请先生成受控 GDB 派生预览。');

  const mapResultBoundaryNote = gwmVisible
    ? gwmIsTrained
      ? gwmExternalHoldout
        ? localizeAbuPair(
          '当前地图来自冻结的历史事件 GWM R1 对 2024 外部留出事件的推理：最大深度和动态水深均可播放；该事件仅用于外部检验，禁止参与训练、调参、阈值或版本选择。Sentinel-2 是云筛选后的积水观测证据，不是实测水深。',
          'The map shows frozen historical-event GWM R1 inference for the 2024 external holdout. Maximum and dynamic depth are playable; the event is restricted to external testing and cannot be used for training, tuning, threshold selection, or version selection. Sentinel-2 is cloud-screened inundation evidence, not measured water depth.',
        )
        : localizeAbuPair(
          '当前地图来自冻结的历史事件 GWM R1 对已准入降雨强迫的推理：最大深度和动态水深均可播放。它模拟 250 m SWMM–ANUGA 物理标签，不替代物理模型，也未完成确认性外部验证或工程准入。',
          'The map shows frozen historical-event GWM R1 inference for registered rainfall forcing. Maximum and dynamic depth are playable. It emulates 250 m SWMM–ANUGA physics labels, does not replace the physical model, and has not completed confirmatory external validation or engineering admission.',
        )
      : localizeAbuPair(
        '当前地图来自规则型 GWM 情景筛选：基线、干预和差值均为二维地表单元结果，动态干预层可在时间轴播放；高风险情景必须回到 SWMM / ANUGA 复核。',
        'The map shows rule-based GWM scenario screening. Baseline, intervention, and delta are 2D surface-cell results, and the dynamic intervention layer is playable. High-risk scenarios must return to SWMM / ANUGA review.',
      )
    : publicCitywide2dVisible
    ? customerDtmSurfaceActive
      ? localizeAbuPair(
        surfaceIsBidirectionalValidation
          ? '当前地图主图层是客户 5 m DTM 的 SWMM–ANUGA 同步双向数值验证成果；回执包含正向与反向交换体积，但它仍是未校准、未工程准入的验证资产。'
          : '当前地图主图层以客户 5 m DTM 为地形输入，ANUGA 2D 实际采用 250 m 计算网格，并接受 SWMM 单向源项；当前没有动态水头回馈。ESA WorldCover 2021 陆海掩膜已应用。',
        surfaceIsBidirectionalValidation
          ? 'The primary layer is the customer-5 m-DTM SWMM–ANUGA synchronous two-way numerical-validation result. Its receipt contains forward and reverse exchange volumes, but it remains an uncalibrated validation asset without engineering admission.'
          : 'The primary map layer uses the customer 5 m DTM as terrain input. ANUGA 2D actually runs on a 250 m computational grid with one-way SWMM source terms and no dynamic head feedback. The ESA WorldCover 2021 land/water mask is applied.',
      )
      : localizeAbuPair(
        '当前地图主图层来自 Copernicus DEM GLO-30 驱动的 ANUGA 2D 全市公共原型，使用 250 m 计算网格；ESA WorldCover 2021 陆海掩膜已应用，结果未校准、未工程准入。',
        'The primary map layer is the citywide public ANUGA 2D prototype driven by Copernicus DEM GLO-30 on a 250 m grid. The ESA WorldCover 2021 land/water mask is applied; the result is uncalibrated and not engineering-admitted.',
      )
    : scenarioMapPayload
    ? localizeAbuPair(
      `当前地图来自 EPA SWMM 原生 OUT：${scenarioNativeNodeCount.toLocaleString()} 个结果节点中，${scenarioMappedNodeCount.toLocaleString()} 个已回挂可解析的客户节点几何，${scenarioMissingGeometryCount.toLocaleString()} 个缺少几何而暂不可视化。结果严格数值质量门未通过，未校准、未工程准入。`,
      `The map comes from native EPA SWMM OUT results. Of ${scenarioNativeNodeCount.toLocaleString()} result nodes, ${scenarioMappedNodeCount.toLocaleString()} are joined to resolvable customer geometry and ${scenarioMissingGeometryCount.toLocaleString()} cannot currently be visualized because geometry is missing. The strict numerical quality gate failed; the result is uncalibrated and not engineering-admitted.`,
    )
    : customerDtmDiagnostic
    ? localizeAbuPair(
      '当前地图主图层来自客户 dtm_5M.tif 驱动的 ANUGA 2D 局部结果，使用真实空间坐标和二维单元面；时间轴可播放动态积水深度。结果未校准、未工程准入。',
      'The primary map layer is a local ANUGA 2D result driven by customer dtm_5M.tif, using real spatial coordinates and 2D cells. Dynamic depth is playable; the result is uncalibrated and not engineering-admitted.',
    )
    : citySpatialResultReady
    ? localizeAbuPair(
      '当前为历史诊断空间资产；其几何覆盖和结果版本必须以接口元数据为准，内部计算资产不得解释为客户正式排水分区。',
      'This is a historical diagnostic spatial asset. Geometry coverage and result version must follow API metadata, and internal compute assets must not be interpreted as official customer drainage districts.',
    )
    : cityRuntimeReady
    ? localizeAbuPair(
      '地图中的运行状态标记表示作业状态，不是排水分区边界，也不代表发生积水的位置。',
      'Run-status markers show job state, not drainage-district boundaries or flooded locations.',
    )
    : cityCompileReady
    ? localizeAbuPair(
      '全市连续网络输入已编译；正式结果必须同时披露数值质量门、几何覆盖和校准状态。',
      'The citywide continuous-network input is compiled. Any formal result must disclose the numerical quality gate, geometry coverage, and calibration status.',
    )
    : localizeAbuPair(
      '当前为公开代理诊断结果；客户权威事件、边界和校准数据到达后，将替换同一结果契约。',
      'This is a public-proxy diagnostic result. Authoritative customer events, boundaries, and calibration data will replace it under the same result contract.',
    );

  return (
    <div className="abu-flood-tab">
      <section className="abu-flood-hero">
        <div>
          <span className="abu-flood-kicker">ABU DHABI / STORMWATER WORLD MODEL</span>
          <h2>{en('title', 'Abu Dhabi Stormwater Flood World Model')}</h2>
          <p>{en('subtitle', 'An end-to-end workspace from authoritative data and physical simulation to GWM rapid rollouts.')}</p>
          <div className="abu-flood-hero-meta">
            <span><Activity size={13} /> {en('hero.diagnosticReady', 'Diagnostic pipeline available')}</span>
            <span><LockKeyhole size={13} /> {en('hero.calibrationPending', 'Engineering calibration not admitted')}</span>
            <span><CloudRain size={13} /> {en('hero.eventPending', 'Apr 2024 historical replay connected')}</span>
          </div>
        </div>
        <div className="abu-flood-hero-side">
          <div className="abu-flood-readiness-ring" data-completed-stages={completedStageCount} data-total-stages={displayStages.length}><strong>{completedStageCount} / {displayStages.length}</strong><span>{en('hero.stagesAvailable', 'stage capabilities ready')}</span></div>
          <div className="abu-flood-hero-note">{en('hero.customerGdbVerified', 'Customer GDB integrated and spatially normalized; engineering semantics remain to be confirmed')}<br />{publicCitywide2dDiagnostic ? localizeAbuText(customerDtmSurfaceActive ? '客户 5 m DTM 输入、250 m 计算网格结果已接入' : 'Copernicus DEM 全市二维公共原型已接入') : customerDtmDiagnostic ? 'Customer dtm_5M local 2D diagnostic connected' : en('hero.eventCalibrationPending', 'Event and calibration data pending admission')}</div>
        </div>
      </section>

      <section className="abu-flood-terminology-correction" aria-label={en('terminology.aria', 'Model scope and fitness-for-use boundary')}>
        <ShieldCheck size={16} />
        <div>
          <strong>{en('terminology.title', 'Model scope and fitness-for-use boundary')}</strong>
          <p>{en('terminology.body', 'The current 1D result comes from a citywide continuous-network EPA SWMM 5.2.4 diagnostic run and is joined to resolvable customer network geometry. Engineering calibration is incomplete; rainfall variability, network attributes, pump operations, tidal boundaries, and inundation observations still require verification. Current results support technical validation and option screening, not engineering design or citywide prediction claims.')}</p>
        </div>
      </section>

      <section className="abu-flood-metrics" aria-label={en('metrics.aria', 'Current project snapshot')}>
        <div><Database size={15} /><span>{en('metrics.pipelines', 'Normalized customer pipes')}</span><strong>238,287</strong></div>
        <div><Network size={15} /><span>{en('metrics.nodes', 'Normalized customer nodes')}</span><strong>238,350</strong></div>
        <div><Gauge size={15} /><span>{en('metrics.network', 'Citywide continuous SWMM network')}</span><strong className="success">{en('metrics.oneRun', '1 run')}</strong></div>
        <div><Activity size={15} /><span>{en('metrics.crs', 'Spatial reference')}</span><strong>EPSG:32640</strong></div>
        <div><AlertTriangle size={15} /><span>{en('metrics.p0', 'Engineering semantics')}</span><strong className="warning">{localizeAbuPair('待确认', 'Pending')}</strong></div>
      </section>

      <section className="abu-flood-scenario-section" aria-label={en('scenario.aria', 'Urban rainfall flood scenario simulation')}>
        <div className="abu-flood-section-heading">
          <div><span className="abu-flood-overline">SCENARIO SIMULATION</span><h3>{en('scenario.title', 'Scenario inputs')}</h3></div>
          <span className="abu-flood-scenario-badge"><SlidersHorizontal size={13} />{en('scenario.badge', 'SWMM diagnostic')}</span>
        </div>
          <div className="abu-flood-scenario-disclaimer"><AlertTriangle size={14} /><span>{en('scenario.disclaimer', 'Run invokes EPA SWMM 5.2.4 on the continuous citywide network and stores native RPT / OUT. Design storms use the 2022 official Zone B DDF values for 2/5/10/25/50/100-year return periods at 180 minutes. The DDF does not publish a complete hyetograph; 5-minute alternating-block allocation and a 40% peak position are explicit modeling assumptions. Results are not calibrated or engineering-admitted.')}</span></div>
        <div className="abu-flood-scenario-grid">
          <div className="abu-flood-scenario-form">
          <div className="abu-flood-form-group">
              <div className="abu-flood-form-group-title">{isOnlinePublicRainfall || isPublicStationEvent ? <Globe2 size={14} /> : <CloudRain size={14} />}<strong>{localizeAbuText('模型输入降雨数据')}</strong><small>{localizeAbuText('三类来源互斥，运行回执记录真实来源')}</small></div>
              <div className="abu-flood-form-grid">
            <label>{localizeAbuText('模拟范围')}<select value={scenario.scope} onChange={event => updateScenario('scope', event.target.value as FloodScenarioForm['scope'])}><option value="citywide">{localizeAbuText('全市连续网络（单个 SWMM 作业）')}</option><option value="partition">{localizeAbuText('内部调试分块（不作为全市结果）')}</option></select></label>
                <label>{localizeAbuText('目标计算分块')}<select value={scenario.partition} disabled={scenario.scope !== 'partition'} onChange={event => updateScenario('partition', event.target.value)}><option value="all">{localizeAbuText('全部计算分块')}</option>{Array.from({ length: 30 }, (_, index) => <option key={index} value={String(index)}>{localizeAbuText('SWMM 计算分块')} {String(index + 1).padStart(2, '0')}</option>)}</select></label>
                <label>{localizeAbuText('降雨来源')}<select value={scenario.rainfallMode} onChange={event => updateRainfallMode(event.target.value as RainfallMode)}><option value="design_storm">{localizeAbuText('参数化设计暴雨')}</option><option value="online_public">{localizeAbuText('在线公开来源降雨数据（Open-Meteo）')}</option><option value="public_station_event">{localizeAbuText('公开站点约束雨型（NOAA NCEI）')}</option><option value="historical_event">{localizeAbuText('客户权威历史降雨时序')}</option></select></label>
                <label>{localizeAbuText('模型开始时间（UTC）')}<input type="datetime-local" step="300" value={scenario.startTime} onChange={event => updateScenario('startTime', event.target.value)} /></label>
                <label>{localizeAbuText('降雨时长（分钟）')}<input type="number" min="5" max="4320" step="5" value={scenario.durationMinutes} disabled={scenario.rainfallMode === 'historical_event' || isOfficialZoneBStorm || isPublicStationEvent} onChange={event => updateScenario('durationMinutes', Number(event.target.value))} /></label>
                <label>{localizeAbuText('总降雨量（mm）')}<input type="number" min="0.1" max="1000" step="0.01" value={scenario.totalDepthMm} disabled={!isDesignStorm || isOfficialZoneBStorm} onChange={event => updateScenario('totalDepthMm', Number(event.target.value))} /></label>
                <label>{localizeAbuText('时间雨型')}<select value={scenario.rainfallPattern} disabled={!isDesignStorm} onChange={event => updateRainfallPattern(event.target.value as RainfallPattern)}>{Object.entries(rainfallPatternLabels).map(([key, label]) => <option key={key} value={key}>{localizeAbuText(label)}</option>)}</select></label>
                <label>{localizeAbuText('设计重现期')}<select value={scenario.returnPeriodYears} disabled={!isOfficialZoneBStorm} onChange={event => updateReturnPeriod(Number(event.target.value) as ReturnPeriodYears)}>{([2, 5, 10, 25, 50, 100] as ReturnPeriodYears[]).map(value => <option key={value} value={value}>{value}{localizeAbuText('年一遇')} · {zoneB180DepthByReturnPeriod[value].toFixed(2)} mm</option>)}</select></label>
                <label>{localizeAbuText('峰值位置（%）')}<input type="number" min="5" max="95" step="5" value={scenario.peakPosition} disabled={!isDesignStorm || scenario.rainfallPattern === 'uniform'} onChange={event => updateScenario('peakPosition', Number(event.target.value))} /></label>
                <label>{localizeAbuText('空间分布')}<select value={scenario.spatialPattern} onChange={event => updateScenario('spatialPattern', event.target.value as FloodScenarioForm['spatialPattern'])}><option value="uniform">{localizeAbuText('全市均匀')}</option><option value="zonal">{localizeAbuText('分区降雨系数（后端接入）')}</option></select></label>
                <label>{localizeAbuText('雨后计算（分钟）')}<input type="number" min="0" max="1440" step="5" value={scenario.tailMinutes} onChange={event => updateScenario('tailMinutes', Number(event.target.value))} /></label>
              </div>
              {isOnlinePublicRainfall && <div className="abu-flood-form-grid abu-flood-public-source-grid"><label>{localizeAbuText('公开来源纬度')}<input type="number" min="-90" max="90" step="0.0001" value={scenario.publicLatitude} onChange={event => updateScenario('publicLatitude', Number(event.target.value))} /></label><label>{localizeAbuText('公开来源经度')}<input type="number" min="-180" max="180" step="0.0001" value={scenario.publicLongitude} onChange={event => updateScenario('publicLongitude', Number(event.target.value))} /></label></div>}
              {isPublicStationEvent && <div className="abu-flood-form-grid abu-flood-public-source-grid"><label>{localizeAbuText('公开站点')}<select value={scenario.publicStation} onChange={event => updateScenario('publicStation', event.target.value as FloodScenarioForm['publicStation'])}><option value="OMAD">OMAD · Bateen Executive</option><option value="OMAA">OMAA · Abu Dhabi International</option></select></label><label>{localizeAbuText('事件窗口')}<input type="text" value="2024-04-15 00:00 – 2024-04-18 00:00 UTC" readOnly /></label></div>}
              {isOnlinePublicRainfall && <div className="abu-flood-form-hint"><Globe2 size={13} />{localizeAbuText('运行时从 Open-Meteo Archive API 拉取该坐标的小时降雨；公开数据仅作原型代理，不等同于客户实测。')}</div>}
              {isPublicStationEvent && <div className="abu-flood-form-hint"><Globe2 size={13} />{localizeAbuText('使用 NOAA NCEI 阿布扎比站点 2024-04 公开累计观测约束的本地代理时序；原始观测为 12 小时累计，不是逐小时实测，结果仅用于原型敏感性验证，不等同客户权威历史降雨。')}</div>}
              {isOfficialZoneBStorm && <div className="abu-flood-form-hint"><CloudRain size={13} />{localizeAbuText('官方输入：Zone B、')}{scenario.returnPeriodYears}{localizeAbuText('年一遇、180 分钟、')}{scenario.totalDepthMm.toFixed(2)} mm；{localizeAbuText('5 分钟时程由 DDF 嵌套雨量插值后采用交替块法生成，峰值位置为可调整假设')}</div>}
              {isOfficialZoneBStorm && designStormBatch && <div className="abu-flood-form-hint"><FileCheck2 size={13} />{localizeAbuText('已准备 2/5/10/25/50/100 年一遇共 6 套全市预计算结果；严格质量门均未通过，仅用于原型诊断展示。')}</div>}
              {isOfficialZoneBStorm && designStormBatchError && <div className="abu-flood-form-error"><AlertTriangle size={13} />{localizeAbuText(designStormBatchError)}</div>}
              {scenario.rainfallMode === 'historical_event' && <div className="abu-flood-form-hint"><TimerReset size={13} />{localizeAbuText('客户权威历史时序入口已保留，但当前私有数据尚未接入，运行会被拦截；后续通过客户 CSV / NetCDF 和事件元数据验收后绑定。')}</div>}
            </div>

            <div className="abu-flood-form-group">
              <div className="abu-flood-form-group-title"><Network size={14} /><strong>{localizeAbuText('排水情景动作')}</strong><small>{localizeAbuText('调整基线的受控动作，不修改客户原始 GDB')}</small></div>
              <div className="abu-flood-form-grid">
                <label>{localizeAbuText('管线作用范围')}<select value={scenario.pipeScope} onChange={event => updateScenario('pipeScope', event.target.value as FloodScenarioForm['pipeScope'])}><option value="none">{localizeAbuText('无管线调整（基线）')}</option><option value="priority_corridor">{localizeAbuText('重点管廊')}</option><option value="selected_zone">{localizeAbuText('选定区域')}</option></select></label>
                <label>{localizeAbuText('堵塞率（%）')}<input type="number" min="0" max="90" step="5" value={scenario.blockagePercent} disabled={scenario.pipeScope === 'none'} onChange={event => updateScenario('blockagePercent', Number(event.target.value))} /></label>
                <label>{localizeAbuText('管线能力倍率')}<input type="number" min="0.1" max="1.5" step="0.05" value={scenario.pipeCapacityMultiplier} disabled={scenario.pipeScope === 'none'} onChange={event => updateScenario('pipeCapacityMultiplier', Number(event.target.value))} /></label>
                <label>{localizeAbuText('出水边界')}<select value={scenario.outfallMode} onChange={event => updateScenario('outfallMode', event.target.value as FloodScenarioForm['outfallMode'])}><option value="open">{localizeAbuText('自由出水（诊断）')}</option><option value="fixed_level">{localizeAbuText('固定水位边界')}</option></select></label>
                <label>{localizeAbuText('边界水位（m）')}<input type="number" min="0" step="0.01" value={scenario.outfallLevelM} disabled={scenario.outfallMode !== 'fixed_level'} onChange={event => updateScenario('outfallLevelM', Number(event.target.value))} /></label>
              </div>
              <div className="abu-flood-control-row">
                <label className="abu-flood-toggle"><input type="checkbox" checked={scenario.pumpEnabled} onChange={event => updateScenario('pumpEnabled', event.target.checked)} /><span>{localizeAbuText('泵站启用')}</span></label>
                <label className="abu-flood-range-label">{localizeAbuText('泵站能力倍率')} <input type="range" min="0" max="1.5" step="0.05" value={scenario.pumpCapacityMultiplier} disabled={!scenario.pumpEnabled} onChange={event => updateScenario('pumpCapacityMultiplier', Number(event.target.value))} /><strong>{scenario.pumpCapacityMultiplier.toFixed(2)}x</strong></label>
              </div>
            </div>

            <div className="abu-flood-form-group compact">
              <div className="abu-flood-form-group-title"><Clock3 size={14} /><strong>{localizeAbuText('运行设置')}</strong><small>{localizeAbuText('当前原型固定 5 分钟路由步长')}</small></div>
              <div className="abu-flood-form-grid">
                <label>{localizeAbuText('输出间隔（分钟）')}<select value={scenario.outputIntervalMinutes} onChange={event => updateScenario('outputIntervalMinutes', Number(event.target.value))}><option value="5">5</option><option value="15">15</option><option value="30">30</option></select></label>
                <label>{localizeAbuText('运行引擎')}<select value="epa_swmm" disabled><option value="epa_swmm">{localizeAbuText('EPA SWMM 5.2.4（当前）')}</option><option value="coupled">{localizeAbuText('SWMM + 二维（待准入）')}</option><option value="gwm">{localizeAbuText('GWM R1（独立入口已接入）')}</option></select></label>
              </div>
            </div>

            {scenarioError && <div className="abu-flood-form-error"><AlertTriangle size={14} />{localizeAbuText(scenarioError)}</div>}
            <div className="abu-flood-scenario-actions">
              <button className="abu-flood-map-action" type="button" onClick={runScenarioPreview} disabled={controlsBusy}><Play size={15} />{scenarioBusy ? en('scenario.running', 'Running SWMM Simulation...') : en('scenario.run', 'Run SWMM Simulation')}</button>
              {isOfficialZoneBStorm && <button className="abu-flood-reset-action abu-flood-precomputed-action" type="button" onClick={loadPrecomputedDesignStorm} disabled={controlsBusy || designStormBatchLoading}>{precomputedLoadStage || designStormBatchLoading ? <LoaderCircle className="abu-flood-loading-icon" size={14} /> : <FileCheck2 size={14} />}{precomputedLoadStage === 'job' ? localizeAbuText('正在读取预计算作业…') : precomputedLoadStage === 'timeline' ? localizeAbuText('正在准备原生 OUT 时间轴…') : precomputedLoadStage === 'map' ? localizeAbuText('正在加载全量节点到地图…') : designStormBatchLoading ? localizeAbuText('正在读取预计算结果目录…') : getLocale() === 'zh-CN' ? `${designStormBatchError ? '重试并加载' : '加载'} ${scenario.returnPeriodYears} 年一遇预计算结果` : `${designStormBatchError ? 'Retry and load' : 'Load'} ${scenario.returnPeriodYears}-year return-period precomputed result`}</button>}
              <button className="abu-flood-reset-action" type="button" onClick={resetScenario} disabled={controlsBusy}><RotateCcw size={14} />{localizeAbuText('恢复默认')}</button>
            </div>
          </div>

          <aside className="abu-flood-scenario-result">
            <div className="abu-flood-result-heading"><Gauge size={14} /><strong>{localizeAbuText('SWMM 作业与诊断结果')}</strong><span className={`abu-flood-pill ${scenarioRun ? 'abu-flood-status-partial' : 'abu-flood-status-blocked'}`}>{scenarioRun ? localizeAbuText(({ queued: '排队中', running: '运行中', completed: '已完成', completed_with_warnings: '完成但有告警', failed: '失败' } as Record<string, string>)[scenarioRun.status] || scenarioRun.status) : localizeAbuText('尚未运行')}</span></div>
            {scenarioRun ? <>
              <details className="abu-flood-quality-details abu-flood-run-technical-details">
                <summary>{localizeAbuText('技术详情与作业标识')}</summary>
                <div className="abu-flood-scenario-run-id"><span>{localizeAbuText(scenarioRun.restoredFromLatestCompleted ? '最近成功作业 Run ID' : '当前作业 Run ID')}</span><code>{scenarioRun.runId}</code></div>
                <small>{localizeAbuPair(`开始：${scenarioRun.startedAt || '—'}${scenarioRun.finishedAt ? ` · 完成：${scenarioRun.finishedAt}` : ''}`, `Started: ${scenarioRun.startedAt || '—'}${scenarioRun.finishedAt ? ` · finished: ${scenarioRun.finishedAt}` : ''}`)}</small>
              </details>
              <div className="abu-flood-scenario-result-metrics"><div><span>{localizeAbuText('全市作业进度')}</span><strong>{scenarioRun.completedPartitions || 0}/{scenarioRun.totalPartitions || 1}</strong><small>{scenarioRun.failedPartitions || 0} {localizeAbuText('个失败')}</small></div><div><span>{localizeAbuText('本次降雨总量')}</span><strong>{scenarioRun.generatedTotalDepthMm.toFixed(1)}</strong><small>mm · {localizeAbuText('模型输入时间窗')}</small></div><div><span>{localizeAbuText('节点积水作业')}</span><strong>{scenarioRun.summary?.node_flooding_partition_count ?? '—'}</strong><small>{localizeAbuText('真实 SWMM 报告')}</small></div></div>
              {scenarioRun.rainfallMode === 'design_storm' && <div className="abu-flood-hyetograph"><div><span>{localizeAbuText('生成雨型预览')}</span><small>{isOfficialZoneBStorm ? localizeAbuText(`官方 DDF 总量 + 假设时间分配 · ${scenario.returnPeriodYears} 年一遇`) : localizeAbuText('参数化设计暴雨，不是实测雨量曲线')}</small></div><div className="abu-flood-hyetograph-bars" aria-label={localizeAbuText('生成雨型预览')}>{rainfallProfile.map((height, index) => <span key={index} style={{ height: `${Math.max(10, height * 100)}%` }} />)}</div><div className="abu-flood-hyetograph-axis"><span>{localizeAbuText('开始')}</span><span>{localizeAbuText('峰值位置')} {scenario.peakPosition}%</span><span>{localizeAbuText('结束')}</span></div></div>}
              <div className="abu-flood-scenario-action-summary"><CloudRain size={13} /><span>{localizeAbuText('本次模型输入降雨数据')}：{localizeAbuText(scenarioRun.rainfallSource || '来源读取中')}{scenarioRun.rainfallMode === 'online_public' ? `；${localizeAbuText('小时公开数据已按模型 5 分钟步长展开，仅用于原型代理。')}` : '。'}</span></div>
              {scenarioRun.rainfallMode === 'public_station_event' && <div className="abu-flood-scenario-action-summary"><Globe2 size={13} /><span>{localizeAbuText('站点累计约束')}：{scenarioRun.rainfallStats?.station || '—'} · {scenarioRun.rainfallStats?.station_label || '—'} · {Number(scenarioRun.rainfallStats?.anchor_total_depth_mm || 0).toFixed(1)} mm；{localizeAbuText('12 小时累计约束')} · {localizeAbuText('仅用于原型敏感性验证')}</span></div>}
              <div className="abu-flood-scenario-action-summary"><SlidersHorizontal size={13} /><span>{localizeAbuText(scenarioRun.actionSummary)}</span></div>
              <div className="abu-flood-scenario-timeline">{scenarioRunStages.map(([index, title, summary], stageIndex) => { const complete = stageIndex === 0 || (stageIndex === 1 && (scenarioRun.completedPartitions || 0) > 0) || (stageIndex === 2 && ['completed', 'completed_with_warnings'].includes(scenarioRun.status)) || (stageIndex === 3 && Boolean(scenarioMapPayload)); return <div className={`abu-flood-scenario-timeline-item ${complete ? 'complete' : 'pending'}`} key={index}><span>{index}</span><div><strong>{localizeAbuText(title)}</strong><small>{complete ? (stageIndex === 1 ? `${scenarioRun.completedPartitions || 0} ${localizeAbuText('个全市作业已执行')}` : localizeAbuText('已完成')) : localizeAbuText(summary)}</small></div><span className="timeline-state">{complete ? localizeAbuText('完成') : localizeAbuText('运行中/待接入')}</span></div>; })}</div>
              {scenarioRun.actualSummary && <div className="abu-flood-scenario-result-metrics"><div><span>{localizeAbuText('外排量')}</span><strong>{scenarioRun.actualSummary.external_outflow_million_litres == null ? '—' : Number(scenarioRun.actualSummary.external_outflow_million_litres).toFixed(2)}</strong><small>{localizeAbuText('百万升 · 全市连续网络')}</small></div><div><span>{localizeAbuText('路由连续性误差')}</span><strong>{scenarioRun.actualSummary.routing_continuity_error_percent == null ? '—' : `${Number(scenarioRun.actualSummary.routing_continuity_error_percent).toFixed(2)}%`}</strong><small>{localizeAbuText('绝对值越接近 0 越好')}</small></div><div><span>{localizeAbuText('严格质量门')}</span><strong>{localizeAbuText(scenarioRun.actualSummary.strict_numerical_quality_passed ? '通过' : '未通过')}</strong><small>{localizeAbuText('不代表工程准入')}</small></div></div>}
              {scenarioRun.partitions && scenarioRun.partitions.length > 0 && <div className="abu-flood-scenario-action-summary"><Activity size={13} /><span>{scenarioRun.partitions.filter(row => ['completed', 'completed_quality_warning'].includes(row.status)).length} {localizeAbuText('个全市连续网络作业已完成')}；{scenarioRun.partitions.filter(row => row.status === 'failed').length} {localizeAbuText('个作业失败，失败原因保留在运行回执。')}</span></div>}
              {scenarioRun.partitions && scenarioRun.partitions.length > 0 && <div className="abu-flood-scenario-partition-list"><div className="abu-flood-scenario-partition-header"><span>{localizeAbuText('作业范围')}</span><span>{localizeAbuText('状态')}</span><span>{localizeAbuText('外排量（百万升）')}</span><span>{localizeAbuText('洪涝损失（百万升）')}</span><span>{localizeAbuText('节点积水')}</span></div>{scenarioRun.partitions.slice(0, 8).map(row => <div className="abu-flood-scenario-partition-row" key={String(row.partition_id)}><strong>{row.partition_id === 'full_city' ? localizeAbuText('全市') : String(Number(row.partition_id) + 1).padStart(2, '0')}</strong><span>{row.status === 'completed_quality_warning' ? localizeAbuText('完成·质量告警') : row.status === 'completed' ? localizeAbuText('完成') : row.status === 'failed' ? `${localizeAbuText('失败')} · ${localizeAbuText(row.failure_reason || '未知')}` : localizeAbuText('运行中')}</span><span>{row.result_summary?.external_outflow_million_litres == null ? '—' : Number(row.result_summary.external_outflow_million_litres).toFixed(2)}</span><span>{row.result_summary?.flooding_loss_million_litres == null ? '—' : Number(row.result_summary.flooding_loss_million_litres).toFixed(2)}</span><span>{row.result_summary?.node_flooding_detected == null ? '—' : localizeAbuText(row.result_summary.node_flooding_detected ? '是' : '否')}</span></div>)}</div>}
              <div className="abu-flood-scenario-claim"><LockKeyhole size={13} />{localizeAbuText(scenarioRun.claimBoundary)}</div>
            </> : <div className="abu-flood-scenario-empty"><CloudRain size={24} /><strong>{localizeAbuText('设置降雨和排水情景')}</strong><span>{localizeAbuText('运行后这里会显示生成的雨型摘要、动作叠加和 SWMM 动态作业状态。')}</span></div>}
          </aside>
        </div>
      </section>

      <section className="abu-flood-map-section">
        <div className="abu-flood-map-copy">
          <div className="abu-flood-section-heading compact">
            <div><span className="abu-flood-overline">CUSTOMER GIS EVIDENCE</span><h3>{localizeAbuText('客户输入、积水热点与模型结果')}</h3></div>
            <MapIcon size={17} />
          </div>
          <p>{localizeAbuText('客户积水热点是独立的静态参考图层；原始管网资产是 SWMM 的空间输入，节点和管段结果是模型计算输出并回挂到客户真实几何。')}</p>
          <div className="abu-flood-map-warning"><AlertTriangle size={14} /><span>{mapWarning}</span></div>
          {customerHotspots && <div className="abu-flood-map-warning"><MapIcon size={14} /><span>{localizeAbuText(`已加载客户静态积水热点 ${Number(customerHotspots.metadata?.feature_count || 506).toLocaleString()} 个；该图层表示客户已知易涝点，不代表当前事件积水、发生时间或实测水深。`)}</span></div>}
          {customerHotspotsChecked && !customerHotspots && <div className="abu-flood-map-warning"><AlertTriangle size={14} /><span>{localizeAbuText(`客户积水热点图层未加载：${customerHotspotsError || '完整性校验未通过'}`)}</span></div>}
          {publicCitywide2dVisible && publicLandWaterMask && <div className="abu-flood-map-warning"><Waves size={14} /><span>{localizeAbuText(`陆海掩膜已应用：${publicLandWaterMask.product || 'ESA WorldCover 2021'}；永久水体占比阈值 ${Number(publicLandWaterMask.water_cell_fraction_threshold || 0.5).toFixed(2)}；降雨仅施加到陆域单元，永久水体和土地覆盖源外单元不进入城市积水图层。`)}</span></div>}
          <button className="abu-flood-map-action" disabled={!customerMapReady && !cityRuntimeReady && !cityCompileReady && !swmmResultReady && !citySpatialResultReady && !scenarioMapPayload && !gwmMapPayload && !publicCitywide2dVisible && !historicalReplayVisible} onClick={() => sendStageToMap()}><MapIcon size={15} />{localizeAbuText(mapSent ? '重新发送当前阶段图层到地图' : '在地图上展示当前阶段')}</button>
        </div>
        <div className="abu-flood-map-layers" aria-label={localizeAbuText('当前地图图层和结果状态')}>
          <div className="abu-flood-map-layer-heading"><Database size={13} /><strong>{localizeAbuText('地图当前显示 · 原始输入')}</strong></div>
          {customerHotspots
            ? <div data-map-layer-id="abu-dhabi-customer-hotspots-506"><span className="abu-flood-map-swatch hotspots" /><span>{localizeAbuText(customerHotspotMapLayerBase.name)}</span><em>{localizeAbuText('静态参考 · 非事件观测')}</em></div>
            : <div className="abu-flood-map-empty"><span className="abu-flood-map-swatch hotspots" /><span>{localizeAbuText(customerHotspotsChecked ? '客户积水热点图层不可用' : '正在校验客户积水热点图层…')}</span></div>}
          {customerMapReady && !publicCitywide2dVisible && (stageLayerKeys[selectedKey] || stageLayerKeys.data).length > 0 && !((stageResultLayerKeys[selectedKey] || []).length > 0 && (citySpatialResultReady || cityRuntimeReady || cityCompileReady || swmmResultReady))
            ? (stageLayerKeys[selectedKey] || stageLayerKeys.data).map(key => <div key={key}><span className={`abu-flood-map-swatch ${key}`} /><span>{localizeAbuText(customerMapLayers[key].name)}</span></div>)
            : <div className="abu-flood-map-empty"><span className="abu-flood-map-swatch extent" /><span>{customerMapReady && (stageResultLayerKeys[selectedKey] || []).length > 0 && (citySpatialResultReady || cityRuntimeReady || cityCompileReady || swmmResultReady) ? localizeAbuText('结果阶段已隐藏原始管网，避免遮挡结果；切换到数据阶段可查看原始输入。') : customerMapReady ? localizeAbuText('当前阶段暂无可展示的结果空间图层') : localizeAbuText('暂无已接入的客户真实图层')}</span></div>}
          <div className="abu-flood-map-result-heading"><Waves size={13} /><strong>{localizeAbuText(historicalReplayVisible ? '历史重演验证结果 · 当前状态' : gwmVisible ? (gwmIsTrained ? '历史事件 GWM R1 结果图层 · 当前状态' : '规则型 GWM 结果图层 · 当前状态') : 'SWMM / ANUGA 结果图层 · 当前状态')}</strong><span className={`abu-flood-pill ${historicalReplayVisible || gwmVisible || scenarioMapPayload || publicCitywide2dVisible || customerDtmDiagnostic || citySpatialResultReady || cityRuntimeReady || cityCompileReady || swmmResultReady ? 'abu-flood-status-partial' : 'abu-flood-status-blocked'}`}>{localizeAbuText(historicalReplayVisible ? '2024 历史重演地图已刷新' : gwmVisible ? (gwmIsTrained ? '历史事件 GWM R1 地图已刷新' : '规则型 GWM 地图已刷新') : scenarioMapPayload ? 'SWMM 诊断地图已刷新' : publicCitywide2dVisible ? (customerDtmSurfaceActive ? '客户 5 m DTM 输入、250 m 网格结果已接入' : '全市公共二维原型已接入') : customerDtmDiagnostic ? 'ANUGA 2D 局部诊断已接入' : citySpatialResultReady ? '历史节点/管段诊断资产已接入' : cityRuntimeReady ? '作业运行状态已接入' : cityCompileReady ? '全市输入已编译 / 结果待运行' : swmmResultReady ? '公开代理原型 / 未准入' : '未生成 / 未准入')}</span></div>
          {historicalReplayVisible && historicalReplayValidation && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('2024 历史重演 · 客户 5 m DTM 输入、250 m 网格积水结果')}</strong><small>{localizeAbuPair(`${Number(historicalReplayValidation.metadata?.timeline?.total_cell_count || 0).toLocaleString()} 个陆域二维单元 · ${Number(historicalReplayValidation.metadata?.timeline?.period_count || 0)} 个时间片 · 交换体积数值对账完成 · SWMM 严格质量门未通过`, `${Number(historicalReplayValidation.metadata?.timeline?.total_cell_count || 0).toLocaleString()} 2D land cells · ${Number(historicalReplayValidation.metadata?.timeline?.period_count || 0)} time slices · exchange-volume numerical reconciliation completed · SWMM strict quality gate failed`)}</small></span><em>{localizeAbuText('阶段 5 诊断验证')}</em></div>}
          {gwmVisible && gwmRun && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{gwmIsTrained ? localizeAbuPair(`历史事件 GWM R1 · 场次 ${String(gwmRun.metadata?.event?.event_id || '')} 最大深度 / 动态水深`, `Historical-event GWM R1 · event ${String(gwmRun.metadata?.event?.event_id || '')} maximum / dynamic depth`) : localizeAbuText(`规则型 GWM · ${Number(gwmRun.metadata?.return_period_years || gwmReturnPeriodYears)} 年一遇基线 / 干预 / 差值`)}</strong><small>{gwmIsTrained ? localizeAbuPair(`${Number(gwmRun.metrics?.affected_cell_count || 0).toLocaleString()} 个受影响 250 m 网格 · ${Number(gwmRun.metadata?.timeline?.period_count || 0)} 个 5 分钟时间片 · 最大深度 ${Number(gwmRun.metrics?.maximum_depth_m || 0).toFixed(3)} m${gwmExternalHoldout ? ' · 2024 外部留出，仅冻结推理/报告' : ''}`, `${Number(gwmRun.metrics?.affected_cell_count || 0).toLocaleString()} affected 250 m cells · ${Number(gwmRun.metadata?.timeline?.period_count || 0)} five-minute time slices · maximum depth ${Number(gwmRun.metrics?.maximum_depth_m || 0).toFixed(3)} m${gwmExternalHoldout ? ' · 2024 external holdout; frozen inference/reporting only' : ''}`) : localizeAbuText(`${Number(gwmRun.metrics?.source_feature_count || 0).toLocaleString()} 个二维单元 · ${Number(gwmRun.metadata?.timeline?.period_count || 0)} 个时间片 · 响应倍率 ${Number(gwmRun.metadata?.response_factor || 1).toFixed(3)} · 不确定性 ${(Number(gwmRun.metadata?.uncertainty_fraction || 0) * 100).toFixed(1)}%`)}</small></span><em>{localizeAbuText(gwmIsTrained ? '研究代理已接入' : '规则筛选已接入')}</em></div>}
          {scenarioMapPayload && !publicCitywide2dVisible && !gwmVisible && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('EPA SWMM 诊断作业 · 节点级原生 OUT 时序')}</strong><small>{localizeAbuPair(`${scenarioNativeNodeCount.toLocaleString()} 个原生结果节点 · ${scenarioMappedNodeCount.toLocaleString()} 个可视化节点 · ${scenarioMissingGeometryCount.toLocaleString()} 个缺失几何 · 已映射节点包含零值且无数值阈值截断`, `${scenarioNativeNodeCount.toLocaleString()} native result nodes · ${scenarioMappedNodeCount.toLocaleString()} mapped nodes · ${scenarioMissingGeometryCount.toLocaleString()} missing geometries · mapped nodes include zero values with no value-threshold truncation`)}</small></span><em>{localizeAbuText(scenarioMissingGeometryCount > 0 ? '部分几何覆盖' : '完整几何覆盖')}</em></div>}
          {publicCitywide2dVisible && publicCitywide2dDiagnostic && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText(customerDtmSurfaceActive ? 'ANUGA 2D · 客户 5 m DTM 输入 / 250 m 全市计算网格' : 'ANUGA 2D · Copernicus DEM GLO-30 全市陆域公共原型')}</strong><small>{localizeAbuPair(`250 m 计算网格 · ${Number(publicCitywide2dDiagnostic.metadata?.timeline?.total_cell_count || 0).toLocaleString()} 个陆域单元 · ${Number(publicLandWaterMask?.excluded_permanent_water_cells || 0).toLocaleString()} 个永久水体单元已排除 · ${Number(publicCitywide2dDiagnostic.metadata?.timeline?.period_count || 0)} 个时间片 · 最大深度 ${Number(publicCitywide2dDiagnostic.metadata?.maximum_depth_m || 0).toFixed(2)} m`, `250 m computational grid · ${Number(publicCitywide2dDiagnostic.metadata?.timeline?.total_cell_count || 0).toLocaleString()} land cells · ${Number(publicLandWaterMask?.excluded_permanent_water_cells || 0).toLocaleString()} permanent-water cells excluded · ${Number(publicCitywide2dDiagnostic.metadata?.timeline?.period_count || 0)} time slices · maximum depth ${Number(publicCitywide2dDiagnostic.metadata?.maximum_depth_m || 0).toFixed(2)} m`)}</small></span><em>{localizeAbuText('陆海掩膜已应用')}</em></div>}
          {citySpatialResultReady && !historicalReplayVisible && !publicCitywide2dVisible && !gwmVisible && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('SWMM 全市连续网络节点/管段结果')}</strong><small>{localizeAbuText('结果回挂客户真实节点和管线几何；内部计算组织不作为空间结果来源')}</small></span><em>{localizeAbuText('诊断已接入')}</em></div>}
          {customerDtmDiagnostic && !historicalReplayVisible && !publicCitywide2dVisible && !gwmVisible && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('ANUGA 2D · 客户 dtm_5M 最大积水深度')}</strong><small>{localizeAbuText('500 m × 500 m 局部诊断 · 2,500 个二维单元 · 结果未校准、未工程准入')}</small></span><em>{localizeAbuText('局部诊断已接入')}</em></div>}
          {cityRuntimeReady && !historicalReplayVisible && !publicCitywide2dVisible && !gwmVisible && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('全市连续网络运行状态')}</strong><small>{localizeAbuText(runtimeCountLabel)} · {localizeAbuText('运行状态标记不代表积水位置')}</small></span><em>{localizeAbuText('已接入')}</em></div>}
          {cityDynamicResultReady && !historicalReplayVisible && !publicCitywide2dVisible && !gwmVisible && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('SWMM 分区汇总统计（非空间水动力图层）')}</strong><small>{localizeAbuText('分区洪涝损失、外排量和连续性误差仅在分区统计表中查看，不映射为中心点结果')}</small></span><em>{localizeAbuText('统计已接入')}</em></div>}
          {!cityRuntimeReady && cityCompileReady && !historicalReplayVisible && !publicCitywide2dVisible && !gwmVisible && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('全市连续网络编译覆盖')}</strong><small>{localizeAbuText('保留跨内部计算组织的可用连接；不是正式分区面')}</small></span><em>{localizeAbuText('已接入')}</em></div>}
          {!historicalReplayVisible && !publicCitywide2dVisible && !gwmVisible && <div className="abu-flood-result-list">
            {swmmResultCatalog.map(result => <div key={result.field}><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText(result.name)}</strong><small>{localizeAbuText(result.geometry)} · {result.unit}</small></span><em>{localizeAbuText(publicCitywide2dVisible ? (customerDtmSurfaceActive ? '二维地表结果已接入（客户 5 m DTM）' : '二维地表结果已接入（公共 DEM 原型）') : scenarioMapPayload && result.geometry === '节点' ? '本次节点结果已接入' : customerDtmDiagnostic && result.geometry === '节点' ? 'ANUGA 2D 局部结果已接入' : citySpatialResultReady ? '客户真实几何已接入' : cityDynamicResultReady ? '分区统计已接入，空间结果待接入' : swmmResultReady && !cityRuntimeReady ? '公开代理局部原型已接入' : cityRuntimeReady ? '仅运行状态已接入' : cityCompileReady ? '待运行' : '暂无')}</em></div>)}
          </div>}
        <div className="abu-flood-result-note"><LockKeyhole size={12} />{mapResultBoundaryNote}</div>
        </div>
      </section>

      <section className="abu-flood-section">
        <div className="abu-flood-section-heading">
          <div><span className="abu-flood-overline">PIPELINE</span><h3>{localizeAbuText('从数据到决策')}</h3></div>
          <span className="abu-flood-muted">{en('pipeline.statusHint', 'The top-right icon shows whether the stage capability or result is ready; it does not indicate engineering admission.')}</span>
        </div>
        <div className="abu-flood-stage-track">
          {displayStages.map((stage, index) => {
            const Icon = stage.icon;
            const pipelineComplete = Boolean(pipelineStageCompletion[stage.key]);
            const StatusIcon = pipelineComplete ? CheckCircle2 : CircleDashed;
            const pipelineStatusLabel = pipelineComplete
              ? en('pipeline.complete', 'Stage capability or result ready; not engineering-admitted')
              : en('pipeline.waiting', 'Waiting for the stage capability or result');
            return (
              <div className="abu-flood-stage-wrap" key={stage.key}>
                <button
                  className={`abu-flood-stage ${selectedKey === stage.key ? 'active' : ''}`}
                  onClick={() => { setSelectedKey(stage.key); sendStageToMap(stage.key, customerMapReady, swmmResultReady, cityCompileReady, cityRuntimeReady, cityDynamicResultReady, citySpatialResultReady); }}
                  aria-pressed={selectedKey === stage.key}
                  data-stage-key={stage.key}
                  data-stage-progress={pipelineComplete ? 'complete' : 'waiting'}
                >
                  <div className="abu-flood-stage-top"><span>{stage.index}</span><span className={pipelineComplete ? stageStatusClass.ready : stageStatusClass.partial} data-stage-progress-icon={pipelineComplete ? 'complete' : 'waiting'} role="img" aria-label={pipelineStatusLabel} title={pipelineStatusLabel}><StatusIcon size={14} aria-hidden="true" /></span></div>
                  <Icon size={20} />
                  <strong>{localizeAbuText(stage.title)}</strong>
                  <small>{localizeAbuText(stage.statusLabel)}</small>
                </button>
                {index < stages.length - 1 && <ArrowRight size={15} className="abu-flood-stage-arrow" />}
              </div>
            );
          })}
        </div>
      </section>

      <section className="abu-flood-detail-grid">
        <div className="abu-flood-detail-panel">
          <div className="abu-flood-detail-heading">
            <div className="abu-flood-detail-title"><span className="abu-flood-detail-icon"><StageIcon size={18} /></span><div><span className="abu-flood-overline">STAGE {selectedStage.index}</span><h3>{localizeAbuText(selectedStage.title)}</h3><p>{localizeAbuText(selectedStage.subtitle)}</p></div></div>
            <div className="abu-flood-detail-heading-actions">
              <span className={`abu-flood-pill ${stageStatusClass[selectedStage.status]}`}>{localizeAbuText(selectedStage.statusLabel)}</span>
              {selectedKey !== 'validation' && <button className="abu-flood-map-action" type="button" disabled={simulationReportLoading || (selectedKey === 'gwm' && (!gwmRun || gwmIsTrained))} onClick={() => {
                const type = selectedKey === 'data' ? 'data_admission' : selectedKey === 'swmm' ? 'swmm_scenario' : selectedKey === 'surface' ? 'citywide_2d' : 'gwm_rollout';
                void openSimulationReport(type, { runId: selectedKey === 'swmm' ? scenarioRun?.runId : selectedKey === 'gwm' ? gwmRun?.run_id : undefined, returnPeriodYears: selectedKey === 'surface' ? surfaceReturnPeriodYears : selectedKey === 'gwm' ? gwmReturnPeriodYears : undefined });
              }}><FileCheck2 size={14} />{simulationReportLoading ? localizeAbuText('正在生成报告…') : localizeAbuText('输出决策支持报告')}</button>}
            </div>
          </div>
          <p className="abu-flood-detail-summary">{localizeAbuText(selectedStage.summary)}</p>
          {simulationReportError && <div className="abu-flood-form-error"><AlertTriangle size={13} />{localizeAbuText(simulationReportError)}</div>}
          {selectedKey === 'surface' && <div className="abu-flood-surface-workspace">
            <div className="abu-flood-surface-workspace-tabs" role="tablist" aria-label={localizeAbuText('二维地表水动力工作区')}>
              <button type="button" role="tab" aria-selected={surfaceWorkspaceView === 'invoke'} className={surfaceWorkspaceView === 'invoke' ? 'active' : ''} onClick={() => setSurfaceWorkspaceView('invoke')}><Play size={14} />{localizeAbuText('二维模型调用')}</button>
              <button type="button" role="tab" aria-selected={surfaceWorkspaceView === 'results'} className={surfaceWorkspaceView === 'results' ? 'active' : ''} onClick={() => setSurfaceWorkspaceView('results')}><FileCheck2 size={14} />{localizeAbuText('已算结果')}</button>
            </div>

            {surfaceWorkspaceView === 'invoke' ? <div className="abu-flood-surface-run-grid">
              <div className="abu-flood-scenario-form">
                <div className="abu-flood-scenario-disclaimer"><AlertTriangle size={14} /><span>{localizeAbuText('提交后会在独立私有目录中真实启动 ANUGA 2D，不覆盖已登记成果。二维面雨、SWMM→ANUGA 单向交换和 SWMM–ANUGA 同步双向交换均调用真实求解器；耦合模式要求服务器已挂载全市 SWMM 输入、250 m 地形网格和接口绑定清单。LISFLOOD-FP 通过独立 GPL 镜像运行，不在本 API 进程内混装。')}</span></div>
                <div className="abu-flood-form-group">
                  <div className="abu-flood-form-group-title"><Layers3 size={14} /><strong>{localizeAbuText('求解器与一维输入')}</strong><small>{localizeAbuText('能力状态与作业来源')}</small></div>
                  <div className="abu-flood-form-grid">
                    <label>{localizeAbuText('二维求解器')}<select value={surfaceRunForm.solver} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('solver', event.target.value as SurfaceRunForm['solver'])}><option value="anuga">{localizeAbuText('ANUGA 2D（当前可新建作业）')}</option><option disabled value="lisflood">{localizeAbuText('LISFLOOD-FP（合成诊断已适配，全市作业器未接入）')}</option></select></label>
                    <label>{localizeAbuText('阶段 2 输入作业')}<select value={surfaceRunForm.couplingMode === 'surface_rainfall_only' ? 'surface_only' : 'mounted_swmm'} disabled><option value="surface_only">{localizeAbuText('本次新算：二维面雨直接驱动')}</option><option value="mounted_swmm">{localizeAbuText('服务器挂载的全市 SWMM 输入')}</option></select></label>
                    <label>{localizeAbuText('耦合方式')}<select value={surfaceRunForm.couplingMode} disabled={surfaceRunBusy} onChange={event => { const couplingMode = event.target.value as SurfaceRunForm['couplingMode']; setSurfaceRunForm(current => ({ ...current, couplingMode, ...(couplingMode === 'surface_rainfall_only' ? {} : { cellSizeM: 250, terrainSource: 'customer_dtm_5m', outputIntervalMinutes: 5 }) })); setSurfaceRunError(null); }}><option value="surface_rainfall_only">{localizeAbuText('二维面雨直接驱动')}</option><option value="one_way_swmm_to_anuga">SWMM → ANUGA {localizeAbuText('单向溢流交换')}</option><option value="two_way_swmm_anuga">SWMM ↔ ANUGA {localizeAbuText('同步双向交换')}</option></select></label>
                    <label>{localizeAbuText('计算范围')}<select value={surfaceRunForm.domain} disabled><option value="citywide">{localizeAbuText('阿布扎比全市登记范围')}</option></select></label>
                  </div>
                </div>

                <div className="abu-flood-form-group">
                  <div className="abu-flood-form-group-title"><CloudRain size={14} /><strong>{localizeAbuText('降雨强迫')}</strong><small>{localizeAbuText('2022 官方 Zone B DDF + 明示雨型假设')}</small></div>
                  <div className="abu-flood-form-grid">
                    <label>{localizeAbuText('降雨来源')}<select value={surfaceRunForm.rainfallSource} disabled><option value="zone_b_design_storm">{localizeAbuText('Zone B 官方 DDF 设计暴雨')}</option></select></label>
                    <label>{localizeAbuText('设计重现期')}<select value={surfaceRunForm.returnPeriodYears} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('returnPeriodYears', Number(event.target.value) as ReturnPeriodYears)}>{([2, 5, 10, 25, 50, 100] as ReturnPeriodYears[]).map(value => <option key={value} value={value}>{value}{localizeAbuText('年一遇')} · {zoneB180DepthByReturnPeriod[value].toFixed(2)} mm</option>)}</select></label>
                    <label>{localizeAbuText('降雨历时（分钟）')}<input type="number" value={surfaceRunForm.rainfallDurationMinutes} disabled /></label>
                    <label>{localizeAbuText('峰值位置（%）')}<input type="number" min="5" max="95" step="5" value={surfaceRunForm.peakPositionPercent} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('peakPositionPercent', Number(event.target.value))} /></label>
                  </div>
                  <div className="abu-flood-form-hint"><CloudRain size={13} />{localizeAbuText(`当前 ${surfaceRunForm.returnPeriodYears} 年一遇 180 分钟总雨量为 ${zoneB180DepthByReturnPeriod[surfaceRunForm.returnPeriodYears].toFixed(2)} mm；5 分钟交替块时程和峰值位置是建模假设。`)}</div>
                </div>

                <div className="abu-flood-form-group">
                  <div className="abu-flood-form-group-title"><MapIcon size={14} /><strong>{localizeAbuText('地形、网格与糙率')}</strong><small>{localizeAbuText('新算参数写入运行回执')}</small></div>
                  <div className="abu-flood-form-grid">
                    <label>{localizeAbuText('地形产品')}<select value={surfaceRunForm.terrainSource} disabled={surfaceRunBusy || surfaceRunForm.couplingMode !== 'surface_rainfall_only'} onChange={event => updateSurfaceRun('terrainSource', event.target.value as SurfaceRunForm['terrainSource'])}><option value="customer_dtm_5m">{localizeAbuText('客户 AUH_DTM 5 m（主输入）')}</option><option value="copernicus_dem_glo30">Copernicus DEM GLO-30（{localizeAbuText('公开回退')}）</option></select></label>
                    <label>{localizeAbuText('计算网格（m）')}<select value={surfaceRunForm.cellSizeM} disabled={surfaceRunBusy || surfaceRunForm.couplingMode !== 'surface_rainfall_only'} onChange={event => updateSurfaceRun('cellSizeM', Number(event.target.value) as SurfaceRunForm['cellSizeM'])}><option value="500">500 · {localizeAbuText('快速诊断')}</option><option value="250">250 · {localizeAbuText('登记/耦合基线')}</option><option disabled value="100">100 · {localizeAbuText('高分辨率（Web 调用暂未开放）')}</option><option disabled value="50">50 · {localizeAbuText('高分辨率（Web 调用暂未开放）')}</option></select></label>
                    <label>{localizeAbuText('陆地 Manning n')}<input type="number" min="0.005" max="0.2" step="0.001" value={surfaceRunForm.landManningN} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('landManningN', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('水体 Manning n')}<input type="number" min="0.005" max="0.2" step="0.001" value={surfaceRunForm.waterManningN} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('waterManningN', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('初始水深（m）')}<input type="number" min="0" max="2" step="0.01" value={surfaceRunForm.initialDepthM} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('initialDepthM', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('最小发布水深（m）')}<input type="number" min="0.0001" max="0.5" step="0.001" value={surfaceRunForm.minimumOutputDepthM} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('minimumOutputDepthM', Number(event.target.value))} /></label>
                  </div>
                </div>

                <div className="abu-flood-form-group">
                  <div className="abu-flood-form-group-title"><Network size={14} /><strong>{localizeAbuText('交换与重复计量控制')}</strong><small>{localizeAbuText(surfaceRunForm.couplingMode === 'surface_rainfall_only' ? '面雨模式不读取阶段 2 节点交换量' : '耦合参数写入运行回执')}</small></div>
                  <div className="abu-flood-form-grid">
                    <label>{localizeAbuText('SWMM→二维交换变量')}<select disabled value="node_flooding"><option value="node_flooding">{localizeAbuText('节点 overflow / flooding 流量')}</option></select></label>
                    <label>{localizeAbuText('动态水头反向反馈')}<select disabled value={surfaceRunForm.couplingMode === 'two_way_swmm_anuga' ? 'on' : 'off'}><option value="off">{localizeAbuText('关闭')}</option><option value="on">{localizeAbuText('开启（同步双向）')}</option></select></label>
                    <label>{localizeAbuText('交换窗口（秒）')}<select value={surfaceRunForm.exchangeWindowSeconds} disabled={surfaceRunBusy || surfaceRunForm.couplingMode === 'surface_rainfall_only'} onChange={event => updateSurfaceRun('exchangeWindowSeconds', Number(event.target.value) as SurfaceRunForm['exchangeWindowSeconds'])}>{([300, 600, 900] as const).map(value => <option key={value} value={value}>{value}</option>)}</select></label>
                    <label>{localizeAbuText('进水口有效开口面积（m²）')}<input type="number" min="0" max="100" step="0.05" value={surfaceRunForm.openingAreaM2} disabled={surfaceRunBusy || surfaceRunForm.couplingMode !== 'two_way_swmm_anuga'} onChange={event => updateSurfaceRun('openingAreaM2', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('流量系数 Cd')}<input type="number" min="0" max="1" step="0.01" value={surfaceRunForm.dischargeCoefficient} disabled={surfaceRunBusy || surfaceRunForm.couplingMode !== 'two_way_swmm_anuga'} onChange={event => updateSurfaceRun('dischargeCoefficient', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('单点最大交换流量（m³/s）')}<input type="number" min="0.0001" max="1000" step="0.1" value={surfaceRunForm.maximumExchangeRateM3s} disabled={surfaceRunBusy || surfaceRunForm.couplingMode !== 'two_way_swmm_anuga'} onChange={event => updateSurfaceRun('maximumExchangeRateM3s', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('回执接口明细上限')}<input type="number" min="0" max="10000" step="10" value={surfaceRunForm.interfaceDetailLimit} disabled={surfaceRunBusy || surfaceRunForm.couplingMode === 'surface_rainfall_only'} onChange={event => updateSurfaceRun('interfaceDetailLimit', Number(event.target.value))} /></label>
                  </div>
                  <div className="abu-flood-control-row"><label className="abu-flood-toggle"><input type="checkbox" checked={surfaceRunForm.couplingMode !== 'surface_rainfall_only'} disabled /><span>{localizeAbuText('耦合模式关闭二维面雨，仅使用 SWMM 节点交换量，避免重复计量')}</span></label></div>
                </div>

                <div className="abu-flood-form-group compact">
                  <div className="abu-flood-form-group-title"><Clock3 size={14} /><strong>{localizeAbuText('边界与运行设置')}</strong><small>{localizeAbuText('模拟总时长 = 降雨历时 + 雨后计算')}</small></div>
                  <div className="abu-flood-form-grid">
                    <label>{localizeAbuText('边界类型')}<select value={surfaceRunForm.boundaryType} disabled><option value="fixed_stage">{localizeAbuText('外边界固定水位')}</option></select></label>
                    <label>{localizeAbuText('海边界水位（m）')}<input type="number" min="-5" max="10" step="0.01" value={surfaceRunForm.seaBoundaryLevelM} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('seaBoundaryLevelM', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('永久水体比例阈值')}<input type="number" min="0" max="1" step="0.05" value={surfaceRunForm.waterCellFractionThreshold} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('waterCellFractionThreshold', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('雨后计算（分钟）')}<input type="number" min="0" max="1440" step="10" value={surfaceRunForm.tailMinutes} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('tailMinutes', Number(event.target.value))} /></label>
                    <label>{localizeAbuText('输出间隔（分钟）')}<select value={surfaceRunForm.outputIntervalMinutes} disabled={surfaceRunBusy} onChange={event => updateSurfaceRun('outputIntervalMinutes', Number(event.target.value) as SurfaceRunForm['outputIntervalMinutes'])}>{([5, 10, 15, 30, 60] as const).map(value => <option key={value} value={value}>{value}</option>)}</select></label>
                    <label>{localizeAbuText('总模拟时长（分钟）')}<input type="number" value={surfaceRunForm.rainfallDurationMinutes + surfaceRunForm.tailMinutes} disabled /></label>
                  </div>
                </div>

                {surfaceRunError && <div className="abu-flood-form-error"><AlertTriangle size={14} />{localizeAbuText(surfaceRunError)}</div>}
                <div className="abu-flood-scenario-actions">
                  <button className="abu-flood-map-action" type="button" onClick={runSurfaceModel} disabled={controlsBusy}><Play size={15} />{surfaceRunBusy ? localizeAbuText(surfaceRunForm.couplingMode === 'surface_rainfall_only' ? '正在运行 ANUGA 2D…' : '正在运行 SWMM–ANUGA 耦合…') : localizeAbuText('提交二维计算')}</button>
                  <button className="abu-flood-reset-action" type="button" onClick={resetSurfaceRun} disabled={controlsBusy}><RotateCcw size={14} />{localizeAbuText('恢复默认')}</button>
                </div>
              </div>

              <aside className="abu-flood-scenario-result">
                <div className="abu-flood-result-heading"><Gauge size={14} /><strong>{localizeAbuText('二维作业与结果回执')}</strong><span className={`abu-flood-pill ${surfaceRunReceipt ? 'abu-flood-status-partial' : 'abu-flood-status-blocked'}`}>{surfaceRunReceipt ? localizeAbuText(({ queued: '排队中', running: '运行中', completed: '已完成', failed: '失败' } as Record<string, string>)[surfaceRunReceipt.status] || surfaceRunReceipt.status) : localizeAbuText('尚未运行')}</span></div>
                {surfaceRunReceipt ? <>
                  <details className="abu-flood-quality-details abu-flood-run-technical-details" open={surfaceRunReceipt.status === 'failed'}><summary>{localizeAbuText('技术详情与作业标识')}</summary><div className="abu-flood-scenario-run-id"><span>{localizeAbuText('当前二维 Run ID')}</span><code>{surfaceRunReceipt.runId}</code></div><small>{localizeAbuText(`开始：${surfaceRunReceipt.startedAt || surfaceRunReceipt.createdAt || '—'}${surfaceRunReceipt.finishedAt ? ` · 完成：${surfaceRunReceipt.finishedAt}` : ''}`)}</small></details>
                  <div className="abu-flood-scenario-result-metrics">
                    <div><span>{localizeAbuText('计算网格')}</span><strong>{Number(surfaceRunReceipt.scenario?.cell_size_m || surfaceRunForm.cellSizeM)}</strong><small>m</small></div>
                    <div><span>{localizeAbuText('总模拟时长')}</span><strong>{Number(surfaceRunReceipt.scenario?.rainfall_duration_minutes || 180) + Number(surfaceRunReceipt.scenario?.tail_minutes || surfaceRunForm.tailMinutes)}</strong><small>min</small></div>
                    <div><span>{localizeAbuText('最大积水深度')}</span><strong>{surfaceRunReceipt.summary?.results?.maximum_depth_m == null ? '—' : Number(surfaceRunReceipt.summary.results.maximum_depth_m).toFixed(2)}</strong><small>m</small></div>
                  </div>
                  <div className="abu-flood-scenario-timeline">
                    {([['01', '参数验收'], ['02', '地形与网格准备'], ['03', 'ANUGA 水动力求解'], ['04', '最大深度与时间轴发布']] as const).map(([index, title], itemIndex) => { const progress = surfaceRunReceipt.status === 'completed' ? 4 : surfaceRunReceipt.status === 'running' ? 2 : surfaceRunReceipt.status === 'failed' ? 2 : 1; const complete = itemIndex < progress; return <div className={`abu-flood-scenario-timeline-item ${complete ? 'complete' : 'pending'}`} key={index}><span>{index}</span><div><strong>{localizeAbuText(title)}</strong><small>{localizeAbuText(complete ? '已完成或正在执行' : '等待前序步骤')}</small></div><span className="timeline-state">{localizeAbuText(complete ? '已进入' : '待处理')}</span></div>; })}
                  </div>
                  {surfaceRunReceipt.failureDetail && <div className="abu-flood-form-error"><AlertTriangle size={13} />{localizeAbuText(surfaceRunReceipt.failureDetail)}</div>}
                  <div className="abu-flood-scenario-claim"><LockKeyhole size={13} />{localizeAbuText('新算结果写入独立私有目录；诊断用途，未校准、未工程准入，不覆盖已登记成果。')}</div>
                </> : <div className="abu-flood-scenario-empty"><Layers3 size={24} /><strong>{localizeAbuText('设置二维水动力参数')}</strong><span>{localizeAbuText('提交后这里会显示 Run ID、求解状态、网格与结果摘要；完成后最大深度和动态时间轴会自动发送到地图。')}</span></div>}
              </aside>
            </div> : <div className="abu-flood-precomputed-surface-page">
              <div className="abu-flood-surface-period-control">
                <div><strong>{localizeAbuText('已登记的二维成果')}</strong><small>{localizeAbuText('单向多年一遇成果与 100 年一遇同步双向数值验证成果独立保留；加载只读成果和回执，不会启动新计算。')}</small></div>
                <label>{localizeAbuText('成果来源')}<select value={surfaceResultSource} disabled={surfaceReturnPeriodLoading} onChange={event => { const source = event.target.value as SurfaceResultSource; setSurfaceReturnPeriodError(null); setSurfaceResultSource(source); if (source === 'bidirectional_validation') setSurfaceReturnPeriodYears(100); }}><option value="return_period_one_way">{localizeAbuText('SWMM→ANUGA 单向多年一遇（6 套）')}</option><option value="bidirectional_validation">{localizeAbuText('SWMM–ANUGA 同步双向验证（100 年一遇）')}</option></select></label>
                <label>{localizeAbuText('设计重现期')}<select value={surfaceResultSource === 'bidirectional_validation' ? 100 : surfaceReturnPeriodYears} disabled={surfaceReturnPeriodLoading || surfaceResultSource === 'bidirectional_validation'} onChange={event => { setSurfaceReturnPeriodError(null); setSurfaceReturnPeriodYears(Number(event.target.value) as ReturnPeriodYears); }}>{([2, 5, 10, 25, 50, 100] as ReturnPeriodYears[]).map(value => <option key={value} value={value}>{value}{localizeAbuText('年一遇')}</option>)}</select></label>
                <div className="abu-flood-scenario-actions"><button className="abu-flood-map-action" type="button" disabled={surfaceReturnPeriodLoading} onClick={() => setSurfaceReloadToken(value => value + 1)}>{surfaceReturnPeriodLoading ? <LoaderCircle className="abu-flood-loading-icon" size={14} /> : <MapIcon size={14} />}{surfaceReturnPeriodLoading ? localizeAbuText('正在加载二维结果…') : localizeAbuText('加载到地图')}</button></div>
                <span className="abu-flood-surface-period-status" aria-live="polite">{surfaceReturnPeriodLoading ? localizeAbuText('正在读取最大深度、时间轴与运行回执…') : surfaceResultVariant === surfaceResultSource && Number(publicCitywide2dDiagnostic?.metadata?.return_period_years || 0) === (surfaceResultSource === 'bidirectional_validation' ? 100 : surfaceReturnPeriodYears) && surfaceModelConfiguration.execution_mode === 'registered_precomputed_result' ? localizeAbuText(surfaceResultSource === 'bidirectional_validation' ? '100 年一遇同步双向数值验证成果已加载' : `${surfaceReturnPeriodYears} 年一遇单向登记成果已加载`) : localizeAbuText('已选择成果来源，点击“加载到地图”读取成果')}</span>
                {surfaceReturnPeriodError && <span className="abu-flood-form-error"><AlertTriangle size={13} />{localizeAbuText(surfaceReturnPeriodError)}</span>}
              </div>
              <div className="abu-flood-scenario-result-metrics abu-flood-surface-result-metrics">
                <div><span>{localizeAbuText('求解器')}</span><strong>{String(surfaceModelConfiguration.solver || 'ANUGA 2D')}</strong><small>{surfaceIsBidirectionalValidation ? 'EPA SWMM 5.2.4 ↔ ANUGA' : 'EPA SWMM 5.2.4 → ANUGA'}</small></div>
                <div><span>{localizeAbuText('地形 / 网格')}</span><strong>{Number(surfaceModelConfiguration.model_cell_size_m || 250).toFixed(0)} m</strong><small>{localizeAbuText(String(surfaceModelConfiguration.terrain_product || '客户 5 m DTM'))}</small></div>
                <div><span>{localizeAbuText('耦合方式')}</span><strong>{localizeAbuText(surfaceIsBidirectionalValidation ? '同步双向验证' : '单向')}</strong><small>{localizeAbuText(String(surfaceModelConfiguration.exchange_quantity || '节点溢流 → 二维源项'))}</small></div>
                <div><span>{localizeAbuText('模拟时长')}</span><strong>{Number(surfaceModelConfiguration.simulation_duration_minutes || 300).toFixed(0)}</strong><small>min · {Number(surfaceModelConfiguration.output_interval_minutes || 30).toFixed(0)} min {localizeAbuText('输出')}</small></div>
                <div><span>{localizeAbuText('最大积水深度')}</span><strong>{Number(publicCitywide2dDiagnostic?.metadata?.maximum_depth_m || 0).toFixed(2)}</strong><small>m</small></div>
                <div><span>{localizeAbuText(surfaceIsBidirectionalValidation ? '淹没面积 ≥ 0.01 m' : '淹没面积 ≥ 0.05 m')}</span><strong>{(Number((surfaceIsBidirectionalValidation ? publicCitywide2dDiagnostic?.metadata?.inundated_area_ge_0_01m2 : publicCitywide2dDiagnostic?.metadata?.inundated_area_ge_0_05m2) || 0) / 1_000_000).toFixed(1)}</strong><small>km²</small></div>
              </div>
              {surfaceIsBidirectionalValidation && <div className="abu-flood-scenario-result-metrics abu-flood-surface-result-metrics">
                <div><span>{localizeAbuText('同步交换窗口')}</span><strong>{Number(surfaceCouplingSummary.window_count || 0).toLocaleString()}</strong><small>{Number(surfaceCouplingSummary.exchange_window_seconds || 0).toFixed(0)} s / {localizeAbuText('窗口')}</small></div>
                <div><span>{localizeAbuText('交换接口')}</span><strong>{Number(surfaceCouplingSummary.interface_count || 0).toLocaleString()}</strong><small>{localizeAbuText('客户管网节点与二维单元')}</small></div>
                <div><span>SWMM → ANUGA</span><strong>{(Number(surfaceCouplingSummary.total_swmm_to_anuga_m3 || 0) / 1_000_000).toFixed(2)}</strong><small>{localizeAbuText('百万 m³')}</small></div>
                <div><span>ANUGA → SWMM</span><strong>{(Number(surfaceCouplingSummary.total_anuga_to_swmm_m3 || 0) / 1_000_000).toFixed(2)}</strong><small>{localizeAbuText('百万 m³')}</small></div>
              </div>}
              <div className="abu-flood-registered-result-receipt"><FileCheck2 size={15} /><div><strong>{localizeAbuText('登记成果运行回执')}</strong><span>Run ID: <code>{surfaceInvocationReceipt?.runId || publicCitywide2dDiagnostic?.metadata?.timeline?.run_id || '—'}</code></span><small>{localizeAbuText(`${Number(publicCitywide2dDiagnostic?.metadata?.timeline?.total_cell_count || 0).toLocaleString()} 个陆域单元 · ${Number(publicCitywide2dDiagnostic?.metadata?.timeline?.period_count || 0)} 个时间片 · 海边界 ${Number(surfaceModelConfiguration.sea_boundary_level_m || 0).toFixed(2)} m · 永久水体阈值 ${Number(surfaceModelConfiguration.water_cell_fraction_threshold || 0.2).toFixed(2)}`)}</small></div></div>
              <div className="abu-flood-validation-gate pending"><LockKeyhole size={13} /><div><strong>{localizeAbuText('能力边界')}</strong><span>{localizeAbuText(surfaceIsBidirectionalValidation ? '该成果的回执记录了同步窗口中的正向与反向交换，可作为 SWMM–ANUGA 双向数值验证成果使用；但回执单独不能证明每个时间窗都重新调用了原生 SWMM，且完整 SWMM 系统质量平衡未在该动态 API 回执中评估。结果未校准、未工程准入。' : '这六套多年一遇成果使用已完成的 SWMM 原生 OUT 作为 ANUGA 单向源项，没有动态水头反向反馈；结果未校准、未工程准入。')}</span></div></div>
            </div>}
          </div>}
          {selectedKey === 'gwm' && <div className="abu-flood-surface-period-control abu-flood-gwm-control">
            <div>
              <strong>{localizeAbuText('GWM 推演模式')}</strong>
              <small>{localizeAbuText('历史事件 GWM R1 仅接受冻结模型与已登记降雨强迫；规则型情景筛选保留工程动作参数，两者结果和适用边界相互独立。')}</small>
            </div>
            <div className="abu-flood-gwm-mode" role="tablist" aria-label={localizeAbuText('GWM 推演模式')}>
              <button type="button" role="tab" aria-selected={gwmMode === 'trained'} className={gwmMode === 'trained' ? 'active' : ''} onClick={() => { setGwmMode('trained'); setGwmError(null); }}>
                <GitBranch size={14} />{localizeAbuText('历史事件 GWM R1')}
              </button>
              <button type="button" role="tab" aria-selected={gwmMode === 'screening'} className={gwmMode === 'screening' ? 'active' : ''} onClick={() => { setGwmMode('screening'); setGwmError(null); }}>
                <SlidersHorizontal size={14} />{localizeAbuText('规则型情景筛选')}
              </button>
            </div>
            {gwmMode === 'trained' ? <>
              <div className="abu-flood-form-grid">
                <label>{localizeAbuText('历史降雨场次')}
                  <select value={trainedGwmEventId} disabled={gwmBusy || trainedGwmEventsLoading || !trainedGwmEvents.length} onChange={event => setTrainedGwmEventId(event.target.value)}>
                    {!trainedGwmEvents.length && <option value="">{localizeAbuText(trainedGwmEventsLoading ? '正在读取历史场次…' : '暂无可用历史场次')}</option>}
                    {trainedGwmEvents.map(event => <option key={event.event_id} value={event.event_id}>
                      {`${event.start_utc.slice(0, 10)} · ${event.split}${event.external_holdout ? ' · 外部留出' : ''} · ${event.event_id}`}
                    </option>)}
                  </select>
                </label>
              </div>
              {trainedGwmModel && <div className="abu-flood-scenario-result-metrics">
                <div><span>{localizeAbuText('模型版本')}</span><strong>{trainedGwmModel.release_id || 'GWM-R1-20260914'}</strong><small>{localizeAbuText('冻结研究代理')}</small></div>
                <div><span>{localizeAbuText('训练事件')}</span><strong>{Number(trainedGwmModel.training_event_count || 0).toLocaleString()}</strong><small>{localizeAbuPair(`${String(trainedGwmModel.training_period_start_utc || '').slice(0, 4)}–${String(trainedGwmModel.training_period_end_utc || '').slice(0, 4)}`, `${String(trainedGwmModel.training_period_start_utc || '').slice(0, 4)}–${String(trainedGwmModel.training_period_end_utc || '').slice(0, 4)}`)}</small></div>
                <div><span>{localizeAbuText('验证 / 盲测')}</span><strong>{Number(trainedGwmModel.validation_event_count || 0)} / {Number(trainedGwmModel.blind_test_event_count || 0)}</strong><small>{localizeAbuText('事件严格分离')}</small></div>
                <div><span>{localizeAbuText('外部留出')}</span><strong>{Number(trainedGwmModel.external_holdout_event_count || 0)}</strong><small>{localizeAbuText('禁止训练与调参')}</small></div>
                <div><span>{localizeAbuText('学习目标')}</span><strong>{Number(trainedGwmModel.grid_cell_size_m || 250).toFixed(0)} m</strong><small>SWMM–ANUGA labels</small></div>
              </div>}
              <div className="abu-flood-scenario-actions">
                <button className="abu-flood-map-action" type="button" onClick={runTrainedGwmRollout} disabled={gwmBusy || trainedGwmEventsLoading || !trainedGwmEventId}>
                  <Play size={15} />{gwmBusy ? localizeAbuText('正在推理历史事件 GWM R1…') : localizeAbuText('推理历史积水过程')}
                </button>
                {gwmIsTrained && <span className="abu-flood-surface-period-status">{localizeAbuText('历史事件 GWM R1 时间轴已就绪')}</span>}
              </div>
              <div className="abu-flood-form-hint" aria-live="polite">
                <GitBranch size={13} />
                {selectedTrainedGwmEvent?.external_holdout
                  ? localizeAbuText(gwmRun?.metadata?.external_validation
                    ? `2024-04-15 为外部留出事件：已追加零雨退水尾段，地图初始帧对齐 Sentinel-2 ${String(gwmRun.metadata.external_validation.satellite_observation_utc || '')}；仅允许冻结模型推理与验证报告，禁止训练、调参、阈值或版本选择。`
                    : '2024-04-15 为外部留出事件：仅允许冻结模型推理与验证报告，禁止训练、调参、阈值或版本选择。')
                  : localizeAbuText('训练型推理使用冻结的 GWM-R1-20260914 与已登记历史降雨强迫；模型由 17 场训练事件学习 250 m SWMM–ANUGA 标签，不直接学习历史观测积水，也不接受规则型控制参数。')}
              </div>
              {trainedGwmEventsError && <span className="abu-flood-form-error"><AlertTriangle size={13} />{localizeAbuText(trainedGwmEventsError)}</span>}
              {gwmIsTrained && <div className="abu-flood-scenario-result-metrics">
                <div><span>{localizeAbuText('最大积水深度')}</span><strong>{Number(gwmRun.metrics?.maximum_depth_m || 0).toFixed(2)}</strong><small>m</small></div>
                <div><span>{localizeAbuText('受影响网格')}</span><strong>{Number(gwmRun.metrics?.affected_cell_count || 0).toLocaleString()}</strong><small>{localizeAbuText('个')}</small></div>
                <div><span>{localizeAbuText('受影响面积')}</span><strong>{(Number(gwmRun.metrics?.affected_area_m2 || 0) / 1_000_000).toFixed(2)}</strong><small>km²</small></div>
                <div><span>{localizeAbuText('时间片')}</span><strong>{Number(gwmRun.metadata?.timeline?.period_count || 0).toLocaleString()}</strong><small>{localizeAbuText('帧')}</small></div>
                <div><span>{localizeAbuText('时间步长')}</span><strong>{Number(gwmRun.metadata?.timeline?.step_minutes || 5).toFixed(0)}</strong><small>{localizeAbuText('分钟')}</small></div>
                <div><span>{localizeAbuText('训练场次')}</span><strong>{Number(gwmRun.metadata?.model?.training_event_count || 0).toLocaleString()}</strong><small>{localizeAbuText('场')}</small></div>
              </div>}
            </> : <>
              <div className="abu-flood-form-grid">
                <label>{localizeAbuText('设计重现期')}
                  <select value={gwmReturnPeriodYears} disabled={gwmBusy} onChange={event => setGwmReturnPeriodYears(Number(event.target.value) as ReturnPeriodYears)}>
                    {([2, 5, 10, 25, 50, 100] as ReturnPeriodYears[]).map(value => <option key={value} value={value}>{value}{localizeAbuText('年一遇')}</option>)}
                  </select>
                </label>
                <label>{localizeAbuText('管线能力倍率')}
                  <input type="number" min="0.1" max="1.5" step="0.05" value={gwmActions.pipeCapacityMultiplier} disabled={gwmBusy} onChange={event => setGwmActions(current => ({ ...current, pipeCapacityMultiplier: Number(event.target.value) }))} />
                </label>
                <label>{localizeAbuText('堵塞率（%）')}
                  <input type="number" min="0" max="90" step="5" value={gwmActions.blockagePercent} disabled={gwmBusy} onChange={event => setGwmActions(current => ({ ...current, blockagePercent: Number(event.target.value) }))} />
                </label>
                <label>{localizeAbuText('泵站能力倍率')}
                  <input type="number" min="0" max="1.5" step="0.05" value={gwmActions.pumpCapacityMultiplier} disabled={gwmBusy} onChange={event => setGwmActions(current => ({ ...current, pumpCapacityMultiplier: Number(event.target.value) }))} />
                </label>
                <label>{localizeAbuText('出水边界水位调整（m）')}
                  <input type="number" min="-2" max="2" step="0.05" value={gwmActions.outfallLevelAdjustment} disabled={gwmBusy} onChange={event => setGwmActions(current => ({ ...current, outfallLevelAdjustment: Number(event.target.value) }))} />
                </label>
              </div>
              <div className="abu-flood-scenario-actions">
                <button className="abu-flood-map-action" type="button" onClick={runGwmRollout} disabled={gwmBusy || scenarioBusy || precomputedLoadStage !== null}><Play size={15} />{gwmBusy ? localizeAbuText('正在运行 GWM 快速推演…') : localizeAbuText('运行规则型情景筛选')}</button>
                {gwmRun && !gwmIsTrained && <span className="abu-flood-surface-period-status">{localizeAbuText(`已完成 ${gwmReturnPeriodYears} 年一遇规则型 GWM rollout`)}</span>}
              </div>
              <div className="abu-flood-form-hint" aria-live="polite">
                <GitBranch size={13} />
                {surfaceReturnPeriodLoading
                  ? localizeAbuText(`正在准备阶段 3 的 ${gwmReturnPeriodYears} 年一遇二维结果…`)
                  : Number(publicCitywide2dDiagnostic?.metadata?.return_period_years || 0) === gwmReturnPeriodYears
                    ? localizeAbuText(`阶段 3 的 ${gwmReturnPeriodYears} 年一遇二维结果已准备，规则型筛选将基于该结果运行。`)
                    : localizeAbuText(`运行前会自动加载阶段 3 的 ${gwmReturnPeriodYears} 年一遇二维结果。`)}
              </div>
              {gwmRun && !gwmIsTrained && <div className="abu-flood-scenario-result-metrics">
                <div><span>{localizeAbuText('基线最大深度')}</span><strong>{Number(gwmRun.metrics?.baseline_max_depth_m || 0).toFixed(2)}</strong><small>m</small></div>
                <div><span>{localizeAbuText('干预最大深度')}</span><strong>{Number(gwmRun.metrics?.intervention_max_depth_m || 0).toFixed(2)}</strong><small>m</small></div>
                <div><span>{localizeAbuText('最大绝对变化')}</span><strong>{Number(gwmRun.metrics?.maximum_absolute_delta_m || 0).toFixed(2)}</strong><small>m</small></div>
                <div><span>{localizeAbuText('二维单元')}</span><strong>{Number(gwmRun.metrics?.source_feature_count || 0).toLocaleString()}</strong><small>{localizeAbuText('个')}</small></div>
                <div><span>{localizeAbuText('基线受影响网格')}</span><strong>{Number(gwmRun.metrics?.baseline_affected_cell_count || 0).toLocaleString()}</strong><small>{localizeAbuText('个')}</small></div>
                <div><span>{localizeAbuText('干预受影响网格')}</span><strong>{Number(gwmRun.metrics?.intervention_affected_cell_count || 0).toLocaleString()}</strong><small>{localizeAbuText('个')}</small></div>
                <div><span>{localizeAbuText('排水改善面积')}</span><strong>{Math.max(0, Number(gwmRun.metrics?.baseline_affected_area_m2_proxy || 0) - Number(gwmRun.metrics?.intervention_affected_area_m2_proxy || 0)).toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong><small>m² proxy</small></div>
                <div><span>{localizeAbuText('峰值地表蓄水量变化')}</span><strong>{Number(gwmRun.metrics?.peak_surface_storage_delta_m3_proxy || 0).toLocaleString(undefined, { maximumFractionDigits: 1 })}</strong><small>m³ proxy</small></div>
                <div><span>{localizeAbuText('排除水域网格')}</span><strong>{Number(gwmRun.metrics?.excluded_water_cell_count || 0).toLocaleString()}</strong><small>{localizeAbuText('个')}</small></div>
              </div>}
              {gwmRun && !gwmIsTrained && <div className="abu-flood-form-hint"><GitBranch size={13} />{localizeAbuText(`时间轴 ${Number(gwmRun.metadata?.timeline?.period_count || 0)} 帧 · 不确定性 ${(Number(gwmRun.metadata?.uncertainty_fraction || 0) * 100).toFixed(1)}% · 高风险情景回退 SWMM / ANUGA 复核`)} · {localizeAbuText('面积与蓄水量为基于网格的代理指标')}</div>}
            </>}
            {gwmError && <span className="abu-flood-form-error"><AlertTriangle size={13} />{localizeAbuText(gwmError)}</span>}
          </div>}
          {selectedKey === 'validation' && <div className="abu-flood-surface-period-control abu-flood-gwm-control">
            <div>
              <strong>{localizeAbuText('2024 历史事件重演验证')}</strong>
              <small>{localizeAbuText('独立于阶段 1-4 的只读验证结果；加载后可在地图 2D / 3D 时间轴播放地表积水演变。当前结果由接口元数据确定；加载完成后显示模拟时长、时间片和时间步长。')}</small>
            </div>
            <div className="abu-flood-scenario-actions">
              <button className="abu-flood-map-action" type="button" onClick={loadHistoricalReplayValidation} disabled={historicalReplayLoading}>
                {historicalReplayLoading ? <LoaderCircle className="abu-flood-loading-icon" size={15} /> : <RotateCcw size={15} />}
                {historicalReplayLoading ? localizeAbuText('正在加载历史重演验证结果…') : localizeAbuText('加载 / 刷新历史重演结果')}
              </button>
              <button className="abu-flood-map-action" type="button" onClick={openHistoricalReplayReport} disabled={historicalReplayReportLoading || simulationReportLoading}>
                {historicalReplayReportLoading || simulationReportLoading ? <LoaderCircle className="abu-flood-loading-icon" size={15} /> : <FileCheck2 size={15} />}
                {historicalReplayReportLoading || simulationReportLoading ? localizeAbuText('正在生成阶段 5 决策支持报告…') : localizeAbuText('打开阶段 5 决策支持报告')}
              </button>
            </div>
            {historicalReplayError && <span className="abu-flood-form-error"><AlertTriangle size={13} />{localizeAbuText(historicalReplayError)}</span>}
            <span className="abu-flood-surface-period-status" aria-live="polite">
              {historicalReplayLoading
                ? localizeAbuText('正在读取历史重演结果并准备地图和时间轴…')
                : historicalReplayValidation
                  ? localizeAbuText('历史重演已加载；地图和时间轴已就绪。需要重新发送图层时，使用“在地图上展示当前阶段”。')
                  : localizeAbuText('历史重演尚未加载；可点击“加载 / 刷新历史重演结果”重试。')}
            </span>
            {historicalReplayValidation && <>
              <div className="abu-flood-scenario-result-metrics">
                <div><span>{localizeAbuText('模拟时长')}</span><strong>{Number(historicalReplayValidation.metadata?.domain?.simulation_duration_hours || 0).toFixed(0)}</strong><small>h</small></div>
                <div><span>{localizeAbuText('时间片')}</span><strong>{Number(historicalReplayValidation.metadata?.timeline?.period_count || 0).toLocaleString()}</strong><small>{localizeAbuText('帧')}</small></div>
                <div><span>{localizeAbuText('二维陆域单元')}</span><strong>{Number(historicalReplayValidation.metadata?.timeline?.total_cell_count || 0).toLocaleString()}</strong><small>{localizeAbuText('个')}</small></div>
                <div><span>{localizeAbuText('最大积水深度')}</span><strong>{Number(historicalReplayValidation.metadata?.results?.maximum_depth_m || 0).toFixed(2)}</strong><small>m</small></div>
              </div>
              <div className="abu-flood-form-hint"><CheckCircle2 size={13} />{localizeAbuText(`客户 ${historicalReplayValidation.metadata?.surface_product || 'DTM'} · ${historicalReplayValidation.metadata?.solver || 'EPA SWMM 5.2.4 + ANUGA 2D'} · 时间轴 ${Number(historicalReplayValidation.metadata?.timeline?.step_minutes || 0).toFixed(0)} 分钟步长`)}</div>
              <div className="abu-flood-form-hint"><GitBranch size={13} />{localizeAbuText(`SWMM→ANUGA 交换体积相对误差 ${(Number(historicalReplayValidation.metadata?.coupling?.relative_volume_error || 0) * 100).toFixed(3)}% · ${historicalReplayValidation.metadata?.validation?.observation_comparison === 'pending' ? '观测对比 pending' : '观测对比已完成'}`)}</div>
              {(() => {
                const quality = historicalReplayValidation.metadata?.validation?.swmm_quality;
                const failedChecks = Array.isArray(quality?.failed_checks) ? quality.failed_checks : [];
                const qualityChecks = Array.isArray(quality?.checks) ? quality.checks : [];
                const qualityFailed = quality?.status === 'failed';
                const solverCompleted = quality?.solver_status === 'completed' || quality?.solver_status === 'success' || quality?.solver_status === 'completed_with_warnings';
                const checkLabel = (checkId: string) => ({
                  report_contains_no_swmm_errors: 'SWMM 报告不含错误',
                  all_links_stable: '管段稳定性',
                  runoff_continuity_within_threshold: '产流连续性误差',
                  routing_continuity_within_threshold: '汇流连续性误差',
                  nonconverging_steps_within_threshold: '未收敛时间步比例',
                } as Record<string, string>)[checkId] || checkId;
                const formatCheckValue = (check: any) => {
                  const observed = check?.observed;
                  const threshold = check?.threshold_or_required;
                  if (check?.check_id === 'all_links_stable') return `${observed ? '是' : '否'} / ${threshold ? '是' : '否'}`;
                  if (observed == null && threshold == null) return '—';
                  const observedText = typeof observed === 'number' ? `${observed.toFixed(2)}%` : String(observed ?? '—');
                  const thresholdText = typeof threshold === 'number' && check?.check_id !== 'report_contains_no_swmm_errors' ? `${threshold.toFixed(2)}%` : String(threshold ?? '—');
                  return `${observedText} / ${thresholdText}`;
                };
                return <div className={`abu-flood-validation-gate ${qualityFailed ? 'failed' : quality?.status === 'passed' ? 'passed' : 'pending'}`}>
                  {qualityFailed ? <AlertTriangle size={14} /> : quality?.status === 'passed' ? <CheckCircle2 size={14} /> : <LockKeyhole size={14} />}
                  <div>
                    <strong>{localizeAbuText(qualityFailed ? 'SWMM 严格数值质量门未通过' : quality?.status === 'passed' ? 'SWMM 严格数值质量门通过' : 'SWMM 严格数值质量门待确认')}</strong>
                    <span>{localizeAbuText(qualityFailed ? `SWMM 进程${solverCompleted ? '已完成' : '已返回'}；结果资产仍可播放。严格门失败检查：${failedChecks.map(checkLabel).join('、') || '—'}` : quality?.status === 'passed' ? 'SWMM 回执中的严格检查已通过；仍不代表工程准入。' : '未找到 SWMM 严格回执，暂不作通过声明。')}</span>
                    {qualityFailed && <span className="abu-flood-validation-gate-explanation">{localizeAbuText('这不是页面加载错误：动态波路由在部分时间步内未达到严格收敛要求。当前结果保留用于历史过程回放和问题定位；修正管网高程、几何、时间步或边界条件后再重新计算。')}</span>}
                    {qualityChecks.length > 0 && <details className="abu-flood-quality-details">
                      <summary>{localizeAbuText('查看 SWMM 数值检查详情')}</summary>
                      <div className="abu-flood-quality-check-list">
                        <div className="abu-flood-quality-check-header"><span>{localizeAbuText('检查项')}</span><span>{localizeAbuText('观测值 / 阈值')}</span><span>{localizeAbuText('状态')}</span></div>
                        {qualityChecks.map((check: any) => <div className="abu-flood-quality-check" key={String(check?.check_id)}><span>{localizeAbuText(checkLabel(String(check?.check_id || 'unknown')))}</span><span className="abu-flood-quality-value">{formatCheckValue(check)}</span><span className={check?.passed ? 'passed' : 'failed'}>{check?.passed ? localizeAbuText('通过') : localizeAbuText('未通过')}</span></div>)}
                      </div>
                      <small>{localizeAbuText('数值格式：百分比检查显示“观测值 / 阈值”；管段稳定性显示布尔值。')}</small>
                    </details>}
                  </div>
                </div>;
              })()}
              <div className="abu-flood-form-hint"><LockKeyhole size={13} />{localizeAbuText('LISFLOOD-FP 交叉复核、道路 / 设施影响叠加和工程准入仍未开启；页面不虚构未提供的观测或影响数据。')}</div>
            </>}
          </div>}
          <div className="abu-flood-io-grid">
            <div><span>{localizeAbuText('输入')}</span>{selectedStage.inputs.map(item => <div key={item}><ArrowRight size={12} />{localizeAbuText(item)}</div>)}</div>
            <div><span>{localizeAbuText('输出')}</span>{selectedStage.outputs.map(item => <div key={item}><CheckCircle2 size={12} />{localizeAbuText(item)}</div>)}</div>
          </div>
          <div className="abu-flood-next"><Play size={14} /><div><span>{localizeAbuText('下一动作')}</span><strong>{localizeAbuText(selectedStage.next)}</strong></div></div>
        </div>

        <div className="abu-flood-gates-panel">
          <div className="abu-flood-section-heading compact"><div><span className="abu-flood-overline">ADMISSION GATES</span><h3>{localizeAbuText('准入闸门')}</h3></div><LockKeyhole size={17} /></div>
          <div className="abu-flood-gate-list">
            {gates.map(([label, value, tone]) => <div className="abu-flood-gate" key={label}><span className={`abu-flood-gate-dot ${tone}`} /><div><strong>{localizeAbuText(label)}</strong><small>{localizeAbuText(value)}</small></div><LockKeyhole size={13} /></div>)}
          </div>
          <div className="abu-flood-gate-note"><ShieldCheck size={14} />{localizeAbuText('数值质量通过不等于工程校准通过。')}</div>
        </div>
      </section>

      <section className="abu-flood-section">
        <div className="abu-flood-view-tabs" role="tablist" aria-label={localizeAbuText('模型流程视图')}>
          <button className={view === 'flow' ? 'active' : ''} onClick={() => setView('flow')}><GitBranch size={14} />{localizeAbuText('协作关系')}</button>
          <button className={view === 'models' ? 'active' : ''} onClick={() => setView('models')}><Layers3 size={14} />{localizeAbuText('模型分工')}</button>
          <button className={view === 'deliverables' ? 'active' : ''} onClick={() => setView('deliverables')}><FileCheck2 size={14} />{localizeAbuText('交付物')}</button>
          <button className={view === 'event' ? 'active' : ''} onClick={() => setView('event')}><CloudRain size={14} />{localizeAbuText('2024 事件证据与重构')}</button>
          <button className={view === 'observation' ? 'active' : ''} onClick={() => setView('observation')}><Globe2 size={14} />{localizeAbuPair('2024 历史观测验证', '2024 historical observation')}</button>
        </div>
        {view === 'flow' && <div className="abu-flood-flow-board">
          <div className="abu-flood-flow-node physical"><span>{localizeAbuText('传统模型')}</span><strong>SWMM + ANUGA</strong><small>{localizeAbuText('质量守恒、边界和物理验证')}</small></div>
          <ArrowRight className="abu-flood-flow-arrow" size={19} />
          <div className="abu-flood-flow-node proxy"><span>GWM</span><strong>{localizeAbuText('快速推演层')}</strong><small>{localizeAbuText('学习已验收状态，筛选候选情景')}</small></div>
          <ArrowRight className="abu-flood-flow-arrow" size={19} />
          <div className="abu-flood-flow-node decision"><span>{localizeAbuText('决策输出')}</span><strong>{localizeAbuText('影响与方案优先级')}</strong><small>{localizeAbuText('高风险情景回到传统模型复核')}</small></div>
          <div className="abu-flood-flow-rule"><LockKeyhole size={13} />{localizeAbuText('GWM 不能绕过物理模型、观测验证和不确定性门控')}</div>
        </div>}
        {view === 'models' && <div className="abu-flood-model-table">
          {modelRows.map(row => {
            const renderedRow = row.name === 'ANUGA' && customerDtmSurfaceActive
              ? { ...row, status: customerDtmBidirectionalSurfaceActive ? '客户 5 m DTM · 250 m 网格 · 同步双向数值验证 · 未校准' : '客户 5 m DTM 输入 · 250 m 网格 · 单向耦合 · 未校准' }
              : row;
            return <div className="abu-flood-model-row" key={renderedRow.name}><div><strong>{renderedRow.name}</strong><span>{localizeAbuText(renderedRow.role)}</span></div><span className="abu-flood-model-owner">{localizeAbuText(renderedRow.owner)}</span><span className={`abu-flood-pill ${renderedRow.tone === 'partial' ? 'abu-flood-status-partial' : 'abu-flood-status-blocked'}`}>{localizeAbuText(renderedRow.status)}</span></div>;
          })}
        </div>}
        {view === 'deliverables' && <div className="abu-flood-deliverable-grid">
          {['客户数据与工程问题回执', 'SWMM 输入、RPT / OUT 与动态状态', '二维积水深度、范围和持续时间', 'SWMM-ANUGA 体积交换对账', 'GWM 快速情景与不确定性报告', '最终哈希清单与准入声明'].map((item, index) => <div className="abu-flood-deliverable" key={item}><span>{String(index + 1).padStart(2, '0')}</span><FileCheck2 size={15} /><strong>{localizeAbuText(item)}</strong></div>)}
        </div>}
        {view === 'event' && <div className="abu-flood-event-evidence">
          {eventEvidenceLoading && <div className="abu-flood-event-loading"><LoaderCircle className="abu-flood-loading-icon" size={16} />{localizeAbuText('正在读取 2024 事件公开证据…')}</div>}
          {!eventEvidenceLoading && !eventEvidence && <div className="abu-flood-event-loading"><AlertTriangle size={16} />{localizeAbuText('2024 事件证据暂不可用')}</div>}
          {eventEvidence && <>
            <div className="abu-flood-event-boundary"><ShieldCheck size={15} /><div><strong>{localizeAbuText(eventEvidence.fidelity?.title_zh || '公开事实与重构雨型分开呈现')}</strong><p>{getLocale() === 'zh-CN' ? eventEvidence.fidelity?.body_zh : eventEvidence.fidelity?.body_en}</p></div><span className="abu-flood-pill abu-flood-status-partial">{localizeAbuText('不发布地图图层')}</span></div>
            <div className="abu-flood-event-facts">
              {(eventEvidence.key_facts || []).map((fact: any) => <article key={fact.label_en} className="abu-flood-event-fact"><span>{getLocale() === 'zh-CN' ? fact.label_zh : fact.label_en}</span><strong>{fact.value}</strong><p>{getLocale() === 'zh-CN' ? fact.detail_zh : fact.detail_en}</p><a href={fact.source?.url} target="_blank" rel="noreferrer"><ExternalLink size={11} />{localizeAbuText('打开来源')}</a></article>)}
            </div>
            <div className="abu-flood-event-grid">
              <div className="abu-flood-event-panel">
                <div className="abu-flood-event-panel-heading"><div><span className="abu-flood-overline">RECONSTRUCTED FORCING</span><h4>{localizeAbuText(eventEvidence.reconstruction?.label_zh || '三波次重构雨型（40 h 雨量窗口）')}</h4></div><span className="abu-flood-pill abu-flood-status-blocked">{localizeAbuText('仅用于原型敏感性演示')}</span></div>
                <div className="abu-flood-event-chart" aria-label={localizeAbuText('逐时雨强（mm/h）')}>
                  {(eventEvidence.reconstruction?.rainfall_profile_mmph || []).map((value: number, index: number) => <span key={`${index}-${value}`} title={`${index} h · ${Number(value).toFixed(2)} mm/h`} style={{ height: `${Math.max(3, Math.min(100, Number(value) / 30.32 * 100))}%` }} />)}
                </div>
                <div className="abu-flood-event-chart-axis"><span>0 h</span><span>{localizeAbuText('最大雨强')} {Number(eventEvidence.reconstruction?.peak_mmph || 0).toFixed(2)} mm/h</span><span>40 h</span></div>
                <div className="abu-flood-event-stats"><div><span>{localizeAbuText('累计重构雨量')}</span><strong>{Number(eventEvidence.reconstruction?.reconstructed_total_mm || 0).toFixed(2)} mm</strong></div><div><span>{localizeAbuText('逐时')}</span><strong>{eventEvidence.reconstruction?.interval_minutes || 60} min</strong></div><div><span>{localizeAbuText('来源')}</span><strong>{localizeAbuText('公开记录 + 明确假设')}</strong></div></div>
                <ul className="abu-flood-event-assumptions">{(getLocale() === 'zh-CN' ? eventEvidence.reconstruction?.assumptions_zh : eventEvidence.reconstruction?.assumptions_en || []).map((item: string) => <li key={item}>{item}</li>)}</ul>
              </div>
              <div className="abu-flood-event-panel">
                <div className="abu-flood-event-panel-heading"><div><span className="abu-flood-overline">DOCUMENTED RECORD</span><h4>{localizeAbuText('事件时间线')}</h4></div><span className="abu-flood-muted">{(eventEvidence.timeline || []).length} {localizeAbuText('条')}</span></div>
                <div className="abu-flood-event-timeline">{(eventEvidence.timeline || []).map((item: any) => <div className="abu-flood-event-timeline-item" key={`${item.time}-${item.area_en}`}><time>{item.time}</time><div><strong>{getLocale() === 'zh-CN' ? item.area_zh : item.area_en}</strong><p>{getLocale() === 'zh-CN' ? item.event_zh : item.event_en}</p><a href={item.source?.url} target="_blank" rel="noreferrer"><ExternalLink size={10} />{item.source?.title || localizeAbuText('打开来源')}</a></div></div>)}</div>
              </div>
            </div>
            <div className="abu-flood-event-gaps"><div className="abu-flood-event-panel-heading"><div><span className="abu-flood-overline">NEXT EVIDENCE</span><h4>{localizeAbuText('验证缺口')}</h4></div></div><div className="abu-flood-event-gap-grid">{(eventEvidence.validation_gaps || []).map((gap: any) => <div key={gap.title_en}><strong>{getLocale() === 'zh-CN' ? gap.title_zh : gap.title_en}</strong><span>{getLocale() === 'zh-CN' ? gap.use_zh : gap.use_en}</span></div>)}</div><div className="abu-flood-event-map-note"><MapIcon size={13} />{localizeAbuText('本页不向地图发送任何空间要素')} · {localizeAbuText('真实 SWMM / ANUGA 结果仍在上方地图区域展示')}</div></div>
          </>}
        </div>}
        {view === 'observation' && <div className="abu-flood-observation" aria-live="polite">
          {sentinelObservationLoading && <div className="abu-flood-event-loading"><LoaderCircle className="abu-flood-loading-icon" size={16} />{localizeAbuPair('正在读取 Sentinel-2 外部留出集观测…', 'Reading the Sentinel-2 external-holdout observation…')}</div>}
          {!sentinelObservationLoading && sentinelObservationError && <div className="abu-flood-form-error"><AlertTriangle size={14} />{localizeAbuText(sentinelObservationError)}<button className="abu-flood-inline-action" type="button" onClick={loadSentinelObservation}>{localizeAbuPair('重试', 'Retry')}</button></div>}
          {!sentinelObservationLoading && !sentinelObservation && !sentinelObservationError && <div className="abu-flood-event-loading"><AlertTriangle size={16} />{localizeAbuPair('2024 历史观测产品暂不可用', 'The April 2024 historical observation product is unavailable')}</div>}
          {sentinelObservation && (() => {
            const observation = sentinelObservation.observation;
            const comparison = sentinelObservation.external_comparison;
            const newWaterKm2 = observation.observed_new_surface_water_area_m2 / 1_000_000;
            const validAreaKm2 = observation.valid_observation_area_m2 / 1_000_000;
            const beforeScenes = sentinelObservation.scenes.before;
            const afterScenes = sentinelObservation.scenes.after;
            const comparisonReady = comparison.status === 'completed_external_physics_comparison' || comparison.status === 'completed_external_comparisons';
            const gwmComparisonReady = comparison.gwm_comparison === 'completed_frozen_model' && comparison.gwm_metrics !== null;
            const sceneLabel = (scenes: typeof beforeScenes) => scenes.map(scene => `${scene.item_id} · ${scene.cloud_cover_percent.toFixed(1)}%`).join(' / ');
            return <>
              <div className="abu-flood-observation-boundary">
                <ShieldCheck size={16} />
                <div><span className="abu-flood-overline">EXTERNAL HOLDOUT · SENTINEL-2 L2A</span><h4>{localizeAbuPair('2024 年 4 月历史积水观测', 'April 2024 historical surface-water observation')}</h4><p>{localizeAbuPair('云、云影、卷云和无数据已剔除；该产品是光谱新增地表水信号，不是实测水深或测绘淹没范围。', 'Cloud, cloud shadow, cirrus and no-data pixels are excluded. This product is a spectral new-surface-water signal, not measured depth or a surveyed inundation extent.')}</p></div>
                <span className="abu-flood-pill abu-flood-status-ready">{localizeAbuPair('观测产品质检通过', 'Observation product QC passed')}</span>
              </div>
              <div className="abu-flood-observation-metrics">
                <div><span>{localizeAbuPair('新增地表水信号', 'New surface-water signal')}</span><strong>{newWaterKm2.toFixed(2)}</strong><small>km²</small></div>
                <div><span>{localizeAbuPair('有效卫星观测覆盖', 'Valid satellite coverage')}</span><strong>{validAreaKm2.toFixed(2)}</strong><small>km²</small></div>
                <div><span>{localizeAbuPair('250 m 观测标签', '250 m observation labels')}</span><strong>{observation.observed_flood_250m_cell_count.toLocaleString()}</strong><small>/ {observation.valid_250m_cell_count.toLocaleString()} {localizeAbuPair('有效单元', 'valid cells')}</small></div>
                <div><span>{localizeAbuPair('训练与调参', 'Training and tuning')}</span><strong>{localizeAbuPair('禁止', 'Forbidden')}</strong><small>{localizeAbuPair('外部留出集', 'external holdout')}</small></div>
              </div>
              <div className="abu-flood-observation-map-action">
                <div><MapIcon size={15} /><span><strong>{localizeAbuPair('地图观测图层', 'Observed-water map layer')}</strong><small>{localizeAbuPair('显示 2024-04-17 Sentinel-2 新增地表水的 250 m 观测单元；颜色表示单元内有效像元的新增水体比例。', 'Shows 250 m observed cells of Sentinel-2 new surface water on 17 April 2024; color represents the new-water fraction among valid pixels.')}</small></span></div>
                <button type="button" aria-label={localizeAbuPair('在地图上查看观测积水', 'Show observed flooding on map')} onClick={showSentinelObservationOnMap} disabled={sentinelObservationMapLoading}>
                  {sentinelObservationMapLoading ? <LoaderCircle className="abu-flood-loading-icon" size={14} /> : <MapIcon size={14} />}
                  {sentinelObservationMapLoading ? localizeAbuPair('正在加载观测地图…', 'Loading observation map…') : sentinelObservationMapSent ? localizeAbuPair('地图已显示 · 重新定位', 'Displayed · re-center map') : localizeAbuPair('在地图上查看观测积水', 'Show observed flooding on map')}
                </button>
              </div>
              {sentinelObservationMapError && <div className="abu-flood-form-error"><AlertTriangle size={14} />{localizeAbuText(sentinelObservationMapError)}<button className="abu-flood-inline-action" type="button" onClick={showSentinelObservationOnMap}>{localizeAbuPair('重试', 'Retry')}</button></div>}
              <div className="abu-flood-observation-grid">
                <section className="abu-flood-observation-panel">
                  <div className="abu-flood-event-panel-heading"><div><span className="abu-flood-overline">EVENT ALIGNMENT</span><h4>{localizeAbuPair('降雨、卫星与模型时相', 'Rainfall, satellite and model alignment')}</h4></div><button className="abu-flood-icon-action" type="button" title={localizeAbuPair('刷新观测状态', 'Refresh observation status')} onClick={loadSentinelObservation} disabled={sentinelObservationLoading}><RotateCcw size={14} /></button></div>
                  <div className="abu-flood-observation-timeline">
                    <div><time>{observation.before_date}</time><span><strong>{localizeAbuPair('雨前基线影像', 'Pre-event baseline')}</strong><small>{sceneLabel(beforeScenes)}</small></span></div>
                    <div><time>{sentinelObservation.forcing.start_utc}</time><span><strong>{localizeAbuPair('外部验证降雨强迫开始', 'External-evaluation rainfall starts')}</strong><small>{sentinelObservation.forcing.source} · {sentinelObservation.forcing.support_point_count} {localizeAbuPair('个空间支撑点', 'spatial support points')}</small></span></div>
                    <div><time>{sentinelObservation.event.satellite_observation_utc}</time><span><strong>{localizeAbuPair('Sentinel-2 雨后观测', 'Post-event Sentinel-2 observation')}</strong><small>{sceneLabel(afterScenes)} · {localizeAbuPair('最近 5 分钟物理帧', 'nearest 5-minute physics frame')} {sentinelObservation.forcing.nearest_300_second_model_frame_seconds.toLocaleString()} s</small></span></div>
                  </div>
                  <div className="abu-flood-observation-note"><TimerReset size={13} />{localizeAbuPair(`为对齐卫星过境，强迫在降雨后延长 ${sentinelObservation.forcing.zero_rainfall_tail_hours.toFixed(0)} 小时零降雨尾段；此尾段只用于外部比较。`, `An ${sentinelObservation.forcing.zero_rainfall_tail_hours.toFixed(0)}-hour zero-rainfall tail aligns the replay with the overpass; it is used only for the external comparison.`)}</div>
                </section>
                <section className="abu-flood-observation-panel">
                  <div className="abu-flood-event-panel-heading"><div><span className="abu-flood-overline">OBSERVATION GATE</span><h4>{localizeAbuPair('云筛选与分类口径', 'Cloud screening and classification')}</h4></div><span className="abu-flood-pill abu-flood-status-ready">{localizeAbuPair('提取质检通过', 'Extraction QC passed')}</span></div>
                  <dl className="abu-flood-observation-definition-list">
                    <div><dt>{localizeAbuPair('数据源', 'Source')}</dt><dd>{observation.source}</dd></div>
                    <div><dt>{localizeAbuPair('有效 SCL 类别', 'Valid SCL classes')}</dt><dd>{observation.valid_scl_classes.join(', ')}</dd></div>
                    <div><dt>{localizeAbuPair('成对有效覆盖门槛', 'Paired-valid coverage gate')}</dt><dd>&ge; {(observation.minimum_250m_valid_fraction * 100).toFixed(0)}%</dd></div>
                    <div><dt>{localizeAbuPair('新增水体标签门槛', 'New-water label gate')}</dt><dd>&ge; {(observation.minimum_250m_observed_water_fraction * 100).toFixed(0)}%</dd></div>
                    <div><dt>MNDWI {localizeAbuPair('变化阈值', 'change threshold')}</dt><dd>&ge; {observation.mndwi_change_threshold.toFixed(2)}</dd></div>
                  </dl>
                </section>
              </div>
              <section className="abu-flood-observation-comparison">
                <div className="abu-flood-event-panel-heading"><div><span className="abu-flood-overline">VALIDATION SEQUENCE</span><h4>{localizeAbuPair('外部验证链', 'External validation chain')}</h4></div><span className={`abu-flood-pill ${gwmComparisonReady ? 'abu-flood-status-ready' : comparisonReady ? 'abu-flood-status-partial' : 'abu-flood-status-partial'}`}>{gwmComparisonReady ? localizeAbuPair('双模型对比完成', 'Both model comparisons complete') : comparisonReady ? localizeAbuPair('物理对比完成', 'Physics comparison complete') : localizeAbuPair('等待物理重演', 'Physics replay pending')}</span></div>
                <div className="abu-flood-observation-chain">
                  <div className="complete"><CheckCircle2 size={14} /><strong>{localizeAbuPair('观测产品', 'Observation product')}</strong><span>{localizeAbuPair('已完成，冻结为外部留出集', 'Complete and frozen as external holdout')}</span></div>
                  <ArrowRight size={16} />
                  <div className={comparisonReady ? 'complete' : 'pending'}>{comparisonReady ? <CheckCircle2 size={14} /> : <CircleDashed size={14} />}<strong>{localizeAbuPair('物理重演对比', 'Physics replay comparison')}</strong><span>{comparisonReady ? localizeAbuPair('已仅在有效观测单元上评分', 'Scored only on valid observed cells') : localizeAbuPair('待零雨尾段重演完成后评分', 'Score after zero-rain-tail replay')}</span></div>
                  <ArrowRight size={16} />
                  <div className={gwmComparisonReady ? 'complete' : 'pending'}>{gwmComparisonReady ? <CheckCircle2 size={14} /> : <LockKeyhole size={14} />}<strong>{localizeAbuPair('冻结 GWM 外部检验', 'Frozen-GWM external test')}</strong><span>{gwmComparisonReady ? localizeAbuPair('已在同相位有效观测单元上评分；仅报告，不得反向调参', 'Scored at the same phase over valid observation cells; report-only, never tune from it') : localizeAbuPair('只能评估冻结模型，不得用于拟合或选参', 'Evaluate a frozen model only; never fit or select it')}</span></div>
                </div>
                {comparisonReady && comparison.comparison && <div className="abu-flood-observation-score"><span>{localizeAbuPair('二维物理回放 IoU', '2D physics IoU')} <strong>{comparison.comparison.iou.toFixed(3)}</strong></span><span>{localizeAbuPair('精确率', 'Precision')} <strong>{comparison.comparison.precision.toFixed(3)}</strong></span><span>{localizeAbuPair('召回率', 'Recall')} <strong>{comparison.comparison.recall.toFixed(3)}</strong></span></div>}
                {gwmComparisonReady && comparison.gwm_metrics && <div className="abu-flood-observation-score"><span>{localizeAbuPair('GWM R1 IoU', 'GWM R1 IoU')} <strong>{comparison.gwm_metrics.iou.toFixed(3)}</strong></span><span>{localizeAbuPair('精确率', 'Precision')} <strong>{comparison.gwm_metrics.precision.toFixed(3)}</strong></span><span>{localizeAbuPair('召回率', 'Recall')} <strong>{comparison.gwm_metrics.recall.toFixed(3)}</strong></span></div>}
                {gwmComparisonReady && <div className="abu-flood-observation-note"><AlertTriangle size={13} />{localizeAbuPair('此处比较的是云筛选后的新增地表水空间一致性，不是实测水深或工程验收。', 'This measures spatial agreement with cloud-screened new surface water, not observed water depth or engineering acceptance.')}</div>}
              </section>
              <div className="abu-flood-observation-assets"><span>{localizeAbuPair('可追溯派生产物', 'Traceable derived artifacts')}</span>{sentinelObservation.assets.map(asset => <code key={asset.kind}>{asset.asset}</code>)}<small>{localizeAbuPair('回执 SHA-256', 'Receipt SHA-256')} {String(sentinelObservation.receipt_sha256 || '—').slice(0, 16)}</small></div>
            </>;
          })()}
        </div>}
      </section>

      <section className="abu-flood-status-footer"><div><Waves size={15} /><strong>{localizeAbuText('当前项目状态')}</strong><span>{localizeAbuText('诊断与外部验证阶段')}</span></div><span className="abu-flood-footer-note">{localizeAbuText('下一步：补齐权威工程属性与运行边界 → 修复 SWMM 数值质量 → 独立二维复核 → 冻结 GWM 确认性外部验证')}</span></section>
    </div>
  );
}
